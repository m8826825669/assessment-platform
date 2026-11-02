# Persistent draft question API — P2-002

Historical draft-release contract. Source 0.8.0 adds workflow state/review_revision and dedicated review/selection routes described in QUESTION_REVIEW_API.md; current head is 0005_question_review. Private draft routes remain author/admin only. The limitations below describe the original 0.7.0 release.

Requirements QBK-01, TEN-01, PUB-01, IAM-01, GOV-01. API/source release 0.7.0. This increment implements saved drafts, not review/approval, retirement, taxonomy, media, imports, exam publication or grading. All new routes require a current bearer session and active institution membership. Successful and problem responses use Cache-Control: no-store.

Base path: `/api/v1/tenants/{tenant_id}/questions`.

| Method / suffix | Behavior |
| --- | --- |
| POST base | Create question identity and version 1; 201 |
| GET base | List current versions as metadata; offset 0–1000000, limit 1–200, default 100 |
| GET /{question_id} | Current saved content plus current revision fence |
| POST /{question_id}/versions | Append a full new snapshot with expected_revision; 201 or 409 |
| GET /{question_id}/versions | Version metadata, newest first; same pagination bounds |
| GET /{question_id}/versions/{version_id} | Exact immutable version content plus the question's current revision fence |
| GET /{question_id}/preview | Candidate-safe projection of current content, or exact version_id query parameter |

## Permissions and response privacy

Institution administrators can author/read all institution drafts; authors can author/read only identities they originally created. Admin edits retain the originating created_by and record the actual editor as authored_by on the new version. Other authors get the same 404 for foreign and nonexistent question/version identities. Cross-institution paths require membership and do not disclose questions. Candidate/coordinator/reviewer/examiner/invigilator roles have no saved-draft bank access in this increment. Reviewers and approved-only coordinator selection arrive in P2-003; do not broaden draft access ahead of that gate.

Detail responses intentionally include private authoring keys/rubrics and a content hash, and are restricted to authorized authoring staff. List/history metadata excludes content. Preview calls the recursive public-content allowlist and includes only question_id, version_id and public content; it omits hashes, keys, tolerances, private rubrics and guidance. Preview is still a staff-only API helper, not a public candidate endpoint or a delivered browser renderer.

## Input

Creation body (synthetic example):

```json
{
  "title": "Example addition",
  "content": {
    "kind": "single_choice",
    "item_id": "addition_one",
    "prompt": "What is two plus two?",
    "points": "1",
    "options": [{"id": "a", "text": "Four"}, {"id": "b", "text": "Five"}],
    "correct_option_id": "a"
  }
}
```

A revision supplies the entire new title/content plus the integer `expected_revision` from a current GET. Tenant IDs, authors, version numbers, approval/status and hashes are server-controlled and rejected as input fields. Missing fields, invalid content and invalid pagination use safe 422 problem details. Titles are nonblank plain text capped at 200 characters; content rules remain question-content.v1.

A successful detail contains question_id, version_id, version_number, title, schema_version, content_hash, authored_by, created_at, state=draft, tenant_id, created_by, revision, and content. On historical detail, version_number identifies that saved snapshot while revision is the question's current edit fence. GET history/list are bounded arrays, not total-count reports. Question listing orders by identity creation time/id; history orders by descending version number. Concurrent creates may shift offset pages; snapshot-consistent pagination/search is not claimed here.

## Persistence and consistency

`questions` retains stable UUID/tenant/originating-author/creation-time and a positive revision. `question_versions` retains immutable UUID, scoped question reference, monotonically allocated number, title, schema version, validated JSONB content, content fingerprint, editor and server creation time. Composite foreign keys prevent cross-tenant parent links. A deferred composite current-version FK makes a dangling committed pointer impossible. The current revision is also the edit fence; there is no approval pointer yet.

Each accepted save creates a new version, even if content is unchanged. Revision updates may advance by exactly one; missing-snapshot commits and revision jumps fail. Application and database serialize on the question identity; the first implementation also takes the institution lock used by membership administration, so authority is rechecked after waiting. This intentionally serializes authoring mutations within an institution; it is not a capacity claim. Session revocation/user activity and actual clock expiry are checked again after acquiring that lock. An authorization decision is a point-in-time check, not a claim that arbitrary revocations after that check retroactively cancel a commit.

The original content fingerprint algorithm stays question-content.v1 and covers the typed content body, including marking secrets. The separately immutable title is not part of that body fingerprint; question/version identity and version number distinguish title-only revisions. Title history is still retained. A content hash is not a signature, approval or proof against a database owner.

Saved versions reject UPDATE/DELETE via privileges, row policies and a trigger. Root identity fields cannot be edited through granted columns, and a trigger rejects their alteration and deletion. Runtime has no DELETE/TRUNCATE/schema rights. Semantic item validation occurs in the application; DB checks enforce structure/version format and relationships, not the entire Pydantic rule set or hash recomputation. The database owner can deliberately disable/replace guards; this is not tamper-proof storage. Database credentials remain private server capabilities, not user credentials.

Readiness requires head 0004_question_versions, both new tables, all nine forced-RLS tables, enabled immutable guards, new API grants and separate worker privileges. It rejects unsafe/missing runtime rights and grants that would permit snapshot rewriting. Migration updates never run automatically on application startup.

## Audit, retries and errors

Create/revise use one transaction for identity pointer, version, audit record, immutable outbox event and pending delivery. Audit actions are question.created and question.revised. The only question state fields allowed in audit/outbox are version_id, revision and content_hash; no title, prompt, choices, marking key, rubric, token or raw request is copied. The existing local receipt worker consumes these safe envelopes and never receives question-table access.

A stale expected_revision returns 409 `question_conflict`; reload and reconcile your edits. Missing/foreign question/version IDs return 404 `question_not_found`. A rolled-back constraint conflict also returns the generic 409 message without SQL details. Unsafe database configuration and SQL failures retain the generic 503 problem contract. Request UUID correlation is preserved.

Revision writes are optimistic concurrency operations, not transparent idempotent replay: retrying a committed revision with its old fence returns 409 and does not append another version. Initial POST has no idempotency key in this increment; after an uncertain create response, inspect the bank before manually retrying. Import idempotency belongs to P2-006. No hard delete, custom-role transfer, review bypass or publication route is provided.

## Acceptance

Actual PostgreSQL coverage is included for all seven types, historical reads, concurrency/stale edits, role and session revocation after lock waits, tenant/author boundaries, direct database denial, immutable guards, malformed input, transaction rollback after delivery insertion failure, P1-data upgrade preservation, new-grant/guard readiness and local worker receipt processing. The authoring workspace cannot execute PostgreSQL here; these tests must pass in the owner's strict local run and new CI before P2-002 is accepted. Unit and SQL parsing evidence is not substituted for those results.
