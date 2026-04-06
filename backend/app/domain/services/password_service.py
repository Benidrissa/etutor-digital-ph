"""Password hashing and validation service."""

import bcrypt


class PasswordService:
    def hash_password(self, password: str) -> str:
        """Hash password with bcrypt (12 rounds default)."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against bcrypt hash."""
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

    def validate_password(self, password: str) -> None:
        """Enforce minimum 6 characters. Raises ValueError if invalid."""
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters")
