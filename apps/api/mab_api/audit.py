"""Log audit: middleware untuk aksi tulis dan akses dokumen, plus fungsi pencatat manual."""
from __future__ import annotations

import logging
import re

import jwt
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from mab_api.models import AuditLog
from mab_api.security import decode_access_token

log = logging.getLogger(__name__)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_DOCUMENT_ACCESS = re.compile(r"^/documents/(?P<doc>[0-9a-f-]{36})(/|$)")
_CLAIM_IN_PATH = re.compile(r"^/claims/(?P<claim>[0-9a-f-]{36})(/|$)")
_SKIP_PATHS = {"/auth/login"}  # login dicatat sendiri oleh endpoint (berhasil/gagal)


def record(
    db: Session,
    action: str,
    *,
    user_id: str | None = None,
    user_role: str | None = None,
    claim_id: str | None = None,
    document_id: str | None = None,
    detail: dict | None = None,
    request: Request | None = None,
    status_code: int | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            user_id=user_id,
            user_role=user_role,
            claim_id=claim_id,
            document_id=document_id,
            detail=detail or {},
            method=request.method if request else None,
            path=request.url.path if request else None,
            ip_address=request.client.host if request and request.client else None,
            status_code=status_code,
        )
    )


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        is_doc_access = request.method == "GET" and _DOCUMENT_ACCESS.match(path)
        if path in _SKIP_PATHS or not (request.method in _WRITE_METHODS or is_doc_access):
            return response

        user_id = role = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = decode_access_token(auth[7:])
                user_id, role = payload.get("sub"), payload.get("role")
            except jwt.PyJWTError:
                pass
        claim = _CLAIM_IN_PATH.match(path)
        doc = _DOCUMENT_ACCESS.match(path)
        try:
            session = request.app.state.session_factory()
            try:
                record(
                    session,
                    "DOCUMENT_ACCESS" if is_doc_access else f"{request.method} {path}",
                    user_id=user_id,
                    user_role=role,
                    claim_id=claim.group("claim") if claim else None,
                    document_id=doc.group("doc") if doc else None,
                    request=request,
                    status_code=response.status_code,
                )
                session.commit()
            finally:
                session.close()
        except Exception:  # log audit tidak boleh menjatuhkan request, tapi harus terlihat
            log.exception("Gagal menulis log audit untuk %s %s", request.method, path)
        return response
