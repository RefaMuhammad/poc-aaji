"""Ringkasan pilot untuk manajer/staf klaim dan tim MAB (data rekaan)."""
from __future__ import annotations

from collections import Counter
from datetime import timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api.access import visible_claims_query
from mab_api import disputes as dispute_mod
from mab_api.api_schemas import CountItem, DashboardOut, DisputeMetrics
from mab_api.db import get_db
from mab_api.deps import require_perm
from mab_api.models import ClaimStatus, Dispute, Review, User
from mab_api.rbac import Perm, can_see_draft
from mab_api.routers.claims import _current_recommendation, _latest_decision, _released_to_insurer
from mab_api.ruleset import active_ruleset

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

STATUS_ORDER = [s.value for s in ClaimStatus]
TRIAGE_ORDER = ["GREEN", "YELLOW", "RED"]


def _utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


@router.get("", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db),
              user: User = Depends(require_perm(Perm.DASHBOARD))) -> DashboardOut:
    """Asuransi/TPA/auditor hanya melihat klaim dalam cakupannya dan rekomendasi yang sudah dirilis."""
    is_insurer = not can_see_draft(user.role)
    claims = list(db.scalars(visible_claims_query(user, db)))
    reason_labels = active_ruleset().reason_codes

    by_status, by_triage, by_rec, decisions = Counter(), Counter(), Counter(), Counter()
    findings, hospitals = Counter(), Counter()
    billed = recommended = correction = awaiting_doctor = 0
    processing: list[float] = []
    claim_ids = []
    for c in claims:
        claim_ids.append(c.id)
        by_status[c.status] += 1
        rec = _current_recommendation(c)
        if rec is None:
            continue
        first = min(c.recommendations, key=lambda r: r.version)
        if first.created_at and c.created_at:
            processing.append((_utc(first.created_at) - _utc(c.created_at)).total_seconds())
        if is_insurer and not _released_to_insurer(rec):
            awaiting_doctor += 1
            continue
        if not _released_to_insurer(rec):
            awaiting_doctor += 1
        by_triage[rec.triage_status] += 1
        by_rec[rec.recommendation] += 1
        if rec.recommended_amount is not None and _released_to_insurer(rec):
            billed += rec.billed_amount
            recommended += rec.recommended_amount
            correction += max(rec.billed_amount - rec.recommended_amount, 0)
        for f in rec.findings:
            findings[f.reason_code] += 1
        if rec.findings:
            hospitals[c.hospital_name] += len(rec.findings)
        dec = _latest_decision(c)
        if dec:
            decisions[dec.decision] += 1

    reviews = list(db.scalars(select(Review).where(Review.claim_id.in_(claim_ids), Review.finished_at.is_not(None)))) if claim_ids else []
    decided = [r for r in reviews if r.agrees_with_ai is not None]
    durations = [(_utc(r.finished_at) - _utc(r.started_at)).total_seconds() for r in decided]

    return DashboardOut(
        total_claims=len(claims),
        by_status=[CountItem(key=s, count=by_status[s]) for s in STATUS_ORDER if by_status[s]],
        by_triage=[CountItem(key=t, count=by_triage[t]) for t in TRIAGE_ORDER],
        by_recommendation=[CountItem(key=k, count=v) for k, v in by_rec.most_common()],
        awaiting_doctor=awaiting_doctor,
        billed_total=billed,
        recommended_total=recommended,
        correction_total=correction,
        top_findings=[CountItem(key=k, label=reason_labels.get(k), count=v) for k, v in findings.most_common(8)],
        top_hospitals=[CountItem(key=k, count=v) for k, v in hospitals.most_common(5)],
        avg_processing_seconds=round(sum(processing) / len(processing), 1) if processing else None,
        decisions=[CountItem(key=k, count=v) for k, v in decisions.most_common()],
        doctor_reviews=len(decided),
        doctor_agreement_pct=round(100 * sum(r.agrees_with_ai for r in decided) / len(decided), 1) if decided else None,
        avg_review_seconds=round(sum(durations) / len(durations), 1) if durations else None,
        disputes=dispute_metrics(db, claim_ids),
    )


def dispute_metrics(db: Session, claim_ids: list[str]) -> DisputeMetrics:
    """U5: metrik sengketa untuk klaim dalam cakupan pengguna."""
    rows = list(db.scalars(select(Dispute).where(Dispute.claim_id.in_(claim_ids)))) if claim_ids else []
    now = dispute_mod._now()
    status = Counter(d.status for d in rows)
    open_rows = [d for d in rows if d.status in dispute_mod.OPEN_STATUSES]
    resolved = [d for d in rows if d.status == dispute_mod.RESOLVED]
    outcomes = Counter(d.outcome for d in resolved)
    days = [(_utc(d.resolved_at) - _utc(d.created_at)).total_seconds() / 86400 for d in resolved if d.resolved_at]
    return DisputeMetrics(
        total=len(rows), open=len(open_rows), in_review=status[dispute_mod.IN_REVIEW],
        awaiting_decision=status[dispute_mod.AWAITING_DECISION],
        overdue=sum(1 for d in open_rows if _utc(d.due_at) < now),
        resolved=len(resolved), withdrawn=status[dispute_mod.WITHDRAWN],
        by_outcome=[CountItem(key=k, label=dispute_mod.OUTCOME_LABEL[k], count=outcomes[k])
                    for k in (dispute_mod.UPHELD, dispute_mod.MODIFIED, dispute_mod.OVERTURNED)],
        by_category=[CountItem(key=k, label=v, count=sum(1 for d in rows if d.category == k))
                     for k, v in dispute_mod.CATEGORY_LABEL.items()],
        overturn_rate=round(100 * (outcomes[dispute_mod.MODIFIED] + outcomes[dispute_mod.OVERTURNED]) / len(resolved), 1)
        if resolved else None,
        avg_resolution_days=round(sum(days) / len(days), 1) if days else None,
        resolved_on_time=sum(1 for d in resolved if d.resolved_at and _utc(d.resolved_at) <= _utc(d.due_at)),
    )
