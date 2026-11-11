"""Compare pipelines on the gold set, weighted back to the 3-year population."""

import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import NONE, E, load


def as_list(x):
    return list(x) if x else [NONE]


def metrics(g, pred, auto, name):
    rows = {}
    for subset, m in (("전체", np.ones(len(g), bool)), ("명확한 건만", ~g.ambiguous.values)):
        w = g.w.values[m]
        a = np.asarray(auto)[m]
        p = [as_list(x) for x, keep in zip(pred, m) if keep]
        gp = g.gold_primary.values[m]
        gs = g.gold.values[m]
        prim = np.array([x in y for x, y in zip(gp, p)])
        exact = np.array([set(x) == set(y) for x, y in zip(gs, p)])
        rows[f"{subset}|자동처리율"] = (w * a).sum() / w.sum()
        rows[f"{subset}|자동건 정확도(주부품)"] = (w * a * prim).sum() / max((w * a).sum(), 1e-9)
        rows[f"{subset}|자동건 정확도(부품 전체 일치)"] = (w * a * exact).sum() / max(
            (w * a).sum(), 1e-9
        )
        rows[f"{subset}|놓친 오류율(자동인데 틀림)"] = (w * a * ~prim).sum() / w.sum()
    return pd.Series(rows, name=name)


def load_llm(tag):
    p = E / f"llm_{tag}.jsonl"
    if not p.exists() or p.stat().st_size == 0:
        return None
    d = pd.DataFrame([json.loads(line) for line in open(p, encoding="utf-8")])
    return d.set_index("gid")


def main():
    base, gold = load()
    knn = pd.read_pickle(E / "knn_e5large.pkl").set_index("gid")
    g = gold.set_index("gid", drop=False)
    rule_auto = (g.status == "규칙분류").values
    out = [metrics(g, g.rule_parts, rule_auto, "① 규칙만 (현재)")]
    kp = [
        r if a else ([] if k == NONE else [k])
        for r, a, k in zip(g.rule_parts, rule_auto, knn.loc[g.gid, "knn_top"])
    ]
    out.append(metrics(g, kp, np.ones(len(g), bool), "② 규칙 + 유사사례(e5) 전부 자동"))
    for tag, label in (
        ("gemma4e2b", "Gemma4-E2B"),
        ("gemma4e4b", "Gemma4-E4B"),
        ("qwen3_4b", "Qwen3-4B"),
    ):
        d = load_llm(tag)
        if d is None or len(d) < len(g):
            print(f"[{tag}] {0 if d is None else len(d)}/{len(g)} done")
            if d is None:
                continue
        gg = g[g.gid.isin(d.index)]
        dd = d.loc[gg.gid]
        llm_parts = [p if dec != "none" else [] for p, dec in zip(dd.parts, dd.decision)]
        llm_auto = (dd.decision != "review").values
        ra = (gg.status == "규칙분류").values
        # ③ rules first, LLM for the rest
        p3 = [r if a else lp for r, a, lp in zip(gg.rule_parts, ra, llm_parts)]
        a3 = ra | llm_auto
        out.append(metrics(gg, p3, a3, f"③ 규칙 + {label}(나머지)"))
        # ④ rules + LLM cross-check: rule result kept only if LLM agrees on primary
        agree = np.array(
            [bool(r) and bool(lp) and r[0] in lp for r, lp in zip(gg.rule_parts, llm_parts)]
        )
        a4 = (ra & agree) | (~ra & llm_auto)
        out.append(metrics(gg, p3, a4, f"④ 규칙 + {label} 교차검증"))
        out.append(metrics(gg, llm_parts, llm_auto, f"⑤ {label} 단독"))
        out[-1]["평균 처리시간(초)"] = dd.sec.mean()
        # ⑥ strict agreement: auto only when rules (incl. provisional review parts) and LLM agree,
        # or both find no part; everything else goes to a person.
        both_none = np.array(
            [
                not r and not lp and dec == "none"
                for r, lp, dec in zip(gg.rule_parts, llm_parts, dd.decision)
            ]
        )
        p6 = [r if a else lp for r, a, lp in zip(gg.rule_parts, agree, llm_parts)]
        out.append(metrics(gg, p6, agree | both_none, f"⑥ 규칙·{label} 일치 시에만 자동"))
    df = pd.concat(out, axis=1).T
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print((df * 1).round(3).to_string())
    df.to_csv(E / "compare.csv")


if __name__ == "__main__":
    main()
