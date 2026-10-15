# v1.5.0
- Classification engine: clause-level part/symptom pairing that stops at the next named part; explicit,
  recorded conflict resolution (part rule over fallback, compound-noun head, replaced part, causal phrase,
  MES part code). Ambiguous records stay under review with all candidates.
- Rules rebuilt from real MES remarks: 29 -> 67 rules with a role column (component / fallback / override).
  Fixed '씌러/씌링/씬' typos (should be 씰러/씰링/씰).
- Preprocessing: spelling normalization (multi-pass), restoration of clause-final syllables cut short in the
  MES field ('후크 교' -> '후크 교체').
- MES target pattern accepts every plant prefix (1P/2P/3P), not only '2P I/C'. A missing target is a review
  reason only when equipment is grouped by target; otherwise it is reported as data-quality information.
- Existing user profiles: untouched bundled defaults are merged into the new release, user edits/deletions
  are kept, backup under config/backup. Earlier default fingerprints in config/defaults_history.json.
- Corrections save only changed fields, can be removed per field or entirely; time-only corrections no
  longer confirm a tentative classification.
- Column mappings confirmed by the user are saved per header row and reused; corrections are re-keyed when
  the mapping changes. The record-ID formula is unchanged.
- Fixed i18n typo ('남걁니다'), numpy timedelta deprecation warnings; new quality metric for auto-resolved
  conflicts; rules sheet shows the role column.
- Rules workbook format v2 (rules_v2 sheet + meta schema): programs before v1.5.0 stop with a clear message
  instead of misclassifying with the new rules (old engine + new rules gave 344 review rows). Newer schemas
  are refused with an upgrade message. Existing profiles are converted on first start.
- BUILD_EXE.bat names the EXE with the version (EquipmentFailureAnalyzer_v1.5.0.exe); pytest uses a
  project-local temp folder so repeated test runs and builds work on PCs with a locked system temp.
- Reports default to ./output next to START.bat or the EXE (fallback: user data folder when read-only);
  output/ contents are git-ignored.
- USER_GUIDE now opens with a two-page summary and explains how the program works: processing steps,
  classification principle and decision order, the full type list (6 majors, 67 rules), totals and data model.
  The guide builder wraps Korean text between words and fixes an empty table on the first page.
- Real MES sample (414 faults): review 300 -> 11. 121 automated tests passed (GUI included).

# v1.4.0
- Review reason, correction route and aggregation effect per review row.
- Per-record work-date and stop-time corrections.

# v1.3.1
- Replace implicit text-column GUI sorting with explicit numeric descending defaults.
- Stable ties, missing numbers last in either direction, and a reset-default button.
- Preserve per-equipment ranking blocks. Rank period tables by time, keep trend axes chronological.
- Sort detail/review reports by stop duration without modifying source records or event IDs.
- Remove unused empty-product warning code, data-quality rows and placeholder report sections.
- Preserve existing names, user rules, two-file exports, formulas and donut charts.

# 1.3.0

- One export action now produces Excel + PDF from a single analysis snapshot.
- Data-backed executive summary, comparisons, monthly trend, equipment donuts and review actions.
- Optional report title/department/author/note dialog, persistent per-user settings.
- Staged pair creation, explicit overwrite, rollback on ordinary file-commit failure.
- Previous Excel schema and all 15 sheets retained; no product-analysis sheet.
- ReportLab dependency, launch/build checks and user guide updated.
- 51 automated tests passed; GUI test module skipped (PySide6 unavailable).

# v1.2.0

- Removed product-only report sheet and GUI tab; shifted following sheet numbers.
- All report cell text and chart labels use registered display names.
- Original workbook and stable IDs remain unchanged.
- Added equipment-local type ranks, count/time shares, and complete totals.
- Added 100% donut charts in sheet 02 and chart+ranking blocks in sheet 15.
- Top five plus the entire remainder; unclassified rows remain in the denominator.
- Added native GUI equipment selector and count/time donut preview.
- Replaced onedir build with single-executable Windows build configuration.
- Top-level source launcher: START.bat. It still requires Python.
- No Windows executable was built or tested in this environment.
