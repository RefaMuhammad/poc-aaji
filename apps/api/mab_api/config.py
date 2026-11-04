from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfigurasi API, dibaca dari variabel lingkungan (.env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MAB Indonesia POC API"
    llm_provider: str = "mock"
    database_url: str = "postgresql+psycopg://mab:mab_dev_password@postgres:5432/mab"
    redis_url: str = "redis://redis:6379/0"
    rq_queue: str = "claims"
    s3_endpoint_url: str = "http://minio:9000"
    s3_bucket: str = "mab-documents"
    rules_path: str = "/app/rules/aturan_klinis_demo.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
