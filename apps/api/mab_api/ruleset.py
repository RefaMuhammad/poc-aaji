"""File aturan yang aktif (klinis + benefit), dibaca sekali per proses API."""
from __future__ import annotations

import dataclasses
from functools import lru_cache

from mab_api.config import get_settings
from mab_pipeline.benefit import BenefitRuleSet, load_benefit_rules
from mab_pipeline.rules import RuleSet, load_rules


@lru_cache(maxsize=1)
def active_benefit_ruleset() -> BenefitRuleSet:
    return load_benefit_rules(get_settings().resolved_benefit_rules_path())


@lru_cache(maxsize=1)
def active_ruleset() -> RuleSet:
    """Aturan klinis. Label kode alasan dan kamus data benefit ikut digabung supaya
    temuan benefit tampil dengan label yang benar di telaah dokter dan dashboard."""
    rs = load_rules(get_settings().rules_path)
    ben = active_benefit_ruleset()
    return dataclasses.replace(
        rs,
        reason_codes={**rs.reason_codes, **ben.reason_codes},
        data_dictionary={**rs.data_dictionary, **ben.data_dictionary},
    )
