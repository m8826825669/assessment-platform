"""Run P2-007 against disposable databases/storage; no application test accounts are created."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main():
    os.chdir(BACKEND)
    if any(
        os.environ.get(name) != "1"
        for name in [
            "ASSESSMENT_ALLOW_TEST_DATABASE_CREATION",
            "ASSESSMENT_ALLOW_TEST_MEDIA_CREATION",
        ]
    ):
        print("BROWSER_GATE=FAIL; enable disposable database and media fixture creation")
        return 1
    sys.path.insert(0, str(BACKEND))
    from app.config import Settings

    try:
        environment = os.environ.copy()
        environment["ASSESSMENT_TEST_ADMIN_URL"] = Settings().migration_url.get_secret_value()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "browser_checks",
                "-q",
                "--require-postgres",
            ],
            cwd=BACKEND,
            env=environment,
            check=False,
        )
        print("BROWSER_GATE=" + ("PASS" if result.returncode == 0 else "FAIL"))
        return result.returncode
    except Exception:
        print("BROWSER_GATE=FAIL; check local prerequisites without printing credentials")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
