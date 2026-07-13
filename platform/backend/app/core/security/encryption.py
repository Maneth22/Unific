"""Envelope encryption for secrets held in the Account Registry (Task 1).

Credentials are encrypted at rest with a Fernet key from the environment
and are only ever decrypted through the explicit `reveal` flow in
`app.accounts.services`, which is separately permissioned and writes an
audit-log row every time. Nothing else in the codebase should import
`decrypt_secret` — encrypted values must never be assembled into a
payload sent to an LLM/agent/provider call.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_fernet = Fernet(settings.secrets_encryption_key.encode("utf-8"))


def encrypt_secret(plain_text: str) -> str:
    return _fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Could not decrypt secret — wrong key or corrupted value") from exc
