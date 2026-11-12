"""Generate bundled rules from the source-backed classification catalogue.

The authoritative names, aliases and workbook provenance live in
config/classification_catalog.json. Run ``python tools/make_rules.py --dry-run``
to validate, or omit --dry-run to recreate classification_config.xlsx through
the application's existing writer. Runtime user profiles are never opened here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.parsing import prepare_text
from core.rules import validate_rules, write_rules

CATALOG_PATH = ROOT / "config" / "classification_catalog.json"
NORMALIZATION_PATH = ROOT / "config" / "normalization.json"

FAIL = (
    "고장|이상|불량|오류|에러|error|트러블|오작동|작동불|작동안|미작동|미가동|미구동|구동불|멈춤|멈춰|"
    "정지|(?<![업셧])다운|불능|안됨|안되|비정상|알람|alarm|fault|trip|트립|문제|나감|망가|소손"
)
BREAK = "파손|부러|깨짐|깨져|절단|끊어|끊김|찢어|터짐|터져|크랙|crack|금감|휨|휘어|변형|뒤틀|찌그러"
WEAR = "마모|닳|녹|부식|손상|스크레치|스크래치|헐거|유격"
LOOSE = "풀림|풀려|풀어|풀리면|풀리며|풀리고|이탈|빠짐|빠져|탈락|떨어|분리|흔들|뒤집"
ELEC = "단선|소손|단락|쇼트|short|합선|누전|과부하|과전류|접촉불량|접촉|타버|나감|발열"
LEAK = "누설|누수|누출|리크|leak|누유"
JAM = "걸림|걸리|끼임|끼어|끼여|막힘|막혀|고착|적체|정체|충돌|간섭"
POSITION_FAILURE = "(?:원점|타이밍|위치|정렬|텐션)(?:이|가)?(?:틀어짐|틀어|틀려|이상|불량)"
TEMPERATURE_FAILURE = "온도(?:저하|상승|이상|불량|불안정|안올|안내)|과열"
ACT = (
    "교체|교환|수리(?!크)|정비|조정|재조정|조절|점검|청소|보수|가공|용접|체결|고정|재조임|세팅|리셋|reset|재부팅|"
    "보강|수정|교정|calibration|영점|분해|조립|급유|도포|a급|신규|온오프|전원종료|전원차단"
)


def symptom_pattern(major: str, middle: str) -> str:
    """Require an observed failure/repair suited to the named component family."""
    # Physical damage and wear can occur on every named part, including sensors
    # and controller housings; family-specific expressions extend this base.
    groups = [FAIL, BREAK, WEAR, ACT]
    if major == "전기·제어":
        groups += [ELEC, LOOSE]
        if middle == "센서·검출":
            groups += ["미감지|오감지|이중감지|감지불|감도|오염|반응없|헌팅|hunting"]
        elif middle in {"계측·계량기", "검사·계수장치"}:
            groups += ["검출불|계수불|계량불|무게편차|측정불|통신불|통신오류"]
        elif middle == "모터":
            groups += [WEAR, "소음|진동|부하|물혼입"]
        elif middle in {"제어기·I/O·통신", "구동제어기", "조작·표시장치"}:
            groups += ["통신오류|통신불|접속불|반응없|먹통"]
        elif middle == "히터·온도제어":
            groups += [WEAR, TEMPERATURE_FAILURE]
        elif middle == "날인·인쇄장치":
            groups += ["번짐|인쇄불|날인불|과다|부족|막힘", TEMPERATURE_FAILURE]
        elif middle == "로봇":
            groups += [JAM, POSITION_FAILURE, "원점|정렬|티칭"]
    elif major == "기계":
        groups += [WEAR, LOOSE, JAM]
        if middle in {"베어링·부싱", "감속기", "축·커플링·키", "기어·스프라켓"}:
            groups += ["소음|진동|누유"]
        if middle in {"벨트·풀리", "체인·링크"}:
            groups += ["늘어|미끄|텐션"]
        if middle in {"씰링기구", "커팅기구", "성형기구"}:
            groups += [
                "단선|실링불|씰링불|성형불|컷팅불|커팅불|틀어|틀려",
                TEMPERATURE_FAILURE,
                POSITION_FAILURE,
            ]
        if middle == "성형기구":
            groups += [LEAK]
        if middle in {"가이드·레일", "스틱공급기구", "인계·정렬기구"}:
            groups += [POSITION_FAILURE, "틀어|틀려|원점|타이밍"]
        if middle == "컨베어":
            groups += [POSITION_FAILURE]
        if middle == "충진·분사기구":
            groups += [LEAK, "분사불|충진불|과투입|미투입"]
    elif major == "공압·진공":
        groups += [LEAK, LOOSE, "압력저하|압력불량|공급불|안걸|약함|약해|부족|막힘"]
        if middle in {"솔레노이드밸브", "공압밸브·조절기"}:
            groups += [ELEC, "닫힘|열림|안열|안닫|미동작"]
        if middle == "실린더":
            groups += [WEAR, JAM, "동작불|작동불|스트로크불"]
    elif major == "유체·배관":
        groups += [LEAK, WEAR, LOOSE, "핀홀|막힘|역류|이물|혼입"]
        if middle == "펌프":
            groups += [ELEC, "소음|진동|공급불|토출불|압력저하"]
        elif middle == "밸브·액추에이터":
            groups += ["닫힘|열림|안열|안닫|오조작|피드백|과투입"]
        elif middle == "필터":
            groups += ["오염|자력|차압|압력저하"]
    elif major == "온도·냉각":
        groups += [LEAK, ELEC, "냉동불|냉각불|냉기부족|냉매부족|온도이상|온도저하|과열|핀홀|막힘"]
    elif major == "공정·운전":
        groups += [JAM, "오염|주름|접착불"]
    else:
        raise ValueError(f"Unknown catalogue major: {major}")
    pattern = alternation(*groups)
    if len(pattern) > 1000:
        raise ValueError(f"Symptom pattern too long: {major} / {middle}")
    return pattern


def alternation(*groups: str) -> str:
    """Prefer full expressions without splitting alternatives inside regex groups."""
    tokens = set()
    for group in groups:
        depth = brackets = start = 0
        escaped = False
        for index, char in enumerate(group):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == "[":
                brackets += 1
            elif char == "]":
                brackets = max(0, brackets - 1)
            elif not brackets:
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                elif char == "|" and depth == 0:
                    tokens.add(group[start:index])
                    start = index + 1
        tokens.add(group[start:])
    tokens.discard("")
    return "|".join(sorted(tokens, key=lambda token: (-len(token), token)))


# Process categories describe what happened to the product or material, not a part.
PROCESS_SYMPTOMS = {
    "제품 걸림·막힘": JAM,
    "제품 낙하": "떨어|낙하|넘어|쓰러",
    # Only a stated defect or physical damage; generic trouble may be the feeding mechanism.
    "자재 불량": "불량|" + BREAK,
}


def load_catalog(path: Path = CATALOG_PATH) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not payload.get("categories"):
        raise ValueError("Invalid classification catalogue schema")
    categories = payload["categories"]
    paths = [(item["major"], item["middle"], item["minor"]) for item in categories]
    if len(paths) != len(set(paths)) or len({item["code"] for item in categories}) != len(paths):
        raise ValueError("Duplicate catalogue category or code")
    group_paths = {
        (group["major"], group["middle"], minor)
        for group in payload["groups"]
        for minor in group["minors"]
    }
    if group_paths != set(paths):
        raise ValueError("Group selections do not match the complete catalogue")
    return payload


def normalized_alias(value: str, normalization: dict) -> str:
    """Use precisely the same spelling normalization as classification input."""
    return re.sub(r"\s+", "", prepare_text(value, normalization))


def _recent_word_guards(words: tuple[str, ...], window: int = 7) -> str:
    # Fixed-width alternatives implement 'no word in the preceding seven chars'.
    return "".join(
        f"(?<!{re.escape(word)}{'.' * gap})"
        for word in words
        for gap in range(window - len(word) + 1)
    )


def _alias_pattern(alias: str, category: dict) -> str:
    minor = category["minor"]
    pattern = re.escape(alias)
    if alias == "축":
        return r"(?<!압)축(?!소|적)"
    if alias == "키":
        return r"(?:키(?=홈|고정|이탈|마모|파손|교체)|(?<=축)키|(?<=커플링)키)"
    if alias == "풀리":
        pattern = r"(?<!볼트)(?<!너트)(?<!나사)풀리(?!면서|며|고|는|게|지)"
    if minor == "고정블록":
        pattern += r"(?!단자)"
    if minor == "스크류":
        pattern += r"(?!기어)"
    if minor == "전기 커넥터" and not alias.startswith("전기"):
        pattern = _recent_word_guards(("에어", "실린더", "air")) + r"(?<!cylinder)" + pattern
    if minor == "실린더(종류 미상)":
        pattern += r"(?!커넥터|커넥트|컨넥터|connector)"
    if alias == "씰":
        pattern += r"(?!러|링|워터)"
    if alias in {"seal", "packing"}:
        # The gasket/packing part is distinct from a sealer or packing machine.
        pattern = r"(?<![a-z])" + pattern
        pattern += r"(?:(?![a-z])|(?=error|fault|trip|alarm|leak|wear|broken))"
    if minor == "V벨트":
        pattern = r"(?<![a-z])" + pattern
    if alias in {"pc", "key", "plc", "ssr", "tpr"}:
        # Clause whitespace is removed by the classifier, so 'PLC error' becomes
        # 'plcerror'. Permit a recognized English symptom while excluding APC/PCB.
        pattern = r"(?<![a-z])" + pattern
        pattern += r"(?:(?![a-z])|(?=error|fault|trip|alarm|reset|calibration))"
    if alias == "tc":
        pattern = r"(?<![a-z])tc(?![a-z]|선|센서)"
    return pattern


def context_pattern(category: dict, normalization: dict) -> str:
    aliases = {
        normalized_alias(alias, normalization)
        for alias in category.get("matching_aliases", category["aliases"])
    }
    aliases.discard("")
    if not aliases:
        raise ValueError(f"No component name aliases for {category['code']}")
    patterns = [
        _alias_pattern(alias, category) for alias in sorted(aliases, key=lambda a: (-len(a), a))
    ]
    result = "(?:" + "|".join(dict.fromkeys(patterns)) + ")"
    if len(result) > 1000:
        raise ValueError(f"Context pattern too long: {category['code']}")
    return result


def build_rules(catalog: dict | None = None, normalization: dict | None = None) -> list[dict]:
    """One enabled rule per selectable catalogue path, plus optional part-less rules.

    Parts become component rules. Process categories, and the part-less statements a
    category lists in ``nopart_patterns``, become nopart rules that the classifier
    consults only when no part rule matched the record.
    """
    catalog = catalog or load_catalog()
    if normalization is None:
        normalization = json.loads(NORMALIZATION_PATH.read_text(encoding="utf-8"))
    rules = []
    for category in catalog["categories"]:
        aliases = category.get("matching_aliases", category["aliases"])
        specificity = min(15, max(len(normalized_alias(a, normalization)) for a in aliases))
        process = category["kind"] == "process"
        base = 40 if process else 60 if category["kind"] == "unspecified" else 80
        rule = {
            "id": "CAT_" + category["code"].replace("-", "_"),
            "enabled": True,
            "priority": base + specificity,
            "major": category["major"],
            "middle": category["middle"],
            "minor": category["minor"],
            "context": context_pattern(category, normalization),
            "symptom": alternation(PROCESS_SYMPTOMS[category["minor"]])
            if process
            else alternation(FAIL, ACT)
            if category.get("match_policy") == "wholebody"
            else symptom_pattern(category["major"], category["middle"]),
            "exclude": "",
            "role": "nopart" if process else "component",
        }
        rules.append(rule)
        if category.get("nopart_patterns"):
            rules.append(
                {
                    **rule,
                    "id": rule["id"] + "_NOPART",
                    "priority": 40,
                    "context": "(?:" + "|".join(category["nopart_patterns"]) + ")",
                    # '...WAGO 31 발생' states the error itself.
                    "symptom": alternation(rule["symptom"], "발생"),
                    "role": "nopart",
                }
            )
    return validate_rules(rules)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--normalization", type=Path, default=NORMALIZATION_PATH)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "config" / "classification_config.xlsx"
    )
    parser.add_argument(
        "--json-output", type=Path, help="Write validated rows for workbook authoring"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    normalization = json.loads(args.normalization.read_text(encoding="utf-8"))
    rules = build_rules(load_catalog(args.catalog), normalization)
    print(f"{len(rules)} catalogue rules valid")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if not args.dry_run:
        write_rules(args.output, rules)
        print("written", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
