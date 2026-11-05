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
    POLICY_VIEW = "policy.view"            # U2: lihat polis & plan benefit tenant
    POLICY_MANAGE = "policy.manage"        # U2: impor polis, ubah plan benefit
    FRAUD_VIEW = "fraud.view"              # U3: Fraud Monitor, sinyal fraud, kartu fraud di detail klaim
    FRAUD_MANAGE = "fraud.manage"          # U3: impor riwayat klaim, jalankan analisis, telaah sinyal
    PORTAL_VIEW = "portal.view"            # U4: portal faskes / peserta (status klaim, penjelasan, linimasa)
    FACILITY_UPLOAD = "facility.upload"    # U4: faskes menjawab permintaan dokumen, unggah dokumen susulan
    TPA_OVERVIEW = "tpa.overview"          # U4: ringkasan klaim per asuransi yang dilayani TPA
    DISPUTE_FILE = "dispute.file"          # U5: faskes / peserta mengajukan dan menarik banding
    DISPUTE_VIEW = "dispute.view"          # U5: daftar sengketa lintas klaim (asuransi, TPA, auditor, admin)


_OPERATOR = {Perm.CLAIM_LIST, Perm.CLAIM_DETAIL, Perm.CLAIM_SUBMIT, Perm.CLAIM_DECIDE, Perm.CLAIM_EXPORT,
             Perm.DASHBOARD, Perm.TENANT_VIEW, Perm.POLICY_VIEW, Perm.POLICY_MANAGE, Perm.FRAUD_VIEW,
             Perm.DISPUTE_VIEW}
_DOCTOR = {Perm.CLAIM_LIST, Perm.CLAIM_DETAIL, Perm.REVIEW, Perm.RULESET_VIEW}

ROLE_PERMS: dict[Role, frozenset[Perm]] = {
    Role.INSURER_STAFF: frozenset(_OPERATOR),
    # Manajer klaim juga investigator fraud tenant-nya: impor riwayat, jalankan analisis, telaah sinyal.
    Role.INSURER_MANAGER: frozenset(_OPERATOR | {Perm.FRAUD_MANAGE}),
    Role.TPA_OPERATOR: frozenset(_OPERATOR | {Perm.TPA_OVERVIEW}),
    Role.DOCTOR_GP: frozenset(_DOCTOR),
    Role.DOCTOR_SPECIALIST: frozenset(_DOCTOR),
    Role.AUDITOR: frozenset({Perm.CLAIM_LIST, Perm.CLAIM_DETAIL, Perm.CLAIM_EXPORT, Perm.DASHBOARD,
                             Perm.RULESET_VIEW, Perm.TENANT_VIEW, Perm.POLICY_VIEW, Perm.FRAUD_VIEW,
                             Perm.DISPUTE_VIEW}),
    # Portal faskes & peserta (U4): klaimnya sendiri, status, penjelasan keputusan. Faskes juga
    # menjawab permintaan dokumen. Keduanya tidak melihat draf AI, field hasil baca, atau skor risiko.
    Role.FACILITY_OFFICER: frozenset({Perm.CLAIM_LIST, Perm.PORTAL_VIEW, Perm.FACILITY_UPLOAD, Perm.DISPUTE_FILE}),
    Role.MEMBER: frozenset({Perm.CLAIM_LIST, Perm.PORTAL_VIEW, Perm.DISPUTE_FILE}),
    # Modul underwriting menyusul di U7; underwriter belum punya akses data klaim.
    Role.UNDERWRITER: frozenset(),
    Role.ADMIN: frozenset({Perm.CLAIM_LIST, Perm.CLAIM_DETAIL, Perm.DASHBOARD, Perm.RULESET_VIEW,
                           Perm.TENANT_VIEW, Perm.TENANT_ADMIN, Perm.USER_ADMIN, Perm.ASSIGN_ADMIN,
                           Perm.POLICY_VIEW, Perm.POLICY_MANAGE, Perm.FRAUD_VIEW, Perm.FRAUD_MANAGE,
                           Perm.TPA_OVERVIEW, Perm.DISPUTE_VIEW}),
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
