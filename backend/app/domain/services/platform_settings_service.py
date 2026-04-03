"""Platform settings service — JSON file-based with Redis cache.

Settings live in a JSON file (``config/platform_settings.json``
next to the backend root).  The file stores only admin overrides;
any key absent from the file falls back to the compiled default
in ``platform_defaults.py``.

Read path:  in-memory dict → Redis → JSON file → compiled default.
Write path: validate → write JSON file → invalidate Redis + memory.
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

# Path to the overrides file (relative to backend/)
_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_SETTINGS_FILE = _CONFIG_DIR / "platform_settings.json"

_REDIS_PREFIX = "platform_setting:"
_REDIS_TTL = 300  # 5 minutes


# ── Validation ─────────────────────────────────────────────────


def _validate_value(defn: SettingDef, raw: Any) -> Any:
    """Validate and coerce *raw* against the setting definition.
    Returns the coerced value or raises ``ValueError``.
    """
    vtype = defn.value_type

    if vtype == "integer":
        try:
            val = int(raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"Expected integer for '{defn.key}', "
                f"got {type(raw).__name__}"
            )
    elif vtype == "float":
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"Expected float for '{defn.key}', "
                f"got {type(raw).__name__}"
            )
    elif vtype == "boolean":
        if not isinstance(raw, bool):
            raise ValueError(
                f"Expected boolean for '{defn.key}'"
            )
        val = raw
    elif vtype == "string":
        val = str(raw)
    elif vtype == "json":
        if not isinstance(raw, (dict, list)):
            raise ValueError(
                f"Expected dict or list for '{defn.key}'"
            )
        val = raw
    else:
        val = raw

    # Range check
    rules = defn.validation
    if rules:
        lo = rules.get("min")
        hi = rules.get("max")
        if lo is not None and isinstance(val, (int, float)):
            if val < lo:
                raise ValueError(f"'{defn.key}' must be >= {lo}")
        if hi is not None and isinstance(val, (int, float)):
            if val > hi:
                raise ValueError(f"'{defn.key}' must be <= {hi}")

    return val


# ── File I/O ───────────────────────────────────────────────────

_file_lock = threading.Lock()


def _read_overrides() -> dict[str, Any]:
    """Read the JSON overrides file.  Returns ``{}`` if absent."""
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(_SETTINGS_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "platform_settings.read_error", error=str(exc),
        )
        return {}


def _write_overrides(data: dict[str, Any]) -> None:
    """Atomically write overrides to the JSON file."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _SETTINGS_FILE.with_suffix(".tmp")
    with _file_lock:
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(_SETTINGS_FILE)


# ── In-Memory Cache (sync access) ─────────────────────────────


class SettingsCache:
    """Process-local cache for synchronous access.

    Used by middleware and auth code that cannot await.
    Loaded at app startup.
    """

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
        """Reload from JSON file + compiled defaults."""
        overrides = _read_overrides()
        merged: dict[str, Any] = {}
        for defn in SETTING_DEFINITIONS:
            merged[defn.key] = overrides.get(
                defn.key, defn.default,
            )
        self._data = merged
        logger.debug(
            "settings_cache.refreshed",
            count=len(self._data),
        )


# ── Async Service (for API endpoints / services) ──────────────


class PlatformSettingsService:
    """Async service for reading and writing platform settings.

    No database dependency.  Redis is used only as a hot cache.
    """

    # ── Read ───────────────────────────────────────────────

    async def get(self, key: str) -> Any:
        """Return the current value for *key*.

        Falls back to compiled default if no override exists.
        Returns ``None`` if the key is unknown.
        """
        defn = DEFAULTS_BY_KEY.get(key)
        if defn is None:
            return None

        # 1. Redis cache
        try:
            from app.infrastructure.cache.redis import (
                redis_client,
            )

            cached = await redis_client.get(
                f"{_REDIS_PREFIX}{key}"
            )
            if cached is not None:
                return json.loads(cached)
        except Exception:
            pass  # Redis down — fall through

        # 2. JSON file
        overrides = _read_overrides()
        val = overrides.get(key, defn.default)

        # Populate Redis
        try:
            from app.infrastructure.cache.redis import (
                redis_client,
            )

            await redis_client.setex(
                f"{_REDIS_PREFIX}{key}",
                _REDIS_TTL,
                json.dumps(val),
            )
        except Exception:
            pass

        return val

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Batch-fetch multiple settings."""
        overrides = _read_overrides()
        result: dict[str, Any] = {}
        for key in keys:
            defn = DEFAULTS_BY_KEY.get(key)
            if defn is not None:
                result[key] = overrides.get(key, defn.default)
        return result

    async def get_by_category(
        self, category: str,
    ) -> list[dict[str, Any]]:
        """Return all settings in a category with metadata."""
        overrides = _read_overrides()
        results = []
        for defn in SETTING_DEFINITIONS:
            if defn.category != category:
                continue
            current = overrides.get(defn.key, defn.default)
            results.append(self._to_dict(defn, current))
        return results

    async def get_all(self) -> list[dict[str, Any]]:
        """Return every setting with metadata."""
        overrides = _read_overrides()
        return [
            self._to_dict(defn, overrides.get(defn.key, defn.default))
            for defn in SETTING_DEFINITIONS
        ]

    async def get_all_public(self) -> dict[str, Any]:
        """Non-sensitive settings as a flat dict for frontend."""
        overrides = _read_overrides()
        return {
            defn.key: overrides.get(defn.key, defn.default)
            for defn in SETTING_DEFINITIONS
            if not defn.is_sensitive
        }

    # ── Write ──────────────────────────────────────────────

    async def set(self, key: str, value: Any) -> dict[str, Any]:
        """Update a setting's value.

        Validates, writes to JSON file, and invalidates caches.
        Returns the updated setting dict.
        """
        defn = DEFAULTS_BY_KEY.get(key)
        if defn is None:
            raise KeyError(f"Setting '{key}' not found")

        validated = _validate_value(defn, value)

        overrides = _read_overrides()
        overrides[key] = validated
        _write_overrides(overrides)

        # Invalidate Redis
        try:
            from app.infrastructure.cache.redis import (
                redis_client,
            )

            await redis_client.delete(f"{_REDIS_PREFIX}{key}")
        except Exception:
            pass

        # Refresh in-memory cache
        SettingsCache.instance().refresh()

        logger.info("platform_setting.updated", key=key)
        return self._to_dict(defn, validated)

    async def reset_to_default(self, key: str) -> dict[str, Any]:
        """Remove the override for *key* (revert to default)."""
        defn = DEFAULTS_BY_KEY.get(key)
        if defn is None:
            raise KeyError(f"Setting '{key}' not found")

        overrides = _read_overrides()
        overrides.pop(key, None)
        _write_overrides(overrides)

        try:
            from app.infrastructure.cache.redis import (
                redis_client,
            )

            await redis_client.delete(f"{_REDIS_PREFIX}{key}")
        except Exception:
            pass

        SettingsCache.instance().refresh()

        logger.info("platform_setting.reset", key=key)
        return self._to_dict(defn, defn.default)

    async def reset_category(self, category: str) -> int:
        """Reset all settings in a category. Returns count."""
        overrides = _read_overrides()
        count = 0
        keys_to_delete = []

        for defn in SETTING_DEFINITIONS:
            if defn.category == category and defn.key in overrides:
                del overrides[defn.key]
                keys_to_delete.append(
                    f"{_REDIS_PREFIX}{defn.key}"
                )
                count += 1

        if count:
            _write_overrides(overrides)
            try:
                from app.infrastructure.cache.redis import (
                    redis_client,
                )

                if keys_to_delete:
                    await redis_client.delete(*keys_to_delete)
            except Exception:
                pass
            SettingsCache.instance().refresh()

        logger.info(
            "platform_setting.category_reset",
            category=category, count=count,
        )
        return count

    # ── Helpers ────────────────────────────────────────────

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
