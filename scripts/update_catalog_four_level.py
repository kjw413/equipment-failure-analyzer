"""Apply the source-backed four-level taxonomy metadata and vocabulary additions.

Existing physical-part IDs and historical source evidence are preserved. This
script does not open/write the rule workbook or any user runtime profile.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "taxonomy_4level_20261111"

# Names are physical equipment/assemblies explicitly named in the three files.
# Generic brand, model, production line and '본체' are intentionally not types.
EQUIPMENT_TYPES = [
    (
        "카토닝머신",
        [
            "카토닝머신",
            "카톤머신",
            "카톤 머신",
            "카토너",
            "카토나",
            "멀티카톤머신",
            "멀티카톤",
            "cartoner",
        ],
    ),
    ("제대기", ["제대기"]),
    (
        "랩어라운드 케이서",
        ["랩어라운드케이서", "랩어라운드 케이서", "랩 어라운드 케이서", "wrap around caser"],
    ),
    ("케이서", ["케이서", "케이샤", "케이셔", "케이사", "멀티케이서", "멀티 케이서", "caser"]),
    (
        "필름·필로우 포장기",
        ["필름포장기", "필름 포장기", "필로우포장기", "필로우 포장기", "pillow wrapper"],
    ),
    (
        "멀티포장기",
        [
            "멀티포장기",
            "멀티 포장기",
            "멀티팩커",
            "멀티패커",
            "미드팩",
            "미드 팩",
            "multipacker",
            "midpack",
        ],
    ),
    ("콘팩커", ["콘팩커", "콘 팩커", "콘패커", "콘 패커"]),
    ("포장기", ["포장기", "포장설비", "포장 설비", "wrapper", "packaging machine"]),
    ("필러·충진기", ["필러", "충진기", "충전기", "충진설비", "filler"]),
    ("프리저", ["프리저", "프리져", "프리자", "프리젠", "프리지", "freezer"]),
    (
        "동결설비",
        [
            "동결설비",
            "동결기",
            "급속동결",
            "QFT",
            "Q.F.T",
            "HT-300",
            "HT300",
            "IQF",
            "HARDNING TUNNEL",
            "HARDENING TUNNEL",
        ],
    ),
    (
        "파렛타이저",
        [
            "파렛타이저",
            "파렛타이져",
            "파레타이저",
            "팔레타이저",
            "팔레타이져",
            "팔렛타이져",
            "팔렛타이저",
            "로봇파렛타이져",
            "로봇파렛타이저",
            "로봇팔레타이져",
            "로봇팔렛타이져",
            "로봇팔레타이저",
            "로봇 파렛타이져",
            "로봇 팔레타이져",
            "palletizer",
        ],
    ),
    ("로봇", ["로봇", "로보트", "robot", "담기로봇", "담기 로봇"]),
    (
        "컨베어",
        [
            "컨베어",
            "컨베이어",
            "콘베어",
            "콘베이어",
            "컨배어",
            "컨배이어",
            "conveyor",
            "con'v",
            "Con’V",
            "C/V",
        ],
    ),
    ("스태커", ["스태커", "스테커", "스택커", "스텍커", "stacker"]),
    ("리프트", ["리프트", "리프터", "승강기", "엘리베이터", "lift", "elevator"]),
    (
        "센터씰러",
        [
            "센터씰러",
            "센터실러",
            "센타실러",
            "센타 실러",
            "센터 실러",
            "센터 씰러",
            "센터씰링",
            "센터실링",
        ],
    ),
    ("엔드씰러", ["엔드씰러", "엔드실러", "엔드 실러", "엔드 씰러"]),
    ("리드씰러", ["리드씰러", "리드실러", "리드 실러", "리드 씰러"]),
    ("초음파씰러", ["초음파씰러", "초음파실러", "초음파 실러", "초음파 씰러"]),
    ("씰러", ["씰러", "실러", "씨러", "sealer"]),
    ("라벨러", ["라벨러", "라벨라", "라벨기", "labeller", "labeler"]),
    ("날인기", ["날인기", "날인장치", "프린터", "제트프린터", "잉크젯", "마킹기", "printer"]),
    ("X-RAY 검사기", ["X-RAY", "X RAY", "XRAY", "엑스레이", "엑스 레이"]),
    ("금속검출기", ["금속검출기", "금속 검출기", "금검기", "금속검사기"]),
    ("중량선별기", ["중량선별기", "중량 선별기", "웨이트체커", "weight checker", "checkweigher"]),
    ("계량기", ["계량기", "계량장치", "계량 장치"]),
    ("박스카운터", ["박스카운터", "박스 카운터"]),
    ("포장카운터", ["포장카운터", "포장 카운터"]),
    ("피더", ["피더", "피다", "feeder"]),
    ("스틱인서터", ["스틱인서터", "스틱 인서터", "스틱삽입기", "스틱 삽입기"]),
    ("제함기", ["제함기"]),
    ("봉함기", ["봉함기", "테이핑기", "테이퍼"]),
    ("세척기", ["세척기", "세병기", "washer", "rinser", "PAA Washer", "Water Rinser"]),
    ("UHT·살균기", ["UHT", "튜블러", "살균기", "살균설비"]),
    ("균질기", ["균질기", "homogenizer"]),
    ("탱크", ["탱크", "tank"]),
    ("펌프", ["펌프", "pump"]),
    ("컴프레서", ["컴프레서", "컴프레샤", "콤프레샤", "콤푸레샤", "compressor"]),
    ("교반기·믹서", ["교반기", "믹서", "호모믹서", "mixer"]),
    ("디스펜서", ["디스펜서", "디스팬서", "dispenser"]),
    ("히팅박스", ["히팅박스", "히팅 박스", "히터박스", "히터 박스"]),
    ("포밍부", ["포밍부", "포밍", "forming"]),
    ("성형기", ["성형기"]),
    ("이송장치", ["트랜스퍼", "트렌스퍼", "트랜스훠", "이송장치", "이송기", "transfer"]),
    ("캡핑기", ["캡핑기", "캐핑기", "캡퍼", "캐퍼", "capper"]),
    ("포드프레스", ["포드프레스", "포드 프레스"]),
    ("스핀웰더", ["스핀웰더", "스핀 웰더"]),
    ("스트로우부착기", ["스트로우부착기", "스트로우 부착기", "빨대부착기", "빨대 부착기"]),
    ("랩어플리케이터", ["랩어플리케이터", "랩 어플리케이터"]),
    ("튜브투입기", ["튜브투입기", "튜브 투입기"]),
]

NORMALIZATION_ADDITIONS = {
    "베아링": "베어링",
    "베어린": "베어링",
    "베아린": "베어링",
    "쎈서": "센서",
    "센써": "센서",
    "쎈써": "센서",
    "가스킷": "가스켓",
    "가스캣": "가스켓",
    "가스켙": "가스켓",
    "메카니컬씰": "메카니칼씰",
    "메커니컬씰": "메카니칼씰",
    "메커니칼씰": "메카니칼씰",
    "메카니컬 씰": "메카니칼씰",
    "메카니칼 씰": "메카니칼씰",
    "메카니칼 실": "메카니칼씰",
    "썸머카플": "써머커플",
    "썸머커플": "써머커플",
    "써머카플": "써머커플",
    "서모커플": "써머커플",
    "서머커플": "써머커플",
    "아닷치": "아타치",
    "아다찌": "아타치",
    "컨배어": "컨베어",
    "히타": "히터",
}

ALIAS_ADDITIONS = {
    "베어링(종류 미상)": ["베아링", "베어린", "베아린"],
    "메인보드": ["메인 보드", "메인기판", "메인 기판", "메인PCB", "mainboard", "main board"],
    "가스켓": [
        "유니언가스켓",
        "유니언 가스켓",
        "플랜지가스켓",
        "플렌지 가스켓",
        "가스킷",
        "가스캣",
    ],
    "메카니칼씰": ["메카니칼 씰", "메카니컬씰", "메커니컬씰", "메커니칼씰", "mechanical seal"],
    "씰·패킹(종류 미상)": ["seal", "packing", "팩킹"],
    "리데나": ["오일씰", "오일 씰", "오일실", "oil seal"],
    "열전대(써머커플)": ["썸머카플", "썸머커플", "써머카플", "서모커플", "서머커플"],
    "TC 센서선": ["TC 선", "T.C 선", "TC센서선", "열전대선", "열전대 선"],
    "센서(종류 미상)": ["쎈서", "센써", "쎈써"],
}

CAUTION_ADDITIONS = {
    "메인보드": "메인보드와 연결된 선·커넥터가 실제 조치 대상인 문맥은 메인보드 고장으로 확정하지 않는다. 청소·점검만으로 고장 증상을 추정하지 않는다.",
    "가스켓": "가스켓 고정부 볼트 조임처럼 가스켓이 위치 문맥이면 실제 조치 부품인 볼트를 보존한다.",
    "PLC": "PLC 판넬의 마그네틱·케이블·카드 등 명시된 하위 부품이 실제 조치 대상이면 PLC 본체 고장으로 확정하지 않는다.",
}


def merge_unique(existing, additions):
    return list(dict.fromkeys([*existing, *additions]))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    catalog_path = ROOT / "config" / "classification_catalog.json"
    norm_path = ROOT / "config" / "normalization.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    norm = json.loads(norm_path.read_text(encoding="utf-8"))
    source_profile = json.loads((OUTPUT / "source_profile.json").read_text(encoding="utf-8"))
    sources = []
    for item in source_profile["inputs"]:
        sources.append(
            {
                "filename": Path(item["file"]).name,
                "path": item["file"],
                "sha256": item["sha256"],
                "sheet": item["sheets"][0]["sheet"],
                "header_row": item["sheets"][0]["header_row"],
                "data_rows": item["rows"],
                "min_start": item["min_start"],
                "max_start": item["max_start"],
                "note": "원본 읽기 전용 분석. A1 차원 메타를 초기화하고 하단 탐색 라벨행을 제외한 MES 고장이력 수.",
            }
        )
    # Existing source object is kept for all original 240 category definitions.
    catalog["three_year_sources"] = sources
    catalog["catalog_version"] = "1.12.0"
    catalog["output_schema"] = "equipment_part_symptom_v2"
    catalog["output_axes"] = {
        "major": "대분류",
        "detail_equipment": "상세설비",
        "middle": "세부 부품",
        "minor": "소분류",
    }
    catalog["equipment_types"] = [
        {"name": name, "aliases": aliases} for name, aliases in EQUIPMENT_TYPES
    ]
    catalog["classification_policy"] = [
        "고장 분류 출력은 대분류=분야, 상세설비=고장·조치 대상 설비, 세부 부품=명시된 부품 종류, 소분류=원문 또는 비가동코드(소)에 명시된 고장 증상/조치",
        *[
            item
            for item in catalog["classification_policy"]
            if not item.startswith("고장 분류 출력은")
        ],
    ]
    catalog["classification_policy"] = merge_unique(
        catalog["classification_policy"],
        [
            "상세설비는 부품별 고장·조치 근거와 연결된 원문 설비를 우선하며 비가동코드(중)으로 보완. 두 근거가 없으면 상세설비 미상으로 표시. 등록 설비명은 원본 등록 위치로만 보존하며 고장 대상 설비나 부품명을 추정하지 않음",
            "상세설비 별칭은 공정·브랜드·라인과 구분. 명시된 카토닝머신·제대기·케이서·파렛타이저 등을 표준화하고 본체·기타만으로 구체 설비 종류를 추정하지 않음",
            "상세설비가 여러 개이면 부품 근거와 연결되는 설비를 후보별로 보존하고 불명확하면 담당자 검토. 세부 부품 미기재는 세부 부품 미기재로 표시하고 베어링·모터 등으로 임의 추정하지 않음",
            "분류 축 확장 전의 사용자 수동 확정값은 원래 부품·증상과 근거를 보존하며 상세설비만 추가로 확인. 새 기본 사전이 사용자 규칙을 덮어쓰지 않음",
        ],
    )
    by_minor = {item["minor"]: item for item in catalog["categories"]}
    alias_changes = []
    for minor, additions in ALIAS_ADDITIONS.items():
        category = by_minor[minor]
        before = list(category.get("matching_aliases", category["aliases"]))
        category["aliases"] = merge_unique(category["aliases"], additions)
        category["matching_aliases"] = merge_unique(before, additions)
        actual_additions = [word for word in additions if word not in before]
        if actual_additions:
            alias_changes.append({"minor": minor, "aliases_added": actual_additions})
    for minor, caution in CAUTION_ADDITIONS.items():
        category = by_minor[minor]
        if caution not in category.get("caution", ""):
            category["caution"] = (category.get("caution", "") + " " + caution).strip()

    # Directly observed in the 2025 and 2026 user-supplied workbooks. Do not
    # classify generic PLC, WAGO alarm number or a card with no PLC identity here.
    if "PLC 카드" not in by_minor:
        code = "E-PLC-CARD"
        new_category = {
            "code": code,
            "major": "전기·제어",
            "middle": "제어기·I/O·통신",
            "minor": "PLC 카드",
            "kind": "observed",
            "aliases": ["PLC카드", "PLC 카드", "PLC보드", "PLC 보드", "PLC기판", "PLC 기판"],
            "matching_aliases": [
                "PLC카드",
                "PLC 카드",
                "PLC보드",
                "PLC 보드",
                "PLC기판",
                "PLC 기판",
            ],
            "definition": "원문에 PLC 카드·보드·기판이라고 명시된 PLC 하위 전자 부품. 입출력 방식이나 카드 형식은 추정하지 않음.",
            "caution": "PLC 단독 언급, WAGO 오류번호, 기판·카드 단독 언급으로 PLC 카드라고 추정하지 않음. PLC 판넬의 마그네틱·배선 교체는 해당 하위 부품을 우선함.",
            "evidence_2024": 0,
            "evidence_2025": 1,
            "evidence_2026": 1,
            "example_refs": ["라인 고장이력_25년.xlsx:1055", "라인 고장이력_26년.xlsx:658"],
            "example_texts": [],
            "sources": [
                {
                    "sha256": sources[1]["sha256"],
                    "sheet": sources[1]["sheet"],
                    "row": 1055,
                    "range": "O1055",
                },
                {
                    "sha256": sources[2]["sha256"],
                    "sheet": sources[2]["sheet"],
                    "row": 658,
                    "range": "O658",
                },
            ],
        }
        # Keep the original order and every original code intact.
        index = next(i for i, item in enumerate(catalog["categories"]) if item["minor"] == "PLC")
        catalog["categories"].insert(index + 1, new_category)
        group = next(
            group
            for group in catalog["groups"]
            if group["major"] == "전기·제어" and group["middle"] == "제어기·I/O·통신"
        )
        group["minors"] = merge_unique(group["minors"], ["PLC 카드"])

    plc_card = next(item for item in catalog["categories"] if item["minor"] == "PLC 카드")
    plc_card["source_row"] = 1055
    plc_card["source"] = {
        "sha256": sources[1]["sha256"],
        "sheet": sources[1]["sheet"],
        "row": 1055,
        "range": "O1055",
        "type": "three_year_observed",
    }

    norm["replacements"].update(
        {
            key: value
            for key, value in NORMALIZATION_ADDITIONS.items()
            if key not in norm["replacements"]
        }
    )
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    norm_path.write_text(json.dumps(norm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    change = {
        "output_schema": catalog["output_schema"],
        "equipment_types": len(catalog["equipment_types"]),
        "categories": len(catalog["categories"]),
        "groups": len(catalog["groups"]),
        "alias_additions": ALIAS_ADDITIONS,
        "normalization_additions": NORMALIZATION_ADDITIONS,
        "sources": sources,
        "source_event_rows": sum(item["data_rows"] for item in sources),
        "notes": [
            "표면 언급 빈도는 검증 정답이나 정확도가 아님.",
            "2026년 자료는 11월 11일까지의 부분연도.",
            "원본 고장이력 파일은 수정하지 않음.",
        ],
    }
    (OUTPUT / "taxonomy_update_summary.json").write_text(
        json.dumps(change, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT / "equipment_types_proposal.json").write_text(
        json.dumps(catalog["equipment_types"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: change[key]
                for key in (
                    "output_schema",
                    "equipment_types",
                    "categories",
                    "groups",
                    "source_event_rows",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
