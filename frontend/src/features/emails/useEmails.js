import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client.js";

// Owns everything that depends on a uid: the profile line, the counts, the list.
export function useEmails(uid, category) {
  const [profile, setProfile] = useState(null);
  const [counts, setCounts] = useState({});
  const [emails, setEmails] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // A different account (or none) must never show the previous account's mail.
  useEffect(() => {
    setProfile(null);
    setCounts({});
    setError(null);
  }, [uid]);

  // Switching mailbox clears the rows straight away, so the previous
  // mailbox's mail is never shown under the new mailbox's title.
  useEffect(() => {
    setEmails([]);
    setLoading(true);
  }, [uid, category]);

  const load = useCallback(async () => {
    if (!uid) return;
    setLoading(true);
    try {
      const [me, stats] = await Promise.all([
        api("/api/ingest/me").catch(() => null),
        api(`/api/emails/stats?uid=${uid}`),
      ]);
      if (me) setProfile(me);
      setCounts(stats.by_category);

      const q = category ? `&category=${encodeURIComponent(category)}` : "";
      setEmails(await api(`/api/emails?uid=${uid}&limit=50${q}`));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  }, [uid, category]);

  useEffect(() => {
    load();
  }, [load]);

  return { profile, counts, emails, error, loading, reload: load };
}
