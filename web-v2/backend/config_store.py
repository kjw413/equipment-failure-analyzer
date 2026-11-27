"""Use desktop equipment settings as defaults for the web profile."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from core.config import ConfigStore, atomic_json, resource_root, user_root
from core.equipment_names import (
    code_key,
    normalize_grouping,
    normalize_name_settings,
    normalize_organization,
    validate_names,
)
from core.models import UserError

NAMES_FILE = "equipment_names.json"
MAPPING_KEYS = {"line": "line_mappings", "equipment": "mappings"}


def desktop_names(path: Path) -> dict | None:
    try:
        return normalize_name_settings(json.loads(path.read_text(encoding="utf-8-sig")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UserError):
        logging.getLogger(__name__).warning("기존 프로그램의 명칭 설정을 읽을 수 없습니다.")
        return None


def merge_mapping(defaults: dict, overrides: dict) -> dict:
    overrides = validate_names(overrides)
    web_names = {code_key(name) for name in overrides.values()}
    merged = {}
    for code, name in defaults.items():
        name_key = code_key(name)
        # An inherited conversion must not merge assets explicitly named in the web UI.
        if code not in web_names and name_key not in web_names and name_key not in overrides:
            merged[code] = name
    return merged | overrides


def merge_organization(defaults: dict, overrides: dict) -> dict:
    merged = {}
    for source, assignments in defaults.items():
        merged[source] = assignments.copy()
        for code, fields in overrides[source].items():
            merged[source][code] = assignments.get(code, {}) | {
                field: value for field, value in fields.items() if value
            }
    return merged


def group_entries(overrides: dict) -> dict:
    return {code_key(name): (name, group) for name, group in overrides.items()}


def inherited_groups(defaults: dict, web: dict) -> dict:
    base = group_entries(defaults["grouping"]["overrides"])
    groups = base.copy()
    for key in MAPPING_KEYS.values():
        for code, name in web.get(key, {}).items():
            old_name = defaults[key].get(code)
            if old_name is not None and (entry := base.get(code_key(old_name))) is not None:
                groups.setdefault(code_key(name), (name, entry[1]))
    return groups


class WebConfigStore(ConfigStore):
    def __init__(self, directory: Path):
        super().__init__(directory)
        self.name_defaults = desktop_names(user_root() / "config" / NAMES_FILE)
        self.bundled_names = json.loads(
            (resource_root() / "config" / NAMES_FILE).read_text(encoding="utf-8-sig")
        )

    def _web_names(self, stored: dict) -> dict:
        # An untouched profile contains a copy of the packaged example settings.
        return {"schema_version": 1} if stored == self.bundled_names else stored.copy()

    def _effective_names(self, stored: dict) -> dict:
        web = self._web_names(stored)
        defaults = self.name_defaults
        web_grouping = web.get("grouping") or {}
        base_groups = inherited_groups(defaults, web)
        web_groups = group_entries(web_grouping.get("overrides", {}))
        return normalize_name_settings(
            {
                **defaults,
                **web,
                **{
                    key: merge_mapping(defaults[key], web.get(key, {}))
                    for key in MAPPING_KEYS.values()
                },
                "grouping": {
                    **defaults["grouping"],
                    **web_grouping,
                    "overrides": dict((base_groups | web_groups).values()),
                },
                "organization": merge_organization(
                    defaults["organization"], normalize_organization(web.get("organization"))
                ),
            }
        )

    def read(self, name: str):
        stored = super().read(name)
        if name == NAMES_FILE and self.name_defaults is not None:
            return self._effective_names(stored)
        return stored

    def save_equipment_names(
        self,
        mapping: dict[str, str],
        *,
        source: str = "equipment",
        grouping: dict | None = None,
        organization: dict | None = None,
    ) -> dict:
        defaults = self.name_defaults
        if defaults is None:
            return super().save_equipment_names(
                mapping, source=source, grouping=grouping, organization=organization
            )
        if source not in MAPPING_KEYS:
            raise UserError("설비명 변환 기준은 line 또는 equipment여야 합니다.")

        stored = super().read(NAMES_FILE)
        web = self._web_names(stored)
        key = MAPPING_KEYS[source]
        web[key] = {
            code: name
            for code, name in validate_names(mapping).items()
            if defaults[key].get(code) != name
        }
        if source == defaults["source"]:
            web.pop("source", None)
        else:
            web["source"] = source

        if grouping is not None:
            group = normalize_grouping(grouping)
            base_group = defaults["grouping"]
            base_entries = inherited_groups(defaults, web)
            group["overrides"] = {
                name: value
                for name, value in group["overrides"].items()
                if base_entries.get(code_key(name), ("", ""))[1] != value
            }
            if (group["mode"], group["separator"]) == (base_group["mode"], base_group["separator"]):
                del group["mode"], group["separator"]
            web["grouping"] = group

        if organization is not None:
            checked = normalize_organization(organization)
            saved = (web.get("organization") or {}).copy()
            for name_source in organization:
                base_assignments = defaults["organization"][name_source]
                saved[name_source] = {}
                for code, fields in checked[name_source].items():
                    base = base_assignments.get(code, {})
                    changed = {
                        field: value
                        for field, value in fields.items()
                        if value and base.get(field) != value
                    }
                    if changed:
                        saved[name_source][code] = changed
            web["organization"] = saved

        changed = stored != web
        if changed:
            web["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        effective = self._effective_names(web)
        if changed:
            atomic_json(self.config_dir / NAMES_FILE, web)
        return effective
