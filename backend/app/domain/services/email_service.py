"""Email service for authentication flows.

Sends mail through a plain SMTP relay (defaults: ``localhost:25``, no auth,
no TLS). This matches the GoDaddy hosting contract — outbound mail is
relayed through the local mail server, and SPF (``v=spf1 include:secureserver.net -all``)
authorizes it on DNS. No external paid provider.
"""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib
from structlog import get_logger

from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class EmailService:
    """Service for sending authentication-related emails via SMTP relay."""

    def __init__(self) -> None:
        self.from_email = settings.from_email or "noreply@sira.local"
        self.from_name = settings.from_name or "Sira"
        self.frontend_url = settings.frontend_url or "https://app.santepublique-aof.org"
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_use_tls = settings.smtp_use_tls
        self.smtp_username = settings.smtp_username or None
        self.smtp_password = settings.smtp_password or None
        self.smtp_timeout = settings.smtp_timeout_seconds

    @staticmethod
    def _is_synthetic(email: str) -> bool:
        return email.endswith("@sira.app")

    async def _send(
        self,
        to_email: str,
        subject: str,
        html: str,
        text: str | None = None,
    ) -> bool:
        """Send a multipart email through the configured SMTP relay.

        Returns True on success, False otherwise. Never raises.
        """
        message = EmailMessage()
        message["From"] = f"{self.from_name} <{self.from_email}>"
        message["To"] = to_email
        message["Subject"] = subject
        if text:
            message.set_content(text)
            message.add_alternative(html, subtype="html")
        else:
            # No plaintext provided — strip tags loosely for a fallback body
            # so spam filters don't penalize html-only mail.
            message.set_content("Please view this email in an HTML-capable client.")
            message.add_alternative(html, subtype="html")

        try:
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                use_tls=self.smtp_use_tls,
                start_tls=False,
                username=self.smtp_username,
                password=self.smtp_password,
                timeout=self.smtp_timeout,
            )
            logger.info(
                "Email sent via SMTP",
                to=to_email,
                subject=subject,
                host=self.smtp_host,
                port=self.smtp_port,
            )
            return True
        except Exception as e:
            logger.error(
                "Failed to send email via SMTP",
                to=to_email,
                subject=subject,
                host=self.smtp_host,
                port=self.smtp_port,
                error=str(e),
            )
            return False

    async def send_magic_link(self, email: str, magic_token: str, language: str = "fr") -> bool:
        if self._is_synthetic(email):
            return False
        magic_url = f"{self.frontend_url}/auth/magic-link?token={magic_token}"

        if language == "en":
            subject = "Reset your Sira account access"
            html_content = f"""
            <h2>Reset Your Account Access</h2>
            <p>You requested to reset access to your Sira account.</p>
            <p>Click the link below to continue:</p>
            <p><a href="{magic_url}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Reset Account Access</a></p>
            <p>This link will expire in 1 hour.</p>
            <p>If you didn't request this, you can safely ignore this email.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Sira</p>
            """
            text_content = (
                "Reset Your Account Access\n\n"
                "You requested to reset access to your Sira account.\n\n"
                f"Click the link below to continue:\n{magic_url}\n\n"
                "This link will expire in 1 hour.\n\n"
                "If you didn't request this, you can safely ignore this email.\n"
            )
        else:
            subject = "Réinitialiser l'accès à votre compte Sira"
            html_content = f"""
            <h2>Réinitialiser l'accès à votre compte</h2>
            <p>Vous avez demandé à réinitialiser l'accès à votre compte Sira.</p>
            <p>Cliquez sur le lien ci-dessous pour continuer :</p>
            <p><a href="{magic_url}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Réinitialiser l'accès au compte</a></p>
            <p>Ce lien expirera dans 1 heure.</p>
            <p>Si vous n'avez pas fait cette demande, vous pouvez ignorer cet email en toute sécurité.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Sira</p>
            """
            text_content = (
                "Réinitialiser l'accès à votre compte\n\n"
                "Vous avez demandé à réinitialiser l'accès à votre compte Sira.\n\n"
                f"Cliquez sur le lien ci-dessous pour continuer :\n{magic_url}\n\n"
                "Ce lien expirera dans 1 heure.\n\n"
                "Si vous n'avez pas fait cette demande, vous pouvez ignorer cet email en toute sécurité.\n"
            )

        return await self._send(email, subject, html_content, text_content)

    async def send_welcome_email(self, email: str, name: str, language: str = "fr") -> bool:
        if self._is_synthetic(email):
            return False
        dashboard_url = f"{self.frontend_url}/dashboard"

        if language == "en":
            subject = f"Welcome to Sira, {name}!"
            html_content = f"""
            <h2>Welcome to Sira!</h2>
            <p>Hello {name},</p>
            <p>Your account has been successfully created.</p>
            <p><a href="{dashboard_url}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Start Learning</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Sira</p>
            """
            text_content = f"Welcome to Sira, {name}!\n\nYour account has been created. Start here: {dashboard_url}\n"
        else:
            subject = f"Bienvenue sur Sira, {name} !"
            html_content = f"""
            <h2>Bienvenue sur Sira !</h2>
            <p>Bonjour {name},</p>
            <p>Votre compte a été créé avec succès.</p>
            <p><a href="{dashboard_url}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Commencer l'apprentissage</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Sira</p>
            """
            text_content = f"Bienvenue sur Sira, {name} !\n\nVotre compte a été créé. Commencez ici : {dashboard_url}\n"

        return await self._send(email, subject, html_content, text_content)

    async def send_relay_alert(
        self,
        to_email: str,
        device_id: str,
        last_seen: str,
        battery: int | None,
    ) -> bool:
        subject = f"[SIRA] SMS relay {device_id} offline"
        battery_info = f"{battery}%" if battery is not None else "unknown"
        html_content = f"""
        <h2>SMS Relay Device Alert</h2>
        <p>The SMS relay device <strong>{device_id}</strong>
        has not sent a heartbeat since
        <strong>{last_seen}</strong>.</p>
        <p>Last known battery: {battery_info}</p>
        <p>Please check the physical device.</p>
        <hr>
        <p style="color: #666; font-size: 12px;">Sira</p>
        """
        text_content = (
            f"SMS relay device {device_id} has not sent a heartbeat since {last_seen}. "
            f"Last known battery: {battery_info}."
        )
        return await self._send(to_email, subject, html_content, text_content)

    async def send_otp_email(
        self, email: str, otp_code: str, purpose: str, language: str = "fr"
    ) -> bool:
        if self._is_synthetic(email):
            return False

        if language == "en":
            if purpose == "registration":
                subject = "Your Sira verification code"
                intro = "Thank you for registering with Sira."
                cta = "Enter this code in the app to complete your registration."
            else:
                subject = "Your Sira login code"
                intro = "Login verification."
                cta = "Enter this code in the app to complete your login."
            footer = "This code will expire in 10 minutes."
        else:
            if purpose == "registration":
                subject = "Votre code de vérification Sira"
                intro = "Merci de vous être inscrit(e) sur Sira."
                cta = "Saisissez ce code dans l'application pour terminer votre inscription."
            else:
                subject = "Votre code de connexion Sira"
                intro = "Vérification de connexion."
                cta = "Saisissez ce code dans l'application pour terminer votre connexion."
            footer = "Ce code expirera dans 10 minutes."

        html_content = f"""
        <h2>{subject}</h2>
        <p>{intro}</p>
        <div style="background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 8px; border-radius: 8px; margin: 20px 0;">
            {otp_code}
        </div>
        <p>{cta}</p>
        <p style="color: #666;">{footer}</p>
        <hr>
        <p style="color: #666; font-size: 12px;">Sira</p>
        """
        text_content = f"{subject}\n\n{intro}\n\nCode: {otp_code}\n\n{cta}\n{footer}\n"
        return await self._send(email, subject, html_content, text_content)
