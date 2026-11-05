"""Pengaturan per tenant (asuransi) dan penerapannya ke aturan klinis.

Tenant hanya boleh MENYESUAIKAN aturan, bukan menulis aturan baru:
- ambang skor untuk status merah dan kuning (baris `skor_min` di bagian triase YAML);
- mematikan aturan tertentu (mis. aturan yang tidak relevan dengan produk asuransinya).
Hasilnya tetap RuleSet biasa, dan versinya diberi akhiran tenant supaya setiap rekomendasi
mencatat persis konfigurasi yang dipakai (mis. `rules-2026.11-demo+NUSA.v3`).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from sqlalchemy.orm import Session

from mab_api.models import Insurer, TenantSettings
from mab_pipeline.benefit import BenefitRuleSet
from mab_pipeline.rules.loader import RuleSet
from mab_pipeline.schemas import TriageStatus

DEFAULT_SLA_GP_HOURS = 24
DEFAULT_SLA_SPECIALIST_HOURS = 48


@dataclass(frozen=True)
class TenantConfig:
    insurer_id: str | None
    code: str | None
    name: str | None
    display_name: str | None = None
    logo_data_url: str | None = None
    primary_color: str | None = None
    triage_red_min_score: int | None = None
    triage_yellow_min_score: int | None = None
    disabled_rules: tuple[str, ...] = ()
    sla_gp_hours: int = DEFAULT_SLA_GP_HOURS
    sla_specialist_hours: int = DEFAULT_SLA_SPECIALIST_HOURS
    auto_assign: bool = True
    version: int = 0
    webhook_url: str | None = None
    webhook_secret: str | None = None

    @property
    def has_rule_overrides(self) -> bool:
        return bool(self.disabled_rules) or self.triage_red_min_score is not None or self.triage_yellow_min_score is not None

    def sla_hours(self, level: str) -> int:
        return self.sla_specialist_hours if level == "SPECIALIST" else self.sla_gp_hours


def tenant_config(db: Session, insurer_id: str | None) -> TenantConfig:
    """Pengaturan efektif tenant; nilai bawaan bila tenant belum punya pengaturan."""
    if insurer_id is None:
        return TenantConfig(insurer_id=None, code=None, name=None)
    insurer = db.get(Insurer, insurer_id)
    row = db.get(TenantSettings, insurer_id)
    base = TenantConfig(insurer_id=insurer_id, code=insurer.code if insurer else None, name=insurer.name if insurer else None)
    if row is None:
        return base
    return dataclasses.replace(
        base,
        display_name=row.display_name,
        logo_data_url=row.logo_data_url,
        primary_color=row.primary_color,
        triage_red_min_score=row.triage_red_min_score,
        triage_yellow_min_score=row.triage_yellow_min_score,
        disabled_rules=tuple(row.disabled_rules or ()),
        sla_gp_hours=row.sla_gp_hours or DEFAULT_SLA_GP_HOURS,
        sla_specialist_hours=row.sla_specialist_hours or DEFAULT_SLA_SPECIALIST_HOURS,
        auto_assign=bool(row.auto_assign),
        version=row.version or 1,
        webhook_url=row.webhook_url,
        webhook_secret=row.webhook_secret,
    )


def all_rule_ids(ruleset: RuleSet, benefit: BenefitRuleSet | None = None) -> set[str]:
    ids = {r.id for r in ruleset.general_rules} | {r.id for d in ruleset.diagnoses for r in d.rules}
    return ids | (benefit.rule_ids if benefit else set())


def apply_tenant_benefit(benefit: BenefitRuleSet, cfg: TenantConfig) -> BenefitRuleSet:
    """Aturan benefit tanpa aturan yang dimatikan tenant (id BEN-xx di daftar aturan nonaktif)."""
    disabled = set(cfg.disabled_rules) & benefit.rule_ids
    if not disabled:
        return benefit
    return dataclasses.replace(
        benefit,
        version=f"{benefit.version}+{cfg.code or 'tenant'}.v{cfg.version}",
        rules=tuple(r for r in benefit.rules if r.rule.id not in disabled),
    )


def apply_tenant(ruleset: RuleSet, cfg: TenantConfig) -> RuleSet:
    """RuleSet dengan penyesuaian tenant. Tanpa penyesuaian, RuleSet asli dikembalikan apa adanya."""
    if not cfg.has_rule_overrides:
        return ruleset
    disabled = set(cfg.disabled_rules)
    general = tuple(r for r in ruleset.general_rules if r.id not in disabled)
    diagnoses = tuple(dataclasses.replace(d, rules=tuple(r for r in d.rules if r.id not in disabled)) for d in ruleset.diagnoses)

    status_rules = []
    for sr in ruleset.triage.status_rules:
        if sr.min_score is not None:
            if sr.status == TriageStatus.RED and cfg.triage_red_min_score is not None:
                sr = dataclasses.replace(sr, min_score=cfg.triage_red_min_score,
                                         description=f"{sr.description} (ambang tenant: skor >= {cfg.triage_red_min_score})")
            elif sr.status == TriageStatus.YELLOW and cfg.triage_yellow_min_score is not None:
                sr = dataclasses.replace(sr, min_score=cfg.triage_yellow_min_score,
                                         description=f"{sr.description} (ambang tenant: skor >= {cfg.triage_yellow_min_score})")
        status_rules.append(sr)

    return dataclasses.replace(
        ruleset,
        version=f"{ruleset.version}+{cfg.code or 'tenant'}.v{cfg.version}",
        general_rules=general,
        diagnoses=diagnoses,
        triage=dataclasses.replace(ruleset.triage, status_rules=tuple(status_rules)),
    )


def tenant_ruleset(db: Session, ruleset: RuleSet, insurer_id: str | None) -> tuple[RuleSet, TenantConfig]:
    cfg = tenant_config(db, insurer_id)
    return apply_tenant(ruleset, cfg), cfg
