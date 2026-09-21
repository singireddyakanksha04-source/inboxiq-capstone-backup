import { categoryMeta, orderedCounts } from "../../lib/categories.js";
import { Icon } from "../../lib/icons.jsx";

// Summary shown in the detail pane when no message is open. Every widget
// is a shortcut: clicking it opens the mailbox behind the number.
export function OverviewCards({ counts, subsCount, monthlyCost, onPick }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const ordered = orderedCounts(counts);
  const urgent = ordered.filter(([c]) => categoryMeta(c).urgent);
  const needsAction = urgent.reduce((a, [, n]) => a + n, 0);
  const promos = counts.promotion || 0;
  const promoShare = total ? Math.round((promos / total) * 100) : 0;

  return (
    <>
      <section className="composition" aria-label="Inbox composition">
        <div className="composition-head">
          <span className="widget-label">Inbox</span>
          <span className="composition-total">
            <strong>{total}</strong> emails sorted
          </span>
        </div>
        <div className="composition-bar" role="img"
          aria-label={ordered.map(([c, n]) => `${categoryMeta(c).label} ${n}`).join(", ")}>
          {ordered.map(([c, n]) => (
            <span key={c} className={`seg tone-${categoryMeta(c).tone}`}
              style={{ flexGrow: n }} title={`${categoryMeta(c).label}: ${n}`} />
          ))}
        </div>
        <div className="legend">
          {ordered.map(([c, n]) => (
            <button key={c} className="legend-item" onClick={() => onPick(c)}>
              <span className={`legend-dot tone-${categoryMeta(c).tone}`} />
              {categoryMeta(c).label}
              <span className="legend-n">{n}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="widgets">
        <Widget icon="attention" tone="red" label="Needs Attention"
          value={needsAction} alert={needsAction > 0}
          onClick={() => onPick(urgent[0]?.[0] ?? null)}>
          {urgent.length
            ? urgent.map(([c, n]) => `${n} ${categoryMeta(c).label.toLowerCase()}`).join(" · ")
            : "Nothing urgent"}
        </Widget>

        <Widget icon="promotion" tone="pink" label="Promotions" value={promos}
          onClick={() => onPick("promotion")}>
          <span className="meter" aria-hidden="true">
            <span className="meter-fill tone-pink" style={{ width: `${promoShare}%` }} />
          </span>
          {promoShare}% of your inbox
        </Widget>

        <Widget icon="subscription" tone="purple" label="Subscriptions" value={subsCount}
          onClick={() => onPick("subscription")}>
          about ${monthlyCost.toFixed(2)} a month
        </Widget>
      </div>
    </>
  );
}

function Widget({ icon, tone, label, value, alert, onClick, children }) {
  return (
    <button className="widget" onClick={onClick}>
      <span className="widget-head">
        <span className={`tile tone-${tone}`}><Icon name={icon} size={14} strokeWidth={2.2} /></span>
        <span className="widget-label">{label}</span>
      </span>
      <span className={alert ? "widget-value ink-red" : "widget-value"}>{value}</span>
      <span className="widget-hint">{children}</span>
    </button>
  );
}
