"""Exact, persistent line/equipment code names and configured equipment groups.

This is separate from equipment_aliases (free-text spelling normalization).
An alias never changes the original workbook or an event's stable identity.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from core.i18n import K
from core.models import LoadedData, UserError
from core.parsing import text as clean_text


def code_key(value: Any) -> str:
    """Normalize casing/outer whitespace, never use substring matching."""
    return unicodedata.normalize("NFKC", clean_text(value)).strip().upper()


def validate_names(mapping: dict[str, str]) -> dict[str, str]:
    if not isinstance(mapping, dict):
        raise UserError(
            "\uc124\ube44\uba85 \uc124\uc815 \ud615\uc2dd\uc744 \ud655\uc778\ud558\uc138\uc694."
        )
    checked: dict[str, str] = {}
    used_names: dict[str, str] = {}
    for original, value in mapping.items():
        if not isinstance(original, str) or not isinstance(value, str):
            raise UserError(
                "\uc124\ube44 \ucf54\ub4dc\uc640 \ud45c\uc2dc\uba85\uc740 \ubb38\uc790\uc5f4\uc774\uc5b4\uc57c \ud569\ub2c8\ub2e4."
            )
        key, name = code_key(original), value.strip()
        if not key:
            if name:
                raise UserError(
                    "\ud45c\uc2dc\uba85\uc5d0 \ub300\ud55c \uc124\ube44 \ucf54\ub4dc\ub97c \uc785\ub825\ud558\uc138\uc694."
                )
            continue
        if len(key) > 200 or len(name) > 120 or re.search(r"[\x00-\x1f\x7f]", key + name):
            raise UserError(
                "\uc124\ube44 \ucf54\ub4dc/\uc774\ub984\uc758 \uae38\uc774 \ub610\ub294 \uc904\ubc14\uafc8\uc744 \ud655\uc778\ud558\uc138\uc694."
            )
        if not name:
            continue  # Clearing the name removes the conversion, not source data.
        if key in checked:
            raise UserError(f"\uc124\ube44 \ucf54\ub4dc \uc911\ubcf5: {key}")
        name_key = unicodedata.normalize("NFKC", name).casefold()
        if name_key in used_names and used_names[name_key] != key:
            raise UserError(
                f"\uc11c\ub85c \ub2e4\ub978 \ucf54\ub4dc\uc5d0 \uac19\uc740 \uc774\ub984\uc744 \uc9c0\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4: {name}\n"
                "\uc124\ube44\ubcc4 \uc9d1\uacc4 \ud63c\uc120\uc744 \ub9c9\uae30 \uc704\ud574 \uad6c\ubd84\ud574 \uc785\ub825\ud558\uc138\uc694."
            )
        checked[key] = name
        used_names[name_key] = key
    # A display name identical to a different raw code would silently merge assets.
    for key, name in checked.items():
        if code_key(name) in checked and code_key(name) != key:
            raise UserError(
                f"\ub2e4\ub978 \uc124\ube44 \ucf54\ub4dc\uc640 \uac19\uc740 \ud45c\uc2dc\uba85: {name}"
            )
    return checked


def normalize_grouping(value=None) -> dict:
    """Validate grouping independently: several names may share one group."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise UserError("설비그룹 설정은 객체여야 합니다.")
    mode = value.get("mode", "prefix")
    separator = value.get("separator", "#")
    if mode not in ("prefix", "none"):
        raise UserError("설비그룹 방식은 prefix 또는 none이어야 합니다.")
    if (
        not isinstance(separator, str)
        or len(separator) > 30
        or re.search(r"[\x00-\x1f\x7f]", separator)
        or (mode == "prefix" and not separator.strip())
    ):
        raise UserError("설비그룹 구분자를 확인하세요.")
    overrides = value.get("overrides", {})
    if not isinstance(overrides, dict):
        raise UserError("설비그룹 지정값은 이름별 그룹이어야 합니다.")
    checked, used = {}, set()
    for name, group in overrides.items():
        if not isinstance(name, str) or not isinstance(group, str):
            raise UserError("설비명과 설비그룹은 문자열이어야 합니다.")
        name, group = name.strip(), group.strip()
        if (
            not name
            or len(name) > 120
            or len(group) > 120
            or re.search(r"[\x00-\x1f\x7f]", name + group)
        ):
            raise UserError("설비명/설비그룹의 길이 또는 줄바꿈을 확인하세요.")
        if not group:
            continue
        key = code_key(name)
        if key in used:
            raise UserError(f"설비그룹 지정 중복: {name}")
        checked[name] = group
        used.add(key)
    return dict(value, mode=mode, separator=separator, overrides=checked)


def extract_factory(raw_line_name: Any) -> str:
    """Use the first nonempty [factory] in the original line name."""
    for match in re.finditer(r"\[([^\[\]]*)\]", clean_text(raw_line_name)):
        factory = re.sub(r"\s+", " ", match.group(1)).strip()
        if factory:
            return factory
    return ""


def normalize_organization(value=None) -> dict[str, dict[str, dict[str, str]]]:
    """Validate manual factory/team assignments independently for each code source."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise UserError("공장/팀 설정은 객체여야 합니다.")
    if any(source not in ("line", "equipment") for source in value):
        raise UserError("공장/팀 설정 기준은 line 또는 equipment여야 합니다.")
    result = {}
    for source in ("line", "equipment"):
        assignments = value.get(source, {})
        if not isinstance(assignments, dict):
            raise UserError("공장/팀 설정은 코드별 지정값이어야 합니다.")
        checked = {}
        for original, fields in assignments.items():
            if not isinstance(original, str) or not isinstance(fields, dict):
                raise UserError("공장/팀 코드는 문자열이고 지정값은 객체여야 합니다.")
            code = code_key(original)
            if not code or len(code) > 200 or re.search(r"[\x00-\x1f\x7f]", code):
                raise UserError("공장/팀 지정 코드의 길이 또는 줄바꿈을 확인하세요.")
            entry = {}
            for field, label in (("factory", "공장"), ("team", "팀")):
                text = fields.get(field, "")
                if not isinstance(text, str):
                    raise UserError(f"{label} 이름은 문자열이어야 합니다.")
                text = text.strip()
                if len(text) > 120 or re.search(r"[\x00-\x1f\x7f]", text):
                    raise UserError(f"{label} 이름의 길이 또는 줄바꿈을 확인하세요.")
                entry[field] = text
            if not any(entry.values()):
                continue
            if code in checked:
                raise UserError(f"공장/팀 지정 코드 중복: {code}")
            checked[code] = entry
        result[source] = checked
    return result


def resolve_organization(
    code: Any, raw_line_name: Any, settings: dict, source: str = "line"
) -> dict[str, str]:
    """Manual assignments win; automatic factory data always uses the source line name."""
    if source not in ("line", "equipment"):
        raise UserError("공장/팀 설정 기준은 line 또는 equipment여야 합니다.")
    names = settings.get("equipment_names", settings)
    organization = normalize_organization(names.get("organization"))
    return _organization_values(code, raw_line_name, organization[source])


def _organization_values(code, raw_line_name, assignments) -> dict[str, str]:
    entry = assignments.get(code_key(code), {})
    return {
        "factory": entry.get("factory") or extract_factory(raw_line_name) or K["missing"],
        "team": entry.get("team") or K["missing"],
    }


def organization_filter_choices(
    loaded: LoadedData | None, settings: dict, factory: str | None = None
) -> dict[str, list[str]]:
    """Resolve source organization choices before classification, with a factory cascade."""
    if loaded is None:
        return {"factories": [], "teams": []}
    names = settings.get("equipment_names", settings)
    source = effective_name_source(loaded, names)
    assignments = normalize_organization(names.get("organization"))[source]
    id_column = loaded.mapping.get(source + "_id")
    name_column = loaded.mapping.get(source + "_name")
    line_name_column = loaded.mapping.get("line_name")
    factories, teams = set(), set()
    resolved = {}
    for record in loaded.frame.to_dict("records"):
        code = code_key(record.get(id_column)) or code_key(record.get(name_column))
        raw_line_name = clean_text(record.get(line_name_column))
        identity = (code, raw_line_name)
        if identity not in resolved:
            resolved[identity] = _organization_values(code, raw_line_name, assignments)
        organization = resolved[identity]
        factories.add(organization["factory"])
        if factory is None or organization["factory"] == factory:
            teams.add(organization["team"])
    return {"factories": sorted(factories), "teams": sorted(teams)}


def organization_catalog(
    loaded: LoadedData | None, source: str = "line"
) -> dict[str, dict[str, str]]:
    """Offer an automatic factory preview only when a code has one parsed factory."""
    if loaded is None:
        return {}
    if source not in ("line", "equipment"):
        raise UserError("공장/팀 설정 기준은 line 또는 equipment여야 합니다.")
    id_column = loaded.mapping.get(source + "_id")
    name_column = loaded.mapping.get(source + "_name")
    line_name_column = loaded.mapping.get("line_name")
    factories = {}
    for record in loaded.frame.to_dict("records"):
        code = code_key(record.get(id_column)) or code_key(record.get(name_column))
        if not code:
            continue
        candidates = factories.setdefault(code, set())
        factory = extract_factory(record.get(line_name_column))
        if factory:
            candidates.add(factory)
    return {
        code: {"factory": next(iter(values)) if len(values) == 1 else "", "team": ""}
        for code, values in sorted(factories.items())
    }


def normalize_name_settings(value) -> dict:
    """Upgrade schema-1 metadata without reinterpreting equipment-code mappings."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise UserError("equipment_names.json: unsupported schema")
    source = value.get("source", "line")
    if source not in ("line", "equipment"):
        raise UserError("설비명 변환 기준은 line 또는 equipment여야 합니다.")
    return dict(
        value,
        source=source,
        mappings=validate_names(value.get("mappings", {})),
        line_mappings=validate_names(value.get("line_mappings", {})),
        grouping=normalize_grouping(value.get("grouping")),
        organization=normalize_organization(value.get("organization")),
    )


def effective_name_source(loaded: LoadedData | None, settings: dict) -> str:
    """Fallback to equipment only when the file has no mapped line columns."""
    names = settings.get("equipment_names", settings)
    source = names.get("source", "line")
    if source not in ("line", "equipment"):
        raise UserError("설비명 변환 기준은 line 또는 equipment여야 합니다.")
    if source == "line" and loaded is not None:
        if not any(
            loaded.mapping.get(field) in loaded.headers
            for field in ("line_id", "line_name")
            if loaded.mapping.get(field)
        ):
            return "equipment"
    return source


def active_name_mapping(loaded: LoadedData | None, settings: dict) -> dict[str, str]:
    names = settings.get("equipment_names", settings)
    key = "line_mappings" if effective_name_source(loaded, names) == "line" else "mappings"
    return names.get(key, {})


def resolve_group(name: Any, grouping: dict | None = None) -> str:
    """Explicit assignments win; otherwise split converted names at the separator."""
    value = normalize_grouping(grouping)
    name = clean_text(name) or "미기재"
    key = code_key(name)
    for original, group in value["overrides"].items():
        if code_key(original) == key:
            return group
    if value["mode"] == "prefix" and value["separator"] in name:
        return name.split(value["separator"], 1)[0].strip() or name
    return name


def resolve_name(code: Any, raw_name: Any, mapping: dict[str, str]) -> tuple[str, bool]:
    key = code_key(code)
    if key and key in mapping:
        return mapping[key], True
    # Unknown assets stay recognizable and separate: do not guess a friendly name.
    fallback = key or clean_text(raw_name) or "\ubbf8\uae30\uc7ac"
    if not key and code_key(raw_name) in mapping:
        return mapping[code_key(raw_name)], True
    return fallback, False


def equipment_catalog(loaded: LoadedData | None, source: str = "equipment") -> list[dict[str, str]]:
    """Unique source codes with original names for the editor's reference column."""
    if loaded is None:
        return []
    if source not in ("line", "equipment"):
        raise UserError("설비명 변환 기준은 line 또는 equipment여야 합니다.")
    id_column = loaded.mapping.get(source + "_id")
    name_column = loaded.mapping.get(source + "_name")
    catalog: dict[str, dict] = {}
    for record in loaded.frame.to_dict("records"):
        code = clean_text(record.get(id_column)) if id_column else ""
        raw_name = clean_text(record.get(name_column)) if name_column else ""
        code = code or raw_name
        if not code:
            continue
        key = code_key(code)
        item = catalog.setdefault(key, {"code": key, "raw_names": set()})
        if raw_name:
            item["raw_names"].add(raw_name)
    return [
        {"code": key, "raw_name": " / ".join(sorted(v["raw_names"]))}
        for key, v in sorted(catalog.items())
    ]
