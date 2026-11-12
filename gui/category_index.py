"""Immutable lookup tables for the four classification menus."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core.failure_modes import UNKNOWN_SYMPTOM

CategoryPath = tuple[str, str, str, str]


@dataclass(frozen=True, init=False, repr=False)
class ClassificationPathIndex(Sequence):
    """Build once per catalog; choosing a menu never scans all complete paths."""

    paths: tuple[CategoryPath, ...]
    _equipment_choices: tuple[str, ...]
    _major_choices: tuple[str, ...]
    _part_choices: tuple[str, ...]
    _symptom_choices: tuple[str, ...]

    def __init__(self, categories):
        excluded = {
            UNKNOWN_SYMPTOM,
            "증상 미기재",
            "현상 미기재",
            "교체",
            "수리·정비",
            "조정",
            "점검",
            "청소·급유",
            "체결·조립",
            "리셋·재가동",
        }
        paths = tuple(tuple(path) for path in categories if path[-1] not in excluded)
        majors, parts, symptoms, equipment = set(), set(), set(), set()
        for path in paths:
            major, detail_equipment, part, symptom = path
            equipment.add(detail_equipment)
            majors.add(major)
            parts.add(part)
            symptoms.add(symptom)
        object.__setattr__(self, "paths", paths)

        def ordered(values):
            return tuple(sorted(values, key=lambda value: (value.casefold(), value)))

        object.__setattr__(self, "_equipment_choices", ordered(equipment))
        object.__setattr__(self, "_major_choices", ordered(majors))
        object.__setattr__(self, "_part_choices", ordered(parts))
        object.__setattr__(self, "_symptom_choices", ordered(symptoms))

    def __getitem__(self, key):
        return self.paths[key]

    def __repr__(self):
        return f"ClassificationPathIndex({len(self.paths):,} paths)"

    def __len__(self):
        return len(self.paths)

    def __contains__(self, path):
        path = tuple(path)
        return (
            len(path) == 4
            and path[0] in self._major_choices
            and path[1] in self._equipment_choices
            and path[2] in self._part_choices
            and path[3] in self._symptom_choices
        )

    def choices(self, prefix: tuple[str, ...]) -> tuple[str, ...]:
        if not self.has_prefix(prefix):
            return ()
        if not prefix:
            return self._major_choices
        if len(prefix) == 1:
            return self._equipment_choices
        if len(prefix) == 2:
            return self._part_choices
        return self._symptom_choices if len(prefix) == 3 else ()

    def has_prefix(self, prefix: tuple[str, ...]) -> bool:
        if not prefix:
            return bool(self.paths)
        if prefix[0] not in self._major_choices:
            return False
        if len(prefix) > 1 and prefix[1] not in self._equipment_choices:
            return False
        if len(prefix) > 2 and prefix[2] not in self._part_choices:
            return False
        return len(prefix) < 4 or prefix in self

    def menu_choices(self, field: str, selected: Mapping[str, str]) -> tuple[str, ...]:
        """All four semantic dimensions are independent, including failure phenomena."""
        if field == "major":
            return self.choices(())
        if field == "detail_equipment":
            return self._equipment_choices
        if field == "middle":
            return self._part_choices
        if field == "minor":
            return self._symptom_choices
        return ()

    @staticmethod
    def menu_enabled(field: str, selected: Mapping[str, str]) -> bool:
        return field in ("major", "detail_equipment", "middle", "minor")

    @staticmethod
    def menu_context_matches(
        field: str, path: tuple[str, ...], selected: Mapping[str, str]
    ) -> bool:
        return True

    def changed_selection(
        self, selected: Mapping[str, str], field: str, value: str
    ) -> dict[str, str]:
        result = dict(selected)
        result[field] = value
        return result

    def matches(self, selected: tuple[str, ...]) -> bool:
        """Complete paths and contiguous partial selections use constant-time lookup."""
        major, equipment, part, symptom = selected
        if equipment and equipment not in self._equipment_choices:
            return False
        if major and major not in self._major_choices:
            return False
        return (not part or part in self._part_choices) and (
            not symptom or symptom in self._symptom_choices
        )


def category_index(categories) -> ClassificationPathIndex:
    return (
        categories
        if isinstance(categories, ClassificationPathIndex)
        else ClassificationPathIndex(categories)
    )
