import { useState } from "react";

import { EmailCard } from "./EmailCard.jsx";

// Up/Down/Home/End move keyboard focus between the rows inside the element
// that got the key.
function moveFocus(e, selector) {
  const all = [...e.currentTarget.querySelectorAll(selector)];
  const i = all.indexOf(document.activeElement);
  let j;
  if (e.key === "ArrowDown") j = Math.min(i + 1, all.length - 1);
  else if (e.key === "ArrowUp") j = Math.max(i - 1, 0);
  else if (e.key === "Home") j = 0;
  else if (e.key === "End") j = all.length - 1;
  else return;
  e.preventDefault();
  all[j]?.focus();
}

// Middle pane: the messages in the chosen mailbox. The list is one Tab stop;
// Up/Down (and Home/End) move between rows, Enter or click opens one.
export function EmailList({ emails, title, loading, empty, selectedId, onSelect }) {
  const [focusedId, setFocusedId] = useState(null);

  // The row Tab lands on: the last one focused, else the open one, else the first.
  const has = (id) => emails.some((m) => m.id === id);
  const tabId = has(focusedId) ? focusedId : has(selectedId) ? selectedId : emails[0]?.id;

  return (
    <section className="pane list-pane" aria-label={title} aria-busy={loading}>
      {emails.length === 0 ? (
        <div className="empty">
          {loading && <span className="spinner" aria-hidden="true" />}
          <p>{loading ? "Loading your mail…" : empty}</p>
        </div>
      ) : (
        <div className="messages" role="listbox" aria-label={title}
          onKeyDown={(e) => moveFocus(e, ".message")}>
          {emails.map((email) => (
            <EmailCard key={email.id} email={email} selected={email.id === selectedId}
              tabIndex={email.id === tabId ? 0 : -1}
              onFocus={() => setFocusedId(email.id)} onSelect={onSelect} />
          ))}
        </div>
      )}
    </section>
  );
}
