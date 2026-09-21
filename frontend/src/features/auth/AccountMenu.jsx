import { useEffect, useRef, useState } from "react";

// Toolbar account button with a small menu: who is signed in, and a way to
// change it. Closes on outside click or Escape.
export function AccountMenu({ email, onSwitch, onSignOut, settings }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const initial = (email || "?").charAt(0).toUpperCase();

  return (
    <div className="account" ref={ref}>
      <button className="account-btn" onClick={() => setOpen(!open)}
        aria-haspopup="menu" aria-expanded={open} title={email}>
        {initial}
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-head">
            <span className="avatar small" aria-hidden="true">{initial}</span>
            <span className="menu-head-text">
              <span className="menu-caption">Signed in as</span>
              <span className="menu-email">{email}</span>
            </span>
          </div>
          {settings && (
            <>
              <div className="menu-sep" />
              {settings}
            </>
          )}
          <div className="menu-sep" />
          <button className="menu-item" role="menuitem" onClick={onSwitch}>Switch Account…</button>
          <button className="menu-item" role="menuitem" onClick={onSignOut}>Sign Out</button>
        </div>
      )}
    </div>
  );
}
