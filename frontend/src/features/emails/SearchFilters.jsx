import { PROMOTION_TYPES } from "../../lib/categories.js";

export function SearchFilters({ filters, onChange, active, onReset, promotions = false, subcategory = "", onSubcategoryChange }) {
  function change(field, value) { onChange({ ...filters, [field]: value }); }
  return (
    <div className="search-tools">
      {promotions && <label className="promotion-filter">Promotion type
        <select value={subcategory} onChange={(event) => onSubcategoryChange(event.target.value)}>
          <option value="">All promotions</option>
          {PROMOTION_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>}
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
