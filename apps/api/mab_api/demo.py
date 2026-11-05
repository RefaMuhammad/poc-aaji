"""Mode demo: pindah cepat antar-akun demo dalam satu jendela browser (DATA REKAAN).

Bukan peran super. Setiap langkah tetap dijalankan oleh akun dengan peran yang benar
(staf mengunggah, dokter menandatangani, manajer melihat dashboard), jadi pemisahan peran
dan log audit tetap utuh. Matikan dengan DEMO_MODE=false.
"""
from __future__ import annotations

# Urutan = urutan alur demo: unggah -> telaah dokter -> keputusan asuransi -> dashboard.
DEMO_ACCOUNTS: list[tuple[str, str]] = [
    ("staf@demo.test", "1. Staf klaim: unggah & keputusan"),
    ("dokter.umum@mab.test", "2. Dokter umum: telaah kasus kuning"),
    ("dokter.spesialis@mab.test", "3. Dokter spesialis: telaah kasus merah"),
    ("manajer@demo.test", "4. Manajer klaim: dashboard"),
    ("admin@mab.test", "5. Admin MAB: aturan & semua data"),
]
DEMO_EMAILS = {email for email, _ in DEMO_ACCOUNTS}
