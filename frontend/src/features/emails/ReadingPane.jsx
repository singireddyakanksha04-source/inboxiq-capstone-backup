import { useEffect, useState } from "react";

import { api } from "../../api/client.js";
import { CATEGORY_ACTIONS, categoryMeta } from "../../lib/categories.js";
import { Icon } from "../../lib/icons.jsx";
import { toneFor } from "../../lib/tones.js";

import { cleanText, dueInfo, senderName } from "./EmailCard.jsx";

function longDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

// Marketing mail leaves empty [] markers where images and buttons were, and
// stacks blank lines between them. Drop both so the text reads as prose.
function readable(text) {
  return cleanText(text)
    .replace(/^[ \t]*(\[\s*\][ \t]*)+$/gm, "")
    .replace(/\[\s*\]/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// Newsletter bodies are full of long tracking URLs; show each as a short
// link named after its site instead of the raw address.
function withShortLinks(text) {
  return text.split(/(https?:\/\/[^\s<>"]+)/g).map((part, i) => {
    if (i % 2 === 0) return part;
    let host = "link";
    try { host = new URL(part).hostname.replace(/^www\./, ""); } catch {}
    return (
      <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="reader-link">
        {host} <span aria-hidden="true">↗</span>
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
    );
  });
}

// Detail pane for one message. The list only carries the snippet, so the
// full text is fetched when a message is opened.
export function ReadingPane({ uid, email, onClose }) {
  const [body, setBody] = useState(null);

  useEffect(() => {
    let live = true;
    setBody(null);
    api(`/api/emails/${encodeURIComponent(email.id)}?uid=${uid}`)
      .then((doc) => live && setBody(readable(doc.body_text) || readable(doc.snippet)))
      .catch(() => live && setBody(readable(email.snippet)));
    return () => { live = false; };
  }, [uid, email.id, email.snippet]);

  const m = categoryMeta(email.category);
  const action = CATEGORY_ACTIONS[email.category];
  const name = senderName(email);
  const due = dueInfo(email);

  return (
    <article className="reader">
      <header className="pane-head reader-bar">
        <button className="tool-btn" onClick={onClose} aria-label="Close message">
          <Icon name="back" size={16} className="only-narrow" />
          <Icon name="close" size={15} className="only-wide" />
          <span className="only-narrow">Back</span>
        </button>
      </header>

      <div className="reader-body">
        <h1 className="reader-subject">{email.subject || "(no subject)"}</h1>

        <div className="reader-from">
          <div className={`avatar tone-${toneFor(email.sender_domain || name)}`} aria-hidden="true">
            {name.charAt(0).toUpperCase()}
          </div>
          <div className="reader-from-text">
            <span className="reader-sender">{name}</span>
            <span className="reader-address">{email.sender_email || email.sender_domain}</span>
          </div>
          <time className="reader-date" dateTime={email.date || undefined}>{longDate(email.date)}</time>
        </div>

        <div className="reader-insight">
          <span className={`tile tone-${m.tone}`} aria-hidden="true"><Icon name={m.icon} size={15} strokeWidth={2} /></span>
          <div>
            <span className={`reader-insight-title ink-${m.tone}`}>
              {m.label}
              {email.promo_subcategory && ` · ${email.promo_subcategory}`}
            </span>
            <span className="reader-insight-text">{action || "No action needed"}</span>
            {due && (
              <span className={due.soon ? "reader-insight-text reader-due ink-red" : "reader-insight-text reader-due"}>
                {email.due_label} {due.long} · {due.overdue ? `overdue, ${due.relative}` : due.relative}
              </span>
            )}
          </div>
        </div>

        {body === null ? (
          <div className="reader-loading" role="status"><span className="spinner" aria-hidden="true" /> Loading message…</div>
        ) : (
          <div className="reader-text">{withShortLinks(body)}</div>
        )}
      </div>
    </article>
  );
}
