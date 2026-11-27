"""Organization comparisons and case trends share Excel's retained fault facts."""

from __future__ import annotations

from reportlab.platypus import Image, KeepTogether, Table, TableStyle

from core.issue_analysis import MISSING, case_months, issue_facts, issue_summary, priority_cases
from core.sorting import descending
from report.charts import chart_png
from report.formatting import number


class IssuePdf:
    def __init__(self, report):
        self.r = report
        self.facts = issue_facts(report.result.selected)
        self.organizations = (
            self.facts[["factory", "team"]].drop_duplicates().sort_values(["factory", "team"])
        )

    def note(self):
        self.r.story.append(
            self.r.p(
                "고장 기록만 집계합니다. 현상 미기재와 검토 중인 기록도 확인된 상세설비에 포함하며, 잠정 후보는 확정하지 않습니다. 사례 = 상세설비 / 고장 현상. 팀 미기재는 조직 연결표에서 보완할 수 있습니다.",
                "muted",
            )
        )

    def dual_cases(self, facts, limit=3):
        summary = issue_summary(facts, ["case"])
        ordered = {}
        for metric in ("count", "total_minutes"):
            eligible = summary if metric == "count" else summary.loc[summary.valid_count.gt(0)]
            ordered[metric] = descending(eligible.sort_values("case", kind="stable"), metric)
        labels = list(
            dict.fromkeys(
                [
                    *ordered["count"].head(limit)["case"],
                    *ordered["total_minutes"].head(limit)["case"],
                ]
            )
        )
        ranks = {
            key: {case: i for i, case in enumerate(table["case"], 1)}
            for key, table in ordered.items()
        }
        lookup = summary.set_index("case")
        rows = [
            [
                case,
                number(lookup.at[case, "count"]),
                number(lookup.at[case, "total_minutes"]),
                number(ranks["count"].get(case)),
                number(ranks["total_minutes"].get(case)),
                number(lookup.at[case, "review_count"]),
            ]
            for case in labels
        ]
        self.r.story.append(
            self.r.layout.table(
                ["고장사례", "건수", "정지(분)", "건수 순위", "시간 순위", "검토(건)"],
                rows,
                [self.r.width - 275, 43, 74, 53, 58, 47],
                (1, 2, 3, 4, 5),
            )
        )

    def organization(self):
        self.r.page("03  공장·팀별 주요 이슈")
        self.note()
        summary = issue_summary(self.facts, ["factory", "team"])
        rows = [
            [
                row["factory"],
                row["team"],
                number(row["count"]),
                number(row["total_minutes"]),
                number(row["review_count"]),
            ]
            for row in summary.to_dict("records")
        ]
        self.r.story.append(
            self.r.layout.table(
                ["공장", "팀", "건수", "정지(분)", "분류 검토(건)"],
                rows,
                [110, self.r.width - 340, 60, 100, 70],
                (2, 3, 4),
            )
        )
        for factory, team in self.organizations.itertuples(index=False, name=None):
            self.r.story.append(self.r.p(f"{factory} / {team}", "h2"))
            self.r.story.append(
                self.r.p(
                    "발생 건수 TOP 3와 정지시간 TOP 3를 모두 포함합니다. 같은 이력의 두 순위를 합산하지 않습니다.",
                    "small",
                )
            )
            self.dual_cases(
                self.facts.loc[self.facts.factory.eq(factory) & self.facts.team.eq(team)]
            )

    def comparison_table(self, selected):
        summary = issue_summary(selected, ["factory", "team"]).set_index(["factory", "team"])
        values = []
        for factory, team in self.organizations.itertuples(index=False, name=None):
            item = summary.loc[(factory, team)] if (factory, team) in summary.index else None
            values.append(
                (
                    factory,
                    team,
                    int(item["count"]) if item is not None else 0,
                    item["total_minutes"] if item is not None else 0,
                )
            )
        baseline = values[0] if values else ("-", "-", 0, 0)
        self.r.story.append(
            self.r.p(
                f"기준 조직: {baseline[0]} / {baseline[1]} · 차이 = 해당 조직 - 기준 조직", "small"
            )
        )
        rows = [
            [
                factory,
                team,
                number(count),
                number(minutes),
                number(count - baseline[2]),
                number(minutes - baseline[3]),
            ]
            for factory, team, count, minutes in values
        ]
        self.r.story.append(
            self.r.layout.table(
                ["공장", "팀", "건수", "정지(분)", "건수 차이", "정지 차이(분)"],
                rows,
                [90, self.r.width - 400, 50, 85, 75, 100],
                (2, 3, 4, 5),
            )
        )

    def comparison_block(self, title, selected):
        start = len(self.r.story)
        self.r.story.append(self.r.p(title, "h2"))
        self.comparison_table(selected)
        self.r.story[start:] = [KeepTogether(self.r.story[start:])]

    def cases(self):
        chosen = str(self.r.settings.get("focus_case", "")).strip()
        return [chosen] if chosen else priority_cases(self.facts, 3)

    def comparisons(self):
        self.r.page("04  동일 설비·사례의 조직 간 비교")
        self.r.story.append(
            self.r.p(
                "동종 설비는 상세설비 종류로, 같은 고장사례는 상세설비·부품·현상 조합으로 비교합니다. 개별 자산명과 상세설비 종류를 구분합니다. 가동시간·생산량 보정 전의 기록 건수·시간 차이입니다. 현재 선택한 공장·팀 범위만 포함합니다.",
                "muted",
            )
        )
        if self.facts.empty:
            self.r.story.append(self.r.p("선택 범위에 고장 기록이 없습니다.", "muted"))
            return
        module_summary = issue_summary(self.facts, ["module"])
        module_summary = module_summary.loc[module_summary["module"].ne(MISSING["module"])]
        if module_summary.empty:
            self.r.story.append(
                self.r.p(
                    "상세설비가 확인된 자동 비교 대상이 없습니다. 미상 기록은 조직별 총계와 Excel에 보존합니다.",
                    "muted",
                )
            )
        modules = []
        for metric in ("count", "total_minutes"):
            modules.extend(descending(module_summary, metric).head(2)["module"])
        for module in dict.fromkeys(modules):
            self.comparison_block(
                f"상세설비 종류: {module}", self.facts.loc[self.facts.module.eq(module)]
            )
        for case in self.cases():
            self.comparison_block(case, self.facts.loc[self.facts["case"].eq(case)])

    def trends(self):
        calendar = case_months(self.facts)
        cases = self.cases()
        self.r.page("05  고장사례별 월간 변화")
        self.r.story.append(
            self.r.p(
                "보고서 설정에서 고장사례를 선택하면 해당 사례를 표시합니다. 자동선정 시 건수·정지시간 주요 사례를 함께 선정합니다. 날짜 미상 기록은 추이에서 제외하며, 0은 해당 사례 기록 없음, 빈칸은 시간 미기재입니다. 첫·마지막 월은 부분기간일 수 있습니다. Excel 03.월별 주요이슈에서 공장·팀·라인·상세설비을 바꿔 확인할 수 있습니다.",
                "muted",
            )
        )
        if not cases:
            self.r.story.append(
                self.r.p(
                    "자동선정할 고장사례가 없습니다. 상세설비 미기재 기록은 Excel에서 확인하세요.",
                    "muted",
                )
            )
        for case in cases:
            self.r.story.append(self.r.p(case, "h2"))
            table = case_months(self.facts.loc[self.facts["case"].eq(case)], calendar["period"])
            if table.empty:
                self.r.story.append(
                    self.r.p("선택한 범위에 해당 고장사례의 월별 기록이 없습니다.", "muted")
                )
                continue
            images = []
            for metric in ("count", "total_minutes"):
                buffer = chart_png(table, "period", metric, "trend")
                self.r.buffers.append(buffer)
                images.append(Image(buffer, width=self.r.width / 2 - 5, height=140))
            chart = Table([images], colWidths=[self.r.width / 2] * 2)
            chart.setStyle(
                TableStyle(
                    [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]
                )
            )
            self.r.story.append(chart)
            rows = [
                [
                    row["period"],
                    number(row["count"]),
                    number(row["total_minutes"]),
                    number(row["valid_count"]),
                    number(row["review_count"]),
                ]
                for row in table.to_dict("records")
            ]
            self.r.story.append(
                self.r.layout.table(
                    ["월", "건수", "정지(분)", "시간 유효(건)", "분류 검토(건)"],
                    rows,
                    [100, 80, 125, 100, self.r.width - 405],
                    (1, 2, 3, 4),
                )
            )
