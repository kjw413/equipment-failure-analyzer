Option Explicit

Private PickerActivations As Long
Private LiveCandidates As Long
Private ActivationFailure As String
Private PreviewDirectory As String

Public Sub SetPreviewDirectory(ByVal path As String)
    PreviewDirectory = path
End Sub

Public Sub Trace(ByVal message As String)
    Dim file As Integer
    file = FreeFile
    Open ThisWorkbook.Path & "\event_trace.txt" For Append As #file
    Print #file, message
    Close #file
End Sub

Public Sub RecordPickerFailure(ByVal message As String)
    ActivationFailure = message
End Sub

Public Sub ObservePicker(ByVal picker As EFAPicker)
    On Error GoTo Failed
    Trace "ObservePicker begin"
    ' This is injected only into QA's unsaved form, after its production Activate handler.
    PickerActivations = PickerActivations + 1
    Check picker.Visible, "Actual search form is visible"
    Check picker.ActiveControl.Name = "Query", "Typing focus is search input"
    Check picker.Candidates.Visible, "Candidate list is visible"
    Check picker.Candidates.Top >= picker.Query.Top + picker.Query.Height, "List is below input"
    picker.Query.Text = "A"
    Check picker.Candidates.ListCount > 0, "First typed character updates list"
    picker.Query.Text = "AJ"
    Check picker.Candidates.ListCount > 0, "Second typed character updates list"
    picker.Query.Text = "AJ10"
    LiveCandidates = picker.Candidates.ListCount
    Check LiveCandidates > 1, "Full query updates visible list"
    picker.Query.Text = "없는문자열xyz"
    Check picker.Candidates.ListCount = 0, "No-match removes previous candidates"
    picker.Query.Text = "AJ10"
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
    On Error GoTo Failed
    Dim previous As Boolean, sheet As Worksheet
    Set sheet = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    previous = Application.EnableEvents
    Application.EnableEvents = False
    sheet.Activate
    sheet.Range("A1").Select
    PickerActivations = 0
    ActivationFailure = ""
    Application.EnableEvents = True
    Trace "Before Range.Select"
    ' Exercise the real Excel selection event; do not call OpenPicker directly.
    sheet.Range("G5").Select
    Trace "After Range.Select"
    Application.EnableEvents = previous
    Check Len(ActivationFailure) = 0, "Form activation failed: " & ActivationFailure
    Check PickerActivations = 1, "Workbook selection event opens actual search form"
    Check sheet.Range("G5").Value2 = "(전체)", "Escape preserves committed filter"
    Check sheet.Range("C9").Value2 = 1001, "Event-driven typing preserves totals"
    Check Not EFASearch.IsSelector(sheet.Range("B5:L5")), "Multiple filter cells do not open picker"
    VerifyWorkbookEvents = "PASS; selection_event=1; visible_candidates=" & CStr(LiveCandidates)
    Exit Function
Failed:
    Application.EnableEvents = previous
    VerifyWorkbookEvents = "FAIL; " & Err.Description
End Function

Private Sub Check(ByVal valid As Boolean, ByVal label As String)
    If Not valid Then Err.Raise vbObjectError + 1701, "Search QA", label
End Sub

Public Function VerifySearch() As String
    On Error GoTo Failed
    Dim target As Range, picker As EFAPicker, ranked As Variant
    Dim original As String, query As String, row As Long, total As Double
    Dim sheet As Worksheet, candidates As Long, errors As Range
    Set sheet = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set target = sheet.Range("G5")
    original = CStr(target.Value2)
    Check EFASearch.IsSelector(target), "Selector detection"
    Check Not EFASearch.IsSelector(sheet.Range("C9")), "Metric is not selector"
    Check EFASearch.MatchScore("모터", "모터") = 10000, "Korean exact score"
    Check EFASearch.MatchScore("컨베어", "컨베어 모터") > EFASearch.MatchScore("컨베어", "상부 컨베어"), "Prefix before contains"
    Check EFASearch.MatchScore("컨베아", "컨베어") > 0, "Typo suggestion"
    Check EFASearch.MatchScore("AJ1O", "[남양주]AJ10-1-A") > 0, "Partial typo suggestion"
    Check EFASearch.MatchScore("없는문자열xyz", "모터") = 0, "Unrelated candidate excluded"
    Check EFASearch.MatchScore("AJ10 1 A", "AJ10-1-A") = 10000, "Spacing and punctuation"
    Set picker = New EFAPicker
    picker.Prepare target
    picker.Query.Text = "AJ10"
    candidates = picker.Candidates.ListCount
    Check candidates > 1, "Multiple suggestions while typing"
    Check CStr(target.Value2) = original, "Typing does not commit"
    Check sheet.Range("C9").Value2 = 1001, "Typing preserves totals"
    Check picker.ProbeKey(vbKeyDown) = 0, "Down handled"
    Check picker.Candidates.ListIndex = 1, "Down moves selection"
    Check picker.ProbeKey(vbKeyUp) = 0, "Up handled"
    Check picker.Candidates.ListIndex = 0, "Up moves selection"
    Check picker.ProbeKey(vbKeyEscape) = 0, "Escape handled"
    Unload picker
    Check CStr(target.Value2) = original, "Cancel preserves prior selection"
    Set picker = New EFAPicker
    picker.Prepare target
    picker.Query.Text = "[남양주]AJ10-1-A"
    Check picker.Candidates.List(0) = "[남양주]AJ10-1-A", "Exact match ranks first"
    Check picker.ProbeKey(vbKeyReturn) = 0, "Enter handled"
    Unload picker
    Check CStr(target.Value2) = "[남양주]AJ10-1-A", "Selected candidate committed"
    Check sheet.Range("C9").Value2 = 48, "Exact line count"
    Check sheet.Range("E9").Value2 = 1632, "Exact line minutes"
    Check Not EFASearch.CommitSelection(target, "컨베어"), "Wrong field candidate rejected"
    Check Not EFASearch.CommitSelection(target, "AJ10"), "Query cannot become selection"
    Check CStr(target.Value2) = "[남양주]AJ10-1-A", "Rejected commit preserves selection"
    Check EFASearch.CommitSelection(target, "(전체)"), "Reset selection"
    Check sheet.Range("C9").Value2 = 1001, "All reset count"
    Set sheet = ThisWorkbook.Worksheets("별첨. 라인별분석")
    Check EFASearch.CommitSelection(sheet.Range("C7"), "[남양주]AJ10-1-A"), "Appendix selector"
    Check sheet.Range("C9").Value2 = 48, "Appendix exact count"
    Check sheet.Range("F9").Value2 = 1632, "Appendix exact minutes"
    Check EFASearch.CommitSelection(sheet.Range("C7"), "(전체)"), "Appendix reset"
    Set sheet = ThisWorkbook.Worksheets("별첨. 상세설비별분석")
    Check EFASearch.CommitSelection(sheet.Range("I7"), "컨베어"), "Module selector"
    Check sheet.Range("C9").Value2 = 129, "Module count"
    Check sheet.Range("F9").Value2 = 4854, "Module minutes"
    Check EFASearch.CommitSelection(sheet.Range("I7"), "(전체)"), "Module reset"
    Set sheet = ThisWorkbook.Worksheets("03.팀간 비교")
    Check Application.Sum(sheet.Range("C22:C28")) = 1001, "Comparison total restored"
    Check Application.Sum(sheet.Range("D22:D28")) = 38802, "Comparison time restored"
    Check EFASearch.CommitSelection(sheet.Range("I5"), "컨베어"), "Comparison module selector"
    Check Application.Sum(sheet.Range("C22:C28")) = 129, "Comparison selected module count"
    Check Application.Sum(sheet.Range("D22:D28")) = 4854, "Comparison selected module time"
    Check EFASearch.CommitSelection(sheet.Range("I5"), "(전체)"), "Comparison module reset"
    Set sheet = ThisWorkbook.Worksheets("04.고장추이")
    Check EFASearch.CommitSelection(sheet.Range("J6"), "센서(종류 미상)"), "Part selector"
    total = 0
    For row = 23 To 33: total = total + sheet.Cells(row, 2).Value2: Next row
    Check total = 48, "Monthly part counts"
    Check EFASearch.CommitSelection(sheet.Range("J6"), "(전체)"), "Part reset"
    Set picker = New EFAPicker
    picker.Prepare target
    picker.Query.Text = "없는문자열xyz"
    Check picker.Candidates.ListCount = 0, "No match empty list"
    picker.ApplyChoice
    Check CStr(target.Value2) = "(전체)", "Empty list cannot commit"
    Unload picker
    Set sheet = ThisWorkbook.Worksheets("01.종합현황")
    Check sheet.Range("D10").Value2 = 109, "Summary count ranking"
    Check sheet.Range("D23").Value2 = 3673, "Summary time ranking"
    Check sheet.Range("A34").Value2 = "", "Draft note removed"
    For Each sheet In ThisWorkbook.Worksheets
        Set errors = Nothing
        On Error Resume Next
        Set errors = sheet.UsedRange.SpecialCells(xlCellTypeFormulas, xlErrors)
        On Error GoTo Failed
        Check errors Is Nothing, "Formula errors in " & sheet.Name
    Next sheet
    VerifySearch = "PASS; candidates=" & CStr(candidates) & "; exact=48/1632; module=129/4854; part=48"
    Exit Function
Failed:
    VerifySearch = "FAIL; " & Err.Description
End Function

Public Function VerifyDrilldown() As String
    On Error GoTo Failed
    Dim main As Worksheet, trends As Worksheet, history As Worksheet, previousEvents As Boolean
    Dim timeLabel As String, timeMinutes As Double, appendix As Worksheet, labels As Range, row As Long
    Set main = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set trends = ThisWorkbook.Worksheets("04.고장추이")
    EFASearch.Initialize
    previousEvents = Application.EnableEvents
    Application.EnableEvents = True
    Set appendix = ThisWorkbook.Worksheets("별첨. 상세설비별분석")
    appendix.Range("K6").Value2 = "정지시간"
    appendix.Range("K6").Value2 = "건수"
    Set labels = ThisWorkbook.Names("_Breakdown_lineLabels").RefersToRange
    For row = labels.Rows.Count To 1 Step -1
        If Len(CStr(labels.Cells(row, 1).Value2)) > 0 Then
            Check Not labels.Cells(row, 1).EntireRow.Hidden, "Metric change restores the entire table"
            Exit For
        End If
    Next row
    Application.EnableEvents = previousEvents
    Check EFASearch.CommitSelection(main.Range("B5"), "남양주"), "Factory selection"
    Check EFASearch.CommitSelection(main.Range("D5"), "생산1팀"), "Scoped team selection"
    Check EFASearch.SourceRange(main.Range("G5")).Cells.Count = 13, "Only 12 scoped lines plus ALL"
    Check EFASearch.SourceRange(main.Range("K5")).Cells.Count = 39, "Only 38 scoped modules plus ALL"
    Check Not EFASearch.CommitSelection(main.Range("G5"), "[김해]바나나성형기"), "Other factory line rejected"
    Check main.Range("C9").Value2 = 270, "Selected team total"
    Check Application.CountA(EFASearch.ControlCell(main, "asset")) = 1, "Line control preserved"
    Check Application.CountIf(ThisWorkbook.Names("_Drill_CountLabels").RefersToRange, "?*") = 12, "Full line table exceeds TOP five"
    Check Application.Sum(main.Range("D28:D" & main.UsedRange.Rows.Count)) = 270, "Full line table reconciles"
    Check main.Range("E9").NumberFormat = "#,##0" And main.Range("E28").NumberFormat = "#,##0", "Integer minute display"
    Check main.Range("B27").Value2 = "라인", "Line ranking label"
    Check main.Range("B28").Value2 = "[남양주]AJ10-B", "Team's leading line"
    Check main.Range("D28").Value2 = 55, "Leading line count"
    If Len(PreviewDirectory) > 0 Then main.ExportAsFixedFormat 0, PreviewDirectory & "\drill_line.pdf"
    timeLabel = CStr(main.Range("H28").Value2): timeMinutes = main.Range("K28").Value2
    Check EFASearch.FollowChart(main.ChartObjects(2).Chart, 1), "Time chart drill"
    Check main.Range("G5").Value2 = timeLabel And main.Range("E9").Value2 = timeMinutes, "Time leader selected exactly"
    Check EFASearch.CommitSelection(main.Range("G5"), "(전체)"), "Line reset after time branch"
    Check EFASearch.FollowChart(main.ChartObjects(1).Chart, 1), "Chart drill into line"
    Check main.Range("G5").Value2 = "[남양주]AJ10-B", "Line selected from bar"
    Check main.Range("B27").Value2 = "상세설비", "Module ranking label"
    Check main.Range("B28").Value2 = "제대기", "Line's leading module"
    Check main.Range("D28").Value2 = 18, "Leading module count"
    Check Application.Sum(main.Range("D28:D" & main.UsedRange.Rows.Count)) = 55, "Full module table reconciles"
    If Len(PreviewDirectory) > 0 Then main.ExportAsFixedFormat 0, PreviewDirectory & "\drill_module.pdf"
    Check EFASearch.FollowRank(main.Range("B28")), "Table drill into module"
    Check main.Range("K5").Value2 = "제대기", "Module selected"
    Check main.Range("B27").Value2 = "세부부품", "Part ranking label"
    Check main.Range("B28").Value2 = "후크", "Module's leading part"
    Check main.Range("D28").Value2 = 8, "Leading part count"
    If Len(PreviewDirectory) > 0 Then main.ExportAsFixedFormat 0, PreviewDirectory & "\drill_part.pdf"
    Check EFASearch.FollowRank(main.Range("B28")), "Part drill opens records"
    Check main.Range("K6").Value2 = "후크", "Part selected"
    Set history = ThisWorkbook.Worksheets("별첨. 고장이력")
    Check ActiveSheet.Name = history.Name, "History activated"
    Check Application.Subtotal(103, history.Range("C7:C1007")) = 8, "Eight matching records visible"
    Check trends.Range("F5").Value2 = "[남양주]AJ10-B" And trends.Range("J6").Value2 = "후크", "Trend context synchronized"
    Check Application.Sum(trends.Range("B23:B33")) = 8, "Linked trend count"
    Check Application.Sum(trends.Range("C23:C33")) = 133, "Linked trend time"
    Check EFASearch.CommitSelection(main.Range("D5"), "생산2팀"), "Parent team change"
    Check main.Range("G5").Value2 = "(전체)" And main.Range("K5").Value2 = "(전체)" And main.Range("K6").Value2 = "(전체)", "Children reset"
    Check main.Range("C9").Value2 = 153, "New team's own total"
    Check Not EFASearch.CommitSelection(main.Range("G5"), "[남양주]AJ10-B"), "Old team's line rejected"
    previousEvents = Application.EnableEvents
    Application.EnableEvents = True
    main.Range("B5").Value2 = "김해"
    Application.EnableEvents = previousEvents
    Check main.Range("D5").Value2 = "(전체)", "Native cell edit resets children too"
    Check EFASearch.CommitSelection(main.Range("B5"), "(전체)"), "Main reset"
    Check EFASearch.CommitSelection(trends.Range("B5"), "(전체)"), "Trend reset"
    If history.FilterMode Then history.ShowAllData
    VerifyDrilldown = "PASS; scoped_lines=12; scoped_modules=38; line=55; module=18; part=8/133; linked_history=8; reset=ok"
    Exit Function
Failed:
    Application.EnableEvents = previousEvents
    VerifyDrilldown = "FAIL; " & Err.Description
End Function
