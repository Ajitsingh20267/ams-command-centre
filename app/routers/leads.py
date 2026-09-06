from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, security


class StageUpdate(BaseModel):
    stage: str


def build_router(cfg) -> APIRouter:
    router = APIRouter()
    require_api = security.require_session(cfg)

    # Correlated subqueries rather than a join+group by: cheap at this scale
    # (hundreds of leads, not millions), and keeps each lead to exactly one
    # row without needing to aggregate the emails join in the caller.
    _ACTIVITY_COLUMNS = """,
        (select count(*) from emails e where e.related_lead_id = l.id
           and e.direction = 'outbound_draft') as drafts_count,
        (select max(e.created_at) from emails e where e.related_lead_id = l.id
           and e.direction = 'outbound_draft') as last_draft_at,
        (select e.classification from emails e where e.related_lead_id = l.id
           and e.direction = 'inbound' order by e.created_at desc limit 1) as last_reply,
        (select max(e.created_at) from emails e where e.related_lead_id = l.id
           and e.direction = 'inbound') as last_reply_at
    """

    @router.get("/api/leads")
    def list_leads(stage: Optional[str] = None, claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                if stage:
                    cur.execute(
                        f"select l.*, c.name as company_name, c.website, c.country"
                        f"{_ACTIVITY_COLUMNS} "
                        "from leads l join companies c on c.id = l.company_id "
                        "where l.stage = %s order by l.score desc nulls last, l.created_at desc",
                        (stage,))
                else:
                    cur.execute(
                        f"select l.*, c.name as company_name, c.website, c.country"
                        f"{_ACTIVITY_COLUMNS} "
                        "from leads l join companies c on c.id = l.company_id "
                        "order by l.score desc nulls last, l.created_at desc limit 200")
                return cur.fetchall()
        finally:
            conn.close()

    @router.get("/api/activity")
    def activity(limit: int = 100, claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select e.id, e.direction, e.status, e.classification, e.subject, "
                    "e.to_address, e.from_address, e.web_link, e.created_at, "
                    "l.id as lead_id, c.name as company_name "
                    "from emails e "
                    "left join leads l on l.id = e.related_lead_id "
                    "left join companies c on c.id = l.company_id "
                    "order by e.created_at desc limit %s", (min(limit, 500),))
                return cur.fetchall()
        finally:
            conn.close()

    @router.post("/api/leads/{lead_id}/stage")
    def update_stage(lead_id: str, body: StageUpdate, claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("update leads set stage=%s, updated_at=now() where id=%s returning id",
                             (body.stage, lead_id))
                if cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail="lead not found")
            db.audit(conn, claims.get("email", "human"), "stage_change", "leads", lead_id,
                      {"new_stage": body.stage})
            return {"ok": True}
        finally:
            conn.close()

    return router
