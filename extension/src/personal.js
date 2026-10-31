// Each person's own categories, filled by the Groq model. The person names a
// category and describes it in one sentence ("emails about my job
// applications, interviews and recruiters"); the model reads each message's
// sender, subject and Gmail preview and picks one of those categories, or
// none, with a short reason the person can check.
//
// Only sender, subject and preview are sent - the same fields a scan already
// reads - and only when the person has added categories and their own Groq
// key. The key stays in this browser's extension storage, never in the code.
(function (InboxIQ) {
  var GROQ = "https://api.groq.com/openai/v1/chat/completions";
  var MODEL = "openai/gpt-oss-20b";   // the backend's "small" model
  var PREVIEW_CHARS = 300;
  var REASON_CHARS = 120;

  InboxIQ.CUSTOM_PREFIX = "my:";  // mailbox key of a custom category, as in categories.js
  InboxIQ.MAX_CUSTOM = 5;
  InboxIQ.AI_BATCH = 10;   // messages per request, so 50 messages is 5 calls
  InboxIQ.AI_LIMIT = 50;   // newest messages the model looks at per scan

  // "Job hunt!" -> "job_hunt", made unique against the ids already taken.
  InboxIQ.customId = function (name, taken) {
    var base = String(name).trim().toLowerCase().replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "").slice(0, 30) || "category";
    var id = base;
    for (var n = 2; taken.indexOf(id) !== -1; n++) id = base + "_" + n;
    return id;
  };

  // Changes whenever a category is added, removed or re-described, so mail is
  // only sent to the model again when the answer could be different.
  InboxIQ.customSignature = function (categories) {
    var text = JSON.stringify(categories.map(function (c) { return [c.id, c.name, c.description]; }));
    var hash = 5381;
    for (var i = 0; i < text.length; i++) hash = ((hash * 33) ^ text.charCodeAt(i)) >>> 0;
    return hash.toString(36);
  };

  var SYSTEM =
    "You sort emails into categories that the user defined themselves. " +
    "Each category has an id, a name and the user's own description. " +
    "For every email, pick the one category whose description it clearly fits, " +
    "or \"none\" if no description fits. Prefer \"none\" over a weak guess. " +
    "Give a short reason (under 15 words) that names what in the email matched.\n" +
    // Groq's JSON mode requires the word JSON and the shape spelled out here.
    'Reply with JSON only: {"results": [{"i": <email number>, ' +
    '"category": <category id or "none">, "reason": <short string>}]}';

  InboxIQ.aiPrompt = function (categories, messages) {
    var lines = ["Categories:"];
    categories.forEach(function (c) {
      lines.push("- id: " + c.id + " | name: " + c.name + " | description: " + c.description);
    });
    lines.push("\nEmails:");
    messages.forEach(function (m, i) {
      var preview = String(m.snippet || "").replace(/\s+/g, " ").trim().slice(0, PREVIEW_CHARS);
      lines.push("[" + i + "] From: " + (m.sender || m.from_name || "") +
        "\n    Subject: " + (m.subject || "") + "\n    Preview: " + preview);
    });
    return lines.join("\n");
  };

  // One JSON-mode request. Returns the parsed answer ({} when it cannot be
  // read). Throws an Error whose message is safe to show when the model
  // cannot be reached.
  // Groq's free tier counts tokens per minute, and a split or a full sort is
  // several requests in a row, so a "busy" answer is normal. Wait as long as
  // Groq says (capped) and try again before giving up.
  InboxIQ.RETRIES = 3;
  InboxIQ.MAX_WAIT_MS = 30000;
  InboxIQ.sleep = function (ms) { return new Promise(function (done) { setTimeout(done, ms); }); };

  // "7.5" (retry-after, seconds) or "13.4s" / "1m2s" (x-ratelimit-reset-tokens).
  function waitFor(response) {
    var get = function (name) {
      return response.headers && response.headers.get ? response.headers.get(name) : null;
    };
    var after = parseFloat(get("retry-after"));
    if (after > 0) return after * 1000;
    var reset = /^(?:(\d+)m)?([\d.]+)s$/.exec(String(get("x-ratelimit-reset-tokens") || ""));
    if (reset) return ((Number(reset[1]) || 0) * 60 + Number(reset[2])) * 1000;
    return 10000;
  }

  // temperature 0 unless asked: sorting must give the same answer every time.
  async function ask(key, system, user, temperature) {
    var response;
    for (var attempt = 0; ; attempt++) {
      try {
        response = await fetch(GROQ, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: "Bearer " + key },
          body: JSON.stringify({
            model: MODEL,
            temperature: temperature || 0,
            max_tokens: 1500,
            reasoning_effort: "low",  // fewer tokens per answer, so fewer busy replies
            response_format: { type: "json_object" },
            messages: [
              { role: "system", content: system },
              { role: "user", content: user },
            ],
          }),
        });
      } catch (err) {
        throw new Error("The AI is unavailable right now.");
      }
      if (response.status !== 429 || attempt >= InboxIQ.RETRIES) break;
      await InboxIQ.sleep(Math.min(waitFor(response) + 500, InboxIQ.MAX_WAIT_MS));
    }
    if (response.status === 401) throw new Error("The Groq key was rejected. Check it and save it again.");
    if (response.status === 429) throw new Error("The AI is busy (rate limit). Try again in a minute.");
    if (!response.ok) throw new Error("The AI is unavailable right now.");
    try {
      var body = await response.json();
      return JSON.parse(body.choices[0].message.content || "{}") || {};
    } catch (err) {
      return {};
    }
  }
  InboxIQ.ask = ask;  // reply.js drafts replies through the same request

  // One { category: id|null, reason } per message, in order.
  InboxIQ.aiSortBatch = async function (key, categories, messages) {
    // An unreadable answer means every message is no match.
    var data = await ask(key, SYSTEM, InboxIQ.aiPrompt(categories, messages));

    var known = categories.map(function (c) { return c.id; });
    var out = messages.map(function () { return { category: null, reason: "" }; });
    var rows = data && Array.isArray(data.results) ? data.results : [];
    rows.forEach(function (row) {
      if (!row || typeof row !== "object") return;
      var i = parseInt(row.i, 10);
      if (!(i >= 0 && i < messages.length)) return;
      var id = String(row.category || "").trim();
      // An id the person never made (or "none") means no match.
      if (known.indexOf(id) === -1) return;
      out[i] = { category: id, reason: String(row.reason || "").replace(/\s+/g, " ").trim().slice(0, REASON_CHARS) };
    });
    return out;
  };

  // --- splitting one category into subcategories ------------------------------
  //
  // The model reads sender and subject of the emails already in a category and
  // proposes a few smaller groups, each with a name and a one-sentence
  // description. Those descriptions then go through aiSortBatch like the
  // person's own categories, so every email gets a subcategory (or none, shown
  // as Other) and a reason.

  InboxIQ.SPLIT_MIN = 6;    // fewer emails than this are not worth splitting
  InboxIQ.SPLIT_SUBS = 4;   // at most this many subcategories
  // "Other", "Misc promotions", "General updates": the leftovers already have Other.
  var CATCH_ALL = /\b(other|others|misc|miscellaneous|general|everything else|rest)\b/i;

  var SPLIT_SYSTEM =
    "You split one email category into smaller subcategories. " +
    "You get the category's name, its description if there is one, and the sender and " +
    "subject of the emails in it. Suggest 2 to 4 subcategories that together cover most " +
    "of these emails and are clearly different from each other. Give each a short name " +
    "(1 to 3 words) and a one-sentence description of which emails belong in it. " +
    "Do not suggest a catch-all such as Other or Misc.\n" +
    'Reply with JSON only: {"subcategories": [{"name": <short name>, "description": <one sentence>}]}';

  InboxIQ.splitPrompt = function (label, description, messages) {
    var lines = ["Category: " + label];
    if (description) lines.push("Description: " + description);
    lines.push("\nEmails:");
    messages.forEach(function (m, i) {
      lines.push("[" + i + "] From: " + (m.sender || m.from_name || "") + " | Subject: " + (m.subject || ""));
    });
    return lines.join("\n");
  };

  // The suggestions, cleaned: names trimmed to 30 characters, descriptions to
  // 200, no empty, repeated or catch-all names, at most SPLIT_SUBS. Each gets
  // an id. Fewer than two usable suggestions means there is nothing to split.
  InboxIQ.cleanSubs = function (raw) {
    var out = [];
    var seen = [];
    (Array.isArray(raw) ? raw : []).forEach(function (s) {
      if (!s || typeof s !== "object" || out.length >= InboxIQ.SPLIT_SUBS) return;
      var name = String(s.name || "").replace(/\s+/g, " ").trim().slice(0, 30);
      var description = String(s.description || "").replace(/\s+/g, " ").trim().slice(0, 200);
      var lower = name.toLowerCase();
      if (!name || !description || seen.indexOf(lower) !== -1 || CATCH_ALL.test(name)) return;
      seen.push(lower);
      out.push({ id: InboxIQ.customId(name, out.map(function (o) { return o.id; })), name: name, description: description });
    });
    return out.length >= 2 ? out : [];
  };

  InboxIQ.aiSuggestSubs = async function (key, label, description, messages) {
    var data = await ask(key, SPLIT_SYSTEM, InboxIQ.splitPrompt(label, description, messages));
    return InboxIQ.cleanSubs(data && data.subcategories);
  };
})(self.InboxIQ || (self.InboxIQ = {}));
