import { toneFor } from "../../lib/tones.js";

const CYCLE = { monthly: "Monthly", yearly: "Yearly", trial: "Free trial" };

// Inset grouped list: the monthly total heads the group, one row per service.
export function SubscriptionsPanel({ subs, monthlyCost, busy, onDetect }) {
  return (
    <section className="group" aria-label="Subscriptions">
      <header className="group-head">
        <h3>Subscriptions</h3>
        <button className="link-btn" onClick={onDetect} disabled={busy}>
          {busy ? "Scanning…" : "Rescan"}
        </button>
      </header>

      <div className="cells">
        <div className="cell cell-total">
          <span className="cell-title">Estimated monthly</span>
          <span className="cell-amount large">${monthlyCost.toFixed(2)}</span>
        </div>

        {subs.length === 0 ? (
          <div className="cell cell-empty">
            No subscriptions found yet. Sync your inbox, then rescan.
          </div>
        ) : (
          subs.map((s) => {
            const name = s.sub_service || "Unknown service";
            const trial = s.sub_cycle === "trial";
            return (
              <div key={s.id} className="cell">
                <span className={`app-tile tone-${toneFor(name)}`} aria-hidden="true">
                  {name.charAt(0).toUpperCase()}
                </span>
                <span className="cell-text">
                  <span className="cell-title">{name}</span>
                  <span className="cell-sub">
                    {CYCLE[s.sub_cycle] || "Cycle unknown"}
                    {s.sub_renewal_hint && ` · ${s.sub_renewal_hint}`}
                  </span>
                </span>
                {trial
                  ? <span className="pill">Trial</span>
                  : <span className="cell-amount">{s.sub_amount || "—"}</span>}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
