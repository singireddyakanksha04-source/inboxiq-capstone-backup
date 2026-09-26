"""Due dates and deadlines pulled out of stored mail. Owner: Akanksha.

extract_due_date looks for a phrase like "payment due by Oct 3", "expires on
10/03/2026", "renews on October 3, 2026" or "ends tomorrow" in the subject,
snippet and body, and returns (ISO date, short label) or None. Relative words
(today/tonight/tomorrow) are read against the email's own date.

Only some categories are scanned. Promotions say "ends today" in almost every
email and one-time codes "expire in 10 minutes", so those would just be noise.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from app.models.email import EmailMessage

# Categories worth scanning. Relative dates (today/tomorrow) are only trusted
# for bill and subscription mail, where they are almost always a real due date.
DUE_CATEGORIES = {"bill", "subscription", "receipt", "alert", "personal", "other"}
_RELATIVE_CATEGORIES = {"bill", "subscription"}

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH = (
    r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_WEEKDAY = r"(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*,?\s+)?"
_DAY = r"(?P<day>[0-3]?\d)(?:st|nd|rd|th)?"
_YEAR = r"(?P<year>20\d{2})"

# Each alternative sets its own named groups; _to_date works out which matched.
_DATE = (
    r"(?:" + _WEEKDAY + r"(?:"
    rf"{_MONTH}\s+{_DAY}(?:,?\s+{_YEAR})?"                       # Oct 3, 2026
    rf"|{_DAY.replace('day', 'day2')}\s+(?:of\s+)?{_MONTH.replace('mon', 'mon2')},?\s*(?:{_YEAR.replace('year', 'year2')})?"  # 3 October 2026
    r"|(?P<iy>20\d{2})-(?P<im>[01]?\d)-(?P<id>[0-3]?\d)"          # 2026-10-03
    r"|(?P<nm>[01]?\d)/(?P<nd>[0-3]?\d)(?:/(?P<ny>(?:20)?\d{2}))?"  # 10/03/2026, 10/3
    r"|(?P<rel>today|tonight|tomorrow)"
    r"))\b"
)

# (label, lead-in phrase). The date has to follow the phrase within a few words.
_LEADS: list[tuple[str, str]] = [
    ("Payment due", r"(?:payment|amount|balance|bill|minimum payment|autopay|payment date)\s+(?:is\s+)?(?:due|scheduled)"),
    ("Payment due", r"(?:due date|pay(?:ment)? by|please pay)"),
    ("Renews", r"(?:auto-?)?renew(?:s|al date|al)?|next (?:billing|payment|charge) (?:date|on)|will be (?:charged|billed)|trial ends"),
    ("Expires", r"expir(?:es|ing|y date|ation date|ation|e)|valid (?:until|through|thru)"),
    ("Event", r"(?:event|webinar|session|class|meeting|interview|appointment|orientation|conference)\s+(?:is\s+|will be\s+)?(?:on|scheduled for|starts)"),
    ("Deadline", r"deadline|last day to(?:\s+\w+){0,2}?|due|closes|(?:apply|register|enrol+|submit|respond|rsvp|sign up)(?:\s+[\w-]+){0,6}?\s+(?:by|before)"),
    ("Expires", r"(?:offer|sale|deal|promotion|discount) ends|ends"),
]
_GAP = r"(?:[\s:,.\-]+|\b(?:on|by|of|is|at|for|before|until|date|the|will|be)\b)*"
_PATTERNS = [
    (label, re.compile(rf"\b(?:{lead}){_GAP}{_DATE}", re.I)) for label, lead in _LEADS
]

_URL_RE = re.compile(r"<?https?://\S+>?")
_SPACE_RE = re.compile(r"[\s͏​-‍⁠﻿­]+")


def _clean(text: str) -> str:
    return _SPACE_RE.sub(" ", _URL_RE.sub(" ", text or "")).strip()


def _year(raw: str | None, month: int, day: int, sent: date) -> int:
    if raw:
        return int(raw) + 2000 if len(raw) == 2 else int(raw)
    # No year: take the sent year, rolling over when that lands well before
    # the email (a December email saying "due Jan 5").
    try:
        guess = date(sent.year, month, day)
    except ValueError:
        return sent.year
    return sent.year + 1 if guess < sent - timedelta(days=60) else sent.year


def _to_date(m: re.Match, sent: date) -> date | None:
    g = m.groupdict()
    try:
        if g["rel"]:
            return sent + timedelta(days=1) if g["rel"].lower() == "tomorrow" else sent
        if g["mon"] or g["mon2"]:
            month = _MONTHS[(g["mon"] or g["mon2"]).lower()[:3]]
            day = int(g["day"] or g["day2"])
            return date(_year(g["year"] or g["year2"], month, day, sent), month, day)
        if g["iy"]:
            return date(int(g["iy"]), int(g["im"]), int(g["id"]))
        if g["nm"]:
            month, day = int(g["nm"]), int(g["nd"])
            return date(_year(g["ny"], month, day, sent), month, day)
    except ValueError:
        return None
    return None


def extract_due_date(email: EmailMessage) -> tuple[str, str] | None:
    """(ISO date, label) for the first due date found, else None."""
    if email.category not in DUE_CATEGORIES:
        return None
    sent = (email.date or datetime.now(timezone.utc)).date()
    allow_relative = email.category in _RELATIVE_CATEGORIES

    # Subject first, then snippet, then the top of the body — the earliest
    # mention is usually the one the email is about.
    for part in (email.subject, email.snippet, email.body_text[:4000]):
        text = _clean(part)
        if not text:
            continue
        hits = []
        for label, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                if m.group("rel") and not allow_relative:
                    continue
                when = _to_date(m, sent)
                # Dates far in the past or years out are card numbers, fine
                # print, or old references rather than something to act on.
                if when and sent - timedelta(days=7) <= when <= sent + timedelta(days=400):
                    hits.append((m.start(), label, when))
                    break
        if hits:
            _, label, when = min(hits)
            if email.category == "bill" and label == "Deadline":
                label = "Payment due"
            return when.isoformat(), label
    return None
