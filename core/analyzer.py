"""Select analysis records and assemble summary tables and review metrics."""

from __future__ import annotations

import re

import pandas as pd

from core.aggregation import (
    STAT_COLUMNS as STAT_COLUMNS,
)
from core.aggregation import (
    grouped as grouped,
)
from core.aggregation import (
    mode_text as mode_text,
)
from core.aggregation import (
    trend as trend,
)
from core.component_analysis import component_tables
from core.i18n import UNMATCHED, K
from core.models import AnalysisOptions, AnalysisResult, LoadedData
from core.preprocessing import review_target
from core.review_guidance import review_issues
from core.sorting import descending


def select_records(records: pd.DataFrame, options: AnalysisOptions) -> pd.DataFrame:
    selected = records.copy()
    if options.scope == "fault":
        selected = selected.loc[selected["kind"].eq(K["fault"])]
    elif options.scope != "all":
        raise ValueError("Unknown scope")
    if options.date_from:
        selected = selected.loc[selected["date"].ge(pd.Timestamp(options.date_from).normalize())]
    if options.date_to:
        selected = selected.loc[selected["date"].le(pd.Timestamp(options.date_to).normalize())]
    if options.factory is not None:
        selected = selected.loc[selected["factory"].eq(options.factory)]
    if options.team is not None:
        selected = selected.loc[selected["team"].eq(options.team)]
    if options.deduplicate:
        selected = selected.drop_duplicates("event_id", keep="first")
    return selected.reset_index(drop=True)


def analyze(
    loaded: LoadedData, records: pd.DataFrame, config: dict, options: AnalysisOptions
) -> AnalysisResult:
    if options.date_from and options.date_to and options.date_from > options.date_to:
        raise ValueError("Date range is reversed")
    d = select_records(records, options)
    known_products = d.loc[d["product"].ne(K["missing"])]
    tables = {
        "equipment": grouped(d, ["equipment"]),
        "line": grouped(d, ["line"]),
        "product": grouped(d, ["product"])
        if len(known_products)
        else grouped(d.iloc[:0], ["product"]),
        "type": grouped(d, ["type"]),
        "raw_kind": grouped(records, ["kind"]),
        "equipment_type": grouped(d, ["equipment", "type"]),
        "product_type": grouped(d, ["product", "type"]),
        "equipment_product": grouped(d, ["equipment", "product"]),
        "triple": grouped(d, ["equipment", "product", "type"]),
        **{f"trend_{f}": trend(d, f) for f in ("day", "week", "month", "year")},
        "long_stops": descending(d, "minutes").head(options.top_n).copy(),
    }
    tables.update(component_tables(d))
    component_counts = pd.to_numeric(
        d.get("component_count", pd.Series(0, index=d.index)), errors="coerce"
    ).fillna(0)
    tables["combination"] = grouped(d.loc[component_counts.gt(1)], ["type"])
    valid_count = int(d["minutes"].count())
    total = float(d["minutes"].sum(min_count=1)) if valid_count else None

    def period_of(frame):
        dates = frame["date"].dropna()
        return f"{dates.min():%Y-%m-%d} ~ {dates.max():%Y-%m-%d}" if len(dates) else K["unknown"]

    flagged = [
        re.escape(K[key]) for key in review_issues(review_target(config["settings"], options))
    ]
    review_mask = d["status"].isin([K["review"], *UNMATCHED]) | d["issues"].str.contains(
        "|".join(flagged), regex=True, na=False
    )
    review_columns = [
        "source_row",
        "raw_description",
        "review_reason",
        "review_action",
        "aggregation_effect",
        "status",
        "type",
        "minutes",
        "target",
        "issues",
        "candidates",
    ]
    review_frame = d.loc[review_mask]
    tables["review"] = descending(
        review_frame[review_columns + [c for c in review_frame.columns if c not in review_columns]],
        "minutes",
    )

    def issue_rows(key):
        return int(d["issues"].str.contains(K[key], regex=False, na=False).sum())

    metrics = {
        "source_rows": len(records),
        "selected_rows": len(d),
        "excluded_rows": len(records) - len(d),
        "fault_rows_source": int(records["kind"].eq(K["fault"]).sum()),
        "valid_time_rows": valid_count,
        "total_minutes": total,
        "mean_minutes": float(d["minutes"].mean()) if valid_count else None,
        "max_minutes": float(d["minutes"].max()) if valid_count else None,
        "mapped_name_rows": int(d["name_mapped"].sum()),
        "equipment_count": int(d["equipment"].nunique()),
        "line_count": int(d.loc[d["line"].ne(K["missing"]), "line"].nunique()),
        "registered_count": int(d.loc[d["registered"].ne(K["missing"]), "registered"].nunique()),
        "target_count": int(
            d.loc[~d["target"].isin([K["missing"], K["target_missing"]]), "target"].nunique()
        ),
        "missing_target_rows": int(d["target"].eq(K["target_missing"]).sum()),
        "product_count": int(known_products["product"].nunique()),
        "auto_rows": int(d["status"].eq(K["auto"]).sum()),
        "manual_rows": int(d["status"].isin([K["manual"], K["manual_multi"]]).sum()),
        "manual_multi_rows": int(d["status"].eq(K["manual_multi"]).sum()),
        "combination_rows": int(component_counts.gt(1).sum()),
        "unclassified_rows": int(d["status"].isin(UNMATCHED).sum()),
        "code_missing_rows": int(d["status"].eq(K["code_missing"]).sum()),
        "rule_unmatched_rows": int(d["status"].eq(K["rule_unmatched"]).sum()),
        "ambiguous_rows": issue_rows("multi_rule")
        + issue_rows("multiple_faults")
        + issue_rows("alternative_types"),
        "classification_review_rows": int(d["status"].eq(K["review"]).sum()),
        "alternative_type_rows": issue_rows("alternative_types"),
        "multiple_fault_rows": issue_rows("multiple_faults"),
        "auto_resolved_rows": int(
            (
                d["status"].eq(K["auto"])
                & d["evidence"].str.contains(K["auto_resolved"], regex=False, na=False)
            ).sum()
        ),
        "review_rows": int(review_mask.sum()),
        "date_missing_rows": int(d["date"].isna().sum()),
        "duplicate_candidate_rows": int(d["duplicate"].sum()),
        "period": period_of(d),
        "source_period": period_of(records),
    }
    notes = [
        K["names_note"],
        K["record_note"],
        K["no_cause"],
        K["time_note"],
        K["exposure_note"],
        K["fuzzy_note"],
    ]
    notes.append(
        "자동분류는 부품·증상 조건에 일치한 규칙을 사용합니다. 교체·고장·원인 표현과 MES 단서로 후보를 해소하며, 여러 부품을 하나의 고장·교체 표현으로 나열한 기록은 복수 유형 조합으로 분류하고, 해소되지 않는 후보와 독립 복수 고장은 사용자 확인이 필요합니다."
    )
    notes.append(
        "조합별 건수·정지시간은 기록당 한 번 집계합니다. 부품별 포함 건수는 중복을 허용하며 정지시간을 부품별로 배분하지 않습니다. 잠정검토 포함 건수를 별도로 표시합니다."
    )
    if loaded.profile == "mes_downtime_v1":
        notes.extend([K["reported_note"], K["rounding_note"]])
    if (
        not loaded.mapping.get("kind")
        and not loaded.mapping.get("kind_code")
        and config["settings"].get("assume_generic_is_failure", False)
    ):
        notes.append(K["kind_assumed"])
    if metrics["date_missing_rows"]:
        notes.append(
            f"{K['date_invalid']}: {metrics['date_missing_rows']} / {K['trend_tab']} \uc81c\uc678"
        )
    if options.equipment_basis == "family":
        notes.append(
            "\uc124\ube44\uad70\uc740 \ud0a4\uc6cc\ub4dc \uae30\ubc18 \ud6c4\ubcf4\uc774\uba70 \ud655\uc815 \uc124\ube44\uac00 \uc544\ub2d9\ub2c8\ub2e4."
        )
    if options.equipment_basis == "group":
        notes.append(
            "설비군별 건수와 정지시간은 각 원본 기록을 한 번씩 집계합니다. 보고서 설비명에 적용한 구분자 규칙과 직접 지정한 설비군을 사용합니다."
        )
    if not total:
        notes.append(K["zero_total"])
    return AnalysisResult(
        loaded, records, d, tables, options, metrics, notes, config["hash"], config
    )
