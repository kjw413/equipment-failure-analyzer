"""Draw the stratified gold sample from baseline.pkl and write texts for hand labelling.
Labels go to exp/gold_labels_*.txt as '<gid> <code>[,<code>...] [?]' (see gold_build.CODES)."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import E

SIZES = {"규칙분류": 100, "규칙 미일치": 80, "검토필요": 80, "비가동코드 미기입": 40}

d = pd.read_pickle(E / "baseline.pkl").drop_duplicates("raw_description")
s = pd.concat(
    [
        d[d.status == k].sample(min(v, (d.status == k).sum()), random_state=7)
        for k, v in SIZES.items()
    ]
)
s = s.sample(frac=1, random_state=3).reset_index(drop=True)
s["gid"] = range(1, len(s) + 1)
s.to_pickle(E / "gold_sample.pkl")
with open(E / "gold_texts.txt", "w", encoding="utf-8") as f:
    for _, r in s.iterrows():
        text = str(r.raw_description).replace("\r", " ").replace("\n", " ")
        f.write(f"{r.gid} | {str(r.raw_mid)[:30]} | {text}\n")
print(len(s), "records ->", E / "gold_texts.txt")
