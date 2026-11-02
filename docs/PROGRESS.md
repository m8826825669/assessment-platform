# Progress

Controlling scope: MASTER_ROADMAP.md v1.0. Source release 0.5, 1 November 2026.

## Completed gates

- P0: roadmap, requirements, architecture decisions and continuity records.
- P1-001: domain reference kernel, 25 tests.
- P1-002: real Windows/PostgreSQL migration/schema/readiness and 57 tests; see LOCAL_VERIFICATION_P1_002.md.
- P1-003: real Windows/PostgreSQL identity/tenant enforcement, 134 tests and restricted-role readiness/auth/logout/revocation smoke; see LOCAL_VERIFICATION_P1_003.md.
- P1-004: real Windows/PostgreSQL strict suite 227 passed with no skips, clean migration/schema/Ruff, separate worker provisioning and real queued event delivery with an empty repeat. See LOCAL_VERIFICATION_P1_004.md. The 0.4.1 correction changed only the correlation-sensitive test assertion.

## Current increment: P1-005

Implemented repeatable setup, dependency declaration/lock/installed-version checks, a single verification gate with sanitized counts, skip rejection and explicit partial mode. Added nine tests covering false acceptance, prerequisite opt-in, fail-fast behavior and secret-safe summary output. Added CI source with three Linux Python/PostgreSQL jobs and one partial Windows job. Existing migration bytes, dependency versions and application schema/behavior remain unchanged. Source updater now verifies all three migrations.

Fresh authoring environment: Python 3.12.14 on Linux; pinned installation, dependency checks, lint/format and 146 non-database tests passed, no skips. Full collection is 236 tests. See VALIDATION_P1_005.txt. Existing Starlette/httpx deprecation warning remains tracked. Ruff import classification is explicit so checks behave consistently across working directories; two test import blocks were normalized, not application logic.

## Gate status and next action

P1-005 IMPLEMENTED, FRESH LOCAL POSTGRESQL AND ACTUAL REMOTE CI ACCEPTANCE PENDING.
P1 overall IN PROGRESS. No remote repository was created or published and no CI run occurred.

Apply P1_005_UPGRADE_WINDOWS.md. Run the full gate with the working environment, then a separately created fresh environment. Retain sanitized reports and zero-skips results. Place the complete project at the root of a repository and run the included workflow; retain actual run URL, commit SHA and every job outcome. Review DEVELOPER_GUIDE.md's final P1 checklist. Resolve any failures before closing P1 and expanding P2 tasks. Do not mark authored CI or partial unit checks as passing CI.

## Scope limits

No frontend, persistent question bank, live examination runner, scoring/results workflow or adaptive testing yet. The domain kernel remains an in-memory reference. Current worker effects are local database receipts only; no external transport, daemon supervision, fanout or ordering guarantee is claimed. Audit and envelopes are append-only for restricted roles, not sealed against the owner. Runtime and worker credentials remain private server capabilities. No public registration, MFA, recovery email, SSO, custom roles, cookie browser integration or platform-owner console yet. Production capacity, recovery, observability, retention and privacy gates remain later work.
