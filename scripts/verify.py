"""Run the engineering gate with the active Python. Full mode requires disposable PostgreSQL tests."""

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def test_counts(path):
    suites = ET.parse(path).getroot()
    if suites.tag == "testsuite":
        suites = [suites]
    counts = {
        name: sum(int(suite.get(name, "0")) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }
    if counts["tests"] == 0 or any(counts[key] for key in ("failures", "errors", "skipped")):
        raise ValueError("Test gate requires at least one test, no failures, errors or skips")
    return counts


def test_environment(local_postgres, unit_only):
    environment = os.environ.copy()
    if unit_only:
        return environment
    if environment.get("ASSESSMENT_ALLOW_TEST_DATABASE_CREATION") != "1":
        raise ValueError("Set ASSESSMENT_ALLOW_TEST_DATABASE_CREATION=1 for disposable test databases")
    if local_postgres:
        sys.path.insert(0, str(BACKEND))
        from app.config import Settings

        environment["ASSESSMENT_TEST_ADMIN_URL"] = Settings().migration_url.get_secret_value()
    if not environment.get("ASSESSMENT_TEST_ADMIN_URL"):
        raise ValueError("Configure ASSESSMENT_TEST_ADMIN_URL or use --local-postgres with backend/.env")
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--unit-only", action="store_true", help="Partial check; excludes all PostgreSQL tests")
    mode.add_argument(
        "--local-postgres", action="store_true", help="Read test admin URL from local migration settings"
    )
    args = parser.parse_args()
    report = {
        "mode": "unit-only" if args.unit_only else "full-postgresql",
        "status": "failed",
        "python": platform.python_version(),
        "started_at": datetime.now(UTC).isoformat(),
        "stages": [],
    }
    output = ROOT / "artifacts/verification.json"
    output.parent.mkdir(exist_ok=True)
    try:
        # Settings resolves .env from this directory. Never serialize its values.
        os.chdir(BACKEND)
        environment = test_environment(args.local_postgres, args.unit_only)
        stages = [
            ("dependency-compatibility", ["-m", "pip", "check"], ROOT),
            ("dependency-pins", [str(ROOT / "scripts/check_dependencies.py")], ROOT),
            ("lint", ["-m", "ruff", "check", "--config", str(BACKEND / "pyproject.toml"), str(ROOT)], ROOT),
            (
                "format",
                ["-m", "ruff", "format", "--check", "--config", str(BACKEND / "pyproject.toml"), str(ROOT)],
                ROOT,
            ),
        ]
        with tempfile.TemporaryDirectory(prefix="assessment_verify_") as temporary:
            junit = Path(temporary) / "tests.xml"
            test_args = ["-m", "pytest", "-q", "-ra", "--junitxml", str(junit)]
            test_args += ["--ignore=tests/integration"] if args.unit_only else ["--require-postgres"]
            stages.append(("tests", test_args, BACKEND))
            for name, arguments, directory in stages:
                print("CHECK=" + name, flush=True)
                result = subprocess.run(
                    [sys.executable, *arguments], cwd=directory, env=environment, check=False
                )
                report["stages"].append({"name": name, "exit_code": result.returncode})
                if result.returncode:
                    return 1
            report["tests"] = test_counts(junit)
        report["status"] = "partial-pass" if args.unit_only else "pass"
        print("VERIFICATION=" + ("PARTIAL_PASS" if args.unit_only else "PASS"))
        return 0
    except Exception as error:
        # Do not expose configuration validation inputs or connection credentials.
        print("VERIFICATION=FAIL; " + type(error).__name__ + "; check prerequisites and stage output")
        return 1
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("REPORT=artifacts/verification.json", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
