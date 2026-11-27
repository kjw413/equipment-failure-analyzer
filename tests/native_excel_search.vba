Option Explicit

Private Const AllValues As String = "(전체)"
Private PickerActivations As Long
Private LiveCandidates As Long
Private ActivationFailure As String
Private SearchExample As String
Private EvidenceDirectory As String
Private PreviewDirectory As String

Public Sub ConfigureEvidence(ByVal path As String, ByVal preview As Boolean)
    Dim file As Integer
    EvidenceDirectory = path
    If preview Then PreviewDirectory = path
    file = FreeFile
    Open EvidenceDirectory & "\event_trace.txt" For Output As #file
    Close #file
End Sub

Public Sub Trace(ByVal message As String)
    Dim file As Integer
    file = FreeFile
    Open EvidenceDirectory & "\event_trace.txt" For Append As #file
    Print #file, message
    Close #file
End Sub

Public Sub RecordPickerFailure(ByVal message As String)
    ActivationFailure = message
End Sub

Public Sub ObservePicker(ByVal picker As EFAPicker)
    On Error GoTo Failed
    Trace "ObservePicker begin"
    ' This runs after the production Activate handler in the unsaved QA copy.
    PickerActivations = PickerActivations + 1
    Check picker.Visible, "Actual search form is visible"
    Check picker.ActiveControl.Name = "Query", "Typing focus is search input"
    Check picker.Candidates.Visible, "Candidate list is visible"
    Check picker.Candidates.Top >= picker.Query.Top + picker.Query.Height, "List is below input"
    Check picker.Candidates.ListCount > 1, "Blank query shows selectable values"
    picker.Query.Text = Left$(EFASearch.Normalize(SearchExample), 1)
    Check picker.Candidates.ListCount > 0, "First typed character updates list"
    picker.Query.Text = SearchExample
    LiveCandidates = picker.Candidates.ListCount
    Check LiveCandidates > 0, "Full query updates visible list"
    Check picker.Candidates.List(0) = SearchExample, "Exact live match ranks first"
    picker.Query.Text = "없는문자열xyz"
    Check picker.Candidates.ListCount = 0, "No-match removes previous candidates"
    picker.Query.Text = SearchExample
    Check picker.Candidates.ListCount = LiveCandidates, "Editing search restores candidates"
    picker.ProbeKey vbKeyEscape
    Trace "ObservePicker escaped"
    Exit Sub
Failed:
    ActivationFailure = Err.Description
    Trace "ObservePicker error: " & Err.Description
    picker.Hide
End Sub

Public Function VerifyWorkbookEvents() As String
    Dim previous As Boolean, sheet As Worksheet, target As Range
    previous = Application.EnableEvents
    On Error GoTo Failed
    Set sheet = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set target = EFASearch.ControlCell(sheet, "asset")
    SearchExample = FirstChoice(target)
    Application.EnableEvents = False
    sheet.Activate
    sheet.Range("A1").Select
    PickerActivations = 0
    ActivationFailure = ""
    Application.EnableEvents = True
    Trace "Before Range.Select"
    target.Select
    Trace "After Range.Select"
    Application.EnableEvents = previous
    Check Len(ActivationFailure) = 0, "Form activation failed: " & ActivationFailure
    Check PickerActivations = 1, "Workbook selection event opens actual search form"
    Check target.Value2 = AllValues, "Escape preserves committed filter"
    CheckTeamTotals sheet
    Check Not EFASearch.IsSelector(sheet.Range("B7:L7")), "Multiple filter cells do not open picker"
    VerifyWorkbookEvents = "PASS; selection_event=1; visible_candidates=" & CStr(LiveCandidates)
    Exit Function
Failed:
    Application.EnableEvents = previous
    VerifyWorkbookEvents = "FAIL; " & Err.Description
End Function

Public Function VerifyComparisonSort() As String
    On Error GoTo Failed
    Dim ws As Worksheet, table As Range, facts As Worksheet, baseline As String
    Set ws = ThisWorkbook.Worksheets("04.고장비교")
    Set table = ThisWorkbook.Names("_Fault_TableRows").RefersToRange
    Set facts = ThisWorkbook.Worksheets("_fault_facts")
    baseline = CStr(ws.Range("B7").Value2)
    Check EFASearch.CommitSelection(ws.Range("E7"), AllValues), "Baseline line reset"
    Check EFASearch.CommitSelection(ws.Range("B9"), AllValues), "Comparison department reset"
    Check Application.Sum(table.Columns(5)) = facts.UsedRange.Rows.Count - 1, "All department counts reconcile"
    Check Abs(Application.Sum(table.Columns(6)) - Application.Sum(facts.UsedRange.Columns(11))) < 0.00001, "All department minutes reconcile"
    CheckComparisonCharts ws, table
    Check EFASearch.CommitSelection(ws.Range("B9"), baseline), "Comparison filtered to baseline department"
    Check Application.Count(table.Columns(5)) = 1, "Identical baseline and comparison department deduplicated"
    CheckComparisonCharts ws, table
    Check EFASearch.CommitSelection(ws.Range("B9"), AllValues), "Comparison reset"
    VerifyComparisonSort = "PASS; descending_count_and_minutes; department_filter_recalculates"
    Exit Function
Failed:
    VerifyComparisonSort = "FAIL; " & Err.Description
End Function

Private Sub CheckComparisonCharts(ByVal sheet As Worksheet, ByVal table As Range)
    Dim values As Variant, index As Long, metric As Long, scores As Range
    For metric = 1 To 2
        Set scores = table.Columns(metric + 4)
        If Application.Count(scores) > 0 Then
            sheet.ChartObjects(metric).Chart.Refresh
            values = sheet.ChartObjects(metric).Chart.SeriesCollection(1).Values
            Check Abs(values(1) - Application.Max(scores)) < 0.00001, "Comparison leading value matches table maximum"
            For index = 2 To UBound(values)
                Check values(index - 1) >= values(index), "Metric-specific descending comparison chart"
            Next index
        End If
    Next metric
End Sub

Private Sub Check(ByVal valid As Boolean, ByVal label As String)
    If Not valid Then Err.Raise vbObjectError + 1701, "Search QA", label
End Sub

Private Function FirstChoice(ByVal target As Range) As String
    Dim cell As Range
    For Each cell In EFASearch.SourceRange(target).Cells
        If Len(CStr(cell.Value2)) > 0 And cell.Value2 <> AllValues Then
            FirstChoice = CStr(cell.Value2)
            Exit Function
        End If
    Next cell
    Check False, "Expected a selectable value: " & target.Address
End Function

Private Sub ReadScopeTotals(ByVal sheet As Worksheet, ByRef rowCount As Long, ByRef minutes As Double)
    Dim data As Variant, fields As Variant, columns As Variant, selected(0 To 3) As String
    Dim row As Long, index As Long, matches As Boolean
    data = ThisWorkbook.Worksheets("_issue_facts").UsedRange.Value2
    fields = Array("factory", "team", "asset", "module")
    columns = Array(3, 4, 5, 7)
    For index = 0 To UBound(fields)
        selected(index) = CStr(EFASearch.ControlCell(sheet, CStr(fields(index))).Value2)
    Next index
    rowCount = 0
    minutes = 0
    For row = 2 To UBound(data, 1)
        matches = True
        For index = 0 To UBound(fields)
            If selected(index) <> AllValues And selected(index) <> CStr(data(row, columns(index))) Then
                matches = False
                Exit For
            End If
        Next index
        If matches Then
            rowCount = rowCount + 1
            If IsNumeric(data(row, 11)) Then minutes = minutes + CDbl(data(row, 11))
        End If
    Next row
End Sub

Private Sub CheckTeamTotals(ByVal sheet As Worksheet)
    Dim rowCount As Long, minutes As Double
    ReadScopeTotals sheet, rowCount, minutes
    Check sheet.Range("C10").Value2 = rowCount, "Team count reconciles with report facts"
    If minutes > 0 Then Check Abs(sheet.Range("E10").Value2 - minutes) < 0.00001, "Team minutes reconcile with report facts"
End Sub

Public Function VerifySearch() As String
    On Error GoTo Failed
    Dim target As Range, picker As EFAPicker, original As String, lineLabel As String
    Dim sheet As Worksheet, candidates As Long
    Set sheet = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set target = EFASearch.ControlCell(sheet, "asset")
    original = CStr(target.Value2)
    lineLabel = FirstChoice(target)
    Check EFASearch.IsSelector(target), "Selector detection"
    Check Not EFASearch.IsSelector(sheet.Range("C10")), "Metric is not selector"
    Check EFASearch.MatchScore("모터", "모터") = 10000, "Korean exact score"
    Check EFASearch.MatchScore("컨베어", "컨베어 모터") > EFASearch.MatchScore("컨베어", "상부 컨베어"), "Prefix before contains"
    Check EFASearch.MatchScore("컨베아", "컨베어") > 0, "Typo suggestion"
    Check EFASearch.MatchScore("AJ1O", "[남양주]AJ10-1-A") > 0, "Partial typo suggestion"
    Check EFASearch.MatchScore("없는문자열xyz", "모터") = 0, "Unrelated candidate excluded"
    Check EFASearch.MatchScore("AJ10 1 A", "AJ10-1-A") = 10000, "Spacing and punctuation"
    Set picker = New EFAPicker
    picker.Prepare target
    candidates = picker.Candidates.ListCount
    Check candidates > 1, "Initial candidate list"
    Check CStr(target.Value2) = original, "Opening the picker does not commit"
    CheckTeamTotals sheet
    Check picker.ProbeKey(vbKeyDown) = 0, "Down handled"
    Check picker.Candidates.ListIndex = 1, "Down moves selection"
    Check picker.ProbeKey(vbKeyUp) = 0, "Up handled"
    Check picker.Candidates.ListIndex = 0, "Up moves selection"
    Check picker.ProbeKey(vbKeyEscape) = 0, "Escape handled"
    Unload picker
    Check CStr(target.Value2) = original, "Cancel preserves prior selection"
    Set picker = New EFAPicker
    picker.Prepare target
    picker.Query.Text = lineLabel
    Check picker.Candidates.List(0) = lineLabel, "Exact match ranks first"
    Check picker.ProbeKey(vbKeyReturn) = 0, "Enter handled"
    Unload picker
    Check CStr(target.Value2) = lineLabel, "Selected candidate committed"
    CheckTeamTotals sheet
    Check Not EFASearch.CommitSelection(target, "없는문자열xyz"), "Unknown candidate rejected"
    Check CStr(target.Value2) = lineLabel, "Rejected commit preserves selection"
    Check EFASearch.CommitSelection(target, AllValues), "Reset selection"
    CheckTeamTotals sheet
    Set target = EFASearch.ControlCell(sheet, "module")
    Check EFASearch.CommitSelection(target, FirstChoice(target)), "Module selector"
    CheckTeamTotals sheet
    Check EFASearch.CommitSelection(target, AllValues), "Module reset"
    Set sheet = ThisWorkbook.Worksheets("03.월별 주요이슈")
    VerifySearch = "PASS; candidate_count=" & CStr(candidates) & "; exact_and_typo_matches; scoped_totals"
    Exit Function
Failed:
    VerifySearch = "FAIL; " & Err.Description
End Function

Public Function VerifyDrilldown() As String
    Dim previousEvents As Boolean
    previousEvents = Application.EnableEvents
    On Error GoTo Failed
    Dim main As Worksheet, labels As Range, chart As ChartObject
    Dim factory As Range, team As Range, asset As Range, moduleTarget As Range
    Dim timeLabel As String, timeMinutes As Double, lineName As String, chartLabels As Variant
    Set main = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set factory = EFASearch.ControlCell(main, "factory")
    Set team = EFASearch.ControlCell(main, "team")
    Set asset = EFASearch.ControlCell(main, "asset")
    Set moduleTarget = EFASearch.ControlCell(main, "module")
    Set labels = ThisWorkbook.Names("_Drill_CountLabels").RefersToRange
    Check EFASearch.CommitSelection(factory, FirstChoice(factory)), "Factory selection"
    Check EFASearch.CommitSelection(team, FirstChoice(team)), "Scoped team selection"
    CheckTeamTotals main
    Check Application.CountIf(labels, "?*") = EFASearch.SourceRange(asset).Cells.Count - 1, "Full line table matches scoped choices"
    Check Application.Sum(labels.Offset(0, 2)) = main.Range("C10").Value2, "Full line table reconciles"
    Check main.Range("E10").NumberFormat = "#,##0" And main.Cells(labels.Row, 5).NumberFormat = "#,##0", "Integer minute display"
    Check labels.Cells(1, 1).Offset(-1, 0).Value2 = "라인", "Line ranking label"
    If Len(CStr(main.Range("H28").Value2)) > 0 And IsNumeric(main.Range("K28").Value2) Then
        timeLabel = CStr(main.Range("H28").Value2)
        timeMinutes = main.Range("K28").Value2
        Check EFASearch.CommitSelection(asset, timeLabel), "Time leader selected by line filter"
        Check asset.Value2 = timeLabel And main.Range("E10").Value2 = timeMinutes, "Time leader selected exactly"
        Check EFASearch.CommitSelection(asset, AllValues), "Line reset after time branch"
    End If
    If Len(PreviewDirectory) > 0 Then main.ExportAsFixedFormat 0, PreviewDirectory & "\drill_line.pdf"
    lineName = CStr(labels.Cells(1, 1).Value2)
    Check Not EFASearch.ProbeChartDoubleClick(main.Name, 1, 1), "Team chart has no double-click navigation"
    Check Not ThisWorkbook.ProbeSheetDoubleClick(labels.Cells(1, 1)), "Team rank table has no double-click navigation"
    Check asset.Value2 = AllValues, "Data clicks leave the line filter unchanged"
    Application.EnableEvents = True
    asset.Value2 = "'" & lineName
    Application.EnableEvents = False
    Check asset.Value2 = lineName, "Line selected from the native filter"
    CheckTeamTotals main
    Check labels.Cells(1, 1).Offset(-1, 0).Value2 = "상세설비", "Module ranking label"
    Check Application.Sum(labels.Offset(0, 2)) = main.Range("C10").Value2, "Full module table reconciles"
    Set chart = main.ChartObjects(1)
    chartLabels = chart.Chart.SeriesCollection(1).XValues
    Check CStr(chartLabels(LBound(chartLabels))) = CStr(labels.Cells(1, 1).Value2), "Line filter refreshes chart categories"
    If Len(PreviewDirectory) > 0 Then main.ExportAsFixedFormat 0, PreviewDirectory & "\drill_module.pdf"
    Check EFASearch.CommitSelection(moduleTarget, CStr(labels.Cells(1, 1).Value2)), "Detailed-equipment filter selected"
    CheckTeamTotals main
    Application.EnableEvents = True
    factory.Value2 = AllValues
    Application.EnableEvents = previousEvents
    Check team.Value2 = AllValues And asset.Value2 = AllValues And moduleTarget.Value2 = AllValues, "Native parent edit resets children"
    CheckTeamTotals main

    VerifyDrilldown = "PASS; team_filters_update_chart_and_table; no_click_navigation; parent_filter_resets_children"
    Exit Function
Failed:
    VerifyDrilldown = "FAIL; " & CStr(Err.Number) & "; " & Err.Description
    Application.EnableEvents = previousEvents
End Function
