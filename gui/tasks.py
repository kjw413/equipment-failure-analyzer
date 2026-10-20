"""Background work for the desktop interface."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QThread, Signal

from core.models import UserError


class Task(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, function: Callable, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            result = self.function(self.progress.emit)
        except UserError as exc:
            self.failed.emit(str(exc))
        except Exception:
            logging.getLogger(__name__).exception("Processing failed")
            self.failed.emit(
                "\ucc98\ub9ac \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4. \uc124\uc815 \ud3f4\ub354\uc758 logs\ub97c \ud655\uc778\ud558\uc138\uc694."
            )
        else:
            self.succeeded.emit(result)
