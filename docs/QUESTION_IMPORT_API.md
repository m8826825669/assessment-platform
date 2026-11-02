# P2-006 question import contract

Requirements QBK-01, QBK-02, TEN-01, GOV-01. Source/API 0.11.0, schema 0008_question_imports. This implements the internal JSON profile assessment-question-import.v1. No QTI/LTI/CSV/Excel adapter, asynchronous import worker or browser import interface is claimed.

## Document

Use Content-Type application/json with UTF-8 (optional BOM). See QUESTION_IMPORT_EXAMPLE.json for all seven synthetic types and QUESTION_IMPORT_SCHEMA.json for the JSON Schema. Each document requires schema_version and 1–50 items. Every item contains a distinct lowercase token reference (maximum 64), title, validated content, optional taxonomy_ids and optional media_ids. The row shape reuses the normal question-create contract. No tenant/user/question/version identifiers, update revisions, approval/status or arbitrary media URLs may be supplied. Imports create new revision-one drafts only.

Limits: 2 MiB actual request bytes, 50 rows, maximum 16 total media attachment references across the whole batch (occurrences, not distinct assets), existing per-question taxonomy/media bounds, at most 64 JSON nesting levels. Empty/malformed/nonfinite/duplicate-property JSON and invalid UTF-8 are rejected; JSON property order/spacing does not create separate semantics. Numeric points/tolerances use the normal decimal-string/integer rules, never floats. No raw import file is persisted. Existing typed content.v1, candidate projection and fingerprint schema are unchanged.

Example outline:

```json
{
  "schema_version": "assessment-question-import.v1",
  "items": [
    {
      "reference": "math_question_1",
      "title": "Simple addition",
      "content": {
        "kind": "numeric",
        "item_id": "addition",
        "prompt": "What is 2 + 2?",
        "points": "1",
        "expected": "4"
      }
    }
  ]
}
```

## Routes

Base `/api/v1/tenants/{tenant_id}/question-imports`. Bearer authentication and current admin/author question-write permission required. Reviewer/coordinator/examiner/invigilator/candidate have no import authority. Body intake checks live permission before streaming and releases its read transaction; mutations acquire the same institution lock as existing authoring/membership changes and recheck live session/role.

| Method | Path | Result |
| --- | --- | --- |
| POST | base/preview | Validate content/local active taxonomy/owned clean and retrievable media; return safe candidate previews and counts; no business/audit/outbox writes |
| POST | base | Require Idempotency-Key UUID header; atomically create all drafts and immutable success receipt; 201 first success, 200 replay |
| GET | base/{batch_id} | Read your own success receipt under current import authority |

Preview returns schema_version, valid=true, item_count and rows (index, reference, title, taxonomy_count including implicit subject parents, media_count and allowlisted candidate preview). Private keys/rubrics/marker guidance are excluded. Intrinsic validation errors provide safe field paths; unknown field names are redacted, input/context values omitted, maximum 100 field errors. Reference errors fail with the same generic missing/foreign response as normal authoring; a preview may stop at the first such reference error. Preview is advisory, not a reservation/approval capability. Commit does not require preview and validates again through the same draft-save paths. Concurrent catalogue or storage changes may invalidate an earlier preview.

Commit response: batch_id, schema_version, created_at, created_as=draft, item_count and items [{reference,question_id,version_id}]. The receipt describes the ORIGINAL creation; created_as is not live workflow state after later edits/reviews. Use normal question/history endpoints for current details. The response contains no private content, body fingerprints, storage coordinates, actor credentials or idempotency key.

Every row uses existing question/content/reference validation, ownership, automatic subject-parent closure, immutable snapshots and per-question audit/outbox. Receipt and one batch audit/outbox event commit with all rows in one SQL transaction. A later row failure, bad reference, unavailable object, expired session, receipt failure or audit/outbox failure rolls back all new rows and the key. Nothing is partially imported and no existing question is edited. Imports never scan/upload media or create taxonomy; those resources must already be valid. No inherited approval or self-review bypass.

## Retries and receipt scope

Use a fresh random UUID key for one intended batch and KEEP that key through timeouts/retries. Scope is institution + originating user + key, across that user's sessions. Another user or institution using the same key is an independent namespace. Even admins cannot retrieve another actor's private import receipt via this module. Admin question-bank authority itself is unchanged.

A successful replay with an equivalent typed document returns exactly the original receipt/IDs/time, with 200 and no new question/audit/outbox rows. Changed valid payload under an already-successful key returns 409. Invalid documents fail validation before replay lookup. Failure does not consume a key. A different key intentionally creates a new import, even for identical content. There is no global deduplication, import-update or receipt expiry workflow in this increment.

The request fingerprint binds profile, item order, client references, exact title, v1 canonical content fingerprints and sorted taxonomy/media UUIDs. JSON whitespace/property order, decimal spellings already equivalent under content.v1, explicit default values and reference-array order are retry-equivalent. Row order is significant. The server stores the fingerprint and IDs, not the raw uploaded request. Do not treat a fingerprint as an authorization capability or digital signature.

Replay after success does not revalidate retired references or read storage again: it acknowledges prior durable creation and never creates replacements. Normal subsequent question use/preview/review/selection/download continues enforcing current media availability and exact stored versions. Import receipts do not promise ongoing object availability. Every retry still checks current permission and live session first.

## Database and operational boundaries

question_import_receipts is immutable, forced-RLS and actor/tenant scoped. Runtime has SELECT/INSERT only; worker has no receipt data grants. The insert guard validates exact result key shape, unique references/question/version IDs and binding to owned, unreviewed revision-one versions created in the same transaction. JSON ID references are checked by the trigger; existing immutable version retention prevents later ordinary deletion. The guard is not an independent proof of a semantic upload hash against malicious application code or a privileged database owner.

Batch audit action question.import_committed allows only batch UUID/item_count. Each normal question.created record retains its existing safe version/hash metadata; client references, keys, titles and raw scoring content never enter batch audit/outbox. Worker handles the registered safe event using its existing local receipt consumer; no external delivery is added.

The initial batch is deliberately bounded/synchronous and serializes mutations per institution. No production throughput, cross-request snapshot consistency, capacity/quota or unlimited bulk-upload promise is made. Operational errors/timeouts can leave the client uncertain about an ACK; retry the SAME key after connectivity recovers. The database receipt provides durable business idempotency, not exactly-once network delivery. No new dependencies, storage provisioning or accepted migration edits are introduced.
