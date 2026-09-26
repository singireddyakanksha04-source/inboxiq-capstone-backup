import { useEffect, useState } from "react";

import { api } from "../../api/client.js";

// Unsubscribe suggestions. Mounted only while the cleanup list is open, so the
// summary does not pay for it and every opening re-fetches.
export function useCleanup(uid) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let stale = false; // account switched or list closed mid-request
    setItems([]);
    setError(null);
    if (!uid) return undefined;
    setLoading(true);
    api(`/api/emails/unsubscribe-suggestions?uid=${uid}`)
      .then((r) => { if (!stale) setItems(r.items); })
      .catch((e) => { if (!stale) setError(e.message); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; setLoading(false); };
  }, [uid]);

  return { items, loading, error };
}
