// Mailbox metadata, kept in step with the web dashboard's lib/categories.js so
// the same message reads the same way in both places. `tone` is a colour token
// in panel.css; `icon` is a path in ICON_PATHS below.
var InboxIQ = window.InboxIQ || {};
window.InboxIQ = InboxIQ;

InboxIQ.CATEGORY_META = {
  bill: { label: "Bills", tone: "red", icon: "bill", urgent: true },
  security: { label: "Security", tone: "red", icon: "security", urgent: true },
  otp: { label: "Codes", tone: "orange", icon: "otp", urgent: true },
  subscription: { label: "Subscriptions", tone: "purple", icon: "subscription" },
  receipt: { label: "Receipts", tone: "green", icon: "receipt" },
  shipping: { label: "Shipping", tone: "blue", icon: "shipping" },
  alert: { label: "Alerts", tone: "yellow", icon: "alert" },
  promotion: { label: "Promotions", tone: "pink", icon: "promotion" },
  newsletter: { label: "Newsletters", tone: "teal", icon: "newsletter" },
  personal: { label: "Personal", tone: "indigo", icon: "personal" },
  other: { label: "Other", tone: "gray", icon: "other" },
  uncategorized: { label: "Uncategorized", tone: "gray", icon: "uncategorized" },
};

InboxIQ.categoryMeta = function (category) {
  return (
    InboxIQ.CATEGORY_META[category || "uncategorized"] || {
      label: category,
      tone: "gray",
      icon: "other",
    }
  );
};

// [category, count] pairs, urgent first, then largest first.
InboxIQ.orderedCounts = function (counts) {
  return Object.entries(counts).sort(function (a, b) {
    var ua = InboxIQ.categoryMeta(a[0]).urgent ? 1 : 0;
    var ub = InboxIQ.categoryMeta(b[0]).urgent ? 1 : 0;
    return ub - ua || b[1] - a[1];
  });
};

// What a person would actually do next with this category.
InboxIQ.CATEGORY_ACTIONS = {
  bill: "Review & pay",
  otp: "One-time code, safe to ignore once used",
  security: "Check your account",
  alert: "Update your search, or unsubscribe",
  subscription: "Track this renewal",
  shipping: "Track package",
  receipt: "Keep for records",
  promotion: "Skim or unsubscribe",
};

// 24px grid, round caps, stroke follows the surrounding text colour.
InboxIQ.ICON_PATHS = {
  inbox: "M3 13h5l1.5 2.5h5L16 13h5M5.2 5h13.6L21 13v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5z",
  bill: "M4.5 5.5h15a1.5 1.5 0 0 1 1.5 1.5v10a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17V7a1.5 1.5 0 0 1 1.5-1.5zM3 10h18M7 14.5h4",
  security: "M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6zM9.5 11.5h5v4h-5zM10.5 11.5V10a1.5 1.5 0 0 1 3 0v1.5",
  otp: "M11.5 14a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0zM10.5 11.5 19 3M16 6l2.5 2.5M13.5 8.5l2 2",
  subscription: "M20 12a8 8 0 1 1-2.34-5.66M20 4v4.5h-4.5",
  receipt: "M6 3h12v18l-2-1.5-2 1.5-2-1.5-2 1.5-2-1.5-2 1.5zM9 8h6M9 12h6M9 16h3",
  shipping: "M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5zM3.5 7.5 12 12l8.5-4.5M12 12v9",
  alert: "M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0",
  promotion: "M3.5 12.5V4.5a1 1 0 0 1 1-1h8l8 8a1.4 1.4 0 0 1 0 2l-7 7a1.4 1.4 0 0 1-2 0zM8 8.5h.01",
  newsletter: "M5.5 5h13a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM7 9h10M7 12.5h10M7 16h6",
  personal: "M16 8a4 4 0 1 1-8 0 4 4 0 0 1 8 0zM4.5 20.5a7.5 7.5 0 0 1 15 0",
  other: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0zM8 12h.01M12 12h.01M16 12h.01",
  uncategorized: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0zM9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.4M12 17h.01",
  sync: "M4 12a8 8 0 0 1 14-5.3M20 4v4h-4M20 12a8 8 0 0 1-14 5.3M4 20v-4h4",
  back: "M15 5l-7 7 7 7",
  chevron: "M6 9l6 6 6-6",
  pencil: "M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17zM14.5 7.5l2 2",
  trash: "M4 7h16M10 11v6M14 11v6M5.5 7l1 12a1.5 1.5 0 0 0 1.5 1.4h8a1.5 1.5 0 0 0 1.5-1.4l1-12M9 7V4.5h6V7",
  sparkle: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18",
};

// The person's own mailboxes are addressed as "my:<id>" so they never clash
// with a built-in category.
InboxIQ.CUSTOM_PREFIX = "my:";

InboxIQ.icon = function (name, size, strokeWidth) {
  var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", size || 16);
  svg.setAttribute("height", size || 16);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", strokeWidth || 1.8);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", InboxIQ.ICON_PATHS[name] || InboxIQ.ICON_PATHS.other);
  svg.appendChild(path);
  return svg;
};
