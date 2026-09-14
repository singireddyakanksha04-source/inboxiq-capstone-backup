const URGENT = new Set(["bill", "otp", "security"]);

// What a person would actually do next with this category — the point of
// sorting mail is deciding what to act on, not just labeling it.
const ACTIONS = {
  bill: "Review & pay",
  otp: "One-time code — safe to ignore once used",
  security: "Check your account",
  alert: "Update your search, or unsubscribe",
  subscription: "Track this renewal",
  shipping: "Track package",
  receipt: "Keep for records",
  promotion: "Skim or unsubscribe",
};

export function EmailCard({ email }) {
  const when = email.date ? new Date(email.date).toLocaleDateString() : "";
  const urgent = URGENT.has(email.category);
  const action = ACTIONS[email.category];

  return (
    <div className={urgent ? "row urgent" : "row"}>
      <div className="top">
        <span className="subj">{email.subject || "(no subject)"}</span>
        <span className="tag">
          {email.category || "unclassified"}
          {email.promo_subcategory && ` · ${email.promo_subcategory}`}
        </span>
      </div>
      <div className="meta">
        {email.sender_domain} · {when}
        {action && <span className="action"> · {action}</span>}
      </div>
      <div className="snip">{(email.snippet || "").slice(0, 160)}</div>
    </div>
  );
}
