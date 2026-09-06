"""Lead generation — UK Companies House. Free, real, no cost ever (a REST
key, registered free at developer.company-information.service.gov.uk).

This exists to fix a real targeting problem the SEC EDGAR agent has: EDGAR
only indexes SEC-registered (i.e. public) companies, and a company
sophisticated enough to be public almost always already has an investment
bank — the wrong target for a firm selling a first advisory engagement.
Companies House indexes the actual target: private, UK-incorporated
companies, with real signals of both need (a charge = secured borrowing in
place) and the ability to pay (filed accounts, an individual with
significant control who can approve a fee without a board).

Two stages, both against the free public register:
  1. Discovery — Advanced Search for active companies in relevant sectors.
     This is the piece the original reference implementation
     (`Sales Department/feeds/companies-house-feed.py`) deliberately did not
     do ("this feed enriches and gates a candidate universe; it does not
     invent one") — that script expected a pre-built number list. This one
     builds the list itself.
  2. Enrichment + gating — same rules as that reference implementation:
     reject insolvency history (the wrong hunt — strongest need, weakest
     ability to pay), reject dormant/no-accounts (no evidence of trading),
     evidence owner-management from officers/PSC data, evidence a live
     asset from outstanding charges.

Never fabricates a signal: a company with no charge and no accounts
evidence is skipped, not guessed at.
"""
from __future__ import annotations

import base64
import time
from datetime import date, datetime, timedelta

import httpx

from .. import db

API = "https://api.company-information.service.gov.uk"

# Real, full 5-digit UK SIC 2007 codes for the sectors A.M.S. actually
# advises — filters out the long tail of dormant holding companies and
# unrelated trades that would otherwise dominate a broad search.
#
# These must be exact 5-digit codes, not prefixes: the advanced-search API's
# sic_codes filter matches on the literal code, unlike the reference
# implementation's local prefix-matching against an already-fetched
# company's own sic_codes list. Verified live against the real API on
# 2026-09-06 — a 3-digit value (e.g. "412") returns 404, not zero results.
SIC_CODES = [
    "41100",   # development of building projects
    "41201",   # construction of commercial buildings
    "41202",   # construction of domestic buildings
    "43999",   # other specialised construction activities n.e.c.
    "68100",   # buying and selling of own real estate
    "68201",   # renting and operating of Housing Association real estate
    "68209",   # other letting and operating of own or leased real estate
    "68320",   # management of real estate on a fee or contract basis
    "35110",   # production of electricity
    "35130",   # distribution of electricity
    "35300",   # steam and air conditioning supply
    "42110",   # construction of roads and motorways
    "42910",   # construction of water projects
    "42990",   # construction of other civil engineering projects n.e.c.
    "62012",   # business and domestic software development
    "62020",   # information technology consultancy activities
    "62090",   # other information technology service activities
    "63110",   # data processing, hosting and related activities
    "56101",   # licensed restaurants
    "56102",   # unlicensed restaurants and cafes
    "55100",   # hotels and similar accommodation
    "47190",   # other retail sale in non-specialised stores
]

DESK_FORMS_NOTE = {"DEB-1": "outstanding charge", "REF-1": "outstanding charge, dated",
                     "MNA-1": "succession-shaped (age + small board)", "RDY-1": "accounts overdue"}

DISTRESS_STATUSES = {"liquidation", "receivership", "administration",
                       "voluntary-arrangement", "insolvency-proceedings"}


class CompaniesHouseError(RuntimeError):
    pass


def _auth_header(key: str) -> dict:
    token = base64.b64encode(f"{key}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _get(cfg, path: str, params: dict = None) -> dict | None:
    r = httpx.get(f"{API}{path}", headers=_auth_header(cfg.companies_house_key),
                   params=params, timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code == 401:
        raise CompaniesHouseError("COMPANIES_HOUSE_KEY rejected (401) — check it's a REST key")
    if r.status_code == 429:
        raise CompaniesHouseError("Companies House rate-limited us (429)")
    r.raise_for_status()
    return r.json()


PAGE_SIZE = 3  # per SIC code, per run — modest on purpose, see run_sweep's docstring


def discover_candidates(conn, cfg, per_sic: int = PAGE_SIZE) -> list:
    """Advanced Search for active companies in relevant sectors, incorporated
    at least a year ago (a brand-new company has no accounts history yet, so
    there is nothing to evidence against the fee-payer gate).

    Each SIC code has its own persisted paging cursor (agent_cursors) so an
    hourly run explores a fresh slice of the register each time rather than
    re-fetching the same top results forever — one code alone can have well
    over 100,000 matches, so without this the agent would plateau after its
    first run and never see the other 99%+ of the target population. A code
    that returns nothing at its current offset (end of that SIC's results)
    wraps back to the start rather than getting stuck.
    """
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    seen, out = set(), []
    for sic in SIC_CODES:
        cursor_key = f"companies_house:sic:{sic}"
        start_index = db.get_cursor(conn, cursor_key, default=0)
        data = _get(cfg, "/advanced-search/companies", {
            "sic_codes": sic, "company_status": "active",
            "incorporated_to": cutoff, "size": per_sic, "start_index": start_index,
        }) or {}
        items = data.get("items", [])
        if not items and start_index > 0:
            # Ran off the end of this SIC code's results — wrap around.
            start_index = 0
            data = _get(cfg, "/advanced-search/companies", {
                "sic_codes": sic, "company_status": "active",
                "incorporated_to": cutoff, "size": per_sic, "start_index": 0,
            }) or {}
            items = data.get("items", [])
        for item in items:
            num = item.get("company_number")
            if num and num not in seen:
                seen.add(num)
                out.append(num)
        db.set_cursor(conn, cursor_key, start_index + len(items))
        time.sleep(0.3)
    return out


def _accounts_signal(profile: dict):
    acc = (profile.get("accounts") or {})
    last = acc.get("last_accounts") or {}
    return (last.get("type") or "").lower(), last.get("made_up_to")


def _owner_managed(officers: dict, pscs: dict):
    active = [o for o in (officers or {}).get("items", []) if not o.get("resigned_on")]
    if not active or len(active) > 4:
        return None
    individuals = [p for p in (pscs or {}).get("items", [])
                    if (p.get("kind") or "").startswith("individual") and not p.get("ceased_on")]
    if not individuals:
        return None
    return f"{len(active)} active officer(s), {len(individuals)} individual PSC(s) with control"


def _desk_signal(desk: str, profile: dict, charges: list):
    if desk == "DEB-1":
        if not charges:
            return None, None
        newest = max(charges, key=lambda c: c.get("created_on") or c.get("delivered_on") or "")
        d = newest.get("created_on") or newest.get("delivered_on")
        return f"Charge registered {d}, {len(charges)} outstanding charge(s) on the register.", d
    if desk == "REF-1":
        dated = [c for c in charges if c.get("particulars")]
        if not dated:
            return None, None
        newest = max(dated, key=lambda c: c.get("created_on") or "")
        d = newest.get("created_on")
        return f"Outstanding charge created {d} still on the register — inside a typical " \
               f"refinancing window.", d
    if desk == "MNA-1":
        inc = profile.get("date_of_creation")
        if not inc:
            return None, None
        age = (date.today() - datetime.strptime(inc, "%Y-%m-%d").date()).days / 365.25
        if age < 12:
            return None, None
        return f"Incorporated {inc}, {age:.0f} years trading, small active board — " \
               f"succession-shaped.", inc
    if desk == "RDY-1":
        nxt = (profile.get("accounts") or {}).get("next_accounts") or {}
        if nxt.get("overdue"):
            return f"Accounts overdue (due {nxt.get('due_on')}).", nxt.get("due_on")
        return None, None
    return None, None


def _score(desk: str, evidence: dict) -> tuple:
    score = 50
    notes = [f"base 50 for a matched {desk} trigger"]
    if evidence.get("owner_managed"):
        score += 20
        notes.append("+20: owner-managed shape evidenced from officers/PSC data")
    if evidence.get("revenue"):
        score += 15
        notes.append("+15: filed accounts evidence trading")
    if evidence.get("asset"):
        score += 10
        notes.append("+10: outstanding charge evidences a funded asset")
    score = min(100, score)
    band = ("Priority" if score >= 90 else "High" if score >= 75 else
             "Medium" if score >= 60 else "Low" if score >= 40 else "Reject")
    return score, band, "; ".join(notes)


def run_sweep(conn, cfg) -> str:
    """Discovers candidates, gates them, and inserts new leads. Idempotent —
    dedup is on (company name, country) at the DB level.

    Discovery volume is deliberately modest per run (PAGE_SIZE=3 per SIC
    code, ~22 codes -> ~66 candidates, ~260 enrichment calls) rather than
    fetching everything available in one go: Companies House's free tier
    allows 600 requests per 5 minutes, and a single SIC code alone can have
    six-figure match counts, so "all of it in one run" was never realistic
    or safe. Run hourly (see .github/workflows/scheduler.yml), this steadily
    works through the full target population over weeks via the persisted
    per-SIC-code cursor in discover_candidates — a marathon, not a sprint,
    and one that never re-covers ground it's already paged past.
    """
    run_id = db.start_run(conn, "companies_house")
    try:
        numbers = discover_candidates(conn, cfg)
        inserted = rejected_distress = rejected_no_evidence = rejected_duplicate = 0
        rejected_error = 0

        for num in numbers:
            # One candidate's failure (a network blip, a transient 5xx) must
            # not lose the whole run's progress — the cursor in
            # discover_candidates has already advanced past every candidate
            # in `numbers`, so any of them left unprocessed here is genuinely
            # skipped this run, not silently retried. Logging it and moving
            # on is the honest behaviour; crashing the whole sweep for one
            # bad connection (as happened in testing on 2026-09-07 — a real
            # SSL handshake timeout mid-run) is not.
            try:
                time.sleep(0.15)  # stay comfortably under the free-tier rate limit
                profile = _get(cfg, f"/company/{num}")
                if not profile:
                    continue
                if profile.get("company_status") != "active":
                    continue
                if (profile.get("company_status_detail") or "").lower() in DISTRESS_STATUSES:
                    rejected_distress += 1
                    continue

                cat, made_up = _accounts_signal(profile)
                evidence = {}
                if cat in ("full", "group", "medium", "audit-exemption-subsidiary",
                            "small", "total-exemption-full"):
                    evidence["revenue"] = f"{cat} accounts to {made_up}"
                elif cat in ("dormant", "no-accounts-filed", ""):
                    rejected_no_evidence += 1
                    continue

                officers = _get(cfg, f"/company/{num}/officers")
                pscs = _get(cfg, f"/company/{num}/persons-with-significant-control")
                om = _owner_managed(officers, pscs)
                if om:
                    evidence["owner_managed"] = om

                charges_data = _get(cfg, f"/company/{num}/charges") or {}
                charges = [c for c in charges_data.get("items", [])
                            if c.get("status") == "outstanding"]
                if charges:
                    evidence["asset"] = f"{len(charges)} outstanding charge(s)"

                # Fee-payer gate: at least 2 of the evidenced tests, same
                # threshold as the reference implementation and the
                # origination sweep.
                if len(evidence) < 2:
                    rejected_no_evidence += 1
                    continue

                desk, signal, signal_date = None, None, None
                for candidate_desk in ("DEB-1", "REF-1", "MNA-1", "RDY-1"):
                    s, d = _desk_signal(candidate_desk, profile, charges)
                    if s:
                        desk, signal, signal_date = candidate_desk, s, d
                        break
                if not desk:
                    rejected_no_evidence += 1
                    continue

                name = profile.get("company_name", num)
                score, band, score_reason = _score(desk, evidence)
                source_url = ("https://find-and-update.company-information.service.gov.uk"
                               f"/company/{num}")

                with conn.cursor() as cur:
                    cur.execute(
                        "insert into companies (name, country, notes) values (%s,%s,%s) "
                        "on conflict (name, country) do nothing returning id",
                        (name, "United Kingdom",
                         f"Companies House {num}. First seen via UK sweep."))
                    row = cur.fetchone()
                    if row is None:
                        rejected_duplicate += 1
                        continue
                    company_id = row["id"]
                    cur.execute(
                        "insert into leads (company_id, desk, geography, sector, signal, "
                        "signal_date, source_url, score, score_reason, band, confidence, "
                        "stage, next_action) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (company_id, desk, "United Kingdom",
                         ", ".join(profile.get("sic_codes") or []) or "UNKNOWN", signal,
                         signal_date, source_url, score, score_reason, band, "VERIFIED",
                         "Lead", "Verify a named decision-maker and contact route before "
                         "drafting — Companies House has no contact data beyond a "
                         "registered office"))
                inserted += 1
            except Exception as e:
                rejected_error += 1
                db.audit(conn, "companies_house", "candidate_error", "companies", None,
                          {"company_number": num, "error": str(e)})
                continue

        summary = (f"UK sweep: {len(numbers)} candidates, {inserted} inserted, "
                    f"{rejected_distress} rejected (distress/insolvency), "
                    f"{rejected_no_evidence} rejected (insufficient evidence), "
                    f"{rejected_error} failed (network/API error), "
                    f"{rejected_duplicate} already on file")
        db.audit(conn, "companies_house", "sweep_complete", "leads", None,
                  {"inserted": inserted, "candidates": len(numbers)})
        db.finish_run(conn, run_id, True, summary)
        return summary
    except Exception as e:
        db.finish_run(conn, run_id, False, "", str(e))
        raise
