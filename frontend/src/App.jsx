import { Pagination } from "./features/emails/Pagination.jsx";
import { PAGE_SIZE, MAILBOX_WINDOW } from "./features/emails/paging.js";
import { useEffect, useRef, useState } from "react";

import { AccountMenu } from "./features/auth/AccountMenu.jsx";
import { ConnectGmail } from "./features/auth/ConnectGmail.jsx";
import { useAuth } from "./features/auth/useAuth.js";
import { dueInfo } from "./features/emails/EmailCard.jsx";
import { EmailList } from "./features/emails/EmailList.jsx";
import { ReadingPane } from "./features/emails/ReadingPane.jsx";
import { SearchFilters } from "./features/emails/SearchFilters.jsx";
import { SearchField } from "./features/emails/SearchField.jsx";
import { useEmails } from "./features/emails/useEmails.js";
import { useSearch } from "./features/emails/useSearch.js";
import { OverviewCards } from "./features/overview/OverviewCards.jsx";
import { CategorySidebar } from "./features/stats/CategorySidebar.jsx";
import { SubscriptionsPanel } from "./features/subscriptions/SubscriptionsPanel.jsx";
import { useSubscriptions } from "./features/subscriptions/useSubscriptions.js";
import { SyncButton } from "./features/sync/SyncButton.jsx";
import { AppearanceControl, useAppearance } from "./features/theme/AppearanceControl.jsx";
import { categoryMeta } from "./lib/categories.js";
import { Icon } from "./lib/icons.jsx";

// Each feature lives in src/features/<name>/ and is imported only here, so
// removing a feature is: delete the folder, delete its lines in this file.
//
// Layout is a three-pane split view: mailboxes | messages | detail. The
// detail pane shows the summary until a message is opened.
export default function App() {
  const { authorized, email, uid, error: authError, switchAccount, signOut } = useAuth();
  const [appearance, setAppearance] = useAppearance();
  const [category, setCategory] = useState(null);
  const [promoSubcategory, setPromoSubcategory] = useState("");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ sender: "", after: "", before: "" });
  const [searchRevision, setSearchRevision] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [position, setPosition] = useState({ key: null, page: 0 });
  // Narrow windows show one of list/detail at a time.
  const [showDetail, setShowDetail] = useState(false);
  const detailRef = useRef(null);
  const selectedRef = useRef(null);
  selectedRef.current = selectedId;

  // New account: start from a clean slate, not the old account's filter/status.
  useEffect(() => {
    setCategory(null);
    setPromoSubcategory("");
    setStatus("");
    setQuery("");
    setFilters({ sender: "", after: "", before: "" });
    setSelectedId(null);
    setShowDetail(false);
  }, [uid]);

  const { profile, counts, emails, error, loading, reload } = useEmails(
    authorized ? uid : "",
    category
  );
  // A search looks inside the chosen mailbox; "All Mail" searches everything.
  const search = useSearch(authorized ? uid : "", category, query, filters, searchRevision, promoSubcategory);
  const {
    subs,
    monthlyCost,
    busy: subsBusy,
    detect: detectSubs,
    reload: reloadSubs,
  } = useSubscriptions(authorized ? uid : "");

  useEffect(() => {
    // Skipped when a popover already used this Escape to close itself.
    const onKey = (e) => { if (e.key === "Escape" && !e.defaultPrevented) closeMessage(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function onSynced() {
    setSearchRevision((value) => value + 1);
    reload();
    reloadSubs();
  }

  function pickMailbox(c) {
    setCategory(c);
    setPromoSubcategory("");
    setSelectedId(null);
    setShowDetail(false);
  }

  // When the panes swap (narrow windows) or the reader closes, keyboard focus
  // would fall back to the page; move it to what is now on screen.
  function openMessage(id) {
    setSelectedId(id);
    setShowDetail(true);
    requestAnimationFrame(() => {
      const a = document.activeElement;
      if (a === document.body || a?.offsetParent === null) {
        detailRef.current?.querySelector("button")?.focus();
      }
    });
  }

  function closeMessage() {
    const id = selectedRef.current;
    setSelectedId(null);
    setShowDetail(false);
    if (!id) return;
    requestAnimationFrame(() => {
      const a = document.activeElement;
      if (a === document.body || detailRef.current?.contains(a)) {
        document.querySelector(`.message[data-id="${CSS.escape(id)}"]`)?.focus();
      }
    });
  }

  function openSummary() {
    setSelectedId(null);
    setShowDetail(true);
  }

  const pageKey = JSON.stringify([authorized ? uid : "", category, query.trim(), filters.sender.trim(), filters.after, filters.before, searchRevision, promoSubcategory]);
  useEffect(() => { setPosition({ key: pageKey, page: 0 }); }, [pageKey]);
  const pageCount = search.active ? (search.total === null ? null : Math.max(1, Math.ceil(search.total / PAGE_SIZE)))
    : Math.max(1, Math.ceil(emails.length / PAGE_SIZE));
  const page = position.key === pageKey ? Math.min(position.page, (pageCount ?? position.page + 1) - 1) : 0;
  function goToPage(next) {
    setPosition({ key: pageKey, page: next });
    setSelectedId(null);
    setShowDetail(false);
  }
  async function nextPage() {
    const rows = search.active ? search.results : emails;
    if ((page + 1) * PAGE_SIZE < rows.length) goToPage(page + 1);
    else if (search.active && await search.loadMore()) goToPage(page + 1);
  }

  if (authorized === null) {
    return <div className="splash"><span className="spinner" aria-hidden="true" /> Checking sign-in…</div>;
  }
  if (!authorized) {
    return (
      <>
        <ConnectGmail />
        {authError && <div className="toast" role="alert">{authError}</div>}
      </>
    );
  }

  const synced = Object.keys(counts).length > 0;
  const empty = !synced
    ? "Nothing synced for this account yet. Click Sync to pull your latest mail."
    : "No messages in this mailbox.";
  const available = search.active ? search.results : emails;
  const listed = available.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const hasNext = (page + 1) * PAGE_SIZE < available.length || (search.active && search.hasMore);
  const busy = search.active ? search.searching : loading;
  const totalPages = pageCount;
  const range = listed.length ? `${page * PAGE_SIZE + 1}–${page * PAGE_SIZE + listed.length}` : "0";
  const selected = listed.find((m) => m.id === selectedId);
  const title = category ? categoryMeta(category).label : "All Mail";
  const quoted = `\u201c${query.trim()}\u201d`;
  // Summary counts stay independent from the current 20-message page.
  const upcoming = emails.filter((m) => {
    const due = dueInfo(m);
    return due && due.days >= 0 && due.days <= 14;
  }).length;
  const shown = category
    ? counts[category] || 0
    : Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className={showDetail ? "window detail-open" : "window"}>
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-tile" aria-hidden="true"><Icon name="envelope" size={14} strokeWidth={2.2} /></span>
          InboxIQ
        </div>
        <CategorySidebar counts={counts} active={category} onPick={pickMailbox} />
      </aside>

      <header className="toolbar">
        <div className="toolbar-title">
          <h1 className="toolbar-name">{title}</h1>
          <span className="toolbar-sub" aria-live="polite">
            {search.active
              ? search.searching
                ? "Searching…"
                : `${range} results${query.trim() ? ` for ${quoted}` : ""}`
              : loading
                ? "Loading…"
                : `${range} of ${emails.length}${shown > MAILBOX_WINDOW ? " newest" : ""} synced messages`}
            {!search.active && profile && ` · ${profile.total.toLocaleString()} in Gmail`}
          </span>
        </div>
        <SearchField value={query} onChange={setQuery} label={`Search ${title}`} />
        <div className="toolbar-actions">
          {/* Always mounted so screen readers announce each sync step. */}
          <span className="status" role="status" aria-live="polite">{status}</span>
          <button className="tool-btn only-narrow-mid" onClick={openSummary} aria-label="Summary"
            title="Summary">
            <Icon name="summary" size={16} />
          </button>
          <SyncButton onSynced={onSynced} onStatus={setStatus} />
          <AccountMenu email={email} onSwitch={switchAccount} onSignOut={signOut}
            settings={<AppearanceControl mode={appearance} onChange={setAppearance} />} />
        </div>
      </header>

      <EmailList emails={listed} title={title} pageKey={`${pageKey}:${page}`}
        loading={search.active ? search.searching : loading}
        loadingText={search.active ? "Searching…" : undefined}
        empty={search.active ? "No emails match these filters. Try a broader search or reset the filters." : empty}
        query={query}
        controls={<SearchFilters promotions={category === "promotion"} subcategory={promoSubcategory} onSubcategoryChange={setPromoSubcategory} filters={filters} onChange={setFilters} active={search.active || Boolean(category)}
          onReset={() => { setQuery(""); setFilters({ sender: "", after: "", before: "" }); pickMailbox(null); }} />}
        footer={<Pagination page={page} totalPages={totalPages} hasNext={hasNext} busy={busy}
          onPrevious={() => goToPage(page - 1)} onNext={nextPage} />}
        selectedId={selectedId} onSelect={openMessage} />

      <section className="pane detail-pane" ref={detailRef}
        aria-label={selected ? "Message" : "Summary"}>
        {selected ? (
          <ReadingPane key={`${uid}:${selected.id}`} uid={uid} email={selected} onClose={closeMessage} />
        ) : (
          <div className="summary">
            <header className="pane-head summary-bar">
              <button className="tool-btn only-narrow" onClick={closeMessage}>
                <Icon name="back" size={16} /> Back
              </button>
            </header>
            <div className="summary-body">
              <h1 className="large-title">Summary</h1>
              <OverviewCards counts={counts} subsCount={subs.length} monthlyCost={monthlyCost}
                upcoming={upcoming} onPick={pickMailbox} />
              <SubscriptionsPanel uid={uid} subs={subs} monthlyCost={monthlyCost} busy={subsBusy}
                onDetect={detectSubs} />
            </div>
          </div>
        )}
      </section>

      {(error || search.error) && <div className="toast" role="alert">{error || search.error}</div>}
    </div>
  );
}
