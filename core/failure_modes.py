"""Public part/symptom axes, kept separate from the source part-name library."""

from __future__ import annotations

import hashlib
import json
import re

CLASSIFICATION_SCHEMA = "part_symptom_v1"
UNKNOWN_SYMPTOM = "증상 미기재"

# These are observed phenomena. Repairs and inspections belong to actions.
SYMPTOM_PATTERNS = (
    ("손상", r"손상|스크레치|스크래치"),
    ("파손", r"파손|부러|깨짐|깨져|절단|끊어|끊김|찢어|터짐|터져|크랙|crack|금감|broken"),
    ("마모", r"마모|닳|녹|부식"),
    ("변형", r"휨|휘어|변형|뒤틀|찌그러"),
    ("이탈·풀림", r"풀림|풀려|풀리면|풀리며|풀리고|이탈|빠짐|빠져|탈락|분리|흔들|뒤집|헐거|유격"),
    ("누설", r"누설|누수|누출|리크|leak|누유|핀홀"),
    ("막힘·걸림", r"걸림|걸리|끼임|끼어|끼여|막힘|막혀|적체|정체|충돌|간섭|jam"),
    ("단선", r"단선"),
    ("소손·단락", r"소손|쇼트|short|합선|누전|타버|나감"),
    ("과부하", r"과부하|과전류|부하|trip|트립"),
    (
        "동작불량",
        r"오작동|작동불|작동안|미작동|미가동|미구동|구동불|동작불|미동작|멈춤|멈춰|정지|불능|안됨|안되|먹통|반응없|닫힘|열림|안열|안닫",
    ),
    ("감지불량", r"미감지|오감지|이중감지|감지불|검출불|계수불|계량불|측정불|무게편차"),
    ("통신이상", r"통신|접속불"),
    ("소음·진동", r"소음|진동"),
    ("온도이상", r"온도|과열|발열|동결|결빙|냉동불|냉각불|냉기부족|냉매부족"),
    ("압력이상", r"압력|공급불|토출불|안걸|약함|약해|부족"),
    ("오염", r"오염|이물|혼입"),
    ("위치·설정이상", r"틀어|틀려|원점|타이밍|늘어|미끄|텐션|정렬|티칭"),
    ("낙하", r"떨어|낙하|넘어|쓰러"),
    ("자재 불량", r"자재불량"),
    (
        "고장·이상",
        r"고장|이상|불량|오류|에러|error|트러블|비정상|알람|alarm|fault|failed|문제|다운",
    ),
)
SYMPTOM_NAMES = tuple(name for name, _ in SYMPTOM_PATTERNS) + (UNKNOWN_SYMPTOM,)
COMPILED_SYMPTOMS = tuple((name, re.compile(pattern, re.I)) for name, pattern in SYMPTOM_PATTERNS)
ACTION_PATTERNS = (
    ("교체", r"교체|교환|신규|새것|[ab]급|replaced"),
    ("수리", r"수리|정비|재정비|가공|재가공|보수|용접|보강|repair"),
    (
        "조정",
        r"조정|조절|세팅|수정|교정|영점|위치|각도|타이밍|원점|센터|높이|간격|텐션|감도|길이|adjusted",
    ),
    ("점검", r"점검|확인|inspected"),
    ("청소·급유", r"청소|급유|도포"),
    ("체결·조립", r"체결|고정|재조임|분해|조립"),
    ("전원 차단·종료", r"셧다운|전원종료|전원차단"),
    ("리셋·재가동", r"리셋|reset|재부팅|온오프|재투입|재가동|가동"),
)


def part_name(value: str) -> str:
    """Keep explicit subtypes, shortening only an unspecified-kind suffix."""
    value = str(value).strip()
    if value in {"제품 걸림·막힘", "제품 낙하", "자재 불량"}:
        return "제품·자재"
    return re.sub(r"\((?:종류|방식|세부|세부 부품)\s*미상\)$", "", value).strip()


def part_key(major: str, part: str) -> str:
    identity = json.dumps([major, part_name(part)], ensure_ascii=False, separators=(",", ":"))
    return "PART:" + hashlib.sha256(identity.encode()).hexdigest()[:20]


def symptom_names(words: list[str]) -> list[str]:
    names = {name for word in words for name, pattern in COMPILED_SYMPTOMS if pattern.search(word)}
    if len(names) > 1:
        names.discard("고장·이상")
    return [name for name in SYMPTOM_NAMES if name in names]


def action_names(words: list[str]) -> list[str]:
    return [
        name
        for name, pattern in ACTION_PATTERNS
        if any(re.search(pattern, word, re.I) for word in words)
    ]


def migrate_legacy_category(category: dict) -> dict:
    """Preserve a previously confirmed part without inventing its symptom."""
    if category.get("schema") == CLASSIFICATION_SCHEMA:
        return dict(category)
    original = {key: str(category[key]).strip() for key in ("major", "middle", "minor")}
    explicit_process_symptom = {
        "제품 걸림·막힘": "막힘·걸림",
        "제품 낙하": "낙하",
        "자재 불량": "자재 불량",
    }.get(original["minor"], UNKNOWN_SYMPTOM)
    return {
        **category,
        "major": original["major"],
        "middle": part_name(original["minor"]),
        "minor": explicit_process_symptom,
        "schema": CLASSIFICATION_SCHEMA,
        "part_key": part_key(original["major"], original["minor"]),
        "part_group": original["middle"],
        "part_type": original["minor"],
        "legacy_category": original,
    }


def manual_category(category: dict, schema: str | None = None) -> dict:
    if schema != CLASSIFICATION_SCHEMA and category.get("schema") != CLASSIFICATION_SCHEMA:
        return migrate_legacy_category(category)
    return {
        **category,
        "schema": CLASSIFICATION_SCHEMA,
        "part_key": part_key(category["major"], category["middle"]),
        "part_type": category.get("part_type", category["middle"]),
    }
