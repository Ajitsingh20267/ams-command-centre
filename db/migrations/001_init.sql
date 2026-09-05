-- A.M.S. Command Centre — initial schema, for Supabase (Postgres).
-- Run via the Supabase SQL editor, or `supabase db push` / psql against the
-- connection string in .env. Idempotent: safe to re-run (IF NOT EXISTS
-- throughout), so it can also serve as the up-to-date reference schema.

-- gen_random_uuid() is built into Postgres core since v13 (Supabase runs 15+)
-- — no extension needed, and some managed hosts restrict extensions anyway.

-- ---------------------------------------------------------------------------
-- People inside the firm. Supabase Auth owns auth.users; this is the
-- profile row every authenticated user gets, and where role lives.
-- ---------------------------------------------------------------------------
create table if not exists profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  display_name  text,
  role          text not null default 'managing_partner'
                check (role in ('managing_partner', 'team_member')),
  created_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Companies, contacts, leads
-- ---------------------------------------------------------------------------
create table if not exists companies (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  website       text,
  industry      text,
  country       text,
  size_estimate text,
  notes         text,
  created_at    timestamptz not null default now(),
  unique (name, country)
);

create table if not exists contacts (
  id            uuid primary key default gen_random_uuid(),
  company_id    uuid references companies(id) on delete cascade,
  name          text,
  role          text,
  email         text,
  phone         text,
  -- never fabricated: VERIFIED means confirmed from a named source, PATTERN
  -- means inferred and must never be drafted to, UNKNOWN is the honest default
  email_status  text not null default 'UNKNOWN'
                check (email_status in ('VERIFIED', 'PATTERN-INFERRED', 'UNKNOWN')),
  source        text,
  created_at    timestamptz not null default now()
);

create table if not exists leads (
  id                    uuid primary key default gen_random_uuid(),
  company_id            uuid references companies(id) on delete cascade,
  desk                  text,
  sector                text,
  geography             text,
  signal                text,               -- the dated, cited buying trigger
  signal_date           date,
  source_url            text,
  funding_requirement_min numeric,
  funding_requirement_max numeric,
  instrument            text,
  score                 numeric default 0,
  band                  text check (band in ('Priority', 'High', 'Medium', 'Low', 'Reject')),
  confidence            text check (confidence in ('VERIFIED', 'INFERRED', 'UNVERIFIED')),
  -- the client pipeline from the operating brief
  stage                 text not null default 'Lead'
                        check (stage in ('Lead', 'Research', 'Qualified', 'Contacted',
                          'Conversation', 'Discovery', 'Meeting', 'Proposal', 'Negotiation',
                          'Human Approval', 'Client', 'Onboarding', 'Fundraising',
                          'Investor Matching', 'Investor Outreach', 'Investor Interest',
                          'Due Diligence', 'Term Sheet', 'Commitment', 'Funds Received',
                          'Closed', 'Nurture', 'Declined')),
  owner                 text,
  next_action           text,
  next_action_date      date,
  human_approval_required boolean not null default true,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
create index if not exists idx_leads_stage on leads(stage);
create index if not exists idx_leads_company on leads(company_id);

-- ---------------------------------------------------------------------------
-- Opportunities / deals — the commercial view of a lead once it is live
-- ---------------------------------------------------------------------------
create table if not exists opportunities (
  id                 uuid primary key default gen_random_uuid(),
  lead_id            uuid references leads(id) on delete cascade,
  company_id         uuid references companies(id) on delete cascade,
  value_estimate     numeric,
  currency           text default 'GBP',
  probability        numeric check (probability between 0 and 100),
  expected_close_date date,
  next_action        text,
  next_action_date   date,
  owner              text,
  risk               text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create table if not exists deals (
  id             uuid primary key default gen_random_uuid(),
  opportunity_id uuid references opportunities(id) on delete cascade,
  value          numeric,
  currency       text default 'GBP',
  stage          text,
  close_date     date,
  won            boolean,
  lost_reason    text,
  created_at     timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Clients — once a mandate is signed. Fee is invoiced revenue only; a success
-- fee is contingent, charged to the investor, and NEVER counted here.
-- ---------------------------------------------------------------------------
create table if not exists clients (
  id                    uuid primary key default gen_random_uuid(),
  company_id            uuid references companies(id) on delete cascade,
  opportunity_id         uuid references opportunities(id),
  mandate_fee_amount     numeric,
  mandate_fee_currency   text default 'GBP',
  engagement_signed_date date,
  status                 text not null default 'onboarding'
                          check (status in ('onboarding', 'fundraising', 'in_market',
                            'completed', 'at_risk', 'lost')),
  created_at             timestamptz not null default now()
);

create table if not exists fundraising_campaigns (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid references clients(id) on delete cascade,
  target_amount     numeric,
  currency          text default 'USD',
  raised_amount     numeric default 0,
  status            text not null default 'preparing'
                    check (status in ('preparing', 'active', 'paused', 'closed')),
  start_date        date,
  target_close_date date,
  created_at        timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Onboarding — checklist items per client. Never fabricated status: a row
-- with no requested_at has not actually been asked for yet.
-- ---------------------------------------------------------------------------
create table if not exists documents (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid references clients(id) on delete cascade,
  doc_type          text not null,     -- e.g. "Business plan", "Cap table", "Director ID"
  category          text not null default 'onboarding'
                    check (category in ('onboarding', 'kyc', 'data_room')),
  status            text not null default 'not_requested'
                    check (status in ('not_requested', 'requested', 'received',
                      'verified', 'missing')),
  requested_at      timestamptz,
  received_at       timestamptz,
  verified_at       timestamptz,
  notes             text,
  created_at        timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Investors and matching — see network/INVESTOR-MATCHING.md for the scoring
-- method this feeds. Never claim a relationship beyond what nda_status and
-- last_contact actually record.
-- ---------------------------------------------------------------------------
create table if not exists investors (
  id                  uuid primary key default gen_random_uuid(),
  entity_name          text not null unique,
  type                 text,
  jurisdiction         text,
  ticket_min           numeric,
  ticket_max           numeric,
  sectors              text,
  geographies          text,
  structures           text,
  stage_preference     text,
  contact_name         text,
  role                 text,
  source_url           text,
  -- relationship status is never inferred to be stronger than this
  relationship_status  text not null default 'unverified_lead'
                       check (relationship_status in ('verified_relationship',
                         'historical_relationship', 'publicly_identified',
                         'potential_investor', 'unverified_lead')),
  eligibility_category text,
  eligibility_date     date,
  nda_status           text default 'NOT EXECUTED',
  tier                 text,
  sanctions_checked    text default 'UNSCREENED',
  last_contact         date,
  notes                text,
  created_at           timestamptz not null default now()
);

create table if not exists investor_matches (
  id                    uuid primary key default gen_random_uuid(),
  client_id             uuid references clients(id) on delete cascade,
  investor_id           uuid references investors(id) on delete cascade,
  match_score           numeric,
  sector_fit            numeric,
  geography_fit         numeric,
  ticket_fit            numeric,
  stage_fit             numeric,
  confidence_fit        numeric,
  why                   jsonb,
  concerns              jsonb,
  recommended_approach  text,
  created_at            timestamptz not null default now(),
  unique (client_id, investor_id)
);

-- ---------------------------------------------------------------------------
-- Communication — every message this system drafts or observes. Drafts only:
-- there is no "sent by the system" state, because the system never sends.
-- ---------------------------------------------------------------------------
create table if not exists emails (
  id                uuid primary key default gen_random_uuid(),
  direction         text not null check (direction in ('outbound_draft', 'inbound')),
  mailbox           text,
  to_address        text,
  from_address      text,
  subject           text,
  body_html         text,
  graph_message_id  text,
  web_link          text,
  related_lead_id   uuid references leads(id),
  related_client_id uuid references clients(id),
  classification    text,   -- for inbound: INTERESTED / QUESTION / NOT NOW / NO-REMOVE /
                             -- WRONG PERSON / INVESTOR / ANGRY / UNCLASSIFIED
  status            text not null default 'draft'
                    check (status in ('draft', 'approved_by_human', 'observed_sent',
                      'received', 'handled')),
  created_at        timestamptz not null default now()
);

create table if not exists conversations (
  id            uuid primary key default gen_random_uuid(),
  lead_id       uuid references leads(id) on delete cascade,
  channel       text default 'email',
  summary       text,
  created_at    timestamptz not null default now()
);

create table if not exists meetings (
  id              uuid primary key default gen_random_uuid(),
  company_id      uuid references companies(id),
  lead_id         uuid references leads(id),
  scheduled_for   timestamptz,
  attendees       text,
  status          text not null default 'proposed'
                  check (status in ('proposed', 'confirmed', 'completed', 'cancelled')),
  briefing_markdown text,
  outcome_notes   text,
  created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Work tracking, notes, campaigns
-- ---------------------------------------------------------------------------
create table if not exists tasks (
  id                  uuid primary key default gen_random_uuid(),
  title               text not null,
  description         text,
  owner               text,
  due_date            date,
  status              text not null default 'open'
                      check (status in ('open', 'in_progress', 'done', 'cancelled')),
  related_entity_type text,
  related_entity_id   uuid,
  created_at          timestamptz not null default now()
);

create table if not exists notes (
  id                  uuid primary key default gen_random_uuid(),
  related_entity_type text not null,
  related_entity_id   uuid not null,
  author              text,
  body                text not null,
  created_at          timestamptz not null default now()
);

create table if not exists campaigns (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  channel     text,
  status      text not null default 'draft'
              check (status in ('draft', 'active', 'paused', 'completed')),
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Approvals — the GREEN / AMBER / RED gate. Nothing AMBER or RED executes
-- without a row here moving to 'approved' with a named decided_by.
-- ---------------------------------------------------------------------------
create table if not exists approvals (
  id            uuid primary key default gen_random_uuid(),
  level         text not null check (level in ('GREEN', 'AMBER', 'RED')),
  entity_type   text not null,
  entity_id     uuid not null,
  description   text not null,
  status        text not null default 'pending'
                check (status in ('pending', 'approved', 'rejected')),
  requested_by  text not null default 'system',
  decided_by    text,
  decided_at    timestamptz,
  created_at    timestamptz not null default now()
);
create index if not exists idx_approvals_status on approvals(status);

-- ---------------------------------------------------------------------------
-- Suppression — permanent. Never delete a row from this table.
-- ---------------------------------------------------------------------------
create table if not exists suppression (
  id          uuid primary key default gen_random_uuid(),
  value       text not null unique,   -- lowercased email or bare domain
  kind        text not null check (kind in ('EMAIL', 'DOMAIN')),
  reason      text,
  actioned_by text,
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- The knowledge base — every agent's source of truth. If a fact an agent
-- needs is not here, the agent must say UNVERIFIED INFORMATION, not guess.
-- ---------------------------------------------------------------------------
create table if not exists knowledge_base (
  id          uuid primary key default gen_random_uuid(),
  category    text not null,   -- company_info, pricing, approved_claim, faq, template, compliance
  key         text not null,
  content     text not null,
  updated_at  timestamptz not null default now(),
  unique (category, key)
);

-- ---------------------------------------------------------------------------
-- OAuth connections — Microsoft Graph / Google. Tokens are stored encrypted
-- at the application layer (see app/auth.py); this table never holds a
-- plaintext secret. `status` starts CONNECTION_REQUIRED and only becomes
-- CONNECTED once a real OAuth callback has completed.
-- ---------------------------------------------------------------------------
create table if not exists oauth_connections (
  id                    uuid primary key default gen_random_uuid(),
  provider              text not null check (provider in ('microsoft', 'google')),
  mailbox               text not null,
  access_token_encrypted  text,
  refresh_token_encrypted text,
  expires_at            timestamptz,
  status                text not null default 'CONNECTION_REQUIRED'
                        check (status in ('CONNECTION_REQUIRED', 'CONNECTED', 'ERROR')),
  connected_at          timestamptz,
  last_error            text,
  created_at            timestamptz not null default now(),
  unique (provider, mailbox)
);

-- ---------------------------------------------------------------------------
-- System self-monitoring
-- ---------------------------------------------------------------------------
create table if not exists agent_runs (
  id            uuid primary key default gen_random_uuid(),
  agent_name    text not null,
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  ok            boolean,
  summary       text,
  error         text
);
create index if not exists idx_agent_runs_agent on agent_runs(agent_name, started_at desc);

create table if not exists audit_logs (
  id            uuid primary key default gen_random_uuid(),
  at            timestamptz not null default now(),
  actor         text not null,     -- 'system' | agent name | a human's identifier
  action        text not null,
  entity_type   text,
  entity_id     uuid,
  detail        jsonb
);
create index if not exists idx_audit_at on audit_logs(at desc);
