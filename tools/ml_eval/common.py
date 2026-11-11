"""Shared data loading, text cleaning and weighted scoring for the classifier comparison."""

import json
import os
import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("ML_EVAL_DIR", REPO / "ml_eval_work")).resolve()
E = WORK / "exp"
E.mkdir(parents=True, exist_ok=True)
CATALOG = json.load(open(REPO / "config/classification_catalog.json", encoding="utf-8"))
GROUPS = [g["middle"] for g in CATALOG["groups"]]
NONE = "없음"
SEG_NAME = re.compile(
    r"^\s*(?:(?:공무|기계|전기|생산|op|조치자\s*:)\s*(?:팀|반)?\s*)?[가-힣]{2,3}(?:\s*(?:님)?\s*[,·& ]\s*[가-힣]{2,3})*\s*(?:님)?\s*$",
    re.I,
)
SEG_DEPT = re.compile(r"^\s*(?:공무|기계|전기|생산|공무팀|기계반|전기반)\s*(?:팀|반)?\s*$")


def clean(text: str) -> str:
    """Drop '/'-separated segments that are only worker names or a department."""
    text = re.sub(r"[\r\n]+", " ", str(text))
    segs = [
        s for s in text.split("/") if s.strip() and not SEG_NAME.match(s) and not SEG_DEPT.match(s)
    ]
    return " / ".join(s.strip() for s in segs) or text.strip()


def rule_parts(details: str) -> list[str]:
    if not details:
        return []
    return list(
        dict.fromkeys(c.get("part_group") for c in json.loads(details) if c.get("part_group"))
    )


def load():
    base = pd.read_pickle(E / "baseline.pkl")
    gold = pd.read_pickle(E / "gold.pkl")
    base["text"] = base.raw_description.map(clean)
    gold["text"] = gold.raw_description.map(clean)
    base["rule_parts"] = base.component_details.map(rule_parts)
    gold["rule_parts"] = gold.component_details.map(rule_parts)
    weights = base.status.value_counts() / gold.status.value_counts()
    gold["w"] = gold.status.map(weights)
    return base, gold


def score(gold: pd.DataFrame, pred_col: str, auto_col: str, label: str = "") -> dict:
    """pred_col: list of groups ([] = '없음'). auto_col: True when the method decides without a human.
    Accuracy on auto decisions, weighted back to the full 3-year population."""
    out = {"method": label}
    for name, sub in (("all", gold), ("clear", gold[~gold.ambiguous])):
        p = sub[pred_col].map(lambda x: list(x) if x else [NONE])
        g = sub.gold
        prim = [gp in pp for gp, pp in zip(sub.gold_primary, p)]
        exact = [set(a) == set(b) for a, b in zip(g, p)]
        auto = sub[auto_col].astype(bool)
        w = sub.w
        out[f"{name}_auto_rate"] = (w * auto).sum() / w.sum()
        out[f"{name}_auto_primary_acc"] = (w * auto * pd.Series(prim, index=sub.index)).sum() / max(
            (w * auto).sum(), 1e-9
        )
        out[f"{name}_auto_exact_acc"] = (w * auto * pd.Series(exact, index=sub.index)).sum() / max(
            (w * auto).sum(), 1e-9
        )
        out[f"{name}_overall_primary_acc"] = (w * pd.Series(prim, index=sub.index)).sum() / w.sum()
    return out
