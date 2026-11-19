"""Faults without a matching rule are labelled by whether the source downtime codes exist."""

import pytest
from conftest import analyze_file
from openpyxl import Workbook, load_workbook

from core.corrections import shown
from core.i18n import UNMATCHED, K
from core.review_guidance import guidance
from report.excel_report import SHEETS, export_report

HEADERS = [
    "발생일",
    "설비코드",
    "설비명",
    "고장내용",
    "정지시간",
    "정지구분",
    "비가동 코드(중)",
    "비가동 코드(소)",
]


@pytest.fixture
def unmatched_file(tmp_path):
    path = tmp_path / "unmatched.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    rows = [
        ("unique unknown problem 1", None, None),
        ("unique unknown problem 2", "2P I/C VITAL-14 #5 필러", "구동파트"),
        ("센서 교체", None, None),
        ("이탈로 인해 정비및교체", "2P I/C VITAL-14 #5 필러", "세척기 진입 전 Con'V"),
    ]
    for number, (text, mid, small) in enumerate(rows, 1):
        sheet.append(
            [f"2026-01-0{number}", f"EQ{number}", f"EQ{number}", text, 10, K["fault"], mid, small]
        )
    workbook.save(path)
    return path


def test_unmatched_faults_are_labelled_by_source_downtime_codes(store, unmatched_file):
    result = analyze_file(store, unmatched_file)
    records = result.selected.set_index("raw_description")
    missing = records.loc["unique unknown problem 1"]
    unmatched = records.loc["unique unknown problem 2"]
    assert missing["status"] == K["code_missing"]
    assert unmatched["status"] == K["rule_unmatched"]
    assert [missing[key] for key in ("major", "detail_equipment", "middle", "minor")] == [""] * 4
    assert unmatched["detail_equipment"] == "필러·충진기"
    assert all(unmatched[key] == "" for key in ("major", "middle", "minor"))
    assert "비가동코드" in missing["classification_reason"]
    # Blank source codes never discard a description that a rule does match.
    replaced = records.loc["센서 교체"]
    assert replaced["status"] == K["partial"]
    assert replaced["middle"] == "센서(종류 미상)"
    assert replaced["detail_equipment"] == "상세설비 미상"
    assert replaced["minor"] == "현상 미기재"
    assert replaced["repair_actions"] == "교체"
    assert replaced["classification_mode"] == "single"
    assert replaced["component_count"] == replaced["part_count"] == 1
    assert replaced["classification_missing_fields"] == "상세설비·모듈, 고장 현상"
    assert K["symptom_missing"] not in replaced["issues"]
    # The source code names the whole conveyor, without inventing its failed subpart.
    coded = records.loc["이탈로 인해 정비및교체"]
    assert (coded["status"], coded["middle"], coded["minor"]) == (
        K["partial"],
        "세부 부품 미기재",
        "이탈·풀림",
    )
    assert coded["detail_equipment"] == "컨베어"
    assert coded["part_count"] == 0
    assert coded["component_count"] == 1
    assert coded["classification_missing_fields"] == "세부 부품"
    assert "비가동코드(소)" in coded["classification_reason"]
    assert result.metrics["code_missing_rows"] == 1
    assert result.metrics["rule_unmatched_rows"] == 1
    assert result.metrics["unclassified_rows"] == 2
    # Both remain in the review tab, as unclassified records did before.
    assert {"unique unknown problem 1", "unique unknown problem 2"} <= set(
        result.tables["review"]["raw_description"]
    )
    assert "센서 교체" not in set(result.tables["review"]["raw_description"])


def test_unmatched_labels_are_explained_and_never_offered_as_categories():
    for label in UNMATCHED:
        reason, action, effect = guidance({"status": label, "issues": "", "minutes": 1.0})
        assert reason.startswith(label) and action and "미확정 상태에서도 출력" in effect
        assert shown(label) == ""


def test_quality_sheet_counts_each_unmatched_label(store, unmatched_file, tmp_path):
    result = analyze_file(store, unmatched_file)
    out = export_report(result, tmp_path / "report.xlsx")
    quality = load_workbook(out, data_only=True)[SHEETS["review"]]
    counts = {
        quality.cell(row, 2).value: quality.cell(row, 3).value
        for row in range(1, quality.max_row + 1)
    }
    assert counts[K["code_missing"]] == 1
    assert counts[K["rule_unmatched"]] == 1
    assert "미분류" not in counts
