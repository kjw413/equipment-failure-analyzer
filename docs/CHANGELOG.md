# v1.10.0 - 규칙 미일치 보완과 판정 정리

- 복수 고장으로 의심돼도 부품별로 묶은 결과 고장·교체 근거가 있는 유형이 하나뿐이면 규칙분류. 일부만 겹치는 부품명은 같은 부품군이면 구체적인 규칙, 다른 부품군이면 뒤쪽 중심어를 사용('몰드체인 연결핀' → 체인연결핀).
- 나열된 부품 이름 안의 짧은 부품명('솔밸브' 안의 '밸브')이 앞 부품의 증상 연결을 끊거나 후보를 밀어내던 문제 수정.
- 'A 및 B 마모', 'A, B 교체'처럼 하나의 고장·교체 표현으로 나열한 부품은 복수 유형 조합으로 규칙분류(판정 열 '복수 · 자동'). '와/과' 연결, 의심·추정 표현, 결과로 빠진 교체 부품이 있으면 검토필요 유지. 공통 증상을 받는 나열 부품을 서로의 원인·결과로 보지 않음.
- '미분류'를 비가동코드(중·소)가 비어 있으면 '비가동코드 미기입', 입력돼 있으면 '규칙 미일치'로 구분. 두 상태 모두 검토필요 탭에 표시. 유형 구성 방식의 '미분류'는 '유형 없음'으로 표시.
- 고장내용에 부품명이 없으면 비가동코드(소)의 부품명으로 다시 판정.
- 부품 후보가 하나도 없을 때만 적용하는 nopart 규칙 추가. 새 분류 공정·운전 / 제품·자재(제품 걸림·막힘, 제품 낙하, 자재 불량)와 부품 언급 없는 WAGO 에러 번호·통신 이상 → 제어기(종류 미상).
- 증상어(뒤집, 온오프, 전원종료, 전원차단)와 별칭(부스터 펌프 베어링 → 부스터펌프, 리드 씰링 → 리드씰러) 보완.
- 카탈로그 대분류 6개·중분류 59개·소분류 240개, 기본 규칙 241개(component 237, nopart 4). 규칙 파일 schema 4, 최소 v1.10.0으로 이전 실행파일의 해석 차단.
- 2026년 실제 기록 415건: 규칙 미일치 24 → 8건(생산팀 협의 보류 6건, 미확인 용어 2건), 검토필요 탭 86 → 59건. 이미 분류되던 기록은 변경 없음.

# v1.9.0 - 결과 탭 정리와 표에서 직접 수정

- 결과 영역을 종합현황·검토필요·상세분석·설비별 유형순위·부품별 포함 건수·월별 부품 추이·그래프의 7개 탭으로 정리.
- 설비명 변환·분류기준·설정 폴더를 상단 [기준정보 · 설정] 메뉴로 통합.
- 파일을 불러오면 등록 영역을 작게 표시하고 [다른 파일 선택] 제공. 분석표 공간을 확보하며 초기화 시 원래 등록 화면 복원.
- [파일 · 분석 조건] 접기 패널 제공. 파일 등록 시 펼치고 분석 완료 시 자동으로 접으며 파일명·건수·설비 기준 요약 유지.
- 상세분석에 설비별·라인별·유형별 분석과 전체 기록·교차분석·원본 확인을 배치하여 기존 분석 기능 보존.
- [선택 행 수동 수정] 버튼을 제거하고 검토필요·전체 기록 표의 셀에서 직접 보정. 분류는 계층별 선택 목록과 단일·복수 유형 편집으로 확정.
- 검토 표 앞에 대·중·소분류를 배치하고 원본 설비·원본 분류·비고를 함께 확인하도록 열 구성 개선.
- 일반 값은 Enter·포커스 이동으로 저장하고 분류 편집은 적용·취소 제공. 시간·일자만 보정하면 분류를 확정하지 않는 기존 정책 유지.
- 행 우클릭 메뉴에서 단일·복수 분류 편집, 분류 보정 해제, 해당 기록의 수동 보정 전체 해제 지원.
- 기록 ID에 보정을 연결하고 저장 후 분석 결과 갱신. 기존 수동 보정·운영 카탈로그·점수 없는 규칙 판정과 보고서 구성 유지.

# v1.8.0 - 운영 분류 카탈로그 적용

- 제공된 분류 카탈로그의 대분류 6개·중분류 58개·소분류 237개를 기본 규칙과 계층별 분류 선택 목록에 실제 적용. 소분류를 구체적인 부품 종류로 정리하고 고장 현상·조치와 분리.
- 기본 활성 규칙 237개를 모두 component로 구성. 부품명과 고장·조치 조건이 모두 일치해야 후보 생성. 증상·약어·브랜드명만으로 세부 부품을 추정하지 않음.
- 첫 카탈로그 전환 시 새 기본 규칙을 설치하고 이전 기본 규칙 퇴역. 목록 밖 사용자 규칙은 내용·우선순위를 보존하여 비활성화하고 범위 안 사용자 규칙 유지.
- 기존 수동 보정 파일은 바이트 그대로 보존. 이전 수동확정값은 해당 기록에서 유지하며 새 목록으로 자동 재해석하지 않음.
- 같은 운영 카탈로그에서는 사용자가 비활성화·삭제한 새 규칙을 복원하지 않음. 전환 실패 시 완료 처리 없이 오류 표시 후 재시도 가능.
- 규칙 파일 schema 3, 최소 프로그램 버전 1.8.0으로 이전 실행파일의 역방향 기본값 병합 차단.
- 점수 없는 조건 일치·결정 규칙 판정과 복수 유형 조합 집계 유지.

# v1.7.2 - 조건 일치와 결정 규칙에 따른 분류로 복원

- 후보 점수와 최소 점수·점수 차이 임계값을 분류 판정에서 제거. 이전 점수 설정값은 사용하지 않음.
- 부품·증상 조건 일치를 기준으로 후보 생성. 제외·부정·예정 표현을 걸러내고 원인 규칙, 구체적인 부품명, 고장·교체 근거, 명시적 인과관계, MES 단서로 후보 해소.
- 해소되지 않은 후보·명시적 대안·독립 복수 고장은 검토필요로 유지. 일치 후보가 없으면 미분류.
- 분류 판정 사유(classification_reason)와 후보별 규칙·근거(candidate_evidence)를 화면과 보고서에 표시.
- 계층별 분류 선택 목록, 수동 단일·복수 확정, 조합 집계와 부품별 추이 유지.
- 새로 정리한 2025·2026 분류 목록은 검토 자료로 유지하며 운영 규칙에는 자동 적용하지 않음.

# v1.7.1 - 행 수정의 계층별 분류 선택 목록

- 대·중·소분류 직접 입력을 현재 활성 규칙에 연결된 선택 목록으로 교체. 상위 분류 변경 시 하위 목록 갱신.
- 복수 유형도 계층별 목록에서 추가·삭제. 완전한 유형 2개 이상과 명시적 복수 확정 조건 유지.
- 활성 규칙에 없는 기존 수동 분류값은 기존값으로 표시하고 시간·일자만 수정할 때 유지.
- 사용자 규칙 편집 내용을 수정 창을 열 때 즉시 반영. 자동분류·점수·집계 정책은 유지.

# v1.7.0 - 복수 고장 유형 조합과 부품 추이

- 독립 고장 근거를 물리 부품별로 묶고 유형 조합으로 기록. 순서 무관·유형 중복 제거·안정된 조합 식별자 제공.
- 같은 부품의 대안/반복 언급·단순 점검·예정 정비·부정·인과 결과를 별개 구성원으로 무조건 포함하지 않음.
- 또는/혹은 등 명시적 대안 관계는 따로 묶어 검토하고 실제 동시 고장과 구분.
- 조합별 유형·설비·기간 집계는 원본 기록 1건과 정지시간 1회 유지. 부품별 시간 임의 배분 금지.
- 행 수정에서 복수 유형 명시 확정·변경·해제 지원. 수동 단일/복수 분류는 상호배타이며 시간만 보정하면 분류 미확정 유지.
- 부품별 포함 건수·월별 부품 추이 화면과 Excel 16/17 시트 추가. 사용자확정·잠정검토를 구분하고 비율 합계100% 초과 가능 표시.
- 기존47개 상세열 뒤 구성필드5개 추가. PDF에 조합 정책·부품별 요약 및 긴 조합명 표시 개선.
- 점수는 최고 단일 후보의 근거이며 조합 전체 확률이 아님을 명시.

# v1.6.0 - 후보 점수 기반 분류

- 최종 유형별 근거 점수(0~100)로 후보를 정렬하며 규칙 priority는 동점 표시 순서에만 사용.
- 기본 자동 기준: 1위 75점 이상, 2위가 있으면 차이 12점 이상. 설정 창에서 변경 가능.
- 점수 부족·후보 접전·복수 부품/고장을 구분해 검토필요 처리. 동점과 복수 고장 보호 유지.
- 부품·증상 관계, 부정·제외 조건, 복합명사 및 원인 연결을 유지하고 중복 규칙 가점 방지.
- 상세·검토 화면, 보정 창, Excel/PDF에 점수와 산정 근거·후보 순위·판정 사유 추가.
- 기존 상세 41개 열 뒤에 점수 6개 열 추가. 기존 수식 기준열·15시트·기록 ID·수동 보정 유지.
- 수동 분류 확정 시 자동 점수를 적용하지 않으며 시간만 수정하면 분류 점수는 유지.
- 점수는 보정된 확률이 아니며 초기 임계값은 사용자 확정 자료로 검증·조정해야 함.

# 리팩토링 (2026-10-15, v1.5.0 소스)

- 규칙 저장·검증, 값 파싱, 공통 집계를 별도 core 모듈로 분리하고 기존 import 경로 유지.
- GUI 조립 메서드 분리, 작업 스레드·테마 분리, 반복 경로 열기 통합.
- 시트/제목 행 변경 시 재읽기 안내, 재분석 시 이전 보고서 바로가기 초기화,
  차트 오류 메시지가 화면 갱신 후 남는 문제 수정.
- 모든 정지시간이 결측일 때 Excel의 nan분·최다 설비 안내 수정.
- 설비별 집계·차트 중복 생성 제거, 숫자 표시·PNG 인코딩·파일 교체 공통화,
  실패 시 Workbook·버퍼 정리 보장. 도넛 설명에 설정한 TOP N 반영.
- pandas.NA 설비 코드가 실제 코드 문자열로 처리되던 문제 수정.
- CLI 인자 검증/실행 분리, 예상 가능한 사용자 오류를 간결한 메시지와 종료 코드 1로 반환.
- scripts/에 배치 도구, tools/에 생성 도구 정리. START.bat과 BUILD_EXE.bat 진입점 유지.
- START_HERE.txt의 중복 안내는 READ_ME_FIRST.txt와 README.md로 통합.
  UPDATE_v1.3.1/v1.4.0/v1.5.0 안내는 이 변경 이력과 사용자 안내서로 통합.
- 테스트 fixture 통합, 개발 의존성 분리, Ruff 정적 검사·포맷 규칙 및 빌드 검사 추가.
- EXE 빌드의 DLL 검색 경로를 격리해 외부 도구의 오래된 시스템 DLL이 섞여 QtCore 시작이 실패하는 문제 수정.
- 분류 기본 규칙 67개, Excel 시트 15개, 기록 ID, 사용자 설정 저장 위치는 유지.

# v1.5.0
- Classification engine: clause-level part/symptom pairing that stops at the next named part; explicit,
  recorded conflict resolution (part rule over fallback, compound-noun head, replaced part, causal phrase,
  MES part code). Ambiguous records stay under review with all candidates.
- Rules rebuilt from real MES remarks: 29 -> 67 rules with a role column (component / fallback / override).
  Fixed '씌러/씌링/씬' typos (should be 씰러/씰링/씰).
- Preprocessing: spelling normalization (multi-pass), restoration of clause-final syllables cut short in the
  MES field ('후크 교' -> '후크 교체').
- MES target pattern accepts every plant prefix (1P/2P/3P), not only '2P I/C'. A missing target is a review
  reason only when equipment is grouped by target; otherwise it is reported as data-quality information.
- Existing user profiles: untouched bundled defaults are merged into the new release, user edits/deletions
  are kept, backup under config/backup. Earlier default fingerprints in config/defaults_history.json.
- Corrections save only changed fields, can be removed per field or entirely; time-only corrections no
  longer confirm a tentative classification.
- Column mappings confirmed by the user are saved per header row and reused; corrections are re-keyed when
  the mapping changes. The record-ID formula is unchanged.
- Fixed i18n typo ('남걁니다'), numpy timedelta deprecation warnings; new quality metric for auto-resolved
  conflicts; rules sheet shows the role column.
- Rules workbook format v2 (rules_v2 sheet + meta schema): programs before v1.5.0 stop with a clear message
  instead of misclassifying with the new rules (old engine + new rules gave 344 review rows). Newer schemas
  are refused with an upgrade message. Existing profiles are converted on first start.
- BUILD_EXE.bat names the EXE with the version (EquipmentFailureAnalyzer_v1.5.0.exe); pytest uses a
  project-local temp folder so repeated test runs and builds work on PCs with a locked system temp.
- Reports default to ./output next to START.bat or the EXE (fallback: user data folder when read-only);
  output/ contents are git-ignored.
- USER_GUIDE now opens with a two-page summary and explains how the program works: processing steps,
  classification principle and decision order, the full type list (6 majors, 67 rules), totals and data model.
  The guide builder wraps Korean text between words and fixes an empty table on the first page.
- Real MES sample (414 faults): review 300 -> 11. 121 automated tests passed (GUI included).

# v1.4.0
- Review reason, correction route and aggregation effect per review row.
- Per-record work-date and stop-time corrections.

# v1.3.1
- Replace implicit text-column GUI sorting with explicit numeric descending defaults.
- Stable ties, missing numbers last in either direction, and a reset-default button ([큰 값순 정렬]).
- Preserve per-equipment ranking blocks. Rank period tables by time, keep trend axes chronological.
- Sort detail/review reports by stop duration without modifying source records or event IDs.
- Remove unused empty-product warning code, data-quality rows and placeholder report sections.
- Preserve existing names, user rules, two-file exports, formulas and donut charts.

# 1.3.0

- One export action now produces Excel + PDF from a single analysis snapshot.
- Data-backed executive summary, comparisons, monthly trend, equipment donuts and review actions.
- Optional report title/department/author/note dialog, persistent per-user settings.
- Staged pair creation, explicit overwrite, rollback on ordinary file-commit failure.
- Previous Excel schema and all 15 sheets retained; no product-analysis sheet.
- ReportLab dependency, launch/build checks and user guide updated.
- 51 automated tests passed; GUI test module skipped (PySide6 unavailable).

# v1.2.0

- Removed product-only report sheet and GUI tab; shifted following sheet numbers.
- All report cell text and chart labels use registered display names.
- Original workbook and stable IDs remain unchanged.
- Added equipment-local type ranks, count/time shares, and complete totals.
- Added 100% donut charts in sheet 02 and chart+ranking blocks in sheet 15.
- Top five plus the entire remainder; unclassified rows remain in the denominator.
- Added native GUI equipment selector and count/time donut preview.
- Replaced onedir build with single-executable Windows build configuration.
- Top-level source launcher: START.bat. It still requires Python.
- No Windows executable was built or tested in this environment.
