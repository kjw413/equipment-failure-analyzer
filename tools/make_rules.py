"""Source of the bundled classification rules (config/classification_config.xlsx).

Edit the rule list below, then run from the project folder:  .venv/Scripts/python.exe tools/make_rules.py
Patterns run on normalized, space-free text of one clause (see core/classifier.py).
Before a release that changes bundled rules, add the previous release's rule digests to
config/defaults_history.json so untouched user copies are recognised and updated.
Users edit their own copy in the program ([분류기준 관리]); this file only defines the defaults.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.classifier import write_rules, validate_rules

FAIL = ('고장|이상|불량|오류|에러|error|트러블|오작동|작동불|작동안|미작동|미가동|미구동|구동불|멈춤|멈춰|'
        '정지|(?<![업셧])다운|불능|안됨|안되|비정상|알람|alarm|fault|trip|트립|문제')
BREAK = '파손|부러|깨짐|깨져|절단|끊어|끊김|찢어|터짐|터져|크랙|crack|금감|휨|휘어|변형|뒤틀|찌그러'
WEAR = '마모|닳|녹|부식|손상|스크레치|스크래치|헐거|유격'
LOOSE = '풀림|풀려|풀어|풀리면|풀리며|풀리고|이탈|빠짐|빠져|탈락|떨어|분리|흔들'
ELEC = '단선|소손|쇼트|short|합선|누전|과부하|과전류|접촉불량|접촉|타버|나감|발열'
LEAK = '누설|누수|누출|리크|leak'
JAM = '걸림|걸리|끼임|끼어|끼여|막힘|막혀|적체|정체|충돌|간섭'
ACT = ('교체|교환|수리|정비|조정|재조정|조절|점검|청소|보수|가공|용접|체결|고정|재조임|세팅|리셋|reset|재부팅|'
       '보강|수정|교정|calibration|영점|분해|조립|급유|도포|a급|신규')

def sym(*groups):
    return '|'.join(groups)

R = []
def rule(id, priority, major, middle, minor, context, symptom, exclude='', role='component'):
    R.append(dict(id=id, enabled=1, priority=priority, major=major, middle=middle, minor=minor,
                  context=context, symptom=symptom, exclude=exclude, role=role))

E, M, P, T, F, W = '전기·제어', '기계', '공압·진공', '온도·냉각', '공정·운전', '유체·배관'

# ---- 전기·제어
rule('SENSOR', 90, E, '센서·검출', '센서·검출 이상/조치',
     '(?:원점|레벨|근접|광|감지|온도|압력|농도|리미트|하강|상승|소진|위치)?센서|sensor|근접|포토|photo|광전|리미트|리밋|감지기|엔코더|encoder|카운터|counter|레벨스위치',
     sym(FAIL, ELEC, BREAK, LOOSE, '감지|미감지|오감지|이중감지|감도|오염', ACT),
     '센서정상|센서이상없|sensorok')
rule('HEATER', 88, E, '히터·온도제어', '히터 이상/교체', '히터|heater|히팅|ssr|점화플러그|버너|burner',
     sym(FAIL, ELEC, BREAK, WEAR, '온도저하|온도이상|저하', ACT))
rule('THERMO', 89, E, '히터·온도제어', 'TC·온도조절기 이상', '(?<![a-z])tc(?![a-z])|열전대|써모커플|thermocouple|온도컨트롤러|온도조절기|온조기',
     sym(FAIL, ELEC, BREAK, LOOSE, ACT))
rule('POWER', 88, E, '전원·차단기', '전원·차단기·퓨즈 이상',
     '퓨즈|fuse|차단기|(?<![탑톱])브레이커|breaker|파워서플라이|파워|smps|전원|정전|서지|surge|변압기|트랜스(?!미터|듀서|퍼)|누전|ups|단자함|단자대',
     sym(FAIL, ELEC, '떨어|발생|온오프|반복|재투입', ACT))
rule('INVERTER', 88, E, '인버터', '인버터 이상', '인버터|inverter|vfd', sym(FAIL, ELEC, ACT))
rule('SERVO', 88, E, '서보·드라이브', '서보 이상', '서보|servo', sym(FAIL, ELEC, '드라이브', ACT))
rule('MOTOR', 86, E, '모터', '모터 이상', '모터|motor', sym(FAIL, ELEC, WEAR, '부하|소음|진동', ACT),
     '모터정상|모터이상없')
rule('CONTROL', 90, E, 'PLC·통신·제어기', 'PLC·통신·제어기 이상',
     'plc|통신|hmi|터치패널|터치스크린|(?<![a-z])pc(?![a-z])|컴퓨터|wago|이더넷|ethernet|네트워크|cpu|메인보드',
     sym(FAIL, '접촉|재부팅|리셋|발생', ACT))
rule('SWITCH', 86, E, '스위치·릴레이', '스위치·릴레이 이상',
     '스위치|switch|릴레이|relay|버튼|비상정지|셀렉트|접점|마그네트|전자접촉기|컨택터|contactor',
     sym(FAIL, ELEC, '물혼입|반응없', ACT))
rule('WIRE', 84, E, '배선·커넥터', '배선·커넥터 단선·소손',
     '배선|케이블|cable|전선|결선|하네스|(?<!에어)컨넥터|(?<!에어)커넥터|connector|슬립링|slipring|단자(?!함|대)',
     sym(FAIL, ELEC, BREAK, LOOSE, ACT))
rule('INSTRUMENT', 86, E, '계측기', '계측기 이상',
     '기록계|유량계|압력계|조절계|트랜스미터|transmitter|트랜스듀서|transducer|게이지|gauge|지시계|레코더|recorder',
     sym(FAIL, BREAK, ACT))
rule('LOADCELL', 87, E, '로드셀·계량', '로드셀·계량 이상',
     '로드셀|loadcell|중량선별기|체크웨어|checkweigher|저울|계량기|무게', sym(FAIL, '감지|영점|calibration', ACT))
rule('PRINTER', 85, E, '날인·프린터', '날인·프린터 이상',
     '날인|프린터|printer|프린트|잉크|ink|마킹|marking|인쇄', sym(FAIL, '번짐|과다|부족|막힘|타이밍|헤드|노즐', ACT))
rule('VISION', 85, E, '검사기(X-RAY·비전)', '검사기 이상',
     'x-ray|xray|엑스레이|비전|비젼|vision|카메라|camera|검출기|금속검출|이물검출', sym(FAIL, ACT))
rule('ROBOT', 70, E, '로봇', '로봇 이상/조치', '로봇|robot|파렛타이저|palletizer',
     sym(FAIL, JAM, LOOSE, '원점|정렬|위치|티칭', ACT))

# ---- 기계
rule('BEARING', 90, M, '베어링', '베어링 손상/교체', '베어링|bearing|로드엔드|볼부싱',
     sym(WEAR, BREAK, FAIL, ELEC, LOOSE, '소음|진동', ACT))
rule('CHAIN', 90, M, '체인', '체인 끊어짐·이탈', '체인|chain|연결핀|체인링크',
     sym(BREAK, LOOSE, WEAR, FAIL, '늘어|뒤집|텐션|걸림', ACT))
rule('GEAR', 88, M, '기어·스프라켓', '기어·스프라켓 마모·파손', '스프라켓|sprocket|(?<!기어드)기어(?!드)|gear|피니언|랙기어',
     sym(WEAR, BREAK, LOOSE, FAIL, ACT))
rule('BELT', 88, M, '벨트·풀리', '벨트·풀리 끊어짐·마모',
     '벨트|belt|폴리|(?<!볼트)(?<!너트)(?<!나사)풀리(?!면서|며|어|고|는|게|지)|pulley',
     sym(BREAK, WEAR, LOOSE, ELEC, FAIL, '텐션|늘어|미끄|끼임', ACT))
rule('REDUCER', 89, M, '감속기', '감속기 이상', '감속기|reducer|기어박스|gearbox', sym(FAIL, WEAR, BREAK, '소음|진동|누유', ACT))
rule('SHAFT', 86, M, '축·커플링·키', '축·키·연결부 이상',
     '(?<![압수0-9])축(?!소|구|하|적|산)|샤프트|shaft|커플링|coupling|아타치|attach|조인트|joint|'
     '(?:구동부|축)키|키(?=이탈|탈락|빠짐|마모|파손|교체|고정부)',
     sym(LOOSE, BREAK, WEAR, FAIL, ACT))
rule('GUIDE', 82, M, '가이드·레일', '가이드·레일 이상', '가이드|guide|레일|rail|슈트|chute|트랙|track',
     sym(BREAK, LOOSE, WEAR, FAIL, JAM, ACT))
rule('ROLLER', 82, M, '롤러·브러쉬', '롤러·브러쉬 이상', '롤러|roller|브러쉬|브러시|브라쉬|brush',
     sym(BREAK, LOOSE, WEAR, FAIL, JAM, ELEC, ACT))
rule('FRAME', 80, M, '프레임·고정부', '프레임·브라켓·고정부 이상',
     '프레임|frame|브라켓|bracket|하우징|housing|커버|cover|스토퍼|stopper|스톱퍼|스탑바|고정부|고정대|받침|패드|블럭|블록|block|플레이트|plate',
     sym(BREAK, LOOSE, WEAR, FAIL, ACT))
rule('FASTEN', 87, M, '체결부(볼트·너트)', '볼트·너트 풀림·파손',
     '고정볼트|고정너트|볼트|bolt|너트|nut|나사|셋트스크류|세트스크류|고정핀|와셔|체결부|체결',
     sym(LOOSE, BREAK, WEAR, ELEC, '나사산|체결불량|불량', ACT))
rule('GRIPPER', 86, M, '그립퍼·후크', '그립퍼·후크 이상/조정',
     '후크|훅|hook|그립퍼|gripper|집게|핑거|finger|조우|jaw|클램프|clamp',
     sym(FAIL, BREAK, LOOSE, WEAR, JAM, '틀어|틀려|위치', ACT))
rule('AGITATOR', 85, M, '교반기', '교반기 이상', '교반기|교반|agitator|임펠러|impeller', sym(FAIL, BREAK, LOOSE, ACT))
rule('CUTTER', 80, M, '커팅부(커터·블레이드)', '커팅부 이상', '컷팅|커팅|cutting|커터|cutter|나이프|knife|칼날|블레이드|blade',
     sym(FAIL, BREAK, WEAR, JAM, ACT))
rule('LUBRICATION', 70, M, '윤활', '윤활 부족·급유', '그리스|윤활|급유|오일(?!펌프)|oil', sym('부족|누유|도포|주입|교체', LEAK, ACT))
rule('CONVEYOR', 60, M, '컨베어', '컨베어 이상/조치', '컨베어|conveyor|버켓|버킷|bucket|인계부',
     sym(FAIL, BREAK, LOOSE, WEAR, JAM, ELEC, '틀어|틀려|원점', ACT))
rule('PUSHER', 75, M, '푸셔·디버터', '푸셔·디버터 이상', '푸셔|pusher|디버터|diverter|게이트|gate',
     sym(FAIL, BREAK, LOOSE, JAM, ACT))
rule('DISCHARGE', 74, M, '배출부(셔터·디스차지)', '배출부 이상/조치', '셔터|shutter|디스차지|discharge|배출부|배출구|엑스트로바',
     sym(FAIL, BREAK, LOOSE, WEAR, JAM, '틀어|틀려|위치', ACT))
rule('STICK', 78, M, '스틱 공급', '스틱 공급·타이밍 이상', '스틱운반컨베어|스틱컨베어|스틱|stick|인서터|인서트',
     sym(FAIL, JAM, BREAK, LOOSE, '원점|타이밍|틀어|틀려|재조', ACT))
rule('SEALER', 76, M, '씰러(실링부)', '씰러 이상/조정',
     '씰러|sealer|초음파|엔드씰|센터씰|탑씰|씰바|endtop|엔드탑|씰링바',
     sym(FAIL, ELEC, BREAK, LOOSE, WEAR, '위치|각도|틀어', ACT))
rule('SEAL_TEMP', 80, T, '씰러 온도', '씰러 온도 이상',
     '씰러|sealer|초음파|엔드씰|센터씰|탑씰|씰바|endtop|엔드탑|씰링바', '온도')
rule('FILLER', 72, M, '충진부(노즐·호퍼·피스톤)', '충진부 이상/조정',
     '노즐|nozzle|호퍼|hopper|충진|필러|filler|도징|dosing|디스펜서|dispenser|맨드럴|mandrel',
     sym(FAIL, BREAK, LOOSE, WEAR, JAM, LEAK, '위치|역류', ACT))
rule('NOZZLE_CLOG', 82, F, '막힘(노즐·필터)', '노즐·필터 막힘', '노즐|nozzle|필터|filter|스트레이너|strainer', '막힘|막혀|clog')
rule('MOLD', 70, M, '성형부(몰드·포머)', '성형부 이상', '몰드|mold|금형|포머|former|포밍|성형',
     sym(FAIL, BREAK, LOOSE, WEAR, JAM, ACT))

# ---- 공압·진공
rule('CYLINDER', 84, P, '실린더', '실린더 이상/조치', '실린더|cylinder|로드리스|에어척',
     sym(FAIL, BREAK, LOOSE, WEAR, ELEC, LEAK, '간섭|미동작', ACT))
rule('SOLENOID', 88, P, '솔밸브', '솔밸브 이상/교체', '솔밸브|솔레노이드|solenoid|전자변',
     sym(FAIL, ELEC, BREAK, LEAK, '망가|역류|막힘', ACT))
rule('VACUUM', 84, P, '진공·석션', '진공·석션 이상', '진공펌프|진공컵|진공|석션|suction|흡착|vacuum',
     sym(FAIL, LEAK, BREAK, '안걸|약함|약해|저하|막힘', ACT))
rule('AIR', 83, P, '에어 공급·배관', '에어라인·공기압 이상',
     '에어라인|에어호스|에어커넥터|에어필터|에어(?!컨)|(?<![a-z])air(?!con)|공기압|압축공기|컴프레서|compressor|레귤레이터|regulator|소음기',
     sym(FAIL, LEAK, BREAK, LOOSE, '저하|약해|약함|부족|낮음|막힘', ACT))

# ---- 유체·배관
rule('PUMP', 84, W, '펌프', '펌프 이상', '펌프|pump|블로워|blower|부스터|균질기|homogenizer', sym(FAIL, ELEC, BREAK, WEAR, LEAK, ACT))
rule('VALVE', 82, W, '밸브·액추에이터', '밸브·액추에이터 이상',
     '(?<!솔)밸브|valve|버터플라이|다이버트|액추에이터|actuator|씽크탑|thinktop|ssv',
     sym(FAIL, BREAK, LEAK, '닫힘|열림|안열|안닫|오조작|역류|막힘|피드백|약해|이물|혼입|과투입', ACT))
rule('HOSE', 82, W, '배관·호스', '배관·호스 파손·누설', '호스|hose|배관|파이프|pipe|피팅|fitting|니플',
     sym(BREAK, LEAK, ELEC, WEAR, LOOSE, FAIL, '막힘', ACT))
rule('SEAL', 86, W, '씰·오링', '씰·오링 누설·손상',
     '오링|oring|유컵|ucup|가스켓|개스킷|gasket|패킹|피스톤씰|메카니컬씰|(?<![가-힣])씰(?![러링바])',
     sym(LEAK, BREAK, WEAR, LOOSE, ACT))
rule('FILTER', 83, W, '필터', '필터 막힘·교체', '필터|filter|스트레이너|strainer', sym('오염|자력', BREAK, FAIL, ACT))
rule('HEAT_EXCHANGER', 86, W, '열교환기', '열교환기 파손·누설', '열교환|브레이즈드|brazed|판형|튜블러|tubular',
     sym('핀홀', LEAK, BREAK, FAIL, '막힘', ACT))
rule('TANK', 60, F, '탱크·전환', '탱크·전환 이상', '탱크|tank|사일로|silo',
     '오류|에러|교체안됨|전환안됨|자동교체안됨|레벨|고장|이상')

# ---- 온도·냉각
rule('REFRIGERATION', 86, T, '냉동·냉각설비', '냉동기·냉매·냉각 이상',
     '냉동기|냉매|암모니아|nh3|응축기|증발기|에어컨|aircon|냉각팬|팬모터|쿨러|cooler|칠러|chiller|냉각수|브라인|brine|냉각탑|bpr',
     sym(FAIL, LEAK, '다운|과부하|부족|공급불량|불능', ACT))

# ---- 공정·운전
rule('FLOW', 70, F, '공급량·중량', '공급량·중량 이상', '중량|분사량|토출량|충진량|공급량|유량', '미달|부족|과다|초과|덜나|이상|불량|편차')
rule('PRODUCT_JAM', 60, F, '제품·용기 걸림', '제품·용기 걸림·낙하',
     '제품|크레이트|crate|박스|box|컵|cup|용기|캡|cap|리드|lid|트레이|tray|파렛트|pallet',
     '걸림|걸리|끼임|끼어|낙하|넘어짐|쓰러짐|떨굼|떨어|빠짐|적체|흩날|올라감|올라가')
rule('MATERIAL', 62, F, '자재', '자재 불량·교체', '원단|필름|film|테이프|tape|라벨|label|포장재|자재',
     '불량|교체|부족|소진|걸림|찢어|끊어|불균일')
rule('SEALING', 75, F, '씰링 품질', '씰링 불량', '씰링|sealing', '불량|미흡|터짐|새는|불균일')
rule('OPERATOR', 95, F, '작업자 조작', '작업자 조작 기인', '작업자가|작업자의|조작실수|조작미스|부주의|작업미숙', '.', role='override')
rule('NONFAILURE', 94, F, '개선·시험 작업', '개선·시험 작업(고장 아님)', '개선test|개선테스트|개선작업|테스트작업|시운전', '.', role='override')

# ---- 부위 미기재 (fallback: used only when no part is named)
rule('PACKER', 40, M, '포장설비(부위 미기재)', '포장설비 이상(부위 미기재)',
     '포장기|봉함기|제함기|케이서|케이셔|caser|팩커|packer|밴딩기|랩어라운드|카토너|cartoner|스태커|stacker|제대기|미드팩|멀티팩',
     sym(FAIL, JAM, BREAK, LOOSE, '틀어|틀려|타이밍', ACT), role='fallback')
rule('FREEZER', 40, T, '동결설비(부위 미기재)', '프리저·동결설비 이상(부위 미기재)',
     '프리저|freezer|qft|iqf|동결|ht-300', sym(FAIL, JAM, BREAK, LOOSE, '압력|부하|온도', ACT), role='fallback')
rule('TEMP', 45, T, '온도(부위 미기재)', '온도 이상(부위 미기재)', '온도|temp',
     '이상|불량|상승|저하|낮음|높음|불안정|에러|오류|고장', role='fallback')
rule('PRESSURE', 44, F, '압력(부위 미기재)', '압력 이상(부위 미기재)', '압력|pressure|압(?=저하|낮음)',
     '낮음|저하|높음|상승|이상|오류|에러|불안정', role='fallback')
rule('POSITION', 42, M, '위치·원점(부위 미기재)', '위치·원점·타이밍 이상(부위 미기재)', '원점|틀어|틀려|틀리|정렬불량|센터|위치|각도|타이밍', '.',
     role='fallback')
rule('ELEC_MODE', 43, E, '전기 이상(부위 미기재)', '단선·소손·트립(부위 미기재)', '단선|소손|쇼트|합선|누전|트립|trip|과부하|과전류', '.',
     role='fallback')
rule('BREAK_MODE', 41, M, '파손·변형(부위 미기재)', '파손·용접부·변형(부위 미기재)',
     '부러|절단|용접|파손|깨짐|깨져|크랙|금감|휘어|휨|변형|찌그러|뒤틀', '.', role='fallback')
rule('LOOSE_MODE', 40, M, '이탈·풀림(부위 미기재)', '이탈·풀림(부위 미기재)', '이탈|빠짐|빠져|탈락|풀림', '.', role='fallback')
rule('JAM_MODE', 40, F, '걸림·끼임(부위 미기재)', '걸림·끼임(부위 미기재)', '걸림|끼임|끼어|적체|정체', '.', role='fallback')
rule('CLOG', 40, F, '원료·공급 막힘', '원료·공급 막힘(부위 미기재)', '막힘|막혀|clog', '.', role='fallback')
rule('LEAK_MODE', 40, W, '누설(부위 미기재)', '누설(부위 미기재)', '리크|누설|누수|누출|leak', '.', role='fallback')

if __name__ == '__main__':
    checked = validate_rules(R)
    print(len(checked), 'rules valid')
    if '--dry-run' not in sys.argv:
        out = ROOT / 'config' / 'classification_config.xlsx'
        write_rules(out, R)
        out.with_suffix('.xlsx.bak').unlink(missing_ok=True)
        print('written', out)
