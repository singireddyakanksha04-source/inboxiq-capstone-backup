import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
import pytest
from app.models.email import EmailMessage

def mk(subject="", snippet="", body="", sender="Someone <a@example.com>", labels=None, **kw):
    import email.utils as eu
    _, addr = eu.parseaddr(sender)
    return EmailMessage(id=kw.pop("id", "m1"), thread_id="t1", sender=sender, sender_email=addr,
                        sender_domain=addr.split("@")[-1].lower() if "@" in addr else "",
                        subject=subject, snippet=snippet, body_text=body, labels=labels or [], **kw)

@pytest.fixture
def make():
    return mk
