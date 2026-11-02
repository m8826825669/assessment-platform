# Progress

Controlling baseline MASTER_ROADMAP.md v1.0; phase plan P2_QUESTION_BANK_PLAN.md. Updated 2 November 2026. Source/API 0.11.0, P2-006. Original roadmap/Word baseline unchanged.

## Accepted

P0/P1 and P2-001 through P2-005 accepted. Latest owner evidence: 581 strict corrected tests passed, zero skips, 561.22s; 47 focused tests passed; schema/grants, private storage/scanner, five-dependency API readiness and worker healthy. Pushed 709e448, clean tree and green workflow #6 screenshot. No run ID/full SHA/individual job logs supplied. See LOCAL_VERIFICATION_P2_005.md.

## Current: P2-006

Implemented authenticated bounded internal JSON preview and atomic draft imports, immutable actor/tenant/key-scoped success receipts, stable response replay and changed-payload conflict. All seven types use normal content validation; preview uses safe candidate projection. Real reference checks reuse active taxonomy/subject closure and owned clean exact-version media validation. A failure in any row/receipt/audit/outbox rolls back the full batch. Existing question creation now exposes a shared no-commit staging helper; regular single-create behavior remains the same.

Head 0008_question_imports adds one forced-RLS receipt table/guard (sixteen RLS tables, ten guards). Earlier seven migrations, content.v1, domain reference and dependency locks unchanged. Restricted API grant refresh required; worker remains denied private receipt data. Successful receipts store IDs/fingerprint only, never raw uploaded documents; batch audit records UUID/count only. Existing local outbox consumer has one additional registered safe event, with no external effects.

## Evidence and next gate

IMPLEMENTED, LOCAL POSTGRESQL/STORAGE AND NEW CI ACCEPTANCE PENDING. Portable gate: 393 tests passed, no skips; dependency/lint/format passed. Full collection 652 (393 portable, 259 integration), including real media import validation. Offline SQL/configuration/package checks in VALIDATION_P2_006.txt do not prove database behavior. This workspace cannot execute the supported real PostgreSQL/storage/scanner environment; no live gate or new CI run is invented.

Follow P2_006_UPGRADE_WINDOWS.md, migrate/compare schema, refresh restricted roles, run all 652 strict tests without skips while existing storage/scanner services stay running, restart/check API and worker, then commit/push and verify new CI. Only then begin P2-007 browser authoring/review/media/import journeys. P2 overall remains incomplete.

## Limits

Internal JSON profile only; no QTI/LTI/CSV/Excel, asynchronous bulk worker, import updates or auto-approval. Max 2 MiB/50 rows/16 media references per batch; preview advisory and may become stale. Keys deduplicate successful creation per actor/institution, not globally; new keys intentionally create new drafts. Receipts do not guarantee later storage availability. No frontend/browser accessibility acceptance, published exams, candidate runner/uploads or grading yet. Earlier static-media/production storage/retention/recovery/capacity limits remain. Existing TestClient warning tracked.
