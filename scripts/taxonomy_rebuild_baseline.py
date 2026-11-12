"""Run the current app in an isolated profile to compare a proposed taxonomy."""

# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.config import ConfigStore
from core.excel_loader import load_excel
from core.models import AnalysisOptions
from core.service import run_analysis

OUT = ROOT / "output/taxonomy_rebuild_20261112"


def main():
    store = ConfigStore(OUT / "baseline_profile")
    config = store.load()
    output, metrics = [], []
    for year in (24, 25, 26):
        path = Path(f"C:/Users/user/Downloads/라인 고장이력_{year}년.xlsx")
        loaded = load_excel(path, config["column_mapping"], mapping_lookup=store.saved_mapping)
        result = run_analysis(
            loaded,
            config,
            AnalysisOptions(scope="fault", equipment_basis="mapped", deduplicate=False),
        )
        frame = result.selected
        columns = [
            "record_id",
            "event_id",
            "source_row",
            "source_sheet",
            "major",
            "detail_equipment",
            "middle",
            "minor",
            "status",
            "classification_mode",
            "classification_candidates",
            "classification_reason",
            "component_details",
            "raw_description",
            "description",
            "part_code",
            "code_small",
            "code_mid",
            "minutes",
        ]
        for item in frame[[key for key in columns if key in frame]].to_dict("records"):
            item["year"] = 2000 + year
            output.append(item)
        metrics.append({"year": 2000 + year, **result.metrics})
        print(year, len(frame), flush=True)
    for name, value in (("baseline_records.json", output), ("baseline_metrics.json", metrics)):
        (OUT / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
