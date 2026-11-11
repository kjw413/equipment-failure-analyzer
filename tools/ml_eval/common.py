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
SURNAMES = set(
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉사부가복태목형피두감음빈동온호범좌팽승간상갈"
)
# 3-letter words that start like a surname but are not names.
NOT_NAMES = set(
    "정상화 조정후 교체후 점검후 조치후 정리후 조립후 이송부 이탈됨 전기반 기계반 공무팀 생산팀 정비반 "
    "안전문 전원부 정지됨 이상무 이물질 장착부 고정부 구동부 진행중 재가동 재조정 재셋팅 재부팅 "
    "고장남 고장후 이상함 작동후 가동중 가동후 정지후 확인후 교체중 정비중 조정중 체결후 용접후 "
    "제상후 인피드 인입부 배출부 공급부 이송중 전후진 상하강 좌우측 정위치 원점화 연결부 이음부 하단부 상단부".split()
)
DEPT_WORDS = {
    "공무",
    "기계",
    "전기",
    "생산",
    "공무팀",
    "기계반",
    "전기반",
    "정비반",
    "생산팀",
    "op",
    "조치자",
}


def is_name(token: str) -> bool:
    token = token.removesuffix("님")
    return (
        bool(re.fullmatch(r"[가-힣]{3}", token)) and token[0] in SURNAMES and token not in NOT_NAMES
    )


def is_signature(segment: str) -> bool:
    """True when a '/'-separated segment holds only worker names and/or a department word."""
    seg = re.sub(r"^\s*op(?=[가-힣])", "op ", segment.strip(), flags=re.I)
    tokens = [t for t in re.split(r"[\s,·&:]+", seg) if t]
    rest = [t for t in tokens if t.lower() not in DEPT_WORDS]
    if not tokens:
        return False
    return all(is_name(t) for t in rest)


def clean(text: str) -> str:
    """Drop '/'-separated segments that are only worker names or a department."""
    text = re.sub(r"[\r\n]+", " ", str(text))
    segs = [s for s in text.split("/") if s.strip() and not is_signature(s)]
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
