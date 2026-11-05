"""Render dokumen klaim sintetis ke PDF (satu PDF per jenis dokumen).

Pemakaian: python -m synthetic.render_pdf [folder_output]
Membaca data/synthetic_output/<claim_id>/case.json, menulis <jenis>.pdf.
Dokumen yang sengaja tidak dilampirkan (skenario dokumen tidak lengkap) dirender ke
<claim_id>/susulan/<jenis>.pdf: dokumen yang "dikirim faskes belakangan" untuk demo U4.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from itertools import groupby
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from synthetic.generate_cases import DEFAULT_OUTPUT, MONTHS

TEMPLATES = Path(__file__).with_name("templates")
DOC_TEMPLATES = {
    "resume_medis": ("resume_medis.html", "RESUME MEDIS"),
    "hasil_laboratorium": ("hasil_lab.html", "HASIL PEMERIKSAAN LABORATORIUM"),
    "cppt": ("cppt.html", "CATATAN PERKEMBANGAN PASIEN TERINTEGRASI (CPPT)"),
    "rincian_tagihan": ("rincian_tagihan.html", "RINCIAN TAGIHAN PERAWATAN"),
}


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, autoescape=True)


def render_html(case: dict, doc_type: str) -> str:
    template_name, title = DOC_TEMPLATES[doc_type]
    fmt_style = case["hospital"]["date_format"]

    def fmt(value: str) -> str:
        d = date.fromisoformat(value)
        if fmt_style == "indo":
            return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
        return d.strftime(fmt_style)

    labs = sorted(case["labs"], key=lambda r: (r["date"], r["time"]))
    labs_by_day = [(day, list(items)) for day, items in groupby(labs, key=lambda r: r["date"])]
    return _env().get_template(template_name).render(
        case=case,
        title=title,
        style=case["hospital"]["style"],
        L=case["hospital"]["labels"],
        labs_by_day=labs_by_day,
        fmt=fmt,
        num=lambda n: f"{int(n):,}".replace(",", "."),
        posneg=lambda r: "Positif" if r == "pos" else "Negatif",
    )


def render_case(case_dir: Path) -> list[Path]:
    from weasyprint import HTML  # impor lambat: butuh pustaka sistem (pango)

    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    (case_dir / ".pindaian_selesai").unlink(missing_ok=True)  # PDF baru = belum dipindai
    written = []
    for doc_type in case["documents"]:
        out = case_dir / f"{doc_type}.pdf"
        pdf = HTML(string=render_html(case, doc_type), base_url=str(TEMPLATES)).write_pdf()
        try:
            out.write_bytes(pdf)
        except PermissionError:
            # Di Windows, file yang sedang dibuka (penampil PDF, pratinjau File Explorer)
            # terkunci dan tidak bisa ditimpa dari container.
            sys.exit(f"Tidak bisa menulis {out}: file sedang dibuka atau terkunci. "
                     "Tutup penampil PDF/pratinjau File Explorer, atau hapus folder "
                     "data/synthetic_output, lalu jalankan ulang.")
        written.append(out)
    return written + render_late(case_dir)


def render_late(case_dir: Path) -> list[Path]:
    """Render hanya dokumen susulan (tanpa menimpa PDF yang sudah ada / sudah dipindai)."""
    from weasyprint import HTML

    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    written = []
    for doc_type in [d for d in DOC_TEMPLATES if d not in case["documents"]]:
        (case_dir / "susulan").mkdir(exist_ok=True)
        out = case_dir / "susulan" / f"{doc_type}.pdf"
        out.write_bytes(HTML(string=render_html(case, doc_type), base_url=str(TEMPLATES)).write_pdf())
        written.append(out)
    return written


def main(out_dir: Path = DEFAULT_OUTPUT) -> None:
    dirs = sorted(p for p in out_dir.iterdir() if (p / "case.json").exists())
    for d in dirs:
        render_case(d)
    print(f"PDF dirender untuk {len(dirs)} klaim di {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT)
