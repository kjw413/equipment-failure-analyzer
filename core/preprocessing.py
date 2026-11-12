"""Build stable source records and apply the configured classification policy."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import timedelta
from typing import Any

import pandas as pd

from core.classification_candidates import parse_candidates, rank_candidates
from core.equipment_names import (
    active_name_mapping,
    code_key,
    effective_name_source,
    normalize_name_settings,
    resolve_group,
    resolve_name,
    resolve_organization,
)
from core.failure_classification import FaultClassifier
from core.failure_modes import CLASSIFICATION_SCHEMA, UNKNOWN_SYMPTOM, manual_category
from core.fault_components import (
    CATEGORY_FIELDS,
    COMPONENT_OVERRIDE,
    PART_CATEGORY_FIELDS,
    canonical_components,
    component_payload,
    parse_components,
    type_label,
)
from core.i18n import UNMATCHED, K
from core.models import (
    CLASSIFICATION_COMPONENT_COLUMNS,
    CLASSIFICATION_DECISION_COLUMNS,
    AnalysisOptions,
    LoadedData,
    Progress,
    UserError,
    noop_progress,
)
from core.parsing import (
    CLAUSE_END as CLAUSE_END,
)
from core.parsing import (
    ENDING_STOPWORDS as ENDING_STOPWORDS,
)
from core.parsing import (
    expand_endings as expand_endings,
)
from core.parsing import (
    is_missing as is_missing,
)
from core.parsing import (
    is_time_only as is_time_only,
)
from core.parsing import (
    normalize as normalize,
)
from core.parsing import (
    parse_date as parse_date,
)
from core.parsing import (
    parse_duration as parse_duration,
)
from core.parsing import (
    parse_stamp as parse_stamp,
)
from core.parsing import (
    prepare_text as prepare_text,
)
from core.parsing import (
    text as text,
)
from core.review_guidance import guidance

RECORD_COLUMNS = [
    "record_id",
    "event_id",
    "source_row",
    "source_sheet",
    "date",
    "start",
    "end",
    "minutes",
    "elapsed_minutes",
    "duration_delta",
    "duration_source",
    "kind",
    "line",
    "registered",
    "target",
    "family",
    "equipment",
    "equipment_basis",
    "line_code",
    "raw_line_name",
    "equipment_code",
    "raw_equipment_name",
    "report_equipment",
    "equipment_group",
    "factory",
    "team",
    "name_mapped",
    "product",
    "raw_description",
    "normalized",
    "raw_cause",
    "raw_action",
    "raw_big",
    "raw_mid",
    "raw_small",
    "major",
    "detail_equipment",
    "middle",
    "minor",
    "type",
    "status",
    "evidence",
    "candidates",
    "issues",
    "review_reason",
    "review_action",
    "aggregation_effect",
    "duplicate",
    *CLASSIFICATION_DECISION_COLUMNS,
    *CLASSIFICATION_COMPONENT_COLUMNS,
    "classification_candidates",
]


def normalized_name(value: Any, aliases: dict[str, str]) -> str:
    s = re.sub(r"\s+", " ", text(value)).strip()
    lookup = {normalize(k): str(v).strip() for k, v in aliases.items()}
    return lookup.get(normalize(s), s) or K["missing"]


def family_candidate(reported: str, description: str, families: list[dict]) -> str:
    # Prefer explicitly reported equipment. Free text is only a candidate, never an asset ID.
    for source in [reported, description] if reported else [description]:
        names = [r["name"] for r in families if re.search(r["pattern"], source, re.I)]
        if names:
            return " / ".join(dict.fromkeys(names))
    return K["unclassified"]


EVENT_FIELDS = (
    "line_id",
    "line_name",
    "equipment_id",
    "equipment_name",
    "start",
    "end",
    "work_date",
    "description",
    "kind",
    "code_big",
    "code_mid",
    "code_small",
    "duration",
    "product_name",
)


def event_id_for(raw: dict, mapping: dict) -> str:
    """Stable identity of one source record; manual corrections are keyed by it.

    Saved corrections depend on this exact formula: do not change fields or order.
    """
    payload = [text(raw.get(mapping.get(key, ""))) for key in EVENT_FIELDS]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def event_ids(loaded: LoadedData, mapping: dict) -> list[str]:
    """Record IDs of every source row under a given column mapping."""
    return [event_id_for(raw, mapping) for raw in loaded.frame.to_dict("records")]


def review_target(settings: dict, options: AnalysisOptions) -> bool:
    """A missing failure target only matters when equipment is grouped by target."""
    return (
        settings.get("target_missing_review", "target_basis") == "always"
        or options.equipment_basis == "target"
    )


def standardize(
    loaded: LoadedData, config: dict, options: AnalysisOptions, progress: Progress = noop_progress
) -> pd.DataFrame:
    m = loaded.mapping.copy()
    if not any(
        m.get(k) for k in ("equipment_id", "equipment_name", "line_name", "line_id", "code_mid")
    ):
        raise UserError(K["missing_equipment"])
    for key, column in m.items():
        if column is not None and column not in loaded.headers:
            raise UserError(
                f"{key}: \uceec\ub7fc\uc744 \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694."
            )
    settings = config["settings"]
    name_settings = normalize_name_settings(config.get("equipment_names", {"schema_version": 1}))
    name_source = effective_name_source(loaded, name_settings)
    name_mapping = active_name_mapping(loaded, name_settings)
    classifier = FaultClassifier(
        config["rules"],
        settings.get("classifier"),
        config.get("classification_catalog", {}).get("equipment_types"),
        config.get("classification_catalog", {}).get("public_taxonomy"),
    )
    target_review = review_target(settings, options)
    fault_labels = {normalize(v) for v in settings["fault_labels"]}
    rows = []
    for index, raw in enumerate(loaded.frame.to_dict("records")):

        def get(key):
            return raw.get(m.get(key, ""))

        issues = []
        original_kind = text(get("kind"))
        kind = original_kind or settings["kind_codes"].get(text(get("kind_code")), "")
        if normalize(kind) in fault_labels:
            kind = K["fault"]
        if not kind:
            if (
                not m.get("kind")
                and not m.get("kind_code")
                and settings.get("assume_generic_is_failure", False)
            ):
                kind = K["fault"]
                issues.append(K["kind_assumed"])
            else:
                kind = K["missing"]
                issues.append(K["no_kind"])
        dt = parse_date(get("work_date"))
        start = parse_stamp(get("start"), dt)
        end = parse_stamp(get("end"), dt)
        if pd.isna(dt) and not pd.isna(start):
            dt = start.normalize()
        if pd.isna(dt):
            issues.append(K["date_invalid"])
        elapsed = None
        if not pd.isna(start) and not pd.isna(end):
            if (
                end < start
                and is_time_only(get("start"))
                and is_time_only(get("end"))
                and settings.get("allow_time_only_overnight", False)
            ):
                end += timedelta(days=1)
                issues.append(K["overnight"])
            if end < start:
                issues.append(K["time_negative"])
            else:
                elapsed = (end - start).total_seconds() / 60
        supplied = parse_duration(get("duration"), options.duration_unit)
        minutes = supplied
        source = K["supplied"] if supplied is not None else K["unknown"]
        if supplied is None and not is_missing(get("duration")):
            issues.append(K["time_invalid"])
        if supplied is None and elapsed is not None:
            minutes = elapsed
            source = K["calculated"]
        if minutes is None:
            issues.append(K["time_missing"])
        delta = supplied - elapsed if supplied is not None and elapsed is not None else None
        if delta is not None and abs(delta) > float(settings["duration_tolerance_minutes"]):
            issues.append(K["time_diff"])
        line = normalized_name(get("line_name") or get("line_id"), {})
        # NaN is truthy: fall back explicitly rather than relying on Python's 'or'.
        if line == K["missing"]:
            line = normalized_name(get("line_id"), {})
        registered = normalized_name(get("equipment_name"), config["equipment_aliases"])
        line_code = text(get("line_id"))
        raw_line_name = text(get("line_name"))
        raw_equipment_name = text(get("equipment_name"))
        equipment_code = text(get("equipment_id"))
        report_equipment, name_mapped = resolve_name(
            line_code if name_source == "line" else equipment_code,
            raw_line_name if name_source == "line" else raw_equipment_name,
            name_mapping,
        )
        equipment_group = resolve_group(report_equipment, name_settings["grouping"])
        organization_code = (
            line_code or raw_line_name
            if name_source == "line"
            else equipment_code or raw_equipment_name
        )
        organization = resolve_organization(
            organization_code, raw_line_name, name_settings, source=name_source
        )
        factory, team = organization["factory"], organization["team"]
        team_equipment = f"{factory} / {team}" if factory != K["missing"] else team
        raw_mid = text(get("code_mid"))
        if loaded.profile == "mes_downtime_v1":
            target = (
                normalized_name(raw_mid, config["equipment_aliases"])
                if re.search(settings["equipment_prefix_pattern"], raw_mid)
                else K["target_missing"]
            )
            target_basis = K["raw_mid"] if target != K["target_missing"] else K["target_missing"]
        else:
            target = (
                normalized_name(raw_mid, config["equipment_aliases"])
                if raw_mid and m.get("code_mid") == "\uace0\uc7a5\ub300\uc0c1\uc124\ube44"
                else registered
            )
            target_basis = K["registered"] if target == registered else K["raw_mid"]
            if target == K["missing"]:
                target = K["target_missing"]
        description = text(get("description"))
        cause = text(get("cause"))
        action = text(get("action"))
        norm = prepare_text(description, config["normalization"])
        combined = prepare_text(
            " | ".join(v for v in (description, cause, action) if v), config["normalization"]
        )
        product = normalized_name(get("product_name"), config["product_aliases"])
        event_id = event_id_for(raw, m)
        override = config.get("overrides", {}).get(event_id, {})
        raw_small = text(get("code_small"))
        classification = (
            classifier.classify(
                combined,
                raw_small,
                prepare_text(raw_small, config["normalization"]),
                equipment_context=prepare_text(raw_mid, config["normalization"]),
                registered_equipment=prepare_text(raw_equipment_name, config["normalization"]),
            )
            if kind == K["fault"]
            else {
                "major": K["nonfault"],
                "detail_equipment": K["nonfault"],
                "middle": K["nonfault"],
                "minor": K["nonfault"],
                "status": K["nonfault"],
                "evidence": "",
                "candidates": "",
            }
        )
        review_code = classification.pop("review_code", "")
        for field in CLASSIFICATION_DECISION_COLUMNS:
            classification.setdefault(field, "")
        classification.setdefault("detail_equipment", "")
        classification.setdefault("classification_candidates", "[]")
        if classification["status"] == K["rule_unmatched"] and not raw_mid and not raw_small:
            # Without a rule match, only records whose downtime codes were never entered
            # are reported as missing codes; the rest point to a gap in the rules.
            classification.update(
                status=K["code_missing"],
                classification_reason="비가동코드(중·소)가 비어 있고 고장 설명과 일치하는 분류 규칙이 없습니다.",
            )
        # Older classifier snapshots and non-fault records have no component payload.
        if "component_details" not in classification:
            if kind != K["fault"]:
                classification.update(component_payload([], "nonfault"))
            elif classification["status"] in UNMATCHED:
                classification.update(component_payload([], "unclassified"))
            else:
                classification.update(
                    component_payload([{key: classification[key] for key in PART_CATEGORY_FIELDS}])
                )
        manual_components = None
        manual_current = False
        if override.get(COMPONENT_OVERRIDE):
            # A malformed saved multi-selection must never silently revert to an automatic type.
            stored_components = parse_components(override[COMPONENT_OVERRIDE], strict=True)
            manual_current = override.get("classification_schema") == CLASSIFICATION_SCHEMA and all(
                all(item.get(key) for key in CATEGORY_FIELDS) for item in stored_components
            )
            manual_components = [
                manual_category(item, override.get("classification_schema"))
                for item in stored_components
            ]
            manual_components = canonical_components(manual_components)
            if not manual_components:
                raise UserError("저장된 복수 고장 유형 목록이 비어 있습니다.")
        elif all(override.get(k) for k in PART_CATEGORY_FIELDS):
            manual_current = override.get("classification_schema") == CLASSIFICATION_SCHEMA and all(
                override.get(key) for key in CATEGORY_FIELDS
            )
            category = manual_category(
                {key: override[key] for key in CATEGORY_FIELDS if override.get(key)},
                override.get("classification_schema"),
            )
            manual_components = [category]
        if manual_components is not None:
            if (
                len(manual_components) == 1
                and manual_components[0]["minor"] != UNKNOWN_SYMPTOM
                and manual_current
                and all(manual_components[0].get(key) for key in CATEGORY_FIELDS)
            ):
                category = manual_components[0]
                classification.update({key: category[key] for key in CATEGORY_FIELDS})
                classification.update(
                    detail_equipment_source=K["manual"], detail_equipment_evidence="사용자 확정값"
                )
                classification.update(component_payload([category], "single"))
                classification.update(status=K["manual"], evidence=K["manual"], candidates="")
                classification.update({field: "" for field in CLASSIFICATION_DECISION_COLUMNS})
                classification["classification_reason"] = (
                    "사용자확정: 고장이력 한 건에 선택한 최종 분류 하나를 적용합니다."
                )
                review_code = ""
            else:
                reason = (
                    "이전에 저장된 복수 분류입니다. 후보를 확인한 뒤 최종 분류 하나를 선택하세요."
                    if len(manual_components) > 1
                    else (
                        "이전에 저장된 분류에 증상이 없습니다. 실제 증상을 확인해 최종 분류 하나를 선택하세요."
                        if manual_components[0]["minor"] == UNKNOWN_SYMPTOM
                        else "이전 기준으로 저장된 분류입니다. 새 부품·고장 현상 기준을 확인해 최종 분류를 다시 선택하세요."
                    )
                )
                candidates = rank_candidates(
                    [
                        *parse_candidates(classification.get("classification_candidates")),
                        *[
                            {
                                **item,
                                "reason": reason,
                                "evidence": item.get("evidence", "이전 사용자 저장값"),
                            }
                            for item in manual_components
                        ],
                    ]
                )
                classification.update(component_payload([], "ambiguous"))
                classification.update({key: "" for key in CATEGORY_FIELDS})
                classification.update(detail_equipment_source="", detail_equipment_evidence="")
                classification.update(
                    status=K["review"],
                    classification_reason=reason,
                    classification_candidates=json.dumps(candidates, ensure_ascii=False),
                    candidates=" | ".join(
                        f"{item['rank']}. {type_label(item)}" for item in candidates
                    ),
                    candidate_evidence="\n".join(
                        f"{item['rank']}. {type_label(item)}: {item.get('reason', '')}"
                        for item in candidates
                    ),
                )
                review_code = (
                    "multiple_faults"
                    if len(manual_components) > 1
                    else "symptom_missing"
                    if manual_components[0]["minor"] == UNKNOWN_SYMPTOM
                    else "legacy_equipment_missing"
                )
        classification["classification_schema"] = CLASSIFICATION_SCHEMA
        from core.classification_completeness import missing_fields_text

        classification["classification_missing_fields"] = (
            missing_fields_text(classification)
            if classification.get("status") in (K["auto"], K["manual"], K["partial"])
            else ""
        )
        from core.public_taxonomy import parse_repair_actions, part_group

        classification["part_group"] = part_group(classification.get("middle", ""))
        if "repair_actions" in override:
            classification["repair_actions"] = ", ".join(
                parse_repair_actions(override["repair_actions"])
            )
        else:
            classification.setdefault("repair_actions", "")
        if manual_components and manual_current and classification.get("status") == K["manual"]:
            category = {
                **manual_components[0],
                "part_group": classification["part_group"],
                "actions": parse_repair_actions(classification["repair_actions"]),
            }
            classification.update(component_payload([category], "single"))
        if override.get("product"):
            product = override["product"]
        if override.get("work_date"):
            new_date = parse_date(override["work_date"])
            if not pd.isna(new_date):
                dt = new_date.normalize()
                issues = [i for i in issues if i != K["date_invalid"]]
        if override.get("minutes") not in (None, ""):
            try:
                revised = float(override["minutes"])
                if math.isfinite(revised) and revised >= 0:
                    minutes = revised
                    source = K["manual"]
                    issues = [
                        i
                        for i in issues
                        if i not in (K["time_invalid"], K["time_missing"], K["time_diff"])
                    ]
            except (TypeError, ValueError):
                pass
        if override.get("target"):
            target = override["target"]
            target_basis = K["manual"]
        family = family_candidate(
            target if target != K["target_missing"] else "", combined, config["equipment_families"]
        )
        if kind == K["fault"]:
            if target == K["target_missing"]:
                issues.append(K["target_missing"])
            if not combined:
                issues.append(K["no_text"])
            if classification["status"] == K["review"]:
                issue_key = (
                    review_code
                    if review_code
                    in (
                        "multiple_faults",
                        "alternative_types",
                        "uncertain_fault",
                        "multiple_symptoms",
                        "symptom_missing",
                        "domain_missing",
                    )
                    and review_code in K
                    else "multi_rule"
                )
                issues.append(K[issue_key])
        equipment = {
            "mapped": report_equipment,
            "group": equipment_group,
            "factory": factory,
            "team": team_equipment,
            "registered": registered,
            "target": target,
            "family": family,
        }[options.equipment_basis]
        if options.equipment_basis == "target" and target == K["target_missing"]:
            equipment = f"{line} / {K['target_missing']}"
        source_row = int(raw["__source_row"])
        record = {
            "record_id": f"{loaded.file_hash[:16]}:{loaded.sheet}:{source_row}",
            "event_id": event_id,
            "source_row": source_row,
            "source_sheet": loaded.sheet,
            "date": dt.normalize() if not pd.isna(dt) else pd.NaT,
            "start": start,
            "end": end,
            "minutes": minutes,
            "elapsed_minutes": elapsed,
            "duration_delta": delta,
            "duration_source": source,
            "kind": kind,
            "line": line,
            "registered": registered,
            "target": target,
            "family": family,
            "equipment": equipment,
            "line_code": line_code,
            "raw_line_name": raw_line_name,
            "equipment_code": equipment_code,
            "raw_equipment_name": raw_equipment_name,
            "report_equipment": report_equipment,
            "equipment_group": equipment_group,
            "factory": factory,
            "team": team,
            "name_mapped": name_mapped,
            "equipment_basis": target_basis
            if options.equipment_basis == "target"
            else K[options.equipment_basis],
            "product": product,
            "raw_description": description,
            "normalized": norm,
            "raw_cause": cause,
            "raw_action": action,
            "raw_big": text(get("code_big")),
            "raw_mid": raw_mid,
            "raw_small": raw_small,
            **classification,
            "type": type_label(classification)
            if all(classification.get(k) for k in CATEGORY_FIELDS)
            else K["review"],
            "issues": " | ".join(dict.fromkeys(issues)),
            "duplicate": False,
        }
        reason, action, effect = guidance(record, target_review)
        record.update(review_reason=reason, review_action=action, aggregation_effect=effect)
        rows.append(record)
        if index % 200 == 0:
            progress(10 + int(65 * (index + 1) / max(1, len(loaded.frame))), K["processing"])
    result = pd.DataFrame(rows, columns=RECORD_COLUMNS)
    if not result.empty:
        code_column, raw_name_column = (
            ("line_code", "raw_line_name")
            if name_source == "line"
            else ("equipment_code", "raw_equipment_name")
        )
        identities = result[[code_column, raw_name_column, "report_equipment"]].copy()
        identities["_key"] = [
            code_key(c) or code_key(n)
            for c, n in zip(identities[code_column], identities[raw_name_column])
        ]
        identities["_display"] = identities.report_equipment.astype(str).str.casefold()
        clashes = identities.groupby("_display")["_key"].nunique()
        if (clashes > 1).any():
            raise UserError(
                "\uc11c\ub85c \ub2e4\ub978 \uc124\ube44 \ucf54\ub4dc\uac00 \uac19\uc740 \ud45c\uc2dc\uba85\uc73c\ub85c \ubcc0\ud658\ub429\ub2c8\ub2e4. \uc124\ube44\uba85 \ubcc0\ud658 \uc124\uc815\uc5d0\uc11c \uc774\ub984\uc744 \uad6c\ubd84\ud558\uc138\uc694."
            )
    for key in (
        "minutes",
        "elapsed_minutes",
        "duration_delta",
    ):
        result[key] = pd.to_numeric(result[key], errors="coerce")
    result["component_count"] = (
        pd.to_numeric(result["component_count"], errors="coerce").fillna(0).astype(int)
    )
    result["part_count"] = (
        pd.to_numeric(result["part_count"], errors="coerce").fillna(0).astype(int)
    )
    for key in ("date", "start", "end"):
        result[key] = pd.to_datetime(result[key], errors="coerce")
    if not result.empty:
        result["duplicate"] = result.duplicated("event_id", keep=False)
    return result
