from __future__ import annotations

import hashlib
import re
import warnings
from pathlib import Path
from typing import Any, Callable

import openpyxl
import pandas as pd

from core.i18n import K
from core.models import LoadedData, Progress, UserError, noop_progress

SUPPORTED = {".xlsx", ".xlsm"}


def header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9\uac00-\ud7a3]", "", str(value or "").casefold())


def validate_path(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if p.suffix.casefold() not in SUPPORTED:
        raise UserError(K["unsupported"])
    if not p.is_file():
        raise UserError(K["missing_file"])
    if p.name.startswith("~$"):
        raise UserError(
            "\uc784\uc2dc Excel \ud30c\uc77c\uc740 \uc77d\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4."
        )
    if p.stat().st_size > 100 * 1024 * 1024:
        raise UserError(
            "100 MB \uc774\ud558\uc758 \ud30c\uc77c\uc744 \uc0ac\uc6a9\ud558\uc138\uc694."
        )
    return p


def open_book(path: Path):
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Workbook contains no default style.*")
            return openpyxl.load_workbook(path, read_only=False, data_only=True, keep_links=False)
    except Exception as e:
        raise UserError(K["bad_workbook"]) from e


def aliases_set(aliases: dict) -> set[str]:
    return {header_key(a) for values in aliases.values() for a in values}


def detect_header(ws, aliases: dict) -> int:
    keys = aliases_set(aliases)
    scores = []
    for row in ws.iter_rows(
        min_row=1, max_row=min(ws.max_row, 60), max_col=min(ws.max_column, 300)
    ):
        score = sum(header_key(c.value) in keys for c in row if c.value is not None)
        scores.append((score, -row[0].row))
    best = max(scores, default=(0, -1))
    return -best[1] if best[0] >= 2 else 1


def auto_mapping(headers: list[str], aliases: dict) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for field, candidates in aliases.items():
        mapping[field] = None
        for alias in candidates:
            match = next(
                (h for h in headers if header_key(h) == header_key(alias) and h not in used), None
            )
            if match is not None:
                mapping[field] = match
                used.add(match)
                break
    return mapping


def load_excel(
    path: str | Path,
    aliases: dict,
    sheet: str | None = None,
    header_row: int | None = None,
    progress: Progress = noop_progress,
    mapping_lookup: Callable[[list[str]], dict | None] | None = None,
) -> LoadedData:
    """mapping_lookup(headers) returns a column mapping the user saved for these headers."""
    p = validate_path(path)
    progress(5, K["loading"])
    wb = open_book(p)
    try:
        if not wb.sheetnames:
            raise UserError(K["empty"])
        selected = sheet or wb.sheetnames[0]
        if selected not in wb.sheetnames:
            raise UserError("\uc2dc\ud2b8\ub97c \ub2e4\uc2dc \uc120\ud0dd\ud558\uc138\uc694.")
        ws = wb[selected]
        if ws.max_row > 250_000 or ws.max_column > 300:
            raise UserError(
                "\uc9c0\uc6d0 \ud06c\uae30\ub294 250,000\ud589 / 300\uc5f4\uae4c\uc9c0\uc785\ub2c8\ub2e4."
            )
        hr = header_row or detect_header(ws, aliases)
        if hr < 1 or hr > ws.max_row:
            raise UserError(
                "\uc81c\ubaa9 \ud589 \ubc88\ud638\ub97c \ud655\uc778\ud558\uc138\uc694."
            )
        raw_headers = [ws.cell(hr, c).value for c in range(1, ws.max_column + 1)]
        while raw_headers and raw_headers[-1] is None:
            raw_headers.pop()
        if not raw_headers:
            raise UserError("\uc81c\ubaa9 \ud589\uc774 \ube44\uc5b4 \uc788\uc2b5\ub2c8\ub2e4.")
        headers, seen = [], {}
        for i, v in enumerate(raw_headers, 1):
            base = str(v).strip() if v is not None else f"Column_{i}"
            seen[base] = seen.get(base, 0) + 1
            headers.append(base if seen[base] == 1 else f"{base}__{seen[base]}")
        merged = {}
        # Fill only cells actually merged in the source. Never forward-fill arbitrary blanks.
        for r in ws.merged_cells.ranges:
            if r.min_row <= hr:
                continue
            if (r.max_row - r.min_row + 1) * (r.max_col - r.min_col + 1) > 50_000:
                continue
            value = ws.cell(r.min_row, r.min_col).value
            for rr in range(r.min_row, r.max_row + 1):
                for cc in range(r.min_col, r.max_col + 1):
                    merged[(rr, cc)] = value
        keyset = aliases_set(aliases)
        records, skipped = [], []
        for rnum, row in enumerate(ws.iter_rows(min_row=hr + 1, max_col=len(headers)), hr + 1):
            vals = [merged.get((rnum, c.column), c.value) for c in row]
            nonempty = [v for v in vals if v is not None and str(v).strip()]
            if not nonempty:
                skipped.append({"row": rnum, "reason": K["blank"]})
                continue
            hits = sum(header_key(v) in keyset for v in nonempty)
            if hits >= 3 and hits / max(1, len(nonempty)) >= 0.35:
                skipped.append({"row": rnum, "reason": K["header_footer"]})
                continue
            if str(nonempty[0]).strip() in ("\ud569\uacc4", "\ucd1d\uacc4", "\uc18c\uacc4"):
                skipped.append({"row": rnum, "reason": "\ud569\uacc4 \ud589"})
                continue
            record = dict(zip(headers, vals))
            record["__source_row"] = rnum
            records.append(record)
            if rnum % 500 == 0:
                progress(10 + int(70 * rnum / max(1, ws.max_row)), K["loading"])
        df = pd.DataFrame(records, columns=[*headers, "__source_row"])
        mapping = auto_mapping(headers, aliases)
        signature = {
            "\ube44\uac00\ub3d9 \uc2dc\uac04(\ubd84)",
            "\ube44\uac00\ub3d9 \ucf54\ub4dc(\uc911)",
            "\ube44\uac00\ub3d9 \uc720\ud615",
        }
        profile = "mes_downtime_v1" if signature.issubset(set(headers)) else "generic"
        if profile == "mes_downtime_v1" and "\uc124\ube44" in headers:
            mapping["equipment_id"] = "\uc124\ube44"
        saved = mapping_lookup(headers) if mapping_lookup else None
        if saved:
            # The user's confirmed choice wins over automatic detection, column by column.
            mapping.update(
                {k: v for k, v in saved.items() if k in mapping and (v is None or v in headers)}
            )
        with p.open("rb") as stream:
            file_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        progress(100, K["done"])
        return LoadedData(
            p, selected, hr, df, headers, mapping, profile, file_hash, skipped, list(wb.sheetnames)
        )
    finally:
        wb.close()
