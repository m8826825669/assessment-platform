"""Apply the 0.4.1 test-only fix from the existing backend directory."""

import argparse
import ast
import os
from pathlib import Path
from uuid import uuid4

OLD = b"    assert responses[0].json() == responses[1].json()"
NEW = b"""    from uuid import UUID

    payloads = [response.json() for response in responses]
    for response, payload in zip(responses, payloads, strict=True):
        correlation = str(UUID(payload["request_id"]))
        assert response.headers["x-request-id"] == correlation
        assert payload["instance"] == "urn:assessment:request:" + correlation
        assert payload["code"] == "invalid_credentials"
        assert payload["detail"] == "Invalid email or password"
    assert payloads[0]["request_id"] != payloads[1]["request_id"]
    stable = [
        {key: value for key, value in payload.items() if key not in {"request_id", "instance"}}
        for payload in payloads
    ]
    assert stable[0] == stable[1]"""


def apply(backend: Path) -> str:
    path = backend / "tests/integration/test_identity_tenancy.py"
    original = path.read_bytes()
    replacement = NEW.replace(b"\n", b"\r\n") if b"\r\n" in original else NEW
    if replacement in original and OLD not in original:
        return "PATCH=ALREADY_APPLIED"
    if original.count(OLD) != 1:
        raise ValueError("Expected one original assertion; no changes made")
    patched = original.replace(OLD, replacement)
    ast.parse(patched.decode("utf-8-sig"))
    backup = path.with_name(path.name + ".before-correlation-fix")
    if not backup.exists():
        with backup.open("xb") as output:
            output.write(original)
    temporary = path.with_name(path.name + ".patch-" + uuid4().hex)
    try:
        temporary.write_bytes(patched)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return "PATCH=APPLIED; ORIGINAL_TEST_BACKED_UP; DATABASE_NOT_MODIFIED"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        print(apply(args.backend))
    except (OSError, ValueError, SyntaxError) as error:
        raise SystemExit("PATCH=FAILED: " + str(error)) from None
