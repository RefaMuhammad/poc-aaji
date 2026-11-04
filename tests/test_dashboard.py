"""Tes M8: ringkasan dashboard hanya menghitung rekomendasi yang boleh dilihat peran tersebut."""
from __future__ import annotations

from tests.test_review import PIN, pins, processed  # noqa: F401  (fixture)
from tests.test_reasoning import mock_llm, ruleset  # noqa: F401  (fixture)


def test_dashboard_counts_released_only_for_insurer(client, login, processed):  # noqa: F811
    green = processed("SYN-GEA-02", "PST-1")
    red = processed("SYN-TIF-06", "PST-2")
    staf, admin = login("manajer"), login("admin")

    d = client.get("/dashboard", headers=staf).json()
    assert d["total_claims"] == 2 and d["awaiting_doctor"] == 1
    assert {t["key"]: t["count"] for t in d["by_triage"]} == {"GREEN": 1, "YELLOW": 0, "RED": 0}
    assert d["top_findings"] == []  # temuan klaim merah belum dirilis ke asuransi
    assert d["avg_processing_seconds"] is not None

    # admin MAB melihat semua, termasuk draf yang menunggu dokter
    a = client.get("/dashboard", headers=admin).json()
    assert {t["key"]: t["count"] for t in a["by_triage"]}["RED"] == 1
    assert {f["key"] for f in a["top_findings"]} == {"DX_NOT_SUPPORTED", "DRUG_NOT_INDICATED"}

    # setelah dokter menandatangani, temuan dan nilai koreksi ikut terhitung untuk asuransi
    sp = login("spesialis")
    client.post(f"/review/{red}/start", headers=sp)
    body = {"recommendation": "PAY_PARTIAL", "recommended_amount": 1_000_000, "reason_code": "DRUG_NOT_INDICATED", "pin": PIN}
    assert client.post(f"/review/{red}/sign", json=body, headers=sp).status_code == 200
    client.post(f"/claims/{green}/decision", json={"decision": "AGREE"}, headers=staf)
    d = client.get("/dashboard", headers=staf).json()
    assert d["awaiting_doctor"] == 0 and d["correction_total"] > 0
    assert d["top_hospitals"][0]["count"] == 2
    assert d["doctor_reviews"] == 1 and d["doctor_agreement_pct"] == 0.0
    assert d["decisions"] == [{"key": "AGREE", "label": None, "count": 1, "amount": None}]
    assert client.get("/dashboard", headers=login("dokter_umum")).status_code == 403
