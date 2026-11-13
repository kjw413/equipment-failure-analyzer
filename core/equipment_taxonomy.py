"""Resolve the affected machine independently from its replaceable parts.

Only explicit machine aliases are recognized. The registered MES asset is kept
as source data and cannot establish the actual affected machine on its own.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from core.failure_modes import UNKNOWN_EQUIPMENT, UNKNOWN_PART, part_name
from core.models import UserError

SUCTION_COMPONENT_SUFFIX = (
    r"진공|패드|컵|밸브|솔밸브|제어밸브|자동컨트롤밸브|라인|배관|호스|게이지|블럭|블록"
    r"|실린더|에어커넥터|연결부|센서"
)

DEFAULT_EQUIPMENT_TYPES = (
    ("카토닝머신", ("카토닝머신", "카톤머신", "멀티카톤머신", "멀티카톤", "cartoner")),
    ("제대기", ("제대기",)),
    ("스틱인서터", ("스틱인서터", "스틱삽입기")),
    ("필러·충진기", ("필러", "충진기", "충전기", "filler")),
    ("컨베어", ("컨베어", "컨베이어", "콘베어", "콘베이어", "conveyor", "con'v", "c/v")),
    ("프리저", ("프리저", "프리져", "프리자", "프리젠", "freezer")),
    (
        "파렛타이저",
        (
            "파렛타이저",
            "파렛타이져",
            "파레타이저",
            "팔레타이저",
            "로봇팔레타이져",
            "로봇파렛타이져",
        ),
    ),
    ("로봇", ("로봇", "로보트", "robot")),
    ("케이서", ("케이서", "케이샤", "케이셔", "케이사", "멀티케이서", "caser")),
    ("씰러", ("씰러", "실러", "씨러", "sealer")),
    ("포장기", ("포장기", "필로우포장기", "필름포장기")),
    ("세척기", ("세척기", "washer", "paa washer", "크레이트세척기")),
    ("동결설비", ("동결설비", "동결기", "qft", "ht-300", "스파이럴qft")),
    ("날인기", ("날인기", "프린터", "printer")),
    ("피더", ("피더", "feeder")),
    ("검사기", ("검사기", "x-ray", "xray", "검출기")),
    ("봉함기", ("봉함기",)),
    ("제함기", ("제함기",)),
    ("탱크", ("탱크", "tank")),
    ("포장카운터", ("포장카운터",)),
)


def validate_equipment_types(value) -> list[dict]:
    if not isinstance(value, (list, tuple)):
        raise UserError("상세설비 표준 목록은 배열이어야 합니다.")
    seen, checked = set(), []
    for row in value:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("name"), str)
            or not row["name"].strip()
        ):
            raise UserError("상세설비 표준명과 별칭을 확인하세요.")
        name = row["name"].strip()
        if name in seen:
            raise UserError(f"상세설비 표준명이 중복됩니다: {name}")
        seen.add(name)
        aliases = row.get("aliases", [])
        if not isinstance(aliases, (list, tuple)) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise UserError(f"상세설비 {name}: 별칭은 비어 있지 않은 문자열 목록이어야 합니다.")
        checked.append({"name": name, "aliases": list(dict.fromkeys([name, *aliases]))})
    return checked


def equipment_types(value=None) -> list[dict]:
    if value is None:
        value = [
            {"name": name, "aliases": list(aliases)} for name, aliases in DEFAULT_EQUIPMENT_TYPES
        ]
    return validate_equipment_types(value)


def equipment_type_names(value=None) -> tuple[str, ...]:
    return tuple(sorted({UNKNOWN_EQUIPMENT, *(row["name"] for row in equipment_types(value))}))


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold())


class EquipmentResolver:
    def __init__(self, types=None):
        self.aliases = sorted(
            {
                (_compact(alias), row["name"])
                for row in equipment_types(types)
                for alias in row["aliases"]
            },
            key=lambda item: (-len(item[0]), item),
        )
        self.body_aliases = {}
        for alias, name in self.aliases:
            self.body_aliases.setdefault(name, set()).add(alias)

    def component_name(self, part: str, equipment: str) -> str:
        """A whole machine name does not establish any replaceable subpart."""
        name = part_name(part)
        bare = re.sub(r"\((?:종류|방식|세부|세부 부품)\s*미상\)$", "", name).strip()
        if _compact(bare) in self.body_aliases.get(equipment, ()):
            return UNKNOWN_PART
        return name

    def mentions(self, value: str) -> list[tuple[int, int, str]]:
        text = _compact(value)
        matches = []
        for alias, name in self.aliases:
            for match in re.finditer(re.escape(alias), text):
                start, end = match.span()
                if alias == "석션" and re.match(SUCTION_COMPONENT_SUFFIX, text[end:]):
                    continue
                # A specific name such as 로봇파렛타이져 owns the embedded 로봇.
                if any(
                    start < other_end and end > other_start for other_start, other_end, _ in matches
                ):
                    continue
                if alias.isascii() and alias.isalnum():
                    prefix_word = start and text[start - 1].isalpha() and text[start - 1].isascii()
                    suffix_word = end < len(text) and text[end].isalpha() and text[end].isascii()
                    # RuleClassifier removes spaces: "filler motor trip" becomes
                    # "fillermotortrip". Recognize known maintenance words while
                    # rejecting unrelated words such as "refiller"/"freezersideways".
                    known_suffix = re.match(
                        r"motor|sensor|bearing|pump|belt|chain|plc|trip|fault|error|alarm|broken|damage|leak|normal|replace|repair|inspect",
                        text[end:],
                    )
                    if prefix_word or (suffix_word and not known_suffix):
                        continue
                matches.append((start, end, name))
        return sorted(matches)

    @staticmethod
    def _value(name: str, source: str, evidence: str) -> dict:
        return {
            "detail_equipment": name,
            "detail_equipment_source": source,
            "detail_equipment_evidence": evidence,
        }

    def resolve(self, chunks, pairs, code_mid="", registered="") -> list[dict]:
        """Bind machine names to the same clause as this part's fault/action.

        A bare preceding machine label is also accepted (컨베어 / 베어링 파손).
        Names from another sentence with their own normal/planned work do not
        become locations for this part. Conflicting explicit locations remain
        separate candidates so the caller can request one human final choice.
        """
        found = []
        conflicting_later_location = False
        excluded = set()
        active = set()
        for chunk in chunks:
            mentions = self.mentions(chunk)
            for position, (start, end, name) in enumerate(mentions):
                tail = _compact(chunk)[
                    end : mentions[position + 1][0]
                    if position + 1 < len(mentions)
                    else len(_compact(chunk))
                ]
                negative = re.search(
                    r"정상|이상없|고장없|불량없|예정|계획|교체안함|normal|planned", tail
                )
                remaining = re.sub(r"정상|이상없|고장없|불량없|normal", "", tail)
                actual_fault = re.search(
                    r"파손|손상|마모|누설|누수|누유|단선|소손|불량|고장|트립|trip|fault|error|broken|damage|leak",
                    remaining,
                )
                if negative and not actual_fault:
                    excluded.add(name)
                elif actual_fault:
                    active.add(name)
        excluded.difference_update(active)
        for pair in pairs:
            chunk = chunks[pair.clause]
            mentions = [mention for mention in self.mentions(chunk) if mention[2] not in excluded]
            before = [mention for mention in mentions if mention[0] <= pair.c0]
            if before:
                nearest = max(before, key=lambda mention: mention[0])
                mentions = [nearest]
                for earlier in reversed(before[:-1]):
                    connector = _compact(chunk)[earlier[1] : mentions[0][0]]
                    if not re.fullmatch(r"(?:및|와|과|&|·)+", connector):
                        break
                    mentions.insert(0, earlier)
            elif mentions:
                nearest = min(mentions, key=lambda mention: abs(mention[0] - pair.c1))
                # A machine introduced after this part's own failure/action
                # belongs to the later statement, not its earlier location.
                ended_before_machine = any(
                    symptom.clause == pair.clause and symptom.end <= nearest[0]
                    for symptom in pair.symptoms
                )
                separate_later_subject = nearest[0] >= pair.c1
                if ended_before_machine or separate_later_subject:
                    # The source explicitly introduces another subject later.
                    # Its MES area cannot supply the earlier part's location.
                    conflicting_later_location = True
                    mentions = []
                else:
                    mentions = [nearest]
            elif pair.clause:
                previous = chunks[pair.clause - 1]
                previous_mentions = self.mentions(previous)
                if len(previous_mentions) == 1:
                    start, end, name = previous_mentions[0]
                    remainder = _compact(previous)[:start] + _compact(previous)[end:]
                    if len(remainder) <= 12 and re.fullmatch(
                        r"[\d번호기측부상하좌우전후입출구:#\-]*", remainder
                    ):
                        found.append(self._value(name, "원문", previous + " / " + chunk))
            for start, end, name in mentions:
                between = _compact(chunk)[end : max(end, pair.c0)]
                if re.search(r"정상|이상없|불량없|교체예정|점검예정|교체안함", between):
                    continue
                found.append(self._value(name, "원문", chunk))
        if not found and not conflicting_later_location:
            for value, source in ((code_mid, "비가동코드(중)"),):
                names = list(
                    dict.fromkeys(
                        name for _, _, name in self.mentions(value) if name not in excluded
                    )
                )
                if names:
                    found = [self._value(name, source, str(value)) for name in names]
                    break
        if not found:
            return [self._value(UNKNOWN_EQUIPMENT, "미기재", "")]
        return list({item["detail_equipment"]: item for item in found}.values())
