"""Menyusun draf rekomendasi dari hasil aturan, bukti, dan tagihan.

Prinsip:
- AI tidak pernah menolak klaim. Hasilnya hanya PAY_FULL, DOCTOR_REVIEW, atau PEND;
  selain PAY_FULL wajib ditelaah dan ditandatangani dokter.
- Temuan yang butuh bukti AI tetapi tidak punya satu pun bukti dibuang.
- Masalah kualitas data (dokumen tidak terbaca, kutipan AI tidak terbukti, aturan
  tidak bisa dinilai, temuan dibuang) tidak boleh menghasilkan hijau: klaim
  dinaikkan ke kuning. Lebih baik kuning keliru daripada hijau keliru.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from mab_pipeline.extraction.facts import BillingFacts
from mab_pipeline.rules.loader import RuleSet
from mab_pipeline.schemas import ClaimData, Finding, InitialRecommendation, TriageResult, TriageStatus
from mab_pipeline.triage.scorer import score_triage

MAX_EVIDENCE_PER_FINDING = 8
ROOM_WORDS = ("kamar",)
VISIT_WORDS = ("visite",)

QUALITY_MESSAGES = {
    "DOC_UNREADABLE": "Ada dokumen yang tidak terbaca atau gagal diekstrak.",
    "DX_UNKNOWN": "Diagnosis utama tidak terbaca dari resume medis, sehingga aturan diagnosis tidak dijalankan.",
    "AI_FAILED": "Penalaran klinis AI gagal; field klinis tidak terisi.",
    "AI_UNVERIFIED": "Ada nilai klinis dari AI yang kutipannya tidak ditemukan di dokumen; nilai itu dianggap tidak diketahui.",
    "RULE_SKIPPED": "Ada aturan yang tidak bisa dinilai karena datanya kosong.",
    "FINDING_WITHOUT_EVIDENCE": "Ada temuan yang dibuang karena tidak punya bukti di dokumen.",
}


@dataclass
class FindingDraft:
    rule_id: str
    rule_name: str
    reason_code: str
    severity: str
    text: str
    needs_ai: bool
    evidence: list[dict]
    guideline_refs: list[str]
    fields_used: list[str]
    source: str = "RULE"


@dataclass
class RecommendationDraft:
    triage_status: str
    risk_score: int
    recommendation: str
    findings: list[FindingDraft]
    dropped_findings: list[str]
    skipped_rules: list[dict]
    line_adjustments: list[dict]
    billed_amount: int
    recommended_amount: int | None
    guideline_refs: list[str]
    next_action: str
    explanation_text: str
    quality_flags: list[dict] = field(default_factory=list)
    matched_diagnosis: str | None = None


def _rupiah(n: int) -> str:
    return "Rp" + f"{n:,}".replace(",", ".")


def _dedupe_evidence(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in items:
        key = (e.get("doc"), e.get("page"), tuple(e.get("line_ids") or ()), e.get("claim_id"), e.get("quote"))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out[:MAX_EVIDENCE_PER_FINDING]


def _has_document_evidence(evidence: list[dict]) -> bool:
    return any(e.get("doc") and e.get("page") for e in evidence)


def _adjustments(findings: list[FindingDraft], claim: ClaimData, billing: BillingFacts | None, ai_items: dict[str, list[str]]) -> list[dict]:
    if billing is None:
        return []
    codes = {f.reason_code for f in findings}
    out: list[dict] = []

    def add(it, code: str, note: str) -> None:
        if it.unit_price is None:
            return
        out.append({"item": it.name, "date": it.date.isoformat() if it.date else None, "time": it.time, "qty": it.qty,
                    "amount": it.unit_price * it.qty, "reason_code": code, "note": note, "line_ids": it.source_line_ids})

    if "DUP_ITEM" in codes:
        groups: dict[tuple, list] = defaultdict(list)
        for it in billing.items:
            groups[(" ".join(it.name.lower().split()), it.date, it.time)].append(it)
        for group in groups.values():
            for it in group[1:]:
                add(it, "DUP_ITEM", "Item ganda (nama, tanggal, jam sama)")
    if "BILLED_NOT_DOCUMENTED" in codes:
        names = [n.lower() for n in ai_items.get("bill.items_without_clinical_note", [])]
        for it in billing.items:
            if any(n and (n in it.name.lower() or it.name.lower() in n) for n in names):
                add(it, "BILLED_NOT_DOCUMENTED", "Tidak ada catatan klinis pendukung")
    if "LOS_EXCESS" in codes and claim.clin.days_after_discharge_criteria:
        days = sorted({it.date for it in billing.items if it.date and any(w in it.name.lower() for w in ROOM_WORDS)})
        extra = set(days[-int(claim.clin.days_after_discharge_criteria):])
        for it in billing.items:
            if it.date in extra and any(w in it.name.lower() for w in ROOM_WORDS + VISIT_WORDS):
                add(it, "LOS_EXCESS", "Hari rawat setelah kriteria pulang terpenuhi")
    return out


def build_recommendation(
    triage: TriageResult,
    claim: ClaimData,
    ruleset: RuleSet,
    field_evidence: dict[str, list[dict]],
    billed_amount: int,
    billing: BillingFacts | None = None,
    ai_items: dict[str, list[str]] | None = None,
    quality: list[str] | None = None,
) -> RecommendationDraft:
    rules = {r.id: r for r in ruleset.general_rules}
    for dx in ruleset.diagnoses:
        rules.update({r.id: r for r in dx.rules})
    flags = list(dict.fromkeys(quality or []))

    kept: list[Finding] = []
    drafts: list[FindingDraft] = []
    dropped: list[str] = []
    for f in triage.findings:
        evidence = _dedupe_evidence([e for path in f.fields_used for e in field_evidence.get(path, [])])
        if f.needs_ai_evidence and not _has_document_evidence(evidence):
            dropped.append(f.rule_id)
            continue
        kept.append(f)
        ref = rules[f.rule_id].reference if f.rule_id in rules else f.reference
        drafts.append(FindingDraft(f.rule_id, f.rule_name, f.reason_code, f.severity.value, f.message,
                                   f.needs_ai_evidence, evidence, [ref] if ref else [], list(f.fields_used)))
    if dropped:
        flags.append("FINDING_WITHOUT_EVIDENCE")
    if triage.skipped_rules:
        flags.append("RULE_SKIPPED")

    status, score, rec = score_triage(kept, ruleset.triage)
    if status == TriageStatus.GREEN and flags:
        status = TriageStatus.YELLOW
        rec = InitialRecommendation.PEND if "DOC_UNREADABLE" in flags else InitialRecommendation.DOCTOR_REVIEW

    adjustments = _adjustments(drafts, claim, billing, ai_items or {})
    total_adjust = sum(a["amount"] for a in adjustments)
    if rec == InitialRecommendation.PAY_FULL:
        recommended = billed_amount
    elif adjustments:
        recommended = max(billed_amount - total_adjust, 0)
    else:
        recommended = None

    refs = list(dict.fromkeys(r for d in drafts for r in d.guideline_refs))
    missing = list(claim.docs.missing or [])
    if rec == InitialRecommendation.PAY_FULL:
        next_action = "Asuransi dapat mencatat keputusan bayar penuh."
    elif rec == InitialRecommendation.PEND:
        what = f"dokumen yang kurang ({', '.join(missing)})" if missing else "dokumen yang bisa dibaca"
        next_action = f"Minta {what} ke rumah sakit; setelah itu dokter menelaah dan menandatangani rekomendasi."
    elif status == TriageStatus.RED:
        next_action = "Telaah dokter spesialis, lalu tanda tangan rekomendasi final."
    else:
        next_action = "Telaah dokter umum, lalu tanda tangan rekomendasi final."

    quality_flags = [{"code": c, "message": QUALITY_MESSAGES[c]} for c in flags]
    return RecommendationDraft(
        triage_status=status.value,
        risk_score=score,
        recommendation=rec.value,
        findings=drafts,
        dropped_findings=dropped,
        skipped_rules=[s.model_dump() for s in triage.skipped_rules],
        line_adjustments=adjustments,
        billed_amount=billed_amount,
        recommended_amount=recommended,
        guideline_refs=refs,
        next_action=next_action,
        explanation_text=explain(status.value, rec.value, drafts, adjustments, quality_flags),
        quality_flags=quality_flags,
        matched_diagnosis=triage.matched_diagnosis,
    )


def explain(status: str, rec: str, findings: list[FindingDraft], adjustments: list[dict], quality_flags: list[dict]) -> str:
    """Draf penjelasan dalam bahasa sederhana. Tidak pernah menyatakan klaim ditolak."""
    parts: list[str] = []
    if rec == "PAY_FULL":
        parts.append("Tidak ditemukan hal yang perlu ditelaah dokter menurut aturan klinis yang dipakai. "
                     "Sistem menyarankan klaim dibayar penuh. Keputusan akhir tetap di tangan asuransi.")
        parts += [f"- (Informasi) {f.text}" for f in findings]
    else:
        if findings:
            parts.append(f"Sistem menemukan {len(findings)} hal yang perlu ditelaah dokter:")
            parts += [f"- {f.text}" for f in findings if f.severity != "INFO"]
            info = [f for f in findings if f.severity == "INFO"]
            parts += [f"- (Informasi) {f.text}" for f in info]
        if quality_flags:
            parts.append("Catatan kualitas data:")
            parts += [f"- {q['message']}" for q in quality_flags]
        if adjustments:
            total = sum(a["amount"] for a in adjustments)
            parts.append(f"Usulan koreksi tagihan untuk ditinjau dokter: {len(adjustments)} item, total {_rupiah(total)}.")
        parts.append("Ini draf dari sistem, bukan keputusan. Rekomendasi final ditetapkan dan ditandatangani dokter.")
    return "\n".join(parts)
