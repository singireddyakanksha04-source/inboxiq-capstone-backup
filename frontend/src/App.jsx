import { useState } from "react";

import { ConnectGmail } from "./features/auth/ConnectGmail.jsx";
import { useAuth } from "./features/auth/useAuth.js";
import { EmailList } from "./features/emails/EmailList.jsx";
import { useEmails } from "./features/emails/useEmails.js";
import { CategoryChips } from "./features/stats/CategoryChips.jsx";
import { SubscriptionsPanel } from "./features/subscriptions/SubscriptionsPanel.jsx";
import { useSubscriptions } from "./features/subscriptions/useSubscriptions.js";
import { SyncButton } from "./features/sync/SyncButton.jsx";

// Each feature lives in src/features/<name>/ and is imported only here, so
// removing a feature is: delete the folder, delete its lines in this file.
export default function App() {
  const { authorized, error: authError } = useAuth();
  const [uid, setUid] = useState(() => localStorage.getItem("uid") || "");
  const [category, setCategory] = useState(null);
  const [status, setStatus] = useState("");

  const { profile, counts, emails, error, reload } = useEmails(
    authorized ? uid : "",
    category
  );
  const {
    subs,
    monthlyCost,
    busy: subsBusy,
    detect: detectSubs,
  } = useSubscriptions(authorized ? uid : "");

  function onSynced(newUid) {
    localStorage.setItem("uid", newUid);
    setUid(newUid);
    reload();
  }

  const message =
    authError ||
    error ||
    status ||
    (authorized === null
      ? "Checking sign-in…"
      : !authorized
        ? "Click Connect Gmail to sign in with Google."
        : !uid
          ? "Click Sync inbox to pull mail from Gmail into Firestore."
          : emails.length === 0
            ? "No emails match this filter."
            : "");

  return (
    <>
      <header>
        <h1>InboxIQ</h1>
        <span className="who">
          {profile ? `${profile.email} · ${profile.total} messages in Gmail` : "not connected"}
        </span>
        {authorized === false && <ConnectGmail />}
        <SyncButton disabled={!authorized} onSynced={onSynced} onStatus={setStatus} />
      </header>

      <main>
        {uid && <CategoryChips counts={counts} active={category} onPick={setCategory} />}
        <EmailList emails={emails} />
        {message && <div className="msg">{message}</div>}
        {uid && (
          <SubscriptionsPanel
            subs={subs}
            monthlyCost={monthlyCost}
            busy={subsBusy}
            onDetect={detectSubs}
          />
        )}
      </main>
    </>
  );
}
