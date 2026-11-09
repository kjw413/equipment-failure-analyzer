from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import UserError
from version import APP_ID

CONFIG_FILES = [
    "settings.json",
    "column_mapping.json",
    "normalization.json",
    "equipment_aliases.json",
    "product_aliases.json",
    "equipment_families.json",
    "classification_config.xlsx",
    "classification_catalog.json",
    "equipment_names.json",
    "final_report.json",
]


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def app_root() -> Path:
    """The folder the user started the program from: the EXE's folder, or the project folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".efa_write_test_", dir=path)
        os.close(handle)
        Path(name).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def output_root() -> Path:
    """Default report folder: ./output next to the program. Falls back to the user
    data folder when the program folder is read-only (e.g. an EXE under Program Files)."""
    custom = os.environ.get("EFA_OUTPUT_DIR")
    preferred = Path(custom).expanduser().resolve() if custom else app_root() / "output"
    if writable_dir(preferred):
        return preferred
    fallback = user_root() / "output"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def user_root() -> Path:
    custom = os.environ.get("EFA_DATA_DIR")
    if custom:
        return Path(custom).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_ID
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID


def atomic_json(path: Path, value: Any, backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    handle, name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class ConfigStore:
    """Defaults are copied once. User rules and corrections survive upgrades."""

    def __init__(self, directory: Path | None = None):
        self.root = Path(directory) if directory else user_root()
        self.config_dir = self.root / "config"
        self.log_dir = self.root / "logs"
        for p in (self.config_dir, self.log_dir):
            p.mkdir(parents=True, exist_ok=True)
        for name in CONFIG_FILES:
            dest = self.config_dir / name
            if not dest.exists():
                shutil.copy2(resource_root() / "config" / name, dest)
        self.override_path = self.config_dir / "manual_overrides.json"
        if not self.override_path.exists():
            atomic_json(self.override_path, {}, backup=False)
        self.mapping_path = self.config_dir / "column_overrides.json"
        # Bring untouched defaults up to this release; the user's own edits are kept.
        from core.defaults_merge import merge_defaults

        self.merge_error = None
        try:
            self.merge_summary = merge_defaults(resource_root() / "config", self.config_dir)
        except Exception as exc:
            logging.getLogger(__name__).exception("Defaults merge failed")
            self.merge_summary = {}
            self.merge_error = exc
        # Older programs must not reinterpret the current part/symptom output schema.
        from core.rules import upgrade_rules_format

        try:
            if upgrade_rules_format(self.config_dir / "classification_config.xlsx"):
                self.merge_summary.setdefault("rules", {})["format_upgraded"] = 1
        except Exception:
            logging.getLogger(__name__).exception("Rules format upgrade failed")

    def read(self, name: str) -> Any:
        try:
            return json.loads((self.config_dir / name).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise UserError(f"\uc124\uc815 \ud30c\uc77c \ud655\uc778: {name}\n{e}") from e

    def load(self) -> dict[str, Any]:
        from core.rules import read_rules

        if self.merge_error is not None:
            raise UserError(f"분류 목록과 기본 설정 적용을 완료하지 못했습니다: {self.merge_error}")
        result = {Path(n).stem: self.read(n) for n in CONFIG_FILES if n.endswith(".json")}
        from core.classification_catalog import validate_catalog

        validate_catalog(result["classification_catalog"])
        from core.equipment_names import normalize_name_settings

        final_report = result["final_report"]
        if not isinstance(final_report, dict) or final_report.get("schema_version") != 1:
            raise UserError("final_report.json: unsupported schema")
        result["equipment_names"] = normalize_name_settings(result["equipment_names"])
        sections = result["settings"].get("report_sections", [])
        result["settings"]["report_sections"] = [key for key in sections if key != "product"]
        if "equipment_types" not in result["settings"]["report_sections"]:
            result["settings"]["report_sections"].append("equipment_types")
        result["settings"].setdefault("donut_top_n", 5)
        from core.review_colors import normalized_review_colors

        result["settings"]["review_colors"] = normalized_review_colors(
            result["settings"].get("review_colors")
        )
        engine = result["settings"].setdefault("classifier", {})
        if not isinstance(engine, dict):
            raise UserError("settings.json: classifier는 객체여야 합니다.")
        # Numeric thresholds from previous releases do not affect rule matching.
        engine.pop("scoring", None)
        result["rules"] = read_rules(self.config_dir / "classification_config.xlsx")
        result["overrides"] = self.read("manual_overrides.json")
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
        result["hash"] = hashlib.sha256(payload).hexdigest()
        return result

    def save_override(self, event_id: str, values: dict[str, str]) -> None:
        """Add correction values through the same field-update path as the editor."""
        self.update_override(
            event_id, {key: value for key, value in values.items() if value not in (None, "")}
        )

    def override(self, event_id: str) -> dict[str, str]:
        return dict(self.read("manual_overrides.json").get(event_id, {}))

    def update_override(self, event_id: str, patch: dict[str, str | None]) -> dict[str, str]:
        """Set (text) or remove (None) individual corrected fields of one record."""
        overrides = self.read("manual_overrides.json")
        current = {k: v for k, v in overrides.get(event_id, {}).items() if k != "saved_at"}
        from core.failure_modes import CLASSIFICATION_SCHEMA
        from core.fault_components import (
            CATEGORY_FIELDS,
            COMPONENT_OVERRIDE,
            combination_category,
            parse_components,
        )

        patch = dict(patch)
        if patch.get("classification_schema") not in (None, "", CLASSIFICATION_SCHEMA):
            raise UserError("지원하지 않는 분류 저장 형식입니다.")
        multiple = patch.get(COMPONENT_OVERRIDE)
        single_selection = any(str(patch.get(key) or "").strip() for key in CATEGORY_FIELDS)
        classification_changed = multiple not in (None, "") or single_selection
        if single_selection and current.get("classification_schema") != CLASSIFICATION_SCHEMA:
            if not all(str(patch.get(key) or "").strip() for key in CATEGORY_FIELDS):
                raise UserError("새 부품·증상 분류는 대·중·소분류를 모두 입력하세요.")
        if multiple not in (None, ""):
            if single_selection:
                raise UserError("단일 유형과 복수 유형을 동시에 확정할 수 없습니다.")
            members = parse_components(multiple, strict=True)
            combination_category(members)
            patch[COMPONENT_OVERRIDE] = json.dumps(
                [{key: member[key] for key in CATEGORY_FIELDS} for member in members],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for key in CATEGORY_FIELDS:
                current.pop(key, None)
        elif single_selection and current.get(COMPONENT_OVERRIDE):
            if not all(
                str(patch.get(key, current.get(key, "")) or "").strip() for key in CATEGORY_FIELDS
            ):
                raise UserError("단일 유형으로 바꾸려면 대·중·소분류를 모두 입력하세요.")
            current.pop(COMPONENT_OVERRIDE, None)
        for key, value in patch.items():
            if value is None or str(value).strip() == "":
                current.pop(key, None)
            else:
                current[key] = str(value).strip()
        has_classification = bool(current.get(COMPONENT_OVERRIDE)) or any(
            current.get(key) for key in CATEGORY_FIELDS
        )
        if classification_changed:
            current["classification_schema"] = CLASSIFICATION_SCHEMA
            current.pop("legacy_category", None)
        elif not has_classification:
            current.pop("classification_schema", None)
            current.pop("legacy_category", None)
        elif overrides.get(event_id, {}).get("classification_schema") == CLASSIFICATION_SCHEMA:
            # Editing a date/time must not turn a current classification into a
            # legacy unmarked triplet, even when an empty marker was submitted.
            current["classification_schema"] = CLASSIFICATION_SCHEMA
        if current:
            overrides[event_id] = {
                **current,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
            }
        else:
            overrides.pop(event_id, None)
        atomic_json(self.override_path, overrides)
        return current

    def clear_override(self, event_id: str) -> None:
        self.update_override(event_id, {key: None for key in self.override(event_id)})

    def rekey_overrides(self, moves: dict[str, str]) -> int:
        """Copy corrections to new record IDs after a column re-mapping. Old keys are kept."""
        overrides = self.read("manual_overrides.json")
        moved = 0
        for old, new in moves.items():
            if old != new and old in overrides and new not in overrides:
                overrides[new] = dict(overrides[old])
                moved += 1
        if moved:
            atomic_json(self.override_path, overrides)
        return moved

    @staticmethod
    def header_signature(headers: list[str]) -> str:
        return hashlib.sha256(
            json.dumps(list(headers), ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]

    def saved_mapping(self, headers: list[str]) -> dict[str, str | None] | None:
        """The column mapping the user last confirmed for a sheet with these exact headers."""
        if not self.mapping_path.exists():
            return None
        entry = self.read(self.mapping_path.name).get(self.header_signature(headers))
        return dict(entry["mapping"]) if entry else None

    def save_mapping(self, headers: list[str], mapping: dict[str, str | None]) -> None:
        saved = self.read(self.mapping_path.name) if self.mapping_path.exists() else {}
        saved[self.header_signature(headers)] = {
            "headers": list(headers),
            "mapping": dict(mapping),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        atomic_json(self.mapping_path, saved)

    def save_equipment_names(
        self,
        mapping: dict[str, str],
        *,
        source: str = "equipment",
        grouping: dict | None = None,
        organization: dict | None = None,
    ) -> dict:
        """Save the selected mapping while preserving the other source and metadata."""
        from core.equipment_names import (
            normalize_grouping,
            normalize_name_settings,
            normalize_organization,
            validate_names,
        )

        if source not in ("line", "equipment"):
            raise UserError("설비명 변환 기준은 line 또는 equipment여야 합니다.")
        checked = validate_names(mapping)
        current = self.read("equipment_names.json")
        value = normalize_name_settings(current)
        key = "line_mappings" if source == "line" else "mappings"
        value[key] = checked
        value["source"] = source
        if grouping is not None:
            value["grouping"] = normalize_grouping(grouping)
        if organization is not None:
            checked_organization = normalize_organization(organization)
            value["organization"] = {
                name_source: checked_organization[name_source]
                if name_source in organization
                else value["organization"][name_source]
                for name_source in ("line", "equipment")
            }
        if current == value:
            return current
        value["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        atomic_json(self.config_dir / "equipment_names.json", value)
        return value

    def save_report_settings(self, fields: dict[str, str]) -> None:
        value = self.read("final_report.json")
        limits = {"title": 100, "department": 120, "prepared_by": 80, "closing_note": 1600}
        for key, limit in limits.items():
            if key in fields:
                text = str(fields[key]).strip()
                if len(text) > limit:
                    raise UserError(f"{key}: maximum {limit} characters")
                value[key] = text
        atomic_json(self.config_dir / "final_report.json", value)

    def save_review_colors(self, colors: dict[str, str]) -> dict[str, str]:
        """Persist highlight choices without replacing other analysis settings."""
        from core.review_colors import normalized_review_colors, validate_review_colors

        checked = validate_review_colors(colors)
        value = self.read("settings.json")
        merged = normalized_review_colors(value.get("review_colors"))
        merged.update(checked)
        value["review_colors"] = merged
        atomic_json(self.config_dir / "settings.json", value)
        return merged
