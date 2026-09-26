"""Read emails from Gmail and flatten them into EmailMessage objects."""

from __future__ import annotations

import base64
import re
from email.utils import parsedate_to_datetime, parseaddr
from html import unescape

from app.models.email import EmailMessage
from app.services.gmail_auth import gmail_service


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", " ", html))


def _extract_body(payload: dict) -> str:
    """Walk the MIME tree, preferring text/plain over text/html."""
    plain, html = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            if mime == "text/plain":
                plain.append(_decode(data))
            elif mime == "text/html":
                html.append(_html_to_text(_decode(data)))
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    text = "\n".join(plain) or "\n".join(html)
    return _clean_body_text(text)


_ZERO_WIDTH = re.compile(r"[​‌‍﻿͏]")
_TRACKING_LINK = re.compile(r"\(\s?https?://\S+?\s?\)")


def _clean_body_text(text: str) -> str:
    """Marketing HTML decodes into a lot of noise that hides the signal
    classify/subscription-extraction actually needs: zero-width tracking
    characters, inline tracking-link parens, and runs of blank lines left
    over from stripped table cells."""
    text = _ZERO_WIDTH.sub("", text)
    text = _TRACKING_LINK.sub("", text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _unsubscribe_link(head: dict[str, str]) -> str | None:
    """List-Unsubscribe is a comma-separated list of <...> links, usually a
    mailto and/or an https one. The https link is the better one to hand the
    user (with List-Unsubscribe-Post it is a one-click link), so prefer it."""
    links = re.findall(r"<\s*([^>\s]+)\s*>", head.get("list-unsubscribe", ""))
    web = [u for u in links if u.lower().startswith(("https://", "http://"))]
    web.sort(key=lambda u: not u.lower().startswith("https://"))
    mail = [u for u in links if u.lower().startswith("mailto:")]
    return (web or mail or [None])[0]


def parse_message(raw: dict) -> EmailMessage:
    payload = raw.get("payload", {})
    head = _headers(payload)

    sender = head.get("from", "")
    _, addr = parseaddr(sender)

    date = None
    if head.get("date"):
        try:
            date = parsedate_to_datetime(head["date"])
        except (TypeError, ValueError):
            date = None

    return EmailMessage(
        id=raw["id"],
        thread_id=raw.get("threadId", ""),
        sender=sender,
        sender_email=addr,
        sender_domain=addr.split("@")[-1].lower() if "@" in addr else "",
        to=head.get("to", ""),
        subject=head.get("subject", ""),
        date=date,
        snippet=unescape(raw.get("snippet", "")),
        body_text=_extract_body(payload)[:20000],
        labels=raw.get("labelIds", []),
        list_unsubscribe=_unsubscribe_link(head),
    )


def get_profile(account: str = "default") -> dict:
    return gmail_service(account).users().getProfile(userId="me").execute()


def fetch_messages(
    max_results: int = 10,
    query: str = "in:inbox",
    account: str = "default",
) -> list[EmailMessage]:
    """`query` uses Gmail search syntax, e.g. 'category:promotions newer_than:30d'."""
    svc = gmail_service(account)
    listing = (
        svc.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    out = []
    for stub in listing.get("messages", []):
        raw = (
            svc.users()
            .messages()
            .get(userId="me", id=stub["id"], format="full")
            .execute()
        )
        out.append(parse_message(raw))
    return out
