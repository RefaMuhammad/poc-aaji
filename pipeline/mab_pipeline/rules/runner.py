"""Menjalankan aturan umum + aturan diagnosis yang cocok, lalu triase."""
from __future__ import annotations

from mab_pipeline.rules.engine import MissingData, evaluate, render_message
from mab_pipeline.rules.loader import Rule, RuleSet
from mab_pipeline.schemas import ClaimData, Finding, SkippedRule, TriageResult
from mab_pipeline.triage.scorer import score_triage


def run_rules(ruleset: RuleSet, claim: ClaimData) -> TriageResult:
    dx_rules = ruleset.match_diagnosis(claim.dx.primary)
    rules: list[Rule] = list(ruleset.general_rules) + (list(dx_rules.rules) if dx_rules else [])

    findings: list[Finding] = []
    skipped: list[SkippedRule] = []
    for rule in rules:
        try:
            hit = evaluate(rule.condition, claim)
        except MissingData as missing:
            skipped.append(SkippedRule(rule_id=rule.id, missing_fields=list(dict.fromkeys(missing.fields))))
            continue
        if hit:
            findings.append(
                Finding(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    reason_code=rule.reason_code,
                    severity=rule.severity,
                    needs_ai_evidence=rule.needs_ai,
                    message=render_message(rule.message, claim),
                    reference=rule.reference,
                    fields_used=list(rule.condition.fields),
                )
            )

    status, score, recommendation = score_triage(findings, ruleset.triage)
    return TriageResult(
        claim_id=claim.claim_id,
        ruleset_version=ruleset.version,
        matched_diagnosis=dx_rules.id if dx_rules else None,
        triage_status=status,
        risk_score=score,
        initial_recommendation=recommendation,
        findings=findings,
        skipped_rules=skipped,
    )
