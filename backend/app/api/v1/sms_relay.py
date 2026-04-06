"""SMS relay API endpoints for heartbeat and SMS ingestion."""

from __future__ import annotations

import datetime
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user, require_role
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
        settings.sms_relay_trusted_senders_list
        if settings.sms_relay_trusted_senders
        else None
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
    current_user=Depends(
        require_role(UserRole.admin)
    ),
    db=Depends(get_db_session),
) -> RelayStatusResponse:
    settings = get_settings()
    service = SmsRelayService()

    devices = await service.get_all_devices(db)
    cutoff = datetime.datetime.now(
        tz=datetime.UTC
    ) - timedelta(
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
            last_sms_at=(
                d.last_sms_at.isoformat()
                if d.last_sms_at
                else None
            ),
            last_heartbeat_at=d.last_heartbeat_at.isoformat(),
            app_version=d.app_version,
            is_stale=d.last_heartbeat_at < cutoff,
        )
        for d in devices
    ]

    recent_count = await service.count_by_status(
        SmsProcessingStatus.payment_processed, db
    )
    failed_count = await service.count_by_status(
        SmsProcessingStatus.parse_failed, db
    )

    return RelayStatusResponse(
        devices=device_list,
        recent_sms_count=recent_count,
        failed_parse_count=failed_count,
    )
