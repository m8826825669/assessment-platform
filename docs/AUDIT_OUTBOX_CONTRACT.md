# Audit outbox and API problem contract

Requirement references GOV-01, INT-01, IAM-01 and TEN-01. Version 0.4.0 uses migration 0003_audit_outbox. This is a foundation capability; no external transport, frontend or general platform-owner console is delivered.

## Transactional audit

Current identity and membership services retain their legacy security events and additionally stage an audit record, immutable event envelope and pending delivery. The helper flushes but never commits. The calling business operation owns the transaction. Failure to append any part rolls back the business change and its audit/outbox records. Rate-limit reservation counters are a separate admission-control transaction; they are not a successful login event.

An audit record contains action, actor kind, actor user UUID or operator database principal, optional subject UUID, tenant scope, timestamp, request UUID and explicit before/after state. Membership snapshots permit only role, status and user UUID. Other registered actions normally have empty snapshots. Requeue permits status, attempts and a fixed reason code. Unknown actions or snapshot fields fail closed. Passwords, hashes, tokens, emails and arbitrary request bodies are not valid snapshot fields.

GET /api/v1/tenants/{tenant_id}/audit supports offset and limit up to 200, ordered by timestamp and UUID descending. Only the institution administrator has audit.read in this version. Application checks and forced row policies scope history. Global identity audit is not exposed through the tenant API. A trusted migration owner can inspect global history. Runtime cannot update, delete or truncate audit records. This is not a claim of cryptographic sealing or WORM compliance against the database owner.

Existing security_events are preserved. The migration does not fabricate historical before/after snapshots or backfill a delivery queue for old events. PostgreSQL role provisioning is infrastructure administration, distinct from the application identity/membership ledger.

## Immutable envelope and mutable delivery

| Table | Purpose | API access | Worker access |
|---|---|---|---|
| audit_records | Sanitized business/security history | INSERT and scoped SELECT | None |
| outbox_events | Versioned immutable envelope | INSERT | SELECT |
| outbox_deliveries | Lease, attempts, status and last safe error code | INSERT | SELECT and bounded state-column UPDATE |
| consumer_receipts | Unique consumer/event receipt and payload digest | None | SELECT and INSERT |

The event and its audit share a non-null scope_key. A composite foreign key enforces the match, including global identity events whose tenant UUID is null. Each audit has at most one envelope. Queue job and receipt IDs reference existing events. Four new tables have forced row security; SQL grants separately distinguish producers from consumers.

Event type audit.recorded.v1 contains schema_version, event and audit UUIDs, tenant/subject/request UUIDs, action and approved before/after state. The worker validates the payload against the immutable envelope before processing. It never deserializes executable code or loads user-supplied handlers.

## Processing and failure semantics

Claims use row locks with SKIP LOCKED. The claim transaction increments attempts, assigns a new random lease token and expiry, then commits. The processing transaction locks the delivery again, checks token and expiry, writes the handler's local database effect and records delivery success together. An expired token cannot acknowledge a newer claim. Expiry during processing rolls back the local effect.

The built-in handler writes a unique audit_receipt_v1 receipt per event with a canonical payload hash. Repeated processing with the same payload keeps one receipt; a hash mismatch is a permanent failure. This proves idempotence for that local transactional effect. It does not guarantee exactly once execution for arbitrary external services.

Failures roll back handler effects before rescheduling. A delivery has five attempts by default. Transient retries use exponential delay, capped at one hour. Expired claims are recoverable. Exhausted claims and permanent contract failures become dead jobs. Only stable failure codes are stored; raw exception text is not persisted. Requeue requires an explicit operator action and fixed reason code; its audit and new event commit with the reset. The worker never automatically replays delivered jobs or overwrites receipts.

No external email, Slack, SMS, payment or webhook call occurs. Future external adapters must define idempotency and acknowledgement semantics for the destination, with bounded network timeouts and appropriate secret isolation. Long-running handlers need a separately reviewed lease/heartbeat policy; this release supports a short local database consumer only. General attempt history, retention jobs, alerting, supervision and capacity evidence remain later operational gates.

## API problems

Exception responses follow RFC 9457 using application/problem+json. Fields are type, title, status, detail, instance, code, request_id and errors. Validation errors contain only location, code and a generic message. They omit supplied input and exception context. The instance is a request URN, not a URL containing caller-supplied data. X-Request-ID is server generated and correlates responses, audit records and safe diagnostic logs. Callers cannot override it with a request header.

HTTP authentication headers are preserved; throttling includes a conservative Retry-After window. Unknown routes, wrong methods, validation, authorization, conflicts, database failures and unexpected server exceptions use the same envelope. Logs identify request UUID and exception class without printing exception messages, request bodies, tokens or connection strings. Dependency readiness 503 is intentionally a diagnostic Readiness model rather than an exception problem. OpenAPI documents both shapes.

This changes error access from detail.code in 0.3.0 to top-level code in 0.4.0. Login success tokens, institution and membership success payloads and readiness fields are otherwise preserved.

## References

PostgreSQL SELECT locking and queue consumers: https://www.postgresql.org/docs/current/sql-select.html
Problem Details for HTTP APIs: https://www.rfc-editor.org/rfc/rfc9457.html

## Current delivery boundaries

There is one delivery state per event and one built-in consumer. Independent destinations/fanout, per-consumer retry state and ordered aggregate streams are not implemented. Parallel queue processing does not guarantee global or per-institution event order. The current receipt effect is order-independent. Extend the delivery model and introduce required sequencing before adding consumers whose correctness depends on ordering or independent delivery schedules.
