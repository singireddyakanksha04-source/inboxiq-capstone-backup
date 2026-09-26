import { useState } from "react";

import { toneFor } from "../../lib/tones.js";
import { useCleanup } from "./useCleanup.js";

const CYCLE = { monthly: "Monthly", yearly: "Yearly", trial: "Free trial" };

// Inset grouped list: the monthly total heads the group, one row per service.
export function SubscriptionsPanel({ uid, subs, monthlyCost, busy, onDetect }) {
  const [cleanupOpen, setCleanupOpen] = useState(false);

  return (
    <section className="group" aria-label="Subscriptions">
      <header className="group-head">
        <h3>Subscriptions</h3>
        <span className="group-actions">
          <button className="link-btn" onClick={() => setCleanupOpen((o) => !o)}
            aria-expanded={cleanupOpen}>
            {cleanupOpen ? "Hide cleanup" : "Cleanup"}
          </button>
          <button className="link-btn" onClick={onDetect} disabled={busy}>
            {busy ? "Scanning…" : "Rescan"}
          </button>
        </span>
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
                  <span className="cell-title">
                    {name}
                    {s.is_stale && <span className="pill pill-stale">Stale</span>}
                  </span>
                  <span className="cell-sub">
                    {CYCLE[s.sub_cycle] || "Cycle unknown"}
                    {s.sub_renewal_hint && ` · ${s.sub_renewal_hint}`}
                    {s.is_stale && s.stale_reason && ` · ${s.stale_reason}`}
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

      {cleanupOpen && <CleanupList uid={uid} />}
    </section>
  );
}

// Senders worth unsubscribing from. The link only opens in a new tab;
// nothing is ever unsubscribed on the user's behalf.
function CleanupList({ uid }) {
  const { items, loading, error } = useCleanup(uid);

  let body;
  if (loading) body = <div className="cell cell-empty">Looking for senders to clean up…</div>;
  else if (error) body = <div className="cell cell-empty">Couldn't load suggestions.</div>;
  else if (items.length === 0) body = <div className="cell cell-empty">Nothing to clean up.</div>;
  else {
    body = items.map((s) => (
      <div key={`${s.category}-${s.sender_domain}-${s.service}`} className="cell">
        <span className={`app-tile tone-${toneFor(s.service)}`} aria-hidden="true">
          {s.service.charAt(0).toUpperCase()}
        </span>
        <span className="cell-text">
          <span className="cell-title">{s.service}</span>
          <span className="cell-sub">{s.reason}</span>
        </span>
        {s.unsubscribe_url && (
          <a className="link-btn" href={s.unsubscribe_url} target="_blank"
            rel="noopener noreferrer">
            Unsubscribe
          </a>
        )}
      </div>
    ));
  }

  return (
    <div className="cleanup">
      <p className="cleanup-note">Suggestions only. Links open the sender's own page.</p>
      <div className="cells">{body}</div>
    </div>
  );
}
