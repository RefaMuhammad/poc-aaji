"""Admin (baca saja): aturan klinis yang aktif."""
from fastapi import APIRouter, Depends

from mab_api.api_schemas import RulesetDiagnosis, RulesetOut, RulesetRule
from mab_api.config import get_settings
from mab_api.deps import require_roles
from mab_api.models import Role, User
from mab_api.ruleset import active_ruleset

router = APIRouter(prefix="/admin", tags=["admin"])


def _rule(r) -> RulesetRule:
    return RulesetRule(id=r.id, name=r.name, reason_code=r.reason_code, severity=r.severity.value,
                       needs_ai=r.needs_ai, reference=r.reference)


@router.get("/ruleset", response_model=RulesetOut)
def ruleset(_: User = Depends(require_roles(Role.ADMIN, Role.DOCTOR_GP, Role.DOCTOR_SPECIALIST))) -> RulesetOut:
    rs = active_ruleset()
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
    )
