import { useState } from "react";

import { api } from "../../api/client.js";

export function SyncButton({ disabled, onSynced, onStatus }) {
  const [busy, setBusy] = useState(false);

  async function sync() {
    setBusy(true);
    onStatus("Syncing…");
    try {
      const r = await api("/api/ingest/sync?count=30", { method: "POST" });
      onStatus(`Stored ${r.stored} emails.`);
      onSynced(r.uid);
    } catch (e) {
      onStatus("Sync failed: " + e.message);
    }
    setBusy(false);
  }

  return (
    <button onClick={sync} disabled={disabled || busy}>
      {busy ? "Syncing…" : "Sync inbox"}
    </button>
  );
}
