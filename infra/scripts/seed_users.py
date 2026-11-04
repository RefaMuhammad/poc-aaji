"""Buat 1 asuransi demo dan satu akun untuk setiap peran (DATA REKAAN).

Pemakaian (di container api):
    python infra/scripts/seed_users.py
Password diambil dari DEMO_PASSWORD (default: demo12345). Aman dijalankan ulang.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from mab_api.db import make_session_factory  # noqa: E402
from mab_api.models import Insurer, Role, User  # noqa: E402
from mab_api.security import hash_secret  # noqa: E402

INSURER = {"code": "DEMO", "name": "Asuransi Sehat Demo (rekaan)"}
DEMO_USERS = [
    ("staf@demo.test", "Staf Klaim Demo", Role.INSURER_STAFF, True, None),
    ("manajer@demo.test", "Manajer Klaim Demo", Role.INSURER_MANAGER, True, None),
    ("dokter.umum@mab.test", "dr. Dokter Umum Demo", Role.DOCTOR_GP, False, None),
    ("dokter.spesialis@mab.test", "dr. Spesialis Demo, Sp.PD", Role.DOCTOR_SPECIALIST, False, "Penyakit Dalam"),
    ("admin@mab.test", "Admin MAB Demo", Role.ADMIN, False, None),
]


def seed(session_factory=None, password: str | None = None) -> list[str]:
    password = password or os.environ.get("DEMO_PASSWORD", "demo12345")
    session_factory = session_factory or make_session_factory()
    created = []
    with session_factory() as db:
        insurer = db.scalar(select(Insurer).where(Insurer.code == INSURER["code"]))
        if insurer is None:
            insurer = Insurer(**INSURER)
            db.add(insurer)
            db.flush()
        for email, name, role, is_insurer, specialty in DEMO_USERS:
            if db.scalar(select(User).where(User.email == email)):
                continue
            db.add(
                User(
                    email=email,
                    full_name=name,
                    role=role.value,
                    insurer_id=insurer.id if is_insurer else None,
                    specialty=specialty,
                    password_hash=hash_secret(password),
                    pin_hash=hash_secret("123456") if role in (Role.DOCTOR_GP, Role.DOCTOR_SPECIALIST) else None,
                )
            )
            created.append(email)
        db.commit()
    return created


if __name__ == "__main__":
    created = seed()
    print(f"Akun baru: {', '.join(created) if created else '(tidak ada, semua sudah ada)'}")
    print("Password semua akun demo: nilai DEMO_PASSWORD (default demo12345). PIN dokter: 123456")
