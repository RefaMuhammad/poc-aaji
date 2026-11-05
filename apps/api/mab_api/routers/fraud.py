"""Fraud Monitor (U3): sinyal fraud per tenant, bukti, dan telaah investigator.

Sinyal fraud adalah bahan investigasi. Endpoint di sini tidak pernah mengubah status,
rekomendasi, atau keputusan klaim.
"""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.access import get_visible_claim
from mab_api.api_schemas import (FraudClaimOut, FraudEntityOut, FraudImportOut, FraudOverviewOut, FraudReviewIn,
                                 FraudReviewOut, FraudRuleOut, FraudRulesetOut, FraudRunOut, FraudSignalOut)
from mab_api.db import get_db
from mab_api.deps import require_perm
from mab_api.fraud import REVIEW_STATUSES, import_history, latest_run, reviews_for, run_analysis, signals_for_claim
from mab_api.models import FraudClaimRecord, FraudReview, FraudSignal, IntegrationJob, User
from mab_api.policies import read_rows
from mab_api.rbac import Perm
from mab_api.routers.policies import MAX_IMPORT_BYTES, target_tenant
from mab_api.ruleset import active_fraud_ruleset
from mab_pipeline.fraud import HISTORY_COLUMNS

router = APIRouter(prefix="/fraud", tags=["fraud"])

can_view = require_perm(Perm.FRAUD_VIEW)
can_manage = require_perm(Perm.FRAUD_MANAGE)


def _review_out(r: FraudReview | None, names: dict[str, str]) -> FraudReviewOut | None:
    if r is None:
        return None
    return FraudReviewOut(status=r.status, notes=r.notes, reviewed_by_id=r.reviewed_by_id,
                          reviewed_by_name=names.get(r.reviewed_by_id), reviewed_at=r.reviewed_at)


def _user_names(db: Session, reviews) -> dict[str, str]:
    ids = {r.reviewed_by_id for r in reviews}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def _signal_out(s: FraudSignal, review: FraudReview | None, names: dict[str, str], *, full: bool) -> FraudSignalOut:
    rs = active_fraud_ruleset()
    rule = next((r for r in rs.rules if r.id == s.rule_id), None)
    return FraudSignalOut(
        id=s.id, run_id=s.run_id, rule_id=s.rule_id, rule_name=rule.name if rule else None, reason_code=s.reason_code,
        reason_label=rs.reason_codes.get(s.reason_code), severity=s.severity, weight=s.weight, entity_type=s.entity_type,
        entity_key=s.entity_key, entity_label=s.entity_label, message=s.message, claim_count=len(s.claim_numbers or []),
        claim_numbers=list(s.claim_numbers or []) if full else [], evidence=s.evidence if full else {},
        review=_review_out(review, names),
    )


def _status_of(review: FraudReview | None) -> str:
    return review.status if review else "OPEN"


@router.get("/ruleset", response_model=FraudRulesetOut)
def ruleset(_: User = Depends(can_view)):
    rs = active_fraud_ruleset()
    return FraudRulesetOut(version=rs.version, params=rs.params, reason_codes=rs.reason_codes, rules=[
        FraudRuleOut(id=r.id, name=r.name, entity=r.group, entity_type=r.entity_type, condition=r.condition.source,
                     reason_code=r.reason_code, severity=r.severity.value, weight=r.weight, message=r.message)
        for r in rs.rules])


@router.get("/overview", response_model=FraudOverviewOut)
def overview(insurer_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(can_view)):
    tenant = target_tenant(db, user, insurer_id)
    sources = dict(db.execute(select(FraudClaimRecord.source, func.count()).where(FraudClaimRecord.insurer_id == tenant)
                              .group_by(FraudClaimRecord.source)).all())
    run = latest_run(db, tenant)
    reviews = reviews_for(db, tenant)
    by_status: Counter = Counter()
    entities: list[FraudEntityOut] = []
    stale = False
    if run is not None:
        signals = db.scalars(select(FraudSignal).where(FraudSignal.run_id == run.id)).all()
        statuses: dict[tuple[str, str], list[str]] = {}
        for s in signals:
            st = _status_of(reviews.get((s.rule_id, s.entity_key)))
            by_status[st] += 1
            statuses.setdefault((s.entity_type, s.entity_key), []).append(st)
        entities = [FraudEntityOut(**e, review_statuses=statuses.get((e["entity_type"], e["entity_key"]), []))
                    for e in run.entities or []]
        newest = db.scalar(select(func.max(FraudClaimRecord.updated_at)).where(FraudClaimRecord.insurer_id == tenant))
        stale = bool(newest and _aware(newest) > _aware(run.created_at)) or sum(sources.values()) != run.record_count
    rs = active_fraud_ruleset()
    return FraudOverviewOut(
        insurer_id=tenant, ruleset_version=rs.version, record_count=sum(sources.values()), record_sources=sources,
        last_run=FraudRunOut.model_validate(run) if run else None, stale=stale,
        signals_open=by_status.get("OPEN", 0) + by_status.get("INVESTIGATING", 0), signals_by_status=dict(by_status),
        entities=entities,
    )


def _aware(d):
    from datetime import timezone

    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@router.get("/signals", response_model=list[FraudSignalOut])
def list_signals(
    insurer_id: str | None = None,
    entity_type: str | None = Query(default=None, max_length=20),
    review_status: str | None = Query(default=None, pattern="^(OPEN|INVESTIGATING|CONFIRMED|DISMISSED)$"),
    db: Session = Depends(get_db),
    user: User = Depends(can_view),
):
    """Sinyal run terakhir (tanpa bukti lengkap; ambil /fraud/signals/{id} untuk bukti)."""
    tenant = target_tenant(db, user, insurer_id)
    run = latest_run(db, tenant)
    if run is None:
        return []
    query = select(FraudSignal).where(FraudSignal.run_id == run.id)
    if entity_type:
        query = query.where(FraudSignal.entity_type == entity_type)
    signals = db.scalars(query).all()
    reviews = reviews_for(db, tenant)
    names = _user_names(db, reviews.values())
    out = []
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for s in sorted(signals, key=lambda s: (order.get(s.severity, 9), -s.weight, s.rule_id, s.entity_key)):
        review = reviews.get((s.rule_id, s.entity_key))
        if review_status and _status_of(review) != review_status:
            continue
        out.append(_signal_out(s, review, names, full=False))
    return out


def _visible_signal(db: Session, user: User, signal_id: str) -> FraudSignal:
    s = db.get(FraudSignal, signal_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sinyal tidak ditemukan")
    try:
        target_tenant(db, user, s.insurer_id)
    except HTTPException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sinyal tidak ditemukan")
    return s


@router.get("/signals/{signal_id}", response_model=FraudSignalOut)
def get_signal(signal_id: str, db: Session = Depends(get_db), user: User = Depends(can_view)):
    s = _visible_signal(db, user, signal_id)
    review = reviews_for(db, s.insurer_id).get((s.rule_id, s.entity_key))
    names = _user_names(db, [review] if review else [])
    out = _signal_out(s, review, names, full=True)
    # tautkan nomor klaim ke klaim platform supaya bisa dibuka dari bukti
    linked = dict(db.execute(select(FraudClaimRecord.claim_number, FraudClaimRecord.claim_id).where(
        FraudClaimRecord.insurer_id == s.insurer_id, FraudClaimRecord.claim_id.is_not(None),
        FraudClaimRecord.claim_number.in_(out.claim_numbers))).all()) if out.claim_numbers else {}
    if linked:
        out.evidence = {**out.evidence, "claim_links": linked}
    return out


@router.put("/signals/{signal_id}/review", response_model=FraudSignalOut)
def review_signal(signal_id: str, body: FraudReviewIn, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(can_manage)):
    """Catat hasil telaah investigator. Tidak mengubah klaim apa pun."""
    s = _visible_signal(db, user, signal_id)
    if body.status not in REVIEW_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Status telaah tidak dikenal")
    if body.status == "DISMISSED" and not (body.notes or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tulis alasan bila sinyal dinilai wajar")
    review = db.scalar(select(FraudReview).where(FraudReview.insurer_id == s.insurer_id, FraudReview.rule_id == s.rule_id,
                                                 FraudReview.entity_key == s.entity_key))
    before = {"status": review.status, "notes": review.notes} if review else None
    if review is None:
        review = FraudReview(insurer_id=s.insurer_id, rule_id=s.rule_id, entity_type=s.entity_type, entity_key=s.entity_key,
                             status=body.status, reviewed_by_id=user.id)
        db.add(review)
    from mab_api.models import utcnow

    review.status = body.status
    review.notes = (body.notes or "").strip() or None
    review.reviewed_by_id = user.id
    review.reviewed_at = utcnow()
    db.flush()
    audit.record(db, "FRAUD_SIGNAL_REVIEWED", user_id=user.id, user_role=user.role, request=request, detail={
        "insurer_id": s.insurer_id, "signal_id": s.id, "rule_id": s.rule_id, "entity_type": s.entity_type,
        "entity_key": s.entity_key, "before": before, "after": {"status": review.status, "notes": review.notes}})
    db.commit()
    return _signal_out(s, review, {user.id: user.full_name}, full=True)


@router.post("/runs", response_model=FraudRunOut)
def start_run(request: Request, insurer_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(can_manage)):
    """Jalankan analisis fraud atas seluruh data analitik tenant (sinkron; ribuan klaim selesai dalam detik)."""
    tenant = target_tenant(db, user, insurer_id)
    run = run_analysis(db, tenant, active_fraud_ruleset(), user_id=user.id)
    audit.record(db, "FRAUD_ANALYSIS_RUN", user_id=user.id, user_role=user.role, request=request, detail={
        "insurer_id": tenant, "run_id": run.id, "ruleset_version": run.ruleset_version, "records": run.record_count,
        "signals": run.signal_count})
    db.commit()
    return FraudRunOut.model_validate(run)


@router.get("/claims/{claim_id}", response_model=FraudClaimOut)
def claim_fraud(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_view)):
    claim = get_visible_claim(db, user, claim_id)
    run, signals = signals_for_claim(db, claim)
    reviews = reviews_for(db, claim.insurer_id)
    names = _user_names(db, reviews.values())
    # sinyal yang dinilai wajar tidak menambah skor
    score = min(100, sum(s.weight for s in signals if _status_of(reviews.get((s.rule_id, s.entity_key))) != "DISMISSED"))
    in_analysis = db.scalar(select(func.count()).select_from(FraudClaimRecord).where(
        FraudClaimRecord.insurer_id == claim.insurer_id, FraudClaimRecord.claim_number == claim.claim_number)) > 0
    return FraudClaimOut(
        claim_id=claim.id, ruleset_version=run.ruleset_version if run else None, run_at=run.created_at if run else None,
        score=score, level=active_fraud_ruleset().level(score), in_analysis=in_analysis,
        signals=[_signal_out(s, reviews.get((s.rule_id, s.entity_key)), names, full=False) for s in signals],
    )


@router.get("/records/template.csv")
def template(_: User = Depends(can_view)) -> Response:
    sample = ("HIS-REKAAN-0001,PST-REKAAN-001,Peserta Rekaan,\"Jl. Contoh No. 1, Kota Rekaan\",REK-00000001,RS Rekaan,"
              "\"dr. Rekaan, Sp.PD\",,A09,2026-01-10,2026-01-13,3600000,3")
    body = ",".join(HISTORY_COLUMNS) + "\n" + sample + "\n"
    return Response(body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="template_riwayat_klaim.csv"'})


@router.post("/records/import", response_model=FraudImportOut)
async def import_records(
    request: Request,
    file: UploadFile = File(...),
    insurer_id: str | None = Form(default=None),
    run: bool = Form(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(can_manage),
):
    """Impor riwayat klaim dari sistem inti (CSV/XLSX), lalu (bawaan) jalankan analisis ulang."""
    tenant = target_tenant(db, user, insurer_id)
    name = file.filename or "riwayat.csv"
    if not name.lower().endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File harus CSV atau XLSX")
    data = await file.read()
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File maksimal 10 MB")
    try:
        rows = read_rows(name, data)
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"File tidak bisa dibaca: {type(exc).__name__}")
    result = import_history(db, tenant, rows)
    job = IntegrationJob(insurer_id=tenant, channel="FRAUD_HISTORY", reference=name[:255], status=result.status,
                         summary=result.summary(), user_id=user.id)
    db.add(job)
    db.flush()
    audit.record(db, "FRAUD_HISTORY_IMPORTED", user_id=user.id, user_role=user.role, request=request,
                 detail={"insurer_id": tenant, "job_id": job.id, "file": name, **result.summary()})
    run_obj = None
    if run and (result.created or result.updated):
        run_obj = run_analysis(db, tenant, active_fraud_ruleset(), user_id=user.id)
        audit.record(db, "FRAUD_ANALYSIS_RUN", user_id=user.id, user_role=user.role, request=request, detail={
            "insurer_id": tenant, "run_id": run_obj.id, "ruleset_version": run_obj.ruleset_version,
            "records": run_obj.record_count, "signals": run_obj.signal_count})
    db.commit()
    return FraudImportOut(job_id=job.id, status=result.status, created=result.created, updated=result.updated,
                          errors=result.errors[:50], run=FraudRunOut.model_validate(run_obj) if run_obj else None)
