"""Public part/symptom axes, kept separate from the source part-name library."""

from __future__ import annotations

import hashlib
import json
import re

CLASSIFICATION_SCHEMA = "equipment_part_failure_v3"
PREVIOUS_CLASSIFICATION_SCHEMA = "equipment_part_symptom_v2"
LEGACY_CLASSIFICATION_SCHEMA = "part_symptom_v1"
LEGACY_CLASSIFICATION_SCHEMAS = frozenset(
    {LEGACY_CLASSIFICATION_SCHEMA, PREVIOUS_CLASSIFICATION_SCHEMA}
)
UNKNOWN_EQUIPMENT = "상세설비 미상"
UNKNOWN_PART = "세부 부품 미기재"
UNKNOWN_SYMPTOM = "현상 미기재"

# Only observed failures appear here; completed work is a separate action axis.
SYMPTOM_PATTERNS = (
    (
        "손상·파손",
        r"손상|스크레치|스크래치|파손|부러|깨짐|깨져|절단|끊어|끈어|끊김|찢어|터짐|터져|크랙|crack|금감|broken",
    ),
    ("마모", r"마모|닳"),
    ("부식", r"부식|녹발생|녹슴|^녹$"),
    ("변형", r"휨|휘어|변형|뒤틀|찌그러"),
    ("이탈·풀림", r"풀림|풀려|풀리면|풀리며|풀리고|이탈|빠짐|빠져|탈락|분리|흔들|뒤집|헐거|유격"),
    ("누설", r"누설|누수|누출|리크|leak|누유|핀홀"),
    ("막힘·걸림", r"걸림|걸리|끼임|끼어|끼여|막힘|막혀|고착|적체|정체|충돌|간섭|jam|stuck"),
    ("단선", r"단선"),
    ("소손·단락", r"소손|쇼트|short|합선|누전|단락|타버"),
    ("보호장치 동작", r"트립|trip|차단기.{0,12}떨어|차단기차단"),
    ("과부하·과전류", r"과부하|과전류|overload|overcurrent"),
    (
        "동작불량",
        r"오작동|작동불|작동안|미작동|미가동|미구동|구동불|동작불|미동작|멈춤|멈춰|정지|불능|안됨|안되|먹통|반응없|닫힘|열림|안열|안닫",
    ),
    (
        "감지불량",
        r"미감지|오감지|이중감지|감지불|검출불|계수불|계량불|측정불|무게편차|헌팅|hunting",
    ),
    (
        "통신·입출력 이상",
        r"통신|접속불|network\s*station\s*in\s*defect|입출력.{0,5}(?:이상|오류|불량)|inputs.?outputs\s*network",
    ),
    ("소음·진동", r"소음|진동"),
    (
        "온도이상",
        r"과열|과냉|발열|동결|결빙|냉동불|냉각불|냉기부족|냉매부족|온도(?:저하|상승|이상|불량|불안정|안올|안내)",
    ),
    ("압력이상", r"압력(?:저하|상승|이상|불량|과다|부족)|공급불|토출불|안걸|약함|약해"),
    ("오염", r"오염|이물|혼입"),
    ("위치·설정이상", r"틀어|틀려|원점|타이밍|늘어|미끄|텐션|정렬|티칭"),
    ("낙하", r"떨어|낙하|넘어|쓰러"),
    ("자재 불량", r"자재불량"),
    (
        "고장·이상",
        r"고장|이상|불량|오류|에러|error|트러블|비정상|알람|alarm|fault|failed|문제|다운|나감|망가",
    ),
)
SYMPTOM_NAMES = tuple(name for name, _ in SYMPTOM_PATTERNS) + (UNKNOWN_SYMPTOM,)
COMPILED_SYMPTOMS = tuple((name, re.compile(pattern, re.I)) for name, pattern in SYMPTOM_PATTERNS)
ACTION_PATTERNS = (
    ("교체", r"교체|교환|신규|새것|[ab]급|replaced"),
    ("수리·정비", r"수리(?!크)|정비|재정비|가공|재가공|보수|용접|보강|연마|repair"),
    (
        "조정",
        r"조정|조절|세팅|셋팅|수정|교정|adjusted",
    ),
    ("점검", r"점검|확인|inspected"),
    ("청소·급유", r"청소|세척(?!장|기|설비|라인|부)|급유|도포"),
    ("체결·조립", r"체결|고정(?!볼트|너트|핀|브라켓|브래킷|장치|부|축|판)|재조임|분해|조립"),
    ("리셋·재가동", r"리셋|reset|재부팅|온오프|재투입|재가동|전원재동작|생산재개|복구"),
)


def part_name(value: str) -> str:
    """Keep the kind-unspecified distinction and normalize only true synonyms."""
    from core.public_taxonomy import canonical_part_name

    return canonical_part_name(value)


def part_key(major: str, part: str, detail_equipment: str = "") -> str:
    identity = json.dumps(
        [major, detail_equipment, part_name(part)]
        if detail_equipment
        else [major, part_name(part)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "PART:" + hashlib.sha256(identity.encode()).hexdigest()[:20]


def canonical_symptom(value: str) -> str:
    return {
        "손상": "손상·파손",
        "파손": "손상·파손",
        "통신이상": "통신·입출력 이상",
        "과부하": "과부하·과전류",
        "증상 미기재": UNKNOWN_SYMPTOM,
        "교체": UNKNOWN_SYMPTOM,
    }.get(value, value)


def symptom_names(words: list[str], context: str = "") -> list[str]:
    names = {name for word in words for name, pattern in COMPILED_SYMPTOMS if pattern.search(word)}
    if "낙하" in names and re.search(r"차단기.{0,12}떨어", context):
        names.discard("낙하")
        names.add("보호장치 동작")
    if "낙하" in names and re.search(r"(?:품온|온도).{0,8}떨어", context):
        names.discard("낙하")
        names.add("온도이상")
    if "낙하" in names and re.search(r"(?:압력|진공도).{0,8}떨어", context):
        names.discard("낙하")
        names.add("압력이상")
    if len(names) > 1:
        names.discard("고장·이상")
    return [name for name in SYMPTOM_NAMES if name in names]


def action_names(words: list[str]) -> list[str]:
    return [
        name
        for name, pattern in ACTION_PATTERNS
        if any(re.search(pattern, word, re.I) for word in words)
    ]


def incomplete_action_context(before: str, after: str) -> bool:
    """Use the same unperformed-work boundary for evidence and displayed actions."""
    return bool(
        re.search(
            r"미실시|(?:not|never|without)$|(?:늦은|지연된|지연|대기중)$",
            before,
            re.I,
        )
        or (
            re.search(r"추후|향후|예정|계획", before, re.I)
            and not re.match(r"^(?:완료|실시|하였|했|함)", after)
        )
        or re.match(r"^(?:이|가|는|을|를)?(?:늦음|늦은|늦어|지연)", after)
        or re.search(
            r"예정|계획|요망|요청|필요|해야|대기|작업전|미실시|미완료|안(?:함|했|하)|하지않|하지안|하지못|못함|불가|불필요|취소|보류|없음|planned|required|needed|pending|requested|cancel",
            after,
            re.I,
        )
    )


def extract_actions(text: str) -> list[str]:
    """Keep completed actions in their own clause; planned/negated work is excluded."""
    from core.classifier import clauses

    output = []
    for chunk in clauses(text):
        for label, pattern in ACTION_PATTERNS:
            for match in re.finditer(pattern, chunk, re.I):
                before = chunk[max(0, match.start() - 10) : match.start()]
                after = chunk[match.end() : match.end() + 12]
                if incomplete_action_context(before, after):
                    continue
                if label not in output:
                    output.append(label)
    return output


def migrate_legacy_category(category: dict) -> dict:
    """Preserve a previously confirmed part without inventing its symptom."""
    if category.get("schema") == CLASSIFICATION_SCHEMA:
        return dict(category)
    original = {key: str(category[key]).strip() for key in ("major", "middle", "minor")}
    if category.get("schema") in LEGACY_CLASSIFICATION_SCHEMAS:
        return {
            **category,
            "middle": part_name(original["middle"]),
            "minor": canonical_symptom(original["minor"]),
            "actions": ["교체"] if original["minor"] == "교체" else category.get("actions", []),
            "detail_equipment": category.get("detail_equipment") or UNKNOWN_EQUIPMENT,
            "schema": CLASSIFICATION_SCHEMA,
            "part_key": part_key(
                original["major"],
                original["middle"],
                category.get("detail_equipment") or UNKNOWN_EQUIPMENT,
            ),
            "legacy_category": original,
            "legacy_schema": category["schema"],
        }
    explicit_process_symptom = {
        "제품 걸림·막힘": "막힘·걸림",
        "제품 낙하": "낙하",
        "자재 불량": "자재 불량",
    }.get(original["minor"], UNKNOWN_SYMPTOM)
    return {
        **category,
        "major": original["major"],
        "detail_equipment": UNKNOWN_EQUIPMENT,
        "middle": part_name(original["minor"]),
        "minor": explicit_process_symptom,
        "schema": CLASSIFICATION_SCHEMA,
        "part_key": part_key(original["major"], original["minor"]),
        "part_group": original["middle"],
        "part_type": original["minor"],
        "legacy_category": original,
    }


def manual_category(category: dict, schema: str | None = None) -> dict:
    if schema in LEGACY_CLASSIFICATION_SCHEMAS:
        return migrate_legacy_category({**category, "schema": schema})
    if schema != CLASSIFICATION_SCHEMA and category.get("schema") != CLASSIFICATION_SCHEMA:
        return migrate_legacy_category(category)
    return {
        **category,
        "middle": part_name(category["middle"]),
        "minor": canonical_symptom(category["minor"]),
        "schema": CLASSIFICATION_SCHEMA,
        "detail_equipment": category.get("detail_equipment") or UNKNOWN_EQUIPMENT,
        "part_key": part_key(
            category["major"],
            category["middle"],
            category.get("detail_equipment") or UNKNOWN_EQUIPMENT,
        ),
        "part_type": category.get("part_type", category["middle"]),
    }
