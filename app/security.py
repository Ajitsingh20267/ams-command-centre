"""Auth (Supabase) and at-rest encryption for OAuth tokens.

Login goes through Supabase's own GoTrue REST API rather than reimplementing
password handling — Supabase already does the hashing, rate limiting and
password-reset flow, and there is no reason to duplicate any of that here.
This module only verifies the JWT Supabase hands back and carries it in an
httpOnly cookie.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Optional

import httpx
import jwt
from cryptography.fernet import Fernet
from fastapi import Cookie, HTTPException

SESSION_COOKIE = "ams_session"


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
    """Returns the decoded claims if the cookie holds a valid, unexpired
    Supabase-issued JWT. None otherwise — callers redirect to /login."""
    if not token:
        return None
    try:
        return jwt.decode(token, cfg.supabase_jwt_secret, algorithms=["HS256"],
                            audience="authenticated")
    except jwt.PyJWTError:
        return None


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
