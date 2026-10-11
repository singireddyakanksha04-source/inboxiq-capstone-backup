# InboxIQ for Gmail

A Chrome extension that sorts the signed-in Gmail inbox into the InboxIQ
mailboxes - Bills, Security, Codes, Subscriptions, Receipts, Shipping, Alerts,
Promotions, Newsletters, Personal - and lists them inside Gmail's own left
navigation, under Labels. It reads mail only; nothing is labelled, moved,
archived or deleted.

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

## Layout

| File | What it does |
| --- | --- |
| `src/categories.js` | Mailbox labels, colours and icons, in step with the web dashboard |
| `src/classifier.js` | The rule classifier, ported from the backend |
| `src/background.js` | Gmail sign-in, message fetching, sorting, caching |
| `src/content.js` | Mounts the panel in Gmail's navigation and holds view state |
| `src/panel.js` | Draws the mailbox list and the per-mailbox message list |
| `src/panel.css` | The panel's look; loaded into the shadow root, out of Gmail's reach |
| `popup.html`, `src/popup.js` | The toolbar popup, sharing the same view and cache |

## Tests

```
node extension/tests/classifier_parity.test.mjs   # same verdicts as the backend
node extension/tests/background_scan.test.mjs     # scan, sort, count, token loss
```

## Limits

- A scan reads the newest 150 inbox messages, headers and Gmail's preview
  snippet only. Full bodies are not fetched, so a rule that depends on wording
  deep in the body can miss where the dashboard catches it.
- Sorting happens in the browser; no message text is sent anywhere.
