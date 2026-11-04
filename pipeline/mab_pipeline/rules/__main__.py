"""CLI: python -m mab_pipeline.rules rules/aturan_klinis_demo.yaml klaim.json"""
import json
import sys

from mab_pipeline.rules import load_rules, run_rules
from mab_pipeline.schemas import ClaimData


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("Pemakaian: python -m mab_pipeline.rules <aturan.yaml> <klaim.json>")
    ruleset = load_rules(sys.argv[1])
    with open(sys.argv[2], encoding="utf-8") as fh:
        data = json.load(fh)
    claims = data if isinstance(data, list) else [data]
    results = [run_rules(ruleset, ClaimData.model_validate(c)).model_dump(mode="json") for c in claims]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
