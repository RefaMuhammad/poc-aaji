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

    jwt_secret: str = "ganti_dengan_rahasia_acak_minimal_32_karakter"
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

    # --- U8: operasi dan kesiapan data sungguhan ---
    # development | staging | production. Selain development, API menolak start bila konfigurasi tidak aman.
    environment: str = "development"
    # text = log biasa (dev), json = satu baris JSON per log (staging/produksi, untuk log terpusat)
    log_format: str = "text"
    log_level: str = "INFO"
    # Antrean RQ per jenis pekerjaan. Worker bisa dipisah per antrean (lihat Helm chart).
    rq_queue_underwriting: str = "underwriting"
    rq_queue_webhooks: str = "webhooks"
    # S3/MinIO: region dan enkripsi sisi server. "" = tanpa header (MinIO dev), AES256 = SSE-S3, aws:kms = SSE-KMS
    s3_region: str = "us-east-1"
    s3_sse: str = ""
    s3_kms_key_id: str | None = None
    # /metrics untuk Prometheus. Token kosong = terbuka (batasi lewat NetworkPolicy); diisi = wajib header Bearer.
    metrics_enabled: bool = True
    metrics_token: str | None = None
    # Batas percobaan login dan PIN tanda tangan (per akun), dalam jendela waktu
    auth_max_failures: int = 5
    auth_lockout_seconds: int = 15 * 60
    # Batas per alamat IP (banyak akun dari satu sumber). Dibuat jauh lebih longgar karena satu kantor
    # asuransi bisa keluar lewat satu IP publik; terlalu ketat malah mengunci semua staf.
    auth_ip_max_failures: int = 100
    # Gerbang data sungguhan. Selama false, platform hanya boleh berisi data rekaan.
    real_data_enabled: bool = False
    # Diisi true hanya setelah keputusan residensi data LLM disetujui (docs/u8-residensi-llm.md)
    llm_data_residency_approved: bool = False

    def readiness_problems(self) -> list[str]:
        """Konfigurasi yang belum aman untuk staging/produksi. Kosong berarti lolos."""
        problems: list[str] = []
        if self.environment == "development":
            return problems
        if self.jwt_secret in {"ganti_dengan_rahasia_acak", "ganti_dengan_rahasia_acak_minimal_32_karakter", ""} or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET masih bawaan atau kurang dari 32 karakter")
        if "mab_dev_password" in self.database_url:
            problems.append("DATABASE_URL masih memakai password dev")
        if self.minio_root_password == "mabminio_dev_password":
            problems.append("MINIO_ROOT_PASSWORD masih password dev")
        if self.log_format != "json":
            problems.append("LOG_FORMAT harus json supaya log bisa dikumpulkan terpusat")
        if any(o.strip().startswith("http://") and "localhost" not in o for o in self.cors_origins.split(",")):
            problems.append("CORS_ORIGINS memuat origin http:// (harus https)")
        if self.real_data_enabled:
            if self.environment != "production":
                problems.append("REAL_DATA_ENABLED hanya boleh di environment production")
            if self.demo_mode:
                problems.append("DEMO_MODE harus false bila memakai data sungguhan")
            if self.llm_provider == "mock":
                problems.append("LLM_PROVIDER mock tidak untuk data sungguhan")
            if not self.llm_data_residency_approved:
                problems.append("Keputusan residensi data LLM belum disetujui (LLM_DATA_RESIDENCY_APPROVED)")
            if not self.s3_sse:
                problems.append("S3_SSE wajib diisi (AES256 atau aws:kms) untuk data sungguhan")
            if "sslmode=require" not in self.database_url and "sslmode=verify" not in self.database_url:
                problems.append("DATABASE_URL harus memakai sslmode=require atau verify-full")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
