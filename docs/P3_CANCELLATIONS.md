# P3-004 pre-opening sitting cancellation

Requirements SCH-01, TEN-01 and GOV-01. Baseline 43bc993 passed 757 strict local tests, migration 0014/schema/runtime checks and Foundation gate #14 (run 46013682334, 7m 59s). All three PostgreSQL 17/Python matrix jobs and the partial Windows job succeeded on owner evidence.

## Contract

An active administrator or coordinator with exams.manage can PUT `/api/v1/tenants/{tenant_id}/exam-sittings/{sitting_id}/cancellation` with `{"reason_code":"administrative"}`. Allowed reason codes are administrative, schedule_error and operational. No free-text reason, candidate details, email or arbitrary metadata is accepted. GET on the same path retrieves the staff receipt; absence returns 404. Candidate HTTP callers use eligibility, not the staff receipt route.

A new cancellation is allowed only before opens_at, using database server time. It is permanent. A replacement schedule requires a new sitting ID and explicit new registrations; no candidate is silently transferred. Open/running sitting cancellation, attempts and refunds are outside this increment. Exact same-code retries acknowledge the durable cancellation, including after opening; another code returns 409. Current staff authority is checked before replay.

Cancellation is a new immutable row, not an update to the original sitting or registrations. It preserves the exact publication, schedule, policy and original registration receipts. Identical sitting/registration retries continue to acknowledge their original records. New registration batches containing any new candidate fail atomically for a cancelled sitting.

For a registered active candidate, eligibility reports window_state=cancelled, can_start=false and deadline_if_started_now=null. Its existing safe field allowlist is preserved, without staff cancellation metadata. Unregistered, wrong-tenant or inactive candidates retain generic denial. Eligibility remains informational; P4 must recheck cancellation atomically when actually creating an attempt. Cancellation does not send email or other external effects.

## Database boundaries

Migration 0015_sitting_cancellations adds a same-tenant composite foreign key to exam_sittings, a constrained reason code and actor/time receipt. Forced RLS permits staff reads/creates in their institution and registered candidate reads for their own sitting. Candidate SQL sees only fixed non-sensitive reason codes and receipt metadata; there is no private text. No candidate insert/update/delete policy is added. The worker receives no access.

Cancellation insert and registration insert both lock the institution row before checking the other state, matching existing membership/registration serialization. Two concurrent cancellation retries produce one durable receipt; a concurrent registration may finish first, or is rejected if cancellation wins. In either case no registered candidate can subsequently start under the cancelled eligibility state. Update/delete triggers protect cancellation even from owner SQL. Existing migrations 0001-0014 are unchanged.

Business row, registered safe-empty audit action exam.sitting_cancelled, outbox event and delivery commit together. Failure rolls back the entire transaction. No reason or request body is copied into audit snapshots. Readiness expects revision 0015, 21 forced-RLS tables, 15 enabled guards and separate runtime SELECT/INSERT grants for the new table. The restricted worker is rejected if given cancellation privileges. Downgrade refuses to discard existing cancellations; empty-schema downgrade/reupgrade remains supported.

## Owner installation and gate

Stop the application. From backend with the active project virtual environment, run the delivered installer --check, then with no flags, then --verify. The installer backs up changed sources and does not migrate application data. Focused tests use only random disposable databases via configured migration credentials. After focused success, apply `python -m alembic upgrade head`, run `python -m alembic check`, and `python -m app.manage grant-runtime` before restarting the application. Run the full existing live-media verification gate with local scanner port 23310, then review/commit/push and obtain actual new CI evidence before the next dependent task.

Rescheduling, registration withdrawals, accommodation amendments, invitations/acceptance, CSV, coordinator browser acceptance and P3 milestone acceptance remain open. This bounded increment addresses pre-opening cancellation only.

## Authoring verification

Pinned Python 3.12 environment: 426 portable tests passed. Real disposable PostgreSQL 16.2 over TCP: 62 tests passed for cancellation/sitting/database contracts, followed by 136 passing cancellation/identity/audit/question-version tests, including all 24 new cancellation cases. The runs overlap and their counts must not be added. Schema metadata comparison, empty-schema downgrade/reupgrade, nonempty cancellation downgrade refusal, cutoff/replay behavior, forced-RLS visibility, direct SQL mutation denial, transaction rollback, concurrent retries and registration/cancellation serialization passed. Dependency compatibility/pins, repository Ruff lint/format with its explicit backend config, SQL binding checks and clean diff checks passed. A clean-baseline installer smoke test verified installation, identical replay and rejection of drift.

The existing Starlette TestClient/httpx deprecation warning remains non-failing. These results do not replace owner PostgreSQL 17/live-storage/ClamAV/full verification, coordinator browser testing or new remote CI. No application data was used for these tests.
