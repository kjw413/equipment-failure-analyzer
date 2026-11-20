# 설비 고장 분석기

Windows에서 설비 고장이력 Excel을 표준화하고 분류합니다. 공장·팀·라인·상세설비별 고장 건수와 정지시간을 집계해 Excel과 PDF를 생성합니다. 분석과 보고서 생성은 로컬에서 실행됩니다.

## 처음 실행하기

1. 배포본으로 사용하는 경우 `EquipmentFailureAnalyzer_v1.34.1.exe`를 실행합니다. Python 설치 없이 실행할 수 있습니다.
2. 소스에서 실행하는 경우 Windows 64비트 Python 3.11~3.13을 설치하고 `scripts\setup.bat`를 실행한 뒤 `START.bat`를 엽니다. 오프라인 설치 시에는 해당 Python 버전에 맞는 의존성 전체를 `wheels\`에 준비합니다.
3. 고장이력 파일을 열고 분석을 실행합니다. 열 이름이 다른 경우 처음 가져올 때 표시되는 열 매핑을 확인합니다.
4. 결과를 저장합니다. 기본 폴더는 실행 위치 옆의 `output/`이며, 저장 위치는 화면에서 바꿀 수 있습니다. Excel의 검색과 차트 드릴다운은 설치형 Excel에서 매크로 실행이 허용된 경우 사용할 수 있습니다.

실제 사내 파일 없이 분석과 저장을 확인하려면 [예제 입력](examples/demo_input.xlsx)을 사용합니다. 아래 명령은 별도의 프로필과 출력 폴더를 사용합니다.

```powershell
.\.venv\Scripts\python.exe analyze_cli.py examples/demo_input.xlsx --output tmp/demo/demo.xlsm --data-dir tmp/demo/profile
```

## 결과 보기

| 보고서 | 확인할 내용 |
| --- | --- |
| 01.종합현황 | 고장 건수·정지시간과 라인별 우선순위 |
| 02.팀별 주요이슈 | 공장·팀을 고른 뒤 라인과 상세설비를 순서대로 확인 |
| 03.월별 주요이슈 | 월별 실적과 선택 월의 일별 실적 |
| 04.고장비교 | 기준과 비교 대상의 부서·라인·상세설비별 실적 |
| 별첨. 검토·분류현황 | 분류 판정과 검토 대기 기록 |
| 별첨. 고장이력 | 표준화된 고장내용과 분류 근거 |
| 별첨. 원본 검토표시 | 입력 이력과 검토가 필요한 원본 행 |

Excel 1개와 PDF 1개를 함께 내보냅니다. 원본 검토표시는 결과 Excel 안에 포함됩니다. 분류를 검수할 때는 표준화된 고장내용과 원문을 함께 확인할 수 있습니다.

제품 자료가 있고 제품 교차분석을 켠 경우 Excel에 해당 별첨이 추가됩니다.

## 프로젝트 찾기

| 찾는 내용 | 위치 |
| --- | --- |
| 실행 경로, 폴더 분류, 규칙·화면·보고서 수정 위치 | [프로젝트 구조](docs/ARCHITECTURE.md) |
| 사용법과 사내 배포 방법 | [사용자 안내](USER_GUIDE.pdf) |
| 어떤 문제를 왜 어떻게 개선했는지 | [개발 이력](docs/DEVELOPMENT_HISTORY.md) |
| 버전별 변경 상세 | [변경 이력](docs/CHANGELOG.md) |
| 검증 명세와 실행 기록 | [테스트 결과](docs/TEST_RESULTS.md) |
| 최신 배포·보고서 검수 근거 | [QA 기록](docs/QA_EVIDENCE.md) |

## 개발 작업

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q
```

`BUILD_EXE.bat`는 검사를 실행한 뒤 버전이 붙은 Windows EXE를 만듭니다. 현재 소스 버전은 [version.py](version.py)에서 확인합니다.

작업 캐시를 정리하려면 `python tools/clean_project.py`로 대상을 확인한 뒤 `--apply`를 붙입니다. `--validation-temp`를 추가하면 별도로 만든 검증 작업 폴더도 확인할 수 있습니다. [프로젝트 구조](docs/ARCHITECTURE.md)
