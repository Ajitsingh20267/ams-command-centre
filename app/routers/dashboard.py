"""The Command Centre home screen. Every number on it comes from a live
query — nothing here is a placeholder figure, and a section with no data
says so plainly rather than being hidden or invented."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import config as config_mod
from .. import db, security

DASHBOARD_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A.M.S. Command Centre</title>
<style>
 :root{--navy:#172944;--bg:#faf8f4;--card:#fff;--text:#1c1c1c;--muted:#6b6b6b;--line:#e6e2da}
 @media (prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1a1f27;--text:#eae7e0;
   --muted:#9a9a9a;--line:#2a2f38}}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,sans-serif}
 header{background:var(--navy);color:#fff;padding:14px 24px;display:flex;align-items:center;
        gap:24px;flex-wrap:wrap}
 header h1{margin:0;font-size:16px;white-space:nowrap}
 header nav a{color:#fff;opacity:.75;text-decoration:none;font-size:13px;margin-right:16px}
 header nav a:hover{opacity:1}
 header .signout{margin-left:auto;color:#fff;opacity:.7;font-size:13px;text-decoration:none}
 main{padding:20px;max-width:1100px;margin:0 auto}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;
       margin-bottom:24px}
 .stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
 .stat .n{font-size:24px;font-weight:700;color:var(--navy)}
 @media (prefers-color-scheme:dark){.stat .n{color:#7fa3d9}}
 .stat .l{font-size:12px;color:var(--muted);margin-top:2px}
 section{margin-bottom:26px}
 h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
 .scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
 table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}
 th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line)}
 th{color:var(--muted)}
 tr:last-child td{border-bottom:none}
 .empty{padding:12px;color:var(--muted);font-size:13px}
 .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px}
 .badge.required{background:#f3d9c9;color:#8a3d15}
 .badge.connected{background:#c9e8d1;color:#1a5c33}
 button{background:var(--navy);color:#fff;border:none;border-radius:6px;padding:6px 12px;
        cursor:pointer;font-size:12px}
</style></head><body>
<header><h1>A.M.S. Command Centre</h1>
<nav>
 <a href="/">Home</a><a href="/leads">Leads</a><a href="/investors">Investors</a>
 <a href="/approvals">Approvals</a><a href="/clients">Clients</a>
 <a href="/connect/microsoft">Connections</a>
</nav>
<a class="signout" href="/logout">Sign out</a></header>
<main>
 <div class="grid" id="stats"></div>
 <section><h2>Needs your approval</h2><div class="scroll" id="approvals"></div></section>
 <section><h2>Connections</h2><div class="scroll" id="connections"></div></section>
 <section><h2>Recent agent runs</h2><div class="scroll" id="runs"></div></section>
</main>
<script>
function table(headers, rows, emptyMsg) {
  if (!rows.length) return '<div class="empty">' + emptyMsg + '</div>';
  let h = '<table><thead><tr>' + headers.map(x=>'<th>'+x+'</th>').join('') + '</tr></thead><tbody>';
  for (const r of rows) h += '<tr>' + r.map(x=>'<td>'+(x??'')+'</td>').join('') + '</tr>';
  return h + '</tbody></table>';
}
fetch('/api/state').then(r => { if (!r.ok) throw new Error('status '+r.status); return r.json(); })
.then(s => {
  document.getElementById('stats').innerHTML = [
    ['Leads', s.leads_total], ['Pending approvals', s.approvals_pending],
    ['Clients', s.clients_total], ['Investor matches', s.investor_matches_total],
  ].map(([l,n]) => '<div class="stat"><div class="n">'+n+'</div><div class="l">'+l+'</div></div>').join('');

  document.getElementById('approvals').innerHTML = table(
    ['Level','What','Requested'],
    s.pending_approvals.map(a => [a.level, a.description, a.created_at]),
    'Nothing waiting on you.');

  document.getElementById('connections').innerHTML = table(
    ['Service','Status'],
    [['Microsoft Graph (Outlook)', s.ms_configured
        ? '<span class="badge connected">configured</span>'
        : '<span class="badge required">CONNECTION REQUIRED</span>'],
     ['Anthropic (drafting)', s.anthropic_configured
        ? '<span class="badge connected">configured</span>'
        : '<span class="badge required">CONNECTION REQUIRED</span>']],
    '');

  document.getElementById('runs').innerHTML = table(
    ['Agent','Started','Result','Summary'],
    s.recent_runs.map(r => [r.agent_name, r.started_at,
      r.ok === true ? 'ok' : (r.ok === false ? 'failed: '+(r.error||'') : 'running'),
      r.summary]),
    'No agent runs yet.');
}).catch(e => { document.body.insertAdjacentHTML('beforeend',
  '<div style="padding:20px;color:#b3402a">Failed to load: '+e.message+'</div>'); });
</script>
</body></html>"""


def build_router(cfg) -> APIRouter:
    router = APIRouter()
    require_api = security.require_session(cfg)
    optional = security.optional_session(cfg)

    @router.get("/", response_class=HTMLResponse)
    def home(claims=Depends(optional)):
        if claims is None:
            return RedirectResponse(url="/login", status_code=303)
        return DASHBOARD_HTML

    @router.get("/api/state")
    def state(claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("select count(*) as n from leads")
                leads_total = cur.fetchone()["n"]
                cur.execute("select count(*) as n from approvals where status='pending'")
                approvals_pending = cur.fetchone()["n"]
                cur.execute("select count(*) as n from clients")
                clients_total = cur.fetchone()["n"]
                cur.execute("select count(*) as n from investor_matches")
                investor_matches_total = cur.fetchone()["n"]
                cur.execute("select level, description, created_at from approvals "
                             "where status='pending' order by "
                             "case level when 'RED' then 0 when 'AMBER' then 1 else 2 end, "
                             "created_at desc limit 20")
                pending_approvals = cur.fetchall()
                cur.execute("select agent_name, started_at, finished_at, ok, summary, error "
                             "from agent_runs order by started_at desc limit 15")
                recent_runs = cur.fetchall()
            return {
                "leads_total": leads_total, "approvals_pending": approvals_pending,
                "clients_total": clients_total, "investor_matches_total": investor_matches_total,
                "pending_approvals": pending_approvals, "recent_runs": recent_runs,
                "ms_configured": cfg.ms_configured, "anthropic_configured": cfg.anthropic_configured,
            }
        finally:
            conn.close()

    return router
