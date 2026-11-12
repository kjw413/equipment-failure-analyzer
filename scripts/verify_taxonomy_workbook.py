"""Reconcile the delivered workbook independently of its authoring runtime."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output/taxonomy_rebuild_20261112"
FILE = ROOT / "outputs/taxonomy_rebuild_20261112/분류체계_재정립_검토본.xlsx"


def load(name):
    return json.loads((WORK / name).read_text(encoding="utf-8"))


def main():
    source = load("source_records.json")
    draft = load("phase4_all_event_draft.json")
    data = load("workbook_data.json")
    wb = openpyxl.load_workbook(FILE, read_only=True, data_only=True)
    checks = {"sheet_names": wb.sheetnames == [x["name"] for x in data["tables"]]}
    history = list(wb["06_전체검토"].iter_rows(min_row=9, min_col=2, max_col=21, values_only=True))
    checks["event_rows"] = len(history) == len(source) == 3493
    checks["source_refs"] = [x[0] for x in history] == [x["ref"] for x in source]

    def normalized_newlines(value):
        return str(value or "").replace("\r\n", "\n").replace("\r", "\n")

    checks["raw_text_equal_after_newline_normalization"] = all(
        [normalized_newlines(value) for value in row[3:7]]
        == [
            normalized_newlines(item.get(key))
            for key in ("registered", "mid", "small", "description")
        ]
        for row, item in zip(history, source)
    )
    checks["record_ids"] = [x[18] for x in history] == [x["baseline_record_id"] for x in draft]
    checks["minutes"] = sum(x[17] for x in history) == sum(x["minutes"] for x in source)
    checks["wall_clock_timestamps"] = all(
        x[2] == datetime.fromisoformat(y["start"]) for x, y in zip(history, source)
    )
    checks["unreviewed_sample_stays_unmeasured"] = (
        wb["07_검수표본"]["C5"].value == 0 and wb["07_검수표본"]["E5"].value == "미측정"
    )
    checks["all_manual_labels_blank"] = all(
        all(value is None for value in row)
        for row in wb["07_검수표본"].iter_rows(
            min_row=9, max_row=68, min_col=7, max_col=12, values_only=True
        )
    )
    errors = []
    for sheet in wb:
        for row in sheet:
            errors.extend(
                f"{sheet.title}!{cell.coordinate}:{cell.value}"
                for cell in row
                if cell.data_type == "e"
            )
    checks["no_error_cells"] = not errors
    wb.close()
    metadata = openpyxl.load_workbook(FILE, read_only=False, data_only=False)
    checks["all_sheet_filters"] = all(len(sheet.tables) == 1 for sheet in metadata)
    checks["review_validation_controls"] = (
        len(metadata["07_검수표본"].data_validations.dataValidation) == 3
    )
    checks["review_formulas_preserved"] = all(
        metadata["07_검수표본"][f"M{row}"].data_type == "f" for row in range(9, 69)
    )
    metadata.close()
    profile = load("phase1_source_profile.json")
    checks["source_files_unchanged"] = all(
        hashlib.sha256(Path(x["path"]).read_bytes()).hexdigest() == x["sha256_before"]
        for x in profile["sources"]
    )
    feedback = profile["feedback_file"]
    checks["review_source_unchanged"] = (
        hashlib.sha256(Path(feedback["path"]).read_bytes()).hexdigest() == feedback["sha256"]
    )
    output = {
        "file": str(FILE),
        "bytes": FILE.stat().st_size,
        "checks": checks,
        "error_cells": errors,
        "source_rows": len(history),
        "minutes": sum(x[17] for x in history),
        "sha256": hashlib.sha256(FILE.read_bytes()).hexdigest(),
    }
    (WORK / "delivery_validation.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    assert all(checks.values()), checks


if __name__ == "__main__":
    main()
