"""U8: log JSON, request id, metrik Prometheus, dan header keamanan.

Log JSON ditulis ke stdout satu baris per kejadian, lalu dikumpulkan oleh agen log klaster
(Cloud Logging, CloudWatch, Azure Monitor, atau Loki). Isi log tidak memuat isi dokumen atau data medis:
hanya metode, rute, status, durasi, dan id.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            out["request_id"] = rid
        for key in ("method", "route", "status", "duration_ms", "client_ip", "user_id"):
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup_logging(fmt: str = "text", level: str = "INFO") -> None:
    """Pasang handler stdout. Dipanggil sekali saat API/worker start."""
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Log akses uvicorn diganti log permintaan dari middleware di bawah (sudah memuat request id dan durasi).
    if fmt == "json":
        logging.getLogger("uvicorn.access").disabled = True
        for name in ("uvicorn", "uvicorn.error"):
            logging.getLogger(name).handlers[:] = []
            logging.getLogger(name).propagate = True


# --- Metrik ---
try:
    from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

    REGISTRY = CollectorRegistry(auto_describe=True)
    HTTP_REQUESTS = Counter("mab_http_requests_total", "Jumlah permintaan HTTP", ["method", "route", "status"], registry=REGISTRY)
    HTTP_LATENCY = Histogram("mab_http_request_duration_seconds", "Durasi permintaan HTTP", ["method", "route"],
                             buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30), registry=REGISTRY)
    QUEUE_DEPTH = Gauge("mab_queue_depth", "Jumlah job menunggu di antrean RQ", ["queue"], registry=REGISTRY)
    QUEUE_FAILED = Gauge("mab_queue_failed", "Jumlah job gagal di antrean RQ", ["queue"], registry=REGISTRY)
    AUTH_LOCKOUTS = Counter("mab_auth_lockouts_total", "Percobaan yang ditolak karena terlalu banyak gagal", ["kind"], registry=REGISTRY)
except ImportError:  # pragma: no cover - prometheus_client selalu ada di image API
    REGISTRY = None


def route_template(request: Request) -> str:
    """Pola rute (/claims/{claim_id}), bukan path asli, supaya label metrik tidak meledak dan tidak memuat id."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    # API hanya mengembalikan JSON/PDF/gambar; tidak ada skrip yang perlu dijalankan dari respons API.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Request id, header keamanan, metrik, dan satu baris log per permintaan."""

    def __init__(self, app, *, hsts: bool = False):
        super().__init__(app)
        self.hsts = hsts
        self.log = logging.getLogger("mab_api.request")

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID_OK.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            elapsed = time.perf_counter() - start
            route = route_template(request)
            if REGISTRY is not None and route not in {"/metrics", "/health/live", "/health/ready"}:
                HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
                HTTP_LATENCY.labels(request.method, route).observe(elapsed)
            if route not in {"/metrics", "/health", "/health/live", "/health/ready"}:
                self.log.info("%s %s %s", request.method, route, status, extra={
                    "method": request.method, "route": route, "status": status,
                    "duration_ms": round(elapsed * 1000, 1), "client_ip": client_ip(request),
                })
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            # /docs (Swagger UI) butuh skrip; CSP ketat hanya untuk respons API biasa.
            if k == "Content-Security-Policy" and request.url.path in {"/docs", "/redoc"}:
                continue
            response.headers.setdefault(k, v)
        if self.hsts:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


def refresh_queue_metrics(redis_conn, queue_names: list[str]) -> None:
    if REGISTRY is None or redis_conn is None:
        return
    from rq import Queue

    for name in queue_names:
        try:
            q = Queue(name, connection=redis_conn)
            QUEUE_DEPTH.labels(name).set(q.count)
            QUEUE_FAILED.labels(name).set(q.failed_job_registry.count)
        except Exception:
            logging.getLogger(__name__).warning("Gagal membaca panjang antrean %s", name)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
