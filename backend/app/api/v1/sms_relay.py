"""SMS relay API endpoints for heartbeat and SMS ingestion."""

from __future__ import annotations

import contextlib
import csv
import datetime
import io
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import require_role
from app.domain.models.sms_relay import SmsProcessingStatus
from app.domain.models.user import UserRole
from app.domain.services.sms_relay_service import SmsRelayService
from app.infrastructure.config.settings import get_settings

logger = get_logger(__name__)

router = APIRouter(tags=["SMS Relay"])


# ---------- Auth dependency ----------


async def verify_relay_api_key(
    authorization: str = Header(...),
) -> str:
    settings = get_settings()
    if not settings.sms_relay_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS relay not configured",
        )
    expected = f"Bearer {settings.sms_relay_api_key}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return settings.sms_relay_api_key


# ---------- Schemas ----------


class SmsPayload(BaseModel):
    id: str
    device_id: str
    sender: str
    body: str
    ts: datetime.datetime
    v: int | str | None = None


class SmsResponse(BaseModel):
    status: str = "ok"


class HeartbeatPayload(BaseModel):
    device_id: str
    battery: int | None = None
    charging: bool | None = None
    signal: int | None = None
    pending: int | None = None
    failed: int | None = None
    last_sms_at: datetime.datetime | None = None
    v: int | str | None = None


class HeartbeatResponse(BaseModel):
    status: str = "ok"
    trusted_senders: list[str] | None = None
    update_url: str | None = None


class DeviceStatusResponse(BaseModel):
    device_id: str
    battery: int | None
    charging: bool | None
    signal: int | None
    pending: int | None
    failed: int | None
    last_sms_at: str | None
    last_heartbeat_at: str
    app_version: str | None
    is_stale: bool


class SmsRecordResponse(BaseModel):
    id: str
    sms_id: str
    device_id: str
    sender: str
    body: str
    sms_received_at: str
    processing_status: str
    parsed_amount: int | None
    parsed_phone: str | None
    parsed_reference: str | None
    parsed_provider: str | None
    error_message: str | None
    created_at: str


class SmsListResponse(BaseModel):
    items: list[SmsRecordResponse]
    total: int
    offset: int
    limit: int


class RelayStatusResponse(BaseModel):
    devices: list[DeviceStatusResponse]
    recent_sms_count: int
    failed_parse_count: int


# ---------- Endpoints ----------


@router.post(
    "/sms",
    response_model=SmsResponse,
    status_code=status.HTTP_200_OK,
)
async def receive_sms(
    payload: SmsPayload,
    _key: str = Depends(verify_relay_api_key),
    db=Depends(get_db_session),
) -> SmsResponse:
    service = SmsRelayService()
    app_version = str(payload.v) if payload.v else None
    await service.ingest_sms(
        sms_id=payload.id,
        device_id=payload.device_id,
        sender=payload.sender,
        body=payload.body,
        ts=payload.ts,
        app_version=app_version,
        session=db,
    )
    return SmsResponse(status="ok")


@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    status_code=status.HTTP_200_OK,
)
async def receive_heartbeat(
    payload: HeartbeatPayload,
    _key: str = Depends(verify_relay_api_key),
    db=Depends(get_db_session),
) -> HeartbeatResponse:
    service = SmsRelayService()
    app_version = str(payload.v) if payload.v else None
    await service.upsert_heartbeat(
        device_id=payload.device_id,
        battery=payload.battery,
        charging=payload.charging,
        signal=payload.signal,
        pending=payload.pending,
        failed=payload.failed,
        last_sms_at=payload.last_sms_at,
        app_version=app_version,
        session=db,
    )

    settings = get_settings()
    trusted = (
        settings.sms_relay_trusted_senders_list if settings.sms_relay_trusted_senders else None
    )

    return HeartbeatResponse(
        status="ok",
        trusted_senders=trusted,
    )


@router.get(
    "/admin/relay/status",
    response_model=RelayStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_relay_status(
    current_user=Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> RelayStatusResponse:
    settings = get_settings()
    service = SmsRelayService()

    devices = await service.get_all_devices(db)
    cutoff = datetime.datetime.now(tz=datetime.UTC) - timedelta(
        minutes=settings.sms_relay_heartbeat_timeout_minutes
    )

    device_list = [
        DeviceStatusResponse(
            device_id=d.device_id,
            battery=d.battery,
            charging=d.charging,
            signal=d.signal,
            pending=d.pending,
            failed=d.failed,
            last_sms_at=(d.last_sms_at.isoformat() if d.last_sms_at else None),
            last_heartbeat_at=d.last_heartbeat_at.isoformat(),
            app_version=d.app_version,
            is_stale=d.last_heartbeat_at < cutoff,
        )
        for d in devices
    ]

    recent_count = await service.count_by_status(
        SmsProcessingStatus.payment_processed,
        db,
    )
    failed_count = await service.count_by_status(
        SmsProcessingStatus.parse_failed,
        db,
    )

    return RelayStatusResponse(
        devices=device_list,
        recent_sms_count=recent_count,
        failed_parse_count=failed_count,
    )


def _parse_filter_params(
    status_filter: str | None,
    phone: str | None,
    reference: str | None,
    date_from: str | None,
    date_to: str | None,
) -> dict:
    """Parse common filter query params into kwargs for the service layer."""
    filter_val = None
    if status_filter:
        with contextlib.suppress(ValueError):
            filter_val = SmsProcessingStatus(status_filter)

    df = None
    if date_from:
        with contextlib.suppress(ValueError):
            df = (
                datetime.datetime.fromisoformat(date_from).replace(tzinfo=datetime.UTC)
                if "T" in date_from
                else datetime.datetime.combine(
                    datetime.date.fromisoformat(date_from),
                    datetime.time.min,
                    tzinfo=datetime.UTC,
                )
            )

    dt = None
    if date_to:
        with contextlib.suppress(ValueError):
            dt = (
                datetime.datetime.fromisoformat(date_to).replace(tzinfo=datetime.UTC)
                if "T" in date_to
                else datetime.datetime.combine(
                    datetime.date.fromisoformat(date_to),
                    datetime.time.max,
                    tzinfo=datetime.UTC,
                )
            )

    return {
        "status_filter": filter_val,
        "phone": phone or None,
        "reference": reference or None,
        "date_from": df,
        "date_to": dt,
    }


def _sms_to_response(r) -> SmsRecordResponse:
    return SmsRecordResponse(
        id=str(r.id),
        sms_id=r.sms_id,
        device_id=r.device_id,
        sender=r.sender,
        body=r.body,
        sms_received_at=r.sms_received_at.isoformat(),
        processing_status=r.processing_status,
        parsed_amount=r.parsed_amount,
        parsed_phone=r.parsed_phone,
        parsed_reference=r.parsed_reference,
        parsed_provider=r.parsed_provider,
        error_message=r.error_message,
        created_at=r.created_at.isoformat(),
    )


@router.get(
    "/admin/relay/sms/export/csv",
    status_code=status.HTTP_200_OK,
)
async def export_relay_sms_csv(
    status_filter: str | None = Query(None),
    phone: str | None = Query(None),
    reference: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user=Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> StreamingResponse:
    """Export filtered SMS records as CSV. Admin only."""
    service = SmsRelayService()
    filters = _parse_filter_params(
        status_filter,
        phone,
        reference,
        date_from,
        date_to,
    )

    records = await service.get_all_sms_for_export(
        session=db,
        **filters,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "date",
            "sender",
            "amount",
            "phone",
            "reference",
            "status",
            "device",
            "provider",
            "error",
        ]
    )
    for r in records:
        writer.writerow(
            [
                r.sms_received_at.isoformat(),
                r.sender,
                r.parsed_amount or "",
                r.parsed_phone or "",
                r.parsed_reference or "",
                r.processing_status,
                r.device_id,
                r.parsed_provider or "",
                r.error_message or "",
            ]
        )

    output.seek(0)
    logger.info(
        "Admin exported SMS CSV",
        admin_id=current_user.id,
        count=len(records),
    )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=sms_export.csv",
        },
    )


@router.get(
    "/admin/relay/sms",
    response_model=SmsListResponse,
    status_code=status.HTTP_200_OK,
)
async def get_relay_sms(
    status_filter: str | None = Query(None),
    phone: str | None = Query(None),
    reference: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> SmsListResponse:
    service = SmsRelayService()
    filters = _parse_filter_params(
        status_filter,
        phone,
        reference,
        date_from,
        date_to,
    )

    records = await service.get_recent_sms(
        limit=limit,
        session=db,
        offset=offset,
        **filters,
    )
    total = await service.count_sms(
        session=db,
        **filters,
    )

    return SmsListResponse(
        items=[_sms_to_response(r) for r in records],
        total=total,
        offset=offset,
        limit=limit,
    )
