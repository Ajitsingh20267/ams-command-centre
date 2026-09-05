"""Microsoft Graph connection screen.

There is no user-facing OAuth consent redirect here — the app uses the
client-credentials (app-only) flow, which is authorised once in the Azure
portal by an admin, not per-user. What this screen gives you is exactly what
the build brief asked for when a credential is missing: the configuration
surface, the environment variables it reads, and a real connection test —
not a fake "connected" toggle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from .. import db, security
from ..agents.graph_client import GraphClient, GraphError

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Connect Microsoft 365</title>
<style>
 body{{font-family:-apple-system,sans-serif;background:#faf8f4;padding:32px;max-width:640px;
       margin:0 auto}}
 h1{{color:#172944;font-size:18px}}
 .badge{{padding:3px 10px;border-radius:10px;font-size:12px}}
 .required{{background:#f3d9c9;color:#8a3d15}} .ok{{background:#c9e8d1;color:#1a5c33}}
 pre{{background:#fff;border:1px solid #e6e2da;border-radius:8px;padding:12px;overflow-x:auto}}
 button{{background:#172944;color:#fff;border:none;border-radius:6px;padding:8px 16px;
         cursor:pointer}}
 #result{{margin-top:16px;white-space:pre-wrap;font-size:13px}}
</style></head><body>
<h1>Microsoft 365 / Outlook connection</h1>
<p>Status: <span class="badge {badge_class}">{status_text}</span></p>
<p>This app uses an application-only Graph connection (client-credentials flow), which is
granted once by an Azure admin, not per user. Set these in your deployment's environment
variables:</p>
<pre>MS_TENANT_ID=...
MS_CLIENT_ID=...
MS_CLIENT_SECRET=...
MS_MAILBOX=invest@amscapital.co.uk</pre>
<p>Azure setup: Portal &rarr; App registrations &rarr; New registration &rarr; API permissions
&rarr; add the <b>application</b> permission <code>Mail.ReadWrite</code> &rarr; grant admin
consent &rarr; Certificates &amp; secrets &rarr; new client secret. <b>Do not add
Mail.Send</b> — this system has no code path that sends, and withholding the permission means
a bug here cannot become an incident.</p>
<button onclick="test()">Run connection test</button>
<div id="result"></div>
<script>
function test() {{
  document.getElementById('result').textContent = 'Testing...';
  fetch('/connect/microsoft/test', {{method: 'POST'}}).then(r => r.json()).then(d => {{
    document.getElementById('result').textContent = JSON.stringify(d, null, 2);
  }});
}}
</script>
</body></html>"""


def build_router(cfg) -> APIRouter:
    router = APIRouter()
    require_api = security.require_session(cfg)

    @router.get("/connect/microsoft", response_class=HTMLResponse)
    def page(claims=Depends(require_api)):
        configured = cfg.ms_configured
        return PAGE.format(
            badge_class="ok" if configured else "required",
            status_text="environment variables set" if configured else "CONNECTION REQUIRED")

    @router.post("/connect/microsoft/test")
    def test(claims=Depends(require_api)):
        if not cfg.ms_configured:
            return {"connected": False,
                     "error": "CONNECTION REQUIRED — MS_TENANT_ID/MS_CLIENT_ID/MS_CLIENT_SECRET "
                              "are not set in this deployment's environment"}
        conn = db.connect(cfg.database_url)
        try:
            client = GraphClient(cfg, cfg.ms_mailbox)
            try:
                # A real, minimal Graph call — lists up to 1 message. If the
                # token or the permission grant is wrong, this fails here,
                # not silently at 07:00.
                client.list_recent_inbox_messages(
                    datetime.now(timezone.utc) - timedelta(days=1), top=1)
                with conn.cursor() as cur:
                    cur.execute(
                        "insert into oauth_connections (provider, mailbox, status, connected_at) "
                        "values ('microsoft', %s, 'CONNECTED', now()) "
                        "on conflict (provider, mailbox) do update set status='CONNECTED', "
                        "connected_at=now(), last_error=null", (cfg.ms_mailbox,))
                db.audit(conn, claims.get("email", "human"), "connection_test_ok",
                          "oauth_connections", None, {"provider": "microsoft"})
                return {"connected": True, "mailbox": cfg.ms_mailbox}
            except GraphError as e:
                with conn.cursor() as cur:
                    cur.execute(
                        "insert into oauth_connections (provider, mailbox, status, last_error) "
                        "values ('microsoft', %s, 'ERROR', %s) "
                        "on conflict (provider, mailbox) do update set status='ERROR', "
                        "last_error=%s", (cfg.ms_mailbox, str(e), str(e)))
                return {"connected": False, "error": str(e)}
        finally:
            conn.close()

    return router
