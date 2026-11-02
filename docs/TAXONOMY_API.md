# P2-004 taxonomy and retrieval contract

Requirements QBK-01, TEN-01, GOV-01. API/source 0.9.0, schema 0006_question_taxonomy. Authenticated JSON APIs; browser interface follows in P2-007.

## Catalogue

Base `/api/v1/tenants/{tenant_id}/taxonomy`.

| Method | Path | Permission | Behavior |
| --- | --- | --- | --- |
| POST | base | admin | Create active revision-one term |
| GET | base | admin/author/reviewer/coordinator | Paged catalogue, optional kind, state (default active) |
| GET | base/{term_id} | same four staff roles | Current term including retired state |
| PATCH | base/{term_id} | admin | Change label and/or retire with expected_revision |

Create JSON: `{"kind":"subject","code":"math","label":"Mathematics"}`. Kinds subject/topic/outcome/tag. Topic requires parent_id of an active local subject. Other kinds have no parent. Code is lowercase ASCII letter followed by letters/digits/_/- (maximum 64), unique per institution and kind. Label is nonblank plain text, maximum 200. Identity, code, kind, parent and creator cannot change. No delete/reparent/reactivation route. Retire active topics before their subject. Duplicate/stale/conflicting changes return 409. Foreign/missing object references return generic 404.

PATCH example: `{"expected_revision":1,"label":"Updated label"}`; retirement uses `{"expected_revision":2,"state":"retired"}`. All mutations atomically append allowlisted audit/outbox metadata (IDs/state/revisions only). Private labels/codes are not audit snapshots. Catalogue read does not grant draft/private-question access.

## Saved classifications

Question create and full revision payloads accept `taxonomy_ids`, an array of distinct local active term UUIDs. Maximum 64 INCLUDING automatically added subject parents for topics. If omitted, classification is empty; revision is a replacement, not a patch or implicit copy. Send desired existing IDs again to retain them. Retired references cannot be attached to a new version. Parent closure over 64 returns 422 atomically.

Metadata, history, review and approved selection responses add `taxonomy`: ordered snapshots `{id,kind,code,label,parent_id,revision}`. These contain the label/code/term revision at save time. Rename/retirement cannot rewrite history or an approved selection. Changing classification requires a new question version, fresh review and a new version_id. The existing content_hash fingerprints only the typed v1 body, so metadata-only revisions can have equal hashes but different version IDs. Do not use body hashes as the sole identity for approvals or future publication.

Database links use tenant-scoped composite foreign keys. Triggers derive snapshot values and permit insertion only in the version creation transaction, before any review; no subsequent link insert/update/delete. Old saved versions migrate with empty classification and creation marker zero. No fabricated tags or approvals. Runtime receives limited catalogue column updates and link INSERT/SELECT only; worker has neither table's data privileges.

## Search

Existing collection routes `/questions`, `/question-reviews`, `/question-selections` accept:

| Query | Meaning |
| --- | --- |
| q | Trimmed, nonblank single-line title substring, maximum 160; `%` and `_` are literal |
| kind | One of seven question-content types |
| state | Known workflow state; pending queue supports in_review only, selection supports approved only |
| taxonomy_ids | Repeat UUID parameter; every referenced term must match the version (AND) |
| offset | 0–1,000,000, default 0 |
| limit | 1–200, default 100 |

Example: `?q=algebra&kind=single_choice&taxonomy_ids=UUID1&taxonomy_ids=UUID2&limit=20`.

Filters apply before offset/limit and preserve deterministic collection order. Authoring lists current versions for own author/admin scope; reviewers see submitted pending versions; coordinators see only approved public snapshots. No answer keys, rubrics, feedback or private bodies are searched. No descendant expansion: topics capture their subject explicitly, so subject filtering finds assigned topic versions. Retired IDs remain usable for historical selection search. Foreign and nonexistent filter IDs yield identical generic 404. Malformed/unknown collection filters, duplicate scalar parameters, duplicate taxonomy UUIDs and unsupported collection states yield 422. Authentication and authorization remain required.

Search is literal title matching, without relevance ranking/full-text indexing. Offset pagination is stable for a static dataset; concurrent writes can move page boundaries. Catalogue listing supports only its documented kind/state/pagination parameters. No cross-request snapshot or production-scale performance claim is made.
