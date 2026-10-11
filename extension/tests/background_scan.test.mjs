// Drives the service worker against a stand-in Gmail: checks it pages the
// message list, reads each message's headers, sorts with the shared rule
// classifier, counts the mailboxes, survives one unreadable message, and
// drops a token Google has rejected. No Google account involved.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const read = (name) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");

const MAIL = [
  { id: "m1", threadId: "t1", internalDate: "1700000003000", snippet: "Use 482913 to continue",
    labelIds: ["INBOX"], headers: { From: "Slack <no-reply@slack.com>", Subject: "Your verification code" } },
  { id: "m2", threadId: "t2", internalDate: "1700000002000", snippet: "",
    labelIds: ["INBOX", "CATEGORY_UPDATES"], headers: { From: "Chase <no.reply.alerts@chase.com>",
      Subject: "Your latest statement is now available" } },
  { id: "m3", threadId: "t3", internalDate: "1700000001000", snippet: "Ends tonight",
    labelIds: ["INBOX", "CATEGORY_PROMOTIONS"], headers: { From: "Nike <news@nike.com>",
      Subject: "40% off running shoes" } },
  { id: "m4", threadId: "t4", internalDate: "1700000000000", snippet: "boom",
    labelIds: ["INBOX"], headers: { From: "Broken <x@example.com>", Subject: "unreadable" } },
];

// --- a fake Chrome and a fake Gmail -----------------------------------------

let listener;
let storage = {};
let removedTokens = [];
let tokenValid = true;
let interactiveCalls = 0;

globalThis.chrome = {
  identity: {
    getAuthToken({ interactive }, cb) {
      if (interactive) interactiveCalls += 1;
      if (!tokenValid && !interactive) { chrome.runtime.lastError = { message: "not signed in" }; cb(); chrome.runtime.lastError = undefined; return; }
      cb("token-1");
    },
    removeCachedAuthToken({ token }, cb) { removedTokens.push(token); cb(); },
  },
  runtime: { onMessage: { addListener: (fn) => { listener = fn; } }, lastError: undefined },
  storage: { local: {
    get: async (key) => (key in storage ? { [key]: storage[key] } : {}),
    set: async (obj) => { Object.assign(storage, obj); },
  } },
};

let status401 = false;
globalThis.fetch = async (url, options) => {
  assert.equal(options.headers.Authorization, "Bearer token-1");
  if (status401) return { ok: false, status: 401, statusText: "Unauthorized", json: async () => ({}) };
  const path = url.replace("https://gmail.googleapis.com/gmail/v1/users/me", "");
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  if (path === "/profile") return ok({ emailAddress: "someone@example.com" });
  if (path.startsWith("/messages?")) {
    // Two pages, so the paging loop is exercised.
    const page = /pageToken=p2/.test(path) ? 1 : 0;
    return page === 0
      ? ok({ messages: MAIL.slice(0, 2).map(({ id }) => ({ id })), nextPageToken: "p2" })
      : ok({ messages: MAIL.slice(2).map(({ id }) => ({ id })) });
  }
  const id = /\/messages\/([^?]+)/.exec(path)[1];
  const mail = MAIL.find((m) => m.id === id);
  if (mail.id === "m4") return { ok: false, status: 500, statusText: "Server Error", json: async () => ({}) };
  return ok({ id: mail.id, threadId: mail.threadId, internalDate: mail.internalDate,
    snippet: mail.snippet, labelIds: mail.labelIds,
    payload: { headers: Object.entries(mail.headers).map(([name, value]) => ({ name, value })) } });
};

// Loaded the way a service worker loads it: a global to hang InboxIQ on, and
// no CommonJS module in scope.
globalThis.importScripts = (relative) => {
  new Function("self", read("../src/" + relative.replace("./", "")))(globalThis);
};

new Function(read("../src/background.js")).call(globalThis);
const send = (message) => new Promise((resolve) => listener(message, null, resolve));

// --- what the panel asks for -------------------------------------------------

assert.deepEqual(await send({ type: "status" }), { connected: false, counts: {}, messages: [], scanned: 0 },
  "nothing scanned yet, so the panel shows Connect Gmail");

const scanned = await send({ type: "connect" });
assert.equal(scanned.connected, true);
assert.equal(scanned.email, "someone@example.com");
assert.equal(scanned.scanned, 3, "the message Gmail refused is left out, the scan still finishes");
assert.deepEqual(scanned.counts, { otp: 1, bill: 1, promotion: 1 });
assert.deepEqual(scanned.messages.map((m) => [m.category, m.from_name, m.thread_id]), [
  ["otp", "Slack", "t1"],
  ["bill", "Chase", "t2"],
  ["promotion", "Nike", "t3"],
], "newest first, sender display name kept for the panel rows");
assert.equal(scanned.messages[2].promo_subcategory, "clothing", "promotions keep their finer tag");
assert.equal(scanned.messages[0].date, 1700000003000);

const after = await send({ type: "status" });
assert.equal(after.scanned, 3, "a later panel load reads the stored scan instead of hitting Gmail");

tokenValid = false;
assert.deepEqual(await send({ type: "status" }), { connected: false, counts: {}, messages: [], scanned: 0 },
  "signed out of Chrome: the panel falls back to Connect Gmail, no prompt");

interactiveCalls = 0;
await send({ type: "scan", force: true });
assert.equal(interactiveCalls, 1, "a rescan without a cached token asks once, the same way Connect does");

tokenValid = true;
status401 = true;
const rejected = await send({ type: "scan", force: true });
assert.match(rejected.error, /sign-in expired/i);
assert.ok(removedTokens.includes("token-1"), "a token Google rejected is dropped from Chrome's cache");

console.log("12 background scan checks passed");
