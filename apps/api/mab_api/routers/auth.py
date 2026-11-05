from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.api_schemas import DemoAccountOut, DemoSwitchRequest, LoginRequest, TokenResponse, UserOut
from mab_api.config import get_settings
from mab_api.demo import DEMO_ACCOUNTS, DEMO_EMAILS
from mab_api.db import get_db
from mab_api.deps import get_current_user
from mab_api.models import User
from mab_api.observability import AUTH_LOCKOUTS
from mab_api.security import create_access_token, verify_secret

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = body.email.strip().lower()
    limiter = request.app.state.limiter
    # Batas per akun (menebak password satu akun) dan per alamat IP (menebak banyak akun dari satu sumber).
    ip = request.client.host if request.client else "?"
    keys = [f"login:{email}", f"login-ip:{ip}"]
    for key, limit in zip(keys, (None, get_settings().auth_ip_max_failures)):
        if limiter.blocked(key, limit):
            AUTH_LOCKOUTS.labels("login").inc()
            audit.record(db, "LOGIN_LOCKED", detail={"email": email}, request=request, status_code=429)
            db.commit()
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Terlalu banyak percobaan login gagal. Coba lagi nanti.",
                                headers={"Retry-After": str(limiter.retry_after(key))})
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_secret(body.password, user.password_hash):
        for key in keys:
            limiter.fail(key)
        audit.record(db, "LOGIN_FAILED", detail={"email": email}, request=request, status_code=401)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email atau password salah")
    limiter.reset(keys[0])
    audit.record(db, "LOGIN", user_id=user.id, user_role=user.role, request=request, status_code=200)
    db.commit()
    token = create_access_token(user.id, user.role, user.insurer_id)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/demo-accounts", response_model=list[DemoAccountOut])
def demo_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[DemoAccountOut]:
    """Akun demo yang bisa dipilih di "Ganti peran (demo)". Kosong bila mode demo mati."""
    if not get_settings().demo_mode or user.email not in DEMO_EMAILS:
        return []
    users = {u.email: u for u in db.scalars(select(User).where(User.email.in_(DEMO_EMAILS), User.is_active.is_(True)))}
    return [DemoAccountOut(email=e, label=label, full_name=users[e].full_name, role=users[e].role)
            for e, label in DEMO_ACCOUNTS if e in users]


@router.post("/demo-switch", response_model=TokenResponse)
def demo_switch(body: DemoSwitchRequest, request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> TokenResponse:
    """Pindah ke akun demo lain tanpa mengetik password. Hanya antar-akun demo, hanya di mode demo."""
    email = body.email.strip().lower()
    if not get_settings().demo_mode or user.email not in DEMO_EMAILS or email not in DEMO_EMAILS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ganti peran hanya tersedia untuk akun demo di mode demo")
    target = db.scalar(select(User).where(User.email == email))
    if target is None or not target.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Akun demo tidak ditemukan")
    audit.record(db, "DEMO_SWITCH", user_id=target.id, user_role=target.role, request=request, status_code=200,
                 detail={"from": user.email, "to": target.email})
    db.commit()
    token = create_access_token(target.id, target.role, target.insurer_id)
    return TokenResponse(access_token=token, user=UserOut.model_validate(target))
