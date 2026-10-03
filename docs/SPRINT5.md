# Sprint 5: inbox search and advanced filters

Selected commitment: F12 in the product backlog. The source product plan left
individual Sprint 4–14 commitments open; this scope was selected for Sprint 5.

## Changes and dependencies

| Branch | Distinct change | Dependency |
| --- | --- | --- |
| feature/abhiram-search-sprint5 | Bounded text/sender/date/category search API, ranking, paging and synthetic API tests | Published main baseline |
| feature/akanksha-search-sprint5 | Search field, filters, reset, loading/errors, additional pages and stale-response handling | Backend search branch |
| feature/satwik-search-quality-sprint5 | Safe matching-text display, accent-aware highlights, body excerpts, advanced search cases and documentation | Both preceding branches |

The feature branches are stacked; they do not represent three independent
implementations. Their labels organize feature areas. The actual configured
committer identity is used for all commits; labels do not claim other authorship.
The dedicated `sprint5` branch merges all three. Existing feature branches and
the repository's default branch are preserved.

## Acceptance and limits

Search combines text, sender, category and inclusive UTC-day bounds, ranks
header matches above body-only matches, and uses date then message ID for ties.
Reset clears the query and all filters. Opening a result preserves the query.
Additional pages suppress duplicate IDs; failed pages can be retried while
keeping prior rows. New queries and accounts abort or ignore older responses.
Keyboard navigation and narrow-screen reading remain available.

Search scans the newest 500 synced messages in the selected mailbox. It does
not search unsynced Gmail. Pages read current stored data rather than a historical
snapshot. UID scoping in the local prototype is not production account
authorization; server-side authorization remains separate backlog work.

The published closure includes only F12 and direct dependencies. Unrelated local
classifier, auth/ingest fixes, private mail cases, credentials, local plans,
submission files and browser artifacts are excluded. Testing results for the
larger local checkout must not be presented as tests of this smaller closure.

## Verification

Run `python -m pytest tests -q` in backend using the development requirements,
`node tests/search_text.test.mjs` in frontend, and `npm run build` in frontend.
Synthetic tests exercise matching, operators, Unicode, ranking, account scope,
bounds, paging and input validation. Highlight checks exercise accent boundaries,
repeated matches, literal punctuation, safe HTML and body excerpt placement.
Live Gmail, OAuth consent, real Firestore and model services are not exercised.
No email mutation or send is part of F12.
