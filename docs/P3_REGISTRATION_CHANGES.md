# P3-004 registration withdrawal and accommodation amendments

Requirements SCH-01, TEN-01 and GOV-01. Accepted baseline cc82675 passed 782 strict local tests and Foundation gate #15 (run 46030933675), all four jobs green in 9m 11s on owner evidence. This is the next bounded scheduling increment; P3 remains open.

## Immutable decisions and revision fencing

Original sitting_registrations remain revision 1 receipts. A change appends a new registration_changes event with a strictly increasing per-registration revision, and a separate registration_change_reasons row. No original registration, candidate identity, sitting, publication, policy or past decision is rewritten. GET on the original registrations collection and original registration-batch retries continue to return the frozen creation receipts; they do not imply the registration is still active or that its initial allowance is current.

Staff GET `/api/v1/tenants/{tenant_id}/exam-sittings/{sitting_id}/registrations/{registration_id}/status` returns effective revision, status, extra_minutes and allowed_minutes. GET `/changes` on that registration returns ordered decision history and private reasons, paginated with offset and limit. Original revision 1 remains available in the original registration receipt; the change history begins at revision 2.

An active institution administrator or coordinator with exams.manage uses PUT `/registrations/{registration_id}/changes/{change_id}` beneath the sitting path. The change_id is a new caller UUID, preserved for retries. The body contains expected_revision, action, reason and, for accommodation amendments only, extra_minutes. Unexpected fields are rejected.

Example amendment from original revision 1:

```json
{"expected_revision":1,"action":"amend_accommodation","extra_minutes":20,"reason":"Approved synthetic pilot accommodation"}
```

Example withdrawal after that amendment:

```json
{"expected_revision":2,"action":"withdraw","reason":"Synthetic candidate withdrawal request"}
```

Reasons are trimmed and require 3-500 characters. The server derives the next revision, effective total duration and referenced candidate/sitting. Extra time is a strict integer from 0 to 240. Zero explicitly removes an existing allowance. An unchanged allowance returns 409 rather than creating a new decision. An amendment requires a currently active candidate membership and user. Withdrawal is permitted for an existing inactive candidate registration, so staff can remove eligibility without restoring membership.

A new decision requires the current expected revision and an active, not-cancelled sitting that has not opened, using database clock_timestamp(). Effective duration must fit the sitting's full window. The close remains the hard cap. A stale revision, cancelled sitting, opened sitting or already-withdrawn registration returns 409 without writes. Withdrawal is permanent in this increment; no reinstatement, deletion or second registration bypass is supported. No attempt/deadline amendment after opening is introduced.

Same change ID and normalized body return the original decision, even after later changes, withdrawal, sitting cancellation or opening. Changed ID reuse or reuse on another registration returns 409. Current staff authority is rechecked before replay. New requests after a terminal state remain rejected. A new sitting/registration does not automatically inherit old decisions.

## Candidate and private projections

The existing candidate eligibility endpoint uses the latest allowed duration and reports window_state=withdrawn, can_start=false and deadline_if_started_now=null after withdrawal. Sitting cancellation takes precedence if both are recorded. No private reason, decision actor, history, grading key or policy is added to the candidate HTTP payload. Current membership and server timing still apply. The eligibility check is informational; P4 must recheck the current registration state, cancellation and allowance atomically at actual attempt creation.

The candidate-readable registration_changes table contains timing/state/identity receipt metadata only, limited by forced RLS to the active candidate's own history. Free-text reasons are in a separate forced-RLS table restricted to current admin/coordinator staff. Candidate SQL cannot select any reason rows; staff HTTP history is also protected by exams.manage. Reasons are not put in audit or outbox snapshots. The existing original registration projection contract is preserved; this increment does not introduce another copy of its original accommodation reason.

## SQL, audit and concurrency

Migration 0016_registration_changes adds the two immutable tables, same-tenant foreign keys, unique per-registration revisions and constrained action/timing/reason fields. No previous migration is modified or prior row backfilled. Event insertion locks the institution row, then validates original registration binding, latest revision, candidate, sitting, cancellation, terminal status and duration. This matches existing membership, scheduling and cancellation serialization. Same-ID concurrent retries acknowledge one event; different decisions against the same revision permit one winner and a stale conflict. Cancellation and registration decisions serialize under the same lock.

A deferred constraint trigger requires the private reason row before committing any event. SQL UPDATE/DELETE guards protect event and reason history even from the owner. A forged candidate/sitting/allowance, nonsequential revision, terminal/open transition or reasonless commit is rejected. The API commits decision, private reason, registered audit action (exam.registration_withdrawn or exam.registration_accommodation_changed), outbox event and delivery in one transaction. Injection failures must leave all rows unchanged. Audit states are empty safe objects rather than serialized requests or sensitive explanations.

Readiness expects revision 0016, 23 forced-RLS tables and 18 enabled guards. Runtime gets separate SELECT and INSERT privileges on both new tables, without UPDATE/DELETE/TRUNCATE. The worker gets neither table; provisioning rejects a worker role already holding decision/reason access. Downgrade refuses to discard existing decisions or reasons. An empty schema supports downgrade/reupgrade and metadata comparison.

## Installation and remaining gates

Keep the application stopped. From backend with the project virtual environment, run the guarded installer --check, default installation and --verify. The installer backs up changed sources; it does not migrate application data. Focused verification creates random disposable PostgreSQL databases using the configured migration credentials. Only after passing, apply `python -m alembic upgrade head`, run `python -m alembic check`, and refresh `python -m app.manage grant-runtime`. Then run the full PostgreSQL/live-media gate with scanner port 23310 and obtain new remote CI evidence before the next dependent task.

Rescheduling, invitation acceptance/delivery, CSV import, coordinator browser workflows, operational acceptance and P3 completion remain open. There is no candidate self-service withdrawal, outbound email, accommodation deadline extension, running-attempt modification or automatic reinstatement in this increment.

## Authoring evidence

Pinned Python 3.12: 442 portable tests passed. Disposable real PostgreSQL 16.2 over TCP: 222 integration tests passed, including all 44 new registration-decision cases plus sitting, cancellation, schema/metadata, empty migration round-trip, identity, audit/outbox and question-version regressions. This verifies private-reason SQL isolation, same-ID retries, stale-revision conflicts, cancellation/decision serialization, immutable history, open/terminal SQL denial, reasonless commit rejection, grant/guard readiness and transactional rollback. The older cancellation downgrade test now compares its rolled-back head with EXPECTED_DATABASE_REVISION rather than hard-coding 0015; its data-preservation assertions remain intact.

Dependency compatibility/pins, repository Ruff lint/format with its backend config, diff checks and unintended-SQL-bind checks passed. The guarded installer was smoke-tested against exact baseline cc82675 for baseline validation, complete source installation, payload integrity, identical replay and rejection of local source drift. Existing TestClient/httpx deprecation warning remains non-failing. Full collection is 842 cases; collection is not a full-run claim. Owner PostgreSQL 17/live-media verification, browser acceptance and new CI remain pending. No application database was used.
