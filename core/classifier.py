"""Deterministic classification of named parts and their reported symptoms."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from core.fault_components import combination_category, component_payload
from core.i18n import K
from core.rules import (
    LEGACY_GUARD as LEGACY_GUARD,
)
from core.rules import (
    LEGACY_SHEET as LEGACY_SHEET,
)
from core.rules import (
    META_SHEET as META_SHEET,
)
from core.rules import (
    MIN_APP_VERSION as MIN_APP_VERSION,
)
from core.rules import (
    REQUIRED_COLUMNS as REQUIRED_COLUMNS,
)
from core.rules import (
    ROLES as ROLES,
)
from core.rules import (
    RULE_COLUMNS as RULE_COLUMNS,
)
from core.rules import (
    RULES_SCHEMA as RULES_SCHEMA,
)
from core.rules import (
    RULES_SHEET as RULES_SHEET,
)
from core.rules import (
    file_schema as file_schema,
)
from core.rules import (
    needs_format_upgrade as needs_format_upgrade,
)
from core.rules import (
    read_rules as read_rules,
)
from core.rules import (
    upgrade_rules_format as upgrade_rules_format,
)
from core.rules import (
    validate_rules as validate_rules,
)
from core.rules import (
    write_rules as write_rules,
)

DEFAULT_ENGINE = {
    # Max characters (spaces removed) between a part and its symptom in one clause.
    "window": 15,
    # Symptom words that report a part replacement or repair: the strongest evidence of the failed part.
    "replace_pattern": "교체|교환|신규|새것|a급|b급|수리(?!크)|정비|재정비|가공|재가공",
    # Other repair words (adjust, inspect, clean) and adjusted attributes (위치, 타이밍).
    # A part that was only adjusted is weaker evidence than a stated failure.
    "action_pattern": "조정|재조정|조절|점검|청소|보수|용접|체결|고정|재조임|세팅|리셋|reset|재부팅|셧다운|온오프|재투입|"
    "보강|수정|교정|calibration|영점|분해|조립|급유|도포|확인|제거|재가동|가동|조치|작업|"
    "위치|각도|타이밍|원점|센터|높이|간격|텐션|감도|길이|전원종료|전원차단|윤활(?!유)",
    # Worker-selected MES part code (비가동 코드(소)) -> compatible standard majors.
    "part_code_majors": {},
    # Optional legacy first-stated-failure preference; off by default.
    "first_failure": False,
}
STRENGTH_REASON = {
    3: "교체 부품 우선",
    2: "교체 부품 우선",
    1: "고장 증상 우선",
    0: "고장 증상 우선",
}

# Clause boundaries. Decimal points (1.3.5번) and hyphens inside codes (A-5, x-ray) are not boundaries.
CLAUSE_SPLIT = re.compile(
    r"[\n\r/;|*()\[\]→]|->|=>|>>|(?<!\d)\.|\.(?!\d)|\s-\s|(?<=[가-힣])-(?=[가-힣\s])"
    r"|(?<=교체),(?=[^/;|]{0,24}(?:의심|추정|추측|가능성))"
)
NEGATION = re.compile(
    r"(?:은|는|이|가|도|을|를)?(?:전혀)?(?:없|무(?![가-힣])|아님|아니(?!면)|하지않|하지안|"
    r"안(?:함|했|하|됨|되)|(?:되)?지않|(?:되)?지안|않|불필요|취소|보류|미실시|한것이아니)"
)
NEGATED_PART = re.compile(r"(?:정상(?:작동)?|이상없|문제없|고장없|없음|무고장|ok)", re.I)
NORMAL_AFTER_INSPECTION = re.compile(
    r"^(?:(?:결과|후|은|는|이|가|로|한|시))*?(?:정상|이상(?:은|이)?없|문제(?:는|가)?없|고장없|ok)",
    re.I,
)
# Keep independent markers in their new clause so continuation cannot attach them
# to the previous failed part after punctuation or a source-field separator.
INDEPENDENT_MARKER = re.compile(
    r"별도(?:로)?|별개(?:로)?|추가로|한편|(?<![A-Za-z])separately(?![A-Za-z])", re.I
)
INDEPENDENT_SPLIT = re.compile(r"(?=" + INDEPENDENT_MARKER.pattern + r")", re.I)
# Parts listed together ('가이드 및 후크 조정') share the symptom; neither modifies the other.
LIST_JOIN = re.compile(r"(?:\d*번?)?(?:및|,|·|&|와|과|하고|또는|혹은|아니면)(?:\d*번?)?")
# '…이탈로 인해 몰드 빠짐', '리크 발생하며 과동결': the stated failure caused what follows.
CAUSAL = re.compile(
    r"(?:발생)?(?:지|져|되|돼|해|하)?(?:(?:으로|로)(?:인해|인한|인하여)?|에의한|에의해|때문|어서|어져|져|어|서|여|면서|며)"
)
# '스프라켓에서 이탈': a part followed by '에서' names a location, not the failed part.
LOCATIVE = re.compile(r"에서|쪽|(?:와|과)(?:직접)?연결(?:되는|된|되|하는)")
PLANNED_BEFORE = re.compile(r"추후|향후|예정|계획")
PLANNED_AFTER = re.compile(r"^(?:이|가|는)?(?:필요|예정|계획|요망)")
COMPLETED_AFTER = re.compile(r"^(?:완료|실시|하였|했|함)")
EXPLICIT_CAUSE = re.compile(r"(?:고장)?원인(?:으로|은|이|:)|원인확인결과")
ALTERNATIVE = re.compile(r"또는|혹은|아니면")
PRODUCT_MENTION = re.compile(r"제품|믹스|원료|내용물|생산품")
PRODUCT_RESULT = re.compile(r"찌그러|구겨|찢어|변형|파손|동결|결빙|온도(?:상승|하강)")
STOPPAGE = re.compile(r"정지|중지|다운|멈춤|작동불|작동이상")
SINGLE_COMPONENT_REASON = "부품별 근거 묶음 결과 단일 유형"
LISTED_COMPONENTS_REASON = "나열 부품의 공통 고장·교체 근거로 복수 유형 조합"
# Suspected or guessed parts are not recorded facts and keep a combination under review.
UNCERTAIN = re.compile(r"의심|추정|추측|예상|가능성|것같|듯")
PREVENTIVE_FAILURE = re.compile(r"^(?:이|가|을|를)?(?:예방|방지|대비|우려|예상|가능성|예정)")
# A following subject-less clause may continue a part, but an unrecognized
# subject ('브라인교체') must never be attributed to that previous part.
CONTINUATION_PREFIX = re.compile(
    r"(?:(?:후|이후|그후|즉시|이에|따라서|이로인해|으로|로|인해|인하여|및|하고|하여|해서|신품|새것|신규|재차|우선|다시|:|,)|(?:then|after|and|new))*",
    re.I,
)
NAME_LIST = re.compile(r"[가-힣]{2,4}(?:,[가-힣]{2,4})+")
CODE_PART_REASON = "고장내용에 부품명이 없어 비가동코드(소) '{code}'의 부품명으로 판정했습니다."
NOPART_REASON = "부품 후보가 없어 부품 미기재 규칙으로 판정했습니다."
# Unambiguous list joins; '와/과' also mean 'connected with' and are excluded.
STRICT_LIST = re.compile(r"(?:\d*번?)?(?:및|,|·|&)(?:\d*번?)?")
ALTERNATIVE_REASON = "원문이 여러 고장 유형을 명시적으로 대안으로 제시하여 어느 유형인지 확인이 필요합니다. 대안 그룹에서는 대표 규칙 하나만 잠정 표시합니다."


def clauses(text: str) -> list[str]:
    """Split a record into clauses and drop spaces, so '센서 교체' == '센서교체'."""
    # Preserve the standalone English connector before whitespace is removed.
    source = re.sub(r"\bor\b", "또는", text or "", flags=re.I)
    # A compact parenthesized model qualifies its preceding noun. It is not
    # a new subject: '씽크탑(V50) 고장' must retain the control head's fault.
    # Dimensions, descriptions and part lists keep their clause boundaries.
    source = re.sub(
        r"(?<=[가-힣A-Za-z0-9])\(((?=[A-Za-z0-9-]*\d)[A-Za-z][A-Za-z0-9-]{0,15})\)",
        r"\1",
        source,
    )
    return [
        part
        for clause in CLAUSE_SPLIT.split(source)
        for chunk in INDEPENDENT_SPLIT.split(clause)
        if (part := re.sub(r"\s+", "", chunk))
    ]


@dataclass(frozen=True)
class Symptom:
    clause: int
    start: int
    end: int
    text: str
    kind: str  # R = replaced/repaired, A = adjusted/inspected, F = failure


@dataclass(frozen=True)
class Pair:
    """One named part (context) and the symptoms stated for it inside a clause."""

    rule: dict
    clause: int
    c0: int
    c1: int
    context: str
    symptoms: tuple

    @property
    def category(self):
        return (self.rule["major"], self.rule["middle"], self.rule["minor"])

    @property
    def first(self):
        return self.symptoms[0] if self.symptoms else None

    def kinds(self):
        return {s.kind for s in self.symptoms}


def repair_word_boundary(pattern: str) -> str:
    """Keep legacy regex alternatives from consuming '수리' inside '냉각수리크'."""
    return re.sub(r"수리(?!\(\?!)", "수리(?!크)", pattern)


class RuleClassifier:
    """Deterministic, auditable part/symptom classification; no root-cause guessing.

    Symptoms must follow their part before the next independent named part.
    A rule requiring a symptom must include that symptom. Matching types are resolved by recorded
    repair, failure, cause and MES evidence; unresolved alternatives remain under review.
    """

    def __init__(self, rules: list[dict[str, Any]], engine: dict[str, Any] | None = None):
        self.engine = {**DEFAULT_ENGINE, **(engine or {})}
        self.engine.pop("scoring", None)  # Ignore thresholds saved by earlier releases.
        self.window = int(self.engine["window"])
        replace_pattern = repair_word_boundary(self.engine["replace_pattern"])
        self.replace = re.compile(f"(?:{replace_pattern})+", re.I)
        self.action = re.compile(f"(?:{replace_pattern}|{self.engine['action_pattern']})+", re.I)
        self.part_majors = {
            re.sub(r"\s+", "", str(k)): set(v)
            for k, v in (self.engine.get("part_code_majors") or {}).items()
        }
        self.rules = []
        # Consulted only when no other rule finds a candidate in the record.
        self.nopart_rules = []
        for row in sorted(validate_rules(rules), key=lambda r: (-r["priority"], r["id"])):
            if row["enabled"]:
                symptom = (
                    None
                    if row["symptom"] == "."
                    else re.compile(repair_word_boundary(row["symptom"]), re.I)
                )
                (self.nopart_rules if row["role"] == "nopart" else self.rules).append(
                    (
                        row,
                        re.compile(row["context"], re.I),
                        symptom,
                        re.compile(row["exclude"], re.I) if row["exclude"] else None,
                    )
                )

    def kind(self, word: str) -> str:
        if self.replace.fullmatch(word):
            return "R"
        return "A" if self.action.fullmatch(word) else "F"

    def symptoms(
        self, symptom, text: str, index: int, start: int, limit: int, nouns
    ) -> list[Symptom]:
        words = []
        for s in symptom.finditer(text, start, limit):
            # '이상 없음' is not a failure; '고정' inside the noun '고정볼트' is not a symptom.
            if not s.group() or NEGATION.match(text, s.end()):
                continue
            # '냉각수리크' contains the syllables '수리', but reports a leak.
            # Keep this lexical boundary even for older customized regexes.
            if s.group() == "수리" and text[s.end() :].startswith("크"):
                continue
            if any(a <= s.start() and s.end() <= b for a, b in nouns):
                continue
            kind = self.kind(s.group())
            if kind == "F" and s.group() == "이상" and re.match(r"유무|여부", text[s.end() :]):
                continue
            if kind in {"R", "A"}:
                from core.failure_modes import incomplete_action_context

                if incomplete_action_context(
                    text[max(0, s.start() - 10) : s.start()], text[s.end() : limit]
                ):
                    continue
            if kind == "F" and PREVENTIVE_FAILURE.match(text[s.end() : limit]):
                continue
            if (
                kind == "A"
                and re.fullmatch(r"점검|확인|inspected", s.group(), re.I)
                and NORMAL_AFTER_INSPECTION.match(text[s.end() : limit])
            ):
                continue
            if (
                kind in {"R", "A"}
                and not COMPLETED_AFTER.match(text[s.end() :])
                and (
                    PLANNED_BEFORE.search(text[max(0, s.start() - 12) : s.start()])
                    or PLANNED_AFTER.match(text[s.end() : s.end() + 8])
                )
            ):
                continue  # Future/required work is not evidence of an actual repair.
            words.append(Symptom(index, s.start(), s.end(), s.group(), kind))
        return words

    def pairs(self, parts: list[str], rules=None) -> list[Pair]:
        rules = self.rules if rules is None else rules
        found = {}

        def add(rule, index, c, words):
            key = (rule["id"], index, c.start())
            old = found.get(key)
            found[key] = Pair(
                rule,
                index,
                c.start(),
                c.end(),
                c.group(),
                (old.symptoms if old else ()) + tuple(words),
            )

        previous = None
        for index, text in enumerate(parts):
            # Whitespace removal joins an English marker to the following word.
            if INDEPENDENT_MARKER.match(text) or text.casefold().startswith("separately"):
                previous = None
            active = [
                (rule, context, symptom)
                for rule, context, symptom, exclude in rules
                if not (exclude and exclude.search(text))
            ]
            hits = {
                rule["id"]: [
                    m
                    for m in context.finditer(text)
                    if m.group() and self.supported_context(rule, m, text)
                ]
                for rule, context, _ in active
            }
            # Part names only; fallback contexts are symptom words themselves (파손, 틀어짐).
            nouns = sorted(
                (m.start(), m.end())
                for rule, _, _ in active
                if rule["role"] != "fallback"
                for m in hits[rule["id"]]
            )
            if not nouns and self.metadata_name_list(text, active):
                previous = None
                continue
            # A location ('스프라켓에서') does not end the previous part's statement.
            bounds = [(a, b) for a, b in nouns if not LOCATIVE.match(text, b)]
            last = []
            for rule, _, symptom in active:
                for c in hits[rule["id"]]:
                    if NEGATION.match(text, c.end()) or NEGATED_PART.match(text, c.end()):
                        continue
                    if symptom is None:
                        add(rule, index, c, ())
                        continue
                    if LOCATIVE.match(text, c.end()):
                        continue
                    # A part's symptoms end where the next part begins, unless the two are listed together.
                    limit = min(c.end() + self.window, len(text))
                    passed = c.end()
                    for a, b in bounds:
                        if a < passed:
                            continue  # Names nested in a listed part ('밸브' in '솔밸브').
                        if not LIST_JOIN.fullmatch(text[c.end() : a]):
                            limit = min(limit, a)
                            break
                        passed = max(passed, b)
                    words = self.symptoms(symptom, text, index, c.end(), limit, nouns)
                    negated = any(
                        NEGATION.match(text, hit.end())
                        for hit in symptom.finditer(text, c.end(), limit)
                    )
                    if not words and negated:
                        continue  # A negated symptom must never return as a weak part-only candidate.
                    if rule["role"] != "fallback":
                        if not last or c.start() > last[0][2].start():
                            last = [(rule, symptom, c)]
                        elif c.start() == last[0][2].start():
                            last.append((rule, symptom, c))
                    if words or rule["role"] != "fallback":
                        add(rule, index, c, words)
            if nouns and previous:
                # A parenthesized alias may end just before its failure, then
                # another part starts later: '(ICM 밸브) 누설 확인, 자동밸브…'.
                # Only the prefix before the next named part can continue it.
                origin, previous_parts = previous
                prefix_end = min(a for a, _ in nouns)
                if origin == index - 1 and 0 < prefix_end <= self.window:
                    for rule, symptom, c in previous_parts:
                        if symptom is not None:
                            words = self.symptoms(symptom, text, index, 0, prefix_end, ())
                            if words and self.subjectless_continuation(text, words):
                                add(rule, origin, c, words)
            if nouns:
                previous = (index, last) if last else None
            elif previous:
                # Only genuinely subject-less adjacent clauses continue a part.
                origin, previous_parts = previous
                continued = False
                for rule, symptom, c in previous_parts:
                    words = self.symptoms(symptom, text, index, 0, len(text), ())
                    if words and self.subjectless_continuation(text, words):
                        add(rule, origin, c, words)
                        continued = True
                if not continued:
                    previous = None
        return list(found.values())

    @staticmethod
    def subjectless_continuation(text: str, words: list[Symptom]) -> bool:
        return bool(CONTINUATION_PREFIX.fullmatch(text[: words[0].start]))

    def metadata_name_list(self, text: str, active) -> bool:
        """A short comma-separated name list is metadata, unless it names work."""
        if not NAME_LIST.fullmatch(text):
            return False
        if any(
            self.action.fullmatch(token)
            or any(symptom and symptom.fullmatch(token) for _, _, symptom in active)
            for token in text.split(",")
        ):
            return False
        from core.public_taxonomy import default_catalog

        return not any(
            re.sub(r"\s+", "", alias).casefold() in text.casefold()
            for equipment in default_catalog().get("equipment_types", [])
            for alias in [equipment["name"], *equipment.get("aliases", [])]
            if len(re.sub(r"\s+", "", alias)) >= 2
        )

    @staticmethod
    def supported_context(rule: dict, match, text: str) -> bool:
        """Ambiguous short aliases require their recorded equipment context."""
        if match.group().casefold() == "tc" and rule["minor"].startswith("열전대"):
            # TC can also mean a controller. Only the heating/sealing context
            # observed in the history supports its thermocouple abbreviation.
            return bool(re.search(r"히터|히팅|씰러|실러|포밍|온도|열전", text[: match.start()]))
        return True

    def causal(self, pair: Pair, parts: list[str]) -> bool:
        """'…이탈로 인해 몰드 빠짐' links two failures; '고장으로 교체' is a self-contained repair."""
        for s in pair.symptoms:
            if s.kind != "F":
                continue
            text = parts[s.clause]
            marker = CAUSAL.match(text, s.end)
            if marker and marker.end() < len(text) and not self.action.match(text, marker.end()):
                return True
        return False

    def eligible_pairs(self, pairs: list[Pair], parts: list[str]) -> list[Pair]:
        """Remove generic and compound-noun duplicates before comparing evidence."""
        named = [pair for pair in pairs if pair.rule["role"] != "fallback"]

        def spans(pair):
            return [
                (pair.clause, pair.c0, pair.c1),
                *((symptom.clause, symptom.start, symptom.end) for symptom in pair.symptoms),
            ]

        named_spans = [
            span
            for pair in named
            if pair.symptoms or pair.rule["role"] == "override"
            for span in spans(pair)
        ]

        def duplicate_fallback(pair):
            # Includes symptoms genuinely continued in another clause ('파손/교체').
            # Independent clauses retain their own otherwise-unlocated symptoms.
            if any(
                clause == other_clause and start < other_end and other_start < end
                for clause, start, end in spans(pair)
                for other_clause, other_start, other_end in named_spans
            ):
                return True
            # A generic failure between a named part and its recognized symptom
            # describes that part, provided another named part does not intervene.
            for other in named:
                ends = [symptom.end for symptom in other.symptoms if symptom.clause == pair.clause]
                if other.clause != pair.clause or not ends:
                    continue
                if (
                    other.c1 <= pair.c0
                    and pair.c1 <= max(ends)
                    and not any(
                        boundary.clause == pair.clause and other.c1 <= boundary.c0 < pair.c0
                        for boundary in named
                        if boundary is not other
                    )
                ):
                    return True
            return False

        live = [
            pair
            for pair in pairs
            if pair.rule["role"] != "fallback" or not duplicate_fallback(pair)
        ]
        # A name nested in a longer one ('밸브' in '솔밸브') is not a separate
        # neighbor; the longer name stands for it in every comparison below.
        nested = {
            id(pair)
            for pair in named
            for other in named
            if other is not pair
            and other.clause == pair.clause
            and other.c0 <= pair.c0
            and pair.c1 <= other.c1
            and (other.c0, other.c1) != (pair.c0, pair.c1)
        }
        losers = set()
        for pair in live:
            for other in named:
                if pair is other or pair.category == other.category or pair.clause != other.clause:
                    continue
                if id(other) in nested:
                    continue
                # A compound part's full name wins over its nested generic word.
                contains = (
                    other.c0 <= pair.c0
                    and other.c1 >= pair.c1
                    and (other.c0, other.c1) != (pair.c0, pair.c1)
                )
                # Overlapping names describe one part. Within one part family
                # ('몰드체인연결핀', '플랙시블컨베어') the more specific rule wins;
                # across families ('플렉시블컨베어날개') the later, head-final name wins.
                partial = (
                    pair.c0 < other.c0 < pair.c1 < other.c1
                    or other.c0 < pair.c0 < other.c1 < pair.c1
                )
                outranked = (
                    (other.rule["priority"], other.c1) > (pair.rule["priority"], pair.c1)
                    if other.rule["middle"] == pair.rule["middle"]
                    else other.c1 > pair.c1
                )
                if (contains or (partial and outranked)) and (other.symptoms or not pair.symptoms):
                    losers.add(id(pair))
                    break
                # '실린더 센서 교체': the preceding noun is not a second failed part.
                if (
                    pair.rule["role"] == "component"
                    and not pair.symptoms
                    and other.rule["role"] == "component"
                    and other.symptoms
                    and pair.c1 == other.c0
                ):
                    losers.add(id(pair))
                    break
                if not pair.first or not other.first:
                    continue
                same_symptom = (pair.first.clause, pair.first.start) == (
                    other.first.clause,
                    other.first.start,
                )
                if same_symptom and pair.c1 <= other.c0:
                    bridge = parts[pair.clause][pair.c1 : other.c0]
                    if not LIST_JOIN.fullmatch(bridge):
                        losers.add(id(pair))
                        break
        return [pair for pair in live if id(pair) not in losers]

    def evidence_kinds(self, candidate: Pair) -> set[str]:
        """A literal fallback denotes its own symptom even without a separate match."""
        kinds = candidate.kinds()
        if (
            not kinds
            and candidate.rule["role"] in ("fallback", "nopart")
            and candidate.rule["symptom"] == "."
        ):
            kinds = {self.kind(candidate.context)}
        return kinds

    def explicit_cause_pairs(self, pairs: list[Pair], parts: list[str]):
        """Find the first evidenced part after an explicit 'the cause is...' marker."""
        result = []
        for clause, text in enumerate(parts):
            for marker in EXPLICIT_CAUSE.finditer(text):
                following = [
                    pair
                    for pair in pairs
                    if pair.clause == clause
                    and pair.c0 >= marker.end()
                    and (self.evidence_kinds(pair) & {"F", "R"} or pair.rule["role"] == "override")
                ]
                if not following:
                    continue
                first = min(pair.c0 for pair in following)
                result.extend((pair, marker.start()) for pair in following if pair.c0 == first)
        return result

    def causal_part_keys(self, pairs: list[Pair], parts: list[str]):
        roots = [pair for pair in pairs if self.causal(pair, parts)]
        roots.extend(pair for pair, _ in self.explicit_cause_pairs(pairs, parts))
        return {(pair.clause, pair.c0, pair.c1) for pair in roots}

    def independent_pairs(self, pairs: list[Pair], parts: list[str]) -> list[Pair]:
        """Keep independent faults, excluding stated and clearly scoped outcomes."""
        causes = [
            pair for pair in pairs if self.causal(pair, parts) or pair.rule["role"] == "override"
        ]
        explicit = self.explicit_cause_pairs(pairs, parts)

        def product_outcome(pair):
            if pair.rule["role"] != "fallback":
                return False
            text = parts[pair.clause]
            end = max([pair.c1, *(s.end for s in pair.symptoms if s.clause == pair.clause)])
            for product in PRODUCT_MENTION.finditer(text, 0, pair.c0):
                if PRODUCT_RESULT.search(text[product.end() : end]) and any(
                    named.clause == pair.clause
                    and named.c1 <= product.start()
                    and named.rule["role"] == "component"
                    and "F" in self.evidence_kinds(named)
                    for named in pairs
                ):
                    return True
            return False

        def consequence(pair):
            if product_outcome(pair):
                return True
            # '베어링 및 축 마모로 인한': listed parts share one cause, not cause and outcome.
            if any(
                root.category != pair.category
                and root.clause == pair.clause
                and root.c1 < pair.c0
                and not self.shared_symptom(root, pair)
                for root in causes
            ):
                return True
            # A later explicit cause explains an earlier stop, but does not erase
            # a physically damaged part merely because that part came first.
            return any(
                root.category != pair.category
                and root.clause == pair.clause
                and pair.c1 <= marker
                and any(STOPPAGE.search(symptom.text) for symptom in pair.symptoms)
                for root, marker in explicit
            )

        return [pair for pair in pairs if not consequence(pair)]

    def alternative_relation(self, first: Pair, second: Pair, parts: list[str]) -> bool:
        """An explicit choice between different mentions is an alternative group."""
        if (first.clause, first.c0, first.c1) == (second.clause, second.c0, second.c1):
            return False
        left, right = sorted((first, second), key=lambda pair: (pair.clause, pair.c0))
        if left.clause == right.clause and left.c1 <= right.c0:
            text = parts[left.clause]
            bridge = text[left.c1 : right.c0]
            # Link neighboring mentions, not every later part across an entire
            # phrase such as 'motor or sensor, and independently a valve'.
            if any(
                rule["role"] != "fallback"
                and any(match.group() for match in context.finditer(text, left.c1, right.c0))
                for rule, context, _, _ in self.rules
            ):
                return False
            if ALTERNATIVE.search(bridge):
                return True
            return "인지" in bridge and "인지" in text[right.c1 :]
        if right.clause == left.clause + 1:
            return bool(ALTERNATIVE.match(parts[right.clause][: right.c0]))
        return False

    def alternative_types(self, pairs: list[Pair], parts: list[str]) -> bool:
        return any(
            self.alternative_relation(pair, other, parts)
            for index, pair in enumerate(pairs)
            for other in pairs[index + 1 :]
        )

    @staticmethod
    def stated_symptoms(pair: Pair) -> set[tuple[int, int]]:
        return {(s.clause, s.start) for s in pair.symptoms if s.kind in {"F", "R"}}

    def shared_symptom(self, first: Pair, second: Pair) -> bool:
        """Listed parts ('베어링 및 축 마모') carry one stated failure or repair."""
        return bool(self.stated_symptoms(first) & self.stated_symptoms(second))

    @staticmethod
    def shared_fallback_evidence(first: Pair, second: Pair) -> bool:
        if first.rule["role"] != "fallback" or second.rule["role"] != "fallback":
            return False

        def symptoms(pair):
            spans = [
                (symptom.clause, symptom.start, symptom.end)
                for symptom in pair.symptoms
                if symptom.kind in {"F", "R"}
            ]
            if pair.rule["symptom"] == ".":
                spans.append((pair.clause, pair.c0, pair.c1))
            return spans

        return any(
            clause == other_clause and start < other_end and other_start < end
            for clause, start, end in symptoms(first)
            for other_clause, other_start, other_end in symptoms(second)
        )

    def multiple_faults(self, pairs: list[Pair], parts: list[str]) -> bool:
        """Independent faults or explicitly listed parts cannot be auto-confirmed."""
        live = self.independent_pairs(pairs, parts)
        for index, pair in enumerate(live):
            for other in live[index + 1 :]:
                if pair.category == other.category:
                    continue
                if pair.clause == other.clause and pair.c0 < other.c1 and other.c0 < pair.c1:
                    continue  # Different descriptions of the same physical part are alternatives, not two faults.
                kinds, other_kinds = self.evidence_kinds(pair), self.evidence_kinds(other)
                if "F" in kinds and "F" in other_kinds:
                    return True
                if pair.clause != other.clause:
                    if kinds & {"F", "R"} and other_kinds & {"F", "R"}:
                        return True
                    continue
                left, right = sorted((pair, other), key=lambda item: item.c0)
                bridge = parts[pair.clause][left.c1 : right.c0]
                listed = LIST_JOIN.fullmatch(bridge) or re.search(r"및|그리고|또한|동시|&", bridge)
                if left.c1 <= right.c0 and listed and kinds and other_kinds:
                    return True
        return False

    @staticmethod
    def pair_order(pair: Pair):
        return (-pair.rule["priority"], pair.clause, pair.c0, pair.rule["id"])

    def component_pairs(self, live: list[Pair], parts: list[str], part_code: str = ""):
        """Preserve independent observed faults, resolving each part by matching rules.

        Returns one (pair, note) per distinct resolved type, plus unresolved-conflict notes.
        """
        strong = [
            pair
            for pair in self.independent_pairs(live, parts)
            if self.evidence_kinds(pair) & {"F", "R"}
        ]

        def physical_identity(pair):
            qualifier = re.search(
                r"(?:#?\d+(?:번|호)?|좌측|우측|좌|우|상부|하부|전단|후단)$",
                parts[pair.clause][: pair.c0],
            )
            return pair.context.casefold(), qualifier.group() if qualifier else ""

        def same_part(first, second):
            if self.alternative_relation(first, second, parts) or self.shared_fallback_evidence(
                first, second
            ):
                return True
            if first.clause == second.clause and first.c0 < second.c1 and second.c0 < first.c1:
                return True
            if physical_identity(first) != physical_identity(second):
                return False
            lo, hi = sorted((first.clause, second.clause))
            return not any(
                INDEPENDENT_MARKER.match(part) or part.casefold().startswith("separately")
                for part in parts[lo + 1 : hi + 1]
            )

        groups = []
        for pair in sorted(strong, key=lambda p: (p.clause, p.c0, p.c1, p.rule["id"])):
            overlapping = [
                group for group in groups if any(same_part(other, pair) for other in group)
            ]
            merged = [pair, *(item for group in overlapping for item in group)]
            groups = [group for group in groups if all(group is not old for old in overlapping)]
            groups.append(merged)
        by_type, notes = {}, []
        for group in groups:
            chosen, reason = self.resolve(group, parts, part_code)
            note = ""
            if chosen is None:
                chosen = min(group, key=self.pair_order)
                note = "동일 부품의 분류 규칙 충돌: 사용자 확인 필요"
                notes.append(" / ".join(chosen.category) + ": " + note)
            by_type.setdefault(chosen.category, (chosen, note or reason))
        return list(by_type.values()), notes

    def listed_components(self, live: list[Pair], members: list[Pair], parts: list[str]) -> bool:
        """'A 및 B 마모', 'A, B 교체': one statement names every part as failed or replaced.

        The combination is then the recorded fact. Ambiguous joins ('A와 연결되는 B'),
        suspicion, or a replaced part set aside as an outcome keep it under review.
        """
        if UNCERTAIN.search("".join(parts)):
            return False
        if not set.intersection(*(self.stated_symptoms(pair) for pair in members)):
            return False
        ordered = sorted(members, key=lambda pair: (pair.clause, pair.c0))
        if any(
            left.clause != right.clause
            or not STRICT_LIST.fullmatch(parts[left.clause][left.c1 : right.c0])
            for left, right in zip(ordered, ordered[1:])
        ):
            return False
        independent = {id(pair) for pair in self.independent_pairs(live, parts)}
        types = {pair.category for pair in members}
        return not any(
            id(pair) not in independent
            and "R" in self.evidence_kinds(pair)
            and pair.category not in types
            for pair in live
        )

    @staticmethod
    def component_value(pair: Pair, note: str = "") -> dict[str, Any]:
        words = ", ".join(dict.fromkeys([pair.context, *(s.text for s in pair.symptoms)]))
        return {
            **{key: pair.rule[key] for key in ("major", "middle", "minor")},
            "rule_id": pair.rule["id"],
            "evidence": words + (" | " + note if note else ""),
        }

    def resolve(self, pairs: list[Pair], parts: list[str], part_code: str):
        """Return (pair, reason) or (None, '') when the evidence is not decisive."""

        def decided(live):
            return len({p.category for p in live}) == 1

        def best(live):
            return min(live, key=lambda p: (-p.rule["priority"], p.clause, p.c0, p.rule["id"]))

        override = [p for p in pairs if p.rule["role"] == "override"]
        if override:
            return best(override), "원인 표현 규칙"
        live = list(pairs)
        if decided(live):
            return best(live), ""
        components = [p for p in live if p.rule["role"] == "component"]
        if components and len(components) < len(live):
            live = components
            if decided(live):
                return best(live), "부품 규칙 우선"
        if all(p.rule["role"] == "fallback" for p in live):
            return best(live), "부위 미기재 규칙 우선순위"
        # Two rules on the same part: the more specific (higher priority) rule refines it.
        same_part = defaultdict(list)
        for p in live:
            same_part[(p.clause, p.c0, p.c1)].append(p)
        live = [
            p
            for group in same_part.values()
            for p in group
            if p.rule["priority"] == max(item.rule["priority"] for item in group)
        ]
        if decided(live):
            return best(live), "세부 규칙"
        # Overlapping part names on one symptom ('진공펌프' vs '펌프'): the longest, closest name wins.
        same_symptom = defaultdict(list)
        for p in live:
            if p.first:
                same_symptom[(p.first.clause, p.first.start)].append(p)
        losers = set()
        for group in same_symptom.values():
            head = max(group, key=lambda p: (p.clause, p.c1, p.c1 - p.c0, p.rule["priority"]))
            for p in group:
                if (p.clause, p.c0, p.c1) == (head.clause, head.c0, head.c1):
                    continue  # Equal-priority types on the same part remain alternatives.
                listed = p.clause == head.clause and LIST_JOIN.fullmatch(
                    parts[p.clause][p.c1 : head.c0]
                )
                if p is not head and p.category != head.category and not listed:
                    losers.add(id(p))
        live = [p for p in live if id(p) not in losers]
        if decided(live):
            return best(live), "복합명사 중심어"
        # Evidence per category: replaced+failed > replaced > failed > only adjusted or inspected.
        kinds = defaultdict(set)
        for p in live:
            kinds[p.category] |= p.kinds()
        strength = {
            category: 3 if {"R", "F"} <= k else 2 if "R" in k else 1 if "F" in k else 0
            for category, k in kinds.items()
        }
        top = max(strength.values())
        tied = [p for p in live if strength[p.category] == top]
        if decided(tied):
            return best(tied), STRENGTH_REASON[top]
        causes = [p for p in tied if self.causal(p, parts)]
        if causes and decided(causes):
            return min(causes, key=lambda p: (p.clause, p.c0)), "원인 표현(으로/로 인해)"
        majors = self.part_majors.get(re.sub(r"\s+", "", part_code or ""))
        if majors:
            fit = [p for p in tied if p.rule["major"] in majors]
            if fit and decided(fit):
                return best(fit), "MES 소분류 일치"
        if self.engine.get("first_failure"):
            failures = [p for p in tied if "F" in p.kinds()] or tied
            return min(failures, key=lambda p: (p.clause, p.c0)), "첫 고장 기술"
        return None, ""

    def classify(
        self, text: str, part_code: str = "", code_text: str | None = None
    ) -> dict[str, Any]:
        """Classify by the description first; later stages run only when nothing matched.

        ``code_text`` is the normalized 비가동코드(소); it defaults to ``part_code``.
        """
        result = self.decide(text, part_code)
        if result["status"] != K["rule_unmatched"]:
            return result
        code = (part_code if code_text is None else code_text).strip()
        if code:
            # The worker-selected MES part code names the part the description omits.
            coded = self.decide(f"{code} {text}", part_code)
            if coded["status"] != K["rule_unmatched"]:
                return self.staged(coded, CODE_PART_REASON.format(code=part_code or code))
        if self.nopart_rules:
            unnamed = self.decide(text, part_code, self.nopart_rules)
            if unnamed["status"] != K["rule_unmatched"]:
                return self.staged(unnamed, NOPART_REASON)
        return result

    @staticmethod
    def staged(result: dict[str, Any], reason: str) -> dict[str, Any]:
        """Record which later stage produced the decision."""
        result["classification_reason"] = f"{reason} {result['classification_reason']}"
        result["evidence"] += f" | {reason}"
        return result

    def decide(self, text: str, part_code: str = "", rules=None) -> dict[str, Any]:
        parts = clauses(text)
        # A named part alone does not satisfy a rule requiring a symptom.
        matched = [
            pair
            for pair in self.pairs(parts, rules)
            if pair.symptoms or pair.rule["symptom"] == "."
        ]
        live = self.eligible_pairs(matched, parts)
        if not live:
            # Preprocessing relabels this as code_missing when the source codes are blank.
            return {
                "major": K["rule_unmatched"],
                "middle": K["rule_unmatched"],
                "minor": K["rule_unmatched"],
                "status": K["rule_unmatched"],
                "evidence": "",
                "candidates": "",
                "candidate_evidence": "",
                "classification_reason": "부품·증상 조건을 모두 충족하는 규칙이 없습니다.",
                "review_code": "",
                **component_payload([], mode="unclassified"),
            }
        ordered = sorted(live, key=self.pair_order)
        chosen, reason = self.resolve(live, parts, part_code)
        code = "" if chosen is not None else "multi_rule"
        if chosen is None:
            chosen = ordered[0]
            reason = (
                "서로 다른 분류 규칙이 일치하며 기록된 근거만으로 한 유형을 확정할 수 없습니다."
            )
        elif not reason:
            reason = "부품·증상 조건에 일치하는 유형이 하나입니다."
        selection_reason = reason
        multiple = self.multiple_faults(live, parts)
        alternative = self.alternative_types(live, parts)
        components, notes = (
            self.component_pairs(live, parts, part_code) if multiple or alternative else ([], [])
        )
        if multiple and not alternative and len(components) == 1 and not notes:
            # Grouped by physical part, only one type has failure or repair evidence:
            # the other mentions were the same part or merely adjusted/inspected.
            resolved = components[0][0]
            if chosen.category != resolved.category:
                chosen = resolved
            multiple, code, reason = False, "", SINGLE_COMPONENT_REASON
            selection_reason = reason
        listed = (
            multiple
            and not alternative
            and len(components) >= 2
            and not notes
            and self.listed_components(live, [pair for pair, _ in components], parts)
        )
        if listed:
            code, reason = "", LISTED_COMPONENTS_REASON
            selection_reason = reason
        elif multiple:
            code, reason = (
                "multiple_faults",
                "독립된 복수 부품·고장 또는 나열된 부품을 확인해야 합니다.",
            )
        if alternative:
            code, reason = "alternative_types", ALTERNATIVE_REASON
        classification = {key: chosen.rule[key] for key in ("major", "middle", "minor")}
        payload = component_payload(
            [self.component_value(chosen)], mode="ambiguous" if code else "single"
        )
        if multiple or alternative:
            members = [self.component_value(pair, note) for pair, note in components]
            combined = component_payload(members, mode="multiple")
            if combined["component_count"] >= 2:
                payload = combined
                classification = combination_category(members)
                if code:
                    reason += " 독립된 유형들을 조합으로 보존하며 사용자 확인 후 확정합니다."
                if notes:
                    reason += " 부품별 검토: " + " | ".join(dict.fromkeys(notes))
            else:
                reason += " 실제 복수 고장을 확정할 근거가 부족하여 대표 규칙을 잠정 표시합니다."
        words = ", ".join(dict.fromkeys([chosen.context, *(s.text for s in chosen.symptoms[:2])]))
        evidence = f"{chosen.rule['id']} | {words}"
        if not code and reason != "부품·증상 조건에 일치하는 유형이 하나입니다.":
            evidence += f" | {K['auto_resolved']}: {reason}"
        elif (
            code
            and selection_reason
            and selection_reason != "부품·증상 조건에 일치하는 유형이 하나입니다."
        ):
            evidence += " | 대표 규칙 선택: " + selection_reason
        return {
            **classification,
            **payload,
            "status": K["review"] if code else K["auto"],
            "evidence": evidence,
            "candidates": " | ".join(
                dict.fromkeys(f"{p.rule['id']}: {p.rule['minor']}" for p in ordered)
            ),
            "candidate_evidence": "\n".join(
                dict.fromkeys(
                    f"{' / '.join(p.category)} [{p.rule['id']}] | {self.component_value(p)['evidence']}"
                    for p in ordered
                )
            ),
            "classification_reason": reason,
            "review_code": code,
        }
