"""Password hashing — argon2id (current OWASP recommendation), replacing
the bcrypt used in the prototype. No plaintext password is ever logged,
stored, or included in an audit-log payload.
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, plain_password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was created with older parameters and should be
    refreshed the next time the plaintext is available (i.e. at login)."""
    return _hasher.check_needs_rehash(password_hash)
