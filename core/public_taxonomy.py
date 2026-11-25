"""Public independent axes and the part-family/type navigation master."""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

REPAIR_ACTIONS = (
    "교체",
    "수리·정비",
    "조정",
    "점검",
    "청소·급유",
    "체결·조립",
    "리셋·재가동",
)
DOMAINS = ("기계", "전기·제어", "공압·진공", "유체·배관", "온도·냉각", "공정·운전", "분야 미상")
UNKNOWN_DOMAIN = "분야 미상"
ACTION_ALIASES = {
    "수리": "수리·정비",
    "정비": "수리·정비",
    "재정비": "수리·정비",
    "조절": "조정",
    "세팅": "조정",
    "셋팅": "조정",
    "교환": "교체",
    "청소": "청소·급유",
    "급유": "청소·급유",
    "세척": "청소·급유",
    "체결": "체결·조립",
    "조립": "체결·조립",
    "재부팅": "리셋·재가동",
    "리셋": "리셋·재가동",
    "재가동": "리셋·재가동",
}


def _key(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _bare(value):
    return re.sub(r"\((?:종류|방식|세부|세부 부품)\s*미상\)$", "", str(value)).strip()


@lru_cache(maxsize=1)
def default_catalog():
    root = (
        Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    )
    return json.loads((root / "config/classification_catalog.json").read_text(encoding="utf-8"))


class PublicTaxonomy:
    def __init__(self, value=None, equipment_types=None):
        catalog = default_catalog()
        self.value = value if value is not None else catalog.get("public_taxonomy", {})
        self.domains = tuple(self.value.get("domains", DOMAINS))
        self.parts = self.value.get("parts") or [
            {
                "name": item["minor"],
                "family": item["middle"],
                "aliases": item.get("matching_aliases", item.get("aliases", [])),
                "old_names": [item["minor"]],
            }
            for item in catalog["categories"]
        ]
        self.names, self.groups, self.aliases = {}, {}, {}
        ambiguous_aliases = set()
        for item in self.parts:
            name = item["name"]
            self.names[name] = name
            self.groups[name] = item["family"]
            for alias in [name, _bare(name), *item.get("old_names", []), *item.get("aliases", [])]:
                key = _key(alias)
                if key in ambiguous_aliases:
                    continue
                if key in self.aliases and self.aliases[key] != name:
                    ambiguous_aliases.add(key)
                self.aliases[key] = (
                    name if key not in self.aliases or self.aliases[key] == name else ""
                )
        self.module_names = {}
        for item in (
            equipment_types if equipment_types is not None else catalog.get("equipment_types", [])
        ):
            for alias in [item["name"], *item.get("aliases", [])]:
                self.module_names[_key(alias)] = item["name"]

    def canonical_part(self, name):
        name = str(name or "").strip()
        if name in {"제품·자재", "제품 걸림·막힘", "제품 낙하", "자재 불량"}:
            return "제품·자재"
        return self.aliases.get(_key(name)) or name

    def group(self, name):
        canonical = self.canonical_part(name)
        if canonical == "세부 부품 미기재" or not canonical:
            return "미기재" if canonical else ""
        if canonical == "제품·자재":
            return "제품·자재"
        return self.groups.get(canonical, "기타 부품")

    def component_name(self, name, equipment):
        canonical = self.canonical_part(name)
        if canonical == "포머" and equipment in {"포밍부", "포밍부(포머)"}:
            return "세부 부품 미기재"
        if canonical not in self.names and _key(_bare(name)) in self.module_names:
            return "세부 부품 미기재"
        if _key(_bare(name)) == _key(equipment):
            return "세부 부품 미기재"
        return canonical

    def major_for(self, part, symptom, context, original, equipment=""):
        for mapping in self.value.get("contextual_domains", []):
            if (
                part == mapping["part"]
                and equipment == mapping["equipment"]
                and symptom in mapping["symptoms"]
                and (
                    not mapping.get("context")
                    or re.search(mapping["context"], re.sub(r"\s+", "", context), re.I)
                )
            ):
                return mapping["domain"]
        family = self.group(part)
        if symptom == "소손·단락":
            electrical_families = {
                "모터",
                "구동제어기",
                "배선·접속부",
                "센서·계측",
                "스위치·조작·표시",
                "전원·보호장치",
                "제어·통신부품",
                "히터·온도제어",
            }
            if family in electrical_families or re.search(
                r"단락|쇼트|short|합선|누전", context, re.I
            ):
                return "전기·제어"
            if part == "세부 부품 미기재":
                return UNKNOWN_DOMAIN
            # A worn or burned belt is not evidence of an electrical short.
            return original if original in self.domains else UNKNOWN_DOMAIN
        if symptom in {
            "단선",
            "보호장치 동작",
            "과부하·과전류",
            "통신·입출력 이상",
            "에러코드 발생",
        }:
            return "전기·제어"
        if part == "밸브 제어헤드":
            return "전기·제어"
        if family == "모터":
            return (
                "기계" if symptom in {"마모", "변형", "이탈·풀림", "소음·진동"} else UNKNOWN_DOMAIN
            )
        if family == "씰·패킹·링" and symptom in {"손상·파손", "마모", "변형", "이탈·풀림"}:
            return "기계"
        if symptom == "온도이상":
            return "온도·냉각"
        generic_valve = part == "밸브(종류 미상)" or (
            part == "세부 부품 미기재" and equipment == "밸브"
        )
        if generic_valve and symptom in {"손상·파손", "마모", "변형", "부식", "이탈·풀림"}:
            return "기계"
        if symptom == "누설" or generic_valve:
            if re.search(r"냉매|icm|석션.*밸브|썩션.*밸브", context, re.I):
                return "온도·냉각"
            if re.search(r"에어|공압|진공", context):
                return "공압·진공"
            if re.search(r"냉각수|공정수|용수|스팀|증기|온수|냉수|원유|오일|유체", context) or (
                symptom == "누설" and not generic_valve and original != UNKNOWN_DOMAIN
            ):
                return "유체·배관"
            return UNKNOWN_DOMAIN
        if part == "세부 부품 미기재" and symptom == "고장·이상":
            return UNKNOWN_DOMAIN
        return original if original in self.domains else UNKNOWN_DOMAIN


@lru_cache(maxsize=1)
def default_taxonomy():
    return PublicTaxonomy()


def canonical_part_name(name):
    return default_taxonomy().canonical_part(name)


def part_group(name):
    return default_taxonomy().group(name)


def part_names():
    return tuple(sorted({*default_taxonomy().names, "세부 부품 미기재"}))


def group_names():
    return tuple(sorted({*default_taxonomy().groups.values(), "미기재"}))


def parse_repair_actions(value, *, strict=False):
    if value is None or value == "":
        return []
    if isinstance(value, str):
        if value.startswith("["):
            try:
                value = json.loads(value)
            except ValueError:
                value = re.split(r"[,;|\n]", value)
        else:
            value = re.split(r"[,;|\n]", value)
    if not isinstance(value, (list, tuple)):
        if strict:
            raise ValueError("조치는 표준 목록에서 선택하세요.")
        return []
    result = []
    for item in value:
        name = ACTION_ALIASES.get(str(item).strip(), str(item).strip())
        if not name:
            continue
        if name not in REPAIR_ACTIONS:
            if strict:
                raise ValueError("조치는 표준 목록에서 선택하세요: " + ", ".join(REPAIR_ACTIONS))
            continue
        if name not in result:
            result.append(name)
    return result
