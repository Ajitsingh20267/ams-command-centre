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
 <a href="/">Home</a><a href="/leads">Leads</a><a href="/activity">Activity</a>
 <a href="/investors">Investors</a><a href="/approvals">Approvals</a><a href="/clients">Clients</a>
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
 .kanban{display:flex;gap:12px;overflow-x:auto;padding-bottom:8px;align-items:flex-start}
 .kcol{flex:0 0 220px;background:var(--card);border:1px solid var(--line);border-radius:8px;
       display:flex;flex-direction:column;max-height:75vh}
 .kcol-head{padding:10px 12px;border-bottom:1px solid var(--line);font-size:12px;
       text-transform:uppercase;letter-spacing:.03em;color:var(--muted);display:flex;
       justify-content:space-between}
 .kcol-note{font-size:10px;color:var(--muted);padding:0 12px 8px;font-style:italic}
 .kcol-body{padding:8px;overflow-y:auto;flex:1;min-height:60px}
 .kcol-body.dragover{background:rgba(127,163,217,.15)}
 .kcard{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px 10px;
       margin-bottom:8px;font-size:12px;cursor:grab}
 .kcard:active{cursor:grabbing}
 .kcard .co{font-weight:600;margin-bottom:2px}
 .kcard .meta{color:var(--muted);font-size:11px}
 .kcard .status{margin-top:4px;display:flex;gap:4px;flex-wrap:wrap}
 .pill{font-size:10px;padding:1px 6px;border-radius:8px;white-space:nowrap}
 .pill.draft{background:#dce8f5;color:#1a4d7a}
 .pill.reply-interested{background:#c9e8d1;color:#1a5c33}
 .pill.reply-other{background:#e8e0c9;color:#6b5d1a}
 .pill.reply-urgent{background:#f3c9c9;color:#8a1515}
 .pill.none{background:transparent;color:var(--muted);font-style:italic}
</style>"""

def _page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'>{STYLE}<title>{title}</title>" \
           f"</head><body>{NAV}<main>{body}</main></body></html>"


LEADS_BODY = """<h2>Pipeline</h2>
<p style="color:var(--muted);font-size:12px;margin-top:-8px">
Drag a card to move it a stage. The Client column is drop-off only — converting
a lead to a client goes through the approval gate on the Clients page, not a
casual drag, since that step creates a real client record and onboarding
checklist.</p>
<div id="leads"><div class="empty">Loading…</div></div>
<script>
// Groups the schema's fine-grained `stage` values into columns a human can
// actually scan. The underlying lead keeps its precise stage in the database
// either way — this is a view, not a data model change.
const COLUMNS = [
  ["Sourced", ["Lead", "Research"]],
  ["Qualified", ["Qualified"]],
  ["Contacted", ["Contacted"]],
  ["Conversation", ["Conversation", "Discovery", "Meeting"]],
  ["Proposal", ["Proposal", "Negotiation", "Human Approval"]],
  ["Client", ["Client", "Onboarding", "Fundraising", "Investor Matching",
              "Investor Outreach", "Investor Interest", "Due Diligence",
              "Term Sheet", "Commitment", "Funds Received", "Closed"]],
  ["Nurture", ["Nurture"]],
  ["Declined", ["Declined"]],
];
// Dropping a card into a column sets the lead's stage to this representative
// value. "Client" has none on purpose — see the note above the board.
const DROP_STAGE = {"Sourced": "Lead", "Qualified": "Qualified", "Contacted": "Contacted",
  "Conversation": "Conversation", "Proposal": "Proposal", "Nurture": "Nurture",
  "Declined": "Declined"};

let LEADS = [];

// Real, drafted-then-observed status only — never invents a "sent" or
// "contacted" state the system doesn't actually know about. A draft
// existing means exactly that: a draft exists in Outlook, waiting on you.
function statusPills(l) {
  const pills = [];
  if (l.drafts_count > 0) {
    pills.push('<span class="pill draft">' + l.drafts_count + ' draft'
              + (l.drafts_count > 1 ? 's' : '') + '</span>');
  }
  if (l.last_reply) {
    const cls = l.last_reply === 'INTERESTED' ? 'reply-interested'
              : (l.last_reply === 'ANGRY' || l.last_reply === 'INVESTOR'
                 || l.last_reply === 'UNCLASSIFIED') ? 'reply-urgent' : 'reply-other';
    pills.push('<span class="pill ' + cls + '">replied: ' + l.last_reply + '</span>');
  }
  if (!pills.length) pills.push('<span class="pill none">no contact yet</span>');
  return pills.join('');
}

function render() {
  const byCol = {};
  for (const [name] of COLUMNS) byCol[name] = [];
  for (const l of LEADS) {
    const match = COLUMNS.find(([, stages]) => stages.includes(l.stage));
    byCol[match ? match[0] : "Sourced"].push(l);
  }
  let html = '<div class="kanban">';
  for (const [name] of COLUMNS) {
    const rows = byCol[name];
    const droppable = name in DROP_STAGE;
    html += '<div class="kcol"><div class="kcol-head"><span>' + name + '</span><span>'
          + rows.length + '</span></div>';
    if (!droppable) html += '<div class="kcol-note">via Clients page</div>';
    html += '<div class="kcol-body" data-col="' + name + '" ondragover="onDragOver(event)" '
          + 'ondragleave="onDragLeave(event)" ondrop="onDrop(event)">';
    for (const l of rows) {
      html += '<div class="kcard" draggable="true" data-id="' + l.id + '" '
            + 'ondragstart="onDragStart(event)"><div class="co">' + l.company_name + '</div>'
            + '<div class="meta">' + (l.desk || '') + ' · score ' + (l.score || 0) + '</div>'
            + '<div class="status">' + statusPills(l) + '</div></div>';
    }
    html += '</div></div>';
  }
  document.getElementById('leads').innerHTML = html + '</div>';
}

function onDragStart(e) { e.dataTransfer.setData('text/plain', e.currentTarget.dataset.id); }
function onDragOver(e) {
  if (e.currentTarget.dataset.col in DROP_STAGE) {
    e.preventDefault();
    e.currentTarget.classList.add('dragover');
  }
}
function onDragLeave(e) { e.currentTarget.classList.remove('dragover'); }
function onDrop(e) {
  e.preventDefault();
  e.currentTarget.classList.remove('dragover');
  const stage = DROP_STAGE[e.currentTarget.dataset.col];
  if (!stage) return;
  const id = e.dataTransfer.getData('text/plain');
  fetch('/api/leads/' + id + '/stage', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({stage})}).then(() => {
      const lead = LEADS.find(l => l.id === id);
      if (lead) lead.stage = stage;
      render();
    });
}

fetch('/api/leads').then(r => r.json()).then(rows => {
  LEADS = rows;
  if (!rows.length) { document.getElementById('leads').innerHTML =
    '<div class="empty">No leads yet — /cron/discover-leads has not run, or found nothing.</div>';
    return; }
  render();
});
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

ACTIVITY_BODY = """<h2>Activity — every email this system has drafted or observed</h2>
<p style="color:var(--muted);font-size:12px;margin-top:-8px">
Drafts sit in Outlook until you send them — nothing here has gone out on its own.
Replies are read-only observations, classified but never auto-answered.</p>
<div class="scroll" id="activity"></div>
<script>
fetch('/api/activity').then(r => r.json()).then(rows => {
  if (!rows.length) { document.getElementById('activity').innerHTML =
    '<div class="empty">Nothing yet — connect Outlook and Anthropic, then run '
    + '/cron/draft-outreach, to see drafts appear here.</div>';
    return; }
  let h = '<table><thead><tr><th>When</th><th>Company</th><th>Direction</th>'
        + '<th>Subject</th><th>Status / classification</th><th></th></tr></thead><tbody>';
  for (const a of rows) {
    const statusText = a.direction === 'inbound' ? (a.classification || 'unclassified')
                                                    : a.status;
    h += '<tr><td>' + a.created_at + '</td><td>' + (a.company_name || '(unmatched)') + '</td>'
       + '<td>' + (a.direction === 'inbound' ? 'Reply received' : 'Draft created') + '</td>'
       + '<td>' + (a.subject || '') + '</td><td>' + statusText + '</td>'
       + '<td>' + (a.web_link ? '<a href="' + a.web_link + '" target="_blank">open</a>' : '')
       + '</td></tr>';
  }
  document.getElementById('activity').innerHTML = h + '</tbody></table>';
});
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
    router.get("/activity", response_class=HTMLResponse)(_guarded("Activity", ACTIVITY_BODY))
    router.get("/investors", response_class=HTMLResponse)(_guarded("Investors", INVESTORS_BODY))
    router.get("/approvals", response_class=HTMLResponse)(_guarded("Approvals", APPROVALS_BODY))
    router.get("/clients", response_class=HTMLResponse)(_guarded("Clients", CLIENTS_BODY))

    return router
