# P3-001 exam blueprint and publication contract

Working contract for the development pilot. Requirements ASM-01, PUB-01 and TEN-01.

## Draft assembly

A coordinator works within one active institution. An exam has a stable identity and revisioned drafts. A draft contains ordered sections, an ordered list of exact question-version IDs in each section, and a scoring policy. Use the existing coordinator-safe approved selection projection for browsing. Treat a passage and its child items as one indivisible selection for assembly and section counts.

For the fixed pilot, validate explicit selections against section item counts and taxonomy coverage rules. Count coverage using the selected version’s saved taxonomy, with each selection counted once per matching rule. Permit overlapping coverage rules and reject duplicate question identities across the exam. Validate count bounds before checking selections. The same ordered draft and eligibility inputs produce the same ordered diagnostics. Each diagnostic identifies the section or rule, the required and observed values where applicable, and the correction needed. Use a generic unavailable-selection error for inaccessible IDs to avoid revealing another tenant’s content.

## Publication

Use the roadmap lifecycle of draft, validated, published and archived. Validation applies to an exact draft revision. Editing creates a new draft revision and requires validation again. Publication rechecks current coordinator authority, tenant, expected revision, blueprint and exact approved selection eligibility inside the write transaction. Serialize eligibility checks with retirement so that retirement first prevents publication and publication first preserves the snapshot. Persist the publication, audit and outbox atomically. Concurrent publication of the same revision must resolve to one snapshot. A stale revision must fail without side effects.

Freeze ordered sections, selected version IDs and hashes, content and taxonomy snapshots, exact media object versions, points and scoring policy. Keep grading material in a restricted representation and derive candidate content from explicit public projections. Never resolve published content against the newest question or media version. Later drafts, taxonomy changes and retirement affect future assembly only. A sitting references an exact publication.

Freeze decimal scoring parameters and explicit rules for weights, partial credit, negative marks, unanswered and invalid items, rounding, numeric tolerance, short-answer normalization and manual rubric versions. P5 consumes these rules for evaluation.

## Development pilot profile

Use Pilot Institute, English Grammar and adult candidates (18+) with synthetic candidate records. These are provisional development assumptions and do not establish a live institution’s policy.

- Set a 30-minute base duration. Persist UTC instants and display the sitting timezone explicitly.
- Use the selected versions’ configured points with a weight of 1. Preserve their marking rules and rubric references. Set negative marks to zero and award zero for unanswered items. Exclude invalidated items from earned and available points. Round the final percentage to two decimal places using half-up rounding. A zero available total has no percentage.
- An approved candidate accommodation adds recorded extra minutes to the base duration. The sitting close remains a hard cap. Coordinators must schedule sufficient time for approved accommodations. Do not pause the timer for breaks in this pilot.
- An authorized coordinator or institution admin may extend a deadline through a recorded decision with a reason and audit entry. The extension must fit within the sitting close. Starting at or after close is denied.

These are fixture defaults. Store effective exam and sitting policies explicitly so future institution settings can vary. P4 enforces candidate deadlines and P5 computes grades.

## Verification by dependent task

- P3-002 verifies fixed assembly, deterministic coverage diagnostics and tenant isolation.
- P3-003 verifies publication versus retirement and concurrent retries with real PostgreSQL, audit and outbox rollback, and snapshot stability after later edits and retirement.
- P3-004 verifies eligibility and timing policy snapshots against the exact publication.
- P3-005 verifies the coordinator journey and strict local and CI gates.
