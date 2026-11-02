"""Provision a NEW dedicated MinIO bucket and restricted application credential."""

import argparse
from getpass import getpass
from pathlib import Path

from app.config import Settings
from app.manage import configure_keys
from app.media.adapters import Gateway
from app.media.provisioning import provision, refresh_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["provision", "status", "refresh-policy"])
    args = parser.parse_args()
    try:
        settings = Settings()
        if args.command == "status":
            if not settings.media_enabled:
                raise ValueError("Media is disabled")
            result = Gateway(settings).ready()
            print("MEDIA_STORAGE=" + result["media_storage"])
            print("MEDIA_SCANNER=" + result["media_scanner"])
            return 0 if all(v == "ok" for v in result.values()) else 1
        access = getpass("Storage operator access key: ")
        secret = getpass("Storage operator secret key: ")
        if args.command == "refresh-policy":
            refresh_policy(settings, access, secret)
            print("MEDIA_APPLICATION_POLICY=UPDATED; credentials/bucket/objects/database unchanged")
            return 0
        app_access, app_secret = provision(
            settings.media_endpoint, access, secret, settings.media_bucket, settings.media_secure
        )
        configure_keys(
            Path.cwd() / ".env",
            {
                "ASSESSMENT_MEDIA_ENABLED": "true",
                "ASSESSMENT_MEDIA_ACCESS_KEY": app_access,
                "ASSESSMENT_MEDIA_SECRET_KEY": app_secret,
            },
            ".env.pre-p2-005",
        )
        print("MEDIA_BUCKET_AND_RESTRICTED_CREDENTIAL=READY")
        print("ENV_CONFIGURATION=UPDATED; database credentials unchanged")
        return 0
    except Exception as error:
        # SDK exceptions can include endpoint/key details; suppress them at this operator boundary.
        print(
            "MEDIA_OPERATION=FAILED; "
            + type(error).__name__
            + "; check private storage configuration and connectivity"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
