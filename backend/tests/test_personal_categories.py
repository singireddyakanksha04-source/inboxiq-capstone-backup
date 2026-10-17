"""Custom categories and AI sorting. The model is faked, so these run offline."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fakefs import FakeDB

from app.services import firestore_client as fs
from app.services import personal_ai

NOW = datetime.now(timezone.utc)
UID = "u1"
JOBS = {"name": "Job hunt", "description": "emails about job applications, interviews and recruiters"}


class FakeAI:
    """Stands in for the Groq client. `answer(prompt)` returns the results list."""

    def __init__(self, answer=None, error=None, raw=None):
        self.answer, self.error, self.raw, self.prompts = answer, error, raw, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        prompt = kw["messages"][1]["content"]
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        content = self.raw if self.raw is not None else json.dumps({"results": self.answer(prompt)})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def jobs_by_subject(prompt):
    """Match every email whose subject mentions an interview."""
    out = []
    for block in prompt.split("\n[")[1:]:
        i = int(block.split("]")[0])
        hit = "interview" in block.lower()
        out.append({"i": i, "category": "job_hunt" if hit else "none", "reason": "Interview invite" if hit else ""})
    return out


def doc(id, days_ago=0, **kw):
    d = dict(id=id, thread_id="t", sender="A <a@a.com>", sender_email="a@a.com", sender_domain="a.com",
             subject="", snippet="", body_text="secret body", labels=[], date=NOW - timedelta(days=days_ago),
             category="other", confidence=0.3)
    d.update(kw)
    return d


@pytest.fixture
def env(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    ai = FakeAI(answer=jobs_by_subject)
    monkeypatch.setattr(personal_ai, "_client", lambda: ai)
    from app.main import app
    return TestClient(app), f, ai


# ---------------------------------------------------------------- categories

def test_add_list_and_delete_category(env):
    c, f, _ = env
    r = c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    assert r.status_code == 201 and r.json()["id"] == "job_hunt"
    items = c.get(f"/api/personal/categories?uid={UID}").json()["items"]
    assert [(i["id"], i["name"], i["count"]) for i in items] == [("job_hunt", "Job hunt", 0)]
    assert c.delete(f"/api/personal/categories/job_hunt?uid={UID}").status_code == 200
    assert c.get(f"/api/personal/categories?uid={UID}").json()["items"] == []


def test_category_validation(env):
    c, _, _ = env
    url = f"/api/personal/categories?uid={UID}"
    assert c.post(url, json={"name": "", "description": "something long"}).status_code == 422
    assert c.post(url, json={"name": "X", "description": "   ab      "}).status_code == 422
    assert c.post(url, json={"name": "X" * 31, "description": "long enough"}).status_code == 422
    assert c.post(url, json=JOBS).status_code == 201
    dup = c.post(url, json={"name": "JOB HUNT", "description": "another description"})
    assert dup.status_code == 409


def test_at_most_five_categories(env):
    c, _, _ = env
    url = f"/api/personal/categories?uid={UID}"
    for n in range(personal_ai.MAX_CATEGORIES):
        assert c.post(url, json={"name": f"Cat {n}", "description": "a description"}).status_code == 201
    assert c.post(url, json={"name": "One more", "description": "a description"}).status_code == 409


def test_ids_are_unique_and_safe():
    assert personal_ai.make_id("Job hunt!", set()) == "job_hunt"
    assert personal_ai.make_id("Job hunt", {"job_hunt"}) == "job_hunt_2"
    assert personal_ai.make_id("../../x", set()) == "x"
    assert personal_ai.make_id("!!!", set()) == "category"


def test_delete_unknown_category_is_404(env):
    c, _, _ = env
    assert c.delete(f"/api/personal/categories/nope?uid={UID}").status_code == 404


def test_bad_uid_rejected(env):
    c, _, _ = env
    assert c.get("/api/personal/categories?uid=a/b").status_code == 422
    assert c.post("/api/personal/sort?uid=").status_code == 422


def test_categories_are_per_account(env):
    c, _, _ = env
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    assert c.get("/api/personal/categories?uid=u2").json()["items"] == []


# ---------------------------------------------------------------- sorting

def test_sort_tags_matching_mail_and_lists_it_as_a_mailbox(env):
    c, f, _ = env
    f.put_email(UID, doc("a", subject="Interview on Monday"))
    f.put_email(UID, doc("b", days_ago=1, subject="50% off shoes", category="promotion"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    r = c.post(f"/api/personal/sort?uid={UID}").json()
    assert r == {"checked": 2, "matched": 1, "error": None}

    mailbox = c.get(f"/api/emails?uid={UID}&category=my:job_hunt").json()
    assert [m["id"] for m in mailbox] == ["a"]
    assert mailbox[0]["custom_reason"] == "Interview invite"
    assert mailbox[0]["category"] == "other"  # built-in category untouched
    counts = c.get(f"/api/personal/categories?uid={UID}").json()["items"]
    assert counts[0]["count"] == 1


def test_search_works_inside_a_custom_mailbox(env):
    c, f, _ = env
    f.put_email(UID, doc("a", subject="Interview on Monday"))
    f.put_email(UID, doc("b", days_ago=1, subject="Interview prep tips"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    c.post(f"/api/personal/sort?uid={UID}")
    page = c.get(f"/api/emails/search/page?uid={UID}&category=my:job_hunt&q=monday").json()
    assert [m["id"] for m in page["items"]] == ["a"]


def test_only_sender_subject_and_preview_reach_the_model(env):
    c, f, ai = env
    f.put_email(UID, doc("a", subject="Interview", snippet="see you then", body_text="TOP SECRET BODY"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    c.post(f"/api/personal/sort?uid={UID}")
    assert "see you then" in ai.prompts[0] and "TOP SECRET BODY" not in ai.prompts[0]
    assert JOBS["description"] in ai.prompts[0]


def test_already_checked_mail_is_not_sent_again(env):
    c, f, ai = env
    f.put_email(UID, doc("a", subject="Interview"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    c.post(f"/api/personal/sort?uid={UID}")
    again = c.post(f"/api/personal/sort?uid={UID}").json()
    assert again["checked"] == 0 and len(ai.prompts) == 1


def test_changing_categories_rechecks_mail(env):
    c, f, ai = env
    f.put_email(UID, doc("a", subject="Interview"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    c.post(f"/api/personal/sort?uid={UID}")
    c.post(f"/api/personal/categories?uid={UID}", json={"name": "Travel", "description": "flights and hotels"})
    assert c.post(f"/api/personal/sort?uid={UID}").json()["checked"] == 1 and len(ai.prompts) == 2


def test_emails_are_sent_in_batches_of_ten(env):
    c, f, ai = env
    for n in range(25):
        f.put_email(UID, doc(f"m{n:02}", days_ago=n, subject=f"Message {n}"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    r = c.post(f"/api/personal/sort?uid={UID}&limit=25").json()
    assert r["checked"] == 25 and len(ai.prompts) == 3


def test_no_categories_means_no_model_call(env):
    c, f, ai = env
    f.put_email(UID, doc("a", subject="Interview"))
    assert c.post(f"/api/personal/sort?uid={UID}").json() == {"checked": 0, "matched": 0, "error": None}
    assert ai.prompts == []


def test_deleting_a_category_clears_its_mail(env):
    c, f, _ = env
    f.put_email(UID, doc("a", subject="Interview"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    c.post(f"/api/personal/sort?uid={UID}")
    r = c.delete(f"/api/personal/categories/job_hunt?uid={UID}").json()
    assert r["emails_cleared"] == 1
    assert c.get(f"/api/emails?uid={UID}&category=my:job_hunt").json() == []


# ---------------------------------------------------------------- bad model output

def test_invented_or_missing_answers_mean_no_match():
    cats = [{"id": "job_hunt", "name": "Job hunt", "description": "jobs"}]
    emails = [doc("a"), doc("b"), doc("c")]
    ai = FakeAI(answer=lambda p: [{"i": 0, "category": "made_up"}, {"i": 9, "category": "job_hunt"},
                                  {"i": "x"}, "junk", {"i": 2, "category": "job_hunt", "reason": " a\n b "}])
    assert personal_ai.sort_batch(cats, emails, client=ai) == [(None, ""), (None, ""), ("job_hunt", "a b")]


def test_non_json_answer_means_no_match():
    cats = [{"id": "job_hunt", "name": "Job hunt", "description": "jobs"}]
    ai = FakeAI(raw="not json at all")
    assert personal_ai.sort_batch(cats, [doc("a")], client=ai) == [(None, "")]


def test_model_failure_is_reported_not_raised(env, monkeypatch):
    c, f, _ = env
    f.put_email(UID, doc("a", subject="Interview"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    busy = Exception("rate limited")
    busy.status_code = 429
    monkeypatch.setattr(personal_ai, "_client", lambda: FakeAI(error=busy))
    r = c.post(f"/api/personal/sort?uid={UID}")
    assert r.status_code == 200
    assert r.json() == {"checked": 0, "matched": 0, "error": "The AI is busy (rate limit). Try again in a minute."}


def test_missing_key_is_a_clear_message(env, monkeypatch):
    c, f, _ = env
    f.put_email(UID, doc("a", subject="Interview"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    monkeypatch.undo()  # back to the real client factory
    monkeypatch.setattr(fs, "db", lambda: f)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert c.post(f"/api/personal/sort?uid={UID}").json()["error"] == "AI sorting needs a GROQ_API_KEY in .env."


def test_resync_keeps_custom_results(env):
    from app.models.email import EmailMessage
    c, f, _ = env
    f.put_email(UID, doc("a", subject="Interview"))
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    c.post(f"/api/personal/sort?uid={UID}")
    fresh = EmailMessage(**{k: v for k, v in doc("a", subject="Interview").items() if k in EmailMessage.model_fields})
    fs.save_emails(UID, [fresh])
    assert fs.get_email(UID, "a")["custom_category"] == "job_hunt"
