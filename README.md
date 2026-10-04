# InboxIQ

Pulls your Gmail inbox into Firestore, then labels every message —
`promotion`, `receipt`, `bill`, `newsletter`, `shipping`, `otp`,
`subscription`, `personal`, `other` — with either a free rules baseline or an
LLM, and shows the result as a filterable dashboard.

CSC 450 Capstone.

```
Gmail API  ->  FastAPI  ->  classifier  ->  Firestore  ->  React dashboard
```

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python 3.12) |
| Frontend | React 18 + Vite |
| Database | Cloud Firestore (Native mode) |
| Auth | Google OAuth 2.0, web application client |
| LLM | Groq — `openai/gpt-oss-20b` / `-120b`, `qwen/qwen3.8-27b` |

## Team

| Owner | Area | Files |
|---|---|---|
| Abhiram | Google sign-in, Gmail ingest | `app/services/gmail_*.py`, `app/features/{auth,ingest}/`, `src/features/{auth,sync}/` |
| Akanksha | Storage, dashboard | `app/services/firestore_client.py`, `app/features/emails/`, `src/features/{emails,stats}/` |
| Sathwik | Classification, model comparison | `app/services/classifier.py`, `app/features/classify/`, `scripts/compare_models.py` |

## Layout

```
backend/
  app/
    main.py                  mounts whatever registry.py finds
    registry.py              auto-discovers app/features/*
    core/config.py           settings from .env
    models/email.py          EmailMessage — the contract between all three layers
    services/                shared clients: gmail_auth, gmail_client,
                             firestore_client, classifier
    features/
      auth/      /api/auth/*        OAuth handshake, token storage
      ingest/    /api/ingest/*      fetch Gmail -> save to Firestore
      emails/    /api/emails/*      list, filter, per-category counts
      classify/  /api/classify/*    run a classifier over stored mail
  scripts/                   runnable checks, one per layer
frontend/
  src/
    App.jsx                  the only file that imports features
    api/client.js            shared fetch wrapper
    features/{auth,sync,emails,stats}/
```

**Adding or removing a feature touches nothing else.** Backend: drop a package
under `app/features/` that exports a `router`, and `registry.py` mounts it at
startup — delete the folder and its routes disappear. Frontend: one folder per
feature under `src/features/`, imported only in `App.jsx`. Features never import
each other; anything shared lives in `app/services` and `app/models`.

## Run it

Full install and Google Cloud steps: **[SETUP.md](SETUP.md)**.

```bash
# terminal 1 — API
cd backend && source .venv/bin/activate
PYTHONPATH=. uvicorn app.main:app --reload      # http://localhost:8000

# terminal 2 — dashboard
cd frontend && npm run dev                      # http://localhost:5180
```

Open <http://localhost:5180>, click **Connect Gmail**, then **Sync inbox**.
Use `localhost`, not `127.0.0.1` — the OAuth redirect URI is registered under
that hostname.

## API

| Method | Path | Does |
|---|---|---|
| `GET` | `/health` | status + which features loaded |
| `GET` | `/api/auth/status` | is there a usable token |
| `GET` | `/api/auth/login` | redirect to Google consent |
| `GET` | `/api/auth/callback` | trade code for token, bounce to dashboard |
| `POST` | `/api/auth/logout` | delete stored token |
| `GET` | `/api/ingest/me` | signed-in address, Gmail message count |
| `POST` | `/api/ingest/sync?count=30` | fetch + store, returns `uid` |
| `GET` | `/api/emails?uid=&limit=&category=` | stored mail |
| `GET` | `/api/emails/stats?uid=` | counts per category |
| `GET` | `/api/emails/{message_id}?uid=` | one email |
| `GET` | `/api/classify/backends` | available backends + categories |
| `POST` | `/api/classify?uid=&backend=rules` | classify, write categories back |

Interactive docs at <http://localhost:8000/docs>.

## Data

```
users/{uid}                   email, created_at, last_sync_at, prefs
users/{uid}/emails/{msg_id}   sender, subject, date, body_text, labels[],
                              category, confidence
```

`uid` is the address with non-alphanumerics replaced, e.g.
`name_gmail_com` — a placeholder until real Firebase Auth uids.

## Classification

Two backends behind one interface, so a cheap path can be measured against an
expensive one on identical inputs.

- `rules` — keyword and header heuristics. Free, instant, the baseline to beat.
- Groq (`small` / `large` / `qwen`) — one JSON-mode call per email; the answer
  is clamped to the category list so a hallucinated label can't reach the DB.

Measured on 40 hand-labelled emails:

| Backend | Accuracy | Speed |
|---|---|---|
| `rules` | 57.5% (23/40) | 0.00 s/email |
| Groq backends | not yet scored | ~4 s/email |

Rules mostly fail by falling back to `other` on promotions and newsletters.

```bash
cd backend
PYTHONPATH=. python scripts/compare_models.py --uid <uid> --make-labels   # then fill in scripts/labels.json
PYTHONPATH=. python scripts/compare_models.py --uid <uid> --backends rules small
```

Needs `GROQ_API_KEY` in `.env` — free at <https://console.groq.com/keys>. The
`rules` backend needs no key.

## Secrets

`.env`, `secrets/oauth_client.json` and `secrets/tokens/` are gitignored and
must stay that way. Each person creates their own OAuth client; tokens are
never shared or committed.

## Inbox search and advanced filters

Search the active mailbox by subject, sender, snippet or body. Words are combined;
quotes match a phrase. `from:shop@example.com` and `subject:receipt` restrict a term.
Open **Search filters** for a sender name/address and inclusive **From date** /
**To date** bounds. Dates use UTC days. Select a mailbox to combine category with
these filters; **Reset all filters** returns to All Mail and clears the query.

Search checks the newest **500 synced messages in the chosen mailbox**, not the
entire Gmail inbox. Every email-list view shows **20 messages per page** with **Previous**, **Next**
and **Page N of M**. Search pages keep relevance order, with newest dates and
message IDs breaking ties. Normal inbox and category pages browse a bounded
window of the newest 500 synced messages in that mailbox. Filter controls and
page navigation remain visible while message rows scroll. Sync refreshes
the current search. Rows show matching text, and opening a message preserves the
query. Changing account clears search state.

`GET /api/emails/search/page?uid=&q=&sender=&category=&after=&before=&offset=&limit=`
returns `items`, `next_offset` and `search_window`. `after` and `before` use
`YYYY-MM-DD`; either can be omitted. Sender/date filters can be used without text.
The API accepts page sizes 1–200; the UI uses 20. The response also includes
`total_matches` for the selected bounded search window. The scan is bounded
at 500 messages. The older
`/api/emails/search` list response remains compatible. Paging uses the current
stored data rather than a historical snapshot; refresh after inbox updates.

The local prototype scopes queries by UID. Production server-side account
authorization remains a separate backlog item; UID scoping alone is not a
production authorization boundary. Search does not change Gmail or call a model.

In **Promotions**, **Promotion type** filters existing stored tags such as Shopping,
Food, Education, Travel and the other supported types. **Other / Unknown** includes
missing or unrecognized tags. It combines with text, sender and UTC-day filters;
reset, mailbox and account changes clear it. This reads `promo_subcategory` and
never reclassifies messages or modifies Gmail labels. The search-page API accepts
`subcategory` only with `category=promotion`.

## Search verification

Backend: `cd backend && python -m pytest tests -q` after installing
`requirements-dev.txt`. Frontend: `cd frontend && node tests/search_text.test.mjs`,
then `npm run build`. These tests use synthetic stored mail; no live Gmail or
Firestore account is required. See [Sprint 5 scope](docs/SPRINT5.md).
