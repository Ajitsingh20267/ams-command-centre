"""A real, embedded, throwaway Postgres for tests that need to prove SQL
against the actual schema — not a mock, not SQLite standing in for Postgres
syntax it doesn't share (jsonb, on conflict, returning, interval, uuid
defaults). This is exactly the class of test that catches a wrong column
name in a raw SQL string, which unit tests of pure functions cannot.

Session-scoped: one embedded server for the whole test run, schema applied
once. Each test that uses `pg_conn` should clean up its own rows if it
inserts fixture data another test could trip over.
"""
import os
import shutil
import tempfile

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://placeholder")
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "fake")
os.environ.setdefault("SUPABASE_JWT_SECRET", "fake-jwt-secret-for-tests")
os.environ.setdefault("APP_SECRET", "fake-app-secret-for-tests-32-bytes-ok")
os.environ.setdefault("CRON_SECRET", "fake-cron-secret-for-tests")


@pytest.fixture(scope="session")
def pg_uri():
    pgserver = pytest.importorskip(
        "pgserver", reason="pgserver not installed — run `pip install -r requirements-dev.txt` "
                            "to run the real-Postgres integration tests")
    pgdata = tempfile.mkdtemp(prefix="ams-test-pg-")
    server = pgserver.get_server(pgdata)
    uri = server.get_uri()
    os.environ["DATABASE_URL"] = uri

    import psycopg2
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    with conn.cursor() as cur:
        # Supabase provides this automatically; stub it here since this is a
        # vanilla Postgres used purely to test our own schema against real SQL.
        cur.execute("create schema if not exists auth")
        cur.execute("create table if not exists auth.users "
                     "(id uuid primary key default gen_random_uuid())")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "db", "migrations", "001_init.sql")) as f:
            cur.execute(f.read())
    conn.close()

    yield uri

    shutil.rmtree(pgdata, ignore_errors=True)


@pytest.fixture
def pg_conn(pg_uri):
    from app import db
    conn = db.connect(pg_uri)
    yield conn
    conn.close()
