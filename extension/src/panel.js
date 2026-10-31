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
        navItem({ label: "All sorted mail", tone: "blue", icon: "inbox" }, total, isOn(state, null),
          function () { handlers.onPick(null); })
      );
    }
    function add(pair) {
      var meta = InboxIQ.categoryMeta(pair[0]);
      list.appendChild(navItem(meta, pair[1], isOn(state, pair[0]), function () { handlers.onPick(pair[0]); }));
      if (isOn(state, pair[0])) list.appendChild(inlineActions(state, handlers, pair[0], meta.label, "", pair[1], null));
      appendSubs(list, pair[0], state, handlers);
    }
    function sum(pairs) { return pairs.reduce(function (n, p) { return n + p[1]; }, 0); }
    if (urgent.length) list.appendChild(groupHeader("attention", "Needs attention", sum(urgent), state, handlers));
    if (!isCollapsed(state, "attention")) urgent.forEach(add);
    if (rest.length) list.appendChild(groupHeader("mailboxes", "Mailboxes", sum(rest), state, handlers));
    if (!isCollapsed(state, "mailboxes")) rest.forEach(add);
    frag.appendChild(list);
    frag.appendChild(customSection(state, handlers));
    return frag;
  }

  // --- collapsible groups ----------------------------------------------------
  //
  // Each group heading opens and closes its mailboxes. A closed group still
  // shows its total, so nothing is hidden without a hint that it is there.

  function isCollapsed(state, key) {
    return Boolean(state.collapsed && state.collapsed[key]);
  }

  function groupHeader(key, label, total, state, handlers) {
    var closed = isCollapsed(state, key);
    var button = el("button", "iq-group iq-group-toggle");
    button.type = "button";
    button.setAttribute("aria-expanded", String(!closed));
    var chevron = InboxIQ.icon("chevron", 12, 2.4);
    chevron.classList.add("iq-chevron");
    button.appendChild(chevron);
    button.appendChild(el("span", "iq-group-label", label));
    if (closed && total > 0) button.appendChild(el("span", "iq-group-total", String(total)));
    button.addEventListener("click", function () { handlers.onToggleGroup(key); });
    return button;
  }

  // When the panel is taller than the space it has, close the big built-in
  // groups (Mailboxes first, then Needs attention) so My categories stays in
  // view. Only until the person opens or closes a group themselves; from then
  // on their choice is kept.
  InboxIQ.fitPanel = function (root, state, rerender) {
    if (state.groupsChosen || state.view !== undefined || !state.connected) return;
    ["mailboxes", "attention"].forEach(function (key) {
      if (root.scrollHeight <= root.clientHeight + 4 || isCollapsed(state, key)) return;
      state.collapsed = Object.assign({}, state.collapsed);
      state.collapsed[key] = true;
      rerender();
    });
  };

  // --- My categories: the person's own mailboxes, filled by the AI ----------

  var CUSTOM_META = { tone: "indigo", icon: "sparkle" };

  function customMeta(category) {
    return Object.assign({ label: category.name }, CUSTOM_META);
  }

  function findCustom(state, view) {
    if (typeof view !== "string" || view.indexOf(InboxIQ.CUSTOM_PREFIX) !== 0) return null;
    var id = view.slice(InboxIQ.CUSTOM_PREFIX.length);
    return (state.custom || []).filter(function (c) { return c.id === id; })[0] || null;
  }

  // Gmail listens for single-key shortcuts on the whole page; typing "c" or
  // "/" in our fields must not open Compose or jump to Gmail's search.
  function keepKeys(node) {
    ["keydown", "keypress", "keyup"].forEach(function (type) {
      node.addEventListener(type, function (e) { e.stopPropagation(); });
    });
    return node;
  }

  function field(label, input) {
    var wrap = el("label", "iq-field");
    wrap.appendChild(el("span", null, label));
    wrap.appendChild(input);
    return wrap;
  }

  function categoryForm(state, handlers) {
    var form = keepKeys(el("form", "iq-form"));
    var drafts = state.drafts;
    var name = el("input");
    name.maxLength = 30;
    name.required = true;
    name.placeholder = "Job hunt";
    name.value = drafts.name || "";
    name.addEventListener("input", function () { drafts.name = name.value; });
    var about = el("textarea");
    about.maxLength = 200;
    about.rows = 3;
    about.required = true;
    about.placeholder = "Emails about my job applications, interviews and recruiters";
    about.value = drafts.description || "";
    about.addEventListener("input", function () { drafts.description = about.value; });
    form.appendChild(field("Name", name));
    form.appendChild(field("Describe it in one sentence", about));
    form.appendChild(el("div", "iq-hint", "AI reads each email's sender, subject and preview to decide."));
    form.appendChild(formActions("Add", handlers));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      handlers.onAddCategory(name.value, about.value);
    });
    setTimeout(function () { if (!name.value) name.focus(); }, 0);
    return form;
  }

  function keyForm(state, handlers) {
    var form = keepKeys(el("form", "iq-form"));
    var key = el("input");
    key.type = "password";
    key.required = true;
    key.autocomplete = "off";
    key.placeholder = "gsk_…";
    form.appendChild(field("Groq API key", key));
    form.appendChild(el("div", "iq-hint",
      "Saved only in this browser. Used to sort mail into your own categories."));
    form.appendChild(formActions("Save key", handlers));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      handlers.onSaveKey(key.value);
    });
    setTimeout(function () { key.focus(); }, 0);
    return form;
  }

  function formActions(label, handlers) {
    var row = el("div", "iq-form-actions");
    var cancel = el("button", "iq-link", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", function () { handlers.onForm(null); });
    var submit = el("button", "iq-connect iq-small", label);
    submit.type = "submit";
    row.appendChild(cancel);
    row.appendChild(submit);
    return row;
  }

  function customSection(state, handlers) {
    var frag = document.createDocumentFragment();
    var custom = state.custom || [];
    var total = custom.reduce(function (n, c) { return n + c.count; }, 0);
    frag.appendChild(groupHeader("mine", "My categories", total, state, handlers));
    if (isCollapsed(state, "mine")) return frag;
    var list = el("nav", "iq-list");
    list.setAttribute("aria-label", "My categories");
    custom.forEach(function (c) {
      var key = InboxIQ.CUSTOM_PREFIX + c.id;
      var item = navItem(customMeta(c), c.count, isOn(state, key), function () { handlers.onPick(key); });
      item.title = c.description;
      list.appendChild(item);
      if (isOn(state, key)) list.appendChild(inlineActions(state, handlers, key, c.name, c.description, c.count, c));
      appendSubs(list, InboxIQ.CUSTOM_PREFIX + c.id, state, handlers);
    });
    frag.appendChild(list);

    if (state.form === "category") {
      frag.appendChild(categoryForm(state, handlers));
    } else if (state.form === "key") {
      frag.appendChild(keyForm(state, handlers));
    } else {
      if (!custom.length) {
        frag.appendChild(el("div", "iq-note",
          "Make your own mailbox: name it, describe it, and AI fills it."));
      }
      if (state.sorting) frag.appendChild(aiBanner(state));
      var tools = el("div", "iq-tools");
      if (custom.length < (state.custom_max || 5)) {
        var add = el("button", "iq-link", "+ New category");
        add.type = "button";
        add.addEventListener("click", function () { handlers.onForm("category"); });
        tools.appendChild(add);
      }
      if (custom.length) {
        var sort = el("button", "iq-link iq-with-icon");
        sort.type = "button";
        sort.appendChild(InboxIQ.icon("sparkle", 12, 2.2));
        sort.appendChild(el("span", null, !state.ai_ready ? "Add AI key" : state.sorting ? "Sorting…" : "Sort with AI"));
        sort.disabled = state.busy;
        sort.addEventListener("click", function () {
          if (state.ai_ready) handlers.onSort();
          else handlers.onForm("key");
        });
        tools.appendChild(sort);
      }
      frag.appendChild(tools);
    }
    if (state.ai_note && !state.sorting) frag.appendChild(aiNote(state.ai_note));
    return frag;
  }

  // --- subcategories -----------------------------------------------------------
  //
  // A split category keeps its own page; its subcategories sit under it in the
  // list (closable like a group) and as chips at the top of its page. A
  // subcategory's page is "sub|<parent>|<id>"; "_other" holds the rest.

  var OTHER = "_other";

  function subView(parent, id) { return "sub|" + parent + "|" + id; }

  function parseSubView(view) {
    if (typeof view !== "string" || view.indexOf("sub|") !== 0) return null;
    var cut = view.lastIndexOf("|");
    return { parent: view.slice(4, cut), id: view.slice(cut + 1) };
  }

  function inParent(m, parent) {
    if (parent.indexOf(InboxIQ.CUSTOM_PREFIX) === 0) {
      return m.custom_category === parent.slice(InboxIQ.CUSTOM_PREFIX.length);
    }
    return m.category === parent;
  }

  function subOf(m, parent) { return (m.subs && m.subs[parent]) || null; }

  function parentLabel(state, parent) {
    var own = findCustom(state, parent);
    return own ? own.name : InboxIQ.categoryMeta(parent).label;
  }

  function subMeta(sub) {
    return sub.id === OTHER
      ? { label: "Other", tone: "gray", icon: "other" }
      : { label: sub.name, tone: "indigo", icon: "sparkle" };
  }

  function subItems(entry) {
    var items = entry.items.slice();
    if (entry.other > 0) items.push({ id: OTHER, name: "Other", count: entry.other });
    return items;
  }

  // In Gmail a picked mailbox stays in the list, highlighted, while its mail
  // shows on the right; its few actions sit in a row under it.
  function isOn(state, key) {
    return Boolean(state.listInGmail) && state.selected !== undefined && state.selected === key;
  }

  function actionLink(label, onClick, extra) {
    var button = el("button", "iq-link" + (extra ? " " + extra : ""), label);
    button.type = "button";
    button.addEventListener("click", onClick);
    return button;
  }

  function inlineActions(state, handlers, key, label, description, count, own) {
    if (state.splitting === key) return aiBanner(state, "AI is splitting this category");
    var row = el("div", "iq-inline");
    if (count >= (state.split_min || 6)) {
      var split = el("button", "iq-link iq-with-icon");
      split.type = "button";
      split.disabled = state.busy;
      split.appendChild(InboxIQ.icon("sparkle", 12, 2.2));
      split.appendChild(el("span", null, state.subs && state.subs[key] ? "Split again" : "Split with AI"));
      split.addEventListener("click", function () { handlers.onSplit(key, label, description); });
      row.appendChild(split);
    }
    if (own) row.appendChild(actionLink("Delete", function () { handlers.onRemoveCategory(own.id); }, "iq-delete"));
    return row.childNodes.length ? row : document.createDocumentFragment();
  }

  function subActions(state, handlers, parent, sub) {
    if (state.form === "rename:" + sub.id) return renameForm(sub, parent, handlers);
    var row = el("div", "iq-inline iq-inline-sub");
    row.appendChild(actionLink("Rename", function () { handlers.onForm("rename:" + sub.id); }));
    row.appendChild(actionLink("Delete", function () { handlers.onRemoveSub(parent, sub.id); }, "iq-delete"));
    return row;
  }

  function appendSubs(list, parent, state, handlers) {
    var entry = state.subs && state.subs[parent];
    if (!entry) return;
    var key = "sub:" + parent;
    var closed = isCollapsed(state, key);
    var toggle = el("button", "iq-subhead");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(!closed));
    var chevron = InboxIQ.icon("chevron", 10, 2.4);
    chevron.classList.add("iq-chevron");
    toggle.appendChild(chevron);
    toggle.appendChild(el("span", null, entry.items.length + " subcategories"));
    toggle.addEventListener("click", function () { handlers.onToggleGroup(key); });
    list.appendChild(toggle);
    if (closed) return;
    subItems(entry).forEach(function (s) {
      var key = subView(parent, s.id);
      var item = navItem(subMeta(s), s.count, isOn(state, key), function () { handlers.onPick(key); });
      item.classList.add("iq-sub");
      if (s.description) item.title = s.description;
      list.appendChild(item);
      if (isOn(state, key) && s.id !== OTHER) list.appendChild(subActions(state, handlers, parent, s));
    });
  }

  // Top of a category page: the split button, the progress while it runs, or
  // the subcategories once it has.
  function splitArea(state, handlers, parent, label, description, count) {
    if (state.splitting === parent) return aiBanner(state, "AI is splitting this category");
    var wrap = el("div", "iq-split");
    var entry = state.subs && state.subs[parent];
    var enough = count >= (state.split_min || 6);
    if (entry) {
      var chips = el("div", "iq-chips");
      subItems(entry).forEach(function (s) {
        var chip = el("button", "iq-chip");
        chip.type = "button";
        chip.appendChild(el("span", null, s.id === OTHER ? "Other" : s.name));
        chip.appendChild(el("span", "iq-chip-count", String(s.count)));
        if (s.description) chip.title = s.description;
        chip.addEventListener("click", function () { handlers.onPick(subView(parent, s.id)); });
        chips.appendChild(chip);
      });
      wrap.appendChild(chips);
    }
    if (enough) {
      var button = el("button", entry ? "iq-link iq-with-icon" : "iq-split-btn iq-with-icon");
      button.type = "button";
      button.disabled = state.busy;
      button.appendChild(InboxIQ.icon("sparkle", 12, 2.2));
      button.appendChild(el("span", null, entry ? "Split again" : "Split with AI"));
      button.addEventListener("click", function () { handlers.onSplit(parent, label, description); });
      wrap.appendChild(button);
      if (!entry) wrap.appendChild(el("div", "iq-hint", "AI suggests 2 to 4 smaller groups for these emails."));
    }
    return wrap.childNodes.length ? wrap : document.createDocumentFragment();
  }

  function subPage(state, handlers, where) {
    var frag = document.createDocumentFragment();
    var entry = state.subs && state.subs[where.parent];
    var sub = entry && subItems(entry).filter(function (s) { return s.id === where.id; })[0];
    var plabel = parentLabel(state, where.parent);

    var back = el("button", "iq-back");
    back.type = "button";
    back.appendChild(InboxIQ.icon("back", 14, 2));
    back.appendChild(el("span", null, plabel));
    back.addEventListener("click", function () { handlers.onPick(where.parent); });
    frag.appendChild(back);
    if (!sub) {
      frag.appendChild(el("div", "iq-note", "This subcategory no longer exists."));
      return frag;
    }

    var rows = InboxIQ.viewRows(state);

    var head = el("div", "iq-cat-head");
    var title = el("div", "iq-cat-title");
    title.appendChild(tile(subMeta(sub)));
    title.appendChild(paint(el("span", "iq-cat-name", sub.name), ink()));
    title.appendChild(el("span", "iq-cat-count", rows.length + (rows.length === 1 ? " message" : " messages")));
    if (sub.id !== OTHER) {
      var rename = iconButton("pencil", "Rename " + sub.name, function () {
        handlers.onForm("rename:" + sub.id);
      });
      rename.classList.add("iq-cat-edit");
      title.appendChild(rename);
      title.appendChild(iconButton("trash", "Delete " + sub.name, function () {
        handlers.onRemoveSub(where.parent, sub.id);
      }));
    }
    head.appendChild(title);
    var about = el("div", "iq-cat-about");
    about.appendChild(el("span", "iq-cat-about-label", "In " + plabel));
    about.appendChild(el("span", null, sub.id === OTHER
      ? "Emails that don't fit any of the subcategories."
      : sub.description));
    head.appendChild(about);
    frag.appendChild(head);

    if (state.form === "rename:" + sub.id) frag.appendChild(renameForm(sub, where.parent, handlers));

    if (!rows.length) {
      frag.appendChild(el("div", "iq-note", "No messages here right now."));
      return frag;
    }
    frag.appendChild(rowsOrNote(state, rows, handlers, function (m) {
      var s = subOf(m, where.parent);
      return s && s.reason;
    }));
    return frag;
  }

  function iconButton(icon, label, onClick) {
    var button = el("button", "iq-cat-delete");
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.appendChild(InboxIQ.icon(icon, 14, 2));
    button.addEventListener("click", onClick);
    return button;
  }

  function renameForm(sub, parent, handlers) {
    var form = keepKeys(el("form", "iq-form"));
    var name = el("input");
    name.maxLength = 30;
    name.required = true;
    name.value = sub.name;
    form.appendChild(field("New name", name));
    form.appendChild(formActions("Save", handlers));
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      handlers.onRenameSub(parent, sub.id, name.value);
    });
    setTimeout(function () { name.focus(); name.select(); }, 0);
    return form;
  }

  function messageRows(rows, handlers, reasonOf) {
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
      var reason = reasonOf && reasonOf(m);
      if (reason) button.appendChild(reasonChip(reason));
      button.addEventListener("click", function () { handlers.onOpen(m); });
      list.appendChild(button);
    });
    return list;
  }

  // The messages a view lists: a subcategory, one of the person's own
  // categories, a built-in one, or (null) all sorted mail.
  InboxIQ.viewRows = function (state, key) {
    var view = arguments.length > 1 ? key : state.view;
    if (view === undefined) return [];
    var where = parseSubView(view);
    var own = findCustom(state, view);
    if (!where && !own && typeof view === "string" && view.indexOf(InboxIQ.CUSTOM_PREFIX) === 0) return [];
    return (state.messages || []).filter(function (m) {
      if (where) {
        if (!inParent(m, where.parent)) return false;
        var s = subOf(m, where.parent);
        return where.id === OTHER ? !s : Boolean(s && s.id === where.id);
      }
      if (own) return m.custom_category === own.id;
      return !view || m.category === view;
    });
  };

  // In Gmail the list itself shows on the right, in Gmail's own mail list (see
  // content.js); the panel only says so. The popup has no Gmail beside it, so
  // it lists the messages itself.
  function rowsOrNote(state, rows, handlers, reasonOf) {
    if (!state.listInGmail) return messageRows(rows, handlers, reasonOf);
    var shown = InboxIQ.gmailIds(rows).length;
    var text = shown === rows.length
      ? "Showing " + rows.length + (rows.length === 1 ? " email" : " emails") + " in Gmail on the right."
      : shown
        ? "Showing the newest " + shown + " of " + rows.length + " emails in Gmail on the right."
        : "Sort the inbox again to show these emails in Gmail.";
    var note = el("div", "iq-ai-note");
    note.appendChild(InboxIQ.icon("inbox", 11, 2.2));
    note.appendChild(el("span", null, text));
    return note;
  }

  // Gmail search finds one exact email by its Message-ID; {a b} means a OR b.
  // Kept to the newest 50 so the search stays a reasonable length.
  InboxIQ.GMAIL_LIST_MAX = 50;
  InboxIQ.gmailIds = function (rows) {
    return rows.map(function (m) { return m.rfc822_id; })
      .filter(function (id) { return id && /^[^\s"{}()]+$/.test(id); })
      .slice(0, InboxIQ.GMAIL_LIST_MAX);
  };
  InboxIQ.gmailQuery = function (rows) {
    var ids = InboxIQ.gmailIds(rows);
    if (!ids.length) return null;
    return "{" + ids.map(function (id) { return "rfc822msgid:" + id; }).join(" ") + "}";
  };

  function messageView(state, handlers) {
    var where = parseSubView(state.view);
    if (where) return subPage(state, handlers, where);
    var frag = document.createDocumentFragment();
    var category = state.view;
    var own = findCustom(state, category);
    var meta = own ? customMeta(own)
      : category ? InboxIQ.categoryMeta(category) : { label: "All sorted mail" };

    var back = el("button", "iq-back");
    back.type = "button";
    back.appendChild(InboxIQ.icon("back", 14, 2));
    back.appendChild(el("span", null, own ? "Back" : meta.label));
    back.addEventListener("click", function () { handlers.onPick(undefined); });
    frag.appendChild(back);

    var rows = InboxIQ.viewRows(state);

    if (own) {
      frag.appendChild(customHeader(own, rows.length, handlers));
      if (state.sorting) frag.appendChild(aiBanner(state));
      if (!rows.length && state.sorting) {
        frag.appendChild(skeleton());
        return frag;
      }
    } else {
      var action = category && InboxIQ.CATEGORY_ACTIONS[category];
      if (action) frag.appendChild(el("div", "iq-action", action));
    }
    if (category) {
      frag.appendChild(splitArea(state, handlers, own ? InboxIQ.CUSTOM_PREFIX + own.id : category,
        meta.label, own ? own.description : "", rows.length));
    }

    if (!rows.length) {
      frag.appendChild(el("div", "iq-note", own
        ? "Nothing here yet. Use Sort with AI to fill it."
        : "Nothing in this mailbox yet."));
      if (own) frag.appendChild(deleteButton(own, handlers));
      return frag;
    }
    frag.appendChild(rowsOrNote(state, rows, handlers, own ? function (m) { return m.custom_reason; } : null));
    if (own) frag.appendChild(deleteButton(own, handlers));
    return frag;
  }

  // Name, count and the person's own description, at the top of a category.
  function customHeader(category, count, handlers) {
    var wrap = el("div", "iq-cat-head");
    var title = el("div", "iq-cat-title");
    title.appendChild(tile(customMeta(category)));
    title.appendChild(paint(el("span", "iq-cat-name", category.name), ink()));
    title.appendChild(el("span", "iq-cat-count", count + (count === 1 ? " message" : " messages")));
    var remove = el("button", "iq-cat-delete");
    remove.type = "button";
    remove.title = "Delete this category";
    remove.setAttribute("aria-label", "Delete " + category.name);
    remove.appendChild(InboxIQ.icon("trash", 14, 2));
    remove.addEventListener("click", function () { handlers.onRemoveCategory(category.id); });
    title.appendChild(remove);
    wrap.appendChild(title);
    var about = el("div", "iq-cat-about");
    about.appendChild(el("span", "iq-cat-about-label", "Your description"));
    about.appendChild(el("span", null, category.description));
    wrap.appendChild(about);
    return wrap;
  }

  function reasonChip(reason) {
    var chip = el("div", "iq-reason");
    chip.appendChild(InboxIQ.icon("sparkle", 10, 2.4));
    chip.appendChild(el("span", null, reason));
    return chip;
  }

  // Shown while the model works: a spinner, and a bar once the worker has
  // reported how many messages it is checking.
  function aiBanner(state, text) {
    var p = state.ai_progress;
    var banner = el("div", "iq-ai-banner");
    banner.setAttribute("role", "status");
    var top = el("div", "iq-ai-top");
    top.appendChild(el("span", "iq-spinner"));
    top.appendChild(el("span", "iq-ai-text", text || "AI is sorting your mail"));
    if (p && p.total) top.appendChild(el("span", "iq-ai-count", p.done + "/" + p.total));
    banner.appendChild(top);
    var bar = el("div", p && p.total ? "iq-progress" : "iq-progress iq-progress-busy");
    var fill = el("span");
    if (p && p.total) fill.style.width = Math.round((p.done / p.total) * 100) + "%";
    bar.appendChild(fill);
    banner.appendChild(bar);
    return banner;
  }

  function aiNote(text) {
    var note = el("div", "iq-ai-note");
    note.appendChild(InboxIQ.icon("sparkle", 11, 2.4));
    note.appendChild(el("span", null, text));
    return note;
  }

  function skeleton() {
    var list = el("div", "iq-list");
    list.setAttribute("aria-hidden", "true");
    for (var i = 0; i < 3; i++) {
      var row = el("div", "iq-skel-row");
      row.appendChild(el("span", "iq-skel iq-skel-a"));
      row.appendChild(el("span", "iq-skel iq-skel-b"));
      row.appendChild(el("span", "iq-skel iq-skel-c"));
      list.appendChild(row);
    }
    return list;
  }

  function deleteButton(category, handlers) {
    var button = el("button", "iq-link iq-delete", "Delete this category");
    button.type = "button";
    // One click deletes. Messages only lose this extra category; they stay
    // in their normal mailboxes, so nothing is lost. (No confirm dialog:
    // Chrome does not show those reliably from extension pages.)
    button.addEventListener("click", function () { handlers.onRemoveCategory(category.id); });
    return button;
  }

  // Shared by the Gmail panel and the toolbar popup: the custom-category part
  // of the view state, and the clicks that change it.
  InboxIQ.applyCustom = function (state, reply) {
    state.custom = reply.custom || [];
    state.custom_max = reply.custom_max || 5;
    state.ai_ready = Boolean(reply.ai_ready);
    if (reply.ai_error !== undefined) {
      var matched = state.custom.reduce(function (n, c) { return n + c.count; }, 0);
      state.ai_note = reply.ai_error || ("AI put " + matched + " messages in your categories.");
    }
    state.subs = reply.subs || {};
    state.split_min = reply.split_min || 6;
    if (state.view && String(state.view).indexOf(InboxIQ.CUSTOM_PREFIX) === 0 && !findCustom(state, state.view)) {
      state.view = undefined; // that category was deleted
    }
    var picked = parseSubView(state.selected);
    if (picked && !(state.subs[picked.parent] && subItems(state.subs[picked.parent]).some(function (s) { return s.id === picked.id; }))) {
      state.selected = picked.parent;
    }
    if (typeof state.selected === "string" && state.selected.indexOf(InboxIQ.CUSTOM_PREFIX) === 0 && !findCustom(state, state.selected)) {
      state.selected = undefined;
    }
    var where = parseSubView(state.view);
    if (where && !state.subs[where.parent]) {
      // The split (or its parent) is gone: show the parent, or the list.
      state.view = where.parent.indexOf(InboxIQ.CUSTOM_PREFIX) === 0 && !findCustom(state, where.parent)
        ? undefined : where.parent;
    }
  };

  InboxIQ.customHandlers = function (state, send, render) {
    return {
      onForm: function (which) { state.form = which; state.error = ""; render(); },
      onAddCategory: function (name, description) {
        send({ type: "custom:add", name: name, description: description }, function (reply) {
          state.form = null;
          state.drafts = {};
          // A new category is checked against the scan straight away when a
          // key is already saved; otherwise ask for the key next.
          if (reply.ai_ready) send({ type: "custom:sort" });
          else { state.form = "key"; render(); }
        });
      },
      // The category leaves the view at once; the worker's reply then
      // confirms it (or brings it back with an error if the delete failed).
      onRemoveCategory: function (id) {
        console.log("[InboxIQ] delete category", id);
        state.custom = (state.custom || []).filter(function (c) { return c.id !== id; });
        state.messages = (state.messages || []).map(function (m) {
          return m.custom_category === id ? Object.assign({}, m, { custom_category: null, custom_reason: null }) : m;
        });
        state.view = undefined;
        state.selected = undefined;
        send({ type: "custom:remove", id: id }, function (reply) {
          console.log("[InboxIQ] deleted; categories left:", (reply.custom || []).length);
          render();
        });
      },
      onSaveKey: function (key) {
        send({ type: "ai:key", key: key }, function (reply) {
          state.form = null;
          if (reply.ai_ready && (reply.custom || []).length) send({ type: "custom:sort" });
          else render();
        });
      },
      onSort: function () { send({ type: "custom:sort" }); },
      onSplit: function (parent, label, description) {
        if (!state.ai_ready) {
          // The key form lives on the mailbox list.
          state.view = undefined;
          state.form = "key";
          render();
          return;
        }
        send({ type: "sub:split", parent: parent, label: label, description: description });
      },
      onRenameSub: function (parent, id, name) {
        send({ type: "sub:rename", parent: parent, id: id, name: name }, function () {
          state.form = null;
          render();
        });
      },
      // Like a category: gone from the view at once, the reply confirms it.
      onRemoveSub: function (parent, id) {
        if (state.listInGmail) state.selected = parent;
        else state.view = parent;
        state.form = null;
        send({ type: "sub:remove", parent: parent, id: id });
      },
      onToggleGroup: function (key) {
        state.collapsed = Object.assign({}, state.collapsed);
        state.collapsed[key] = !state.collapsed[key];
        state.groupsChosen = true;
        try { chrome.storage.local.set({ inboxiq_collapsed: state.collapsed }); } catch (err) {}
        render();
      },
    };
  };

  // The groups the person opened or closed last time, shared by panel and popup.
  InboxIQ.loadGroups = function (state, render) {
    try {
      chrome.storage.local.get("inboxiq_collapsed").then(function (stored) {
        if (!stored || !stored.inboxiq_collapsed) return;
        state.collapsed = stored.inboxiq_collapsed;
        state.groupsChosen = true;
        render();
      }, function () {});
    } catch (err) {
      // No extension storage (a plain page preview): groups start open.
    }
  };

  // Progress of a running AI sort, written by the worker after each batch.
  InboxIQ.watchProgress = function (state, render) {
    try {
      chrome.storage.onChanged.addListener(function (changes, area) {
        if (area !== "local" || !changes.inboxiq_ai_progress) return;
        state.ai_progress = changes.inboxiq_ai_progress.newValue || null;
        if (state.sorting || state.splitting) render();
      });
    } catch (err) {
      // No extension storage (a plain page preview): the bar stays indeterminate.
    }
  };

  // --- reply drafts ------------------------------------------------------------
  //
  // Shown while an email is open in Gmail. The draft stays editable here; it
  // only reaches Gmail's reply box when the person inserts it, and they send it.

  function replyCard(state, handlers) {
    var reply = state.reply;
    var card = el("section", "iq-reply");
    card.setAttribute("aria-label", "Reply draft");
    if (!reply) {
      card.appendChild(noteField(state, handlers));
      var start = el("button", "iq-split-btn iq-with-icon");
      start.type = "button";
      start.appendChild(InboxIQ.icon("sparkle", 12, 2.2));
      start.appendChild(el("span", null, state.ai_ready ? "Draft reply with AI" : "Add AI key to draft replies"));
      start.addEventListener("click", handlers.onDraft);
      card.appendChild(start);
      return card;
    }
    if (reply.loading) {
      card.appendChild(aiBanner({}, "AI is writing a reply"));
      return card;
    }
    if (reply.error) {
      card.appendChild(el("div", "iq-note iq-error", reply.error));
      card.appendChild(noteField(state, handlers));
      card.appendChild(replyActions(handlers, false));
      return card;
    }
    if (!reply.needs_reply) card.appendChild(aiNote("This looks automatic; it may not need a reply."));
    var box = keepKeys(el("textarea", "iq-reply-text"));
    box.rows = 8;
    box.value = reply.text;
    box.setAttribute("aria-label", "Reply to " + (reply.to || "the sender"));
    box.addEventListener("input", function () { handlers.onDraftEdit(box.value); });
    card.appendChild(field(reply.to ? "Reply to " + reply.to : "Reply", box));
    card.appendChild(noteField(state, handlers));
    if ((reply.options || []).length) card.appendChild(optionChips(reply.options, handlers));
    card.appendChild(replyActions(handlers, true));
    if (reply.note) card.appendChild(el("div", "iq-hint", reply.note));
    return card;
  }

  // Optional: what the person wants the reply to say. Kept for Redraft.
  function noteField(state, handlers) {
    var note = keepKeys(el("textarea"));
    note.rows = 2;
    note.maxLength = 300;
    note.placeholder = "Yes, but Friday works better";
    note.value = state.replyNote || "";
    note.addEventListener("input", function () { handlers.onDraftNote(note.value); });
    return field("What to say (optional)", note);
  }

  // The model's suggestions for what else to say; one click redrafts with it.
  function optionChips(options, handlers) {
    var row = el("div", "iq-chips iq-reply-options");
    row.setAttribute("aria-label", "Other things to say");
    options.forEach(function (text) {
      var chip = el("button", "iq-chip", text);
      chip.type = "button";
      chip.addEventListener("click", function () { handlers.onPickOption(text); });
      row.appendChild(chip);
    });
    return row;
  }

  function replyActions(handlers, ready) {
    var row = el("div", "iq-form-actions iq-reply-actions");
    function link(label, onClick) {
      var button = el("button", "iq-link", label);
      button.type = "button";
      button.addEventListener("click", onClick);
      row.appendChild(button);
    }
    link("Close", handlers.onCloseDraft);
    link("Redraft", handlers.onDraft);
    if (ready) {
      link("Copy", handlers.onCopyDraft);
      var insert = el("button", "iq-connect iq-small", "Insert into Gmail");
      insert.type = "button";
      insert.addEventListener("click", handlers.onInsertDraft);
      row.appendChild(insert);
    }
    return row;
  }

  // The panel and the worker are separate pieces of the extension; after an
  // update, an old worker does not know the new requests until reloaded.
  InboxIQ.friendlyError = function (message) {
    return message === "Unknown request."
      ? "InboxIQ was updated. Reload it in chrome://extensions, then refresh Gmail."
      : message;
  };

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
    if (state.openThread) root.appendChild(replyCard(state, handlers));

    if (state.view === undefined) root.appendChild(mailboxView(state, handlers));
    else root.appendChild(messageView(state, handlers));
  };
})(window.InboxIQ);
