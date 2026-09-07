"""Contact discovery — turns a bare lead into one a human can actually be
asked to approve outreach to.

Companies House never publishes an email address (only a registered
office), so a lead sourced there arrives with a real company and a real
signal but no one to write to. This agent closes that gap using only the
same free register: it pulls the named, currently-active officer(s) for
each qualifying UK lead and records them as a contact — a real name and
role, sourced and dated, never guessed.

This does NOT invent an email. `contacts.email_status` stays 'UNKNOWN'
here; draft-outreach's gate (VERIFIED email required) is deliberately not
satisfied by this step alone, because a plausible-looking
firstname.lastname@company.com pattern is exactly the kind of fabrication
this system refuses to do (see PATTERN-INFERRED in the schema comment,
and 'never fabricate' throughout this codebase). Getting a VERIFIED email
requires an actual published source (the company's own site, a filing) —
that step is done separately, by hand, in a Claude Code session with web
access, and written to the same table with source_url set to where it
was actually found.
"""
from __future__ import annotations

import re

from .. import db
from .companies_house import _get


_CH_NUMBER_RE = re.compile(r"Companies House (\S+)\.")


def _officer_contact(officers: dict):
    """Pick one real, currently-active officer to name as the contact.
    Prefers a director over other roles (secretary, etc.) since a director
    can actually approve an engagement; falls back to whichever active
    officer is listed first. Returns None if there is no active officer at
    all (already excluded upstream by the fee-payer gate, but the sweep
    and this step can run at different times as the register changes)."""
    active = [o for o in (officers or {}).get("items", []) if not o.get("resigned_on")]
    if not active:
        return None
    directors = [o for o in active if "director" in (o.get("officer_role") or "").lower()]
    officer = directors[0] if directors else active[0]
    return officer.get("name"), officer.get("officer_role") or "Officer"


def run(conn, cfg) -> str:
    """For every UK lead eligible for drafting (score >= 60, no contact on
    file yet), look up the company's active officers on Companies House and
    record the best one as a named contact. Free, real, no cost — reuses
    the same REST key as the discovery sweep."""
    run_id = db.start_run(conn, "contact_discovery")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select l.id as lead_id, c.id as company_id, c.name, c.notes "
                "from leads l join companies c on c.id = l.company_id "
                "where c.country = 'United Kingdom' and l.score >= 60 "
                "and not exists (select 1 from contacts ct where ct.company_id = c.id)")
            candidates = cur.fetchall()

        named = skipped_no_number = skipped_no_officer = failed = 0
        for row in candidates:
            match = _CH_NUMBER_RE.search(row["notes"] or "")
            if not match:
                skipped_no_number += 1
                continue
            number = match.group(1)
            try:
                officers = _get(cfg, f"/company/{number}/officers")
            except Exception as e:
                failed += 1
                db.audit(conn, "contact_discovery", "lookup_error", "companies",
                          row["company_id"], {"company_number": number, "error": str(e)})
                continue

            found = _officer_contact(officers)
            if not found:
                skipped_no_officer += 1
                continue
            name, role = found

            with conn.cursor() as cur:
                cur.execute(
                    "insert into contacts (company_id, name, role, email_status, source) "
                    "values (%s,%s,%s,'UNKNOWN',%s)",
                    (row["company_id"], name, role,
                     f"Companies House officers — {number}"))
            named += 1

        summary = (f"Contact discovery: {len(candidates)} UK leads checked, "
                    f"{named} named contact(s) recorded (no email — Companies House "
                    f"doesn't publish one), {skipped_no_officer} had no active officer "
                    f"on record, {skipped_no_number} had no parseable company number, "
                    f"{failed} lookup failure(s)")
        db.finish_run(conn, run_id, True, summary)
        return summary
    except Exception as e:
        db.finish_run(conn, run_id, False, "", str(e))
        raise
