"""Cakupan data: klaim mana yang boleh dilihat pengguna, dan tenant mana yang boleh dilayaninya."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import Select, false, or_, select
from sqlalchemy.orm import Session

from mab_api.models import DOCTOR_ROLES, Claim, ClaimStatus, Role, User, UserTenant


def _role(user: User) -> Role | None:
    try:
        return Role(user.role)
    except ValueError:
        return None


def tenant_ids(db: Session, user: User) -> set[str] | None:
    """Tenant (insurer_id) yang boleh dilayani pengguna. None = semua tenant (admin, dokter panel MAB)."""
    role = _role(user)
    if role in (Role.ADMIN, *DOCTOR_ROLES):
        return None
    if role == Role.AUDITOR and user.insurer_id is None:
        return None  # auditor platform (mis. OJK) melihat semua tenant
    ids = {user.insurer_id} if user.insurer_id else set()
    if role == Role.TPA_OPERATOR:
        ids |= set(db.scalars(select(UserTenant.insurer_id).where(UserTenant.user_id == user.id)))
    return ids


def visible_claims_query(user: User, db: Session | None = None) -> Select:
    """Klaim yang boleh dilihat pengguna. Peran yang tidak disebut di sini tidak melihat klaim apa pun.

    - Staf/manajer asuransi, auditor tenant: klaim milik asuransinya.
    - Operator TPA: klaim milik semua asuransi yang dilayaninya.
    - Auditor platform (tanpa tenant) dan admin: semua klaim.
    - Dokter: klaim yang ditugaskan kepadanya, atau yang menunggu dokter dan belum ditugaskan.
    - Petugas faskes: klaim dari rumah sakitnya. Peserta: klaim atas nomor pesertanya di asuransinya.
    """
    q = select(Claim)
    role = _role(user)
    if role in (Role.INSURER_STAFF, Role.INSURER_MANAGER):
        return q.where(Claim.insurer_id == user.insurer_id) if user.insurer_id else q.where(false())
    if role == Role.TPA_OPERATOR:
        if db is None:
            raise RuntimeError("visible_claims_query butuh sesi database untuk operator TPA")
        ids = tenant_ids(db, user) or set()
        return q.where(Claim.insurer_id.in_(ids)) if ids else q.where(false())
    if role == Role.AUDITOR:
        return q.where(Claim.insurer_id == user.insurer_id) if user.insurer_id else q
    if role in DOCTOR_ROLES:
        return q.where(
            or_(
                Claim.assigned_doctor_id == user.id,
                (Claim.assigned_doctor_id.is_(None)) & (Claim.status == ClaimStatus.AWAITING_DOCTOR.value),
            )
        )
    if role == Role.FACILITY_OFFICER:
        return q.where(Claim.hospital_name == user.facility_name) if user.facility_name else q.where(false())
    if role == Role.MEMBER:
        if not (user.member_ref and user.insurer_id):
            return q.where(false())
        return q.where(Claim.member_id == user.member_ref, Claim.insurer_id == user.insurer_id)
    if role == Role.ADMIN:
        return q
    return q.where(false())


def get_visible_claim(db: Session, user: User, claim_id: str) -> Claim:
    claim = db.scalar(visible_claims_query(user, db).where(Claim.id == claim_id))
    if claim is None:
        # 404, bukan 403, supaya keberadaan klaim asuransi lain tidak bocor
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Klaim tidak ditemukan")
    return claim


def resolve_target_tenant(db: Session, user: User, requested: str | None) -> str:
    """Tenant tujuan untuk klaim baru. Staf asuransi: tenant sendiri. TPA: wajib memilih salah satu tenantnya."""
    allowed = tenant_ids(db, user) or set()
    if requested:
        if requested not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Anda tidak melayani asuransi tersebut")
        return requested
    if user.insurer_id and user.insurer_id in allowed:
        return user.insurer_id
    if len(allowed) == 1:
        return next(iter(allowed))
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pilih asuransi (insurer_id) untuk klaim ini")
