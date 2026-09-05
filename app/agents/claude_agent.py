"""Anthropic calls: drafts outreach copy and classifies replies. Every call
is grounded in the `knowledge_base` table — nothing else. If the table is
empty or missing the fact a draft needs, the model is instructed to say so
rather than invent it, and this module never asks it to draft against an
empty knowledge base pretending one exists.
"""
from __future__ import annotations

import json
import re

import anthropic

REPLY_LABELS = {"INTERESTED", "QUESTION", "NOT NOW", "NO/REMOVE", "WRONG PERSON",
                "INVESTOR", "ANGRY"}


def load_knowledge_base(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("select category, key, content from knowledge_base order by category, key")
        rows = cur.fetchall()
    if not rows:
        return ("THE KNOWLEDGE BASE IS EMPTY. No approved company information, pricing, "
                "claims or templates are on file. Do not draft anything that states a fact "
                "about the firm — respond with INSUFFICIENT VERIFIED INFORMATION instead.")
    return "\n\n".join(f"### {r['category']} / {r['key']}\n{r['content']}" for r in rows)


def _client(cfg) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=cfg.anthropic_key)


def draft_touch(cfg, conn, lead: dict, touch_name: str) -> dict | None:
    """Returns {"subject", "body_html"} or None if generation failed or the
    model reported insufficient verified information — callers must treat
    both as "do not draft", never fall back to a generic template."""
    kb = load_knowledge_base(conn)
    system = (
        "You write outbound correspondence for a corporate advisory firm. Use ONLY facts "
        "present in the knowledge base below. If a fact you would need is not there, do not "
        "invent it — respond with exactly the JSON "
        '{"subject": null, "body_html": null, "reason": "INSUFFICIENT VERIFIED INFORMATION: '
        '<what is missing>"} instead of drafting.\n\n'
        f"KNOWLEDGE BASE:\n{kb}\n\n"
        'Otherwise respond with ONLY {"subject": "...", "body_html": "..."}, no other text.')
    user = f"Write the '{touch_name}' touch for this lead:\n" + json.dumps(lead, default=str)

    resp = _client(cfg).messages.create(model=cfg.anthropic_model, max_tokens=1200,
                                          system=system, messages=[{"role": "user", "content": user}])
    text = re.sub(r"^```(?:json)?|```$", "", resp.content[0].text.strip(),
                   flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not data.get("subject") or not data.get("body_html"):
        return None
    return {"subject": data["subject"], "body_html": data["body_html"]}


def classify_reply(cfg, body_text: str) -> str:
    system = (f"Classify one inbound email reply. Respond with EXACTLY one label from: "
               f"{', '.join(sorted(REPLY_LABELS))}. Nothing else.")
    resp = _client(cfg).messages.create(model=cfg.anthropic_model, max_tokens=20, system=system,
                                          messages=[{"role": "user", "content": body_text[:4000]}])
    label = resp.content[0].text.strip().upper()
    for known in REPLY_LABELS:
        if label == known.upper():
            return known
    return "UNCLASSIFIED"
