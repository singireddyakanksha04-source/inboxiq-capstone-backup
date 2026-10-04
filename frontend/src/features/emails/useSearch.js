import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client.js";
import { PAGE_SIZE } from "./paging.js";

export function useSearch(uid, category, query, filters, revision = 0, promoSubcategory = "") {
  const q = query.trim();
  const sender = filters.sender.trim();
  const subcategory = category === "promotion" ? promoSubcategory : "";
  const active = Boolean(q || sender || filters.after || filters.before || subcategory);
  const key = JSON.stringify([uid, category, q, sender, filters.after, filters.before, revision, subcategory]);
  const [page, setPage] = useState({ key: null, items: [], next_offset: null, total_matches: null, busy: false, error: null });
  const controller = useRef(null);
  const current = useRef(key);
  current.current = key;

  async function request(offset, signal) {
    const params = new URLSearchParams({ uid, q, sender, offset, limit: PAGE_SIZE });
    if (category) params.set("category", category);
    if (subcategory) params.set("subcategory", subcategory);
    if (filters.after) params.set("after", filters.after);
    if (filters.before) params.set("before", filters.before);
    return api(`/api/emails/search/page?${params}`, { signal });
  }

  useEffect(() => {
    controller.current?.abort();
    if (!uid || !active) return;
    const abort = new AbortController();
    controller.current = abort;
    setPage({ key, items: [], next_offset: null, total_matches: null, busy: true, error: null });
    const timer = setTimeout(async () => {
      try {
        const data = await request(0, abort.signal);
        if (current.current === key && !abort.signal.aborted) {
          setPage({ key, ...data, busy: false, error: null });
        }
      } catch (e) {
        if (current.current === key && !abort.signal.aborted) {
          setPage({ key, items: [], next_offset: null, total_matches: null, busy: false, error: e.message });
        }
      }
    }, 250);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [key, active]);

  async function loadMore() {
    if (page.key !== key || page.busy || page.next_offset === null || controller.current?.signal.aborted) return false;
    const signal = controller.current.signal;
    setPage((prev) => ({ ...prev, busy: true, error: null }));
    try {
      const data = await request(page.next_offset, signal);
      if (current.current !== key || signal.aborted) return false;
      setPage((prev) => {
        const known = new Set(prev.items.map((item) => item.id));
        return { ...prev, items: [...prev.items, ...data.items.filter((item) => !known.has(item.id))],
          next_offset: data.next_offset, total_matches: data.total_matches, busy: false, error: null };
      });
      return true;
    } catch (e) {
      if (current.current === key && !signal.aborted) setPage((prev) => ({ ...prev, busy: false, error: e.message }));
      return false;
    }
  }

  const valid = uid && active && page.key === key;
  return { active, results: valid ? page.items : [], searching: active && Boolean(uid) && (!valid || page.busy),
    error: valid ? page.error : null, total: valid ? (page.total_matches ?? null) : null, hasMore: valid && page.next_offset !== null, loadMore };
}
