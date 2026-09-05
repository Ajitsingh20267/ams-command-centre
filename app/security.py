"""Auth (Supabase) and at-rest encryption for OAuth tokens.

Login goes through Supabase's own GoTrue REST API rather than reimplementing
password handling — Supabase already does the hashing, rate limiting and
password-reset flow, and there is no reason to duplicate any of that here.

Session verification calls Supabase's own /auth/v1/user endpoint rather than
verifying the JWT locally. That was the original design, but newer Supabase
projects (this one included) no longer expose a static JWT secret through
any API — it's been deprecated in favour of rotating signing keys — so
local verification isn't reliably possible any more. Asking Supabase itself
is also strictly better: it respects token revocation (a locally-verified
JWT stays "valid" by signature alone even after a user is banned or signs
out everywhere), at the cost of one extra HTTP round trip per request.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Optional

import httpx
from cryptography.fernet import Fernet
from fastapi import Cookie, HTTPException

SESSION_COOKIE = "ams_session"

# The /dev-login route (ENV=local only, see auth_routes.py) sets exactly this
# value rather than a real token, since there is no live Supabase session to
# validate against on a local machine with no deployed project.
_DEV_SESSION_VALUE = "local-dev-session-not-a-real-token"


def login(cfg, email: str, password: str) -> dict:
    """Returns Supabase's token response, or raises HTTPException(401)."""
    r = httpx.post(
        f"{cfg.supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": cfg.supabase_anon_key, "Content-Type": "application/json"},
        json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="incorrect email or password")
    return r.json()


def verify_session(cfg, token: Optional[str]) -> Optional[dict]:
    """Returns the user's claims (dict with at least "email") if the cookie
    holds a live, valid Supabase session. None otherwise — callers redirect
    to /login. Never raises on a bad/expired token; that's just "not logged in".
    """
    if not token:
        return None
    if cfg.env == "local" and token == _DEV_SESSION_VALUE:
        return {"sub": "dev-user", "email": "ajit@amscapital.co.uk"}
    try:
        r = httpx.get(f"{cfg.supabase_url}/auth/v1/user",
                       headers={"apikey": cfg.supabase_anon_key,
                                 "Authorization": f"Bearer {token}"}, timeout=10)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    return r.json()


def require_session(cfg):
    """FastAPI dependency for JSON/API routes: 401s without a valid session."""
    def _dep(ams_session: Optional[str] = Cookie(default=None)):
        claims = verify_session(cfg, ams_session)
        if claims is None:
            raise HTTPException(status_code=401, detail="not authenticated — go to /login")
        return claims
    return _dep


def optional_session(cfg):
    """FastAPI dependency for HTML page routes: returns None instead of
    raising, so the route can redirect to /login itself with a 303 rather
    than showing a bare JSON 401."""
    def _dep(ams_session: Optional[str] = Cookie(default=None)):
        return verify_session(cfg, ams_session)
    return _dep


def _fernet(cfg) -> Fernet:
    # Fernet needs a 32-byte urlsafe-base64 key; derive one deterministically
    # from APP_SECRET so there is exactly one secret to manage, not two.
    key = base64.urlsafe_b64encode(hashlib.sha256(cfg.app_secret.encode()).digest())
    return Fernet(key)


def encrypt_token(cfg, plaintext: str) -> str:
    return _fernet(cfg).encrypt(plaintext.encode()).decode()


def decrypt_token(cfg, ciphertext: str) -> str:
    return _fernet(cfg).decrypt(ciphertext.encode()).decode()
