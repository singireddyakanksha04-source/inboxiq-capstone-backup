# InboxIQ — CSC 450 Capstone

Gmail -> Backend -> Email Analysis -> Firestore

Setup and commands: `SETUP.md`

```
backend/app/services/gmail_auth.py       Google OAuth          (Abhiram)
backend/app/services/gmail_client.py     fetch + parse mail    (Abhiram)
backend/app/services/firestore_client.py all DB access         (Akansha)
backend/app/services/classifier.py       rules + Groq LLM      (Satwik)
backend/app/models/email.py              shared EmailMessage   (all — change together)

backend/app/features/<name>/router.py    one feature's HTTP routes
backend/app/registry.py                  auto-mounts every features/* package
  auth      /api/auth/*      sign-in        (Abhiram)
  ingest    /api/ingest/*    Gmail -> DB    (Abhiram)
  emails    /api/emails/*    read + stats   (Akansha)
  classify  /api/classify/*  categorise     (Satwik)

frontend/src/features/<name>/            one feature's UI, imported only in App.jsx
frontend/src/api/client.js               shared fetch wrapper
backend/scripts/                         runnable tests

Deleting a feature = delete its folder (backend: nothing else to touch;
frontend: also drop its lines from App.jsx). Features never import each other —
shared code lives in app/services and app/models.
```
