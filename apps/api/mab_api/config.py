from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfigurasi API, dibaca dari variabel lingkungan (.env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MAB Indonesia POC API"
    database_url: str = "postgresql+psycopg://mab:mab_dev_password@postgres:5432/mab"
    redis_url: str = "redis://redis:6379/0"
    rq_queue: str = "claims"

    s3_endpoint_url: str = "http://minio:9000"
    s3_bucket: str = "mab-documents"
    minio_root_user: str = "mabminio"
    minio_root_password: str = "mabminio_dev_password"

    jwt_secret: str = "ganti_dengan_rahasia_acak"
    jwt_expire_minutes: int = 8 * 60

    max_upload_mb: int = 20
    max_zip_mb: int = 500
    cors_origins: str = "http://localhost:3000"

    rules_path: str = "/app/rules/aturan_klinis_demo.yaml"
    llm_provider: str = "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
