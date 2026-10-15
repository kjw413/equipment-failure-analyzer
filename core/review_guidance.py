"""Explain each review flag and the specific safe correction route."""
from core.i18n import K

REVIEW_ISSUES = ('date_invalid','time_invalid','time_missing','time_negative','time_diff','target_missing')

def review_issues(target_review: bool = True) -> tuple[str,...]:
    """Issue keys that put a record under review for the current equipment basis."""
    return REVIEW_ISSUES if target_review else tuple(k for k in REVIEW_ISSUES if k!='target_missing')

def guidance(record, target_review: bool = True):
    explanations=[];actions=[]
    active=review_issues(target_review)
    status=record.get('status','')
    issues=str(record.get('issues','') or '')
    if status==K['unclassified']:
        explanations.append('미분류: 고장 설명과 일치하는 표준 분류 규칙이 없습니다.')
        actions.append('행 수정에서 대·중·소분류를 확정하거나 분류 규칙을 보완하세요.')
    if status==K['review']:
        explanations.append('복수 분류 충돌: 서로 다른 분류의 규칙이 동시에 일치합니다.')
        actions.append('후보 규칙과 원본 설명을 비교한 뒤 대·중·소분류를 확정하세요.')
    checks=[
      ('target_missing','고장대상 설비가 확인되지 않습니다.','행 수정에서 고장대상 설비를 입력하세요. 보고 기준이 등록설비인 경우 집계 설비명은 바뀌지 않을 수 있습니다.'),
      ('date_invalid','작업일자가 없거나 날짜로 해석할 수 없습니다.','원본 Excel 날짜를 수정한 뒤 재분석하거나 행 수정에서 작업일자를 YYYY-MM-DD 형식으로 입력하세요.'),
      ('time_invalid','원본 정지시간 형식이 올바르지 않습니다.','원본 Excel 정지시간 형식을 수정하거나 행 수정에서 확정 정지시간(분)을 입력하세요.'),
      ('time_missing','정지시간이 없어 시간 집계에서 빠집니다.','원본 Excel 정지시간을 입력하거나 행 수정에서 확정 정지시간(분)을 입력하세요.'),
      ('time_negative','종료시각이 시작시각보다 이릅니다.','원본 시작·종료시각을 확인하세요. 자정 경과라면 옵션을 확인하고 재분석하세요.'),
      ('time_diff','기록 정지시간과 시작·종료 차이가 허용오차를 넘습니다.','원본 기록을 대조하세요. 확정 값이 있다면 행 수정에서 확정 정지시간(분)을 입력하세요.'),
    ]
    for key,reason,action in checks:
        if key in active and K[key] in issues:
            explanations.append(reason);actions.append(action)
    if not explanations:
        return '검토 사유 없음','추가 수정 없이 집계됩니다.','정상'
    # A known classification is included as-is; review is not synonymous with exclusion.
    if status==K['unclassified']:
        effect='건수·정지시간에 포함되나 유형은 미분류로 집계됩니다.'
    elif status==K['review']:
        effect='건수·정지시간에 포함되며 임시 1순위 유형으로 집계됩니다. 확정 후 유형 집계가 바뀝니다.'
    else:
        effect='기본 건수에 포함될 수 있으나 시간·날짜·설비별 집계의 정확도에 영향이 있습니다.'
    if record.get('minutes') is None or str(record.get('minutes')).lower() == 'nan':
        effect+=' 정지시간 미집계 가능.'
    return ' / '.join(explanations),' / '.join(dict.fromkeys(actions)),effect
