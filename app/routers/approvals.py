"""The GREEN/AMBER/RED queue. Only a human (a valid session) can move an
approval to 'approved' or 'rejected' — there is no route an agent can call
to approve its own request."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, security


class Decision(BaseModel):
    decision: str  # "approved" | "rejected"


def build_router(cfg) -> APIRouter:
    router = APIRouter()
    require_api = security.require_session(cfg)

    @router.get("/api/approvals")
    def list_approvals(status: str = "pending", claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select * from approvals where status=%s "
                    "order by case level when 'RED' then 0 when 'AMBER' then 1 else 2 end, "
                    "created_at desc", (status,))
                return cur.fetchall()
        finally:
            conn.close()

    @router.post("/api/approvals/{approval_id}/decide")
    def decide(approval_id: str, body: Decision, claims=Depends(require_api)):
        if body.decision not in ("approved", "rejected"):
            raise HTTPException(status_code=400, detail="decision must be approved or rejected")
        conn = db.connect(cfg.database_url)
        try:
            decided_by = claims.get("email", "human")
            with conn.cursor() as cur:
                cur.execute(
                    "update approvals set status=%s, decided_by=%s, decided_at=now() "
                    "where id=%s and status='pending' returning id",
                    (body.decision, decided_by, approval_id))
                if cur.fetchone() is None:
                    raise HTTPException(status_code=404,
                                          detail="approval not found or already decided")
            db.audit(conn, decided_by, f"approval_{body.decision}", "approvals", approval_id)
            return {"ok": True}
        finally:
            conn.close()

    return router
