import { categoryMeta } from "../../lib/categories.js";
import { Icon } from "../../lib/icons.jsx";
import { toneFor } from "../../lib/tones.js";

// "Nike <news@nike.com>" -> "Nike"
export function senderName(email) {
  const raw = email.sender || "";
  const name = raw.replace(/<.*>/, "").replace(/"/g, "").trim();
  return name || email.sender_email || email.sender_domain || "Unknown sender";
}

export function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

// Gmail snippets are padded with invisible preheader characters; drop them.
export function cleanText(text) {
  return (text || "")
    .replace(/[͏­​-‏⁠﻿  ]/g, " ")
    .replace(/[ \t]+/g, " ")
    .trim();
}

// One row in the message list. Selection is persistent, like Mail.
export function EmailCard({ email, selected, onSelect }) {
  const m = categoryMeta(email.category);
  const name = senderName(email);

  return (
    <button
      className={selected ? "message sel" : "message"}
      onClick={() => onSelect(email.id)}
      aria-selected={selected}
      role="option"
      data-id={email.id}
    >
      {m.urgent && <span className="message-dot" title="Needs attention" />}
      <span className={`monogram tone-${toneFor(email.sender_domain || name)}`} aria-hidden="true">
        {name.charAt(0).toUpperCase()}
      </span>
      <span className="message-main">
        <span className="message-top">
          <span className="message-sender">{name}</span>
          <span className="message-date">{shortDate(email.date)}</span>
        </span>
        <span className="message-subject">{email.subject || "(no subject)"}</span>
        <span className="message-snippet">
          {cleanText(email.snippet).replace(/\s+/g, " ").slice(0, 200)}
        </span>
        <span className="message-tags">
          <span className={`chip tint-${m.tone}`}>
            <Icon name={m.icon} size={12} strokeWidth={2.2} />
            {m.label}
          </span>
          {email.promo_subcategory && <span className="chip plain">{email.promo_subcategory}</span>}
        </span>
      </span>
    </button>
  );
}
