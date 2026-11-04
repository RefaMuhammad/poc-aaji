"""Render halaman dokumen ke PNG (untuk pratinjau bukti) dan rekomendasi ke PDF sederhana."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

MAX_DPI = 200
FONT_DIRS = (Path("/usr/share/fonts/truetype/dejavu"),)


class PageNotFound(ValueError):
    pass


def page_count(data: bytes, content_type: str) -> int:
    if content_type == "application/pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        try:
            return len(pdf)
        finally:
            pdf.close()
    return 1


def render_page_png(data: bytes, content_type: str, page: int, dpi: int = 110) -> bytes:
    """Halaman ke-`page` (mulai 1) sebagai PNG."""
    dpi = max(50, min(dpi, MAX_DPI))
    if content_type == "application/pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        try:
            if not 1 <= page <= len(pdf):
                raise PageNotFound(f"Halaman {page} tidak ada")
            image = pdf[page - 1].render(scale=dpi / 72).to_pil()
        finally:
            pdf.close()
    else:
        if page != 1:
            raise PageNotFound(f"Halaman {page} tidak ada")
        image = Image.open(io.BytesIO(data))
        image.load()
        image.thumbnail((1700, 2400))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ----------------------------------------------------------------------------- PDF rekomendasi

STATUS_LABEL = {"GREEN": "HIJAU", "YELLOW": "KUNING", "RED": "MERAH"}
REC_LABEL = {
    "PAY_FULL": "Bayar penuh", "PAY_PARTIAL": "Bayar sebagian", "PEND": "Tunda (minta dokumen/klarifikasi)",
    "NOT_COVERED": "Tidak dijamin", "DOCTOR_REVIEW": "Menunggu telaah dokter",
}


def _rp(n: int | None) -> str:
    return "-" if n is None else "Rp" + f"{n:,}".replace(",", ".")


def recommendation_pdf(view: dict, doc_names: dict[str, str]) -> bytes:
    """PDF sederhana dari RecommendationOut (dict). Isi sama dengan tampilan portal."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    font = next((d for d in FONT_DIRS if (d / "DejaVuSans.ttf").exists()), None)
    if font:
        pdf.add_font("dv", "", str(font / "DejaVuSans.ttf"))
        pdf.add_font("dv", "B", str(font / "DejaVuSans-Bold.ttf"))
        family = "dv"

        def clean(s: str) -> str:
            return s
    else:  # tanpa font Unicode: batasi ke latin-1
        family = "helvetica"

        def clean(s: str) -> str:
            return s.replace("µ", "u").replace("–", "-").replace("—", "-").encode("latin-1", "replace").decode("latin-1")

    w = pdf.epw

    def text(s: str, size: int = 10, style: str = "", gap: float = 1.5, color=(30, 41, 59)) -> None:
        pdf.set_font(family, style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(w, size * 0.5, clean(s), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(gap)

    text("DATA REKAAN UNTUK DEMONSTRASI - bukan dokumen klaim sungguhan", 8, "B", color=(176, 0, 0))
    text(f"Rekomendasi klaim {view['claim_number']}", 15, "B", 2)
    text(f"Status triase: {STATUS_LABEL.get(view['triage_status'], view['triage_status'])}    "
         f"Skor risiko: {view['risk_score']}/100    Rekomendasi: {REC_LABEL.get(view['recommendation'], view['recommendation'])}", 10, "B")
    text(f"Nilai tagihan: {_rp(view['billed_amount'])}    Nilai rekomendasi: {_rp(view.get('recommended_amount'))}")
    reviewer = view.get("reviewer")
    if reviewer:
        text(f"Ditelaah: {reviewer['name']}{', ' + reviewer['specialty'] if reviewer.get('specialty') else ''} - {reviewer['signed_at']}")
    elif view["recommendation"] != "PAY_FULL":
        text("Belum ditandatangani dokter.", 10, "B", color=(176, 0, 0))

    if view.get("findings"):
        text("Temuan", 12, "B", 1)
        for i, f in enumerate(view["findings"], 1):
            text(f"{i}. [{f['severity']}] {f['code']} ({f['source']}{' ' + f['rule_id'] if f.get('rule_id') else ''})", 10, "B", 0.5)
            text(f["text"], 10, gap=0.5)
            for e in f.get("evidence") or []:
                where = f"{doc_names.get(e.get('doc') or '', e.get('doc') or 'riwayat klaim')}, hal. {e['page']}" if e.get("page") else "riwayat klaim"
                text(f'   Bukti ({where}): "{e.get("quote") or ""}"', 9, gap=0.3, color=(71, 85, 105))
            for g in f.get("guideline_refs") or []:
                text(f"   Rujukan: {g}", 9, gap=0.3, color=(71, 85, 105))
            pdf.ln(1.5)
    else:
        text("Tidak ada temuan.", 10)

    if view.get("line_adjustments"):
        text("Usulan koreksi tagihan", 12, "B", 1)
        for a in view["line_adjustments"]:
            text(f"- {a.get('date') or ''} {a.get('item')}: {_rp(a.get('amount'))} ({a.get('reason_code')})", 9, gap=0.3)
        pdf.ln(1.5)
    if view.get("explanation_text"):
        text("Penjelasan", 12, "B", 1)
        text(view["explanation_text"], 10)
    if view.get("next_action"):
        text(f"Langkah berikutnya: {view['next_action']}", 10)
    decision = view.get("insurer_decision")
    if decision:
        label = "Setuju" if decision["decision"] == "AGREE" else "Berbeda"
        text(f"Keputusan asuransi: {label}{' - ' + decision['reason'] if decision.get('reason') else ''} "
             f"({decision['decided_by']}, {decision['decided_at']})", 10, "B")
    text(f"Versi model: {view['model_version']} | prompt: {view['prompt_version']} | aturan: {view['ruleset_version']}", 8, color=(100, 116, 139))
    return bytes(pdf.output())
