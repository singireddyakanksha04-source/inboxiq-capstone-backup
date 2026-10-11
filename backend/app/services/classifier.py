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
    # Payment problems, transfers and status notices. First, because bank
    # templates carry bill words ("autopay") in every footer.
    (
        "alert",
        r"\bzelle\b|couldn[’']?t (complete|process) your (online )?payment|"
        r"payment (failed|declined|was declined|was unsuccessful|could not be processed)|"
        r"\btracked (flight|price)s?\b|price (alert|tracking)|"
        r"application (received|submitted)|thank you for (applying|your application)|"
        r"registration status",
    ),
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
        r"account access|someone (used|is using) your|"
        r"password (was |has been )?(successfully )?(reset|changed|updated)|reset your password|"
        r"confirm (this |recent |your )?activity|fraud alert|unusual activity)\b",
    ),
]

_PROMO_PATTERN = (
    r"(\b\d{1,2}% off\b|sale ends|limited time|\bdeals?\b|coupon|promo code|"
    r"shop now|save big|\bclearance\b|\bsave (today|now)\b|for \$0(\.00)?\b|\b\d+ months? of \w+( \w+)? for (free|\$0)|"
    r"try (\w+ )?premium|save up to|only \d+ \w+ left|fees? waived)"
)

_BILL_PATTERN = (
    r"\b(payment due|amount due|statement is (now )?(ready|available)|"
    r"autopay|past due|minimum payment|(new|your) invoice|"
    r"invoice (is )?(available|attached|due|#))\b"
)

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
    ("receipt", r"\b(receipt|order confirm(ed|ation)?|your order|thanks for your (order|purchase)|invoice paid)\b"),
    ("bill", _BILL_PATTERN),
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
        r"subscription (confirmation|receipt|renewal|cancell?ation|has been)|"
        r"subscription is (now )?(ready|active))\b",
    ),
    (
        "alert",
        r"\b(new listing|price drop|saved search|search alert|top match|"
        r"job match(es)?|new job(s)? for you|now hiring|recommended for you|"
        r"based on your (recent )?(activity|search))\b",
    ),
    ("promotion", _PROMO_PATTERN),
    (
        "newsletter",
        r"\b(newsletter|this week in|digest|unsubscribe from our list|issue #|"
        r"weekly (\w+ )?(news|roundup|recap))\b",
    ),
]

# A payment receipt for something that recurs (a plan, a membership, a
# billing period) is a subscription, not a one-off receipt. Both halves must
# match: "total charged" alone is a ride or an order, and "subscription"
# alone is sales copy.
_PAID_RE = re.compile(
    r"\b(receipt|amount paid|total charged|invoice (has been )?paid|has been paid|"
    r"payment (received|successful|confirmation|was successful|has been processed)|"
    r"thanks for your payment|(we|you('ve| have)? been|you were) (charged|billed))\b"
)
_RECURRING_RE = re.compile(
    r"\b((monthly|annual|yearly) (plan|subscription|membership|fee|billing|charge)|"
    r"per (month|year)|recurring|auto-?renew\w*|renews?|"
    r"billed (monthly|annually|yearly|every)|next (billing|payment|charge)|"
    r"billing (period|cycle)|subscription|membership)\b"
    r"|\$\d[\d,.]*\s?/\s?(mo|month|yr|year)\b"
)
# "Sep 3 - Oct 3, 2026" or "09/03/2026 - 10/03/2026": the period a charge covers.
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_PERIOD_RANGE_RE = re.compile(
    rf"\b{_MON} (\d{{1,2}})(?:,? (\d{{4}}))?\s*(?:-|–|—|to)\s*{_MON} (\d{{1,2}}),? (\d{{4}})\b"
    r"|\b(\d{1,2})/(\d{1,2})/(\d{4})\s*(?:-|–|—|to)\s*(\d{1,2})/(\d{1,2})/(\d{4})\b",
    re.I,
)


def _is_recurring_charge(text: str) -> bool:
    return bool(_PAID_RE.search(text)) and bool(
        _RECURRING_RE.search(text) or _PERIOD_RANGE_RE.search(text)
    )


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


_MARKETING_SUBDOMAINS = {"marketing", "promo", "promos", "promotions", "offers", "mailer", "deals"}
# Only phrases a person wouldn't write to a friend; "great deal on the
# couch" from a friend stays personal.
_AD_PHRASE_RE = re.compile(
    r"\b\d{1,2}% off\b|promo code|coupon|shop now|limited time|save up to|"
    r"only \d+ \w+ left|fees? waived|unsubscribe"
)


def _looks_like_marketing(domain: str, head: str) -> bool:
    first = domain.split(".")[0] if domain.count(".") >= 2 else ""
    return first in _MARKETING_SUBDOMAINS or bool(_AD_PHRASE_RE.search(head))


class RuleClassifier:
    """Header/keyword baseline. Cheap, deterministic, surprisingly hard to beat
    on transactional mail — which is exactly why it is the control group."""

    name = "rules"

    def classify(self, email: EmailMessage) -> tuple[str, float]:
        blob = f"{email.subject}\n{email.snippet}\n{email.body_text[:2000]}".lower()
        for category, pattern in _URGENT_RULES:
            if re.search(pattern, blob):
                return category, 0.7

        domain = email.sender_domain.lower()
        head = f"{email.subject}\n{email.snippet}".lower()
        # Gmail's own category labels are strong evidence when present, but
        # Gmail also files some marketing as Personal (lease offers, mail from
        # marketing.* senders); that is treated like the Promotions tab.
        bulk_personal = False
        if "CATEGORY_PERSONAL" in email.labels:
            if not _looks_like_marketing(domain, head):
                return "personal", 0.5
            bulk_personal = True

        social = _social_category(email, domain)
        if social:
            return social, 0.6

        # On mail Gmail files as Promotions, bill/subscription words deep in
        # the body are fine print ("membership is required", "subscription
        # auto-renews at ..."), so those two only count in subject/preview.
        promo_tab = "CATEGORY_PROMOTIONS" in email.labels or bulk_personal
        listing = _matches(domain, _LISTING_DOMAINS)
        # Card statements say "payment received" and "next payment" too;
        # those stay bills.
        charge_text = head if promo_tab else blob
        if _is_recurring_charge(charge_text) and not re.search(_BILL_PATTERN, charge_text):
            return "subscription", 0.7
        for category, pattern in _RULES:
            if category == "shipping" and listing:
                continue
            if category == "alert" and promo_tab:
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
    ("travel", r"\b(flights?|hotels?|resorts?|vacations?|booking\.com|airbnb|itinerary|airfares?)\b"),
    ("food", r"\b(restaurant|delivery|doordash|uber eats|grubhub|recipe|menu|dining)\b"),
    ("groceries", r"\b(grocery|groceries|instacart|supermarket|produce)\b"),
    ("electronics", r"\b(laptop|phone|electronics|headphones|tv|gadget|charger)\b"),
    ("clothing", r"\b(clothing|apparel|shoes|dress|sneakers|fashion|wardrobe)\b"),
    ("entertainment", r"\b(movie|concert|streaming|tickets|show|game pass|subscription box)\b"),
    ("education", r"\b(courses?|bootcamps?|udemy|coursera|certificat\w*|masterclass|tutorials?|learning)\b"),
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

# "$9.99", "US$9.99", "USD 12.00", "$1,299.00", or a bare "9.99" that is
# followed by a currency word or a billing period ("9.99 per month").
_NUM = r"\d{1,4}(?:,\d{3})*"
_AMOUNT_RE = re.compile(
    rf"(?:US\$|\$|\bUSD\s?)\s?({_NUM}(?:\.\d{{2}})?)(?![\d,])"
    rf"|(?<![\d.,$])({_NUM}\.\d{{2}})(?=\s?(?:USD|dollars|/\s?mo|/\s?yr|per\s|a\s(?:month|year)))",
    re.I,
)
# Billing period written right after the amount: "/mo", " per month", " a year".
_PERIOD_RE = re.compile(
    r"\s?(?:USD|dollars)?\s?(?:/|per|a|each)\s?(mo|month|yr|year|annum)\b", re.I
)
# Words near an amount that say it is the actual charge vs. a promo figure.
_CHARGE_RE = re.compile(
    r"\b(charged?|billed|billing|total|amount|payment|paid|price|renew\w*|"
    r"subscription|plan|membership|due)\b",
    re.I,
)
_PROMO_RE = re.compile(r"\b(save|off|discount|credit|gift|reward|cash ?back|up to)\b", re.I)

_CYCLE_RE = re.compile(r"\b(monthly|annual(?:ly)?|yearly|per month|per year|free trial)\b", re.I)
_RENEWAL_RE = re.compile(
    r"(renews?\s+on|next billing date|renewal date|your trial ends|billed on)\s*[:\-]?\s*(.{0,30})",
    re.I,
)

_STOPWORDS = {"the", "team", "inc", "no-reply", "noreply", "support", "billing"}
# Trailing words that make "Netflix Account" look like a different service.
_NAME_NOISE = {
    "account", "accounts", "billing", "team", "support", "payments", "receipts",
    "notifications", "no-reply", "noreply", "members", "membership", "inc", "llc",
}


_LEGAL_SUFFIX_RE = re.compile(r",?\s+(inc|llc|ltd|limited|pbc|corp|corporation|gmbh|co)\.?$", re.I)
_TIERS = (
    r"(Pro|Plus|Premium|Max|Team|Teams|Family|Individual|Basic|Standard|Student|"
    r"Duo|Business|Enterprise)"
)
# Tier names are matched case-sensitively: "Netflix Standard" is a plan,
# "Netflix standard features" is not.
# Capitalised words before a tier that describe the offer, not the product
# ("Free Trial Enterprise", "Your Plus").
_NOT_PRODUCT_WORDS = {
    "free", "trial", "your", "the", "our", "this", "new", "plan", "subscription",
    "total", "monthly", "annual", "yearly", "upgrade", "get", "try", "start",
}
_PRODUCT_TIER_RE = re.compile(rf"(?<![Tt]he )\b([A-Z][\w+]*(?: [A-Z][\w+]*)?) {_TIERS}\b")


def _domain_name(domain: str) -> str:
    # members.netflix.com -> "netflix": the label before the TLD, not the
    # first; netflix.co.uk -> "netflix", not "co".
    labels = domain.lower().split(".")
    if len(labels) > 2 and labels[-2] in {"co", "com", "org", "net", "ac", "gov", "edu"}:
        labels.pop()
    return labels[-2] if len(labels) > 1 else labels[0]


def _guess_service_name(email: EmailMessage, text: str = "") -> str:
    """Service a subscription email is about. A product and plan named in
    the email ("Spotify Premium") wins, since the sender is often the
    company, an app store or a payment processor rather than the product;
    otherwise the sender's display name without legal suffixes."""
    domain = _domain_name(email.sender_domain or "")
    display = email.sender.split("<")[0].strip().strip('"')
    if "@" in display:  # bare address, no display name
        display = ""
    display = _LEGAL_SUFFIX_RE.sub("", display).strip(" ,")
    display = re.sub(r"\.(io|com|ai|app|so|co|net|org|dev)$", "", display, flags=re.I)
    words = display.split()
    while words and words[-1].lower().strip(".,") in _NAME_NOISE:
        words.pop()
    name = " ".join(words)
    if not name or name.lower() in _STOPWORDS:
        name = domain.capitalize()

    # "(?<!the )": "The Cypress Team" is a sign-off, not a Team plan.
    m = re.search(rf"(?<![Tt]he )\b{re.escape(name)} {_TIERS}\b", text)
    if m:
        return f"{name} {m.group(1)}"
    for m in _PRODUCT_TIER_RE.finditer(text):
        if not set(m.group(1).lower().split()) & _NOT_PRODUCT_WORDS:
            return f"{m.group(1)} {m.group(2)}"
    return name


def _pick_amount(blob: str) -> tuple[float, str | None] | None:
    """Best-scoring charge amount in the text, with the billing period written
    next to it if any. Promo figures ("save $20", "$5 off") lose to amounts
    near billing words; if only promo figures are present, nothing is returned."""
    best = None
    for m in _AMOUNT_RE.finditer(blob):
        value = float((m.group(1) or m.group(2)).replace(",", ""))
        if value == 0:  # "$0.00 due today" on a trial is not the price
            continue
        before = blob[max(0, m.start() - 50) : m.start()]
        after = blob[m.end() : m.end() + 20]
        period = _PERIOD_RE.match(after)
        score = 0
        if period:
            score += 2
        if _CHARGE_RE.search(before):
            score += 1
        if _PROMO_RE.search(blob[max(0, m.start() - 20) : m.start()]) or re.match(
            r"\s?off\b", after, re.I
        ):
            score -= 2
        if score >= 0 and (best is None or score > best[0]):
            best = (score, value, period.group(1).lower() if period else None)
    return (best[1], best[2]) if best else None


def _cycle_from_period(text: str) -> str | None:
    """monthly/yearly from the billing period a receipt covers."""
    from datetime import date

    m = _PERIOD_RANGE_RE.search(text)
    if not m:
        return None
    g = m.groups()
    try:
        if g[0]:
            months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
            end = date(int(g[5]), months.index(g[3][:3].lower()) + 1, int(g[4]))
            start = date(int(g[2] or g[5]), months.index(g[0][:3].lower()) + 1, int(g[1]))
            if start > end:  # "Dec 3 - Jan 3, 2027"
                start = start.replace(year=start.year - 1)
        else:
            start = date(int(g[8]), int(g[6]), int(g[7]))
            end = date(int(g[11]), int(g[9]), int(g[10]))
    except ValueError:
        return None
    days = (end - start).days
    if 26 <= days <= 32:
        return "monthly"
    if 360 <= days <= 370:
        return "yearly"
    return None


def extract_subscription_info(email: EmailMessage) -> dict:
    """Rules-based pull of service/amount/cycle/renewal hint from a
    category == 'subscription' email. No LLM call — same free-baseline
    philosophy as RuleClassifier."""
    blob = f"{email.subject}\n{email.snippet}\n{email.body_text[:2000]}"

    amount = _pick_amount(blob)
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
    if cycle is None:
        cycle = _cycle_from_period(blob)
    # A period written on the amount itself ("$99/yr") beats a cycle word
    # found elsewhere in the email, except for trials.
    if amount and amount[1] and cycle != "trial":
        cycle = "monthly" if amount[1].startswith("mo") else "yearly"

    return {
        "sub_service": _guess_service_name(email, blob),
        "sub_amount": f"${amount[0]:,.2f}" if amount else None,
        "sub_cycle": cycle,
        "sub_renewal_hint": renewal_match.group(2).strip() if renewal_match else None,
    }


def get_classifier(backend: str = "rules") -> Classifier:
    """backend: 'rules' | 'small' | 'large' | 'oss' | a raw Groq model id."""
    if backend == "rules":
        return RuleClassifier()
    return GroqClassifier(model=MODELS.get(backend, backend))
