"""Apply this verified source bundle to an existing checkout, preserving local configuration."""

import argparse
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4


def safe_path(root: Path, relative: str) -> Path:
    candidate = root / relative
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path leaves the selected project folder")
    if any(part in {".venv", ".git", "node_modules"} for part in Path(relative).parts):
        raise ValueError("Local environment directories are not update targets")
    if candidate.name.startswith(".env") and candidate.name != ".env.example":
        raise ValueError("Local configuration is not an update target")
    return candidate


def apply(source: Path, target: Path) -> Path:
    source, target = source.resolve(), target.resolve()
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Extract the new bundle separately from the existing project")
    if not (target / "backend/alembic.ini").is_file():
        raise ValueError("Target is not the existing assessment-platform project folder")
    manifest = source / "docs/FILE_CHECKSUMS.sha256"
    entries = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64:
            raise ValueError("Invalid source manifest")
        path = safe_path(source, relative)
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Source verification failed for " + relative)
        safe_path(target, relative)
        entries.append(relative)
    for revision in [
        "0001_foundation.py",
        "0002_identity_tenancy.py",
        "0003_audit_outbox.py",
        "0004_question_versions.py",
        "0005_question_review.py",
        "0006_question_taxonomy.py",
        "0007_authoring_media.py",
        "0008_question_imports.py",
    ]:
        baseline = Path("backend/alembic/versions") / revision
        if revision == "0008_question_imports.py" and not (target / baseline).exists():
            continue  # New in this bundle; compare it on subsequent applications.
        if (
            not (target / baseline).is_file()
            or sha256((target / baseline).read_bytes()).digest()
            != sha256((source / baseline).read_bytes()).digest()
        ):
            raise ValueError("Existing verified migration differs or is missing: " + revision)
    backup = target.parent / (
        "assessment-source-backup-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    )
    backup.mkdir()
    entries.append("docs/FILE_CHECKSUMS.sha256")
    existed, changed = set(), []
    try:
        for relative in entries:
            destination = safe_path(target, relative)
            if destination.is_file():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
                existed.add(relative)
            elif destination.exists():
                raise ValueError("A destination file is occupied by a directory")
        for relative in entries:
            destination = safe_path(target, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            changed.append(relative)
            shutil.copy2(source / relative, destination)
    except Exception:
        for relative in reversed(changed):
            destination = safe_path(target, relative)
            if relative in existed:
                shutil.copy2(backup / relative, destination)
            elif destination.is_file():
                destination.unlink()
        raise
    return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    try:
        backup = apply(Path(__file__).resolve().parent, args.target)
    except (OSError, ValueError) as error:
        raise SystemExit("UPDATE=FAILED: " + str(error)) from None
    print("UPDATE=APPLIED")
    print("SOURCE_BACKUP=" + str(backup))
    print("LOCAL_ENV_AND_VIRTUAL_ENV=UNCHANGED")
    print("DATABASE_MODIFIED=NO")
