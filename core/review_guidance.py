"""Explain each review flag and the specific safe correction route."""

from core.i18n import UNMATCHED, K

REVIEW_ISSUES = (
    "date_invalid",
    "time_invalid",
    "time_missing",
    "time_negative",
    "time_diff",
    "target_missing",
)


def review_issues(target_review: bool = True) -> tuple[str, ...]:
    """Issue keys that put a record under review for the current equipment basis."""
    return (
        REVIEW_ISSUES if target_review else tuple(k for k in REVIEW_ISSUES if k != "target_missing")
    )


def guidance(record, target_review: bool = True):
    explanations = []
    actions = []
    active = review_issues(target_review)
    status = record.get("status", "")
    if status == K["partial"]:
        explanations.append(
            "원문에서 확인된 항목은 자동 분류했습니다. 미기재 항목: "
            + str(record.get("classification_missing_fields", ""))
        )
        actions.append(
            "추가 근거가 확보되면 미기재 항목만 보완할 수 있습니다. 기록에 없는 현상을 추측해 입력할 필요는 없습니다."
        )
    issues = str(record.get("issues", "") or "")
    if status == K["code_missing"]:
        explanations.append(
            "비가동코드 미기입: 원본의 비가동코드(중·소)가 비어 있고 고장 설명과 일치하는 분류 규칙도 없습니다."
        )
        actions.append(
            "원본의 비가동코드 입력을 확인하고, 행 수정에서 대분류·상세설비·세부 부품·소분류를 확정하거나 분류 규칙을 보완하세요."
        )
    elif status == K["rule_unmatched"]:
        explanations.append(
            "규칙 미일치: 비가동코드는 입력됐지만 고장 설명과 일치하는 분류 규칙이 없습니다."
        )
        actions.append(
            "분류 규칙을 보완하거나 행 수정에서 대분류·상세설비·세부 부품·소분류를 확정하세요."
        )
    if status == K["review"]:
        decision_reason = str(record.get("classification_reason", "") or "")
        explanations.append(
            decision_reason or "복수 분류 충돌: 서로 다른 분류의 규칙이 동시에 일치합니다."
        )
        if K["symptom_missing"] in issues:
            actions.append(
                "실제 고장 현상을 확인한 뒤 최종 분류를 선택하세요. 교체·점검·조정은 별도 조치 내역에 저장하며 고장 현상을 추정하지 않습니다."
            )
        elif K["multiple_symptoms"] in issues:
            actions.append(
                "같은 부품에 여러 증상 후보가 있습니다. 기록의 대표 고장 증상 하나를 선택하세요."
            )
        elif K["alternative_types"] in issues:
            actions.append(
                "추천순 후보의 근거와 원문을 비교하여 이 고장이력의 최종 분류 하나를 선택하세요."
            )
        elif K["multiple_faults"] in issues:
            actions.append(
                "여러 부품·고장이 함께 적혔습니다. 추천순 후보와 원문을 확인해 이 이력을 대표하는 최종 분류 하나를 선택하세요."
            )
        elif K.get("uncertain_fault", "고장 추정") in issues:
            actions.append(
                "의심·추정된 부품과 증상을 실제 점검 결과로 확인한 뒤 분류를 확정하세요."
            )
        else:
            actions.append(
                "일치한 분류 규칙·고장 근거와 원본 설명을 비교한 뒤 대분류·상세설비·세부 부품·소분류를 확정하세요."
            )
    checks = [
        (
            "target_missing",
            "고장대상 설비가 확인되지 않습니다.",
            "행 수정에서 고장대상 설비를 입력하세요. 보고 기준이 등록설비인 경우 집계 설비명은 바뀌지 않을 수 있습니다.",
        ),
        (
            "date_invalid",
            "작업일자가 없거나 날짜로 해석할 수 없습니다.",
            "원본 Excel 날짜를 수정한 뒤 재분석하거나 행 수정에서 작업일자를 YYYY-MM-DD 형식으로 입력하세요.",
        ),
        (
            "time_invalid",
            "원본 정지시간 형식이 올바르지 않습니다.",
            "원본 Excel 정지시간 형식을 수정하거나 행 수정에서 확정 정지시간(분)을 입력하세요.",
        ),
        (
            "time_missing",
            "정지시간이 없어 시간 집계에서 빠집니다.",
            "원본 Excel 정지시간을 입력하거나 행 수정에서 확정 정지시간(분)을 입력하세요.",
        ),
        (
            "time_negative",
            "종료시각이 시작시각보다 이릅니다.",
            "원본 시작·종료시각을 확인하세요. 자정 경과라면 옵션을 확인하고 재분석하세요.",
        ),
        (
            "time_diff",
            "기록 정지시간과 시작·종료 차이가 허용오차를 넘습니다.",
            "원본 기록을 대조하세요. 확정 값이 있다면 행 수정에서 확정 정지시간(분)을 입력하세요.",
        ),
    ]
    for key, reason, action in checks:
        if key in active and K[key] in issues:
            explanations.append(reason)
            actions.append(action)
    if not explanations:
        return "검토 사유 없음", "추가 수정 없이 집계됩니다.", "정상"
    # A known classification is included as-is; review is not synonymous with exclusion.
    if status in UNMATCHED:
        effect = "전체 이력·정지시간에는 한 건으로 포함됩니다. 미확정 상태에서도 출력하고 검토품질 시트에 정답을 적어 규칙 보완 자료로 사용할 수 있습니다."
    elif status == K["review"]:
        effect = "전체 이력·정지시간에는 한 건으로 포함되며 후보는 확정 부품으로 합산하지 않습니다. 검토 중에도 출력할 수 있으며 검토품질 시트에 정답을 적을 수 있습니다."
    elif status == K["partial"]:
        effect = "확인된 항목과 미기재 항목을 구분하여 전체 이력·정지시간에 한 건으로 포함합니다. 미기재 부품은 실제 부품 건수에 포함하지 않습니다."
    else:
        effect = "기본 건수에 포함될 수 있으나 시간·날짜·설비별 집계의 정확도에 영향이 있습니다."
    if record.get("minutes") is None or str(record.get("minutes")).lower() == "nan":
        effect += " 정지시간 미집계 가능."
    return " / ".join(explanations), " / ".join(dict.fromkeys(actions)), effect
