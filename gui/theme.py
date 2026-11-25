"""Shared desktop stylesheet."""

STYLE = """
QMainWindow, QDialog { background: #F3F4F6; color: #25313B; }
QLabel { color: #25313B; }
QLabel#muted { color: #697681; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#dropTitle { font-size: 15px; font-weight: 600; }
QFrame#dropArea { background: #FFFFFF; border: 2px dashed #AAB3BC; border-radius: 10px; }
QPushButton { background: #FFFFFF; border: 1px solid #C5CCD3; border-radius: 5px; padding: 7px 13px; min-height: 20px; }
QPushButton:hover { background: #E8EDF1; }
QPushButton:checked { background: #E5E9ED; border-color: #98A8B5; }
QToolButton { background: white; border: 1px solid #C5CCD3; border-radius: 5px; padding: 7px 16px 7px 10px; min-height: 20px; }
QToolButton:hover { background: #E8EDF1; }
QMenu { background: white; border: 1px solid #C5CCD3; padding: 5px; }
QMenu::item { padding: 7px 20px; }
QMenu::item:selected { background: #D9E4ED; color: #172A3A; }
QPushButton:disabled { color: #A7AFB7; background: #F2F3F4; }
QPushButton#primary { background: #354451; color: white; border: 1px solid #354451; font-weight: 600; }
QPushButton#primary:disabled { background: #ADB6BE; border-color: #ADB6BE; }
QLineEdit, QComboBox, QSpinBox, QDateEdit { background: white; border: 1px solid #C9D0D6; padding: 5px; border-radius: 4px; min-height: 19px; }
QLineEdit:read-only { background: #F1F3F5; color: #626F7B; }
QTableView, QTableWidget { background: white; alternate-background-color: #F5F7F8; gridline-color: #E6E9ED; border: 1px solid #D4DAE0; selection-background-color: #D9E4ED; selection-color: #172A3A; }
QHeaderView::section { background: #E8ECF0; color: #34414E; font-weight: 600; padding: 7px; border: 0; border-right: 1px solid #D6DCE1; border-bottom: 1px solid #D6DCE1; }
QTabWidget::pane { border: 1px solid #D2D9DF; background: white; }
QTabBar::tab { background: #E5E9ED; padding: 9px 13px; border: 1px solid #D2D9DF; }
QTabBar::tab:selected { background: white; border-bottom-color: white; font-weight: 600; }
QTabWidget#workspaceTabs > QTabBar::tab { padding: 11px 12px; }
QTabWidget#workspaceTabs > QTabBar::tab:selected { background: #354451; color: white; border-color: #354451; }
QGroupBox { border: 1px solid #D4DBE1; border-radius: 6px; margin-top: 13px; padding-top: 12px; background: white; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QProgressBar { border: 1px solid #CFD7DE; border-radius: 4px; text-align: center; background: white; max-height: 20px; }
QProgressBar::chunk { background: #758D9E; }
QTextBrowser { background: white; border: none; }
"""
