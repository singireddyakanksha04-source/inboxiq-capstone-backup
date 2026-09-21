import { Icon } from "../../lib/icons.jsx";

const FEATURES = [
  { icon: "sparkle", tone: "blue", title: "Sorted for you",
    text: "Bills, receipts, shipping, promotions and more, each in its own mailbox." },
  { icon: "attention", tone: "red", title: "What needs attention",
    text: "Bills and security alerts rise to the top so nothing important slips by." },
  { icon: "subscription", tone: "purple", title: "Subscriptions, tallied",
    text: "See every service you pay for and roughly what it costs each month." },
];

// Full-page welcome shown before sign-in. A full navigation, not fetch:
// Google's consent page has to own the tab.
export function ConnectGmail() {
  return (
    <main className="welcome">
      <div className="welcome-inner">
        <div className="app-icon" aria-hidden="true"><Icon name="envelope" size={38} strokeWidth={1.6} /></div>
        <h1>Welcome to InboxIQ</h1>

        <ul className="features">
          {FEATURES.map((f) => (
            <li key={f.title}>
              <span className={`tile large tone-${f.tone}`}><Icon name={f.icon} size={20} strokeWidth={2} /></span>
              <span>
                <strong>{f.title}</strong>
                <span>{f.text}</span>
              </span>
            </li>
          ))}
        </ul>

        <button className="btn prominent large" onClick={() => { location.href = "/api/auth/login"; }}>
          Sign in with Google
        </button>
        <p className="welcome-note">
          Read-only access. InboxIQ never deletes or sends mail on its own.
        </p>
      </div>
    </main>
  );
}
