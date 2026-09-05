"""Microsoft Graph client. Creates drafts and reads the inbox. Nothing else.

Same design rule as the desk deploy build: no function in this file sends a
message, and none should ever be added. The Azure app registration this
service uses should grant Mail.ReadWrite only — Mail.Send withheld at the
Azure side means a bug here cannot make Graph deliver anything.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import msal

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = ["https://graph.microsoft.com/.default"]


class GraphError(RuntimeError):
    pass


class GraphClient:
    def __init__(self, cfg, mailbox: str):
        self._cfg = cfg
        self._mailbox = mailbox
        self._app = None   # built lazily — see _headers(). msal's constructor
                            # itself makes a live network call to discover the
                            # tenant's OIDC config, so building it eagerly here
                            # would mean simply instantiating a GraphClient
                            # (e.g. for an unrelated code path, or a test)
                            # silently depends on Microsoft's servers.
        self._token = None

    def _headers(self) -> dict:
        if self._app is None:
            self._app = msal.ConfidentialClientApplication(
                self._cfg.ms_client_id,
                authority=f"https://login.microsoftonline.com/{self._cfg.ms_tenant_id}",
                client_credential=self._cfg.ms_client_secret)
        if not self._token:
            result = self._app.acquire_token_for_client(scopes=SCOPE)
            if "access_token" not in result:
                raise GraphError(f"token acquisition failed: {result.get('error_description')}")
            self._token = result["access_token"]
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def create_draft(self, to_email: str, subject: str, body_html: str) -> dict:
        payload = {"subject": subject, "body": {"contentType": "HTML", "content": body_html},
                    "toRecipients": [{"emailAddress": {"address": to_email}}]}
        r = httpx.post(f"{GRAPH}/users/{self._mailbox}/messages",
                        headers=self._headers(), json=payload, timeout=30)
        r.raise_for_status()
        msg = r.json()
        return {"graph_message_id": msg["id"], "web_link": msg.get("webLink", "")}

    def list_recent_inbox_messages(self, since: datetime, top: int = 50) -> list:
        since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {"$filter": f"receivedDateTime ge {since_iso}",
                    "$select": "id,internetMessageId,from,subject,receivedDateTime,bodyPreview,body",
                    "$orderby": "receivedDateTime asc", "$top": str(top)}
        r = httpx.get(f"{GRAPH}/users/{self._mailbox}/mailFolders/inbox/messages",
                       headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("value", [])
