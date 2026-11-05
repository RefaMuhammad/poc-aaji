"""Matriks hak akses per peran (RBAC).

Satu tempat untuk menjawab "peran X boleh melakukan apa". Endpoint memakai
`require_perm(...)`; cakupan data (tenant, faskes, peserta) diatur di `access.py`.
Matriks yang sama ditampilkan di docs/ARSITEKTUR.md dan diuji di tests/test_rbac.py.
"""
from __future__ import annotations

from enum import Enum

from mab_api.models import Role


class Perm(str, Enum):
    CLAIM_LIST = "claim.list"              # daftar & status klaim (sesuai cakupan data)
    CLAIM_DETAIL = "claim.detail"          # field hasil baca, dokumen, rekomendasi yang sudah dirilis
    CLAIM_SUBMIT = "claim.submit"          # buat klaim, unggah dokumen / ZIP
    CLAIM_DECIDE = "claim.decide"          # keputusan asuransi (setuju / berbeda), setuju massal
    CLAIM_EXPORT = "claim.export"          # ekspor CSV
    DASHBOARD = "dashboard.view"
    REVIEW = "review.perform"              # antrean & telaah dokter, tanda tangan
    RULESET_VIEW = "ruleset.view"
    TENANT_VIEW = "tenant.view"            # lihat pengaturan tenant sendiri
    TENANT_ADMIN = "tenant.admin"          # ubah pengaturan tenant, kelola API key
    USER_ADMIN = "user.admin"
    ASSIGN_ADMIN = "assignment.admin"      # pindahkan penugasan dokter


_OPERATOR = {Perm.CLAIM_LIST, Perm.CLAIM_DETAIL, Perm.CLAIM_SUBMIT, Perm.CLAIM_DECIDE, Perm.CLAIM_EXPORT,
             Perm.DASHBOARD, Perm.TENANT_VIEW}
_DOCTOR = {Perm.CLAIM_LIST, Perm.CLAIM_DETAIL, Perm.REVIEW, Perm.RULESET_VIEW}

ROLE_PERMS: dict[Role, frozenset[Perm]] = {
    Role.INSURER_STAFF: frozenset(_OPERATOR),
    Role.INSURER_MANAGER: frozenset(_OPERATOR),
    Role.TPA_OPERATOR: frozenset(_OPERATOR),
    Role.DOCTOR_GP: frozenset(_DOCTOR),
    Role.DOCTOR_SPECIALIST: frozenset(_DOCTOR),
    Role.AUDITOR: frozenset({Perm.CLAIM_LIST, Perm.CLAIM_DETAIL, Perm.CLAIM_EXPORT, Perm.DASHBOARD,
                             Perm.RULESET_VIEW, Perm.TENANT_VIEW}),
    # Portal faskes & peserta (U4): untuk sekarang hanya daftar dan status klaimnya sendiri.
    Role.FACILITY_OFFICER: frozenset({Perm.CLAIM_LIST}),
    Role.MEMBER: frozenset({Perm.CLAIM_LIST}),
    # Modul underwriting menyusul di U7; underwriter belum punya akses data klaim.
    Role.UNDERWRITER: frozenset(),
    Role.ADMIN: frozenset({Perm.CLAIM_LIST, Perm.CLAIM_DETAIL, Perm.DASHBOARD, Perm.RULESET_VIEW,
                           Perm.TENANT_VIEW, Perm.TENANT_ADMIN, Perm.USER_ADMIN, Perm.ASSIGN_ADMIN}),
}

# Peran yang boleh melihat draf AI sebelum ditandatangani dokter. Selain ini hanya melihat
# rekomendasi yang sudah dirilis (bayar penuh, atau sudah ditandatangani dokter).
DRAFT_VIEWERS = {Role.DOCTOR_GP, Role.DOCTOR_SPECIALIST, Role.ADMIN}

ROLE_LABELS: dict[Role, str] = {
    Role.INSURER_STAFF: "Staf klaim asuransi",
    Role.INSURER_MANAGER: "Manajer klaim asuransi",
    Role.TPA_OPERATOR: "Operator TPA",
    Role.DOCTOR_GP: "Dokter umum (panel MAB)",
    Role.DOCTOR_SPECIALIST: "Dokter spesialis (panel MAB)",
    Role.AUDITOR: "Auditor (internal / OJK)",
    Role.FACILITY_OFFICER: "Petugas faskes",
    Role.MEMBER: "Peserta",
    Role.UNDERWRITER: "Underwriter",
    Role.ADMIN: "Admin MAB",
}


def has_perm(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMS[Role(role)]
    except ValueError:
        return False


def can_see_draft(role: str) -> bool:
    try:
        return Role(role) in DRAFT_VIEWERS
    except ValueError:
        return False
