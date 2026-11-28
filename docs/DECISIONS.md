# Decisions

Baseline decisions DEC 001 through DEC 008 are recorded in MASTER_ROADMAP.md.

2026-11-01 — Begin with a dependency free reference domain kernel so core invariants can be verified before adding persistence. This is a P1 increment, not closure of P1. FastAPI and PostgreSQL remain the intended application stack.

Open decisions: pilot institution and policies; hosting region; product name; supported browser matrix; production capacity and recovery commitments; pricing; integration profiles. Resolve before the gates specified in the roadmap.

## 1 November 2026 P1 002 implementation choices
DEC 009 Use synchronous SQLAlchemy and psycopg for the initial API. FastAPI sync handlers run database work off the event loop. Revisit concurrency choices only against measured requirements.
DEC 010 Begin persistence with institutions, global user identity shells and explicit tenant memberships. Authentication, roles and database isolation remain P1 003, so expose no business routes yet.
DEC 011 Liveness is independent of database state. Readiness requires connectivity, exactly 0001_foundation and the foundation tables. Startup never applies migrations automatically.
DEC 012 P1 002 remains pending until real PostgreSQL migration and integration tests pass. Offline SQL generation and mocked readiness are not substitutes. No milestone order change is authorised.
DEC 013 Use a full pinned dependency resolution for this increment; Windows and Linux conditional requirements are included. The local PostgreSQL container is a development example, not a deployment image approval.

## 1 November 2026 P1 003
DEC 014 Close P1 002 using the user's 57 passing Windows/PostgreSQL tests, clean migration comparison and Ruff output. User evidence is retained separately from workspace evidence.
DEC 015 Use Argon2id passwords and opaque revocable bearer sessions. Store only token digests. JWT is not required by roadmap v1.0; a later JWT/SSO adapter would need a recorded decision and the same revocation/authority guarantees.
DEC 016 Keep migration credentials separate from a restricted API login. Reject elevated or owner roles for business transactions. Force row security on institution-owned foundation tables and bind context per transaction after authentication.
DEC 017 Use seven fixed roles, one per membership, with current permissions rechecked on each request. Initial users and institutions are provisioned by a trusted local operator; no public registration or default password is introduced.
DEC 018 Record minimum security events atomically with successful identity and membership changes. The full audit model, before/after details and outbox remain P1 004. This increment does not close that later task.
DEC 019 Serialize administrative membership changes on the institution row, recheck actor authority after locking, and retain one administrator with an active user account. The gate includes a concurrent demotion test.
DEC 020 P1 003 remains pending until the new real PostgreSQL suite and local restricted-account smoke pass. No later milestone is entered based on skipped tests.

## 1 November 2026 P1 004
DEC 021 Close P1 003 using the user's 134 passing Windows/PostgreSQL tests, restricted-role readiness and successful login/read/logout/revocation sequence. Retain only redacted status evidence.
DEC 022 Append an audit record, immutable versioned event and pending delivery in the calling business transaction. Preserve existing security_events and do not fabricate historical snapshots for earlier actions.
DEC 023 Capture explicit allowlisted state rather than serializing ORM objects or raw requests. Membership changes record before/after role, status and user UUID. Operators are identified by their database principal; a later deployment must govern human operator accountability.
DEC 024 Separate API enqueuer and worker credentials. Runtime cannot consume queue jobs; worker cannot access identity credentials or edit audit/envelope/receipt history. Row policies and explicit grants both apply.
DEC 025 The first consumer writes a local transactional receipt. Use SKIP LOCKED claims, expiring fenced leases, bounded attempts/backoff, permanent failure handling and audited operator requeue. No external transport is enabled, and no exactly once network claim is made.
DEC 026 Exception responses adopt RFC 9457 application/problem+json with top-level code and server request UUID. Diagnostic readiness retains its typed 503 report. Document the detail.code compatibility change.
DEC 027 P1 004 remains pending until all 227 tests and local producer/worker smoke pass. P1 005 CI/developer environment remains the next planned task; no milestone order or final goal changed.

## 1 November 2026 P1 005
DEC 028 Close P1 004 using the user's strict 227-test PostgreSQL pass, clean migration/schema/Ruff checks and real producer/worker/repeat smoke. See LOCAL_VERIFICATION_P1_004.md.
DEC 029 Use one stdlib setup entry point and one verification entry point. Full mode fails on missing PostgreSQL prerequisites or skipped tests; portable unit mode is explicitly partial. Use the existing separate migration credentials only to administer random disposable test databases.
DEC 030 Commit CI with isolated PostgreSQL services, pinned action commits, least-privilege repository access and no deployment. Preserve the existing application schema and all three migration bytes. Installed dependency version checks supplement the existing full pinned resolutions.
DEC 031 Actual fresh local PostgreSQL and remote CI evidence are required to close P1 005 and P1. Authored workflows and authoring-workspace unit evidence alone cannot satisfy the roadmap gate. No P2 development begins in this increment.

## 2 November 2026 P1 acceptance and P2 entry
DEC 032 Accept P1-005 and the P1 engineering foundation from the owner's local 236-test strict passes, separate-environment verification, and screenshot showing all four CI jobs successful for b00e0a8 / run 41375023675 attempt 2. Evidence provenance and limitations are retained in P1_ACCEPTANCE.md.
DEC 033 Expand P2 into eight requirement-linked tasks in P2_QUESTION_BANK_PLAN.md and BACKLOG.json. Preserve the original roadmap; include frontend and actual browser acceptance before closing P2.
DEC 034 First implement tagged immutable content contracts for the seven baseline question types, explicit public projections and a versioned content hash. No new database/API behavior or scoring engine is implied. The existing domain reference kernel remains unchanged.
DEC 035 Use plain text and explicit bounded engineering defaults for initial content. Use exact Decimal rules; multiple select initially declares all-or-nothing; numeric tolerance is absolute; short answers declare NFKC/case/whitespace rules; manual rubric totals must equal marks. These are content policies, not implemented P5 grading. Extensions require a compatible explicit contract/version decision.
DEC 036 P2 persistence will store immutable content versions and fence mutable pointers/status. Review is independent: an author, including an admin, cannot approve their own work. Approval binds exact content version/hash. Candidate projections exclude all private marking material. Media and imports require their own real storage/transaction/permission tests.
DEC 037 P2-001 remains pending strict local regression and actual CI on the new commit. The P1 CI run cannot be reused as evidence for P2 source. Do not begin P2-002 before that gate passes.

## 2 November 2026 P2-002
DEC 038 Accept P2-001 from the owner's local 299-test strict pass and correct CI screenshot for 918036d / run 41378575934, all four jobs successful. The earlier b00e0a8 rerun is excluded from P2 evidence. See LOCAL_VERIFICATION_P2_001.md.
DEC 039 Persist stable question identities and append-only saved content/title versions. Use a monotonic integer revision as edit fence/current pointer, a deferred tenant/question/number FK and composite parent FK. Triggers prevent history rewriting, identity mutation/deletion, revision jumps and appends outside the current revision. Privileges/RLS complement these structural guards.
DEC 040 Limit draft bank routes to institution admins and owning authors; review/coordinator selection remains P2-003. Preserve originating authorship across administrator edits. Recheck membership and live user/session/clock after the institution mutation lock; root version allocation is serialized too. Initial authoring writes intentionally share the institution lock with membership changes.
DEC 041 Audit question mutations with version UUID/revision/content hash only, in the business transaction. Worker receives safe audit envelopes and no question-table grants. Content validation and fingerprint remain question-content.v1; immutable title metadata is separate from that content-body hash.
DEC 042 Source/API release 0.7.0 adds migration 0004_question_versions and explicit runtime grant refresh. Existing dependency locks, question-content contracts and migrations 0001–0003 remain unchanged. No automatic migration, approval, imports, storage, grading or frontend is introduced. P2-002 stays pending strict PostgreSQL/new-CI evidence; do not start P2-003 until accepted.

## 2 November 2026 P2-003
DEC 043 Accept P2-002 from the owner's local 357-test strict pass, head/schema/readiness/worker checks and successful workflow list entry for e18af0c. The workflow run ID/full SHA and individual logs were not supplied; no values are invented. See LOCAL_VERIFICATION_P2_002.md.
DEC 044 Store immutable per-version review events; derive state from the latest sequence. Approval/return requires an actor distinct from the originating author, exact version editor and submitter, including admins and role changes. All commands bind current question revision, per-version review counter and exact content hash.
DEC 045 Revising a pending version atomically supersedes its review and creates a fresh draft. Returned/superseded/retired snapshots are not resubmitted; corrections use new versions. Previously approved versions remain selectable while a newer draft is prepared, until explicitly retired. This does not change or implement P3 publication policy.
DEC 046 Use a separate public selection snapshot and nonrecursive role policies so coordinators do not need private version/review access. The database derives public content through a recursive allowlist; a deferred guard requires selection eligibility and approval/retirement to commit together. Private title/body content remain immutable. No definer privilege is introduced.
DEC 047 Preserve the existing institution mutation lock and live-authority recheck; add a shared transaction advisory lock for root revisions/review event appends with independent optimistic counters. Audit version/state metadata only; feedback stays in private decision history. No external notifications or browser acceptance are claimed.
DEC 048 Source/API 0.8.0 adds migration 0005_question_review and explicit runtime grant refresh. Prior migration bytes, dependency locks and question-content.v1 remain frozen. P2-003 remains pending strict local/new-CI evidence; next dependent task is P2-004 taxonomy/retrieval.

## P2-004 decisions (2 November 2026)

- Use one institution catalogue with subjects, subject-owned topics and flat outcomes/tags. Admin manages it; four staff roles may read it. No arbitrary hierarchy, deletion, reparenting or reactivation in this increment.
- Capture relational immutable term snapshots per question version; derive labels in SQL and fence link creation by server-generated transaction ID. Preexisting versions use marker zero and empty classification. Body-hash schema v1 stays unchanged; version identity binds metadata and approvals.
- Automatically include a topic's active subject. Maximum 64 references includes closure. Revision payloads fully replace classification; omission means empty. Retirement prevents new assignment but preserves old snapshots and filterability.
- Reuse existing permission-scoped collections with literal title/type/state/AND reference filters before bounded deterministic pagination. No secret-content search, full-text/relevance or descendant expansion. Initial offset paging promises no cross-request snapshot under concurrent writes.
- Catalogue, authoring and review mutations share institution serialization and post-lock authority checks; do not infer production throughput. Worker receives no taxonomy data privileges. Every new business mutation keeps atomic safe audit/outbox behavior.

## P2-005 decisions (2 November 2026)

- Accept P2-004 on owner evidence for 5b3e6a8; preserve roadmap and six earlier migrations.
- First secure static PNG/JPEG at question scope, with required immutable accessible descriptions; do not enable broader formats without validation/rendering acceptance. This is an explicit format boundary within P2-005, not completion of UI/media accessibility certification.
- Keep v1 content/hash unchanged and add frozen relational media references, bound by exact question version identity and creation transaction. Omitted media_ids clears a new version's attachment list.
- Use private versioned S3 object reads, exact length/hash checks and server-proxied authorization; no bearer public URLs, object overwrite route, listing or deletion authority in application storage credentials.
- Use explicit fenced synchronous ClamAV scanning with quarantine-on-error and signature freshness checks. Do not broaden the local outbox consumer into an external scanner worker. Database guards enforce legal states/clean references; external verdict correctness is a trusted application boundary.
- Use separate disposable test storage, real IAM/anonymous denials and real ClamAV/EICAR checks in strict local/CI acceptance. New dependencies are pinned; prior pins unchanged. Source-built archived MinIO is for local fixtures only; production storage support/licensing remains unresolved until release.
- SQL/audit/outbox are atomic, external object PUT is not. A failure may orphan an inaccessible opaque-key object; never auto-delete live bytes as rollback. Document reconciliation/retention/recovery gates rather than inventing a distributed transaction.

### P2-005 correction after owner live testing

0.10.0 real gate failed three cases (569 passed). Correct the still-unaccepted 0007 downgrade only, keeping upgrade AST and accepted six migrations unchanged; do not perform a main DB downgrade. Require an explicit real version ID in MinIO read policy because GetObjectVersion also matches GetObject. Refresh existing policy without rotating keys/recreating storage. Reject image trailing payloads and retain current validation on stored-byte reads; standard raw EICAR and format rejection are distinct evidence. 0.10.1 remains pending its own strict live/CI gate.

## P2-006 decisions (2 November 2026)

- Accept P2-005 from owner 581-test corrected pass, real storage/scanning/readiness and green workflow #6 for 709e448. No individual CI logs/run ID supplied.
- First import internal JSON profile v1, all seven existing content types, 2 MiB/50 rows/16 total media references. No QTI/LTI/CSV/Excel/update-import/approval authority; existing resources must already be valid.
- Preview is read-only/advisory and uses candidate projection; commit reuses a no-commit normal draft staging primitive in a single institution-serialized transaction, with live authority rechecked. Failures roll back all question/version/link/receipt/audit/outbox rows.
- Immutable success receipts scope UUID idempotency keys to institution + user across sessions. Equivalent canonical typed requests replay original IDs/time without side effects; changed valid payload conflicts, failures do not consume keys, new keys intentionally create new imports. Retired/unavailable references do not prevent acknowledging an already-committed receipt.
- Fingerprint includes ordered rows, refs, title, v1 body hashes and sorted metadata IDs. Preserve original content/hash schema and seven prior migrations. Batch audit stores UUID/count only; private keys/references/raw rows stay out of audit/outbox. Runtime receipt INSERT/SELECT only; worker gets no private receipt access.
- Source/API 0.11.0 and new migration 0008, with role/readiness changes, must pass strict new local/CI acceptance before P2-007 frontend journeys. No dependency/storage changes or production performance claim.

## P2-007 decisions (2 November 2026)

- Accept P2-006 on owner screenshot evidence for 6bae92a / Foundation gate #7, 652 strict tests and healthy API/worker. Preserve all eight accepted migration files and original roadmap.
- Add the intended Next.js/TypeScript institution workspace as a local repository application. No hosted Site, deployment, candidate runner, exam assembly or grading is introduced. Use plain CSS with native accessible controls; no extra component framework is necessary for the initial bounded screens.
- Pin Next 16.4.3 / React 19.3.1 and the resolved npm lock; minimum project Node 22. Preserve Python dependency locks. Browser tokens live in memory only; refreshing requires sign-in. A fixed operator-configured server proxy forwards explicit headers and bounded bodies, never browser-selected origins or cookies.
- Saved candidate rendering uses existing backend allowlisted projection, not private form contents. Add an exact-version reviewer preview route using the existing review authority/RLS and media verification; no new database privileges or migrations. All seven renderer branches escape plain text; staff marking fields are visibly separated.
- Retain unsaved form values on validation/conflict errors; reload/discard is explicit. Import commit attempts freeze payload/key until an explicit new-batch action. No local-storage draft/token cache, service worker or third-party analytics.
- Add component/proxy checks and a separate real PostgreSQL/S3/ClamAV Playwright gate. The existing Python full gate and a real browser pass are both required, followed by actual new-commit CI. Managed authoring preview failed because its launcher supplied unsupported Next CLI flags; no actual browser verification is claimed here. CI adds frontend/build/browser steps to the Python 3.12 PostgreSQL job, retaining all other jobs.

### P2-007 owner browser corrections

Preserve the successful 659-test backend gate. Mark decorative sidebar glyphs aria-hidden; give the application error alert a stable accessible name and scope browser selectors to that name, preserving Next route announcements. Keep the behavioral assertions and timeouts. Replace the affected Vitest 4.0.18 development dependency with exact 4.1.12 and regenerate its lock; do not use a blanket force fix. API/schema/Python/storage behavior stays unchanged. Corrected frontend/browser and actual new CI are still required.

### P2-007 saved-editor and viewport corrections

Use explicit unique prompt label/control association so imported saved textarea values cannot affect exact label queries; preserve existing field names and content. Constrain intrinsic responsive grid/control widths instead of hiding document overflow. Wait for the reload action to finish, then keep the same document-width acceptance criterion and attach safe class/geometry diagnostics. Owner accessibility snapshots do not identify the exact geometric overflow source; do not claim viewport acceptance without the corrected real browser run. Dependencies, API and schema unchanged.

### P2-007 table-label containment

Retain the owner's two successful0.12.2 browser scenarios. Remove absolute sr-only table title spans, preserving their semantics in explicit button aria-labels; establish a table scroll containing block. This addresses a code-supported root overflow source consistent with document474/body390 metrics; no actual corrected viewport pass is inferred. Keep strict document-width assertion and improve positioned/shadow diagnostics instead of clipping the document or extending timeouts. Dependencies and all backend/schema bytes unchanged.


## P3 immutable draft lineage — 27 November 2026

Preserve the deployed immutable draft-ID contract. Each edit appends a new draft row and ID, sharing the initial draft ID as stable exam_id, with a strict parent revision precondition. Existing IDs become revision 1. This avoids rewriting publications or widening runtime UPDATE grants. The public revision URL plus expected_revision protects stale editing; identical request-ID retries return original revisions. New publications must use the current revision; existing publication retries continue serving their frozen snapshots. Optional publication expected_revision keeps current clients compatible while the immutable draft ID and current-head check remain mandatory. These are implementation choices within ASM-01/PUB-01; archive/scheduling/UI acceptance remain future work.


## P3-004 initial scheduling contract - 27 November 2026

Use immutable sitting and registration snapshots tied to exact publications. The initial import format is a bounded atomic JSON batch for existing candidate accounts, with stable registration IDs as internal invitation references. External invitation delivery/acceptance and CSV remain explicit follow-up scope. Store UTC instants and an explicit fixed display offset initially; do not infer IANA/DST behavior. Accommodations add recorded minutes and require a reason and sufficient window length; sitting close remains the hard cap. New registrations close at sitting open. Current membership and server time drive the informational candidate eligibility projection; P4 must recheck the actual start atomically. Cancellation, withdrawal and accommodation amendments require separate audited lifecycle work before P3 acceptance.


## SCH-01 pre-opening cancellation boundary (27 November 2026)

Store permanent cancellations separately from immutable sitting/registration snapshots. Accept a fixed reason code only; preserve existing receipts on replay, reject new registrations and return cancelled candidate timing eligibility. Serialize cancellation/registration with the institution lock, require atomic audit/outbox and guard inserts/immutability in SQL. Cancellation after opens_at and any effect on running attempts are deferred to the attempt lifecycle design; no external notification is introduced.


## SCH-01 registration decision lineage (27 November 2026)

Preserve original registration receipts as revision 1 and append server-fenced decisions. Amendments can replace or remove extra time before opening, with candidate eligibility and window checks. Withdrawal is terminal and also permitted for an inactive candidate; no reinstatement or second-registration bypass is added. Both new operations reject cancelled/open sittings, while authorized identical retries acknowledge their historical receipt. Keep free-text reasons in a separate staff-only table and use a deferred SQL constraint to require them atomically. Expose only safe timing/state to candidates; defer post-opening attempt/deadline changes to P4.


## SCH-01 CSV registration profile (28 November 2026)

Accept raw UTF-8 text/csv with four fixed columns, 64 KiB and 50-record bounds, stable caller registration UUIDs and existing candidate account UUIDs. Preview is read-only and never reserves eligibility; commit rechecks authority/timing and shares the original JSON batch's locked, atomic business/audit/outbox flow. Per-row retry receipts acknowledge history rather than restoring withdrawn/cancelled eligibility. Keep private CSV cells out of diagnostics and preview, show effective status separately from original receipt values, release read transactions before streaming, and retain schema/grants at 0016. External invitations/account creation and browser upload controls remain separate increments.


## SCH-01 atomic pre-opening replacement (28 November 2026)

Preserve immutable sitting snapshots by creating a new sitting and cancelling/linking the original in one institution-serialized transaction. Retain the exact publication/title/policy; require a fresh replacement UUID and future fitting window. Store only fixed reason codes and immutable same-tenant one-to-one links. Historical retries acknowledge immediate successors, even after later replacement decisions. Do not transfer registrations/allowances or restore withdrawn candidates automatically: staff must explicitly re-register them. Candidate link discovery, external notification and open/running attempt changes remain separate scope.


## SCH-01 in-app invitation acknowledgement (28 November 2026)

Use existing registration references for a signed-in candidate's own paged inbox. Add an immutable receipt of the current registration revision under the institution lock, with a database-owned timestamp and atomic audit/outbox. Acknowledgement is optional for both old and new registrations, may occur before close, and never starts an attempt, changes timing, restores authority or freezes later accommodations. Separate current invitation state from historical receipt replay. Staff may inspect receipts but cannot accept on a candidate's behalf. External email/link delivery and browser workflows remain separate scope; no new outbox side effect is authorized.


## SCH-01 candidate invitation browser boundary (28 November 2026)

Reuse memory-only identity and the existing candidate-safe invitation API for a paged inbox and optional acknowledgement. No local clock eligibility, question content, public registration, persisted bearer token or attempt-start control is introduced. Preserve the same registration identity during uncertain acknowledgement outcomes; separate historical receipt from a fresh state read. Tenant/session unmount discards late work. Candidate browser fixtures use disposable PostgreSQL without requiring media; existing authoring media journeys stay separate. Pin Next.js 16.4.6 to address audit-reported advisories exposed by the build of baseline 16.4.3. Coordinator screens, external delivery and P3 closure remain deferred.


## ASM-01 / PUB-01 / SCH-01 coordinator browser boundary (28 November 2026)

Expose accepted assembly/publication/sitting APIs through one permission-scoped workflow. Preserve exact version order, server diagnostics, immutable revision IDs and expected_revision publication fencing. Recover by explicit IDs rather than inventing a draft catalogue or persisted local token/draft cache. Freeze UUID, body and endpoint during uncertain requests, and keep form values after stale conflicts. Convert sitting times using an explicit fixed offset, never implicit browser/DST inference. Fixed pilot scoring policy remains read-only. Candidate-safe snapshots use explicit rendering, and current registration/lifecycle management remains a separate browser increment. No schema, grant, dependency pin or outbound effect change is required.
