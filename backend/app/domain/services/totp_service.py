"""TOTP (Time-based One-Time Password) service for MFA."""

import base64
import io
import json
import secrets

import pyotp
import qrcode
from structlog import get_logger

logger = get_logger(__name__)


class TOTPService:
    """Service for managing TOTP secrets and verification."""

    def __init__(self):
        from app.domain.services.platform_settings_service import SettingsCache

        self.issuer_name = "SantePublique AOF"
        self.backup_codes_count = SettingsCache.instance().get("auth-backup_codes_count", 8)

    def generate_secret(self) -> str:
        """Generate a new TOTP secret.

        Returns:
            Base32 encoded TOTP secret
        """
        secret = pyotp.random_base32()
        logger.info("Generated new TOTP secret")
        return secret

    def generate_qr_code(self, secret: str, user_email: str) -> str:
        """Generate QR code for TOTP setup.

        Args:
            secret: Base32 encoded TOTP secret
            user_email: User's email address

        Returns:
            Base64 encoded PNG image of QR code
        """
        try:
            totp = pyotp.TOTP(secret)
            provisioning_uri = totp.provisioning_uri(name=user_email, issuer_name=self.issuer_name)

            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(provisioning_uri)
            qr.make(fit=True)

            # Create image
            img = qr.make_image(fill_color="black", back_color="white")

            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            img_data = buffer.getvalue()

            base64_img = base64.b64encode(img_data).decode("utf-8")
            logger.info("Generated QR code", user_email=user_email)
            return base64_img

        except Exception as e:
            logger.error("Failed to generate QR code", error=str(e))
            raise ValueError(f"Failed to generate QR code: {e}")

    def verify_token(self, secret: str, token: str, window: int = 1) -> bool:
        """Verify a TOTP token.

        Args:
            secret: Base32 encoded TOTP secret
            token: 6-digit TOTP code from authenticator
            window: Number of time windows to check (for clock drift)

        Returns:
            True if token is valid, False otherwise
        """
        try:
            totp = pyotp.TOTP(secret)

            # Remove any spaces or formatting
            token = token.replace(" ", "").replace("-", "")

            # Verify the token
            is_valid = totp.verify(token, valid_window=window)

            logger.info("TOTP verification attempt", is_valid=is_valid, token_length=len(token))

            return is_valid

        except Exception as e:
            logger.error("TOTP verification failed", error=str(e))
            return False

    def generate_backup_codes(self) -> list[str]:
        """Generate backup codes for account recovery.

        Returns:
            List of 8-digit backup codes
        """
        codes = []
        for _ in range(self.backup_codes_count):
            # Generate 8-digit code
            code = f"{secrets.randbelow(100000000):08d}"
            codes.append(code)

        logger.info("Generated backup codes", count=len(codes))
        return codes

    def hash_backup_codes(self, codes: list[str]) -> str:
        """Hash and serialize backup codes for storage.

        Args:
            codes: List of plaintext backup codes

        Returns:
            JSON string of hashed backup codes
        """
        import hashlib

        hashed_codes = []
        for code in codes:
            hash_obj = hashlib.sha256(code.encode())
            hashed_codes.append(hash_obj.hexdigest())

        return json.dumps(hashed_codes)

    def verify_backup_code(self, stored_codes: str, provided_code: str) -> tuple[bool, str]:
        """Verify a backup code and remove it from the list.

        Args:
            stored_codes: JSON string of hashed backup codes
            provided_code: Backup code provided by user

        Returns:
            Tuple of (is_valid, updated_codes_json)
        """
        try:
            import hashlib

            # Parse stored codes
            hashed_codes = json.loads(stored_codes)

            # Hash provided code
            provided_hash = hashlib.sha256(provided_code.encode()).hexdigest()

            # Check if code exists and remove it
            if provided_hash in hashed_codes:
                hashed_codes.remove(provided_hash)
                updated_codes = json.dumps(hashed_codes)

                logger.info("Backup code used successfully", remaining_codes=len(hashed_codes))
                return True, updated_codes
            else:
                logger.warning("Invalid backup code provided")
                return False, stored_codes

        except Exception as e:
            logger.error("Backup code verification failed", error=str(e))
            return False, stored_codes

    def get_current_token(self, secret: str) -> str:
        """Get current TOTP token for testing purposes.

        Args:
            secret: Base32 encoded TOTP secret

        Returns:
            Current 6-digit TOTP token
        """
        totp = pyotp.TOTP(secret)
        return totp.now()

    def get_provisioning_uri(self, secret: str, user_email: str) -> str:
        """Get the provisioning URI for manual entry.

        Args:
            secret: Base32 encoded TOTP secret
            user_email: User's email address

        Returns:
            Provisioning URI string
        """
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=user_email, issuer_name=self.issuer_name)
