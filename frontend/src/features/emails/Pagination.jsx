export function Pagination({ page, totalPages, hasNext, busy, onPrevious, onNext }) {
  return <nav className="message-pagination" aria-label="Message pagination">
    <button className="tool-btn" disabled={busy || page === 0} onClick={onPrevious}>Previous</button>
    <span aria-live="polite">Page {page + 1}{totalPages ? ` of ${totalPages}` : ""}</span>
    <button className="tool-btn" disabled={busy || !hasNext} onClick={onNext}>Next</button>
  </nav>;
}
