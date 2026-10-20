"""The seven workspace sections, with related analyses kept together."""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class WorkspaceNavigation(QWidget):
    TOP_PAGES = (
        ("summary", "종합현황"),
        ("review", "검토필요"),
        ("analysis", "상세분석"),
        ("equipment_types", "설비별 유형순위"),
        ("component", "부품별 포함 건수"),
        ("component_trend", "월별 부품 추이"),
        ("chart", "그래프"),
    )
    ANALYSIS_PAGES = (
        ("equipment", "설비별"),
        ("line", "라인별"),
        ("type", "유형별"),
        ("cross", "교차분석"),
        ("detail", "전체 기록 · 수정"),
        ("raw", "원본 확인"),
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
        self.tabs.setUsesScrollButtons(True)
        self.analysis_tabs = QTabWidget()
        self.analysis_tabs.setObjectName("analysisTabs")
        self.analysis_tabs.setDocumentMode(True)
        for key, title in self.ANALYSIS_PAGES:
            self.analysis_tabs.addTab(self.pages[key], title)
        self.pages["analysis"] = self.analysis_tabs
        for key, title in self.TOP_PAGES:
            self.tabs.addTab(self.pages[key], title)
            self.tabs.setTabToolTip(self.tabs.count() - 1, title)
        layout.addWidget(self.tabs)

    def show_page(self, key):
        if key in dict(self.ANALYSIS_PAGES):
            self.tabs.setCurrentWidget(self.analysis_tabs)
            self.analysis_tabs.setCurrentWidget(self.pages[key])
        else:
            self.tabs.setCurrentWidget(self.pages[key])

    def current_page_key(self):
        page = self.tabs.currentWidget()
        if page is self.analysis_tabs:
            page = self.analysis_tabs.currentWidget()
        return next(key for key, widget in self.pages.items() if widget is page)

    def update_counts(self, review_rows=0, detail_rows=0):
        index = self.tabs.indexOf(self.pages["review"])
        self.tabs.setTabText(index, f"검토필요 ({review_rows:,})")
        index = self.analysis_tabs.indexOf(self.pages["detail"])
        self.analysis_tabs.setTabText(index, f"전체 기록 · 수정 ({detail_rows:,})")
