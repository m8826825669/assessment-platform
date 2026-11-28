# P3-004 bounded CSV registration import

Requirements SCH-01, TEN-01 and GOV-01. Baseline e7fae39 is accepted on owner evidence: 842 full local tests passed with live storage/scanner, and Foundation gate #16 (run 46107461594) succeeded in 9m 43s across the three PostgreSQL 17/Python jobs and partial Windows job. A prior isolated fixture-login 503 did not reproduce in the seven-test publication-access diagnostic or the final full run; its original cause remains unconfirmed. No retry, timeout or permission relaxation was introduced.

## CSV profile

The CSV registers existing active candidate accounts in the current institution; it does not create users, memberships or external invitations. Send raw UTF-8 bytes as text/csv, optionally with charset=utf-8. A UTF-8 BOM is accepted. No multipart upload, JSON wrapper, alternate encoding or query parameter is accepted. Maximum body size is 65,536 bytes, checked against Content-Length and incrementally while streaming. At most 50 data records are accepted; larger imports must use separate explicit batches.

The header has these four columns in this order (surrounding whitespace is normalized):

```csv
id,candidate_user_id,extra_minutes,accommodation_reason
```

id is a caller-generated registration UUID, generated once and retained across retries. candidate_user_id is the existing account's UUID, not an email, display name, question ID or membership ID. Data cells are trimmed. UUIDs are normalized; duplicate registration IDs or candidate UUIDs in one file fail. Blank extra_minutes becomes 0; otherwise use a plain ASCII integer from 0 to 240, without signs, decimals or leading zeroes. A positive allowance needs a trimmed reason of 3-500 characters; zero must have a blank reason. Standard quoted commas and embedded newlines in reasons are supported.

Empty files/header-only files, blank data records, wrong/duplicate/reordered headers, extra/missing cells, invalid UTF-8/NULs, invalid UUIDs, malformed quotes, duplicate IDs/candidates and excess records are rejected. Diagnostics contain only a stable code, known column and logical CSV record number (header=1, first candidate=2). A quoted multiline field is still one logical record. No raw cell or private reason is included in diagnostics. Parsing stops at the first structural/field error; correct it and preview again.

## Preview and commit

Staff with exams.manage POST the bytes to `/api/v1/tenants/{tenant_id}/exam-sittings/{sitting_id}/registrations/csv/preview`. Transport/authentication errors use the normal problem response. Parsed or registration-policy errors return HTTP 200 with valid=false and bounded diagnostics. A structural error has row_count=null; otherwise row_count is the parsed count. rows contains successfully checked row numbers, status=new/replayed, original receipt allowed_minutes, registration_status, registration_revision and effective_allowed_minutes. Counts identify only checked rows; valid=false always means do not commit yet. For replay rows, the effective fields distinguish later accommodation decisions or withdrawal from the immutable original receipt. The preview never echoes the CSV, UUID cells or reasons.

Preview performs no registration/audit/outbox mutation or reservation. Candidate state, sitting state, permissions and timing can change afterwards; a successful preview is not permission to start an exam and does not override a withdrawn registration or cancelled sitting. Existing eligibility/status APIs remain authoritative for participation.

POST the same bytes to `/registrations/csv` to commit. The result is the existing staff registration receipt list in CSV order. Parser errors use the normal 422 problem envelope with safe body/record/column locations. Registration-policy conflicts keep the existing JSON route's status semantics. Every row is validated before adding any business rows. Commit takes the existing institution lock and rechecks current authority, active candidate membership, accommodation window, cancellation and the database clock. The SQL registration guards and forced tenant policies remain authoritative.

Original per-row registration IDs provide durable retries, matching the JSON contract. Exact normalized replay acknowledges the original creation record without duplicate audit/outbox, even after opening, cancellation, withdrawal or later accommodation changes. That never reactivates or amends a registration. Changed existing-ID content, a different ID for an already-registered candidate or any invalid new row rejects the batch without partial writes. Mixed old/new rows are supported: existing receipts remain unchanged and all new rows commit atomically. Preserve the same CSV and IDs after an uncertain network outcome; do not regenerate IDs. There is no new actor-bound batch receipt or retained source document in this increment.

## Boundaries and verification

Authorization and sitting visibility are checked before consuming upload bytes, then the read transaction is rolled back so no transaction is held while waiting for the stream. Preview/commit recheck authority afterwards; commit serializes under the existing institution lock. The JSON route and CSV route share side-effect-free planning and atomic persistence functions. Existing JSON response/replay semantics, safe audit action exam.candidate_registered and SQL policies are unchanged. Preview does not reserve time or lock the sitting against later staff changes. PostgreSQL/storage errors remain genuine 503 failures rather than being reported as valid=false.

Schema head remains 0016_registration_changes. No migration, model, runtime/worker grant, media configuration or dependency-lock change is required. No outbound message or external side effect is introduced. This is an API increment; CSV selection/upload controls in the coordinator browser, invitation acceptance/delivery, rescheduling, full P3 acceptance and actual P4 attempt enforcement remain open.

Use the guarded installer from backend with the active virtual environment: --check, default installation, --verify. It backs up sources and tests only random disposable databases using configured migration credentials. Stop/restart the application to load changed routes, then use the standard full PostgreSQL/live-media gate and obtain new CI evidence before the next dependent task. Do not apply an invented 0017 migration or widen database privileges for CSV support.

## Authoring evidence

Pinned Python 3.12 portable suite: 473 tests passed. Real disposable PostgreSQL 16.2 over TCP: 130 scheduling/CSV/schema cases and a disjoint 121 upload-authority/identity/audit/question-version/publication-access cases passed, for 251 distinct integration tests. All 22 new CSV cases passed, including no-write preview, row diagnostics, JSON/CSV receipt compatibility, mixed replay/new rows, audit/outbox rollback on the second candidate, concurrent retries, changed state after preview, revoked staff access during the body stream, withdrawn/cancelled historical replay, content-type and byte-stream limits, and tenant/role denial. All seven publication-access cases passed unchanged. Schema metadata and empty migration round-trip checks passed at unchanged head 0016.

Dependency compatibility/pins, repository Ruff lint/format, clean diff and the guarded installer's exact-baseline/payload/replay/drift checks passed. Full collection is 895 tests, which is not a full-run claim. The existing TestClient/httpx warning remains non-failing. Owner PostgreSQL 17/full live-storage/scanner verification, browser acceptance and new CI remain pending. No application database or live candidate data was used.
