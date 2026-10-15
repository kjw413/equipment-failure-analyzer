"""What a per-record correction saves. Only fields the user actually changed are stored."""
from __future__ import annotations
import math
import pandas as pd
from core.i18n import K

CLASSIFICATION = ('major','middle','minor')
FIELDS = (*CLASSIFICATION,'target','product','work_date','minutes')
# Placeholder labels are not real values and never become a correction.
PLACEHOLDERS = (K['missing'],K['unclassified'],K['target_missing'],K['nonfault'])

def shown(value) -> str:
    text='' if value is None else str(value).strip()
    return '' if text in PLACEHOLDERS or text.casefold() in ('nan','nat','none') else text

def initial_values(record: dict, existing: dict) -> dict[str,str]:
    """Values a correction form starts with: current classification, target and product;
    work date and minutes only when they were already corrected (the source value is a hint)."""
    values={key:shown(record.get(key)) for key in (*CLASSIFICATION,'target','product')}
    values.update(work_date=shown(existing.get('work_date')),minutes=shown(existing.get('minutes')))
    return values

def validate(values: dict[str,str]) -> str | None:
    parts=[values.get(key,'').strip() for key in CLASSIFICATION]
    if any(parts) and not all(parts):
        return '대/중/소분류를 모두 입력하거나 모두 비우세요.'
    if values.get('work_date','').strip():
        from core.preprocessing import parse_date
        if pd.isna(parse_date(values['work_date'].strip())):
            return '작업일자를 YYYY-MM-DD 형식으로 입력하세요.'
    if values.get('minutes','').strip():
        try:
            minutes=float(values['minutes'])
            valid=math.isfinite(minutes) and minutes>=0
        except ValueError:
            valid=False
        if not valid:
            return '확정 정지시간은 0 이상의 숫자(분)로 입력하세요.'
    return None

def correction_patch(initial: dict[str,str], values: dict[str,str], existing: dict, confirm: bool) -> dict[str,str | None]:
    """Fields to set (text) or remove (None). Unchanged prefilled values are never saved,
    so fixing only the stop time does not silently confirm a tentative classification."""
    values={key:str(values.get(key,'')).strip() for key in FIELDS}
    patch={}
    parts=tuple(values[key] for key in CLASSIFICATION)
    before=tuple(initial.get(key,'') for key in CLASSIFICATION)
    if all(parts) and (confirm or parts!=before):
        patch.update(zip(CLASSIFICATION,parts))
    elif not any(parts) and any(existing.get(key) for key in CLASSIFICATION):
        patch.update({key:None for key in CLASSIFICATION})
    for key in ('target','product','work_date','minutes'):
        if values[key]!=initial.get(key,''):
            patch[key]=values[key] or None
    return {key:value for key,value in patch.items() if value is not None or key in existing}
