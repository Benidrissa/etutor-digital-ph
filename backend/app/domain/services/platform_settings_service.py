"""Platform settings service — JSON file-based with Redis cache.

Settings live in ``config/platform_settings.json``.  The file stores
only admin overrides; missing keys fall back to compiled defaults.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import structlog

from app.infrastructure.config.platform_defaults import (
    CATEGORIES,
    DEFAULTS_BY_KEY,
    SETTING_DEFINITIONS,
    SettingDef,
)

logger = structlog.get_logger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_SETTINGS_FILE = _CONFIG_DIR / "platform_settings.json"
_REDIS_PREFIX = "platform_setting:"
_REDIS_TTL = 300
_file_lock = threading.Lock()


def _validate_value(defn: SettingDef, raw: Any) -> Any:
    vtype = defn.value_type
    if vtype == "integer":
        val = int(raw)
    elif vtype == "float":
        val = float(raw)
    elif vtype == "boolean":
        if not isinstance(raw, bool):
            raise ValueError(f"Expected boolean for '{defn.key}'")
        val = raw
    elif vtype == "json":
        if not isinstance(raw, (dict, list)):
            raise ValueError(f"Expected dict/list for '{defn.key}'")
        val = raw
    else:
        val = str(raw)

    rules = defn.validation
    if rules:
        lo, hi = rules.get("min"), rules.get("max")
        if lo is not None and isinstance(val, (int, float)) and val < lo:
            raise ValueError(f"'{defn.key}' must be >= {lo}")
        if hi is not None and isinstance(val, (int, float)) and val > hi:
            raise ValueError(f"'{defn.key}' must be <= {hi}")
    return val


def _read_overrides() -> dict[str, Any]:
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(_SETTINGS_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("platform_settings.read_error", error=str(exc))
        return {}


def _write_overrides(data: dict[str, Any]) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _SETTINGS_FILE.with_suffix(".tmp")
    with _file_lock:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(_SETTINGS_FILE)


class SettingsCache:
    """Process-local cache for synchronous access."""

    _instance: SettingsCache | None = None
    _data: dict[str, Any] = {}

    @classmethod
    def instance(cls) -> SettingsCache:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def refresh(self) -> None:
        overrides = _read_overrides()
        self._data = {d.key: overrides.get(d.key, d.default) for d in SETTING_DEFINITIONS}
        logger.debug("settings_cache.refreshed", count=len(self._data))


class PlatformSettingsService:
    """Async service for reading/writing platform settings."""

    async def get(self, key: str) -> Any:
        defn = DEFAULTS_BY_KEY.get(key)
        if defn is None:
            return None
        try:
            from app.infrastructure.cache.redis import redis_client

            cached = await redis_client.get(f"{_REDIS_PREFIX}{key}")
            if cached is not None:
                return json.loads(cached)
        except Exception:
            pass
        overrides = _read_overrides()
        val = overrides.get(key, defn.default)
        try:
            from app.infrastructure.cache.redis import redis_client

            await redis_client.setex(f"{_REDIS_PREFIX}{key}", _REDIS_TTL, json.dumps(val))
        except Exception:
            pass
        return val

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        overrides = _read_overrides()
        return {
            k: overrides.get(k, DEFAULTS_BY_KEY[k].default) for k in keys if k in DEFAULTS_BY_KEY
        }

    async def get_by_category(self, category: str) -> list[dict[str, Any]]:
        overrides = _read_overrides()
        return [
            self._to_dict(d, overrides.get(d.key, d.default))
            for d in SETTING_DEFINITIONS
            if d.category == category
        ]

    async def get_all(self) -> list[dict[str, Any]]:
        overrides = _read_overrides()
        return [self._to_dict(d, overrides.get(d.key, d.default)) for d in SETTING_DEFINITIONS]

    async def get_all_public(self) -> dict[str, Any]:
        overrides = _read_overrides()
        return {
            d.key: overrides.get(d.key, d.default)
            for d in SETTING_DEFINITIONS
            if not d.is_sensitive
        }

    async def set(self, key: str, value: Any) -> dict[str, Any]:
        defn = DEFAULTS_BY_KEY.get(key)
        if defn is None:
            raise KeyError(f"Setting '{key}' not found")
        validated = _validate_value(defn, value)
        overrides = _read_overrides()
        overrides[key] = validated
        _write_overrides(overrides)
        try:
            from app.infrastructure.cache.redis import redis_client

            await redis_client.delete(f"{_REDIS_PREFIX}{key}")
        except Exception:
            pass
        SettingsCache.instance().refresh()
        return self._to_dict(defn, validated)

    async def reset_to_default(self, key: str) -> dict[str, Any]:
        defn = DEFAULTS_BY_KEY.get(key)
        if defn is None:
            raise KeyError(f"Setting '{key}' not found")
        overrides = _read_overrides()
        overrides.pop(key, None)
        _write_overrides(overrides)
        try:
            from app.infrastructure.cache.redis import redis_client

            await redis_client.delete(f"{_REDIS_PREFIX}{key}")
        except Exception:
            pass
        SettingsCache.instance().refresh()
        return self._to_dict(defn, defn.default)

    async def reset_category(self, category: str) -> int:
        overrides = _read_overrides()
        keys = [d.key for d in SETTING_DEFINITIONS if d.category == category and d.key in overrides]
        for k in keys:
            del overrides[k]
        if keys:
            _write_overrides(overrides)
            try:
                from app.infrastructure.cache.redis import redis_client

                await redis_client.delete(*[f"{_REDIS_PREFIX}{k}" for k in keys])
            except Exception:
                pass
            SettingsCache.instance().refresh()
        return len(keys)

    @staticmethod
    def _to_dict(defn: SettingDef, current: Any) -> dict[str, Any]:
        return {
            "key": defn.key,
            "category": defn.category,
            "value": current,
            "default_value": defn.default,
            "value_type": defn.value_type,
            "label": defn.label,
            "description": defn.description,
            "validation_rules": defn.validation,
            "is_sensitive": defn.is_sensitive,
            "is_default": current == defn.default,
        }

    @staticmethod
    def categories() -> list[str]:
        return CATEGORIES
