"""Real-Postgres proof that the RED-approval gate on client conversion
actually blocks, not just that the code reads like it should. Same check
run manually during the pre-launch review; now permanent.

Reloads app.config/app.main rather than importing normally: both build a
module-level `cfg` at import time, and if some earlier test already
imported app.main against a different (fake) DATABASE_URL, a plain import
here would silently reuse that stale, module-cached config instead of
pointing at this test's real embedded Postgres.
"""
import importlib

import jwt
from fastapi.testclient import TestClient


def _client(pg_uri):
    import app.config
    import app.main
    importlib.reload(app.config)
    importlib.reload(app.main)
    cfg = app.main.cfg
    assert cfg.database_url == pg_uri, "app.main did not pick up the real test database"

    token = jwt.encode({"sub": "u", "email": "ajit@amscapital.co.uk", "aud": "authenticated"},
                         cfg.supabase_jwt_secret, algorithm="HS256")
    c = TestClient(app.main.app)
    c.cookies.set("ams_session", token)
    return c, cfg


def test_conversion_blocked_without_approval_then_succeeds_once_approved(pg_conn, pg_uri):
    with pg_conn.cursor() as cur:
        cur.execute("insert into companies (name, country) values "
                     "('Gate Integration Test Co','UK') returning id")
        company_id = cur.fetchone()["id"]
        cur.execute("insert into opportunities (company_id) values (%s) returning id",
                     (company_id,))
        opp_id = cur.fetchone()["id"]

    client, cfg = _client(pg_uri)

    r = client.post("/api/clients/convert",
                      json={"opportunity_id": opp_id, "mandate_fee_amount": 7500})
    assert r.status_code == 403, "must block with no approval on file"

    r = client.post("/api/approvals", json={"level": "RED", "entity_type": "opportunities",
                                               "entity_id": opp_id, "description": "test"})
    approval_id = r.json()["approval_id"]

    r = client.post("/api/clients/convert",
                      json={"opportunity_id": opp_id, "mandate_fee_amount": 7500})
    assert r.status_code == 403, "a merely-pending approval must still block"

    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approved"})
    assert r.status_code == 200

    r = client.post("/api/clients/convert",
                      json={"opportunity_id": opp_id, "mandate_fee_amount": 7500})
    assert r.status_code == 200
    client_id = r.json()["client_id"]
    assert r.json()["checklist_items_created"] == 10

    r = client.get(f"/api/clients/{client_id}/onboarding")
    assert len(r.json()) == 10
