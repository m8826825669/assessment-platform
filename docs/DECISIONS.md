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
