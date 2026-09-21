import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client.js";

// One row per service: several receipts from the same service are one subscription.
function uniqueByService(items) {
  const seen = new Map();
  for (const s of items) {
    const key = (s.sub_service || s.id).toLowerCase();
    if (!seen.has(key)) seen.set(key, s);
  }
  return [...seen.values()];
}

export function useSubscriptions(uid) {
  const [subs, setSubs] = useState([]);
  const [monthlyCost, setMonthlyCost] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Whatever was already detected for this account; no re-scan.
  const load = useCallback(async () => {
    setSubs([]);
    setMonthlyCost(0);
    setError(null);
    if (!uid) return;
    try {
      const r = await api(`/api/emails/subscriptions?uid=${uid}`);
      setSubs(uniqueByService(r.items));
      setMonthlyCost(r.estimated_monthly_cost);
    } catch (e) {
      setError(e.message);
    }
  }, [uid]);

  useEffect(() => {
    load();
  }, [load]);

  const detect = useCallback(async () => {
    if (!uid) return;
    setBusy(true);
    try {
      await api(`/api/classify/subscriptions?uid=${uid}`, { method: "POST" });
      const r = await api(`/api/emails/subscriptions?uid=${uid}`);
      setSubs(uniqueByService(r.items));
      setMonthlyCost(r.estimated_monthly_cost);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  }, [uid]);

  return { subs, monthlyCost, busy, error, detect, reload: load };
}
