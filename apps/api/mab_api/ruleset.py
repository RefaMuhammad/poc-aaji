"""File aturan klinis yang aktif, dibaca sekali per proses API."""
from __future__ import annotations

from functools import lru_cache

from mab_api.config import get_settings
from mab_pipeline.rules import RuleSet, load_rules


@lru_cache(maxsize=1)
def active_ruleset() -> RuleSet:
    return load_rules(get_settings().rules_path)
