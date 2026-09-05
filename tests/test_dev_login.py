"""/dev-login must not exist in a production configuration — it's a
demo-only bypass of real Supabase auth, gated entirely by ENV=local."""
import importlib
import os


def _fresh_app_with_env(env_value):
    os.environ["ENV"] = env_value
    # main.py builds `cfg` and routers at import time, so a fresh import is
    # needed to see the effect of a changed ENV.
    import app.config
    import app.main
    importlib.reload(app.config)
    importlib.reload(app.main)
    return app.main.app


def test_dev_login_absent_in_production_config():
    app = _fresh_app_with_env("production")
    paths = {r.path for r in app.routes}
    assert "/dev-login" not in paths


def test_dev_login_present_only_when_env_local():
    app = _fresh_app_with_env("local")
    paths = {r.path for r in app.routes}
    assert "/dev-login" in paths
    os.environ["ENV"] = "production"  # restore default for any test run after this one


def test_dev_login_actually_creates_a_working_session():
    """Hits the real route and the real cookie it sets, rather than only
    checking the route is registered — proves the whole local-auth bypass
    works end to end without ever calling Supabase."""
    from fastapi.testclient import TestClient

    app = _fresh_app_with_env("local")
    client = TestClient(app, follow_redirects=False)

    r = client.get("/dev-login")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "ams_session" in r.cookies

    client.cookies.update(r.cookies)
    home = client.get("/")
    assert home.status_code == 200
    assert "A.M.S. Command Centre" in home.text
    os.environ["ENV"] = "production"
