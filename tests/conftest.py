"""Shared synthetic workbooks and current isolated profiles for regression tests."""

import gc
import importlib.util
import json
import os
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from core.config import ConfigStore
from core.excel_loader import load_excel
from core.i18n import K
from core.models import AnalysisOptions
from core.service import run_analysis


@pytest.fixture(scope="session", autouse=True)
def qt_application_lifetime():
    """Keep Qt alive until deferred widget deletion and Python cycles are drained.

    Per-module app fixtures reuse this instance. Without a session owner, hidden
    popup/signal cycles can outlive their application during interpreter shutdown.
    Pure-core environments without the GUI dependency still run their tests.
    """
    if importlib.util.find_spec("PySide6") is None:
        yield
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    yield
    for widget in application.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    gc.collect()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    application.quit()


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path / "profile")


@pytest.fixture
def input_file(tmp_path):
    path = tmp_path / "synthetic_input.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Events"
    ws.merge_cells("A1:I1")
    ws["A1"] = "SYNTHETIC TEST DATA - NOT FACTORY RECORDS"
    headers = [
        "\ubc1c\uc0dd\uc77c",
        "\uc124\ube44\ucf54\ub4dc",
        "\uc124\ube44\uba85",
        "\uc81c\ud488\uba85",
        "\uace0\uc7a5\ub0b4\uc6a9",
        "\uc815\uc9c0\uc2dc\uac04",
        "\uc815\uc9c0\uad6c\ubd84",
        "\uace0\uc7a5\uc2dc\uc791",
        "\uace0\uc7a5\uc885\ub8cc",
    ]
    ws.append([None])
    ws.append(headers)
    rows = [
        [
            "2026-01-01",
            "IF18115",
            "Original counter",
            "Product A",
            "motor trip",
            10,
            K["fault"],
            "08:00",
            "08:10",
        ],
        [
            "2026-01-01",
            "IF18115",
            "Original counter",
            "Product B",
            "motor trip",
            20,
            K["fault"],
            "09:00",
            "09:20",
        ],
        [
            "2026-01-02",
            "IF20000",
            "Counter 2",
            "Product A",
            "\uc13c\uc11c \uac10\uc9c0\ubd88\ub7c9",
            "1\uc2dc\uac04 5\ubd84",
            K["fault"],
            "10:00",
            "11:05",
        ],
        [
            "2026-01-03",
            "IF18115",
            "Original counter",
            "Product A",
            "CIP",
            60,
            K["planned"],
            "08:00",
            "09:00",
        ],
        [
            "2026-01-03",
            "IF20000",
            "Counter 2",
            "Product A",
            "\uc790\uc138\ud55c \ub0b4\uc6a9 \uc5c6\uc74c",
            None,
            K["fault"],
            None,
            None,
        ],
    ]
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


@pytest.fixture(scope="session")
def approved_catalog_paths():
    """Frozen from the user-approved workbook and later user decisions, independently of rules."""
    fixture = Path(__file__).parent / "fixtures" / "catalog_2025_2026_paths.json"
    frozen = json.loads(fixture.read_text(encoding="utf-8"))
    paths = frozen["paths"] + frozen.get("user_decision_paths", {}).get("paths", [])
    return {tuple(path) for path in paths}


@pytest.fixture
def catalog_input(input_file):
    """Exercise concrete catalog types while retaining known counts and time cases."""
    workbook = load_workbook(input_file)
    sheet = workbook.active
    for row, description in {
        4: "도징펌프 파손 / 별도로 근접센서 고장",
        5: "로터리펌프 파손 교체",
        6: "타이밍벨트 파손 교체",
        8: "로드리스 실린더 파손 교체",
    }.items():
        sheet.cell(row, 5, description)
    workbook.save(input_file)
    workbook.close()
    return input_file


def analyze_file(store, path, options=None):
    cfg = store.load()
    loaded = load_excel(path, cfg["column_mapping"])
    return run_analysis(loaded, cfg, options or AnalysisOptions())


def finalize_classifications(store, path, options=None):
    """Simulate explicit user choices for publication/rollback test fixtures."""
    from core.classification_policy import unresolved_classifications

    result = analyze_file(store, path, options)
    for event_id in unresolved_classifications(result.selected).event_id:
        store.update_override(
            event_id,
            {
                "major": "기계",
                "detail_equipment": "상세설비 미상",
                "middle": "베어링(종류 미상)",
                "minor": "손상·파손",
            },
        )
    return analyze_file(store, path, options)
