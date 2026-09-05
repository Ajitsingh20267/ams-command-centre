"""Real-Postgres, end-to-end proof of the core autonomous loop: a scored
lead with a verified contact gets drafted (never sent), and a reply gets
classified and advances the lead's stage. External calls (Graph, Claude) are
mocked here — those integrations were verified separately (Graph against a
live tenant-validation call, Claude's prompt logic by inspection) — this
suite proves the database/routing logic that sits between them, which is
exactly where the real 'jurisdiction' vs 'geography' bug and the client-
conversion gate were found.

app.main builds `cfg` and every router at import time, closing over that one
cfg object — so this test sets MS_*/ANTHROPIC_API_KEY in the environment
*before* reloading app.main, rather than mutating cfg afterward (which
would not reach the routers; they already closed over the original object).
"""
import importlib
import os
from unittest import mock

from fastapi.testclient import TestClient


def _app_with_full_config(pg_uri):
    # ENV=local so the session check accepts the /dev-login sentinel below
    # instead of calling Supabase's real /auth/v1/user endpoint.
    os.environ.update({"MS_TENANT_ID": "t", "MS_CLIENT_ID": "c", "MS_CLIENT_SECRET": "s",
                         "ANTHROPIC_API_KEY": "k", "ENV": "local"})
    import app.config
    import app.main
    importlib.reload(app.config)
    importlib.reload(app.main)
    assert app.main.cfg.database_url == pg_uri
    assert app.main.cfg.ms_configured and app.main.cfg.anthropic_configured
    return app.main


def _session_client(main_module):
    import app.security
    c = TestClient(main_module.app)
    c.cookies.set("ams_session", app.security._DEV_SESSION_VALUE)
    return c


def test_draft_outreach_and_check_replies_end_to_end(pg_conn, pg_uri):
    with pg_conn.cursor() as cur:
        cur.execute("insert into companies (name, country) values "
                     "('Cron Integration Co','United States') returning id")
        company_id = cur.fetchone()["id"]
        cur.execute("insert into contacts (company_id, name, role, email, email_status) "
                     "values (%s,'Jane Doe','CFO','jane@cronintegration.example','VERIFIED')",
                     (company_id,))
        cur.execute("insert into leads (company_id, desk, sector, geography, signal, "
                     "signal_date, source_url, score, band, stage) values "
                     "(%s,'REF-1','Consumer','USA','10-Q test signal','2026-08-01',"
                     "'https://example.com',75,'High','Lead') returning id", (company_id,))
        lead_id = cur.fetchone()["id"]

    main = _app_with_full_config(pg_uri)
    client = _session_client(main)

    with mock.patch("app.agents.claude_agent.draft_touch",
                     return_value={"subject": "Test subject", "body_html": "<p>Test</p>"}), \
         mock.patch("app.agents.graph_client.GraphClient.create_draft",
                     return_value={"graph_message_id": "fake-id", "web_link": "https://fake"}):
        r = client.post("/cron/draft-outreach", headers={"X-Cron-Secret": main.cfg.cron_secret})

    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] is True and "1 drafted" in body["summary"]

    with pg_conn.cursor() as cur:
        cur.execute("select stage from leads where id=%s", (lead_id,))
        assert cur.fetchone()["stage"] == "Contacted"
        cur.execute("select direction, status, subject from emails where related_lead_id=%s",
                     (lead_id,))
        email_row = cur.fetchone()
        assert email_row["direction"] == "outbound_draft"
        assert email_row["status"] == "draft"
        assert email_row["subject"] == "Test subject"

    # Now a reply arrives from that same contact and gets classified INTERESTED.
    fake_message = {
        "internetMessageId": "<reply-1@cronintegration.example>",
        "from": {"emailAddress": {"address": "jane@cronintegration.example"}},
        "subject": "Re: your note", "receivedDateTime": "2026-09-05T12:00:00Z",
        "body": {"content": "Yes, let's talk."},
    }
    with mock.patch("app.agents.claude_agent.classify_reply", return_value="INTERESTED"), \
         mock.patch("app.agents.graph_client.GraphClient.list_recent_inbox_messages",
                     return_value=[fake_message]):
        r = client.post("/cron/check-replies", headers={"X-Cron-Secret": main.cfg.cron_secret})

    assert r.status_code == 200, r.json()
    with pg_conn.cursor() as cur:
        cur.execute("select stage from leads where id=%s", (lead_id,))
        assert cur.fetchone()["stage"] == "Conversation"
        cur.execute("select classification from emails where direction='inbound' "
                     "and related_lead_id=%s", (lead_id,))
        assert cur.fetchone()["classification"] == "INTERESTED"


def test_draft_outreach_reports_connection_required_when_unconfigured(pg_conn, pg_uri):
    # A fresh reload with the MS_*/ANTHROPIC_API_KEY env vars unset (as they
    # are by default in this test process) must report the real gap rather
    # than silently doing nothing or crashing.
    for key in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET", "ANTHROPIC_API_KEY"):
        os.environ.pop(key, None)
    os.environ["ENV"] = "local"
    import app.config
    import app.main
    importlib.reload(app.config)
    importlib.reload(app.main)
    assert not app.main.cfg.ms_configured

    client = _session_client(app.main)
    r = client.post("/cron/draft-outreach", headers={"X-Cron-Secret": app.main.cfg.cron_secret})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "CONNECTION REQUIRED" in r.json()["error"]
