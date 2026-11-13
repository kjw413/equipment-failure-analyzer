"""Scope the approved spelling, module and observed-versus-guessed feedback."""

import json
from pathlib import Path

import pytest

from core.classification_candidates import parse_candidates
from core.failure_classification import FaultClassifier
from core.fault_components import CATEGORY_FIELDS, parse_components
from core.i18n import K
from core.parsing import prepare_text
from tools.make_rules import build_rules

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def classify():
    normalization = json.loads((ROOT / "config/normalization.json").read_text("utf-8"))
    engine = FaultClassifier(build_rules())
    return lambda text, mid="": engine.classify(
        prepare_text(text, normalization), equipment_context=mid
    )


@pytest.mark.parametrize(
    "source,mid,expected",
    [
        (
            "63번 배칭탱크 원유이송펌프 가동시 차단기 떨어짐-전기 단자함 교",
            "배칭탱크",
            ("전기·제어", "펌프", "차단기", "보호장치 동작"),
        ),
        (
            "필러 구동축 작동부 부싱 마모 및 감속기 체인 끈어짐 정비",
            "필러",
            ("기계", "필러·충진기", "부싱", "마모"),
        ),
        (
            "열풍건조기에 병걸림.",
            "필러",
            ("온도·냉각", "열풍건조기", "제품·자재", "막힘·걸림"),
        ),
        (
            "보드에러로 인한 운휴/스패어 없음/스패어확보 요청하였으나 해결안됨",
            "필로우 포장기",
            ("전기·제어", "필름·필로우 포장기", "제어기판·카드(종류 미상)", "고장·이상"),
        ),
        (
            "크레이트 세척장 컨베어 레일 이찰/조치후 가동",
            "컨베어",
            ("기계", "컨베어", "레일(종류 미상)", "이탈·풀림"),
        ),
        (
            "아웃밸브 씽크탑(V50) 고장으로 A급으로 교체-전기반 보유",
            "믹스저장탱크",
            ("전기·제어", "밸브", "밸브 제어헤드", "고장·이상"),
        ),
    ],
)
def test_feedback_selects_only_stated_axes(classify, source, mid, expected):
    result = classify(source, mid)
    assert tuple(result[key] for key in CATEGORY_FIELDS) == expected
    assert result["status"] == K["auto"]
    assert len(parse_components(result["component_details"])) == 1


def test_first_listed_fault_retains_later_observed_fault_and_action(classify):
    row = classify("필러 부싱 마모 및 감속기 체인 끈어짐 정비")
    candidates = parse_candidates(row["classification_candidates"])
    assert (row["middle"], row["minor"]) == ("부싱", "마모")
    assert any(c["middle"] == "체인(종류 미상)" and c["minor"] == "손상·파손" for c in candidates)
    assert "수리·정비" in row["repair_actions"]


def test_certain_first_fault_keeps_later_suspicion_as_a_candidate(classify):
    row = classify("설비 퓨즈이상 (오일펌프 쇼트의심)", "필러")
    assert row["status"] == K["auto"] and row["middle"] == "퓨즈"
    candidates = parse_candidates(row["classification_candidates"])
    assert len(candidates) == 2
    assert "의심·추정 후보" in candidates[1]["reason"]
    assert "후보로만 보존" in row["classification_reason"]


@pytest.mark.parametrize(
    "source",
    [
        "퓨즈 이상 의심",
        "퓨즈 이상 오일펌프 쇼트 의심",
        "모터 소손 의심 / 퓨즈 이상",
        "퓨즈 이상 또는 모터 소손",
    ],
)
def test_suspected_or_alternative_first_fault_still_requires_review(classify, source):
    row = classify(source, "필러")
    assert row["status"] not in (K["auto"], K["partial"])
    assert not parse_components(row["component_details"])


@pytest.mark.parametrize(
    "source",
    [
        "메인",
        "몰드 상판위로 브라인 over flow현상 발생/브라인 교체",
        "스팀콘트롤밸브 포지셔너 에어라인(8미리) 교",
    ],
)
def test_accepted_unresolved_feedback_stays_unresolved(classify, source):
    row = classify(source)
    assert row["status"] not in (K["auto"], K["partial"])
    assert not parse_components(row["component_details"])


@pytest.mark.parametrize(
    "source", ["프리져 점도 헌팅", "프리저 점도 불량", "freezer/프리져 점도 헌팅"]
)
def test_viscosity_is_a_process_condition_without_an_invented_failed_sensor(classify, source):
    row = classify(source, "FREEZER")
    assert row["status"] == K["review"]
    assert not parse_components(row["component_details"])
    candidates = parse_candidates(row["classification_candidates"])
    assert any(c["minor"] == "점도이상" for c in candidates)
    assert all(c["middle"] == "세부 부품 미기재" for c in candidates)


@pytest.mark.parametrize("mid", ["필로우 포장기", "컨베어", "X-RAY 검사기", ""])
def test_bare_board_never_implies_mainboard(classify, mid):
    row = classify("보드 에러", mid)
    assert row["middle"] == "제어기판·카드(종류 미상)"


def test_explicit_board_types_are_not_lost(classify):
    assert classify("메인보드 에러", "필로우 포장기")["middle"] == "메인보드"
    assert classify("PCI보드 에러", "필로우 포장기")["middle"] == "제어기판·카드(종류 미상)"
    assert classify("PLC 카드 에러", "필로우 포장기")["middle"] == "PLC 카드"
    for text in ("유보드 교체", "서보 드라이버 교체"):
        assert classify(text)["middle"] != "제어기판·카드(종류 미상)"


def test_new_modules_do_not_invent_internal_parts(classify):
    suction = classify("상과자 석션 불량/브로워 분해 점검,윤활")
    assert suction["status"] == K["partial"]
    assert suction["detail_equipment"] == "석션기·블로워"
    assert suction["middle"] == "세부 부품 미기재"
    assert "청소·급유" in suction["repair_actions"]
    extractor = classify("엑스트로바 걸리며 센타 틀어짐", "필러")
    assert extractor["status"] == K["partial"]
    assert extractor["detail_equipment"] == "익스트랙터 바"
    assert extractor["middle"] == "세부 부품 미기재"
    assert extractor["minor"] == "막힘·걸림"


def test_suction_subparts_keep_the_stated_parent_machine(classify):
    row = classify("로봇 석션패드 교체")
    assert row["detail_equipment"] == "로봇"
    assert row["middle"] == "진공컵·석션패드"
    cylinder = classify("석션실린더 작동불량", "포장기")
    assert cylinder["detail_equipment"] == "포장기"
    assert cylinder["middle"] == "실린더(종류 미상)"


def test_checking_for_an_error_does_not_state_that_error(classify):
    row = classify("엑스트로바 과부하 이상유무 확인 및 수동조작")
    assert row["minor"] != "고장·이상"


def test_normalization_preserves_raw_and_scope():
    normalization = json.loads((ROOT / "config/normalization.json").read_text("utf-8"))
    raw = "열풍건조기에 병걸림."
    assert prepare_text(raw, normalization) == "열풍건조기 병 걸림."
    assert raw == "열풍건조기에 병걸림."
    assert prepare_text("이찰수 점검", normalization) == "이찰수 점검"
