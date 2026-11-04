from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mab_api.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Data rekaan untuk demonstrasi. Tahap 0 POC Platform MAB Indonesia.",
    version="0.0.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Pemeriksaan sederhana bahwa API hidup."""
    return {"status": "ok"}
