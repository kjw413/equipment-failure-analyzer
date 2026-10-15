# 설비 고장 분석기 v1.5.0

MES 비가동 내보내기(Excel)를 읽어 고장 기록을 표준 유형으로 분류하고, Excel 분석파일(15개 시트)과 PDF 최종보고서를 함께 만드는 오프라인 Windows 프로그램입니다. 분류는 로컬 규칙 기반이며 외부 전송이나 LLM을 쓰지 않습니다.

## v1.5.0 변경 요약

실제 MES 파일(2026-01~10, 고장 414건) 기준 검토필요: **300건 → 11건**.

| 단계 | 검토필요 |
|---|---|
| v1.4.0 | 300 |
| 고장대상 판정 패턴 수정 (1P·2P·3P 전 라인 인정) | 230 |
| 고장대상 미기재는 '고장대상 설비' 기준일 때만 검토 | 188 |
| 표기 정규화·잘린 어미 복원 | 193 |
| 근접 매칭·근거 기반 자동선택 엔진 | 153 |
| 분류 규칙 확장 29 → 67개 | 11 |

남은 11건은 두 부품·두 사건이 한 기록에 함께 적혀 근거 있게 하나를 고를 수 없는 경우입니다.

- 분류 엔진: 구절 단위로 부품 뒤 가까운 증상만 짝짓고, 다음 부품명 앞에서 멈춥니다. 복수 후보는 부품 규칙 우선 / 복합명사 중심어 / 교체 부품 우선 / 원인 표현 / MES 소분류 일치 근거가 있을 때만 자동 선택하고 사유를 '분류 근거'에 남깁니다.
- 규칙: role 열(component / fallback / override) 추가. '씰러'가 '씌러'로, '씰/오링'이 '씬/오링'으로 잘못 들어가 있던 오타 수정.
- 기존 사용자 설정 자동 병합: 직접 수정하지 않은 기본값만 새 버전으로 바꾸고, 수정·추가·삭제한 규칙은 보존. 변경 전 config/backup에 백업.
- 행 수정: 바꾼 항목만 저장(시간만 고치면 분류는 확정되지 않음), 항목별 해제와 [수동 보정 해제] 지원.
- 컬럼 매핑: 수정한 매핑을 같은 제목 행의 파일에 다시 적용. 매핑 변경 시 기존 수동 보정을 새 기록 ID로 이전.
- 기타: '남걁니다' 등 문구 오타, numpy 지원 중단 경고, v1.4.0 기능 테스트 누락 보완.

자세한 내용: docs/UPDATE_v1.5.0.txt, docs/CHANGELOG.md

## 실행

ZIP을 모두 푼 후 맨 위의 **START.bat**을 더블클릭하세요. Python 3.11~3.13 (64-bit)이 필요합니다.
최초 실행은 인터넷 또는 source/wheels의 사전 준비 파일로 라이브러리를 설치합니다. 설치 후에는 오프라인으로 동작합니다.

Python이 없는 현장 PC용: 준비된 Windows PC에서 **BUILD_EXE.bat**을 실행하면 테스트 후 상위 폴더에 **EquipmentFailureAnalyzer.exe**가 생성됩니다.
폴더에 이미 있는 EXE는 BUILD_EXE.bat으로 다시 빌드하기 전까지 이전 버전일 수 있습니다. 사내 설치·배포는 IT 정책을 따르세요.

## 사용 순서

Excel 드래그 앤 드롭 / 파일 찾아보기 -> (필요 시) [컬럼 매핑] -> [설비명 변환 설정] -> 분석 -> [검토필요] 탭 확인·행 수정 -> [Excel + PDF 생성]

지원: .xlsx/.xlsm. 매크로는 실행하지 않습니다. .xls/암호화 파일은 미지원입니다. 시트나 제목 행을 바꾼 후에는 [시트 읽기]를 누르세요.

CLI: `python analyze_cli.py INPUT.xlsx --output OUTPUT.xlsx [--basis target] [--overwrite]`

## 분류·집계 기준

- 기본은 고장만 집계하며 계획운휴/작업운휴는 제외합니다. 1행=1기록. 시간 미기재를 0분으로 보지 않습니다.
- 생산량/가동시간/실수리시간 없이 고장률·MTBF·MTTR를 만들지 않습니다.
- 유형은 비고에 기록된 부품·증상 기준 분류이며 원인 확정이 아닙니다. 근거가 대등하면 검토필요로 남깁니다.
- 검토필요 = 미분류, 복수 유형 후보, 정지시간·일자 이상, (설비 기준이 '고장대상 설비'일 때) 고장대상 미기재. 검토필요도 건수·정지시간 집계에는 포함됩니다.
- MES 형식에서 고장대상은 '비가동 코드(중)'의 설비명(예: `1P M/Y …`, `2P I/C …`, `3P F/M …`)입니다. '유틸리티 고장(이상)', '제품불량(설비기인)'은 MES 구조상 코드(중)가 없습니다.

## 설정과 저장 위치

사용자 설정: `%LOCALAPPDATA%/EquipmentFailureAnalyzer/config` (같은 PC·사용자에서 업데이트 후에도 유지)

| 파일 | 내용 |
|---|---|
| classification_config.xlsx | 분류 규칙 ([분류기준 관리]에서 편집) |
| normalization.json | 표기 정규화(replacements), 잘린 어미 복원(clause_end_expansions) |
| settings.json | 집계 설정, 고장대상 판정 패턴, 분류 엔진 설정(classifier) |
| equipment_names.json | 설비 코드 -> 보고서 설비명 |
| manual_overrides.json | 행별 수동 보정 (기록 ID 기준) |
| column_overrides.json | 사용자가 확정한 컬럼 매핑 (제목 행 기준) |
| backup/ | 기본값 자동 병합 전 백업 |

번들 기본값: `source/config` (이전 기본값 지문: `defaults_history.json`)

## 시트 구성

01 종합현황 / 02 설비별분석 / 03 라인별분석 / 04 유형별분석 / 05 기간별추이 / 06 Pareto / 07 교차분석 / 08 고장상세 / 09 검토필요 / 10 데이터품질 / 11 원본데이터 / 12 분류기준 / 13 설비명설정 / 14 TOP고장 / 15 설비별유형순위

## 코드 수정 위치

| 파일 | 역할 |
|---|---|
| main.py, gui/ | GUI 진입점, 화면, 대화상자 |
| core/excel_loader.py | Excel 입력, 제목 행·컬럼 자동 매핑 |
| core/preprocessing.py | 정규화, 시간·날짜 파싱, 기록 ID, 수동 보정 반영 |
| core/classifier.py | 규칙 검증·저장, 분류 엔진 |
| core/review_guidance.py | 검토 사유·수정 방법·집계 영향 |
| core/corrections.py | 행 수정 저장 항목 계산 |
| core/defaults_merge.py | 새 버전 기본값을 사용자 설정에 병합 |
| core/analyzer.py | 집계표와 지표 |
| core/config.py | 사용자 설정 저장소 |
| report/ | Excel·PDF·차트 |
| tools/make_rules.py | 번들 기본 분류 규칙 정의·생성 (config/classification_config.xlsx) |
| docs/build_user_guide.py | docs/USER_GUIDE.txt -> USER_GUIDE.pdf |
| tests/ | 회귀 테스트 |

## 테스트 / 오류

`python -m pytest -q` (결과: docs/TEST_RESULTS.md). PySide6가 없으면 GUI 테스트는 건너뜁니다.
오류 로그: 사용자 폴더/logs/application.log. 보고서가 Excel에서 열려 있으면 닫거나 다른 이름으로 저장하세요.

기술 참고: https://pyinstaller.org/en/stable/ / https://doc.qt.io/qtforpython-6/
