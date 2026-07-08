"""Symmetric encryption for tenant-supplied secrets (provider API keys).

Mirrors the reseller console's ``app/core/security.py`` Fernet helpers so that a
key encrypted on either side uses the same derivation. The key material comes
from ``settings.encryption_key`` (env ``ENCRYPTION_KEY``); it is padded/truncated
to 32 bytes and urlsafe-base64-encoded to satisfy Fernet.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet

from app.infrastructure.config.settings import settings


class EncryptionNotConfigured(RuntimeError):
    """Raised when an encryption operation is attempted with no ENCRYPTION_KEY set."""


class ApiKeyDecryptError(ValueError):
    """Raised when an encrypted API key cannot be decrypted with the current ENCRYPTION_KEY.

    This almost always means the ENCRYPTION_KEY was rotated after the key was
    stored. The tenant admin must re-enter the affected keys via the admin UI.
    """


def _get_fernet() -> Fernet:
    raw = settings.encryption_key
    if not raw:
        raise EncryptionNotConfigured("ENCRYPTION_KEY is not set")
    # Pad/truncate to 32 bytes, then urlsafe-base64 encode for Fernet.
    key_bytes = raw.encode().ljust(32, b"\0")[:32]
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_api_key(api_key: str) -> str:
    return _get_fernet().encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except EncryptionNotConfigured:
        raise
    except Exception as exc:  # cryptography.fernet.InvalidToken and friends
        raise ApiKeyDecryptError(str(exc)) from exc
