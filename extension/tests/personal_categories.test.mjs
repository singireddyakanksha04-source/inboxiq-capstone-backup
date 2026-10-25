// The person's own categories, end to end through the service worker, with a
// stand-in Gmail and a stand-in Groq: adding and removing categories, the key
// staying in extension storage, batching, what is sent to the model, caching,
// bad model answers and model failures. No Google or Groq account involved.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const read = (name) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");

// 25 inbox messages; every third one is about an interview.
const MAIL = Array.from({ length: 25 }, (_, n) => ({
  id: "m" + String(n).padStart(2, "0"),
  threadId: "t" + n,
  internalDate: String(1700000000000 - n * 1000),
  snippet: n % 3 === 0 ? "Please pick a time for your interview" : "Weekly update",
  labelIds: ["INBOX"],
  headers: { From: n % 3 === 0 ? "Greenhouse <no-reply@greenhouse.io>" : "News <news@example.com>",
    Subject: n % 3 === 0 ? "Interview availability" : "This week " + n },
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

// --- stand-in Groq: answers by looking for "interview" in each email block ---
const groqCalls = [];
let groqMode = "ok"; // ok | junk | invented | 429 | 401 | offline
function groqAnswer(prompt) {
  const ids = [...prompt.matchAll(/- id: (\S+)/g)].map((m) => m[1]);
  const blocks = prompt.split("\nEmails:")[1].split(/\n(?=\[\d+\])/).filter(Boolean);
  return blocks.map((block) => {
    const i = Number(/^\[(\d+)\]/.exec(block.trim())[1]);
    const hit = /interview/i.test(block) && ids.includes("job_hunt");
    return { i, category: hit ? "job_hunt" : "none", reason: hit ? "Interview\n  invite" : "" };
  });
}

globalThis.fetch = async (url, options) => {
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  if (url.startsWith("https://api.groq.com/")) {
    const body = JSON.parse(options.body);
    groqCalls.push({ key: options.headers.Authorization, body });
    if (groqMode === "offline") throw new TypeError("Failed to fetch");
    if (groqMode === "429") return { ok: false, status: 429, json: async () => ({}) };
    if (groqMode === "401") return { ok: false, status: 401, json: async () => ({}) };
    const content = groqMode === "junk" ? "not json"
      : groqMode === "invented" ? JSON.stringify({ results: [{ i: 0, category: "made_up" }, { i: 99, category: "job_hunt" }, "x"] })
      : JSON.stringify({ results: groqAnswer(body.messages[1].content) });
    return ok({ choices: [{ message: { content } }] });
  }
  assert.equal(options.headers.Authorization, "Bearer token-1", "Gmail calls never carry the Groq key");
  const path = url.replace("https://gmail.googleapis.com/gmail/v1/users/me", "");
  if (path === "/profile") return ok({ emailAddress: "someone@example.com" });
  if (path.startsWith("/messages?")) return ok({ messages: MAIL.map(({ id }) => ({ id })) });
  const mail = MAIL.find((m) => m.id === /\/messages\/([^?]+)/.exec(path)[1]);
  return ok({ id: mail.id, threadId: mail.threadId, internalDate: mail.internalDate, snippet: mail.snippet,
    labelIds: mail.labelIds, payload: { headers: Object.entries(mail.headers).map(([name, value]) => ({ name, value })) } });
};

globalThis.importScripts = (...files) => {
  for (const f of files) {
    // Like a fresh checkout: the git-ignored key file is not there.
    if (f.includes("local_key")) throw new Error("NetworkError: local_key.js not found");
    new Function("self", read("../src/" + f.replace("./", "")))(globalThis);
  }
};
new Function(read("../src/background.js")).call(globalThis);
// Busy answers are retried after a wait; no real waiting in tests.
const sleeps = [];
InboxIQ.sleep = async (ms) => { sleeps.push(ms); };
const send = (message) => new Promise((resolve) => listener(message, null, resolve));
const JOBS = { type: "custom:add", name: "Job hunt", description: "emails about my job applications, interviews and recruiters" };
let checks = 0;
const check = (fn) => { fn(); checks += 1; };

// --- before any categories --------------------------------------------------

const scanned = await send({ type: "connect" });
check(() => assert.deepEqual(scanned.custom, [], "no categories yet"));
check(() => assert.equal(scanned.ai_ready, false));
check(() => assert.equal(scanned.messages[0].custom_category, null));
check(() => assert.equal(groqCalls.length, 0, "a scan alone never calls the model"));

// --- adding categories --------------------------------------------------------

let r = await send({ type: "custom:add", name: "", description: "something long" });
check(() => assert.match(r.error, /name/i));
r = await send({ type: "custom:add", name: "X", description: "  ab  " });
check(() => assert.match(r.error, /one sentence/i));
r = await send(JOBS);
check(() => assert.deepEqual(r.custom.map((c) => [c.id, c.name, c.count]), [["job_hunt", "Job hunt", 0]]));
r = await send({ ...JOBS, name: "JOB HUNT" });
check(() => assert.match(r.error, /already have/i));
for (let n = 0; n < 4; n++) await send({ type: "custom:add", name: "Cat " + n, description: "a description" });
r = await send({ type: "custom:add", name: "One more", description: "a description" });
check(() => assert.match(r.error, /up to 5/i));
for (let n = 0; n < 4; n++) await send({ type: "custom:remove", id: "cat_" + n });
check(() => assert.deepEqual(InboxIQ.customId("Job hunt", ["job_hunt"]), "job_hunt_2"));
check(() => assert.equal(InboxIQ.customId("../!!", []), "category"));

// --- sorting needs the key ----------------------------------------------------

r = await send({ type: "custom:sort" });
check(() => assert.equal(r.ai_error, "Add your Groq key to sort with AI."));
check(() => assert.equal(groqCalls.length, 0));

r = await send({ type: "ai:key", key: "  gsk_test  " });
check(() => assert.equal(r.ai_ready, true));
check(() => assert.equal(storage.inboxiq_ai_key, "gsk_test", "key kept in extension storage, trimmed"));
check(() => assert.ok(!JSON.stringify(r).includes("gsk_test"), "the key is never sent back to the page"));

// --- sorting ------------------------------------------------------------------

r = await send({ type: "custom:sort" });
check(() => assert.equal(r.ai_error, null));
check(() => assert.equal(groqCalls.length, 3, "25 messages go to the model 10 at a time"));
check(() => assert.equal(groqCalls[0].key, "Bearer gsk_test"));
check(() => assert.equal(groqCalls[0].body.response_format.type, "json_object"));
const prompt = groqCalls[0].body.messages[1].content;
check(() => assert.ok(prompt.includes("emails about my job applications"), "the description guides the model"));
check(() => assert.ok(prompt.includes("Greenhouse <no-reply@greenhouse.io>") && prompt.includes("Please pick a time")));
check(() => assert.ok(!prompt.includes("token-1"), "no Gmail credentials in the prompt"));
const hits = r.messages.filter((m) => m.custom_category === "job_hunt");
check(() => assert.equal(hits.length, 9, "every interview message, and only those"));
check(() => assert.equal(hits[0].custom_reason, "Interview invite", "reason whitespace tidied"));
check(() => assert.equal(r.custom[0].count, 9));
check(() => assert.equal(storage.inboxiq_ai_progress, null, "progress is cleared once sorting ends"));
check(() => assert.equal(r.messages.find((m) => m.id === "m00").category !== undefined, true, "built-in category kept"));

r = await send({ type: "status" });
check(() => assert.equal(r.custom[0].count, 9, "results survive a panel reload"));

r = await send({ type: "custom:sort" });
check(() => assert.equal(groqCalls.length, 3, "already-checked messages are not sent again"));

// --- changing the categories re-checks the mail --------------------------------

await send({ type: "custom:add", name: "Travel", description: "flights and hotels" });
r = await send({ type: "status" });
check(() => assert.equal(r.custom[0].count, 0, "old answers no longer count once the list changed"));
r = await send({ type: "custom:sort" });
check(() => assert.equal(groqCalls.length, 6));
check(() => assert.equal(r.custom.find((c) => c.id === "job_hunt").count, 9));

// --- bad answers and failures ---------------------------------------------------

await send({ type: "custom:remove", id: "travel" });
groqMode = "junk";
r = await send({ type: "custom:sort" });
check(() => assert.equal(r.ai_error, null));
check(() => assert.equal(r.custom[0].count, 0, "an unreadable answer means no match, not a crash"));

await send({ type: "custom:add", name: "Travel", description: "flights and hotels" });
groqMode = "invented";
r = await send({ type: "custom:sort" });
check(() => assert.equal(r.custom.reduce((n, c) => n + c.count, 0), 0, "invented ids and positions are ignored"));

await send({ type: "custom:remove", id: "travel" });
for (const [mode, message] of [["429", /busy/], ["401", /key was rejected/], ["offline", /unavailable/]]) {
  groqMode = mode;
  r = await send({ type: "custom:sort" });
  check(() => assert.match(r.ai_error, message));
  check(() => assert.equal(r.connected, true, "built-in mailboxes still work when the model fails"));
  await send({ type: "custom:add", name: "Tmp " + mode, description: "forces a re-check" });
}

// --- removing ------------------------------------------------------------------

r = await send({ type: "custom:remove", id: "job_hunt" });
check(() => assert.ok(!r.custom.some((c) => c.id === "job_hunt")));
check(() => assert.ok(r.messages.every((m) => m.custom_category !== "job_hunt")));
r = await send({ type: "ai:key", key: "" });
check(() => assert.equal(r.ai_ready, false));
check(() => assert.ok(!("inboxiq_ai_key" in storage), "clearing the key removes it"));

// --- a key copied from .env by scripts/load_key.mjs ------------------------------

globalThis.InboxIQ_LOCAL_KEY = "gsk_from_env";
groqMode = "ok";
await send(JOBS);
r = await send({ type: "custom:sort" });
check(() => assert.equal(r.ai_ready, true, "no key typed in, the local file is enough"));
check(() => assert.equal(groqCalls.at(-1).key, "Bearer gsk_from_env"));
check(() => assert.ok(!JSON.stringify(r).includes("gsk_from_env"), "the file's key is never sent to the page"));

console.log(checks + " personal category checks passed");
