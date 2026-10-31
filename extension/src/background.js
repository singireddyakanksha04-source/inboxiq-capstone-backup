// Gmail sign-in, reading and sorting. The content script holds no credentials
// and makes no Gmail calls: it asks this worker, which keeps the token in
// Chrome's own identity store and the sorted result in extension storage.
//
// Read-only throughout. Nothing is labelled, archived, moved or deleted.
// Built-in sorting is the local rule classifier and sends nothing anywhere.
// The person's own categories (personal.js) are the one exception: when they
// have added categories and their own Groq key, sender, subject and preview
// of the newest messages go to the model to be sorted into them. A reply
// draft (reply.js) sends the text of the one email the person asked about.
importScripts("./classifier.js", "./personal.js", "./reply.js");
// The developer's own Groq key, copied from .env by scripts/load_key.mjs.
// Git-ignored, so a fresh checkout has no such file and falls back to a key
// saved from the panel.
try {
  importScripts("./local_key.js");
} catch (err) {
  // no local key file
}

var GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me";
var SCAN_LIMIT = 150;   // newest messages in the inbox, kept small so a scan is quick
var BATCH = 10;         // concurrent metadata fetches

function getToken(interactive) {
  return new Promise(function (resolve, reject) {
    chrome.identity.getAuthToken({ interactive: interactive }, function (token) {
      if (chrome.runtime.lastError || !token) {
        reject(new Error(chrome.runtime.lastError ? chrome.runtime.lastError.message : "No Gmail access yet."));
        return;
      }
      resolve(token);
    });
  });
}

function dropToken(token) {
  return new Promise(function (resolve) {
    chrome.identity.removeCachedAuthToken({ token: token }, resolve);
  });
}

async function gmail(token, path) {
  var response = await fetch(GMAIL + path, { headers: { Authorization: "Bearer " + token } });
  if (response.status === 401) {
    // Chrome handed us a token Google has since expired or revoked.
    await dropToken(token);
    throw new Error("Gmail sign-in expired. Connect again.");
  }
  if (!response.ok) {
    throw new Error("Gmail said " + response.status + " " + response.statusText + ".");
  }
  return response.json();
}

function header(payload, name) {
  var headers = (payload && payload.headers) || [];
  for (var i = 0; i < headers.length; i++) {
    if (headers[i].name.toLowerCase() === name) return headers[i].value || "";
  }
  return "";
}

// 'Nike <news@nike.com>' -> { name: "Nike", domain: "nike.com" }
function parseFrom(raw) {
  var match = /<([^>]+)>/.exec(raw);
  var address = (match ? match[1] : raw).trim();
  var name = (match ? raw.slice(0, match.index) : "").trim().replace(/^"|"$/g, "");
  var at = address.lastIndexOf("@");
  return {
    name: name || address,
    address: address,
    domain: at === -1 ? "" : address.slice(at + 1).toLowerCase(),
  };
}

// Gmail's metadata format carries the headers, the label ids and the snippet,
// which is what the rule classifier reads. Full bodies are skipped on purpose:
// they are the slow part of a scan, and subject plus preview decides nearly
// every rule.
async function readMessage(token, id) {
  var raw = await gmail(token, "/messages/" + id +
    "?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date" +
    "&metadataHeaders=Message-ID");
  var from = parseFrom(header(raw.payload, "from"));
  var email = {
    id: raw.id,
    thread_id: raw.threadId,
    sender: header(raw.payload, "from"),
    sender_domain: from.domain,
    subject: header(raw.payload, "subject"),
    snippet: raw.snippet || "",
    body_text: "",
    labels: raw.labelIds || [],
  };
  var verdict = InboxIQ.classify(email);
  return {
    id: email.id,
    thread_id: email.thread_id,
    sender: email.sender,
    from_name: from.name,
    subject: email.subject,
    snippet: email.snippet,   // the preview the AI step reads for custom categories
    // The email's own Message-ID, which Gmail search finds with rfc822msgid:
    rfc822_id: header(raw.payload, "message-id").trim().replace(/^<|>$/g, ""),
    date: Number(raw.internalDate) || null,
    category: verdict.category,
    confidence: verdict.confidence,
    promo_subcategory: verdict.category === "promotion" ? InboxIQ.promoSubcategory(email) : null,
  };
}

async function listIds(token, limit) {
  var ids = [];
  var page = "";
  while (ids.length < limit) {
    var query = "/messages?q=in%3Ainbox&maxResults=" + Math.min(100, limit - ids.length) +
      (page ? "&pageToken=" + encodeURIComponent(page) : "");
    var data = await gmail(token, query);
    (data.messages || []).forEach(function (m) { ids.push(m.id); });
    page = data.nextPageToken || "";
    if (!page) break;
  }
  return ids;
}

async function scan(token) {
  var profile = await gmail(token, "/profile");
  var ids = await listIds(token, SCAN_LIMIT);
  var messages = [];
  for (var i = 0; i < ids.length; i += BATCH) {
    var slice = ids.slice(i, i + BATCH);
    var batch = await Promise.all(slice.map(function (id) {
      // One unreadable message must not sink the whole scan.
      return readMessage(token, id).catch(function () { return null; });
    }));
    batch.forEach(function (m) { if (m) messages.push(m); });
  }
  messages.sort(function (a, b) { return (b.date || 0) - (a.date || 0); });

  var counts = {};
  messages.forEach(function (m) { counts[m.category] = (counts[m.category] || 0) + 1; });

  var result = {
    connected: true,
    email: profile.emailAddress,
    counts: counts,
    messages: messages,
    scanned: messages.length,
    scanned_at: Date.now(),
  };
  await chrome.storage.local.set({ inboxiq: result });
  return result;
}

async function cached() {
  var stored = await chrome.storage.local.get("inboxiq");
  return stored.inboxiq || null;
}

// Signed-out answer: the panel shows Connect Gmail and nothing is requested.
var SIGNED_OUT = { connected: false, counts: {}, messages: [], scanned: 0 };

// --- the person's own categories ---------------------------------------------
//
// inboxiq_custom: { categories: [{ id, name, description }],
//                   results: { <message id>: { category, reason, sig } } }
// inboxiq_ai_key: the person's Groq key, kept only in this browser.

async function customStore() {
  var stored = await chrome.storage.local.get("inboxiq_custom");
  var custom = stored.inboxiq_custom || {};
  return { categories: custom.categories || [], results: custom.results || {} };
}

async function aiKey() {
  var stored = await chrome.storage.local.get("inboxiq_ai_key");
  return stored.inboxiq_ai_key || globalThis.InboxIQ_LOCAL_KEY || "";
}

// The scan as the panel sees it: each message carries its custom category
// (only if it was decided against the current category list) and the list
// comes with per-category counts.
async function decorate(result) {
  if (!result.connected) return result;
  var custom = await customStore();
  var sig = InboxIQ.customSignature(custom.categories);
  var counts = {};
  var messages = result.messages.map(function (m) {
    var r = custom.results[m.id];
    var hit = r && r.sig === sig && r.category ? r : null;
    if (hit) counts[hit.category] = (counts[hit.category] || 0) + 1;
    return Object.assign({}, m, {
      custom_category: hit ? hit.category : null,
      custom_reason: hit ? hit.reason : null,
    });
  });
  var split = await subStore();
  var subs = {};
  Object.keys(split).forEach(function (parent) {
    var entry = split[parent];
    var subCounts = {};
    var members = 0;
    messages.forEach(function (m) {
      if (!inParent(m, parent)) return;
      members += 1;
      var r = entry.results[m.id];
      var live = r && r.sub && entry.subs.some(function (s) { return s.id === r.sub; });
      // Each message may sit in a built-in and a custom parent at once.
      m.subs = Object.assign({}, m.subs);
      m.subs[parent] = live ? { id: r.sub, reason: r.reason } : null;
      if (live) subCounts[r.sub] = (subCounts[r.sub] || 0) + 1;
    });
    var placed = Object.values(subCounts).reduce(function (a, b) { return a + b; }, 0);
    subs[parent] = {
      items: entry.subs.map(function (s) { return Object.assign({}, s, { count: subCounts[s.id] || 0 }); }),
      other: members - placed,
    };
  });
  return Object.assign({}, result, {
    messages: messages,
    custom: custom.categories.map(function (c) {
      return Object.assign({}, c, { count: counts[c.id] || 0 });
    }),
    custom_max: InboxIQ.MAX_CUSTOM,
    subs: subs,
    split_min: InboxIQ.SPLIT_MIN,
    ai_ready: Boolean(await aiKey()),
  });
}

// --- subcategories -------------------------------------------------------------
//
// inboxiq_subs: { <parent>: { subs: [{ id, name, description }],
//                             results: { <message id>: { sub, reason } } } }
// <parent> is a built-in category ("promotion") or one of the person's own
// ("my:job_hunt"). A message in the parent without a live subcategory is
// shown as Other, so deleting a subcategory returns its messages there.

async function subStore() {
  var stored = await chrome.storage.local.get("inboxiq_subs");
  return stored.inboxiq_subs || {};
}

function inParent(message, parent) {
  if (parent.indexOf(InboxIQ.CUSTOM_PREFIX) === 0) {
    return message.custom_category === parent.slice(InboxIQ.CUSTOM_PREFIX.length);
  }
  return message.category === parent;
}

// The newest messages of the parent go to the model twice: once to propose
// subcategories, then in groups to be sorted into them. Nothing is saved
// unless both steps finish, so a failed split leaves the category as it was.
async function splitCategory(parent, label, description) {
  parent = String(parent || "");
  var saved = await cached();
  if (!saved || !parent) throw new Error("Connect Gmail first.");
  var view = await decorate(saved);
  var members = view.messages.filter(function (m) { return inParent(m, parent); })
    .slice(0, InboxIQ.AI_LIMIT);
  if (members.length < InboxIQ.SPLIT_MIN) {
    throw new Error("A category needs at least " + InboxIQ.SPLIT_MIN + " emails to split.");
  }
  var key = await aiKey();
  if (!key) throw new Error("Add your Groq key to split with AI.");

  var total = members.length + 1; // the suggestion step counts as one
  try {
    await chrome.storage.local.set({ inboxiq_ai_progress: { done: 0, total: total } });
    var subs = await InboxIQ.aiSuggestSubs(key, String(label || parent), String(description || ""), members);
    if (!subs.length) throw new Error("Couldn't find clear subcategories in these emails.");
    await chrome.storage.local.set({ inboxiq_ai_progress: { done: 1, total: total } });
    var results = {};
    for (var i = 0; i < members.length; i += InboxIQ.AI_BATCH) {
      var batch = members.slice(i, i + InboxIQ.AI_BATCH);
      var answers = await InboxIQ.aiSortBatch(key, subs, batch);
      batch.forEach(function (m, j) {
        results[m.id] = { sub: answers[j].category, reason: answers[j].reason };
      });
      await chrome.storage.local.set({ inboxiq_ai_progress: { done: 1 + i + batch.length, total: total } });
    }
    var store = await subStore();
    store[parent] = { subs: subs, results: results };
    await chrome.storage.local.set({ inboxiq_subs: store });
  } finally {
    await chrome.storage.local.set({ inboxiq_ai_progress: null });
  }
}

async function renameSub(parent, id, name) {
  name = String(name || "").replace(/\s+/g, " ").trim();
  if (!name || name.length > 30) throw new Error("Give the subcategory a name of up to 30 characters.");
  var store = await subStore();
  var entry = store[parent];
  var sub = entry && entry.subs.filter(function (s) { return s.id === id; })[0];
  if (!sub) throw new Error("That subcategory no longer exists.");
  if (entry.subs.some(function (s) { return s.id !== id && s.name.toLowerCase() === name.toLowerCase(); })) {
    throw new Error("There is already a subcategory called " + name + ".");
  }
  sub.name = name;
  await chrome.storage.local.set({ inboxiq_subs: store });
}

async function removeSub(parent, id) {
  var store = await subStore();
  var entry = store[parent];
  if (!entry) return;
  entry.subs = entry.subs.filter(function (s) { return s.id !== id; });
  Object.keys(entry.results).forEach(function (msgId) {
    if (entry.results[msgId].sub === id) delete entry.results[msgId];
  });
  // One group left is no split at all.
  if (entry.subs.length < 2) delete store[parent];
  await chrome.storage.local.set({ inboxiq_subs: store });
}

async function addCategory(name, description) {
  name = String(name || "").trim();
  description = String(description || "").replace(/\s+/g, " ").trim();
  if (!name || name.length > 30) throw new Error("Give the category a name of up to 30 characters.");
  if (description.length < 5 || description.length > 200) {
    throw new Error("Describe the category in one sentence (5 to 200 characters).");
  }
  var custom = await customStore();
  if (custom.categories.length >= InboxIQ.MAX_CUSTOM) {
    throw new Error("You can have up to " + InboxIQ.MAX_CUSTOM + " categories.");
  }
  if (custom.categories.some(function (c) { return c.name.toLowerCase() === name.toLowerCase(); })) {
    throw new Error("You already have a category called " + name + ".");
  }
  var id = InboxIQ.customId(name, custom.categories.map(function (c) { return c.id; }));
  custom.categories.push({ id: id, name: name, description: description });
  await chrome.storage.local.set({ inboxiq_custom: custom });
}

async function removeCategory(id) {
  var custom = await customStore();
  custom.categories = custom.categories.filter(function (c) { return c.id !== id; });
  await chrome.storage.local.set({ inboxiq_custom: custom });
  var store = await subStore();
  if (store[InboxIQ.CUSTOM_PREFIX + id]) {
    delete store[InboxIQ.CUSTOM_PREFIX + id];
    await chrome.storage.local.set({ inboxiq_subs: store });
  }
}

// Ask the model about the newest messages not yet checked against the
// current category list. A model failure comes back as ai_error next to the
// scan, so the built-in mailboxes keep working.
async function aiSort() {
  var saved = await cached();
  if (!saved) return SIGNED_OUT;
  var custom = await customStore();
  var key = await aiKey();
  var error = null;
  if (custom.categories.length && !key) error = "Add your Groq key to sort with AI.";
  if (custom.categories.length && key) {
    var sig = InboxIQ.customSignature(custom.categories);
    var newest = saved.messages.slice(0, InboxIQ.AI_LIMIT);
    var pending = newest.filter(function (m) {
      var r = custom.results[m.id];
      return !r || r.sig !== sig;
    });
    // Forget results for messages that have left the scan.
    var keep = {};
    saved.messages.forEach(function (m) { if (custom.results[m.id]) keep[m.id] = custom.results[m.id]; });
    custom.results = keep;
    // The panel draws a progress bar from this while the batches run.
    await chrome.storage.local.set({ inboxiq_ai_progress: { done: 0, total: pending.length } });
    for (var i = 0; i < pending.length; i += InboxIQ.AI_BATCH) {
      var batch = pending.slice(i, i + InboxIQ.AI_BATCH);
      var answers;
      try {
        answers = await InboxIQ.aiSortBatch(key, custom.categories, batch);
      } catch (err) {
        error = err.message;
        break;
      }
      batch.forEach(function (m, j) {
        custom.results[m.id] = { category: answers[j].category, reason: answers[j].reason, sig: sig };
      });
      await chrome.storage.local.set({
        inboxiq_ai_progress: { done: Math.min(i + batch.length, pending.length), total: pending.length },
      });
    }
    await chrome.storage.local.set({ inboxiq_custom: custom, inboxiq_ai_progress: null });
  }
  var result = await decorate(saved);
  result.ai_error = error;
  return result;
}

// --- reply drafts ------------------------------------------------------------
//
// The thread open in Gmail is read in full (read-only, like the scan) and the
// model drafts a reply to its newest message from someone else. The draft is
// handed back to the panel; it is never sent or saved to Gmail from here.

async function draftReply(threadId, note, previous) {
  if (!/^[0-9a-f]{6,24}$/i.test(String(threadId || ""))) throw new Error("Open an email first.");
  var key = await aiKey();
  if (!key) throw new Error("Add your Groq key to draft replies.");
  var token = await getToken(false);
  var saved = await cached();
  var me = String((saved && saved.email) || "").toLowerCase();
  var thread = await gmail(token, "/threads/" + threadId + "?format=full");
  var messages = thread.messages || [];
  var fromOf = function (m) { return parseFrom(header(m.payload, "from")); };
  var mine = function (m) { return Boolean(me) && fromOf(m).address.toLowerCase() === me; };
  var theirs = messages.filter(function (m) { return !mine(m); });
  var target = theirs[theirs.length - 1] || messages[messages.length - 1];
  if (!target) throw new Error("Couldn't read this email.");
  // The person's own name as their earlier mail in this thread shows it.
  var sent = messages.filter(mine)[0];
  var ownerName = sent && fromOf(sent).name !== fromOf(sent).address ? fromOf(sent).name : "";
  var from = fromOf(target);
  var subject = header(target.payload, "subject");
  var draft = await InboxIQ.draftReply(key, {
    from: header(target.payload, "from"),
    subject: subject,
    text: InboxIQ.emailText(target.payload) || target.snippet || "",
  }, ownerName, note, previous);
  return { draft: {
    thread_id: threadId,
    to: from.address,
    subject: subject,
    text: draft.text,
    needs_reply: draft.needs_reply,
    options: draft.options,
  } };
}

async function current() {
  return decorate((await cached()) || SIGNED_OUT);
}

async function handle(message) {
  if (message.type === "status") {
    var saved = await cached();
    if (!saved) return SIGNED_OUT;
    // Confirm Chrome still holds a token, without ever showing a prompt.
    try {
      await getToken(false);
    } catch (err) {
      return SIGNED_OUT;
    }
    return decorate(saved);
  }

  if (message.type === "custom:add") {
    await addCategory(message.name, message.description);
    return current();
  }
  if (message.type === "custom:remove") {
    await removeCategory(message.id);
    return current();
  }
  if (message.type === "ai:key") {
    var key = String(message.key || "").trim();
    if (key) await chrome.storage.local.set({ inboxiq_ai_key: key });
    else await chrome.storage.local.remove("inboxiq_ai_key");
    return current();
  }
  if (message.type === "custom:sort") {
    return aiSort();
  }
  if (message.type === "sub:split") {
    await splitCategory(message.parent, message.label, message.description);
    return current();
  }
  if (message.type === "sub:rename") {
    await renameSub(message.parent, message.id, message.name);
    return current();
  }
  if (message.type === "sub:remove") {
    await removeSub(message.parent, message.id);
    return current();
  }

  if (message.type === "reply:draft") {
    return draftReply(message.thread_id, message.note, message.previous);
  }

  if (message.type === "connect" || message.type === "scan") {
    var token;
    try {
      token = await getToken(false);
    } catch (err) {
      // Rescans stay silent until Chrome has actually lost the grant; then
      // they ask the same way the Connect button does.
      token = await getToken(true);
    }
    return decorate(await scan(token));
  }

  return { error: "Unknown request." };
}

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  handle(message).then(sendResponse, function (err) {
    sendResponse({ error: err && err.message ? err.message : String(err) });
  });
  return true; // reply arrives after the await
});
