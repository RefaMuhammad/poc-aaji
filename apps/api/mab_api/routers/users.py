from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api.api_schemas import UserOut
from mab_api.db import get_db
from mab_api.deps import require_perm
from mab_api.models import User
from mab_api.rbac import Perm

router = APIRouter(prefix="/users", tags=["admin"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_perm(Perm.USER_ADMIN))) -> list[User]:
    return list(db.scalars(select(User).order_by(User.role, User.email)))
