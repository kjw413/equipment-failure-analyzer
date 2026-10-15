# v1.5.0 validation (2026-10-15)

Environment: Windows 11, Python 3.13, pandas 2.3.3, numpy 2.5.4, PySide6 6.12.0, reportlab 4.5.1.

`python -m pytest -q -W error::DeprecationWarning` (QT_QPA_PLATFORM=offscreen): **115 passed**, GUI tests included, no warnings.
New in tests/test_v15.py and tests/test_gui.py: classification engine cases, clause-end restoration,
MES target pattern and review policy, review guidance per issue, work-date/stop-time corrections,
correction patch (changed fields only, removal), defaults merge on a real v1.4.0 profile
(untouched defaults updated, user edits/deletions kept, typo fix, idempotent), saved column mappings,
correction re-keying, unchanged record-ID formula, encoding-typo guard, correction dialog and rule editor.

## Real MES export (라인 비가동 현황 조회_261014.xlsx)

11,075 source rows, 414 faults, 18,328 minutes. The source file hash was unchanged.

| Step | Review rows | Unclassified | Multiple candidates | Target missing |
|---|---|---|---|---|
| v1.4.0 | 300 | 141 | 47 | 217 |
| Target pattern fixed (1P/2P/3P) | 230 | 141 | 47 | 57 |
| Target missing reviewed only for target basis | 188 | 141 | 47 | 57 (info) |
| Normalization + clause-end restoration | 193 | 137 | 56 | 57 (info) |
| New engine (pairing + evidence-based resolution) | 153 | 149 | 4 | 57 (info) |
| Rules 29 -> 67 | **11** | 0 | 11 | 57 (info) |

During rule development the full list of automatic classifications was read and judged by hand once,
and every later rule/engine change was checked row by row against the previous run. The remaining 11
review rows mention two parts or two events.

Excel + PDF from the real file: 15 sheets, 7,006 formulas, 0 error cells. 428 formulas cache an empty
string by design (daily trend rows with no records; identical in the v1.4.0 output). PDF 30 pages.
CLI end-to-end time about 46 s.

Not verified here: EXE build/execution (run BUILD_EXE.bat) and interactive use on other PCs.
