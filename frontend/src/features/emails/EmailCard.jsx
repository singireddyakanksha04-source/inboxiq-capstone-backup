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

// Due date from the classify step ("2026-10-03" + "Payment due"), as the
// words to show and whether it is close enough to flag. Null when none.
// Soon = within 3 days, or a payment already overdue; a deadline that has
// simply passed is not worth flagging.
const DUE_WORD = { "Payment due": "Due", Deadline: "Due" };

export function dueInfo(email) {
  if (!email.due_date) return null;
  const [y, mo, d] = email.due_date.split("-").map(Number);
  const due = new Date(y, mo - 1, d);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((due - today) / 86400000);
  const word = DUE_WORD[email.due_label] || email.due_label || "Due";
  const when = due.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(y !== today.getFullYear() && { year: "numeric" }),
  });
  const relative =
    days === 0 ? "today" : days === 1 ? "tomorrow" : days > 1 ? `in ${days} days`
      : days === -1 ? "yesterday" : `${-days} days ago`;
  const overdue = days < 0 && email.due_label === "Payment due";
  return {
    days,
    word,
    when,
    relative,
    overdue,
    soon: (days >= 0 && days <= 3) || overdue,
    short: days === 0 || days === 1 ? `${word} ${relative}` : `${word} ${when}`,
    long: due.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric", year: "numeric" }),
  };
}

// One row in the message list. Selection is persistent, like Mail.
export function EmailCard({ email, selected, tabIndex, onFocus, onSelect }) {
  const m = categoryMeta(email.category);
  const name = senderName(email);
  const due = dueInfo(email);

  return (
    <button
      className={selected ? "message sel" : "message"}
      onClick={() => onSelect(email.id)}
      aria-selected={selected}
      role="option"
      tabIndex={tabIndex}
      onFocus={onFocus}
      data-id={email.id}
    >
      {m.urgent && (
        <>
          <span className="message-dot" title="Needs attention" aria-hidden="true" />
          <span className="sr-only">Needs attention.</span>
        </>
      )}
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
          {due && (
            <span className={due.soon ? "chip tint-red due-chip" : "chip plain due-chip"}
              title={`${email.due_label} ${due.long} (${due.overdue ? "overdue" : due.relative})`}>
              {due.short}
              {due.overdue && <span className="sr-only">, overdue</span>}
            </span>
          )}
        </span>
      </span>
    </button>
  );
}
