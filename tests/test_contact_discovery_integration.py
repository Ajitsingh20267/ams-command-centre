"""Real-Postgres tests for the contact-discovery agent — same discipline as
test_companies_house_integration.py. The Companies House HTTP call
(officers lookup) is mocked; the write path against the real schema is
what's under test.

pg_conn is session-scoped and shared across every test file (see
conftest.py), and this agent's own query intentionally scans *all* UK
leads DB-wide (that's the point — it has to catch leads from other
sweeps too). So assertions here check state scoped to this file's own
companies (by company_id) rather than parsing absolute counts out of the
agent's summary string, which would be coupled to whatever other test
files happened to leave behind (e.g. test_companies_house_integration.py's
own "Harbourgate Developments Limited" fixture, which never gets a
contact and so stays a real eligible row for the rest of the suite).
Company/CH-number values here are still kept distinct from other test
files' fixtures to avoid an outright (name, country) collision.
"""
import re
from unittest import mock

from app.agents import companies_house as ch
from app.agents import contact_discovery


def _insert_uk_lead(conn, name: str, ch_number: str, score: int = 75):
    with conn.cursor() as cur:
        cur.execute(
            "insert into companies (name, country, notes) values (%s,'United Kingdom',%s) "
            "returning id",
            (name, f"Companies House {ch_number}. First seen via UK sweep."))
        company_id = cur.fetchone()["id"]
        cur.execute(
            "insert into leads (company_id, desk, geography, sector, signal, signal_date, "
            "source_url, score, band, confidence, stage) values "
            "(%s,'DEB-1','United Kingdom','Construction','Test signal','2026-08-01',"
            "'https://example.com',%s,'Priority','VERIFIED','Lead') returning id",
            (company_id, score))
        lead_id = cur.fetchone()["id"]
    return company_id, lead_id


def test_run_names_the_active_director_without_inventing_an_email(pg_conn):
    from app import config
    cfg = config.load()

    company_id, lead_id = _insert_uk_lead(pg_conn, "Kelso Fabrications Limited",
                                            "CDT900001")

    officers = {"items": [
        {"name": "OKONKWO, Adaeze", "officer_role": "director"},
        {"name": "SMITH, John", "officer_role": "secretary"},
        {"name": "RETIRED, Person", "officer_role": "director", "resigned_on": "2020-01-01"},
    ]}

    def fake_get(cfg, path, params=None):
        if path == "/company/CDT900001/officers":
            return officers
        return {"items": []}  # any other leftover eligible lead: no active officer

    with mock.patch.object(contact_discovery, "_get", side_effect=fake_get):
        summary = contact_discovery.run(pg_conn, cfg)

    assert re.search(r"[1-9]\d* named contact\(s\) recorded", summary)
    with pg_conn.cursor() as cur:
        cur.execute("select name, role, email, email_status, source from contacts "
                     "where company_id = %s", (company_id,))
        row = cur.fetchone()
    assert row["name"] == "OKONKWO, Adaeze"  # the active director, not the resigned one
    assert row["role"] == "director"
    assert row["email"] is None
    assert row["email_status"] == "UNKNOWN"  # never fabricated
    assert "Companies House" in row["source"]


def test_run_skips_leads_that_already_have_a_contact(pg_conn):
    from app import config
    cfg = config.load()

    company_id, _ = _insert_uk_lead(pg_conn, "Already Contacted Ltd", "CDT900002")
    with pg_conn.cursor() as cur:
        cur.execute("insert into contacts (company_id, name, role, email_status) "
                     "values (%s,'Existing Person','Director','UNKNOWN')", (company_id,))

    def fake_get(cfg, path, params=None):
        if path == "/company/CDT900002/officers":
            raise AssertionError("should not look up a company that already has a contact")
        return {"items": []}  # any other leftover eligible lead: no active officer

    with mock.patch.object(contact_discovery, "_get", side_effect=fake_get):
        contact_discovery.run(pg_conn, cfg)

    with pg_conn.cursor() as cur:
        cur.execute("select count(*) as n from contacts where company_id = %s", (company_id,))
        assert cur.fetchone()["n"] == 1, \
            "the pre-existing contact must be untouched — no second row, no lookup attempted"


def test_run_records_a_lookup_failure_without_aborting(pg_conn):
    from app import config
    cfg = config.load()

    flaky_id, _ = _insert_uk_lead(pg_conn, "Flaky Lookup Ltd", "CDT900003")
    reliable_id, _ = _insert_uk_lead(pg_conn, "Reliable Lookup Ltd", "CDT900004")

    def fake_get(cfg, path, params=None):
        if path == "/company/CDT900003/officers":
            raise ConnectionError("simulated network flake")
        if path == "/company/CDT900004/officers":
            return {"items": [{"name": "OKONKWO, Adaeze", "officer_role": "director"}]}
        return {"items": []}  # any other leftover eligible lead: no active officer

    with mock.patch.object(contact_discovery, "_get", side_effect=fake_get):
        contact_discovery.run(pg_conn, cfg)

    with pg_conn.cursor() as cur:
        cur.execute("select count(*) as n from contacts where company_id = %s", (flaky_id,))
        assert cur.fetchone()["n"] == 0, "a failed lookup must not write a fabricated contact"
        cur.execute("select name from contacts where company_id = %s", (reliable_id,))
        assert cur.fetchone()["name"] == "OKONKWO, Adaeze", \
            "one candidate failing must not stop the next candidate being processed"
