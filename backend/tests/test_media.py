"""SEC-01/ACC-01 media bounds, bytes, protocol and safe projections."""

import io
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from app.audit.service import clean_state
from app.config import Settings
from app.media.adapters import MAX_BYTES, InvalidImage, MediaUnavailable, ObjectStore, Scanner, inspect_image
from app.media.contracts import Attachments, Fence, Reserve
from app.media.provisioning import application_policy


def image_bytes(kind="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (4, 3), "blue").save(stream, format=kind)
    return stream.getvalue()


@pytest.mark.parametrize("kind,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_only_decodable_expected_static_images_are_accepted(kind, mime):
    data = image_bytes(kind)
    assert inspect_image(data, mime) == (4, 3)
    with pytest.raises(InvalidImage):
        inspect_image(data, "image/jpeg" if mime == "image/png" else "image/png")


@pytest.mark.parametrize(
    "data,mime",
    [
        (b"", "image/png"),
        (b"<svg/>", "image/png"),
        (b"GIF89a", "image/png"),
        (b"%PDF", "application/pdf"),
        (b"x" * (MAX_BYTES + 1), "image/png"),
    ],
)
def test_invalid_or_oversized_uploads_rejected(data, mime):
    with pytest.raises(InvalidImage):
        inspect_image(data, mime)


def test_truncated_and_animated_images_are_rejected():
    with pytest.raises(InvalidImage):
        inspect_image(image_bytes()[:30], "image/png")
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(
        stream, format="PNG", save_all=True, append_images=[Image.new("RGB", (2, 2), "blue")]
    )
    with pytest.raises(InvalidImage):
        inspect_image(stream.getvalue(), "image/png")


@pytest.mark.parametrize(
    "changes",
    [
        {"description": " "},
        {"description": "ab"},
        {"filename": "../x.png"},
        {"filename": "x\n.png"},
        {"mime_type": "image/svg+xml"},
        {"state": "clean"},
        {"object_key": "forged"},
    ],
)
def test_reservation_never_accepts_private_storage_or_scan_authority(changes):
    with pytest.raises(ValidationError):
        Reserve.model_validate(
            {
                "filename": "diagram.png",
                "mime_type": "image/png",
                "description": "A labelled triangle",
                **changes,
            }
        )


def test_attachment_and_revision_input_is_bounded():
    identifier = uuid4()
    for ids in [(identifier, identifier), tuple(uuid4() for _ in range(17))]:
        with pytest.raises(ValidationError):
            Attachments(media_ids=ids)
    for revision in [0, True, -1]:
        with pytest.raises(ValidationError):
            Fence(expected_revision=revision)


@pytest.mark.parametrize("action", ["media.reserved", "media.uploaded", "media.scanned"])
def test_media_audit_never_contains_bytes_keys_descriptions_or_scanner_details(action):
    assert clean_state(action, {"asset_id": str(uuid4()), "media_revision": 1, "media_state": "pending"})
    for payload in [
        {"object_key": "private"},
        {"object_version": "private"},
        {"description": "private"},
        {"filename": "private"},
        {"scanner_version": "private"},
        {"media_state": "unknown"},
        {"media_revision": True},
    ]:
        with pytest.raises(ValueError):
            clean_state(action, payload)


@pytest.mark.parametrize(
    "verdict,expected", [("stream: OK", "clean"), ("stream: Eicar-Test-Signature FOUND", "rejected")]
)
def test_scanner_accepts_only_explicit_complete_verdicts(verdict, expected):
    scanner = Scanner(
        SimpleNamespace(
            media_scanner_host="localhost", media_scanner_port=3310, media_signature_max_age_days=7
        )
    )
    scanner.ready = Mock(return_value="ClamAV fixture")
    scanner.exchange = Mock(return_value=verdict)
    assert scanner.scan(b"data") == (expected, "ClamAV fixture")


@pytest.mark.parametrize(
    "reply", ["OK", "stream: ERROR", "INSTREAM size limit exceeded. ERROR", "", "stream: MAYBE"]
)
def test_scanner_errors_never_become_clean(reply):
    scanner = Scanner(
        SimpleNamespace(
            media_scanner_host="localhost", media_scanner_port=3310, media_signature_max_age_days=7
        )
    )
    scanner.ready = Mock(return_value="ClamAV fixture")
    scanner.exchange = Mock(return_value=reply)
    with pytest.raises(MediaUnavailable):
        scanner.scan(b"data")


@pytest.mark.parametrize("days,valid", [(0, True), (8, False), (-3, False)])
def test_stale_or_future_signature_database_fails_readiness(days, valid):
    scanner = Scanner(
        SimpleNamespace(
            media_scanner_host="localhost", media_scanner_port=3310, media_signature_max_age_days=7
        )
    )
    stamp = (datetime.now(UTC) - timedelta(days=days)).strftime("%a %b %d %H:%M:%S %Y")
    scanner.exchange = Mock(side_effect=["PONG", f"ClamAV 1.5.4/12345/{stamp}"])
    if valid:
        assert scanner.ready().startswith("ClamAV")
    else:
        with pytest.raises(MediaUnavailable):
            scanner.ready()


def test_object_reads_bind_version_and_validate_bytes_and_close_connections():
    store = object.__new__(ObjectStore)
    store.bucket = "private"
    store.client = Mock()
    response = store.client.get_object.return_value
    data = image_bytes()
    response.read.return_value = data
    assert store.get("opaque/key", "frozen-version", sha256(data).hexdigest(), len(data)) == data
    store.client.get_object.assert_called_with("private", "opaque/key", version_id="frozen-version")
    response.release_conn.assert_called_once()
    with pytest.raises(MediaUnavailable):
        store.get("opaque/key", "frozen-version", "a" * 64, len(data))


def test_application_policy_excludes_deletion_public_listing_and_administration():
    policy = application_policy("private")
    actions = {a for statement in policy["Statement"] for a in statement["Action"]}
    assert actions == {"s3:GetBucketVersioning", "s3:GetBucketPolicy", "s3:PutObject", "s3:GetObjectVersion"}
    assert all("Principal" not in s for s in policy["Statement"])


@pytest.mark.parametrize(
    "change",
    [
        {"media_secure": False, "media_endpoint": "external.example:9000"},
        {"media_endpoint": "user:password@localhost:9000"},
        {"media_access_key": None},
        {"media_endpoint": "localhost:9000/path"},
    ],
)
def test_enabled_media_requires_safe_configuration(change):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://local@localhost/test",
            media_enabled=True,
            **{"media_access_key": "test", "media_secret_key": "test", **change},
        )


@pytest.mark.parametrize("kind,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
@pytest.mark.parametrize(
    "suffix",
    [
        b"unexpected payload",
        b"unexpected payload\x00\x00\x00\x00IEND\xaeB`\x82",
        b"unexpected payload\xff\xd9",
    ],
)
def test_trailing_payload_cannot_be_hidden_by_an_extra_terminator(kind, mime, suffix):
    with pytest.raises(InvalidImage):
        inspect_image(image_bytes(kind) + suffix, mime)


def test_progressive_jpeg_remains_supported():
    stream = io.BytesIO()
    Image.new("RGB", (4, 3), "blue").save(stream, format="JPEG", progressive=True)
    assert inspect_image(stream.getvalue(), "image/jpeg") == (4, 3)


def test_storage_read_policy_requires_nonempty_explicit_version():
    statements = application_policy("private")["Statement"]
    read = next(s for s in statements if s["Action"] == ["s3:GetObjectVersion"])
    assert read["Condition"]["StringLike"]["s3:versionid"] == "?*"
    assert read["Condition"]["StringNotEquals"]["s3:versionid"] == "null"
    put = next(s for s in statements if s["Action"] == ["s3:PutObject"])
    assert "Condition" not in put


def test_previously_recorded_bytes_must_pass_current_format_checks():
    from starlette.exceptions import HTTPException

    from app.media.service import checked_bytes

    data = image_bytes() + b"trailing payload accepted by an older decoder"
    store = Mock()
    store.get.return_value = data
    db = SimpleNamespace(info={"media": SimpleNamespace(store=store)})
    asset = SimpleNamespace(
        object_key="private",
        object_version="fixed",
        digest=sha256(data).hexdigest(),
        byte_length=len(data),
        mime_type="image/png",
    )
    with pytest.raises(HTTPException) as blocked:
        checked_bytes(db, asset)
    assert blocked.value.status_code == 503
