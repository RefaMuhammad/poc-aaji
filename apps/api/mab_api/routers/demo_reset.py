"""Tombol "Reset data demo" di halaman admin (DATA REKAAN). Lihat mab_api/demo_reset.py."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from mab_api import demo_reset
from mab_api.config import get_settings
from mab_api.deps import require_perm
from mab_api.models import User
from mab_api.rbac import Perm

router = APIRouter(prefix="/demo", tags=["demo"])
log = logging.getLogger(__name__)

PUBLIC_FIELDS = ("state", "step", "step_no", "steps_total", "started_at", "finished_at", "message")


def _redis(request: Request):
    conn = getattr(request.app.state.job_queue, "connection", None)
    if conn is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Redis tidak tersedia")
    return conn


@router.get("/reset")
def reset_status(request: Request) -> dict:
    """Status reset. Tanpa login, karena akun admin ikut terhapus selama reset berjalan."""
    s = get_settings()
    if not demo_reset.enabled(s):
        return {"enabled": False, "state": "idle"}
    st = demo_reset.read_status(_redis(request))
    out = {"enabled": True, **{k: st.get(k) for k in PUBLIC_FIELDS}}
    if st.get("state") == "failed":
        out["log_tail"] = st.get("log_tail") or []
    return out


@router.post("/reset", status_code=status.HTTP_202_ACCEPTED)
def start_reset(request: Request, user: User = Depends(require_perm(Perm.DEMO_RESET))) -> dict:
    """Kosongkan semua data lalu isi ulang data demo. Hanya bila DEMO_MODE=true dan REAL_DATA_ENABLED=false."""
    if not demo_reset.enabled(get_settings()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reset demo tidak tersedia di lingkungan ini")
    redis = _redis(request)
    if not demo_reset.try_start(redis):
        raise HTTPException(status.HTTP_409_CONFLICT, "Reset demo sedang berjalan")
    log.warning("Reset data demo dimulai oleh %s", user.email)
    launcher = getattr(request.app.state, "demo_reset_launcher", None) or demo_reset.launch
    try:
        launcher()
    except Exception as e:
        demo_reset.release(redis)
        demo_reset._write_status(redis, state="failed", message=f"Gagal memulai reset: {type(e).__name__}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Gagal memulai reset demo") from e
    return reset_status(request)
