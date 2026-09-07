"""Template-based outreach drafting — a zero-cost fallback for
claude_agent.draft_touch, used while ANTHROPIC_API_KEY isn't configured
(deliberately deferred — no budget until the first mandate closes).

Same discipline as the Anthropic path, just without a model in the loop:
every fact stated comes from the knowledge_base table or the lead's own
verified fields (contact name, company name, the real signal the sourcing
agent already evidenced) — nothing is invented. If a required
knowledge_base entry is missing, this refuses to draft rather than guess
at wording, exactly like claude_agent.draft_touch's "insufficient verified
information" path returning None.

The wording below is fixed, not generated, so there's no model to
hallucinate a claim compliance/never_claim forbids — but it was still
written by hand against that entry and brand/house_voice, not
independently of them: no regulated/FCA claim, no promise capital will be
raised or a deal will complete, no named capital partner, no pooling
language, none of the banned phrases in the house voice entry. Once
Anthropic is connected, cron.py prefers claude_agent.draft_touch (richer,
personalised); this stays as the fallback that keeps outreach moving at
zero cost until then.
"""
from __future__ import annotations

REQUIRED_KB = (("company_info", "overview"), ("company_info", "verified_track_record"))


def _kb_lookup(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("select category, key, content from knowledge_base")
        return {(r["category"], r["key"]): r["content"] for r in cur.fetchall()}


def _greeting_name(contact_name: str) -> str:
    """Companies House officer names arrive as "SURNAME, Firstname Middle"
    (all-caps surname first) -- e.g. "MCKENZIE, George". A greeting built
    straight from that reads as if it's shouting the surname. This turns
    it into "George Mckenzie" when it can, and falls back to the raw
    string as-is (never inventing a name it doesn't have) for anything
    that isn't in that specific two-part comma form."""
    parts = [p.strip() for p in (contact_name or "").split(",")]
    if len(parts) == 2 and parts[0] and parts[1]:
        surname, given = parts
        first_given = given.split()[0] if given.split() else given
        return f"{first_given.title()} {surname.title()}"
    return contact_name


def draft_touch(conn, lead: dict) -> dict | None:
    """Returns {"subject", "body_html"} or None if a required knowledge_base
    entry is missing — callers must treat that as "do not draft", same
    contract as claude_agent.draft_touch."""
    kb = _kb_lookup(conn)
    if any(k not in kb for k in REQUIRED_KB):
        return None

    company = lead.get("company") or "your business"
    greeting = f"Dear {_greeting_name(lead.get('contact_name'))}," \
        if lead.get("contact_name") else "Hello,"
    signal = (lead.get("signal") or "").strip()

    subject = f"A.M.S. Capital Management — {company}"

    signal_para = (f"<p>We noted the following on the public record: {signal}</p>"
                    if signal else "")

    body_html = (
        f"<p>{greeting}</p>"
        f"<p>A.M.S. Capital Management is an independent capital advisory firm. Since 2022 "
        f"we have advised on transactions and developments with an aggregate value of "
        f"$3.35bn, working with a database of over 1,700 international capital partners.</p>"
        f"{signal_para}"
        f"<p>If a conversation about capital or strategic options for {company} would be "
        f"useful, I would welcome a short call.</p>"
        f"<p>A.M.S. Capital Management<br>invest@amscapital.co.uk</p>"
    )
    return {"subject": subject, "body_html": body_html}
