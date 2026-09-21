import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client.js";

// The OAuth callback bounces the browser back as /?signed_in=1
// `uid` comes from whoever is signed in right now, never from an old session,
// so signing in with another Google account switches every panel with it.
export function useAuth() {
  const [authorized, setAuthorized] = useState(null); // null = still checking
  const [email, setEmail] = useState(null);
  const [uid, setUid] = useState("");
  const [error, setError] = useState(null);

  const check = useCallback(async () => {
    try {
      const s = await api("/api/auth/status");
      setAuthorized(s.authorized);
      setEmail(s.email);
      setUid(s.uid || "");
      return s.authorized;
    } catch (e) {
      setError(e.message);
      setAuthorized(false);
      setEmail(null);
      setUid("");
      return false;
    }
  }, []);

  useEffect(() => {
    // left over from the old version, which pinned the dashboard to one account
    localStorage.removeItem("uid");
    if (new URLSearchParams(location.search).get("signed_in")) {
      history.replaceState({}, "", "/");
    }
    check();
  }, [check]);

  // Drop the current token, then go straight to Google's account chooser.
  const switchAccount = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => null);
    location.href = "/api/auth/login";
  }, []);

  const signOut = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => null);
    await check();
  }, [check]);

  return { authorized, email, uid, error, recheck: check, switchAccount, signOut };
}
