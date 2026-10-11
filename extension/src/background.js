// Gmail sign-in, reading and sorting. The content script holds no credentials
// and makes no Gmail calls: it asks this worker, which keeps the token in
// Chrome's own identity store and the sorted result in extension storage.
//
// Read-only throughout. Nothing is labelled, archived, moved or deleted, and
// no message text leaves the browser - sorting is the local rule classifier.
importScripts("./classifier.js");

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
    "?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date");
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
    from_name: from.name,
    subject: email.subject,
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
    return saved;
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
    return scan(token);
  }

  return { error: "Unknown request." };
}

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  handle(message).then(sendResponse, function (err) {
    sendResponse({ error: err && err.message ? err.message : String(err) });
  });
  return true; // reply arrives after the await
});
