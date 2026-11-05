"""python -m synthetic : buat data, render PDF, terapkan efek pindaian, riwayat klaim berpola fraud (U3),
dan kasus underwriting medis (U7)."""
from synthetic import generate_fraud, generate_underwriting, render_pdf, scan_effects
from synthetic.generate_cases import DEFAULT_OUTPUT, write_outputs

if __name__ == "__main__":
    write_outputs(DEFAULT_OUTPUT)
    render_pdf.main(DEFAULT_OUTPUT)
    scan_effects.main(DEFAULT_OUTPUT)
    generate_fraud.write_outputs(DEFAULT_OUTPUT / "fraud")
    generate_underwriting.write_outputs(DEFAULT_OUTPUT / "underwriting")
