from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from mab_api.access import get_visible_claim
from mab_api.db import get_db
from mab_api.deps import get_current_user, get_storage
from mab_api.models import Document, User

router = APIRouter(prefix="/documents", tags=["dokumen"])


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    storage=Depends(get_storage),
) -> Response:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan")
    get_visible_claim(db, user, doc.claim_id)  # 404 bila klaimnya tidak boleh dilihat
    data = storage.get(doc.storage_key)
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(doc.filename)}"},
    )
