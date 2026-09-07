# Setup

## One time per person

```bash
brew install --cask google-cloud-sdk && exec zsh -l

gcloud auth login
gcloud config set project inboxiq-capstone-01     # owner runs `gcloud projects create` once
gcloud services enable gmail.googleapis.com firestore.googleapis.com
gcloud auth application-default login
```

Console, twice:
- Firestore DB: console.firebase.google.com -> add project -> Firestore -> Create -> Production, nam5
- OAuth: console.cloud.google.com/auth -> External, add your Gmail under Test users
  -> Clients -> Create -> **Web application** -> download JSON

  On that client, add both **Authorized redirect URIs**, exactly:
  ```
  http://localhost:8000/api/auth/callback     # dashboard sign-in
  http://localhost:8080/                      # backend/scripts/*
  ```
  Declaring scopes on the consent screen is only needed for Google verification;
  a Testing-mode app requests `gmail.readonly` at runtime.

```bash
mv ~/Downloads/client_secret_*.json secrets/oauth_client.json
cp .env.example .env      # set GOOGLE_CLOUD_PROJECT
```

Teammates need editor role + their Gmail in Test users. Everyone makes their own
OAuth client — do not share `oauth_client.json`.

## Install

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
```

## Run

```bash
cd backend
PYTHONPATH=. python scripts/test_gmail_login.py --count 5      # Abhiram
PYTHONPATH=. python scripts/test_firestore.py                  # Akansha
PYTHONPATH=. python scripts/sync_inbox.py --count 25           # joined workflow
PYTHONPATH=. python scripts/classify_emails.py --uid <uid> --backend rules   # Satwik
PYTHONPATH=. uvicorn app.main:app --reload      # API on http://localhost:8000
```

Frontend, second terminal:

```bash
cd frontend
npm install       # first time only
npm run dev       # http://localhost:5180, proxies /api to :8000
```

Open **http://localhost:5180** (localhost, not 127.0.0.1 — the redirect URI says
`localhost`), click **Connect Gmail** once, then **Sync inbox**.

`sync_inbox.py` prints the `uid`. The dashboard's Sync button does the same thing.
The CLI scripts run their own sign-in on port 8080; both share `secrets/tokens/`.

## Firestore layout

```
users/{uid}                     email, created_at, last_sync_at, prefs
users/{uid}/emails/{msg_id}     sender, subject, date, body_text, labels[], category, confidence
```

## Model comparison (Satwik)

```bash
PYTHONPATH=. python scripts/compare_models.py --uid <uid> --make-labels   # edit labels.json
PYTHONPATH=. python scripts/compare_models.py --uid <uid> --backends rules small large
```
Needs `GROQ_API_KEY` in `.env` (free at console.groq.com/keys). `rules` backend needs no key.
