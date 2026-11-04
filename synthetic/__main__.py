"""python -m synthetic : buat data, render PDF, terapkan efek pindaian."""
from synthetic import render_pdf, scan_effects
from synthetic.generate_cases import DEFAULT_OUTPUT, write_outputs

if __name__ == "__main__":
    write_outputs(DEFAULT_OUTPUT)
    render_pdf.main(DEFAULT_OUTPUT)
    scan_effects.main(DEFAULT_OUTPUT)
