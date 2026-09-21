// One place for how each category looks and reads, shared by the sidebar,
// summary widgets, message rows and reader. `tone` maps to a system colour
// token in styles.css; `icon` is a name from lib/icons.jsx.
export const CATEGORY_META = {
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

export function categoryMeta(category) {
  return (
    CATEGORY_META[category || "uncategorized"] || {
      label: category,
      tone: "gray",
      icon: "other",
    }
  );
}

// [category, count] pairs, urgent first, then largest first.
export function orderedCounts(counts) {
  return Object.entries(counts).sort((a, b) => {
    const ua = categoryMeta(a[0]).urgent ? 1 : 0;
    const ub = categoryMeta(b[0]).urgent ? 1 : 0;
    return ub - ua || b[1] - a[1];
  });
}

// What a person would actually do next with this category.
export const CATEGORY_ACTIONS = {
  bill: "Review & pay",
  otp: "One-time code, safe to ignore once used",
  security: "Check your account",
  alert: "Update your search, or unsubscribe",
  subscription: "Track this renewal",
  shipping: "Track package",
  receipt: "Keep for records",
  promotion: "Skim or unsubscribe",
};
