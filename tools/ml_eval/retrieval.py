"""Similar-case retrieval: rule-classified records (silver labels) are the case base.
Applied only to records the rules did not auto-classify."""

import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import NONE, E, load, score


def embed_tfidf(texts):
    from sklearn.feature_extraction.text import TfidfVectorizer

    v = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True, min_df=1)
    X = v.fit_transform(texts)
    return X


def embed_fe(model, texts):
    from fastembed import TextEmbedding

    m = TextEmbedding(model, cache_dir=str(E.parent / "models/fe"), threads=4)
    prefix = "query: " if "e5" in model else ""
    X = np.array(list(m.embed([prefix + t for t in texts], batch_size=64)))
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def knn_predict(sim_row, pool_labels, k=5):
    idx = np.argsort(-sim_row)[:k]
    votes = defaultdict(float)
    for i in idx:
        for p in pool_labels[i] or [NONE]:
            votes[p] += sim_row[i]
    ranked = sorted(votes.items(), key=lambda x: -x[1])
    total = sum(v for _, v in ranked)
    top, topv = ranked[0]
    return top, topv / total, float(sim_row[idx[0]]), [(int(i), float(sim_row[i])) for i in idx]


def run(name, embed):
    base, gold = load()
    pool = base[(base.status == "규칙분류") & ~base.record_id.isin(gold.record_id)].reset_index(
        drop=True
    )
    texts = list(pool.text) + list(gold.text)
    X = embed(texts)
    P, G = X[: len(pool)], X[len(pool) :]
    S = G @ P.T
    S = S.toarray() if hasattr(S, "toarray") else S
    res = [knn_predict(S[i], list(pool.rule_parts)) for i in range(len(gold))]
    gold["knn_top"] = [r[0] for r in res]
    gold["knn_share"] = [r[1] for r in res]
    gold["knn_sim"] = [r[2] for r in res]
    gold["knn_neighbors"] = [[(pool.text[i], pool.rule_parts[i], s) for i, s in r[3]] for r in res]
    gold.to_pickle(E / f"knn_{name}.pkl")
    rows = []
    rest = gold.status != "규칙분류"
    for tau in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9):
        g = gold.copy()
        g["pred"] = [
            r if a else (k if k != NONE else [])
            for r, a, k in zip(g.rule_parts, g.status == "규칙분류", g.knn_top)
        ]
        g["pred"] = g.pred.map(lambda x: [x] if isinstance(x, str) else x)
        g["auto"] = (g.status == "규칙분류") | (rest & (g.knn_sim >= tau) & (g.knn_share >= 0.6))
        r = score(g, "pred", "auto", f"{name} tau={tau}")
        # accuracy of retrieval alone on the non-rule part
        sub = g[rest]
        r["rest_knn_primary_acc"] = np.average(
            [gp == k for gp, k in zip(sub.gold_primary, sub.knn_top)], weights=sub.w
        )
        rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    name = sys.argv[1]
    embed = embed_tfidf if name == "tfidf" else (lambda t: embed_fe(sys.argv[2], t))
    df = run(name, embed)
    pd.set_option("display.width", 250)
    print(
        df[
            [
                "method",
                "all_auto_rate",
                "all_auto_primary_acc",
                "clear_auto_primary_acc",
                "all_overall_primary_acc",
                "rest_knn_primary_acc",
            ]
        ]
        .round(3)
        .to_string()
    )
