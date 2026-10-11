"""Cases taken from a read-only pass over real mail (names removed). Each one
was misfiled by the rules before; guards keep what already worked."""
import pytest

from conftest import mk
from app.services.classifier import RuleClassifier, extract_promo_subcategory

clf = RuleClassifier()
UPD, PROMO, PERS = ["CATEGORY_UPDATES"], ["CATEGORY_PROMOTIONS"], ["CATEGORY_PERSONAL"]
TEMPLATE = "[auto-pay body copy] [auto-pay cta] end autopay section --> secure"

CASES = [
    # bank mail
    ("statement_now_available", dict(subject="Your latest statement is now available",
                                     sender="Chase <no.reply.alerts@chase.com>", labels=UPD), "bill"),
    ("zelle_delayed_not_bill", dict(subject="A Zelle® payment to you is delayed",
                                    sender="Chase <no.reply.alerts@chase.com>", body=TEMPLATE, labels=UPD), "alert"),
    ("zelle_incoming", dict(subject="Good news! We’re sending a Zelle® payment to you",
                            sender="Chase <no.reply.alerts@chase.com>", labels=UPD), "alert"),
    ("payment_failed_curly", dict(subject="We couldn’t complete your online payment",
                                  sender="Chase <no.reply.alerts@chase.com>", labels=UPD), "alert"),
    ("payment_declined", dict(subject="Your payment was declined", sender="Hulu <billing@hulu.com>"), "alert"),
    # account safety
    ("password_reset_linkedin", dict(subject="Alex, your password was successfully reset",
                                     sender="LinkedIn <security-noreply@linkedin.com>"), "security"),
    ("password_reset_github", dict(subject="[GitHub] Your password was reset",
                                   sender="GitHub <noreply@github.com>"), "security"),
    ("please_reset_password", dict(subject="[GitHub] Please reset your password",
                                   sender="GitHub <noreply@github.com>"), "security"),
    ("fraud_confirm_activity_personal_label", dict(subject="Action Needed: Please confirm activity",
                                                   sender="Chase Fraud <alerts@fraudalert.chase.com>", labels=PERS), "security"),
    # tracking / notices
    ("tracked_flight_price", dict(subject="Your tracked flight to Denver is now $2,363 (was $2,878)",
                                  sender="Google Flights <noreply-travel@google.com>", labels=UPD), "alert"),
    ("application_received", dict(subject="Application Received for R0000123456 2027 IT Analyst",
                                  sender="Workday <acme@myworkday.com>", labels=UPD), "alert"),
    ("thanks_for_applying", dict(subject="Thank you for applying to Acme", sender="Acme Careers <jobs@acme.com>"), "alert"),
    ("registration_status", dict(subject="Your event registration status: ED1234567",
                                 sender="Event Desk <noreply@events.example.gov>"), "alert"),
    ("free_subscription_ready", dict(subject="Your free AWS Skill Builder subscription is ready",
                                     sender="AWS Training <no-reply@aws.training>"), "subscription"),
    # promotions Gmail filed elsewhere, or with alert words in them
    ("promo_tab_recommended_for_you", dict(subject="Last chance savings: Start your skill-building routine",
                                           sender="Udemy <hello@students.udemy.com>", labels=PROMO,
                                           body="Certified AI Practitioner 4.71 (52,337) Recommended for you"), "promotion"),
    ("personal_label_lease_ad", dict(subject="Save Up to $600 When You Lease Soon!",
                                     sender="Riverside Apartments <leasing@emailrelay.com>", labels=PERS), "promotion"),
    ("personal_label_units_left", dict(subject="Only 10 Units Left - Admin Fee Waived",
                                       sender="Riverside Apartments <leasing@emailrelay.com>", labels=PERS), "promotion"),
    ("personal_label_marketing_subdomain", dict(subject="Get your verified rider badge",
                                                sender="Lyft <no-reply@marketing.lyftmail.com>", labels=PERS), "promotion"),
    # guards: already right, must stay right
    ("guard_rent_reply_personal", dict(subject="RE: Rent payment", sender="Office <office@example-apartments.com>",
                                       labels=PERS, body="Thanks, we received it."), "personal"),
    ("guard_verify_device_otp", dict(subject="[GitHub] Please verify your device", sender="GitHub <noreply@github.com>",
                                     body="Verification code: 123456"), "otp"),
    ("guard_google_security", dict(subject="Security alert", sender="Google <no-reply@accounts.google.com>",
                                   body="A new sign-in on Mac"), "security"),
    ("guard_lyft_receipt", dict(subject="Your receipt for rides on April 23", sender="Lyft <no-reply@lyftmail.com>",
                                body="Total $18.20"), "receipt"),
    ("guard_linkedin_invite", dict(subject="You have 1 new invitation", sender="LinkedIn <invitations@linkedin.com>"), "alert"),
    ("guard_bank_offer_promo", dict(subject="Get up to $1,000 cash bonus when you invest",
                                    sender="Chase <offers@mcmap.chase.com>", labels=PROMO), "promotion"),
    ("guard_webinar_promo_tab", dict(subject="Webinar: Discover KEDGE Business School on 17th September",
                                     sender="Amity <x@mailer.amityonline.com>", labels=PROMO), "promotion"),
]


@pytest.mark.parametrize("kw,expected", [(k, e) for _, k, e in CASES], ids=[n for n, _, _ in CASES])
def test_real_mail(kw, expected):
    assert clf.classify(mk(**kw))[0] == expected


PROMO_SUB = [
    ("course_sale_not_finance", dict(subject="Save with a Udemy Personal Plan", body="Invest in your skills for less. 200+ courses."), "education"),
    ("bootcamp", dict(subject="Still thinking about Generative AI? Join the bootcamp"), "education"),
    ("real_finance_stays", dict(subject="Earn a $1,000 bonus on your new credit card"), "finance"),
    ("travel_stays", dict(subject="Cheap flights this fall"), "travel"),
]


@pytest.mark.parametrize("kw,expected", [(k, e) for _, k, e in PROMO_SUB], ids=[n for n, _, _ in PROMO_SUB])
def test_promo_subcategory(kw, expected):
    assert extract_promo_subcategory(mk(**kw)) == expected


# ------------------------------------------------ from the second real sync

from app.services.classifier import extract_subscription_info

CYPRESS = dict(subject="Your Cypress subscription has been activated", sender='"Cypress.io" <billing@cypress.io>',
               body="YOUR CYPRESS SUBSCRIPTION IS ACTIVE! Next renewal on 17-Aug-2026. "
                    "Free Trial Enterprise Cloud $0.0000. - The Cypress Team, Cypress.io, Inc.")
NJT = dict(subject="NJ TRANSIT - Receipt", sender="noreply@mytix.njtransit.com",
           body="Purchase Receipt. Ticket Details Product Ticket Type Bus Monthly-Adult 609 2 INTRASTATE 1 $85.00 "
                "Payment Details Apple Pay $85.00. One-Way, Round-Trip, and Flex Pass tickets cannot be refunded.")


def test_cypress_is_subscription_named_cypress():
    assert clf.classify(mk(**CYPRESS))[0] == "subscription"
    info = extract_subscription_info(mk(**CYPRESS))
    assert info["sub_service"] == "Cypress"


def test_monthly_bus_pass_is_a_receipt():
    assert clf.classify(mk(**NJT))[0] == "receipt"


@pytest.mark.parametrize("sender,expected", [
    ('"Notion.so" <team@makenotion.com>', "Notion"),
    ('"Linear.app" <billing@linear.app>', "Linear"),
])
def test_domain_suffix_dropped_from_name(sender, expected):
    assert extract_subscription_info(mk(subject="Receipt", sender=sender))["sub_service"] == expected


@pytest.mark.parametrize("body,expected", [
    ("Your Monthly Plan renews on Oct 3. Amount paid $10.00", "subscription"),   # "monthly plan"
    ("Monthly membership fee received. Amount paid $29.99", "subscription"),
    ("Receipt. Monthly-Adult bus pass $85.00", "receipt"),                     # a pass, not a plan
    ("Receipt. Yearly calendar print $15.00", "receipt"),
])
def test_bare_period_word_not_enough(body, expected):
    assert clf.classify(mk(subject="Receipt", body=body))[0] == expected
