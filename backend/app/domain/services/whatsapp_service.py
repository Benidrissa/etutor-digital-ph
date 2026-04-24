"""WhatsApp Cloud API client for OTP delivery.

OTPs MUST be delivered through a Meta-approved AUTHENTICATION-category
template — the WhatsApp policy rejects freeform OTP messages and risks
template-tier suspensions for sustained violations. The template name and
language are configured via settings; the service only injects the OTP code
as the body parameter.

In dev/staging, when ``settings.whatsapp_stub_mode`` is true, or when
credentials are missing, the service logs the OTP locally and returns
success — there's nothing to install or approve to iterate on the auth
flow.
"""

from __future__ import annotations

import httpx
from structlog import get_logger

from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class WhatsAppError(Exception):
    """Errors from the WhatsApp Cloud API."""


class WhatsAppService:
    """Send templated WhatsApp messages via Meta Cloud API."""

    def __init__(self) -> None:
        self.phone_number_id = settings.whatsapp_phone_number_id
        self.access_token = settings.whatsapp_access_token
        self.template_name = settings.whatsapp_otp_template_name
        self.api_version = settings.whatsapp_api_version
        self.api_base_url = settings.whatsapp_api_base_url
        self.stub_mode = settings.whatsapp_stub_mode or not (
            self.phone_number_id and self.access_token
        )

    async def send_otp_template(
        self,
        to_phone: str,
        otp_code: str,
        language: str = "fr",
    ) -> bool:
        """Send an OTP via the configured authentication template.

        Args:
            to_phone: Recipient phone number in E.164 format (no leading ``+``
                accepted but will be normalized).
            otp_code: 6-digit OTP code.
            language: Template language tag (``fr``/``en`` mapped to
                ``fr``/``en_US`` on the WhatsApp side).

        Returns:
            True on accepted send, False on failure.
        """
        recipient = to_phone.lstrip("+")

        if self.stub_mode:
            logger.warning(
                "WhatsApp OTP STUB — not actually sent",
                to=recipient,
                otp_code=otp_code,
                template=self.template_name,
                language=language,
            )
            return True

        lang_code = "en_US" if language == "en" else "fr"
        url = (
            f"{self.api_base_url}/{self.api_version}/{self.phone_number_id}/messages"
        )
        # WhatsApp authentication templates require both a body parameter and
        # a button parameter (the "copy code" button) carrying the OTP. Both
        # use the same code value.
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": lang_code},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": otp_code}],
                    },
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [{"type": "text", "text": otp_code}],
                    },
                ],
            },
        }
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code >= 400:
                    logger.error(
                        "WhatsApp send failed",
                        to=recipient,
                        status=response.status_code,
                        body=response.text[:500],
                    )
                    return False
                logger.info(
                    "WhatsApp OTP template sent",
                    to=recipient,
                    template=self.template_name,
                    language=lang_code,
                )
                return True
        except Exception as e:
            logger.error("WhatsApp send raised", to=recipient, error=str(e))
            return False
