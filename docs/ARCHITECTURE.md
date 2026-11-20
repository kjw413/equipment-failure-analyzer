# 프로젝트 구조

## 실행 흐름

```text
START.bat → scripts/run.bat → main.py → gui/
analyze_cli.py ───────────────────────┐
                                     ↓
core/excel_loader.py → core/service.py → AnalysisResult → report/export_bundle.py
                       ├─ preprocessing.py                   ├─ excel_report.py
                       └─ analyzer.py                        └─ pdf_report.py
```

화면과 CLI는 같은 분석 서비스를 호출합니다. 입력 시트에서 열을 매핑하고 본문을 표준화한 뒤 분류와 집계를 수행합니다. 두 보고서는 같은 분석 결과에서 생성되며, 저장 도중 한쪽 파일을 쓰지 못하면 기존 결과 복구를 시도합니다.

## 폴더별 책임

파일은 주 용도에 따라 한 곳에 둡니다. 기능별 모듈은 공통 분석 결과를 사용하고, 수정 위치는 아래 표에서 찾을 수 있습니다. 검증과 빌드는 재생성 가능한 파일을 전용 경로에 쓰므로 해당 경로만 정리할 수 있습니다.

| 분류 | 경로 | 책임 |
| --- | --- | --- |
| 진입점 | `main.py`, `analyze_cli.py`, `START.bat`, `BUILD_EXE.bat` | 앱, CLI, Windows 실행과 빌드의 시작 |
| 분석 | `core/` | 입력 해석, 표준화, 분류, 집계, 사용자 설정 |
| 화면 | `gui/` | 입력·설정 화면, 분류 검수, 분석·저장 작업 호출 |
| 보고서 | `report/` | Excel·PDF, 차트와 표, Excel 검색·드릴다운용 VBA |
| 배포 기본값 | `config/` | 규칙, 열 매핑, 보고서 양식과 검색용 VBA 리소스 |
| 실행 절차 | `scripts/` | Windows 설치·실행·시험·빌드와 분류 체계 검증 명령 |
| 유지보수 | `tools/` | 양식·VBA·사용자 안내 재생성, Excel 검증, 캐시 정리 |
| 회귀 검증 | `tests/` | 자동 테스트, 호환성 시험 자료, 네이티브 Excel 검증 코드 |
| 실행 예시 | `examples/` | 외부 업무 파일 없이 실행할 수 있는 예제 입력 |
| 문서 | `docs/` | 구조, 개발 이력, 테스트 근거와 사용자 안내 원본 |
| 사용자 자료 | `source/`, `output/` | 보관 입력과 사용자가 생성·수정한 결과 |
| 검수 기준 자료 | `outputs/` | 최신 검수 보고서 쌍과 분류 체계 검토 자료 |
| 배포 파일 | 루트의 버전 표기 EXE·ZIP | 현재 전달용 Windows 배포본 |
| 로컬 의존성 | `.venv/`, `wheels/` | 가상환경과 오프라인 설치에 필요한 패키지 |
| 재생성 산출물 | `build/`, `dist/`, `tmp/`, `.pytest_tmp*/`, 각종 캐시 | 빌드 중간본, 임시 검증 결과, 실행 캐시 |

`config/`는 배포에 포함되는 기본값입니다. 사용자 설정과 검수 결과는 Windows에서 `%LOCALAPPDATA%\EquipmentFailureAnalyzer\config`에 저장됩니다. 별도 프로필을 쓰려면 CLI의 `--data-dir`나 `EFA_DATA_DIR`을 지정합니다. **소스에서 검증할 때는 임시 프로필 경로를 명시**해 개인 설정에서 검증을 분리합니다. 기본 출력 경로는 `EFA_OUTPUT_DIR`로 지정할 수 있습니다.

## 변경할 기능 찾기

| 변경 | 시작 위치 | 확인할 항목 |
| --- | --- | --- |
| 원본 열이 다르게 인식됨 | `core/excel_loader.py`, `config/column_mapping.json` | 헤더 탐지, 저장된 매핑, 입력 시트 보호 |
| 띄어쓰기·오타·라인명 표준화 | `core/preprocessing.py`, `config/normalization.json`, `config/equipment_names.json` | 표준화 전후 내용, 원본 중분류의 상세설비 근거 |
| 분류 규칙·검토 판정 | `core/failure_classification.py`, `core/classification_policy.py`, `config/classification_catalog.json` | 확인된 항목의 부분 분류, 애매한 후보의 검토 표시 |
| 화면 검수·사용자 설정 | `gui/main_window.py`, `gui/dialogs.py`, `core/config.py` | 원문과 표준화 결과, 이전 프로필에서 가져온 사용자 규칙 |
| Excel 양식·표·차트 | `config/report_template.xlsx`, `report/locked_template.py`, `report/issue_workbook.py` | 필터 기본값, 병합·테두리·행 높이, 내림차순·천 단위 |
| Excel 드릴다운·검색·비교 | `report/vba/`, `report/search_project.py`, `report/fault_comparison.py` | VBA 프로젝트 재생성, Excel에서 실제 필터 연동 |
| PDF 형식과 결과 파일 저장 | `report/pdf_report.py`, `report/export_bundle.py` | Excel과 동일한 분석 범위, 두 파일 저장과 복구 |

## 파일을 둘 위치

- 사람이 입력하거나 수정한 Excel 및 원본은 운영 데이터로 관리합니다. 향후 자동 테스트를 만들 때 필요한 최소 입력은 `tests/`에 합성 자료나 의도적으로 유지하는 호환성 자료로 둡니다.
- 일회성 검증을 실행할 때는 `tmp/qa/` 아래에 프로필과 결과를 만듭니다. 자동 테스트 작업 폴더는 pytest가 관리합니다. 재생성할 수 있는 캐시는 [정리 도구](../tools/clean_project.py)로 대상을 확인하고 비울 수 있습니다.
- 테스트의 결론과 재현에 필요한 조건은 [테스트 결과](TEST_RESULTS.md)에, 문제와 개선 배경은 [개발 이력](DEVELOPMENT_HISTORY.md)에 기록합니다. 이전 테스트 산출물 경로는 해당 시점의 검증 기록입니다.
- 실행 중 읽히는 기본값·양식·VBA 리소스와 오래된 형식을 열기 위한 회귀 자료는 유지합니다. 자동 생성되는 과거의 배포본과 보고서는 전달이나 검수에 필요한 버전만 작업 폴더에 둡니다.
