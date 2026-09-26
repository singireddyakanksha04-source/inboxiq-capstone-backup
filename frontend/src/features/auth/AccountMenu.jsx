import { useEffect, useRef, useState } from "react";

// Toolbar account button with a small popover: who is signed in, and a way to
// change it. It mixes a caption, a setting and actions, so it is a small
// dialog rather than a menu. Closes on outside click, on Tab past its end, or
// on Escape, which also puts focus back on the button.
export function AccountMenu({ email, onSwitch, onSignOut, settings }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const buttonRef = useRef(null);
  const panelRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector(`button:not([tabindex="-1"])`)?.focus();
    const onDown = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    // Capture phase, and marked handled, so the app's own Escape (close the
    // open message) does not fire for the same key press.
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  function onBlur(e) {
    if (e.relatedTarget && !ref.current?.contains(e.relatedTarget)) setOpen(false);
  }

  const initial = (email || "?").charAt(0).toUpperCase();

  return (
    <div className="account" ref={ref} onBlur={onBlur}>
      <button className="account-btn" ref={buttonRef} onClick={() => setOpen(!open)}
        aria-haspopup="dialog" aria-expanded={open} aria-controls="account-menu"
        aria-label={`Account: ${email || "signed in"}`} title={email}>
        {initial}
      </button>
      {open && (
        <div className="menu" id="account-menu" role="dialog" aria-label="Account"
          ref={panelRef}>
          <div className="menu-head">
            <span className="avatar small" aria-hidden="true">{initial}</span>
            <span className="menu-head-text">
              <span className="menu-caption">Signed in as</span>
              <span className="menu-email">{email}</span>
            </span>
          </div>
          {settings && (
            <>
              <div className="menu-sep" aria-hidden="true" />
              {settings}
            </>
          )}
          <div className="menu-sep" aria-hidden="true" />
          <button className="menu-item" onClick={onSwitch}>Switch Account…</button>
          <button className="menu-item" onClick={onSignOut}>Sign Out</button>
        </div>
      )}
    </div>
  );
}
