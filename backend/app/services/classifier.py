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
    "alert",
    "security",
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
    ("otp", r"\b(one[- ]time (pass)?code|verification code|temporary (access )?code|otp|\b\d{6}\b is your)\b"),
    (
        "security",
        r"\b(new device|new sign-?in|signed in (to|from)|verify it'?s you|"
        r"security alert|suspicious (login|activity)|shared (your|some).*data|"
        r"account access|someone (used|is using) your)\b",
    ),
    ("shipping", r"\b(shipped|out for delivery|tracking number|arriving|delivered)\b"),
    ("receipt", r"\b(receipt|order confirm|your order|thanks for your (order|purchase)|invoice paid)\b"),
    ("bill", r"\b(payment due|amount due|statement is ready|autopay|past due|invoice)\b"),
    ("subscription", r"\b(renew(s|al|ed)?|free trial|billing cycle|membership|plan will)\b"),
    (
        "alert",
        r"\b(new listing|price drop|saved search|search alert|top match|"
        r"job match(es)?|new job(s)? for you|now hiring|recommended for you|"
        r"based on your (recent )?(activity|search))\b",
    ),
    ("promotion", r"(\b\d{1,2}% off\b|sale ends|limited time|deal|coupon|promo code|shop now|save big)"),
    ("newsletter", r"\b(newsletter|this week in|digest|unsubscribe from our list|issue #)\b"),
]

# Sender domains that are reliably one category regardless of body wording —
# listing/monitoring platforms don't always say "alert" in the email itself,
# and newsletter senders don't always say "newsletter".
_ALERT_DOMAINS = ("realtor.com", "cars.com", "carfax.com", "imotors.com", "ziprecruiter.com", "remotehunter.com")
_NEWSLETTER_DOMAINS = ("beehiiv.com", "substack.com", "convertkit.com")


class RuleClassifier:
    """Header/keyword baseline. Cheap, deterministic, surprisingly hard to beat
    on transactional mail — which is exactly why it is the control group."""

    name = "rules"

    def classify(self, email: EmailMessage) -> tuple[str, float]:
        # Gmail's own category labels are strong evidence when present.
        if "CATEGORY_PERSONAL" in email.labels:
            return "personal", 0.5

        blob = f"{email.subject}\n{email.snippet}\n{email.body_text[:2000]}".lower()
        for category, pattern in _RULES:
            if re.search(pattern, blob):
                return category, 0.7

        domain = email.sender_domain.lower()
        if any(domain.endswith(d) for d in _ALERT_DOMAINS):
            return "alert", 0.55
        if any(domain.endswith(d) for d in _NEWSLETTER_DOMAINS):
            return "newsletter", 0.55
        if "CATEGORY_PROMOTIONS" in email.labels:
            return "promotion", 0.6

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


# ------------------------------------------------ promotion subcategories

_PROMO_SUBCATS: list[tuple[str, str]] = [
    ("travel", r"\b(flight|hotel|resort|vacation|booking\.com|airbnb|itinerary|airfare)\b"),
    ("food", r"\b(restaurant|delivery|doordash|uber eats|grubhub|recipe|menu|dining)\b"),
    ("groceries", r"\b(grocery|groceries|instacart|supermarket|produce)\b"),
    ("electronics", r"\b(laptop|phone|electronics|headphones|tv|gadget|charger)\b"),
    ("clothing", r"\b(clothing|apparel|shoes|dress|sneakers|fashion|wardrobe)\b"),
    ("entertainment", r"\b(movie|concert|streaming|tickets|show|game pass|subscription box)\b"),
    ("finance", r"\b(credit card|loan|apr|cashback|invest(ment)?|bank(ing)?)\b"),
    ("shopping", r"\b(shop now|sale|deal|coupon|promo code|discount|% off)\b"),
]


def extract_promo_subcategory(email: EmailMessage) -> str | None:
    """Second-pass, rules-based split of the broad 'promotion' bucket into the
    finer categories the proposal asks for, so users don't have to open every
    promo email to tell a travel deal from a clothing sale."""
    blob = f"{email.subject}\n{email.snippet}\n{email.body_text[:2000]}".lower()
    for subcat, pattern in _PROMO_SUBCATS:
        if re.search(pattern, blob):
            return subcat
    return None


# --------------------------------------------------- subscription extraction

_AMOUNT_RE = re.compile(r"\$\s?\d+(?:\.\d{2})?")
_CYCLE_RE = re.compile(r"\b(monthly|annual(?:ly)?|yearly|per month|per year|free trial)\b", re.I)
_RENEWAL_RE = re.compile(
    r"(renews?\s+on|next billing date|renewal date|your trial ends|billed on)\s*[:\-]?\s*(.{0,30})",
    re.I,
)

_STOPWORDS = {"the", "team", "inc", "no-reply", "noreply", "support", "billing"}


def _guess_service_name(email: EmailMessage) -> str:
    name = email.sender.split("<")[0].strip().strip('"')
    if name and name.lower() not in _STOPWORDS:
        return name
    return email.sender_domain.split(".")[0].capitalize()


def extract_subscription_info(email: EmailMessage) -> dict:
    """Rules-based pull of service/amount/cycle/renewal hint from a
    category == 'subscription' email. No LLM call — same free-baseline
    philosophy as RuleClassifier."""
    blob = f"{email.subject}\n{email.snippet}\n{email.body_text[:2000]}"

    amount_match = _AMOUNT_RE.search(blob)
    cycle_match = _CYCLE_RE.search(blob)
    renewal_match = _RENEWAL_RE.search(blob)

    cycle = None
    if cycle_match:
        raw = cycle_match.group(1).lower()
        if "trial" in raw:
            cycle = "trial"
        elif "year" in raw or "annual" in raw:
            cycle = "yearly"
        else:
            cycle = "monthly"

    return {
        "sub_service": _guess_service_name(email),
        "sub_amount": amount_match.group(0) if amount_match else None,
        "sub_cycle": cycle,
        "sub_renewal_hint": renewal_match.group(2).strip() if renewal_match else None,
    }


def get_classifier(backend: str = "rules") -> Classifier:
    """backend: 'rules' | 'small' | 'large' | 'oss' | a raw Groq model id."""
    if backend == "rules":
        return RuleClassifier()
    return GroqClassifier(model=MODELS.get(backend, backend))
