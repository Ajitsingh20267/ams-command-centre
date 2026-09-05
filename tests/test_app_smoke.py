"""Smoke tests: the app wires together and serves routes that don't need a
live database. Routes that do (dashboard state, leads, approvals, cron) need
a real Supabase Postgres instance to test against — that is a genuine
prerequisite, not something this suite can fake. See README's "what was
actually verified" section.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/fake")
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "fake-anon-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "fake-jwt-secret-for-import-only")
os.environ.setdefault("APP_SECRET", "fake-app-secret-for-import-only-32-bytes")
os.environ.setdefault("CRON_SECRET", "fake-cron-secret")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402  (startup event NOT triggered without `with`)


def test_app_imports_and_registers_routes():
    paths = {r.path for r in app.routes}
    for expected in ["/healthz", "/login", "/", "/api/leads", "/api/investors",
                     "/api/approvals", "/connect/microsoft", "/cron/discover-leads",
                     "/cron/draft-outreach", "/cron/check-replies",
                     "/cron/match-investors", "/cron/report"]:
        assert expected in paths, f"missing route: {expected}"


def test_healthz_does_not_require_db_or_auth():
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_login_page_renders_without_db():
    client = TestClient(app)
    r = client.get("/login")
    assert r.status_code == 200
    assert "A.M.S. Command Centre" in r.text


def test_home_redirects_to_login_without_session():
    client = TestClient(app, follow_redirects=False)
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_api_routes_401_without_session():
    client = TestClient(app)
    for path in ["/api/leads", "/api/investors", "/api/approvals"]:
        r = client.get(path)
        assert r.status_code == 401, f"{path} should require auth"


def test_cron_routes_require_secret():
    client = TestClient(app)
    r = client.post("/cron/report")
    assert r.status_code == 401
    r2 = client.post("/cron/report", headers={"X-Cron-Secret": "wrong"})
    assert r2.status_code == 401
