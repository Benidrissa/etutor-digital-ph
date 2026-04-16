"""Pydantic schemas for certificate endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

# ── Template schemas ───────────────────────────────────────────────


class CertificateTemplateCreate(BaseModel):
    title_fr: str
    title_en: str
    organization_name: str | None = None
    signatory_name: str | None = None
    signatory_title: str | None = None
    logo_url: str | None = None
    additional_text_fr: str | None = None
    additional_text_en: str | None = None


class CertificateTemplateUpdate(BaseModel):
    title_fr: str | None = None
    title_en: str | None = None
    organization_name: str | None = None
    signatory_name: str | None = None
    signatory_title: str | None = None
    logo_url: str | None = None
    additional_text_fr: str | None = None
    additional_text_en: str | None = None
    is_active: bool | None = None


class CertificateTemplateResponse(BaseModel):
    id: str
    course_id: str
    title_fr: str
    title_en: str
    organization_name: str | None
    signatory_name: str | None
    signatory_title: str | None
    logo_url: str | None
    additional_text_fr: str | None
    additional_text_en: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── Certificate schemas ────────────────────────────────────────────


class CertificateListItem(BaseModel):
    id: str
    course_id: str
    course_title_fr: str
    course_title_en: str
    verification_code: str
    average_score: float
    completed_at: datetime
    issued_at: datetime
    status: str


class CertificateDetail(BaseModel):
    id: str
    course_id: str
    course_title_fr: str
    course_title_en: str
    verification_code: str
    average_score: float
    completed_at: datetime
    issued_at: datetime
    status: str
    pdf_url: str | None
    metadata_json: dict | None
    template: CertificateTemplateResponse | None


class CertificateVerifyResponse(BaseModel):
    valid: bool
    learner_name: str | None = None
    course_title_fr: str | None = None
    course_title_en: str | None = None
    completion_date: datetime | None = None
    average_score: float | None = None
    organization_name: str | None = None
    signatory_name: str | None = None
    status: str | None = None
