"""Sorting mail into an account's own categories with the Groq model.

The user describes a category in one sentence ("emails about job applications,
interviews and recruiters"); the model reads sender, subject and the short
preview of each email and picks one of those categories, or none, with a
reason the user can check. The full body is never sent.

Emails go ten to a request so a 50-email sync is five calls, which stays inside
Groq's free-tier rate limits.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

from app.services.classifier import MODELS

MAX_CATEGORIES = 5
BATCH_SIZE = 10
AI_LIMIT = 50  # newest emails of a category looked at when splitting it
MODEL = MODELS["small"]
_PREVIEW_CHARS = 300
_REASON_CHARS = 120


class AIUnavailable(RuntimeError):
    """The model could not be reached; the message is safe to show the user."""


def make_id(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")[:30] or "category"
    cid, n = base, 2
    while cid in taken:
        cid, n = f"{base}_{n}", n + 1
    return cid


def signature(categories: list[dict]) -> str:
    """Changes whenever a category is added, removed or re-described."""
    raw = json.dumps([[c["id"], c["name"], c["description"]] for c in categories])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


_SYSTEM = (
    "You sort emails into categories that the user defined themselves. "
    "Each category has an id, a name and the user's own description. "
    "For every email, pick the one category whose description it clearly fits, "
    "or \"none\" if no description fits. Prefer \"none\" over a weak guess. "
    "Give a short reason (under 15 words) that names what in the email matched.\n"
    # Groq's JSON mode requires the word JSON and the shape spelled out here.
    'Reply with JSON only: {"results": [{"i": <email number>, '
    '"category": <category id or "none">, "reason": <short string>}]}'
)


def _prompt(categories: list[dict], emails: list[dict]) -> str:
    lines = ["Categories:"]
    lines += [f"- id: {c['id']} | name: {c['name']} | description: {c['description']}" for c in categories]
    lines.append("\nEmails:")
    for i, e in enumerate(emails):
        preview = " ".join(str(e.get("snippet") or "").split())[:_PREVIEW_CHARS]
        lines.append(f"[{i}] From: {e.get('sender', '')}\n    Subject: {e.get('subject', '')}\n    Preview: {preview}")
    return "\n".join(lines)


def _client():
    if not os.getenv("GROQ_API_KEY"):
        raise AIUnavailable("AI sorting needs a GROQ_API_KEY in .env.")
    from groq import Groq  # imported lazily so the rest of the app needs no SDK

    return Groq()


def _ask(system: str, user: str, client=None) -> dict:
    """One JSON-mode request; {} when the answer cannot be read."""
    client = client or _client()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            max_tokens=1500,
            reasoning_effort="low",  # fewer tokens per answer, so fewer rate-limit replies
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        data = json.loads(response.choices[0].message.content or "{}")
    except AIUnavailable:
        raise
    except json.JSONDecodeError:
        data = {}
    except Exception as e:  # SDK errors: rate limit, network, bad key
        if getattr(e, "status_code", None) == 429:
            raise AIUnavailable("The AI is busy (rate limit). Try again in a minute.") from e
        raise AIUnavailable("AI sorting is unavailable right now.") from e
    return data if isinstance(data, dict) else {}


def sort_batch(categories: list[dict], emails: list[dict], client=None) -> list[tuple[str | None, str]]:
    """One (category id or None, reason) per email, in order."""
    data = _ask(_SYSTEM, _prompt(categories, emails), client)

    known = {c["id"] for c in categories}
    out: list[tuple[str | None, str]] = [(None, "")] * len(emails)
    rows = data.get("results")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            i = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        if not 0 <= i < len(emails):
            continue
        cid = str(row.get("category") or "").strip()
        # An id the user never made (or "none") means no match.
        if cid in known:
            out[i] = (cid, " ".join(str(row.get("reason") or "").split())[:_REASON_CHARS])
    return out


# ---------------------------------------------------------------- subcategories

# One category (built-in or the account's own) split into a few smaller ones.
# The model proposes them from sender and subject of the emails already in the
# category; the descriptions it writes then go through sort_batch like any
# custom category, so each email gets a subcategory (or none: "Other").

SPLIT_MIN = 6
MAX_SUBS = 4
# "Other", "Misc promotions", "General updates": the leftovers already have Other.
_CATCH_ALL = re.compile(r"\b(other|others|misc|miscellaneous|general|everything else|rest)\b", re.I)

_SPLIT_SYSTEM = (
    "You split one email category into smaller subcategories. "
    "You get the category's name, its description if there is one, and the sender and "
    "subject of the emails in it. Suggest 2 to 4 subcategories that together cover most "
    "of these emails and are clearly different from each other. Give each a short name "
    "(1 to 3 words) and a one-sentence description of which emails belong in it. "
    "Do not suggest a catch-all such as Other or Misc.\n"
    'Reply with JSON only: {"subcategories": [{"name": <short name>, "description": <one sentence>}]}'
)


def _split_prompt(label: str, description: str, emails: list[dict]) -> str:
    lines = [f"Category: {label}"]
    if description:
        lines.append(f"Description: {description}")
    lines.append("\nEmails:")
    lines += [f"[{i}] From: {e.get('sender', '')} | Subject: {e.get('subject', '')}" for i, e in enumerate(emails)]
    return "\n".join(lines)


def clean_subs(raw) -> list[dict]:
    """Names to 30 characters, descriptions to 200; no empty, repeated or
    catch-all names; at most MAX_SUBS. Fewer than two means no split."""
    out: list[dict] = []
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict) or len(out) >= MAX_SUBS:
            continue
        name = " ".join(str(s.get("name") or "").split())[:30]
        description = " ".join(str(s.get("description") or "").split())[:200]
        lower = name.lower()
        if not name or not description or _CATCH_ALL.search(name) or any(o["name"].lower() == lower for o in out):
            continue
        out.append({"id": make_id(name, {o["id"] for o in out}), "name": name, "description": description})
    return out if len(out) >= 2 else []


def suggest_subcategories(label: str, description: str, emails: list[dict], client=None) -> list[dict]:
    data = _ask(_SPLIT_SYSTEM, _split_prompt(label, description, emails), client)
    return clean_subs(data.get("subcategories"))
