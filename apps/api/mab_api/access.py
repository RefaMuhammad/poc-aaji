"""Aturan siapa boleh melihat klaim apa."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from mab_api.models import DOCTOR_ROLES, INSURER_ROLES, Claim, ClaimStatus, Role, User


def _role(user: User) -> Role:
    return Role(user.role)


def visible_claims_query(user: User) -> Select:
    """Klaim yang boleh dilihat pengguna.

    - Staf/manajer asuransi: semua klaim milik asuransinya.
    - Dokter: klaim yang ditugaskan kepadanya, atau yang menunggu dokter dan belum ditugaskan.
    - Admin: semua klaim.
    """
    q = select(Claim)
    role = _role(user)
    if role in INSURER_ROLES:
        return q.where(Claim.insurer_id == user.insurer_id)
    if role in DOCTOR_ROLES:
        return q.where(
            or_(
                Claim.assigned_doctor_id == user.id,
                (Claim.assigned_doctor_id.is_(None)) & (Claim.status == ClaimStatus.AWAITING_DOCTOR.value),
            )
        )
    return q


def get_visible_claim(db: Session, user: User, claim_id: str) -> Claim:
    claim = db.scalar(visible_claims_query(user).where(Claim.id == claim_id))
    if claim is None:
        # 404, bukan 403, supaya keberadaan klaim asuransi lain tidak bocor
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Klaim tidak ditemukan")
    return claim
