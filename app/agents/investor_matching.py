"""Investor matching — pure computation, no DB, no network.

Takes a client's requirement dict and a list of investor dicts (however they
were fetched — a live Postgres query in production, a fixture in a test) and
returns a ranked, explainable shortlist. See
`Sales Department/network/INVESTOR-MATCHING.md` in the Dropbox company folder
for the method this ports (same weights, same synonym approach) — kept in
sync by hand since the two run in different codebases.

This module never contacts an investor and never shares a client's specific
requirement with anyone. Its output is for the Managing Partner's dashboard
only, gated the same way as the original: Box 2 content stays behind the s21
eligibility gate regardless of match score.
"""
from __future__ import annotations

import re

WEIGHTS = {"sector": 30, "geography": 25, "ticket": 20, "stage": 15, "confidence": 10}

STOPWORDS = {"and", "the", "of", "in", "a", "or", "for", "to", "all", "not", "published",
             "with", "across", "including", "select", "selective", "diversified", "other"}

SECTOR_TAGS = {
    "real estate": "real_estate", "real assets": "real_estate", "property": "real_estate",
    "residential": "real_estate", "commercial real estate": "real_estate",
    "infrastructure": "infrastructure", "project": "infrastructure",
    "energy transition": "energy", "energy": "energy", "natural capital": "energy",
    "critical minerals": "mining", "mining": "mining", "metals": "mining",
    "private equity": "private_equity", "buyout": "private_equity",
    "growth capital": "private_equity", "growth equity": "private_equity",
    "growth": "private_equity",
    "venture capital": "venture", "early stage": "venture", "deep tech": "venture",
    "private credit": "credit", "credit": "credit", "structured credit": "credit",
    "special situations": "credit",
    "consumer": "consumer", "retail": "consumer",
    "fintech": "fintech", "financial services": "fintech",
    "hospitality": "hospitality", "leisure": "hospitality", "gaming": "hospitality",
    "technology": "technology", "digital media": "technology", "tech": "technology",
    "healthcare": "healthcare",
    "owner-managed": "sme", "smes": "sme", "employee ownership": "sme",
}

STRUCTURE_TAGS = {
    "debt": "debt", "refinancing": "debt", "recapitalisation": "debt", "loan": "debt",
    "loans": "debt", "lending": "debt", "bridging": "debt", "credit": "debt",
    "equity": "equity", "direct equity": "equity", "private placement": "equity",
    "strategic equity": "equity", "co-investment": "equity", "joint venture": "equity",
    "fund commitment": "fund", "fund commitments": "fund", "funds": "fund",
    "growth": "growth", "buyout": "growth", "mbo": "growth", "acquisition": "growth",
}

GEO_TAGS = {
    "usa": "usa", "united states": "usa", "north america": "usa",
    "united kingdom": "uk", "uk": "uk",
    "india": "india",
    "mena": "mena", "gcc": "mena", "middle east": "mena", "uae": "mena", "dubai": "mena",
    "europe": "europe", "ireland": "europe", "italy": "europe", "spain": "europe",
    "asia": "asia", "south east asia": "asia", "singapore": "asia",
    "brazil": "brazil", "latin america": "brazil",
    "australia": "australia",
    "global": "global", "international": "global",
}


def _tags(text, tagmap):
    low = (text or "").lower()
    return {tag for phrase, tag in tagmap.items() if phrase in low}


def _words(text):
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in STOPWORDS}


def _overlap(client_text, investor_text, tagmap):
    if not (client_text or "").strip() or not (investor_text or "").strip():
        return None, ["one side has no data on file"]
    c_tags, i_tags = _tags(client_text, tagmap), _tags(investor_text, tagmap)
    c_words, i_words = _words(client_text), _words(investor_text)
    matched_tags, matched_words = c_tags & i_tags, c_words & i_words
    if not matched_tags and not matched_words:
        return 0, ["no overlap found — verify manually"]
    if tagmap is GEO_TAGS and "global" in i_tags:
        return 90, ["investor states global/international reach — verify actual coverage"]
    denom = max(len(c_tags | c_words), 1)
    numer = len(matched_tags) * 2 + len(matched_words)
    score = min(100, round(100 * numer / max(denom * 1.5, 1)))
    terms = sorted({f"tag:{t}" for t in matched_tags} | matched_words)
    return score, terms


def _ticket_fit(client_min, client_max, investor):
    if not client_min or not client_max:
        return None, ["client raise amount undisclosed — cannot score, verify directly"]
    tmin, tmax = investor.get("ticket_min"), investor.get("ticket_max")
    if not tmin or not tmax:
        return None, ["investor ticket size not published — cannot score, verify directly"]
    cmin, cmax, tmin, tmax = float(client_min), float(client_max), float(tmin), float(tmax)
    overlap = min(cmax, tmax) - max(cmin, tmin)
    if overlap > 0:
        return 100, [f"client ${cmin:,.0f}-${cmax:,.0f} sits inside published range "
                       f"${tmin:,.0f}-${tmax:,.0f}"]
    gap = max(cmin, tmin) - min(cmax, tmax)
    span = max(cmax, tmax) - min(cmin, tmin)
    score = max(0, round(100 * (1 - gap / span))) if span else 0
    direction = "above" if cmin > tmax else "below"
    return score, [f"client range is {direction} published range ${tmin:,.0f}-${tmax:,.0f}"]


def _confidence(investor):
    base, notes = 100, []
    elig = (investor.get("eligibility_category") or "").upper()
    sanctions = (investor.get("sanctions_checked") or "").upper().strip()
    if "PROVISIONAL" in elig:
        base -= 30
        notes.append("eligibility category recorded as PROVISIONAL, not evidenced")
    if sanctions == "UNSCREENED" or not sanctions:
        base -= 30
        notes.append("sanctions screening not on file — required before any contact")
    if not notes:
        notes.append("eligibility evidenced and sanctions screened")
    return max(0, base), notes


def score_match(client: dict, investor: dict) -> dict:
    parts = {
        "sector": _overlap(client.get("sector"), investor.get("sectors"), SECTOR_TAGS),
        "geography": _overlap(client.get("geography"), investor.get("geographies"), GEO_TAGS),
        "ticket": _ticket_fit(client.get("funding_requirement_min"),
                                client.get("funding_requirement_max"), investor),
        "stage": _overlap(f"{client.get('instrument','')} {client.get('stage','')}",
                            f"{investor.get('structures','')} {investor.get('stage_preference','')}",
                            STRUCTURE_TAGS),
    }
    conf_score, conf_notes = _confidence(investor)
    parts["confidence"] = (conf_score, conf_notes)

    total_w, weighted = 0, 0
    breakdown = {}
    for key, w in WEIGHTS.items():
        score, notes = parts[key]
        breakdown[key] = {"score": score, "notes": notes}
        if score is not None:
            total_w += w
            weighted += w * score
    overall = round(weighted / total_w) if total_w else 0

    concerns = [f"{k}: {n}" for k in ("sector", "geography", "ticket", "stage")
                for n in breakdown[k]["notes"] if breakdown[k]["score"] in (0, None)]
    if breakdown["confidence"]["score"] < 100:
        concerns += [f"confidence: {n}" for n in breakdown["confidence"]["notes"]]

    why = [f"{k}: {'; '.join(parts[k][1])}" for k in ("sector", "geography", "stage", "ticket")
           if parts[k][0] and parts[k][0] >= 50]

    return {
        "investor_id": investor.get("id"), "investor_name": investor.get("entity_name"),
        "match_score": overall, "sector_fit": parts["sector"][0],
        "geography_fit": parts["geography"][0], "ticket_fit": parts["ticket"][0],
        "stage_fit": parts["stage"][0], "confidence_fit": parts["confidence"][0],
        "why": why or ["weak on every dimension — see concerns"],
        "concerns": concerns or ["none beyond standard eligibility gating"],
        "recommended_approach": (
            "Route via the investor desk. No opportunity detail may be shared until the s21 "
            "eligibility gate clears (FPO status confirmed in writing, NDA executed, risk "
            "warnings attached)."),
    }


def top_matches(client: dict, investors: list, top_n: int = 10) -> list:
    scored = [score_match(client, inv) for inv in investors]
    scored.sort(key=lambda m: m["match_score"], reverse=True)
    return scored[:top_n]
