# ruff: noqa: E402 -- standalone script bootstraps the repository import path.
"""Inspect approved feedback cases through the production classifier."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.config import ConfigStore
from core.failure_classification import FaultClassifier
from core.parsing import prepare_text

config = ConfigStore(ROOT / "output/taxonomy_v3_20261112/probe_profile").load()
classifier = FaultClassifier(
    config["rules"],
    config["settings"].get("classifier"),
    config["classification_catalog"].get("equipment_types"),
)
cases = json.loads(
    (ROOT / "output/taxonomy_rebuild_20261112/phase3_representative_cases.json").read_text(
        encoding="utf-8"
    )
)
for item in cases:
    text = item["description"]
    result = classifier.classify(
        prepare_text(text, config["normalization"]), equipment_context=item.get("code_mid", "")
    )
    print(
        json.dumps(
            {
                "source": text,
                "proposed": item.get("proposed_decision"),
                "status": result["status"],
                "final": [result.get(k) for k in ("major", "detail_equipment", "middle", "minor")],
                "actions": result.get("repair_actions"),
                "candidates": [
                    {k: c.get(k) for k in ("major", "detail_equipment", "middle", "minor")}
                    for c in json.loads(result.get("classification_candidates", "[]"))
                ],
            },
            ensure_ascii=False,
        )
    )
