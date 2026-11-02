"""Check direct declarations, exact lock pins, runtime/dev coherence and installed versions."""

import importlib.metadata
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def requirements(path):
    return [
        Requirement(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-r "))
    ]


def check():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if set(project["dependencies"]) != {str(item) for item in requirements(BACKEND / "requirements.in")}:
        raise ValueError("pyproject.toml and requirements.in direct dependencies differ")
    runtime = requirements(BACKEND / "requirements.lock")
    development = requirements(BACKEND / "requirements-dev.lock")
    if not {str(item) for item in runtime}.issubset({str(item) for item in development}):
        raise ValueError("Development lock must contain the full runtime resolution")
    for direct in requirements(BACKEND / "requirements.in") + requirements(BACKEND / "requirements-dev.in"):
        if not any(
            canonicalize_name(direct.name) == canonicalize_name(locked.name)
            and direct.specifier == locked.specifier
            and direct.extras.issubset(locked.extras)
            for locked in development
        ):
            # uv represents extras through their resolved additional distributions.
            if not any(
                canonicalize_name(direct.name) == canonicalize_name(locked.name)
                and direct.specifier == locked.specifier
                for locked in development
            ):
                raise ValueError("Direct dependency differs from lock: " + direct.name)
    for item in development:
        pins = list(item.specifier)
        if len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version or item.url:
            raise ValueError("Dependency must have one exact version pin: " + item.name)
        if item.marker is None or item.marker.evaluate():
            if importlib.metadata.version(item.name) not in item.specifier:
                raise ValueError("Installed version differs from lock: " + item.name)


if __name__ == "__main__":
    try:
        check()
    except (ValueError, importlib.metadata.PackageNotFoundError) as error:
        print("DEPENDENCIES=FAIL; " + str(error))
        raise SystemExit(1) from None
    print("DEPENDENCIES=PASS")
