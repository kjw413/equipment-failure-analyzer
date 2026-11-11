"""Write an Excel sheet so a person can check the hand labels against every method's answer."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import NONE, E, load

base, gold = load()
knn = pd.read_pickle(E / "knn_e5large.pkl").set_index("gid")
out = pd.DataFrame(
    {
        "번호": gold.gid,
        "연도": gold.year,
        "규칙 상태": gold.status,
        "설비(비가동코드 중)": gold.raw_mid,
        "고장내용 원문": gold.raw_description,
        "정답 부품군(가라벨)": gold.gold.map(", ".join),
        "해석 애매": gold.ambiguous.map({True: "애매", False: ""}),
        "규칙 엔진": gold.rule_parts.map(lambda x: ", ".join(x) or NONE),
        "유사사례(e5)": gold.gid.map(knn.knn_top),
    }
)
for tag, label in (
    ("gemma4e2b", "Gemma4-E2B"),
    ("gemma4e2b_norm", "Gemma4-E2B(표준화 입력)"),
    ("gemma4e4b", "Gemma4-E4B"),
    ("qwen3_4b", "Qwen3-4B"),
):
    p = E / f"llm_{tag}.jsonl"
    if p.exists():
        d = {r["gid"]: r for r in map(json.loads, open(p, encoding="utf-8"))}
        out[label] = gold.gid.map(
            lambda g: (
                f"[{d[g]['decision']}] " + (", ".join(d[g]["parts"]) or NONE) if g in d else ""
            )
        )
out["검수: 정답이 맞으면 O, 틀리면 올바른 부품군"] = ""
path = E / "gold_review.xlsx"
with pd.ExcelWriter(path, engine="openpyxl") as w:
    out.to_excel(w, index=False, sheet_name="정답셋 검수")
    ws = w.sheets["정답셋 검수"]
    for col, width in zip("ABCDEFGHIJKL", (6, 6, 12, 26, 60, 26, 8, 22, 18, 26, 26, 30)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "F2"
print(path)
