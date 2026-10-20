# v1.9.0 화면 구조 및 그리드 직접 수정 검증 (2026-10-20)

- 확정 소스 전체: `python -m pytest -q -W error::DeprecationWarning` → **401 passed (141.13s)**, 실제 Python 종료 코드 0. 실행 전후 core/gui/report/tests 소스 SHA256 불변 확인. 새 그리드 23개·창 통합 11개 회귀 포함.
- 사용자 이미지에 따라 최상위 7개 탭을 종합현황 / 검토필요 / 상세분석 / 설비별 유형순위 / 부품별 포함 건수 / 월별 부품 추이 / 그래프로 정리. 상세분석에 설비별·라인별·유형별을 묶고 교차분석·전체 기록·원본 확인 기능도 보존.
- 검토·전체 기록 그리드의 기본 9개 열을 대·중·소분류 → 원본 설비명·비가동 코드(중)·비가동 코드(소)·고장내용/비고 → 유형조합·조합판정 순으로 배치. 원본 4열은 2단 헤더로 묶고 읽기 전용. 일자·정지시간·검토 근거 등은 추가 열 표시로 확인.
- 선택 행 수동 수정 버튼과 메인 화면의 별도 CorrectionDialog 진입 제거. 분류 3개 열은 계층별 목록에서 직접 선택하며 상위 변경 시 하위를 비움. 완전한 경로만 원자적으로 저장하고 미완성 선택은 노란색으로 표시. 같은 값 재선택은 기존 자동분류를 확정하지 않음.
- 유형조합 셀의 비모달 편집기에서 단일·복수 유형을 명시적으로 적용·취소. 분류 보정만 해제하면 시간·일자·대상설비·제품 보정은 유지. 행 우클릭에서 전체 보정 해제도 가능.
- 일반 셀 Enter·포커스 이동 저장, Esc 취소, 잘못된 일자·음수/비유한 시간 거절, 빈값의 해당 보정만 해제, 단일↔복수 전환, 저장 실패 후 재시도 검증. 시간·일자만 수정하면 분류를 확정하지 않음.
- 정렬·검색 후 실제 event_id에 저장하는 통합 검증. 수정 후 재집계하면서 탭·필터·정렬·열 너비·스크롤·행 위치 유지. 검토가 끝난 행이 빠지면 다음 행 선택. 이전 보고서 열기 링크 무효화.
- 처리 중·갱신 대기 중의 추가 저장 차단. 저장 파일 잠김은 기존 모델·결과·파일 보존. 저장 성공 후 분석 갱신 실패 시 저장값은 유지하고 이전 결과 편집을 잠그며 재분석으로 복구.
- 실제 Qt delegate의 Enter·포커스 이동 경로를 포함한 GUI 통합 47개 검사 통과. 전체 Ruff 정적 검사·서식 검사(78파일), 문법 검사, `git diff --check` 통과.
- 실제 2026년 자료로 1430×940 및 최소 1050×690 화면을 렌더 검수. 요청한 창 크기를 그대로 유지하며 모든 주요 탭·버튼 표시. 기본 창의 표 viewport 1333×566에서 9개 기본 열의 가로 스크롤 최대값 0. 최소 창의 표 viewport 953×285에서 5행 이상 표시.
- 분석 완료 후 파일·분석 조건 패널을 자동으로 접어 표 공간 확보. 버튼으로 언제든 펼칠 수 있고 파일 재등록 시 다시 펼침. 글꼴 누락 문자를 제거하고 Qt 목록 아이콘 사용. 기본 6/58/237 분류와 비점수 판정 유지. 시각 검수 중 원본 415건·검토 86건 및 원본 파일·보정 파일 불변 확인.
- 사용자 안내서 v1.9.0 22페이지 갱신. 237개 소분류 목록 보존, 전체 페이지 렌더 및 새 탭·직접 수정·보정 해제 안내 페이지 시각 검증.
- 최종 실행파일 `EquipmentFailureAnalyzer_v1.9.0.exe`: **87,779,496 bytes**, SHA256 `939dab2f7b312aeffa7daef6f38959d3039f2eb42fd7fe7a2fbc3d25b795a422`. 내장 프로젝트 모듈 44개가 최종 소스와 일치하고 설정 11개는 바이트 일치. 새 탐색·그리드 편집·그룹 헤더 모듈 및 7개 주 탭 포함, 메인 화면에 이전 수정 버튼·수정 대화상자 참조 없음 확인.
- 격리 프로필로 237개 분류·schema 3·최소 규칙 버전 1.8 설치 및 17.3초 시작 관찰(초기화 후 8초 유지), 오류 로그 없음. 기존 실행파일 6개 SHA256 불변 확인.
- 검증 자료: `output/ui_1_9_0/`, `output/ui_redesign_1_9_0/`.

# v1.8.0 제공 카탈로그 운영 적용 검증 (2026-10-20)

- 확정 소스 전체: `python -m pytest tests -q -W error::DeprecationWarning` → **367 passed (136.33s)**, 실패·오류·건너뜀 0개. Python 실제 종료 코드 0과 stderr 빈값을 별도 기록한 최종 재검증까지 완료.
- Ruff 정적 검사·서식 검사(73파일), core/gui/report/tools 문법 검사, `git diff --check` 통과.
- 사용자 첨부 `Classification_Catalog_2025_2026.xlsx`의 237개 대·중·소 경로와 기본 규칙·신규 사용자 설정·기존 활성 사용자 설정·실제 Qt 목록을 집합 대조: **대분류 6개 / 중분류 58개 / 소분류 237개**, 누락·추가 경로 없음.
- 첨부 SHA256 `6c4158911b05e5e438cdd97c158b2287ada7b9c4a3f7092a302917726b488f30`. 첨부와 두 원본 자료는 변경하지 않음.
- 펌프 목록은 `도징펌프 / 로터리펌프 / 부스터펌프 / 펌프(종류 미상)`이며 신규 선택 목록에 `펌프 이상` 없음. 센서·벨트·실린더와 전체 237개 경로의 상하위 목록 연동 및 직접 입력 불가 검증.
- 모든 기본 규칙은 component 역할. 237개 정식 부품명과 교체 표현이 해당 경로로 분류됨. 종류를 특정할 근거가 없는 TC·WAGO 번호·모호한 커넥터는 세부 유형으로 추정하지 않음.
- 점수·임계값 방식은 사용하지 않으며 기존 조건 일치·결정 규칙과 복수 고장 조합 집계를 유지. 수동 단일·복수 확정, 시간만 수정, 구분류 수동값의 해당 기록 보존 검증.
- 실제 사용자 프로필에서 이전 기본 규칙 67개를 새 237개로 이관하고 전환 전 설정 백업. 수동 보정·설비명·별칭·컬럼 설정은 바이트 그대로 보존. 범위 밖 사용자 규칙은 내용·우선순위를 보존하여 비활성화하며, 범위 안 사용자 규칙은 유지.
- 같은 catalog_id의 별칭·설명 갱신에도 사용자 삭제·비활성화 보존, 새 기본 규칙 추가, 기존 기본값 업데이트, 구버전 캐시 덮어쓰기 이후의 사용자 삭제 보존을 검증. 이관 실패는 완료 기록 없이 오류 표시하고 재시도 가능.
- schema 3·최소 버전 1.8.0으로 이전 규칙 리더 차단. 최종 활성 프로필은 237개 기본 규칙 digest를 별도 보관하며 두 번째 시작 시 변경 없음.
- 새 목록으로 원본 전수 재분석한 결과는 아래와 같음. 이전 v1.7.2의 67개 운영 분류와 분류 범위가 달라 검토 감소나 정확도 향상을 뜻하지 않음.

| 원본 | 고장 기록 | 정지시간(분) | 규칙분류 | 분류 검토 | 미분류 | 전체 검토 |
|---|---:|---:|---:|---:|---:|---:|
| 2025년 | 532 | 34,168 | 396 | 39 | 97 | 136 |
| 2026년 | 415 | 18,339 | 329 | 50 | 36 | 86 |

- 원본 기록 수·정지시간 합계 보존. 비수동 분류의 모든 구성원은 제공된 237개 경로 안에 있으며 숫자 점수 필드 없음.
- 실제 2026년 Excel 보고서의 고유 기록 ID·원본 행·날짜·시간을 원본 415행과 독립 대조. 설비·라인·유형 집계가 각각 415건·18,339분으로 일치하고 부품 포함 421건은 월별 포함 건수와 일치. 부품 포함 건수는 비가산 지표이며 정지시간을 중복 배분하지 않음.
- Excel 상세 415행·검토 86행·분류기준 237행, 전체 셀 오류 0개. 수식 캐시 검증에서 빈 결과는 자료 없는 일자의 의도된 빈 문자열로 확인. 상세 행 높이 42~138pt로 한도 이내. 실제 PDF 31쪽 중 요약·분류 근거·부품 집계 설명 페이지를 렌더 확인.
- 사용자 안내서 v1.8.0 20쪽 갱신. 중분류 58행의 소분류 237개가 원본 목록과 정확히 일치하고 PDF에도 모두 포함됨. 주요 페이지 시각 검증 완료.
- 최종 실행파일 `EquipmentFailureAnalyzer_v1.8.0.exe`: **87,745,444 bytes**, SHA256 `d90c37da1dce8c8a2c7d607ce1d8c1fb3cc47c2a98ca5cdd588ff362a401a2fe`.
- 내장 core/gui/report 및 version 코드 객체가 최종 소스와 일치하고 config 11개 파일은 바이트 일치. 카탈로그·이관 모듈 포함, 삭제한 점수 모듈 3개 미포함. 격리 실행으로 6/58/237 경로와 schema 3 설치 및 18.4초 시작 관찰 중 오류 없음 확인. 기존 실행파일 5개 SHA256 보존.
- 검증 자료: `output/catalog_application_20261020/`, `output/catalog_activation_1_8_0/`.

# v1.7.2 규칙 판정 복원 검증 (2026-10-20)

- 확정 소스 전체: `python -m pytest -q -W error::DeprecationWarning` → **295 passed (93.68s)**.
- Ruff 정적 검사·서식 검사(69파일), 문법 검사, `git diff --check` 통과.
- 숫자 점수·점수 차이·임계값 판정과 설정 화면 제거. 이전 저장 임계값은 결과에 영향을 주지 않으며 사용자 설정 파일을 덮어쓰지 않음.
- 부품·증상 조건 일치, 교체·고장·원인·MES 단서, 세부 규칙 우선순위 복원. 동일 부품의 동률 충돌·명시적 대안·독립 복수 고장은 검토 유지.
- 정상·부정·예정 표현 제외, 복합명사, 독립 고장 구성원, 조합 식별자, 수동 보정·목록 선택·시간만 수정하는 동작 검증.
- 제공된 2026년 원본 415행을 이전 분석 결과의 모든 기록 ID·정지시간과 대조: **65건 → 47건 검토**, 기존 검토 18건 해소, 신규 검토 0건. 복수 고장 45건과 규칙 충돌 2건은 검토 유지.
- 2025년 원본 532건도 재분석: 규칙분류 393건, 분류 검토 57건, 미분류 82건. 총검토 139건이며 2026년과 원문 범위가 다름.
- 두 원본 SHA256 및 운영 설정·규칙·수동 보정 파일 불변 확인. 새 237개 소분류 목록과 대·중 한 쌍+소분류 복수 시범안은 운영 규칙에 적용하지 않음.
- 실제 2026년 보고서: Excel 17시트·48열·수식 7,622개, 오류 셀·깨진 참조 0개. 415행 판정사유·후보근거와 분석 결과 전수 일치. 긴 후보 행의 최대 필요 높이 151pt로 Excel 한도 409pt 이내.
- 실제 PDF 31쪽 전체 렌더, 규칙 설명과 검토 근거 확인. 이전 점수 결과는 재분석 전 자료로 명시하며 새 규칙 판정으로 바꾸어 표시하지 않음.
- 사용자 안내서 v1.7.2 20쪽 재생성 및 주요 페이지 시각 검증 완료.
- 최종 실행파일 `EquipmentFailureAnalyzer_v1.7.2.exe`: **87,683,726 bytes**, SHA256 `7055aeb49a64a41e7538541d2054b7fab2c6d23363dcd1fbba2bd9855f25ea75`.
- 핵심 내장 모듈 11개가 확정 소스와 일치. 삭제한 점수 모듈 3개 미포함. 격리 프로필로 15.9초 시작 검사 및 오류 로그 없음 확인. 기존 실행파일 4개 보존.
- 검증 자료: `output/rollback_1_7_2/`, `output/rules_report_validation/`.

# v1.7.1 분류 선택 목록 검증 (2026-10-19)

- 전체 회귀 검사: `python -m pytest -q -W error::DeprecationWarning` → **355 passed (100.83s)**.
- Ruff 정적 검사·포맷 검사와 `git diff --check` 통과.
- 대→중→소 목록 연동, 비활성 규칙 제외, 실제 사용자 규칙 재읽기, 기존값 보존 검증.
- 복수 유형 행 추가·삭제, 중복·미완성 선택 차단, 명시적 확정·전환·해제 및 시간만 보정 검증.
- 현재 사용자 규칙과 기본 규칙의 계층 목록 일치: 대분류 6개 / 중분류 경로 66개 / 소분류 경로 67개.
- 실제 사용자 규칙 67개 경로를 수정 화면에 불러오는 검증과 한글 화면 배치·저장 버튼·스크롤 확인.
- 사용 설명서 20페이지 재생성. 수정 화면 안내와 전체 목록 안내 페이지 렌더링 확인.
- `EquipmentFailureAnalyzer_v1.7.1.exe`: **87,691,470 bytes**.
- SHA256: `86ccf6ba7197c5ed49f0191d2cfafa144e74a97509cd73146ecaa1fcc4a6909c`.
- 새 목록 UI·분류 목록 모듈의 EXE 포함 및 내장 버전 1.7.1 확인. 격리 프로필로 18.2초 시작 관찰, 오류 로그 없음.
- 자동분류 점수·복수 고장 판정·집계 정책은 변경하지 않음.

# v1.7.0 복수 고장 조합 검증 (2026-10-15)

환경: Windows 11, Python 3.13.12. GUI 및 EXE는 QT_QPA_PLATFORM=offscreen으로 검증.

- 최종 소스 전체: `python -m pytest -q -W error::DeprecationWarning` → **345 passed (98.16s)**.
- Ruff 정적 검사·포맷 검사와 `git diff --check` 통과. 기본 규칙 67개 유효.
- 순서 무관 조합·유형 중복 제거, 실제 독립 고장과 동일 부품 대안·반복 언급 구분.
- 또는/혹은/아니면/인지 쌍/영문 or의 대안 그룹을 하나의 잠정 후보로 묶고 강제 검토.
- 대안 그룹 옆의 독립 고장 보존, 단순 점검·예정 정비·위치 표현·공유 증상·제품 손상 결과의 과다 구성 방지.
- 실자료 원문 7건의 과다 구성원 회귀와 제품/믹스가 실제 부품 수식어인 경우 등 반례 검증.
- 단일/복수 수동 확정 상호배타, 재열기·시간만 보정·전환·해제·잘못된 저장 입력의 원자성 검증.
- 구조화된 구성원 JSON의 설비명 투영 및 원본 보존, GUI 한글 표시·근거 표시·월별 시간순 복원 검증.
- 사용자확정/잠정 포함 건수 분리, 월별 분모·빈 월·결측 날짜·비고장·미분류 분모·빈 결과 검증.
- 장문 구성 유형 40개의 시작/끝 식별자 80개가 PDF에서 생략 없이 보존되는 회귀 통과.
- 마지막 PDF 간격·중복 안내 정리는 관련 29개 및 추가 3개 회귀 후 전체 345개로 재검증.

실제 원본 11,075행 / 고장 **414건 / 18,328분**을 v1.6.0과 대조했습니다.
기록 ID·원본 행·개별 정지시간과 전체 합계가 모두 같습니다. 사용자 삭제 sample 파일은 복원하지 않고
Git 원본을 임시 검증 입력으로만 사용했습니다.
원본 SHA-256: `02d90c7f0ae154b574ba4e667f79e78da7a172bd03ad56d1928e7932c118362a`.

최종 점수 기준은 기존 최소 75 / 격차 12입니다.

| 결과 | 건수 |
|---|---:|
| 자동분류 | 318 |
| 분류 검토필요 | 96 |
| 미분류 | 0 |
| 구성 유형 2개 이상인 잠정 조합 기록 | 36 |
| 서로 다른 조합 | 28 |
| 부품·유형 포함 기록 수 (비가산) | 454 |

잠정 조합 36건의 정지시간 1,668분은 조합별 집계에만 한 번 반영됩니다.
부품별 포함 건수에는 정지시간 열이 없습니다. 포함 비율 합계는 109.66%이며
한 기록에 여러 유형이 포함되므로 정상적인 비가산 지표입니다. 잠정검토 건수는 별도로 표시합니다.
전체 414개 설명에서 priority 역전 시 점수와 복수 판정 차이는 0건입니다.
이는 정확도 평가가 아니며 원문·사용자 확인이 필요한 유형은 검토 상태로 유지합니다.

최종 실제 보고서: Excel **17시트**, 기존47개 상세열 뒤 구성5개열로 **52열**.
상세414행·검토96행·부품62행·월별부품620행을 분석 결과와 대조했습니다.
숫자 점수·구성원·조합 식별자·사유별 건수·18,328분 합계가 일치하고, 수식7,636개 / 오류 셀0개입니다.
부품별16/17시트는 분석 시점 정적 스냅샷임을 표시합니다.
PDF **31페이지**, 사용자 안내서 **20페이지**를 전체 렌더링했습니다.
짧은 안내·중복된 상세 참조만 다음 페이지로 밀리는 현상을 정리했고 보정창도 실제 글꼴로 확인했습니다.

배포 파일: `EquipmentFailureAnalyzer_v1.7.0.exe` / **87,682,019 bytes**.
SHA-256: `0124025e02f6b01f1695b9d0234e6ba04b2e07cf4aa178c5264f463df25d43a5`.
조합·부품 집계 모듈을 포함한 핵심12모듈, 최종 대안/예정 정비 및 PDF 출력 코드 포함을 확인했습니다.
외부 도구 ICU/libheif DLL 혼입0개. 격리 프로필에서 EXE를 실제 시작해 17.3초 관찰했고
설정·잠금·로그 생성 및 Traceback/시작 오류 없음, stderr 빈값을 확인했습니다.
다른 PC의 대화형 사용은 이번 검증 범위에 포함하지 않았습니다.

최종 로그·검증 요약·검증 보고서는 Git 제외 경로 `output/combination_validation/`에 있습니다.
아래는 이전 버전의 검증 기록입니다.

---

# v1.6.0 점수 기반 분류 검증 (2026-10-15)

환경: Windows 11, Python 3.13.12. GUI 및 EXE 시작 검증은 QT_QPA_PLATFORM=offscreen.

- `BUILD_EXE.bat` 전체 검사: Ruff 정적 검사·포맷 검사 통과, **254 passed (64.38s)**.
- 최종 유형별 0~100점 순위, 동일 유형 중복 규칙 가점 방지, priority 점수 미반영 확인.
- 점수·격차 경계값, 동점(최소 격차 0 포함), 부정·제외, 복합명사, MES 부위 근거 검증.
- 독립 고장 접속어에서 인과/이어짐 종료, 독립 fallback 보존, 동일 부품의 원인 근거 공유 회귀.
- `first_failure=True`인 이전 프로필도 동점·복수 고장 검토를 우회하지 않음.
- 임계값 저장의 입력 검증·원자적 저장, 수동 분류 시 점수 제거, 시간만 보정 시 점수 유지 검증.
- GUI 설정·상세·보정 화면, Excel 숫자 점수/빈값, PDF 기준 스냅샷, 이전 결과 출력 호환 검증.

실제 MES 원본 11,075행을 이전 엔진과 새 엔진으로 각각 분석했습니다.
기록 ID·원본 행·414건의 개별 정지시간과 합계 **18,328분**은 모두 동일합니다.
원본 SHA-256: `02d90c7f0ae154b574ba4e667f79e78da7a172bd03ad56d1928e7932c118362a`.
사용자가 삭제한 sample 파일은 복원하지 않았고 Git 원본의 검증용 임시 복사본만 사용했습니다.

| 판정 | 이전 엔진 | 점수 엔진 (최소 75 / 격차 12) |
|---|---:|---:|
| 자동분류 | 403 | 312 |
| 분류 검토필요 | 11 | 102 |
| 미분류 | 0 | 0 |

새 검토 사유: 점수 부족 34건, 후보 접전 17건, 복수 고장 51건.
잠정 1위 유형이 바뀐 20건은 모두 검토필요이며, 자동 확정된 유형 변경은 0건입니다.
전체 414개 설명에서 priority를 역전해도 유형별 점수와 복수 고장 판정 차이는 0건입니다.
이는 분류 정확도 측정이 아닙니다. 75/12는 초기 기준이며 사람이 확정한 자료로 조정해야 합니다.

실제 자료 CLI 전체 실행으로 Excel 15시트와 PDF 31페이지를 생성했습니다.
상세 414행·검토 102행, 점수 숫자/빈값 1,242셀을 분석 결과와 대조했고 오류 셀은 0개입니다.
기존 수식 7,006개와 기준 열 위치를 유지했습니다. 새 판정 기준과 검토 근거 페이지를 포함해
PDF 전체를 렌더링·점검했습니다. 사용자 안내서도 v1.6.0 19페이지로 재생성·렌더링했습니다.

`EquipmentFailureAnalyzer_v1.6.0.exe` 빌드 완료: 87,654,003 bytes.
SHA-256: `aee7ad0e7744ca2b7460a9165fe3d58e534f21c4e57c7988cfb1f6bc85399d02`.
점수 엔진·GUI 설정·보고서 점수 모듈 및 분리한 공통 모듈 10개 포함을 확인했습니다.
외부 도구의 ICU/libheif DLL 혼입은 0개이며, 격리된 새 설정으로 실제 EXE를 시작해
17.7초 관찰했습니다. 시작 종료/Traceback 없이 기본 점수 설정·설정 파일·잠금 파일이 생성됐습니다.
다른 PC의 대화형 사용은 이번 검증 범위에 포함하지 않았습니다.

빌드 로그·검증 요약·검증 보고서는 Git 제외 경로 `output/scoring_validation/`에 있습니다.
아래는 이전 리팩토링과 릴리스의 검증 기록입니다.

---

# 리팩토링 검증 (2026-10-15)

환경: Windows 11, Python 3.13.12, pandas 2.3.3, numpy 2.5.4,
PySide6 6.12.0, reportlab 4.5.1. GUI 테스트는 QT_QPA_PLATFORM=offscreen으로 실행.

- 변경 전: 121 passed (52.82s).
- 통합 후: `python -m pytest -q -W error::DeprecationWarning` → **157 passed** (63.38s).
- BUILD_EXE.bat의 전체 재검증: **157 passed** (65.23s).
- `python -m ruff check .` 및 `python -m ruff format --check .` 통과.
- `python tools/make_rules.py --dry-run` → 67 rules valid.
- 코어 함수·클래스의 AST 비교로 계산식과 기록 ID 로직의 보존 확인.
- 이전 버전 설정 병합, 분류 규칙 스키마, 기존 import 경로 호환성 회귀 유지.

실제 MES 자료를 Git HEAD의 원본 코드와 리팩토링 코드로 각각 격리된 프로필에서 분석했습니다.
원본 11,075행 / 고장 414건 / 정지시간 18,328분 / 검토필요 11건으로 동일합니다.
전체 기록, 선택 기록, 모든 집계표, 지표, 안내문과 설정 해시를 JSON 스냅샷으로 비교해
차이가 없음을 확인했습니다. 원본 Excel의 SHA-256도 그대로 유지됐습니다.

CLI에서 실제 자료로 Excel + PDF 생성까지 완료했습니다.
Excel 15개 시트, 수식 7,006개, 오류 셀 0개; PDF 30페이지.
사용자 안내서는 19페이지로 재생성했으며 전체 렌더링을 확인했습니다.
보고서 PDF 전체 30페이지도 렌더링하여 표·차트·페이지 구성을 점검했습니다.

신규 회귀 범위: CLI 잘못된 인자와 사용자 오류, 공유 파싱/집계 API,
규칙 저장 교체 실패, 설비 코드 결측값, 보정 저장 호환,
정지시간 결측 요약, 차트 렌더링 재사용, Workbook·버퍼 정리,
시트/제목 행 변경, 재분석 후 보고서 링크, 차트 오류 문구 초기화.

EXE 빌드와 시작 검증도 완료했습니다(87,632,108 bytes).
첫 패키징에서는 외부 PATH의 Poppler ICU DLL이 OS ICU 대신 포함돼 QtCore가 시작하지 못했습니다.
EXE spec의 DLL 검색 PATH를 가상환경·Python·Windows로 제한한 후 재빌드했습니다.
새 패키지의 외부 도구 DLL 0개, Qt/Shiboken 의존성 누락 심볼 0개를 확인했습니다.
분리한 7개 모듈이 EXE에 포함됐고, 격리된 임시 설정으로 offscreen 시작 검증을 통과했습니다.
다른 PC에서의 대화형 사용은 이번 검증 범위에 포함하지 않았습니다.

로컬 검증 결과와 빌드 로그는 output/refactor_validation/에 저장되며 Git에서 제외됩니다.
이 아래는 리팩토링 전 릴리스 검증 기록입니다.

---

# v1.5.0 validation (2026-10-15)

Environment: Windows 11, Python 3.13, pandas 2.3.3, numpy 2.5.4, PySide6 6.12.0, reportlab 4.5.1.

`python -m pytest -q -W error::DeprecationWarning` (QT_QPA_PLATFORM=offscreen): **121 passed**, GUI tests included, no warnings.
Repeated runs pass on this PC with the project-local temp folder (pytest.ini).
New in tests/test_v15.py and tests/test_gui.py: classification engine cases, clause-end restoration,
MES target pattern and review policy, review guidance per issue, work-date/stop-time corrections,
correction patch (changed fields only, removal), defaults merge on a real v1.4.0 profile
(untouched defaults updated, user edits/deletions kept, typo fix, idempotent), saved column mappings,
correction re-keying, unchanged record-ID formula, encoding-typo guard, correction dialog and rule editor.

## Real MES export (라인 비가동 현황 조회_261014.xlsx)

11,075 source rows, 414 faults, 18,328 minutes. The source file hash was unchanged.

| Step | Review rows | Unclassified | Multiple candidates | Target missing |
|---|---|---|---|---|
| v1.4.0 | 300 | 141 | 47 | 217 |
| Target pattern fixed (1P/2P/3P) | 230 | 141 | 47 | 57 |
| Target missing reviewed only for target basis | 188 | 141 | 47 | 57 (info) |
| Normalization + clause-end restoration | 193 | 137 | 56 | 57 (info) |
| New engine (pairing + evidence-based resolution) | 153 | 149 | 4 | 57 (info) |
| Rules 29 -> 67 | **11** | 0 | 11 | 57 (info) |

During rule development the full list of automatic classifications was read and judged by hand once,
and every later rule/engine change was checked row by row against the previous run. The remaining 11
review rows mention two parts or two events.

Excel + PDF from the real file: 15 sheets, 7,006 formulas, 0 error cells. 428 formulas cache an empty
string by design (daily trend rows with no records; identical in the v1.4.0 output). PDF 30 pages.
CLI end-to-end time about 46 s.

## Old-program guard

A report generated on 2026-10-15 09:59 showed 344 review rows (320 multiple candidates). It was produced by the
v1.4.0 EXE reading the v1.5.0 rules from the shared user profile; the v1.4.0 source with the same profile
reproduces 344 / 320 / 86 / 8 exactly, while v1.5.0 gives 11. Rules are now saved in format v2:
- the v1.4.0 source stops at startup with "이 분류 규칙은 v1.5.0 이상 전용입니다 …" for the bundled rules and for
  a real profile after v1.5.0 has opened it once;
- v1.5.0 converts an older-format profile on first start (status bar message), no change on the second start.

## EXE

BUILD_EXE.bat ran end to end on this PC (tests 118 passed, PyInstaller) and produced
EquipmentFailureAnalyzer_v1.5.0.exe (about 90 MB); it started headless and converted a copy of the user
profile. Interactive use on other PCs was not verified here.
