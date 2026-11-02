# Institutional Assessment Platform

Source/API **0.11.0**, P2-006 validated question imports; pending strict local/CI acceptance. P1 and P2-001–P2-005 accepted, latest 709e448. Roadmap v1.0 and final goal unchanged.

Follow [Windows upgrade and verification](docs/P2_006_UPGRADE_WINDOWS.md), [import contract](docs/QUESTION_IMPORT_API.md), [progress](docs/PROGRESS.md) and [backlog](docs/BACKLOG.json). Read AGENTS.md before changes.

This release adds bounded JSON preview, atomic revision-one draft import and actor/institution-scoped idempotent success receipts. It reuses the seven existing content types, active taxonomy and protected clean media. Preview does not write business data; invalid later rows never leave a partial batch. No auto-approval, existing-question update or public integration-standard import.

Existing private static image, role/review/selection and safe projection behavior remains. No frontend/browser journey, published examination, candidate runner or grading engine yet.

Portable verification is explicitly partial: run scripts/verify.py --unit-only with the backend environment Python. Full gate requires disposable PostgreSQL plus the existing dedicated storage/ClamAV services and both creation-consent flags. Missing services fail instead of skipping. See the Windows guide. CI performs no deployment.
