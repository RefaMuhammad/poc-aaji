import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from mab_api.audit import AuditMiddleware
from mab_api.config import get_settings
from mab_api.observability import RequestContextMiddleware, refresh_queue_metrics, render_metrics, setup_logging
from mab_api.ratelimit import FailureLimiter
from mab_api.routers import admin, auth, claims, dashboard, demo_reset, disputes, documents, fraud, integrations, policies, portal, reports, review, tenants, underwriting, users


log = logging.getLogger(__name__)


def create_app(*, session_factory=None, storage=None, job_queue=None, limiter=None) -> FastAPI:
    """Buat aplikasi. Tes bisa menyuntikkan session factory, storage, dan antrean sendiri."""
    settings = get_settings()
    problems = settings.readiness_problems()
    if problems:
        # Staging/produksi tidak boleh jalan dengan rahasia bawaan atau gerbang data sungguhan yang belum lengkap.
        raise RuntimeError(f"Konfigurasi belum aman untuk {settings.environment}: " + "; ".join(problems))
    app = FastAPI(
        title=settings.app_name,
        description="Data rekaan untuk demonstrasi. Tahap 0 POC Platform MAB Indonesia.",
        version="0.5.0",
    )

    if session_factory is None:
        from mab_api.db import make_session_factory

        session_factory = make_session_factory()
    if storage is None:
        from mab_api.storage import S3Storage

        storage = S3Storage.from_settings(settings)
    if job_queue is None:
        from mab_api.job_queue import RQJobQueue

        job_queue = RQJobQueue.from_settings(settings)
    redis_conn = getattr(job_queue, "connection", None)
    if limiter is None:
        limiter = FailureLimiter(settings.auth_max_failures, settings.auth_lockout_seconds, redis=redis_conn)

    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.job_queue = job_queue
    app.state.limiter = limiter

    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    )
    # Paling luar: request id dan header keamanan juga ada di respons error dan respons CORS.
    app.add_middleware(RequestContextMiddleware, hsts=settings.environment != "development")

    @app.get("/health", tags=["sistem"])
    @app.get("/health/live", tags=["sistem"])
    def health() -> dict[str, str]:
        """Liveness: proses API hidup. Tidak memeriksa dependensi supaya pod tidak di-restart saat database sesaat lambat."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["sistem"])
    def ready() -> JSONResponse:
        """Readiness: database, Redis, dan penyimpanan objek bisa dihubungi. Pod baru menerima trafik bila semua ok."""
        checks: dict[str, str] = {}
        try:
            with app.state.session_factory() as db:
                db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:  # noqa: BLE001 - laporkan jenis error saja, tanpa detail koneksi
            checks["database"] = f"gagal: {type(e).__name__}"
        try:
            if redis_conn is not None:
                redis_conn.ping()
            checks["redis"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["redis"] = f"gagal: {type(e).__name__}"
        try:
            ping = getattr(app.state.storage, "ping", None)
            if ping:
                ping()
            checks["storage"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["storage"] = f"gagal: {type(e).__name__}"
        ok = all(v == "ok" for v in checks.values())
        if not ok:
            log.warning("Readiness gagal: %s", checks)
        return JSONResponse({"status": "ok" if ok else "tidak siap", "checks": checks}, status_code=200 if ok else 503)

    if settings.metrics_enabled:
        @app.get("/metrics", include_in_schema=False)
        def metrics(request: Request) -> Response:
            """Metrik Prometheus. Tidak diekspos lewat ingress; dibatasi NetworkPolicy dan token opsional."""
            if settings.metrics_token and request.headers.get("authorization") != f"Bearer {settings.metrics_token}":
                raise HTTPException(401, "Token metrik salah")
            refresh_queue_metrics(redis_conn, getattr(job_queue, "queue_names", []))
            body, ctype = render_metrics()
            return Response(body, media_type=ctype)

    app.include_router(auth.router)
    app.include_router(claims.router)
    app.include_router(documents.router)
    app.include_router(users.router)
    app.include_router(review.router)
    app.include_router(admin.router)
    app.include_router(dashboard.router)
    app.include_router(tenants.router)
    app.include_router(integrations.router)
    app.include_router(integrations.demo_router)
    app.include_router(policies.router)
    app.include_router(fraud.router)
    app.include_router(portal.router)
    app.include_router(disputes.router)
    app.include_router(reports.router)
    app.include_router(underwriting.router)
    app.include_router(demo_reset.router)
    return app


# uvicorn mab_api.main:app  (Redis, S3, dan Postgres baru dihubungi saat dipakai, bukan saat impor)
setup_logging(get_settings().log_format, get_settings().log_level)
app = create_app()
