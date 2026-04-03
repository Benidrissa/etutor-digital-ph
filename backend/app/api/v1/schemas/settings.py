"""Pydantic schemas for platform settings endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SettingResponse(BaseModel):
    key: str
    category: str
    value: Any
    default_value: Any
    value_type: str
    label: str
    description: str
    validation_rules: dict | None = None
    is_sensitive: bool = False
    is_default: bool = True


class SettingUpdateRequest(BaseModel):
    value: Any


class SettingsByCategoryResponse(BaseModel):
    category: str
    settings: list[SettingResponse]


class PublicSettingsResponse(BaseModel):
    settings: dict[str, Any]


class ResetCategoryResponse(BaseModel):
    category: str
    reset_count: int
