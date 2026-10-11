import base64, pytest
from app.services.gmail_client import _unsubscribe_link, parse_message, _clean_body_text

@pytest.mark.parametrize("header,expected", [
    ("<mailto:unsub@x.com>", "mailto:unsub@x.com"),
    ("<https://x.com/u?id=1>", "https://x.com/u?id=1"),
    ("<mailto:unsub@x.com>, <https://x.com/u>", "https://x.com/u"),
    ("<https://x.com/u>, <mailto:unsub@x.com>", "https://x.com/u"),
    ("<http://x.com/u>, <https://x.com/s>", "https://x.com/s"),
    ("<http://x.com/u>", "http://x.com/u"),
    ("<http://x.com/u>, <mailto:a@x.com>", "http://x.com/u"),
    ("< https://x.com/u >", "https://x.com/u"),
    ("<HTTPS://X.com/U>", "HTTPS://X.com/U"),
    ("<MAILTO:a@x.com>", "MAILTO:a@x.com"),
    ("<mailto:a@x.com?subject=unsubscribe>,<https://x.com/u>", "https://x.com/u"),
    ("", None),
    ("https://x.com/u", None),                 # malformed: no angle brackets
    ("mailto:a@x.com", None),
    ("<ftp://x.com/u>", None),
    ("<javascript:alert(1)>", None),
    ("<https://x.com/a b>", None),             # whitespace inside -> no match
    ("<>", None),
    ("<https://x.com/u", None),                # unterminated
    ("garbage <mailto:a@x.com", None),
])
def test_unsubscribe_header(header, expected):
    assert _unsubscribe_link({"list-unsubscribe": header}) == expected

def test_unsubscribe_header_missing():
    assert _unsubscribe_link({}) is None

def b64(s): return base64.urlsafe_b64encode(s.encode()).decode()

def test_parse_message_end_to_end():
    raw = {"id": "m1", "threadId": "t1", "snippet": "Hi &amp; bye", "labelIds": ["INBOX", "UNREAD"],
           "payload": {"headers": [
               {"name": "From", "value": "Nike <News@Nike.COM>"}, {"name": "Subject", "value": "Sale"},
               {"name": "Date", "value": "Sat, 20 Sep 2026 10:00:00 +0000"},
               {"name": "List-Unsubscribe", "value": "<mailto:u@nike.com>, <https://nike.com/u>"}],
               "mimeType": "multipart/alternative",
               "parts": [{"mimeType": "text/html", "body": {"data": b64("<p>HTML</p>")}},
                         {"mimeType": "text/plain", "body": {"data": b64("Plain​ text\n\n\n\nmore")}}]}}
    m = parse_message(raw)
    assert m.sender_email == "News@Nike.COM" and m.sender_domain == "nike.com"
    assert m.list_unsubscribe == "https://nike.com/u" and m.snippet == "Hi & bye"
    assert m.body_text == "Plain text\n\nmore" and m.date.year == 2026 and m.labels == ["INBOX", "UNREAD"]

def test_parse_message_minimal_and_bad_date():
    m = parse_message({"id": "x", "payload": {"headers": [{"name": "Date", "value": "not a date"}]}})
    assert m.date is None and m.sender_domain == "" and m.list_unsubscribe is None and m.body_text == ""

def test_parse_html_only():
    raw = {"id": "x", "payload": {"mimeType": "text/html", "body": {"data": b64("<style>.a{}</style><p>Hello<br>World</p>")}}}
    assert parse_message(raw).body_text == "Hello\nWorld"

def test_clean_body_tracking_parens():
    assert _clean_body_text("Shop (https://t.co/abc) now\r\n") == "Shop  now"  # double space left by paren removal (cosmetic)
