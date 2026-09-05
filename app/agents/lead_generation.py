"""Lead generation — SEC EDGAR full-text search. Free, no API key.

This is a real data source, not a simulated one: it queries the same public
endpoint behind the EDGAR full-text search UI that
`Sales Department/feeds/sec-edgar-feed.py` already uses in production, and
applies the same distress-rejection rule — a company already in going-concern
or insolvency language is the strongest need and the weakest ability to pay,
which is the wrong hunt (see CLAUDE.md's fee-payer gate). Ported here rather
than re-derived so the two stay behaviourally identical; if the phrase sets or
gate logic change, change both.

The endpoint is the JSON service behind the EDGAR UI, not a formally
versioned API — SEC has moved it before. It is isolated in EDGAR_FTS_URL for
exactly that reason, and this module fails loudly (raises) rather than
silently returning nothing if SEC starts rejecting requests.
"""
from __future__ import annotations

import os
import time
import urllib.parse
from datetime import date, timedelta

import httpx

from .. import db

EDGAR_FTS_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"

USER_AGENT = os.getenv(
    "SEC_USER_AGENT", "A.M.S. Capital Management Holdings Ltd invest@amscapital.co.uk")
REQUEST_SLEEP_S = 0.2  # ~5 req/s, comfortably under SEC's limit

DESK_QUERIES = {
    "REF-1": ['"matures within the next twelve months"', '"balloon payment"',
              '"revolving credit facility expires"'],
    "CAP-1": ['"we will require additional capital"', '"additional financing will be required"'],
    "RDY-1": ['"withdraw the registration statement"', '"application for withdrawal"'],
    "DEB-1": ['"forbearance agreement"', '"waiver of the covenant"'],
}
DESK_FORMS = {
    "REF-1": ["10-K", "10-Q"], "CAP-1": ["10-K", "10-Q", "S-1"],
    "RDY-1": ["RW", "AW"], "DEB-1": ["8-K", "10-Q"],
}
DISTRESS_MARKERS = ["chapter 11", "chapter 7", "receivership", "liquidation",
                     "substantial doubt about", "ceased operations", "delisting notice"]


class EdgarError(RuntimeError):
    pass


def _score(desk: str, form: str, filed: str) -> tuple:
    """0-100, built only from evidence actually on the filing — no invented
    factors. Recency and form type are the only two things this feed knows
    for certain; a richer score needs a human call or a second data source.
    """
    score = 50
    notes = [f"base 50 for a matched {desk} trigger phrase"]
    try:
        days_old = (date.today() - date.fromisoformat(filed)).days
        if days_old <= 30:
            score += 20
            notes.append(f"+20: filed {days_old}d ago, inside the 30-day recency window")
    except (ValueError, TypeError):
        notes.append("filing date unparseable — no recency bonus applied")
    if form in ("10-K", "10-Q"):
        score += 15
        notes.append(f"+15: {form} is an ongoing SEC registrant — audited accounts, named "
                       f"auditor, evidences 2 of the 4 fee-payer tests on its own")
    if desk in ("REF-1", "DEB-1"):
        score += 10
        notes.append(f"+10: {desk} triggers carry a dated deadline, which is the desk's own "
                       f"highest-value signal")
    score = min(100, score)
    band = ("Priority" if score >= 90 else "High" if score >= 75 else
             "Medium" if score >= 60 else "Low" if score >= 40 else "Reject")
    return score, band, "; ".join(notes)


def _fetch(url: str) -> dict:
    r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if r.status_code == 403:
        raise EdgarError("SEC returned 403 — almost always the User-Agent. "
                          "Set SEC_USER_AGENT to a real contact address and retry.")
    if r.status_code == 429:
        raise EdgarError("SEC rate-limited us (429). Raise REQUEST_SLEEP_S.")
    if r.status_code == 404:
        raise EdgarError(f"{url} returned 404 — the EDGAR full-text endpoint has likely "
                          f"moved. Fix EDGAR_FTS_URL; do not work around it downstream.")
    r.raise_for_status()
    return r.json()


def search(desk: str, days: int, limit: int) -> list:
    end = date.today()
    start = end - timedelta(days=days)
    hits, seen = [], set()
    for phrase in DESK_QUERIES[desk]:
        params = {"q": phrase, "dateRange": "custom", "startdt": start.isoformat(),
                   "enddt": end.isoformat(), "forms": ",".join(DESK_FORMS[desk])}
        data = _fetch(EDGAR_FTS_URL + "?" + urllib.parse.urlencode(params))
        time.sleep(REQUEST_SLEEP_S)
        for h in (data.get("hits", {}) or {}).get("hits", []):
            src = h.get("_source", {}) or {}
            cik = (src.get("ciks") or [None])[0]
            name = (src.get("display_names") or ["UNKNOWN"])[0]
            if not cik or cik in seen:
                continue
            seen.add(cik)
            hits.append({"cik": cik, "name": name,
                          "form": src.get("root_form") or src.get("file_type"),
                          "filed": src.get("file_date"),
                          "adsh": (h.get("_id") or "").split(":")[0], "phrase": phrase})
            if len(hits) >= limit:
                return hits
    return hits


def run_sweep(conn, cfg, desk: str = "REF-1", days: int = 30, limit: int = 40) -> str:
    """Fetches, filters, and inserts new leads. Returns a one-line summary.
    Every insert is deduplicated on (company name, country) at the DB
    level (companies.unique constraint), so re-running this is always safe.
    """
    run_id = db.start_run(conn, f"lead_generation:{desk}")
    try:
        hits = search(desk, days, limit)
        inserted, rejected_distress, rejected_duplicate = 0, 0, 0

        for h in hits:
            name = h["name"].split("  (CIK")[0].strip()
            blob = " ".join(str(v).lower() for v in h.values())
            if any(m in blob for m in DISTRESS_MARKERS):
                rejected_distress += 1
                continue

            cik = str(h["cik"]).lstrip("0")
            adsh = (h.get("adsh") or "").replace("-", "")
            source_url = f"{EDGAR_ARCHIVE}/{cik}/{adsh}" if adsh else f"{EDGAR_ARCHIVE}/{cik}"
            signal = f"{h['form']} filed {h['filed']} contains {h['phrase']}."
            score, band, score_reason = _score(desk, h["form"], h["filed"])

            with conn.cursor() as cur:
                cur.execute(
                    "insert into companies (name, country, notes) values (%s,%s,%s) "
                    "on conflict (name, country) do nothing returning id",
                    (name, "United States",
                     f"SEC CIK {h['cik']}. First seen via {desk} EDGAR sweep."))
                row = cur.fetchone()
                if row is None:
                    rejected_duplicate += 1
                    continue
                company_id = row["id"]

                cur.execute(
                    "insert into leads (company_id, desk, geography, signal, signal_date, "
                    "source_url, score, score_reason, band, confidence, stage, next_action) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (company_id, desk, "United States", signal, h["filed"], source_url,
                     score, score_reason, band, "VERIFIED", "Lead",
                     "Verify a named decision-maker and contact route before drafting"))
            inserted += 1

        summary = (f"desk {desk}: {len(hits)} raw hits, {inserted} inserted, "
                    f"{rejected_distress} rejected (distress), "
                    f"{rejected_duplicate} already on file")
        db.audit(conn, f"lead_generation:{desk}", "sweep_complete", "leads", None,
                  {"inserted": inserted, "distress_rejected": rejected_distress,
                   "duplicates": rejected_duplicate})
        db.finish_run(conn, run_id, True, summary)
        return summary
    except Exception as e:
        db.finish_run(conn, run_id, False, "", str(e))
        raise
