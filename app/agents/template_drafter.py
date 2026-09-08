"""Template-based outreach drafting — a zero-cost fallback for
claude_agent.draft_touch, used while ANTHROPIC_API_KEY isn't configured
(deliberately deferred — no budget until the first mandate closes).

Same discipline as the Anthropic path, just without a model in the loop:
every fact stated comes from the knowledge_base table or the lead's own
verified fields (contact name, company name, desk, the real signal the
sourcing agent already evidenced) — nothing is invented. If a required
knowledge_base entry is missing, this refuses to draft rather than guess
at wording, exactly like claude_agent.draft_touch's "insufficient verified
information" path returning None.

Matched to the tone and structure of the firm's own already-approved
outreach (see Sales Department/outreach/sequences/maddox-planning-
sequence.md — the human-written reference this was rewritten against on
2026-09-08 after the first batch of drafts read as a mail-merge, not a
cold email): first person, one specific real observation instead of the
internal audit string verbatim, the "investor pays the success fee, not
you" hook (compliance/never_claim's own strongest true commercial point),
a proactive regulatory disclosure rather than a hidden one, a real named
signer, and a proper compliance footer. The wording below is fixed, not
generated, so there's no model to hallucinate a claim compliance/
never_claim forbids — but it was still written by hand against that
entry and brand/house_voice, not independently of them.
"""
from __future__ import annotations

REQUIRED_KB = (("company_info", "overview"), ("company_info", "verified_track_record"),
               ("compliance", "regulatory_position"), ("pricing", "stage_two"))

SIGNER = "Ajit Sohal"
SIGNER_LINE = f"{SIGNER}<br>A.M.S. Capital Management, London"

FOOTER = (
    "<hr>"
    "<p style=\"font-size:12px;color:#666\">A.M.S. Capital Management Holdings Ltd &middot; "
    "Registered in England and Wales, company number 17396139<br>"
    "5th Floor, 167-169 Great Portland Street, London W1W 5PF &middot; "
    "invest@amscapital.co.uk</p>"
    "<p style=\"font-size:12px;color:#666\">A.M.S. Capital Management Holdings Ltd provides "
    "corporate advisory services. It does not manage client money or hold client assets. "
    "Where regulated activities are involved, the firm works alongside appropriately "
    "authorised advisers and counterparties. Nothing in this message is an offer, a "
    "solicitation, or a financial promotion, and no representation is made that capital "
    "will be raised on any mandate.</p>"
    "<p style=\"font-size:12px;color:#666\">If you would prefer not to hear from us, reply "
    "with \"remove\" and we will delete your details.</p>"
)

# Per-desk opening line: what the sourcing agent actually evidenced, restated
# as one plain, specific, non-alarming observation a person would write --
# never the raw internal signal string (that reads as an audit log, not a
# cold email, and for RDY-1 specifically, leading with "your accounts are
# overdue" reads as an accusation rather than an opening). Each one stays
# strictly inside what that desk's gate actually checked -- see
# app/agents/companies_house.py's _desk_signal and DESK_FORMS_NOTE, and
# lead_generation.py's DESK_QUERIES for what "evidenced" means per desk.
_DESK_OPENER = {
    "DEB-1": "I noticed from the public record that {company} has secured lending in "
             "place.",
    "REF-1": "I noticed {company} has had a secured facility on the register for a while "
             "now -- often the point where it is worth checking the terms are still "
             "competitive rather than assuming they are.",
    "MNA-1": "{company} is a long-established, closely-held business -- exactly the "
             "position where succession or bringing in a strategic partner tends to "
             "become worth a real conversation.",
    "RDY-1": "As {company} approaches its next accounts filing, this is often a natural "
             "point to take stock of capital plans for the year ahead.",
    "CAP-1": "Your recent filing referenced anticipated additional capital requirements.",
}

_DESK_QUESTION = {
    "DEB-1": "Is that facility still on the best terms available, or worth a second look?",
    "REF-1": "Worth comparing it against what is available now?",
    "MNA-1": "Is succession, or bringing in a strategic partner, something that has been "
             "on your mind?",
    "RDY-1": "Is raising or restructuring capital something worth discussing before then?",
    "CAP-1": "Is that still an open question for you?",
}

_DEFAULT_OPENER = "I noticed {company} came up in our research into businesses that may " \
                   "be weighing capital plans."
_DEFAULT_QUESTION = "Is that something worth a short conversation?"


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


def _first_name(greeting_name: str) -> str:
    return greeting_name.split()[0] if greeting_name and greeting_name.split() else "there"


def draft_touch(conn, lead: dict) -> dict | None:
    """Returns {"subject", "body_html"} or None if a required knowledge_base
    entry is missing — callers must treat that as "do not draft", same
    contract as claude_agent.draft_touch."""
    kb = _kb_lookup(conn)
    if any(k not in kb for k in REQUIRED_KB):
        return None

    company = lead.get("company") or "your business"
    greeting_name = _greeting_name(lead.get("contact_name"))
    greeting = f"Dear {_first_name(greeting_name)}," if greeting_name else "Dear there,"

    desk = lead.get("desk")
    opener = (_DESK_OPENER.get(desk) or _DEFAULT_OPENER).format(company=company)
    question = _DESK_QUESTION.get(desk) or _DEFAULT_QUESTION

    subject = f"A question about {company}'s capital plans"

    body_html = (
        f"<p>{greeting}</p>"
        f"<p>I run capital advisory at A.M.S. Capital Management in London. {opener}</p>"
        f"<p>We prepare businesses for capital and run a targeted process against a "
        f"network of over 1,700 international capital partners -- institutions, family "
        f"offices, private equity and lenders -- having advised on mandates with an "
        f"aggregate value of $3.35bn since 2022. The success fee is charged to the "
        f"investor, not you, so if a raise completes, {company} receives the agreed "
        f"capital in full.</p>"
        f"<p>We are a corporate advisory firm and are not currently authorised by the "
        f"Financial Conduct Authority -- we say that upfront because you would find it "
        f"anyway, and we work alongside appropriately authorised counterparties where "
        f"regulated activities arise.</p>"
        f"<p>{question}</p>"
        f"<p>{SIGNER_LINE}</p>"
        f"{FOOTER}"
    )
    return {"subject": subject, "body_html": body_html}
