// The toolbar popup. Same view as the Gmail sidebar panel, so connecting or
// rescanning here shows up there as well - both read the worker's one cache.
(function (InboxIQ) {
  var root = document.getElementById("inboxiq-popup");

  var state = {
    connected: false,
    busy: false,
    status: "",
    error: "",
    counts: {},
    messages: [],
    custom: [],          // the person's own categories, with counts
    custom_max: 5,
    ai_ready: false,     // a Groq key is saved
    ai_note: "",
    form: null,          // "category" | "key" while a form is open
    drafts: {},
    sorting: false,      // an AI sort is running
    splitting: null,     // the category being split into subcategories
    subs: {},            // parent -> { items, other } once split
    ai_progress: null,   // { done, total } while it runs
    collapsed: {},       // group key -> true when closed
    groupsChosen: false, // the person opened/closed a group; stop auto-fitting
    view: undefined,
    scanned: 0,
  };

  var handlers = {
    onConnect: function () { send({ type: "connect" }); },
    onRescan: function () { send({ type: "scan", force: true }); },
    onPick: function (category) { state.view = category; render(); },
    onOpen: function (message) {
      if (!message.thread_id) return;
      // Open the thread in Gmail; the popup closes itself on the way.
      chrome.tabs.create({ url: "https://mail.google.com/mail/u/0/#all/" + message.thread_id });
      window.close();
    },
  };

  var custom = InboxIQ.customHandlers(state, send, render);
  Object.keys(custom).forEach(function (name) { handlers[name] = custom[name]; });

  // `then` runs only on success, after the reply is applied.
  function send(message, then) {
    state.busy = true;
    state.error = "";
    if (message.type === "custom:sort") {
      state.sorting = true;
      state.ai_note = "";
      state.ai_progress = null;
    }
    if (message.type === "sub:split") {
      state.splitting = message.parent;
      state.ai_progress = null;
    }
    render();
    chrome.runtime.sendMessage(message, function (reply) {
      state.busy = false;
      if (message.type === "custom:sort") state.sorting = false;
      if (message.type === "sub:split") state.splitting = null;
      if (chrome.runtime.lastError) state.error = chrome.runtime.lastError.message;
      else if (reply && reply.error) {
        console.warn("[InboxIQ]", message.type, "failed:", reply.error);
        state.error = InboxIQ.friendlyError(reply.error);
        if (message.type === "custom:remove") {
          // Put the real list back, keeping the error on screen.
          var shown = state.error;
          send({ type: "status" }, function () { state.error = shown; render(); });
        }
        setTimeout(function () { root.scrollTop = 0; }, 0); // errors show at the top
      }
      else if (reply) {
        apply(reply);
        if (then) return then(reply);
        // A fresh scan brings new mail: sort it into the person's categories.
        if ((message.type === "scan" || message.type === "connect") &&
            reply.ai_ready && (reply.custom || []).length) return send({ type: "custom:sort" });
      }
      render();
    });
  }

  function apply(reply) {
    state.connected = !!reply.connected;
    state.counts = reply.counts || {};
    state.messages = reply.messages || [];
    state.scanned = reply.scanned || 0;
    state.status = reply.email
      ? reply.email + " · " + state.scanned + " messages sorted"
      : "";
    InboxIQ.applyCustom(state, reply);
    if (!state.connected) state.view = undefined;
  }

  // The popup is our own page, so here the system preference is the right
  // signal - unlike in Gmail, which has a theme of its own.
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  InboxIQ.INK = dark ? "#e8eaed" : "#202124";
  if (dark) root.classList.add("iq-dark");

  function render() {
    InboxIQ.renderPanel(root, state, handlers);
    InboxIQ.fitPanel(root, state, function () { InboxIQ.renderPanel(root, state, handlers); });
  }

  InboxIQ.loadGroups(state, render);
  InboxIQ.watchProgress(state, render);
  render();
  chrome.runtime.sendMessage({ type: "status" }, function (reply) {
    if (!chrome.runtime.lastError && reply) apply(reply);
    render();
  });
})(window.InboxIQ);
