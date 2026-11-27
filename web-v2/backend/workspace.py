"""Private, single-user analysis state for the browser application."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, replace
from pathlib import Path, PureWindowsPath
from threading import RLock
from typing import BinaryIO

import pandas as pd
from config_store import WebConfigStore

from core.aggregation import grouped
from core.classification_candidates import parse_candidates
from core.classification_catalog import equipment_classification_categories
from core.corrections import FIELDS, correction_patch, initial_values, validate
from core.equipment_breakdown import type_breakdown
from core.equipment_names import (
    equipment_catalog,
    organization_catalog,
    organization_filter_choices,
)
from core.excel_loader import SUPPORTED, load_excel
from core.fault_components import CATEGORY_FIELDS, COMPONENT_OVERRIDE, PUBLIC_CATEGORY_FIELDS
from core.i18n import DISPLAY, FIELD_LABELS, K
from core.models import AnalysisOptions, AnalysisResult, LoadedData, UserError
from core.preprocessing import event_ids, review_target
from core.public_taxonomy import REPAIR_ACTIONS
from core.review_colors import REVIEW_TYPES, review_types
from core.rules import RULE_COLUMNS, write_rules
from core.service import run_analysis

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
CLASSIFICATION_FIELDS = {*CATEGORY_FIELDS, COMPONENT_OVERRIDE}
EDIT_FIELDS = set(FIELDS) - {"middle", COMPONENT_OVERRIDE}

TABLE_LABELS = {
    "raw": "원본 데이터",
    "factory": "공장별 분석",
    "team": "팀별 분석",
    "equipment": "설비별 분석",
    "line": "라인별 분석",
    "type": "유형별 분석",
    "product": "제품별 분석",
    "detailed_equipment": "상세설비별 분석",
    "equipment_types": "설비별 고장 유형",
    "detail": "고장이력",
    "review": "검토 필요",
    "triple": "설비·제품·유형 교차분석",
    "equipment_type": "설비·유형 교차분석",
    "equipment_product": "설비·제품 교차분석",
    "product_type": "제품·유형 교차분석",
    "raw_kind": "비가동 유형",
    "combination": "복수 고장",
    "long_stops": "장시간 정지",
    "trend_day": "일별 추이",
    "trend_week": "주별 추이",
    "trend_month": "월별 추이",
    "trend_year": "연도별 추이",
}
EXTRA_LABELS = {
    "__source_row": "원본 행",
    "rank": "순위",
    "asset": "라인",
    "family": "설비군",
    "module": "상세설비",
    "symptom": "고장 현상",
    "review_count": "검토 건수",
}
DETAIL_COLUMNS = (
    "date",
    "line",
    "equipment",
    "major",
    "detail_equipment",
    "minor",
    "normalized",
    "raw_description",
    "minutes",
    "status",
    "repair_actions",
    "source_row",
    "factory",
    "team",
    "target",
    "product",
    "review_reason",
    "review_action",
    "aggregation_effect",
    "classification_reason",
)
HIDDEN_COLUMNS = {
    "event_id",
    "record_id",
    "classification_schema",
    "component_details",
    "classification_candidates",
    "classification_known_fields",
    "combination_key",
}


def records(frame: pd.DataFrame) -> list[dict]:
    """Serialize spreadsheet dates and unavailable values as JSON-compatible values."""
    return json.loads(
        frame.to_json(orient="records", date_format="iso", force_ascii=False, double_precision=15)
    )


def table_payload(frame: pd.DataFrame, total: int | None = None, *, raw=False) -> dict:
    labels = [
        {
            "key": column,
            "label": column
            if raw and column != "__source_row"
            else EXTRA_LABELS.get(column, DISPLAY.get(column, K.get(column, column))),
        }
        for column in frame.columns
        if raw or column not in HIDDEN_COLUMNS
    ]
    return {
        "columns": labels,
        "rows": records(frame),
        "total": len(frame) if total is None else total,
    }


class Workspace:
    def __init__(self, data_directory: Path):
        self.store = WebConfigStore(data_directory)
        self.lock = RLock()
        self.upload: tempfile.TemporaryDirectory | None = None
        self.loaded: LoadedData | None = None
        self.result: AnalysisResult | None = None
        self.organizations: dict = {}
        self.pending: dict[str, dict[str, str | None]] = {}
        self.current_ids: set[str] = set()
        self._equipment_types: pd.DataFrame | None = None

    def reset(self) -> None:
        if self.upload is not None:
            self.upload.cleanup()
        self.upload = None
        self.loaded = None
        self.result = None
        self.organizations = {}
        self.current_ids.clear()
        self.pending.clear()
        self._equipment_types = None

    def require_source(self) -> LoadedData:
        if self.loaded is None:
            raise UserError("먼저 Excel 고장이력 파일을 올려주세요.")
        return self.loaded

    def require_result(self) -> AnalysisResult:
        if self.result is None:
            raise UserError("먼저 분석을 실행해주세요.")
        return self.result

    def _read_source(self, path: Path, sheet=None, header_row=None) -> LoadedData:
        return load_excel(
            path,
            self.store.read("column_mapping.json"),
            sheet,
            header_row,
            mapping_lookup=self.store.saved_mapping,
        )

    def load_source(self, path: Path, *, upload: tempfile.TemporaryDirectory | None = None) -> None:
        loaded = self._read_source(path)
        organizations = self._organization_choices(loaded)
        self.reset()
        self.upload = upload
        self.loaded = loaded
        self.organizations = organizations

    def upload_source(self, name: str, stream: BinaryIO) -> dict:
        # Browser clients may send Windows paths even when the server runs on Linux.
        basename = name.replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(basename).suffix.casefold()
        if suffix not in SUPPORTED:
            raise UserError(K["unsupported"])
        if basename.startswith("~$"):
            raise UserError("Excel 임시 파일 대신 원본 파일을 올려주세요.")
        # Keep the source's display name where possible, using a private directory per file.
        safe_name = "".join(
            ch if ch not in '<>:"/\\|?*' and ord(ch) >= 32 else "_" for ch in basename
        )
        if len(safe_name) > 170:
            safe_name = safe_name[: 170 - len(suffix)] + suffix
        if PureWindowsPath(safe_name).is_reserved():
            safe_name = "_" + safe_name
        directory = tempfile.TemporaryDirectory(prefix="efa-upload-", dir=self.store.root)
        try:
            path = Path(directory.name) / safe_name
            with path.open("wb") as output:
                written = 0
                while chunk := stream.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise UserError("100 MB 이하의 파일을 사용하세요.")
                    output.write(chunk)
            self.load_source(path, upload=directory)
        except BaseException:
            directory.cleanup()
            raise
        return self.source_summary()

    def _organization_choices(self, loaded: LoadedData) -> dict:
        config = {"equipment_names": self.store.read("equipment_names.json")}
        choices = organization_filter_choices(loaded, config)
        return {
            **choices,
            "organizations": {
                factory: organization_filter_choices(loaded, config, factory=factory)["teams"]
                for factory in choices["factories"]
            },
        }

    def source_summary(self) -> dict | None:
        loaded = self.loaded
        if loaded is None:
            return None
        return {
            "name": loaded.path.name,
            "sheet": loaded.sheet,
            "header_row": loaded.header_row,
            "sheet_names": loaded.sheet_names,
            "headers": loaded.headers,
            "mapping": loaded.mapping,
            "fields": {key: FIELD_LABELS.get(key, key) for key in loaded.mapping},
            "row_count": len(loaded.frame),
            "skipped_count": len(loaded.skipped),
            "warnings": loaded.warnings,
            "profile": loaded.profile,
            **self.organizations,
        }

    def change_source(
        self,
        sheet: str | None,
        header_row: int | None,
        mapping: dict[str, str | None] | None,
        *,
        auto_header: bool,
    ) -> dict:
        current = self.require_source()
        sheet = sheet or current.sheet
        use_row = header_row if header_row is not None or auto_header else current.header_row
        loaded = current
        if sheet != current.sheet or use_row != current.header_row:
            loaded = self._read_source(current.path, sheet, use_row)
        if mapping is not None:
            if mapping.keys() - loaded.mapping.keys() or any(
                value is not None and value not in loaded.headers for value in mapping.values()
            ):
                raise UserError("컬럼 매핑에 현재 시트에서 사용할 수 없는 항목이 있습니다.")
            new_mapping = {**loaded.mapping, **mapping}
            if new_mapping != loaded.mapping:
                moves = dict(
                    zip(
                        event_ids(loaded, loaded.mapping),
                        event_ids(loaded, new_mapping),
                        strict=True,
                    )
                )
                self.store.rekey_overrides(moves)
                self.store.save_mapping(loaded.headers, new_mapping)
                self.pending = {moves.get(key, key): value for key, value in self.pending.items()}
                loaded = replace(loaded, mapping=new_mapping)
        self.organizations = self._organization_choices(loaded)
        self.loaded = loaded
        self.result = None
        self.current_ids.clear()
        self._equipment_types = None
        return self.source_summary()

    def analysis_summary(self, *, applied_count=0) -> dict | None:
        result = self.result
        if result is None:
            return None
        counts = {
            "detail": len(result.selected),
            "equipment_types": len(result.tables["equipment_type"]),
            "raw": len(result.loaded.frame),
            **{key: len(frame) for key, frame in result.tables.items()},
        }
        return {
            "metrics": result.metrics,
            "notes": result.notes,
            "tables": [
                {"key": key, "label": label, "count": counts[key]}
                for key, label in TABLE_LABELS.items()
                if key in counts
            ],
            "options": asdict(result.options),
            "pending_count": sum(key in self.current_ids for key in self.pending),
            "applied_count": applied_count,
        }

    def analyze(self, options: AnalysisOptions, *, apply_pending=False) -> dict:
        loaded = self.require_source()
        applied_count = 0
        if apply_pending and self.pending:
            ids = set(event_ids(loaded, loaded.mapping))
            batch = {key: value for key, value in self.pending.items() if key in ids}
            applied_count = self.store.apply_classifications(batch)
            for key in batch:
                self.pending.pop(key)
            if applied_count:
                self.result = None

        result = run_analysis(loaded, self.store.load(), options)
        result.tables["factory"] = grouped(result.selected, ["factory"])
        result.tables["team"] = grouped(result.selected, ["factory", "team"])
        self.result = result
        self.current_ids = set(result.all_records["event_id"])
        self._equipment_types = None
        return self.analysis_summary(applied_count=applied_count)

    def refresh_result(self) -> None:
        if self.result is not None:
            options = self.result.options
            self.result = None
            self.analyze(options)

    def table_frame(self, key: str) -> pd.DataFrame:
        if key == "raw":
            return self.require_source().frame
        result = self.require_result()
        if key == "detail":
            frame = result.selected
            leading = [column for column in DETAIL_COLUMNS if column in frame]
            return frame.loc[:, leading + [column for column in frame if column not in leading]]
        if key == "equipment_types":
            if self._equipment_types is None:
                frames = [
                    type_breakdown(group, equipment).assign(equipment=equipment)
                    for equipment, group in result.selected.groupby("equipment", sort=False)
                ]
                self._equipment_types = (
                    pd.concat(frames, ignore_index=True)
                    if frames
                    else result.tables["equipment_type"].assign(rank=None)
                )
                columns = [
                    "equipment",
                    "rank",
                    *[
                        column
                        for column in self._equipment_types
                        if column not in ("equipment", "rank")
                    ],
                ]
                self._equipment_types = self._equipment_types.loc[:, columns]
            return self._equipment_types
        if key not in result.tables:
            raise UserError("분석 표를 찾을 수 없습니다.")
        return result.tables[key]

    def add_review_metadata(self, rows: list[dict]) -> None:
        result = self.require_result()
        target_review = review_target(result.config_snapshot["settings"], result.options)
        for row in rows:
            colors = review_types(row, target_review)
            row["review_color_key"] = colors[0] if colors else None
            row["pending_classification"] = row["event_id"] in self.pending

    def event(self, event_id: str, source_row: int | None) -> dict:
        result = self.require_result()
        matches = result.selected.loc[result.selected["event_id"].eq(event_id)]
        if source_row is not None:
            matches = matches.loc[matches["source_row"].eq(source_row)]
        if matches.empty:
            raise UserError("현재 분석 결과에 없는 기록입니다. 분석을 다시 실행하세요.")
        record = records(matches.iloc[:1])[0]
        self.add_review_metadata([record])
        original = result.loaded.frame.loc[
            result.loaded.frame["__source_row"].eq(record["source_row"]), result.loaded.headers
        ]
        existing = self.store.override(event_id)
        values = initial_values(record, existing)
        values["normalized"] = str(record.get("normalized") or "")
        pending = self.pending.get(event_id)
        if pending:
            values.update({key: value or "" for key, value in pending.items()})
        return {
            "record": record,
            "original": records(original)[0] if not original.empty else {},
            "values": {key: value for key, value in values.items() if key in EDIT_FIELDS},
            "pending": pending,
            "overrides": existing,
            "candidates": parse_candidates(record.get("classification_candidates")),
        }

    def edit_event(
        self, event_id: str, source_row: int | None, updates: dict[str, str | None], confirm: bool
    ) -> dict:
        event = self.event(event_id, source_row)
        if updates.keys() - EDIT_FIELDS:
            raise UserError("수정할 수 없는 항목입니다.")
        existing = event["overrides"]
        initial = initial_values(event["record"], existing)
        initial["normalized"] = str(event["record"].get("normalized") or "")
        values = {**initial, **event["values"]}
        values.update({key: (value or "").strip() for key, value in updates.items()})
        category_keys = set(PUBLIC_CATEGORY_FIELDS)
        edit_category = confirm or any(
            values[key] != event["values"].get(key, "")
            for key in category_keys.intersection(updates)
        )
        checked = (
            values
            if edit_category
            else {key: value for key, value in values.items() if key not in category_keys}
        )
        error = validate(checked)
        if error:
            raise UserError(error)

        patch = correction_patch(initial, values, existing, confirm)
        if values["normalized"] != initial["normalized"]:
            patch["normalized"] = values["normalized"] or None
        immediate = {key: value for key, value in patch.items() if key not in CLASSIFICATION_FIELDS}
        if immediate:
            self.store.update_override(event_id, immediate)
            self.refresh_result()
        if edit_category:
            staged = {key: value for key, value in patch.items() if key in CLASSIFICATION_FIELDS}
            merged = (
                self.store._patch_override({event_id: existing}, event_id, staged)
                if staged
                else existing
            )
            if any(
                merged.get(key) != existing.get(key)
                for key in (*CLASSIFICATION_FIELDS, "classification_schema")
            ):
                self.pending[event_id] = staged
            else:
                self.pending.pop(event_id, None)
        return self.analysis_summary()

    def settings(self) -> dict:
        config = self.store.load()
        catalog = config["classification_catalog"]
        return {
            "report": config["final_report"],
            "review_colors": config["settings"]["review_colors"],
            "review_color_types": [
                {"key": key, "label": label, "default": default}
                for key, label, default in REVIEW_TYPES
            ],
            "equipment_names": config["equipment_names"],
            "equipment_catalog": {
                source: equipment_catalog(self.loaded, source) for source in ("line", "equipment")
            },
            "organization_catalog": {
                source: organization_catalog(self.loaded, source)
                for source in ("line", "equipment")
            },
            "rules": config["rules"],
            "rule_columns": list(RULE_COLUMNS),
            "classification_paths": equipment_classification_categories(
                config["rules"], catalog.get("equipment_types")
            ),
            "repair_actions": list(REPAIR_ACTIONS),
        }

    def save_names(self, mapping: dict[str, str], source: str, grouping, organization) -> None:
        self.store.save_equipment_names(
            mapping, source=source, grouping=grouping, organization=organization
        )
        if self.loaded is not None:
            self.organizations = self._organization_choices(self.loaded)
        self.refresh_result()

    def save_rules(self, rules: list[dict]) -> None:
        target = self.store.config_dir / "classification_config.xlsx"
        with tempfile.TemporaryDirectory(prefix="efa-rules-", dir=target.parent) as directory:
            staged = Path(directory) / target.name
            write_rules(staged, rules)
            shutil.copy2(target, target.with_suffix(".xlsx.bak"))
            os.replace(staged, target)
        self.refresh_result()
