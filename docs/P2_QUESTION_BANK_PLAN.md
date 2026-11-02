# P2 governed question bank — execution plan

Version 1.0, 2 November 2026. This expands P2 within MASTER_ROADMAP.md v1.0; final goal, customer segment and milestone order are unchanged. P1 acceptance is recorded in P1_ACCEPTANCE.md.

## Outcome

An institution's authorized author can create typed question content, assign taxonomy, attach protected accessible media, request independent review and obtain an approved immutable version. Coordinators can select approved versions, and an author can revise a question without altering previously approved or referenced content. Malformed imports, cross-tenant object access and unauthorized changes are rejected. Staff can complete this journey in an actual browser interface before P2 closes.

## Ordered work and acceptance

| Task | Requirements | Deliverable | Acceptance evidence | Dependencies |
| --- | --- | --- | --- | --- |
| P2-001 Content contracts | QBK-01, QBK-02, PUB-01, SEC-01 | Seven tagged schemas, bounded validation, decimal rules, private scoring/rubric fields, recursive candidate-safe projection and content fingerprint | Type-specific rejection tests; nested projection has no keys or marker guidance; changing a key changes the fingerprint; nested validated content cannot be mutated normally | P1-005 |
| P2-002 Persistent question versions | QBK-01, TEN-01, PUB-01, IAM-01, GOV-01 | Question identity, immutable saved version snapshots, tenant composite references, authoring service/routes, migration/grants/readiness updates and concurrency control | Real PostgreSQL: new/upgrade/downgrade, cross-tenant API and direct database denial, prior snapshots unchanged after edits, stale writes return conflict, concurrent version allocation stays unique, audit/outbox rollback with business changes | P2-001 |
| P2-003 Independent review | QBK-01, IAM-01, GOV-01 | Submit, return with reason, approve and retire; actor authority rechecked in transaction | Author cannot approve own work, including dual-role/admin cases; role/membership revocation blocks mutation; concurrent edit/review cannot approve stale content; immutable review decisions and atomic audit; approved-only selection API | P2-002 |
| P2-004 Taxonomy and retrieval | QBK-01, TEN-01 | Institution subjects/topics/outcomes/tags, ownership, paged filters and approved-version retrieval | No cross-tenant references; rename/retire does not rewrite saved historical snapshots; deterministic bounded pagination and permission-filtered search; invalid filters rejected | P2-002, P2-003 |
| P2-005 Protected authoring media | QBK-01, TEN-01, SEC-01, ACC-01 | Private object storage, upload bounds, scan/quarantine states, accessible descriptions, authorized download and immutable content references | Actual storage integration: wrong tenant/role and guessed IDs denied; unscanned/failed/mismatched/oversized uploads unavailable; clean immutable bytes survive later edits; alt text/transcript checks; object failure cannot produce a selectable broken item | P2-002, P2-003 |
| P2-006 Validated imports | QBK-01, QBK-02, TEN-01, GOV-01 | Explicit internal JSON profile, preview/error report, atomic draft import and retry contract | Invalid rows or foreign assets create no partial import; privileged status/owner/version fields rejected; exact retries return original outcome; changed payload/key conflicts; bounded request and item limits; safe error locations without keys in logs | P2-003, P2-004, P2-005 |
| P2-007 Authoring UI and preview | QBK-01, QBK-02, IAM-01, ACC-01 | Journey prototype then institution shell, question list/editor, review queue, history, media and import controls, candidate-rendering preview | Actual browser author → reviewer → coordinator journey for all seven types; preview hides keys; keyboard/error recovery and narrow-screen checks; stale edit recovery; staff-only notes clearly separated; secrets absent from candidate preview traffic | P2-003, P2-004, P2-005, P2-006 |
| P2-008 Milestone acceptance | QBK-01, QBK-02, TEN-01, PUB-01, SEC-01, ACC-01, GOV-01 | Regression, two-tenant adversarial checks, release evidence and documented limitations | Full PostgreSQL and storage checks, all CI jobs, actual browser journey; pinned approved version remains byte-equivalent after new revision; malformed imports and unauthorized media access rejected; final P2 checklist recorded | P2-007 |

Task order does not imply a delivery date. Implement bounded increments; update BACKLOG.json, PROGRESS.md and evidence after each one. Backend-only completion cannot close P2. P2-004 and P2-005 can be developed independently after their prerequisites pass.

## Content and version rules

P2-001 defines `question-content.v1`: single choice, multiple select, numeric tolerance, short answer, essay, file upload and passage group. All text is plain text. Later rendering must escape it; the validator is not an HTML sanitizer. Markdown/HTML, arbitrary regular expressions, executable question scripts and code execution are unsupported. Rich media references enter through P2-005 with an explicit compatible schema/version decision, not by silently changing existing fingerprints.

Use one Question identity with immutable saved QuestionVersion content snapshots. Every accepted save creates a new snapshot; a mutable draft pointer and revision token locate current work. A save requires the current revision token, and stale writers receive a conflict rather than overwriting work. Database guards must protect immutable content even if service code is bypassed by the restricted API role. Freeze content, point values, rubric and relevant taxonomy/media references; approval and retirement are separate controlled records/transitions. A fingerprint is not an authorization check, signature or substitute for a foreign key.

Approval addresses an exact version/hash, not "the latest question." An edit to a reviewed or approved version creates a new draft; previous approval never transfers. P3 will freeze selected version identities and exam policies in publication snapshots. P2 must demonstrate historical stability through persisted version references; actual published-exam behavior is verified again in P3.

## Review and role boundaries

| Role | Question-bank access to implement |
| --- | --- |
| Institution administrator | Manage the institution bank and review others' content; cannot approve own authored work |
| Author | Create/revise own drafts, see own history and review feedback, submit own versions |
| Reviewer | Read submitted versions and their private marking material; approve or return others' work |
| Coordinator | Read/select approved, non-retired versions; no draft secrets or authoring authority from coordinator role |
| Candidate, invigilator, examiner | No general question-bank access from these roles |

These are service permissions to be implemented, not a claim that current routes already enforce them. Admin authority does not bypass independent review. The originating author is retained across revisions; reassignment cannot erase authorship for self-review checks. Authorized read projections differ between staff authoring, approved selection and candidate preview. Tenant identity comes from verified membership; missing/foreign IDs must not become an existence oracle. Any future collaboration or ownership-transfer workflow needs explicit permission and self-review tests.

Workflow: draft → in review → approved → retired; in review → returned draft with recorded reason. Submitted/approved content itself stays frozen. Review records are append-only; status/pointers use a revision fence. Retirement prevents new selection but preserves historical references. Cross-tenant access and permission revocation must be checked in both normal and concurrent mutation paths.

## Point and marking rules

P2-001 uses positive decimal points with at most two fractional digits. Numeric expected values/tolerances have up to 18 total digits and six fractional digits; tolerance is inclusive absolute tolerance, initially nonnegative. Multiple select initially declares all-or-nothing scoring. Short answers explicitly use NFKC, optional case sensitivity and whitespace normalization; no fuzzy/AI matching. Manual items require criterion totals equal to item points and private marker guidance. Passage groups contain bounded non-nested leaf items and sum child points.

These define content intent, not an implemented grading engine. P3 must freeze exam weighting/negative/unanswered/rounding policy; P5 implements and validates score calculations, manual marking and corrections. Relative tolerance, alternative partial-credit rules and richer rubric scales require explicit contract extension and tests before use. Limits are engineering defaults, not commercial quotas.

File-upload content defines permitted response formats and limits only. P2-005 secures authoring media. Actual candidate response upload, accepted-answer persistence and scan/evaluation behavior belong to P4/P5 and must not be claimed complete from this schema.

## Media, import and UI gates

Private media uses opaque server-controlled object keys, immutable checked bytes, tenant ownership, scan state and accessible descriptions. No public bucket or trust in a client-provided MIME/extension alone. Any signed read URL has short expiry and is issued only after current authorization; it must not become a general object-listing credential. Scanner/storage choices will be pinned and verified during P2-005. No unverified infrastructure reuse from other applications.

Imports first target our documented JSON profile, not unimplemented QTI/LTI compatibility. QTI/LTI remains P7. Imported questions become drafts only, use normal content validation, reference authorized clean media and cannot set tenant/approval/audit authority. Preview performs no business writes. Invalid batch commit is atomic; allowlisted audit records carry IDs and safe state/hash metadata, never scoring bodies or raw uploaded rows.

The UI uses the intended Next.js/TypeScript stack after the journey prototype; actual dependency versions are selected and verified when frontend implementation starts. Preview uses the allowlisted content projection and the same eventual candidate renderer. Clear draft/review/approved/retired state labels, keyboard controls, accessible media and visible unsaved/conflict handling are required. No credentials or private keys in local-storage debug dumps or client logs.

## P2 exit checklist

- All seven types pass authoring, persisted-version, review and preview journeys.
- Submitted/approved/used content and media remain unchanged after subsequent revisions.
- Two tenants cannot reference, discover or download each other's content/assets.
- Self-approval, stale approvals and unauthorized grants are denied, including concurrent cases.
- Audit/outbox commits atomically with mutations and never stores keys or raw content.
- Invalid/retried imports have deterministic, atomic outcomes.
- Fresh schema/grant/readiness checks, full test suite and actual CI pass on the release commit.
- Browser journey, keyboard/error recovery and media accessibility evidence are retained.
- Known gaps are recorded; no production-readiness or P3 examination-publication claim is inferred.

## First implementation boundary

P2-001 is accepted with local PostgreSQL and correct remote CI evidence in LOCAL_VERIFICATION_P2_001.md. P2-002 is accepted at e18af0c; source 0.8.0 implements P2-003 review/approval/retirement and awaits its own PostgreSQL/CI gate. There is still no protected media, frontend or grading engine. Follow BACKLOG.json and PROGRESS.md for current task status; this plan retains the original task order.
