#!/usr/bin/env python3
"""One-shot import: the existing investor CSV -> the `investors` table.

Run locally (needs DATABASE_URL in your environment or .env):
    python3 scripts/import_investors.py \\
        --source "/Users/ajitsohal/Downloads/AMS Capital Management/Sales Department/network/ams-capital-partners.csv"

Idempotent — `entity_name` is unique, so re-running updates existing rows
rather than duplicating them. Never invents a ticket size or eligibility
status: a "Not published" field in the CSV stays null here, not a guess.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, db  # noqa: E402


def _parse_amounts(*texts) -> list:
    blob = " ".join(t or "" for t in texts)
    if "not published" in blob.lower():
        return []
    nums = re.findall(r"[\d,]{6,}", blob.replace(" ", ""))
    return sorted(int(n.replace(",", "")) for n in nums if n.replace(",", "").isdigit())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="path to ams-capital-partners.csv")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        print(f"not found: {args.source}", file=sys.stderr)
        return 2

    cfg = config.load()
    conn = db.connect(cfg.database_url)

    with open(args.source, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    inserted = updated = 0
    with conn.cursor() as cur:
        for r in rows:
            name = (r.get("entity") or "").strip()
            if not name:
                continue
            amounts = _parse_amounts(r.get("ticket_min"), r.get("ticket_max"), r.get("notes"))
            ticket_min = min(amounts) if amounts else None
            ticket_max = max(amounts) if amounts else None
            elig = (r.get("eligibility_category") or "").strip()
            relationship = "unverified_lead" if "PROVISIONAL" in elig.upper() else \
                "potential_investor"

            cur.execute(
                "insert into investors (entity_name, type, jurisdiction, ticket_min, ticket_max, "
                "sectors, geographies, structures, stage_preference, contact_name, role, "
                "source_url, relationship_status, eligibility_category, nda_status, tier, "
                "sanctions_checked, notes) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict (entity_name) do update set "
                "type=excluded.type, jurisdiction=excluded.jurisdiction, "
                "ticket_min=excluded.ticket_min, ticket_max=excluded.ticket_max, "
                "sectors=excluded.sectors, geographies=excluded.geographies, "
                "structures=excluded.structures, stage_preference=excluded.stage_preference, "
                "eligibility_category=excluded.eligibility_category, "
                "nda_status=excluded.nda_status, tier=excluded.tier, "
                "sanctions_checked=excluded.sanctions_checked, notes=excluded.notes "
                "returning (xmax = 0) as was_insert",
                (name, r.get("type"), r.get("jurisdiction"), ticket_min, ticket_max,
                 r.get("sectors"), r.get("geographies"), r.get("structures"),
                 r.get("stage_preference"), r.get("contact_name"), r.get("role"),
                 r.get("source_url"), relationship, elig,
                 r.get("nda_status") or "NOT EXECUTED", r.get("tier"),
                 r.get("sanctions_checked") or "UNSCREENED", r.get("notes")))
            was_insert = cur.fetchone()["was_insert"]
            inserted += int(was_insert)
            updated += int(not was_insert)

    db.audit(conn, "import_investors", "csv_import", "investors", None,
              {"inserted": inserted, "updated": updated, "source": args.source})
    print(f"Investors inserted: {inserted}")
    print(f"Investors updated:  {updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
