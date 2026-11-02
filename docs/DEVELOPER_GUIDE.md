# Reproducible developer setup and CI (P1-005)

Requirements: CPython 3.11 or newer with venv/pip; the declared CI matrix targets 3.11, 3.12 and 3.13 on Linux, and 3.12 on Windows. P1 acceptance for this matrix is recorded in P1_ACCEPTANCE.md; new source increments still require their own successful runs. PostgreSQL 17 is the CI service target. Existing local PostgreSQL installations remain supported through actual test evidence rather than an untested broad version claim.

## Fresh checkout

Use the complete `assessment-platform` directory as repository root. Run `python scripts/setup_dev.py` from any directory by providing the script's path. It creates `backend/.venv`, or reuses it, installs `requirements-dev.lock`, and runs `pip check`. It never writes configuration or connects to PostgreSQL. Nonempty broken environments are rejected instead of overwritten. A separate environment can be selected with `--venv PATH`; relative paths are relative to your current directory.

For application configuration and initial database/role provisioning, follow LOCAL_SETUP_WINDOWS.md and P1_003_UPGRADE_WINDOWS.md, then P1_004_UPGRADE_WINDOWS.md as applicable. Existing installations must use P1_005_UPGRADE_WINDOWS.md and must not rebootstrap. `.env.example` contains examples only; real credentials remain private and ignored by Git.

## One verification entry point

Use the Python from the installed development environment:

```text
backend/.venv/bin/python scripts/verify.py
```

Windows equivalent: `backend\.venv\Scripts\python.exe scripts\verify.py`.

Full mode requires `ASSESSMENT_TEST_ADMIN_URL` and `ASSESSMENT_ALLOW_TEST_DATABASE_CREATION=1`. Use a dedicated development/test PostgreSQL server with an administrator able to create databases and roles. Alternatively, `--local-postgres` reads the migration URL privately from `backend/.env` (including environment overrides); the explicit database-creation flag is still required. No URL is printed or put into subprocess arguments. Full tests use random database and role names and teardown their own resources. Interrupted tests can leave random test resources; review them before manual cleanup.

The gate runs dependency compatibility, direct declaration/lock/installed-version consistency, Ruff lint, Ruff format check, and the entire strict PostgreSQL suite. Existing integration tests migrate fresh databases from zero, compare SQLAlchemy metadata, verify downgrade/reupgrade, and exercise tenant permissions and worker transactions. Verification does not invoke migrations against the configured administrator database. Any failed stage stops the command. Successful test exit alone is insufficient: JUnit counts must contain at least one test and zero failures, errors or skips. The command always attempts a sanitized `artifacts/verification.json` summary. Transient JUnit files are removed at completion; normal test output remains visible.

`--unit-only` excludes the integration directory and reports **PARTIAL_PASS**. It is useful without PostgreSQL but never closes the database/CI gate. Full mode fails when PostgreSQL configuration is absent; it never silently degrades to a partial run.

## Dependency policy

Runtime declarations live in `backend/requirements.in` and `backend/pyproject.toml`. Development additions live in `requirements-dev.in`. Both complete resolution lockfiles are committed. Setup installs versions from the development lock; marker-specific Windows/Linux dependencies are preserved. The dependency checker validates runtime pins are included in development pins and the installed platform's versions match. `pip check` validates dependency compatibility. This checks declared pins, not package authenticity, vulnerability absence, or byte-identical builds; hashes and a dependency security scan are not claimed.

Change declarations and regenerate both lockfiles intentionally together using the recorded `uv pip compile --universal` command in each file header. Run the full gate after dependency changes and record the reason. Do not fix the existing Starlette/httpx warning by silently switching the HTTP client stack during another milestone.

## CI

`.github/workflows/ci.yml` runs on push, pull requests and manual dispatch. Linux jobs cover Python 3.11/3.12/3.13, each with its own disposable PostgreSQL 17.6 service and a fresh virtual environment. Each runs the full gate. The Windows Python 3.12 job runs portable setup/static/unit checks and is explicitly partial. All Linux jobs plus the Windows job must pass. Service credentials are disposable examples; CI needs no production secrets. The workflow uses read-only repository permissions, no persistent checkout credentials, bounded timeouts, and commit-pinned GitHub actions. It does not deploy or publish releases. No CI artifacts containing raw test failures or configuration are uploaded; sanitized full-gate counts appear in the job summary.

The workflow expects the project at repository root. Configure required branch checks only after the first actual successful run. The owner supplied a successful P1 run screenshot for b00e0a8 / run 41375023675; see P1_ACCEPTANCE.md. Each new source increment requires its own actual run URL, commit and matrix outcomes; prior runs cannot verify later source.

References for maintainers: [PostgreSQL services](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers), [setup-python v5.6.0](https://github.com/actions/setup-python/releases/tag/v5.6.0), [checkout v4.2.2](https://github.com/actions/checkout/releases/tag/v4.2.2). Action pins are deliberate dependency choices, not claims to be the latest release. Review them through the same controlled dependency-update process.

## Final P1 review

P1 is accepted as recorded in P1_ACCEPTANCE.md. The following remains the historical P1 review checklist and applies again to relevant regression checks. Before P2: retain the fresh local full verification report, actual successful CI run/commit, P1-002/003/004 local evidence, and a readiness/auth/worker smoke against the current source. Confirm the migration head remains 0003 and that API and worker use separate restricted accounts. Record any remaining limitations and approve the P2 task breakdown against MASTER_ROADMAP.md. CI passing does not imply production readiness or delivery of a usable examination runner.
