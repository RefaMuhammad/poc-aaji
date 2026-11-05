"""Notifikasi ke pengguna (U4): kotak masuk di portal plus email.

Selama demo, email TIDAK dikirim. Setiap email disimpan di tabel `notifications` dengan
delivery=SIMULATED, dan bisa dibaca di halaman Kotak masuk. Saat SMTP sungguhan dipasang,
cukup ganti `_deliver`.

Penerima per peristiwa:
- claim.documents_requested : petugas faskes RS klaim, peserta pemilik klaim
- claim.documents_received  : staf/manajer asuransi pemilik klaim, operator TPA yang melayaninya
- claim.recommendation_released / claim.decision_recorded : peserta (dan faskes untuk keputusan)
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from mab_api.models import Claim, Notification, Role, User, UserTenant

LABEL = "Data rekaan untuk demonstrasi"

DOC_LABEL = {
    "resume_medis": "resume medis",
    "rincian_tagihan": "rincian tagihan",
    "hasil_laboratorium": "hasil laboratorium",
    "cppt": "catatan perkembangan (CPPT)",
    "laporan_operasi": "laporan operasi",
    "resep": "resep",
}


def doc_label(doc_type: str) -> str:
    return DOC_LABEL.get(doc_type, doc_type.replace("_", " "))


def facility_users(db: Session, claim: Claim) -> list[User]:
    return list(db.scalars(select(User).where(User.role == Role.FACILITY_OFFICER.value, User.is_active.is_(True),
                                              User.facility_name == claim.hospital_name)))


def member_users(db: Session, claim: Claim) -> list[User]:
    return list(db.scalars(select(User).where(User.role == Role.MEMBER.value, User.is_active.is_(True),
                                              User.member_ref == claim.member_id, User.insurer_id == claim.insurer_id)))


def insurer_users(db: Session, claim: Claim) -> list[User]:
    """Staf dan manajer asuransi pemilik klaim, plus operator TPA yang melayani asuransi itu."""
    tpa_ids = select(UserTenant.user_id).where(UserTenant.insurer_id == claim.insurer_id)
    return list(db.scalars(select(User).where(
        User.is_active.is_(True),
        or_(
            User.role.in_([Role.INSURER_STAFF.value, Role.INSURER_MANAGER.value]) & (User.insurer_id == claim.insurer_id),
            (User.role == Role.TPA_OPERATOR.value) & (or_(User.insurer_id == claim.insurer_id, User.id.in_(tpa_ids))),
        ),
    )))


def _deliver(n: Notification) -> None:
    """Demo: email tidak dikirim, hanya dicatat sebagai SIMULATED."""
    n.delivery = "SIMULATED"


def notify(db: Session, users: list[User], claim: Claim | None, event: str, subject: str, body: str) -> list[Notification]:
    out, seen = [], set()
    for u in users:
        if u.id in seen:
            continue
        seen.add(u.id)
        n = Notification(user_id=u.id, insurer_id=claim.insurer_id if claim else u.insurer_id,
                         claim_id=claim.id if claim else None, event=event, email=u.email,
                         subject=subject[:300], body=f"Yth. {u.full_name},\n\n{body}\n\n-- Platform MAB ({LABEL})")
        _deliver(n)
        db.add(n)
        out.append(n)
    return out


def documents_requested(db: Session, claim: Claim, doc_types: list[str], message: str, due_text: str) -> None:
    docs = ", ".join(doc_label(d) for d in doc_types) or "dokumen pendukung"
    notify(db, facility_users(db, claim), claim, "claim.documents_requested",
           f"Permintaan dokumen susulan klaim {claim.claim_number}",
           f"Asuransi meminta dokumen susulan untuk klaim {claim.claim_number} atas nama peserta {claim.member_id}.\n"
           f"Dokumen yang diminta: {docs}.\nCatatan asuransi: {message}\nMohon diunggah lewat Portal Faskes sebelum {due_text}.")
    notify(db, member_users(db, claim), claim, "claim.documents_requested",
           f"Klaim {claim.claim_number} menunggu dokumen dari rumah sakit",
           f"Klaim Anda di {claim.hospital_name} ditunda sementara karena asuransi membutuhkan {docs}.\n"
           "Rumah sakit sudah kami minta mengirimkan dokumen tersebut. Anda tidak perlu melakukan apa pun.")


def documents_received(db: Session, claim: Claim, doc_types: list[str], uploader: User) -> None:
    docs = ", ".join(doc_label(d) for d in doc_types) or "dokumen"
    notify(db, insurer_users(db, claim), claim, "claim.documents_received",
           f"Dokumen susulan klaim {claim.claim_number} sudah diterima",
           f"{uploader.full_name} mengunggah {docs} untuk klaim {claim.claim_number}.\n"
           "Klaim diproses ulang otomatis lalu ditelaah dokter sebelum kembali ke Anda untuk diputuskan.")
    notify(db, member_users(db, claim), claim, "claim.documents_received",
           f"Dokumen klaim {claim.claim_number} sudah lengkap",
           "Rumah sakit sudah mengirim dokumen yang diminta. Klaim Anda sedang diproses ulang.")


def recommendation_released(db: Session, claim: Claim) -> None:
    notify(db, member_users(db, claim), claim, "claim.recommendation_released",
           f"Klaim {claim.claim_number} sedang menunggu keputusan asuransi",
           "Pemeriksaan medis atas klaim Anda sudah selesai. Asuransi akan segera mencatat keputusan.")


def decision_recorded(db: Session, claim: Claim, summary: str) -> None:
    body = f"Asuransi sudah memutuskan klaim {claim.claim_number}: {summary}.\nPenjelasan lengkap ada di portal."
    notify(db, member_users(db, claim), claim, "claim.decision_recorded", f"Keputusan klaim {claim.claim_number}", body)
    notify(db, facility_users(db, claim), claim, "claim.decision_recorded", f"Keputusan klaim {claim.claim_number}", body)


# ----------------------------------------------------------------------------- U5: sengketa / banding


def _filer_side(db: Session, claim: Claim, filer: User) -> list[User]:
    """Pihak portal selain pengaju (faskes <-> peserta), supaya keduanya tahu ada banding."""
    others = member_users(db, claim) if filer.role == Role.FACILITY_OFFICER.value else facility_users(db, claim)
    return [u for u in others if u.id != filer.id]


def dispute_filed(db: Session, claim: Claim, dispute, filer: User) -> None:
    who = "rumah sakit" if filer.role == Role.FACILITY_OFFICER.value else "peserta"
    notify(db, insurer_users(db, claim), claim, "claim.dispute_filed", f"Banding atas klaim {claim.claim_number}",
           f"{filer.full_name} ({who}) mengajukan banding atas keputusan klaim {claim.claim_number}.\n"
           f"Alasan: {dispute.reason}\nBanding ditelaah ulang oleh dokter yang berbeda dari penelaah awal, "
           "lalu dikembalikan ke Anda untuk diputus ulang.")
    notify(db, [filer], claim, "claim.dispute_filed", f"Banding klaim {claim.claim_number} diterima",
           "Banding Anda sudah kami terima dan akan ditelaah ulang oleh dokter lain. "
           f"Target penyelesaian: {dispute.due_at.strftime('%d-%m-%Y')}.")
    notify(db, _filer_side(db, claim, filer), claim, "claim.dispute_filed", f"Klaim {claim.claim_number} sedang dibanding",
           f"Keputusan klaim {claim.claim_number} sedang dibanding oleh {who} dan ditelaah ulang.")


def dispute_reviewed(db: Session, claim: Claim, dispute) -> None:
    notify(db, insurer_users(db, claim), claim, "claim.dispute_reviewed",
           f"Telaah ulang banding klaim {claim.claim_number} selesai",
           "Dokter penelaah banding sudah menandatangani rekomendasi baru. Mohon catat keputusan ulang.")


def dispute_resolved(db: Session, claim: Claim, dispute, decision: str) -> None:
    label = {"UPHELD": "dikuatkan (keputusan awal tetap)", "MODIFIED": "diubah",
             "OVERTURNED": "dibatalkan (klaim dibayar penuh)"}.get(dispute.outcome or "", dispute.outcome or "")
    body = (f"Banding atas klaim {claim.claim_number} selesai: keputusan awal {label}."
            + (" Asuransi memutuskan berbeda dari rekomendasi dokter; lihat alasannya di portal." if decision == "DIFFER" else "")
            + "\nPenjelasan lengkap ada di portal.")
    users = member_users(db, claim) + facility_users(db, claim)
    notify(db, users, claim, "claim.dispute_resolved", f"Hasil banding klaim {claim.claim_number}", body)
