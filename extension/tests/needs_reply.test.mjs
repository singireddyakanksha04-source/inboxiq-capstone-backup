// Needs reply, end to end through the service worker with a stand-in Gmail
// and a stand-in Groq: which messages the rules settle without the model, what
// the model is sent, answered threads leaving the list, one entry per thread,
// caching, failures, and that nothing is written to Gmail. No Google or Groq
// account involved.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const read = (name) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");
const headers = (h) => Object.entries(h).map(([name, value]) => ({ name, value }));
const ME = "someone@example.com";

// The inbox, newest first. internalDate orders them.
const INBOX = [
  { id: "m1", threadId: "t1", from: "Priya Shah <priya@example.com>", subject: "Thursday?", snippet: "Could we meet Thursday at 3?" },
  { id: "m2", threadId: "t2", from: "Shop <orders@shop.example>", subject: "Your receipt", snippet: "Thanks for your order #42" },
  { id: "m3", threadId: "t3", from: "GitHub <noreply@github.com>", subject: "New sign-in", snippet: "Did you sign in?" },
  { id: "m4", threadId: "t4", from: "Dev Patel <dev@example.com>", subject: "Slides", snippet: "Can you send the slides by Friday?" },
  { id: "m5", threadId: "t5", from: "Ana Lee <ana@example.com>", subject: "Lunch", snippet: "Lunch on Monday?" },
  { id: "m6", threadId: "t1", from: "Priya Shah <priya@example.com>", subject: "Sync", snippet: "Are you free this week?" },
  { id: "m7", threadId: "t7", from: "Team News <news@example.com>", subject: "Weekly digest", snippet: "This week in the newsletter" },
];
const THREAD_FROM = {
  t1: [{ from: "Priya Shah <priya@example.com>" }],
  t4: [{ from: "Dev Patel <dev@example.com>" }, { from: `Sam Rivera <${ME}>` }],          // already answered
  t5: [{ from: "Ana Lee <ana@example.com>" }, { from: `Sam <${ME}>`, labels: ["DRAFT"] }], // only a draft
};

let listener;
const storage = {};
globalThis.chrome = {
  identity: {
    getAuthToken(_, cb) { cb("token-1"); },
    removeCachedAuthToken(_, cb) { cb(); },
  },
  runtime: { onMessage: { addListener: (fn) => { listener = fn; } }, lastError: undefined },
  storage: { local: {
    get: async (key) => (key in storage ? { [key]: structuredClone(storage[key]) } : {}),
    set: async (obj) => { Object.assign(storage, structuredClone(obj)); },
    remove: async (key) => { delete storage[key]; },
  } },
};

// --- stand-ins --------------------------------------------------------------------
const groqCalls = [];
const gmailCalls = [];
// The model's verdicts, by the subject it was shown.
let verdicts = {
  "Thursday?": [true, "Priya asks if Thursday at 3 works"],
  "Slides": [true, "Dev asks for the slides by Friday"],
  "Lunch": [true, "Ana asks about lunch on Monday"],
  "Sync": [true, "Priya asks if you are free"],
};
let groqMode = "ok"; // ok | junk | 429
globalThis.fetch = async (url, options = {}) => {
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  if (url.startsWith("https://api.groq.com/")) {
    const body = JSON.parse(options.body);
    const user = body.messages[1].content;
    groqCalls.push({ system: body.messages[0].content, user });
    if (groqMode === "429") return { ok: false, status: 429, json: async () => ({}) };
    if (groqMode === "junk") return ok({ choices: [{ message: { content: "not json" } }] });
    const results = [...user.matchAll(/\[(\d+)\] From: .*\n {4}Subject: (.*)\n/g)].map(([, i, subject]) => {
      const v = verdicts[subject] || [false, ""];
      return { i: Number(i), needs_reply: v[0], reason: v[1] };
    });
    results.push({ i: 99, needs_reply: true, reason: "out of range" }, { i: 0, needs_reply: "yes" });
    return ok({ choices: [{ message: { content: JSON.stringify({ results }) } }] });
  }
  gmailCalls.push({ url, method: options.method || "GET" });
  const path = url.replace("https://gmail.googleapis.com/gmail/v1/users/me", "");
  if (path === "/profile") return ok({ emailAddress: ME });
  if (path.startsWith("/messages?")) return ok({ messages: INBOX.map((m) => ({ id: m.id })) });
  const msg = /^\/messages\/([^?]+)\?format=metadata/.exec(path);
  if (msg) {
    const m = INBOX.find((x) => x.id === msg[1]);
    return ok({ id: m.id, threadId: m.threadId, snippet: m.snippet, labelIds: ["INBOX"],
      internalDate: String(1000 - INBOX.indexOf(m)),
      payload: { headers: headers({ From: m.from, Subject: m.subject, "Message-ID": `<${m.id}@x>` }) } });
  }
  const thread = /^\/threads\/([^?]+)\?format=metadata&metadataHeaders=From$/.exec(path);
  if (thread) {
    const list = THREAD_FROM[thread[1]];
    if (!list) return { ok: false, status: 404, statusText: "Not Found", json: async () => ({}) };
    return ok({ id: thread[1], messages: list.map((x) => ({ labelIds: x.labels || ["INBOX"], payload: { headers: headers({ From: x.from }) } })) });
  }
  return { ok: false, status: 404, statusText: "Not Found", json: async () => ({}) };
};

globalThis.importScripts = (...files) => {
  for (const f of files) {
    if (f.includes("local_key")) throw new Error("NetworkError: local_key.js not found");
    new Function("self", read("../src/" + f.replace("./", "")))(globalThis);
  }
};
new Function(read("../src/background.js")).call(globalThis);
InboxIQ.sleep = async () => {};
const send = (message) => new Promise((resolve) => listener(message, null, resolve));
let checks = 0;
const check = (fn) => { fn(); checks += 1; };
const waiting = (r) => r.messages.filter((m) => m.needs_reply).map((m) => [m.id, m.needs_reason]);

let r = await send({ type: "connect" });
check(() => assert.equal(r.needs_count, 0));
check(() => assert.equal(r.needs_checked, false, "nothing checked before the first run"));

// --- no key ------------------------------------------------------------------------------

r = await send({ type: "needs:check" });
check(() => assert.match(r.needs_error, /Groq key/));
check(() => assert.equal(groqCalls.length, 0, "nothing reaches the model without a key"));

// --- the first run -----------------------------------------------------------------------

await send({ type: "ai:key", key: "gsk_test" });
r = await send({ type: "needs:check" });
check(() => assert.equal(r.needs_error, null));
check(() => assert.equal(groqCalls.length, 1, "the 4 candidates fit in one request"));
const prompt = groqCalls[0].user;
for (const subject of ["Thursday?", "Slides", "Lunch", "Sync"]) {
  check(() => assert.ok(prompt.includes("Subject: " + subject), subject + " is asked about"));
}
for (const subject of ["Your receipt", "New sign-in", "Weekly digest"]) {
  check(() => assert.ok(!prompt.includes(subject), subject + " is settled by the rules and never sent"));
}
check(() => assert.ok(prompt.includes("Preview: Could we meet Thursday at 3?")));
check(() => assert.match(groqCalls[0].system, /Prefer false over a weak guess/));
check(() => assert.deepEqual(waiting(r), [
  ["m1", "Priya asks if Thursday at 3 works"],
  ["m5", "Ana asks about lunch on Monday"],
], "Dev's thread is answered; Ana's unsent draft is not an answer; Priya's thread is listed once, newest"));
check(() => assert.equal(r.needs_count, 2));
check(() => assert.equal(r.needs_checked, true));
check(() => assert.ok(!r.messages.find((m) => m.id === "m4").needs_reason));
check(() => assert.ok(gmailCalls.every((c) => c.method === "GET"), "only reads from Gmail"));
const threadReads = gmailCalls.filter((c) => c.url.includes("/threads/"));
check(() => assert.ok(threadReads.every((c) => c.url.endsWith("format=metadata&metadataHeaders=From")),
  "answered or not is read from the From headers only"));
check(() => assert.equal(storage.inboxiq_ai_progress, null, "the progress bar is cleared"));

// --- cached, and answered threads re-checked ------------------------------------------------

THREAD_FROM.t1 = [{ from: "Priya Shah <priya@example.com>" }, { from: `Sam <${ME}>` }]; // the person replied
r = await send({ type: "needs:check" });
check(() => assert.equal(groqCalls.length, 1, "messages already asked about are not sent again"));
check(() => assert.deepEqual(waiting(r).map((w) => w[0]), ["m5"], "a reply sent since takes the email off the list"));
r = await send({ type: "status" });
check(() => assert.equal(r.needs_count, 1, "the list survives a reload"));

// --- failures ---------------------------------------------------------------------------------

delete storage.inboxiq_needs;
groqMode = "429";
r = await send({ type: "needs:check" });
check(() => assert.match(r.needs_error, /busy/));
check(() => assert.equal(r.needs_count, 0, "a failed run lists nothing it did not check"));
check(() => assert.equal(storage.inboxiq_ai_progress, null));

groqMode = "junk";
r = await send({ type: "needs:check" });
check(() => assert.equal(r.needs_error, null));
check(() => assert.equal(r.needs_count, 0, "an unreadable answer means nothing needs a reply"));

// --- the rules on their own ---------------------------------------------------------------------

check(() => assert.equal(InboxIQ.needsCandidate({ category: "personal", sender: "A <a@x.com>" }, ME), true));
check(() => assert.equal(InboxIQ.needsCandidate({ category: "other", sender: "no-reply@x.com" }, ME), false));
check(() => assert.equal(InboxIQ.needsCandidate({ category: "other", sender: "Do Not Reply <donotreply@x.com>" }, ME), false));
check(() => assert.equal(InboxIQ.needsCandidate({ category: "other", sender: "notifications@x.com" }, ME), false));
check(() => assert.equal(InboxIQ.needsCandidate({ category: "other", sender: `Me <${ME.toUpperCase()}>` }, ME), false,
  "the person's own mail"));
check(() => assert.equal(InboxIQ.needsCandidate({ category: "bill", sender: "A <a@x.com>" }, ME), false));
check(() => assert.equal(InboxIQ.needsCandidate({ category: "other", sender: "" }, ME), false));
check(() => assert.equal(InboxIQ.needsCandidate({ category: "other", sender: "Renotify Ltd <hello@renotify.com>" }, ME), true,
  "a name that merely contains 'notify' is not a no-reply address"));
check(() => assert.equal(InboxIQ.threadAnswered(["a@x.com", `Sam <${ME}>`], ME), true));
check(() => assert.equal(InboxIQ.threadAnswered([`Sam <${ME}>`, "a@x.com"], ME), false));
check(() => assert.equal(InboxIQ.threadAnswered([], ME), false));

console.log("needs reply: " + checks + " checks passed");
