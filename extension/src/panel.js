// Renders the InboxIQ mailbox list. Pure view: it reads a state object and
// reports clicks back through handlers, so content.js owns all the data.
(function (InboxIQ) {
  // The ink the host decided on. Gmail follows its own theme rather than the
  // system one, so whoever mounts the panel measures the background it sits
  // on and sets this; the system preference is only the last resort.
  InboxIQ.INK = null;
  function ink() {
    if (InboxIQ.INK) return InboxIQ.INK;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "#e8eaed" : "#202124";
  }

  function paint(node, color) {
    node.style.color = color;
    node.style.webkitTextFillColor = color;
    node.style.opacity = "1";
    return node;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function tile(meta) {
    var span = el("span", "iq-tile iq-tone-" + meta.tone);
    span.appendChild(InboxIQ.icon(meta.icon, 13, 2.2));
    return span;
  }

  function navItem(meta, count, on, onClick) {
    var button = el("button", on ? "iq-item on" : "iq-item");
    button.type = "button";
    button.appendChild(tile(meta));
    button.appendChild(paint(el("span", "iq-label", meta.label), ink()));
    if (count > 0) {
      var tone = " iq-tone-" + (meta.tone || "gray");
      var badge = el("span", "iq-count " + (meta.urgent ? "iq-badge" : "iq-pill") + tone);
      badge.appendChild(el("span", "iq-sr", ", "));
      badge.appendChild(document.createTextNode(String(count)));
      button.appendChild(badge);
    }
    button.addEventListener("click", onClick);
    return button;
  }

  // "9 Oct" / "12:42" the way Gmail itself shortens dates.
  function shortDate(ms) {
    if (!ms) return "";
    var d = new Date(ms);
    var today = new Date();
    if (d.toDateString() === today.toDateString()) {
      return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { day: "numeric", month: "short" });
  }

  function head(state, handlers) {
    var wrap = el("div", "iq-head");
    wrap.appendChild(el("span", "iq-title", "INBOXIQ"));
    var refresh = el("button", "iq-ghost");
    refresh.type = "button";
    refresh.title = state.busy ? "Sorting your inbox…" : "Sort the inbox again";
    refresh.setAttribute("aria-label", refresh.title);
    refresh.disabled = state.busy || !state.connected;
    var spinner = InboxIQ.icon("sync", 16, 2);
    if (state.busy) spinner.classList.add("iq-spin");
    refresh.appendChild(spinner);
    refresh.addEventListener("click", handlers.onRescan);
    wrap.appendChild(refresh);
    return wrap;
  }

  function mailboxView(state, handlers) {
    var frag = document.createDocumentFragment();
    var counts = state.counts || {};
    var ordered = InboxIQ.orderedCounts(counts);
    var urgent = ordered.filter(function (p) { return InboxIQ.categoryMeta(p[0]).urgent; });
    var rest = ordered.filter(function (p) { return !InboxIQ.categoryMeta(p[0]).urgent; });
    var total = Object.values(counts).reduce(function (a, b) { return a + b; }, 0);

    var list = el("nav", "iq-list");
    list.setAttribute("aria-label", "InboxIQ mailboxes");
    if (total > 0) {
      list.appendChild(
        navItem({ label: "All sorted mail", tone: "blue", icon: "inbox" }, total, false,
          function () { handlers.onPick(null); })
      );
    }
    function add(pair) {
      var meta = InboxIQ.categoryMeta(pair[0]);
      list.appendChild(navItem(meta, pair[1], false, function () { handlers.onPick(pair[0]); }));
    }
    if (urgent.length) list.appendChild(el("div", "iq-group", "Needs attention"));
    urgent.forEach(add);
    if (rest.length) list.appendChild(el("div", "iq-group", "Mailboxes"));
    rest.forEach(add);
    frag.appendChild(list);
    return frag;
  }

  function messageView(state, handlers) {
    var frag = document.createDocumentFragment();
    var category = state.view;
    var meta = category ? InboxIQ.categoryMeta(category) : { label: "All sorted mail" };

    var back = el("button", "iq-back");
    back.type = "button";
    back.appendChild(InboxIQ.icon("back", 14, 2));
    back.appendChild(el("span", null, meta.label));
    back.addEventListener("click", function () { handlers.onPick(undefined); });
    frag.appendChild(back);

    var action = category && InboxIQ.CATEGORY_ACTIONS[category];
    if (action) frag.appendChild(el("div", "iq-action", action));

    var rows = (state.messages || []).filter(function (m) {
      return !category || m.category === category;
    });
    if (!rows.length) {
      frag.appendChild(el("div", "iq-note", "Nothing in this mailbox yet."));
      return frag;
    }
    var list = el("div", "iq-list");
    rows.forEach(function (m) {
      var button = el("button", "iq-msg");
      button.type = "button";
      var from = el("div", "iq-from");
      from.appendChild(paint(el("span", "iq-from-name", m.from_name || m.from || "Unknown sender"), ink()));
      from.appendChild(el("span", "iq-date", shortDate(m.date)));
      button.appendChild(from);
      button.appendChild(paint(el("div", "iq-subject", m.subject || "(no subject)"), ink()));
      if (m.due_label) button.appendChild(el("div", "iq-due", m.due_label));
      button.addEventListener("click", function () { handlers.onOpen(m); });
      list.appendChild(button);
    });
    frag.appendChild(list);
    return frag;
  }

  // state: { connected, busy, status, error, counts, messages, view, scanned }
  InboxIQ.renderPanel = function (root, state, handlers) {
    root.textContent = "";
    root.appendChild(head(state, handlers));

    if (state.error) root.appendChild(el("div", "iq-note iq-error", state.error));

    if (!state.connected) {
      root.appendChild(el("div", "iq-note",
        "Sort this inbox into bills, codes, security notices and the rest."));
      var connect = el("button", "iq-connect", "Connect Gmail");
      connect.type = "button";
      connect.disabled = state.busy;
      connect.addEventListener("click", handlers.onConnect);
      root.appendChild(connect);
      return;
    }

    if (state.status) root.appendChild(el("div", "iq-note", state.status));

    if (state.view === undefined) root.appendChild(mailboxView(state, handlers));
    else root.appendChild(messageView(state, handlers));
  };
})(window.InboxIQ);
