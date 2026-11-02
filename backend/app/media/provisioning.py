"""Operator-only storage provisioning; never imported by HTTP routes."""

from secrets import token_urlsafe
from uuid import uuid4

import urllib3
from minio import Minio
from minio.credentials import StaticProvider
from minio.minioadmin import MinioAdmin
from minio.versioningconfig import ENABLED, VersioningConfig


def application_policy(bucket):
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetBucketVersioning", "s3:GetBucketPolicy"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:PutObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/authoring/*"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObjectVersion"],
                "Resource": [f"arn:aws:s3:::{bucket}/authoring/*"],
                # MinIO also matches GetObject through GetObjectVersion. Bind the request to a real version ID.
                "Condition": {
                    "StringLike": {"s3:versionid": "?*"},
                    "StringNotEquals": {"s3:versionid": "null"},
                },
            },
        ],
    }


def clients(endpoint, access, secret, secure):
    pool = urllib3.PoolManager(timeout=urllib3.Timeout(connect=3, read=15), retries=False)
    store = Minio(
        endpoint, access_key=access, secret_key=secret, secure=secure, region="us-east-1", http_client=pool
    )
    admin = MinioAdmin(
        endpoint=endpoint,
        credentials=StaticProvider(access, secret),
        secure=secure,
        region="us-east-1",
        http_client=pool,
    )
    return store, admin


def provision(endpoint, root_access, root_secret, bucket, secure=True):
    store, admin = clients(endpoint, root_access, root_secret, secure)
    if store.bucket_exists(bucket):
        raise ValueError("Refusing to change an existing bucket; select a new dedicated bucket")
    store.make_bucket(bucket)
    store.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
    name, secret = "assess_" + uuid4().hex[:12], token_urlsafe(40)
    # No anonymous policy. No object listing/deletion/latest-version GET or bucket administration.
    admin.policy_add(name, policy=application_policy(bucket))
    admin.user_add(name, secret)
    admin.policy_set(name, user=name)
    return name, secret


def refresh_policy(settings, root_access, root_secret):
    import json
    import re

    if not settings.media_enabled or not settings.media_access_key:
        raise ValueError("Configured media application credential required")
    name = settings.media_access_key.get_secret_value()
    if not re.fullmatch(r"assess_[0-9a-f]{12}", name):
        raise ValueError("Refusing to change an unknown storage principal")
    store, admin = clients(settings.media_endpoint, root_access, root_secret, settings.media_secure)
    if not store.bucket_exists(settings.media_bucket):
        raise ValueError("Configured media bucket missing")
    user = json.loads(admin.user_info(name))
    if user.get("policyName") != name:
        raise ValueError("Refusing to replace an unexpected policy assignment")
    # Replace only this known application's policy. No bucket/object/credential changes.
    admin.policy_add(name, policy=application_policy(settings.media_bucket))
