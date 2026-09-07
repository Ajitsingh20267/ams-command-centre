"""Real-Postgres tests for the sole-trader discovery agent (FSA Food
Hygiene Ratings). Same discipline as the other agent integration tests:
the HTTP call is mocked, the write path against the real schema is what's
under test — this is exactly the kind of code where a wrong column name
or a broken cursor hides until it's run for real.
"""
from unittest import mock

from app.agents import sole_trader_discovery as std


def _page(items, total_pages=1):
    return {"establishments": items,
            "meta": {"totalCount": len(items) * total_pages, "totalPages": total_pages}}


TAKEAWAY = {"FHRSID": 111, "BusinessName": "Test Takeaway Ltd",
             "BusinessType": "Takeaway/sandwich shop",
             "AddressLine1": "1 High Street", "AddressLine2": "Testville",
             "AddressLine3": "", "AddressLine4": "", "PostCode": "TE1 1ST",
             "Phone": "01234 567890", "LocalAuthorityName": "Test Council",
             "RatingValue": "5"}


def test_run_inserts_a_real_sole_trader_lead_unscored(pg_conn):
    from app import config
    cfg = config.load()

    def fake_get(cfg, params):
        if params["businessTypeId"] == 7844:
            return _page([TAKEAWAY])
        return _page([])

    with mock.patch.object(std, "_get", side_effect=fake_get):
        summary = std.run(pg_conn, cfg)

    assert "1 inserted" in summary
    with pg_conn.cursor() as cur:
        cur.execute("select * from sole_trader_leads where source_id = '111'")
        row = cur.fetchone()
    assert row["business_name"] == "Test Takeaway Ltd"
    assert row["source"] == "FSA Food Hygiene Ratings"
    assert row["postcode"] == "TE1 1ST"
    assert row["phone"] == "01234 567890"
    assert row["contacted_at"] is None
    # no score/band/stage columns exist on this table at all -- there is
    # nothing to assert their absence of, which is exactly the point:
    # this table structurally cannot carry fabricated evidence.
    with pg_conn.cursor() as cur:
        cur.execute("select column_name from information_schema.columns "
                     "where table_name = 'sole_trader_leads'")
        cols = {r["column_name"] for r in cur.fetchall()}
    assert "score" not in cols and "band" not in cols


def test_run_is_idempotent_and_advances_the_cursor(pg_conn):
    from app import config
    cfg = config.load()

    calls = []
    fixture = {**TAKEAWAY, "FHRSID": 333, "BusinessName": "Idempotency Test Takeaway"}

    def fake_get(cfg, params):
        calls.append((params["businessTypeId"], params["pageNumber"]))
        if params["businessTypeId"] == 7844:
            return _page([fixture], total_pages=5)
        return _page([])

    with mock.patch.object(std, "_get", side_effect=fake_get):
        s1 = std.run(pg_conn, cfg)
        s2 = std.run(pg_conn, cfg)

    assert "1 inserted" in s1
    assert "1 already on file" in s2
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) as n from sole_trader_leads where source_id = '333'")
        assert cur.fetchone()["n"] == 1

    takeaway_pages = [p for (t, p) in calls if t == 7844]
    assert takeaway_pages == [1, 2], "second run must fetch the next page, not re-fetch page 1"


def test_run_records_a_page_fetch_failure_without_aborting(pg_conn):
    from app import config
    cfg = config.load()

    def fake_get(cfg, params):
        if params["businessTypeId"] == 7844:
            raise ConnectionError("simulated network flake")
        if params["businessTypeId"] == 1:
            return _page([{**TAKEAWAY, "FHRSID": 222, "BusinessName": "Test Cafe Ltd"}])
        return _page([])

    with mock.patch.object(std, "_get", side_effect=fake_get):
        summary = std.run(pg_conn, cfg)

    assert "1 page fetch failure(s)" in summary
    with pg_conn.cursor() as cur:
        cur.execute("select count(*) as n from sole_trader_leads where source_id = '222'")
        assert cur.fetchone()["n"] == 1, \
            "one business type's page failing must not stop the others being processed"
