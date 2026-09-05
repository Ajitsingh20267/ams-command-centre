"""Endpoints GitHub Actions calls on a schedule (see
.github/workflows/scheduler.yml). This is the free replacement for a
long-running scheduler process: nothing runs unless one of these routes is
hit, and each call does exactly one unit of work and returns.

Authorised by a shared secret header, never by the session cookie — GitHub
Actions has no Supabase login. Rotate CRON_SECRET if it ever leaks into a
public log.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from .. import db
from ..agents import lead_generation


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
