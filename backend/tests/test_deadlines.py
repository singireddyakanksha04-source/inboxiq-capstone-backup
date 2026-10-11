import pytest
from datetime import datetime, timezone
from conftest import mk
from app.services.deadlines import extract_due_date

SENT = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
def due(category="bill", date=SENT, **kw):
    return extract_due_date(mk(category=category, date=date, **kw))

CASES = [
 ("bill_payment_due_by_month_day", dict(subject="Payment due by Oct 3"), ("2026-10-03", "Payment due")),
 ("bill_amount_due_full", dict(body="Your minimum payment is due on October 3, 2026."), ("2026-10-03", "Payment due")),
 ("bill_due_date_slash", dict(body="Due date: 10/03/2026"), ("2026-10-03", "Payment due")),
 ("bill_due_date_short_slash", dict(body="Due date: 10/3"), ("2026-10-03", "Payment due")),
 ("bill_iso", dict(body="Payment due 2026-10-03"), ("2026-10-03", "Payment due")),
 ("bill_day_month", dict(body="Please pay by 3 October 2026"), ("2026-10-03", "Payment due")),
 ("bill_day_of_month", dict(body="Payment due on the 3rd of October"), ("2026-10-03", "Payment due")),
 ("bill_weekday_prefix", dict(body="Payment is due Saturday, October 3"), ("2026-10-03", "Payment due")),
 ("bill_ordinal", dict(body="Payment due Oct 3rd"), ("2026-10-03", "Payment due")),
 ("bill_tomorrow_relative", dict(subject="Your payment is due tomorrow"), ("2026-09-21", "Payment due")),
 ("bill_today_relative", dict(subject="Payment due today"), ("2026-09-20", "Payment due")),
 ("bill_deadline_relabel", dict(body="Deadline: Oct 3"), ("2026-10-03", "Payment due")),
 ("bill_two_digit_year", dict(body="Due date 10/03/26"), ("2026-10-03", "Payment due")),
 ("sub_renews_on", dict(category="subscription", subject="Your plan renews on October 3, 2026"), ("2026-10-03", "Renews")),
 ("sub_trial_ends", dict(category="subscription", body="Your trial ends Oct 1"), ("2026-10-01", "Renews")),
 ("sub_next_billing", dict(category="subscription", body="Next billing date: Oct 5, 2026"), ("2026-10-05", "Renews")),
 ("sub_will_be_charged", dict(category="subscription", body="You will be charged on 10/05/2026"), ("2026-10-05", "Renews")),
 ("sub_expires", dict(category="subscription", body="Your membership expires on Nov 1"), ("2026-11-01", "Expires")),
 ("personal_interview", dict(category="personal", body="Your interview is scheduled for Sept 25"), ("2026-09-25", "Event")),
 ("alert_webinar_on", dict(category="alert", body="The webinar is on October 1, 2026"), ("2026-10-01", "Event")),
 ("other_apply_by", dict(category="other", body="Apply for the scholarship by Oct 15"), ("2026-10-15", "Deadline")),
 ("other_register_before", dict(category="other", body="Register before October 10, 2026"), ("2026-10-10", "Deadline")),
 ("receipt_valid_until", dict(category="receipt", body="Return valid until Dec 1, 2026"), ("2026-12-01", "Expires")),
 ("year_rollover_dec_email", dict(date=datetime(2026, 12, 20, tzinfo=timezone.utc), body="Payment due Jan 5"), ("2027-01-05", "Payment due")),
 ("subject_before_body", dict(subject="Payment due Oct 3", body="Payment due Oct 10"), ("2026-10-03", "Payment due")),
 ("earliest_in_part", dict(body="Your plan renews Oct 10. Payment due Oct 3."), ("2026-10-10", "Renews")),
 ("url_ignored", dict(body="Payment due https://pay.example.com/due/2026-10-03 on Oct 9"), ("2026-10-09", "Payment due")),
 # --- None expected
 ("no_date", dict(subject="Your statement is ready"), None),
 ("promotion_skipped", dict(category="promotion", subject="Sale ends Oct 3"), None),
 ("otp_skipped", dict(category="otp", subject="Code expires today"), None),
 ("newsletter_skipped", dict(category="newsletter", body="Registration deadline Oct 3"), None),
 ("none_category", dict(category=None, body="Payment due Oct 3"), None),
 ("relative_not_trusted_other", dict(category="other", subject="Offer ends tomorrow"), None),
 ("relative_not_trusted_personal", dict(category="personal", subject="Deadline today"), None),
 ("past_date_ignored", dict(body="Payment due Aug 1, 2026"), None),
 ("past_date_within_7_days_kept", dict(body="Payment due Sep 15, 2026"), ("2026-09-15", "Payment due")),
 ("far_future_ignored", dict(body="Payment due Oct 3, 2028"), None),
 ("invalid_date_feb30", dict(body="Payment due Feb 30, 2027"), None),
 ("trap_card_ending", dict(body="Card ending 10/28 was charged"), None),
 ("trap_date_without_lead", dict(body="Statement period Sep 1 - Sep 30"), None),
 ("trap_version_number", dict(category="other", body="Update to version 10/3 due to bugs"), None),
 ("trap_percent", dict(body="Your APR is 24/7 fixed"), None),
 ("trap_due_to", dict(category="other", body="Delayed due to weather on Oct 3"), None),
 ("trap_ends_generic_other", dict(category="other", body="The season ends Oct 3"), None),
 ("no_date_email_uses_now", dict(date=None, body="Payment due 2099-01-01"), None),
]

@pytest.mark.parametrize("kw,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_due(kw, expected):
    assert due(**kw) == expected
