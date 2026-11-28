# P3-004 in-app candidate invitation inbox and acknowledgement

Requirements SCH-01, TEN-01 and GOV-01. Accepted baseline 51d35c5 passed 943 strict local tests and Foundation gate #18 (run 46121352839) in 13m 43s, with all three PostgreSQL 17/Python jobs and the partial Windows job green on owner evidence. This increment adds authenticated in-app discovery and acknowledgement for existing registered candidates. It does not close P3.

## Discovery and safe timing

An active candidate with exams.take GETs `/api/v1/tenants/{tenant_id}/exam-invitations`. The response contains items, offset, limit, has_more and server_time. Default limit is 25, maximum 100, offset 0-1,000,000. Tenant and candidate ownership are applied in SQL before paging. Order is sitting opens_at, sitting ID, registration ID. A registered user can GET `/exam-invitations/{registration_id}` for the same explicit safe item projection. Another candidate's, unknown or wrong-institution registration is a generic not-found response. Staff use existing staff routes rather than impersonating a candidate inbox.

Registrations are the internal invitation references already created by JSON/CSV import. The inbox includes historical withdrawn, cancelled and closed registrations with their current states; it is not a list of guaranteed available attempts. It shows the same explicit candidate timing/title/reference fields as eligibility, plus current registration_revision/status, acceptance (receipt or null), and can_accept. It never includes private accommodation reasons, marking keys, content, scoring policy, other candidate identities or replacement-link history.

The list captures one database clock value for its page. Latest registration changes, cancellations and acceptances are fetched in bounded bulk queries. Effective allowed duration and terminal-state precedence match the existing eligibility endpoint. Candidate eligibility's existing field allowlist is unchanged, through a shared explicit projection helper. Offset paging is not a frozen snapshot across separate requests. None of these reads reserves an attempt or changes registration/audit/outbox rows.

## Acknowledgement contract

POST `/exam-invitations/{registration_id}/accept` with no body or an empty JSON object. Extra fields, client timestamps, chosen identities and chosen revisions are forbidden. Only the registered candidate can create this receipt; staff cannot accept on someone's behalf.

New acknowledgement requires the candidate's current active membership/user/institution, their own registration, no withdrawal or sitting cancellation, and database time strictly before closes_at. It may be made before opening or during an open window. It records the current registration revision and a server-generated accepted_at, and returns registration_id, sitting_id, registration_revision and accepted_at. A matching retry returns the original durable receipt without duplicate events, including after later amendments, withdrawal, cancellation or close, provided current candidate authority remains valid.

Acknowledgement is optional for BOTH existing and new registrations in this increment. It is an invitation acknowledgement, not consent to unspecified terms, an attempt start, a timer reset, a policy edit or a reservation. Missing acceptance does not newly block can_start. Accepting does not restore withdrawn/cancelled eligibility or freeze future accommodations. Later staff changes update the inbox's effective revision/allowance while the historical receipt retains its accepted revision. P4 must implement and atomically enforce actual attempt-start policy; no delivery-start guarantee is added here.

An admin/coordinator with exams.manage can GET `/exam-sittings/{sitting_id}/registrations/{registration_id}/acceptance` to inspect the receipt, or gets 404 if none exists. The response omits candidate/private marking data beyond existing registration references. Candidate API and SQL remain scoped to their own receipt. Revoked membership hides discovery and blocks retries; an old receipt never restores authority.

## Rescheduling and delivery limits

A rescheduled original stays visible as cancelled with its historical receipt. The replacement and its registrations/acceptances are not copied or exposed automatically; staff must explicitly register the candidate for the new sitting. This preserves withdrawal and accommodation review boundaries. An accepted old invitation does not imply acceptance of a new registration.

No email, secret link, account creation, external invitation acceptance, outbound delivery/fanout or browser inbox has been implemented by this increment. Existing sessions and candidate memberships are required. Candidate/coordinator browser workflows, external delivery/provider configuration, operational acceptance and final P3 closure remain open. The outbox consumer remains local only.

## SQL, audit and concurrency

Migration 0018_invitation_acceptances adds immutable registration_acceptances with a same-tenant registration foreign key and recorded revision. Forced RLS permits current admin/coordinator reads and own active candidate reads; only the matching active candidate can insert. No UPDATE/DELETE/TRUNCATE runtime privileges are added. The SQL trigger binds candidate/sitting/revision to the registration, rejects inactive candidates, withdrawn/cancelled/closed invitations, assigns clock_timestamp() itself, and rejects owner UPDATE/DELETE. Candidate-supplied SQL timestamp values are overwritten by the database, not trusted.

The API and SQL guard lock the institution, serializing acknowledgement with membership, accommodation, withdrawal and cancellation changes. Acceptance/withdrawal either records the acknowledgement first and then withdraws eligibility, or withdrawal first prevents the acknowledgement. Concurrent acknowledgement retries produce one receipt. When amendment and acknowledgement race, the receipt records the valid revision at its serialization point, while current eligibility uses the latest revision.

Receipt, safe-empty exam.invitation_accepted audit record, outbox event and delivery commit atomically. Any business/audit/outbox failure rolls the transaction back; no private state is serialized into snapshots. Readiness expects head 0018, 25 forced-RLS tables and 20 enabled guards, plus separate SELECT and INSERT grants on the new table. Worker access remains forbidden and provisioning rejects acknowledgement privileges on the worker role. Downgrade refuses to discard existing receipts; empty-schema migration round-trip and metadata comparison remain required. Migrations 0001-0017 are unchanged.

## Owner installation and gates

Stop the API. From backend with the project virtual environment run the guarded installer --check, default installation and --verify. Focused tests use random disposable PostgreSQL databases from the configured migration credentials. After passing, apply `python -m alembic upgrade head`, run `python -m alembic check`, then refresh `python -m app.manage grant-runtime`. Run the full PostgreSQL/live-media gate with local scanner override 23310, then commit/push and obtain new remote CI evidence. The installer itself never migrates application data or grants roles. P3 remains in progress until the remaining workflows and acceptance evidence are complete.

## Authoring evidence and owner gate

496 portable tests passed on Python 3.12.14. Repository-wide Ruff lint/format, dependency pins/compatibility, complete collection of 990 tests, and migration SQL bind checks passed. The 16-file installer passed baseline verification, exact payload validation, repeat installation and refusal of modified source without writes. Existing application migrations are unchanged.

These checks do not replace the owner's PostgreSQL 17, Windows and full live-media gate, or CI for the new commit. The existing Starlette/httpx deprecation warning remains non-failing. Do not advance dependent P3 work until the owner full gate and actual new CI are green.

323 distinct real PostgreSQL 16.2 integration tests passed across disjoint 42- and 281-case runs, including all 35 new invitation cases. Coverage includes forced RLS and runtime/worker grants, immutable SQL guards, migration/metadata round trips, current authority, safe projections, rollback, retry and concurrent registration changes. Owner PostgreSQL 17/full live-media verification and new CI remain pending.
