# Progress

Controlling baseline: MASTER_ROADMAP.md v1.0; phase plan: P2_QUESTION_BANK_PLAN.md. Updated 2 November 2026. Source/API 0.9.0, P2-004. Original roadmap/Word baseline unchanged.

## Accepted

P0/P1 and P2-001 through P2-003 are accepted. P2-003 owner evidence: strict Windows gate VERIFICATION=PASS, 0005 head, clean schema, roles refreshed, worker healthy, API ready; pushed 5bc13f9 and green Foundation gate #4 screenshot. No run ID/individual job logs supplied; screenshot test count partly obscured. See LOCAL_VERIFICATION_P2_003.md and earlier acceptance records.

## Current: P2-004

Implemented institution subjects, subject-owned topics, flat outcomes and tags. Admin catalogue changes use fenced revisions and terminal retirement. All four staff roles can read the catalogue; candidate/invigilator/examiner cannot. Classification references and labels freeze within each saved version's creation transaction. Renames/retirements never rewrite saved versions. Topics automatically include their subject snapshot. No approval transfers across a metadata-only revision.

Author current-version lists, pending review queues and approved selections support bounded literal title, content type, workflow state and AND taxonomy filters before deterministic pagination. Existing role/RLS boundaries apply. Coordinator selection includes approved classification without private version/hash/comment access. New schema head 0006_question_taxonomy; thirteen forced-RLS tables and seven enabled guards. Earlier five migrations, content.v1 and pinned dependencies remain unchanged.

## Evidence and next gate

IMPLEMENTED, STRICT LOCAL POSTGRESQL AND NEW CI ACCEPTANCE PENDING. Portable gate: 313 tests passed, zero skips; dependency compatibility/pins, lint and format passed. Full collection 502 tests (189 require real PostgreSQL). Offline migration SQL parsing is syntax evidence only. This workspace cannot run PostgreSQL under its non-root server constraints; no PostgreSQL/CI result is invented. See VALIDATION_P2_004.txt.

Follow P2_004_UPGRADE_WINDOWS.md: apply separate source bundle, migrate, compare schema, refresh restricted grants, run full strict verification, restart API, check worker and readiness. Only after this increment's local and new-commit CI gate can P2-005 protected accessible media begin.

## Limits

No frontend/browser authoring, protected media/storage scanning, imports, examination publication, candidate runner or evaluation/results yet. Taxonomy outcomes have no arbitrary hierarchy; only topics have subject parents. Search covers titles only, with literal substrings and existing offset pagination. No full-text relevance, descendant expansion, cross-request snapshot consistency or capacity claim. Content hash remains the v1 typed-body fingerprint; immutable version identity binds title/classification/review. Omitting taxonomy_ids on revision clears classification. Authoring/review/catalogue mutation serializes per institution. Privileged database owners can disable guards. Local outbox consumer sends no external messages. Existing TestClient deprecation warning remains tracked.
