"""Login / logout. Password verification is delegated entirely to Supabase
Auth (see security.login) — this module never sees or stores a password."""
from __future__ import annotations

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import security

LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>A.M.S. Command Centre — sign in</title>
<style>
 body{font-family:-apple-system,sans-serif;background:#faf8f4;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0}
 form{background:#fff;border:1px solid #e6e2da;border-radius:10px;padding:32px;width:320px}
 h1{font-size:16px;color:#172944;margin:0 0 20px}
 input{width:100%;padding:10px;margin-bottom:12px;border:1px solid #ccc;border-radius:6px;
       box-sizing:border-box}
 button{width:100%;padding:10px;background:#172944;color:#fff;border:none;border-radius:6px;
        cursor:pointer}
 .err{color:#b3402a;font-size:13px;margin-bottom:12px}
</style></head><body>
<form method="post" action="/login">
 <h1>A.M.S. Command Centre</h1>
 {error_html}
 <input name="email" type="email" placeholder="Email" required>
 <input name="password" type="password" placeholder="Password" required>
 <button type="submit">Sign in</button>
</form></body></html>"""


def build_router(cfg) -> APIRouter:
    router = APIRouter()

    @router.get("/login", response_class=HTMLResponse)
    def login_page(error: str = ""):
        error_html = f'<div class="err">{error}</div>' if error else ""
        return LOGIN_PAGE.replace("{error_html}", error_html)

    @router.post("/login")
    def login_submit(email: str = Form(...), password: str = Form(...)):
        try:
            tokens = security.login(cfg, email, password)
        except Exception:
            return RedirectResponse(url="/login?error=Incorrect+email+or+password",
                                      status_code=303)
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie(security.SESSION_COOKIE, tokens["access_token"],
                          httponly=True, samesite="lax", secure=cfg.cookie_secure,
                          max_age=60 * 60 * 8)
        return resp

    if cfg.env == "local":
        # Demo/dev login only — real login always goes through Supabase Auth
        # (see /login above). This route does not exist at all unless ENV=local,
        # which no real deployment sets (Render's blueprint never sets it), so
        # there is no code path in production that can reach this.
        @router.get("/dev-login")
        def dev_login():
            resp = RedirectResponse(url="/", status_code=303)
            resp.set_cookie(security.SESSION_COOKIE, security._DEV_SESSION_VALUE,
                              httponly=True, samesite="lax", secure=cfg.cookie_secure,
                              max_age=60 * 60 * 8)
            return resp

    @router.get("/logout")
    def logout():
        resp = RedirectResponse(url="/login", status_code=303)
        resp.delete_cookie(security.SESSION_COOKIE)
        return resp

    return router
