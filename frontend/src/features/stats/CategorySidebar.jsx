import { categoryMeta, orderedCounts } from "../../lib/categories.js";
import { Icon } from "../../lib/icons.jsx";

// Mailbox list. Two levels at most: a group title, then its mailboxes.
// Urgent categories get their own group so they are the first thing seen.
export function CategorySidebar({ counts, active, onPick }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const ordered = orderedCounts(counts);
  const urgent = ordered.filter(([c]) => categoryMeta(c).urgent);
  const rest = ordered.filter(([c]) => !categoryMeta(c).urgent);

  const item = ([category, n]) => {
    const m = categoryMeta(category);
    return (
      <NavItem key={category} label={m.label} icon={m.icon} tone={m.tone} n={n}
        urgent={m.urgent} on={active === category} onClick={() => onPick(category)} />
    );
  };

  return (
    <nav className="source-list" aria-label="Mailboxes">
      <NavItem label="All Mail" icon="inbox" tone="blue" n={total}
        on={active === null} onClick={() => onPick(null)} />
      {urgent.length > 0 && <div className="source-group">Needs Attention</div>}
      {urgent.map(item)}
      {rest.length > 0 && <div className="source-group">Mailboxes</div>}
      {rest.map(item)}
    </nav>
  );
}

function NavItem({ label, icon, tone, n, urgent, on, onClick }) {
  return (
    <button className={on ? "source-item on" : "source-item"} onClick={onClick}
      aria-current={on ? "page" : undefined}>
      <span className={`source-icon tone-${tone}`}><Icon name={icon} size={13} strokeWidth={2.2} /></span>
      <span className="source-label">{label}</span>
      {n > 0 && <span className={urgent ? "source-count badge" : "source-count"}>{n}</span>}
    </button>
  );
}
