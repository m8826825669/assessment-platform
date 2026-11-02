"""Create or reuse a development environment; never provision or migrate a database."""

import argparse
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, default=ROOT / "backend/.venv")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    folder = args.venv.resolve()
    executable = folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not executable.is_file():
        if folder.exists() and any(folder.iterdir()):
            parser.error("Selected environment is nonempty but has no Python; choose a new folder")
        venv.EnvBuilder(with_pip=True).create(folder)
    for command in [
        [str(executable), "-m", "pip", "install", "-r", str(ROOT / "backend/requirements-dev.lock")],
        [str(executable), "-m", "pip", "check"],
    ]:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    print("SETUP=PASS; environment ready; configuration and database unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
