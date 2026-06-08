"""SettingsCache auto-reload on file change (#2449).

The Celery worker reads platform settings via the synchronous SettingsCache,
which previously loaded once at process start. These tests assert it now picks
up a cross-process write to the shared settings file (mtime-gated, throttled)
without an explicit refresh() — i.e. an admin change in the API process reaches
the worker without a restart.
"""

from __future__ import annotations

import os

import pytest

from app.domain.services import platform_settings_service as pss
from app.domain.services.platform_settings_service import SettingsCache, _write_overrides

_KEY = "ai-model-content"


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    f = tmp_path / "platform_settings.json"
    monkeypatch.setattr(pss, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(pss, "_SETTINGS_FILE", f)
    return f


def _write(model: str, mtime: float) -> None:
    _write_overrides({_KEY: model})
    os.utime(pss._SETTINGS_FILE, (mtime, mtime))


def test_settings_cache_auto_reloads_on_file_change(settings_file):
    cache = SettingsCache()

    _write("claude-haiku-4-5", mtime=1_000_000.0)
    cache.refresh()
    assert cache.get(_KEY) == "claude-haiku-4-5"

    # Simulate the API process writing a new value (newer mtime).
    _write("moonshot-v1-128k", mtime=1_000_100.0)
    cache._last_check = 0.0  # bypass the throttle window

    # get() reloads from the changed file without an explicit refresh().
    assert cache.get(_KEY) == "moonshot-v1-128k"


def test_settings_cache_throttles_stat_checks(settings_file):
    cache = SettingsCache()
    _write("claude-sonnet-4-6", mtime=2_000_000.0)
    cache._last_check = 0.0
    assert cache.get(_KEY) == "claude-sonnet-4-6"  # primes _last_check ~= now

    # A change within the throttle interval is not yet observed.
    _write("moonshot-v1-128k", mtime=2_000_100.0)
    assert cache.get(_KEY) == "claude-sonnet-4-6"

    # Once the throttle is cleared, the new value is picked up.
    cache._last_check = 0.0
    assert cache.get(_KEY) == "moonshot-v1-128k"
