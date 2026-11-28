"""Run ASM-01/PUB-01/SCH-01 coordinator browser checks with disposable PostgreSQL only."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT / "backend")
    if os.environ.get("ASSESSMENT_ALLOW_TEST_DATABASE_CREATION") != "1":
        print("COORDINATOR_BROWSER_GATE=FAIL; enable disposable database creation")
        return 1
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import Settings

    try:
        environment = os.environ.copy()
        environment["ASSESSMENT_TEST_ADMIN_URL"] = Settings().migration_url.get_secret_value()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "browser_checks/test_coordinator_exams.py",
                "-q",
                "--require-postgres",
            ],
            env=environment,
            check=False,
        )
        print("COORDINATOR_BROWSER_GATE=" + ("PASS" if result.returncode == 0 else "FAIL"))
        return result.returncode
    except Exception:
        print("COORDINATOR_BROWSER_GATE=FAIL; check prerequisites without printing credentials")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
