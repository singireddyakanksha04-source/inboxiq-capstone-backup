import { useState } from "react";

import { api } from "../../api/client.js";
import { Icon } from "../../lib/icons.jsx";

const BILLING_COUNT = 50;

// One click does the whole pipeline a user expects from "sync":
// pull the last 30 days of mail from Gmail (plus that window's receipts and
// bills, so monthly charges show up), categorise it, then look for subscriptions.
export function SyncButton({ disabled, count = 50, onSynced, onStatus }) {
  const [busy, setBusy] = useState(false);

  async function sync() {
    setBusy(true);
    try {
      onStatus("Fetching mail from Gmail…");
      const r = await api(`/api/ingest/sync?count=${count}&billing=${BILLING_COUNT}`, { method: "POST" });
      onStatus(`Sorting ${r.stored} emails into categories…`);
      await api(`/api/classify?uid=${r.uid}&limit=${Math.min(200, Math.max(r.stored, count))}`, { method: "POST" });
      onStatus("Looking for subscriptions…");
      await api(`/api/classify/subscriptions?uid=${r.uid}`, { method: "POST" });
      onStatus(`Synced and sorted ${r.stored} emails.${r.billing_error ? " " + r.billing_error : ""}`);
      onSynced(r.uid);
    } catch (e) {
      onStatus("Sync failed: " + e.message);
    }
    setBusy(false);
  }

  return (
    <button className="btn prominent" onClick={sync} disabled={disabled || busy}>
      <Icon name="sync" size={14} strokeWidth={2.2} className={busy ? "spin" : ""} />
      {busy ? "Syncing…" : "Sync"}
    </button>
  );
}
