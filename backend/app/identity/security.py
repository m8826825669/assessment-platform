import re
import secrets
from functools import lru_cache
from hashlib import sha256

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, type=Type.ID)
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def validate_new_password(password: str) -> None:
    if not 15 <= len(password) <= 1024:
        raise ValueError("Password must contain 15 to 1024 characters")


def hash_password(password: str) -> str:
    validate_new_password(password)
    return HASHER.hash(password)


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    return HASHER.hash(secrets.token_urlsafe(32))


def verify_password(stored_hash: str | None, supplied: str) -> bool:
    try:
        return HASHER.verify(stored_hash or dummy_password_hash(), supplied) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def token_digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)
