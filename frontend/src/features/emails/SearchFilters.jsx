export function SearchFilters({ filters, onChange, active, onReset }) {
  function change(field, value) { onChange({ ...filters, [field]: value }); }
  return (
    <div className="search-tools">
      <details className="search-filters" open={Boolean(filters.sender || filters.after || filters.before)}>
        <summary>Search filters</summary>
        <div className="search-filter-fields">
          <label>Sender<input type="search" value={filters.sender} maxLength={254}
            placeholder="Name or address" onChange={(e) => change("sender", e.target.value)} /></label>
          <label>From date<input type="date" value={filters.after}
            onChange={(e) => change("after", e.target.value)} /></label>
          <label>To date<input type="date" value={filters.before}
            onChange={(e) => change("before", e.target.value)} /></label>
        </div>
      </details>
      <p className="search-help">Search checks the newest 500 synced messages in this mailbox. Dates include the whole UTC day. Use the mailboxes to filter by category.</p>
      {active && <button type="button" className="tool-btn search-reset" onClick={onReset}>Reset all filters</button>}
    </div>
  );
}
