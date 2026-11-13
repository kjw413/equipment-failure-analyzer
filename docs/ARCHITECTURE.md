# 코드 구조와 유지보수 - v1.15.0

## 실행과 처리 흐름

`START.bat → scripts/run.bat → main.py → gui.main_window.MainWindow`

`analyze_cli.py`는 같은 분석 서비스와 Excel/PDF 동시 내보내기를 사용합니다.
두 진입점 모두 `core.service.run_analysis`에서 입력 표준화와 집계를 수행합니다.

| 영역 | 책임 |
|---|---|
| core/excel_loader.py | Excel 검증, 제목 행 탐지, 컬럼 매핑, 원본 읽기 |
| core/parsing.py | 결측값, 문자열 정규화, 날짜·시각·정지시간 변환 |
| core/preprocessing.py | 기록 ID, 표준 기록 생성, 사용자 보정, 분류 적용 |
| core/rules.py | 분류 규칙 검증, 버전 스키마, Excel 저장 및 업그레이드 |
| core/classifier.py | 부품·증상 조건 일치, 결정 규칙에 따른 후보 해소, 자동 대표 선택과 보호 조건 |
| core/failure_classification.py / failure_modes.py | 부품 매칭 결과를 분야·부품 종류·증상으로 변환, 증상과 조치 분리 |
| core/aggregation.py | 공통 그룹 집계와 빈 기간을 포함한 추이 |
| core/analyzer.py | 분석 범위 선택, 집계표·지표·품질 정보 구성 |
| core/config.py / defaults_merge.py | 사용자 설정 저장 및 기본값 병합 |
| core/corrections.py / review_guidance.py | 보정 항목 계산 및 검토 안내 |
| core/equipment_names.py / equipment_breakdown.py | 라인/설비 코드별 설비명, 설비군·공장·팀 검증 및 설비별 유형 구성 |
| core/report_view.py / sorting.py | 보고서 표시용 투영 및 안정적인 기본 정렬 |
| gui/main_window.py | UI 조립과 화면 상태 전환 |
| gui/tasks.py / theme.py | 백그라운드 작업 및 스타일 |
| gui/widgets.py / dialogs.py / report_settings.py | 재사용 화면 요소와 설정 창 |
| report/excel_report.py / pdf_report.py | 형식별 문서 구성 |
| report/export_bundle.py | Excel/PDF 생성·덮어쓰기·실패 복구 |
| report/output.py | 같은 폴더에서 임시 파일 생성 후 원자적 교체 |
| report/charts.py / formatting.py | 공용 차트 생성 및 결측값·숫자 표시 |
| report/cache.py / pdf_layout.py | Excel 수식 캐시 및 PDF 레이아웃 |

## 경계와 호환성

- 원본 Excel과 기록 ID 생성 규칙은 유지합니다. 운영 카탈로그는 classification_catalog.json으로 관리하며 규칙 파일에 schema 7과 필요 버전 메타데이터 1.15.0을 기록합니다. 새 대표 정책은 v1.15.0 실행파일에 구현되어 있습니다.
- 표시용 설비명 변경은 보고서 사본에만 적용합니다.
- 값 파싱·집계·규칙 저장은 별도 모듈을 직접 참조합니다.
- 기존 `core.preprocessing` 파싱 함수, `core.analyzer.grouped/trend`,
  `core.classifier` 규칙 API, `gui.widgets.Task`, `report.pdf_report` 숫자 함수는
  명시적인 재노출로 기존 import 호환성을 유지합니다.
- Excel의 두 설비 분석 시트는 설비별 집계와 PNG bytes를 공유합니다.
  이미지 삽입마다 독립된 버퍼를 만들어 저장 중 스트림 종료 충돌을 방지합니다.
- 개별 보고서는 완성 후 교체하고, 묶음 내보내기는 두 보고서를 준비한 뒤
  기존 파일 백업과 복구를 포함해 커밋합니다.
- 재분석 결과가 화면에 적용되면 이전 보고서 바로가기를 초기화합니다.
  시트와 제목 행을 바꾸면 다시 읽어야 새 결과를 내보낼 수 있습니다.

## 개발·배포

런타임 의존성은 requirements.txt, 테스트·정적 검사는 requirements-dev.txt,
EXE 빌드는 requirements-build.txt로 구분합니다. 빌드 의존성에는 개발 의존성이 포함됩니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q -W error::DeprecationWarning
```

`BUILD_EXE.bat`은 scripts/build.bat을 통해 정적 검사·포맷 검사·전체 테스트 후 빌드합니다.
버전은 version.py를 import하여 읽으므로 문자열의 따옴표 표기에 의존하지 않습니다.
EXE spec은 DLL 탐색 PATH를 가상환경·Python·Windows로 한정합니다. 외부 개발 도구의
오래된 시스템 DLL이 배포 파일에 수집되는 문제를 방지합니다.

`tools/make_rules.py --dry-run`은 기본 규칙을 검증합니다. 기본 규칙을 실제 변경하는
릴리스에서는 이전 기본값 지문을 config/defaults_history.json에 먼저 기록해야 합니다.
사용자 안내서 원문은 docs/USER_GUIDE.txt이며 `tools/build_user_guide.py`로
루트 USER_GUIDE.pdf를 만듭니다. 버전별 변경 기록은 docs/CHANGELOG.md에 통합합니다.

## 검증 자료와 로컬 파일

공유 fixture는 tests/conftest.py에 두고 합성 입력과 임시 사용자 프로필을 생성합니다.
테스트 모듈을 다른 테스트 모듈에서 import하지 않습니다. 이전 버전의 설정 fixture는
사용자 수정·삭제 보존과 업그레이드 호환성을 검증하므로 유지합니다.

sample/ 원본 자료, 사용자 설정, 기존 보고서, .venv와 실행 파일은 정리 과정에서 지우지 않습니다.
output/의 검증 결과와 .pytest_tmp*/, .ruff_cache/, tmp/는 Git 추적에서 제외합니다.

`tools/clean_project.py`는 빌드 중간 파일과 재생성 가능한 캐시만 정리하며 기본은 미리보기입니다.
`--apply`로 실제 정리하고, `--validation-temp`를 추가하면 명시한 과거 검증 폴더의
pytest 임시 프로필도 포함합니다. 실행·테스트·빌드가 끝난 뒤 사용합니다.
실제 보고서와 검증 요약은 유지하고, Git 추적 파일과 재분석 지점(링크)이 있는 대상은 거부합니다.
2026-10-20 정리에서 카탈로그 분석용 일회성 `notebook_runtime`은 패키지 버전 목록
`output/taxonomy_redesign_20261019/requirements-notebook.txt`와 재설치 안내를 남기고 제거했습니다.
분석 노트북·HTML·카탈로그·보고서·사용자 설정 사본은 보존했습니다.

## 조건 일치와 결정 규칙에 따른 분류

부품·증상 조건에 일치하는 후보를 만들고 제외·부정·예정 표현을 제거합니다. 원인 규칙,
구체적인 부품명, 고장·교체 근거, 명시적 인과관계와 MES 부위 단서로 겹치는 후보를 해소합니다.
기존 결정 규칙으로 명확한 단일 고장을 선택한 뒤에도 여러 후보가 남으면, 원문 고장 또는 완료 조치 근거가 있는 1순위를 이력 대표로 자동 선택합니다. 의심·대안, 미등록 다른 물리 고장, 불명확한 공동주어, 동일 명사 동률 상충 규칙, 명사만 있는 기록은 검토필요로 유지합니다.
판정은 세 단계입니다. 고장내용에 component/fallback/override 규칙을 적용하고, 후보가 없으면
정규화한 비가동코드(소)를 부품명 구절로 앞에 붙여 다시 판정하며, 그래도 없으면 nopart 규칙
(공정·자재 현상, 부품 미상 제어 오류)을 적용합니다. 앞 단계에서 후보가 있으면 뒤 단계는 실행하지 않습니다.
모든 단계에서 후보가 없으면 비가동코드(중·소)가 비어 있으면 '비가동코드 미기입', 입력돼 있으면 '규칙 미일치'입니다.

classification_reason은 분류 판정 사유, candidate_evidence는 후보별 규칙·근거를 담습니다.
GUI와 Excel/PDF는 같은 분석 스냅샷의 판정 사유와 근거를 표시합니다. 이전 점수 설정값은
분류에 사용하지 않습니다. 사용자 수동확정, 기존 집계 기준과 기록 ID는 유지합니다.
공개 출력 필드 `major/detail_equipment/middle/minor`는 고장 분야 / 상세설비·모듈 / 세부 부품 / 고장 현상을 뜻합니다. 출력 스키마는 `equipment_part_failure_v3`입니다. 네 축은 독립적으로 선택하며 다른 축의 변경으로 기존 선택을 초기화하지 않습니다. 부품군은 종류 탐색에만 사용하고 선택한 세부 부품에서 `part_group`을 파생합니다.
`repair_actions`는 교체 / 수리·정비 / 조정 / 점검 / 청소·급유 / 체결·조립 / 리셋·재가동을 쉼표로 구분한 별도 문자열입니다. 구성원과 후보의 원문 조치 근거도 별도로 보존합니다. 단일 대상의 조치만 기재된 기록은 `현상 미기재` 부분분류로 보존하며 조치나 원인을 고장 현상으로 변환하지 않습니다.

`status=부분분류`는 단일 대상을 확인했지만 고장 분야·상세설비·세부 부품·고장 현상 중 일부가 미기재인 자동처리 결과입니다. `classification_mode=single`과 확인된 구성원을 유지하고 `classification_missing_fields`에 원문 미기재 항목을 쉼표로 표시합니다. `auto_rows`는 완전 자동분류만 세고, `partial_rows`는 부분 자동분류, `auto_processed_rows`는 두 값의 합입니다. 시간·일자 등 별도 품질 문제는 부분분류 여부와 관계없이 검토 목록에 포함합니다. 보고서 투영·GUI 편집에서 부분분류의 확인된 축을 비우지 않습니다.

`core/representative_fault.py`는 직접 관찰된 단일 실제 부품 고장을 다른 부품의 완료 조치와 구분해 먼저 선택합니다. 그 뒤의 복수 부품·현상·설비 후보는 원문 고장 또는 완료 조치 근거가 있는 1순위를 대표로 자동 선택하며 `classification_reason`에 `1순위 대표 자동선택`을 표시합니다. 의심·대안, 미등록 다른 물리 고장, 불명확한 공동주어, 동일 명사 동률 상충 규칙, 명사만 있는 기록은 자동 선택을 막습니다. 미등록 대상의 별도 물리 고장도 `unmapped_fault_context`로 검토에 남기며, 이미 연결된 괄호 안 부품·증상이나 같은 고장의 부위 수리는 새 고장으로 만들지 않습니다. 후보 전체와 후속 조치는 별도 근거로 보존합니다.

완료 조치 판정은 `incomplete_action_context()`를 규칙 증거와 원문 조치 추출에서 공유합니다. 교체 요청·미완료·지연·부정·예정은 완료 작업이 아니며, 원문의 명시 완료는 보존합니다. 다른 주어가 생긴 다음 절의 조치나 뒤쪽 설비를 앞 부품에 연결하지 않습니다. 일반 원문과 달리 MES 부품코드 보완은 그 코드가 이름을 명시하는 의도된 접두 문맥으로 처리합니다.
내부 부품 식별 경로 244개와 공개 분류축은 구분합니다. 기본 규칙 245개, 상세설비 65종, 공개 부품·공정 대상 199종, 실제 부품군 28개와 제품·자재 대상군 1개, 현상 23종과 조치 7종을 제공합니다. 부품 식별용 major/middle/minor는 내부 소속 분야/부품군/부품 종류이고 공개 고장 분야는 실제 현상으로 확인합니다. `모터 소손`과 모터의 기계적 마모는 같은 부품이라도 분야가 다를 수 있습니다.
`core/equipment_taxonomy.py`는 상세설비 별칭과 원문의 고장·조치 문맥, 비가동코드(중)로 상세설비를 식별합니다. 등록 설비명만으로 고장 상세설비를 추정하지 않습니다. 본체만 명시된 기록은 `세부 부품 미기재`로 보존하며 제품·자재 대상과 함께 실제 부품 집계에서 제외합니다.
사용자 수동 선택 목록은 `fault_catalog_categories()`로 활성 설비·부품·고장 현상을 캐시합니다. 원본 부품 경로를 다루는 규칙 도구는 `catalog_categories()`를 사용합니다. 구체적인 종류를 알 수 없는 부품은 `(종류 미상)`을 보존합니다.
차단기 떨어짐은 보호장치 동작이며 과부하 원인이나 물체 낙하를 추정하지 않습니다. 손상·파손은 통합하고 마모·부식은 별도 현상으로 관리합니다. 표준화는 동의어·표기만 통합하고 냉매/냉각수, 씰/가스켓/링 등의 의미 차이는 보존합니다.

## 운영 카탈로그 이관

classification_catalog.json을 CONFIG_FILES에 포함하여 같은 사용자 프로필에 카탈로그 버전을 저장합니다.
첫 카탈로그 전환에서는 새 기본 규칙 전체를 설치하고 알려진 이전 기본 규칙을 퇴역시킵니다.
기존 사용자 규칙 중 새 카탈로그 범위 밖 경로는 내용·우선순위를 보존한 채 비활성화하여 백업하고,
새 범위 안의 사용자 규칙은 유지합니다. 기존 manual_overrides.json은 바이트 그대로 보존하며
수동확정값은 해당 기록에서만 유지합니다. 신규 선택 목록에 이전 수동 유형을 전역으로 추가하지 않습니다.

동일 운영 카탈로그의 후속 기본값 병합은 사용자의 규칙 비활성화·삭제를 존중합니다.
전환 실패 시 완료 상태를 기록하지 않고 로드 오류를 표시하여 재시도할 수 있게 합니다.
schema 7을 지원하지 않는 구버전은 규칙 읽기가 차단됩니다. 필요 버전 메타데이터만으로 같은 schema 7을 지원하는 모든 이전 실행파일을 차단하지는 않습니다. 새 대표 정책은 v1.15.0 실행파일로 적용하며 이전 실행파일은 이전 판정 정책으로 동작합니다. 이전 스키마 수동확정은 파일을 변경하지 않고 추천 후보로 보존하며 새 기준의 재확정을 요구합니다. 과거 소분류 교체는 고장 현상으로 자동 채택하지 않습니다. 일자·시간 등 분류 외 보정은 계속 적용할 수 있습니다.

## 단일 최종 분류와 검토 후보

core/fault_components.py는 4단계 최종 분류와 내부 부품 식별 경로를 구분하고 JSON 구성원·표시명을 생성합니다. 한 이력의 공개 최종 구성원은 0개 또는 1개입니다. 근거 있는 복수 부품·현상·설비 기록은 대표 하나를 자동 선택하고 전체 후보를 `classification_candidates`에 보존합니다. 의심·대안 등 보호 조건은 최종값을 비우고 검토합니다. 후보 순위는 규칙 근거의 순서이며 정확도나 확률이 아닙니다. 대표 선택은 다른 실제 고장이 없다는 뜻이 아니며, 부품별 건수는 대표로 선택한 실제 부품의 기록 수입니다.

classification_mode/component_count/component_types/component_details/combination_key, part_group/repair_actions와 상세설비 근거 필드는 CLASSIFICATION_COMPONENT_COLUMNS로 공유합니다. 새 수동 보정은 4필드 전체가 필요하며 단일 분류만 허용합니다. 과거 복수 보정은 후보로 보존하고 재확정합니다. 분류 선택은 메모리에서 대기하고 표준화 시 현재 파일의 보정을 검증한 뒤 한 번에 저장합니다.

core/component_analysis.py는 확정 부품만 대분류·상세설비·세부 부품별로 한 번 집계합니다. 전체 고장이력이 비율의 분모이며 검토 후보·세부 부품 미기재·제품·자재 대상은 실제 부품 건수에 포함하지 않습니다. 월별 분모는 날짜가 유효한 해당월 전체 고장기록입니다. 부품별 표에는 정지시간을 반복 배분하지 않습니다.

부품·증상 구성원에는 부품 식별자와 상세설비·증상 근거·조치를 보존합니다. `fault_detail` 표는 미확정도 포함해 이력당 한 행을 유지하며 `event_id`로 원본 기록과 연결합니다. 정지시간 열을 넣지 않습니다. GUI 상세분석, Excel 08_부품증상상세와 PDF가 같은 표를 사용합니다.
