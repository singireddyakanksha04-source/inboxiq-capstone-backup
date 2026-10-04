import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client.js";
import { MAILBOX_WINDOW } from "./paging.js";

// Keep a bounded, ordered mailbox window for local pages. Older requests cannot
// replace a newer mailbox/account or a refresh of the same mailbox.
export function useEmails(uid, category) {
  const key = JSON.stringify([uid, category]);
  const current = useRef(key);
  current.current = key;
  const requestId = useRef(0);
  const controller = useRef(null);
  const [state, setState] = useState({ key: null, uid: null, emails: [], profile: null, counts: {}, error: null, loading: false });

  const load = useCallback(async () => {
    controller.current?.abort();
    const id = ++requestId.current;
    if (!uid) return;
    const abort = new AbortController();
    controller.current = abort;
    const options = { signal: abort.signal };
    const valid = () => current.current === key && requestId.current === id && !abort.signal.aborted;
    setState((prev) => ({ key, uid, emails: prev.key === key ? prev.emails : [],
      profile: prev.uid === uid ? prev.profile : null, counts: prev.uid === uid ? prev.counts : {}, error: null, loading: true }));
    try {
      const [profile, stats] = await Promise.all([
        api("/api/ingest/me", options).catch(() => null),
        api(`/api/emails/stats?uid=${encodeURIComponent(uid)}`, options),
      ]);
      const params = new URLSearchParams({ uid, limit: MAILBOX_WINDOW });
      if (category) params.set("category", category);
      const rows = await api(`/api/emails?${params}`, options);
      if (valid()) {
        const seen = new Set();
        const emails = rows.filter((row) => !seen.has(row.id) && seen.add(row.id));
        setState({ key, uid, emails, profile, counts: stats.by_category, error: null, loading: false });
      }
    } catch (error) {
      if (valid()) setState((prev) => ({ ...prev, error: error.message, loading: false }));
    }
  }, [uid, category, key]);

  useEffect(() => {
    load();
    return () => { controller.current?.abort(); requestId.current++; };
  }, [load]);

  const valid = Boolean(uid) && state.key === key;
  const sameAccount = Boolean(uid) && state.uid === uid;
  return { profile: sameAccount ? state.profile : null, counts: sameAccount ? state.counts : {},
    emails: valid ? state.emails : [], error: valid ? state.error : null,
    loading: Boolean(uid) && (!valid || state.loading), reload: load };
}
