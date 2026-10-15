# Run on Windows. A single real EXE; no font files or factory inputs bundled.
from pathlib import Path
ROOT=Path(SPECPATH)
a=Analysis([str(ROOT/'main.py')], pathex=[str(ROOT)], binaries=[],
    datas=[(str(ROOT/'config'),'config')],
    hiddenimports=['matplotlib.backends.backend_qtagg', 'reportlab.pdfbase._fontdata', 'reportlab.pdfbase.ttfonts'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter','PyQt5','PyQt6','PySide2','pytest'], noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='EquipmentFailureAnalyzer',
        debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
        console=False,disable_windowed_traceback=False)
