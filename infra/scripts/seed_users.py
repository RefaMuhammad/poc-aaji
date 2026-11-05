"""Buat 2 asuransi (tenant) demo dengan pengaturan berbeda dan satu akun untuk setiap peran (DATA REKAAN).

Pemakaian (di container api):
    python infra/scripts/seed_users.py
Password diambil dari DEMO_PASSWORD (default: demo12345). Aman dijalankan ulang:
akun dan tenant yang sudah ada tidak diubah.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from mab_api.db import make_session_factory  # noqa: E402
from mab_api.models import Insurer, Role, TenantSettings, User, UserTenant  # noqa: E402
from mab_api.security import hash_secret  # noqa: E402


def _svg_logo(initials: str, color: str) -> str:
    """Logo rekaan sederhana (inisial di kotak berwarna), bukan logo perusahaan sungguhan."""
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='{color}'/>"
           f"<text x='32' y='41' font-family='Arial,sans-serif' font-size='26' font-weight='700' fill='white' "
           f"text-anchor='middle'>{initials}</text></svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# Dua tenant berdampingan: tampilan, ambang triase, dan SLA berbeda (U1).
INSURERS = [
    {"code": "DEMO", "name": "Asuransi Sehat Demo (rekaan)",
     "settings": {"display_name": "Asuransi Sehat Demo", "logo_data_url": _svg_logo("SD", "#0f766e"),
                  "primary_color": "#0f766e", "sla_gp_hours": 24, "sla_specialist_hours": 48}},
    {"code": "PELITA", "name": "Asuransi Pelita Demo (rekaan)",
     "settings": {"display_name": "Asuransi Pelita Demo", "logo_data_url": _svg_logo("PD", "#b45309"),
                  "primary_color": "#b45309", "triage_red_min_score": 20, "sla_gp_hours": 8, "sla_specialist_hours": 24}},
]
INSURER = INSURERS[0]  # tenant utama demo (kompatibel dengan skrip lama)

# (email, nama, peran, kode tenant atau None, spesialisasi)
DEMO_USERS = [
    ("staf@demo.test", "Staf Klaim Demo", Role.INSURER_STAFF, "DEMO", None),
    ("manajer@demo.test", "Manajer Klaim Demo", Role.INSURER_MANAGER, "DEMO", None),
    ("dokter.umum@mab.test", "dr. Dokter Umum Demo", Role.DOCTOR_GP, None, None),
    ("dokter.spesialis@mab.test", "dr. Spesialis Demo, Sp.PD", Role.DOCTOR_SPECIALIST, None, "Penyakit Dalam"),
    # U5: spesialis kedua bidang yang sama, untuk telaah banding (harus berbeda dari penelaah awal)
    ("dokter.spesialis2@mab.test", "dr. Spesialis Banding Demo, Sp.PD", Role.DOCTOR_SPECIALIST, None, "Penyakit Dalam"),
    ("admin@mab.test", "Admin MAB Demo", Role.ADMIN, None, None),
    # U1: tenant kedua dan peran baru
    ("staf@pelita.test", "Staf Klaim Pelita", Role.INSURER_STAFF, "PELITA", None),
    ("manajer@pelita.test", "Manajer Klaim Pelita", Role.INSURER_MANAGER, "PELITA", None),
    ("tpa@mab.test", "Operator TPA Demo", Role.TPA_OPERATOR, None, None),
    ("auditor@demo.test", "Auditor Internal Demo", Role.AUDITOR, "DEMO", None),
    ("auditor@ojk.test", "Auditor Regulator Demo", Role.AUDITOR, None, None),
    ("faskes@demo.test", "Petugas Klaim RS Demo", Role.FACILITY_OFFICER, None, None),
    ("peserta@demo.test", "Peserta Demo", Role.MEMBER, "DEMO", None),
    ("underwriter@demo.test", "Underwriter Demo", Role.UNDERWRITER, "DEMO", None),
]
TPA_TENANTS = {"tpa@mab.test": ["DEMO", "PELITA"]}
# Nilai bawaan; seed_demo.py menyamakannya dengan data sintetis (link_portal_accounts).
DEFAULT_FACILITY = "RSU Harapan Bunda"
DEFAULT_MEMBER_REF = "PST-15720019"


def seed(session_factory=None, password: str | None = None, skip: frozenset[str] = frozenset()) -> list[str]:
    """Buat tenant dan akun demo yang belum ada. `skip`: email yang belum dibuat sekarang (lihat seed_demo.py)."""
    password = password or os.environ.get("DEMO_PASSWORD", "demo12345")
    session_factory = session_factory or make_session_factory()
    created = []
    with session_factory() as db:
        tenants: dict[str, Insurer] = {}
        for spec in INSURERS:
            insurer = db.scalar(select(Insurer).where(Insurer.code == spec["code"]))
            if insurer is None:
                insurer = Insurer(code=spec["code"], name=spec["name"])
                db.add(insurer)
                db.flush()
            if db.get(TenantSettings, insurer.id) is None:
                db.add(TenantSettings(insurer_id=insurer.id, version=1, disabled_rules=[], auto_assign=True,
                                      **spec["settings"]))
            tenants[spec["code"]] = insurer
        for email, name, role, tenant, specialty in DEMO_USERS:
            if email in skip or db.scalar(select(User).where(User.email == email)):
                continue
            user = User(
                email=email,
                full_name=name,
                role=role.value,
                insurer_id=tenants[tenant].id if tenant else None,
                specialty=specialty,
                password_hash=hash_secret(password),
                pin_hash=hash_secret("123456") if role in (Role.DOCTOR_GP, Role.DOCTOR_SPECIALIST) else None,
                facility_name=DEFAULT_FACILITY if role == Role.FACILITY_OFFICER else None,
                member_ref=DEFAULT_MEMBER_REF if role == Role.MEMBER else None,
            )
            db.add(user)
            db.flush()
            for code in TPA_TENANTS.get(email, []):
                db.add(UserTenant(user_id=user.id, insurer_id=tenants[code].id))
            created.append(email)
        db.commit()
    return created


def link_portal_accounts(facility_name: str, member_ref: str, session_factory=None) -> None:
    """Samakan RS akun faskes dan nomor peserta akun peserta dengan data sintetis yang diunggah."""
    session_factory = session_factory or make_session_factory()
    with session_factory() as db:
        for user in db.scalars(select(User).where(User.role.in_([Role.FACILITY_OFFICER.value, Role.MEMBER.value]))):
            if user.role == Role.FACILITY_OFFICER.value:
                user.facility_name = facility_name
            else:
                user.member_ref = member_ref
        db.commit()


if __name__ == "__main__":
    created = seed()
    print(f"Akun baru: {', '.join(created) if created else '(tidak ada, semua sudah ada)'}")
    print("Password semua akun demo: nilai DEMO_PASSWORD (default demo12345). PIN dokter: 123456")
    print("Tenant: DEMO (ambang bawaan, SLA dokter umum 24 jam) dan PELITA (ambang merah 20, SLA dokter umum 8 jam)")
