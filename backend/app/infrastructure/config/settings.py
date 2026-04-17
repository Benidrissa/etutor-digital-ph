from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/santepublique_aof"

    @property
    def database_url_sync(self) -> str:
        """Derive sync URL from async URL by stripping the +asyncpg dialect."""
        return self.database_url.replace("+asyncpg", "")

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Local JWT Auth
    jwt_secret: str = "your-secret-key-change-in-production"

    # Email Service
    resend_api_key: str = ""
    from_email: str = "noreply@santepublique-aof.org"
    frontend_url: str = "http://localhost:3000"

    # Anthropic Claude API
    anthropic_api_key: str = ""

    # Google AI (Gemini TTS)
    google_api_key: str = ""

    # OpenAI Embeddings
    openai_api_key: str = ""

    # Embeddings
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Monitoring
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.2
    sentry_profiles_sample_rate: float = 0.1

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:3000"
    api_v1_prefix: str = "/api/v1"

    # Subscription webhook
    subscription_webhook_secret: str = ""

    # SMS Relay
    sms_relay_api_key: str = ""
    sms_relay_alert_email: str = ""
    sms_relay_heartbeat_timeout_minutes: int = 60
    sms_relay_trusted_senders: str = ""

    # Admin seeding
    admin_email: str = ""

    # File upload settings
    upload_temp_dir: str = "/tmp/santepublique_uploads"
    upload_max_size_bytes: int = 10 * 1024 * 1024  # 10MB
    upload_ttl_hours: int = 24
    upload_daily_limit: int = 10
    upload_allowed_types: str = (
        "image/png,image/jpeg,image/jpg,image/webp,image/gif,"
        "application/pdf,text/csv,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "text/plain,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    upload_max_pdf_tokens: int = 5000
    upload_max_csv_rows: int = 20

    # Meta MMS TTS sidecar (Moore / Dioula / Bambara)
    mms_tts_url: str = "http://mms-tts:5050"
    mms_tts_timeout_seconds: float = 60.0

    # MinIO / S3-compatible object storage
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket_media: str = "santepublique-media"
    minio_public_url: str = "http://localhost:9000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_allowed_types_list(self) -> list[str]:
        return [t.strip() for t in self.upload_allowed_types.split(",") if t.strip()]

    @property
    def sms_relay_trusted_senders_list(self) -> list[str]:
        return [s.strip() for s in self.sms_relay_trusted_senders.split(",") if s.strip()]


settings = Settings()


def get_settings() -> Settings:
    """Get application settings."""
    return settings
