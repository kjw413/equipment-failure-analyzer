Option Explicit
Private Sub Check(ByVal condition As Boolean, ByVal message As String)
    If Not condition Then Err.Raise vbObjectError + 1900, "FaultComparisonQA", message
End Sub

Public Function VerifyFaultComparison(ByVal evidence As String) As String
    On Error GoTo Failed
    Dim ws As Worksheet, facts As Worksheet, count As Long, finish As Long, r As Long, last As Long
    Dim factories As Object, teams As Object, lines As Object, families As Object, candidates As Object
    Dim factory As String, family As String, line As String, key As Variant, cell As Range, total As Double, selectedCount As Long
    Dim firstLine As String, lastLine As String, before As Double, expected As Long, maxLines As Long, phase As String
    phase = "initial"
    Set ws = ThisWorkbook.Worksheets("04.고장비교")
    Set facts = ThisWorkbook.Worksheets("_fault_facts")
    Check ThisWorkbook.Worksheets(3).Name = "03.월별 주요이슈" And ThisWorkbook.Worksheets(4).Name = ws.Name, "Report order"
    For Each key In Array("04.팀간 비교", "03.팀간 비교")
        Set cell = Nothing
        On Error Resume Next
        Set cell = ThisWorkbook.Worksheets(CStr(key)).Range("A1")
        On Error GoTo Failed
        Check cell Is Nothing, "Obsolete team comparison sheet removed"
    Next key
    finish = facts.Cells(facts.Rows.Count, 1).End(xlUp).Row
    count = finish - 1
    last = ThisWorkbook.Names("_Fault_TableRows").RefersToRange.Row + ThisWorkbook.Names("_Fault_TableRows").RefersToRange.Rows.Count - 1
    EFASearch.Initialize
    Application.CalculateFull
    Check ws.Range("B6").Value2 = "부서", "Department default"
    VerifyFaultFilterView ws
    Check Application.Sum(ws.Range("E25:E" & last)) = count, "Department count reconciles"
    total = Application.Sum(facts.Range("L2:L" & finish))
    Check Abs(Application.Sum(ws.Range("F25:F" & last)) - total) < 0.00001, "Department time reconciles"
    Set factories = CreateObject("Scripting.Dictionary")
    For Each cell In EFASearch.SourceRange(ws.Range("B7")).Cells
        If CStr(cell.Value2) <> "(전체)" Then
            Set lines = CreateObject("Scripting.Dictionary")
            For r = 2 To finish
                If facts.Cells(r, 3).Value2 = cell.Value2 Then lines(CStr(facts.Cells(r, 4).Value2) & " / " & CStr(facts.Cells(r, 5).Value2)) = True
            Next r
            If lines.Count > maxLines Then maxLines = lines.Count: factory = CStr(cell.Value2)
        End If
    Next cell
    Check Len(factory) > 0, "Factory with comparison lines"
    Check EFASearch.CommitSelection(ws.Range("B6"), "라인"), "First line mode"
    Check ws.Range("B7").Value2 <> "(전체)", "Line mode chooses an explicit factory"
    VerifyFaultFilterView ws
    Check Not EFASearch.CommitSelection(ws.Range("E6"), CStr(ws.Range("E6").Value2)), "Hidden department selector cannot be edited"
    Check EFASearch.CommitSelection(ws.Range("B6"), "부서"), "Return to department filters"
    VerifyFaultFilterView ws
    Check EFASearch.CommitSelection(ws.Range("B7"), factory), "Factory selection"
    Check EFASearch.CommitSelection(ws.Range("B6"), "라인"), "Line mode selection"
    VerifyFaultFilterView ws
    Check ws.PageSetup.FitToPagesTall = False, "Line table is not shrunk to one printed page"
    Set lines = CreateObject("Scripting.Dictionary")
    Set teams = CreateObject("Scripting.Dictionary")
    Set families = CreateObject("Scripting.Dictionary")
    expected = 0: total = 0
    For r = 2 To finish
        If facts.Cells(r, 3).Value2 = factory Then
            lines(CStr(facts.Cells(r, 4).Value2) & " / " & CStr(facts.Cells(r, 5).Value2)) = True
            teams(CStr(facts.Cells(r, 4).Value2)) = True
            families(CStr(facts.Cells(r, 15).Value2)) = True
            expected = expected + 1
            If IsNumeric(facts.Cells(r, 12).Value2) Then total = total + CDbl(facts.Cells(r, 12).Value2)
        End If
    Next r
    Check teams.Count > 1 And lines.Count > 1, "Cross-team, multiple line fixture"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = lines.Count, "All factory lines across teams are present"
    Check Application.Sum(ws.Range("E25:E" & last)) = expected, "Line totals reconcile with whole factory"
    Check Abs(Application.Sum(ws.Range("F25:F" & last)) - total) < 0.00001, "Line time reconciles"
    Check Application.Count(ws.Range("H25:I" & last)) = 0, "No implicit line baseline before selection"
    Set candidates = CreateObject("Scripting.Dictionary")
    For Each cell In EFASearch.SourceRange(ws.Range("F7")).Cells
        If CStr(cell.Value2) <> "(전체)" Then candidates(CStr(cell.Value2)) = True
    Next cell
    Check candidates.Count = lines.Count, "Baseline line list includes other teams"
    For r = 25 To last
        If Len(CStr(ws.Cells(r, 13).Value2)) > 0 Then
            Check ws.Cells(r, 1).Value2 = factory, "No other factory appears"
            Check Len(CStr(ws.Cells(r, 4).Value2)) > 0, "Equipment group is shown"
            Check lines.Exists(CStr(ws.Cells(r, 2).Value2) & " / " & CStr(ws.Cells(r, 3).Value2)), "Line identity retained"
        End If
    Next r
    key = candidates.Keys
    firstLine = CStr(key(0)): lastLine = CStr(key(UBound(key)))
    Check EFASearch.CommitSelection(ws.Range("F7"), firstLine), "First baseline line"
    before = Application.Sum(ws.Range("E25:E" & last))
    Check EFASearch.CommitSelection(ws.Range("F7"), lastLine), "Other baseline line"
    Check Application.Sum(ws.Range("E25:E" & last)) = before, "Baseline selection never narrows the population"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = lines.Count, "All lines remain after baseline change"
    For Each key In families.Keys
        family = CStr(key)
        Check EFASearch.CommitSelection(ws.Range("B8"), family), "Equipment group filter"
        selectedCount = 0
        For r = 2 To finish
            If facts.Cells(r, 3).Value2 = factory And facts.Cells(r, 15).Value2 = family Then selectedCount = selectedCount + 1
        Next r
        Check Application.Sum(ws.Range("E25:E" & last)) = selectedCount, "Group-filtered counts reconcile"
        For r = 25 To last
            If Len(CStr(ws.Cells(r, 13).Value2)) > 0 Then Check ws.Cells(r, 4).Value2 = family, "Only selected group rows shown"
        Next r
    Next key
    Check EFASearch.CommitSelection(ws.Range("B8"), "(전체)"), "All groups reset"
    Check EFASearch.CommitSelection(ws.Range("B6"), "부서"), "Department mode restored"
    Check EFASearch.CommitSelection(ws.Range("B7"), "(전체)"), "All factory reset"
    Check Application.Sum(ws.Range("E25:E" & last)) = count, "Department totals restored"
    For Each key In families.Keys
        family = CStr(key)
        If EFASearch.CommitSelection(ws.Range("B8"), family) Then
            selectedCount = 0
            For r = 2 To finish
                If facts.Cells(r, 15).Value2 = family Then selectedCount = selectedCount + 1
            Next r
            Check Application.Sum(ws.Range("E25:E" & last)) = selectedCount, "Same group across departments ignores differing line codes"
            Exit For
        End If
    Next key
    Check EFASearch.CommitSelection(ws.Range("B8"), "(전체)"), "Department family reset"
    Application.EnableEvents = True
    ws.Range("B6").Value2 = "unsupported"
    Check ws.Range("B6").Value2 = "부서", "Invalid mode edit reverted"
    ws.Range("B7").Value2 = factory
    ws.Range("B6").Value2 = "라인"
    Check Application.Sum(ws.Range("E25:E" & last)) = expected, "Direct dropdown change event"
    ws.Range("D7").Value2 = "invalid team"
    Check ws.Range("D7").Value2 = "(전체)", "Line comparison keeps all teams"
    Application.EnableEvents = False
    Application.CalculateFull
    VerifyCharts ws
    Check ws.AutoFilterMode, "Native table filter is available"
    phase = "table filter"
    family = CStr(families.Keys()(0))
    ws.Range("A24:K" & last).AutoFilter Field:=4, Criteria1:="=" & Replace(Replace(Replace(family, "~", "~~"), "*", "~*"), "?", "~?")
    Application.CalculateFull
    Check ws.AutoFilter.Filters(4).On, "Equipment group column filter applied"
    VerifyCharts ws
    phase = "clear table filter"
    Check EFASearch.CommitSelection(ws.Range("F7"), firstLine), "Control change clears table filter"
    Check Not ws.AutoFilter.Filters(4).On, "Table filter cleared for new selection"
    Check Application.Sum(ws.Range("E25:E" & last)) = expected, "Factory population restored after native table filter"
    Application.CalculateFull
    ws.Activate
    ws.Select Replace:=True
    ws.Range("A1").Select
    ws.ExportAsFixedFormat 0, evidence & "/fault_line.pdf"
    Check EFASearch.CommitSelection(ws.Range("B6"), "부서"), "Final department restore"
    Check EFASearch.CommitSelection(ws.Range("B7"), "(전체)"), "Final factory restore"
    ws.Range("A1").Select
    ws.ExportAsFixedFormat 0, evidence & "/fault_department.pdf"
    VerifyCharts ws
    phase = "related views"
    VerifyRelatedViews
    Dim s As Worksheet, errors As Range
    For Each s In ThisWorkbook.Worksheets
        Set errors = Nothing
        On Error Resume Next
        Set errors = s.UsedRange.SpecialCells(xlCellTypeFormulas, xlErrors)
        On Error GoTo Failed
        Check errors Is Nothing, "No formula errors: " & s.Name
    Next s
    VerifyFaultComparison = "PASS; records=" & count & "; factory=" & factory & "; all_factory_lines=" & lines.Count & "; teams=" & teams.Count & "; groups=" & families.Count & "; baseline_independent=ok; family_filter=ok; department_group_comparison=ok; change_events=ok; charts=descending"
    Exit Function
Failed:
    VerifyFaultComparison = "FAIL; " & phase & "; " & Err.Description
End Function

Private Sub VerifyFaultFilterView(ByVal sheet As Worksheet)
    Dim metadata As Worksheet, r As Long, active As Boolean, count As Long, area As Variant, edge As Variant
    Dim mode As String, cell As Range, box As Range
    Set metadata = ThisWorkbook.Worksheets("_fault_controls")
    mode = CStr(sheet.Range("B6").Value2)
    For r = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        Set cell = sheet.Range(metadata.Cells(r, 2).Value2)
        active = InStr(1, "," & CStr(metadata.Cells(r, 6).Value2) & ",", "," & mode & ",", vbBinaryCompare) > 0
        Check EFASearch.IsSelector(cell) = active, "Only active filter fields have dropdown/search"
        If active Then count = count + 1
        For Each area In Array(metadata.Cells(r, 4).Value2, metadata.Cells(r, 5).Value2)
            Set box = sheet.Range(CStr(area))
            If active Then
                Check box.Font.Color <> RGB(255, 255, 255), "Visible filter text restored"
                For Each edge In Array(xlEdgeLeft, xlEdgeTop, xlEdgeRight, xlEdgeBottom)
                    Check box.Borders(CLng(edge)).LineStyle = xlContinuous, "Complete border: " & CStr(area)
                Next edge
            Else
                Check box.NumberFormat = ";;;", "Inactive filter content is hidden"
                Check box.Font.Color = RGB(255, 255, 255), "Inactive filter caption is hidden"
            End If
        Next area
    Next r
    Check count = IIf(mode = "부서", 6, 5), "Mode-specific filter count"
End Sub

Private Sub VerifyRelatedViews()
    Dim main As Worksheet, trends As Worksheet, facts As Worksheet, name As String
    Dim r As Long, expected As Long, finish As Long, periodRows As Range, total As Double, month As String, first As Long
    Set main = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set trends = ThisWorkbook.Worksheets("03.월별 주요이슈")
    Set facts = ThisWorkbook.Worksheets("_issue_facts")
    Check EFASearch.ControlCell(main, "asset").Address(False, False) = "G6", "Edited team filter position"
    Check EFASearch.ControlCell(main, "part").Address(False, False) = "K7", "Edited team part position"
    Check EFASearch.ControlCell(trends, "part").Address(False, False) = "F7", "Edited month part position"
    name = CStr(main.Range("B27").Value2)
    Check EFASearch.FollowChart(main.ChartObjects(1).Chart, 1), "Team chart drills from edited table position"
    Check main.Range("G6").Value2 = name, "Team leading line chosen"
    finish = facts.Cells(facts.Rows.Count, 1).End(xlUp).Row
    For r = 2 To finish
        If facts.Cells(r, 5).Value2 = name Then expected = expected + 1
    Next r
    Check main.Range("C9").Value2 = expected, "Team line drill count"
    Check EFASearch.CommitSelection(main.Range("G6"), "(전체)"), "Team reset"
    name = CStr(facts.Cells(2, 8).Value2)
    Check EFASearch.CommitSelection(trends.Range("F7"), name), "Month part selection"
    Set periodRows = ThisWorkbook.Names("_Period_Rows").RefersToRange
    Check periodRows.Row = 24, "Edited monthly table begins on row 24"
    first = periodRows.Row
    month = CStr(trends.Cells(first, 1).Value2)
    total = trends.Cells(first, 2).Value2
    Application.EnableEvents = True
    trends.Range("D7").Value2 = month
    Check trends.Range("B7").Value2 = "일별", "Edited month selector activates daily view"
    Check trends.Range("F7").Value2 = name, "Month selection preserves part selector"
    Check Abs(Application.Sum(trends.Range("B" & first & ":B" & first + 30)) - total) < 0.00001, "Month-day reconciliation after template move"
    Check EFASearch.BackToMonths(), "Monthly return"
    Check EFASearch.CommitSelection(trends.Range("F7"), "(전체)"), "Month part reset"
    Application.EnableEvents = False
End Sub

Private Sub VerifyCharts(ByVal sheet As Worksheet)
    Dim metric As Long, values As Variant, labels As Variant, i As Long
    For metric = 1 To 2
        sheet.ChartObjects(metric).Chart.Refresh
        values = sheet.ChartObjects(metric).Chart.SeriesCollection(1).Values
        labels = sheet.ChartObjects(metric).Chart.SeriesCollection(1).XValues
        For i = 1 To UBound(values)
            Check Len(CStr(labels(i))) > 0, "Real chart labels"
            If i > 1 Then Check values(i - 1) >= values(i), "Independent metric descending chart"
        Next i
    Next metric
End Sub
