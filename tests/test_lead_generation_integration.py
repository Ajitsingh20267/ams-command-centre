"""Real-Postgres tests for the write path in lead_generation.run_sweep.
This is exactly the test that would have caught the 'jurisdiction' vs
'geography' column-name bug found on 2026-09-05 — a unit test of the
filtering logic alone (test_lead_generation.py) can't, because the bug was
in the raw SQL string, never exercised until a live run against a real
schema. search() itself (the live SEC EDGAR call) is mocked here for CI
speed and determinism; it was verified separately against the real API.
"""
from unittest import mock

from app.agents import lead_generation

FAKE_HIT = {"cik": "1234567", "name": "Fixture Test Co", "form": "10-Q",
             "filed": "2026-08-01", "adsh": "0001234567-26-000001",
             "phrase": '"matures within the next twelve months"'}


def test_run_sweep_inserts_a_real_row(pg_conn):
    from app import config
    cfg = config.load()

    with mock.patch.object(lead_generation, "search", return_value=[FAKE_HIT]):
        summary = lead_generation.run_sweep(pg_conn, cfg, desk="REF-1", days=30, limit=10)

    assert "1 inserted" in summary
    with pg_conn.cursor() as cur:
        cur.execute("select l.*, c.name as company_name from leads l "
                     "join companies c on c.id = l.company_id "
                     "where c.name = 'Fixture Test Co'")
        row = cur.fetchone()
    assert row is not None
    assert row["desk"] == "REF-1"
    assert row["geography"] == "United States"
    assert row["score"] is not None and row["band"] is not None
    assert "matures within the next twelve months" in row["signal"]


def test_run_sweep_is_idempotent_on_rerun(pg_conn):
    from app import config
    cfg = config.load()
    hit = {**FAKE_HIT, "cik": "7654321", "name": "Rerun Test Co"}

    with mock.patch.object(lead_generation, "search", return_value=[hit]):
        s1 = lead_generation.run_sweep(pg_conn, cfg, desk="REF-1", days=30, limit=10)
        s2 = lead_generation.run_sweep(pg_conn, cfg, desk="REF-1", days=30, limit=10)

    assert "1 inserted" in s1
    assert "already on file" in s2
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) as n from companies where name = 'Rerun Test Co'")
        assert cur.fetchone()["n"] == 1


def test_run_sweep_rejects_distress_language(pg_conn):
    from app import config
    cfg = config.load()
    hit = {**FAKE_HIT, "cik": "9999999", "name": "Distressed Test Co",
           "phrase": "substantial doubt about the Company's ability to continue"}

    with mock.patch.object(lead_generation, "search", return_value=[hit]):
        summary = lead_generation.run_sweep(pg_conn, cfg, desk="REF-1", days=30, limit=10)

    assert "0 inserted" in summary
    assert "rejected (distress)" in summary
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) as n from companies where name = 'Distressed Test Co'")
        assert cur.fetchone()["n"] == 0
