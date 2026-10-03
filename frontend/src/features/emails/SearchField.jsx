import { useEffect, useRef } from "react";

import { Icon } from "../../lib/icons.jsx";

function isTyping(el) {
  return el?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el?.tagName);
}

// Search box in the toolbar. "/" jumps here from anywhere that isn't a text
// field, Escape clears it, Down moves into the results.
export function SearchField({ value, onChange, label }) {
  const input = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      e.preventDefault();
      input.current?.focus();
      input.current?.select();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function onKeyDown(e) {
    if (e.key === "Escape" && value) {
      // Handled here, so the app doesn't also close the open message.
      e.preventDefault();
      onChange("");
    } else if (e.key === "ArrowDown") {
      const row = document.querySelector('.message[tabindex="0"]');
      if (row) {
        e.preventDefault();
        row.focus();
      }
    }
  }

  function clear() {
    onChange("");
    input.current?.focus();
  }

  return (
    <div className="search" role="search">
      <Icon name="search" size={14} className="search-icon" />
      <input ref={input} type="search" className="search-input" value={value}
        placeholder="Search" aria-label={label} autoComplete="off" spellCheck={false}
        onChange={(e) => onChange(e.target.value)} onKeyDown={onKeyDown} />
      {value && (
        <button type="button" className="search-clear" onClick={clear} aria-label="Clear search"
          title="Clear search">
          <Icon name="close" size={12} strokeWidth={2.2} />
        </button>
      )}
    </div>
  );
}
