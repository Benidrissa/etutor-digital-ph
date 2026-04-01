"""Email service for authentication flows."""

import resend
from structlog import get_logger

from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class EmailService:
    """Service for sending authentication-related emails."""

    def __init__(self):
        resend.api_key = settings.resend_api_key
        self.from_email = settings.from_email or "noreply@santepublique-aof.org"
        self.frontend_url = settings.frontend_url or "https://app.santepublique-aof.org"

    async def send_magic_link(self, email: str, magic_token: str, language: str = "fr") -> bool:
        """Send a magic link for account recovery.

        Args:
            email: User's email address
            magic_token: Token for the magic link
            language: User's preferred language (fr/en)

        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            magic_url = f"{self.frontend_url}/auth/magic-link?token={magic_token}"

            if language == "en":
                subject = "Reset your SantePublique AOF account access"
                html_content = f"""
                <h2>Reset Your Account Access</h2>
                <p>You requested to reset access to your SantePublique AOF account.</p>
                <p>Click the link below to continue:</p>
                <p><a href="{magic_url}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Reset Account Access</a></p>
                <p>This link will expire in 1 hour.</p>
                <p>If you didn't request this, you can safely ignore this email.</p>
                <hr>
                <p style="color: #666; font-size: 12px;">SantePublique AOF - Advancing Public Health in West Africa</p>
                """
                text_content = f"""
                Reset Your Account Access

                You requested to reset access to your SantePublique AOF account.

                Click the link below to continue:
                {magic_url}

                This link will expire in 1 hour.

                If you didn't request this, you can safely ignore this email.

                ---
                SantePublique AOF - Advancing Public Health in West Africa
                """
            else:  # French
                subject = "Réinitialiser l'accès à votre compte SantePublique AOF"
                html_content = f"""
                <h2>Réinitialiser l'accès à votre compte</h2>
                <p>Vous avez demandé à réinitialiser l'accès à votre compte SantePublique AOF.</p>
                <p>Cliquez sur le lien ci-dessous pour continuer :</p>
                <p><a href="{magic_url}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Réinitialiser l'accès au compte</a></p>
                <p>Ce lien expirera dans 1 heure.</p>
                <p>Si vous n'avez pas fait cette demande, vous pouvez ignorer cet email en toute sécurité.</p>
                <hr>
                <p style="color: #666; font-size: 12px;">SantePublique AOF - Faire progresser la santé publique en Afrique de l'Ouest</p>
                """
                text_content = f"""
                Réinitialiser l'accès à votre compte

                Vous avez demandé à réinitialiser l'accès à votre compte SantePublique AOF.

                Cliquez sur le lien ci-dessous pour continuer :
                {magic_url}

                Ce lien expirera dans 1 heure.

                Si vous n'avez pas fait cette demande, vous pouvez ignorer cet email en toute sécurité.

                ---
                SantePublique AOF - Faire progresser la santé publique en Afrique de l'Ouest
                """

            # Send email using Resend
            response = resend.Emails.send(
                {
                    "from": self.from_email,
                    "to": [email],
                    "subject": subject,
                    "html": html_content,
                    "text": text_content,
                }
            )

            logger.info(
                "Magic link email sent",
                email=email,
                language=language,
                message_id=response.get("id"),
            )
            return True

        except Exception as e:
            logger.error("Failed to send magic link email", email=email, error=str(e))
            return False

    async def send_welcome_email(self, email: str, name: str, language: str = "fr") -> bool:
        """Send welcome email after successful registration.

        Args:
            email: User's email address
            name: User's name
            language: User's preferred language (fr/en)

        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            dashboard_url = f"{self.frontend_url}/dashboard"

            if language == "en":
                subject = f"Welcome to SantePublique AOF, {name}!"
                html_content = f"""
                <h2>Welcome to SantePublique AOF!</h2>
                <p>Hello {name},</p>
                <p>Your account has been successfully created. You're now ready to begin your public health learning journey in West Africa.</p>
                <p>What's next:</p>
                <ul>
                    <li>Complete your placement test to determine your starting level</li>
                    <li>Explore our adaptive learning modules</li>
                    <li>Access real West African health data and case studies</li>
                </ul>
                <p><a href="{dashboard_url}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Start Learning</a></p>
                <hr>
                <p style="color: #666; font-size: 12px;">SantePublique AOF - Advancing Public Health in West Africa</p>
                """
            else:  # French
                subject = f"Bienvenue sur SantePublique AOF, {name} !"
                html_content = f"""
                <h2>Bienvenue sur SantePublique AOF !</h2>
                <p>Bonjour {name},</p>
                <p>Votre compte a été créé avec succès. Vous êtes maintenant prêt(e) à commencer votre parcours d'apprentissage en santé publique en Afrique de l'Ouest.</p>
                <p>Prochaines étapes :</p>
                <ul>
                    <li>Complétez votre test de positionnement pour déterminer votre niveau de départ</li>
                    <li>Explorez nos modules d'apprentissage adaptatifs</li>
                    <li>Accédez aux données de santé réelles d'Afrique de l'Ouest et aux études de cas</li>
                </ul>
                <p><a href="{dashboard_url}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">Commencer l'apprentissage</a></p>
                <hr>
                <p style="color: #666; font-size: 12px;">SantePublique AOF - Faire progresser la santé publique en Afrique de l'Ouest</p>
                """

            # Send email using Resend
            response = resend.Emails.send(
                {
                    "from": self.from_email,
                    "to": [email],
                    "subject": subject,
                    "html": html_content,
                }
            )

            logger.info(
                "Welcome email sent", email=email, language=language, message_id=response.get("id")
            )
            return True

        except Exception as e:
            logger.error("Failed to send welcome email", email=email, error=str(e))
            return False

    async def send_otp_email(
        self, email: str, otp_code: str, purpose: str, language: str = "fr"
    ) -> bool:
        """Send an OTP verification code via email.

        Args:
            email: User's email address
            otp_code: 6-digit OTP code
            purpose: Purpose of the OTP (registration/login)
            language: User's preferred language (fr/en)

        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            if language == "en":
                if purpose == "registration":
                    subject = "Your SantePublique AOF verification code"
                    html_content = f"""
                    <h2>Verification Code</h2>
                    <p>Thank you for registering with SantePublique AOF.</p>
                    <p>Your verification code is:</p>
                    <div style="background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 8px; border-radius: 8px; margin: 20px 0;">
                        {otp_code}
                    </div>
                    <p>Enter this code in the app to complete your registration.</p>
                    <p style="color: #666;">This code will expire in 10 minutes.</p>
                    <p style="color: #666;">If you didn't request this code, please ignore this email.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">SantePublique AOF - Advancing Public Health in West Africa</p>
                    """
                else:
                    subject = "Your SantePublique AOF login code"
                    html_content = f"""
                    <h2>Login Verification</h2>
                    <p>Your login verification code is:</p>
                    <div style="background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 8px; border-radius: 8px; margin: 20px 0;">
                        {otp_code}
                    </div>
                    <p>Enter this code in the app to complete your login.</p>
                    <p style="color: #666;">This code will expire in 10 minutes.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">SantePublique AOF - Advancing Public Health in West Africa</p>
                    """
            else:  # French
                if purpose == "registration":
                    subject = "Votre code de vérification SantePublique AOF"
                    html_content = f"""
                    <h2>Code de vérification</h2>
                    <p>Merci de vous être inscrit(e) sur SantePublique AOF.</p>
                    <p>Votre code de vérification est :</p>
                    <div style="background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 8px; border-radius: 8px; margin: 20px 0;">
                        {otp_code}
                    </div>
                    <p>Saisissez ce code dans l'application pour terminer votre inscription.</p>
                    <p style="color: #666;">Ce code expirera dans 10 minutes.</p>
                    <p style="color: #666;">Si vous n'avez pas demandé ce code, ignorez cet email.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">SantePublique AOF - Faire progresser la santé publique en Afrique de l'Ouest</p>
                    """
                else:
                    subject = "Votre code de connexion SantePublique AOF"
                    html_content = f"""
                    <h2>Vérification de connexion</h2>
                    <p>Votre code de vérification de connexion est :</p>
                    <div style="background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 8px; border-radius: 8px; margin: 20px 0;">
                        {otp_code}
                    </div>
                    <p>Saisissez ce code dans l'application pour terminer votre connexion.</p>
                    <p style="color: #666;">Ce code expirera dans 10 minutes.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">SantePublique AOF - Faire progresser la santé publique en Afrique de l'Ouest</p>
                    """

            # Send email using Resend
            response = resend.Emails.send(
                {
                    "from": self.from_email,
                    "to": [email],
                    "subject": subject,
                    "html": html_content,
                }
            )

            logger.info(
                "OTP email sent",
                email=email,
                purpose=purpose,
                language=language,
                message_id=response.get("id"),
            )
            return True

        except Exception as e:
            logger.error("Failed to send OTP email", email=email, purpose=purpose, error=str(e))
            return False
