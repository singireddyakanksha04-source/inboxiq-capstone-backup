"""Reply drafts with the Groq model.

The user opens one email and asks for a draft; the model reads who sent it,
the subject and its text (quoted earlier mail cut off) and writes the reply
the user would send. The draft is only returned: the user edits and sends it
themselves, nothing is sent from here. Same model, prompt and checks as the
extension's reply.js.
"""

from __future__ import annotations

import re

from app.services.personal_ai import AIUnavailable, _ask

TEXT_CHARS = 4000  # longer emails are cut; the start says what is asked
MAX_CHARS = 2000
NOTE_CHARS = 300  # the user's own "what to say", optional
# A first draft is steady; a redraft is told what it wrote before and may vary.
REDRAFT_TEMPERATURE = 0.8
MAX_OPTIONS = 3  # suggested "what to say" choices per draft

_SYSTEM = (
    "You write email replies for the user. You get one email they received: who sent it, "
    "the subject and its text. Write the reply the user would send. Answer what the email "
    "asks, in plain and polite language, in the same language as the email. Keep it short "
    "(under 120 words) unless the email really needs more. Never make up facts, dates, times, "
    "prices, links or promises. Never choose a time, date or option for the user that the "
    "email does not fix already; put what the user has to fill in in square brackets, like "
    "[day and time]. Do not repeat the subject or quote the email. Start with a greeting "
    "that uses the sender's first name if the sender is a person, otherwise just Hello. "
    "End with a short sign-off "
    "and the user's name if it is given, otherwise the sign-off alone. Also say whether the "
    "email needs a reply at all: newsletters, receipts and automatic notices usually do not. "
    "If the user says what they want to say, build the reply around that and follow it "
    "over your own guess. If you are shown an earlier draft, the user wants a different "
    "one: change the wording and structure, but keep to the same rules. Also suggest 2 to 3 "
    "other things the user might want to say instead, as different answers (for example "
    "yes, no, or later), in under 6 words each, like \"Decline politely\".\n"
    'Reply with JSON only: {"reply": <the reply text, paragraphs separated by \\n\\n>, '
    '"needs_reply": <true or false>, "options": [<short string>]}'
)

_ORIGINAL = re.compile(r"^-{2,}\s*original message\s*-{2,}$", re.I)
_WROTE = re.compile(r"^on\b.*\bwrote:$", re.I)


def strip_quoted(text: str) -> str:
    """Only what this email adds, not the earlier mail quoted under it."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if _ORIGINAL.match(line) or _WROTE.match(line):
            break
        # Gmail wraps a long "On ... wrote:" over two lines.
        if re.match(r"^on\b", line, re.I) and i + 1 < len(lines) and lines[i + 1].strip().lower().endswith("wrote:"):
            break
        if line.startswith(">"):
            continue
        kept.append(raw.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def prompt(email: dict, owner_name: str = "", note: str = "", previous: str = "") -> str:
    text = strip_quoted(email.get("body_text") or "") or str(email.get("snippet") or "").strip()
    lines = [
        f"From: {email.get('sender', '')}",
        f"Subject: {email.get('subject', '')}",
        f"The user's name: {owner_name or 'not given'}",
    ]
    note = " ".join(str(note or "").split())[:NOTE_CHARS]
    if note:
        lines.append(f"What the user wants to say: {note}")
    lines += ["", "Email text:", text[:TEXT_CHARS] or "(no text, only the subject)"]
    previous = clean_reply(previous)
    if previous:
        lines += ["", "Earlier draft (write a different one):", previous]
    return "\n".join(lines)


def clean_reply(raw) -> str:
    """Trimmed, line ends and blank-line runs folded, a stray Subject: line
    dropped. Empty when there is nothing usable."""
    text = raw if isinstance(raw, str) else ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^\s*subject:.*\n+", "", text, flags=re.I)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_CHARS]


def clean_options(raw, note: str = "") -> list[str]:
    """Short, no repeats, not what the user already asked for; at most MAX_OPTIONS."""
    asked = " ".join(str(note or "").split())[:NOTE_CHARS].lower()
    out: list[str] = []
    for o in raw if isinstance(raw, list) else []:
        if not isinstance(o, str) or len(out) >= MAX_OPTIONS:
            continue
        text = re.sub(r'[."]+$', "", " ".join(o.split())).lstrip('"')[:60]
        if text and text.lower() != asked and all(x.lower() != text.lower() for x in out):
            out.append(text)
    return out


def draft_reply(email: dict, owner_name: str = "", note: str = "", previous: str = "", client=None) -> dict:
    """{"text", "needs_reply"}; AIUnavailable when the model fails or writes nothing.
    `previous`, when given, is the draft the user asked to redraft."""
    temperature = REDRAFT_TEMPERATURE if clean_reply(previous) else 0
    data = _ask(_SYSTEM, prompt(email, owner_name, note, previous), client, temperature)
    text = clean_reply(data.get("reply"))
    if not text:
        raise AIUnavailable("Couldn't write a reply for this email. Try again.")
    return {"text": text, "needs_reply": data.get("needs_reply") is not False,
            "options": clean_options(data.get("options"), note)}
