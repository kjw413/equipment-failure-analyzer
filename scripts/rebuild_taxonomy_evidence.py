"""Build source-backed taxonomy proposals without changing production profiles."""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from profile_three_year_taxonomy import read_records

OUT = ROOT / "output/taxonomy_rebuild_20261112"


def clean(value):
    return re.sub(r"\s+", "", str(value or "").replace("_x000D_", "\n")).casefold()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    records, sources = [], []
    for year in (24, 25, 26):
        path = Path(f"C:/Users/user/Downloads/라인 고장이력_{year}년.xlsx")
        before = sha(path)
        rows, sheets = read_records(path)
        events = []
        for row in rows:
            ref = f"20{year}:{row['_sheet']}!{row['_row']}"
            item = {
                "ref": ref,
                "year": 2000 + year,
                "file": path.name,
                "sheet": row["_sheet"],
                "row": row["_row"],
                "line": row.get("라인명", ""),
                "registered": row.get("설비명", ""),
                "mid": row.get("비가동 코드(중)", ""),
                "small": row.get("비가동 코드(소)", ""),
                "description": row.get("비고", "") or "",
                "minutes": float(row.get("비가동 시간(분)") or 0),
                "start": str(row.get("비가동 시작 시간") or ""),
            }
            records.append(item)
            events.append(item)
        fingerprints = Counter(
            (x["line"], x["registered"], x["start"], x["description"]) for x in events
        )
        sources.append(
            {
                "file": path.name,
                "path": str(path),
                "sha256_before": before,
                "sha256_after": sha(path),
                "rows": len(events),
                "minutes": sum(x["minutes"] for x in events),
                "first": min(x["start"] for x in events),
                "last": max(x["start"] for x in events),
                "blank_description": sum(not clean(x["description"]) for x in events),
                "blank_mid": sum(not clean(x["mid"]) for x in events),
                "blank_small": sum(not clean(x["small"]) for x in events),
                "duplicate_excess": sum(n - 1 for n in fingerprints.values()),
                "sheets": sheets,
            }
        )
        assert sources[-1]["sha256_before"] == sources[-1]["sha256_after"]
    review_path = ROOT / "설비 고장 분석기_검토필요 수기 검수.xlsx"
    import openpyxl

    before = sha(review_path)
    wb = openpyxl.load_workbook(review_path, read_only=True, data_only=True)
    reviewed = []
    original = {i: list(row) for i, row in enumerate(wb["원본"].iter_rows(values_only=True), 1)}
    review_rows = list(wb["검수"].iter_rows(values_only=True))
    last_feedback = max(i for i, row in enumerate(review_rows, 1) if len(row) > 10 and row[10])
    for number, row in enumerate(review_rows, 1):
        if number == 1:
            continue
        values = list(row) + [None] * 11
        if not any(values[:11]):
            continue
        selected = values[:4]
        note = str(values[10] or "").strip()
        if not any(selected) and note in ("", "-") and number > last_feedback:
            continue
        matches = [
            x["ref"]
            for x in records
            if clean(x["description"]) == clean(values[7]) and clean(values[7])
        ]
        complete = all(v and "선택" not in str(v) for v in selected)
        reviewed.append(
            {
                "ref": f"검수!{number}",
                "row": number,
                "selected": selected,
                "description": values[7] or "",
                "feedback": note,
                "registered": values[4] or "",
                "mid": values[5] or "",
                "small": values[6] or "",
                "original_final": (original.get(number, []) + [None] * 10)[8],
                "source_refs": matches,
                "label_status": "공통 의견"
                if str(selected[0]) == "공통의견"
                else "수기 완성값·기준 재검토"
                if complete
                else "미완성·개선 의견",
            }
        )
    wb.close()
    assert before == sha(review_path)
    catalog = json.loads((ROOT / "config/classification_catalog.json").read_text(encoding="utf-8"))
    type_names = {clean(x["name"]): x["name"] for x in catalog["equipment_types"]}
    for item in catalog["equipment_types"]:
        for alias in item["aliases"]:
            type_names[clean(alias)] = item["name"]
    overlap = []
    for item in catalog["categories"]:
        key = clean(re.sub(r"\([^)]*미상\)", "", item["minor"]))
        if key in type_names:
            overlap.append(
                {"part": item["minor"], "group": item["middle"], "equipment": type_names[key]}
            )
    token_counts = Counter()
    for item in records:
        tokens = set(re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9·/+.-]{1,35}", item["description"]))
        token_counts.update(tokens)
    profile = {
        "sources": sources,
        "rows": len(records),
        "minutes": sum(x["minutes"] for x in records),
        "feedback_file": {"path": str(review_path), "sha256": before},
        "feedback_notes": sum(x["feedback"] not in ("", "-") for x in reviewed),
        "review_items": len(reviewed),
        "catalog_equipment": len(catalog["equipment_types"]),
        "catalog_parts": len(catalog["categories"]),
        "equipment_part_overlap": overlap,
        "scope_note": "2026년은 제공 파일의 마지막 기록까지이며 연간 전체가 아님. 출현은 고장 확정·정확도가 아님.",
    }
    save("phase1_source_profile.json", profile)
    save("source_records.json", records)
    save("review_cases.json", reviewed)
    save(
        "surface_vocabulary.json",
        [{"term": name, "event_mentions": count} for name, count in token_counts.most_common()],
    )
    print(
        json.dumps(
            {
                "rows": len(records),
                "feedback_notes": profile["feedback_notes"],
                "overlap": overlap,
                "sources": [
                    {k: x[k] for k in ("file", "rows", "minutes", "blank_description", "last")}
                    for x in sources
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    prepare()
