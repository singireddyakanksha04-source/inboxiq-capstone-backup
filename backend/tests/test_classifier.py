import pytest
from conftest import mk
from app.services.classifier import (RuleClassifier, CATEGORIES, extract_promo_subcategory,
    extract_subscription_info, get_classifier, _matches)

C = RuleClassifier()
def cat(**kw): return C.classify(mk(**kw))[0]

CASES = [
 # (id, kwargs, expected)
 # --- otp
 ("otp_verification_code", dict(subject="Your verification code", body="Use 482913 to continue"), "otp"),
 ("otp_six_digit_is_your", dict(subject="482913 is your Instagram code"), "otp"),
 ("otp_one_time_passcode", dict(subject="Your one-time passcode"), "otp"),
 ("otp_login_code", dict(subject="Your login code for Slack", sender="Slack <no-reply@slack.com>"), "otp"),
 ("otp_signin_code", dict(subject="Your sign-in code"), "otp"),
 ("otp_reset_code", dict(subject="Password reset code"), "otp"),
 ("otp_bare_OTP", dict(subject="OTP for your transaction"), "otp"),
 ("otp_beats_personal_label", dict(subject="Your verification code is 123456", labels=["CATEGORY_PERSONAL"]), "otp"),
 ("otp_beats_promotions_label", dict(subject="Security code for your account", labels=["CATEGORY_PROMOTIONS"]), "otp"),
 # --- security
 ("sec_new_signin", dict(subject="New sign-in to your Google Account"), "security"),
 ("sec_new_device", dict(subject="We noticed a new device"), "security"),
 ("sec_security_alert", dict(subject="Security alert", sender="Google <no-reply@accounts.google.com>"), "security"),
 ("sec_suspicious_activity", dict(subject="Suspicious activity on your account"), "security"),
 ("sec_verify_its_you", dict(subject="Verify it's you"), "security"),
 ("sec_beats_personal", dict(subject="Security alert for your account", labels=["CATEGORY_PERSONAL"]), "security"),
 ("sec_github_signin_before_social", dict(subject="[GitHub] A new sign-in to your account", sender="GitHub <noreply@github.com>"), "security"),
 # --- personal
 ("personal_label", dict(subject="Dinner Saturday?", labels=["CATEGORY_PERSONAL"]), "personal"),
 ("personal_label_with_deal_word", dict(subject="Great deal on the couch you wanted?", labels=["CATEGORY_PERSONAL"]), "personal"),
 # --- shipping
 ("ship_out_for_delivery", dict(subject="Your package is out for delivery"), "shipping"),
 ("ship_has_shipped", dict(subject="Your order has shipped!"), "shipping"),
 ("ship_tracking_number", dict(subject="Update", body="Your tracking number is 1Z999"), "shipping"),
 ("ship_package_delivered", dict(subject="Your package was delivered"), "shipping"),
 ("ship_arriving_tomorrow", dict(subject="Arriving tomorrow: AA batteries"), "shipping"),
 ("ship_items_on_the_way", dict(subject="Your items are on the way"), "shipping"),
 ("ship_delivery_attempt", dict(subject="Delivery attempt failed"), "shipping"),
 ("ship_track_your_package", dict(subject="Track your package"), "shipping"),
 ("ship_not_bare_delivered", dict(subject="We delivered a new feature to your dashboard"), "other"),
 ("ship_not_bare_arriving", dict(subject="New inventory arriving soon"), "other"),
 ("ship_not_we_shipped_product_news", dict(subject="We shipped dark mode"), "other"),
 ("ship_skip_cars_domain", dict(subject="New inventory arriving today", body="Your saved car has been shipped to the dealer", sender="Cars.com <alerts@cars.com>"), "alert"),
 ("ship_skip_listing_subdomain", dict(subject="Package has shipped", sender="Zillow <x@em.zillow.com>"), "other"),
 ("ship_skip_carvana_not_alert_domain", dict(subject="Your car is on the way", sender="Carvana <hi@carvana.com>"), "other"),
 ("ship_not_skip_lookalike_domain", dict(subject="Your order has shipped", sender="Shop <x@notcars.com>"), "shipping"),
 # --- receipt
 ("receipt_word", dict(subject="Your receipt from Apple"), "receipt"),
 ("receipt_order_confirm_exact", dict(subject="Order confirm: 1234"), "receipt"),
 ("receipt_order_confirmation", dict(subject="Order confirmation #1234"), "receipt"),
 ("receipt_thanks_purchase", dict(subject="Thanks for your purchase"), "receipt"),
 ("receipt_invoice_paid", dict(subject="Invoice paid - thank you"), "receipt"),
 # --- bill
 ("bill_payment_due", dict(subject="Payment due soon"), "bill"),
 ("bill_statement_ready", dict(subject="Your statement is ready"), "bill"),
 ("bill_minimum_payment", dict(subject="Minimum payment reminder"), "bill"),
 ("bill_new_invoice", dict(subject="Your new invoice from Comcast"), "bill"),
 ("bill_invoice_hash", dict(subject="Invoice #4411 due"), "bill"),
 ("bill_past_due", dict(subject="Your account is past due"), "bill"),
 ("bill_promo_tab_body_autopay_ignored", dict(subject="Big summer savings", body="Set up autopay with our card", labels=["CATEGORY_PROMOTIONS"]), "promotion"),
 ("bill_promo_tab_subject_counts", dict(subject="Your statement is ready", labels=["CATEGORY_PROMOTIONS"]), "bill"),
 # --- subscription
 ("sub_renews_on", dict(subject="Your Netflix plan renews on Oct 3"), "subscription"),
 ("sub_trial_ends", dict(subject="Your free trial ends in 3 days"), "subscription"),
 ("sub_next_billing_date", dict(subject="Heads up", body="Your next billing date is Oct 3"), "subscription"),
 ("sub_membership_cancelled", dict(subject="Your membership has been cancelled"), "subscription"),
 ("sub_subscription_renewed", dict(subject="Your subscription was renewed"), "subscription"),
 ("sub_plan_will_renew", dict(subject="Your plan will renew next week"), "subscription"),
 ("sub_subscription_confirmation", dict(subject="Subscription confirmation"), "subscription"),
 ("sub_auto_renewal_notice", dict(subject="Auto-renewal notice"), "subscription"),
 ("sub_renewal_reminder", dict(subject="Renewal reminder for Spotify"), "subscription"),
 ("sub_not_plain_membership_salescopy", dict(subject="Join our membership today"), "other"),
 ("sub_not_annual_subscription_salescopy", dict(subject="Get an annual subscription and save"), "other"),
 ("sub_promo_tab_body_ignored", dict(subject="Weekend sale", body="Subscription auto-renews at $9.99. Your subscription renews automatically.", labels=["CATEGORY_PROMOTIONS"]), "promotion"),
 # --- alert
 ("alert_price_drop", dict(subject="Price drop on a home you viewed"), "alert"),
 ("alert_job_matches", dict(subject="New jobs for you"), "alert"),
 ("alert_saved_search", dict(subject="3 new results for your saved search"), "alert"),
 ("alert_indeed_domain", dict(subject="Software engineer, Dallas", sender="Indeed <alert@indeed.com>"), "alert"),
 ("alert_ziprecruiter_subdomain", dict(subject="Hello there", sender="Zip <x@mail.ziprecruiter.com>"), "alert"),
 ("alert_bank_balance", dict(subject="Your available balance is below $100", sender="Chase <no.reply@chase.com>"), "alert"),
 ("alert_bank_zelle", dict(subject="You received money with Zelle", sender="Bank <alerts@bofa.com>"), "alert"),
 ("alert_direct_deposit", dict(subject="Direct deposit posted"), "alert"),
 ("alert_large_purchase", dict(subject="Large purchase on your card"), "alert"),
 ("alert_new_document", dict(subject="You received a new document"), "alert"),
 ("alert_webinar", dict(subject="You're registered: Cloud webinar"), "alert"),
 ("alert_notice_not_on_promo_tab", dict(subject="Join our webinar", labels=["CATEGORY_PROMOTIONS"]), "promotion"),
 # --- social
 ("social_linkedin_invite", dict(subject="You have an invitation", sender="LinkedIn <invitations@linkedin.com>"), "alert"),
 ("social_linkedin_viewed", dict(subject="5 people viewed your profile", sender="LinkedIn <x@linkedin.com>"), "alert"),
 ("social_linkedin_jobs", dict(subject="Software Engineer jobs in Dallas", sender="LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"), "alert"),
 ("social_linkedin_searches", dict(subject="You appeared in 12 searches this week", sender="LinkedIn <x@linkedin.com>"), "alert"),
 ("social_linkedin_feed_post", dict(subject="Jane Doe recently posted", sender="LinkedIn <x@linkedin.com>"), "newsletter"),
 ("social_linkedin_generic_newsletter", dict(subject="Top picks in tech", sender="LinkedIn <news@linkedin.com>"), "newsletter"),
 ("social_linkedin_promo_tab_not_newsletter", dict(subject="Top picks in tech", sender="LinkedIn <news@linkedin.com>", labels=["CATEGORY_PROMOTIONS"]), "promotion"),
 ("social_linkedin_subdomain", dict(subject="You have a new message", sender="LinkedIn <x@e.linkedin.com>"), "alert"),
 ("social_linkedin_feed_body_keyword_ignored", dict(subject="John recently posted", body="Huge deal! 50% off sale, your order has shipped", sender="LinkedIn <x@linkedin.com>"), "newsletter"),
 ("social_github_pr", dict(subject="[repo] New pull request #12", sender="GitHub <notifications@github.com>"), "alert"),
 ("social_github_issue", dict(subject="Re: [org/repo] Bug in parser (Issue #4)", sender="GitHub <notifications@github.com>"), "alert"),
 ("social_github_workflow", dict(subject="Run failed: CI workflow", sender="GitHub <notifications@github.com>"), "alert"),
 ("social_github_trending_digest", dict(subject="GitHub digest: trending repos", sender="GitHub <noreply@github.com>"), "newsletter"),
 ("social_github_unknown_defaults_alert", dict(subject="Welcome aboard", sender="GitHub <noreply@github.com>"), "alert"),
 ("social_slack_mention", dict(subject="Alex mentioned you in #general", sender="Slack <feedback@slack.com>"), "alert"),
 ("social_slack_notification", dict(subject="New notifications from Team", sender="Slack <x@slack.com>"), "alert"),
 ("social_x_domain_not_suffix_of_box", dict(subject="Your files are ready", sender="Dropbox <no-reply@dropbox.com>"), "other"),
 ("social_lookalike_notlinkedin", dict(subject="John recently posted", sender="X <a@notlinkedin.com>"), "other"),
 # --- promotion
 ("promo_percent_off", dict(subject="20% off everything"), "promotion"),
 ("promo_deal_word", dict(subject="Today's deal: headphones"), "promotion"),
 ("promo_deals_plural", dict(subject="Hot deals this weekend"), "promotion"),
 ("promo_deal_whole_word_not_dealer", dict(subject="Message from your dealer"), "other"),
 ("promo_deal_whole_word_not_ideal", dict(subject="An ideal time to visit"), "other"),
 ("promo_deal_whole_word_not_dealt", dict(subject="We dealt with your request"), "other"),
 ("promo_coupon", dict(subject="Your coupon inside"), "promotion"),
 ("promo_shop_now", dict(subject="New arrivals - shop now"), "promotion"),
 ("promo_try_premium", dict(subject="Try YouTube Premium"), "promotion"),
 ("promo_3_months_free", dict(subject="Get 3 months of Apple Music for free"), "promotion"),
 ("promo_for_0", dict(subject="Get it for $0"), "promotion"),
 ("promo_tab_fallback", dict(subject="Meet the new collection", labels=["CATEGORY_PROMOTIONS"]), "promotion"),
 ("promo_clearance", dict(subject="Clearance event"), "promotion"),
 # --- newsletter
 ("news_word", dict(subject="The October newsletter"), "newsletter"),
 ("news_this_week_in", dict(subject="This week in Python"), "newsletter"),
 ("news_issue_hash", dict(subject="Issue #42: tooling"), "newsletter"),
 ("news_weekly_roundup", dict(subject="Your weekly tech roundup"), "newsletter"),
 ("news_substack_domain", dict(subject="On building things", sender="Author <author@substack.com>"), "newsletter"),
 ("news_medium_subdomain", dict(subject="Stories for you", sender="Medium <noreply@email.medium.com>"), "newsletter"),
 # --- other
 ("other_plain", dict(subject="Hello"), "other"),
 ("other_empty", dict(), "other"),
 # --- precedence traps
 ("prec_shipping_before_receipt", dict(subject="Your order has shipped", body="receipt attached"), "shipping"),
 ("prec_receipt_before_promo", dict(subject="Your receipt", body="20% off your next order"), "receipt"),
 ("trap_otp_word_in_body_deep", dict(subject="Monthly newsletter", body="Learn how OTP protects you"), "otp"),
]

@pytest.mark.parametrize("kw,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_rules(kw, expected):
    assert cat(**kw) == expected

def test_categories_list():
    assert len(CATEGORIES) == 11 and len(set(CATEGORIES)) == 11

def test_all_outputs_in_categories():
    for _, kw, _e in CASES:
        c, conf = C.classify(mk(**kw))
        assert c in CATEGORIES and 0 <= conf <= 1

def test_get_classifier_rules():
    assert get_classifier("rules").name == "rules"

@pytest.mark.parametrize("dom,expected", [("cars.com", True), ("em.cars.com", True), ("a.b.cars.com", True),
    ("notcars.com", False), ("cars.com.evil.io", False), ("", False)])
def test_matches(dom, expected):
    assert _matches(dom, ("cars.com",)) is expected

# ------------------------------------------------ promo subcategory
PROMO = [
 ("travel", dict(subject="Cheap flights to Paris"), "travel"),
 ("travel_singular", dict(subject="Book a flight to Paris"), "travel"),
 ("travel_hotel", dict(subject="Hotel deals this weekend"), "travel"),
 ("food", dict(subject="$10 off DoorDash"), "food"),
 ("groceries", dict(subject="Save on groceries with Instacart"), "groceries"),
 ("electronics", dict(subject="New laptop sale"), "electronics"),
 ("clothing", dict(subject="Sneakers for fall"), "clothing"),
 ("entertainment", dict(subject="Concert tickets on sale"), "entertainment"),
 ("finance", dict(subject="Earn 5% cashback with our credit card"), "finance"),
 ("shopping", dict(subject="Big sale starts now"), "shopping"),
 ("none", dict(subject="Hello there"), None),
 ("tv_word_boundary", dict(subject="New TV lineup"), "electronics"),
 ("trap_showroom_not_show", dict(subject="Visit our showroom"), None),
]
@pytest.mark.parametrize("kw,expected", [p[1:] for p in PROMO], ids=[p[0] for p in PROMO])
def test_promo_sub(kw, expected):
    assert extract_promo_subcategory(mk(**kw)) == expected

# ------------------------------------------------ subscription info
SUB = [
 ("netflix_monthly", dict(subject="Your Netflix membership", body="Your plan is $15.49/month. Renews on October 3, 2026.", sender="Netflix <info@account.netflix.com>"),
    dict(sub_service="Netflix", sub_amount="$15.49", sub_cycle="monthly")),
 ("yearly_amount_period", dict(subject="Renewal notice", body="You will be charged $99.00/yr", sender="Acme <billing@acme.com>"),
    dict(sub_service="Acme", sub_amount="$99.00", sub_cycle="yearly")),
 ("annual_word", dict(subject="Annual plan renewed", body="Total charged: $120.00", sender="Tool <x@tool.io>"),
    dict(sub_amount="$120.00", sub_cycle="yearly")),
 ("per_month", dict(subject="Plan", body="Price: USD 12.00 per month", sender="Svc <x@svc.com>"),
    dict(sub_amount="$12.00", sub_cycle="monthly")),
 ("bare_number_usd", dict(subject="Plan", body="You paid 9.99 USD for your subscription", sender="Svc <x@svc.com>"),
    dict(sub_amount="$9.99")),
 ("thousands", dict(subject="Renewal", body="Amount charged: $1,299.00 annually", sender="Big <x@big.com>"),
    dict(sub_amount="$1,299.00", sub_cycle="yearly")),
 ("us_dollar_prefix", dict(subject="Receipt", body="Total: US$4.99 a month", sender="App <x@app.com>"),
    dict(sub_amount="$4.99", sub_cycle="monthly")),
 ("promo_amount_loses", dict(subject="Save $20 on your plan", body="Your subscription renews at $10.99/mo", sender="S <x@s.com>"),
    dict(sub_amount="$10.99", sub_cycle="monthly")),
 ("only_promo_amount", dict(subject="Save $20 today", body="Get $5 off", sender="S <x@s.com>"),
    dict(sub_amount=None)),
 ("zero_trial", dict(subject="Your free trial started", body="$0.00 due today. Then $7.99/month after your trial ends.", sender="Trial Co <x@trialco.com>"),
    dict(sub_amount="$7.99", sub_cycle="trial")),
 ("no_amount", dict(subject="Your plan was cancelled", sender="Hulu <x@hulu.com>"),
    dict(sub_amount=None, sub_cycle=None, sub_service="Hulu")),
 ("service_strip_noise", dict(subject="x", sender="Spotify Billing Team <x@spotify.com>"), dict(sub_service="Spotify")),
 ("service_from_domain_when_empty", dict(subject="x", sender="<x@members.netflix.com>"), dict(sub_service="Netflix")),
 ("service_bare_com", dict(subject="x", sender="noreply@spotify.com"), dict(sub_service="Spotify")),
 ("service_couk_named", dict(subject="x", sender="<noreply@netflix.co.uk>"), dict(sub_service="Netflix")),
 ("service_couk", dict(subject="x", sender="noreply@netflix.co.uk"), dict(sub_service="Netflix")),
 ("service_quoted", dict(subject="x", sender='"Disney+" <x@disneyplus.com>'), dict(sub_service="Disney+")),
 ("service_stopword_team", dict(subject="x", sender="Team <x@notion.so>"), dict(sub_service="Notion")),
 ("renewal_hint", dict(subject="x", body="Your plan renews on Oct 3, 2026 automatically", sender="A <x@a.com>"),
    dict(sub_renewal_hint="Oct 3, 2026 automatically")),
 ("next_billing_hint", dict(subject="x", body="Next billing date: 2026-10-03", sender="A <x@a.com>"),
    dict(sub_renewal_hint="2026-10-03")),
 ("cycle_word_monthly", dict(subject="Your monthly plan", sender="A <x@a.com>"), dict(sub_cycle="monthly")),
 ("period_beats_cycle_word", dict(subject="Monthly update", body="Your plan is $99.99/year", sender="A <x@a.com>"), dict(sub_cycle="yearly")),
 ("amount_no_cents", dict(subject="x", body="You were charged $15 for your subscription", sender="A <x@a.com>"), dict(sub_amount="$15.00")),
 ("amount_percent_not_price", dict(subject="x", body="20.00% interest. Membership price $5.00", sender="A <x@a.com>"), dict(sub_amount="$5.00")),
]
@pytest.mark.parametrize("kw,expected", [s[1:] for s in SUB], ids=[s[0] for s in SUB])
def test_sub_info(kw, expected):
    info = extract_subscription_info(mk(**kw))
    assert set(info) == {"sub_service", "sub_amount", "sub_cycle", "sub_renewal_hint"}
    for k, v in expected.items():
        assert info[k] == v, f"{k}: {info}"
