"""Turn matched source parts into event-linked part/symptom classifications."""

from __future__ import annotations

from collections import defaultdict

from core.classifier import UNCERTAIN, RuleClassifier, clauses
from core.failure_modes import (
    CLASSIFICATION_SCHEMA,
    COMPILED_SYMPTOMS,
    UNKNOWN_SYMPTOM,
    action_names,
    part_key,
    part_name,
    symptom_names,
)
from core.fault_components import combination_category, component_payload, parse_components
from core.i18n import K


class FaultClassifier:
    """Public event classifier; RuleClassifier remains the internal part matcher."""

    def __init__(self, rules, engine=None):
        self.parts = RuleClassifier(rules, engine)

    def classify(self, text: str, part_code: str = "", code_text: str | None = None) -> dict:
        original = self.parts.classify(text, part_code, code_text)
        selected = parse_components(original.get("component_details"))
        if not selected:
            return {**original, "part_count": 0, "classification_schema": CLASSIFICATION_SCHEMA}
        source = text
        if "비가동코드(소)" in original.get("classification_reason", ""):
            source = f"{part_code if code_text is None else code_text} | {text}"
        chunks = clauses(source)
        nopart_ids = {rule["id"] for rule, *_ in self.parts.nopart_rules}
        stage_rules = (
            self.parts.nopart_rules
            if any(item.get("rule_id") in nopart_ids for item in selected)
            else self.parts.rules
        )
        matched = self.parts.pairs(chunks, stage_rules)
        live = self.parts.eligible_pairs(
            [pair for pair in matched if pair.symptoms or pair.rule["symptom"] == "."], chunks
        )
        by_type = defaultdict(list)
        for pair in live:
            by_type[pair.category].append(pair)
        members = []
        for item in selected:
            old_path = tuple(item[key] for key in ("major", "middle", "minor"))
            pairs = by_type[old_path]
            failures = [s for pair in pairs for s in pair.symptoms if s.kind == "F"]
            actions = [s.text for pair in pairs for s in pair.symptoms if s.kind in {"R", "A"}]
            names = symptom_names([s.text for s in failures])
            if not names:
                names = [UNKNOWN_SYMPTOM]
            for name in names:
                evidence_words = list(
                    dict.fromkeys(
                        s.text
                        for s in failures
                        if any(
                            label == name and pattern.search(s.text)
                            for label, pattern in COMPILED_SYMPTOMS
                        )
                    )
                )
                member = {
                    "major": item["major"],
                    "middle": part_name(item["minor"]),
                    "minor": name,
                    "schema": CLASSIFICATION_SCHEMA,
                    "part_key": part_key(item["major"], item["minor"]),
                    "part_group": item["middle"],
                    "part_type": item["minor"],
                    "symptom_evidence": ", ".join(evidence_words),
                    "actions": action_names(actions),
                    "rule_id": item.get("rule_id", ""),
                    "evidence": item.get("evidence", ""),
                }
                members.append(member)
        mode = original["classification_mode"]
        if len(members) > 1:
            mode = "multiple"
        payload = component_payload(members, mode)
        actual = parse_components(payload["component_details"])
        category = (
            combination_category(actual)
            if len(actual) > 1
            else {key: actual[0][key] for key in ("major", "middle", "minor")}
        )
        result = {**original, **payload, **category, "classification_schema": CLASSIFICATION_SCHEMA}
        if UNCERTAIN.search("".join(chunks)):
            result.update(status=K["review"], review_code="uncertain_fault")
            result["classification_reason"] = (
                "원문의 의심·추정 표현을 부품·증상 후보로 보존하며 확인이 필요합니다."
            )
        return result
