from pathlib import Path

import yaml

RULES_FILE = Path(__file__).resolve().parents[1] / "rules" / "aturan_klinis_demo.yaml"


def test_rules_file_is_valid_yaml_with_19_rules():
    """Cek dasar M0. Validasi lengkap terhadap kamus data dikerjakan di M1."""
    doc = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    total = len(doc["aturan_umum"]) + sum(len(dx["aturan"]) for dx in doc["diagnosis"])
    assert doc["version"] == "rules-2026.10-demo"
    assert total == 19
