# Progress

Controlling baseline MASTER_ROADMAP.md v1.0; phase plan P2_QUESTION_BANK_PLAN.md. Updated 2 November 2026. Source/API 0.10.1, P2-005. Original roadmap/Word unchanged.

## Accepted

P0/P1 and P2-001 through P2-004. Latest owner evidence: 502 strict tests passed, zero skips, 436.07s; schema 0006 clean, roles/API/worker healthy. CI workflow #5 green for cleanup commit 5b3e6a8. Run ID/individual matrix logs not supplied. See LOCAL_VERIFICATION_P2_004.md.

## Current: P2-005

Implemented private versioned object storage, bounded static PNG/JPEG validation, pending/quarantine/clean/rejected lifecycle, fenced scan retries, ClamAV INSTREAM/fresh signature checks, protected downloads, immutable descriptions/bytes and creation-only question links. Existing public metadata adds safe media descriptors; typed-body v1 remains unchanged. Checks on attachment/submit/approve/selection/preview/download prevent use of missing, altered or unclean bytes. Safe media audit/outbox writes are transactional; external uploads may leave inaccessible orphans if SQL fails. No external effects added to the existing outbox worker.

Head 0007_authoring_media: fifteen forced-RLS tables and nine guards. Earlier six migrations unchanged. New SDK/image dependencies are pinned, previous dependency versions retained. Local private storage provisioning creates a new bucket and separate restricted credential; the API never receives storage administration. Media defaults disabled until explicitly provisioned, preserving existing no-media question behavior. When enabled, readiness includes storage/scanner health.

## Evidence and next gate

IMPLEMENTED, LOCAL POSTGRESQL/STORAGE/SCANNER AND NEW CI PENDING. Portable gate 360 tests passed, no skips; dependency/lint/format passed. Full collection and SQL evidence in VALIDATION_P2_005.txt. This workspace has no runnable PostgreSQL, Docker, object store or ClamAV, so no live result is inferred from mocks/parsing. New mandatory live tests use dedicated loopback storage, restricted IAM, anonymous/deletion denials, exact-version overwrite/missing checks and real EICAR scanning. CI provisions isolated services and retains the existing three Python/PostgreSQL jobs plus portable Windows job.

Follow P2_005_UPGRADE_WINDOWS.md. Prove storage/scanner prerequisites first, then schema/grants, full strict gate, restarted readiness and worker status, then new-commit CI. Do not begin dependent imports until this gate passes. Keep P2-005 acceptance pending if any live service/test is unavailable.

## Limits

Initial media is question-level static PNG/JPEG only, 8 MiB/20MP/16 references; no PDFs/SVG/animation/audio/video or per-option positioning. Accessible description is required but browser/keyboard/screen-reader verification remains P2-007. No frontend, imports, published exams, candidate runner/uploads or grading yet. Clean scan is point-in-time; immutable storage checks do not promise permanent availability. No automated orphan deletion, quotas, threat re-scan policy, storage disaster recovery or production capacity claim. Development MinIO is a pinned source-built fixture from archived upstream; supported production storage/security/licensing remains a release decision. Existing TestClient warning tracked.

## 0.10.1 correction gate

Owner 0.10.0 full run: 569 passed, three failed, 522.02s. Correct downgrade dependency order, require explicit version ID in the existing application storage policy, and reject image trailing payloads rather than assuming ClamAV detects appended EICAR. Raw standard EICAR remains a real scanner test. See P2_005_FIXES_WINDOWS.md. Upgrade SQL and accepted migrations unchanged; no main DB migration/downgrade needed. Full collection now 581; real local correction/CI results pending.
