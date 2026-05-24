"""Guardrail: no field on any v1 response schema may leak internal storage URLs.

MinIO is private in prod (no Traefik route). Any field containing a raw
storage URL or storage key serializes an internal Docker hostname to the
browser. The fix pattern is to expose proxy URLs via /api/v1/.../data
endpoints instead. This test fails any future schema that re-introduces
the leak (#1610).

Two rules enforced statically:
1. No field named ``storage_url``, ``storage_key``, or ``minio_url``.
2. No field whose *default* is a string matching ``http(s)?://.*minio``.
"""

from __future__ import annotations

import importlib
import pkgutil
import re

import pydantic

import app.api.v1.schemas as schemas_pkg

FORBIDDEN_FIELD_NAMES = frozenset({"storage_url", "storage_key", "minio_url"})
_MINIO_URL_RE = re.compile(r"https?://.*minio", re.IGNORECASE)


def _walk_response_models() -> list[type[pydantic.BaseModel]]:
    models: list[type[pydantic.BaseModel]] = []
    pkg_path = schemas_pkg.__path__
    pkg_name = schemas_pkg.__name__
    for _, mod_name, _ in pkgutil.iter_modules(pkg_path, pkg_name + "."):
        mod = importlib.import_module(mod_name)
        for attr in vars(mod).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, pydantic.BaseModel)
                and attr is not pydantic.BaseModel
            ):
                models.append(attr)
    return models


def test_no_storage_url_or_key_field_in_v1_schemas():
    """No response schema should expose raw storage_url / storage_key / minio_url.

    All known violations have been cleaned up:
    - SourceImageRef.storage_url / storage_url_fr removed (#1610): frontend
      uses /api/v1/source-images/{id}/data proxy URL via the ``id`` field.

    If you need to add a truly exceptional allow-list entry, add it here with
    a comment and owner sign-off.
    """
    offenders = []
    for model in _walk_response_models():
        leaked = set(model.model_fields) & FORBIDDEN_FIELD_NAMES
        if leaked:
            offenders.append(f"{model.__module__}.{model.__name__}: {sorted(leaked)}")
    assert not offenders, (
        "Response schemas must not expose internal storage URLs or keys. "
        "Use /api/v1/.../data proxy endpoints instead.\n"
        "Offenders:\n  " + "\n  ".join(offenders)
    )


def test_no_minio_url_as_default():
    """No field default may hard-code an internal http://minio URL."""
    offenders = []
    for model in _walk_response_models():
        for field_name, field_info in model.model_fields.items():
            default = field_info.default
            if isinstance(default, str) and _MINIO_URL_RE.search(default):
                offenders.append(f"{model.__module__}.{model.__name__}.{field_name}: {default!r}")
    assert not offenders, (
        "Schema fields must not have internal MinIO URLs as defaults:\n  " + "\n  ".join(offenders)
    )
