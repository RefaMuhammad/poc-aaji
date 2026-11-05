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
    # U2: aturan benefit polis. Kosong = aturan_benefit_demo.yaml di folder yang sama dengan rules_path.
    benefit_rules_path: str | None = None
    # U2: SFTP batch. Folder per tenant: <sftp_root>/<KODE_TENANT>/{masuk,keluar,diproses,gagal}
    sftp_root: str = "/data/sftp"
    # U2: webhook keluar
    webhook_timeout_seconds: float = 5.0
    webhook_max_attempts: int = 3
    # U3: aturan fraud. Kosong = aturan_fraud_demo.yaml di folder yang sama dengan rules_path.
    fraud_rules_path: str | None = None
    # U7: aturan underwriting. Kosong = aturan_underwriting_demo.yaml di folder yang sama dengan rules_path.
    underwriting_rules_path: str | None = None

    def resolved_benefit_rules_path(self) -> str:
        from pathlib import Path

        return self.benefit_rules_path or str(Path(self.rules_path).with_name("aturan_benefit_demo.yaml"))

    def resolved_fraud_rules_path(self) -> str:
        from pathlib import Path

        return self.fraud_rules_path or str(Path(self.rules_path).with_name("aturan_fraud_demo.yaml"))

    def resolved_underwriting_rules_path(self) -> str:
        from pathlib import Path

        return self.underwriting_rules_path or str(Path(self.rules_path).with_name("aturan_underwriting_demo.yaml"))
    llm_provider: str = "mock"
    # Tampilkan pemilih "Ganti peran (demo)" di portal. Hanya untuk data rekaan.
    demo_mode: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
