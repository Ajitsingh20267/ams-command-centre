"""Template-based outreach drafting — a zero-cost fallback for
claude_agent.draft_touch, used while ANTHROPIC_API_KEY isn't configured
(deliberately deferred — no budget until the first mandate closes).

Same discipline as the Anthropic path, just without a model in the loop:
every fact stated comes from the knowledge_base table or the lead's own
verified fields (contact name, company name, desk, source_url, the real
signal the sourcing agent already evidenced) — nothing is invented. If a
required knowledge_base entry is missing, this refuses to draft rather
than guess at wording, exactly like claude_agent.draft_touch's
"insufficient verified information" path returning None.

Rewritten twice on 2026-09-08. First pass fixed a mail-merge-reading
draft (raw audit string pasted into the email, no regulatory disclosure,
no named signer). Ajit's second round of feedback: it should read as
coming from an established firm, not a one-line personal note — a full
introduction (who A.M.S. is, what it does, what it can do for this
specific business), an honest answer to "how did you get my details"
(the natural first reaction to an unsolicited email), and why a
conversation rather than an email exchange is the right next step. Still
zero-cost, still fixed wording grounded only in knowledge_base and the
lead's own verified fields, still refuses to draft rather than invent.
"""
from __future__ import annotations

REQUIRED_KB = (("company_info", "overview"), ("company_info", "verified_track_record"),
               ("compliance", "regulatory_position"), ("pricing", "stage_two"))

SIGNER = "Ajit Sohal"
SIGNER_LINE = f"{SIGNER}<br>Managing Partner<br>A.M.S. Capital Management"

FOOTER = (
    "<hr>"
    "<p style=\"font-size:12px;color:#666\">A.M.S. Capital Management Holdings Ltd &middot; "
    "Registered in England and Wales, company number 17396139<br>"
    "5th Floor, 167-169 Great Portland Street, London W1W 5PF &middot; "
    "London &middot; New York &middot; Dubai &middot; Delhi &middot; Singapore<br>"
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

# Per-desk observation: what the sourcing agent actually evidenced, restated
# as one plain, specific, non-alarming sentence a person would write --
# never the raw internal signal string (that reads as an audit log, and for
# RDY-1 specifically, leading with "your accounts are overdue" reads as an
# accusation, not an opening). Each one stays strictly inside what that
# desk's gate actually checked -- see app/agents/companies_house.py's
# _desk_signal and DESK_FORMS_NOTE, and lead_generation.py's DESK_QUERIES
# for what "evidenced" means per desk.
_DESK_OBSERVATION = {
    "DEB-1": "we noted from the public record that {company} has secured lending in "
             "place, and that is often where a second opinion on terms is worth having.",
    "REF-1": "we noted {company} has had a secured facility on the register for a while "
             "now -- often the point where it is worth checking the terms are still "
             "competitive rather than assuming they are.",
    "MNA-1": "{company} is a long-established, closely-held business -- exactly the "
             "position where succession planning or bringing in a strategic partner "
             "tends to become worth a real conversation.",
    "RDY-1": "as {company} approaches its next accounts filing, this is often a natural "
             "point to take stock of capital plans for the year ahead.",
    "CAP-1": "your recent filing referenced anticipated additional capital requirements, "
             "which is exactly the situation our process is built for.",
}
_DEFAULT_OBSERVATION = "{company} came up in our research into businesses that may be " \
                        "weighing capital plans, and we wanted to introduce ourselves " \
                        "directly rather than not at all."

_DESK_QUESTION = {
    "DEB-1": "Is that facility still on the best terms available, or worth a second look?",
    "REF-1": "Worth comparing it against what is available now?",
    "MNA-1": "Is succession, or bringing in a strategic partner, something that has been "
             "on your mind?",
    "RDY-1": "Is raising or restructuring capital something worth discussing before then?",
    "CAP-1": "Is that still an open question for you?",
}
_DEFAULT_QUESTION = "Is that something worth a short conversation?"

# What we tell a recipient about how we found them -- true regardless of
# which sourcing agent produced the lead, since source_url always points at
# the real public record the company itself was found on, and every
# VERIFIED contact in this system is, by the contract in
# app/agents/contact_discovery.py and the manual verification process
# alongside it, sourced from the company's own published details, never
# purchased or guessed. Branches on source_url's domain rather than
# parsing contacts.source (an internal audit string, not client-facing
# text -- the exact anti-pattern the first rewrite of this file fixed).
def _source_description(source_url: str) -> str:
    if source_url and "sec.gov" in source_url:
        return "public filings with the U.S. Securities and Exchange Commission"
    if source_url and "company-information.service.gov.uk" in source_url:
        return "the public record at UK Companies House"
    return "public company records"


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
    observation = (_DESK_OBSERVATION.get(desk) or _DEFAULT_OBSERVATION).format(company=company)
    question = _DESK_QUESTION.get(desk) or _DEFAULT_QUESTION
    source_description = _source_description(lead.get("source_url"))

    subject = f"A.M.S. Capital Management — capital advisory for {company}"

    body_html = (
        f"<p>{greeting}</p>"

        f"<p>A.M.S. Capital Management is an independent capital advisory firm, "
        f"headquartered in London with offices in New York, Dubai, Delhi and Singapore. "
        f"Since 2022 we have advised on mandates with an aggregate value of $3.35bn, "
        f"working with a network of over 1,700 international capital partners -- "
        f"institutions, family offices, private equity firms and lenders.</p>"

        f"<p>We help owner-managed businesses raise, structure and secure capital -- from "
        f"an initial strategic assessment and investor-readiness review through to "
        f"introduction and, where a mandate proceeds, completion. In your case, "
        f"{observation}</p>"

        f"<p>The commercial structure is built so this costs you nothing to explore: our "
        f"success fee is charged to the investor, not the client, so if a raise "
        f"completes, {company} receives the agreed capital in full.</p>"

        f"<p>You may reasonably ask how we came by your details. We identified {company} "
        f"through {source_description}, and this email address from your own published "
        f"contact information -- we do not purchase contact lists.</p>"

        f"<p>We are a corporate advisory firm and are not currently authorised by the "
        f"Financial Conduct Authority -- we say that upfront because you would find it "
        f"anyway, and we work alongside appropriately authorised counterparties where "
        f"regulated activities arise.</p>"

        f"<p>Every mandate is different, and the right structure and the right investors "
        f"depend on specifics an email cannot cover -- that is why a short call, not a "
        f"long email exchange, is the fastest way to find out whether this is worth "
        f"pursuing, with no obligation either way. {question}</p>"

        f"<p>{SIGNER_LINE}</p>"
        f"{FOOTER}"
    )
    return {"subject": subject, "body_html": body_html}
