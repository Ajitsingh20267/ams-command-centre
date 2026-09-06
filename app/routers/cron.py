"""Endpoints GitHub Actions calls on a schedule (see
.github/workflows/scheduler.yml). This is the free replacement for a
long-running scheduler process: nothing runs unless one of these routes is
hit, and each call does exactly one unit of work and returns.

Authorised by a shared secret header, never by the session cookie — GitHub
Actions has no Supabase login. Rotate CRON_SECRET if it ever leaks into a
public log.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException

from .. import db
from ..agents import claude_agent, companies_house, lead_generation
from ..agents.graph_client import GraphClient


def build_router(cfg) -> APIRouter:
    router = APIRouter()

    def _check(x_cron_secret: str = Header(default="")):
        if x_cron_secret != cfg.cron_secret:
            raise HTTPException(status_code=401, detail="bad or missing X-Cron-Secret")

    @router.post("/cron/discover-leads")
    def discover_leads(x_cron_secret: str = Header(default="")):
        _check(x_cron_secret)
        conn = db.connect(cfg.database_url)
        try:
            summaries = []
            for desk in lead_generation.DESK_QUERIES:
                try:
                    summaries.append(lead_generation.run_sweep(conn, cfg, desk=desk))
                except Exception as e:
                    summaries.append(f"desk {desk}: FAILED — {e}")
            return {"ok": True, "summaries": summaries}
        finally:
            conn.close()

    @router.post("/cron/discover-leads-uk")
    def discover_leads_uk(x_cron_secret: str = Header(default="")):
        _check(x_cron_secret)
        if not cfg.companies_house_configured:
            return {"ok": False, "error": "CONNECTION REQUIRED: COMPANIES_HOUSE_KEY not "
                                            "configured — register free at "
                                            "developer.company-information.service.gov.uk"}
        conn = db.connect(cfg.database_url)
        try:
            summary = companies_house.run_sweep(conn, cfg)
            return {"ok": True, "summary": summary}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            conn.close()

    @router.post("/cron/match-investors")
    def match_investors(x_cron_secret: str = Header(default="")):
        _check(x_cron_secret)
        from ..agents.investor_matching import top_matches
        import json as _json

        conn = db.connect(cfg.database_url)
        run_id = db.start_run(conn, "match_investors")
        try:
            with conn.cursor() as cur:
                cur.execute("select id from clients where status='fundraising'")
                client_ids = [r["id"] for r in cur.fetchall()]
                cur.execute("select * from investors")
                investors = [dict(r) for r in cur.fetchall()]

            total_matches = 0
            for client_id in client_ids:
                with conn.cursor() as cur:
                    cur.execute(
                        "select c.id as client_id, l.sector, l.geography, "
                        "l.funding_requirement_min, l.funding_requirement_max, l.instrument, "
                        "l.stage from clients c "
                        "left join opportunities o on o.id = c.opportunity_id "
                        "left join leads l on l.id = o.lead_id where c.id=%s", (client_id,))
                    client_row = cur.fetchone()
                if client_row is None:
                    continue
                matches = top_matches(dict(client_row), investors, top_n=10)
                with db.tx(conn) as cur:
                    cur.execute("delete from investor_matches where client_id=%s", (client_id,))
                    for m in matches:
                        cur.execute(
                            "insert into investor_matches (client_id, investor_id, match_score, "
                            "sector_fit, geography_fit, ticket_fit, stage_fit, confidence_fit, "
                            "why, concerns, recommended_approach) values "
                            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (client_id, m["investor_id"], m["match_score"], m["sector_fit"],
                             m["geography_fit"], m["ticket_fit"], m["stage_fit"],
                             m["confidence_fit"], _json.dumps(m["why"]),
                             _json.dumps(m["concerns"]), m["recommended_approach"]))
                total_matches += len(matches)

            summary = f"{len(client_ids)} fundraising client(s), {total_matches} matches written"
            db.finish_run(conn, run_id, True, summary)
            return {"ok": True, "summary": summary}
        except Exception as e:
            db.finish_run(conn, run_id, False, "", str(e))
            raise
        finally:
            conn.close()

    @router.post("/cron/draft-outreach")
    def draft_outreach(x_cron_secret: str = Header(default="")):
        """Drafts touch-one emails for leads with a VERIFIED contact. Writes
        to `emails` with status='draft' and creates the actual Outlook draft
        via Graph — never sends. If MS_* or ANTHROPIC_API_KEY are not
        configured, returns CONNECTION REQUIRED rather than pretending."""
        _check(x_cron_secret)
        if not cfg.ms_configured or not cfg.anthropic_configured:
            missing = [n for n, ok in [("Microsoft Graph", cfg.ms_configured),
                                         ("Anthropic", cfg.anthropic_configured)] if not ok]
            return {"ok": False, "error": f"CONNECTION REQUIRED: {', '.join(missing)} not "
                                            f"configured — see /connect/microsoft and .env.example"}

        conn = db.connect(cfg.database_url)
        run_id = db.start_run(conn, "draft_outreach")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select l.id as lead_id, l.company_id, l.desk, l.sector, l.geography, "
                    "l.signal, l.signal_date, l.source_url, l.instrument, co.name as company, "
                    "ct.name as contact_name, ct.role as contact_role, ct.email as contact_email "
                    "from leads l "
                    "join companies co on co.id = l.company_id "
                    "join contacts ct on ct.company_id = l.company_id "
                    "where l.stage = 'Lead' and l.score >= 60 and ct.email_status = 'VERIFIED' "
                    "and not exists (select 1 from emails e where e.related_lead_id = l.id "
                    "and e.direction = 'outbound_draft') limit 20")
                candidates = cur.fetchall()

            graph_client = GraphClient(cfg, cfg.ms_mailbox)
            drafted, skipped_suppressed, failed = 0, 0, 0
            for lead in candidates:
                if db.is_suppressed(conn, lead["contact_email"]):
                    skipped_suppressed += 1
                    continue
                copy = claude_agent.draft_touch(cfg, conn, dict(lead), "signal email")
                if copy is None:
                    failed += 1
                    db.audit(conn, "draft_outreach", "draft_failed", "leads", lead["lead_id"])
                    continue
                try:
                    created = graph_client.create_draft(lead["contact_email"], copy["subject"],
                                                           copy["body_html"])
                except Exception as e:
                    failed += 1
                    db.audit(conn, "draft_outreach", "graph_draft_failed", "leads",
                              lead["lead_id"], {"error": str(e)})
                    continue
                with conn.cursor() as cur:
                    cur.execute(
                        "insert into emails (direction, mailbox, to_address, subject, "
                        "body_html, graph_message_id, web_link, related_lead_id, status) "
                        "values ('outbound_draft',%s,%s,%s,%s,%s,%s,%s,'draft')",
                        (cfg.ms_mailbox, lead["contact_email"], copy["subject"],
                         copy["body_html"], created["graph_message_id"], created["web_link"],
                         lead["lead_id"]))
                    cur.execute("update leads set stage='Contacted', updated_at=now() "
                                 "where id=%s", (lead["lead_id"],))
                db.audit(conn, "draft_outreach", "draft_created", "leads", lead["lead_id"],
                          {"web_link": created["web_link"]})
                drafted += 1

            summary = (f"{len(candidates)} eligible, {drafted} drafted, "
                        f"{skipped_suppressed} suppressed, {failed} failed")
            db.finish_run(conn, run_id, True, summary)
            return {"ok": True, "summary": summary}
        except Exception as e:
            db.finish_run(conn, run_id, False, "", str(e))
            raise
        finally:
            conn.close()

    @router.post("/cron/check-replies")
    def check_replies(x_cron_secret: str = Header(default="")):
        """Reads the inbox (never sends), classifies each new reply, and
        either suppresses, escalates, or advances the matching lead's stage.
        A reply from an address with no matching lead is recorded but not
        actioned — there is nothing safe to infer without one."""
        _check(x_cron_secret)
        if not cfg.ms_configured or not cfg.anthropic_configured:
            missing = [n for n, ok in [("Microsoft Graph", cfg.ms_configured),
                                         ("Anthropic", cfg.anthropic_configured)] if not ok]
            return {"ok": False, "error": f"CONNECTION REQUIRED: {', '.join(missing)} not "
                                            f"configured"}

        conn = db.connect(cfg.database_url)
        run_id = db.start_run(conn, "check_replies")
        try:
            with conn.cursor() as cur:
                cur.execute("select max(created_at) as m from emails where direction='inbound'")
                last = cur.fetchone()["m"]
            since = last if last else datetime.now(timezone.utc) - timedelta(days=2)

            graph_client = GraphClient(cfg, cfg.ms_mailbox)
            messages = graph_client.list_recent_inbox_messages(since)

            processed = suppressed_n = escalated = unmatched = 0
            for m in messages:
                msg_id = m.get("internetMessageId")
                if not msg_id:
                    continue
                with conn.cursor() as cur:
                    cur.execute("select 1 from emails where graph_message_id=%s", (msg_id,))
                    if cur.fetchone():
                        continue

                from_addr = ((m.get("from") or {}).get("emailAddress") or {}) \
                    .get("address", "").lower()
                body_text = (m.get("body") or {}).get("content") or m.get("bodyPreview") or ""
                label = claude_agent.classify_reply(cfg, body_text)

                with conn.cursor() as cur:
                    cur.execute(
                        "select l.id as lead_id from leads l join contacts ct "
                        "on ct.company_id = l.company_id where ct.email = %s "
                        "order by l.created_at desc limit 1", (from_addr,))
                    lead_row = cur.fetchone()
                lead_id = lead_row["lead_id"] if lead_row else None

                with conn.cursor() as cur:
                    cur.execute(
                        "insert into emails (direction, from_address, subject, classification, "
                        "graph_message_id, related_lead_id, status, created_at) "
                        "values ('inbound',%s,%s,%s,%s,%s,'received',%s)",
                        (from_addr, m.get("subject"), label, msg_id, lead_id,
                         m.get("receivedDateTime")))
                    if lead_id and label == "NO/REMOVE":
                        db.suppress(conn, from_addr, "replied requesting removal",
                                     actioned_by="check_replies")
                        cur.execute("update leads set stage='Declined', updated_at=now() "
                                     "where id=%s", (lead_id,))
                        suppressed_n += 1
                    elif lead_id and label == "INTERESTED":
                        cur.execute("update leads set stage='Conversation', updated_at=now() "
                                     "where id=%s", (lead_id,))
                    elif lead_id and label in ("ANGRY", "INVESTOR", "UNCLASSIFIED"):
                        db.request_approval(conn, "RED", "leads", lead_id,
                                              f"Reply classified {label} — needs a human, not "
                                              f"an automated next step", requested_by="check_replies")
                        escalated += 1
                    if not lead_id:
                        unmatched += 1
                db.audit(conn, "check_replies", "reply_classified", "emails", None,
                          {"label": label, "matched_lead": bool(lead_id)})
                processed += 1

            summary = (f"{processed} replies processed, {suppressed_n} suppressed, "
                        f"{escalated} escalated to approval queue, {unmatched} unmatched to a lead")
            db.finish_run(conn, run_id, True, summary)
            return {"ok": True, "summary": summary}
        except Exception as e:
            db.finish_run(conn, run_id, False, "", str(e))
            raise
        finally:
            conn.close()

    @router.post("/cron/report")
    def report(x_cron_secret: str = Header(default="")):
        _check(x_cron_secret)
        conn = db.connect(cfg.database_url)
        run_id = db.start_run(conn, "report")
        try:
            with conn.cursor() as cur:
                cur.execute("select stage, count(*) as n from leads group by stage")
                by_stage = {r["stage"]: r["n"] for r in cur.fetchall()}
                cur.execute("select count(*) as n from approvals where status='pending'")
                pending = cur.fetchone()["n"]
                cur.execute("select count(*) as n from agent_runs where ok=false and "
                             "started_at > now() - interval '1 day'")
                failures_24h = cur.fetchone()["n"]
            summary = (f"leads by stage: {by_stage} | pending approvals: {pending} | "
                        f"agent failures in last 24h: {failures_24h}")
            db.finish_run(conn, run_id, True, summary)
            return {"ok": True, "summary": summary}
        except Exception as e:
            db.finish_run(conn, run_id, False, "", str(e))
            raise
        finally:
            conn.close()

    return router
