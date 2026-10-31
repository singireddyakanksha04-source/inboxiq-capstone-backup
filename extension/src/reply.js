// Reply drafts. The person opens an email in Gmail and asks for a draft; the
// worker reads that one email and the Groq model writes a reply in their name.
// The draft only ever goes into Gmail's reply box (or the clipboard): the
// person reads it, edits it and presses Send themselves. Nothing is sent here.
//
// Unlike sorting, a draft needs the email's text, not just its preview. That
// text goes to the model only for the email the person asked about, only when
// they ask.
(function (InboxIQ) {
  InboxIQ.REPLY_TEXT_CHARS = 4000;  // longer emails are cut; the start says what is asked
  InboxIQ.REPLY_MAX_CHARS = 2000;
  InboxIQ.REPLY_NOTE_CHARS = 300;   // the person's own "what to say", optional
  // A first draft is steady; Redraft is told what it wrote before and may vary.
  InboxIQ.REDRAFT_TEMPERATURE = 0.8;
  InboxIQ.REPLY_OPTIONS = 3;         // suggested "what to say" choices per draft

  var REPLY_SYSTEM =
    "You write email replies for the user. You get one email they received: who sent it, " +
    "the subject and its text. Write the reply the user would send. Answer what the email " +
    "asks, in plain and polite language, in the same language as the email. Keep it short " +
    "(under 120 words) unless the email really needs more. Never make up facts, dates, times, " +
    "prices, links or promises. Never choose a time, date or option for the user that the " +
    "email does not fix already; put what the user has to fill in in square brackets, like " +
    "[day and time]. Do not repeat the subject or quote the email. Start with a greeting " +
    "that uses the sender's first name if the sender is a person, otherwise just Hello. " +
    "End with a short sign-off " +
    "and the user's name if it is given, otherwise the sign-off alone. Also say whether the " +
    "email needs a reply at all: newsletters, receipts and automatic notices usually do not. " +
    "If the user says what they want to say, build the reply around that and follow it " +
    "over your own guess. If you are shown an earlier draft, the user wants a different " +
    "one: change the wording and structure, but keep to the same rules. Also suggest 2 to 3 " +
    "other things the user might want to say instead, as different answers (for example " +
    "yes, no, or later), in under 6 words each, like \"Decline politely\".\n" +
    'Reply with JSON only: {"reply": <the reply text, paragraphs separated by \\n\\n>, ' +
    '"needs_reply": <true or false>, "options": [<short string>]}';

  InboxIQ.cleanNote = function (note) {
    return String(note || "").replace(/\s+/g, " ").trim().slice(0, InboxIQ.REPLY_NOTE_CHARS);
  };

  InboxIQ.replyPrompt = function (email, ownerName, note, previous) {
    var text = String(email.text || "").trim().slice(0, InboxIQ.REPLY_TEXT_CHARS);
    var lines = [
      "From: " + (email.from || ""),
      "Subject: " + (email.subject || ""),
      "The user's name: " + (ownerName || "not given"),
    ];
    note = InboxIQ.cleanNote(note);
    if (note) lines.push("What the user wants to say: " + note);
    lines = lines.concat(["", "Email text:", text || "(no text, only the subject)"]);
    previous = InboxIQ.cleanReply(previous);
    if (previous) lines.push("", "Earlier draft (write a different one):", previous);
    return lines.join("\n");
  };

  // Trimmed, Windows line ends and runs of blank lines folded, a stray
  // "Subject:" line dropped. Empty when there is nothing usable.
  InboxIQ.cleanReply = function (raw) {
    var text = typeof raw === "string" ? raw : "";
    text = text.replace(/\r\n?/g, "\n").replace(/^\s*subject:.*\n+/i, "")
      .replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    return text.slice(0, InboxIQ.REPLY_MAX_CHARS);
  };

  // The suggested choices, cleaned: short, no repeats, not what was already asked.
  InboxIQ.cleanOptions = function (raw, note) {
    var asked = InboxIQ.cleanNote(note).toLowerCase();
    var out = [];
    (Array.isArray(raw) ? raw : []).forEach(function (o) {
      if (typeof o !== "string" || out.length >= InboxIQ.REPLY_OPTIONS) return;
      var text = o.replace(/\s+/g, " ").trim().replace(/[."]+$/, "").replace(/^"/, "").slice(0, 60);
      var lower = text.toLowerCase();
      if (!text || lower === asked || out.some(function (x) { return x.toLowerCase() === lower; })) return;
      out.push(text);
    });
    return out;
  };

  // { text, needs_reply, options }. Throws when the model cannot be reached or gives
  // back nothing usable.
  // `previous`, when given, is the draft the person asked to redraft.
  InboxIQ.draftReply = async function (key, email, ownerName, note, previous) {
    var redraft = Boolean(InboxIQ.cleanReply(previous));
    var data = await InboxIQ.ask(key, REPLY_SYSTEM, InboxIQ.replyPrompt(email, ownerName, note, previous),
      redraft ? InboxIQ.REDRAFT_TEMPERATURE : 0);
    var text = InboxIQ.cleanReply(data && data.reply);
    if (!text) throw new Error("Couldn't write a reply for this email. Try again.");
    return { text: text, needs_reply: !(data && data.needs_reply === false),
      options: InboxIQ.cleanOptions(data && data.options, note) };
  };

  // --- reading the email's text from Gmail's full format ----------------------

  // Gmail sends bodies as base64url; the bytes are UTF-8.
  function decode(data) {
    var b64 = String(data || "").replace(/-/g, "+").replace(/_/g, "/");
    while (b64.length % 4) b64 += "=";
    try {
      var bin = atob(b64);
      var bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      return new TextDecoder("utf-8").decode(bytes);
    } catch (err) {
      return "";
    }
  }

  // The first part of the given type, searching nested multiparts in order.
  function findPart(part, type) {
    if (!part) return null;
    if (part.mimeType === type && part.body && part.body.data) return part;
    var parts = part.parts || [];
    for (var i = 0; i < parts.length; i++) {
      var hit = findPart(parts[i], type);
      if (hit) return hit;
    }
    return null;
  }

  var ENTITIES = { nbsp: " ", amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", apos: "'" };

  InboxIQ.htmlToText = function (html) {
    return String(html || "")
      .replace(/<(style|script|head)[\s\S]*?<\/\1>/gi, "")
      .replace(/<blockquote[\s\S]*?<\/blockquote>/gi, "")  // quoted earlier mail
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/(p|div|li|tr|h\d)>/gi, "\n")
      .replace(/<[^>]+>/g, "")
      .replace(/&(nbsp|amp|lt|gt|quot|#39|apos);/g, function (_, name) { return ENTITIES[name]; })
      .replace(/[ \t]+/g, " ");
  };

  // Only what this email adds: earlier mail quoted under "On ... wrote:",
  // "-----Original Message-----" or ">" lines is the thread, not the question.
  InboxIQ.stripQuoted = function (text) {
    var lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    var kept = [];
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (/^-{2,}\s*original message\s*-{2,}$/i.test(line)) break;
      if (/^on\b.*\bwrote:$/i.test(line)) break;
      // Gmail wraps a long "On ... wrote:" over two lines.
      if (/^on\b/i.test(line) && i + 1 < lines.length && /\bwrote:$/i.test(lines[i + 1].trim())) break;
      if (/^>/.test(line)) continue;
      kept.push(lines[i].trimEnd());
    }
    return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  };

  InboxIQ.emailText = function (payload) {
    var plain = findPart(payload, "text/plain");
    if (plain) return InboxIQ.stripQuoted(decode(plain.body.data));
    var html = findPart(payload, "text/html");
    if (html) return InboxIQ.stripQuoted(InboxIQ.htmlToText(decode(html.body.data)));
    return "";
  };
})(self.InboxIQ || (self.InboxIQ = {}));
