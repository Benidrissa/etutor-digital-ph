"""Guardrail: no field on any v1 response schema may leak internal storage URLs.

MinIO is private in prod (no Traefik route). Any field containing a raw
storage URL or storage key serializes an internal Docker hostname to the
browser. The fix pattern is to expose proxy URLs via /api/v1/.../data
endpoints instead. This test fails any future schema that re-introduces
the leak.
"""

from __future__ import annotations

import importlib
import pkgutil

import pydantic

import app.api.v1.schemas as schemas_pkg

FORBIDDEN_FIELD_NAMES = {"storage_url", "storage_key", "minio_url"}

# Intentionally-allowed carry-overs: schemas where the field is kept on purpose.
# Keyed by "module.ClassName" and accompanied by a comment explaining why. New
# entries should be rare; prefer dropping the field and routing through a
# /api/v1/.../data proxy endpoint (the pattern that closed #1603/#1628).
ALLOWED_LEAKS: dict[str, set[str]] = {
    # Retained per owner decision 2026-04-18: lesson output carries a CDN URL
    # reference via SourceImageRef that the frontend renderer may consume
    # directly. Byte streams still flow through /api/v1/source-images/{id}/data.
    "app.api.v1.schemas.content.SourceImageRef": {"storage_url"},
}


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
    offenders = []
    for model in _walk_response_models():
        leaked = set(model.model_fields) & FORBIDDEN_FIELD_NAMES
        key = f"{model.__module__}.{model.__name__}"
        leaked -= ALLOWED_LEAKS.get(key, set())
        if leaked:
            offenders.append(f"{key}: {sorted(leaked)}")
    assert not offenders, (
        "Response schemas must not expose internal storage URLs or keys. "
        "Use /api/v1/.../data proxy endpoints instead. If a field is "
        "intentionally retained, add it to ALLOWED_LEAKS with a comment "
        "explaining why.\n"
        "Offenders:\n  " + "\n  ".join(offenders)
    )
