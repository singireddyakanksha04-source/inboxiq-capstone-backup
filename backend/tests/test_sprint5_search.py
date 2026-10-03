from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.services import firestore_client as fs
from fakefs import FakeDB

@pytest.fixture
def mailbox(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(fs, 'db', lambda: db)
    from app.main import app
    return db, TestClient(app)

def put(db, id, *, uid='u1', day='2026-10-01', sender='Shop <shop@example.com>', subject='Running shoes', category='promotion'):
    db.put_email(uid, dict(id=id, date=datetime.fromisoformat(day).replace(tzinfo=timezone.utc), sender=sender,
                           sender_email=sender, subject=subject, category=category, body_text='special offer', snippet=''))

def page(client, **params):
    return client.get('/api/emails/search/page', params={'uid': 'u1', **params})

def ids(response):
    return [item['id'] for item in response.json()['items']]

def test_combined_filters_and_inclusive_dates(mailbox):
    db, client = mailbox
    put(db, 'hit')
    put(db, 'old', day='2026-09-30')
    put(db, 'new', day='2026-10-02')
    put(db, 'sender', sender='News <news@example.com>')
    put(db, 'category', category='newsletter')
    put(db, 'query', subject='Grocery offer')
    put(db, 'other-account', uid='u2')
    response = page(client, q='running', sender='SHOP', category='promotion', after='2026-10-01', before='2026-10-01')
    assert response.status_code == 200 and ids(response) == ['hit']
    assert response.json()['next_offset'] is None
    assert db.writes == [] and db.batches == []

@pytest.mark.parametrize('params', [{'sender': 'shop'}, {'after': '2026-10-01'}, {'before': '2026-10-01'}])
def test_filter_without_text(mailbox, params):
    db, client = mailbox
    put(db, 'hit')
    assert ids(page(client, **params)) == ['hit']

def test_empty_and_no_match(mailbox):
    db, client = mailbox
    put(db, 'hit')
    assert ids(page(client)) == []
    assert ids(page(client, q='zzzz')) == []

@pytest.mark.parametrize('params', [{'after':'not-a-date'}, {'before':'2026-02-30'},
    {'after':'2026-10-02', 'before':'2026-10-01'}, {'offset':-1}, {'offset':501}, {'limit':0}, {'limit':201},
    {'sender':'s'*255}, {'q':'q'*501}, {'uid':'other/account'}])
def test_invalid_filters_rejected(mailbox, params):
    assert page(mailbox[1], **params).status_code == 422

def test_pages_have_deterministic_ties_and_no_duplicates(mailbox):
    db, client = mailbox
    for id in ['c','a','d','b','e']: put(db, id)
    first = page(client, q='running', limit=2)
    second = page(client, q='running', limit=2, offset=first.json()['next_offset'])
    third = page(client, q='running', limit=2, offset=second.json()['next_offset'])
    assert ids(first) + ids(second) + ids(third) == ['a','b','c','d','e']
    assert third.json()['next_offset'] is None
    assert ids(page(client, q='running', offset=500)) == []
    assert first.json()['search_window'] == 500

def test_open_result_uses_active_account(mailbox):
    db, client = mailbox
    put(db, 'shared', uid='u1', subject='Running shoes')
    put(db, 'shared', uid='u2', subject='Private receipt')
    result = page(client, q='running').json()['items'][0]
    response = client.get('/api/emails/'+result['id'], params={'uid':'u1'})
    assert response.json()['subject'] == 'Running shoes'
    assert ids(page(client, uid='u2', q='running')) == []

def test_date_conversion_uses_utc(mailbox):
    db, client = mailbox
    put(db, 'near-midnight')
    db.docs[('users','u1','emails','near-midnight')]['date'] = datetime.fromisoformat('2026-10-01T23:30:00-05:00')
    assert ids(page(client, after='2026-10-02', before='2026-10-02')) == ['near-midnight']
    assert ids(page(client, after='2026-10-01', before='2026-10-01')) == []

def test_uncategorized_and_sender_literal(mailbox):
    db, client = mailbox
    put(db, 'hit', category=None, sender='A+B <a+b@example.com>')
    put(db, 'miss', category=None, sender='AB <ab@example.com>')
    assert ids(page(client, sender='a+b', category='uncategorized')) == ['hit']
