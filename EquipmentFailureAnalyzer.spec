# Run on Windows. A single real EXE; no font files or factory inputs bundled.
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
ICON = ROOT / "assets" / "equipment-failure.ico"
# Dependency discovery must not collect stale DLLs from unrelated tools on PATH.
# Qt and scientific-package hooks add their own wheel directories explicitly.
windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
build_paths = [
    Path(sys.executable).parent,
    Path(sys.base_prefix),
    Path(sys.base_prefix) / "DLLs",
    windows / "System32",
    windows,
]
os.environ["PATH"] = os.pathsep.join(str(path) for path in build_paths if path.is_dir())
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "config"), "config"), (str(ICON), "assets")],
    hiddenimports=["matplotlib.backends.backend_qtagg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EquipmentFailureAnalyzer",
    icon=str(ICON),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
