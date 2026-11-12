# ruff: noqa: E402 -- standalone script bootstraps the repository import path.
"""Run the real offline application against supplied yearly files and export XLSX.

An isolated profile keeps the user's installed settings and manual overrides
untouched. Quality checks are accounting/structural checks, not accuracy scores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openpyxl
from profile_three_year_taxonomy import read_records

from core.component_analysis import final_component
from core.config import ConfigStore
from core.excel_loader import load_excel
from core.failure_modes import UNKNOWN_PART
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.models import AnalysisOptions
from core.preprocessing import standardize
from core.service import run_analysis
from report.excel_report import DETAIL_COLS, SHEETS, export_report


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def final_path(row):
    member = final_component(row)
    return {key: member.get(key, "") for key in CATEGORY_FIELDS} if member else None


def candidate_paths(row):
    value = row.get("classification_candidates", "")
    if not value:
        return []
    return [{key: member.get(key, "") for key in CATEGORY_FIELDS} for member in json.loads(value)]


def check_export(path, result):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[SHEETS["detail"]]
        # The app's report uses row 6 headers and row 7+ event data.
        actual_ids = [
            row[0]
            for row in ws.iter_rows(min_row=7, max_col=1, values_only=True)
            if row[0] not in (None, "")
        ]
        expected_ids = result.selected["record_id"].tolist()
        id_ok = len(actual_ids) == len(expected_ids) and set(actual_ids) == set(expected_ids)
        headers = [cell.value for cell in ws[6]]
        return {
            "sheets": wb.sheetnames,
            "history_rows": len(actual_ids),
            "history_ids_preserved": id_ok,
            "four_axis_headers": {key: headers[DETAIL_COLS.index(key)] for key in CATEGORY_FIELDS},
            "file_bytes": path.stat().st_size,
        }
    finally:
        wb.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=Path("C:/Users/user/Downloads"))
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "output" / "taxonomy_4level_20261111"
    )
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile = args.output_dir / "validation_profile"
    store = ConfigStore(profile)
    config = store.load()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else []
    previous = {row["record_id"]: row for row in baseline}
    summary = {
        "validation_stage": "independent_axes_v3_20261112",
        "generated_at_seoul": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "schema": config["classification_catalog"]["output_schema"],
        "config_hash": config["hash"],
        "baseline": str(args.baseline) if args.baseline else None,
        "profile": str(profile),
        "options": {"scope": "fault", "equipment_basis": "mapped", "deduplicate": False},
        "note": "행·식별자·분류 개수·정지시간·집계 불변 검증. 정답셋이 없어 분류 정확도는 측정하지 않음.",
        "years": [],
        "binding_samples": [],
        "plc_card_cases": [],
    }
    part_equipment_samples = defaultdict(lambda: defaultdict(list))
    for year in ("24", "25", "26"):
        started = time.monotonic()
        source = args.source_dir / f"라인 고장이력_{year}년.xlsx"
        before = sha256(source)
        independent, _ = read_records(source)
        expected_rows = {row["_row"] for row in independent}
        expected_minutes = sum(
            float(row["비가동 시간(분)"])
            for row in independent
            if row.get("비가동 시간(분)") is not None
        )
        loaded = load_excel(source, config["column_mapping"], mapping_lookup=store.saved_mapping)
        options = AnalysisOptions(scope="fault", equipment_basis="mapped", deduplicate=False)
        result = run_analysis(loaded, config, options)
        rows = result.selected.to_dict("records")
        counts = [len(parse_components(row.get("component_details"))) for row in rows]
        confirmed = [row for row in rows if final_component(row) is not None]
        known_part_confirmed = [
            row
            for row in confirmed
            if final_component(row)["middle"] not in (UNKNOWN_PART, "제품·자재")
        ]
        duplicate_row_ids = int(result.all_records["record_id"].duplicated().sum())
        # Classification changes cannot rekey events or add/drop source rows.
        repeated = standardize(loaded, config, options)
        stable_ids = list(
            zip(
                result.all_records["source_row"],
                result.all_records["record_id"],
                result.all_records["event_id"],
            )
        ) == list(zip(repeated["source_row"], repeated["record_id"], repeated["event_id"]))
        aggregation_checks = {}
        for key in ("equipment", "line", "type", "equipment_type", "trend_month", "trend_year"):
            table = result.tables[key]
            aggregation_checks[key] = {
                "rows_counted": int(table["count"].sum()),
                "total_minutes": float(table["total_minutes"].sum()),
                "count_once": int(table["count"].sum()) == len(rows),
                "minutes_once": math.isclose(
                    float(table["total_minutes"].sum()), expected_minutes, abs_tol=1e-8
                ),
            }
        checks = {
            "independent_source_rows_equal_loaded": len(independent) == len(loaded.frame),
            "source_rows_preserved": expected_rows == set(result.all_records["source_row"]),
            "selected_source_rows_preserved": expected_rows == set(result.selected["source_row"]),
            "unique_record_ids": duplicate_row_ids == 0,
            "event_record_ids_deterministic": stable_ids,
            "maximum_one_final_classification": max(counts, default=0) <= 1,
            "known_part_final_count_matches_component_summary": int(
                result.tables["component"]["count"].sum()
            )
            == len(known_part_confirmed),
            "unknown_part_counts_as_zero_physical_parts": all(
                int(row.get("part_count", 0)) == 0
                for row in confirmed
                if final_component(row)["middle"] == UNKNOWN_PART
            ),
            "machine_not_repeated_as_detail_part": all(
                row.get("detail_equipment") != row.get("middle") for row in confirmed
            ),
            "fault_detail_one_row_per_event": len(result.tables["fault_detail"]) == len(rows),
            "raw_duration_sum_preserved": math.isclose(
                result.metrics["total_minutes"], expected_minutes, abs_tol=1e-8
            ),
            "every_aggregation_counted_once": all(
                value["count_once"] and value["minutes_once"]
                for value in aggregation_checks.values()
            ),
            "source_fingerprint_unchanged": sha256(source) == before,
        }
        if args.baseline:
            year_baseline = [row for row in baseline if str(row["year"]) == "20" + year]
            checks["baseline_event_record_ids_and_minutes_unchanged"] = {
                row["record_id"] for row in year_baseline
            } == {row["record_id"] for row in rows} and all(
                row["event_id"] == previous[row["record_id"]]["event_id"]
                and math.isclose(
                    float(row["minutes"]),
                    float(previous[row["record_id"]]["minutes"]),
                    abs_tol=1e-8,
                )
                for row in rows
                if row["record_id"] in previous
            )
        entry = {
            "year": "20" + year,
            "source": str(source),
            "source_sha256_before": before,
            "source_sha256_after": sha256(source),
            "independent_source_rows": len(independent),
            "metrics": result.metrics,
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "final_classification_count": len(confirmed),
            "known_part_final_classification_count": len(known_part_confirmed),
            "unknown_part_final_classification_count": len(confirmed) - len(known_part_confirmed),
            "max_final_classifications_per_event": max(counts, default=0),
            "detail_equipment_unknown_final_rows": sum(
                row.get("detail_equipment") == "상세설비 미상" for row in rows
            ),
            "detail_equipment_blank_final_rows": sum(
                not row.get("detail_equipment") for row in rows
            ),
            "detail_equipment_unknown_candidate_rows": sum(
                any(
                    candidate["detail_equipment"] == "상세설비 미상"
                    for candidate in candidate_paths(row)
                )
                for row in rows
            ),
            "detail_equipment_final_source_counts": dict(
                Counter(row.get("detail_equipment_source", "") for row in confirmed)
            ),
            "independent_raw_total_minutes": expected_minutes,
            "checks": checks,
            "aggregation_checks": aggregation_checks,
            "seconds": round(time.monotonic() - started, 3),
        }
        for row in rows:
            final = final_path(row)
            candidates = candidate_paths(row)
            compact = {
                "year": "20" + year,
                "source_row": int(row["source_row"]),
                "status": row["status"],
                "final": final,
                "candidate_paths": candidates,
                "detail_equipment_source": row.get("detail_equipment_source", ""),
            }
            if (
                final
                and len(part_equipment_samples[final["middle"]][final["detail_equipment"]]) < 3
            ):
                part_equipment_samples[final["middle"]][final["detail_equipment"]].append(compact)
            if any("PLC 카드" == candidate["middle"] for candidate in candidates) or (
                final and final["middle"] == "PLC 카드"
            ):
                summary["plc_card_cases"].append(compact)
        if not args.no_export:
            report = export_report(
                result, args.output_dir / f"라인 고장이력_{year}년_4단계분류_분석.xlsx"
            )
            entry["report"] = str(report)
            entry["export_checks"] = check_export(report, result)
            checks["export_history_ids_preserved"] = entry["export_checks"]["history_ids_preserved"]
            checks["source_fingerprint_after_export_unchanged"] = sha256(source) == before
        entry["all_checks_passed"] = all(checks.values())
        summary["years"].append(entry)
        print(
            json.dumps(
                {
                    "year": entry["year"],
                    "rows": len(rows),
                    "metrics": result.metrics,
                    "detail_unknown_final": entry["detail_equipment_unknown_final_rows"],
                    "checks": checks,
                    "report": entry.get("report"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    for part, equipment in part_equipment_samples.items():
        if len(equipment) > 1:
            summary["binding_samples"].append(
                {"part": part, "different_equipment": dict(equipment)}
            )
    summary["all_checks_passed"] = all(entry["all_checks_passed"] for entry in summary["years"])
    (args.output_dir / "application_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if not summary["all_checks_passed"]:
        raise SystemExit(
            "One or more application/accounting checks failed; see application_validation.json"
        )


if __name__ == "__main__":
    main()
