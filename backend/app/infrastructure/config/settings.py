from pydantic import Field
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

    # Email Service — SMTP relay (GoDaddy hosting expects localhost:25,
    # no auth, no TLS, with `v=spf1 include:secureserver.net -all` on DNS).
    # Defaults match that contract; staging/prod typically don't override.
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_use_tls: bool = False
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_timeout_seconds: float = 10.0
    from_email: str = "noreply@sira.local"
    from_name: str = "Sira"
    frontend_url: str = "http://localhost:3000"

    # WhatsApp Cloud API (Meta) — used for phone-OTP delivery.
    # OTP MUST be delivered through an AUTHENTICATION-category template that
    # has been pre-approved in Meta Business Manager. Freeform messages are
    # rejected for OTPs and risk template suspension.
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_otp_template_name: str = "sira_otp"
    whatsapp_api_version: str = "v20.0"
    whatsapp_api_base_url: str = "https://graph.facebook.com"
    # When credentials are missing or this flag is on, WhatsAppService logs
    # the OTP locally and short-circuits the HTTP call — for dev/staging.
    whatsapp_stub_mode: bool = False

    # Provider API keys. These fields hold the reseller-provisioned env value;
    # they are the *fallback*. A tenant admin can override any of them at
    # runtime via /admin/settings (encrypted, see api_key_service). Read the
    # effective key through the same-named property below, never the _env field.
    encryption_key: str = Field(default="", validation_alias="ENCRYPTION_KEY")

    # Anthropic Claude API
    anthropic_api_key_env: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    # Pluggable content-generation providers (#2443). The active model is the
    # admin-selected `ai-model-content` setting; the registry resolves it to a
    # provider by prefix. Keys are server-side only (never exposed to clients).
    # Kimi K2.6 is served over Moonshot's OpenAI-compatible endpoint — keep prod
    # use gated on a data-residency compliance review (China-based servers).
    moonshot_api_key_env: str = Field(default="", validation_alias="MOONSHOT_API_KEY")
    moonshot_base_url: str = "https://api.moonshot.ai/v1"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Cost kill-switch for Vision-backed figure tasks (classifier, flowchart
    # SVG re-deriver, complex_diagram overlay extractor). Set to False in an
    # environment that shouldn't spend on Claude Vision — backfills and the
    # Vision-gated ingest branches short-circuit cleanly. Text-only Haiku
    # features (caption translation, tutor, lessons) are unaffected.
    # Issue #1928 — staging burned ~$30 in 4 hours of repeated backfills.
    enable_figure_vision: bool = True

    # Drop unreadable extracted images (blank/near-uniform fills, random-noise
    # garbage from botched colorspace/mask decodes, decode-failures) before they
    # are persisted as source_images and linked to content (#2540). Calibrated
    # to keep sparse line-diagrams/flowcharts. Set False to disable the filter
    # if a real figure is ever wrongly dropped.
    enable_image_readability_filter: bool = True

    # Figure-vision provider selection (#2435). The classifier + caption reader
    # call whichever provider is configured here. Gemini 2.5 Flash-Lite is the
    # cheapest accurate VLM (~$0.10/$0.40 per 1M; a figure image bills ~258
    # tokens) and is reached through its OpenAI-compatible endpoint, so it
    # reuses the OpenAI client and needs no extra dependency. Switch to
    # "anthropic" (Haiku) or "openai" without code changes.
    figure_vision_provider: str = "gemini"  # gemini | anthropic | openai
    figure_vision_gemini_model: str = "gemini-2.5-flash-lite"
    figure_vision_anthropic_model: str = "claude-haiku-4-5"
    figure_vision_openai_model: str = "gpt-4o-mini"
    gemini_openai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # Google AI (Gemini TTS + figure vision)
    google_api_key_env: str = Field(default="", validation_alias="GOOGLE_API_KEY")

    # OpenAI Embeddings
    openai_api_key_env: str = Field(default="", validation_alias="OPENAI_API_KEY")

    # Resend (transactional email). Not yet wired to a consumer (SMTP relay is
    # the active path); stored so tenant admins can set it ahead of integration.
    resend_api_key_env: str = Field(default="", validation_alias="RESEND_API_KEY")

    # Effective provider keys — tenant override (encrypted, decrypted on read)
    # takes precedence over the reseller-provisioned *_env fallback above. All
    # existing consumers read these properties as `settings.<provider>_api_key`.
    @property
    def anthropic_api_key(self) -> str:
        return self._effective_api_key("anthropic")

    @property
    def openai_api_key(self) -> str:
        return self._effective_api_key("openai")

    @property
    def google_api_key(self) -> str:
        return self._effective_api_key("google")

    @property
    def moonshot_api_key(self) -> str:
        return self._effective_api_key("moonshot")

    @property
    def resend_api_key(self) -> str:
        return self._effective_api_key("resend")

    @staticmethod
    def _effective_api_key(provider: str) -> str:
        # Lazy import avoids a circular import at module load
        # (api_key_service imports this settings singleton).
        from app.domain.services.api_key_service import ApiKeyService

        return ApiKeyService.effective(provider)

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
    app_version: str = "0.1.0"
    api_service_name: str = "sira-api"

    # Branding — tenant-overridable via env at provisioning time. Defaults are
    # generic so no pre-generalization copy leaks. See issue #1618.
    app_name: str = "Sira"
    app_short_name: str = "Sira"
    app_description_fr: str = "Plateforme d'apprentissage adaptative"
    app_description_en: str = "Adaptive learning platform"
    app_tagline_fr: str = "Apprenez à votre rythme"
    app_tagline_en: str = "Learn at your own pace"
    app_theme_color: str = "#22c55e"
    openapi_description: str = ""  # empty → fall back to app_description_en

    # Subscription webhook
    subscription_webhook_secret: str = ""

    # Payment provider webhooks (Orange Money / Wave / Paystack). Public HTTPS
    # origin where providers can reach /api/v1/payments/webhook/{provider}. When
    # empty, the initialize endpoint falls back to the incoming request origin.
    payments_callback_base_url: str = ""

    # HeyGen (lesson summary video rendering) — see issue #1791.
    # The API key is required to create videos; the webhook secret is used
    # to HMAC-verify the async completion callback; the callback base URL is
    # the public HTTPS origin where HeyGen can reach /api/v1/webhooks/heygen.
    heygen_api_key: str = ""
    heygen_webhook_secret: str = ""
    heygen_callback_base_url: str = ""

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

    # Meta MMS TTS sidecar (Moore / Dioula / Bambara) — see #1503.
    mms_tts_url: str = "http://mms-tts:5050"
    # 180s (matches nllb_timeout_seconds) — MMS-TTS synthesis on CPU for
    # long question text can take 30–60s per call, and when multiple
    # Celery workers hit the single-worker sidecar concurrently calls
    # queue up and 60s hits before the request is served (#1732 follow-up).
    mms_tts_timeout_seconds: float = 180.0

    # NLLB translation sidecar — pruned + CT2 int8 artifact (#1709) replacing
    # the original transformers + distilled-600M setup (#1690, #1705). Port
    # 5060 is the sidecar's inbound. Timeout kept at 180s to cover the
    # worst-case CPU decode under load, even though CT2 int8 is much faster
    # than the old transformers greedy path. nllb_model tracks which
    # upstream model generation the artifact derives from, for telemetry.
    nllb_url: str = "http://nllb:5060"
    nllb_timeout_seconds: float = 180.0
    nllb_model: str = "distilled-600M"
    # Artifact pin — docker-compose passes these to the sidecar Dockerfile
    # at build time so the CT2 int8 tarball is baked into the image.
    # Production overrides the tag via env when cutting a new release.
    # Artifact is produced by the Benidrissa/sira-nllb-distill pipeline and
    # published as ct2_int8.tar.gz on a GitHub release.
    nllb_artifact_release_repo: str = "Benidrissa/sira-nllb-distill"
    nllb_artifact_release_tag: str = "v1.0.0"

    # Tutor voice output (#1932) — aliases, NEVER dated snapshots. OpenAI's
    # 2026-07-23 snapshot sunset becomes a no-op as long as these stay on the
    # unversioned aliases. If OpenAI consolidates TTS into the realtime stack
    # medium-term (gpt-4o-mini-tts-2025-03-20 → substitute gpt-realtime on the
    # 2026-04-22 deprecation page), the swap is isolated to TutorAudioService.
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_realtime_model: str = "gpt-realtime-mini"
    # Free-tier cap on live voice-call minutes per user per day. Paid tiers
    # should override via subscription but v1 applies the same cap to all.
    tutor_voice_daily_minutes_cap: int = 10

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
