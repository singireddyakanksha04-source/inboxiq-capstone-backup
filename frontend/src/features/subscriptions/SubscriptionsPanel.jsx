export function SubscriptionsPanel({ subs, monthlyCost, busy, onDetect }) {
  return (
    <section className="subscriptions">
      <div className="subscriptions-head">
        <h2>
          Subscriptions
          {subs.length > 0 && (
            <span className="est-cost"> · ~${monthlyCost.toFixed(2)}/mo</span>
          )}
        </h2>
        <button onClick={onDetect} disabled={busy}>
          {busy ? "Scanning…" : "Detect subscriptions"}
        </button>
      </div>
      {subs.length === 0 ? (
        <p className="msg">No subscriptions detected yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Service</th>
              <th>Cycle</th>
              <th>Renewal</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                <td>{s.sub_service || "—"}</td>
                <td>{s.sub_cycle || "—"}</td>
                <td>{s.sub_renewal_hint || "—"}</td>
                <td className="num">{s.sub_amount || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
