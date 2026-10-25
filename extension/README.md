# InboxIQ for Gmail

A Chrome extension that sorts the signed-in Gmail inbox into the InboxIQ
mailboxes - Bills, Security, Codes, Subscriptions, Receipts, Shipping, Alerts,
Promotions, Newsletters, Personal - and lists them inside Gmail's own left
navigation, under Labels. It reads mail only; nothing is labelled, moved,
archived or deleted.

You can also add up to five categories of your own. Give one a name and a
one-sentence description ("emails about my job applications, interviews and
recruiters") and an AI model sorts your newest mail into it, with a short
reason for each message.

## Load it

1. Open `chrome://extensions`, turn on Developer mode.
2. "Load unpacked" and pick this `extension/` folder.
3. Open Gmail. The panel appears in the left navigation, under Labels. The
   toolbar icon opens the same view in a popup.

## Gmail access

Sorting needs a Chrome-extension OAuth client:

1. In the Google Cloud project that already has the Gmail API enabled, create
   an OAuth client of type **Chrome extension** with the application id
   `jicokcehhmimilfichhjaajdceboopbi`. The `key` in `manifest.json` pins that id,
   so it survives reloads of the unpacked build. The backend's web client cannot
   be reused: web clients are confidential and would need their secret shipped
   inside the extension.
2. Put that client id in `manifest.json` under `oauth2.client_id`.
3. Add your Google account as a test user on the consent screen.

Scope: `gmail.readonly`.

## My categories (AI)

1. In the panel, under **My categories**, click **+ New category**, name it
   and describe it in one sentence.
2. The Groq key comes from the project's `.env`: run
   `node extension/scripts/load_key.mjs` once, then reload the extension. It
   writes `src/local_key.js`, which is git-ignored and must never be shared.
   Without that file the panel asks for a key instead (free at
   console.groq.com/keys) and keeps it in this browser's extension storage.
3. **Sort with AI** checks the newest 50 messages; later scans do it
   automatically. Open a category to see each message's reason.

Only sender, subject and Gmail's preview are sent, ten messages per request.
A message is not sent again until the category list changes.

## Layout

| File | What it does |
| --- | --- |
| `src/categories.js` | Mailbox labels, colours and icons, in step with the web dashboard |
| `src/classifier.js` | The rule classifier, ported from the backend |
| `src/personal.js` | Your own categories: the AI prompt, batching and answer checks |
| `src/background.js` | Gmail sign-in, message fetching, sorting, caching |
| `src/content.js` | Mounts the panel in Gmail's navigation and holds view state |
| `src/panel.js` | Draws the mailbox list and the per-mailbox message list |
| `src/panel.css` | The panel's look; loaded into the shadow root, out of Gmail's reach |
| `popup.html`, `src/popup.js` | The toolbar popup, sharing the same view and cache |

## Tests

```
node extension/tests/classifier_parity.test.mjs   # same verdicts as the backend
node extension/tests/background_scan.test.mjs     # scan, sort, count, token loss
node extension/tests/personal_categories.test.mjs # own categories, AI sorting, failures
node extension/tests/subcategories.test.mjs      # split a category, rename, delete, failures
```

## Limits

- A scan reads the newest 150 inbox messages, headers and Gmail's preview
  snippet only. Full bodies are not fetched, so a rule that depends on wording
  deep in the body can miss where the dashboard catches it.
- Built-in sorting happens in the browser and sends nothing anywhere. Your
  own categories are the exception: with a key saved, sender, subject and
  preview of the newest 50 messages go to Groq.
- The AI can be wrong; that is why each message shows its reason.
