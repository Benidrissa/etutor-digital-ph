from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class SmsProcessingStatus(enum.StrEnum):
    pending = "pending"
    parsed = "parsed"
    payment_processed = "payment_processed"
    parse_failed = "parse_failed"
    duplicate = "duplicate"
    ignored = "ignored"


class RelayDevice(Base):
    __tablename__ = "relay_devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    battery: Mapped[int | None] = mapped_column(Integer, nullable=True)
    charging: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    signal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sms_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class InboundSms(Base):
    __tablename__ = "inbound_sms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sms_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sender: Mapped[str] = mapped_column(String(50), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sms_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    processing_status: Mapped[SmsProcessingStatus] = mapped_column(
        Enum(SmsProcessingStatus, name="smsprocessingstatus"),
        nullable=False,
        server_default="pending",
        default=SmsProcessingStatus.pending,
    )
    parsed_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parsed_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parsed_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscription_payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_inbound_sms_status", "processing_status"),
        Index("ix_inbound_sms_created", "created_at"),
    )
