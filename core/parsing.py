"""Source-value parsing and text preparation shared by ingestion and editors."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd
from openpyxl.utils.datetime import from_excel

from core.models import UserError


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in ("", "nan", "nat", "none", "null")
    try:
        return bool(pd.isna(value))
    except (ValueError, TypeError):
        return False


def text(value: Any) -> str:
    return "" if is_missing(value) else str(value).strip()


def normalize(value: Any, replacements: dict[str, str] | None = None) -> str:
    result = re.sub(r"\s+", " ", text(value).casefold()).strip()
    ordered = sorted((replacements or {}).items(), key=lambda t: -len(t[0]))
    # A few passes let one fix enable another ('솔레노이드 벨브' -> '솔레노이드 밸브' -> '솔밸브').
    for _ in range(3):
        before = result
        for old, new in ordered:
            result = result.replace(old.casefold(), new.casefold())
        if result == before:
            break
    return result


# A clause ends at a line break, slash, bracket, arrow, sentence period or ' - '.
CLAUSE_END = r"(?=\s*(?:$|[\n\r/;|*()\[\]→,]|->|=>|>>|\.(?!\d)|\s-\s))"
# Real words that end in '교'; never expanded to '…교체'.
ENDING_STOPWORDS = {"비교", "학교", "종교", "외교", "선교", "설교"}


def expand_endings(value: str, endings: dict[str, str] | None) -> str:
    """Restore clause-final syllables cut short in the MES field ('후크 교' -> '후크 교체').

    Only a lone final syllable is expanded, plus a final '교' attached to a noun.
    """
    if not value or not endings:
        return value
    keys = "|".join(map(re.escape, sorted(endings, key=len, reverse=True)))
    result = re.sub(
        rf"(?:^|(?<=[\s/;|*(\[]))({keys}){CLAUSE_END}",
        lambda m: endings[m.group(1)],
        value,
        flags=re.M,
    )
    if "교" in endings:
        result = re.sub(
            rf"([가-힣]+)교{CLAUSE_END}",
            lambda m: m.group(0) if m.group(0) in ENDING_STOPWORDS else m.group(1) + endings["교"],
            result,
            flags=re.M,
        )
    return result


def prepare_text(value: Any, normalization: dict | None) -> str:
    """Normalized, classification-ready text; the raw source text is kept separately."""
    settings = normalization or {}
    return expand_endings(
        normalize(value, settings.get("replacements", {})),
        settings.get("clause_end_expansions", {}),
    )


def parse_date(value: Any) -> pd.Timestamp:
    if is_missing(value):
        return pd.NaT
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return (
            pd.Timestamp(value).tz_localize(None)
            if pd.Timestamp(value).tzinfo
            else pd.Timestamp(value)
        )
    if isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return pd.NaT
        if 20000101 <= value <= 20991231 and float(value).is_integer():
            return pd.to_datetime(str(int(value)), format="%Y%m%d", errors="coerce")
        if 1 <= value < 100000:
            dt = from_excel(float(value))
            return pd.Timestamp(dt) if isinstance(dt, datetime) else pd.NaT
        return pd.NaT
    s = text(value).replace("\ub144", "-").replace("\uc6d4", "-").replace("\uc77c", "").strip()
    try:
        result = pd.to_datetime(s, errors="coerce", format="mixed")
        if pd.isna(result):
            return pd.NaT
        return result.tz_localize(None) if result.tzinfo else result
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def is_time_only(value: Any) -> bool:
    return isinstance(value, time) or bool(re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", text(value)))


def parse_stamp(value: Any, day: pd.Timestamp) -> pd.Timestamp:
    if not is_time_only(value):
        return parse_date(value)
    if pd.isna(day):
        return pd.NaT
    if isinstance(value, time):
        return pd.Timestamp(datetime.combine(day.date(), value))
    parts = [int(x) for x in text(value).split(":")]
    if parts[0] > 23 or parts[1] > 59 or (len(parts) > 2 and parts[2] > 59):
        return pd.NaT
    return day.normalize() + timedelta(
        hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0
    )


def parse_duration(value: Any, unit: str = "minutes") -> float | None:
    factors = {"minutes": 1.0, "hours": 60.0, "seconds": 1 / 60, "excel_days": 1440.0}
    if unit not in factors:
        raise UserError("Unknown duration unit")
    if is_missing(value):
        return None
    if isinstance(value, (timedelta, pd.Timedelta)):
        v = value.total_seconds() / 60
    elif isinstance(value, time):
        v = value.hour * 60 + value.minute + value.second / 60
    elif isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
        v = float(value) * factors[unit]
    else:
        s = text(value).lower().replace(",", "").replace(" ", "")
        if re.fullmatch(r"\d+(?:\.\d+)?", s):
            v = float(s) * factors[unit]
        elif re.fullmatch(r"\d+:\d{2}(?::\d{2})?", s):
            p = [int(x) for x in s.split(":")]
            if p[1] > 59 or (len(p) > 2 and p[2] > 59):
                return None
            v = p[0] * 60 + p[1] + (p[2] / 60 if len(p) > 2 else 0)
        else:
            pattern = r"(\d+(?:\.\d+)?)(\uc2dc\uac04|\ubd84|\ucd08|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)"
            parts = list(re.finditer(pattern, s))
            if not parts or "".join(m.group(0) for m in parts) != s:
                return None
            v = 0.0
            for m in parts:
                n = float(m.group(1))
                u = m.group(2)
                v += n * (
                    60
                    if u in ("\uc2dc\uac04", "h", "hour", "hours", "hr", "hrs")
                    else 1 / 60
                    if u in ("\ucd08", "s", "second", "seconds", "sec", "secs")
                    else 1
                )
    return float(v) if math.isfinite(v) and v >= 0 else None
