"""Validation and versioned Excel storage for classification rules."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from core.models import UserError
from version import VERSION

REQUIRED_COLUMNS = [
    "id",
    "enabled",
    "priority",
    "major",
    "middle",
    "minor",
    "context",
    "symptom",
    "exclude",
]
# role: component = a named part; fallback = only when no part is named; override = cause statement;
# nopart = considered only after no component/fallback/override candidate matched the record
# (process symptoms such as a product jam, or a controller error without a named part).
RULE_COLUMNS = REQUIRED_COLUMNS + ["role"]
ROLES = ("component", "fallback", "override", "nopart")

# Rules workbook format. Schema 1 = single 'rules' sheet (v1.4.0 and earlier).
# Schema 2 = rules_v2 plus hidden compatibility/meta sheets.
# Schema 3 protects the physical-part catalogue from pre-1.8 default mergers.
# Schema 4 adds the nopart role, which earlier programs would reject as an unknown role.
# Schema 5 prevents earlier programs from exposing part IDs as output symptoms.
RULES_SCHEMA = 7
MIN_APP_VERSION = "1.18.0"
RULES_SHEET, LEGACY_SHEET, META_SHEET = "rules_v2", "rules", "meta"
LEGACY_GUARD = (
    f"이 분류 규칙은 v{MIN_APP_VERSION} 이상 전용입니다. "
    f"최신 프로그램(START.bat 또는 v{MIN_APP_VERSION} 이상 EXE)으로 실행하세요"
)


def validate_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result, ids = [], set()
    for i, raw in enumerate(rules, 2):
        row = {
            key: "" if raw.get(key) is None else str(raw.get(key)).strip() for key in RULE_COLUMNS
        }
        if not any(row[key] for key in REQUIRED_COLUMNS):
            continue
        if not row["id"] or row["id"] in ids:
            raise UserError(f"Rule row {i}: ID는 비어 있거나 중복될 수 없습니다.")
        ids.add(row["id"])
        if row["enabled"].casefold() not in ("0", "1", "true", "false", "yes", "no"):
            raise UserError(f"Rule {row['id']}: enabled는 0 또는 1입니다.")
        row["enabled"] = row["enabled"].casefold() in ("1", "true", "yes")
        try:
            row["priority"] = int(row["priority"])
        except ValueError as e:
            raise UserError(f"Rule {row['id']}: priority는 정수입니다.") from e
        row["role"] = row["role"].casefold() or "component"
        if row["role"] not in ROLES:
            raise UserError(f"Rule {row['id']}: role은 {' / '.join(ROLES)} 중 하나입니다.")
        for key in ("major", "middle", "minor", "context", "symptom"):
            if not row[key]:
                raise UserError(f"Rule {row['id']}: {key} 필수 입력")
        for key in ("context", "symptom", "exclude"):
            if len(row[key]) > 1000:
                raise UserError(f"Rule {row['id']}: pattern 길이 초과")
            try:
                re.compile(row[key], re.IGNORECASE)
            except re.error as e:
                raise UserError(f"Rule {row['id']}: {key} 정규식 오류: {e}") from e
        result.append(row)
    return result


def file_schema(wb) -> tuple[int, str]:
    """(schema, minimum program version) of a rules workbook. A single 'rules' sheet is schema 1."""
    if META_SHEET not in wb.sheetnames:
        return (2 if RULES_SHEET in wb.sheetnames else 1), ""
    meta = {
        str(row[0]).strip(): row[1]
        for row in wb[META_SHEET].iter_rows(min_row=2, values_only=True)
        if row and row[0]
    }
    try:
        return int(meta.get("schema", RULES_SCHEMA)), str(meta.get("min_app_version") or "")
    except (TypeError, ValueError):
        return RULES_SCHEMA, ""


def read_rules(path: Path) -> list[dict[str, Any]]:
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            schema, minimum = file_schema(wb)
            if schema > RULES_SCHEMA:
                raise UserError(
                    f"classification_config.xlsx는 더 새로운 프로그램(v{minimum or '?'} 이상)에서 저장한 분류 규칙입니다.\n"
                    f"현재 프로그램은 v{VERSION}입니다. 최신 버전으로 실행하세요."
                )
            ws = (
                wb[RULES_SHEET]
                if RULES_SHEET in wb.sheetnames
                else wb[LEGACY_SHEET]
                if LEGACY_SHEET in wb.sheetnames
                else wb.active
            )
            it = ws.iter_rows(values_only=True)
            headers = [str(x or "").strip() for x in next(it, ())]
            if not set(REQUIRED_COLUMNS).issubset(headers):
                raise UserError("classification_config.xlsx: 필수 열이 없습니다.")
            rows = [dict(zip(headers, row)) for row in it if any(v is not None for v in row)]
            return validate_rules(rows)
        finally:
            wb.close()
    except UserError:
        raise
    except Exception as e:
        raise UserError("classification_config.xlsx 파일을 확인하세요.") from e


def write_rules(path: Path, rules: list[dict[str, Any]]) -> None:
    checked = validate_rules(rules)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = RULES_SHEET
    ws.append(RULE_COLUMNS)
    # Programs before v1.5.0 read the 'rules' sheet with a different engine and would misclassify
    # silently. That sheet holds one deliberately invalid row, so they stop with this message instead.
    guard = wb.create_sheet(LEGACY_SHEET)
    guard.append(REQUIRED_COLUMNS)
    guard.append([LEGACY_GUARD, f"v{MIN_APP_VERSION}", 0, "-", "-", "-", "-", "-", ""])
    guard.sheet_state = "hidden"
    meta = wb.create_sheet(META_SHEET)
    meta.append(["key", "value"])
    for key, value in (
        ("schema", RULES_SCHEMA),
        ("min_app_version", MIN_APP_VERSION),
        ("saved_by", VERSION),
    ):
        meta.append([key, value])
    meta.sheet_state = "hidden"
    for row in checked:
        ws.append([int(row[k]) if k == "enabled" else row[k] for k in RULE_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(name="Malgun Gothic", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="343A40")
    for col, width in zip("ABCDEFGHIJ", [22, 10, 10, 14, 22, 34, 55, 65, 40, 12]):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Malgun Gothic", size=10)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            # A user-editable rule is data, never an Excel formula.
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.data_type = "s"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=path.parent)
    os.close(fd)
    try:
        wb.save(tmp)
        if path.exists():
            shutil.copy2(path, path.with_suffix(".xlsx.bak"))
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def needs_format_upgrade(path: Path) -> bool:
    """True for a rules file older programs can still read (no rules_v2 sheet or an older schema)."""
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return RULES_SHEET not in wb.sheetnames or file_schema(wb)[0] < RULES_SCHEMA
    finally:
        wb.close()


def upgrade_rules_format(path: Path) -> bool:
    """Rewrite an older-format rules file in the current format, rules unchanged."""
    if not path.exists() or not needs_format_upgrade(path):
        return False
    write_rules(path, read_rules(path))
    return True
