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

# Codes and account-safety mail. Checked before everything else, even Gmail's
# Personal label, because a reset code from a sender Gmail files as personal
# is still a code.
_URGENT_RULES: list[tuple[str, str]] = [
    (
        "otp",
        r"\b(one[- ]time (pass)?code|verification code|temporary (access )?code|"
        r"(password )?reset code|security code|log-?in code|sign-?in code|"
        r"otp|\b\d{6}\b is your)\b",
    ),
    (
        "security",
        r"\b(new device|new sign-?in|signed in (to|from)|verify it'?s you|"
        r"security alert|suspicious (login|activity)|shared (your|some).*data|"
        r"account access|someone (used|is using) your)\b",
    ),
]

_RULES: list[tuple[str, str]] = [
    # Needs a parcel/order in the sentence: a bare "delivered" or "arriving"
    # also shows up in car ads ("new inventory arriving") and product news
    # ("we shipped ...").
    (
        "shipping",
        r"\b(out for delivery|tracking (number|id|#|info\w*|link)|"
        r"track (your )?(package|order|shipment|parcel|delivery)|"
        r"(package|order|shipment|parcel|item)s? (has |have |was |were |is |are )?"
        r"(been )?(shipped|delivered|on (its|the) way|arriving|out for delivery)|"
        r"(has|have) shipped|delivery (update|attempt|exception)|"
        r"arriving (today|tomorrow|on (mon|tue|wed|thu|fri|sat|sun)))\b",
    ),
    ("receipt", r"\b(receipt|order confirm|your order|thanks for your (order|purchase)|invoice paid)\b"),
    (
        "bill",
        r"\b(payment due|amount due|statement is ready|statement is available|"
        r"autopay|past due|minimum payment|(new|your) invoice|"
        r"invoice (is )?(available|attached|due|#))\b",
    ),
    # Lifecycle of a subscription the user already has. Plain "membership" or
    # "annual subscription" is also sales copy and fine print on deal mail.
    (
        "subscription",
        r"\b(renews? (on|automatically|soon|in \d+ days)|auto-?renew(al|s|ed)? (on|is|will|notice)|"
        r"renewal (date|notice|reminder|confirmation)|"
        r"(your )?(free )?trial (ends|is ending|will end|expires|has ended|ending soon)|"
        r"billing cycle|next billing date|"
        r"(your|the) (plan|subscription|membership) (has been |was |is |will be |will )?"
        r"(renewed|renews|cancell?ed|expired|expires|expiring|ending|ends|paused|"
        r"activated|confirmed|started)|"
        r"plan will (renew|end|expire|change)|"
        r"subscription (confirmation|receipt|renewal|cancell?ation|has been))\b",
    ),
    (
        "alert",
        r"\b(new listing|price drop|saved search|search alert|top match|"
        r"job match(es)?|new job(s)? for you|now hiring|recommended for you|"
        r"based on your (recent )?(activity|search))\b",
    ),
    (
        "promotion",
        r"(\b\d{1,2}% off\b|sale ends|limited time|\bdeals?\b|coupon|promo code|"
        r"shop now|save big|\bclearance\b|\bsave (today|now)\b|for \$0(\.00)?\b|\b\d+ months? of \w+( \w+)? for (free|\$0)|"
        r"try (\w+ )?premium)",
    ),
    (
        "newsletter",
        r"\b(newsletter|this week in|digest|unsubscribe from our list|issue #|"
        r"weekly (\w+ )?(news|roundup|recap))\b",
    ),
]

# Account notices and event confirmations. Only used when nothing above
# matched and Gmail did not file the mail under Promotions, since the same
# words ("webinar", "account") are common in marketing.
_NOTICE_RULES: list[tuple[str, str]] = [
    (
        "alert",
        r"\b(available balance|balance (is )?(below|above)|daily (account )?summary|"
        r"zelle|contact information (change|update)|you received a new (letter|document|message)|"
        r"direct deposit|(large|new) (purchase|transaction)|account alert)\b",
    ),
    (
        "alert",
        r"\b(registration (is )?confirmed|you'?re registered|"
        r"confirm your (spot|seat|registration|application)|webinar|webclass|"
        r"event reminder|meetup|rsvp)\b",
    ),
]

# Shipping words from these senders are car/home listings ("new inventory
# arriving", "price drop"), never a parcel.
_LISTING_DOMAINS = (
    "realtor.com", "zillow.com", "cars.com", "carfax.com", "imotors.com",
    "autotrader.com", "cargurus.com", "carvana.com", "truecar.com", "edmunds.com",
    "openauto.com",
)

# Sender domains that are reliably one category regardless of body wording —
# listing/monitoring platforms don't always say "alert" in the email itself,
# and newsletter senders don't always say "newsletter".
_ALERT_DOMAINS = (
    "realtor.com", "cars.com", "carfax.com", "imotors.com", "ziprecruiter.com",
    "remotehunter.com", "autotrader.com", "cargurus.com", "indeed.com",
    "glassdoor.com",
)
_NEWSLETTER_DOMAINS = (
    "beehiiv.com", "substack.com", "convertkit.com", "kaggle.com",
    "freecodecamp.org", "medium.com", "bytebytego.com",
)

# Social and developer platforms: notifications about the user (invites,
# mentions, profile views, jobs, activity) are alerts; feed posts and
# article digests are newsletters. Checked before the keyword rules because
# these mails quote other people's posts, which trip random keywords.
_SOCIAL_DOMAINS = (
    "linkedin.com", "facebookmail.com", "x.com", "twitter.com", "instagram.com",
    "github.com", "gitlab.com", "slack.com", "discord.com",
)
_SOCIAL_FEED = re.compile(
    r"\b(recently posted|reshared|shared a post|posted:|is popular|trending|"
    r"top (posts|stories)|newsletter|digest|article|edition)\b"
)
_SOCIAL_ALERT = re.compile(
    r"\b(jobs?|hiring|hired|openings?|applied|application|"
    r"invit(e|ed|ation)s?|you may know|connect(ion)?s?|viewed your|"
    r"appeared in \d+ searche?s?|mentioned you|tagged you|replied|commented|"
    r"message|follow(ed|er)s?|notifications?|pull request|issue|review|"
    r"build|workflow|security)\b"
)


def _matches(domain: str, domains: tuple[str, ...]) -> bool:
    """em.cars.com matches cars.com; notcars.com does not."""
    return any(domain == d or domain.endswith("." + d) for d in domains)


def _social_category(email: EmailMessage, domain: str) -> str | None:
    if not _matches(domain, _SOCIAL_DOMAINS):
        return None
    subject = email.subject.lower()
    if _SOCIAL_ALERT.search(subject):
        return "alert"
    if _SOCIAL_FEED.search(subject) or _matches(domain, ("linkedin.com",)):
        # LinkedIn mail that isn't about the user is feed/news content, but
        # Gmail's Promotions label (sponsored rankings, ads) still wins.
        if "CATEGORY_PROMOTIONS" in email.labels:
            return None
        return "newsletter"
    return "alert"


class RuleClassifier:
    """Header/keyword baseline. Cheap, deterministic, surprisingly hard to beat
    on transactional mail — which is exactly why it is the control group."""

    name = "rules"

    def classify(self, email: EmailMessage) -> tuple[str, float]:
        blob = f"{email.subject}\n{email.snippet}\n{email.body_text[:2000]}".lower()
        for category, pattern in _URGENT_RULES:
            if re.search(pattern, blob):
                return category, 0.7

        # Gmail's own category labels are strong evidence when present.
        if "CATEGORY_PERSONAL" in email.labels:
            return "personal", 0.5

        domain = email.sender_domain.lower()
        social = _social_category(email, domain)
        if social:
            return social, 0.6

        # On mail Gmail files as Promotions, bill/subscription words deep in
        # the body are fine print ("membership is required", "subscription
        # auto-renews at ..."), so those two only count in subject/preview.
        promo_tab = "CATEGORY_PROMOTIONS" in email.labels
        head = f"{email.subject}\n{email.snippet}".lower()
        listing = _matches(domain, _LISTING_DOMAINS)
        for category, pattern in _RULES:
            if category == "shipping" and listing:
                continue
            text = head if promo_tab and category in ("bill", "subscription") else blob
            if re.search(pattern, text):
                return category, 0.7

        if _matches(domain, _ALERT_DOMAINS):
            return "alert", 0.55
        if _matches(domain, _NEWSLETTER_DOMAINS):
            return "newsletter", 0.55
        if promo_tab:
            return "promotion", 0.6

        for category, pattern in _NOTICE_RULES:
            if re.search(pattern, blob):
                return category, 0.5

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
