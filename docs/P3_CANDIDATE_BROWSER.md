# SCH-01 / ACC-01 candidate invitation browser journey

## Accepted baseline and bounded scope

799c74c is accepted on owner evidence: 990 strict local tests and Foundation gate #19, run 46128839007, all four jobs green in 11m 39s. Migration 0018_invitation_acceptances is current. This increment adds the first candidate browser invitation workflow over that accepted API; it does not close P3 or begin P4. Coordinator assembly/scheduling screens and external invitation delivery remain open.

## Screen and recovery design

| Screen | Candidate action | Boundary and recovery |
| --- | --- | --- |
| Sign in and institution | Existing login and explicit institution choice | In-memory bearer session; reload requires sign-in. Current API permissions decide navigation. |
| My invitations | Read ten invitations per page; refresh, previous, next | SQL-scoped API pagination; historical invitations remain visible. Clear previous page while loading. No question-bank, taxonomy or publication requests. |
| Invitation detail | Inspect title, fixed display offset, opening/closing, allowance and server check time | Explicit candidate projection only. The browser never recalculates eligibility from its local clock or begins a countdown. Clear old detail on refresh. |
| Acknowledgement | Optional acknowledgement before close when offered by the API | Same registration's existing idempotent POST. No exam start, terms consent, reservation or timer. Server receipt is authoritative; re-read current state separately. |
| Unconfirmed outcome | Retry same acknowledgement or refresh to discover a saved receipt | Retain original registration ID during uncertain network/5xx outcome. No new idempotency identity; no automatic retry. Server conflicts retain an explicit refresh path. |
| Historical receipt | See accepted revision alongside current allowance/revision | Later amendments do not rewrite the receipt; withdrawal/cancellation never becomes eligible through acknowledgement. |
| Error or role change | Focus named error alert, clear protected data on denied access, sign in again on 401 | No raw server problem detail or arbitrary payload rendered. Session/tenant-keyed component ignores late responses after unmount. |

Existing staff navigation and question-bank workflows are retained. The candidate inbox has no start-exam control, private accommodation reason, scoring policy, question content, other candidate identity or replacement registration transfer. Empty and loading states are explicit. Detail and error focus, keyboard activation and a 390px viewport are tested; this is not a complete accessibility conformance audit.

## Dependencies and verification

Frontend version 0.13.0 pins Next.js 16.4.6, replacing 16.4.3 after the build flagged affected dependencies and npm audit identified moderate Next.js advisories (including GHSA-pc58-hwjq-p385). No blanket force fix or application configuration bypass is used. React and test framework pins remain unchanged. Reference: https://github.com/vercel/next.js/security/advisories/GHSA-pc58-hwjq-p385.

Run frontend npm ci, typecheck, format:check, test and build. The candidate browser gate is separate from default backend testpaths and requires explicit disposable database creation consent. From activated backend, set ASSESSMENT_ALLOW_TEST_DATABASE_CREATION=1 and run `python ../scripts/verify_candidate_browser.py`. It reads local migration credentials privately only to create an isolated random database, synthetic memberships/publication/sittings and a loopback restricted API. No application migration, runtime grant refresh, application business data or media service is needed for this candidate-only gate. Keep port 14173 free. Install Playwright Chromium with `npx playwright install chromium` from frontend first.

The existing full browser gate continues to require dedicated live media. Its old journey runner explicitly selects journeys.spec.ts; the new runner selects invitations.spec.ts. CI already invokes every Python browser-check file and therefore runs both suites on Python 3.12. CI uses pinned Playwright Chromium by default. An optional ASSESSMENT_BROWSER_EXECUTABLE path selects an explicitly installed authoring browser without changing the shipped application or CI defaults.

Five real-browser scenarios cover safe traffic, acknowledgement/paging/memory-only session, committed response loss and retry with SQL event-count assertion, terminal states and amended historical receipt at narrow viewport, cross-tenant late response isolation/other-candidate scope, and session expiration. The last is an injected HTTP 401 response, not proof of a real revocation race; real membership revocation remains covered by accepted API/database tests. All candidates and events are synthetic disposable fixtures. No screenshots/traces with bearer sessions are saved.

Owner Windows browser evidence, full local gate and actual new-commit CI remain pending until explicitly recorded. External email invitations, coordinator UI, manual screen-reader checks, attempt delivery and final P3 acceptance remain open.

## Authoring evidence

Authoring verification: 496 portable backend tests and all 35 real PostgreSQL invitation API tests passed. All 29 frontend tests, TypeScript checks, Prettier, production build, dependency pin checks and repository Ruff checks passed. npm audit reports zero vulnerabilities after the Next.js patch. All five actual candidate browser scenarios passed against the restricted API and disposable PostgreSQL 16.2, using authoring Chromium 158.0.8127.0; pinned Playwright Chromium download was blocked in this environment. SQL confirms exactly three acknowledgement receipts/events (one seeded plus two browser acknowledgements), with no duplicate on lost-response retry. The 390px focus issue was corrected without weakening assertions or increasing timeouts. Existing media authoring browser scenarios were not rerun here and remain part of owner/CI acceptance.
