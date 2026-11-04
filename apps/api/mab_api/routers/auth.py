from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.api_schemas import LoginRequest, TokenResponse, UserOut
from mab_api.db import get_db
from mab_api.deps import get_current_user
from mab_api.models import User
from mab_api.security import create_access_token, verify_secret

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not user.is_active or not verify_secret(body.password, user.password_hash):
        audit.record(db, "LOGIN_FAILED", detail={"email": body.email.strip().lower()}, request=request, status_code=401)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email atau password salah")
    audit.record(db, "LOGIN", user_id=user.id, user_role=user.role, request=request, status_code=200)
    db.commit()
    token = create_access_token(user.id, user.role, user.insurer_id)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
