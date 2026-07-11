"""Tenant-supplied provider API keys — encrypted file store with a process cache.

A tenant admin sets their own provider keys from ``/admin/settings``; they are
Fernet-encrypted (see :mod:`app.infrastructure.crypto`) into
``config/api_keys.json`` on the ``./config:/app/config`` shared volume, so the
backend and Celery workers read the same file. Keys **override** the
reseller-provisioned env vars; env remains the fallback.

Decrypted overrides are cached in-process with a short TTL so the ~30 call sites
that read ``settings.<provider>_api_key`` don't pay decrypt cost on every access.
Cross-process changes (e.g. an update made by the web process) propagate to
Celery workers within ``_CACHE_TTL`` seconds via file re-read.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import structlog

from app.infrastructure.config.settings import settings
from app.infrastructure.crypto import decrypt_api_key, encrypt_api_key

logger = structlog.get_logger(__name__)

# Single source of truth for the provider set (the console duplicates it 6×).
PROVIDERS: list[str] = ["anthropic", "openai", "google", "resend", "moonshot"]

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_STORE_FILE = _CONFIG_DIR / "api_keys.json"
_file_lock = threading.Lock()
_CACHE_TTL = 30.0

# Env-fallback field on Settings for each provider (see settings.py properties).
_ENV_FIELD = {p: f"{p}_api_key_env" for p in PROVIDERS}


def _env_fallback(provider: str) -> str:
    return getattr(settings, _ENV_FIELD[provider], "") or ""


def _read_store() -> dict[str, str]:
    if not _STORE_FILE.exists():
        return {}
    try:
        data = json.loads(_STORE_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("api_keys.read_error", error=str(exc))
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in PROVIDERS and isinstance(v, str) and v}


def _write_store(data: dict[str, str]) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_FILE.with_suffix(".tmp")
    with _file_lock:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(_STORE_FILE)


class _DecryptCache:
    """Process-local cache of decrypted overrides with a TTL."""

    _lock = threading.Lock()
    _values: dict[str, str] = {}  # provider -> decrypted key (valid overrides only)
    _errors: set[str] = set()  # providers whose stored ciphertext failed to decrypt
    _expires_at: float = 0.0

    @classmethod
    def _refresh_locked(cls) -> None:
        store = _read_store()
        values: dict[str, str] = {}
        errors: set[str] = set()
        for provider, enc in store.items():
            try:
                values[provider] = decrypt_api_key(enc)
            except Exception:
                errors.add(provider)
        cls._values = values
        cls._errors = errors
        cls._expires_at = time.monotonic() + _CACHE_TTL

    @classmethod
    def snapshot(cls) -> tuple[dict[str, str], set[str]]:
        with cls._lock:
            if time.monotonic() >= cls._expires_at:
                cls._refresh_locked()
            return dict(cls._values), set(cls._errors)

    @classmethod
    def invalidate(cls) -> None:
        with cls._lock:
            cls._expires_at = 0.0


class ApiKeyService:
    """Read/write tenant provider keys and resolve the effective key."""

    @staticmethod
    def effective(provider: str) -> str:
        """Tenant override (decrypted) if set and valid, else the env fallback."""
        if provider not in _ENV_FIELD:
            return ""
        values, _ = _DecryptCache.snapshot()
        return values.get(provider) or _env_fallback(provider)

    @staticmethod
    def source(provider: str) -> str:
        """``"tenant"`` when a valid tenant override serves this provider, else ``"platform"``.

        Used by the AI usage ledger (#2629) to attribute spend to the paying key.
        """
        if provider not in _ENV_FIELD:
            return "platform"
        values, _ = _DecryptCache.snapshot()
        return "tenant" if values.get(provider) else "platform"

    @staticmethod
    def status() -> list[dict]:
        """Per-provider display status. Never includes the key value."""
        store = _read_store()
        values, errors = _DecryptCache.snapshot()
        out: list[dict] = []
        for provider in PROVIDERS:
            has_override = provider in store
            out.append(
                {
                    "provider": provider,
                    # A tenant-set key that decrypts cleanly.
                    "is_set": bool(values.get(provider)),
                    # Stored but undecryptable (ENCRYPTION_KEY rotated).
                    "decrypt_error": provider in errors,
                    # No tenant key, but a reseller-provisioned env key is present.
                    "env_fallback": not has_override and bool(_env_fallback(provider)),
                }
            )
        return out

    @staticmethod
    def set(provider: str, raw: str) -> None:
        if provider not in PROVIDERS:
            raise KeyError(provider)
        # encrypt_api_key raises EncryptionNotConfigured when ENCRYPTION_KEY is empty.
        encrypted = encrypt_api_key(raw)
        store = _read_store()
        store[provider] = encrypted
        _write_store(store)
        _DecryptCache.invalidate()

    @staticmethod
    def clear(provider: str) -> None:
        if provider not in PROVIDERS:
            raise KeyError(provider)
        store = _read_store()
        if store.pop(provider, None) is not None:
            _write_store(store)
        _DecryptCache.invalidate()
