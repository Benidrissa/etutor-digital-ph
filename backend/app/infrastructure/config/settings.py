from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/santepublique_aof"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/santepublique_aof"

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

    # OpenAI Embeddings
    openai_api_key: str = ""

    # Embeddings
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:3000"
    api_v1_prefix: str = "/api/v1"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()


def get_settings() -> Settings:
    """Get application settings."""
    return settings
