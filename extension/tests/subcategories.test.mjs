// Splitting a category into subcategories, end to end through the service
// worker with a stand-in Gmail and a stand-in Groq: the suggestion step, the
// checks on what comes back, sorting into the subcategories, Other, rename,
// delete, and failures leaving the category as it was. No Google or Groq
// account involved.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const read = (name) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");

// 30 inbox messages: 14 about the job hunt (interviews, applications, job
// alerts and two recruiter notes that fit none of those), the rest updates.
const SUBJECTS = [
  ...Array.from({ length: 4 }, (_, n) => "Interview slot " + n),
  ...Array.from({ length: 4 }, (_, n) => "Application received " + n),
  ...Array.from({ length: 4 }, (_, n) => "New jobs for you " + n),
  "Recruiter call notes", "Recruiter follow up",
  ...Array.from({ length: 16 }, (_, n) => "Weekly update " + n),
];
const MAIL = SUBJECTS.map((subject, n) => ({
  id: "m" + String(n).padStart(2, "0"),
  threadId: "t" + n,
  internalDate: String(1700000000000 - n * 1000),
  snippet: "PREVIEW TEXT " + n,
  labelIds: ["INBOX"],
  headers: { From: "Sender " + n + " <s" + n + "@example.com>", Subject: subject,
    "Message-ID": "<id" + n + "@mail.example.com>" },
}));

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

// --- stand-in Groq --------------------------------------------------------------
// A split request gets `suggestion`; a sort request is answered by keyword,
// for whichever category ids the prompt lists.
const KEYWORDS = { job_hunt: /interview|application|new jobs|recruiter/i,
  interviews: /interview/i, applications: /application/i, job_alerts: /new jobs/i };
const SUGGESTION = [
  { name: "Interviews", description: "Interview invites and scheduling" },
  { name: "Applications", description: "Updates on applications I sent" },
  { name: "Job alerts", description: "Lists of new job openings" },
  { name: "interviews", description: "a repeat that should be dropped" },
  { name: "Other", description: "a catch-all that should be dropped" },
  { name: "", description: "no name" },
];
const groqCalls = [];
let suggestion = SUGGESTION;
let groqMode = "ok"; // ok | sort429 | busy-once | junk-suggest | 401
function sortAnswer(prompt) {
  const ids = [...prompt.matchAll(/- id: (\S+)/g)].map((m) => m[1]);
  const blocks = prompt.split("\nEmails:")[1].split(/\n(?=\[\d+\])/).filter(Boolean);
  return blocks.map((block) => {
    const i = Number(/^\[(\d+)\]/.exec(block.trim())[1]);
    const hit = ids.find((id) => KEYWORDS[id] && KEYWORDS[id].test(block));
    return { i, category: hit || "none", reason: hit ? "Mentions " + hit : "" };
  });
}

globalThis.fetch = async (url, options) => {
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  if (url.startsWith("https://api.groq.com/")) {
    const body = JSON.parse(options.body);
    const split = body.messages[0].content.startsWith("You split one email category");
    groqCalls.push({ split, user: body.messages[1].content, key: options.headers.Authorization });
    if (groqMode === "401") return { ok: false, status: 401, json: async () => ({}) };
    if (groqMode === "sort429" && !split) return { ok: false, status: 429, json: async () => ({}) };
    if (groqMode === "busy-once" && !split) {
      groqMode = "ok";
      return { ok: false, status: 429, headers: new Headers({ "x-ratelimit-reset-tokens": "7.5s" }), json: async () => ({}) };
    }
    const content = split
      ? (groqMode === "junk-suggest" ? "not json" : JSON.stringify({ subcategories: suggestion }))
      : JSON.stringify({ results: sortAnswer(body.messages[1].content) });
    return ok({ choices: [{ message: { content } }] });
  }
  const path = url.replace("https://gmail.googleapis.com/gmail/v1/users/me", "");
  if (path === "/profile") return ok({ emailAddress: "someone@example.com" });
  if (path.startsWith("/messages?")) return ok({ messages: MAIL.map(({ id }) => ({ id })) });
  const mail = MAIL.find((m) => m.id === /\/messages\/([^?]+)/.exec(path)[1]);
  return ok({ id: mail.id, threadId: mail.threadId, internalDate: mail.internalDate, snippet: mail.snippet,
    labelIds: mail.labelIds, payload: { headers: Object.entries(mail.headers).map(([name, value]) => ({ name, value })) } });
};

globalThis.importScripts = (...files) => {
  for (const f of files) {
    if (f.includes("local_key")) throw new Error("NetworkError: local_key.js not found");
    new Function("self", read("../src/" + f.replace("./", "")))(globalThis);
  }
};
new Function(read("../src/background.js")).call(globalThis);
// Busy answers are retried after a wait; no real waiting in tests.
const sleeps = [];
InboxIQ.sleep = async (ms) => { sleeps.push(ms); };
const send = (message) => new Promise((resolve) => listener(message, null, resolve));
const PARENT = "my:job_hunt";
const SPLIT = { type: "sub:split", parent: PARENT, label: "Job hunt",
  description: "emails about my job applications, interviews and recruiters" };
let checks = 0;
const check = (fn) => { fn(); checks += 1; };
const counts = (r, parent = PARENT) =>
  Object.fromEntries(r.subs[parent].items.map((s) => [s.id, s.count]).concat([["other", r.subs[parent].other]]));

// --- setup: a Job hunt category filled by the Sprint 7 sort ------------------------

await send({ type: "connect" });
await send({ type: "custom:add", name: "Job hunt", description: SPLIT.description });
await send({ type: "ai:key", key: "gsk_test" });
let r = await send({ type: "custom:sort" });
check(() => assert.equal(r.custom[0].count, 14, "14 job hunt messages to split"));
check(() => assert.deepEqual(r.subs, {}, "nothing split yet"));
check(() => assert.equal(r.split_min, 6));
groqCalls.length = 0;

// --- the checks before anything is sent ----------------------------------------------

r = await send({ type: "sub:split", parent: "my:nothing_here", label: "Empty" });
check(() => assert.match(r.error, /at least 6 emails/));
await send({ type: "ai:key", key: "" });
r = await send(SPLIT);
check(() => assert.match(r.error, /Groq key/));
await send({ type: "ai:key", key: "gsk_test" });
check(() => assert.equal(groqCalls.length, 0, "neither case calls the model"));

// --- a split -------------------------------------------------------------------------

r = await send(SPLIT);
check(() => assert.equal(r.error, undefined));
check(() => assert.deepEqual(r.subs[PARENT].items.map((s) => s.name), ["Interviews", "Applications", "Job alerts"],
  "repeated, catch-all and empty names are dropped"));
check(() => assert.deepEqual(counts(r), { interviews: 4, applications: 4, job_alerts: 4, other: 2 }));
check(() => assert.equal(groqCalls.length, 3, "one suggestion call, then 14 messages 10 at a time"));
check(() => assert.ok(groqCalls[0].split && !groqCalls[1].split && !groqCalls[2].split));
const splitPrompt = groqCalls[0].user;
check(() => assert.ok(splitPrompt.includes("Category: Job hunt") && splitPrompt.includes(SPLIT.description)));
check(() => assert.ok(splitPrompt.includes("Interview slot 0") && splitPrompt.includes("s0@example.com")));
check(() => assert.ok(!splitPrompt.includes("Weekly update"), "only the category's own messages are sent"));
check(() => assert.ok(!splitPrompt.includes("PREVIEW TEXT"), "the suggestion step reads sender and subject only"));
check(() => assert.ok(groqCalls[1].user.includes("Interview invites and scheduling"),
  "the suggested descriptions drive the sort"));
check(() => assert.equal(storage.inboxiq_ai_progress, null, "progress cleared once the split ends"));
const m00 = r.messages.find((m) => m.id === "m00");
check(() => assert.deepEqual(m00.subs[PARENT], { id: "interviews", reason: "Mentions interviews" }));
check(() => assert.equal(m00.custom_category, "job_hunt", "the message stays in its category"));
check(() => assert.equal(r.messages.find((m) => m.id === "m12").subs[PARENT], null, "recruiter notes are Other"));

r = await send({ type: "status" });
check(() => assert.deepEqual(counts(r), { interviews: 4, applications: 4, job_alerts: 4, other: 2 },
  "the split survives a panel reload"));

// --- failures leave the category as it was ----------------------------------------------

const before = JSON.stringify(storage.inboxiq_subs);
groqMode = "sort429";
r = await send(SPLIT);
check(() => assert.match(r.error, /busy/));
check(() => assert.equal(JSON.stringify(storage.inboxiq_subs), before, "a split that fails half way saves nothing"));
check(() => assert.equal(storage.inboxiq_ai_progress, null));
check(() => assert.deepEqual(sleeps.slice(-3), [10500, 10500, 10500], "busy is retried 3 times before giving up"));
groqMode = "busy-once";
sleeps.length = 0;
r = await send(SPLIT);
check(() => assert.equal(r.error, undefined, "one busy answer is waited out"));
check(() => assert.deepEqual(sleeps, [8000], "waits as long as Groq says, plus a little"));
check(() => assert.deepEqual(counts(r), { interviews: 4, applications: 4, job_alerts: 4, other: 2 }));
groqMode = "junk-suggest";
r = await send(SPLIT);
check(() => assert.match(r.error, /clear subcategories/));
groqMode = "ok";
suggestion = [{ name: "Only one", description: "a single group" }];
r = await send(SPLIT);
check(() => assert.match(r.error, /clear subcategories/, "one group is not a split"));
check(() => assert.equal(JSON.stringify(storage.inboxiq_subs), before));
groqMode = "401";
r = await send(SPLIT);
check(() => assert.match(r.error, /key was rejected/));
groqMode = "ok";
suggestion = SUGGESTION;
r = await send({ type: "status" });
check(() => assert.equal(r.connected, true, "the built-in mailboxes still work"));

// --- rename ---------------------------------------------------------------------------

r = await send({ type: "sub:rename", parent: PARENT, id: "job_alerts", name: "  Job   listings " });
check(() => assert.equal(r.subs[PARENT].items[2].name, "Job listings"));
check(() => assert.equal(r.subs[PARENT].items[2].count, 4, "renaming keeps its messages"));
r = await send({ type: "sub:rename", parent: PARENT, id: "job_alerts", name: "INTERVIEWS" });
check(() => assert.match(r.error, /already a subcategory/));
r = await send({ type: "sub:rename", parent: PARENT, id: "job_alerts", name: "x".repeat(31) });
check(() => assert.match(r.error, /up to 30/));
r = await send({ type: "sub:rename", parent: PARENT, id: "nope", name: "Fine" });
check(() => assert.match(r.error, /no longer exists/));

// --- delete -----------------------------------------------------------------------------

r = await send({ type: "sub:remove", parent: PARENT, id: "interviews" });
check(() => assert.deepEqual(counts(r), { applications: 4, job_alerts: 4, other: 6 },
  "a deleted subcategory's messages go back to Other"));
r = await send({ type: "sub:remove", parent: PARENT, id: "applications" });
check(() => assert.equal(r.subs[PARENT], undefined, "one group left is no split"));
check(() => assert.equal(r.custom[0].count, 14, "the category itself is untouched"));

// --- a built-in mailbox can be split too ------------------------------------------------

const builtIn = Object.entries(r.counts).sort((a, b) => b[1] - a[1])[0][0];
r = await send({ type: "sub:split", parent: builtIn, label: "Built in" });
check(() => assert.equal(r.error, undefined));
check(() => assert.equal(r.subs[builtIn].items.length, 3));
check(() => assert.equal(r.subs[builtIn].items.reduce((n, s) => n + s.count, 0) + r.subs[builtIn].other,
  r.counts[builtIn], "every message of the mailbox is in one subcategory or Other"));

// --- deleting a category deletes its split ------------------------------------------------

await send(SPLIT);
check(() => assert.ok(storage.inboxiq_subs[PARENT]));
r = await send({ type: "custom:remove", id: "job_hunt" });
check(() => assert.ok(!(PARENT in storage.inboxiq_subs)));
check(() => assert.ok(r.subs[builtIn], "other splits stay"));

// --- showing a mailbox in Gmail's own list -------------------------------------------

globalThis.window = globalThis;
new Function(read("../src/panel.js"))();
await send({ type: "custom:add", name: "Job hunt", description: SPLIT.description });
await send({ type: "custom:sort" });
await send(SPLIT);
r = await send({ type: "status" });
const state = { messages: r.messages, custom: r.custom, subs: r.subs };
const ids = (view) => InboxIQ.viewRows(Object.assign({}, state, { view })).map((m) => m.id);
check(() => assert.equal(r.messages[0].rfc822_id, "id0@mail.example.com", "the scan keeps the Message-ID, without <>"));
check(() => assert.deepEqual(ids("sub|" + PARENT + "|interviews"), ["m00", "m01", "m02", "m03"]));
check(() => assert.deepEqual(ids("sub|" + PARENT + "|_other"), ["m12", "m13"]));
check(() => assert.equal(ids(PARENT).length, 14));
check(() => assert.equal(ids(null).length, 30, "all sorted mail"));
check(() => assert.deepEqual(ids(undefined), [], "the mailbox list has no rows"));
check(() => assert.equal(InboxIQ.gmailQuery(InboxIQ.viewRows(Object.assign({}, state, { view: "sub|" + PARENT + "|_other" }))),
  "{rfc822msgid:id12@mail.example.com rfc822msgid:id13@mail.example.com}"));
const rows = (list) => list.map((id) => ({ rfc822_id: id }));
check(() => assert.equal(InboxIQ.gmailQuery(rows(["", "a b", 'x"y'])), null, "no usable Message-ID, no search"));
check(() => assert.equal(InboxIQ.gmailIds(rows(Array.from({ length: 80 }, (_, n) => "i" + n + "@x"))).length, 50,
  "at most the newest 50"));

// --- the suggestion checks on their own ----------------------------------------------------

check(() => assert.deepEqual(InboxIQ.cleanSubs(null), []));
check(() => assert.deepEqual(InboxIQ.cleanSubs([{ name: "A", description: "a" }]), [], "fewer than two"));
const many = InboxIQ.cleanSubs(Array.from({ length: 6 }, (_, n) => ({ name: "Group " + n, description: "d" })));
check(() => assert.equal(many.length, 4, "at most four"));
const tidy = InboxIQ.cleanSubs([{ name: "  Big   deals ", description: " x\n y " }, "junk",
  { name: "Misc", description: "m" }, { name: "Misc promotions", description: "m" },
  { name: "General updates", description: "g" }, { name: "Coupons", description: "" }, { name: "Food", description: "f" }]);
check(() => assert.deepEqual(tidy, [{ id: "big_deals", name: "Big deals", description: "x y" },
  { id: "food", name: "Food", description: "f" }]));

console.log(checks + " subcategory checks passed");
