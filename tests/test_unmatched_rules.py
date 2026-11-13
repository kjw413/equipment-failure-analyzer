"""Rule supplements for records that previously matched no rule (2026-10-20 review)."""

import json

import pytest

from core.classifier import CODE_PART_REASON, NOPART_REASON, RuleClassifier
from core.config import resource_root
from core.i18n import K
from core.parsing import prepare_text
from core.rules import ROLES, read_rules, write_rules

BUNDLE = resource_root() / "config"
CONTROLLER = ("전기·제어", "제어기·I/O·통신", "제어기(종류 미상)")


@pytest.fixture(scope="module")
def classify():
    settings = json.loads((BUNDLE / "settings.json").read_text(encoding="utf-8"))["classifier"]
    normalization = json.loads((BUNDLE / "normalization.json").read_text(encoding="utf-8"))
    engine = RuleClassifier(read_rules(BUNDLE / "classification_config.xlsx"), settings)

    def run(text, code=""):
        return engine.classify(
            prepare_text(text, normalization), code, prepare_text(code, normalization)
        )

    return run


def path(result):
    return tuple(result[key] for key in ("major", "middle", "minor"))


@pytest.mark.parametrize(
    "text, expected",
    [
        ("부스터 펌프 베어링 소손", ("유체·배관", "펌프", "부스터펌프")),
        ("체인 뒤집어 짐", ("기계", "체인·링크", "체인(종류 미상)")),
        (
            "리드 씰링 전원 온오프 반복으로 전기반 외뢰 조치후 생산",
            ("기계", "씰링기구", "리드씰러"),
        ),
        ("wago29 발생으로 pc전원 종료", ("전기·제어", "제어기·I/O·통신", "컴퓨터·PC")),
    ],
)
def test_named_parts_now_match_their_rules(classify, text, expected):
    result = classify(text)
    assert result["status"] == K["auto"], result
    assert path(result) == expected


@pytest.mark.parametrize(
    "text, code, expected",
    [
        ("이탈로 인해 정비및교체", "세척기 진입 전 Con'V", ("기계", "컨베어", "컨베어(종류 미상)")),
        (
            "18번 병무게 감지 이상으로 3kg영점조정및 calibraition 실시",
            "로드셀",
            ("전기·제어", "계측·계량기", "로드셀"),
        ),
    ],
)
def test_part_less_description_uses_the_mes_part_code(classify, text, code, expected):
    result = classify(text, code)
    assert result["status"] == K["auto"], result
    assert path(result) == expected
    assert CODE_PART_REASON.format(code=code) in result["classification_reason"]


def test_the_description_part_wins_over_the_mes_part_code(classify):
    result = classify("센서 교체", "로드셀")
    assert result["minor"] == "센서(종류 미상)"
    assert "비가동코드(소)" not in result["classification_reason"]
    # An area code such as '구동파트' names no part.
    assert classify("작업 대기", "구동파트")["status"] == K["rule_unmatched"]


@pytest.mark.parametrize(
    "text, minor",
    [
        ("쿠키 막힘", "제품 걸림·막힘"),
        ("qft 제품 걸림", "제품 걸림·막힘"),
        ("배출컨베이어에서 제품 걸림 청소 후 생산", "제품 걸림·막힘"),
        ("멀티팩 떨어짐으로 설비 센터틀어짐 정비", "제품 낙하"),
        ("스틱불량으로 스크류 쪽에서 깨져서 올라갑니다", "자재 불량"),
    ],
)
def test_process_types_apply_only_without_any_part(classify, text, minor):
    result = classify(text)
    assert result["status"] == K["auto"], result
    assert path(result) == ("공정·운전", "제품·자재", minor)
    assert NOPART_REASON in result["classification_reason"]


@pytest.mark.parametrize(
    "text",
    [
        "WAGO 31발생 세니테이션",
        "WAGO 29 에러 발생. 재부팅및. 세니테이션",
        "와고#29에러",
        "wago31 발생 전기반 점검",
        "4호기 작업중 통신이상 발생되어 작업 안됨 - 전기반에서 점검중 전원만 ON/OFF 함.",
    ],
)
def test_part_less_controller_errors_use_the_unspecified_controller(classify, text):
    result = classify(text)
    assert result["status"] == K["auto"], result
    assert path(result) == CONTROLLER


@pytest.mark.parametrize(
    "text, minor",
    [
        ("회전실린더 제품걸림 조치후 생산", "회전실린더"),
        ("wago31 발생 브러쉬 청소 및 wago3모듈카드 교체", "제어모듈·카드"),
    ],
)
def test_a_named_part_keeps_precedence_over_part_less_rules(classify, text, minor):
    assert classify(text)["minor"] == minor


@pytest.mark.parametrize(
    "text",
    [
        # Site terms held until production-team criteria exist.
        "스틱 원점타 이밍트러짐",
        "스틱 트러블 발생 타이밍 조정",
        "주입구압력낮음 오류 / 재가동 후 오류 재발생 / 제상 후 생산 시작",
    ],
)
def test_held_terms_remain_unmatched(classify, text):
    assert classify(text)["status"] == K["rule_unmatched"]


def test_tc_is_thermocouple_only_in_explicit_heating_context(classify):
    result = classify("히팅박스 포밍상부 tc교체")
    assert result["status"] == K["auto"]
    assert result["minor"] == "열전대(써머커플)"
    assert classify("tc교체")["status"] == K["rule_unmatched"]


def test_nopart_rules_round_trip_in_the_current_rules_format(tmp_path):
    assert "nopart" in ROLES
    rules = read_rules(BUNDLE / "classification_config.xlsx")
    assert sum(rule["role"] == "nopart" for rule in rules) == 4
    copy = tmp_path / "rules.xlsx"
    write_rules(copy, rules)
    assert read_rules(copy) == rules
