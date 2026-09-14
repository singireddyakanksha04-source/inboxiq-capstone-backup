import { useCallback, useState } from "react";

import { api } from "../../api/client.js";

export function useSubscriptions(uid) {
  const [subs, setSubs] = useState([]);
  const [monthlyCost, setMonthlyCost] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const detect = useCallback(async () => {
    if (!uid) return;
    setBusy(true);
    try {
      await api(`/api/classify/subscriptions?uid=${uid}`, { method: "POST" });
      const r = await api(`/api/emails/subscriptions?uid=${uid}`);
      setSubs(r.items);
      setMonthlyCost(r.estimated_monthly_cost);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  }, [uid]);

  return { subs, monthlyCost, busy, error, detect };
}
