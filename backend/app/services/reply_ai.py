"""Reply drafts with the Groq model.

The user opens one email and asks for a draft; the model reads who sent it,
the subject and its text (quoted earlier mail cut off), the thread's earlier
messages kept short, and writes the reply the user would send, in the tone
and length they pick. The draft is only returned: the user edits and sends it
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
# The user's choice of how the reply sounds; the first of each is the default.
TONES = ("friendly", "formal")
LENGTHS = ("short", "detailed")
# Earlier mail in the thread, newest kept first when it does not all fit.
THREAD_MESSAGES = 5
THREAD_EACH = 600
THREAD_CHARS = 2500

_SYSTEM = (
    "You write email replies for the user. You get one email they received: who sent it, "
    "the subject and its text. Write the reply the user would send. Answer what the email "
    "asks, in plain and polite language, in the same language as the email. Write in the "
    "tone and length the user picks. Friendly: warm and relaxed, contractions are fine. "
    "Formal: polite and professional, no slang or contractions. Short: under 80 words. "
    "Detailed: 100 to 180 words, each point the email raises answered in full sentences; "
    "never add plans, offers or promises just to make it longer. Keep track of who asks "
    "whom: when the sender asks the user to do something, say whether the user will. "
    "When the email asks the user to pick between options, do not pick: put them in "
    "square brackets, like [a room or online]. You may also get "
    "earlier messages of the thread, oldest first: use them to know what was already said "
    "and agreed, but reply to the newest email only and do not repeat what is settled. Never make up facts, dates, times, "
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


def clean_style(style: dict | None) -> dict:
    """{"tone", "length"}, anything unknown replaced by the default."""
    style = style or {}
    return {"tone": style.get("tone") if style.get("tone") in TONES else TONES[0],
            "length": style.get("length") if style.get("length") in LENGTHS else LENGTHS[0]}


def email_text(email: dict) -> str:
    return strip_quoted(email.get("body_text") or "") or str(email.get("snippet") or "").strip()


def thread_context(earlier: list[dict] | None) -> list[str]:
    """The earlier messages, [{"from", "text"}] oldest first, as prompt blocks.
    Each is cut short; when they do not all fit, the oldest are left out."""
    blocks: list[str] = []
    used = 0
    for item in reversed((earlier or [])[-THREAD_MESSAGES:]):
        text = str((item or {}).get("text") or "").strip()[:THREAD_EACH] if isinstance(item, dict) else ""
        if not text:
            continue
        block = f"From: {item.get('from') or ''}\n{text}"
        if used + len(block) > THREAD_CHARS:
            break
        used += len(block)
        blocks.insert(0, block)
    return blocks


def prompt(email: dict, owner_name: str = "", note: str = "", previous: str = "",
           style: dict | None = None, thread: list[dict] | None = None) -> str:
    text = email_text(email)
    style = clean_style(style)
    lines = [
        f"From: {email.get('sender', '')}",
        f"Subject: {email.get('subject', '')}",
        f"The user's name: {owner_name or 'not given'}",
        f"Tone: {style['tone']}",
        f"Length: {style['length']}",
    ]
    note = " ".join(str(note or "").split())[:NOTE_CHARS]
    if note:
        lines.append(f"What the user wants to say: {note}")
    blocks = thread_context(thread)
    if blocks:
        lines += ["", "Earlier in this thread (oldest first):", "\n\n".join(blocks)]
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


def draft_reply(email: dict, owner_name: str = "", note: str = "", previous: str = "",
                style: dict | None = None, thread: list[dict] | None = None, client=None) -> dict:
    """{"text", "needs_reply", "options"}; AIUnavailable when the model fails or
    writes nothing. `previous`, when given, is the draft the user asked to
    redraft; `thread` is the earlier messages, oldest first."""
    temperature = REDRAFT_TEMPERATURE if clean_reply(previous) else 0
    data = _ask(_SYSTEM, prompt(email, owner_name, note, previous, style, thread), client, temperature)
    text = clean_reply(data.get("reply"))
    if not text:
        raise AIUnavailable("Couldn't write a reply for this email. Try again.")
    return {"text": text, "needs_reply": data.get("needs_reply") is not False,
            "options": clean_options(data.get("options"), note)}
