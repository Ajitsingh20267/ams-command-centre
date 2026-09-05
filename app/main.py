"""A.M.S. Command Centre — FastAPI entrypoint.

One process serves the dashboard, the CRM API, the OAuth connection screens,
and the cron-triggered agent endpoints. GitHub Actions (free) calls the
/cron/* routes on a schedule instead of this process scheduling itself —
see .github/workflows/scheduler.yml — which is what makes this deployable to
a free web host with no long-running background worker required.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import config, db
from .routers import approvals, auth_routes, cron, dashboard, investors, leads, oauth_ms

cfg = config.load()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fails loudly at boot if the database is unreachable, rather than
    # quietly at the first request.
    conn = db.connect(cfg.database_url)
    with conn.cursor() as cur:
        cur.execute("select 1")
    conn.close()
    yield


app = FastAPI(title="A.M.S. Command Centre", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"ok": True, "time": db.now(),
             "ms_configured": cfg.ms_configured, "anthropic_configured": cfg.anthropic_configured}


app.include_router(auth_routes.build_router(cfg))
app.include_router(dashboard.build_router(cfg))
app.include_router(leads.build_router(cfg))
app.include_router(investors.build_router(cfg))
app.include_router(approvals.build_router(cfg))
app.include_router(oauth_ms.build_router(cfg))
app.include_router(cron.build_router(cfg))
