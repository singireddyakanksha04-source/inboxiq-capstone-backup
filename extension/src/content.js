// Puts the InboxIQ panel in Gmail's left navigation, under Labels, and keeps
// it there: Gmail rebuilds that column on its own, so we watch for it going
// away and put it back. All Gmail reading and sorting happens in the service
// worker; this file only holds the view state.
(function (InboxIQ) {
  var PANEL_ID = "inboxiq-panel";

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
    view: undefined, // undefined = mailbox list, null = all mail, else category
    listInGmail: true,   // a picked mailbox shows in Gmail's own list on the right
    selected: undefined, // that mailbox (undefined = none, null = all sorted mail)
    scanned: 0,
  };

  var handlers = {
    onConnect: function () { send({ type: "connect" }); },
    onRescan: function () { send({ type: "scan", force: true }); },
    // The list stays; the picked mailbox shows in Gmail on the right. Picking
    // it again lets go of it.
    onPick: function (key) {
      state.selected = state.selected === key ? undefined : key;
      state.form = null;
      render();
    },
    onOpen: function (message) { openThread(message); },
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
      if (chrome.runtime.lastError) {
        state.error = chrome.runtime.lastError.message;
      } else if (reply && reply.error) {
        console.warn("[InboxIQ]", message.type, "failed:", reply.error);
        state.error = InboxIQ.friendlyError(reply.error);
        if (message.type === "custom:remove") {
          // Put the real list back, keeping the error on screen.
          var shown = state.error;
          send({ type: "status" }, function () { state.error = shown; render(); });
        }
        setTimeout(function () { if (panel) panel.scrollTop = 0; }, 0); // errors show at the top
      } else if (reply) {
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

  // Gmail keeps the thread id in the URL fragment; "#all/<id>" opens a thread
  // whatever label it sits under, and leaves the mailbox untouched.
  function openThread(message) {
    if (!message.thread_id) return;
    location.hash = "#all/" + message.thread_id;
  }

  var host = null;  // the element placed in Gmail's page
  var panel = null;  // our own root inside its shadow tree

  // Gmail has its own light/dark setting and ignores the system one, so the
  // panel reads the colour it is actually sitting on. Walk up from the mailbox
  // column until something paints a background, then pick ink to match.
  function luminance(colour) {
    var parts = /rgba?\(([^)]+)\)/.exec(colour);
    if (!parts) return null;
    var bits = parts[1].split(",").map(parseFloat);
    if (bits.length > 3 && bits[3] === 0) return null; // transparent
    return (0.299 * bits[0] + 0.587 * bits[1] + 0.114 * bits[2]) / 255;
  }

  function pageIsDark() {
    for (var node = navRoot() || document.body; node; node = node.parentElement) {
      var light = luminance(getComputedStyle(node).backgroundColor);
      if (light !== null) return light < 0.5;
    }
    return false;
  }

  function applyTheme() {
    if (!panel) return;
    var dark = pageIsDark();
    InboxIQ.INK = dark ? "#e8eaed" : "#202124";
    panel.classList.toggle("iq-dark", dark);
  }

  function render() {
    if (!panel) return;
    applyTheme();
    InboxIQ.renderPanel(panel, state, handlers);
    position(); // the panel just changed height
    InboxIQ.fitPanel(panel, state, function () { InboxIQ.renderPanel(panel, state, handlers); });
    showInGmail();
  }

  // Picking a mailbox in the panel shows its messages in Gmail's own list:
  // a Gmail search for exactly those messages by Message-ID. Leaving it puts
  // Gmail back on the inbox, but only if Gmail is still on that search.
  // Gmail is only moved when the view or the messages behind it change, so an
  // email opened from that list is not pulled away on an ordinary redraw.
  var shownHash = null;
  function showInGmail() {
    if (state.selected === undefined) {
      if (shownHash && location.hash === shownHash) location.hash = "#inbox";
      shownHash = null;
      return;
    }
    var hash = "#inbox"; // all sorted mail is the inbox
    if (state.selected !== null) {
      var query = InboxIQ.gmailQuery(InboxIQ.viewRows(state, state.selected));
      // Without Message-IDs there is nothing exact to search for; leave Gmail
      // where it is rather than show unrelated mail.
      if (!query) return;
      hash = "#search/" + encodeURIComponent(query);
    }
    if (hash === shownHash) return;
    shownHash = hash;
    location.hash = hash;
  }

  // The left column Gmail draws Inbox/Starred/Labels in. Gmail's class names
  // are generated and several parts of the page claim role="navigation" -
  // the Google bar at the top is one of them - so a candidate also has to sit
  // where the mailbox list sits: against the left edge, narrow and tall.
  function isLeftColumn(node) {
    var box = node.getBoundingClientRect();
    return box.left < 80 && box.width >= 120 && box.width <= 400 && box.height > 250;
  }

  function tallest(nodes) {
    var best = null;
    for (var i = 0; i < nodes.length; i++) {
      if (!isLeftColumn(nodes[i])) continue;
      if (!best || nodes[i].getBoundingClientRect().height > best.getBoundingClientRect().height) {
        best = nodes[i];
      }
    }
    return best;
  }

  function navRoot() {
    // The navigation landmark that is actually the mailbox column.
    var landmark = tallest(document.querySelectorAll('[role="navigation"]'));
    if (landmark) return landmark;
    // No landmark fits: climb from the Inbox link instead, still checking
    // that what we land on looks like the column.
    var inbox = document.querySelector('a[href*="#inbox"]');
    for (var node = inbox; node && node !== document.body; node = node.parentElement) {
      if (isLeftColumn(node)) return node;
    }
    return null;
  }

  // Gmail's mailbox column ends in a flexible spacer that eats every spare
  // pixel, so a panel put inside it is pushed to the bottom of the window
  // whatever order we insert it in. Instead the panel sits in the page and is
  // laid over the empty strip under Labels, measured from the column itself.

  // Where Gmail's own list stops. Links alone are not enough - the Labels
  // header and its "+" are not links - and Gmail also parks widgets at the
  // foot of the column, so read the boxes top down and stop at the first
  // real gap: that is the end of the mailbox list.
  var DRAWN = 'a, [role="link"], [role="button"], [role="listitem"], [role="treeitem"], span, img, svg';
  function contentBottom(root, limit) {
    var nodes = root.querySelectorAll(DRAWN);
    var boxes = [];
    for (var i = 0; i < nodes.length; i++) {
      var box = nodes[i].getBoundingClientRect();
      if (box.height > 0 && box.width > 0 && box.bottom <= limit) boxes.push(box);
    }
    boxes.sort(function (a, b) { return a.top - b.top; });
    var bottom = 0;
    for (var j = 0; j < boxes.length; j++) {
      if (bottom && boxes[j].top > bottom + 40) break; // empty strip: list ended
      if (boxes[j].bottom > bottom) bottom = boxes[j].bottom;
    }
    return bottom;
  }

  // Keeps the panel over the gap: same left edge and width as the column,
  // starting under whatever Gmail drew last and stopping at the column's foot.
  function position() {
    if (!host) return;
    var root = navRoot();
    if (!root) {
      host.style.display = "none";
      return;
    }
    var column = root.getBoundingClientRect();
    var content = contentBottom(root, column.bottom);
    var top = (content || column.top) + 12;
    // If Gmail's list runs the full height there is no gap to sit in; keep a
    // usable strip at the foot of the column rather than disappearing.
    var floor = column.bottom - 140;
    if (top > floor) top = Math.max(floor, column.top);
    var height = column.bottom - top;
    host.style.display = "block";
    host.style.left = column.left + "px";
    host.style.width = column.width + "px";
    host.style.top = top + "px";
    host.style.height = height + "px";
    // One line per layout change, so a stuck panel can be read off the console.
    var shape = [column.left, column.top, column.width, column.bottom, content, top].join(",");
    if (shape !== lastShape) {
      lastShape = shape;
      console.log("[InboxIQ] column", column.left, column.top, column.width, column.bottom,
        "content ends", content, "panel top", top, "height", height);
    }
  }

  var lastShape = "";

  // Gmail's own stylesheet reaches every element on the page and wins on
  // specificity even against !important, which left the mailbox names greyed
  // out. The panel therefore lives in a shadow tree: Gmail's CSS cannot cross
  // that boundary, so panel.css is the only thing styling it.
  var attempts = 0;
  function mount() {
    if (!host || !host.isConnected) {
      attempts += 1;
      if (!navRoot()) return; // Gmail still drawing its column
      host = document.createElement("div");
      host.id = PANEL_ID;
      // Gmail's stylesheet cannot reach inside the shadow tree, but it can
      // still style this host element, and an opacity or filter there dims
      // everything within it - which is what greyed the mailbox names out.
      // These are set as !important inline, which no page rule can beat.
      host.style.cssText = "position:fixed;z-index:500;display:none;";
      ["opacity:1", "filter:none", "-webkit-filter:none", "mix-blend-mode:normal",
       "isolation:isolate", "visibility:visible", "transform:none"].forEach(function (rule) {
        var bits = rule.split(":");
        host.style.setProperty(bits[0], bits.slice(1).join(":"), "important");
      });
      var shadow = host.attachShadow({ mode: "open" });
      var sheet = document.createElement("link");
      sheet.rel = "stylesheet";
      // Version-stamped so a reloaded build never paints with a cached sheet.
      sheet.href = chrome.runtime.getURL("src/panel.css") +
        "?v=" + chrome.runtime.getManifest().version;
      shadow.appendChild(sheet);
      panel = document.createElement("div");
      panel.className = "iq-panel iq-anchored";
      shadow.appendChild(panel);
      document.body.appendChild(host);
      console.log("[InboxIQ] panel mounted after " + attempts + " attempt(s), build " +
        chrome.runtime.getManifest().version);
      render();
    }
    position();
  }

  var pending = null;
  function scheduleMount() {
    if (pending) return;
    pending = setTimeout(function () {
      pending = null;
      mount();
    }, 300);
  }

  new MutationObserver(scheduleMount).observe(document.body, {
    childList: true,
    subtree: true,
  });
  scheduleMount();
  // Gmail resizes and collapses its column without touching the page body,
  // so re-measure on a timer as well as on window changes.
  setInterval(mount, 500);
  window.addEventListener("resize", scheduleMount);

  console.log("[InboxIQ] content script running on", location.href);

  InboxIQ.loadGroups(state, render);
  InboxIQ.watchProgress(state, render);

  // Ask for whatever the worker already has; it answers signed-out without
  // prompting, so nothing happens until the person clicks Connect Gmail.
  chrome.runtime.sendMessage({ type: "status" }, function (reply) {
    if (!chrome.runtime.lastError && reply) {
      apply(reply);
      render();
      // A scan saved before Message-IDs were read cannot be shown in Gmail's
      // list; read the inbox again once. Sorting results are kept by message.
      var messages = reply.messages || [];
      if (reply.connected && messages.length && !messages.some(function (m) { return m.rfc822_id; })) {
        send({ type: "scan" });
      }
    }
  });
})(window.InboxIQ);
