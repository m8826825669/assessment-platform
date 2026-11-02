"""Mandatory live S3-compatible store/ClamAV tests; never silently skip missing services."""

import io
import os
from uuid import uuid4

import pytest
from minio import Minio
from minio.deleteobjects import DeleteObject
from minio.error import S3Error
from test_authoring_media import clean, decide, path, png, prepare, question, reserve, upload

from app.config import Settings
from app.media.adapters import Gateway
from app.media.provisioning import clients, provision

pytestmark = pytest.mark.integration


@pytest.fixture
def live_media(security_database):
    if os.environ.get("ASSESSMENT_ALLOW_TEST_MEDIA_CREATION") != "1":
        pytest.fail("Set ASSESSMENT_ALLOW_TEST_MEDIA_CREATION=1 for isolated media fixtures")
    endpoint = os.environ.get("ASSESSMENT_TEST_MEDIA_ENDPOINT", "127.0.0.1:19010")
    # Disposable loopback fixture only; never fall back to application or production storage.
    if endpoint not in {"127.0.0.1:19010", "localhost:19010"}:
        pytest.fail("Live media fixture requires the dedicated loopback port 19010")
    root_access = "assessment_test_operator"
    root_secret = "assessment_test_disposable_only"
    bucket = "assessment-test-" + uuid4().hex
    store, admin = clients(endpoint, root_access, root_secret, False)
    access = None
    try:
        try:
            access, secret = provision(endpoint, root_access, root_secret, bucket, False)
        except Exception:
            pytest.fail(
                "Dedicated test object store unavailable; start compose.media.yaml first", pytrace=False
            )
        settings = Settings(
            _env_file=None,
            database_url=security_database.runtime_url,
            media_enabled=True,
            media_endpoint=endpoint,
            media_secure=False,
            media_bucket=bucket,
            media_access_key=access,
            media_secret_key=secret,
        )
        gateway = Gateway(settings)
        assert gateway.ready() == {"media_storage": "ok", "media_scanner": "ok"}, (
            "Storage/scanner not ready; check ClamAV signature freshness"
        )
        security_database.client.app.state.media = gateway
        yield security_database, gateway, store, bucket
    finally:
        security_database.client.app.state.media = None
        if access:
            admin.user_remove(access)
            admin.policy_remove(access)
            errors = list(
                store.remove_objects(
                    bucket,
                    [
                        DeleteObject(o.object_name, version_id=o.version_id)
                        for o in store.list_objects(bucket, recursive=True, include_version=True)
                    ],
                )
            )
            assert not errors, "Disposable media version cleanup failed"
            store.remove_bucket(bucket)


def test_live_storage_scan_download_version_binding_and_storage_privileges(live_media):
    db, gateway, root, bucket = live_media
    admin, reviewer, coordinator = prepare(db)
    asset = clean(db, admin)
    saved = question(db, admin, [asset["asset_id"]])
    assert saved.status_code == 201, saved.text
    submitted = decide(db, admin, saved.json(), "submit")
    assert submitted.status_code == 200, submitted.text
    approved = decide(db, reviewer, submitted.json(), "approve")
    assert approved.status_code == 200, approved.text
    selected = db.client.get(path(db, kind="question-selections"), headers=coordinator)
    assert selected.status_code == 200 and selected.json()[0]["media"] == saved.json()["media"]
    objects = list(root.list_objects(bucket, recursive=True, include_version=True))
    assert len(objects) == 1 and objects[0].version_id
    original = objects[0]
    # Even an operator's new version of the same key cannot replace the frozen reference.
    root.put_object(bucket, original.object_name, io.BytesIO(b"changed"), 7)
    response = db.client.get(path(db, "/" + asset["asset_id"] + "/content"), headers=admin)
    assert response.status_code == 200 and response.content == png()
    with pytest.raises(S3Error) as denied:
        gateway.store.client.remove_object(bucket, original.object_name, version_id=original.version_id)
    assert denied.value.code == "AccessDenied"
    with pytest.raises(S3Error):
        list(gateway.store.client.list_objects(bucket))
    with pytest.raises(S3Error):
        unexpected = gateway.store.client.get_object(bucket, original.object_name)
        unexpected.close()
        unexpected.release_conn()
    anonymous = Minio("127.0.0.1:19010", secure=False, region="us-east-1")
    with pytest.raises(S3Error):
        anonymous.get_object(bucket, original.object_name, version_id=original.version_id)
    # A deliberately deleted exact version is blocked, rather than falling back to latest.
    root.remove_object(bucket, original.object_name, version_id=original.version_id)
    assert db.client.get(path(db, "/" + asset["asset_id"] + "/content"), headers=admin).status_code == 503


def test_live_clamav_standard_eicar_and_trailing_payload_rejection(live_media):
    db, gateway, _, _ = live_media
    admin = db.login("admin_a")
    # Standard harmless antivirus test string, split to avoid distributing it as a test file.
    eicar = b"X5O!P%@AP[4" + b"\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    assert gateway.scanner.scan(eicar)[0] == "rejected"
    asset = reserve(db, admin)
    # EICAR only guarantees detection at the start of the test file. Appended payloads are rejected by format validation.
    response = upload(db, admin, asset, png() + eicar)
    assert response.status_code == 422, response.text
    assert db.client.get(path(db, "/" + asset["asset_id"]), headers=admin).json()["state"] == "pending"
    assert question(db, admin, [asset["asset_id"]]).status_code == 409
    assert db.client.get(path(db, "/" + asset["asset_id"] + "/content"), headers=admin).status_code == 409
