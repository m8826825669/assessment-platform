# Source release 0.5 — P1-005

- Recorded P1-004 local acceptance: 227 strict PostgreSQL tests, clean schema/lint and real worker/repeat smoke.
- Added safe environment setup and fail-closed verification with sanitized reports; portable checks explicitly report a partial pass.
- Added dependency declaration/lock/installed-version checks and CI matrix source.
- Added nine verification safety tests. Pinned dependencies and application/schema behavior remain unchanged.
- Source updater now verifies all three existing migrations. P1 remains open until fresh local and actual CI evidence passes.

# Changelog

## 0.1.0 — 1 November 2026
Created roadmap v1.0 and project continuity records. Implemented and tested the initial domain reference kernel. No production release.

## 0.2.0 — 1 November 2026
Implemented P1 002 application and database foundation. Added FastAPI operational endpoints, SQLAlchemy foundation models, migration 0001_foundation, pinned dependencies, PostgreSQL integration harness and Windows setup documentation. Local evidence: 42 passed, 15 PostgreSQL tests skipped; live HTTP smoke passed. P1 002 acceptance remains pending. Original domain source received formatting only.

## 0.3.0 — 1 November 2026
Recorded the user's successful P1 002 verification. Implemented P1 003 password hashing, revocable bearer sessions, throttling, password changes, institution discovery, roles, membership administration, minimum security events, separate migration/runtime credentials and forced row policies. Added migration 0002_identity_tenancy, trusted provisioning commands, a source updater that preserves local settings and an upgrade guide. Workspace checks: 82 passed and 52 PostgreSQL tests skipped; new security acceptance remains pending.

## 0.4.0 — 1 November 2026
Recorded the user's successful P1 003 gate. Added explicit audit snapshots, scoped audit history, transactional outbox envelopes/delivery jobs, local idempotent receipt processing, fenced lease recovery, bounded retry/dead-letter handling and audited operator requeue. Added a separate worker credential/provisioning path, role-specific readiness guards, RFC 9457 exception responses and request correlation. New migration 0003_audit_outbox; both prior migrations are unchanged. No external notifications are sent. Workspace evidence: 137 passed, 90 PostgreSQL tests skipped; new database acceptance remains pending.

## 0.4.1 — 1 November 2026
Test-only correction: compare stable credential error fields while separately validating unique request IDs and matching instance/header values. Runtime behavior and migrations are unchanged. Added guarded one-file patch tool. User reported 226 passed and one obsolete assertion failure; final PostgreSQL rerun remains pending.
