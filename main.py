"""Windows desktop entry point. No server, browser or external API is used."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from core.config import ConfigStore, resource_root, user_root
from version import APP_ID, APP_NAME, VERSION


def main() -> int:
    from PySide6.QtCore import QLockFile, QTimer
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    organization_name = "LocalManufacturingTools"
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        from ctypes import windll

        # Give the source app its own taskbar identity before Qt creates any windows.
        windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{organization_name}.{APP_ID}")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setOrganizationName(organization_name)
    app.setApplicationVersion(VERSION)
    app.setFont(QFont(["BinggraeⅡ", "빙그레체Ⅱ", "Malgun Gothic"], 10))
    app.setWindowIcon(QIcon(str(resource_root() / "assets" / "equipment-failure.ico")))
    # One writer per user profile prevents concurrent auto-save races.
    root = user_root()
    root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(root / "desktop.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(
            None,
            APP_NAME,
            "\ud504\ub85c\uadf8\ub7a8\uc774 \uc774\ubbf8 \uc2e4\ud589 \uc911\uc785\ub2c8\ub2e4. \uae30\uc874 \ucc3d\uc744 \ud655\uc778\ud558\uc138\uc694.",
        )
        return 1
    try:
        store = ConfigStore(root)
        handler = RotatingFileHandler(
            store.log_dir / "application.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[handler])
        from gui.main_window import MainWindow

        window = MainWindow(store)
        screen = app.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            window.resize(min(1430, int(area.width() * 0.95)), min(940, int(area.height() * 0.94)))
        window.show()
        args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
        if args:
            QTimer.singleShot(0, lambda: window.load_path(args[0]))
        return app.exec()
    except Exception as exc:
        logging.exception("Startup failure")
        QMessageBox.critical(
            None, APP_NAME, "\ud504\ub85c\uadf8\ub7a8 \uc2dc\uc791 \uc624\ub958\n" + str(exc)
        )
        return 1
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
