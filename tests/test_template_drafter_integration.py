"""Real-Postgres tests for the zero-cost template drafter — proves it
reads the real knowledge_base table (not a mock of one), refuses to draft
when a required fact is missing, and never emits any of the banned
phrases or a false regulatory/performance claim from brand/house_voice
and compliance/never_claim.

Rewritten 2026-09-08 alongside template_drafter.py itself, after the
first batch of real drafts read as a mail-merge rather than a cold
email — see that module's docstring for what changed and why.
"""
from app.agents import template_drafter


def _seed_kb(conn, extra=None):
    rows = [
        ("company_info", "overview", "A.M.S. Capital Management Holdings Ltd — "
         "independent capital advisory. Established 2022."),
        ("company_info", "verified_track_record",
         "Aggregate transaction and development value of mandates advised since 2022: "
         "$3.35bn. This is advisory volume — NOT funds raised, managed, or AUM."),
        ("compliance", "regulatory_position",
         "A.M.S. is not currently authorised by the Financial Conduct Authority."),
        ("pricing", "stage_two",
         "Success fee charged to the investor, never the client, on completion."),
    ]
    if extra:
        rows.extend(extra)
    with conn.cursor() as cur:
        for category, key, content in rows:
            cur.execute("insert into knowledge_base (category, key, content) values (%s,%s,%s) "
                         "on conflict (category, key) do update set content = excluded.content",
                         (category, key, content))


BANNED_PHRASES = ["reach out", "circle back", "touch base", "quick question",
                    "i hope this email finds you well", "just following up", "!"]
# Claims that would be false or non-compliant if made AFFIRMATIVELY (compliance/
# never_claim: never claim A.M.S. is regulated/authorised/will fund/lend/invest,
# never guarantee an outcome). The firm's own approved reference sequence
# (Sales Department/outreach/sequences/maddox-planning-sequence.md) DOES say
# "not authorised by the Financial Conduct Authority" -- that's a required
# honest disclosure, not a forbidden claim -- so this checks for the false
# form specifically rather than banning the words outright.
FORBIDDEN_FALSE_CLAIMS = ["a.m.s. is regulated", "a.m.s. is authorised", "we are regulated",
                            "will fund", "will lend", "will invest in", "guarantee"]
REQUIRED_DISCLOSURE = "not currently authorised by the financial conduct authority"


def test_greeting_name_normalises_companies_house_surname_first_format():
    assert template_drafter._greeting_name("MCKENZIE, George") == "George Mckenzie"
    assert template_drafter._greeting_name("OKONKWO, Adaeze Chidinma") == "Adaeze Okonkwo"
    # Not that specific two-part comma shape -- left as-is, never guessed at.
    assert template_drafter._greeting_name("Jane Doe") == "Jane Doe"
    assert template_drafter._greeting_name(None) is None


def test_draft_uses_real_kb_facts_and_a_desk_specific_real_observation(pg_conn):
    _seed_kb(pg_conn)
    lead = {"company": "Test Garage Ltd", "contact_name": "SMITH, Jane", "desk": "DEB-1",
             "signal": "Charge registered 2024-02-14, 1 outstanding charge(s) on the register."}

    result = template_drafter.draft_touch(pg_conn, lead)

    assert result is not None
    assert "Test Garage Ltd" in result["subject"]
    text = (result["subject"] + " " + result["body_html"]).lower()
    # Companies House gives "SURNAME, Firstname" -- the greeting must be a
    # natural first-name opener, not the shouted-surname form, and not the
    # internal audit string pasted verbatim into client-facing copy.
    assert "dear jane" in text
    assert "charge registered 2024-02-14" not in text
    assert "secured lending in place" in text  # the DEB-1 desk's real, translated hook
    assert "$3.35bn" in result["body_html"]  # the real KB figure, not invented
    assert "ajit sohal" in text  # signed by a real named human, not just the firm


def test_draft_falls_back_to_a_generic_real_opener_when_desk_is_unknown(pg_conn):
    _seed_kb(pg_conn)
    result = template_drafter.draft_touch(
        pg_conn, {"company": "No Desk Ltd", "contact_name": None, "desk": None, "signal": None})

    assert result is not None
    assert "No Desk Ltd" in result["body_html"]


def test_draft_refuses_when_a_required_kb_fact_is_missing(pg_conn):
    # No seed at all in this test's own scope — but pg_conn is shared across
    # the whole test session, so another test file may have already seeded
    # these exact keys. Guard by deleting them first rather than assuming
    # an empty table, matching the documented shared-fixture discipline.
    with pg_conn.cursor() as cur:
        cur.execute("delete from knowledge_base where (category, key) in "
                     "(('company_info','overview'), ('company_info','verified_track_record'), "
                     "('compliance','regulatory_position'), ('pricing','stage_two'))")

    result = template_drafter.draft_touch(pg_conn, {"company": "Anyone Ltd"})

    assert result is None


def test_draft_discloses_regulatory_position_and_never_makes_a_false_claim(pg_conn):
    _seed_kb(pg_conn)
    for lead in [
        {"company": "No Signal Ltd", "contact_name": None, "desk": None, "signal": None},
        {"company": "Full Info Ltd", "contact_name": "OKONKWO, Adaeze", "desk": "RDY-1",
         "signal": "Accounts overdue (due 2026-09-30)."},
    ]:
        result = template_drafter.draft_touch(pg_conn, lead)
        assert result is not None
        text = (result["subject"] + " " + result["body_html"]).lower()
        for phrase in BANNED_PHRASES:
            assert phrase not in text, f"banned phrase {phrase!r} found in: {text}"
        for claim in FORBIDDEN_FALSE_CLAIMS:
            assert claim not in text, f"forbidden claim {claim!r} found in: {text}"
        # RDY-1's real signal is "accounts overdue" -- the client-facing copy
        # must never say that word to the recipient (reads as an accusation),
        # even though it's exactly what the internal signal says.
        assert "overdue" not in text
        assert REQUIRED_DISCLOSURE in text
