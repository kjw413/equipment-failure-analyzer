# 설비 고장 분석기 웹 v2

Next.js에서 분석 조건을 설정하고 결과를 검수합니다. FastAPI는 기존 Python 분석과 Excel 보고서 생성을 실행합니다. 기본 실행 주소는 `http://localhost:3072`이며, 브라우저와 서버를 같은 컴퓨터에서 사용하는 1인용 구성입니다. 데스크톱 버전 1의 실행 파일은 [START.bat](../START.bat)입니다.

## Windows에서 실행하기

1. [설비 고장 분석기 실행.bat](<설비 고장 분석기 실행.bat>)를 더블클릭합니다.
2. 파일 탐색기에서 Excel 파일 하나를 실행 창의 **Excel 파일을 여기에 끌어놓으세요** 영역에 놓습니다. **파일 선택** 버튼으로도 열 수 있습니다.
3. 브라우저가 열리면 선택한 파일을 확인하고 **분석 실행**을 누릅니다.

다른 파일을 열려면 실행 창에서 `Ctrl+C`로 종료한 뒤 같은 실행기로 다시 선택합니다.

### 처음 설치

Python 3.11~3.13과 Node.js 22 이상이 설치된 상태에서 저장소 루트의 PowerShell에서 한 번 실행합니다.

```powershell
python -m venv web-v2/.venv
.\web-v2\.venv\Scripts\python.exe -m pip install -r web-v2/requirements.txt
npm.cmd --prefix web-v2/frontend ci
npm.cmd --prefix web-v2/frontend run build
```

### 터미널에서 파일 지정 또는 브라우저 업로드

터미널에서 열 파일을 직접 지정할 수 있습니다.

```powershell
.\web-v2\.venv\Scripts\python.exe web-v2/run.py --open --source examples/demo_input.xlsx
```

브라우저에서 파일을 업로드할 수 있는 환경에서는 아래 명령이나 [보조 실행 파일](scripts/start-web.bat)을 사용합니다.

```powershell
.\web-v2\.venv\Scripts\python.exe web-v2/run.py --open
```

## macOS 또는 Linux에서 시작하기

```sh
python3 -m venv web-v2/.venv
web-v2/.venv/bin/python -m pip install -r web-v2/requirements.txt
npm --prefix web-v2/frontend ci
npm --prefix web-v2/frontend run build
web-v2/.venv/bin/python web-v2/run.py --open
```

Linux에서 Excel 보고서에 들어가는 한글 차트 이미지가 깨지면 서버에 NanumGothic 글꼴을 설치합니다. Debian과 Ubuntu에서는 `fonts-nanum` 패키지에 들어 있습니다.

## 사용하기

1. 고장이력의 `.xlsx` 또는 `.xlsm` 파일을 엽니다. 파일 크기 상한은 100 MiB입니다. 연습용으로 [예제 입력](../examples/demo_input.xlsx)을 사용할 수 있습니다.
2. 시트·헤더·열 매핑과 분석 조건을 확인한 뒤 분석합니다.
3. 집계와 추이를 확인하고 검색과 필터로 상세 이력을 찾아 원문과 분류를 검수합니다. 임시 분류 선택은 표준화 실행 시 일괄 확정됩니다.
4. 보고서를 브라우저에서 내려받습니다. `.xlsx`는 일반 Excel 형식이고, `.xlsm`은 기존 Excel 검색 및 차트 연동용 VBA가 포함된 형식입니다. 웹 화면에서의 조회와 검수는 브라우저에서 실행됩니다.

확정한 보정과 웹 설정은 기본적으로 `web-v2/.data/config/`에 저장됩니다. 업로드 파일은 작업 중에 같은 데이터 폴더에 임시 보관합니다. 데이터 폴더를 바꾸려면 실행 전에 `EFA_WEB_DATA_DIR` 환경 변수를 지정합니다. 웹 포트는 `run.py --port 3100`처럼 바꿀 수 있습니다. FastAPI의 내부 포트는 `8765`입니다.

웹 버전을 시작할 때 기존 데스크톱 프로그램에 저장된 설비·라인 명칭, 그룹, 공장과 팀을 기본값으로 불러옵니다. **기준정보 · 설정 → 명칭 관리**에서 항목을 바꾸고 **명칭 저장**을 누르면 웹에서 입력한 값이 우선합니다. 입력을 비우고 저장하면 해당 항목은 기존 기본값으로 돌아갑니다.
