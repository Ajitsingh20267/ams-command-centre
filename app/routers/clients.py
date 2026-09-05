"""Converting an approved opportunity into a client. This is the one write
path in the CRM that is deliberately gated: it requires a RED approval
already sitting 'approved' for that opportunity — a human decision, made in
the approvals queue, before the system creates a client record and starts
the onboarding checklist. See CLAUDE.md's approval tiers: this is exactly a
RED action (a material change — creating a client relationship) followed by
GREEN ones (checklist creation is bookkeeping, not a commitment)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, security

ONBOARDING_CHECKLIST = [
    ("Business plan or investment summary", "onboarding"),
    ("Financial statements (2-3 years)", "onboarding"),
    ("Projections / model (3-5 years)", "onboarding"),
    ("Corporate structure and cap table", "onboarding"),
    ("Raise detail (amount, use of proceeds, instrument, security, timeline)", "onboarding"),
    ("Certificate of incorporation", "kyc"),
    ("Register of directors and PSCs / UBOs", "kyc"),
    ("Photo ID for each director / UBO", "kyc"),
    ("Proof of address for each director / UBO", "kyc"),
    ("Proof of registered business address", "kyc"),
]


class ConvertRequest(BaseModel):
    opportunity_id: str
    mandate_fee_amount: float
    mandate_fee_currency: str = "GBP"


def build_router(cfg) -> APIRouter:
    router = APIRouter()
    require_api = security.require_session(cfg)

    @router.get("/api/clients")
    def list_clients(claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select c.*, co.name as company_name from clients c "
                    "join companies co on co.id = c.company_id order by c.created_at desc")
                return cur.fetchall()
        finally:
            conn.close()

    @router.get("/api/clients/{client_id}/onboarding")
    def onboarding_checklist(client_id: str, claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select * from documents where client_id=%s order by category, doc_type",
                    (client_id,))
                return cur.fetchall()
        finally:
            conn.close()

    @router.post("/api/clients/convert")
    def convert_to_client(body: ConvertRequest, claims=Depends(require_api)):
        conn = db.connect(cfg.database_url)
        try:
            with conn.cursor() as cur:
                # The gate: a RED approval for this specific opportunity must
                # already be approved. No route lets an agent grant this to
                # itself — only /api/approvals/{id}/decide, called by a human
                # session, can move a row to 'approved'.
                cur.execute(
                    "select 1 from approvals where entity_type='opportunities' "
                    "and entity_id=%s and level='RED' and status='approved'", (body.opportunity_id,))
                if cur.fetchone() is None:
                    raise HTTPException(
                        status_code=403,
                        detail="No approved RED-level approval on file for this opportunity. "
                                "Create one via POST /api/approvals (level=RED) and approve it "
                                "in the dashboard first — client conversion is not a green-light "
                                "action.")

                cur.execute("select company_id from opportunities where id=%s",
                             (body.opportunity_id,))
                opp = cur.fetchone()
                if opp is None:
                    raise HTTPException(status_code=404, detail="opportunity not found")

                cur.execute(
                    "insert into clients (company_id, opportunity_id, mandate_fee_amount, "
                    "mandate_fee_currency, engagement_signed_date, status) "
                    "values (%s,%s,%s,%s, current_date, 'onboarding') returning id",
                    (opp["company_id"], body.opportunity_id, body.mandate_fee_amount,
                     body.mandate_fee_currency))
                client_id = cur.fetchone()["id"]

                for doc_type, category in ONBOARDING_CHECKLIST:
                    cur.execute(
                        "insert into documents (client_id, doc_type, category, status) "
                        "values (%s,%s,%s,'not_requested')", (client_id, doc_type, category))

            db.audit(conn, claims.get("email", "human"), "client_converted", "clients",
                      client_id, {"opportunity_id": body.opportunity_id})
            return {"ok": True, "client_id": client_id,
                     "checklist_items_created": len(ONBOARDING_CHECKLIST)}
        finally:
            conn.close()

    return router
