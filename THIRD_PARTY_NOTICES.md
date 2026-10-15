# Third-party components

The application uses Python, PySide6/Qt, pandas, NumPy, openpyxl, Matplotlib,
Pillow, ReportLab, and PyInstaller. Their original licenses continue to apply.
No font files are redistributed in this project. Charts use installed system fonts.

Before internal deployment, retain the original third-party license files and
review your organization's software distribution/approval requirements.
The build script targets a single EXE; no prebuilt executable is included here.

Primary documentation:
- https://docs.reportlab.com/
- https://pypdf.readthedocs.io/ (test dependency only)
- https://doc.qt.io/qtforpython-6/
- https://doc.qt.io/qtforpython-6/licenses.html
- https://pyinstaller.org/en/stable/
- https://pandas.pydata.org/docs/
- https://openpyxl.readthedocs.io/en/stable/
- https://matplotlib.org/stable/

This project does not use a web server, browser automation, cloud database,
external AI API, telemetry, or automatic dependency downloads at application runtime.
Dependency installation/building is a separate, explicitly invoked setup step.
