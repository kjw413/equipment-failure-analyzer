Option Explicit

Private PickerActivations As Long
Private LiveCandidates As Long
Private ActivationFailure As String

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
    Set sheet = ThisWorkbook.Worksheets("02.주요이슈_팀별")
    previous = Application.EnableEvents
    Application.EnableEvents = False
    sheet.Activate
    sheet.Range("A1").Select
    PickerActivations = 0
    ActivationFailure = ""
    Application.EnableEvents = True
    Trace "Before Range.Select"
    ' Exercise the real Excel selection event; do not call OpenPicker directly.
    sheet.Range("F5").Select
    Trace "After Range.Select"
    Application.EnableEvents = previous
    Check Len(ActivationFailure) = 0, "Form activation failed: " & ActivationFailure
    Check PickerActivations = 1, "Workbook selection event opens actual search form"
    Check sheet.Range("F5").Value2 = "(전체)", "Escape preserves committed filter"
    Check sheet.Range("B6").Value2 = 1001, "Event-driven typing preserves totals"
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
    Dim sheet As Worksheet, candidates As Long
    Set sheet = ThisWorkbook.Worksheets("02.주요이슈_팀별")
    Set target = sheet.Range("F5")
    original = CStr(target.Value2)
    Check EFASearch.IsSelector(target), "Selector detection"
    Check Not EFASearch.IsSelector(sheet.Range("B6")), "Metric is not selector"
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
    Check sheet.Range("B6").Value2 = 1001, "Typing preserves totals"
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
    Check sheet.Range("B6").Value2 = 48, "Exact line count"
    Check sheet.Range("D6").Value2 = 1632, "Exact line minutes"
    Check Not EFASearch.CommitSelection(target, "컨베어"), "Wrong field candidate rejected"
    Check Not EFASearch.CommitSelection(target, "AJ10"), "Query cannot become selection"
    Check CStr(target.Value2) = "[남양주]AJ10-1-A", "Rejected commit preserves selection"
    Check EFASearch.CommitSelection(target, "(전체)"), "Reset selection"
    Check sheet.Range("B6").Value2 = 1001, "All reset count"
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
    Set sheet = ThisWorkbook.Worksheets("04.고장추이")
    Check EFASearch.CommitSelection(sheet.Range("B6"), "센서(종류 미상)"), "Part selector"
    total = 0
    For row = 8 To 18: total = total + sheet.Cells(row, 2).Value2: Next row
    Check total = 48, "Monthly part counts"
    Check EFASearch.CommitSelection(sheet.Range("B6"), "(전체)"), "Part reset"
    Set picker = New EFAPicker
    picker.Prepare target
    picker.Query.Text = "없는문자열xyz"
    Check picker.Candidates.ListCount = 0, "No match empty list"
    picker.ApplyChoice
    Check CStr(target.Value2) = "(전체)", "Empty list cannot commit"
    Unload picker
    VerifySearch = "PASS; candidates=" & CStr(candidates) & "; exact=48/1632; module=129/4854; part=48"
    Exit Function
Failed:
    VerifySearch = "FAIL; " & Err.Description
End Function
