# A.M.S. Command Centre

An autonomous-workforce operating system for A.M.S. Capital Management:
lead generation, CRM, investor matching, an approval queue, and a dashboard
— running on entirely free infrastructure (Supabase, Render or Fly, GitHub
Actions), deployable from a GitHub push.

**What this does not do, on purpose: send email or book a meeting without a
human.** Every draft lands for a human to review and send; every meeting
proposal is prepared, not booked. This is not a missing feature — it is a
deliberate boundary, for two reasons stated plainly rather than buried:
A.M.S. is not FCA-authorised, and an unattended process sending unreviewed
messages under the firm's name is a real regulatory and reputational risk,
not a hypothetical one (see the company brain, `CLAUDE.md`, in the Dropbox
folder). There is no `SENDING_ENABLED` flag anywhere in this codebase and no
function that sends — see `app/agents/graph_client.py`.

---

## What's actually built, versus what needs a credential

Per the build brief this repo was built against: **no fake buttons, no fake
integrations.** Below is the honest line.

| Component | Status |
|---|---|
| Database schema (22 tables — leads, opportunities, clients, investors, investor_matches, emails, meetings, tasks, documents, approvals, audit_logs, etc.) | **Built and verified** — applied to a real local Postgres, not just reviewed by eye |
| Auth (Supabase) | **Built** — login/session verification is real code against Supabase's own GoTrue API |
| Dashboard | **Built** — every number is a live query; empty states say so rather than showing a placeholder number |
| Lead generation (SEC EDGAR feed) | **Built and verified against the live SEC API** — this found real filings (including Teamshares Inc, already a real mandate case in the Sales Department pipeline) during testing, not fixture data. Now also scores each lead (0-100, evidence-based: recency + form type + desk) |
| Draft outreach (`/cron/draft-outreach`) | **Built and verified end-to-end** against a real Postgres with a mocked Graph/Claude call: drafts a touch-one email for a scored lead with a VERIFIED contact, creates the Outlook draft, advances the lead's stage — never sends |
| Check replies (`/cron/check-replies`) | **Built and verified end-to-end**: classifies an inbound reply, matches it to a lead, advances the stage (INTERESTED) or suppresses (NO/REMOVE) or escalates to the approval queue (ANGRY/INVESTOR/UNCLASSIFIED) — never replies itself |
| Investor matching engine | **Built and verified** — ran against the real 33-row investor CSV and produced a ranked, explainable shortlist |
| Approval queue (GREEN/AMBER/RED) | **Built and verified as an actual gate** — `/api/clients/convert` is hard-blocked (403) without an *approved* RED-level row for that specific opportunity; a merely-*requested* (pending) approval still blocks it. Proven against a real Postgres, including the decision flow |
| Client conversion + onboarding checklist | **Built and verified** — converting an approved opportunity creates the client and auto-generates the real 10-item checklist (5 documents from CLAUDE.md + 5 standard KYC items) |
| Microsoft Graph draft-only client | **Built**, verified with a fake Graph client (unit-testable); **not verified against a real Azure tenant** — that needs your own app registration |
| Anthropic drafting/classification | **Built**, reads the `knowledge_base` table so it never invents a fact — **not verified against a live API key** in this session |
| GitHub Actions scheduler | **Built** — calls the deployed app's `/cron/*` endpoints on a schedule; needs `APP_URL` and `CRON_SECRET` set as repo secrets once deployed |
| Render deployment blueprint | **Built** (`render.yaml`) — not deployed in this session (needs your Render + Supabase accounts) |
| Calendar / meeting booking | **Not built.** Deliberately — see the boundary above. A future "propose times, human confirms" read-only calendar view is a reasonable next step; autonomous booking is not planned |

"CONNECTION REQUIRED" badges on the dashboard and `/connect/microsoft` mean exactly that — not a bug, a real missing credential.

---

## Activate it — the exact flow

### 1. Create a free Supabase project
[supabase.com](https://supabase.com) → New project. Free tier: 500MB database, which is
generous for this schema. Then, in the Supabase SQL Editor, run in order:
```
db/migrations/001_init.sql
db/seed_knowledge_base.sql
```
Copy four values from **Project Settings → API** and **→ Database**:
`DATABASE_URL` (Connection string, URI, Session mode), `SUPABASE_URL`,
`SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`.

Create your own login: **Authentication → Users → Add user** (email + password)
— this is the Managing Partner's account.

### 2. Push this repo to GitHub
```bash
git remote add origin <your-repo-url>
git push -u origin main
```

### 3. Deploy — Render (recommended, genuinely free)
[render.com](https://render.com) → New → Blueprint → connect the repo → Render reads
`render.yaml` and creates the web service. Fill in the Supabase values as
environment variables when prompted; `APP_SECRET` and `CRON_SECRET` are
auto-generated. Wait for the first deploy, then open the URL Render gives you.

*(Fly.io works too — `fly launch` will detect the `Dockerfile`. Any host that
runs a Dockerfile or a `uvicorn app.main:app` process works; Render is the
path with the least manual setup.)*

### 4. Open the URL → sign in
Go to `https://<your-app>.onrender.com/login` with the email/password you
created in Supabase Auth. You should see the Command Centre, at zero leads
and zero approvals — real emptiness, not a broken page.

### 5. Import the existing investor database (optional, one-shot)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="<your Supabase connection string>"
python3 scripts/import_investors.py --source "/path/to/ams-capital-partners.csv"
```

### 6. Connect Outlook (optional — needed for drafting)
Azure Portal → App registrations → New registration → API permissions → add
the **application** permission `Mail.ReadWrite` → grant admin consent →
Certificates & secrets → new client secret. **Do not add `Mail.Send`.** Put
`MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` into Render's environment
variables, redeploy, then visit `/connect/microsoft` and click **Run
connection test**.

### 7. Connect Anthropic (optional — needed for drafting/classification)
console.anthropic.com → API key → `ANTHROPIC_API_KEY` in Render's environment.

### 8. Wire up the free scheduler
In your GitHub repo: **Settings → Secrets and variables → Actions**, add:
- `APP_URL` — your Render URL, no trailing slash
- `CRON_SECRET` — the value Render generated (Render dashboard → Environment)

The workflow in `.github/workflows/scheduler.yml` now runs automatically,
07:00 and 17:00 UTC on weekdays — no further action needed. Trigger it
manually any time from the repo's **Actions** tab → *A.M.S. autonomous
scheduler* → **Run workflow**, to see it work before waiting for the clock.

### 9. Activate
That's it — there is no separate "go live" switch. The moment steps 1-3 are
done, the Command Centre is live (at zero data). Steps 5-8 progressively turn
on real lead sourcing, drafting, and investor matching. Nothing sends
externally until you, personally, open a draft and press send.

---

## Local development
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your Supabase project's values
uvicorn app.main:app --reload --port 8080
```

## Tests
```bash
python3 -m pytest tests/ -v
```
13 tests, all passing without any external service — they cover the scoring
algorithm, the lead-filtering logic, and that the app's routes exist, gate
correctly on session/cron-secret, and render without a database for the
routes that don't need one. Routes that do need a database (dashboard state,
leads, approvals, investor matching end-to-end) were verified in this build
against a real, temporary, local Postgres instance (via the `pgserver`
package) — not against Supabase itself, since that needs your own account —
and that run is not part of the checked-in suite, since it needs a component
(`pgserver`) that exists only for this kind of manual verification.

## Architecture
```
GitHub repo ──push──▶ Render (free, Docker) ──serves──▶ FastAPI app
                                                            │
                                                            ├─▶ Supabase Postgres (free)
                                                            ├─▶ Supabase Auth (free)
                                                            ├─▶ Anthropic API (paid, usage-based)
                                                            └─▶ Microsoft Graph (free API, your tenant)

GitHub Actions (free) ──cron──▶ POST /cron/discover-leads
                       ──cron──▶ POST /cron/match-investors
                       ──cron──▶ POST /cron/report
```
No long-running scheduler process, no paid worker dyno — GitHub Actions'
free scheduled workflows are the entire "always-on" part of this system.

## Repository layout
```
app/
  config.py          env loading, fails loudly at boot
  db.py               Postgres access, audit log, approval helper
  security.py         Supabase Auth session verification, token encryption
  main.py              FastAPI app, route registration, DB health check at boot
  agents/
    lead_generation.py   SEC EDGAR full-text search — free, real, verified live
    investor_matching.py  scoring engine — pure function, fully unit-tested
    graph_client.py        Microsoft Graph, draft-only, no send function exists
    claude_agent.py          drafting + reply classification, grounded in knowledge_base
  routers/
    auth_routes.py, dashboard.py, leads.py, investors.py, approvals.py,
    oauth_ms.py, cron.py
db/
  migrations/001_init.sql     the full schema
  seed_knowledge_base.sql       real, verified company facts
scripts/
  import_investors.py           one-shot CSV -> Postgres importer
tests/                            13 passing tests, no external service required
.github/workflows/
  scheduler.yml                   the free cron
  ci.yml                            runs the test suite on every push
render.yaml, Dockerfile, .env.example
```
