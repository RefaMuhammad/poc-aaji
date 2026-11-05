"""Pemetaan FHIR R4 minimal (U2), divalidasi dengan pustaka fhir.resources (model R4B, kompatibel R4
untuk resource yang dipakai di sini).

Masuk (Bundle):
  Patient            -> id peserta (identifier) dan nama
  Coverage           -> nomor polis (subscriberId atau identifier)
  Encounter          -> tanggal masuk/keluar (period), nama RS (serviceProvider.display)
  Claim              -> nomor klaim (identifier), total tagihan (total.value), ICD-10 utama (diagnosis)
  Observation        -> diterima dan dihitung; nilai lab tetap dibaca dari dokumen supaya ada bukti kutipan
  DocumentReference  -> dokumen klaim (content.attachment.data base64, PDF/JPG/PNG)
Keluar:
  ClaimResponse      -> status proses, rekomendasi yang SUDAH dirilis, nilai disarankan, kode alasan.

Semua contoh di repo ini rekaan. Sistem identifier memakai URN demo, bukan sistem nasional.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from mab_api.api_schemas import ClaimCreate
from mab_api.documents import InvalidFile, ValidFile, validate_file
from mab_api.models import Claim
from mab_api.webhooks import claim_status

MEMBER_SYSTEM = "urn:mab-demo:id-peserta"
POLICY_SYSTEM = "urn:mab-demo:nomor-polis"
CLAIM_SYSTEM = "urn:mab-demo:nomor-klaim"
ICD10_SYSTEMS = ("http://hl7.org/fhir/sid/icd-10", "http://hl7.org/fhir/sid/icd-10-id", "urn:oid:2.16.840.1.113883.6.3")
LABEL = "Data rekaan untuk demonstrasi"


class FhirError(ValueError):
    pass


@dataclass
class MappedClaim:
    claim: ClaimCreate
    files: list[ValidFile]
    primary_icd10: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    bundle_id: str | None = None


def _resources(bundle) -> dict[str, list]:
    out: dict[str, list] = {}
    for entry in bundle.entry or []:
        res = entry.resource
        if res is not None:
            out.setdefault(res.resource_type, []).append(res)
    return out


def _first(items: list | None, what: str):
    if not items:
        raise FhirError(f"Bundle tidak berisi {what}")
    return items[0]


def _identifier(identifiers, system: str | None = None) -> str | None:
    for ident in identifiers or []:
        if ident.value and (system is None or ident.system == system):
            return ident.value
    return None


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_bundle(payload: dict) -> MappedClaim:
    """Validasi Bundle dan petakan ke data klaim + dokumen. Melempar FhirError dengan pesan yang bisa dibaca."""
    from fhir.resources.R4B.bundle import Bundle

    if not isinstance(payload, dict) or payload.get("resourceType") != "Bundle":
        raise FhirError("Body harus resource FHIR Bundle")
    try:
        bundle = Bundle.parse_obj(payload)
    except Exception as exc:  # pydantic ValidationError dari fhir.resources
        raise FhirError(f"Bundle FHIR tidak valid: {str(exc)[:800]}")
    if bundle.type not in ("collection", "transaction", "batch", "message", "document"):
        raise FhirError(f"Bundle.type {bundle.type!r} tidak didukung")
    res = _resources(bundle)

    patient = _first(res.get("Patient"), "Patient")
    member_id = _identifier(patient.identifier, MEMBER_SYSTEM) or _identifier(patient.identifier)
    if not member_id:
        raise FhirError("Patient.identifier (id peserta) wajib diisi")
    name = None
    if patient.name:
        n = patient.name[0]
        name = n.text or " ".join([*(n.given or []), n.family or ""]).strip() or None

    coverage = _first(res.get("Coverage"), "Coverage")
    policy_number = coverage.subscriberId or _identifier(coverage.identifier, POLICY_SYSTEM) or _identifier(coverage.identifier)
    if not policy_number:
        raise FhirError("Coverage.subscriberId atau Coverage.identifier (nomor polis) wajib diisi")

    fhir_claim = _first(res.get("Claim"), "Claim")
    claim_number = _identifier(fhir_claim.identifier, CLAIM_SYSTEM) or _identifier(fhir_claim.identifier)
    if not claim_number:
        raise FhirError("Claim.identifier (nomor klaim) wajib diisi")
    if fhir_claim.total is None or fhir_claim.total.value is None:
        raise FhirError("Claim.total.value (nilai tagihan) wajib diisi")

    encounter = _first(res.get("Encounter"), "Encounter")
    period = encounter.period
    admission = _as_date(period.start) if period else None
    discharge = _as_date(period.end) if period else None
    if admission is None or discharge is None:
        raise FhirError("Encounter.period.start dan .end (tanggal masuk/keluar) wajib diisi")
    hospital = None
    for ref in (encounter.serviceProvider, fhir_claim.provider):
        if ref is not None and ref.display:
            hospital = ref.display
            break
    if not hospital:
        raise FhirError("Encounter.serviceProvider.display atau Claim.provider.display (nama RS) wajib diisi")

    primary = None
    for dx in sorted(fhir_claim.diagnosis or [], key=lambda d: d.sequence or 0):
        concept = dx.diagnosisCodeableConcept
        for coding in (concept.coding if concept else None) or []:
            if coding.code and (coding.system in ICD10_SYSTEMS or coding.system is None):
                primary = coding.code
                break
        if primary:
            break

    files: list[ValidFile] = []
    for n, doc in enumerate(res.get("DocumentReference") or [], start=1):
        for content in doc.content or []:
            att = content.attachment
            if att is None or not att.data:
                raise FhirError(f"DocumentReference #{n}: attachment.data (base64) wajib diisi; URL eksternal belum didukung")
            try:
                data = base64.b64decode(att.data, validate=True)
            except (binascii.Error, ValueError):
                raise FhirError(f"DocumentReference #{n}: attachment.data bukan base64 yang valid")
            title = att.title or doc.description or f"dokumen_{n}"
            if "." not in title:
                title += {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}.get(att.contentType or "", "")
            try:
                files.append(validate_file(title, data))
            except InvalidFile as exc:
                raise FhirError(f"DocumentReference #{n}: {exc}")
    if not files:
        raise FhirError("Bundle tidak berisi DocumentReference dengan dokumen klaim")

    try:
        body = ClaimCreate(claim_number=claim_number, policy_number=policy_number, member_id=member_id, patient_name=name,
                           hospital_name=hospital, admission_date=admission, discharge_date=discharge,
                           billed_amount=int(fhir_claim.total.value))
    except Exception as exc:
        raise FhirError(f"Data klaim tidak valid: {exc}")
    counts = {k: len(v) for k, v in sorted(res.items())}
    return MappedClaim(body, files, primary, counts, bundle.id)


# ----------------------------------------------------------------------------- keluar


_OUTCOME = {"FAILED": "error", "COMPLETED": "complete", "AWAITING_DECISION": "complete"}


def claim_response(claim: Claim, insurer_name: str) -> dict:
    """ClaimResponse R4 untuk satu klaim. Rekomendasi hanya terisi bila sudah dirilis ke asuransi."""
    from fhir.resources.R4B.claimresponse import ClaimResponse

    st = claim_status(claim)
    released = st["recommendation"] is not None
    outcome = _OUTCOME.get(claim.status, "queued") if (released or claim.status == "FAILED") else "queued"
    if claim.status == "FAILED":
        disposition = f"Klaim gagal diproses: {claim.processing_error or '-'}"
    elif released:
        disposition = (f"Rekomendasi {st['recommendation']} (triase {st['triage_status']})"
                       + (f", ditandatangani {st['signed_by']}" if st["signed_by"] else "")
                       + ". Keputusan akhir tetap di tangan asuransi.")
    else:
        disposition = f"Status {claim.status}: rekomendasi belum dirilis ke asuransi."
    total = [{"category": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/adjudication", "code": "submitted"}]},
              "amount": {"value": claim.billed_amount, "currency": "IDR"}}]
    if released and st["recommended_amount"] is not None:
        total.append({"category": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/adjudication", "code": "benefit"}]},
                      "amount": {"value": st["recommended_amount"], "currency": "IDR"}})
    notes = [{"number": i, "type": "display", "text": f"Kode alasan: {code}"} for i, code in enumerate(st["reason_codes"], start=1)]
    notes.append({"number": len(notes) + 1, "type": "display", "text": LABEL})
    resource = {
        "resourceType": "ClaimResponse",
        "id": claim.id,
        "identifier": [{"system": CLAIM_SYSTEM, "value": claim.claim_number}],
        "status": "active",
        "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "institutional"}]},
        "use": "claim",
        "patient": {"identifier": {"system": MEMBER_SYSTEM, "value": claim.member_id}},
        "created": datetime.now(timezone.utc).isoformat(),
        "insurer": {"display": insurer_name},
        "request": {"identifier": {"system": CLAIM_SYSTEM, "value": claim.claim_number}},
        "outcome": outcome,
        "disposition": disposition,
        "total": total,
        "processNote": notes,
    }
    if claim.status == "FAILED":
        resource["error"] = [{"code": {"text": (claim.processing_error or "gagal diproses")[:200]}}]
    ClaimResponse.parse_obj(resource)  # pastikan sesuai skema
    return resource
