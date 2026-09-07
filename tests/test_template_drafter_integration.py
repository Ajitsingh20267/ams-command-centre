"""Real-Postgres tests for the zero-cost template drafter — proves it
reads the real knowledge_base table (not a mock of one), refuses to draft
when a required fact is missing, and never emits any of the banned
phrases or forbidden claims from brand/house_voice and
compliance/never_claim.
"""
from app.agents import template_drafter


def _seed_kb(conn, extra=None):
    rows = [
        ("company_info", "overview", "A.M.S. Capital Management Holdings Ltd — "
         "independent capital advisory. Established 2022."),
        ("company_info", "verified_track_record",
         "Aggregate transaction and development value of mandates advised since 2022: "
         "$3.35bn. This is advisory volume — NOT funds raised, managed, or AUM."),
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
FORBIDDEN_CLAIMS = ["fca", "regulated", "authorised by", "will fund", "will lend",
                      "will invest in", "guarantee"]


def test_greeting_name_normalises_companies_house_surname_first_format():
    assert template_drafter._greeting_name("MCKENZIE, George") == "George Mckenzie"
    assert template_drafter._greeting_name("OKONKWO, Adaeze Chidinma") == "Adaeze Okonkwo"
    # Not that specific two-part comma shape -- left as-is, never guessed at.
    assert template_drafter._greeting_name("Jane Doe") == "Jane Doe"
    assert template_drafter._greeting_name(None) is None


def test_draft_uses_real_kb_facts_and_the_leads_own_verified_signal(pg_conn):
    _seed_kb(pg_conn)
    lead = {"company": "Test Garage Ltd", "contact_name": "SMITH, Jane",
             "signal": "Charge registered 2024-02-14, 1 outstanding charge(s) on the register."}

    result = template_drafter.draft_touch(pg_conn, lead)

    assert result is not None
    assert "Test Garage Ltd" in result["subject"]
    text = (result["subject"] + " " + result["body_html"]).lower()
    # Companies House gives "SURNAME, Firstname" -- the greeting must turn
    # that into a normal "Firstname Surname" form, not shout the surname.
    assert "dear jane smith" in text
    assert "$3.35bn" in result["body_html"]  # the real KB figure, not invented
    assert "outstanding charge" in result["body_html"]  # the lead's own real signal


def test_draft_refuses_when_a_required_kb_fact_is_missing(pg_conn):
    # No seed at all in this test's own scope — but pg_conn is shared across
    # the whole test session, so another test file may have already seeded
    # these exact keys. Guard by deleting them first rather than assuming
    # an empty table, matching the documented shared-fixture discipline.
    with pg_conn.cursor() as cur:
        cur.execute("delete from knowledge_base where (category, key) in "
                     "(('company_info','overview'), ('company_info','verified_track_record'))")

    result = template_drafter.draft_touch(pg_conn, {"company": "Anyone Ltd"})

    assert result is None


def test_draft_never_contains_a_banned_phrase_or_forbidden_claim(pg_conn):
    _seed_kb(pg_conn)
    for lead in [
        {"company": "No Signal Ltd", "contact_name": None, "signal": None},
        {"company": "Full Info Ltd", "contact_name": "OKONKWO, Adaeze",
         "signal": "Accounts overdue (due 2026-09-30)."},
    ]:
        result = template_drafter.draft_touch(pg_conn, lead)
        assert result is not None
        text = (result["subject"] + " " + result["body_html"]).lower()
        for phrase in BANNED_PHRASES:
            assert phrase not in text, f"banned phrase {phrase!r} found in: {text}"
        for claim in FORBIDDEN_CLAIMS:
            assert claim not in text, f"forbidden claim {claim!r} found in: {text}"
