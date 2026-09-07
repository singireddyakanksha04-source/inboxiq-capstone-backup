import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client.js";

// The OAuth callback bounces the browser back as /?signed_in=1
export function useAuth() {
  const [authorized, setAuthorized] = useState(null); // null = still checking
  const [error, setError] = useState(null);

  const check = useCallback(async () => {
    try {
      const { authorized } = await api("/api/auth/status");
      setAuthorized(authorized);
      return authorized;
    } catch (e) {
      setError(e.message);
      setAuthorized(false);
      return false;
    }
  }, []);

  useEffect(() => {
    if (new URLSearchParams(location.search).get("signed_in")) {
      history.replaceState({}, "", "/");
    }
    check();
  }, [check]);

  return { authorized, error, recheck: check };
}
