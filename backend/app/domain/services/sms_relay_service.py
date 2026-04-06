"""SMS relay service for heartbeat and SMS ingestion."""

from __future__ import annotations

import datetime
from datetime import timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.sms_relay import (
    InboundSms,
    RelayDevice,
    SmsProcessingStatus,
)
from app.domain.services.sms_parser import SmsParser
from app.domain.services.subscription_service import (
    SubscriptionService,
)

logger = structlog.get_logger(__name__)

_parser = SmsParser()


class SmsRelayService:

    async def upsert_heartbeat(
        self,
        device_id: str,
        battery: int | None,
        charging: bool | None,
        signal: int | None,
        pending: int | None,
        failed: int | None,
        last_sms_at: datetime.datetime | None,
        app_version: str | None,
        session: AsyncSession,
    ) -> RelayDevice:
        now = datetime.datetime.now(tz=datetime.UTC)
        result = await session.execute(
            select(RelayDevice).where(
                RelayDevice.device_id == device_id
            )
        )
        device = result.scalar_one_or_none()

        if device is not None:
            device.battery = battery
            device.charging = charging
            device.signal = signal
            device.pending = pending
            device.failed = failed
            device.last_sms_at = last_sms_at
            device.app_version = app_version
            device.last_heartbeat_at = now
            device.updated_at = now
        else:
            device = RelayDevice(
                device_id=device_id,
                battery=battery,
                charging=charging,
                signal=signal,
                pending=pending,
                failed=failed,
                last_sms_at=last_sms_at,
                app_version=app_version,
                last_heartbeat_at=now,
            )
            session.add(device)

        await session.commit()
        logger.info(
            "Heartbeat recorded",
            device_id=device_id,
            battery=battery,
            signal=signal,
        )
        return device

    async def ingest_sms(
        self,
        sms_id: str,
        device_id: str,
        sender: str,
        body: str,
        ts: datetime.datetime,
        app_version: str | None,
        session: AsyncSession,
    ) -> InboundSms:
        # Dedup check
        existing = await session.execute(
            select(InboundSms).where(
                InboundSms.sms_id == sms_id
            )
        )
        found = existing.scalar_one_or_none()
        if found is not None:
            logger.info(
                "Duplicate SMS ignored",
                sms_id=sms_id,
            )
            return found

        sms = InboundSms(
            sms_id=sms_id,
            device_id=device_id,
            sender=sender,
            body=body,
            sms_received_at=ts,
            app_version=app_version,
            processing_status=SmsProcessingStatus.pending,
        )
        session.add(sms)

        # Flush to catch unique constraint race
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            result = await session.execute(
                select(InboundSms).where(
                    InboundSms.sms_id == sms_id
                )
            )
            return result.scalar_one()

        # Parse SMS body
        fallback_ref = f"SMS-{sms_id}"
        parsed = _parser.parse(body, sender, fallback_ref)

        if parsed is None:
            sms.processing_status = (
                SmsProcessingStatus.parse_failed
            )
            sms.error_message = (
                "No parser matched the SMS body"
            )
            await session.commit()
            logger.warning(
                "SMS parse failed",
                sms_id=sms_id,
                sender=sender,
            )
            return sms

        sms.parsed_amount = parsed.amount
        sms.parsed_phone = parsed.phone_number
        sms.parsed_reference = parsed.reference
        sms.parsed_provider = parsed.provider
        sms.processing_status = SmsProcessingStatus.parsed

        # Process payment via existing service
        try:
            sub_service = SubscriptionService()
            result = await sub_service.process_payment(
                phone_number=parsed.phone_number,
                amount_xof=parsed.amount,
                external_reference=parsed.reference,
                session=session,
            )
            sms.processing_status = (
                SmsProcessingStatus.payment_processed
            )
            logger.info(
                "SMS payment processed",
                sms_id=sms_id,
                amount=parsed.amount,
                phone=parsed.phone_number,
                reference=parsed.reference,
                result=result,
            )
        except Exception as exc:
            sms.processing_status = (
                SmsProcessingStatus.parse_failed
            )
            sms.error_message = (
                f"Payment processing error: {exc}"
            )
            logger.error(
                "SMS payment processing failed",
                sms_id=sms_id,
                error=str(exc),
            )

        await session.commit()
        return sms

    async def get_stale_devices(
        self,
        timeout_minutes: int,
        session: AsyncSession,
    ) -> list[RelayDevice]:
        cutoff = datetime.datetime.now(
            tz=datetime.UTC
        ) - timedelta(minutes=timeout_minutes)
        result = await session.execute(
            select(RelayDevice).where(
                RelayDevice.last_heartbeat_at < cutoff
            )
        )
        return list(result.scalars().all())

    async def get_all_devices(
        self, session: AsyncSession
    ) -> list[RelayDevice]:
        result = await session.execute(
            select(RelayDevice).order_by(
                RelayDevice.last_heartbeat_at.desc()
            )
        )
        return list(result.scalars().all())

    async def get_recent_sms(
        self,
        limit: int,
        session: AsyncSession,
        status_filter: SmsProcessingStatus | None = None,
    ) -> list[InboundSms]:
        q = select(InboundSms).order_by(
            InboundSms.created_at.desc()
        )
        if status_filter is not None:
            q = q.where(
                InboundSms.processing_status
                == status_filter
            )
        q = q.limit(limit)
        result = await session.execute(q)
        return list(result.scalars().all())

    async def count_by_status(
        self,
        status: SmsProcessingStatus,
        session: AsyncSession,
    ) -> int:
        from sqlalchemy import func

        result = await session.execute(
            select(func.count()).where(
                InboundSms.processing_status == status
            )
        )
        return result.scalar() or 0
