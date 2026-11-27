# P3 immutable draft revisions

Requirements ASM-01, PUB-01, TEN-01 and GOV-01. This increment remains pending real PostgreSQL, full regression and CI acceptance.

## Accepted baseline

Owner Windows verification for commit 3c22436 passed 680 tests with no failures, errors or skips. Foundation gate #12, run 45951039305, succeeded in 7m 36s with all three PostgreSQL/Python jobs and the partial Windows job green. The source baseline includes audit creation and publication-access hardening through migration 0012. This evidence does not close P3.

## Editing contract

Each draft ID identifies an immutable revision. An exam's stable exam_id equals its first draft ID. Existing drafts become revision 1 of their own exam without changing their blueprint, ID or publication. Edits append a new draft ID under the same exam_id and point to an exact parent_id. No UPDATE grant is introduced.

PUT /api/v1/tenants/{tenant_id}/exam-blueprints/drafts/{draft_id} retains its creation and identical-retry behavior. GET returns the saved content and adds exam_id, revision and parent_id.

POST /api/v1/tenants/{tenant_id}/exam-blueprints/drafts/{draft_id}/revisions takes id (a fresh UUID for retry identity), expected_revision (the parent's integer revision) and sections. The parent must be the current revision. A stale editor receives 409 with no writes. Identical replay returns its original committed revision even after later edits; changed payload reuse returns 409. All mutations recheck coordinator/admin authority after acquiring the existing institution lock.

GET /api/v1/tenants/{tenant_id}/exam-blueprints/drafts/{draft_id}/history returns the exam's revisions in ascending order. The same tenant and exam-management permissions apply. The draft ID is the public immutable revision identity; revision integers are meaningful only within exam_id.

Draft revision insertion, exam.draft_revised audit metadata and outbox records commit together. The audit includes actor, tenant, new draft identity and before/after revision counters. It excludes blueprint content, titles, media and scoring keys. Old snapshots remain immutable at the database level through a trigger. Unique revision numbers, tenant-bound parent/root foreign keys and a per-exam advisory lock reject direct-SQL branches or skipped revisions.

## Publishing contract

A new publication must select the current draft revision and revalidate approved questions. The existing draft-ID publication URL remains usable. Optional expected_revision explicitly fences the request; an incorrect revision returns 409. Omitting it retains compatibility because the selected draft ID itself identifies immutable content and must still be current. Validation is repeated inside the transaction; no cached validation status is trusted.

An already published revision continues returning its original snapshot after further draft edits. Starting a later draft does not rewrite or invalidate an earlier publication. Each new revision has its own publication ID, equal to that revision's draft ID. Sittings will bind to that exact publication in P3-004. Archiving, sitting management and configurable scoring policies remain separate work.

## Migration and verification

Migration 0013 adds lineage columns to the existing table and preserves all legacy rows and publications. It adds constraints and a mutation/lineage trigger. Existing table-level runtime SELECT/INSERT privileges cover the added columns; no new elevated grant is required. Readiness expects revision 0013 and the enabled trigger, and retains the 0012 publication-policy absence check.

Apply the source with the guarded installer while the API is stopped, then run its --verify mode first. It uses disposable PostgreSQL databases and includes migration-preservation and deterministic publication/edit lock-order tests. It does not need live media. After it passes, upgrade the application database, check metadata, and run the strict full gate with isolated storage/scanner services. Preserve the prior local scanner override 23310; Compose/CI defaults remain 13310.

A downgrade refuses to discard non-root revisions. Do not use a downgrade as routine installation or rollback; any rollback after real revision creation requires a preservation plan.

Authoring evidence currently includes 398 unit tests, Ruff lint and format checks, offline SQL generation, and collection of 20 new PostgreSQL integration cases. The execution sandbox denies socket creation, preventing a local PostgreSQL server here. No live SQL, authorization, transaction or concurrency pass is inferred from the unit/offline checks.
