"""Real-Postgres tests for the Companies House (UK) lead agent — same
discipline as test_lead_generation_integration.py, and for the same reason:
the write path (raw SQL against the real schema) is exactly where a typo
like the 'jurisdiction'/'geography' bug hides. The Companies House HTTP
calls are mocked (`_get`); the reference implementation's HTTP layer isn't
what's under test here.
"""
from unittest import mock

from app.agents import companies_house as ch

ACTIVE_OWNER_MANAGED_WITH_CHARGE = {
    "company_name": "Harbourgate Developments Limited",
    "company_status": "active",
    "date_of_creation": "2009-03-11",
    "sic_codes": ["41100"],
    "accounts": {"last_accounts": {"type": "full", "made_up_to": "2025-12-31"},
                  "next_accounts": {"due_on": "2026-09-30", "overdue": False}},
}
INSOLVENT = {
    "company_name": "Distressed Print Group Limited",
    "company_status": "active",
    "company_status_detail": "insolvency-proceedings",
    "date_of_creation": "2004-06-30",
}
DORMANT = {
    "company_name": "Kestrel Holdings (No 4) Limited",
    "company_status": "active",
    "date_of_creation": "2021-01-05",
    "accounts": {"last_accounts": {"type": "dormant", "made_up_to": "2025-12-31"}},
}

CANDIDATES = {"items": [{"company_number": "00000001"}, {"company_number": "00000002"},
                          {"company_number": "00000003"}]}


def fake_get(cfg, path, params=None):
    if path == "/advanced-search/companies":
        return CANDIDATES
    if path == "/company/00000001":
        return ACTIVE_OWNER_MANAGED_WITH_CHARGE
    if path == "/company/00000001/officers":
        return {"items": [{"name": "OKONKWO, Adaeze"}, {"name": "OKONKWO, Daniel"}]}
    if path == "/company/00000001/persons-with-significant-control":
        return {"items": [{"kind": "individual-person-with-significant-control"}]}
    if path == "/company/00000001/charges":
        return {"items": [{"status": "outstanding", "created_on": "2024-02-14",
                              "particulars": "First legal charge"}]}
    if path == "/company/00000002":
        return INSOLVENT
    if path == "/company/00000003":
        return DORMANT
    return None


def test_run_sweep_inserts_the_real_gated_lead(pg_conn):
    from app import config
    cfg = config.load()

    with mock.patch.object(ch, "_get", side_effect=fake_get), \
         mock.patch.object(ch.time, "sleep"):
        summary = ch.run_sweep(pg_conn, cfg, limit=10)

    assert "1 inserted" in summary
    assert "rejected (distress/insolvency)" in summary
    assert "rejected (insufficient evidence)" in summary

    with pg_conn.cursor() as cur:
        cur.execute("select l.*, c.name as company_name, c.country from leads l "
                     "join companies c on c.id = l.company_id "
                     "where c.name = 'Harbourgate Developments Limited'")
        row = cur.fetchone()
    assert row is not None
    assert row["country"] == "United Kingdom"
    assert row["geography"] == "United Kingdom"
    assert row["desk"] == "DEB-1"
    assert row["confidence"] == "VERIFIED"
    assert row["score"] >= 75  # revenue + owner-managed evidence, both present

    with pg_conn.cursor() as cur:
        cur.execute("select count(*) as n from companies where name in "
                     "('Distressed Print Group Limited', 'Kestrel Holdings (No 4) Limited')")
        assert cur.fetchone()["n"] == 0, "distressed/dormant companies must never be inserted"


def test_run_sweep_is_idempotent(pg_conn):
    from app import config
    cfg = config.load()

    with mock.patch.object(ch, "_get", side_effect=fake_get), \
         mock.patch.object(ch.time, "sleep"):
        ch.run_sweep(pg_conn, cfg, limit=10)
        s2 = ch.run_sweep(pg_conn, cfg, limit=10)

    assert "already on file" in s2
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) as n from companies where name = "
                     "'Harbourgate Developments Limited'")
        assert cur.fetchone()["n"] == 1
