// Reply drafts, end to end through the service worker with a stand-in Gmail
// and a stand-in Groq: which message of the thread is answered, what text the
// model is given, the person's name, cleaning the draft, and failures. Also
// checks that drafting never writes to Gmail. No Google or Groq account
// involved.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const read = (name) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");
const b64url = (text) => Buffer.from(text, "utf8").toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const headers = (h) => Object.entries(h).map(([name, value]) => ({ name, value }));

// A thread: Priya asks, the account owner answers, Priya asks again with the
// earlier mail quoted under it.
const THREADS = {
  "18c0aa11bb22cc33": { messages: [
    { id: "a1", snippet: "Are you free?", payload: { mimeType: "text/plain",
      headers: headers({ From: "Priya Shah <priya@example.com>", Subject: "Project sync" }),
      body: { data: b64url("Are you free this week for a sync?") } } },
    { id: "a2", snippet: "Yes", payload: { mimeType: "text/plain",
      headers: headers({ From: "Sam Rivera <someone@example.com>", Subject: "Re: Project sync" }),
      body: { data: b64url("Yes, any afternoon works.") } } },
    { id: "a3", snippet: "Great", payload: { mimeType: "multipart/alternative",
      headers: headers({ From: "Priya Shah <priya@example.com>", Subject: "Re: Project sync" }),
      parts: [
        { mimeType: "text/plain", body: { data: b64url(
          "Great, could we do Thursday at 3? Café is fine too.\r\n\r\nOn Mon, Oct 27, 2026 at 9:00 AM Sam Rivera\r\n<someone@example.com> wrote:\r\n> Yes, any afternoon works.\r\n") } },
        { mimeType: "text/html", body: { data: b64url("<p>HTML VERSION</p>") } },
      ] } },
  ] },
  // HTML only, with a style block, entities and a quoted reply.
  "18c0aa11bb22cc44": { messages: [
    { id: "b1", snippet: "Your order", payload: { mimeType: "multipart/mixed",
      headers: headers({ From: "Shop <orders@shop.example>", Subject: "Order shipped" }),
      parts: [{ mimeType: "multipart/alternative", parts: [{ mimeType: "text/html", body: { data: b64url(
        "<style>p{color:red}</style><p>Your order&nbsp;#42 has shipped.</p><br>Track &amp; trace soon." +
        "<blockquote>OLD QUOTED MAIL</blockquote>") } }] }] } },
  ] },
  // Only the owner's own mail: the newest message is answered.
  "18c0aa11bb22cc55": { messages: [
    { id: "c1", snippet: "note to self", payload: { mimeType: "text/plain",
      headers: headers({ From: "someone@example.com", Subject: "Note" }), body: { data: b64url("Buy milk") } } },
  ] },
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
let answer = { reply: "Hi Priya,\r\n\r\n\r\nThursday at 3 works for me.   \n\nBest,\nSam", needs_reply: true,
  options: ["Suggest Friday instead.", "suggest friday instead", "", 42, "\"Decline politely\"", "Ask for the agenda", "A fourth one"] };
let groqMode = "ok"; // ok | junk | busy-once | 429 | 401
globalThis.fetch = async (url, options = {}) => {
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  if (url.startsWith("https://api.groq.com/")) {
    const body = JSON.parse(options.body);
    groqCalls.push({ system: body.messages[0].content, user: body.messages[1].content, temperature: body.temperature });
    if (groqMode === "401") return { ok: false, status: 401, json: async () => ({}) };
    if (groqMode === "429") return { ok: false, status: 429, json: async () => ({}) };
    if (groqMode === "busy-once") {
      groqMode = "ok";
      return { ok: false, status: 429, headers: new Headers({ "retry-after": "4" }), json: async () => ({}) };
    }
    const content = groqMode === "junk" ? "not json" : JSON.stringify(answer);
    return ok({ choices: [{ message: { content } }] });
  }
  gmailCalls.push({ url, method: options.method || "GET" });
  const path = url.replace("https://gmail.googleapis.com/gmail/v1/users/me", "");
  if (path === "/profile") return ok({ emailAddress: "someone@example.com" });
  if (path.startsWith("/messages?")) return ok({ messages: [] });
  const thread = /^\/threads\/([^?]+)\?format=full$/.exec(path);
  if (thread && THREADS[thread[1]]) return ok({ id: thread[1], ...THREADS[thread[1]] });
  return { ok: false, status: 404, statusText: "Not Found", json: async () => ({}) };
};

globalThis.importScripts = (...files) => {
  for (const f of files) {
    if (f.includes("local_key")) throw new Error("NetworkError: local_key.js not found");
    new Function("self", read("../src/" + f.replace("./", "")))(globalThis);
  }
};
new Function(read("../src/background.js")).call(globalThis);
const sleeps = [];
InboxIQ.sleep = async (ms) => { sleeps.push(ms); };
const send = (message) => new Promise((resolve) => listener(message, null, resolve));
const draft = (thread_id) => send({ type: "reply:draft", thread_id });
let checks = 0;
const check = (fn) => { fn(); checks += 1; };

await send({ type: "connect" });

// --- before anything is sent -----------------------------------------------------------

let r = await draft("18c0aa11bb22cc33");
check(() => assert.match(r.error, /Groq key/));
await send({ type: "ai:key", key: "gsk_test" });
for (const bad of [undefined, "", "../x", "#inbox"]) {
  r = await draft(bad);
  check(() => assert.equal(r.error, "Open an email first."));
}
check(() => assert.equal(groqCalls.length, 0, "nothing reaches the model without a key and an email"));

// --- a draft ---------------------------------------------------------------------------

r = await draft("18c0aa11bb22cc33");
check(() => assert.equal(r.error, undefined));
check(() => assert.deepEqual(r.draft, {
  thread_id: "18c0aa11bb22cc33", to: "priya@example.com", subject: "Re: Project sync",
  text: "Hi Priya,\n\nThursday at 3 works for me.\n\nBest,\nSam", needs_reply: true,
  options: ["Suggest Friday instead", "Decline politely", "Ask for the agenda"],
}, "answers Priya's newest message; the draft and the suggestions are tidied"));
check(() => assert.match(groqCalls[0].system, /"options"/));
const prompt = groqCalls[0].user;
check(() => assert.ok(prompt.includes("From: Priya Shah <priya@example.com>")));
check(() => assert.ok(prompt.includes("Subject: Re: Project sync")));
check(() => assert.ok(prompt.includes("could we do Thursday at 3? Café is fine too."), "UTF-8 text is decoded"));
check(() => assert.ok(!prompt.includes("any afternoon") && !prompt.includes("wrote:"), "quoted mail is left out"));
check(() => assert.ok(!prompt.includes("HTML VERSION"), "plain text wins over HTML"));
check(() => assert.ok(prompt.includes("The user's name: Sam Rivera"), "name taken from the owner's own mail"));
check(() => assert.ok(!prompt.includes("Are you free"), "only the message being answered is sent"));
check(() => assert.match(groqCalls[0].system, /Never make up/));
check(() => assert.ok(!prompt.includes("What the user wants to say"), "no note, no note line"));

// --- the person's own note ----------------------------------------------------------------

r = await send({ type: "reply:draft", thread_id: "18c0aa11bb22cc33", note: "  yes,\n but   Friday is better " });
check(() => assert.ok(groqCalls.at(-1).user.includes("What the user wants to say: yes, but Friday is better")));
check(() => assert.match(groqCalls.at(-1).system, /follow it over your own guess/));
await send({ type: "reply:draft", thread_id: "18c0aa11bb22cc33", note: "   " });
check(() => assert.ok(!groqCalls.at(-1).user.includes("What the user wants to say"), "a blank note is no note"));
check(() => assert.equal(InboxIQ.cleanNote("n".repeat(900)).length, InboxIQ.REPLY_NOTE_CHARS));

check(() => assert.deepEqual(InboxIQ.cleanOptions(["Yes, but Friday is better", "Decline"], "yes, but  Friday is better"),
  ["Decline"], "the choice already asked for is not offered again"));
check(() => assert.deepEqual(InboxIQ.cleanOptions("not a list"), []));

// --- Redraft -------------------------------------------------------------------------------

check(() => assert.equal(groqCalls[0].temperature, 0, "a first draft is steady"));
check(() => assert.ok(!groqCalls[0].user.includes("Earlier draft")));
await send({ type: "reply:draft", thread_id: "18c0aa11bb22cc33", note: "yes", previous: "Hi Priya,\n\nThursday works." });
check(() => assert.equal(groqCalls.at(-1).temperature, InboxIQ.REDRAFT_TEMPERATURE, "a redraft may vary"));
check(() => assert.ok(groqCalls.at(-1).user.endsWith("Earlier draft (write a different one):\nHi Priya,\n\nThursday works.")));
check(() => assert.ok(groqCalls.at(-1).user.includes("What the user wants to say: yes"), "the note still counts"));
check(() => assert.match(groqCalls.at(-1).system, /shown an earlier draft/));
await send({ type: "reply:draft", thread_id: "18c0aa11bb22cc33", previous: "  " });
check(() => assert.equal(groqCalls.at(-1).temperature, 0, "a blank earlier draft is a first draft"));

r = await draft("18c0aa11bb22cc44");
const htmlPrompt = groqCalls.at(-1).user;
check(() => assert.match(htmlPrompt, /Your order #42 has shipped\.\n+Track & trace soon\./, "HTML read as text"));
check(() => assert.ok(!htmlPrompt.includes("color:red") && !htmlPrompt.includes("OLD QUOTED")));
check(() => assert.ok(htmlPrompt.includes("The user's name: not given")));
check(() => assert.equal(r.draft.to, "orders@shop.example"));

answer = { reply: "Thanks, noted.", needs_reply: false };
r = await draft("18c0aa11bb22cc55");
check(() => assert.equal(r.draft.needs_reply, false, "automatic mail is flagged"));
check(() => assert.ok(groqCalls.at(-1).user.includes("Buy milk"), "a thread with only own mail answers the newest"));
answer = { reply: "Subject: Re: Note\n\nSure.", needs_reply: "yes" };
r = await draft("18c0aa11bb22cc55");
check(() => assert.equal(r.draft.text, "Sure.", "a repeated subject line is dropped"));
check(() => assert.equal(r.draft.needs_reply, true, "only an explicit false means no reply"));

// --- long emails are cut -----------------------------------------------------------------

check(() => {
  const long = InboxIQ.replyPrompt({ from: "a", subject: "b", text: "x".repeat(9000) }, "");
  assert.ok(long.length < InboxIQ.REPLY_TEXT_CHARS + 200);
});
check(() => assert.ok(InboxIQ.replyPrompt({ from: "a", subject: "Hello" }, "").includes("(no text, only the subject)")));
check(() => assert.equal(InboxIQ.cleanReply("y".repeat(5000)).length, InboxIQ.REPLY_MAX_CHARS));

// --- failures --------------------------------------------------------------------------

for (const [mode, message] of [["junk", /Couldn't write a reply/], ["429", /busy/], ["401", /key was rejected/]]) {
  groqMode = mode;
  r = await draft("18c0aa11bb22cc33");
  check(() => assert.match(r.error, message));
  check(() => assert.equal(r.draft, undefined));
}
answer = { reply: "   ", needs_reply: true };
groqMode = "ok";
r = await draft("18c0aa11bb22cc33");
check(() => assert.match(r.error, /Couldn't write a reply/, "an empty draft is an error, not a blank box"));

answer = { reply: "Sounds good.", needs_reply: true };
groqMode = "busy-once";
sleeps.length = 0;
r = await draft("18c0aa11bb22cc33");
check(() => assert.equal(r.draft.text, "Sounds good.", "a busy answer is retried"));
check(() => assert.deepEqual(sleeps, [4500]));

r = await draft("18c0aa11bb22cc99");
check(() => assert.match(r.error, /Gmail said 404/, "an unknown thread is reported"));

// --- never writes to Gmail -------------------------------------------------------------

check(() => assert.ok(gmailCalls.every((c) => c.method === "GET"), "only reads"));
check(() => assert.ok(!gmailCalls.some((c) => /send|drafts|modify/.test(c.url))));

console.log(checks + " reply draft checks passed");
