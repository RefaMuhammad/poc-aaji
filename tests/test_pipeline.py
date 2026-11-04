"""Tes pipeline baca dokumen (M4): ingest, OCR, klasifikasi, ekstraksi, field turunan, job worker.

Memakai 3 klaim sintetis digital di tests/fixtures/klaim_sintetis (DATA REKAAN) dan LLM mode mock.
"""
from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from mab_api.models import AuditLog, Claim, Document, ExtractedField
from mab_pipeline.documents import LoadedDocument, PageContent, TextLine
from mab_pipeline.extraction.derived_fields import derive
from mab_pipeline.extraction.facts import BillingFacts, BillingItem, ClaimFacts, CpptFacts, LabFacts, LabResult, MedicationAdmin
from mab_pipeline.extraction.llm_extractor import PROMPT_VERSION, extract_document
from mab_pipeline.ingest.doc_classifier import classify
from mab_pipeline.ingest.image_preprocess import estimate_skew
from mab_pipeline.ingest.pdf_loader import load_document, render_pdf_pages
from mab_pipeline.llm.client import OpenAICompatibleClient, get_llm_client
from mab_pipeline.llm.mock import MockLLMClient
from mab_pipeline.ocr.engine import NullOCREngine, OcrLine
from mab_pipeline.pipeline import InputDocument, read_claim
from mab_pipeline.tasks import process_claim
from synthetic.generate_cases import derive_ground_truth

FIXTURES = Path(__file__).parent / "fixtures" / "klaim_sintetis"
CLAIM_IDS = ["SYN-DEN-09", "SYN-TIF-06", "SYN-GEA-07"]
DOC_TYPES = ["resume_medis", "hasil_laboratorium", "cppt", "rincian_tagihan"]
# field yang diisi M4 (dokumen + hitung); clin.* dan bill.items_without_clinical_note dikerjakan M5
SKIP_GROUPS = ("clin", "history")


def _case(claim_id: str) -> dict:
    return json.loads((FIXTURES / claim_id / "case.json").read_text(encoding="utf-8"))


def _inputs(claim_id: str) -> list[InputDocument]:
    return [
        InputDocument(f"doc-{t}", f"{t}.pdf", "application/pdf", (FIXTURES / claim_id / f"{t}.pdf").read_bytes())
        for t in DOC_TYPES
    ]


def _expected(claim_id: str) -> dict:
    truth = derive_ground_truth(_case(claim_id))
    out = {}
    for group, values in truth.items():
        if group == "claim_id" or group in SKIP_GROUPS:
            continue
        for name, value in values.items():
            if f"{group}.{name}" != "bill.items_without_clinical_note":
                out[f"{group}.{name}"] = value
    return out


@pytest.fixture
def mock_llm():
    return MockLLMClient(fixtures_dir=FIXTURES)


# --- ingest -----------------------------------------------------------------------------


def test_digital_pdf_has_text_lines_with_normalized_bbox_and_no_watermark():
    doc = load_document("d1", (FIXTURES / "SYN-DEN-09" / "rincian_tagihan.pdf").read_bytes(), "application/pdf")
    assert [p.mode for p in doc.pages] == ["digital"] * len(doc.pages)
    assert doc.lines[0].id == "D1-P1-L1"
    for line in doc.lines:
        x0, y0, x1, y1 = line.bbox
        assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
        assert line.confidence == 1.0
    # huruf watermark miring "DATA REKAAN" tidak boleh menyusup ke baris tabel
    assert all(line.text in ("DATA REKAAN",) or "Pemeriksaan Darah LeA" not in line.text for line in doc.lines)
    assert any(line.text.endswith("Pemeriksaan Darah Lengkap 1 95.000 95.000") for line in doc.lines)


def test_scanned_page_without_ocr_is_marked_unavailable():
    page = render_pdf_pages((FIXTURES / "SYN-DEN-09" / "resume_medis.pdf").read_bytes(), dpi=50)[0]
    buf = io.BytesIO()
    page.save(buf, format="PNG")
    doc = load_document("d1", buf.getvalue(), "image/png", ocr=NullOCREngine())
    assert doc.pages[0].mode == "ocr_unavailable" and doc.lines == []


class FakeOcr:
    """OCR tiruan: 'membaca' gambar halaman dengan teks dari PDF digital aslinya,
    dipecah per kata seperti kotak keluaran PaddleOCR."""

    name = "fake"

    def __init__(self, pdf_bytes: bytes):
        self.source = load_document("src", pdf_bytes, "application/pdf")

    def available(self) -> bool:
        return True

    def read(self, image: Image.Image) -> list[OcrLine]:
        w, h = image.size
        boxes = []
        for line in self.source.pages[0].lines:
            x0, y0, x1, y1 = line.bbox
            words = line.text.split(" ")
            step = (x1 - x0) / len(words)
            for i, word in enumerate(words):
                boxes.append(OcrLine(word, ((x0 + i * step) * w, y0 * h, (x0 + (i + 1) * step) * w, y1 * h), 0.93))
        return boxes


def test_ocr_path_groups_words_into_lines_and_feeds_extraction(mock_llm):
    pdf = (FIXTURES / "SYN-DEN-09" / "hasil_laboratorium.pdf").read_bytes()
    image = render_pdf_pages(pdf, dpi=100)[0]
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    doc = load_document("lab", buf.getvalue(), "image/png", ocr=FakeOcr(pdf))
    assert doc.pages[0].mode == "ocr"
    digital = load_document("src", pdf, "application/pdf").pages[0].lines
    assert [l.text for l in doc.lines] == [l.text for l in digital]
    assert all(l.confidence == 0.93 for l in doc.lines)

    doc.doc_type, _ = classify(doc)
    outcome = extract_document(mock_llm, doc, "SYN-DEN-09")
    assert outcome.status == "ok" and outcome.facts.results


def test_deskew_estimates_rotation():
    page = render_pdf_pages((FIXTURES / "SYN-TIF-06" / "cppt.pdf").read_bytes(), dpi=100)[0].convert("L")
    tilted = page.rotate(-2, fillcolor=255, expand=False)
    assert abs(estimate_skew(page)) <= 0.5
    assert estimate_skew(tilted) == pytest.approx(2, abs=0.5)


# --- klasifikasi --------------------------------------------------------------------------


@pytest.mark.parametrize("doc_type", DOC_TYPES)
def test_keyword_classifier_recognizes_every_template(doc_type):
    for claim_id in CLAIM_IDS:
        doc = load_document("d", (FIXTURES / claim_id / f"{doc_type}.pdf").read_bytes(), "application/pdf")
        assert classify(doc) == (doc_type, "keyword")


def test_classifier_falls_back_to_llm_then_filename():
    doc = LoadedDocument("d", "x.pdf", [PageContent(1, "digital", [TextLine("D1-P1-L1", "d", 1, "Surat keterangan", (0, 0, 1, 0.1))])])

    class Answer:
        model_version = "uji"

        def complete_json(self, system, user, *, task, context):
            return '{"doc_type": "resep"}'

    assert classify(doc, Answer()) == ("resep", "llm")
    assert classify(doc, MockLLMClient(FIXTURES), hint="cppt") == ("cppt", "filename")
    assert classify(doc) == ("unknown", "none")


# --- ekstraksi LLM ------------------------------------------------------------------------


def _lab_doc() -> LoadedDocument:
    line = TextLine("D1-P1-L1", "d", 1, "Trombosit 95.000 /uL", (0.1, 0.1, 0.5, 0.12))
    return LoadedDocument("d", "lab.pdf", [PageContent(1, "digital", [line])], doc_type="hasil_laboratorium")


class ScriptedLLM:
    model_version = "uji"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def complete_json(self, system, user, *, task, context):
        self.prompts.append(user)
        return self.answers.pop(0)


def test_invalid_answer_is_retried_once_with_error():
    good = '{"results": [{"date": "2026-03-10", "time": "06:00", "test": "plt", "value": 95000, "source_line_ids": ["D1-P1-L1"]}]}'
    llm = ScriptedLLM('{"results": [{"test": "trombosit"}]}', good)
    outcome = extract_document(llm, _lab_doc())
    assert outcome.status == "retried" and outcome.attempts == 2
    assert "tidak valid" in llm.prompts[1]
    assert outcome.facts.results[0].value == 95000


def test_answer_invalid_twice_is_flagged_failed():
    outcome = extract_document(ScriptedLLM("bukan json", "{\"results\": 5}"), _lab_doc())
    assert outcome.status == "failed" and outcome.facts is None
    assert "tidak valid 2 kali" in outcome.warnings[0]


def test_unknown_line_ids_are_dropped_and_flagged():
    answer = '{"results": [{"test": "plt", "value": 95000, "source_line_ids": ["D9-P9-L9"]}]}'
    outcome = extract_document(ScriptedLLM(answer), _lab_doc())
    assert outcome.facts.results[0].source_line_ids == []
    assert any("tidak dikenal" in w for w in outcome.warnings)
    assert any("tanpa bukti" in w for w in outcome.warnings)


def test_fenced_json_is_accepted():
    answer = '```json\n{"results": []}\n```'
    assert extract_document(ScriptedLLM(answer), _lab_doc()).status == "ok"


# --- field turunan ------------------------------------------------------------------------


def test_derived_fields_rules():
    d1, d2 = date(2026, 3, 1), date(2026, 3, 2)
    facts = ClaimFacts(
        documents_present=["resume_medis", "hasil_laboratorium"],
        labs=LabFacts(results=[
            LabResult(date=d1, time="06:00", test="hct", value="40,0", source_line_ids=["a"]),
            LabResult(date=d2, time="06:00", test="hct", value=48.0, source_line_ids=["b"]),
            LabResult(date=d2, time="06:00", test="plt", value="95.000", source_line_ids=["c"]),
            LabResult(date=d2, time="18:00", test="plt", value=101000, source_line_ids=["d"]),
            LabResult(date=d1, time="08:00", test="widal_o", value="1/80"),
            LabResult(date=d2, time="08:00", test="widal_o", value=320),
        ]),
        cppt=CpptFacts(medications=[
            MedicationAdmin(date=d1, name="Seftriakson 2 g IV"), MedicationAdmin(date=d2, name="Seftriakson 2 g IV"),
            MedicationAdmin(date=d1, name="infus RL"),
        ]),
    )
    out = {k: v.value for k, v in derive(facts).items()}
    assert out["lab.hct_rise_pct"] == 20.0
    assert out["lab.platelet_min"] == 95000
    assert out["lab.cbc_max_per_day"] == 2
    assert out["lab.widal_tests"] == 2 and out["lab.widal_o_max_titer"] == 320 and out["lab.widal_fourfold_rise"] is True
    # tagihan tidak ada -> terapi dibaca dari CPPT
    assert out["tx.ceftriaxone_days"] == 2 and out["tx.iv_fluid_days"] == 1 and out["tx.antibiotic_given"] is True
    assert out["bill.duplicate_items"] is None
    assert out["docs.missing"] == ["rincian_tagihan"]
    assert out["claim.los_days"] is None  # resume tidak ada -> tidak bisa dihitung, bukan 0


def test_derived_fields_without_labs_are_unknown_not_zero():
    out = {k: v.value for k, v in derive(ClaimFacts(documents_present=["rincian_tagihan"], billing=BillingFacts())).items()}
    assert out["lab.widal_tests"] is None and out["lab.platelet_min"] is None
    assert out["tx.ceftriaxone_days"] == 0 and out["bill.duplicate_items"] == 0


def test_duplicate_billing_items_counted():
    item = dict(date=date(2026, 3, 1), time="06:00", name="Pemeriksaan Darah Lengkap", unit_price=95000)
    facts = ClaimFacts(billing=BillingFacts(items=[BillingItem(**item, source_line_ids=["x"]), BillingItem(**item, source_line_ids=["y"]),
                                                   BillingItem(**{**item, "time": "12:00"})]))
    dup = derive(facts)["bill.duplicate_items"]
    assert dup.value == 1 and dup.line_ids == ["x", "y"]


# --- alur lengkap dengan mock LLM ----------------------------------------------------------


@pytest.mark.parametrize("claim_id", CLAIM_IDS)
def test_read_claim_matches_ground_truth_with_evidence(claim_id, mock_llm):
    result = read_claim(_inputs(claim_id), mock_llm, NullOCREngine(), claim_id)
    got = {k: v.value for k, v in result.derived.items()}
    assert got == _expected(claim_id)
    assert result.prompt_version == PROMPT_VERSION and result.model_version == "mock-llm-1"
    lines = result.line_index()
    for path, dv in result.derived.items():
        if dv.value not in (None, [], 0, False):
            assert dv.line_ids, f"{path} tanpa bukti"
            assert all(i in lines for i in dv.line_ids)
    assert result.warnings == []


def test_unreadable_documents_fall_back_to_filename_type(mock_llm):
    inputs = _inputs("SYN-DEN-09")
    for item in inputs:
        image = render_pdf_pages(item.data, dpi=40)[0]
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        item.data, item.content_type = buf.getvalue(), "image/png"
        item.doc_type_hint = item.filename.removesuffix(".pdf")
    result = read_claim(inputs, mock_llm, NullOCREngine(), "SYN-DEN-09")
    assert result.derived["docs.missing"].value == []          # dokumen ada, hanya tidak terbaca
    assert result.derived["lab.platelet_min"].value is None     # tidak menebak
    assert any("OCR tidak tersedia" in w for w in result.warnings)


def test_llm_provider_selection(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert isinstance(get_llm_client(), MockLLMClient)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_KEY", "kunci-uji")
    client = get_llm_client()
    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "https://api.deepseek.com" and client.model == "deepseek-chat"


def test_openai_compatible_client_sends_json_mode(monkeypatch):
    sent = {}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"model": "deepseek-chat", "choices": [{"message": {"content": "{\"ok\": true}"}}]}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers)
        return Resp()

    monkeypatch.setattr("mab_pipeline.llm.client.httpx.post", fake_post)
    client = OpenAICompatibleClient("https://api.deepseek.com", "deepseek-chat", "kunci-uji")
    assert client.complete_json("sistem", "isi", task="extract:cppt", context={}) == '{"ok": true}'
    assert sent["url"] == "https://api.deepseek.com/chat/completions"
    assert sent["body"]["response_format"] == {"type": "json_object"} and sent["body"]["temperature"] == 0
    assert sent["headers"]["Authorization"] == "Bearer kunci-uji"


# --- job worker -----------------------------------------------------------------------------


CLAIM_BODY = {
    "claim_number": "SYN-DEN-09",
    "policy_number": "POL-DEMO-1",
    "member_id": "PST-REKAAN-9",
    "hospital_name": "RS rekaan",
    "admission_date": "2026-02-01",
    "discharge_date": "2026-02-06",
    "billed_amount": 5_000_000,
}


def test_process_claim_saves_fields_with_evidence(client, login, session_factory, storage, mock_llm):
    case = _case("SYN-DEN-09")
    headers = login("staf")
    body = {**CLAIM_BODY, "admission_date": case["admission_date"], "discharge_date": case["discharge_date"]}
    claim = client.post("/claims", json=body, headers=headers).json()
    # klaim lain peserta yang sama dengan tanggal tumpang tindih
    other = client.post("/claims", json={**body, "claim_number": "KLM-RIWAYAT-9"}, headers=headers).json()
    files = [("files", (f"{t}.pdf", (FIXTURES / "SYN-DEN-09" / f"{t}.pdf").read_bytes(), "application/pdf")) for t in DOC_TYPES]
    assert client.post(f"/claims/{claim['id']}/documents", files=files, headers=headers).status_code == 201

    assert process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine()) == "AWAITING_DOCTOR"

    fields = {f["field_path"]: f for f in client.get(f"/claims/{claim['id']}/fields", headers=headers).json()}
    expected = _expected("SYN-DEN-09")
    assert {k: fields[k]["value"] for k in expected} == expected
    assert fields["history.overlapping_claims"]["value"] == 1
    assert "KLM-RIWAYAT-9" in fields["history.overlapping_claims"]["evidence"][0]["quote"]

    plt = fields["lab.platelet_min"]
    assert plt["source"] == "dokumen" and plt["confidence"] == 1.0
    ev = plt["evidence"][-1]
    assert ev["page"] == 1 and len(ev["bbox"]) == 4 and f"{expected['lab.platelet_min']:,}".replace(",", ".") in ev["quote"]

    with session_factory() as db:
        c = db.get(Claim, claim["id"])
        assert c.status == "AWAITING_DOCTOR" and c.primary_icd10 == case["icd10"]
        docs = db.scalars(select(Document).where(Document.claim_id == c.id)).all()
        assert {d.doc_type for d in docs} == set(DOC_TYPES) and all(d.page_count for d in docs)
        assert any(ev["doc"] == d.id for d in docs)
        pages = json.loads(storage.get(docs[0].storage_key + ".pages.json"))
        assert pages["pages"][0]["lines"][0]["id"].startswith("D")
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "PIPELINE_COMPLETED"))
        assert audit.detail["model_version"] == "mock-llm-1" and audit.detail["prompt_version"].startswith(PROMPT_VERSION)
        assert audit.detail["ocr_engine"] == "none"

    # menjalankan ulang tidak menggandakan field
    process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine())
    with session_factory() as db:
        n = len(db.scalars(select(ExtractedField).where(ExtractedField.claim_id == claim["id"])).all())
    assert n == len(fields)
    assert other["id"] != claim["id"]


def test_other_insurer_cannot_read_fields(client, login):
    claim = client.post("/claims", json=CLAIM_BODY, headers=login("staf")).json()
    assert client.get(f"/claims/{claim['id']}/fields", headers=login("staf_b")).status_code == 404


def test_paddle_engine_parses_paddleocr_2x_output():
    from mab_pipeline.ocr.engine import PaddleOCREngine

    class FakePaddle:
        def ocr(self, img, cls=True):
            assert img.shape[2] == 3
            return [[[[[10, 20], [110, 20], [110, 40], [10, 40]], ("Trombosit 95.000", 0.91)]]]

    engine = PaddleOCREngine()
    engine._ocr = FakePaddle()
    [line] = engine.read(Image.new("RGB", (200, 100), "white"))
    assert line.text == "Trombosit 95.000" and line.bbox == (10, 20, 110, 40) and line.confidence == 0.91


def test_ping_job():
    from mab_pipeline.tasks import ping

    assert ping() == "pong"
