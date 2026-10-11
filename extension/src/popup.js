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

  function send(message) {
    state.busy = true;
    state.error = "";
    render();
    chrome.runtime.sendMessage(message, function (reply) {
      state.busy = false;
      if (chrome.runtime.lastError) state.error = chrome.runtime.lastError.message;
      else if (reply && reply.error) state.error = reply.error;
      else if (reply) apply(reply);
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
    if (!state.connected) state.view = undefined;
  }

  // The popup is our own page, so here the system preference is the right
  // signal - unlike in Gmail, which has a theme of its own.
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  InboxIQ.INK = dark ? "#e8eaed" : "#202124";
  if (dark) root.classList.add("iq-dark");

  function render() {
    InboxIQ.renderPanel(root, state, handlers);
  }

  render();
  chrome.runtime.sendMessage({ type: "status" }, function (reply) {
    if (!chrome.runtime.lastError && reply) apply(reply);
    render();
  });
})(window.InboxIQ);
