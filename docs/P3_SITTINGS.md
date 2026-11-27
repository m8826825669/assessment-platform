# P3-004 sitting and registration foundation

Requirements SCH-01, TEN-01, PUB-01 and GOV-01. This is an initial scheduling increment, pending PostgreSQL, full regression and CI evidence. P3 remains open.

## Accepted baseline

Commit 6af1026 has owner evidence of 703 local tests passing with zero skips, clean schema at 0013, and green Foundation gate #13 in 7m 23s. The three PostgreSQL matrix jobs and partial Windows job succeeded. This increment starts from that exact source.

## Frozen sitting

An active institution administrator or coordinator can PUT /api/v1/tenants/{tenant_id}/exam-sittings/{sitting_id}. The body contains publication_id, title, timezone-aware opens_at/closes_at, and display_timezone. The publication must exist in the same tenant. A draft ID without a publication is not enough.

Instants are normalized to UTC. The initial display timezone is an explicit fixed offset such as UTC+05:30, or UTC. IANA regions and automatic daylight-saving conversion are not supported in this increment. Callers must supply offset-aware instants and the intended fixed display offset; the backend never interprets naive local times.

The new sitting must open in the future, and its window must fit the publication's base duration. The exact publication policy is copied as a frozen timing/scoring policy snapshot. Later exam edits do not change it. PUT retries with identical normalized data return the original sitting. Changed payload reuse returns 409. Read and paginated list APIs require exams.manage.

## Registration, import and accommodations

POST /exam-sittings/{sitting_id}/registrations accepts a registrations array of 1-50 entries. Each entry has an id UUID, candidate_user_id, extra_minutes (0-240, default zero), and an accommodation_reason when extra time is positive. These refer to existing active candidate memberships and active users in the same institution. No new account is created.

The registration ID is an internal invitation reference. The staff API can list and retrieve those registration references. There is no invitation email, secret link, acceptance workflow or outbound delivery in this increment. The existing outbox consumer remains local. JSON batches are the initial import format; CSV ingestion remains pending.

Registration is atomic for the entire batch, including audit and outbox writes. Entries must have distinct IDs and candidates, and the database permits only one registration per candidate per sitting. Identical per-entry retries return their durable records without duplicate events, including after the registration window closes. A changed ID payload or a second registration ID for the same candidate returns 409 without partial writes. Current coordinator authority is rechecked before replay. Existing registration receipts remain retrievable when a candidate later loses eligibility; that does not restore the candidate's access.

New registrations close at opens_at. The effective allowed duration is publication base duration plus approved extra minutes. The whole sitting window must be long enough for that allowance. Starting late still cannot move the deadline beyond closes_at. Approved breaks do not pause timing under the pilot contract. Reasons are kept in the staff registration record, not audit/outbox metadata or the candidate HTTP view.

## Candidate eligibility view

GET /exam-sittings/{sitting_id}/eligibility requires an active candidate membership and that candidate's registration. Unregistered or wrong-tenant IDs return the existing generic not-found response. The projection includes title, publication/registration references, UTC window, fixed display offset, allowed duration and server time. It omits question content, keys, rubrics, scoring policy and accommodation reasons.

can_start describes only current membership, registration and the sitting window. Before opens_at it is false; at opens_at it is true; at or after closes_at it is false. deadline_if_started_now is the earlier of closes_at and server time plus allowed duration. This endpoint does not create an attempt, reserve a start, pause a timer, perform device/media checks, or promise that the future delivery-start API will succeed. P4 must recompute authority and the actual deadline atomically when starting.

## Database and audit boundaries

Migration 0014 creates exam_sittings and sitting_registrations. Composite foreign keys bind sittings to same-tenant publications and registrations to same-tenant memberships and sittings. Both tables force row-level security. Staff can read their own tenant's scheduling records. Candidates can read only their own registrations and registered sittings, with current role/status rechecks. The worker gets no scheduling access.

Runtime grants add only SELECT/INSERT on the two tables. Snapshot triggers reject UPDATE/DELETE even through the migration owner, bind the sitting to the publication policy, validate effective timing and candidate eligibility, and serialize with institution membership mutations. Audit actions exam.sitting_created and exam.candidate_registered append safe empty states, actor, tenant and subject identity in the same transaction. Titles, candidate details and accommodation reasons never enter event snapshots.

Readiness now expects schema 0014, both enabled triggers, forced policies and both SELECT and INSERT privileges. After application migration, run python -m app.manage grant-runtime to extend the existing runtime role. No worker grant expansion is required. A downgrade refuses to discard existing scheduling rows.

## Verification and remaining work

Authoring evidence: 425 unit tests passed with pinned dependencies; dependency coherence, Ruff and offline SQL generation passed. Twenty-seven new PostgreSQL integration cases collect, including rollback on a late batch failure, concurrent retries, candidate SQL visibility, worker denial and missing-grant readiness. Actual PostgreSQL execution is pending in the owner's environment. No unit/offline result is treated as SQL or concurrency verification.

Use the guarded installer from backend. Run --check, install with no flags, then --verify using disposable PostgreSQL. Keep the API stopped and the application database at 0013 until focused tests pass. Then apply 0014, check schema, extend runtime grants and run the full live-media gate. Preserve the local scanner override 23310 and CI default 13310.

Rescheduling/cancellation, registration withdrawal, accommodation amendments, invitation acceptance/delivery, CSV import, coordinator browser workflow and operational readiness checks remain P3 follow-up work. Deadline-extension decisions and actual attempt enforcement remain P4. This package does not close P3-004 or the P3 milestone.
