# ruff: noqa: E402 -- standalone script bootstraps the repository import path.
"""Read-only production audit of the supplied 2026 downtime workbook.

Outputs live only under the audit output directory; an isolated profile prevents
the user's configuration and manual corrections from changing. The classifier
wrapper observes its returned decision, including the otherwise transient review
code, without changing the decision.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from profile_three_year_taxonomy import read_records

from core.config import ConfigStore
from core.excel_loader import load_excel
from core.failure_classification import FaultClassifier
from core.failure_modes import UNKNOWN_SYMPTOM
from core.i18n import K
from core.models import AnalysisOptions
from core.service import run_analysis


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(value):
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return safe(value.item())
    return str(value)


def parse_json(value):
    if not value:
        return []
    return json.loads(value) if isinstance(value, str) else value


def sample(row):
    return {
        key: row.get(key)
        for key in (
            "record_id",
            "event_id",
            "source_row",
            "minutes",
            "raw_description",
            "normalized",
            "raw_mid",
            "raw_small",
            "status",
            "review_code",
            "classification_reason",
            "issues",
            "repair_actions",
            "candidate_categories",
        )
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, default=Path("C:/Users/user/Downloads/라인 고장이력_26년.xlsx")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "output/review_rate_2026_20261112"
    )
    parser.add_argument("--run-name", default="baseline_v1_13_0")
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    # Unique profile by run name makes reruns inspectable and keeps real settings intact.
    profile = out / (args.run_name + "_profile")
    store = ConfigStore(profile)
    config = store.load()
    files = sorted(
        {
            *ROOT.joinpath("core").glob("*.py"),
            *ROOT.joinpath("config").glob("*.json"),
            ROOT / "config/classification_config.xlsx",
            ROOT / "version.py",
        }
    )
    before = {str(path.relative_to(ROOT)): digest(path) for path in files}
    source_before = digest(args.source)
    independent, sheet_metadata = read_records(args.source)
    independent_by_row = {row["_row"]: row for row in independent}
    loaded = load_excel(args.source, config["column_mapping"], mapping_lookup=store.saved_mapping)
    options = AnalysisOptions(scope="fault", equipment_basis="mapped", deduplicate=False)
    traces = []
    original = FaultClassifier.classify

    def observe(self, *values, **kwargs):
        result = original(self, *values, **kwargs)
        traces.append(
            {
                "input": {
                    "text": values[0],
                    "part_code": values[1] if len(values) > 1 else "",
                    "code_text": values[2] if len(values) > 2 else None,
                    **kwargs,
                },
                "result": copy.deepcopy(result),
            }
        )
        return result

    FaultClassifier.classify = observe
    try:
        result = run_analysis(loaded, config, options)
    finally:
        FaultClassifier.classify = original
    records = result.all_records.to_dict("records")
    trace_iter = iter(traces)
    rows = []
    for row in records:
        item = dict(row)
        item["source_raw"] = independent_by_row[int(row["source_row"])]
        trace = next(trace_iter) if row["kind"] == K["fault"] else None
        item["classifier_trace"] = trace
        item["review_code"] = trace["result"].get("review_code", "") if trace else ""
        candidates = parse_json(row.get("classification_candidates"))
        item["candidate_categories"] = [
            {
                k: candidate.get(k, "")
                for k in (
                    "major",
                    "detail_equipment",
                    "middle",
                    "minor",
                    "rank",
                    "rule_id",
                    "actions",
                    "reason",
                    "evidence",
                )
            }
            for candidate in candidates
        ]
        item["candidate_count"] = len(candidates)
        item["distinct_candidate_parts"] = len(
            {(x.get("detail_equipment"), x.get("middle")) for x in candidates}
        )
        item["distinct_candidate_symptoms"] = len({x.get("minor") for x in candidates})
        item["has_unknown_symptom_candidate"] = any(
            x.get("minor") == UNKNOWN_SYMPTOM for x in candidates
        )
        rows.append(item)
    assert next(trace_iter, None) is None
    after = {str(path.relative_to(ROOT)): digest(path) for path in files}
    source_after = digest(args.source)
    review = [row for row in rows if row["status"] == K["review"]]
    unmatched = [row for row in rows if row["status"] == K["rule_unmatched"]]
    by_code = defaultdict(list)
    by_issue = Counter()
    for row in review:
        by_code[row["review_code"] or "(empty)"].append(row)
        by_issue.update(part.strip() for part in row.get("issues", "").split(" | ") if part)
    summary = {
        "generated_at_seoul": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "source": str(args.source),
        "source_sha256_before": source_before,
        "source_sha256_after": source_after,
        "config_hash": config["hash"],
        "schema": config["classification_catalog"].get("output_schema"),
        "profile": str(profile),
        "input_rows": len(independent),
        "result_rows": len(rows),
        "source_sheets": sheet_metadata,
        "options": safe(vars(options)),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "review_code_counts": {
            key: len(values) for key, values in sorted(by_code.items(), key=lambda x: -len(x[1]))
        },
        "review_issue_counts": dict(by_issue.most_common()),
        "review_candidate_count_histogram": dict(Counter(row["candidate_count"] for row in review)),
        "review_distinct_part_histogram": dict(
            Counter(row["distinct_candidate_parts"] for row in review)
        ),
        "review_unknown_symptom_rows": sum(row["has_unknown_symptom_candidate"] for row in review),
        "review_exactly_one_candidate_rows": sum(row["candidate_count"] == 1 for row in review),
        "review_exactly_one_candidate_definition": f"status=검토필요인 {len(review)}건에서 저장된 classification_candidates 배열의 항목 수가 정확히 1인 행. 후보의 정확도가 검증됐다는 의미는 아님.",
        "review_multiple_candidates_one_part_rows": sum(
            row["candidate_count"] > 1 and row["distinct_candidate_parts"] == 1 for row in review
        ),
        "unmatched_rows": len(unmatched),
        "review_examples_by_code": {
            key: [sample(row) for row in values[:5]] for key, values in by_code.items()
        },
        "unmatched_examples": [sample(row) for row in unmatched[:10]],
        "raw_total_minutes": sum(
            float(row["비가동 시간(분)"])
            for row in independent
            if row.get("비가동 시간(분)") is not None
        ),
        "result_total_minutes": float(result.all_records["minutes"].sum()),
        "checks": {
            "source_bytes_unchanged": source_before == source_after,
            "code_and_config_unchanged_during_run": before == after,
            "source_row_set_preserved": set(independent_by_row)
            == {row["source_row"] for row in rows},
            "one_record_per_source_row": len(rows)
            == len(independent)
            == len({row["record_id"] for row in rows}),
            "event_ids_unique": len(rows) == len({row["event_id"] for row in rows}),
            "minutes_preserved": math.isclose(
                sum(
                    float(row["비가동 시간(분)"])
                    for row in independent
                    if row.get("비가동 시간(분)") is not None
                ),
                float(result.all_records["minutes"].sum()),
                abs_tol=1e-8,
            ),
        },
        "implementation_hashes_before": before,
        "implementation_hashes_after": after,
        "note": "This is a production behavior audit, not a measured classification accuracy score. Source raw includes original confidential notes for local review only.",
    }
    (out / (args.run_name + "_records.json")).write_text(
        json.dumps(safe(rows), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / (args.run_name + "_summary.json")).write_text(
        json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "rows": len(rows),
                "status_counts": summary["status_counts"],
                "review_code_counts": summary["review_code_counts"],
                "review_exactly_one_candidate_rows": summary["review_exactly_one_candidate_rows"],
                "unmatched": len(unmatched),
                "checks": summary["checks"],
                "records_path": str(out / (args.run_name + "_records.json")),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
