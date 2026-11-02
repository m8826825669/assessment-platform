"""Version-specific S3 reads and bounded ClamAV INSTREAM; no public object URLs."""

import io
import socket
import struct
import warnings
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import urllib3
from minio import Minio
from minio.error import MinioException, S3Error
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000


class MediaUnavailable(Exception):
    """Safe boundary: never include storage keys, credentials or scanner replies."""


class InvalidImage(ValueError):
    pass


def strict_container(data, kind):
    """Reject bytes after the first structural image terminator; Pillow handles decoding/CRC checks."""
    if kind == "PNG":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise InvalidImage("Invalid PNG signature")
        position = 8
        while position + 12 <= len(data):
            length = struct.unpack_from("!I", data, position)[0]
            end = position + 12 + length
            if end > len(data):
                break
            if data[position + 4 : position + 8] == b"IEND":
                if length == 0 and end == len(data):
                    return
                break
            position = end
        raise InvalidImage("PNG must end at its first IEND")
    if not data.startswith(b"\xff\xd8"):
        raise InvalidImage("Invalid JPEG signature")
    position = 2
    while position < len(data):
        if data[position] != 255:
            break
        while position < len(data) and data[position] == 255:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker == 217:
            if position == len(data):
                return
            break
        if marker in {0, 216}:
            break
        if marker == 1 or 208 <= marker <= 215:
            continue
        if position + 2 > len(data):
            break
        length = struct.unpack_from("!H", data, position)[0]
        if length < 2 or position + length > len(data):
            break
        position += length
        if marker == 218:  # Entropy-coded scan: skip stuffed bytes and restart markers.
            while position < len(data):
                position = data.find(b"\xff", position)
                if position < 0:
                    raise InvalidImage("Missing JPEG terminator")
                start = position
                while position < len(data) and data[position] == 255:
                    position += 1
                if position >= len(data):
                    break
                if data[position] == 0 or 208 <= data[position] <= 215:
                    position += 1
                    continue
                position = start
                break
    raise InvalidImage("JPEG must end at its first EOI")


def inspect_image(data, mime):
    if not data or len(data) > MAX_BYTES:
        raise InvalidImage("Image size is outside the supported bounds")
    expected = {"image/png": "PNG", "image/jpeg": "JPEG"}.get(mime)
    if expected is None:
        raise InvalidImage("Unsupported image type")
    strict_container(data, expected)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if (
                    image.format != expected
                    or image.width * image.height > MAX_PIXELS
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise InvalidImage("Unsupported or oversized image")
                size = image.size
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        return size
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        ValueError,
    ) as error:
        raise InvalidImage("Invalid image") from error


class ObjectStore:
    def __init__(self, settings):
        self.bucket = settings.media_bucket
        self.client = Minio(
            settings.media_endpoint,
            access_key=settings.media_access_key.get_secret_value(),
            secret_key=settings.media_secret_key.get_secret_value(),
            secure=settings.media_secure,
            region=settings.media_region,
            http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=3, read=15), retries=False),
        )

    def ready(self):
        try:
            if self.client.get_bucket_versioning(self.bucket).status != "Enabled":
                raise MediaUnavailable()
            # No bucket policy may grant anonymous or public reads.
            try:
                import json

                policy = json.loads(self.client.get_bucket_policy(self.bucket))
            except S3Error as error:
                if error.code != "NoSuchBucketPolicy":
                    raise
                policy = {}
            if policy.get("Statement"):
                raise MediaUnavailable()
        except (MinioException, urllib3.exceptions.HTTPError, OSError, ValueError) as error:
            raise MediaUnavailable() from error

    def put(self, key, data, mime):
        try:
            self.ready()
            result = self.client.put_object(
                self.bucket, key, io.BytesIO(data), len(data), content_type=mime, part_size=16 * 1024 * 1024
            )
            if not result.version_id or result.version_id == "null":
                raise MediaUnavailable()
            return result.version_id
        except (MinioException, urllib3.exceptions.HTTPError, OSError, ValueError) as error:
            raise MediaUnavailable() from error

    def get(self, key, version, digest, length):
        response = None
        try:
            if not version or version == "null" or not 1 <= length <= MAX_BYTES:
                raise MediaUnavailable()
            response = self.client.get_object(self.bucket, key, version_id=version)
            data = response.read(MAX_BYTES + 1)
            if len(data) != length or sha256(data).hexdigest() != digest:
                raise MediaUnavailable()
            return data
        except (MinioException, urllib3.exceptions.HTTPError, OSError, ValueError) as error:
            raise MediaUnavailable() from error
        finally:
            if response is not None:
                response.close()
                response.release_conn()


class Scanner:
    def __init__(self, settings):
        self.host = settings.media_scanner_host
        self.port = settings.media_scanner_port
        self.max_age = settings.media_signature_max_age_days

    def exchange(self, command, data=None):
        try:
            with socket.create_connection((self.host, self.port), timeout=3) as connection:
                connection.settimeout(15)
                connection.sendall(b"z" + command + b"\0")
                if data is not None:
                    if len(data) > MAX_BYTES:
                        raise MediaUnavailable()
                    for offset in range(0, len(data), 65536):
                        chunk = data[offset : offset + 65536]
                        connection.sendall(struct.pack("!I", len(chunk)) + chunk)
                    connection.sendall(b"\0\0\0\0")
                result = bytearray()
                while len(result) <= 4096:
                    chunk = connection.recv(4096 - len(result) + 1)
                    if not chunk:
                        break
                    result.extend(chunk)
                    if b"\0" in result:
                        break
                if not result.endswith(b"\0") or len(result) > 4096:
                    raise MediaUnavailable()
                return bytes(result[:-1]).decode("ascii")
        except (OSError, UnicodeError) as error:
            raise MediaUnavailable() from error

    def ready(self):
        if self.exchange(b"PING") != "PONG":
            raise MediaUnavailable()
        version = self.exchange(b"VERSION")
        try:
            engine, signature, date = version.split("/", 2)
            stamp = datetime.strptime(date.strip(), "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC)
            now = datetime.now(UTC)
            if (
                not engine.startswith("ClamAV ")
                or not signature.isdecimal()
                or not now - timedelta(days=self.max_age) <= stamp <= now + timedelta(hours=24)
            ):
                raise ValueError()
        except ValueError as error:
            raise MediaUnavailable() from error
        return version[:200]

    def scan(self, data):
        version = self.ready()
        result = self.exchange(b"INSTREAM", data)
        if result == "stream: OK":
            return "clean", version
        if result.startswith("stream: ") and result.endswith(" FOUND"):
            return "rejected", version
        raise MediaUnavailable()


class Gateway:
    def __init__(self, settings):
        self.store = ObjectStore(settings)
        self.scanner = Scanner(settings)

    def ready(self):
        result = {}
        for name, adapter in [("media_storage", self.store), ("media_scanner", self.scanner)]:
            try:
                adapter.ready()
                result[name] = "ok"
            except MediaUnavailable:
                result[name] = "unavailable"
        return result
