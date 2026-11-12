"""Evidence-first draft policy; deliberately separate from production defaults."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

UNKNOWN_DOMAIN = "분야 미상"
UNKNOWN_MACHINE = "상세설비 미상"
UNKNOWN_PART = "세부 부품 미기재"
UNKNOWN_MODE = "현상 미기재"

MODES = [
    (
        "손상·파손",
        r"손상|파손|부러|깨짐|깨져|절단|끊어|끈어|끊김|찢어|터짐|터져|크랙|crack|금감|broken|스크래치|스크레치",
    ),
    ("마모", r"마모|닳"),
    ("부식", r"부식|녹발생|녹슴"),
    ("변형", r"휨|휘어|변형|뒤틀|찌그러"),
    ("이탈·풀림", r"풀림|풀려|이탈|빠짐|빠져|탈락|헐거|유격"),
    ("누설", r"누설|누수|누출|리크|leak|누유|핀홀"),
    ("막힘·걸림", r"걸림|걸리|끼임|끼어|끼여|막힘|막혀|적체|충돌|간섭|jam"),
    ("단선", r"단선"),
    ("소손·단락", r"소손|쇼트|short|합선|누전|단락|타버"),
    ("보호장치 동작", r"차단기.{0,12}(?:떨어|트립|trip)|차단기차단|breakertrip"),
    ("과부하·과전류", r"과부하|과전류|overload|overcurrent"),
    (
        "동작불량",
        r"오작동|작동불|작동안|미작동|미가동|미구동|구동불|동작불|미동작|멈춤|멈춰|불능|안됨|안되|먹통|반응없|안열|안닫",
    ),
    ("감지불량", r"미감지|오감지|감지불|검출불|계수불|계량불|측정불|무게편차|피드백오류"),
    (
        "통신·입출력 이상",
        r"통신(?:이상|불량|에러|오류|단절|불)|접속불|networkstationindefect|inputs/outputsnetwork|i/o.{0,8}(?:에러|오류|불량)|입출력.{0,6}(?:에러|오류|불량)",
    ),
    ("소음·진동", r"소음|진동"),
    (
        "온도이상",
        r"과열|발열|과냉|동결|결빙|냉동불|냉각불|냉기부족|온도.{0,5}(?:이상|불량|상승|하강|편차|안올|안내)|냉매부족",
    ),
    ("압력이상", r"압력.{0,5}(?:이상|불량|과다|부족|저하|상승|편차)|토출불"),
    ("오염", r"오염|이물|혼입"),
    (
        "위치·설정이상",
        r"틀어|원점.{0,5}(?:이상|불량|오류|안잡)|타이밍.{0,5}(?:이상|불량|안맞)|미끄|정렬불량|위치불량|텐션불량",
    ),
    ("낙하", r"낙하|떨어짐|떨어져|넘어짐|쓰러"),
    ("자재 불량", r"자재불량"),
    (
        "고장·이상",
        r"고장|이상|불량|오류|에러|error|트러블|비정상|알람|alarm|fault|failed|나감|셧다운",
    ),
]
ACTION_PATTERNS = [
    ("교체", r"교체|교환|새것|[ab]급"),
    ("수리·정비", r"수리|정비|가공|보수|용접|보강|연마"),
    ("조정", r"조정|조절|세팅|셋팅|교정|높이조절"),
    ("점검", r"점검|확인"),
    ("청소·급유", r"세척|청소|급유|도포"),
    ("체결·조립", r"체결|재조임|분해|조립"),
    ("리셋·재가동", r"리셋|reset|재부팅|온오프|재투입|전원재동작|생산재개|복구"),
]
CLAUSE = re.compile(r"\n|\r|->|=>|→|;|(?<![A-Za-z])/(?![A-Za-z])|(?<!\d)\.(?!\d)")
BLOCK = re.compile(
    r"정상|이상없|문제없|고장없|불량아님|미발생|예정|계획|의심|추정|미실시|교체안함|교체하지않"
)


@lru_cache(maxsize=8192)
def compact(text):
    return re.sub(r"\s+", "", str(text or "").replace("_x000D_", "\n")).casefold()


@lru_cache(maxsize=4096)
def literal_pattern(token):
    return re.compile(re.escape(token))


@dataclass(frozen=True)
class Mention:
    start: int
    end: int
    name: str
    family: str
    alias: str
    domain: str = ""


def find_entities(text, entities):
    """A specific surface owns overlapping generic surfaces within one axis."""
    hits = []
    for entity in entities:
        for alias in entity["aliases"]:
            token = compact(alias)
            if not token:
                continue
            if len(token) == 1 and token not in {"축", "키"}:
                continue
            pattern = (
                re.compile(re.escape(token) + r"(?=마모|파손|손상|이탈|풀림|부러|교체|홈)")
                if len(token) == 1
                else literal_pattern(token)
            )
            for match in pattern.finditer(text):
                if token.isascii() and token.isalnum():
                    before = text[match.start() - 1 : match.start()] if match.start() else ""
                    after = text[match.end() : match.end() + 1]
                    if (before and before.isascii() and before.isalpha()) or (
                        after
                        and after.isascii()
                        and after.isalpha()
                        and not re.match(
                            r"motor|sensor|bearing|fault|error|trip|broken|leak|replace",
                            text[match.end() :],
                        )
                    ):
                        continue
                hits.append(
                    Mention(
                        match.start(),
                        match.end(),
                        entity["name"],
                        entity["family"],
                        alias,
                        entity.get("original_domain", ""),
                    )
                )
    hits.sort(key=lambda x: (-(x.end - x.start), x.start, x.name))
    kept = []
    for hit in hits:
        overlaps = [x for x in kept if hit.start < x.end and hit.end > x.start]
        if not overlaps or all(
            (hit.start, hit.end) == (x.start, x.end) and hit.name != x.name for x in overlaps
        ):
            kept.append(hit)
    return sorted(kept, key=lambda x: (x.start, x.end, x.name))


def failure_modes(text):
    output = []
    for name, pattern in MODES:
        for match in re.finditer(pattern, text, re.I):
            before = re.split(r"[(),;]", text[max(0, match.start() - 12) : match.start()])[-1]
            after = re.split(r"[(),;]", text[match.end() : match.end() + 12])[0]
            context = before + match.group() + after
            if BLOCK.search(context):
                continue
            if name == "낙하" and re.search(
                r"차단기.{0,15}떨어", text[max(0, match.start() - 15) : match.end() + 3]
            ):
                continue
            if name == "고장·이상" and any(
                x[0] != "고장·이상" and match.start() < x[2] and match.end() > x[1] for x in output
            ):
                continue
            output.append((name, match.start(), match.end(), match.group()))
    return output


def domain_for(part, mode, text):
    if mode in {"소손·단락", "단선", "보호장치 동작", "과부하·과전류", "통신·입출력 이상"}:
        return "전기·제어"
    if part is None:
        return "온도·냉각" if mode == "온도이상" else UNKNOWN_DOMAIN
    if part.family == "모터":
        return "기계" if mode in {"마모", "변형", "이탈·풀림", "소음·진동"} else UNKNOWN_DOMAIN
    if part.name == "밸브 제어헤드":
        return "전기·제어"
    if part.family == "씰·패킹·링" and mode in {"손상·파손", "마모", "변형", "이탈·풀림"}:
        return "기계"
    if mode == "누설":
        if re.search(r"냉매|icm", text):
            return "온도·냉각"
        if re.search(r"에어|공압|진공|실린더", text):
            return "공압·진공"
        return "유체·배관"
    if mode in {"온도이상", "압력이상"}:
        return "온도·냉각" if mode == "온도이상" else part.domain or UNKNOWN_DOMAIN
    return part.domain or UNKNOWN_DOMAIN


def draft_classify(description, mid, equipment, parts):
    source = str(description or "").replace("_x000D_", "\n")
    candidates, actions, observed_parts, observed_machines, flags = [], [], [], [], []
    clauses = [compact(x) for x in CLAUSE.split(source) if compact(x)]
    fallback = list(dict.fromkeys(x.name for x in find_entities(compact(mid), equipment)))
    uncertain = bool(re.search(r"의심|추정|예상|아마", source))
    last_machine = None
    for text in clauses:
        machines = find_entities(text, equipment)
        components = find_entities(text, parts)
        observed_parts.extend(x.name for x in components)
        observed_machines.extend(x.name for x in machines)
        for name, pattern in ACTION_PATTERNS:
            for match in re.finditer(pattern, text, re.I):
                tail = text[match.end() : match.end() + 10]
                if not re.search(r"예정|계획|미실시|안함|하지않", tail):
                    actions.append(name)
        for mode, start, end, word in failure_modes(text):
            # 보호장치 동작 includes the 차단기 subject itself.
            preceding = [x for x in components if x.start <= start]
            part = max(preceding, key=lambda x: (x.end, -len(x.name))) if preceding else None
            if part and start - part.end > 20:
                part = None
            if part is None:
                following = [x for x in components if x.start <= end + 8 and x.end >= start]
                part = min(following, key=lambda x: abs(x.start - start)) if following else None
            target = part.start if part else start
            own = [x for x in machines if x.start <= target]
            machine = (
                max(own, key=lambda x: x.end)
                if own
                else machines[0]
                if len({x.name for x in machines}) == 1
                else None
            )
            machine_name = (
                machine.name
                if machine
                else last_machine or (fallback[0] if len(fallback) == 1 else UNKNOWN_MACHINE)
            )
            machine_source = (
                "원문"
                if machine or last_machine
                else "원본 중분류"
                if len(fallback) == 1
                else "근거 부족"
            )
            linked_parts = [part]
            if part:
                for earlier in reversed([x for x in components if x.end <= part.start]):
                    connector = text[earlier.end : linked_parts[0].start]
                    if not re.fullmatch(r"(?:및|,|·|와|과|&)+", connector):
                        break
                    linked_parts.insert(0, earlier)
            for linked in linked_parts:
                candidates.append(
                    {
                        "major": domain_for(linked, mode, text),
                        "detail_equipment": machine_name,
                        "middle": linked.name if linked else UNKNOWN_PART,
                        "minor": mode,
                        "part_group": linked.family if linked else "",
                        "symptom_evidence": word,
                        "part_evidence": linked.alias if linked else "",
                        "equipment_source": machine_source,
                        "evidence": text,
                    }
                )
        if machines:
            last_machine = machines[-1].name
    if not candidates:
        for name in dict.fromkeys(observed_parts):
            matches = [x for x in parts if x["name"] == name]
            candidates.append(
                {
                    "major": UNKNOWN_DOMAIN,
                    "detail_equipment": observed_machines[-1]
                    if observed_machines
                    else fallback[0]
                    if len(fallback) == 1
                    else UNKNOWN_MACHINE,
                    "middle": name,
                    "minor": UNKNOWN_MODE,
                    "part_group": matches[0]["family"],
                    "symptom_evidence": "",
                    "part_evidence": "",
                    "equipment_source": "후보 문맥",
                    "evidence": compact(source),
                }
            )
    specific_keys = {
        (x["detail_equipment"], x["middle"]) for x in candidates if x["minor"] != "고장·이상"
    }
    candidates = [
        x
        for x in candidates
        if x["minor"] != "고장·이상" or (x["detail_equipment"], x["middle"]) not in specific_keys
    ]
    candidates = list(
        {
            tuple(x[k] for k in ("major", "detail_equipment", "middle", "minor")): x
            for x in candidates
        }.values()
    )
    if uncertain:
        flags.append("의심·추정 표현")
    if len(candidates) > 1:
        flags.append("복수 대상·현상 또는 연결 확인")
    if not candidates:
        flags.append("분류 근거 부족")
    if any(x["major"] == UNKNOWN_DOMAIN for x in candidates):
        flags.append("분야 근거 부족")
    if any(x["detail_equipment"] == UNKNOWN_MACHINE for x in candidates):
        flags.append("설비 근거 부족")
    if any(x["minor"] == UNKNOWN_MODE for x in candidates):
        flags.append("현상 미기재·조치만 기재")
    if any(x["middle"] == UNKNOWN_PART for x in candidates):
        flags.append("세부 부품 미기재")
    status = "단일 근거 후보·미확정" if len(candidates) == 1 and not flags else "검토 필요"
    return {
        "candidates": candidates,
        "actions": list(dict.fromkeys(actions)),
        "status": status,
        "review_reasons": flags,
        "parts_mentioned": list(dict.fromkeys(observed_parts)),
        "equipment_mentioned": list(dict.fromkeys(observed_machines)),
    }
