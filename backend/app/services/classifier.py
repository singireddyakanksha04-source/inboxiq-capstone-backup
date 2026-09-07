"""Email category classification. Owner: Satwik.

Two backends behind one interface so we can measure a cheap model against an
expensive one on the same inputs:

    rules   - keyword/header heuristics, free, the baseline to beat
    groq    - one LLM call per email on Groq's free tier, model chosen by caller

Both return (category, confidence). Nothing here touches Firestore; the caller
writes the result back via firestore_client.set_category.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

from app.models.email import EmailMessage

CATEGORIES = [
    "promotion",
    "receipt",
    "bill",
    "newsletter",
    "shipping",
    "otp",
    "subscription",
    "personal",
    "other",
]

# Groq model ids we compare. "small" is the cheap-model hypothesis from the
# proposal; "large" is the accuracy ceiling we measure it against.
MODELS = {
    "small": "openai/gpt-oss-20b",
    "large": "openai/gpt-oss-120b",
    "qwen": "qwen/qwen3.8-27b",
}


class Classifier(Protocol):
    name: str

    def classify(self, email: EmailMessage) -> tuple[str, float]: ...


# --------------------------------------------------------------- rules baseline

_RULES: list[tuple[str, str]] = [
    ("otp", r"\b(one[- ]time (pass)?code|verification code|otp|\b\d{6}\b is your)\b"),
    ("shipping", r"\b(shipped|out for delivery|tracking number|arriving|delivered)\b"),
    ("receipt", r"\b(receipt|order confirm|your order|thanks for your (order|purchase)|invoice paid)\b"),
    ("bill", r"\b(payment due|amount due|statement is ready|autopay|past due|invoice)\b"),
    ("subscription", r"\b(renew(s|al|ed)?|free trial|billing cycle|membership|plan will)\b"),
    ("promotion", r"(\b\d{1,2}% off\b|sale ends|limited time|deal|coupon|promo code|shop now|save big)"),
    ("newsletter", r"\b(newsletter|this week in|digest|unsubscribe from our list|issue #)\b"),
]


class RuleClassifier:
    """Header/keyword baseline. Cheap, deterministic, surprisingly hard to beat
    on transactional mail — which is exactly why it is the control group."""

    name = "rules"

    def classify(self, email: EmailMessage) -> tuple[str, float]:
        # Gmail's own category labels are strong evidence when present.
        if "CATEGORY_PROMOTIONS" in email.labels:
            return "promotion", 0.6
        if "CATEGORY_PERSONAL" in email.labels:
            return "personal", 0.5

        blob = f"{email.subject}\n{email.snippet}\n{email.body_text[:2000]}".lower()
        for category, pattern in _RULES:
            if re.search(pattern, blob):
                return category, 0.7
        return "other", 0.3


# ----------------------------------------------------------------- groq backend

_SYSTEM = (
    "You classify emails for an inbox management app. "
    "Return exactly one category from the allowed list. "
    "Judge the email's purpose, not its tone: a marketing message about an "
    "order is still a promotion, and an order confirmation is a receipt even "
    "if it advertises. Use 'other' only when nothing else fits.\n"
    # Groq's JSON mode requires the word JSON and the shape spelled out here.
    "Reply with JSON only, no prose: "
    '{"category": <one of ' + "|".join(CATEGORIES) + '>, '
    '"confidence": <0.0-1.0>, "reason": <short string>}'
)

def _prompt(email: EmailMessage) -> str:
    return (
        f"From: {email.sender}\n"
        f"Subject: {email.subject}\n"
        f"Gmail labels: {', '.join(email.labels)}\n\n"
        f"Body:\n{email.body_text[:4000]}"
    )


class GroqClassifier:
    """One Groq call per email. Groq's JSON mode guarantees parseable output;
    we still clamp the category to CATEGORIES in case the model invents one."""

    def __init__(self, model: str = MODELS["small"]):
        from groq import Groq  # imported lazily so the rules path needs no SDK

        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError(
                "No GROQ_API_KEY. Get a free key at console.groq.com/keys "
                "and put it in .env."
            )
        self.client = Groq()
        self.model = model
        self.name = f"groq:{model}"
        self.last_usage: dict[str, int] = {}

    def classify(self, email: EmailMessage) -> tuple[str, float]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=512,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _prompt(email)},
            ],
        )
        usage = response.usage
        self.last_usage = {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
        }

        data = json.loads(response.choices[0].message.content)
        category = str(data.get("category", "other")).lower()
        if category not in CATEGORIES:
            category = "other"
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        return category, max(0.0, min(1.0, confidence))


def get_classifier(backend: str = "rules") -> Classifier:
    """backend: 'rules' | 'small' | 'large' | 'oss' | a raw Groq model id."""
    if backend == "rules":
        return RuleClassifier()
    return GroqClassifier(model=MODELS.get(backend, backend))
