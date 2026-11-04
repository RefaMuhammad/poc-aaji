from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mab_api.audit import AuditMiddleware
from mab_api.config import get_settings
from mab_api.routers import auth, claims, documents, users


def create_app(*, session_factory=None, storage=None, job_queue=None) -> FastAPI:
    """Buat aplikasi. Tes bisa menyuntikkan session factory, storage, dan antrean sendiri."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Data rekaan untuk demonstrasi. Tahap 0 POC Platform MAB Indonesia.",
        version="0.3.0",
    )

    if session_factory is None:
        from mab_api.db import make_session_factory

        session_factory = make_session_factory()
    if storage is None:
        from mab_api.storage import S3Storage

        storage = S3Storage(settings.s3_endpoint_url, settings.s3_bucket, settings.minio_root_user, settings.minio_root_password)
    if job_queue is None:
        from mab_api.job_queue import RQJobQueue

        job_queue = RQJobQueue(settings.redis_url, settings.rq_queue)

    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.job_queue = job_queue

    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["sistem"])
    def health() -> dict[str, str]:
        """Pemeriksaan sederhana bahwa API hidup."""
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(claims.router)
    app.include_router(documents.router)
    app.include_router(users.router)
    return app


# uvicorn mab_api.main:app  (Redis, S3, dan Postgres baru dihubungi saat dipakai, bukan saat impor)
app = create_app()
