"""HTML pages for leads, investors, approvals and clients. Each page is a
thin shell that fetches the existing JSON APIs and renders real data — same
rule as the dashboard: an empty section says so, nothing is a placeholder.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import security

NAV = """<header><h1>A.M.S. Command Centre</h1>
<nav>
 <a href="/">Home</a><a href="/leads">Leads</a><a href="/investors">Investors</a>
 <a href="/approvals">Approvals</a><a href="/clients">Clients</a>
 <a href="/connect/microsoft">Connections</a>
</nav>
<a class="signout" href="/logout">Sign out</a></header>"""

STYLE = """<style>
 :root{--navy:#172944;--bg:#faf8f4;--card:#fff;--text:#1c1c1c;--muted:#6b6b6b;--line:#e6e2da}
 @media (prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1a1f27;--text:#eae7e0;
   --muted:#9a9a9a;--line:#2a2f38}}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,sans-serif}
 header{background:var(--navy);color:#fff;padding:14px 24px;display:flex;align-items:center;
        gap:24px;flex-wrap:wrap}
 header h1{margin:0;font-size:16px;white-space:nowrap}
 nav a{color:#fff;opacity:.75;text-decoration:none;font-size:13px;margin-right:16px}
 nav a:hover{opacity:1}
 .signout{margin-left:auto;color:#fff;opacity:.7;font-size:13px;text-decoration:none}
 main{padding:20px;max-width:1200px;margin:0 auto}
 h2{font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
 .scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin-bottom:20px}
 table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}
 th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line)}
 th{color:var(--muted)}
 tr:last-child td{border-bottom:none}
 .empty{padding:14px;color:var(--muted);font-size:13px}
 button,select{background:var(--navy);color:#fff;border:none;border-radius:6px;
        padding:5px 10px;cursor:pointer;font-size:12px}
 button.reject{background:#8a3d15}
 .badge{padding:2px 8px;border-radius:10px;font-size:11px}
 .RED{background:#f3c9c9;color:#8a1515} .AMBER{background:#f3e2c9;color:#8a5d15}
 .GREEN{background:#c9e8d1;color:#1a5c33}
 select{color:#fff}
 form.inline{display:flex;gap:8px;align-items:center;background:var(--card);
        border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:20px}
 form.inline input{padding:6px 8px;border:1px solid var(--line);border-radius:6px}
</style>"""

STAGE_OPTIONS = ["Lead", "Research", "Qualified", "Contacted", "Conversation", "Discovery",
                  "Meeting", "Proposal", "Negotiation", "Human Approval", "Client", "Onboarding",
                  "Fundraising", "Investor Matching", "Investor Outreach", "Investor Interest",
                  "Due Diligence", "Term Sheet", "Commitment", "Funds Received", "Closed",
                  "Nurture", "Declined"]


def _page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'>{STYLE}<title>{title}</title>" \
           f"</head><body>{NAV}<main>{body}</main></body></html>"


LEADS_BODY = """<h2>Leads</h2><div class="scroll" id="leads"></div>
<script>
const stages = """ + str(STAGE_OPTIONS).replace("'", '"') + """;
function opts(sel){return stages.map(s => '<option'+(s===sel?' selected':'')+'>'+s+'</option>').join('');}
fetch('/api/leads').then(r=>r.json()).then(rows => {
  if (!rows.length) { document.getElementById('leads').innerHTML =
    '<div class="empty">No leads yet — /cron/discover-leads has not run, or found nothing.</div>';
    return; }
  let h = '<table><thead><tr><th>Company</th><th>Desk</th><th>Score</th><th>Band</th>'
        + '<th>Signal</th><th>Stage</th><th></th></tr></thead><tbody>';
  for (const l of rows) {
    h += '<tr><td>'+l.company_name+'</td><td>'+(l.desk||'')+'</td><td>'+(l.score||0)+'</td>'
       + '<td>'+(l.band||'')+'</td><td>'+(l.signal||'').slice(0,60)+'</td>'
       + '<td><select onchange="setStage(\\''+l.id+'\\', this.value)">'+opts(l.stage)+'</select></td>'
       + '<td><a href="'+(l.source_url||'#')+'" target="_blank">source</a></td></tr>';
  }
  document.getElementById('leads').innerHTML = h + '</tbody></table>';
});
function setStage(id, stage) {
  fetch('/api/leads/'+id+'/stage', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({stage})}).then(() => location.reload());
}
</script>"""

INVESTORS_BODY = """<h2>Investor database</h2><div class="scroll" id="investors"></div>
<script>
fetch('/api/investors').then(r=>r.json()).then(rows => {
  if (!rows.length) { document.getElementById('investors').innerHTML =
    '<div class="empty">No investors imported yet — run scripts/import_investors.py.</div>';
    return; }
  let h = '<table><thead><tr><th>Entity</th><th>Type</th><th>Jurisdiction</th><th>Tier</th>'
        + '<th>Relationship</th><th>Sanctions</th></tr></thead><tbody>';
  for (const i of rows) {
    h += '<tr><td>'+i.entity_name+'</td><td>'+(i.type||'')+'</td><td>'+(i.jurisdiction||'')+'</td>'
       + '<td>'+(i.tier||'')+'</td><td>'+(i.relationship_status||'')+'</td>'
       + '<td>'+(i.sanctions_checked||'')+'</td></tr>';
  }
  document.getElementById('investors').innerHTML = h + '</tbody></table>';
});
</script>"""

APPROVALS_BODY = """<h2>Needs your decision</h2><div class="scroll" id="approvals"></div>
<script>
fetch('/api/approvals?status=pending').then(r=>r.json()).then(rows => {
  if (!rows.length) { document.getElementById('approvals').innerHTML =
    '<div class="empty">Nothing pending.</div>'; return; }
  let h = '<table><thead><tr><th>Level</th><th>What</th><th>Requested by</th><th>When</th>'
        + '<th></th></tr></thead><tbody>';
  for (const a of rows) {
    h += '<tr><td><span class="badge '+a.level+'">'+a.level+'</span></td><td>'+a.description+'</td>'
       + '<td>'+a.requested_by+'</td><td>'+a.created_at+'</td>'
       + '<td><button onclick="decide(\\''+a.id+'\\',\\'approved\\')">Approve</button> '
       + '<button class="reject" onclick="decide(\\''+a.id+'\\',\\'rejected\\')">Reject</button></td></tr>';
  }
  document.getElementById('approvals').innerHTML = h + '</tbody></table>';
});
function decide(id, decision) {
  fetch('/api/approvals/'+id+'/decide', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({decision})}).then(() => location.reload());
}
</script>"""

CLIENTS_BODY = """<h2>Clients</h2><div class="scroll" id="clients"></div>
<h2>Convert an approved opportunity</h2>
<form class="inline" onsubmit="return convert(event)">
  <input name="opportunity_id" placeholder="opportunity id" required style="width:280px">
  <input name="fee" placeholder="mandate fee amount" type="number" required style="width:160px">
  <button type="submit">Convert to client</button>
</form>
<div id="convertResult" class="empty"></div>
<script>
fetch('/api/clients').then(r=>r.json()).then(rows => {
  if (!rows.length) { document.getElementById('clients').innerHTML =
    '<div class="empty">No clients yet.</div>'; return; }
  let h = '<table><thead><tr><th>Company</th><th>Status</th><th>Fee</th><th>Signed</th>'
        + '<th>Onboarding</th></tr></thead><tbody>';
  for (const c of rows) {
    h += '<tr><td>'+c.company_name+'</td><td>'+c.status+'</td>'
       + '<td>'+(c.mandate_fee_amount||'')+' '+(c.mandate_fee_currency||'')+'</td>'
       + '<td>'+(c.engagement_signed_date||'')+'</td>'
       + '<td><a href="#" onclick="showChecklist(\\''+c.id+'\\');return false;">view checklist</a></td></tr>';
  }
  document.getElementById('clients').innerHTML = h + '</tbody></table>';
});
function showChecklist(id) {
  fetch('/api/clients/'+id+'/onboarding').then(r=>r.json()).then(items => {
    alert(items.map(i => '['+i.status+'] '+i.category+': '+i.doc_type).join('\\n'));
  });
}
function convert(e) {
  e.preventDefault();
  const f = new FormData(e.target);
  fetch('/api/clients/convert', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({opportunity_id: f.get('opportunity_id'),
                            mandate_fee_amount: parseFloat(f.get('fee'))})})
    .then(async r => ({status: r.status, body: await r.json()}))
    .then(({status, body}) => {
      document.getElementById('convertResult').textContent = JSON.stringify(body);
      if (status === 200) location.reload();
    });
  return false;
}
</script>"""


def build_router(cfg) -> APIRouter:
    router = APIRouter()
    optional = security.optional_session(cfg)

    def _guarded(title, body_html):
        def _route(claims=Depends(optional)):
            if claims is None:
                return RedirectResponse(url="/login", status_code=303)
            return _page(title, body_html)
        return _route

    router.get("/leads", response_class=HTMLResponse)(_guarded("Leads", LEADS_BODY))
    router.get("/investors", response_class=HTMLResponse)(_guarded("Investors", INVESTORS_BODY))
    router.get("/approvals", response_class=HTMLResponse)(_guarded("Approvals", APPROVALS_BODY))
    router.get("/clients", response_class=HTMLResponse)(_guarded("Clients", CLIENTS_BODY))

    return router
