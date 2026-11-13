"""v1.5.0 regression tests: classification engine, review policy, corrections,
defaults merge into existing profiles, saved column mappings and record IDs."""

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from conftest import analyze_file
from openpyxl import Workbook

from core.classifier import RuleClassifier, clauses, read_rules
from core.config import ConfigStore, resource_root
from core.corrections import correction_patch, initial_values, validate
from core.defaults_merge import describe
from core.excel_loader import load_excel
from core.i18n import K
from core.models import AnalysisOptions
from core.preprocessing import (
    EVENT_FIELDS,
    event_id_for,
    event_ids,
    expand_endings,
    prepare_text,
    text,
)
from core.review_guidance import guidance
from core.service import run_analysis

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE = resource_root() / "config"


@pytest.fixture(scope="module")
def classify():
    settings = json.loads((BUNDLE / "settings.json").read_text(encoding="utf-8"))
    normalization = json.loads((BUNDLE / "normalization.json").read_text(encoding="utf-8"))
    # Freeze historical rule IDs only for engine regression examples. ConfigStore
    # fixtures and end-to-end tests continue to load the current production catalog.
    engine = RuleClassifier(
        read_rules(FIXTURES / "v172_config" / "classification_config.xlsx"),
        settings["classifier"],
    )
    return lambda value, part="": engine.classify(prepare_text(value, normalization), part)


def rule_id(result):
    return result["evidence"].split(" | ")[0]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("후크 교", "후크 교체"),
        ("1.3.5번 센터후단 후크교", "1.3.5번 센터후단 후크교체"),
        ("서보 드라이브 에러 발", "서보 드라이브 에러 발생"),
        ("제대기 조", "제대기 조정"),
        ("센서 비교", "센서 비교"),
        ("교 체결 상태", "교 체결 상태"),
        ("후크 교 / 생산", "후크 교체 / 생산"),
    ],
)
def test_clause_end_expansion(value, expected):
    endings = json.loads((BUNDLE / "normalization.json").read_text(encoding="utf-8"))[
        "clause_end_expansions"
    ]
    assert expand_endings(value, endings) == expected


def test_seal_spellings_normalize_to_one_word():
    normalization = json.loads((BUNDLE / "normalization.json").read_text(encoding="utf-8"))
    assert prepare_text("엔드실러 실링 불량", normalization) == "엔드씰러 씰링 불량"
    assert prepare_text("t.c 교체, 솔레노이드 벨브", normalization) == "tc 교체, 솔밸브"


@pytest.mark.parametrize(
    "value,expected,review_code",
    [
        ("실린더 센서 교체", "SENSOR", ""),
        ("제함기 푸셔 실린더 센서 교체", "SENSOR", ""),
        ("인피드 게이트 작동불량 솔밸브교체", "SOLENOID", ""),
        ("순간 정전 발생으로 냉동반 냉동기 다운", "POWER", ""),
        (
            "일반라인 b-12 푸셔실린더 고장으로 교체 및 톰슨 베어링 교체",
            "CYLINDER",
            "multiple_faults",
        ),
        ("봉함기 롤러부 파손", "ROLLER", ""),
        ("센서 이상 없음 모터 트립", "MOTOR", ""),
        ("씰러 온도 이상", "SEAL_TEMP", ""),
        ("실링 불량", "SEALING", ""),
        ("압축 공기 호스 이탈", "HOSE", ""),
        ("로드리스 실린더 파손/교체", "CYLINDER", ""),
        ("트레이 체인 메인, 보조 스프라켓에서 이탈", "CHAIN", ""),
        ("제대기 9번 후크 교", "GRIPPER", ""),
        ("작업자가 블레이드 제낌으로 어퍼 끼임 발생", "OPERATOR", ""),
        ("쿠키 막힘", "CLOG", ""),
    ],
)
def test_classification_examples(classify, value, expected, review_code):
    result = classify(value)
    assert result["status"] == K["review" if review_code else "auto"], result
    assert result["review_code"] == review_code
    assert rule_id(result) == expected, result
    assert result["classification_reason"]
    assert result["candidate_evidence"]


def test_resolved_conflicts_record_the_reason(classify):
    result = classify("인피드 게이트 작동불량 솔밸브교체")
    assert f"{K['auto_resolved']}: 교체 부품 우선" in result["evidence"]
    assert "PUSHER" in result["candidates"] and "SOLENOID" in result["candidates"]


def test_two_listed_parts_stay_under_review(classify):
    result = classify("4번 가이드 및 후크 조정")
    assert result["status"] == K["review"]
    assert "GUIDE" in result["candidates"] and "GRIPPER" in result["candidates"]


def test_mes_part_code_selects_a_representative_without_hiding_independent_faults(classify):
    assert classify("모터 이상 / 실린더 이상")["status"] == K["review"]
    chosen = classify("모터 이상 / 실린더 이상", "공압파트")
    assert rule_id(chosen) == "CYLINDER" and "MES 소분류 일치" in chosen["evidence"]
    assert chosen["status"] == K["review"]
    assert chosen["review_code"] == "multiple_faults"
    assert "score_margin" not in chosen


def test_unknown_text_is_never_guessed(classify):
    assert classify("unique unknown problem 92838475")["status"] == K["rule_unmatched"]
    assert classify("")["status"] == K["rule_unmatched"]


def test_clause_split_keeps_decimals_and_codes():
    assert clauses("1.3.5번 후크 교체. x-ray 검출기 / 에러") == [
        "1.3.5번후크교체",
        "x-ray검출기",
        "에러",
    ]


def mes_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "MES"
    ws.append(
        [
            "작업 일자",
            "라인",
            "라인명",
            "설비",
            "설비명",
            "비가동 시작 시간",
            "비가동 종료 시간",
            "비가동 시간(분)",
            "비가동 유형",
            "비가동 코드(대)",
            "비가동 코드(중)",
            "비가동 코드(소)",
            "비고",
        ]
    )
    ws.append(
        [
            "2026-03-02",
            "L1",
            "라인1",
            "EQ1",
            "1P M/Y 카운터",
            "2026-03-02 08:00:00",
            "2026-03-02 08:10:00",
            10,
            "고장",
            "설비고장",
            "1P M/Y SERAC #1 컨베이어",
            "기계파트",
            "컨베이어 체인 이탈",
        ]
    )
    ws.append(
        [
            "2026-03-03",
            "L1",
            "라인1",
            "EQ1",
            "1P M/Y 카운터",
            "2026-03-03 09:00:00",
            "2026-03-03 09:05:00",
            5,
            "고장",
            "유틸리티 고장(이상)",
            None,
            None,
            "센서 교체",
        ]
    )
    ws.append(
        [
            "2026-03-04",
            "L1",
            "라인1",
            "EQ1",
            "1P M/Y 카운터",
            "2026-03-04 10:00:00",
            "2026-03-04 10:30:00",
            30,
            "계획운휴",
            "생산종료",
            None,
            None,
            None,
        ]
    )
    wb.save(path)
    return path


def test_mes_target_pattern_and_review_policy(store, tmp_path):
    path = mes_workbook(tmp_path / "mes.xlsx")
    default = analyze_file(store, path)
    assert default.loaded.profile == "mes_downtime_v1"
    targets = default.selected.set_index("source_row")["target"]
    assert targets[2] == "1P M/Y SERAC #1 컨베이어"  # every plant prefix, not only '2P I/C'
    assert targets[3] == K["target_missing"]
    assert default.metrics["missing_target_rows"] == 1
    # The named sensor and its completed action are known; the absent phenomenon
    # is kept as missing data instead of requiring the worker to invent it.
    assert default.metrics["review_rows"] == 0
    assert default.metrics["partial_rows"] == 1
    assert len(default.tables["review"]) == 0
    partial = default.selected.set_index("source_row").loc[3]
    assert partial["status"] == K["partial"]
    assert partial["classification_mode"] == "single"
    assert partial["middle"] == "센서(종류 미상)" and partial["minor"] == "현상 미기재"
    assert partial["classification_missing_fields"] == "상세설비·모듈, 고장 현상"
    assert partial["repair_actions"] == "교체"
    assert "교체" not in set(default.selected["minor"])
    assert "교체" in set(default.selected["repair_actions"])
    assert K["target_missing"] in default.selected.set_index("source_row").loc[3, "issues"]
    by_target = analyze_file(store, path, AnalysisOptions(equipment_basis="target"))
    assert by_target.metrics["review_rows"] == 1
    assert by_target.metrics["partial_rows"] == 1
    assert by_target.tables["review"].iloc[0]["event_id"] == partial["event_id"]
    assert "고장대상" in by_target.tables["review"].iloc[0]["review_reason"]


@pytest.mark.parametrize(
    "issue,reason,action",
    [
        ("time_missing", "정지시간이 없어", "확정 정지시간(분)"),
        ("date_invalid", "작업일자가 없거나", "YYYY-MM-DD"),
        ("time_negative", "종료시각이 시작시각보다", "시작·종료시각"),
        ("target_missing", "고장대상 설비가", "고장대상 설비를 입력"),
    ],
)
def test_review_guidance_explains_each_issue(issue, reason, action):
    record = {
        "status": K["auto"],
        "issues": K[issue],
        "minutes": None if issue == "time_missing" else 10.0,
    }
    got_reason, got_action, effect = guidance(record)
    assert reason in got_reason and action in got_action
    assert ("미집계" in effect) == (issue == "time_missing")
    assert (
        guidance({"status": K["auto"], "issues": K["target_missing"], "minutes": 5.0}, False)[2]
        == "정상"
    )


def test_review_guidance_for_classification_status():
    for status in (K["code_missing"], K["rule_unmatched"]):
        reason, _, effect = guidance({"status": status, "issues": "", "minutes": 1.0})
        assert reason.startswith(status) and "미확정 상태에서도 출력" in effect
    assert (
        "후보는 확정 부품으로 합산하지 않습니다"
        in guidance({"status": K["review"], "issues": "", "minutes": 1.0})[2]
    )


def missing_time_event(result):
    row = result.selected.loc[result.selected["minutes"].isna()].iloc[0]
    return row["event_id"]


def test_corrected_date_and_minutes_are_applied(store, input_file):
    before = analyze_file(store, input_file)
    event = missing_time_event(before)
    store.update_override(event, {"minutes": "12", "work_date": "2026-01-05"})
    after = analyze_file(store, input_file)
    row = after.selected.loc[after.selected["event_id"].eq(event)].iloc[0]
    assert row["minutes"] == 12 and row["duration_source"] == K["manual"]
    assert row["date"] == pd.Timestamp("2026-01-05")
    assert K["time_missing"] not in row["issues"]
    assert after.metrics["total_minutes"] == before.metrics["total_minutes"] + 12


def test_override_fields_can_be_removed(store, input_file):
    event = missing_time_event(analyze_file(store, input_file))
    store.update_override(event, {"minutes": "12", "product": "P"})
    assert store.override(event)["minutes"] == "12"
    store.update_override(event, {"minutes": None})
    assert "minutes" not in store.override(event) and store.override(event)["product"] == "P"
    store.clear_override(event)
    assert event not in store.read("manual_overrides.json")


def test_correction_saves_only_changed_fields():
    record = {
        "major": "기계",
        "detail_equipment": "상세설비 미상",
        "middle": "벨트·풀리",
        "minor": "벨트·풀리 끊어짐·마모",
        "target": K["target_missing"],
        "product": K["missing"],
        "date": pd.Timestamp("2026-01-01"),
        "minutes": None,
    }
    initial = initial_values(record, {})
    assert initial["target"] == "" and initial["minutes"] == ""
    values = {**initial, "minutes": "30"}
    assert correction_patch(initial, values, {}, confirm=False) == {"minutes": "30"}
    confirmed = correction_patch(initial, values, {}, confirm=True)
    assert confirmed["minor"] == "벨트·풀리 끊어짐·마모" and confirmed["minutes"] == "30"
    changed = correction_patch(initial, {**initial, "minor": "체인 끊어짐"}, {}, confirm=False)
    assert changed == {
        "major": "기계",
        "detail_equipment": "상세설비 미상",
        "middle": "벨트·풀리",
        "minor": "체인 끊어짐",
    }


def test_correction_can_remove_saved_values():
    existing = {"major": "A", "middle": "B", "minor": "C", "minutes": "30"}
    record = {"major": "A", "middle": "B", "minor": "C", "minutes": 30.0}
    initial = initial_values(record, existing)
    assert initial["minutes"] == "30"
    cleared = {**initial, "major": "", "middle": "", "minor": "", "minutes": ""}
    assert correction_patch(initial, cleared, existing, confirm=False) == {
        "major": None,
        "middle": None,
        "minor": None,
        "minutes": None,
    }
    assert validate({"major": "A", "middle": "", "minor": ""})
    assert validate({"minutes": "-1"}) and validate({"work_date": "not a date"})
    assert validate({"minutes": "15.5", "work_date": "2026-01-02"}) is None


def legacy_profile(tmp_path):
    root = tmp_path / "legacy"
    (root / "config").mkdir(parents=True)
    for item in (FIXTURES / "v140_config").iterdir():
        shutil.copy2(item, root / "config" / item.name)
    return root


def test_untouched_v140_defaults_follow_the_new_release(tmp_path):
    root = legacy_profile(tmp_path)
    store = ConfigStore(root)
    assert store.merge_summary["rules"]["added"] > 0 and store.merge_summary["rules"]["removed"] > 0
    assert describe(store.merge_summary).startswith("기본 설정 업데이트")
    bundled = {r["id"]: r for r in read_rules(BUNDLE / "classification_config.xlsx")}
    merged = {r["id"]: r for r in read_rules(root / "config" / "classification_config.xlsx")}
    assert merged == bundled
    config = store.load()
    assert config["normalization"]["replacements"]["실러"] == "씰러"
    assert (
        config["settings"]["equipment_prefix_pattern"]
        == json.loads((BUNDLE / "settings.json").read_text(encoding="utf-8"))[
            "equipment_prefix_pattern"
        ]
    )
    assert "classifier" in config["settings"]
    backups = list((root / "config" / "backup").iterdir())
    assert len(backups) == 1 and (backups[0] / "classification_config.xlsx").exists()
    assert ConfigStore(root).merge_summary == {}  # idempotent


def test_user_edits_survive_the_merge(tmp_path):
    root = legacy_profile(tmp_path)
    from core.classifier import write_rules

    rules = read_rules(root / "config" / "classification_config.xlsx")
    for rule in rules:
        if rule["id"] == "SENSOR":
            rule["priority"] = 77
        if rule["id"] == "SEAL_TEMP":
            rule["priority"] = 99  # edited, still carries the old typo
    rules = [r for r in rules if r["id"] != "TANK"]  # the user deleted a default rule
    rules.append(
        dict(
            id="MY_RULE",
            enabled=1,
            priority=50,
            major="기계",
            middle="사용자",
            minor="사용자 규칙",
            context="특수부품",
            symptom="이상",
            exclude="",
            role="component",
        )
    )
    write_rules(root / "config" / "classification_config.xlsx", rules)
    normalization = json.loads(
        (root / "config" / "normalization.json").read_text(encoding="utf-8-sig")
    )
    normalization["replacements"]["모타"] = "모우터"
    (root / "config" / "normalization.json").write_text(
        json.dumps(normalization, ensure_ascii=False), encoding="utf-8"
    )
    store = ConfigStore(root)
    merged = {r["id"]: r for r in read_rules(root / "config" / "classification_config.xlsx")}
    assert merged["SENSOR"]["priority"] == 77
    assert merged["SEAL_TEMP"]["priority"] == 99
    assert "TANK" not in merged and "MY_RULE" in merged
    # These edited symptom paths remain inspectable, but do not enter the new
    # component-type menu. Manual event confirmations use a separate store.
    assert all(not merged[key]["enabled"] for key in ("SENSOR", "SEAL_TEMP", "MY_RULE"))
    assert merged["MY_RULE"]["context"] == "특수부품"
    from core.classification_catalog import catalog_categories

    assert catalog_categories(merged.values()) == catalog_categories(
        read_rules(BUNDLE / "classification_config.xlsx")
    )
    assert store.load()["normalization"]["replacements"]["모타"] == "모우터"


def test_fresh_profile_records_catalog_installation_once(tmp_path, approved_catalog_paths):
    from core.classification_catalog import catalog_categories

    root = tmp_path / "fresh"
    first = ConfigStore(root)
    assert first.merge_summary == {"classification_catalog": {"updated": 1, "kept": 0}}
    assert set(catalog_categories(first.load()["rules"])) == approved_catalog_paths | {
        ("전기·제어", "제어기·I/O·통신", "PLC 카드"),
        ("온도·냉각", "냉동·냉각장치", "석션 제어밸브"),
        ("온도·냉각", "냉동·냉각장치", "열풍건조기(세부 부품 미상)"),
        ("온도·냉각", "냉동·냉각장치", "냉각수 공급부(세부 부품 미상)"),
        ("공압·진공", "진공·석션", "석션기·블로워(세부 부품 미상)"),
        ("기계", "충진·분사기구", "익스트랙터 바(세부 부품 미상)"),
    }
    assert ConfigStore(root).merge_summary == {}


def test_bundled_texts_have_no_encoding_typos():
    from core import i18n

    assert not any("걁" in value for value in i18n.K.values())
    payload = json.dumps(read_rules(BUNDLE / "classification_config.xlsx"), ensure_ascii=False)
    payload += (BUNDLE / "normalization.json").read_text(encoding="utf-8")
    payload += (BUNDLE / "equipment_families.json").read_text(encoding="utf-8")
    assert "씌" not in payload and "씬" not in payload


def test_event_id_formula_is_unchanged(store, input_file):
    loaded = load_excel(input_file, store.load()["column_mapping"])
    raw = loaded.frame.to_dict("records")[0]
    # The v1.4.0 formula; saved corrections are keyed by it.
    legacy = [
        text(raw.get(loaded.mapping.get(k, "")))
        for k in (
            "line_id",
            "line_name",
            "equipment_id",
            "equipment_name",
            "start",
            "end",
            "work_date",
            "description",
            "kind",
            "code_big",
            "code_mid",
            "code_small",
            "duration",
            "product_name",
        )
    ]
    assert (
        event_id_for(raw, loaded.mapping)
        == hashlib.sha256(json.dumps(legacy, ensure_ascii=False).encode()).hexdigest()
    )
    assert len(EVENT_FIELDS) == 14


def test_saved_mapping_is_reused_and_corrections_follow(store, input_file):
    config = store.load()
    loaded = load_excel(input_file, config["column_mapping"])
    assert loaded.mapping["description"] is not None
    changed = {**loaded.mapping, "product_name": None}
    store.update_override(event_ids(loaded, loaded.mapping)[0], {"product": "Kept"})
    moved = store.rekey_overrides(
        dict(zip(event_ids(loaded, loaded.mapping), event_ids(loaded, changed)))
    )
    store.save_mapping(loaded.headers, changed)
    assert moved == 1
    reloaded = load_excel(input_file, config["column_mapping"], mapping_lookup=store.saved_mapping)
    assert reloaded.mapping["product_name"] is None
    result = run_analysis(reloaded, store.load(), AnalysisOptions())
    assert "Kept" in result.selected["product"].tolist()


def legacy_reader_error(path):
    """What a v1.4.0 program does: read the 'rules' sheet by name and reject a bad 'enabled' value."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["rules"] if "rules" in wb.sheetnames else wb.active
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    header = [str(x or "").strip() for x in rows[0]]
    for values in rows[1:]:
        row = {k: "" if v is None else str(v).strip() for k, v in zip(header, values)}
        if any(row.values()) and row["enabled"].casefold() not in (
            "0",
            "1",
            "true",
            "false",
            "yes",
            "no",
        ):
            return f"Rule {row['id']}: enabled는 0 또는 1입니다."
    return None


def test_saved_rules_stop_older_programs(tmp_path):
    import openpyxl

    from core.classifier import LEGACY_GUARD, RULES_SHEET, write_rules
    from core.rules import MIN_APP_VERSION

    path = tmp_path / "rules.xlsx"
    rules = read_rules(BUNDLE / "classification_config.xlsx")
    write_rules(path, rules)
    assert read_rules(path) == rules
    wb = openpyxl.load_workbook(path)
    assert (
        wb.active.title == RULES_SHEET
        and wb["rules"].sheet_state == "hidden"
        and wb["meta"].sheet_state == "hidden"
    )
    error = legacy_reader_error(path)
    assert error and LEGACY_GUARD in error and f"v{MIN_APP_VERSION} 이상" in error
    assert LEGACY_GUARD in legacy_reader_error(BUNDLE / "classification_config.xlsx")


def test_newer_rules_schema_is_refused(tmp_path):
    import openpyxl

    from core.classifier import write_rules
    from core.models import UserError
    from core.rules import RULES_SCHEMA

    path = tmp_path / "rules.xlsx"
    write_rules(path, read_rules(BUNDLE / "classification_config.xlsx"))
    wb = openpyxl.load_workbook(path)
    wb["meta"]["B2"] = RULES_SCHEMA + 1
    wb["meta"]["B3"] = "9.0.0"
    wb.save(path)
    with pytest.raises(UserError, match="v9.0.0 이상"):
        read_rules(path)


def test_old_format_profile_is_upgraded_once(tmp_path, input_file):
    from core.classifier import RULE_COLUMNS, needs_format_upgrade

    root = tmp_path / "profile"
    ConfigStore(root)
    path = root / "config" / "classification_config.xlsx"
    rules = read_rules(path)
    # v1.5.0 rules saved the way the first v1.5.0 build did: one plain 'rules' sheet.
    wb = Workbook()
    ws = wb.active
    ws.title = "rules"
    ws.append(RULE_COLUMNS)
    for rule in rules:
        ws.append([int(rule[k]) if k == "enabled" else rule[k] for k in RULE_COLUMNS])
    wb.save(path)
    assert needs_format_upgrade(path) and legacy_reader_error(path) is None
    store = ConfigStore(root)
    assert store.merge_summary["rules"]["format_upgraded"] == 1
    assert "구버전 실행 차단" in describe(store.merge_summary)
    assert not needs_format_upgrade(path) and read_rules(path) == rules
    assert legacy_reader_error(path)
    assert ConfigStore(root).merge_summary == {}
    assert analyze_file(ConfigStore(root), input_file).metrics["selected_rows"] == 4


def test_reports_default_to_output_folder_next_to_program(monkeypatch, tmp_path):
    from core.config import app_root, output_root

    monkeypatch.delenv("EFA_OUTPUT_DIR", raising=False)
    assert output_root() == app_root() / "output"
    assert (app_root() / "output" / "README.txt").exists()
    ConfigStore(tmp_path / "profile")
    assert not (
        tmp_path / "profile" / "output"
    ).exists()  # no longer created in the user data folder


def test_read_only_output_folder_falls_back_to_user_data(monkeypatch, tmp_path):
    from core.config import output_root

    blocked = tmp_path / "not_a_folder"
    blocked.write_text("a file, so no folder can be created here")
    monkeypatch.setenv("EFA_OUTPUT_DIR", str(blocked))
    monkeypatch.setenv("EFA_DATA_DIR", str(tmp_path / "profile"))
    assert output_root() == (tmp_path / "profile" / "output").resolve()
    assert (tmp_path / "profile" / "output").is_dir()
