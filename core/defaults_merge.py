"""Merge updated bundled defaults into an existing user profile.

The user's own edits always win. A bundled value the user never changed
follows the new release; a value the user changed or deleted stays as the user
left it. Every changed file is backed up first, and the run is idempotent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

HISTORY = "defaults_history.json"
STATE = ".defaults_state.json"
# Known spelling defects of earlier releases; fixed even in rules the user edited.
TYPO_FIXES = {"씌러": "씰러", "씌링": "씰링", "씬/오링": "씰/오링", "누설·씬": "누설·씰"}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def rule_digest(rule: dict) -> str:
    from core.rules import RULE_COLUMNS

    return digest({key: rule.get(key) for key in RULE_COLUMNS})


def fix_typos(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    for old, new in TYPO_FIXES.items():
        value = value.replace(old, new)
    return value


def merge_items(user: dict, bundled: dict, known: dict, same) -> tuple[dict, dict[str, int]]:
    """Three-way merge keyed by id/name. `known[key]` holds earlier bundled versions of that item."""
    result, counts = {}, {"added": 0, "updated": 0, "kept": 0, "removed": 0}
    for key, new in bundled.items():
        old = user.get(key)
        if old is None:
            if key in known:
                continue  # The user deleted a default: do not bring it back.
            result[key] = new
            counts["added"] += 1
        elif same(old, new):
            result[key] = old
        elif any(same(old, previous) for previous in known.get(key, ())):
            result[key] = new
            counts["updated"] += 1
        else:
            result[key] = old
            counts["kept"] += 1
    for key, old in user.items():
        if key in bundled:
            continue
        if any(same(old, previous) for previous in known.get(key, ())):
            counts["removed"] += 1  # A retired default the user never touched.
        else:
            result[key] = old
    return result, counts


def merge_named_defaults(user: list, bundled: list, previous: list) -> tuple[list, int]:
    """Three-way merge a named master list without reviving deleted choices."""
    old = {item["name"]: item for item in user}
    new = {item["name"]: item for item in bundled}
    known = {item["name"]: [item] for item in previous}
    merged, counts = merge_items(old, new, known, lambda a, b: a == b)
    order = [item["name"] for item in bundled if item["name"] in merged]
    order += [item["name"] for item in user if item["name"] not in new]
    return [merged[name] for name in order], counts["kept"]


def merge_public_taxonomy(user: dict, bundled: dict, previous: dict) -> tuple[dict, int]:
    """Update untouched public definitions, preserving edits and custom choices."""
    result = {**user, **bundled}
    kept = 0
    for section in ("domains", "modes", "actions"):
        old = {name: name for name in user.get(section, [])}
        new = {name: name for name in bundled.get(section, [])}
        known = {name: [name] for name in previous.get(section, [])}
        merged, counts = merge_items(old, new, known, lambda a, b: a == b)
        result[section] = list(merged)
        kept += counts["kept"]
    result["parts"], count = merge_named_defaults(
        user.get("parts", []), bundled.get("parts", []), previous.get("parts", [])
    )
    kept += count
    # Group members merge individually, so a custom member cannot prevent a
    # newly provided default equipment type from appearing in the same group.
    old_groups = {row["name"]: row for row in user.get("equipment_groups", [])}
    previous_groups = {row["name"]: row for row in previous.get("equipment_groups", [])}
    groups, count = merge_named_defaults(
        user.get("equipment_groups", []),
        bundled.get("equipment_groups", []),
        previous.get("equipment_groups", []),
    )
    kept += count
    new_groups = {row["name"]: row for row in bundled.get("equipment_groups", [])}
    for index, group in enumerate(groups):
        name = group["name"]
        if name not in old_groups or name not in previous_groups or name not in new_groups:
            continue
        old = {item: item for item in old_groups[name].get("items", [])}
        new = {item: item for item in new_groups[name].get("items", [])}
        known = {item: [item] for item in previous_groups[name].get("items", [])}
        merged, _ = merge_items(old, new, known, lambda a, b: a == b)
        groups[index] = {**group, "items": list(merged)}
    result["equipment_groups"] = groups
    return result, kept


class DefaultsMerger:
    def __init__(self, bundle_dir: Path, config_dir: Path):
        self.bundle_dir, self.config_dir = Path(bundle_dir), Path(config_dir)
        self.backup_dir = None
        history_path = self.bundle_dir / HISTORY
        self.history = (
            json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}
        )

    def known(self, section: str, state: dict) -> dict[str, list]:
        known = {key: list(values) for key, values in self.history.get(section, {}).items()}
        for key, value in state.get(section, {}).items():
            known.setdefault(key, []).append(value)
        return known

    def backup(self, name: str) -> None:
        if self.backup_dir is None:
            self.backup_dir = (
                self.config_dir / "backup" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            )
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        source = self.config_dir / name
        if source.exists():
            shutil.copy2(source, self.backup_dir / name)

    def write_json(self, name: str, value: Any) -> None:
        from core.config import atomic_json

        self.backup(name)
        atomic_json(self.config_dir / name, value, backup=False)

    def bundle_fingerprint(self) -> str:
        names = (
            "classification_config.xlsx",
            "classification_catalog.json",
            "normalization.json",
            "equipment_families.json",
            "settings.json",
            "column_mapping.json",
            HISTORY,
        )
        return digest(
            [
                hashlib.sha256((self.bundle_dir / n).read_bytes()).hexdigest()
                for n in names
                if (self.bundle_dir / n).exists()
            ]
        )

    def run(self) -> dict[str, dict[str, int]]:
        state_path = self.config_dir / STATE
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        fingerprint = self.bundle_fingerprint()
        if state.get("bundle") == fingerprint:
            return {}
        summary = {}
        new_state = {
            "bundle": fingerprint,
            "merged_at": datetime.now().isoformat(timespec="seconds"),
        }
        for section, method in (
            ("rules", self.rules),
            ("classification_catalog", self.classification_catalog),
            ("normalization", self.normalization),
            ("equipment_families", self.families),
            ("settings", self.settings),
            ("column_mapping", self.column_mapping),
        ):
            try:
                counts, applied = method(state)
            except Exception:
                logging.getLogger(__name__).exception("Defaults merge failed: %s", section)
                # Do not mark a failed migration complete or silently retain the old list.
                raise
            new_state[section] = applied
            if any(counts.values()):
                summary[section] = counts
        from core.config import atomic_json

        atomic_json(state_path, new_state, backup=False)
        if summary:
            logging.getLogger(__name__).info(
                "Defaults merged into %s: %s (backup %s)", self.config_dir, summary, self.backup_dir
            )
        return summary

    def rules(self, state: dict):
        from core.rules import read_rules, write_rules

        name = "classification_config.xlsx"
        bundled = {r["id"]: r for r in read_rules(self.bundle_dir / name)}
        user_rules = read_rules(self.config_dir / name)
        user = {r["id"]: r for r in user_rules}

        def same(a, b):
            # b is a rule or the stored digest of an earlier bundled rule.
            return (b if isinstance(b, str) else rule_digest(b)) == rule_digest(a)

        catalog_path = self.bundle_dir / "classification_catalog.json"
        catalog = None
        if catalog_path.exists():
            from core.classification_catalog import validate_catalog

            catalog = validate_catalog(json.loads(catalog_path.read_text(encoding="utf-8")))
        current_catalog_path = self.config_dir / "classification_catalog.json"
        current_catalog = (
            json.loads(current_catalog_path.read_text(encoding="utf-8-sig"))
            if current_catalog_path.exists()
            else {}
        )
        installed = bool(
            catalog is not None
            and current_catalog.get("installed_signature")
            and current_catalog.get("catalog_id") == catalog["catalog_id"]
        )
        transition = (
            catalog is not None
            and not installed
            and state.get("classification_catalog", {}).get("catalog_id") != catalog["catalog_id"]
        )
        if transition:
            # A new schema explicitly installs every provided choice once. Old IDs and
            # old default-deletion preferences do not identify the new physical types.
            merged = dict(bundled)
            counts = {
                "added": sum(key not in user for key in bundled),
                "updated": 0,
                "kept": 0,
                "removed": 0,
                "disabled": 0,
            }
            allowed = {
                tuple(row[k].strip() for k in ("major", "middle", "minor"))
                for row in catalog["categories"]
            }
            known = self.known("rules", state)
            for key, old in user.items():
                if key in bundled:
                    if same(old, bundled[key]):
                        continue
                    if any(same(old, previous) for previous in known.get(key, ())):
                        counts["updated"] += 1
                        continue
                elif any(same(old, previous) for previous in known.get(key, ())):
                    counts["removed"] += 1
                    continue
                # Keep custom patterns and user priorities; quarantine only paths
                # outside the new list instead of mixing legacy symptom labels in.
                preserved = dict(old)
                if tuple(old[k] for k in ("major", "middle", "minor")) not in allowed:
                    counts["disabled"] += int(bool(preserved["enabled"]))
                    preserved["enabled"] = False
                merged[key] = preserved
                counts["kept"] += 1
        else:
            known = self.known("rules", state)
            if installed:
                # A prior executable may replace its defaults cache, but it cannot
                # erase the installation marker or revive deleted catalogue types.
                previous_rules = current_catalog.get("installed_rules")
                if previous_rules is None:
                    # Support profiles installed before the durable rule snapshot.
                    prior_ids = {
                        "CAT_" + row["code"].replace("-", "_")
                        for row in current_catalog.get("categories", [])
                        if row.get("code")
                    }
                    previous_rules = {
                        key: rule_digest(rule) for key, rule in bundled.items() if key in prior_ids
                    }
                for key, previous in previous_rules.items():
                    known.setdefault(key, []).append(previous)
            merged, counts = merge_items(user, bundled, known, same)
        fixed = 0
        for key, rule in merged.items():
            repaired = {k: fix_typos(v) for k, v in rule.items()}
            if repaired != rule:
                merged[key] = repaired
                fixed += 1
        counts["typo_fixed"] = fixed
        ordered = [merged[r["id"]] for r in user_rules if r["id"] in merged]
        ordered += [rule for key, rule in merged.items() if key not in user]
        if ordered != user_rules:
            self.backup(name)
            write_rules(self.config_dir / name, ordered)
        return counts, {key: rule_digest(rule) for key, rule in bundled.items()}

    def classification_catalog(self, state: dict):
        """Install the authoritative list together with its migrated rule paths."""
        from core.classification_catalog import CATALOG_FILE, catalog_signature, validate_catalog
        from core.rules import read_rules

        path = self.bundle_dir / CATALOG_FILE
        if not path.exists():
            return {}, {}
        bundled = validate_catalog(json.loads(path.read_text(encoding="utf-8")))
        signature = catalog_signature(bundled)
        installed = {
            **bundled,
            "installed_signature": signature,
            "installed_rules": {
                rule["id"]: rule_digest(rule)
                for rule in read_rules(self.bundle_dir / "classification_config.xlsx")
            },
        }
        current = self.config_dir / CATALOG_FILE
        user = json.loads(current.read_text(encoding="utf-8-sig")) if current.exists() else None
        # Public choices are editable independently of the internal extraction
        # library. Keep a durable baseline in the catalogue itself: older apps
        # may rewrite .defaults_state.json but must not erase these edits.
        previous = state.get("classification_catalog", {})
        counts = {"updated": 0, "kept": 0}
        if user is not None:
            old_public = user.get("installed_public_taxonomy", previous.get("public_taxonomy"))
            if old_public is not None and "public_taxonomy" in user:
                installed["public_taxonomy"], kept = merge_public_taxonomy(
                    user["public_taxonomy"], bundled.get("public_taxonomy", {}), old_public
                )
                counts["kept"] += kept
            old_types = user.get(
                "installed_equipment_types",
                previous.get(
                    "equipment_types", self.history.get("classification_catalog.equipment_types")
                ),
            )
            if old_types is not None and "equipment_types" in user:
                installed["equipment_types"], kept = merge_named_defaults(
                    user["equipment_types"], bundled.get("equipment_types", []), old_types
                )
                counts["kept"] += kept
        if "public_taxonomy" in bundled:
            installed["installed_public_taxonomy"] = bundled["public_taxonomy"]
        if "equipment_types" in bundled:
            installed["installed_equipment_types"] = bundled["equipment_types"]
        changed = user != installed
        if changed:
            self.write_json(CATALOG_FILE, installed)
        counts["updated"] = int(changed)
        return counts, {
            "signature": signature,
            "catalog_id": bundled["catalog_id"],
            "public_taxonomy": bundled.get("public_taxonomy", {}),
            "equipment_types": bundled.get("equipment_types", []),
        }

    def normalization(self, state: dict):
        name = "normalization.json"
        bundled = json.loads((self.bundle_dir / name).read_text(encoding="utf-8"))
        user = json.loads((self.config_dir / name).read_text(encoding="utf-8-sig"))
        known_state = state.get("normalization", {})
        result = dict(user)
        counts = {"added": 0, "updated": 0, "kept": 0, "removed": 0}
        applied = {}
        for section in ("replacements", "clause_end_expansions"):
            known = {
                k: list(v) for k, v in self.history.get(f"normalization.{section}", {}).items()
            }
            for key, value in known_state.get(section, {}).items():
                known.setdefault(key, []).append(value)
            merged, part = merge_items(
                user.get(section, {}), bundled.get(section, {}), known, lambda a, b: a == b
            )
            result[section] = merged
            applied[section] = bundled.get(section, {})
            for k, v in part.items():
                counts[k] += v
        result["comment"] = bundled.get("comment", user.get("comment", ""))
        if result != user:
            self.write_json(name, result)
        return counts, applied

    def families(self, state: dict):
        name = "equipment_families.json"
        bundled_list = json.loads((self.bundle_dir / name).read_text(encoding="utf-8"))
        user_list = json.loads((self.config_dir / name).read_text(encoding="utf-8-sig"))
        bundled = {item["name"]: item["pattern"] for item in bundled_list}
        user = {item["name"]: item["pattern"] for item in user_list}
        known = self.known("equipment_families", state)
        merged, counts = merge_items(user, bundled, known, lambda a, b: a == b)
        if merged != user:
            order = [item["name"] for item in user_list if item["name"] in merged] + [
                n for n in merged if n not in user
            ]
            self.write_json(name, [{"name": n, "pattern": merged[n]} for n in order])
        return counts, bundled

    def settings(self, state: dict):
        name = "settings.json"
        bundled = json.loads((self.bundle_dir / name).read_text(encoding="utf-8"))
        user = json.loads((self.config_dir / name).read_text(encoding="utf-8-sig"))
        known = self.known("settings", state)
        result = dict(user)
        counts = {"added": 0, "updated": 0, "kept": 0, "removed": 0}
        for key, value in bundled.items():
            if key not in user:
                result[key] = value
                counts["added"] += 1
            elif user[key] == value:
                continue
            elif isinstance(value, dict) and isinstance(user[key], dict):
                nested = {**value, **user[key]}  # New sub-settings only; the user's choices stay.
                if nested != user[key]:
                    result[key] = nested
                    counts["added"] += 1
            elif user[key] in known.get(key, ()):
                result[key] = value
                counts["updated"] += 1
            else:
                counts["kept"] += 1
        if result != user:
            self.write_json(name, result)
        return counts, {
            key: value for key, value in bundled.items() if not isinstance(value, (dict, list))
        }

    def column_mapping(self, state: dict):
        name = "column_mapping.json"
        bundled = json.loads((self.bundle_dir / name).read_text(encoding="utf-8"))
        user = json.loads((self.config_dir / name).read_text(encoding="utf-8-sig"))
        result = {key: list(values) for key, values in user.items()}
        counts = {"added": 0, "updated": 0, "kept": 0, "removed": 0}
        for key, aliases in bundled.items():
            current = result.setdefault(key, [])
            for alias in aliases:
                if alias not in current:
                    current.append(alias)
                    counts["added"] += 1
        if result != user:
            self.write_json(name, result)
        return counts, {}


def merge_defaults(bundle_dir: Path, config_dir: Path) -> dict[str, dict[str, int]]:
    return DefaultsMerger(bundle_dir, config_dir).run()


def describe(summary: dict[str, dict[str, int]]) -> str:
    """One status line for the GUI; empty when nothing changed."""
    labels = {
        "rules": "분류 규칙",
        "classification_catalog": "분류 목록",
        "normalization": "표기 정규화",
        "equipment_families": "설비군",
        "settings": "설정",
        "column_mapping": "컬럼 별칭",
    }
    parts = []
    for section, counts in summary.items():
        details = ", ".join(
            f"{label} {counts[key]}"
            for key, label in (
                ("added", "추가"),
                ("updated", "갱신"),
                ("kept", "사용자 수정 보존"),
                ("removed", "폐기"),
                ("disabled", "이전 사용자 규칙 비활성 보존"),
                ("typo_fixed", "오타 수정"),
            )
            if counts.get(key)
        )
        if counts.get("format_upgraded"):
            details = ", ".join(filter(None, (details, "구버전 실행 차단 형식 적용")))
        if details:
            parts.append(f"{labels.get(section, section)}({details})")
    return "기본 설정 업데이트: " + " / ".join(parts) if parts else ""
