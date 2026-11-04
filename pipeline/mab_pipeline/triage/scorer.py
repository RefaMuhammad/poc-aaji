"""Skor risiko dan status triase, sepenuhnya dari bagian `triase` di YAML."""
from __future__ import annotations

from mab_pipeline.rules.loader import StatusRule, TriageConfig
from mab_pipeline.schemas import Finding, InitialRecommendation, TriageStatus


def raw_score(findings: list[Finding], config: TriageConfig) -> int:
    return sum(config.severity_weights[f.severity] for f in findings)


def _matches(rule: StatusRule, findings: list[Finding], score: int) -> bool:
    if rule.is_default:
        return True
    codes = {f.reason_code for f in findings}
    severities = {f.severity for f in findings}
    return (
        any(code in codes for code in rule.any_reason_codes)
        or any(sev in severities for sev in rule.any_severities)
        or (rule.min_score is not None and score >= rule.min_score)
    )


def score_triage(findings: list[Finding], config: TriageConfig) -> tuple[TriageStatus, int, InitialRecommendation]:
    """Kembalikan (status, skor yang dibatasi skor_maksimum, rekomendasi awal)."""
    score = raw_score(findings, config)
    for rule in config.status_rules:
        if _matches(rule, findings, score):
            return rule.status, min(score, config.max_score), rule.initial_recommendation
    raise RuntimeError("aturan_status tidak punya baris default")  # dicegah oleh loader
