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

  // One { category: id|null, reason } per message, in order. Throws an Error
  // whose message is safe to show when the model cannot be reached.
  InboxIQ.aiSortBatch = async function (key, categories, messages) {
    var response;
    try {
      response = await fetch(GROQ, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + key },
        body: JSON.stringify({
          model: MODEL,
          temperature: 0,
          max_tokens: 1500,
          response_format: { type: "json_object" },
          messages: [
            { role: "system", content: SYSTEM },
            { role: "user", content: InboxIQ.aiPrompt(categories, messages) },
          ],
        }),
      });
    } catch (err) {
      throw new Error("AI sorting is unavailable right now.");
    }
    if (response.status === 401) throw new Error("The Groq key was rejected. Check it and save it again.");
    if (response.status === 429) throw new Error("The AI is busy (rate limit). Try again in a minute.");
    if (!response.ok) throw new Error("AI sorting is unavailable right now.");

    var data = {};
    try {
      var body = await response.json();
      data = JSON.parse(body.choices[0].message.content || "{}");
    } catch (err) {
      data = {};  // unreadable answer: treat every message as no match
    }

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
})(self.InboxIQ || (self.InboxIQ = {}));
