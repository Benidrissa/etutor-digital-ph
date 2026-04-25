"""Phone OTP service for registration and login verification (WhatsApp)."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.domain.models.auth import PhoneOTP
from app.domain.models.user import User
from app.domain.services.platform_settings_service import SettingsCache
from app.domain.services.whatsapp_service import WhatsAppService

logger = get_logger(__name__)


class PhoneOTPError(Exception):
    """Phone OTP related errors."""


_E164_RE = re.compile(r"^\+?[1-9]\d{6,14}$")


def normalize_phone(phone: str) -> str:
    """Normalize a phone number to E.164 (with leading ``+``).

    Strips spaces, dashes, parens. Rejects non-E.164 inputs. We deliberately
    avoid pulling in ``phonenumbers`` here so the service stays light; we
    only need a coarse syntactic check before handing the number off to
    WhatsApp, which performs its own validation.
    """
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    if not _E164_RE.match(cleaned):
        raise PhoneOTPError("Invalid phone number format. Use E.164 (e.g. +221770000000).")
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


class PhoneOTPService:
    """Service for phone OTP generation and verification (WhatsApp)."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.whatsapp = WhatsAppService()
        _cache = SettingsCache.instance()
        self.otp_expiry_minutes = _cache.get("auth-otp-expiry-minutes", 10)
        self.max_attempts = _cache.get("auth-otp-max-attempts", 5)
        self.rate_limit_window = _cache.get("auth-otp-rate-limit-window-seconds", 600)
        self.max_otps_per_window = _cache.get("auth-otp-max-requests-per-window", 5)

    def generate_otp_code(self) -> str:
        return f"{secrets.randbelow(1000000):06d}"

    def hash_otp_code(self, otp_code: str) -> str:
        return hashlib.sha256(otp_code.encode()).hexdigest()

    async def send_registration_otp(
        self,
        phone_number: str,
        user_id: UUID | None = None,
        language: str = "fr",
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        try:
            phone = normalize_phone(phone_number)
            await self._check_rate_limit(phone, ip_address)
            await self._cleanup_expired_otps(phone)

            otp_code = self.generate_otp_code()
            expires_at = datetime.utcnow() + timedelta(minutes=self.otp_expiry_minutes)

            otp_record = PhoneOTP(
                id=uuid4(),
                user_id=user_id,
                phone_number=phone,
                code=self.hash_otp_code(otp_code),
                channel="whatsapp",
                purpose="registration",
                attempts=0,
                expires_at=expires_at,
                created_at=datetime.utcnow(),
                ip_address=ip_address,
            )
            self.db.add(otp_record)

            sent = await self.whatsapp.send_otp_template(phone, otp_code, language)
            if not sent:
                await self.db.rollback()
                raise PhoneOTPError("Failed to send OTP via WhatsApp")

            await self.db.commit()

            logger.info("Registration phone OTP sent", phone=phone, otp_id=str(otp_record.id))

            return {
                "otp_id": str(otp_record.id),
                "phone_number": phone,
                "expires_at": expires_at.isoformat(),
                "expires_in_seconds": self.otp_expiry_minutes * 60,
            }

        except PhoneOTPError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Failed to send registration phone OTP", phone=phone_number, error=str(e))
            raise PhoneOTPError(f"Failed to send OTP: {e}")

    async def send_login_otp(
        self,
        phone_number: str,
        language: str = "fr",
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        try:
            phone = normalize_phone(phone_number)
            user = await self.db.scalar(select(User).where(User.phone_number == phone))
            if not user:
                # Don't reveal existence — caller raises a generic error.
                raise PhoneOTPError("User not found")

            await self._check_rate_limit(phone, ip_address)
            await self._cleanup_expired_otps(phone)

            otp_code = self.generate_otp_code()
            expires_at = datetime.utcnow() + timedelta(minutes=self.otp_expiry_minutes)

            otp_record = PhoneOTP(
                id=uuid4(),
                user_id=user.id,
                phone_number=phone,
                code=self.hash_otp_code(otp_code),
                channel="whatsapp",
                purpose="login",
                attempts=0,
                expires_at=expires_at,
                created_at=datetime.utcnow(),
                ip_address=ip_address,
            )
            self.db.add(otp_record)

            sent = await self.whatsapp.send_otp_template(phone, otp_code, language)
            if not sent:
                await self.db.rollback()
                raise PhoneOTPError("Failed to send OTP via WhatsApp")

            await self.db.commit()

            logger.info("Login phone OTP sent", phone=phone, otp_id=str(otp_record.id))

            return {
                "otp_id": str(otp_record.id),
                "phone_number": phone,
                "expires_at": expires_at.isoformat(),
                "expires_in_seconds": self.otp_expiry_minutes * 60,
            }

        except PhoneOTPError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Failed to send login phone OTP", phone=phone_number, error=str(e))
            raise PhoneOTPError(f"Failed to send OTP: {e}")

    async def verify_otp(
        self,
        otp_id: str,
        otp_code: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        try:
            otp_record = await self.db.scalar(
                select(PhoneOTP).where(
                    and_(PhoneOTP.id == UUID(otp_id), PhoneOTP.verified_at.is_(None))
                )
            )

            if not otp_record:
                raise PhoneOTPError("OTP not found or already verified")

            if otp_record.expires_at < datetime.utcnow():
                raise PhoneOTPError("OTP has expired")

            if otp_record.attempts >= self.max_attempts:
                raise PhoneOTPError("Maximum verification attempts exceeded")

            otp_record.attempts += 1

            if not hmac.compare_digest(otp_record.code, self.hash_otp_code(otp_code)):
                await self.db.commit()
                attempts_left = self.max_attempts - otp_record.attempts
                raise PhoneOTPError(f"Invalid OTP code. {attempts_left} attempts remaining.")

            otp_record.verified_at = datetime.utcnow()

            user_info: dict[str, Any] | None = None
            if otp_record.user_id:
                user = await self.db.scalar(select(User).where(User.id == otp_record.user_id))
                if user:
                    user_info = {
                        "id": str(user.id),
                        "email": user.email,
                        "phone_number": user.phone_number,
                        "name": user.name,
                        "preferred_language": user.preferred_language,
                        "country": user.country,
                        "current_level": user.current_level,
                    }

            await self.db.commit()

            logger.info(
                "Phone OTP verified successfully",
                otp_id=otp_id,
                phone=otp_record.phone_number,
                purpose=otp_record.purpose,
            )

            return {
                "verified": True,
                "phone_number": otp_record.phone_number,
                "purpose": otp_record.purpose,
                "user": user_info,
                "verified_at": otp_record.verified_at.isoformat(),
            }

        except PhoneOTPError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Phone OTP verification failed", otp_id=otp_id, error=str(e))
            raise PhoneOTPError(f"Verification failed: {e}")

    async def _check_rate_limit(self, phone: str, ip_address: str | None = None) -> None:
        try:
            window_start = datetime.utcnow() - timedelta(seconds=self.rate_limit_window)

            phone_count = await self.db.scalar(
                select(func.count(PhoneOTP.id)).where(
                    and_(PhoneOTP.phone_number == phone, PhoneOTP.created_at >= window_start)
                )
            )
            if phone_count and phone_count >= self.max_otps_per_window:
                raise PhoneOTPError(
                    f"Too many OTP requests. Please wait {self.rate_limit_window // 60} minutes."
                )

            if ip_address:
                ip_count = await self.db.scalar(
                    select(func.count(PhoneOTP.id)).where(
                        and_(PhoneOTP.ip_address == ip_address, PhoneOTP.created_at >= window_start)
                    )
                )
                if ip_count and ip_count >= self.max_otps_per_window:
                    raise PhoneOTPError(
                        f"Too many OTP requests from this IP. Please wait {self.rate_limit_window // 60} minutes."
                    )
        except PhoneOTPError:
            raise
        except Exception as e:
            logger.error("Rate limit check failed", phone=phone, error=str(e))
            # Don't block on rate-limit-check errors

    async def _cleanup_expired_otps(self, phone: str) -> None:
        try:
            await self.db.execute(
                delete(PhoneOTP).where(
                    and_(PhoneOTP.phone_number == phone, PhoneOTP.expires_at < datetime.utcnow())
                )
            )
            await self.db.commit()
        except Exception as e:
            logger.warning("Failed to cleanup expired phone OTPs", phone=phone, error=str(e))
            await self.db.rollback()
