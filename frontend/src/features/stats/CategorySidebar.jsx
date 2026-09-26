import { categoryMeta, orderedCounts } from "../../lib/categories.js";
import { Icon } from "../../lib/icons.jsx";

// Mailbox list. Two levels at most: a group title, then its mailboxes.
// Urgent categories get their own group so they are the first thing seen.
// One Tab stop: arrow keys (Left/Right too, for the phone row) move between
// mailboxes, Enter opens one.
export function CategorySidebar({ counts, active, onPick }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const ordered = orderedCounts(counts);
  const urgent = ordered.filter(([c]) => categoryMeta(c).urgent);
  const rest = ordered.filter(([c]) => !categoryMeta(c).urgent);
  // Tab lands on the open mailbox, or All Mail if that one has gone.
  const tabStop = active !== null && active in counts ? active : null;

  function onKeyDown(e) {
    const all = [...e.currentTarget.querySelectorAll(".source-item")];
    const i = all.indexOf(document.activeElement);
    const j = {
      ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1, ArrowLeft: i - 1,
      Home: 0, End: all.length - 1,
    }[e.key];
    if (j === undefined) return;
    e.preventDefault();
    all[Math.max(0, Math.min(j, all.length - 1))]?.focus();
  }

  const item = ([category, n]) => {
    const m = categoryMeta(category);
    return (
      <NavItem key={category} label={m.label} icon={m.icon} tone={m.tone} n={n}
        urgent={m.urgent} on={active === category} tab={tabStop === category}
        onClick={() => onPick(category)} />
    );
  };

  return (
    <nav className="source-list" aria-label="Mailboxes" onKeyDown={onKeyDown}>
      <NavItem label="All Mail" icon="inbox" tone="blue" n={total}
        on={active === null} tab={tabStop === null} onClick={() => onPick(null)} />
      {urgent.length > 0 && <div className="source-group">Needs Attention</div>}
      {urgent.map(item)}
      {rest.length > 0 && <div className="source-group">Mailboxes</div>}
      {rest.map(item)}
    </nav>
  );
}

function NavItem({ label, icon, tone, n, urgent, on, tab, onClick }) {
  return (
    <button className={on ? "source-item on" : "source-item"} onClick={onClick}
      aria-current={on ? "page" : undefined} tabIndex={tab ? 0 : -1}>
      <span className={`source-icon tone-${tone}`} aria-hidden="true">
        <Icon name={icon} size={13} strokeWidth={2.2} />
      </span>
      <span className="source-label">{label}</span>
      {n > 0 && (
        <span className={urgent ? "source-count badge" : "source-count"}>
          <span className="sr-only">, </span>{n}
        </span>
      )}
    </button>
  );
}
