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
    Check Abs(Application.Sum(table.Columns(6)) - Application.Sum(facts.UsedRange.Columns(12))) < 0.00001, "All department minutes reconcile"
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

Private Sub ReadScopeTotals(ByVal sheet As Worksheet, ByRef rowCount As Long, ByRef minutes As Double, Optional ByVal monthly As Boolean = False)
    Dim data As Variant, fields As Variant, columns As Variant, selected(0 To 4) As String
    Dim row As Long, index As Long, matches As Boolean
    data = ThisWorkbook.Worksheets("_issue_facts").UsedRange.Value2
    fields = Array("factory", "team", "asset", "module", "part")
    columns = Array(3, 4, 5, 7, 8)
    For index = 0 To 4
        selected(index) = CStr(EFASearch.ControlCell(sheet, CStr(fields(index))).Value2)
    Next index
    rowCount = 0
    minutes = 0
    For row = 2 To UBound(data, 1)
        matches = Not monthly Or Len(CStr(data(row, 14))) > 0
        For index = 0 To 4
            If selected(index) <> AllValues And selected(index) <> CStr(data(row, columns(index))) Then
                matches = False
                Exit For
            End If
        Next index
        If matches Then
            rowCount = rowCount + 1
            If IsNumeric(data(row, 12)) Then minutes = minutes + CDbl(data(row, 12))
        End If
    Next row
End Sub

Private Sub CheckTeamTotals(ByVal sheet As Worksheet)
    Dim rowCount As Long, minutes As Double
    ReadScopeTotals sheet, rowCount, minutes
    Check sheet.Range("C10").Value2 = rowCount, "Team count reconciles with report facts"
    If minutes > 0 Then Check Abs(sheet.Range("E10").Value2 - minutes) < 0.00001, "Team minutes reconcile with report facts"
End Sub

Private Sub CheckMonthlyTotals(ByVal sheet As Worksheet)
    Dim rows As Range, rowCount As Long, minutes As Double
    Set rows = ThisWorkbook.Names("_Period_Rows").RefersToRange
    ReadScopeTotals sheet, rowCount, minutes, True
    Check Application.Sum(rows.Offset(0, 1)) = rowCount, "Monthly counts reconcile with report facts"
    Check Abs(Application.Sum(rows.Offset(0, 2)) - minutes) < 0.00001, "Monthly minutes reconcile with report facts"
End Sub

Private Sub CheckHistoryRows(ByVal history As Worksheet, ByVal expectedCount As Long)
    Dim facts As Worksheet, flags As Worksheet, recordIds As Range, cell As Range
    Dim idIndex As Long, row As Long, expected As Object
    Set facts = ThisWorkbook.Worksheets("_issue_facts")
    Set flags = ThisWorkbook.Worksheets("_issue_filter_1")
    Set expected = CreateObject("Scripting.Dictionary")
    For row = 2 To facts.Cells(facts.Rows.Count, 1).End(xlUp).Row
        If flags.Cells(row, 1).Value2 = 1 Then expected.Add CStr(facts.Cells(row, 1).Value2), True
    Next row
    Check expected.Count = expectedCount, "History scope count " & CStr(expected.Count) & " expected " & CStr(expectedCount)
    idIndex = Application.Match("원본 기록 ID", history.AutoFilter.Range.Rows(1), 0)
    Set recordIds = history.AutoFilter.Range.Columns(idIndex)
    Set recordIds = recordIds.Offset(1, 0).Resize(recordIds.Rows.Count - 1, 1)
    Check Application.Subtotal(103, recordIds) = expectedCount, "Visible history count matches the selected part"
    For Each cell In recordIds.Cells
        If Not cell.EntireRow.Hidden Then
            Check expected.Exists(CStr(cell.Value2)), "Visible history belongs to the new selection"
        End If
    Next cell
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
    Set target = EFASearch.ControlCell(sheet, "part")
    Check EFASearch.BackToMonths(), "Monthly view"
    Check EFASearch.CommitSelection(target, FirstChoice(target)), "Part selector"
    CheckMonthlyTotals sheet
    Check EFASearch.CommitSelection(target, AllValues), "Part reset"
    VerifySearch = "PASS; candidate_count=" & CStr(candidates) & "; exact_and_typo_matches; scoped_totals"
    Exit Function
Failed:
    VerifySearch = "FAIL; " & Err.Description
End Function

Public Function VerifyDrilldown() As String
    Dim previousEvents As Boolean
    previousEvents = Application.EnableEvents
    On Error GoTo Failed
    Dim main As Worksheet, trends As Worksheet, history As Worksheet, labels As Range, chart As ChartObject
    Dim factory As Range, team As Range, asset As Range, moduleTarget As Range, part As Range
    Dim timeLabel As String, timeMinutes As Double, partCount As Long
    Dim previousAsset As String, nextLinePoint As Long
    Set main = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set trends = ThisWorkbook.Worksheets("03.월별 주요이슈")
    Set factory = EFASearch.ControlCell(main, "factory")
    Set team = EFASearch.ControlCell(main, "team")
    Set asset = EFASearch.ControlCell(main, "asset")
    Set moduleTarget = EFASearch.ControlCell(main, "module")
    Set part = EFASearch.ControlCell(main, "part")
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
        Check EFASearch.FollowChart(main.ChartObjects(2).Chart, 1), "Time chart drill"
        Check asset.Value2 = timeLabel And main.Range("E10").Value2 = timeMinutes, "Time leader selected exactly"
        Check EFASearch.CommitSelection(asset, AllValues), "Line reset after time branch"
    End If
    If Len(PreviewDirectory) > 0 Then main.ExportAsFixedFormat 0, PreviewDirectory & "\drill_line.pdf"
    Check EFASearch.FollowChart(main.ChartObjects(1).Chart, 1), "Chart drill into line"
    Check asset.Value2 <> AllValues, "Line selected from bar"
    CheckTeamTotals main
    Check labels.Cells(1, 1).Offset(-1, 0).Value2 = "상세설비", "Module ranking label"
    Check Application.Sum(labels.Offset(0, 2)) = main.Range("C10").Value2, "Full module table reconciles"
    If Len(PreviewDirectory) > 0 Then main.ExportAsFixedFormat 0, PreviewDirectory & "\drill_module.pdf"
    Check EFASearch.FollowRank(labels.Cells(1, 1)), "Table drill into module"
    Check moduleTarget.Value2 <> AllValues, "Module selected"
    Check labels.Cells(1, 1).Offset(-1, 0).Value2 = "세부부품", "Part ranking label"
    If Len(PreviewDirectory) > 0 Then main.ExportAsFixedFormat 0, PreviewDirectory & "\drill_part.pdf"
    partCount = main.Cells(labels.Row, 4).Value2
    Check EFASearch.FollowRank(labels.Cells(1, 1)), "Part drill opens records"
    Check part.Value2 <> AllValues, "Part selected"
    Set history = ThisWorkbook.Worksheets("별첨. 고장이력")
    Check ActiveSheet.Name = history.Name, "History activated"
    CheckHistoryRows history, partCount
    Check EFASearch.ControlCell(trends, "asset").Value2 = asset.Value2 And EFASearch.ControlCell(trends, "part").Value2 = part.Value2, "Trend context synchronized"
    CheckMonthlyTotals trends
    previousAsset = CStr(asset.Value2)
    Application.EnableEvents = True
    factory.Value2 = AllValues
    Application.EnableEvents = previousEvents
    Check team.Value2 = AllValues And asset.Value2 = AllValues And moduleTarget.Value2 = AllValues And part.Value2 = AllValues, "Native parent edit resets children"
    CheckTeamTotals main

    ' Keep the first drill's history filter active while switching to a different line.
    Check history.FilterMode, "First history filter is still applied"
    nextLinePoint = 1
    If labels.Cells(nextLinePoint, 1).Value2 = previousAsset Then nextLinePoint = 2
    Check Len(CStr(labels.Cells(nextLinePoint, 1).Value2)) > 0, "Alternate line available"
    Set chart = main.ChartObjects(1)
    main.Activate
    chart.Activate
    Check EFASearch.FollowChart(chart.Chart, nextLinePoint), "Switch to another line"
    Check asset.Value2 <> previousAsset, "Alternate line selected"
    chart.Activate
    Check EFASearch.FollowChart(chart.Chart, 1), "Drill into alternate module"
    partCount = main.Cells(labels.Row, 4).Value2
    chart.Activate
    Check EFASearch.FollowChart(chart.Chart, 1), "Reopen history from the active part chart"
    Check ActiveSheet.Name = history.Name, "Alternate history activated"
    CheckHistoryRows history, partCount
    history.AutoFilter.Range.AutoFilter Field:=1, Criteria1:="=__EFA_QA_no_match__"
    Check history.AutoFilter.FilterMode, "Additional history filter applied"
    main.Activate
    chart.Activate
    Check EFASearch.FollowChart(chart.Chart, 1), "Reopen after filtering out the history rows"
    CheckHistoryRows history, partCount
    Check EFASearch.CommitSelection(factory, AllValues) And EFASearch.CommitSelection(asset, AllValues), "Team filters reset"
    Check EFASearch.CommitSelection(EFASearch.ControlCell(trends, "factory"), AllValues), "Trend reset"
    If history.AutoFilter.FilterMode Then history.AutoFilter.ShowAllData
    VerifyDrilldown = "PASS; line_to_module_to_part; link_reopened_after_filter_change; empty_history_recovered; visible_history=" & CStr(partCount)
    Exit Function
Failed:
    VerifyDrilldown = "FAIL; " & CStr(Err.Number) & "; " & Err.Description
    Application.EnableEvents = previousEvents
End Function
