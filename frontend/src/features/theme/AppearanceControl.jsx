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
// page to the system setting; the other two pin it.
export function AppearanceControl({ mode, onChange }) {
  return (
    <div className="appearance">
      <span className="menu-caption">Appearance</span>
      <div className="segmented" role="radiogroup" aria-label="Appearance">
        {MODES.map((m) => (
          <button
            key={m.id}
            className={m.id === mode ? "segment on" : "segment"}
            role="radio"
            aria-checked={m.id === mode}
            onClick={() => onChange(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>
    </div>
  );
}
