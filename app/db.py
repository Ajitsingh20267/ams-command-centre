"""Postgres access (Supabase). Every function here takes a connection rather
than opening its own — request-scoped connections are handed out by
`get_conn` (see main.py's dependency), and cron jobs open and close their own
around a single run.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras


def connect(database_url: str):
    conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    return conn


@contextmanager
def tx(conn):
    """Explicit transaction for a group of writes that must land together."""
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(conn, actor: str, action: str, entity_type: str = "", entity_id=None, detail=None):
    with conn.cursor() as cur:
        cur.execute(
            "insert into audit_logs (actor, action, entity_type, entity_id, detail) "
            "values (%s,%s,%s,%s,%s)",
            (actor, action, entity_type or None, entity_id, psycopg2.extras.Json(detail)
             if detail is not None else None))


def is_suppressed(conn, email: str) -> bool:
    e = (email or "").strip().lower()
    if not e:
        return False
    with conn.cursor() as cur:
        cur.execute("select 1 from suppression where value=%s and kind='EMAIL'", (e,))
        if cur.fetchone():
            return True
        domain = e.split("@")[-1]
        cur.execute("select 1 from suppression where value=%s and kind='DOMAIN'", (domain,))
        return bool(cur.fetchone())


def suppress(conn, value: str, reason: str, actioned_by: str = "system"):
    v = (value or "").strip().lower()
    if not v:
        return
    kind = "EMAIL" if "@" in v else "DOMAIN"
    with conn.cursor() as cur:
        cur.execute(
            "insert into suppression (value, kind, reason, actioned_by) values (%s,%s,%s,%s) "
            "on conflict (value) do nothing", (v, kind, reason, actioned_by))
    audit(conn, actioned_by, "suppress", "suppression", None, {"value": v, "reason": reason})


def start_run(conn, agent_name: str) -> str:
    with conn.cursor() as cur:
        cur.execute("insert into agent_runs (agent_name) values (%s) returning id",
                     (agent_name,))
        return cur.fetchone()["id"]


def finish_run(conn, run_id, ok: bool, summary: str = "", error: str = ""):
    with conn.cursor() as cur:
        cur.execute(
            "update agent_runs set finished_at=now(), ok=%s, summary=%s, error=%s where id=%s",
            (ok, summary, error or None, run_id))


def get_cursor(conn, key: str, default: int = 0) -> int:
    """Small persisted progress marker (see agent_cursors in the schema) —
    e.g. how far a paginated discovery agent has gotten for one search
    term, so the next run continues from there instead of repeating."""
    with conn.cursor() as cur:
        cur.execute("select value from agent_cursors where key=%s", (key,))
        row = cur.fetchone()
    if row is None:
        return default
    try:
        return int(row["value"])
    except ValueError:
        return default


def set_cursor(conn, key: str, value: int):
    with conn.cursor() as cur:
        cur.execute(
            "insert into agent_cursors (key, value, updated_at) values (%s,%s,now()) "
            "on conflict (key) do update set value=excluded.value, updated_at=now()",
            (key, str(value)))


def request_approval(conn, level: str, entity_type: str, entity_id, description: str,
                       requested_by: str = "system") -> str:
    """The GREEN/AMBER/RED gate. GREEN rows are logged for visibility but do
    not block anything; AMBER/RED rows must be moved to 'approved' by a named
    human (via the dashboard) before the caller may proceed."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into approvals (level, entity_type, entity_id, description, requested_by) "
            "values (%s,%s,%s,%s,%s) returning id",
            (level, entity_type, entity_id, description, requested_by))
        return cur.fetchone()["id"]
