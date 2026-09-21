import { EmailCard } from "./EmailCard.jsx";

// Middle pane: the messages in the chosen mailbox. Up/Down move the selection.
export function EmailList({ emails, title, loading, empty, selectedId, onSelect }) {
  function onKeyDown(e) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const i = emails.findIndex((m) => m.id === selectedId);
    const next = emails[e.key === "ArrowDown" ? Math.min(i + 1, emails.length - 1) : Math.max(i - 1, 0)];
    if (!next) return;
    onSelect(next.id);
    e.currentTarget.querySelector(`[data-id="${next.id}"]`)?.focus();
  }

  return (
    <section className="pane list-pane" aria-label={title}>
      {emails.length === 0 ? (
        <div className="empty">
          {loading && <span className="spinner" aria-hidden="true" />}
          <p>{loading ? "Loading your mail…" : empty}</p>
        </div>
      ) : (
        <div className="messages" role="listbox" aria-label={title} onKeyDown={onKeyDown}>
          {emails.map((email) => (
            <EmailCard key={email.id} email={email} selected={email.id === selectedId}
              onSelect={onSelect} />
          ))}
        </div>
      )}
    </section>
  );
}
