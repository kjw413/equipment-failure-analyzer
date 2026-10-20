# 코드 구조와 유지보수

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
| core/classifier.py | 부품·증상 조건 일치, 결정 규칙에 따른 후보 해소, 대안·복수 고장 보호 |
| core/aggregation.py | 공통 그룹 집계와 빈 기간을 포함한 추이 |
| core/analyzer.py | 분석 범위 선택, 집계표·지표·품질 정보 구성 |
| core/config.py / defaults_merge.py | 사용자 설정 저장 및 기본값 병합 |
| core/corrections.py / review_guidance.py | 보정 항목 계산 및 검토 안내 |
| core/equipment_names.py / equipment_breakdown.py | 설비명 검증 및 설비별 유형 구성 |
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

- 원본 Excel과 기록 ID 생성 규칙은 유지합니다. 운영 카탈로그는 classification_catalog.json으로 관리하며 규칙 파일은 schema 3, 최소 프로그램 버전 1.8.0을 사용합니다.
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

## 조건 일치와 결정 규칙에 따른 분류

부품·증상 조건에 일치하는 후보를 만들고 제외·부정·예정 표현을 제거합니다. 원인 규칙,
구체적인 부품명, 고장·교체 근거, 명시적 인과관계와 MES 부위 단서로 겹치는 후보를 해소합니다.
해소되지 않은 후보, 명시적 대안, 독립 복수 고장은 검토필요로 유지합니다. 후보가 없으면 미분류입니다.

classification_reason은 분류 판정 사유, candidate_evidence는 후보별 규칙·근거를 담습니다.
GUI와 Excel/PDF는 같은 분석 스냅샷의 판정 사유와 근거를 표시합니다. 이전 점수 설정값은
분류에 사용하지 않습니다. 사용자 수동확정, 기존 집계 기준과 기록 ID는 유지합니다.
운영 카탈로그의 대·중·소분류 경로를 기본 규칙과 계층별 선택 목록에 적용합니다. 소분류는 실제 부품 종류이며 고장 현상·조치와 분리합니다.
배포 카탈로그는 대분류 6개·중분류 58개·소분류 237개이며 기본 활성 규칙 237개를 모두 component로 제공합니다. 기본 fallback·override 규칙은 없습니다. 개인 프로필의 사용자 규칙 수는 별도입니다.

## 운영 카탈로그 이관

classification_catalog.json을 CONFIG_FILES에 포함하여 같은 사용자 프로필에 카탈로그 버전을 저장합니다.
첫 카탈로그 전환에서는 새 기본 규칙 전체를 설치하고 알려진 이전 기본 규칙을 퇴역시킵니다.
기존 사용자 규칙 중 새 카탈로그 범위 밖 경로는 내용·우선순위를 보존한 채 비활성화하여 백업하고,
새 범위 안의 사용자 규칙은 유지합니다. 기존 manual_overrides.json은 바이트 그대로 보존하며
수동확정값은 해당 기록에서만 유지합니다. 신규 선택 목록에 이전 수동 유형을 전역으로 추가하지 않습니다.

동일 운영 카탈로그의 후속 기본값 병합은 사용자의 규칙 비활성화·삭제를 존중합니다.
전환 실패 시 완료 상태를 기록하지 않고 로드 오류를 표시하여 재시도할 수 있게 합니다.
schema 3과 최소 버전 1.8.0 보호로 이전 실행파일의 역방향 기본값 병합을 차단합니다.

## 복수 고장 구성과 비가산 추이

core/fault_components.py는 완전한 대·중·소분류를 정렬·유일화하고 JSON 구성원, 표시명,
조합 키를 생성합니다. classifier는 독립적인 실제 고장 증거만 부품별 local 후보로 묶으며
같은 부품의 대안 유형은 구성원 하나만 잠정 선택합니다. 실제 조합도 사용자 검토 전에는
검토필요이며 원본 한 기록의 시간과 건수는 복제하지 않습니다.

classification_mode/component_count/component_types/component_details/combination_key는
CLASSIFICATION_COMPONENT_COLUMNS로 공유합니다. 사용자 classification_components 보정은
JSON 유형 목록이며 단일 major/middle/minor 보정과 상호배타입니다. 수동복수확정은
복수유형확정 상태로 집계되고 자동검토 사유는 비웁니다. 사용자확정 사유는 자동 판정과 구분합니다.

core/component_analysis.py는 전체 고장기록을 분모로 포함 건수를 계산합니다. 구성 유형별
동일 record_id는 한 번만 세며 사용자확정·잠정검토 건수를 구분하고 minutes를 포함하지 않습니다.
월별 분모는 날짜가 유효한 해당월 전체 고장기록입니다. 조합별 시간은 기존 type집계에만
기록당 한 번 반영합니다. 부품별 표와 월별 표는 Excel 정적 분석 스냅샷으로 내보냅니다.
