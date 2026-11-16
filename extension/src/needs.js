// Needs reply: the emails in the inbox that are waiting on the person's answer.
//
// Two steps. Rules first: mail the classifier already filed as bills, codes,
// receipts, newsletters and the like, and mail from no-reply addresses, never
// needs a reply and is not sent anywhere. The rest of the newest messages go
// to the Groq model with sender, subject and preview only - the same fields
// custom categories use - and it says whether each one asks the person
// something, with a short reason. A thread whose newest message is the
// person's own is already answered and leaves the list.
(function (InboxIQ) {
  InboxIQ.NEEDS_KEY = "needs";      // mailbox key of the Needs reply list
  InboxIQ.NEEDS_LIMIT = 50;         // newest inbox messages looked at
  InboxIQ.NEEDS_BATCH = 10;         // messages per request
  var PREVIEW_CHARS = 300;
  var REASON_CHARS = 120;

  // Built-in categories that are automatic mail by definition.
  InboxIQ.NEEDS_SKIP = ["bill", "security", "otp", "subscription", "receipt",
    "shipping", "alert", "promotion", "newsletter"];
  var NO_REPLY = /(^|[^a-z])(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|mailer-daemon|bounces?)[^@]*@/i;

  function address(sender) {
    var match = /<([^>]+)>/.exec(String(sender || ""));
    return (match ? match[1] : String(sender || "")).trim().toLowerCase();
  }
  InboxIQ.senderAddress = address;

  // Whether a scanned message is worth asking the model about.
  InboxIQ.needsCandidate = function (m, me) {
    if (!m || InboxIQ.NEEDS_SKIP.indexOf(m.category) !== -1) return false;
    var from = address(m.sender);
    if (!from || NO_REPLY.test(from)) return false;
    return !(me && from === String(me).toLowerCase());
  };

  var SYSTEM =
    "You decide which emails are waiting on the user's answer. For each email you get " +
    "the sender, the subject and a short preview. An email needs a reply when a person " +
    "asks the user a question, asks them to do or confirm something, or invites them and " +
    "expects an answer. Newsletters, receipts, notifications, announcements, marketing " +
    "and mail sent to a list do not need a reply, even when they ask a question. " +
    "Neither do events or sign-ups answered on a website or form instead of by email. " +
    "Prefer false over a weak guess. Give a short reason (under 12 words) that says " +
    "what is asked, like \"Priya asks if Thursday at 3 works\".\n" +
    'Reply with JSON only: {"results": [{"i": <email number>, ' +
    '"needs_reply": <true or false>, "reason": <short string>}]}';
  InboxIQ.NEEDS_SYSTEM = SYSTEM;

  InboxIQ.needsPrompt = function (messages) {
    var lines = ["Emails:"];
    messages.forEach(function (m, i) {
      var preview = String(m.snippet || "").replace(/\s+/g, " ").trim().slice(0, PREVIEW_CHARS);
      lines.push("[" + i + "] From: " + (m.sender || m.from_name || "") +
        "\n    Subject: " + (m.subject || "") + "\n    Preview: " + preview);
    });
    return lines.join("\n");
  };

  // One { needs, reason } per message, in order. Only an explicit true counts;
  // an unreadable answer means nothing needs a reply.
  InboxIQ.needsBatch = async function (key, messages) {
    var data = await InboxIQ.ask(key, SYSTEM, InboxIQ.needsPrompt(messages));
    var out = messages.map(function () { return { needs: false, reason: "" }; });
    var rows = data && Array.isArray(data.results) ? data.results : [];
    rows.forEach(function (row) {
      if (!row || typeof row !== "object") return;
      var i = parseInt(row.i, 10);
      if (!(i >= 0 && i < messages.length) || row.needs_reply !== true) return;
      out[i] = { needs: true, reason: String(row.reason || "").replace(/\s+/g, " ").trim().slice(0, REASON_CHARS) };
    });
    return out;
  };

  // A thread is answered when its newest message is the person's own.
  InboxIQ.threadAnswered = function (senders, me) {
    if (!me || !senders || !senders.length) return false;
    return address(senders[senders.length - 1]) === String(me).toLowerCase();
  };
})(self.InboxIQ || (self.InboxIQ = {}));
