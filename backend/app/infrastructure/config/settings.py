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

    # Supabase Auth
    supabase_url: str = ""
    supabase_jwt_secret: str = ""

    # Anthropic Claude API
    anthropic_api_key: str = ""

    # OpenAI Embeddings
    openai_api_key: str = ""

    # ChromaDB
    chromadb_host: str = "localhost"
    chromadb_port: int = 8100

    # App
    app_env: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]
    api_v1_prefix: str = "/api/v1"


settings = Settings()
