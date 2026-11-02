# Progress

Controlling baseline: MASTER_ROADMAP.md v1.0; P2 plan: P2_QUESTION_BANK_PLAN.md. Updated 2 November 2026. Source/API release 0.7.0, P2-002. Original roadmap/Word baseline unchanged.

## Completed

P0 and P1 engineering foundation are accepted; see P1_ACCEPTANCE.md. P2-001 is accepted from the owner's local 299-test strict PostgreSQL pass (147.03s, zero skips) and all four CI jobs green for the correct commit 918036d / run 41378575934. An older b00e0a8 rerun was excluded. See LOCAL_VERIFICATION_P2_001.md. Screenshot evidence proves job conclusions; remote logs/full SHA were not independently fetched.

## Current implementation: P2-002

Persistent tenant-owned questions and immutable saved versions, current revision fencing, scoped composite references, guarded appends, own-author/admin draft CRUD subset (create/read/new-version/history), staff-only safe preview, current authority rechecks after lock waits, and atomic business/audit/outbox writes. No destructive draft edit or delete operation exists; every accepted save is a new snapshot.

Migration 0004_question_versions creates the two new tables, policies, current-version FK and two guards. Application requires nine forced-RLS tables, enabled immutable guards and new restricted API grants; worker is denied question-table rights. API/source version 0.7.0. Dependencies, all three older migration bytes and question-content.v1 remain unchanged.

Portable evidence: 230 tests passed with no skips; dependency/lint/format checks clean. Full suite collection: 357 tests, including 127 PostgreSQL tests. SQL parser accepted 72 migration statements and both PL/pgSQL functions; syntax only, not database execution. See VALIDATION_P2_002.txt for exact evidence and limits.

## Gate and next action

P2-002 IMPLEMENTED, LOCAL POSTGRESQL AND NEW REMOTE CI ACCEPTANCE PENDING. P2 overall remains in progress. This workspace cannot execute PostgreSQL under its required non-root server process constraints. Do not count portable tests or SQL parsing as persistence/concurrency proof.

Follow P2_002_UPGRADE_WINDOWS.md: stop old processes, apply separate source bundle, migrate to 0004, compare schema, refresh existing restricted role grants, run all 357 tests with zero skips, restart/check readiness and worker status, inspect/commit/push and verify every CI job for the new commit. Then record P2-002 acceptance and implement P2-003 independent review/approval. Historical passing CI does not validate new source.

## Explicit limits

All saved versions are drafts; review/approval/retirement and approved selection are P2-003. Taxonomy, protected media, atomic imports and browser authoring are later P2 tasks. No frontend, live candidate runner, scoring/results or adaptive testing is delivered. Current preview is a staff-only JSON projection. Database credentials remain private server capabilities; an owner able to disable guards is outside the append-only protection claim. Initial create has no replay idempotency key; revision retries are conflict-controlled. Authoring mutations currently serialize per institution, without a capacity promise. Existing Starlette/httpx TestClient warning remains visible. Production/security/accessibility/recovery gates remain later work.
