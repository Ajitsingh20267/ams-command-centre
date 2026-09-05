"""Investor CRM + matching. Running the matcher is a GREEN action (internal
analysis only, nothing leaves the building) — see AMS-AI-COMPANY / the
approval-tier note in README. Acting on a match externally is not."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from .. import db, security
from ..agents.investor_matching import top_matches


def build_router(cfg) -> APIRouter:
    router = APIRouter()
    require_api = security.require_session(cfg)

    @router.get("/api/investors")
    def list_investors(claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("select * from investors order by entity_name")
                return cur.fetchall()
        finally:
            conn.close()

    @router.get("/api/clients/{client_id}/matches")
    def get_matches(client_id: str, claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select m.*, i.entity_name from investor_matches m "
                    "join investors i on i.id = m.investor_id "
                    "where m.client_id=%s order by m.match_score desc", (client_id,))
                return cur.fetchall()
        finally:
            conn.close()

    @router.post("/api/clients/{client_id}/run-matching")
    def run_matching(client_id: str, claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select c.id as client_id, co.name as sector, l.sector, l.geography, "
                    "l.funding_requirement_min, l.funding_requirement_max, l.instrument, "
                    "l.stage from clients c "
                    "left join opportunities o on o.id = c.opportunity_id "
                    "left join leads l on l.id = o.lead_id "
                    "left join companies co on co.id = c.company_id "
                    "where c.id=%s", (client_id,))
                client_row = cur.fetchone()
                if client_row is None:
                    raise HTTPException(status_code=404, detail="client not found")
                cur.execute("select * from investors")
                investors = cur.fetchall()

            matches = top_matches(dict(client_row), [dict(i) for i in investors], top_n=10)

            with db.tx(conn) as cur:
                cur.execute("delete from investor_matches where client_id=%s", (client_id,))
                for m in matches:
                    cur.execute(
                        "insert into investor_matches (client_id, investor_id, match_score, "
                        "sector_fit, geography_fit, ticket_fit, stage_fit, confidence_fit, why, "
                        "concerns, recommended_approach) values "
                        "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (client_id, m["investor_id"], m["match_score"], m["sector_fit"],
                         m["geography_fit"], m["ticket_fit"], m["stage_fit"], m["confidence_fit"],
                         json.dumps(m["why"]), json.dumps(m["concerns"]),
                         m["recommended_approach"]))
            db.audit(conn, claims.get("email", "human"), "investor_matching_run", "clients",
                      client_id, {"matches": len(matches)})
            return {"ok": True, "matches": len(matches)}
        finally:
            conn.close()

    return router
