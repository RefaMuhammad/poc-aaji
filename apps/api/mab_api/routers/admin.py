"""Admin: aturan klinis yang aktif (baca saja) dan pemindahan penugasan dokter."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from mab_api.access import get_visible_claim
from mab_api.api_schemas import AssignmentOut, AssignRequest, BenefitRulesetOut, RulesetDiagnosis, RulesetOut, RulesetRule
from mab_api.assignment import (
    GP,
    assign,
    claim_reviews,
    close_active,
    current_recommendation,
    now_utc,
    routing,
    sla_due,
)
from mab_api.config import get_settings
from mab_api.db import get_db
from mab_api.deps import require_perm
from mab_api.models import AssignmentStatus, ClaimStatus, RecommendationState, Role, User
from mab_api.rbac import Perm
from mab_api.ruleset import active_benefit_ruleset, active_ruleset
from mab_api.tenancy import tenant_config

router = APIRouter(prefix="/admin", tags=["admin"])


def _rule(r) -> RulesetRule:
    return RulesetRule(id=r.id, name=r.name, reason_code=r.reason_code, severity=r.severity.value,
                       needs_ai=r.needs_ai, reference=r.reference)


@router.get("/ruleset", response_model=RulesetOut)
def ruleset(_: User = Depends(require_perm(Perm.RULESET_VIEW))) -> RulesetOut:
    rs = active_ruleset()
    ben = active_benefit_ruleset()
    return RulesetOut(
        version=rs.version,
        status=rs.raw.get("status") if rs.raw else None,
        path=get_settings().rules_path,
        general_rules=[_rule(r) for r in rs.general_rules],
        diagnoses=[
            RulesetDiagnosis(id=d.id, name=d.name, icd10=list(d.icd10), specialty=d.specialty, rules=[_rule(r) for r in d.rules])
            for d in rs.diagnoses
        ],
        triage=[
            {"jika": s.description, "status": s.status.value, "rekomendasi_awal": s.initial_recommendation.value}
            for s in rs.triage.status_rules
        ],
        reason_codes=rs.reason_codes,
        benefit=BenefitRulesetOut(version=ben.version, path=get_settings().resolved_benefit_rules_path(),
                                  rules=[_rule(r.rule) for r in ben.rules]),
    )


@router.post("/claims/{claim_id}/assign", response_model=AssignmentOut)
def reassign(claim_id: str, body: AssignRequest, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_perm(Perm.ASSIGN_ADMIN))):
    """Pindahkan kasus ke dokter lain (mis. dokter berhalangan). Telaah yang sedang berjalan dilepas."""
    claim = get_visible_claim(db, user, claim_id)
    rec = current_recommendation(claim)
    if claim.status != ClaimStatus.AWAITING_DOCTOR.value or rec is None or rec.state != RecommendationState.DRAFT.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Klaim tidak sedang menunggu telaah dokter")
    doctor = db.get(User, body.doctor_id)
    reviews = claim_reviews(db, claim)
    level, specialty, _, _ = routing(claim, rec, reviews)
    needed = Role.DOCTOR_GP.value if level == GP else Role.DOCTOR_SPECIALIST.value
    if doctor is None or not doctor.is_active or doctor.role != needed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Kasus ini untuk {'dokter umum' if level == GP else 'dokter spesialis'}")
    if rec.excluded_reviewer_id and doctor.id == rec.excluded_reviewer_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Banding harus ditelaah dokter yang berbeda dari penelaah awal")
    if level != GP and specialty and doctor.specialty != specialty:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Kasus ini untuk spesialis {specialty}")
    now = now_utc()
    for r in reviews:  # telaah terbuka dokter sebelumnya dilepas
        if r.finished_at is None:
            r.finished_at, r.action = now, "REASSIGNED"
    close_active(db, claim, AssignmentStatus.CANCELLED, now)
    claim.assigned_doctor_id = None
    a = assign(db, claim, rec, doctor, level=level, specialty=specialty,
               due=sla_due(rec, reviews, level, tenant_config(db, claim.insurer_id)), method="MANUAL",
               actor=user, request=request)
    db.commit()
    return a
