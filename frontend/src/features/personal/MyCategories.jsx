import { useState } from "react";

import { Icon } from "../../lib/icons.jsx";

export const CUSTOM_PREFIX = "my:";

// "My Categories" in the sidebar: the account's own mailboxes, filled by the
// AI from a one-line description, plus a small form to add one.
export function MyCategories({ items, max, active, onPick, onAdd, onRemove, onSort, busy }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onAdd(name.trim(), description.trim());
      setName("");
      setDescription("");
      setOpen(false);
    } catch (err) {
      setError(err.message);
    }
    setSaving(false);
  }

  async function remove(item) {
    if (!window.confirm(`Delete “${item.name}”? Emails stay in their normal mailboxes.`)) return;
    try {
      await onRemove(item.id);
      if (active === CUSTOM_PREFIX + item.id) onPick(null);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="my-categories">
      <div className="source-group">My Categories</div>
      <nav className="source-list" aria-label="My categories">
        {items.map((item) => {
          const key = CUSTOM_PREFIX + item.id;
          const on = active === key;
          return (
            <div key={item.id} className="my-cat-row">
              <button className={on ? "source-item on" : "source-item"} onClick={() => onPick(key)}
                aria-current={on ? "page" : undefined} title={item.description}>
                <span className="source-icon tone-indigo" aria-hidden="true">
                  <Icon name="sparkle" size={13} strokeWidth={2.2} />
                </span>
                <span className="source-label">{item.name}</span>
                {item.count > 0 && <span className="source-count"><span className="sr-only">, </span>{item.count}</span>}
              </button>
              <button className="my-cat-delete" onClick={() => remove(item)} aria-label={`Delete ${item.name}`}
                title="Delete category">
                <Icon name="close" size={11} strokeWidth={2.2} />
              </button>
            </div>
          );
        })}
      </nav>

      {open ? (
        <form className="my-cat-form" onSubmit={save}>
          <label>Name
            <input value={name} maxLength={30} required placeholder="Job hunt"
              onChange={(e) => setName(e.target.value)} autoFocus />
          </label>
          <label>Describe it in one sentence
            <textarea value={description} maxLength={200} required minLength={5} rows={3}
              placeholder="Emails about my job applications, interviews and recruiters"
              onChange={(e) => setDescription(e.target.value)} />
          </label>
          <p className="my-cat-help">AI reads each email’s sender, subject and preview to decide.</p>
          <div className="my-cat-actions">
            <button type="button" className="link-btn" onClick={() => { setOpen(false); setError(""); }}>Cancel</button>
            <button className="btn prominent" disabled={saving}>{saving ? "Saving…" : "Add"}</button>
          </div>
        </form>
      ) : (
        <div className="my-cat-tools">
          {items.length < max && (
            <button className="link-btn" onClick={() => setOpen(true)}>+ New category</button>
          )}
          {items.length > 0 && (
            <button className="link-btn" onClick={onSort} disabled={busy}>
              {busy ? "Sorting…" : "Sort with AI"}
            </button>
          )}
        </div>
      )}
      {error && <p className="my-cat-error" role="alert">{error}</p>}
    </div>
  );
}
