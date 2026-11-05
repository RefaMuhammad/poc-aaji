"""Buat contoh FHIR R4 Bundle dari satu klaim sintetis (DATA REKAAN).

Isi Bundle: Patient, Coverage, Encounter, Claim, Observation (trombosit/hematokrit/leukosit),
dan DocumentReference untuk setiap PDF (base64). Sistem identifier memakai URN demo.

Pemakaian (di container api):
    docker compose exec api python infra/scripts/make_fhir_bundle.py SYN-DEN-01
Hasil: data/demo_upload/fhir_SYN-DEN-01.json, lalu kirim:
    curl.exe -H "X-API-Key: $KEY" -H "Content-Type: application/fhir+json" ^
         --data-binary "@data/demo_upload/fhir_SYN-DEN-01.json" http://localhost:8000/integrations/v1/fhir
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

DATA = Path(os.environ.get("SEED_DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "synthetic_output"))
OUT_DIR = DATA.parent / "demo_upload"
DOC_ORDER = ["resume_medis", "hasil_laboratorium", "cppt", "rincian_tagihan"]
DOC_LOINC = {  # kode jenis dokumen (LOINC) untuk DocumentReference.type
    "resume_medis": ("18842-5", "Discharge summary"),
    "hasil_laboratorium": ("11502-2", "Laboratory report"),
    "cppt": ("11506-3", "Progress note"),
    "rincian_tagihan": ("34133-9", "Summary of episode note"),
}
LAB_LOINC = {"plt": ("777-3", "Platelets", "/uL"), "hct": ("4544-3", "Hematocrit", "%"), "wbc": ("6690-2", "Leukocytes", "10*3/uL"),
             "hb": ("718-7", "Hemoglobin", "g/dL")}

MEMBER_SYSTEM = "urn:mab-demo:id-peserta"
POLICY_SYSTEM = "urn:mab-demo:nomor-polis"
CLAIM_SYSTEM = "urn:mab-demo:nomor-klaim"


def build_bundle(folder: Path, insurer_name: str = "Asuransi Pelita Demo (rekaan)") -> dict:
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    cid = case["claim_id"]
    p = case["patient"]
    pid, cov_id, enc_id, claim_id = f"pasien-{cid}", f"polis-{cid}", f"rawat-{cid}", f"klaim-{cid}"
    ref = lambda kind, rid: {"reference": f"urn:uuid:{rid}"} | ({"type": kind} if kind else {})  # noqa: E731
    entries: list[dict] = []

    def add(resource: dict) -> None:
        entries.append({"fullUrl": f"urn:uuid:{resource['id']}", "resource": resource})

    add({"resourceType": "Patient", "id": pid,
         "identifier": [{"system": MEMBER_SYSTEM, "value": p["member_id"]}],
         "name": [{"text": p["name"]}], "gender": "female" if p.get("sex") == "P" else "male"})
    add({"resourceType": "Coverage", "id": cov_id, "status": "active", "subscriberId": p["policy_no"],
         "identifier": [{"system": POLICY_SYSTEM, "value": p["policy_no"]}],
         "beneficiary": ref("Patient", pid), "payor": [{"display": insurer_name}]})
    add({"resourceType": "Encounter", "id": enc_id, "status": "finished",
         "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
         "subject": ref("Patient", pid),
         "period": {"start": case["admission_date"], "end": case["discharge_date"]},
         "serviceProvider": {"display": case["hospital"]["name"]}})
    diagnoses = [{"sequence": 1, "diagnosisCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": case["icd10"]}]}}]
    for n, code in enumerate(case.get("secondary_icd10") or [], start=2):
        diagnoses.append({"sequence": n, "diagnosisCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": code}]}})
    add({"resourceType": "Claim", "id": claim_id, "status": "active",
         "identifier": [{"system": CLAIM_SYSTEM, "value": cid}],
         "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "institutional"}]},
         "use": "claim", "patient": ref("Patient", pid), "created": case["discharge_date"],
         "provider": {"display": case["hospital"]["name"]}, "priority": {"coding": [{"code": "normal"}]},
         "insurance": [{"sequence": 1, "focal": True, "coverage": ref("Coverage", cov_id)}],
         "diagnosis": diagnoses,
         "item": [{"sequence": 1, "encounter": [ref("Encounter", enc_id)],
                   "productOrService": {"text": "Rawat inap"}, "net": {"value": int(case["billing_total"]), "currency": "IDR"}}],
         "total": {"value": int(case["billing_total"]), "currency": "IDR"}})
    for n, lab in enumerate(case.get("labs") or [], start=1):
        for key, value in (lab.get("values") or {}).items():
            if key not in LAB_LOINC or not isinstance(value, (int, float)):
                continue
            code, display, unit = LAB_LOINC[key]
            add({"resourceType": "Observation", "id": f"lab-{cid}-{n}-{key}", "status": "final",
                 "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
                 "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
                 "subject": ref("Patient", pid), "encounter": ref("Encounter", enc_id),
                 "effectiveDateTime": f"{lab['date']}T{lab.get('time', '00:00')}:00+07:00",
                 "valueQuantity": {"value": value, "unit": unit}})
    for name in DOC_ORDER:
        pdf = folder / f"{name}.pdf"
        if not pdf.exists():
            continue
        code, display = DOC_LOINC[name]
        add({"resourceType": "DocumentReference", "id": f"dok-{cid}-{name.replace('_', '-')}", "status": "current",
             "type": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
             "subject": ref("Patient", pid), "description": name,
             "context": {"encounter": [ref("Encounter", enc_id)]},
             "content": [{"attachment": {"contentType": "application/pdf", "title": pdf.name,
                                         "data": base64.b64encode(pdf.read_bytes()).decode()}}]})
    return {"resourceType": "Bundle", "id": f"bundle-{cid}", "type": "collection",
            "meta": {"tag": [{"code": "rekaan", "display": "Data rekaan untuk demonstrasi"}]}, "entry": entries}


def main() -> None:
    claim = sys.argv[1] if len(sys.argv) > 1 else "SYN-DEN-01"
    folder = DATA / claim
    if not (folder / "case.json").exists():
        sys.exit(f"Data {claim} tidak ada di {DATA}. Jalankan `docker compose run --rm synthetic` dulu.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"fhir_{claim}.json"
    out.write_text(json.dumps(build_bundle(folder), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Bundle FHIR dibuat: {out}")


if __name__ == "__main__":
    main()
