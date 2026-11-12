from __future__ import annotations

import textwrap
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import pandas as pd
from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from core.i18n import K
from core.sorting import descending

_FONT = None


def chart_font() -> str:
    global _FONT
    if _FONT is None:
        available = {f.name for f in font_manager.fontManager.ttflist}
        _FONT = next(
            (
                n
                for n in (
                    "KoPubWorldDotum",
                    "KoPubWorld Dotum",
                    "Malgun Gothic",
                    "NanumGothic",
                    "Noto Sans CJK JP",
                    "DejaVu Sans",
                )
                if n in available
            ),
            "DejaVu Sans",
        )
    return _FONT


def tidy_label(value: str, width: int = 23) -> str:
    s = str(value)
    if s.startswith("[") and "]" in s:
        s = s.split("]", 1)[1]
    if s.startswith("복수 고장 / "):
        members = s.split(" / ", 2)[-1].split(" + ")
        labels = [member.split(" / ", 2)[-1] for member in members]
        # Keep both leading members visible instead of silently dropping all but
        # the final taxonomy token. Full member names remain in detail tables.
        extra = f" 외 {len(labels) - 2}유형" if len(labels) > 2 else ""
        budget = max(4, (width * 2 - len("복수:  + ") - len(extra)) // min(2, len(labels)))
        shown = [
            label if len(label) <= budget else label[: budget - 1] + "…" for label in labels[:2]
        ]
        s = "복수: " + " + ".join(shown) + extra
    elif s.count(" / ") >= 2:
        s = " / ".join(s.split(" / ")[-2:])
    lines = textwrap.wrap(s, width=width, break_long_words=True)
    if len(lines) > 2:
        lines = [lines[0], lines[1][:-1] + "…"]
    return "\n".join(lines[:2])


def figure_for(
    table: pd.DataFrame, key: str, metric: str = "total_minutes", kind: str = "bar", top_n: int = 10
) -> Figure:
    font = chart_font()
    fig = Figure(figsize=(7.4, 4.1), dpi=140, facecolor="white")
    ax = fig.add_subplot(111)
    title = f"{K.get(key, key)} | {K['total'] if metric == 'total_minutes' else K['count']}"
    if kind == "trend":
        title = K["trend_tab"] + " | " + (K["total"] if metric == "total_minutes" else K["count"])
    if kind == "pareto":
        title = "Pareto | " + (K["total"] if metric == "total_minutes" else K["count"])
    ax.set_title(title, fontname=font, fontsize=13, loc="left", pad=14, fontweight="bold")
    if table.empty or metric not in table or table[metric].notna().sum() == 0:
        ax.text(
            0.5,
            0.5,
            K["empty"],
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontname=font,
            fontsize=12,
        )
        ax.set_axis_off()
        return fig
    if kind == "trend":
        data = table.sort_values(key, kind="stable").copy()
        ax.plot(
            range(len(data)), data[metric].astype(float), marker="o", color="#525F6B", linewidth=2
        )
        step = max(1, len(data) // 12)
        ax.set_xticks(
            range(0, len(data), step),
            [str(x) for x in data[key].iloc[::step]],
            rotation=30,
            ha="right",
            fontname=font,
            fontsize=8,
        )
        ax.grid(axis="y", alpha=0.18)
    elif kind == "pareto":
        full = descending(table, metric)
        data = full.head(top_n).copy()
        values = data[metric].fillna(0).astype(float)
        ax.bar(range(len(data)), values, color="#697681")
        ax.set_xticks(
            range(len(data)),
            [f"{i + 1}. " + tidy_label(v, 16) for i, v in enumerate(data[key])],
            fontname=font,
            fontsize=8,
            rotation=22,
            ha="right",
        )
        total = full[metric].sum(min_count=1)
        if pd.notna(total) and total > 0:
            axis = ax.twinx()
            axis.plot(
                range(len(data)),
                values.cumsum() / total * 100,
                color="#262D35",
                marker="o",
                linewidth=1.8,
            )
            axis.set_ylim(0, 105)
            axis.set_ylabel(K["cumulative"] + " (%)", fontname=font, fontsize=9)
            axis.axhline(80, color="#AAB2B9", linestyle="--", linewidth=0.8)
            axis.spines[["top", "left"]].set_visible(False)
        ax.set_xlabel(
            "\uc21c\uc704 (\uc804\uccb4 \ud569\uacc4 \ub300\ube44 \ub204\uc801)",
            fontname=font,
            fontsize=9,
        )
        ax.grid(axis="y", alpha=0.18)
    else:
        data = descending(table, metric).head(top_n).iloc[::-1]
        values = data[metric].fillna(0).astype(float)
        bars = ax.barh(range(len(data)), values, color="#697681", height=0.63)
        ax.set_yticks(
            range(len(data)), [tidy_label(x) for x in data[key]], fontname=font, fontsize=8.5
        )
        for bar, value in zip(bars, values):
            ax.text(
                value + max(1, values.max() * 0.014),
                bar.get_y() + bar.get_height() / 2,
                f"{value:,.0f}",
                va="center",
                fontname=font,
                fontsize=8.5,
            )
        ax.set_xlim(0, max(1, values.max() * 1.19))
        ax.grid(axis="x", alpha=0.15)
        ax.set_xlabel(
            K["minutes_unit"] if metric == "total_minutes" else K["count"],
            fontname=font,
            fontsize=9,
        )
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#C9CED3")
    ax.tick_params(axis="both", length=0, pad=6)
    fig.tight_layout(pad=1.7)
    return fig


def chart_png(
    table: pd.DataFrame, key: str, metric: str = "total_minutes", kind: str = "bar", top_n: int = 10
) -> BytesIO:
    return _figure_png(figure_for(table, key, metric, kind, top_n))


def _figure_png(fig: Figure) -> BytesIO:
    """Encode a figure and release its artists, including failed renders."""
    buffer = BytesIO()
    try:
        FigureCanvasAgg(fig).print_png(buffer)
        buffer.seek(0)
        return buffer
    except BaseException:
        buffer.close()
        raise
    finally:
        fig.clear()


def donut_figure(
    table: pd.DataFrame, equipment: str, top_n: int = 5, metric: str = "count"
) -> Figure:
    """A 100% composition view of ONE asset, with readable legend values.

    The default denominator includes all classified, unclassified and review
    records for this equipment. 'Other' carries the full remaining count.
    """
    from core.equipment_breakdown import donut_slices

    data = donut_slices(table, metric, top_n)
    font = chart_font()
    fig = Figure(figsize=(11.8, 4.0), dpi=160)
    ax = fig.add_axes([0.035, 0.13, 0.37, 0.73])
    fig.text(0.035, 0.94, str(equipment), fontname=font, fontsize=16, fontweight="bold")
    is_count = metric == "count"
    subtitle = (
        "\uace0\uc7a5\uc720\ud615 \uad6c\uc131\ube44 | \uc774 \uc124\ube44\uc758 "
        + ("\uc804\uccb4 \uac74\uc218" if is_count else "\uc815\uc9c0\uc2dc\uac04")
        + "=100%"
    )
    fig.text(0.035, 0.88, subtitle, fontname=font, fontsize=10)
    if data.empty:
        ax.text(
            0.5,
            0.5,
            "\uc9d1\uacc4 \uac00\ub2a5\ud55c \uac12 \uc5c6\uc74c",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontname=font,
        )
        ax.set_axis_off()
        return fig

    def percentage(value):
        return f"{value:.1f}%" if value >= 4 else ""

    wedges, _, _ = ax.pie(
        data.value,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.36},
        autopct=percentage,
        pctdistance=0.81,
        textprops={"fontsize": 10, "fontname": font},
    )
    total = float(data.value.sum())
    text = f"{total:,.0f}" if is_count else f"{total:,.1f}"
    ax.text(0, 0.08, text, ha="center", va="center", fontname=font, fontsize=27, fontweight="bold")
    ax.text(
        0,
        -0.22,
        "\uc804\uccb4 \uac74\uc218" if is_count else "\uc804\uccb4 \uc815\uc9c0(\ubd84)",
        ha="center",
        va="center",
        fontname=font,
        fontsize=10,
    )
    labels = []
    for item in data.to_dict("records"):
        label = str(item["type"])
        if label.count(" / ") >= 2:
            _, middle, minor = label.split(" / ", 2)
            label = middle + " | " + minor
        label = "\n".join(textwrap.wrap(label, width=32) or [""])
        unit = "\uac74" if is_count else "\ubd84"
        labels.append(f"{label}   {item['value']:,.0f}{unit}  ({item['share']:.1%})")
    fig.legend(
        wedges,
        labels,
        loc="center left",
        bbox_to_anchor=(0.43, 0.50),
        frameon=False,
        prop={"family": font, "size": 10},
        labelspacing=1.05,
        handlelength=1.3,
    )
    fig.text(
        0.035,
        0.035,
        "\uc0c1\uc704 "
        + str(top_n)
        + "\uac1c + \uae30\ud0c0 | \ubaa8\ub4e0 \uc720\ud615\uc740 \uc0c1\uc138\ud45c\uc5d0 \ud45c\uc2dc",
        fontname=font,
        fontsize=9,
    )
    return fig


def donut_png(
    table: pd.DataFrame, equipment: str, top_n: int = 5, metric: str = "count"
) -> BytesIO:
    return _figure_png(donut_figure(table, equipment, top_n, metric))
