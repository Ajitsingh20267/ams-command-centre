"""Configuration. Fails loudly at boot, same discipline as the desk deploy:
a missing setting should stop the process at startup, not surface as a
mysterious 500 at 07:00 when nobody is watching.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _req(key: str) -> str:
    v = os.getenv(key, "").strip()
    if not v:
        print(f"FATAL: {key} is not set. Copy .env.example to .env and fill it in.",
              file=sys.stderr)
        raise SystemExit(2)
    return v


def _opt(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass(frozen=True)
class Config:
    # Supabase Postgres — free tier. Project Settings -> Database -> Connection string.
    database_url: str = field(default_factory=lambda: _req("DATABASE_URL"))

    # Supabase Auth — Project Settings -> API. No JWT secret is needed: newer
    # Supabase projects don't expose one at all (rotating signing keys
    # instead), so session verification calls Supabase's own /auth/v1/user
    # endpoint rather than checking a signature locally — see app/security.py.
    supabase_url: str = field(default_factory=lambda: _req("SUPABASE_URL"))
    supabase_anon_key: str = field(default_factory=lambda: _req("SUPABASE_ANON_KEY"))

    anthropic_key: str = field(default_factory=lambda: _opt("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _opt("ANTHROPIC_MODEL", "claude-sonnet-5"))

    # Microsoft Graph — optional until the Managing Partner connects a mailbox.
    ms_tenant_id: str = field(default_factory=lambda: _opt("MS_TENANT_ID"))
    ms_client_id: str = field(default_factory=lambda: _opt("MS_CLIENT_ID"))
    ms_client_secret: str = field(default_factory=lambda: _opt("MS_CLIENT_SECRET"))
    ms_mailbox: str = field(default_factory=lambda: _opt("MS_MAILBOX", "invest@amscapital.co.uk"))

    # A random 32+ byte string, used only to encrypt OAuth tokens at rest and
    # to sign the session cookie. Generate with: python3 -c "import secrets;
    # print(secrets.token_urlsafe(32))"
    app_secret: str = field(default_factory=lambda: _req("APP_SECRET"))

    # Shared secret GitHub Actions sends to authorise a cron call. Never the
    # same value as APP_SECRET.
    cron_secret: str = field(default_factory=lambda: _req("CRON_SECRET"))

    port: int = field(default_factory=lambda: int(_opt("PORT", "8080") or "8080"))

    # "local" relaxes the session cookie's Secure flag so login works over
    # plain http://localhost during development. Every real deployment
    # (Render, Fly, anywhere with a real domain) serves https and must NOT
    # set this — a Secure-less cookie sent over http is interceptable.
    env: str = field(default_factory=lambda: _opt("ENV", "production"))

    @property
    def cookie_secure(self) -> bool:
        return self.env != "local"

    # There is no environment variable that turns sending on, on purpose —
    # see app/agents/graph_client.py, which has no send function to enable.
    SENDING_ENABLED: bool = False

    @property
    def ms_configured(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret)

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_key)


def load() -> Config:
    return Config()
