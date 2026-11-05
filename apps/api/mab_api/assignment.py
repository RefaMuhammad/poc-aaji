"""Routing kasus ke dokter, penugasan otomatis, dan SLA antrean.

- Klaim kuning masuk antrean dokter umum (GP); merah dan hasil eskalasi ke spesialis sebidang.
- Bila pengaturan tenant `auto_assign` aktif, kasus langsung ditugaskan ke dokter yang memenuhi
  syarat dengan beban aktif paling sedikit. Bila tidak ada dokter yang cocok, kasus tetap di
  antrean bersama dan bisa diambil dokter mana pun yang berhak.
- Batas waktu SLA dihitung dari saat kasus masuk antrean (draf dibuat, atau saat dieskalasi)
  ditambah jam SLA tenant untuk level antrean itu.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.models import (
    Assignment,
    AssignmentStatus,
    Claim,
    ClaimStatus,
    Recommendation,
    RecommendationState,
    Review,
    Role,
    User,
)
from mab_api.ruleset import active_ruleset
from mab_api.tenancy import TenantConfig, tenant_config

GP, SPECIALIST = "GP", "SPECIALIST"
ESCALATE = "ESCALATE"
AT_RISK_FRACTION = 0.25  # sisa waktu <= 25% dari jendela SLA dianggap "hampir lewat"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:  # SQLite menyimpan tanpa zona waktu
        return dt.replace(tzinfo=timezone.utc)
    return dt


def current_recommendation(claim: Claim) -> Recommendation | None:
    return next((r for r in reversed(claim.recommendations) if r.is_current), None)


def claim_reviews(db: Session, claim: Claim) -> list[Review]:
    return list(db.scalars(select(Review).where(Review.claim_id == claim.id).order_by(Review.started_at)))


def escalation(reviews: list[Review], rec: Recommendation | None) -> Review | None:
    if rec is None:
        return None
    return next((r for r in reversed(reviews) if r.action == ESCALATE and r.recommendation_id == rec.id), None)


def routing(claim: Claim, rec: Recommendation | None, reviews: list[Review]) -> tuple[str, str | None, bool, str | None]:
    """(level, spesialisasi, sudah_dieskalasi, nama_diagnosis) untuk antrean dokter."""
    dx = active_ruleset().match_diagnosis(claim.primary_icd10)
    esc = escalation(reviews, rec)
    specialty = (esc.escalated_specialty if esc and esc.escalated_specialty else None) or (dx.specialty if dx else None)
    level = SPECIALIST if (rec is not None and rec.triage_status == "RED") or esc else GP
    return level, specialty, esc is not None, dx.name if dx else None


# ----------------------------------------------------------------------------- SLA


def queue_entered_at(rec: Recommendation, reviews: list[Review]) -> datetime:
    esc = escalation(reviews, rec)
    if esc is not None and esc.finished_at is not None:
        return aware(esc.finished_at)
    return aware(rec.created_at)


def sla_due(rec: Recommendation, reviews: list[Review], level: str, cfg: TenantConfig) -> datetime:
    return queue_entered_at(rec, reviews) + timedelta(hours=cfg.sla_hours(level))


def sla_state(due: datetime, level: str, cfg: TenantConfig, now: datetime | None = None) -> str:
    """ON_TRACK / AT_RISK / OVERDUE untuk kasus yang masih di antrean."""
    now = now or now_utc()
    if now > due:
        return "OVERDUE"
    window = timedelta(hours=cfg.sla_hours(level))
    return "AT_RISK" if (due - now) <= window * AT_RISK_FRACTION else "ON_TRACK"


# ----------------------------------------------------------------------------- penugasan


def active_assignment(db: Session, claim: Claim) -> Assignment | None:
    return db.scalar(select(Assignment).where(Assignment.claim_id == claim.id,
                                              Assignment.status == AssignmentStatus.ACTIVE.value))


def close_active(db: Session, claim: Claim, new_status: AssignmentStatus, now: datetime | None = None) -> Assignment | None:
    a = active_assignment(db, claim)
    if a is not None:
        a.status = new_status.value
        a.closed_at = now or now_utc()
    return a


def eligible_doctors(db: Session, level: str, specialty: str | None) -> list[User]:
    if level == GP:
        q = select(User).where(User.role == Role.DOCTOR_GP.value, User.is_active.is_(True))
    else:
        q = select(User).where(User.role == Role.DOCTOR_SPECIALIST.value, User.is_active.is_(True))
        if specialty:
            q = q.where(User.specialty == specialty)
    return list(db.scalars(q.order_by(User.email)))


def _load(db: Session, doctor_ids: list[str]) -> dict[str, int]:
    rows = db.execute(
        select(Assignment.doctor_id, func.count())
        .where(Assignment.doctor_id.in_(doctor_ids), Assignment.status == AssignmentStatus.ACTIVE.value)
        .group_by(Assignment.doctor_id)
    )
    return {doctor_id: n for doctor_id, n in rows}


def assign(db: Session, claim: Claim, rec: Recommendation, doctor: User, *, level: str, specialty: str | None,
           due: datetime, method: str, actor: User | None = None, request=None) -> Assignment:
    a = Assignment(claim_id=claim.id, recommendation_id=rec.id, doctor_id=doctor.id, level=level, specialty=specialty,
                   method=method, status=AssignmentStatus.ACTIVE.value, assigned_by_id=actor.id if actor else None,
                   assigned_at=now_utc(), due_at=due)
    db.add(a)
    claim.assigned_doctor_id = doctor.id
    db.flush()
    audit.record(db, "CASE_ASSIGNED", user_id=actor.id if actor else None, user_role=actor.role if actor else None,
                 claim_id=claim.id, request=request,
                 detail={"assignment_id": a.id, "doctor_id": doctor.id, "level": level, "specialty": specialty,
                         "method": method, "due_at": due.isoformat()})
    return a


def auto_assign(db: Session, claim: Claim, *, exclude: set[str] | None = None, request=None) -> Assignment | None:
    """Tugaskan kasus yang menunggu dokter ke dokter yang berhak dengan beban paling ringan.

    Tidak melakukan apa-apa bila klaim tidak menunggu dokter, sudah dipegang dokter, tenant
    mematikan penugasan otomatis, atau tidak ada dokter yang memenuhi syarat.
    """
    rec = current_recommendation(claim)
    if (claim.status != ClaimStatus.AWAITING_DOCTOR.value or rec is None
            or rec.state != RecommendationState.DRAFT.value or claim.assigned_doctor_id):
        return None
    cfg = tenant_config(db, claim.insurer_id)
    if not cfg.auto_assign:
        return None
    reviews = claim_reviews(db, claim)
    level, specialty, _, _ = routing(claim, rec, reviews)
    doctors = [d for d in eligible_doctors(db, level, specialty) if d.id not in (exclude or set())]
    if not doctors:
        return None
    load = _load(db, [d.id for d in doctors])
    doctor = min(doctors, key=lambda d: (load.get(d.id, 0), d.email))
    return assign(db, claim, rec, doctor, level=level, specialty=specialty,
                  due=sla_due(rec, reviews, level, cfg), method="AUTO", request=request)
