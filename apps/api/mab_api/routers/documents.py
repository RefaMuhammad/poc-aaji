from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from mab_api.access import get_visible_claim
from mab_api.db import get_db
from mab_api.deps import get_storage, require_perm
from mab_api.rbac import Perm
from mab_api.models import Document, User
from mab_api.rendering import PageNotFound, render_page_png

router = APIRouter(prefix="/documents", tags=["dokumen"])


def _visible_document(db: Session, user: User, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan")
    get_visible_claim(db, user, doc.claim_id)  # 404 bila klaimnya tidak boleh dilihat
    return doc


@router.get("/{document_id}/pages/{page}.png")
def page_image(
    document_id: str,
    page: int,
    dpi: int = Query(default=110, ge=50, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_perm(Perm.CLAIM_DETAIL)),
    storage=Depends(get_storage),
) -> Response:
    """Gambar satu halaman dokumen untuk pratinjau bukti (bbox bukti dalam proporsi halaman)."""
    doc = _visible_document(db, user, document_id)
    try:
        png = render_page_png(storage.get(doc.storage_key), doc.content_type, page, dpi)
    except PageNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_perm(Perm.CLAIM_DETAIL)),
    storage=Depends(get_storage),
) -> Response:
    doc = _visible_document(db, user, document_id)
    data = storage.get(doc.storage_key)
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(doc.filename)}"},
    )
