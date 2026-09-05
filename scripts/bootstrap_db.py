#!/usr/bin/env python3
"""One command, entire database setup: schema + knowledge base + (optionally)
the real investor CSV. Replaces three manual steps (copy migration into the
Supabase SQL editor, copy seed file, run the CSV importer separately) with
one. Safe to re-run — every statement is idempotent.

Usage:
    export DATABASE_URL="<your Supabase connection string>"
    python3 scripts/bootstrap_db.py
    python3 scripts/bootstrap_db.py --investors "/path/to/ams-capital-partners.csv"
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--investors", help="path to ams-capital-partners.csv (optional)")
    ap.add_argument("--database-url", help="overrides $DATABASE_URL")
    args = ap.parse_args()

    database_url = args.database_url or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("FATAL: set DATABASE_URL (or pass --database-url) — your Supabase project's "
              "connection string from Project Settings -> Database.", file=sys.stderr)
        return 2

    import psycopg2
    import psycopg2.extras

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True

    print("Applying schema...")
    with conn.cursor() as cur, open(os.path.join(root, "db", "migrations", "001_init.sql")) as f:
        cur.execute(f.read())
    print("  done — 22 tables.")

    print("Seeding knowledge base...")
    with conn.cursor() as cur, open(os.path.join(root, "db", "seed_knowledge_base.sql")) as f:
        cur.execute(f.read())
    with conn.cursor() as cur:
        cur.execute("select count(*) as n from knowledge_base")
        print(f"  done — {cur.fetchone()['n']} facts on file.")

    if args.investors:
        print(f"Importing investors from {args.investors}...")
        import csv
        import re

        def _amounts(*texts):
            blob = " ".join(t or "" for t in texts)
            if "not published" in blob.lower():
                return []
            nums = re.findall(r"[\d,]{6,}", blob.replace(" ", ""))
            return sorted(int(n.replace(",", "")) for n in nums if n.replace(",", "").isdigit())

        with open(args.investors, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        n = 0
        with conn.cursor() as cur:
            for r in rows:
                name = (r.get("entity") or "").strip()
                if not name:
                    continue
                amounts = _amounts(r.get("ticket_min"), r.get("ticket_max"), r.get("notes"))
                tmin, tmax = (min(amounts), max(amounts)) if amounts else (None, None)
                cur.execute(
                    "insert into investors (entity_name, type, jurisdiction, ticket_min, "
                    "ticket_max, sectors, geographies, structures, stage_preference, "
                    "source_url, eligibility_category, nda_status, tier, sanctions_checked, "
                    "notes) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "on conflict (entity_name) do nothing",
                    (name, r.get("type"), r.get("jurisdiction"), tmin, tmax, r.get("sectors"),
                     r.get("geographies"), r.get("structures"), r.get("stage_preference"),
                     r.get("source_url"), r.get("eligibility_category"), r.get("nda_status"),
                     r.get("tier"), r.get("sanctions_checked"), r.get("notes")))
                n += 1
        print(f"  done — {n} investor rows processed.")

    print("\nDatabase is ready. Deploy the app, sign in, and the dashboard reads from this "
          "same database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
