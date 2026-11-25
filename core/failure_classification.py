"""Keep ranked review recommendations separate from one final part/symptom."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from core.classification_candidates import rank_candidates
from core.classification_completeness import MISSING_VALUES, missing_fields_text
from core.classifier import (
    CAUSAL,
    INDEPENDENT_MARKER,
    NEGATED_PART,
    NEGATION,
    PLANNED_BEFORE,
    UNCERTAIN,
    RuleClassifier,
    clauses,
)
from core.equipment_taxonomy import EquipmentResolver
from core.failure_modes import (
    CLASSIFICATION_SCHEMA,
    COMPILED_SYMPTOMS,
    UNKNOWN_EQUIPMENT,
    UNKNOWN_PART,
    UNKNOWN_SYMPTOM,
    action_names,
    extract_actions,
    part_key,
    symptom_names,
)
from core.fault_components import CATEGORY_FIELDS, component_payload, parse_components, type_label
from core.i18n import K
from core.known_classification import KNOWN_FIELDS
from core.public_taxonomy import UNKNOWN_DOMAIN, PublicTaxonomy, default_catalog
from core.ranked_representative import choose_ranked_representative
from core.representative_fault import choose_direct_fault

MODULE_DESIGNATION = re.compile(r"(?:의)?(?:모듈|유닛|뱅크|클러스터|조립체|본체)")
FLUID_MEDIUM = re.compile(
    r"(?:냉매|에어|공압|진공|냉각수|공정수|용수|스팀|증기|온수|냉수|원유|오일|유체)"
    r"(?:용|공급|회수|이송|입구|출구|순환|측)?$"
)
OBSERVED_WITHOUT_PART = frozenset(
    (
        "누설",
        "소음·진동",
        "압력이상",
        "온도이상",
        "손상·파손",
        "터짐",
        "마모",
        "변형",
        "동작불량",
        "고장·이상",
        "과부하·과전류",
        "통신·입출력 이상",
        "위치·설정이상",
        "에러코드 발생",
    )
)


class FaultClassifier:
    """Classify one representative type while retaining all source candidates."""

    def __init__(self, rules, engine=None, equipment_types=None, public_taxonomy=None):
        self.parts = RuleClassifier(rules, engine)
        if equipment_types is None:
            equipment_types = default_catalog().get("equipment_types")
        self.equipment = EquipmentResolver(equipment_types)
        self.taxonomy = PublicTaxonomy(public_taxonomy, equipment_types)

    @staticmethod
    def _safe_context(pair, live, chunks):
        """Do not resurrect normal, negated or planned work as a weak candidate."""
        text = chunks[pair.clause]
        following = min(
            (other.c0 for other in live if other.clause == pair.clause and other.c0 >= pair.c1),
            default=len(text),
        )
        tail = text[pair.c1 : following]
        prefix = text[max(0, pair.c0 - 12) : pair.c0]
        return not (
            NEGATED_PART.search(tail)
            or NEGATION.search(tail)
            or PLANNED_BEFORE.search(prefix)
            or re.search(r"예정|계획|요망|미실시", tail)
        )

    @staticmethod
    def _qualified_failure(symptom, chunks):
        start, word = symptom.start, symptom.text
        if chunks is not None:
            prefix = chunks[symptom.clause][max(0, start - 12) : start]
            code = re.search(r"wago#?\d+(?:번)?$", prefix, re.I)
            if code and word == "발생":
                return symptom.clause, start - len(code.group()), symptom.end, code.group() + word
            if word in {"오류", "에러", "불량"} and prefix.endswith("통신"):
                return symptom.clause, start - len("통신"), symptom.end, "통신" + word
            qualifier = re.search(
                r"(?:품온|온도|진공도|압력|점도)(?:가|이|는)?(?:\d+(?:\.\d+)?(?:도|℃|bar|mpa|%)?)?$",
                prefix,
                re.I,
            )
            if qualifier:
                start -= len(qualifier.group())
                word = qualifier.group() + word
        return symptom.clause, start, symptom.end, word

    @staticmethod
    def _failure_is_attached(pair, symptom, chunks):
        if chunks is None:
            return True
        chunk = chunks[symptom.clause]
        if symptom.text == "불량" and re.match(
            r"(?:품)?(?:이송|배출|분리|선별|검출|처리)(?:용)?(?:컨베어|장치|설비|라인|벨트|기구)",
            chunk[symptom.end :],
        ):
            return False
        if symptom.text.startswith("풀리") and re.match(
            r"풀리(?:고정|축|키|볼트|베어링|교체|파손|마모)", chunk[symptom.start :]
        ):
            return False
        if pair.clause != symptom.clause:
            return True
        bridge = chunk[pair.c1 : symptom.start]
        if symptom.text.startswith(("이탈", "떨어", "낙하")) and re.search(
            r"(?:제품|스틱|카톤|팩|컵|박스)(?:이|가)?$", bridge
        ):
            return False
        prefix = chunk[max(0, pair.c0 - 18) : pair.c0]
        if "가이드" in pair.rule["minor"] and symptom.text.startswith(("이탈", "떨어", "낙하")):
            if re.search(r"(?:포켓|제품|스틱|카톤|팩|컵|박스)(?:다수|여러개|\d+개|이|가)$", prefix):
                return False
        if chunk[pair.c1 :].startswith("위치") and re.search(
            r"(?:제품|스틱|카톤|팩|컵|박스)(?:이|가).{0,10}$", prefix
        ):
            return False
        return True

    def _causal_symptom(self, pairs, chunks, names):
        if len(names) < 2 or chunks is None:
            return names
        observations = sorted(
            {
                self._qualified_failure(symptom, chunks)
                for pair in pairs
                for symptom in pair.symptoms
                if symptom.kind == "F" and self._failure_is_attached(pair, symptom, chunks)
            }
        )
        observations = [
            value for value in observations if set(symptom_names([value[3]], value[3])) & set(names)
        ]
        if len(observations) < 2:
            return names
        modes = [symptom_names([value[3]], value[3]) for value in observations]
        if any(len(value) != 1 for value in modes):
            return names
        linked = all(
            left[0] == right[0] and CAUSAL.fullmatch(chunks[left[0]][left[2] : right[1]])
            for left, right in zip(observations, observations[1:])
        )
        if linked and set(names) == {value[0] for value in modes}:
            return modes[0]
        return names

    def _members(self, item, pairs, equipment_values, chunks=None, *, part_role=None):
        failures = [
            symptom
            for pair in pairs
            for symptom in pair.symptoms
            if symptom.kind == "F" and self._failure_is_attached(pair, symptom, chunks)
        ]
        actions = [
            symptom.text
            for pair in pairs
            for symptom in pair.symptoms
            if symptom.kind in {"R", "A"}
        ]
        failure_words = [self._qualified_failure(symptom, chunks)[3] for symptom in failures]
        failure_words.extend(
            pair.context
            for pair in pairs
            if not pair.symptoms
            and pair.rule["symptom"] == "."
            and pair.rule["role"] in ("fallback", "nopart")
            and "F" in self.parts.evidence_kinds(pair)
        )
        completed_actions = action_names(actions)
        context = " ".join(pair.context + "".join(s.text for s in pair.symptoms) for pair in pairs)
        context += " " + " ".join(failure_words)
        if chunks is not None:
            for pair in pairs:
                prefix = chunks[pair.clause][max(0, pair.c0 - 12) : pair.c0]
                medium = FLUID_MEDIUM.search(prefix)
                if medium:
                    context += " " + medium.group()
        names = symptom_names(failure_words, context) or [UNKNOWN_SYMPTOM]
        observed_names = list(names)
        names = self._causal_symptom(pairs, chunks, names)
        for name in names:
            evidence = list(
                dict.fromkeys(
                    word
                    for word in (actions if name == "교체" else failure_words)
                    if (name == "교체" and "교체" in action_names([word]))
                    or any(
                        label == name and pattern.search(word)
                        for label, pattern in COMPILED_SYMPTOMS
                    )
                )
            )
            for equipment in equipment_values:
                public_part = self.taxonomy.component_name(
                    item["minor"], equipment["detail_equipment"]
                )
                if part_role is True:
                    public_part = self.taxonomy.canonical_part(item["minor"])
                if part_role is False or item.get("rule_id", "").endswith("_NOPART"):
                    public_part = UNKNOWN_PART
                major = self.taxonomy.major_for(
                    public_part, name, context, item["major"], equipment["detail_equipment"]
                )
                yield {
                    "major": major,
                    **equipment,
                    "middle": public_part,
                    "minor": name,
                    "schema": CLASSIFICATION_SCHEMA,
                    "part_key": part_key(major, public_part, equipment["detail_equipment"]),
                    "part_group": self.taxonomy.group(public_part),
                    "part_type": public_part,
                    "symptom_evidence": ", ".join(evidence),
                    "actions": completed_actions,
                    "rule_id": item.get("rule_id", ""),
                    "evidence": item.get("evidence", ""),
                    "_observed_failure": any(value != UNKNOWN_SYMPTOM for value in observed_names),
                    "observed_symptoms": observed_names,
                }

    @staticmethod
    def _automatic(result, member):
        missing = missing_fields_text(member)
        reason = result.get("classification_reason", "")
        if any(
            "의심·추정 후보" in candidate.get("reason", "")
            for candidate in json.loads(result.get("classification_candidates") or "[]")
        ):
            reason += (
                " 뒤에 적힌 의심·추정 원인은 후보로만 보존하며 실제 고장으로 확정하지 않습니다."
            )
        if missing:
            reason += (
                " 원문에서 확인된 항목을 부분 분류했습니다. 미기재 항목: "
                + missing
                + ". 추가 근거 없이 현상을 추정하지 않습니다."
            )
        return {
            **result,
            **component_payload([member]),
            **{key: member[key] for key in CATEGORY_FIELDS},
            **{
                key: member.get(key, "")
                for key in ("detail_equipment_source", "detail_equipment_evidence")
            },
            "classification_missing_fields": missing,
            "status": K["partial"] if missing else K["auto"],
            "review_code": "",
            "classification_reason": reason.strip(),
        }

    def _source_locations(self, chunks, pairs):
        """Reserve each matched noun for its part or its equipment role."""
        parts_by_clause = defaultdict(list)
        for pair in pairs:
            part = self.taxonomy.canonical_part(pair.rule["minor"])
            if (
                pair.symptoms
                and pair.rule["role"] in {"component", "override"}
                and part in self.taxonomy.names
                and self.taxonomy.canonical_part(pair.context) == part
            ):
                parts_by_clause[pair.clause].append((pair, part))

        locations, roles = [], {}
        for index, chunk in enumerate(chunks):
            mentions = self.equipment.mentions(chunk)
            resolved = []
            for start, end, name in mentions:
                sharing = [
                    (pair, part)
                    for pair, part in parts_by_clause[index]
                    if pair.c0 <= start < end <= pair.c1 and (pair.c0 < start or pair.c1 == end)
                ]
                if not sharing:
                    resolved.append((start, end, name))
                    continue
                explicit_module = MODULE_DESIGNATION.match(chunk, end)
                if explicit_module:
                    roles.update((id(pair), False) for pair, _ in sharing)
                    resolved.append((start, end, name))
                elif all(part == "포머" for _, part in sharing) and not any(
                    other_end <= start for _, other_end, _ in mentions
                ):
                    # A bare former remains the forming module unless a parent is stated.
                    resolved.append((start, end, name))
                else:
                    roles.update((id(pair), True) for pair, _ in sharing)
            locations.append(resolved)
        return locations, roles

    def _bound_members(
        self, item, pairs, chunks, locations, part_roles, equipment_context, registered_equipment
    ):
        """Keep each machine's own symptom evidence together across repeated parts."""
        grouped = {}
        if not pairs:
            values = self.equipment.resolve(
                chunks, [], equipment_context, registered_equipment, locations=locations
            )
            yield from self._members(item, [], values, chunks)
            return
        for pair in pairs:
            role = part_roles.get(id(pair))
            for equipment in self.equipment.resolve(
                chunks, [pair], equipment_context, registered_equipment, locations=locations
            ):
                if (
                    role is True
                    and equipment["detail_equipment_source"] == "비가동코드(중)"
                    and re.sub(r"\s+", "", equipment_context).casefold() == pair.context.casefold()
                ):
                    # A code repeating the same part supplies no separate installation location.
                    equipment = self.equipment._value(UNKNOWN_EQUIPMENT, "미기재", "")
                key = (equipment["detail_equipment"], role)
                if key not in grouped:
                    grouped[key] = (equipment, [])
                grouped[key][1].append(pair)
        known = [key for key in grouped if key[0] != UNKNOWN_EQUIPMENT]
        unknown = (UNKNOWN_EQUIPMENT, known[0][1]) if len(known) == 1 else None
        if unknown in grouped:
            # Repeated mentions of the same part may omit the machine after a
            # sentence boundary. Keep its sole stated location and own evidence.
            grouped[known[0]][1].extend(grouped.pop(unknown)[1])
        for (_, role), (equipment, own_pairs) in grouped.items():
            yield from self._members(item, own_pairs, [equipment], chunks, part_role=role)

    def _unresolved_shared_action(self, live, chunks, *, unknown_only=False):
        """An explicit part list cannot silently confirm only its nearest member.

        Unrecognized words between named parts do not justify propagating a
        repair to them; retain the candidates for a human rather than guessing.
        """
        repaired = [
            pair
            for pair in live
            if action_names(
                [symptom.text for symptom in pair.symptoms if symptom.kind in {"R", "A"}]
            )
        ]
        for pair in repaired:
            for symptom in pair.symptoms:
                if symptom.clause == pair.clause and action_names([symptom.text]):
                    bridge = chunks[pair.clause][pair.c1 : symptom.start]
                    named_subject = any(
                        other.clause == pair.clause
                        and pair.c1 <= other.c0 < other.c1 <= symptom.start
                        for other in live
                    )
                    if re.match(r"(?:및|&|·).+", bridge) and not named_subject:
                        return True
        if unknown_only:
            return False
        for weak in live:
            if weak.symptoms or not self._safe_context(weak, live, chunks):
                continue
            for strong in repaired:
                if (
                    weak.clause != strong.clause
                    or weak.c1 > strong.c0
                    or weak.category == strong.category
                ):
                    continue
                connector = chunks[weak.clause][weak.c1 : strong.c0]
                if re.match(r"(?:및|&|·)", connector) and len(connector) <= self.parts.window:
                    return True
        return False

    def _recommendations(
        self,
        live,
        chunks,
        locations,
        part_roles,
        part_code,
        equipment_context,
        registered_equipment,
    ):
        explicit = {id(pair) for pair, _ in self.parts.explicit_cause_pairs(live, chunks)}
        compatible = self.parts.part_majors.get(re.sub(r"\s+", "", part_code or ""), set())
        candidates = []
        for pair in live:
            if (
                not pair.symptoms
                and pair.context.casefold() in re.sub(r"\s+", "", equipment_context).casefold()
            ):
                # A MES equipment name describes the location unless its own fault/action is stated.
                continue
            if not pair.symptoms and not self._safe_context(pair, live, chunks):
                continue
            kinds = self.parts.evidence_kinds(pair)
            cause = (
                id(pair) in explicit
                or self.parts.causal(pair, chunks)
                or pair.rule["role"] == "override"
            )
            mes = pair.rule["major"] in compatible
            distance = min(
                (
                    abs(symptom.start - pair.c1)
                    if symptom.clause == pair.clause
                    else self.parts.window + 1
                    for symptom in pair.symptoms
                ),
                default=self.parts.window + 2,
            )
            reasons = []
            if UNCERTAIN.search(chunks[pair.clause]):
                reasons.append("의심·추정 후보: 실제 고장 미확정")
            if cause:
                reasons.append("원문 원인 표현과 연결된 부품")
            if "F" in kinds:
                reasons.append("원문에 고장·증상 명시")
            if "R" in kinds:
                reasons.append("원문에 완료된 교체·수리 명시")
            if "A" in kinds:
                reasons.append("원문에 점검·조정 조치 명시")
            if mes:
                reasons.append("MES 소분류의 분야와 일치")
            if pair.symptoms:
                reasons.append("부품과 증상의 문맥 근접 및 세부 규칙 우선순위")
            elif kinds:
                reasons.append("문자 그대로의 고장·증상 조건 일치")
            else:
                reasons.append("부품명 문맥만 일치한 약한 근거: 고장·증상 확인 필요")
            item = self.parts.component_value(pair)
            for member in self._bound_members(
                item, [pair], chunks, locations, part_roles, equipment_context, registered_equipment
            ):
                observed = member["_observed_failure"]
                member_reasons = [
                    reason for reason in reasons if observed or reason != "원문에 고장·증상 명시"
                ]
                if not observed and not member["actions"]:
                    member_reasons.append("부품명만 확인됨: 이 부품의 고장·완료 조치 근거 부족")
                mode_order = min(
                    (
                        index
                        for index, symptom in enumerate(pair.symptoms)
                        if symptom.kind == "F"
                        and self._failure_is_attached(pair, symptom, chunks)
                        and member["minor"]
                        in symptom_names(
                            [self._qualified_failure(symptom, chunks)[3]],
                            pair.context + self._qualified_failure(symptom, chunks)[3],
                        )
                    ),
                    default=len(pair.symptoms),
                )
                candidates.append(
                    {
                        **member,
                        "_span": (pair.clause, pair.c0, pair.c1),
                        "_priority": pair.rule["priority"],
                        "reason": "; ".join(
                            [*member_reasons, "상세설비: " + member["detail_equipment_source"]]
                        ),
                        "_order": (
                            not (cause and (observed or member["actions"])),
                            not observed,
                            "R" not in kinds,
                            not mes,
                            distance,
                            -pair.rule["priority"],
                            pair.clause,
                            pair.c0,
                            pair.rule["id"],
                            mode_order,
                            member["minor"],
                        ),
                    }
                )
        # For explicitly listed physical faults in one sentence, retain the
        # first reported fault even when a later listed fault was repaired.
        # Keep the existing precedence for causes, nested names, repair-only
        # mentions and faults in separate statements.
        physical = [
            member
            for member in candidates
            if member["_observed_failure"]
            and member["middle"] not in {"세부 부품 미기재", "제품·자재"}
        ]
        if physical:
            for member in candidates:
                order = member["_order"]
                module_only = member["middle"] == "세부 부품 미기재" and member[
                    "detail_equipment"
                ] in {"석션기·블로워", "익스트랙터 바"}
                member["_order"] = (*order[:2], module_only, *order[2:])
            first = min(physical, key=lambda member: (*member["_span"][:2], member["_order"]))
            top = min(candidates, key=lambda member: member["_order"])
            clause, start, end = first["_span"]
            top_clause, top_start, _ = top["_span"]
            bridge = chunks[clause][end:top_start] if top_clause == clause else ""
            if (
                top in physical
                and first["_order"][0]
                and top["_order"][0]
                and start < top_start
                and re.search(r"및|그리고|&", bridge)
                and not re.search(r"으로|로인해|로인한|때문", bridge)
            ):
                for member in candidates:
                    member["_order"] = (
                        member["_span"] != first["_span"],
                        *member["_order"],
                    )
        return rank_candidates(candidates), candidates

    @staticmethod
    def _known_first_before_suspicion(ranked, raw, chunks):
        """A later guessed cause does not negate an earlier fault or completed action.

        A suspicion in the first fault's own clause or before it stays under
        review. Never skip a suspected rank 1 to confirm a lower candidate.
        """
        if not ranked:
            return False
        first_uncertain = next(
            (index for index, chunk in enumerate(chunks) if UNCERTAIN.search(chunk)), None
        )
        if first_uncertain is None:
            return False
        keys = (*CATEGORY_FIELDS, "rule_id", "evidence")
        return any(
            all(member.get(key) == ranked[0].get(key) for key in keys)
            and (member.get("_observed_failure") or member.get("actions"))
            and member["_span"][0] < first_uncertain
            for member in raw
            if "_span" in member
        )

    def _retain_known(self, result, raw, chunks, equipment_context, locations_by_clause):
        """Keep consensus facts without turning a pending path into a final part."""
        known = {}
        fallback_location = {}
        if raw:
            fields = CATEGORY_FIELDS
            alternatives_covered = all(
                any(
                    "_span" in member
                    and member["_span"][0] == index
                    and start <= member["_span"][1] < end
                    for member in raw
                )
                for index, chunk in enumerate(chunks)
                if re.search(r"또는|혹은|아니면", chunk)
                for start, end in zip(
                    [0, *(match.end() for match in re.finditer(r"또는|혹은|아니면", chunk))],
                    [
                        *(match.start() for match in re.finditer(r"또는|혹은|아니면", chunk)),
                        len(chunk),
                    ],
                )
                if chunk[start:end]
            )
            # A guessed part can still identify its location. Its failure,
            # domain and symptom are not established by that guess.
            if (
                not alternatives_covered
                or result.get("review_code") == "unmapped_fault_context"
                or any(
                    not (member.get("_observed_failure") or member.get("actions"))
                    or ("_span" in member and UNCERTAIN.search(chunks[member["_span"][0]]))
                    for member in raw
                )
            ):
                fields = ("detail_equipment",)
            for key in fields:
                values = {member.get(key, "") for member in raw}
                if len(values) == 1:
                    value = values.pop()
                    if value and value not in MISSING_VALUES[key]:
                        known[key] = value
        else:
            # MES middle code is a location source; the registered asset is not.
            locations = self.equipment.resolve(
                chunks, [], equipment_context, locations=locations_by_clause
            )
            if len(locations) == 1 and locations[0]["detail_equipment"] != UNKNOWN_EQUIPMENT:
                known["detail_equipment"] = locations[0]["detail_equipment"]
                fallback_location = locations[0]
            observations = [
                match.group()
                for chunk in chunks
                if not (
                    UNCERTAIN.search(chunk)
                    or NEGATION.search(chunk)
                    or NEGATED_PART.search(chunk)
                    or PLANNED_BEFORE.search(chunk)
                    or re.search(r"예정|계획|예방|방지|유무|여부", chunk)
                )
                for match in re.finditer(
                    r"터짐|터져|파열|파손|부러짐|빠짐|걸림|막힘|누설|누수|누출|누유|리크",
                    chunk,
                )
            ]
            modes = symptom_names(observations)
            if len(modes) == 1:
                known["minor"] = modes[0]
        source_locations = {
            name: chunk
            for chunk, mentions in zip(chunks, locations_by_clause, strict=True)
            if not (
                NEGATION.search(chunk)
                or NEGATED_PART.search(chunk)
                or PLANNED_BEFORE.search(chunk)
                or re.search(r"정상|예정|계획|미실시|요망", chunk)
            )
            for _, _, name in mentions
        }
        if len(source_locations) > 1:
            known.pop("detail_equipment", None)
        elif not raw and len(source_locations) == 1:
            name, evidence = next(iter(source_locations.items()))
            fallback_location = self.equipment.refine(
                {
                    "detail_equipment": name,
                    "detail_equipment_source": "원문",
                    "detail_equipment_evidence": evidence,
                },
                equipment_context,
            )
            known["detail_equipment"] = fallback_location["detail_equipment"]
        if not known:
            return result
        location = next(
            (
                member
                for member in raw
                if member.get("detail_equipment") == known.get("detail_equipment")
            ),
            fallback_location,
        )
        return {
            **result,
            **known,
            KNOWN_FIELDS: json.dumps(known, ensure_ascii=False, separators=(",", ":")),
            "part_group": self.taxonomy.group(known.get("middle", "")),
            "detail_equipment_source": location.get(
                "detail_equipment_source", result.get("detail_equipment_source", "")
            ),
            "detail_equipment_evidence": location.get(
                "detail_equipment_evidence", result.get("detail_equipment_evidence", "")
            ),
            "classification_missing_fields": missing_fields_text(known),
        }

    def _machine_problem(self, chunks, raw):
        """A named machine with a general problem needs no invented subpart.

        This fills a gap in machine-body rules, not arbitrary noun/fault binding.
        Require one direct problem statement and reject other fault statements,
        unknown part subjects, plans, alternatives and suspicions.
        """
        source = "".join(chunks)
        if (
            UNCERTAIN.search(source)
            or PLANNED_BEFORE.search(source)
            or NEGATION.search(source)
            or NEGATED_PART.search(source)
            or re.search(r"정상|예정|계획|또는|혹은|아니면|요망|미실시", source)
            or re.search(r"예방|방지|유무|여부|아님|아니|없었|없다|없어", source)
            or any(member.get("middle") != UNKNOWN_PART for member in raw)
        ):
            return None
        failures = [
            (index, match)
            for index, chunk in enumerate(chunks)
            for match in re.finditer(r"고장|이상|불량|오류|에러|트러블|문제", chunk)
        ]
        if len(failures) != 1:
            return None
        index, failure = failures[0]
        chunk = chunks[index]
        if symptom_names([source], source) != ["고장·이상"]:
            return None
        mentions = self.equipment.mentions(chunk)
        if len(mentions) != 1:
            return None
        _, end, name = mentions[0]
        if end > failure.start() or not re.fullmatch(
            r"(?:에서|에|의|가|은|는|이|측|본체|반복적(?:인|으로)?|반복(?:적으로)?|계속|간헐적(?:인|으로)?|지속적(?:인|으로)?|동일|재차|다시)*",
            chunk[end : failure.start()],
        ):
            return None
        # A second named machine creates a location conflict even if only one
        # general problem word was supplied.
        if {n for item in chunks for _, _, n in self.equipment.mentions(item)} != {name}:
            return None
        return {
            "major": UNKNOWN_DOMAIN,
            "detail_equipment": name,
            "middle": UNKNOWN_PART,
            "minor": "고장·이상",
            "schema": CLASSIFICATION_SCHEMA,
            "part_group": "미기재",
            "actions": extract_actions(source),
            "rule_id": "observed_machine_problem",
            "evidence": chunk,
            "symptom_evidence": failure.group(),
            "detail_equipment_source": "원문",
            "detail_equipment_evidence": chunk,
        }

    def _explicit_observation(self, chunks, locations, equipment_context, source_text):
        """Retain one directly stated symptom even when the failed part is omitted."""
        if not chunks:
            return None
        chunk, mentions = chunks[0], locations[0]
        if len(mentions) > 1 or any(
            cites
            or not re.fullmatch(
                r"(?:재가동|재부팅)(?:후(?:오류|에러)재발생)?|(?:제상|리셋)(?:작업|진행)?(?:후(?:생산시작|재가동))?",
                continuation,
            )
            for continuation, cites in zip(chunks[1:], locations[1:], strict=True)
        ):
            return None
        if mentions:
            start, end, name = mentions[0]
            if not re.fullmatch(r"[\d번호기:#\-]*", chunk[:start]):
                return None
            tail = re.sub(r"^(?:에서|본체|측|[에의가는은이]|#?\d+(?:번|호기)?)*", "", chunk[end:])
            location = self.equipment.refine(
                self.equipment._value(name, "원문", chunk), equipment_context
            )
        else:
            tail = chunk
            values = self.equipment.resolve(chunks, [], equipment_context, locations=locations)
            if len(values) != 1:
                return None
            location = values[0]
        tail = re.sub(r"^(?:주입구|입구|출구)(?=(?:공압|에어압|압력))", "", tail)
        if location["detail_equipment"] == "동결설비":
            tail = re.sub(r"^(?:언로딩|로딩)부?(?=오작동|동작불량|작동불량|동작이상)", "", tail)
        # A code reported before the PC was shut down is the observation.
        tail = re.sub(r"(?<=발생)(?:으로|로)(?:pc|컴퓨터)전원(?:종료|차단)$", "", tail, flags=re.I)
        matches = {
            mode: evidence.group()
            for mode, pattern in COMPILED_SYMPTOMS
            if mode in OBSERVED_WITHOUT_PART
            and (evidence := pattern.match(tail))
            and re.fullmatch(
                r"(?:이|가)?(?:오류|에러)?(?:발생(?:함|했음|됨)?|임|됨|현상|상태)?"
                r"(?:\d+분|으로운휴|로중단|정지|운휴)?",
                tail[evidence.end() :],
            )
        }
        if len(matches) > 1:
            matches.pop("고장·이상", None)
        if len(matches) == 1:
            mode, evidence = next(iter(matches.items()))
        elif (
            not matches
            and mentions
            and re.fullmatch(
                r"(?:정비|수리|(?:타이밍|센터링|센터|위치|각도|높이)(?:재)?조정)(?:완료|후(?:가동|생산재개))?",
                tail,
            )
        ):
            mode, evidence = UNKNOWN_SYMPTOM, tail
        else:
            return None
        if mode == "압력이상" and not tail.startswith(("압력", "공압", "에어압")):
            return None
        if mode == "위치·설정이상" and not (
            re.match(r"(?:원점|타이밍|위치|정렬|텐션|센터).+", evidence) or evidence == "슬립"
        ):
            return None
        if (
            mode in {"동작불량", "고장·이상"}
            and not mentions
            and (
                location["detail_equipment"] == UNKNOWN_EQUIPMENT
                or evidence in {"고장", "이상", "문제"}
            )
        ):
            return None
        if (
            mode in {"과부하·과전류", "위치·설정이상"}
            and location["detail_equipment"] == UNKNOWN_EQUIPMENT
        ) or (mode == "통신·입출력 이상" and evidence == "통신"):
            return None
        if (
            source_text is not None
            and mode != UNKNOWN_SYMPTOM
            and mode not in symptom_names([re.sub(r"\s+", "", source_text)])
        ):
            return None
        major = self.taxonomy.major_for(
            UNKNOWN_PART, mode, chunk, UNKNOWN_DOMAIN, location["detail_equipment"]
        )
        if mode == "압력이상" and tail.startswith(("공압", "에어압")):
            major = "공압·진공"
        if mode == "과부하·과전류" and evidence.casefold() in {"과부하", "overload"}:
            major = UNKNOWN_DOMAIN
        return {
            **location,
            "major": major,
            "middle": UNKNOWN_PART,
            "minor": mode,
            "schema": CLASSIFICATION_SCHEMA,
            "part_group": "미기재",
            "rule_id": "observed_symptom_without_part",
            "evidence": chunk,
            "symptom_evidence": evidence if mode != UNKNOWN_SYMPTOM else "",
            "actions": extract_actions(" / ".join(chunks)),
        }

    def classify(
        self,
        text: str,
        part_code: str = "",
        code_text: str | None = None,
        *,
        equipment_context: str = "",
        registered_equipment: str = "",
        source_text: str | None = None,
    ) -> dict:
        equipment_context = str(equipment_context or "").strip()
        code = (part_code if code_text is None else code_text).strip()
        code_action = code in ("교체", "교환")
        blocked_action = (
            PLANNED_BEFORE.search(text)
            or NEGATION.search(text)
            or NEGATED_PART.search(text)
            or re.search(r"요망|미실시|불필요|취소|보류", text)
        )
        original = self.parts.classify(text, part_code, code_text)
        if (
            code_action
            and not blocked_action
            and not parse_components(original.get("component_details"))
        ):
            supplemented = f"{text} 교체"
            coded = self.parts.classify(supplemented, part_code, code_text)
            if parse_components(coded.get("component_details")):
                original = self.parts.staged(
                    coded, f"비가동코드(소) '{code}'의 교체 조치를 적용했습니다."
                )
                text = supplemented
        selected = parse_components(original.get("component_details"))
        source = text
        part_from_code = "부품명으로 판정" in original.get("classification_reason", "")
        if part_from_code:
            source = f"{part_code if code_text is None else code_text} {text}"
        chunks = clauses(source)
        nopart_ids = {rule["id"] for rule, *_ in self.parts.nopart_rules}
        stage_rules = (
            self.parts.nopart_rules
            if any(item.get("rule_id") in nopart_ids for item in selected)
            else self.parts.rules
        )
        matched = self.parts.pairs(chunks, stage_rules)
        live = self.parts.eligible_pairs(matched, chunks)
        locations, part_roles = self._source_locations(chunks, live)
        candidates, raw_candidates = self._recommendations(
            live, chunks, locations, part_roles, part_code, equipment_context, registered_equipment
        )
        result = {
            **original,
            "classification_candidates": json.dumps(
                candidates, ensure_ascii=False, separators=(",", ":")
            ),
            "candidates": " | ".join(f"{item['rank']}. {type_label(item)}" for item in candidates),
            "candidate_evidence": "\n".join(
                f"{item['rank']}. {type_label(item)} "
                f"[{item['rule_id']}] | 추천 근거: {item['reason']} | 원문 근거: {item['evidence']}"
                for item in candidates
            ),
            "classification_schema": CLASSIFICATION_SCHEMA,
            "detail_equipment_source": "",
            "detail_equipment_evidence": "",
            "repair_actions": ", ".join(extract_actions(text)),
            "classification_missing_fields": "",
            KNOWN_FIELDS: "",
        }
        record_text = "".join(
            chunk
            for chunk in clauses(text)
            if not (
                NEGATION.search(chunk)
                or NEGATED_PART.search(chunk)
                or PLANNED_BEFORE.search(chunk)
            )
        )
        shop_terms = set(re.findall(r"무접점홀더", record_text))
        if "익스트랙터바" in record_text and "익스트로바" in (source_text or ""):
            shop_terms.update(re.findall(r"어퍼(?:드라이브)?", record_text))
        if "멤브레인교체" in record_text:
            shop_terms.add("멤브레인")
        unconfirmed = sorted(
            term for term in shop_terms if not any(pair.context == term for pair in live)
        )
        observations = [member for member in raw_candidates if member.get("_observed_failure")]
        if (
            unconfirmed
            and observations
            and all(
                member["middle"] == UNKNOWN_PART or "멤브레인" in unconfirmed
                for member in observations
            )
        ):
            return self._retain_known(
                {
                    **result,
                    **component_payload([], "ambiguous"),
                    **{key: "" for key in CATEGORY_FIELDS},
                    "status": K["review"],
                    "review_code": "unmapped_fault_context",
                    "classification_reason": (
                        "현장 명칭과 대상의 대응 확인 필요: " + ", ".join(unconfirmed)
                    ),
                },
                raw_candidates,
                chunks,
                equipment_context,
                locations,
            )
        if re.search(r"(?:동일|같은)문제", "".join(chunks)) and all(
            member["middle"] == UNKNOWN_PART and member["minor"] in {"고장·이상", UNKNOWN_SYMPTOM}
            for member in raw_candidates
        ):
            return self._retain_known(
                {
                    **result,
                    **component_payload([], "ambiguous"),
                    **{key: "" for key in CATEGORY_FIELDS},
                    "status": K["review"],
                    "review_code": "previous_fault_unspecified",
                    "classification_reason": "이전과 동일한 문제라는 참조만 있고 구체적인 현상·부품이 없습니다. 확인된 상세설비는 보존하고 이전 고장 내용을 확인합니다.",
                },
                raw_candidates,
                chunks,
                equipment_context,
                locations,
            )
        observed = [member for member in raw_candidates if member.get("_observed_failure")]
        if any(member["minor"] == "점도이상" for member in observed) and all(
            member["middle"] == "세부 부품 미기재" for member in observed
        ):
            return self._retain_known(
                {
                    **result,
                    **{key: "" for key in CATEGORY_FIELDS},
                    **component_payload([], "ambiguous"),
                    "status": K["review"],
                    "review_code": "process_condition_without_fault_part",
                    "classification_reason": (
                        "점도 헌팅·이상은 공정조건의 현상으로 후보에 보존합니다. "
                        "원인 부품이 명시되지 않아 검토가 필요하며 센서 고장으로 추정하지 않습니다."
                    ),
                },
                raw_candidates,
                chunks,
                equipment_context,
                locations,
            )
        known_before_suspicion = self._known_first_before_suspicion(
            candidates, raw_candidates, chunks
        )
        network_pattern = r"(?:inputs\s*/\s*outputs\s*network|network\s*station\s*in\s*defect)"
        network = re.search(network_pattern, text, re.I)
        network_members = []
        observed_network = any(
            not (
                PLANNED_BEFORE.search(chunk)
                or UNCERTAIN.search(chunk)
                or re.search(
                    r"^(?:정상|normal)|(?:아님|아니|없음|없다|없었|예정|계획|planned|noerror|notindefect)",
                    chunk,
                    re.I,
                )
                or re.search(network_pattern + r"(?:정상|normal)", chunk, re.I)
            )
            for chunk in chunks
            if re.search(network_pattern, chunk, re.I)
        )
        if (
            network
            and observed_network
            and not any(c["minor"] == "통신·입출력 이상" for c in candidates)
        ):
            names = list(dict.fromkeys(name for mentions in locations for _, _, name in mentions))
            if not names:
                names = [
                    value["detail_equipment"]
                    for value in self.equipment.resolve(
                        chunks, [], equipment_context, registered_equipment, locations=locations
                    )
                ]
            network_members = [
                {
                    "major": "전기·제어",
                    "detail_equipment": name,
                    "middle": "세부 부품 미기재",
                    "minor": "통신·입출력 이상",
                    "schema": CLASSIFICATION_SCHEMA,
                    "part_group": "미기재",
                    "actions": extract_actions(text),
                    "evidence": network.group(),
                    "symptom_evidence": network.group(),
                    "rule_id": "observed_network_description",
                    "_observed_failure": True,
                    "detail_equipment_source": "원문" if name != "상세설비 미상" else "미기재",
                }
                for name in names
            ]
            candidates = rank_candidates([*network_members, *candidates])
            raw_candidates.extend(network_members)
            result.update(
                classification_candidates=json.dumps(candidates, ensure_ascii=False),
                candidates=" | ".join(f"{c['rank']}. {type_label(c)}" for c in candidates),
                candidate_evidence="\n".join(
                    f"{c['rank']}. {type_label(c)}: {c.get('evidence', '')}" for c in candidates
                ),
            )
            if (
                not selected
                and len(network_members) == 1
                and not any(s.kind == "F" for p in live for s in p.symptoms)
            ):
                member = network_members[0]
                return self._automatic(
                    {
                        **result,
                        "classification_reason": "원문 network station/입출력 통신 오류 설명을 적용했습니다. 개별 카드 고장은 추정하지 않습니다.",
                    },
                    {**member, "detail_equipment_evidence": network.group()},
                )
        if not selected or part_from_code or not observed:
            observed_chunks = clauses(text) if part_from_code else chunks
            observed_locations = (
                [self.equipment.mentions(chunk) for chunk in observed_chunks]
                if part_from_code
                else locations
            )
            observation = self._explicit_observation(
                observed_chunks, observed_locations, equipment_context, source_text
            )
            if observation and (
                not part_from_code or observation["detail_equipment_source"].startswith("원문")
            ):
                return self._automatic(
                    {
                        **result,
                        "classification_reason": (
                            (
                                "원문에 기록된 설비와 완료 조치를 보존했습니다."
                                if observation["minor"] == UNKNOWN_SYMPTOM
                                else "원문에 직접 기록된 고장 현상을 보존했습니다. "
                                "현상에 연결되는 세부 부품이 확인되지 않았습니다."
                            )
                            + (
                                " 비가동코드(소)의 부품은 후보에 보존했습니다."
                                if part_from_code
                                else ""
                            )
                        ),
                    },
                    observation,
                )
        if not selected:
            machine = self._machine_problem(chunks, raw_candidates)
            if source_text is not None and not re.search(
                r"고장|이상|불량|오류|에러|트러블|문제", re.sub(r"\s+", "", source_text)
            ):
                # Do not newly auto-confirm a generic machine error solely
                # because a clipped source syllable was expanded by normalization.
                machine = None
            if machine is not None:
                return self._automatic(
                    {
                        **result,
                        "classification_reason": "원문에 명시된 상세설비와 일반적인 고장·이상을 보존했습니다. 원인 부품과 고장 분야는 미상으로 둡니다.",
                    },
                    machine,
                )
            return self._retain_known(
                {
                    **result,
                    **{key: "" for key in CATEGORY_FIELDS},
                    **component_payload([], original.get("classification_mode", "unclassified")),
                },
                raw_candidates,
                chunks,
                equipment_context,
                locations,
            )
        by_type = defaultdict(list)
        for pair in live:
            if pair.symptoms or pair.rule["symptom"] == ".":
                by_type[pair.category].append(pair)
        members = [
            member
            for item in selected
            for member in self._bound_members(
                item,
                by_type[tuple(item[key] for key in ("major", "middle", "minor"))],
                chunks,
                locations,
                part_roles,
                equipment_context,
                registered_equipment,
            )
        ]
        if network_members and not any(member["minor"] == "통신·입출력 이상" for member in members):
            members.extend(network_members)
        independent_pairs = self.parts.independent_pairs(live, chunks)
        independent_pairs = [
            pair
            for pair in independent_pairs
            if pair.rule["priority"]
            == max(
                other.rule["priority"]
                for other in independent_pairs
                if (other.clause, other.c0, other.c1) == (pair.clause, pair.c0, pair.c1)
            )
        ]
        evidenced = defaultdict(list)
        for pair in independent_pairs:
            if pair.symptoms or (
                pair.rule["symptom"] == "." and "F" in self.parts.evidence_kinds(pair)
            ):
                evidenced[pair.category].append(pair)
        evidence_members = [
            member
            for own_pairs in evidenced.values()
            for member in self._bound_members(
                self.parts.component_value(own_pairs[0]),
                own_pairs,
                chunks,
                locations,
                part_roles,
                equipment_context,
                registered_equipment,
            )
        ]
        evidence_members.extend(network_members)
        observed_modes = {
            mode
            for pair in live
            for symptom in pair.symptoms
            if symptom.kind == "F"
            for mode in symptom_names([symptom.text])
        }

        def restated_repair(chunk):
            match = re.fullmatch(
                r"(파손|손상|마모|단선|소손)(?:부위|부분)(?:를|을|에|은|는)?"
                r"(?:용접|보수|수리|정비)(?:함|완료|실시)?",
                chunk,
            )
            return bool(match and set(symptom_names([match.group(1)])) & observed_modes)

        # An unrecognized subject with its own explicit physical failure is
        # competing evidence, even when the catalog cannot name that part.
        # Keep it under review rather than confirm an earlier machine outcome.
        unmatched_fault = any(
            (
                not any(
                    pair.clause == index or any(s.clause == index for s in pair.symptoms)
                    for pair in live
                )
                or (
                    not any(pair.clause == index for pair in live)
                    and re.search(
                        r"(?:용접|보수|수리|정비|교체)(?:및|후|하고)"
                        r"[가-힣a-z0-9]{2,12}(?:소손|단선|파손|손상|마모|누설|고착)",
                        chunk,
                    )
                )
            )
            and not restated_repair(chunk)
            and re.search(r"소손|단선|파손|손상|마모|누설|누수|누유|고착|쇼트|합선|누전", chunk)
            and not (
                PLANNED_BEFORE.search(chunk)
                or NEGATION.search(chunk)
                or NEGATED_PART.search(chunk)
                or re.search(r"예정|계획|불필요|취소|보류|아님|없음|없다", chunk)
            )
            for index, chunk in enumerate(chunks)
        )
        blocked = bool(
            (UNCERTAIN.search(source) and not known_before_suspicion)
            or INDEPENDENT_MARKER.search(source)
            or self.parts.alternative_types(live, chunks)
            or self.parts.explicit_cause_pairs(live, chunks)
            or any(pair.rule["role"] == "override" for pair in live)
            or self._unresolved_shared_action(live, chunks)
            or unmatched_fault
            or re.search(r"또는|혹은|아니면", source)
        )
        direct = choose_direct_fault(evidence_members, blocked=blocked)
        if direct is not None:
            return self._automatic(
                {
                    **result,
                    "classification_reason": "원문에 직접 명시된 단일 부품의 고장 현상을 대표 고장으로 적용했습니다. 다른 부품의 완료 조치는 조치 내역과 근거에 보존합니다.",
                },
                direct,
            )
        payload = component_payload(members)
        actual = parse_components(payload["component_details"])
        uncertain = bool(UNCERTAIN.search("".join(chunks))) and not known_before_suspicion
        shared_action = self._unresolved_shared_action(live, chunks)
        missing_symptom = any(item["minor"] == UNKNOWN_SYMPTOM for item in actual)
        missing_domain = any(item["major"] == UNKNOWN_DOMAIN for item in actual)
        supported = bool(members) and all(
            member.get("_observed_failure") or member.get("actions") for member in members
        )
        selected_identity = {(member["detail_equipment"], member["middle"]) for member in members}
        competing_failure = any(
            member.get("_observed_failure")
            and (member["detail_equipment"], member["middle"]) not in selected_identity
            for member in evidence_members
        )
        worked_identities = {
            (member["detail_equipment"], member["middle"])
            for member in evidence_members
            if member.get("actions")
        }
        ambiguous_work = missing_symptom and len(worked_identities) > 1
        explicit_alternative = bool(re.search(r"또는|혹은|아니면", "".join(chunks)))
        if (
            original["status"] == K["review"]
            or len(actual) != 1
            or not supported
            or uncertain
            or shared_action
            or competing_failure
            or ambiguous_work
            or explicit_alternative
            or unmatched_fault
        ):
            representative = choose_ranked_representative(
                candidates,
                raw_candidates,
                blocked=bool(
                    uncertain
                    or explicit_alternative
                    or unmatched_fault
                    or self._unresolved_shared_action(live, chunks, unknown_only=True)
                ),
            )
            if representative is not None:
                return self._automatic(
                    {
                        **result,
                        "classification_reason": (
                            "1순위 대표 자동선택: 원문에 고장 또는 완료 조치 근거가 있는 추천 1순위를 "
                            "이 이력의 대표 분류로 적용했습니다. 다른 후보와 원문·조치를 보존합니다. "
                            "여러 고장 중 대표 하나를 고른 결과이며 유일한 고장이나 원인 확정은 아닙니다."
                        ),
                    },
                    representative,
                )
            code = original.get("review_code", "")
            reason = original.get("classification_reason", "")
            if uncertain:
                code, reason = (
                    "uncertain_fault",
                    "의심·추정 표현을 추천 후보로 보존합니다. 실제 고장 유형을 확인해 하나를 선택하세요.",
                )
            elif explicit_alternative:
                code, reason = (
                    "alternative_types",
                    "원문에 여러 대안이 명시되어 있습니다. 후보를 임의로 하나 선택하지 않고 실제 고장을 확인합니다.",
                )
            elif unmatched_fault:
                code, reason = (
                    "unmapped_fault_context",
                    "분류 목록에서 부품을 식별하지 못한 다른 절에도 명시된 고장 근거가 있습니다. 앞쪽 설비 현상만 대표 고장으로 확정하지 않고 확인합니다.",
                )
            elif shared_action or ambiguous_work:
                code, reason = (
                    "multiple_faults",
                    "'및'으로 연결된 여러 부품에 완료된 교체·수리 조치가 기록됐습니다. 가까운 부품 하나만 자동 확정하지 않고 최종 분류를 확인합니다.",
                )
            elif competing_failure:
                code, reason = (
                    "multiple_faults",
                    "다른 부품의 고장 근거가 함께 있습니다. 고장 부품과 조치 부품을 구분해 대표 고장을 확인합니다.",
                )
            elif len(actual) > 1:
                several_parts = (
                    len(
                        {
                            (item["major"], item["detail_equipment"], item["middle"])
                            for item in actual
                        }
                    )
                    > 1
                )
                code = code or ("multiple_faults" if several_parts else "multiple_symptoms")
                reason = "복수 부품 또는 복수 증상을 추천 후보로 보존합니다. 사용자 확인 전에는 최종 유형을 선택하지 않습니다."
            elif missing_symptom and not code:
                code, reason = (
                    "symptom_missing",
                    "부품 또는 조치는 확인되지만 고장 증상이 기록되지 않았습니다. 증상을 추정하지 않고 사용자 확인을 기다립니다.",
                )
            elif missing_domain and not code:
                code, reason = (
                    "domain_missing",
                    "고장 분야를 판단할 근거가 부족합니다. 부품과 현상 후보를 확인해 최종 분류를 선택하세요.",
                )
            return self._retain_known(
                {
                    **result,
                    **component_payload([], "ambiguous"),
                    **{key: "" for key in CATEGORY_FIELDS},
                    "status": K["review"],
                    "review_code": code or "multi_rule",
                    "classification_reason": reason,
                },
                raw_candidates,
                chunks,
                equipment_context,
                locations,
            )
        return self._automatic(result, actual[0])
