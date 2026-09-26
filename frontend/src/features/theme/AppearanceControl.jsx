import { useEffect, useState } from "react";

const MODES = [
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
  { id: "auto", label: "Auto" },
];

function saved() {
  try {
    const value = localStorage.getItem("appearance");
    if (MODES.some((m) => m.id === value)) return value;
  } catch {}
  return "auto";
}

// Held by the app, not by the control: the control lives inside a menu that is
// usually closed, and the saved choice has to apply the moment the app loads.
export function useAppearance() {
  const [mode, setMode] = useState(saved);

  useEffect(() => {
    if (mode === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = mode;
    try { localStorage.setItem("appearance", mode); } catch {}
  }, [mode]);

  return [mode, setMode];
}

// Light / Dark / Auto, like the Appearance setting on a Mac. "Auto" leaves the
// page to the system setting; the other two pin it. A radio group: one Tab
// stop, arrow keys pick the next option.
export function AppearanceControl({ mode, onChange }) {
  function onKeyDown(e) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const i = MODES.findIndex((m) => m.id === mode);
    const next = MODES[(i + step + MODES.length) % MODES.length];
    onChange(next.id);
    e.currentTarget.querySelector(`[data-mode="${next.id}"]`)?.focus();
  }

  return (
    <div className="appearance">
      <span className="menu-caption" id="appearance-label">Appearance</span>
      <div className="segmented" role="radiogroup" aria-labelledby="appearance-label"
        onKeyDown={onKeyDown}>
        {MODES.map((m) => (
          <button
            key={m.id}
            className={m.id === mode ? "segment on" : "segment"}
            role="radio"
            aria-checked={m.id === mode}
            tabIndex={m.id === mode ? 0 : -1}
            data-mode={m.id}
            onClick={() => onChange(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>
    </div>
  );
}
