# Identity and tenant contract

Requirements: IAM-01, TEN-01, SEC-01. Migration: 0002_identity_tenancy. API prefix: /api/v1.

| Method | Path | Authorization and effect |
|---|---|---|
| POST | /auth/login | JSON email and password; returns opaque bearer token and lifetime |
| GET | /auth/me | Active unexpired session; returns only own basic identity |
| GET | /auth/institutions | Active session; returns up to 200 own active institution memberships |
| POST | /auth/logout | Revokes current session |
| POST | /auth/change-password | Checks current password, sets new hash, revokes all sessions |
| GET | /tenants/{id}/access | Active institution membership; returns current role and permissions |
| GET | /tenants/{id}/memberships | Institution administrator; offset/limit pagination |
| POST | /tenants/{id}/memberships | Institution administrator; enroll an existing user UUID with one institution role |
| PATCH | /tenants/{id}/memberships/{membership_id} | Institution administrator; role/status changes with last active administrator protection |

Passwords use Argon2id with explicit parameters. Sessions are random 256-bit secrets; only SHA-256 digests are stored. This increment intentionally uses opaque revocable sessions rather than JWT. Tokens are sent through Authorization: Bearer, never query strings. There is no cookie authentication yet, so browser cookie/CSRF integration is not claimed.

Login identifiers are normalized; passwords are not trimmed. Password creation requires 15 to 1024 characters. Account and direct peer IP throttling uses persistent atomic counters. Failed, unknown and inactive-user logins have the same credential error. Throttle budgets commit before hashing, so shared IP bucket locks do not serialize expensive password checks. All token, identity and error responses are marked no-store. Validation errors omit supplied input so passwords are not reflected.

Each request resolves the session and active user. Each institution request rechecks active institution membership and current role. Tenant IDs in the route select the requested resource; they do not establish permission. Row policies use transaction-local context, and connection reuse must not retain tenant scope. Missing or foreign institution membership returns 404; insufficient permission within a valid membership returns 403. Invalid session returns 401; throttling returns 429; last administrator conflict returns 409.

| Role | Core permissions |
|---|---|
| admin | Institution administration, membership management, author/review/exam/evaluation/result permissions |
| coordinator | Exam management and result publication |
| author | Question authoring |
| reviewer | Question review |
| invigilator | Invigilation |
| examiner | Script marking |
| candidate | Own assessment participation and own results |

All roles include basic institution access. Question, exam, evaluation and results permissions are reserved contracts; those business routes do not exist yet. The role matrix alone is not proof of future route enforcement. A user can hold different roles in different institutions; one role is assigned per membership in this version. Custom roles and department-level scoping remain later IAM extensions.

The shared runtime account is a trusted server credential, not a credential distributed to institution users. It can read global identity records required for login; tenant row policies govern the institution-owned tables. The API and its verified context binding enforce user authority. A database actor with arbitrary SQL and server credentials can change custom PostgreSQL settings, so this design does not claim containment of arbitrary SQL execution. All application queries are parameterized; no API accepts raw SQL. Migration credentials remain an exceptional operator capability outside API handlers.

The API rejects superuser, BYPASSRLS, owner, role-management, database-creation, inherited-role and schema-creation authority at transaction boundaries. Runtime grants allow password hash updates for authentication, session/throttle operations, tenant membership operations and security-event inserts. Runtime has no SELECT, UPDATE or DELETE privilege on security events; the migration owner can inspect them. General audit details, outbox delivery, distributed retention, support delegation and complete incident controls are P1 004 and later operational work.

Known limits: no public registration, email verification, MFA, email recovery, session listing, refresh flow, browser client, SSO, tenant creation API or general platform-owner console. Institution suspension denies current institution access now; production suspension handling for running exams must be defined with P4 before launch. Login buckets and expired sessions require a retention/cleanup job before production. Rate limits and proxy settings require load and deployment review at P6.

## Version 0.4.0 extension

P1 004 adds GET /tenants/{id}/audit for administrators, detailed snapshots and outbox jobs written in the same transaction as current identity/membership actions. Exceptions use top-level code/request_id in RFC 9457 problem responses instead of detail.code. See AUDIT_OUTBOX_CONTRACT.md and the current upgrade guide. The earlier P1 003 requirement statements above describe the original identity increment; P1 004 is now implemented but awaiting local acceptance.
