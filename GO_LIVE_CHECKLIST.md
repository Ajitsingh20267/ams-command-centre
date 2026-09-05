# Go live — the exact remaining steps

Everything that could be built, tested, and automated without your own
account credentials is done (see `README.md`'s status table). What's left
below needs your own sign-up on three free services — that's a hard
requirement, not a shortcut I skipped: Supabase, Render and GitHub Actions
secrets all require a human to create or authorise an account, and I should
not and cannot do that for you. Total time: **about 12 minutes.**

## ☐ 1. GitHub (in progress)
A device-login code was issued this session — check your terminal/chat for
`8D79-3FDF` and enter it at [github.com/login/device](https://github.com/login/device).
Once done, tell me and I'll create the repo and push everything automatically.

*(If that code has expired — GitHub codes last ~15 minutes — just say so and
I'll issue a fresh one.)*

## ☐ 2. Supabase — 3 minutes
1. [supabase.com](https://supabase.com) → sign up (free, GitHub login works) → **New project**
2. **Project Settings → API**: copy `Project URL`, `anon public` key, and (under **JWT Settings**) the `JWT Secret`
3. **Project Settings → Database**: copy the **Connection string** (URI, Session mode) — this is `DATABASE_URL`
4. Run the one-command setup:
   ```bash
   cd ams-command-centre
   source .venv/bin/activate
   export DATABASE_URL="<paste it>"
   python3 scripts/bootstrap_db.py --investors "/Users/ajitsohal/Downloads/AMS Capital Management/Sales Department/network/ams-capital-partners.csv"
   ```
5. **Authentication → Users → Add user** — your own email + password. This is
   how you log into the Command Centre itself.

## ☐ 3. Render — 3 minutes
1. [render.com](https://render.com) → sign up (free, GitHub login works)
2. **New → Blueprint** → connect the `ams-command-centre` repo (once step 1 is done)
3. Render reads `render.yaml` and prompts for the Supabase values from step 2 — paste them in
4. `APP_SECRET` and `CRON_SECRET` are generated for you automatically — **copy `CRON_SECRET` from the Environment tab**, you need it in step 4
5. Wait for the first deploy (~2 minutes), then open the URL Render gives you and sign in with the account from step 2.5

## ☐ 4. GitHub Actions secrets — 1 minute
In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**
- `APP_URL` = your Render URL (no trailing slash)
- `CRON_SECRET` = the value from step 3.4

Once both are set, the scheduler is live: **07:00 and 17:00 UTC, Monday to
Friday**, with zero further action. Trigger it once manually right now to
see it work rather than waiting for the clock: repo → **Actions** tab →
*A.M.S. autonomous scheduler* → **Run workflow**.

## Optional, not required to go live tonight
- **Outlook**: Azure app registration (see README §6) — until this is done,
  `/cron/draft-outreach` returns `CONNECTION REQUIRED` rather than failing
  silently, and every other job still runs normally
- **Anthropic API key**: same — drafting/classification report
  `CONNECTION REQUIRED` until it's set, nothing else is blocked
- **Investor CSV import**: already folded into step 2.4 above via `--investors`

## What happens tomorrow morning, concretely
07:00 UTC, GitHub Actions calls `/cron/discover-leads` → the SEC EDGAR agent
runs for real, scores and inserts any new leads it finds. 17:00 UTC, it
checks for replies, runs investor matching for any client marked
`fundraising`, and writes the daily report to `agent_runs`. You will have
something real to look at on the dashboard by the time you open your laptop
— not a demo, actual filings scored against actual rules.
