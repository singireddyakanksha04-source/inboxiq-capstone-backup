// A full navigation, not fetch: Google's consent page has to own the tab.
export function ConnectGmail() {
  return (
    <button onClick={() => { location.href = "/api/auth/login"; }}>
      Connect Gmail
    </button>
  );
}
