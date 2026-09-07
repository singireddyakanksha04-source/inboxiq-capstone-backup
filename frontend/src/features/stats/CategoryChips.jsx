export function CategoryChips({ counts, active, onPick }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const ordered = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  return (
    <div className="stats">
      <Chip label="all" n={total} on={active === null} onClick={() => onPick(null)} />
      {ordered.map(([category, n]) => (
        <Chip
          key={category}
          label={category}
          n={n}
          on={active === category}
          onClick={() => onPick(category)}
        />
      ))}
    </div>
  );
}

function Chip({ label, n, on, onClick }) {
  return (
    <span className={on ? "chip on" : "chip"} onClick={onClick}>
      {label} <b>{n}</b>
    </span>
  );
}
