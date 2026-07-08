"""Unit tests for tenant-supplied provider API keys (crypto + resolution).

No DB — the store is a JSON file and env fallbacks come from Settings, so these
tests monkeypatch the store path and the ENCRYPTION_KEY/env fields directly.
"""

import importlib

import pytest

import app.domain.services.api_key_service as svc
from app.infrastructure.config.settings import settings


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the service at a throwaway store file and ensure encryption is on."""
    monkeypatch.setattr(svc, "_STORE_FILE", tmp_path / "api_keys.json")
    monkeypatch.setattr(settings, "encryption_key", "unit-test-encryption-key")
    svc._DecryptCache.invalidate()
    yield
    svc._DecryptCache.invalidate()


def test_encrypt_decrypt_roundtrip(store):
    crypto = importlib.import_module("app.infrastructure.crypto")
    enc = crypto.encrypt_api_key("sk-secret-123")
    assert enc != "sk-secret-123"
    assert crypto.decrypt_api_key(enc) == "sk-secret-123"


def test_wrong_key_raises_decrypt_error(store, monkeypatch):
    crypto = importlib.import_module("app.infrastructure.crypto")
    enc = crypto.encrypt_api_key("sk-secret-123")
    monkeypatch.setattr(settings, "encryption_key", "a-different-key")
    with pytest.raises(crypto.ApiKeyDecryptError):
        crypto.decrypt_api_key(enc)


def test_encrypt_without_key_raises(store, monkeypatch):
    crypto = importlib.import_module("app.infrastructure.crypto")
    monkeypatch.setattr(settings, "encryption_key", "")
    with pytest.raises(crypto.EncryptionNotConfigured):
        crypto.encrypt_api_key("sk-secret")


def test_effective_falls_back_to_env(store, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key_env", "env-anthropic")
    assert svc.ApiKeyService.effective("anthropic") == "env-anthropic"
    # And the Settings property resolves through the same path.
    assert settings.anthropic_api_key == "env-anthropic"


def test_override_takes_precedence_over_env(store, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key_env", "env-openai")
    svc.ApiKeyService.set("openai", "tenant-openai")
    assert svc.ApiKeyService.effective("openai") == "tenant-openai"
    assert settings.openai_api_key == "tenant-openai"


def test_clear_reverts_to_env(store, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key_env", "env-openai")
    svc.ApiKeyService.set("openai", "tenant-openai")
    svc.ApiKeyService.clear("openai")
    assert svc.ApiKeyService.effective("openai") == "env-openai"


def test_status_never_leaks_value(store):
    svc.ApiKeyService.set("anthropic", "tenant-anthropic-secret")
    rows = svc.ApiKeyService.status()
    serialized = str(rows)
    assert "tenant-anthropic-secret" not in serialized
    by_provider = {r["provider"] for r in rows}
    assert by_provider == set(svc.PROVIDERS)
    anthropic = next(r for r in rows if r["provider"] == "anthropic")
    assert anthropic["is_set"] is True
    assert anthropic["decrypt_error"] is False


def test_status_flags_decrypt_error(store, monkeypatch):
    svc.ApiKeyService.set("google", "tenant-google")
    # Rotate the key so the stored ciphertext no longer decrypts.
    monkeypatch.setattr(settings, "encryption_key", "rotated-key")
    svc._DecryptCache.invalidate()
    google = next(r for r in svc.ApiKeyService.status() if r["provider"] == "google")
    assert google["decrypt_error"] is True
    assert google["is_set"] is False


def test_status_reports_env_fallback(store, monkeypatch):
    monkeypatch.setattr(settings, "google_api_key_env", "env-google")
    google = next(r for r in svc.ApiKeyService.status() if r["provider"] == "google")
    assert google["is_set"] is False
    assert google["env_fallback"] is True
