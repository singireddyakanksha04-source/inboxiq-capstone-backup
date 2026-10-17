import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client.js";

// The account's own categories. Results from an older account never land on
// the new one: each request checks the uid it was made for.
export function usePersonal(uid) {
  const [state, setState] = useState({ uid: null, items: [], max: 5 });
  const current = useRef(uid);
  current.current = uid;

  const reload = useCallback(async () => {
    if (!uid) return;
    try {
      const r = await api(`/api/personal/categories?uid=${encodeURIComponent(uid)}`);
      if (current.current === uid) setState({ uid, items: r.items, max: r.max });
    } catch {
      // The sidebar still works without custom categories.
    }
  }, [uid]);

  useEffect(() => { reload(); }, [reload]);

  async function add(name, description) {
    await api(`/api/personal/categories?uid=${encodeURIComponent(uid)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    });
    await reload();
  }

  async function remove(id) {
    await api(`/api/personal/categories/${encodeURIComponent(id)}?uid=${encodeURIComponent(uid)}`, { method: "DELETE" });
    await reload();
  }

  // Ask the AI to sort the newest mail into these categories.
  async function sort() {
    const r = await api(`/api/personal/sort?uid=${encodeURIComponent(uid)}`, { method: "POST" });
    await reload();
    return r;
  }

  const items = state.uid === uid ? state.items : [];
  return { items, max: state.max, add, remove, sort, reload };
}
