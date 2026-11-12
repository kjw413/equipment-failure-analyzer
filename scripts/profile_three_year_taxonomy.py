"""Read-only profiling of the three user-supplied MES downtime exports.

Source workbooks are never modified. XLSX dimensions are reset because these
exports declare A1 although their data occupies 24 columns and thousands of rows.
Profile output contains counts and source locations, not user names or full notes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "output" / "taxonomy_4level_20261111"

# Exploratory surface mentions, not an automatic classifier. More specific
# patterns are intentionally kept separate to show real vocabulary variation.
EQUIPMENT = {
    "컨베어": r"컨베[어이]|콘베[어이]|컨배[어이]|conveyor|con['’]?v|c/v",
    "필러·충진기": r"필러|충[진전]기|filler",
    "포장기": r"포장기|포장설비|패커|팩커|팩카|팩커|wrapper|packer",
    "라벨러": r"라벨러|라벨라|라벨기|label[el]?er",
    "프리저": r"프리[저져자지젠]|freezer|후리[저져자]",
    "로봇": r"로[봇보]트?|robot",
    "스태커": r"스태커|스테커|스텍커|스택커|stacker",
    "파렛타이저": r"파[렛레]타이[저져]|팔[렛레]타이[저져]|팔렛타이져|palletiz",
    "제함기": r"제함기",
    "봉함기": r"봉함기|테이핑기|테이퍼",
    "씰러": r"씰러|실러|씨러|실링기|씰링기|sealer",
    "날인기": r"날인기|날짜인쇄|마킹기|프린터|printer|잉크젯",
    "계량기·선별기": r"계량기|계량장치|계량부|웨이[어아]|중량선별|웨이트체커",
    "검사기": r"x[ -]?ray|엑스레이|검사기|금속검출|금검기|금속검사",
    "피더": r"피더|피다|feeder",
    "히팅박스": r"히팅박스|히팅 박스|히터박스|히터 박스",
    "포밍부": r"포밍|forming|성형부|성형기",
    "냉동·동결기": r"동결기|동결설비|qft|ht[ -]?300",
    "리프트": r"리프트|리프터|승강기|엘리베이터|elevator|lift",
    "카토너": r"카토너|카토나|카톤기|carton",
    "카토닝머신": r"카토닝머신|카톤\s*머신|멀티카톤|cartoner",
    "제대기": r"제대기",
    "케이서": r"케이[서샤셔사]|caser",
    "스틱인서터": r"스틱\s*인서터|스틱\s*삽입기",
    "세척기": r"세척기|washer|rinser",
    "균질기": r"균질기|homogenizer",
    "UHT": r"(?<![a-z])uht(?![a-z])|튜블러|살균기",
    "카운터": r"박스\s*카운터|포장\s*카운터",
    "멀티팩커·미드팩": r"멀티팩|멀티팩커|멀티패커|미드팩|미드 팩|midpack",
    "캡핑기": r"캡핑기|캐핑기|캡퍼|캐퍼|capp?er",
    "펌프": r"펌프|pump",
    "컴프레서": r"컴프레[서샤]|콤프레[서샤]|콤푸레샤|compressor",
    "탱크": r"탱크|tank",
    "배관": r"배관|파이프|pipe",
    "이송장치": r"트랜스퍼|트렌스퍼|이송장치|이송기|transfer",
    "디스펜서": r"디스펜서|디스팬서|dispenser",
    "호모믹서·교반기": r"호모믹서|교반기|믹서|mixer",
    "아이스크림 제조기": r"메리트|테크노|메트릭스|노벨티|로터리|로타리",
}

PARTS = {
    "베어링": r"베어링|베아링|베어린|베아린|베링|bearing|(?<![a-z])brg(?![a-z])",
    "모터": r"모터|모타|motor",
    "씰": r"오일\s*[씰실]|메[카커]니[칼컬]\s*[씰실]|메카니컬|메카니칼|mechanical\s*seal|oil\s*seal|[씰실]\s*파손",
    "가스켓": r"가스[켓켙]|가스캣|가스깃|가스킷|가스켙|gasket",
    "메인보드": r"메인\s*보드|메인\s*기판|메인\s*pcb|main\s*board|mainboard",
    "PLC 카드": r"plc\s*(?:카드|보드|기판)|plc\s*(?:입력|출력|입출력)|(?:입출력|입력|출력)\s*카드|[io]/?o?\s*카드|io\s*(?:보드|모듈)",
    "PLC": r"(?<![a-z])plc(?![a-z])|피엘씨",
    "센서": r"센서|쎈서|센써|센사|쎈써|sensor",
    "TC·열전대": r"(?<![a-z])t[./ ]?c(?![a-z])|열전대|써머커플|서모커플|thermocouple",
    "인버터": r"인버[터타]|inverter",
    "드라이브": r"드라이[브버]|driver|drive",
    "벨트": r"벨트|밸트|belt",
    "체인": r"체인|체닝|chain",
    "기어·감속기": r"기어|기야|감속기|gear",
    "실린더": r"실린더|시린더|씨린더|cylinder",
    "밸브": r"밸브|벨브|vv|v/v|valve",
    "오링": r"오링|o[ -]?ring|o링",
    "패킹": r"패킹|팩킹|파킹|packing",
    "히터": r"히터|히타|heater",
    "케이블·배선": r"케이블|케이불|배선|전선|하네스|하니스|cable|wire",
    "전원공급장치": r"smps|파워\s*서플라이|파워\s*써플라이|전원\s*공급|power\s*supply",
    "퓨즈": r"퓨즈|휴즈|fuse",
    "릴레이·마그네틱": r"릴레이|릴레리|마그네[틱트]|전자접촉기|relay",
    "엔코더": r"엔코더|인코더|encoder",
    "스위치": r"스위치|스윗치|switch",
    "보드·카드": r"보드|기판|카드|pcb|board",
    "볼트·너트": r"볼트|너트|볼프|블트|bolt|nut",
    "축·샤프트": r"샤프트|샤후트|shaft|회전축|구동축",
    "롤러": r"롤러|로라|roller",
    "스프라켓": r"스프라[켓켙]|스프로[켓킷]|sprocket",
    "커플링": r"커플링|카플링|coupling",
    "노즐": r"노즐|노줄|nozzle",
    "호스": r"호스|hose",
    "흡착패드": r"흡착\s*패드|흡착\s*패드|석션\s*패드|썩션\s*패드|진공\s*패드",
    "칼날·커터": r"칼날|커터|컷터|커팅날|컷팅날|cut[ -]?ter|knife",
}

MARKERS = {
    "부정·정상": r"이상\s*없|정상|불량\s*아|고장\s*아|미발생",
    "예정·추정": r"예정|추후|차후|의심|추정|예상|추측|계획",
    "복수·인과 연결": r"및|동시|와\s|과\s|으로\s*인|로\s*인|원인",
    "증상없이 점검·조정 가능": r"점검|조정|조절|세팅|셋팅|확인",
}


def s(value):
    return "" if value is None else str(value).strip()


def counter_list(counter, n=100):
    return [{"value": value, "rows": count} for value, count in counter.most_common(n)]


def read_records(path):
    records, sheets = [], []
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb:
        declared = ws.calculate_dimension()
        ws.reset_dimensions()
        headers = None
        header_row = None
        for index, row in enumerate(ws.iter_rows(values_only=True), 1):
            if headers is None:
                if "비가동 코드(중)" in row and "비고" in row:
                    headers = [s(value) for value in row]
                    header_row = index
                continue
            if not any(value is not None for value in row):
                continue
            record = dict(zip(headers, row))
            if not s(record.get("비가동 시작 시간")) and not s(record.get("라인")):
                continue
            # MES exports append a navigation/footer row with repeated labels.
            # A timestamp + factory/line identifier identifies source events.
            if not re.match(r"\d{4}-\d{2}-\d{2}[ T]", s(record.get("비가동 시작 시간"))):
                continue
            record["_row"] = index
            record["_sheet"] = ws.title
            records.append(record)
        sheets.append(
            {
                "sheet": ws.title,
                "declared_dimension": declared,
                "header_row": header_row,
                "columns": headers,
            }
        )
    wb.close()
    return records, sheets


def profile(paths, out):
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "method": "Read-only openpyxl iter_rows after reset_dimensions; one MES downtime row is the grain; text mention counts are exploratory, not classification accuracy.",
        "inputs": [],
        "combined": {},
    }
    all_records = []
    per_year = {}
    for path in paths:
        records, sheets = read_records(path)
        year = re.search(r"_(\d+)년", path.stem).group(1)
        for row in records:
            row["_year"] = year
        all_records += records
        per_year[year] = records
        # No names, user IDs or note text included in summary.
        duplicates = Counter(
            tuple(
                s(row.get(key))
                for key in ("공장", "라인", "설비", "비가동 시작 시간", "비가동 종료 시간", "비고")
            )
            for row in records
        )
        fields = [
            "공장",
            "라인",
            "설비",
            "설비명",
            "비가동 코드(대)",
            "비가동 코드(중)",
            "비가동 코드(소)",
            "비고",
        ]
        dates = [
            s(row.get("비가동 시작 시간")) for row in records if s(row.get("비가동 시작 시간"))
        ]
        entry = {
            "file": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "year_label": year,
            "rows": len(records),
            "sheets": sheets,
            "min_start": min(dates, default=""),
            "max_start": max(dates, default=""),
            "exact_event_duplicate_excess": sum(count - 1 for count in duplicates.values()),
            "both_mid_small_missing": sum(
                not s(row.get("비가동 코드(중)")) and not s(row.get("비가동 코드(소)"))
                for row in records
            ),
            "fields": {
                key: {
                    "missing_rows": sum(not s(row.get(key)) for row in records),
                    "distinct_nonempty": len(
                        {s(row.get(key)) for row in records if s(row.get(key))}
                    ),
                }
                for key in fields
            },
        }
        entry["raw_mid_top"] = counter_list(
            Counter(s(row.get("비가동 코드(중)")) for row in records), 60
        )
        entry["raw_small_top"] = counter_list(
            Counter(s(row.get("비가동 코드(소)")) for row in records), 60
        )
        entry["raw_big_top"] = counter_list(
            Counter(s(row.get("비가동 코드(대)")) for row in records), 40
        )
        entry["description_equipment_mentions"] = {
            name: sum(bool(re.search(pattern, s(row.get("비고")), re.I)) for row in records)
            for name, pattern in EQUIPMENT.items()
        }
        entry["description_part_mentions"] = {
            name: sum(bool(re.search(pattern, s(row.get("비고")), re.I)) for row in records)
            for name, pattern in PARTS.items()
        }
        summary["inputs"].append(entry)
    records = all_records
    combined = summary["combined"]
    combined["rows"] = len(records)
    combined["raw_mid_top"] = counter_list(
        Counter(s(row.get("비가동 코드(중)")) for row in records), 200
    )
    combined["raw_small_top"] = counter_list(
        Counter(s(row.get("비가동 코드(소)")) for row in records), 150
    )
    combined["raw_big_top"] = counter_list(
        Counter(s(row.get("비가동 코드(대)")) for row in records), 100
    )
    combined["raw_equipment_top"] = counter_list(
        Counter(s(row.get("설비명")) for row in records), 100
    )
    combined["mid_versus_registered_name_unequal"] = sum(
        bool(s(row.get("비가동 코드(중)")))
        and s(row.get("비가동 코드(중)")) != s(row.get("설비명"))
        for row in records
    )
    combined["description_equipment_mentions"] = {
        name: sum(bool(re.search(pattern, s(row.get("비고")), re.I)) for row in records)
        for name, pattern in EQUIPMENT.items()
    }
    combined["mid_equipment_mentions"] = {
        name: sum(bool(re.search(pattern, s(row.get("비가동 코드(중)")), re.I)) for row in records)
        for name, pattern in EQUIPMENT.items()
    }
    combined["description_part_mentions"] = {
        name: sum(bool(re.search(pattern, s(row.get("비고")), re.I)) for row in records)
        for name, pattern in PARTS.items()
    }
    combined["markers"] = {
        name: sum(bool(re.search(pattern, s(row.get("비고")), re.I)) for row in records)
        for name, pattern in MARKERS.items()
    }
    combined["description_multiple_equipment_mentions"] = sum(
        sum(bool(re.search(pattern, s(row.get("비고")), re.I)) for pattern in EQUIPMENT.values())
        > 1
        for row in records
    )
    combined["description_multiple_part_mentions"] = sum(
        sum(bool(re.search(pattern, s(row.get("비고")), re.I)) for pattern in PARTS.values()) > 1
        for row in records
    )
    # Preserve source provenance and compact counts for manual validation without
    # duplicating notes or including personal data in generated supporting files.
    examples = defaultdict(list)
    for row in records:
        note = s(row.get("비고"))
        for name, pattern in {**EQUIPMENT, **PARTS}.items():
            if re.search(pattern, note, re.I) and len(examples[name]) < 8:
                examples[name].append(
                    {"year": row["_year"], "sheet": row["_sheet"], "row": row["_row"]}
                )
    summary["source_locations"] = dict(examples)
    (out / "source_profile.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "inputs": [
                    {
                        key: item[key]
                        for key in (
                            "year_label",
                            "rows",
                            "min_start",
                            "max_start",
                            "both_mid_small_missing",
                            "exact_event_duplicate_excess",
                        )
                    }
                    for item in summary["inputs"]
                ],
                "combined": {
                    key: value
                    for key, value in combined.items()
                    if key not in ("raw_equipment_top", "raw_mid_top")
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=Path("C:/Users/user/Downloads"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    profile(
        [args.source_dir / f"라인 고장이력_{year}년.xlsx" for year in ("24", "25", "26")],
        args.output_dir,
    )
