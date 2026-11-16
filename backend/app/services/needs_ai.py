"""Needs reply: which stored emails are waiting on the user's answer.

Rules first: mail the classifier filed as bills, codes, receipts, newsletters
and the like, and mail from no-reply addresses, never needs a reply and is
not sent to the model. The rest goes to the Groq model with sender, subject
and preview only, and it says whether each one asks the user something, with
a short reason. A thread whose newest stored message is the user's own is
already answered. Same rules and prompt as the extension's needs.js.
"""

from __future__ import annotations

import re

from app.services.personal_ai import _ask

LIMIT = 50  # newest stored emails looked at
BATCH_SIZE = 10
_PREVIEW_CHARS = 300
_REASON_CHARS = 120

# Built-in categories that are automatic mail by definition.
SKIP_CATEGORIES = frozenset({"bill", "security", "otp", "subscription", "receipt",
                             "shipping", "alert", "promotion", "newsletter"})
_NO_REPLY = re.compile(r"(^|[^a-z])(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|mailer-daemon|bounces?)[^@]*@", re.I)

_SYSTEM = (
    "You decide which emails are waiting on the user's answer. For each email you get "
    "the sender, the subject and a short preview. An email needs a reply when a person "
    "asks the user a question, asks them to do or confirm something, or invites them and "
    "expects an answer. Newsletters, receipts, notifications, announcements, marketing "
    "and mail sent to a list do not need a reply, even when they ask a question. "
    "Neither do events or sign-ups answered on a website or form instead of by email. "
    "Prefer false over a weak guess. Give a short reason (under 12 words) that says "
    "what is asked, like \"Priya asks if Thursday at 3 works\".\n"
    'Reply with JSON only: {"results": [{"i": <email number>, '
    '"needs_reply": <true or false>, "reason": <short string>}]}'
)


def address(email: dict) -> str:
    raw = str(email.get("sender_email") or email.get("sender") or "")
    match = re.search(r"<([^>]+)>", raw)
    return (match.group(1) if match else raw).strip().lower()


def is_candidate(email: dict, me: str = "") -> bool:
    """Whether a stored email is worth asking the model about."""
    if email.get("category") in SKIP_CATEGORIES:
        return False
    sender = address(email)
    if not sender or _NO_REPLY.search(sender):
        return False
    return not (me and sender == me.lower())


def prompt(emails: list[dict]) -> str:
    lines = ["Emails:"]
    for i, e in enumerate(emails):
        preview = " ".join(str(e.get("snippet") or "").split())[:_PREVIEW_CHARS]
        lines.append(f"[{i}] From: {e.get('sender', '')}\n    Subject: {e.get('subject', '')}\n    Preview: {preview}")
    return "\n".join(lines)


def check_batch(emails: list[dict], client=None) -> list[tuple[bool, str]]:
    """One (needs reply, reason) per email, in order. Only an explicit true
    counts; an unreadable answer means nothing needs a reply."""
    data = _ask(_SYSTEM, prompt(emails), client)
    out: list[tuple[bool, str]] = [(False, "")] * len(emails)
    rows = data.get("results")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("needs_reply") is not True:
            continue
        try:
            i = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(emails):
            out[i] = (True, " ".join(str(row.get("reason") or "").split())[:_REASON_CHARS])
    return out


def thread_answered(thread: list[dict], me: str = "") -> bool:
    """True when the thread's newest stored message (oldest first, drafts
    left out) is the user's own."""
    sent = [e for e in thread if "DRAFT" not in (e.get("labels") or [])]
    return bool(me and sent and address(sent[-1]) == me.lower())


def needs_reply(emails: list[dict], me: str = "", threads=None, client=None) -> list[dict]:
    """The emails waiting on an answer, one per thread, each with its reason.
    `emails` comes newest first; `threads(thread_id)` returns the stored mail
    of a thread, oldest first."""
    seen: set[str] = set()
    pending = []
    for e in emails[:LIMIT]:
        thread = e.get("thread_id") or e.get("id")
        if thread in seen or not is_candidate(e, me):
            continue
        if threads and thread_answered(threads(e.get("thread_id") or ""), me):
            continue
        seen.add(thread)
        pending.append(e)
    out = []
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        for e, (needs, reason) in zip(batch, check_batch(batch, client)):
            if needs:
                out.append({**e, "needs_reason": reason})
    return out
