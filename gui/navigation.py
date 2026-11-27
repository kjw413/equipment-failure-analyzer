"""Navigation for the summary, review, records, and analysis workspaces."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class WorkspaceNavigation(QWidget):
    chart_requested = Signal(str)

    HISTORY_PAGES = (
        ("detail", "전체 기록"),
        ("raw", "원본 미리보기"),
    )
    ANALYSIS_PAGES = (
        ("equipment", "설비별"),
        ("line", "라인별"),
        ("detailed_equipment", "상세설비별"),
        ("type", "유형별"),
        ("equipment_types", "설비별 유형순위"),
    )

    def __init__(self, pages, parent=None):
        super().__init__(parent)
        self.pages = dict(pages)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("workspaceTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        layout.addWidget(self.tabs)

        self.history, history_layout, history_bar = self._section()
        self.history_choice, self.history_stack = self._add_selector(
            history_bar, history_layout, "고장이력 보기", self.HISTORY_PAGES
        )
        history_bar.addStretch()

        self.analysis, analysis_layout, analysis_bar = self._section()
        self.analysis_choice, self.analysis_stack = self._add_selector(
            analysis_bar, analysis_layout, "분석표 선택", self.ANALYSIS_PAGES
        )
        self.analysis_stack.addWidget(self.pages["cross"])
        self.analysis_stack.addWidget(self.pages["chart"])
        self.chart_button = QPushButton("그래프 보기")
        self.chart_button.clicked.connect(self._toggle_chart)
        analysis_bar.addWidget(self.chart_button)
        analysis_bar.addStretch()

        self.tabs.addTab(self.pages["summary"], "종합현황")
        self.tabs.addTab(self.pages["review"], "검토필요 · 분석 전")
        self.tabs.addTab(self.history, "고장이력")
        self.tabs.addTab(self.analysis, "상세분석")

    @staticmethod
    def _section():
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 0, 6, 0)
        layout.addLayout(bar)
        return page, layout, bar

    def _add_selector(self, bar, layout, name, entries):
        choice = QComboBox()
        choice.setAccessibleName(name)
        stack = QStackedWidget()
        for key, title in entries:
            choice.addItem(title, key)
            stack.addWidget(self.pages[key])
        choice.currentIndexChanged.connect(
            lambda: stack.setCurrentWidget(self.pages[choice.currentData()])
        )
        bar.addWidget(choice)
        layout.addWidget(stack, 1)
        return choice, stack

    def _set_chart_visible(self, visible):
        key = "chart" if visible else self.analysis_choice.currentData()
        self.analysis_stack.setCurrentWidget(self.pages[key])
        self.analysis_choice.setVisible(not visible)
        self.chart_button.setText("표 보기" if visible else "그래프 보기")

    def _toggle_chart(self):
        if self.analysis_stack.currentWidget() is self.pages["chart"]:
            self._set_chart_visible(False)
        else:
            self.chart_requested.emit(self.analysis_choice.currentData())
            self._set_chart_visible(True)

    def set_product_available(self, available):
        index = self.analysis_choice.findData("cross")
        if available and index == -1:
            self.analysis_choice.addItem("제품 교차분석", "cross")
        elif not available and index != -1:
            if self.analysis_choice.currentIndex() == index:
                chart_visible = self.analysis_stack.currentWidget() is self.pages["chart"]
                self.analysis_choice.setCurrentIndex(0)
                self._set_chart_visible(chart_visible)
            self.analysis_choice.removeItem(index)

    def show_page(self, key):
        if key in ("summary", "review"):
            self.tabs.setCurrentWidget(self.pages[key])
            return
        index = self.history_choice.findData(key)
        if index != -1:
            self.history_choice.setCurrentIndex(index)
            self.tabs.setCurrentWidget(self.history)
            return
        if key != "chart":
            index = self.analysis_choice.findData(key)
            self.analysis_choice.setCurrentIndex(max(0, index))
        self._set_chart_visible(key == "chart")
        self.tabs.setCurrentWidget(self.analysis)

    def current_page_key(self):
        page = self.tabs.currentWidget()
        if page is self.history:
            page = self.history_stack.currentWidget()
        elif page is self.analysis:
            page = self.analysis_stack.currentWidget()
        return next(key for key, widget in self.pages.items() if widget is page)

    def update_counts(self, review_rows=None, detail_rows=None):
        title = "검토필요 · 분석 전" if review_rows is None else f"검토필요 ({review_rows:,})"
        self.tabs.setTabText(self.tabs.indexOf(self.pages["review"]), title)
        title = "전체 기록" if detail_rows is None else f"전체 기록 ({detail_rows:,})"
        self.history_choice.setItemText(self.history_choice.findData("detail"), title)
