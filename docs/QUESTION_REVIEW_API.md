# Independent question review — P2-003

Source/API 0.8.0; requirements QBK-01, IAM-01, TEN-01 and GOV-01. Existing immutable content, title, origin and version-number rules remain. New schema head is 0005_question_review. No frontend, taxonomy, media, imports or exam publication is delivered here.

## Workflow

| Current state | Action | New state | Authority |
| --- | --- | --- | --- |
| draft | submit | in_review | Owning author or institution admin |
| in_review | return, with reason | returned | Independent reviewer or admin |
| in_review | approve | approved | Independent reviewer or admin |
| in_review | new saved version | superseded (old version); draft (new version) | Owning author or admin |
| approved | retire, with reason | retired | Reviewer or admin |

Returned snapshots stay immutable. Correcting/resubmitting creates a new saved version; returned, retired or superseded snapshots cannot be resubmitted unchanged. Approval never transfers to an edit, including an edit with identical content. An earlier approved version remains selectable while a newer draft is being prepared, until that exact approved version is retired. An edit while review is pending appends an explicit superseded decision in the same transaction as the new version. A stale reviewer cannot approve the replaced version.

Approval/return cannot be performed by the originating question author, the exact version's editor, or its submitter. This applies to admins and later role changes; admin permissions do not bypass it. The originating author is retained across revisions. At least two eligible staff identities are needed for a review journey. This does not implement content plagiarism/provenance detection across distinct question identities or arbitrary copy/paste history.

Retirement removes future selection eligibility; it does not erase snapshots or past decisions. P3 must still enforce eligibility at exam publication and retain its own immutable references; this release does not claim a published-exam workflow.

## Endpoints

Base: `/api/v1/tenants/{tenant_id}`. All require a current bearer session, active membership and current institutional status. Responses use no-store caching and existing safe problem/request-ID contracts.

| Method / path | Result |
| --- | --- |
| GET /question-reviews | Latest pending reviews as metadata; reviewer/admin only |
| GET /question-reviews/{question_id}/versions/{version_id} | Exact submitted content and newest-first private decisions; owning author may also read own feedback |
| POST /question-reviews/{question_id}/versions/{version_id} | Submit, return, approve or retire that exact version; HTTP 200 on success |
| GET /question-selections | Approved, non-retired public content for coordinator/admin |
| GET /question-selections/{version_id} | One exact approved public snapshot, or 404 |

Queue, decision history and selection lists accept offset 0–1000000 and limit 1–200 (default 100). Lists are bounded arrays, not snapshot-consistent exports or total-count reports. Pending queue orders by decision creation time/UUID; selections order by approval-row creation time/version UUID. Existing authoring list/history/detail now report actual `state` and `review_revision`, while retaining immutable content and the current question `revision` fence.

Command body:

```json
{
  "action": "approve",
  "expected_revision": 1,
  "expected_review_revision": 1,
  "content_hash": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

The illustrative all-zero hash has valid syntax but must be replaced with the actual version hash. Obtain actual question_id, version_id, revision, review_revision and hash from the authorized detail response. Use action=submit on a draft with expected_review_revision=0. Return/retire require a nonblank plain-text reason capped at 1000 characters; submit/approve must omit reason. No endpoint accepts client-assigned actor, tenant, status, sequence, decision ID, approval pointer or supersede action. Supersede is internal to a revision.

Both fences and the hash must match. Old version approval/return/submission is denied if another saved version is now current. Retirement may address an older approved version, using the question's current revision fence and that version's current review counter. A stale/mismatched/duplicate command returns 409 review_conflict. Ineligible self-review returns 403 review_self. Foreign/missing IDs return 404; lack of role authority is 403. Retrying a committed action does not transparently replay success; it returns a conflict and requires reload.

## Privacy and role boundaries

Reviewers can inspect private marking material only for versions that have actually been submitted in their institution. Seeing one submitted version does not expose a later unsubmitted draft. They may read retained decisions on returned, superseded, approved and retired submitted versions. Existing authoring endpoints still require author/admin permission; reviewers use dedicated review endpoints. Other authors cannot read another author's drafts or feedback.

Coordinators use a separate selection projection table and have no general private-version or review-comment visibility, including through direct database row-policy tests. Selection payloads contain question_id, version_id, title and public content only. No private key, rubric guidance, internal content hash, reviewer comment or authoring model is returned. Retirement hides that projection from coordinator row reads and from selection endpoints. Candidate, invigilator and examiner roles have no bank/review/selection route access.

The database constructs the public JSON from an explicit recursive allowlist for question-content.v1. It ignores private JSON passed to projection insertion and derives the title from the immutable saved version. Public prompts/options may still intentionally contain answer text; human review controls that content-quality risk. Candidate rendering/accessibility remains P2-007; this is a JSON contract, not browser acceptance.

## Persistence, locks and atomicity

`question_review_events` is append-only. Each row binds tenant, question UUID, exact version UUID/hash, immutable originating author, actor, positive per-version sequence, expected question revision, action/state, optional reason and timestamp. The latest sequence is workflow authority; existing v0.7 drafts receive no fabricated decisions or approvals. A scoped composite FK binds the review to its immutable version/hash. Trigger checks validate origin, current role, legal transition, independent reviewer and fences.

`question_selections` stores only a public immutable snapshot and a guarded approved→retired eligibility change. Its event reference is scoped to the same tenant/question/version. A deferred constraint trigger requires approval/retirement and their selection change to commit together. The ordinary API transaction additionally includes audit/outbox writes; failures roll everything back. Version content is never updated to express review state.

Application mutations retain the institution lock shared with membership administration and recheck live user/session/clock afterwards. Root revision changes and review appends also share a PostgreSQL transaction advisory lock keyed by tenant/question, with optimistic counters and uniqueness constraints. No elevated SECURITY DEFINER function is introduced. These are consistency controls, not a throughput claim. Revocation is checked at the decision point, not retroactively after an already authorized commit.

Runtime receives SELECT/INSERT on the two new tables and only state/last_event_id UPDATE on selections. No update/delete/truncate is granted for review history or projection content. Worker credentials have no access to either table. Readiness checks eleven forced-RLS tables, five enabled guards, exact schema head and role-specific grants. Privileged owners can deliberately disable/replace protections; credentials remain private server capabilities.

Audit/outbox use question.review_submitted/returned/approved/retired/superseded. State allowlist: version_id, revision (saved version number), content_hash, review_revision and review_state. Free-text reasons, titles, raw content and marking data are excluded. Reasons remain private in immutable decision history. The local receipt worker validates these events without reading question tables; no email or webhook delivery is enabled.

## Acceptance boundary

Portable tests and parsed SQL do not prove database semantics. Strict local PostgreSQL tests and a new actual CI run are required for P2-003 acceptance. Added cases cover all seven SQL/public projections, self-review across roles and editors/submitters, return/edit flows, stale decisions, edit/approval races, role/session revocation while waiting, scoped visibility, immutable history, forged decisions, missing projections, failure rollback, v0.7 upgrade preservation and worker separation. Browser workflow acceptance remains later P2 work.
