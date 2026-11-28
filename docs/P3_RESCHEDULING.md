# P3-004 atomic pre-opening sitting replacement

Requirements SCH-01, PUB-01, TEN-01 and GOV-01. Baseline 9c638bf is accepted on owner evidence: 895 strict local tests, clean schema comparison and green Foundation gate #17 (run 46113506495) in 9m 33s, across all three PostgreSQL 17/Python jobs and the partial Windows job. P3 remains in progress.

## Contract and retained history

An active administrator/coordinator with exams.manage can POST `/api/v1/tenants/{tenant_id}/exam-sittings/{sitting_id}/reschedule`. The body contains replacement_id (a new caller UUID retained for retries), timezone-aware opens_at/closes_at, reason_code (administrative, schedule_error or operational), and optional display_timezone. Omitted/null display_timezone preserves the original fixed display offset; supplied offsets follow the existing UTC/UTC+05:30 profile. The instants normalize to UTC. No title, publication, scoring policy, candidate list or arbitrary private explanation is accepted.

```json
{"replacement_id":"67cf9247-dc51-45bd-86ec-2e80a641ad8c","opens_at":"2030-01-02T09:00:00+05:30","closes_at":"2030-01-02T11:00:00+05:30","reason_code":"schedule_error"}
```

A new reschedule requires the original not to have opened or already been cancelled/replaced. The replacement must open in the future and its full window must fit the frozen base duration. The replacement ID must be unused in that institution, including when an existing sitting happens to have identical values. The same ID as the original is rejected. Use the existing schedule API for unrelated new sittings; this endpoint never merges an existing target or retargets a published exam.

In one transaction, create the new sitting, cancel the original with the chosen fixed reason, and append a permanent sitting_reschedules link. Freeze the original title, exact publication ID, base duration and full policy onto the new sitting. Later exam drafts, catalog changes or source retirement do not replace that published snapshot. The old sitting, registration receipts and accommodation/withdrawal history remain unchanged. The old candidate eligibility becomes cancelled. The new sitting has no registrations, and old candidates cannot retrieve its eligibility until explicitly registered there.

Registrations and extra-time decisions are deliberately not copied. Staff must review candidates and allowances and register them under new stable IDs, through JSON or CSV, with enough window for every new allowance. A previously withdrawn candidate is never silently restored. There is no automatic candidate migration, invitation/email, notification delivery, refund, attempt/deadline change or candidate-facing replacement discovery in this increment.

## Receipts, retries and chains

GET `/exam-sittings/{sitting_id}/reschedule` requires current exams.manage authority and returns sitting_id, replacement_id, reason_code, rescheduled_at and the frozen staff replacement snapshot. Absence returns 404. The original sitting GET and list remain immutable schedule receipts, not a lifecycle-state summary; use the cancellation/reschedule/status APIs for current decisions.

An identical normalized POST retry returns the original receipt without new rows/events. It remains valid after original opening and after the replacement is later cancelled or rescheduled. Changed replacement ID, reason, instants or effective display offset for an already-linked original returns 409. Current staff authority is always rechecked before replay. Another replacement can itself be rescheduled before opening, creating another immutable link; earlier links continue to identify their immediate historical successor, not the newest descendant. No complete-history traversal UI is claimed.

The replacement registration window still closes at its own opens_at. Starting remains capped by its closes_at and the newly recorded candidate allowance. Eligibility is informational; P4 must recheck actual authority, registrations, cancellations and deadline policy atomically at attempt start. Open/running sittings cannot be rescheduled through this API.

## SQL, authorization and atomicity

Migration 0017_sitting_reschedules adds same-tenant foreign keys to original and replacement sittings, a unique replacement target, a self-link check and constrained reason codes. Each original has one immutable outgoing link; each target has at most one predecessor. Forced RLS limits reads/creates to current admin/coordinator staff in the active institution. Candidate and worker SQL receive no reschedule-history access. A candidate keeps the existing safe cancellation view of their old registered sitting rather than gaining access to the replacement or its candidates.

The insert trigger locks the institution, then verifies both referenced sittings, unopened timing, matching original cancellation reason/actor, replacement creator, identical publication/title/duration/policy, and an uncancelled target without registrations. This enforces coherent relationships and prevents cycles through cancelled predecessors. The API additionally requires a freshly created replacement and creates all three business records itself in one transaction. UPDATE/DELETE triggers protect link history even from owner SQL. Registration and cancellation decisions serialize under the same existing institution lock, so a concurrent original registration either commits first and remains historical or is denied once cancellation wins.

Safe-empty audit actions exam.sitting_created, exam.sitting_cancelled and exam.sitting_rescheduled, with their outbox events/deliveries, commit with the three business records. Correlation and subject IDs connect the operation; no request body or private reason is serialized. Any failure rolls the entire operation back. Concurrent identical requests produce one receipt; different targets for the same original permit one success and one conflict. A standalone cancellation with a different reason code racing with rescheduling permits one success and one conflict, without a partial replacement. A matching cancellation reason may instead acknowledge the cancellation already created by a successful replacement.

Readiness expects revision 0017, 24 forced-RLS tables and 19 enabled guards. Runtime needs SELECT and INSERT on sitting_reschedules, without UPDATE/DELETE/TRUNCATE. The worker receives no new access, and provisioning rejects a worker role already holding reschedule privileges. Downgrade refuses to discard existing links; empty-schema downgrade/reupgrade is supported. Migrations 0001-0016 remain unchanged.

## Owner gate and remaining scope

Stop the API. From backend with the project virtual environment, run the guarded installer --check, default installation, then --verify against random disposable PostgreSQL databases. After passing, apply `python -m alembic upgrade head`, run `python -m alembic check` and refresh `python -m app.manage grant-runtime`. Then run the existing full PostgreSQL/live-media gate with scanner override 23310, commit/push and obtain actual new CI evidence. The installer never migrates the application database or widens grants itself.

External invitation acceptance/delivery, coordinator browser scheduling/import workflows, operational acceptance and P3 completion remain open. This is a pre-opening replacement API, not a running-exam retiming mechanism.

## Authoring evidence

Pinned Python 3.12: 484 portable tests passed. Real disposable PostgreSQL 16.2 over TCP: 169 rescheduling/scheduling/registration/CSV/cancellation/schema cases and a disjoint 119 identity/audit/question-version/publication-access cases passed, for 288 distinct integration tests. All 37 new rescheduling cases passed, including every audit/outbox stage rollback, concurrent replacement and cancellation/registration races, frozen publication/policy retention, explicit registration requirement, historical chains/retries, role revocation, SQL relationship validation, immutable history, forced-RLS visibility, worker separation, missing-grant/guard readiness and nonempty downgrade refusal. Empty migration round-trip and metadata comparison passed at 0017.

A retry time-fixture initially changed the replacement's immutable request window and correctly triggered a conflict. The corrected fixture advances only the original cutoff, leaving the historical replacement snapshot intact; no application relaxation was made. Dependency compatibility/pins, repository Ruff lint/format, clean diff and unintended-SQL-bind checks passed. The installer was smoke-tested against exact baseline 9c638bf for payload integrity, source installation, repeat installation and refusal of local source drift. Full collection is 943 cases, not a full-run claim. Existing TestClient/httpx warning is non-failing. Owner PostgreSQL 17/full live-media verification, browser acceptance and new CI remain pending. No application database or real candidate data was used.
