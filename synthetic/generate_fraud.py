"""Generator riwayat klaim sintetis dengan POLA FRAUD TERTANAM (U3, DATA REKAAN).

Fraud analytics butuh populasi: rata-rata sejawat hanya bermakna bila ada ratusan klaim
dari banyak RS dan dokter. Generator ini membuat riwayat klaim terstruktur (tanpa PDF),
seperti data klaim historis yang diekspor dari sistem inti asuransi, lalu menanam
beberapa pola fraud yang diketahui. Kunci jawabannya dipakai evaluasi deteksi
(evaluation/fraud_eval.py): berapa pola tertangkap dan berapa alarm palsu.

Semua nama RS, dokter, peserta, alamat, dan rekening FIKTIF.

Pemakaian:
    python -m synthetic.generate_fraud            # tulis data/synthetic_output/fraud/*.csv
"""
from __future__ import annotations

import csv
import random
from dataclasses import asdict, dataclass, fields
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "synthetic_output" / "fraud"
HISTORY_FILE = "riwayat_klaim.csv"
KEY_FILE = "kunci_pola_fraud.csv"
SEED = 2026
PERIOD_START, PERIOD_END = date(2026, 1, 5), date(2026, 10, 25)

# Kode ICD-10 -> (lama rawat min, maks), biaya per hari dasar (rupiah), pemeriksaan lab per hari
ICD_PROFILE = {
    "A90": ((3, 5), 1_500_000, 1.6),
    "A91": ((4, 6), 1_800_000, 2.0),
    "A01.0": ((5, 7), 1_400_000, 1.0),
    "A09": ((2, 4), 1_200_000, 0.8),
}
ICD_WEIGHTS = {"A90": 25, "A91": 15, "A01.0": 30, "A09": 30}

# (nama, kota, jumlah dokter, faktor tarif). Faktor tarif tetap supaya hasil stabil.
HOSPITALS = [
    ("RS Sehat Sentosa", "Kota Rekaan Barat", 4, 1.04),
    ("RSU Harapan Bunda", "Kabupaten Contoh", 3, 0.95),
    ("RS Mitra Medika Nusantara", "Kota Fiktif Timur", 4, 1.06),
    ("RS Cempaka Rekaan", "Kota Rekaan Barat", 3, 1.00),
    ("RS Anggrek Fiktif", "Kota Contoh Utara", 3, 0.97),
    ("RSU Melati Contoh", "Kabupaten Contoh", 5, 0.99),
    ("RS Kenari Demo", "Kota Fiktif Timur", 3, 1.02),
    ("RS Teratai Rekaan", "Kota Contoh Utara", 3, 0.96),
    ("RS Bakti Rekaan", "Kota Contoh Selatan", 3, 1.01),
    ("RS Wijaya Kusuma Demo", "Kota Contoh Selatan", 3, 0.98),
]
# Rujukan normal: satu arah, dari RS kecil ke RS rujukan
NORMAL_REFERRALS = [
    ("RS Kenari Demo", "RS Mitra Medika Nusantara"),
    ("RS Wijaya Kusuma Demo", "RS Sehat Sentosa"),
    ("RSU Harapan Bunda", "RS Sehat Sentosa"),
    ("RS Anggrek Fiktif", "RSU Melati Contoh"),
]

FIRST = ["Sari", "Dewi", "Rina", "Ayu", "Lestari", "Wulan", "Fitri", "Indah", "Maya", "Nadia", "Budi", "Agus", "Rizki",
         "Dimas", "Hendra", "Fajar", "Yoga", "Arif", "Bayu", "Eko", "Putri", "Tari", "Gilang", "Rangga", "Sinta", "Joko",
         "Wati", "Iwan", "Nur", "Dian"]
LAST = ["Pratama", "Santoso", "Wibowo", "Saputra", "Hidayat", "Kusuma", "Permana", "Nugroho", "Rahayu", "Setiawan",
        "Gunawan", "Halim", "Siregar", "Lubis", "Nasution", "Tanjung", "Purba", "Sihombing", "Wijaya", "Susanto",
        "Hakim", "Ramadhan", "Firmansyah", "Maulana", "Kurniawan"]
DOCTOR_FIRST = ["Andi", "Bambang", "Citra", "Dedi", "Erna", "Farid", "Gita", "Hadi", "Intan", "Johan", "Kartika",
                "Lukman", "Mira", "Nanda", "Oki", "Prita", "Reza", "Sekar", "Taufik", "Utami", "Vina", "Wahyu",
                "Yanti", "Zul", "Aditya", "Bunga", "Cahyo", "Dina", "Elok", "Fikri", "Galih", "Hesti", "Irfan",
                "Jamal", "Kemala", "Laras", "Miftah"]
STREETS = ["Jl. Kenanga", "Jl. Flamboyan", "Jl. Cendana", "Jl. Merpati", "Jl. Nusa Indah", "Jl. Pahlawan Rekaan",
           "Jl. Sudirman Contoh", "Jl. Diponegoro Fiktif", "Jl. Mawar", "Jl. Seroja", "Gg. Damai", "Jl. Bougenville"]

SPECIALTY = ", Sp.PD"


@dataclass
class HistoryClaim:
    """Satu baris riwayat_klaim.csv. Nama kolom = nama kolom impor di platform."""

    nomor_klaim: str
    id_peserta: str
    nama_peserta: str
    alamat_peserta: str
    rekening_bank: str
    rumah_sakit: str
    dokter: str
    rujukan_dari: str
    icd10: str
    tanggal_masuk: str
    tanggal_keluar: str
    total_tagihan: int
    jumlah_pemeriksaan_lab: int


HISTORY_COLUMNS = [f.name for f in fields(HistoryClaim)]


@dataclass
class PlantedPattern:
    pola_id: str
    nama: str
    aturan_diharapkan: str      # id aturan fraud yang semestinya menangkap pola ini
    jenis_entitas: str          # HOSPITAL / DOCTOR / MEMBER / BANK_ACCOUNT / ADDRESS / REFERRAL_LOOP
    kunci_entitas: str
    keterangan: str


class _Gen:
    def __init__(self, seed: int = SEED):
        self.rng = random.Random(seed)
        self.claims: list[HistoryClaim] = []
        self.patterns: list[PlantedPattern] = []
        self.member_seq = 0
        self.claim_seq = 0
        used: set[str] = set()
        self.doctors: dict[str, list[str]] = {}
        names = list(DOCTOR_FIRST)
        self.rng.shuffle(names)
        for hospital, _city, n, _factor in HOSPITALS:
            docs = []
            for _ in range(n):
                first = names.pop()
                last = self.rng.choice(LAST)
                name = f"dr. {first} {last}{SPECIALTY}"
                while name in used:
                    last = self.rng.choice(LAST)
                    name = f"dr. {first} {last}{SPECIALTY}"
                used.add(name)
                docs.append(name)
            self.doctors[hospital] = docs
        self.factor = {h: f for h, _c, _n, f in HOSPITALS}
        self.city = {h: c for h, c, _n, _f in HOSPITALS}

    # ------------------------------------------------------------------ dasar
    def member(self, surname: str | None = None, address: str | None = None, account: str | None = None,
               member_id: str | None = None) -> dict:
        self.member_seq += 1
        mid = member_id or f"PST-H-{self.member_seq:04d}"
        last = surname or self.rng.choice(LAST)
        city = self.rng.choice(HOSPITALS)[1]
        return {
            "id": mid,
            "name": f"{self.rng.choice(FIRST)} {last}",
            "surname": last,
            "address": address or f"{self.rng.choice(STREETS)} No. {self.rng.randint(1, 180)}, {city}",
            "account": account or f"REK-{self.rng.randint(10_000_000, 99_999_999)}",
        }

    def claim(self, m: dict, hospital: str, admission: date, *, icd: str | None = None, doctor: str | None = None,
              referral: str = "", los_factor: float = 1.0, cost_factor: float = 1.0, lab_factor: float = 1.0,
              los: int | None = None) -> HistoryClaim:
        rng = self.rng
        icd = icd or rng.choices(list(ICD_WEIGHTS), weights=list(ICD_WEIGHTS.values()))[0]
        (lo, hi), per_day, labs_per_day = ICD_PROFILE[icd]
        if los is None:
            los = max(1, round(rng.randint(lo, hi) * los_factor * rng.gauss(1.0, 0.04)))
        cost_day = per_day * self.factor[hospital] * cost_factor * rng.gauss(1.0, 0.08)
        billed = int(round(cost_day * los / 1000.0)) * 1000
        labs = max(1, round(labs_per_day * lab_factor * los * rng.gauss(1.0, 0.12)))
        self.claim_seq += 1
        row = HistoryClaim(
            nomor_klaim=f"HIS-2026-{self.claim_seq:05d}",
            id_peserta=m["id"], nama_peserta=m["name"], alamat_peserta=m["address"], rekening_bank=m["account"],
            rumah_sakit=hospital, dokter=doctor or rng.choice(self.doctors[hospital]), rujukan_dari=referral,
            icd10=icd, tanggal_masuk=admission.isoformat(), tanggal_keluar=(admission + timedelta(days=los)).isoformat(),
            total_tagihan=billed, jumlah_pemeriksaan_lab=labs,
        )
        self.claims.append(row)
        return row

    def random_dates(self, count: int, min_gap: int = 35) -> list[date]:
        """Tanggal masuk acak yang tidak saling tumpang tindih (jarak minimal min_gap hari)."""
        span = (PERIOD_END - PERIOD_START).days - 10
        for _ in range(200):
            days = sorted(self.rng.sample(range(span), count))
            if all(b - a >= min_gap for a, b in zip(days, days[1:])):
                return [PERIOD_START + timedelta(days=d) for d in days]
        return [PERIOD_START + timedelta(days=i * min_gap) for i in range(count)]

    def normal_hospital(self, home: str) -> str:
        return home if self.rng.random() < 0.8 else self.rng.choice(HOSPITALS)[0]

    def normal_claims(self, m: dict, home: str, count: int | None = None) -> None:
        count = count or self.rng.choices([1, 2, 3], weights=[60, 30, 10])[0]
        for adm in self.random_dates(count):
            hospital = self.normal_hospital(home)
            referral = ""
            for src, dst in NORMAL_REFERRALS:
                if dst == hospital and self.rng.random() < 0.15:
                    referral = src
            self.claim(m, hospital, adm, referral=referral)

    # ------------------------------------------------------------------ populasi
    def population(self, singles: int = 450, families: int = 28) -> None:
        hospitals = [h for h, *_ in HOSPITALS]
        for _ in range(singles):
            self.normal_claims(self.member(), self.rng.choice(hospitals))
        # Keluarga: 2-4 orang satu alamat dan satu nama keluarga; sebagian satu rekening. Wajar, bukan fraud.
        for i in range(families):
            head = self.member()
            size = self.rng.randint(2, 4)
            account = head["account"] if i % 3 == 0 else None
            home = self.rng.choice(hospitals)
            self.normal_claims(head, home)
            for _ in range(size - 1):
                self.normal_claims(self.member(surname=head["surname"], address=head["address"], account=account), home)

    # ------------------------------------------------------------------ pola fraud tertanam
    def plant(self) -> None:
        rng = self.rng

        # FP-01 RS memperpanjang lama rawat semua pasien (~70% di atas sejawat)
        h = "RS Cempaka Rekaan"
        for c in self.claims:
            if c.rumah_sakit == h:
                adm = date.fromisoformat(c.tanggal_masuk)
                los = (date.fromisoformat(c.tanggal_keluar) - adm).days
                new_los = max(2, round(los * 1.7))
                c.tanggal_keluar = (adm + timedelta(days=new_los)).isoformat()
                c.total_tagihan = int(round(c.total_tagihan / los * new_los / 1000)) * 1000
                c.jumlah_pemeriksaan_lab = max(1, round(c.jumlah_pemeriksaan_lab / los * new_los))
        self.patterns.append(PlantedPattern("FP-01", "Lama rawat RS jauh di atas sejawat", "FRD-01", "HOSPITAL", h,
                                            "Semua klaim RS Cempaka Rekaan diperpanjang ~70% dari lama rawat wajar."))

        # FP-02 dokter menagih biaya per hari jauh lebih tinggi (upcoding tindakan/obat)
        h = "RS Anggrek Fiktif"
        doc = self.doctors[h][0]
        for c in self.claims:
            if c.dokter == doc:
                c.total_tagihan = int(round(c.total_tagihan * 1.65 / 1000)) * 1000
        self.patterns.append(PlantedPattern("FP-02", "Biaya per hari dokter jauh di atas sejawat", "FRD-03", "DOCTOR", doc,
                                            f"Tagihan pasien {doc} di {h} dinaikkan ~65% per hari rawat."))

        # FP-03 dokter memesan pemeriksaan lab ~3x lipat
        h = "RSU Melati Contoh"
        doc = self.doctors[h][0]
        for c in self.claims:
            if c.dokter == doc:
                c.jumlah_pemeriksaan_lab = c.jumlah_pemeriksaan_lab * 3
        self.patterns.append(PlantedPattern("FP-03", "Frekuensi pemeriksaan lab dokter berlebihan", "FRD-04", "DOCTOR", doc,
                                            f"Pasien {doc} di {h} diperiksa lab ~3x lebih sering."))

        # FP-04 satu rekening bank menerima pembayaran untuk 6 peserta yang tidak berhubungan
        account = "REK-77810042"
        hospitals = [h for h, *_ in HOSPITALS if h not in ("RS Cempaka Rekaan",)]
        for _ in range(6):
            m = self.member(account=account)
            for adm in self.random_dates(rng.randint(1, 2)):
                self.claim(m, rng.choice(hospitals), adm)
        self.patterns.append(PlantedPattern("FP-04", "Rekening bersama banyak peserta", "FRD-05", "BANK_ACCOUNT", account,
                                            "Enam peserta dengan nama keluarga dan alamat berbeda memakai satu rekening."))

        # FP-05 lima peserta tak bersaudara satu alamat, semua klaim di RS yang sama
        address = "Jl. Rekaan Raya No. 17, Kota Fiktif Timur"
        used = set()
        for _ in range(5):
            surname = rng.choice([s for s in LAST if s not in used])
            used.add(surname)
            m = self.member(surname=surname, address=address)
            for adm in self.random_dates(rng.randint(1, 2)):
                self.claim(m, "RS Kenari Demo", adm)
        self.patterns.append(PlantedPattern("FP-05", "Alamat bersama peserta tak bersaudara", "FRD-06", "ADDRESS", address,
                                            "Lima peserta dengan nama keluarga berbeda satu alamat, semua dirawat di RS Kenari Demo."))

        # FP-06 rujukan berputar antara dua RS
        a, b = "RS Teratai Rekaan", "RS Bakti Rekaan"
        for i in range(14):
            src, dst = (a, b) if i % 2 == 0 else (b, a)
            m = self.member()
            self.claim(m, dst, self.random_dates(1)[0], referral=src)
        self.patterns.append(PlantedPattern("FP-06", "Rujukan berputar antar-RS", "FRD-07", "REFERRAL_LOOP",
                                            loop_key([a, b]), "Tujuh pasien dirujuk Teratai -> Bakti dan tujuh Bakti -> Teratai."))

        # FP-07 peserta dengan klaim beruntun (7 klaim dalam ~5 bulan)
        m = self.member(member_id="PST-H-9001")
        adm = date(2026, 3, 2)
        for i in range(7):
            c = self.claim(m, rng.choice(["RS Sehat Sentosa", "RSU Harapan Bunda", "RS Wijaya Kusuma Demo"]), adm, icd="A09")
            adm = date.fromisoformat(c.tanggal_keluar) + timedelta(days=rng.randint(14, 19))
        self.patterns.append(PlantedPattern("FP-07", "Klaim beruntun satu peserta", "FRD-08", "MEMBER", m["id"],
                                            "Tujuh klaim rawat inap gastroenteritis berselang 2-3 minggu."))

        # FP-08 peserta dirawat di dua RS pada tanggal yang tumpang tindih
        m = self.member(member_id="PST-H-9002")
        self.claim(m, "RS Mitra Medika Nusantara", date(2026, 6, 8), icd="A01.0", los=6)
        self.claim(m, "RS Teratai Rekaan", date(2026, 6, 11), icd="A90", los=4)
        self.patterns.append(PlantedPattern("FP-08", "Rawat inap tumpang tindih di dua RS", "FRD-09", "MEMBER", m["id"],
                                            "Dua klaim rawat inap di RS berbeda dengan tanggal yang beririsan."))


def loop_key(hospitals: list[str]) -> str:
    """Kunci kanonik rujukan berputar: mulai dari nama terkecil, ditutup kembali ke awal."""
    i = hospitals.index(min(hospitals))
    ordered = hospitals[i:] + hospitals[:i]
    return " -> ".join(ordered + [ordered[0]])


def generate(seed: int = SEED) -> tuple[list[HistoryClaim], list[PlantedPattern]]:
    g = _Gen(seed)
    g.population()
    g.plant()
    g.claims.sort(key=lambda c: (c.tanggal_masuk, c.nomor_klaim))
    return g.claims, g.patterns


def write_outputs(out_dir: Path = DEFAULT_OUTPUT, seed: int = SEED) -> tuple[Path, Path]:
    claims, patterns = generate(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    history = out_dir / HISTORY_FILE
    with history.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_COLUMNS)
        w.writeheader()
        for c in claims:
            w.writerow(asdict(c))
    key = out_dir / KEY_FILE
    with key.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[f.name for f in fields(PlantedPattern)])
        w.writeheader()
        for p in patterns:
            w.writerow(asdict(p))
    return history, key


def main() -> None:
    history, key = write_outputs()
    print(f"Riwayat klaim sintetis: {history}\nKunci pola fraud: {key}")


if __name__ == "__main__":
    main()
