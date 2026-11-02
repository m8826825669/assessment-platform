> Existing 0.10.0 installations: apply [P2-005 corrections](docs/P2_005_FIXES_WINDOWS.md), refresh the existing storage policy, then rerun focused/full verification.

# Institutional Assessment Platform

Source/API **0.10.1**, P2-005 private authoring media; pending strict live acceptance. P1 and P2-001–P2-004 accepted, latest 5b3e6a8. Roadmap v1.0 and final goal unchanged.

Follow [Windows upgrade and verification](docs/P2_005_UPGRADE_WINDOWS.md), [media contract](docs/MEDIA_API.md), [progress](docs/PROGRESS.md) and [backlog](docs/BACKLOG.json). Read AGENTS.md before changes.

Static PNG/JPEG assets enter quarantine, pass actual ClamAV before use, and use private versioned S3 bytes. Question versions freeze media references/descriptions without changing the v1 typed-body hash. Existing role boundaries apply to metadata/downloads; no public object URLs. Media defaults disabled until provisioned. No frontend, imports, published examinations, candidate runner or grading yet.

Portable checks: `python scripts/setup_dev.py`, then run `scripts/verify.py --unit-only` with the backend environment Python (partial evidence). Full verification requires disposable PostgreSQL plus dedicated local test storage/scanner and both creation-consent flags; see the Windows guide. Missing services must fail, not skip. No production deployment is performed by CI. Existing TestClient warning remains tracked.

API contracts: [questions](docs/QUESTION_BANK_API.md), [review](docs/QUESTION_REVIEW_API.md), [taxonomy](docs/TAXONOMY_API.md), [media](docs/MEDIA_API.md).
