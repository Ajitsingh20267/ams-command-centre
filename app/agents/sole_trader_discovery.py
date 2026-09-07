"""Sole-trader discovery — the FSA Food Hygiene Ratings register.

Companies House only ever shows limited companies. A huge share of real
UK high-street businesses -- most takeaways, many cafes and pubs -- are
run as sole traders or partnerships and simply never appear there, at
any price. The Food Standards Agency's rating register is different: by
law, every food business in the UK gets inspected and listed regardless
of legal structure, and the FSA publishes that register free, with no
API key or signup (https://api.ratings.food.gov.uk).

This deliberately does NOT feed the scored `leads` pipeline. A sole
trader has no filed accounts, no officers/PSC data, no charges register
-- none of the evidence the fee-payer gate checks for exists anywhere,
for free, for them. Scoring them the same way would mean either
inventing evidence or quietly lowering the bar for one segment without
saying so -- both are exactly what this codebase's 'never fabricate'
discipline exists to prevent. So these land in their own unscored
sole_trader_leads table: a real name, address, and (when the FSA has
one on file) phone number, for a human to judge and act on directly.

Scope, honestly: this only covers food businesses (takeaways, cafes,
restaurants, pubs, mobile caterers) -- the FSA register's whole reason
to exist. A car wash or a laundrette run as a sole trader isn't food-
licensed and won't be in here; that needs a different free source
(OpenStreetMap's business listings are the candidate, but need proper
regional query batching to be reliable at UK scale -- not built yet).
"""
from __future__ import annotations

import httpx

from .. import db

API = "https://api.ratings.food.gov.uk"

# Real FSA BusinessTypeIds (see GET /BusinessTypes) -- the food-service
# categories that overlap with "small, independent, high-street" rather
# than e.g. supermarkets or school canteens.
BUSINESS_TYPES = {
    7844: "Takeaway/sandwich shop",
    1: "Restaurant/Cafe/Canteen",
    7843: "Pub/bar/nightclub",
    7846: "Mobile caterer",
}

PAGE_SIZE = 20  # per business type, per run -- modest on purpose, same reasoning as the UK sweep


def _get(cfg, params: dict) -> dict | None:
    r = httpx.get(f"{API}/Establishments", headers={"x-api-version": "2", "Accept": "application/json"},
                   params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _address(est: dict) -> str:
    parts = [est.get(f"AddressLine{i}") for i in (1, 2, 3, 4)]
    return ", ".join(p for p in parts if p)


def run(conn, cfg) -> str:
    """Pages through each target business type using a persisted cursor
    (agent_cursors, shared with the Companies House agent -- same generic
    table, a different key namespace) so an hourly run explores fresh
    territory instead of re-fetching the same top results forever."""
    run_id = db.start_run(conn, "sole_trader_discovery")
    try:
        inserted = already = skipped_no_name = failed = 0
        total_checked = 0

        for type_id, label in BUSINESS_TYPES.items():
            cursor_key = f"sole_trader:fsa:type:{type_id}"
            page = db.get_cursor(conn, cursor_key, default=1)
            try:
                data = _get(cfg, {"businessTypeId": type_id, "pageNumber": page,
                                    "pageSize": PAGE_SIZE})
            except Exception as e:
                failed += 1
                db.audit(conn, "sole_trader_discovery", "page_fetch_error", "sole_trader_leads",
                          None, {"business_type": label, "page": page, "error": str(e)})
                continue

            establishments = (data or {}).get("establishments", [])
            total_pages = ((data or {}).get("meta") or {}).get("totalPages", page)
            next_page = page + 1 if page < total_pages else 1
            db.set_cursor(conn, cursor_key, next_page)

            for est in establishments:
                total_checked += 1
                name = est.get("BusinessName")
                fhrsid = est.get("FHRSID")
                if not name or not fhrsid:
                    skipped_no_name += 1
                    continue

                with conn.cursor() as cur:
                    cur.execute(
                        "insert into sole_trader_leads (source, source_id, business_name, "
                        "business_type, address, postcode, phone, local_authority, "
                        "rating_value, source_url) "
                        "values ('FSA Food Hygiene Ratings',%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "on conflict (source, source_id) do nothing returning id",
                        (str(fhrsid), name, est.get("BusinessType") or label, _address(est),
                         est.get("PostCode"), est.get("Phone") or None,
                         est.get("LocalAuthorityName"), est.get("RatingValue"),
                         f"https://ratings.food.gov.uk/business/{fhrsid}"))
                    if cur.fetchone() is None:
                        already += 1
                    else:
                        inserted += 1

        summary = (f"Sole trader discovery (FSA): {total_checked} checked, {inserted} inserted, "
                    f"{already} already on file, {skipped_no_name} skipped (no name/id), "
                    f"{failed} page fetch failure(s)")
        db.finish_run(conn, run_id, True, summary)
        return summary
    except Exception as e:
        db.finish_run(conn, run_id, False, "", str(e))
        raise
