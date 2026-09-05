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

    @router.get("/api/leads")
    def list_leads(stage: Optional[str] = None, claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                if stage:
                    cur.execute(
                        "select l.*, c.name as company_name, c.website, c.country "
                        "from leads l join companies c on c.id = l.company_id "
                        "where l.stage = %s order by l.score desc nulls last, l.created_at desc",
                        (stage,))
                else:
                    cur.execute(
                        "select l.*, c.name as company_name, c.website, c.country "
                        "from leads l join companies c on c.id = l.company_id "
                        "order by l.score desc nulls last, l.created_at desc limit 200")
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
