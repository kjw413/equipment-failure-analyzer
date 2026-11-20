Option Explicit
Private FactsData As Variant

Private Sub Check(ByVal condition As Boolean, ByVal message As String)
    If Not condition Then Err.Raise vbObjectError + 1932, "HierarchicalComparisonQA", message
End Sub

Public Function VerifyFaultComparison(ByVal evidence As String) As String
    On Error GoTo Failed
    Dim ws As Worksheet, facts As Worksheet, units As Worksheet, state As Worksheet, sheet As Worksheet
    Dim i As Long, j As Long, last As Long, phase As String, errors As Range, cell As Range
    Dim org1 As String, org2 As String, line1 As String, line2 As String, module1 As String, module2 As String, targetModule As String
    Dim modules As Object, key As Variant, original As Variant, factory As String, team As String
    phase = "initialize"
    Set ws = ThisWorkbook.Worksheets("04.고장비교")
    Set facts = ThisWorkbook.Worksheets("_fault_facts")
    Set units = ThisWorkbook.Worksheets("_fault_units")
    Set state = ThisWorkbook.Worksheets("_fault_state")
    FactsData = facts.UsedRange.Value2
    EFASearch.Initialize
    Application.CalculateFull
    Check ThisWorkbook.Worksheets("_fault_controls").UsedRange.Rows.Count = 7, "Six controls, no comparison-unit selector"
    Check ws.Range("A7").Value2 = "기준 부서" And ws.Range("A9").Value2 = "비교 부서" And ws.Range("A8").Value2 = "VS", "Two rows with centered VS"
    Check ws.Range("A8").MergeArea.Address(False, False) = "A8:J8", "VS row layout"
    Check state.Range("B3").Value2 = "부서", "Department default from baseline depth"
    Check Application.Sum(ws.Range("E26:E" & ThisWorkbook.Names("_Fault_Labels").RefersToRange.Row + ThisWorkbook.Names("_Fault_Labels").RefersToRange.Rows.Count - 1)) = UBound(FactsData, 1) - 1, "All departments reconcile"
    Check Not EFASearch.CommitSelection(ws.Range("I7"), CStr(FactsData(2, 7))), "Module requires a selected baseline line"
    VerifyMetrics ws
    VerifyCandidates ws, "E7", "B7", ""
    For i = 2 To units.Cells(units.Rows.Count, 1).End(xlUp).Row
        Set modules = CreateObject("Scripting.Dictionary")
        For j = 2 To UBound(FactsData, 1)
            If FactsData(j, 16) = units.Cells(i, 1).Value2 Then modules(CStr(FactsData(j, 7))) = True
        Next j
        If modules.Count > 1 Then
            line1 = CStr(units.Cells(i, 1).Value2)
            factory = CStr(units.Cells(i, 2).Value2): team = CStr(units.Cells(i, 3).Value2)
            org1 = "[" & factory & "] " & team
            key = modules.Keys: module1 = CStr(key(0)): module2 = CStr(key(1))
            Exit For
        End If
    Next i
    Check Len(line1) > 0, "Multi-module baseline available"
    For i = 2 To units.Cells(units.Rows.Count, 1).End(xlUp).Row
        org2 = "[" & CStr(units.Cells(i, 2).Value2) & "] " & CStr(units.Cells(i, 3).Value2)
        If org2 <> org1 Then line2 = CStr(units.Cells(i, 1).Value2): Exit For
    Next i
    phase = "department pair"
    Check EFASearch.CommitSelection(ws.Range("B7"), org1), "Baseline organization"
    Check EFASearch.CommitSelection(ws.Range("B9"), org2), "Compare organization"
    Check state.Range("B4").Value2 = 2, "Only chosen departments"
    Check Not EFASearch.CommitSelection(ws.Range("E9"), line2), "Department level cannot silently use a comparison line"
    VerifyMetrics ws
    VerifyView ws, evidence & "/fault_department.pdf"
    phase = "independent line scopes"
    Check Not EFASearch.CommitSelection(ws.Range("E7"), line2), "Other organization's baseline line rejected"
    Check EFASearch.CommitSelection(ws.Range("E7"), line1), "Baseline line changes level automatically"
    Check state.Range("B3").Value2 = "라인", "Automatic line level"
    Check ws.Range("B9").Value2 = org2, "Baseline change preserves the independent comparison organization"
    VerifyCandidates ws, "E7", "B7", ""
    VerifyCandidates ws, "E9", "B9", ""
    VerifyCandidates ws, "I7", "B7", "E7"
    VerifyMetrics ws
    Check EFASearch.CommitSelection(ws.Range("E9"), line2), "Choose a line from another department or factory"
    Check state.Range("B4").Value2 = 2, "Two selected lines"
    VerifyMetrics ws
    VerifyView ws, evidence & "/fault_line.pdf"
    phase = "module comparisons"
    Check EFASearch.CommitSelection(ws.Range("I7"), module1), "Baseline module changes level automatically"
    Check state.Range("B3").Value2 = "상세설비", "Automatic module level"
    VerifyCandidates ws, "I9", "B9", "E9"
    VerifyMetrics ws
    For Each cell In EFASearch.SourceRange(ws.Range("I9")).Cells
        If CStr(cell.Value2) <> "(전체)" Then targetModule = CStr(cell.Value2): Exit For
    Next cell
    Check EFASearch.CommitSelection(ws.Range("I9"), targetModule), "Independent comparison module"
    Check state.Range("B4").Value2 = 2, "Two independently selected modules"
    VerifyMetrics ws
    Check EFASearch.CommitSelection(ws.Range("B9"), org1), "Compare organization reset"
    Check ws.Range("E9").Value2 = "(전체)" And ws.Range("I9").Value2 = "(전체)", "Compare parent clears only its descendants"
    Check ws.Range("E7").Value2 = line1 And ws.Range("I7").Value2 = module1, "Compare parent preserves baseline"
    VerifyMetrics ws
    Check EFASearch.CommitSelection(ws.Range("E9"), line1), "Same-line module comparison"
    Check EFASearch.CommitSelection(ws.Range("I9"), module2), "Other module on same line"
    Check state.Range("B4").Value2 = 2, "Different modules on same line remain two rows"
    VerifyMetrics ws
    VerifyView ws, evidence & "/fault_modules.pdf"
    Check EFASearch.CommitSelection(ws.Range("I9"), module1), "Identical module pair"
    Check state.Range("B4").Value2 = 1, "Identical physical line and module deduplicated"
    phase = "missing and zero time"
    original = facts.UsedRange.Value2
    For i = 2 To UBound(FactsData, 1)
        If FactsData(i, 16) = line1 And FactsData(i, 7) = module1 Then facts.Cells(i, 12).ClearContents
    Next i
    FactsData = facts.UsedRange.Value2
    Application.CalculateFull
    VerifyMetrics ws
    Check state.Range("B6").Value2 = "", "All missing baseline minutes are unavailable"
    VerifyView ws, evidence & "/fault_missing_time.pdf"
    For i = 2 To UBound(FactsData, 1)
        If FactsData(i, 16) = line1 And FactsData(i, 7) = module1 Then facts.Cells(i, 12).Value2 = 0
    Next i
    FactsData = facts.UsedRange.Value2
    Application.CalculateFull
    VerifyMetrics ws
    Check state.Range("B6").Value2 = 0, "Recorded zero minutes remain numeric zero"
    facts.UsedRange.Value2 = original
    FactsData = original
    phase = "resets and native change event"
    Application.CalculateFull
    Check EFASearch.CommitSelection(ws.Range("E7"), "(전체)"), "Return to department level"
    Check state.Range("B3").Value2 = "부서", "All line returns department aggregates"
    Check ws.Range("I7").Value2 = "(전체)" And ws.Range("E9").Value2 = "(전체)" And ws.Range("I9").Value2 = "(전체)", "Unavailable descendants reset"
    Check ws.Range("B9").Value2 = org1, "Comparison department retained across level change"
    Check state.Range("B4").Value2 = 1, "Same department shown once"
    Application.EnableEvents = True
    ws.Range("B9").Value2 = org2
    Check state.Range("B4").Value2 = 2, "Real worksheet change event"
    ws.Range("E7").Value2 = line1
    Check state.Range("B3").Value2 = "라인", "Native event updates level"
    Application.EnableEvents = False
    VerifyMetrics ws
    Check EFASearch.CommitSelection(ws.Range("B7"), org2), "Baseline parent change"
    Check ws.Range("E7").Value2 = "(전체)" And ws.Range("I7").Value2 = "(전체)", "Baseline parent resets its own descendants"
    Check ws.Range("B9").Value2 = org2, "Baseline department change does not replace comparison department"
    Check EFASearch.CommitSelection(ws.Range("B9"), "(전체)"), "Global compare department scope"
    Check EFASearch.CommitSelection(ws.Range("E7"), line2), "New baseline line"
    VerifyCandidates ws, "E9", "B9", ""
    VerifyMetrics ws
    Check EFASearch.CommitSelection(ws.Range("E7"), "(전체)"), "Final default department depth"
    VerifyRelatedViews
    VerifyCompanyNumberFormats
    VerifyIntegratedAppendices evidence
    For Each sheet In ThisWorkbook.Worksheets
        Set errors = Nothing
        On Error Resume Next
        Set errors = sheet.UsedRange.SpecialCells(xlCellTypeFormulas, xlErrors)
        On Error GoTo Failed
        Check errors Is Nothing, "No formula errors: " & sheet.Name
        If sheet.Visible = xlSheetVisible Then
            sheet.Activate
            Check Not ActiveWindow.FreezePanes, "No frozen panes: " & sheet.Name
        End If
    Next sheet
    VerifyFaultComparison = "PASS; records=" & CStr(UBound(FactsData, 1) - 1) & "; automatic_levels=ok; independent_scopes=ok; module_pairs=ok; missing_zero=ok; native_events=ok; descending_charts=ok; integrated_appendices=ok"
    Exit Function
Failed:
    Application.EnableEvents = False
    VerifyFaultComparison = "FAIL; phase=" & phase & "; " & CStr(Err.Number) & "; " & Err.Description
    On Error Resume Next
    Dim handle As Integer, c As Long, detail As String, values As Variant, labels As Variant
    handle = FreeFile
    Open evidence & "/failure.txt" For Output As #handle
    Print #handle, VerifyFaultComparison
    Print #handle, "State=" & state.Range("B3").Value2 & "; count=" & state.Range("B4").Value2
    For i = 2 To 14
        detail = ""
        For c = 1 To 10
            detail = detail & " | " & CStr(ThisWorkbook.Worksheets("_fault_chart_rank").Cells(i, c).Value2)
        Next c
        Print #handle, detail
    Next i
    For i = 1 To 2
        Print #handle, ws.ChartObjects(i).Chart.SeriesCollection(1).Formula
        values = ws.ChartObjects(i).Chart.SeriesCollection(1).Values
        labels = ws.ChartObjects(i).Chart.SeriesCollection(1).XValues
        For j = 1 To UBound(values)
            Print #handle, CStr(j) & ": " & CStr(labels(j)) & " = " & CStr(values(j))
        Next j
    Next i
    Close #handle
    VerifyView ws, evidence & "/failure.pdf"
End Function

Private Sub VerifyMetrics(ByVal ws As Worksheet)
    Application.CalculateFull
    EFASearch.RefreshFaultComparison
    Dim level As String, r As Long, i As Long, count As Long, valid As Long, total As Double, last As Long
    Dim baseCount As Long, baseValid As Long, baseTime As Double, baseLine As String, cell As Range
    level = CStr(ThisWorkbook.Worksheets("_fault_state").Range("B3").Value2)
    For Each cell In ThisWorkbook.Worksheets("_fault_units").Range("A2:A" & ThisWorkbook.Worksheets("_fault_units").UsedRange.Rows.Count)
        If cell.Value2 = ws.Range("E7").Value2 Then baseLine = CStr(cell.Offset(0, 4).Value2): Exit For
    Next cell
    For i = 2 To UBound(FactsData, 1)
        If FactsData(i, 3) = ThisWorkbook.Worksheets("_fault_state").Range("B2").Value2 And FactsData(i, 4) = ThisWorkbook.Worksheets("_fault_state").Range("B7").Value2 Then
            If level = "부서" Or FactsData(i, 5) = baseLine Then
                If level <> "상세설비" Or FactsData(i, 7) = ws.Range("I7").Value2 Then
                    baseCount = baseCount + 1
                    If Not IsEmpty(FactsData(i, 12)) And IsNumeric(FactsData(i, 12)) Then baseValid = baseValid + 1: baseTime = baseTime + CDbl(FactsData(i, 12))
                End If
            End If
        End If
    Next i
    Check ThisWorkbook.Worksheets("_fault_state").Range("B5").Value2 = baseCount, "Independent baseline count from original records"
    If baseValid > 0 Then Check Abs(ThisWorkbook.Worksheets("_fault_state").Range("B6").Value2 - baseTime) < 0.00001, "Independent baseline minutes"
    last = ThisWorkbook.Names("_Fault_Labels").RefersToRange.Row + ThisWorkbook.Names("_Fault_Labels").RefersToRange.Rows.Count - 1
    Dim shown As Long
    For r = 26 To last
        If Len(CStr(ws.Cells(r, 13).Value2)) > 0 Then
            shown = shown + 1: count = 0: valid = 0: total = 0
            For i = 2 To UBound(FactsData, 1)
                If FactsData(i, 3) = ws.Cells(r, 1).Value2 And FactsData(i, 4) = ws.Cells(r, 2).Value2 Then
                    If level = "부서" Or FactsData(i, 5) = ws.Cells(r, 3).Value2 Then
                        If level <> "상세설비" Or FactsData(i, 7) = ws.Cells(r, 12).Value2 Then
                            count = count + 1
                            If Not IsEmpty(FactsData(i, 12)) And IsNumeric(FactsData(i, 12)) Then valid = valid + 1: total = total + CDbl(FactsData(i, 12))
                        End If
                    End If
                End If
            Next i
            Check ws.Cells(r, 5).Value2 = count, "Every row count reconciles: " & ws.Cells(r, 13).Value2
            Check ws.Cells(r, 11).Value2 = valid, "Every valid-time count reconciles"
            If valid = 0 Then
                Check ws.Cells(r, 6).Value2 = "", "Missing duration stays blank"
            Else
                Check Abs(ws.Cells(r, 6).Value2 - total) < 0.00001, "Every duration reconciles"
            End If
            Check ws.Cells(r, 8).Value2 = count - baseCount, "Count delta uses baseline"
            If baseValid = 0 Or valid = 0 Then
                Check ws.Cells(r, 9).Value2 = "", "Unavailable duration delta stays blank"
            Else
                Check Abs(ws.Cells(r, 9).Value2 - (total - baseTime)) < 0.00001, "Duration delta uses baseline"
            End If
        End If
    Next r
    Check shown = ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2, "Visible count matches output table"
    VerifyCharts ws
End Sub

Private Sub VerifyCandidates(ByVal ws As Worksheet, ByVal address As String, ByVal organization As String, ByVal parent As String)
    Dim expected As Object, actual As Object, i As Long, org As String, candidate As String, cell As Range, key As Variant
    Set expected = CreateObject("Scripting.Dictionary"): Set actual = CreateObject("Scripting.Dictionary")
    For i = 2 To UBound(FactsData, 1)
        org = "[" & CStr(FactsData(i, 3)) & "] " & CStr(FactsData(i, 4))
        If ws.Range(organization).Value2 = "(전체)" Or org = ws.Range(organization).Value2 Then
            If Len(parent) = 0 Then
                expected(CStr(FactsData(i, 16))) = True
            ElseIf FactsData(i, 16) = ws.Range(parent).Value2 Then
                expected(CStr(FactsData(i, 7))) = True
            End If
        End If
    Next i
    For Each cell In EFASearch.SourceRange(ws.Range(address)).Cells
        candidate = CStr(cell.Value2)
        If candidate <> "(전체)" Then actual(candidate) = True
    Next cell
    Check expected.Count = actual.Count, "Exact scoped candidate count: " & address
    For Each key In expected.Keys
        Check actual.Exists(key), "Only candidates of selected parent: " & address
    Next key
End Sub

Private Sub VerifyView(ByVal ws As Worksheet, ByVal destination As String)
    ws.Activate
    ws.Range("A1").Select
    ws.Range("A1:L29").ExportAsFixedFormat 0, destination
End Sub

Private Sub VerifyRelatedViews()
    Dim main As Worksheet, trends As Worksheet, facts As Worksheet, name As String
    Dim r As Long, expected As Long, finish As Long, periodRows As Range, total As Double, month As String, first As Long
    Set main = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set trends = ThisWorkbook.Worksheets("03.월별 주요이슈")
    Set facts = ThisWorkbook.Worksheets("_issue_facts")
    Check EFASearch.ControlCell(main, "asset").Address(False, False) = "G7", "Edited team filter position"
    Check EFASearch.ControlCell(main, "part").Address(False, False) = "K8", "Edited team part position"
    Check EFASearch.ControlCell(trends, "part").Address(False, False) = "J8", "Edited month part position"
    Check ThisWorkbook.Names("_Period_Back").RefersToRange.Address(False, False) = "L7:L8", "Renewed return button"
    name = CStr(main.Range("B28").Value2)
    Check EFASearch.FollowChart(main.ChartObjects(1).Chart, 1), "Team chart drills from edited table position"
    Check main.Range("G7").Value2 = name, "Team leading line chosen"
    finish = facts.Cells(facts.Rows.Count, 1).End(xlUp).Row
    For r = 2 To finish
        If facts.Cells(r, 5).Value2 = name Then expected = expected + 1
    Next r
    Check main.Range("C10").Value2 = expected, "Team line drill count"
    Check EFASearch.CommitSelection(main.Range("G7"), "(전체)"), "Team reset"
    name = CStr(facts.Cells(2, 8).Value2)
    Check EFASearch.CommitSelection(trends.Range("J8"), name), "Month part selection"
    Set periodRows = ThisWorkbook.Names("_Period_Rows").RefersToRange
    Check periodRows.Row = 25, "Edited monthly table begins on row 24"
    first = periodRows.Row
    month = CStr(trends.Cells(first, 1).Value2)
    Dim axisLabels As Variant
    axisLabels = trends.ChartObjects(1).Chart.SeriesCollection(1).XValues
    Check CStr(axisLabels(1)) = "'" & Right$(month, 5), "Short month chart label"
    Check EFASearch.FollowPeriodChart(1), "Short chart label still drills into full month"
    Check trends.Range("D8").Value2 = month, "Full month selection from chart"
    Check EFASearch.BackToMonths(), "Return from chart drill"
    total = trends.Cells(first, 2).Value2
    Application.EnableEvents = True
    trends.Range("D8").Value2 = month
    Check trends.Range("B8").Value2 = "일별", "Edited month selector activates daily view"
    Check trends.Range("J8").Value2 = name, "Month selection preserves part selector"
    Check Abs(Application.Sum(trends.Range("B" & first & ":B" & first + 30)) - total) < 0.00001, "Month-day reconciliation after template move"
    Check EFASearch.BackToMonths(), "Monthly return"
    Check EFASearch.CommitSelection(trends.Range("J8"), "(전체)"), "Month part reset"
    Application.EnableEvents = False
End Sub

Private Sub VerifyCharts(ByVal sheet As Worksheet)
    Dim metric As Long, values As Variant, labels As Variant, i As Long, available As Long, column As String
    For metric = 1 To 2
        sheet.ChartObjects(metric).Chart.Refresh
        values = sheet.ChartObjects(metric).Chart.SeriesCollection(1).Values
        labels = sheet.ChartObjects(metric).Chart.SeriesCollection(1).XValues
        column = IIf(metric = 1, "E", "F")
        available = Application.Count(ThisWorkbook.Worksheets("_fault_chart_rank").Columns(column))
        If available = 0 Then
            Check IsError(ThisWorkbook.Worksheets("_fault_chart_rank").Range(IIf(metric = 1, "H2", "J2")).Value2), "Unavailable chart source is explicitly N/A"
            ' Excel's Series.Values getter can expose an N/A point as Empty or "".
            Check IsError(values(1)) Or IsEmpty(values(1)) Or (VarType(values(1)) = vbString And Len(CStr(values(1))) = 0), "Unavailable chart has no numeric zero point"
            If sheet.ChartObjects(metric).Chart.SeriesCollection(1).HasDataLabels Then
                Check Not sheet.ChartObjects(metric).Chart.SeriesCollection(1).DataLabels.ShowValue, "Unavailable chart hides the N/A data label"
            End If
            Check CStr(labels(1)) = "시간 미기재" Or CStr(labels(1)) = "해당 조건의 이력 없음", "Clear empty-chart label"
        Else
            Check UBound(values) = WorksheetFunction.Min(10, available), "Only available top candidates"
            For i = 1 To UBound(values)
                Check Len(CStr(labels(i))) > 0, "Real chart labels"
                If i > 1 Then Check values(i - 1) >= values(i), "Independent metric descending chart"
            Next i
        End If
        Check InStr(1, sheet.ChartObjects(metric).Chart.ChartTitle.Text, ThisWorkbook.Worksheets("_fault_state").Range("B3").Value2 & "별") > 0, "Title follows comparison level"
    Next metric
End Sub

Private Function ModuleCount(ByVal facts As Worksheet, ByVal line As String, ByVal moduleName As String) As Long
    Dim r As Long
    For r = 2 To facts.Cells(facts.Rows.Count, 1).End(xlUp).Row
        If CStr(facts.Cells(r, 5).Value2) = line Then
            If moduleName = "(전체)" Or CStr(facts.Cells(r, 7).Value2) = moduleName Then ModuleCount = ModuleCount + 1
        End If
    Next r
End Function

Private Sub VerifyModuleCandidates(ByVal target As Range, ByVal facts As Worksheet, ByVal line As String)
    Dim expected As Object, actual As Object, r As Long, cell As Range, key As Variant
    Set expected = CreateObject("Scripting.Dictionary")
    Set actual = CreateObject("Scripting.Dictionary")
    For r = 2 To facts.Cells(facts.Rows.Count, 1).End(xlUp).Row
        If CStr(facts.Cells(r, 5).Value2) = line Then expected(CStr(facts.Cells(r, 7).Value2)) = True
    Next r
    For Each cell In EFASearch.SourceRange(target).Cells
        If CStr(cell.Value2) <> "(전체)" Then actual(CStr(cell.Value2)) = True
    Next cell
    Check expected.Count = actual.Count, "Exact scoped moduleName list: " & target.Address
    For Each key In expected.Keys
        Check actual.Exists(key), "Module candidate belongs to selected line"
    Next key
End Sub

Private Sub VerifyCompanyNumberFormats()
    Dim sheet As Worksheet, item As ChartObject, series As Series, axis As Axis, point As Point
    Dim charts As Long, grouped As Long
    For Each sheet In ThisWorkbook.Worksheets
        For Each item In sheet.ChartObjects
            charts = charts + 1
            item.Chart.Refresh
            For Each axis In item.Chart.Axes
                If axis.Type = xlValue Then
                    Check axis.TickLabels.NumberFormat = "#,##0", "Grouped integer value axis: " & sheet.Name
                    Check Not axis.TickLabels.NumberFormatLinked, "Axis format does not inherit General"
                End If
            Next axis
            For Each series In item.Chart.SeriesCollection
                If series.HasDataLabels Then
                    Check series.DataLabels.NumberFormat = "#,##0", "Grouped integer labels: " & sheet.Name
                    Check Not series.DataLabels.NumberFormatLinked, "Label format does not inherit General"
                    For Each point In series.Points
                        If point.HasDataLabel Then
                            If InStr(1, CStr(point.DataLabel.Text), ",") > 0 Then grouped = grouped + 1
                        End If
                    Next point
                End If
            Next series
        Next item
    Next sheet
    Check charts = 6, "Every analysis chart checked"
    Check grouped > 0, "Thousands separators appear in rendered label text"
End Sub

Private Sub VerifyIntegratedAppendices(ByVal evidence As String)
    Dim s As Worksheet, overview As Worksheet, raw As Worksheet, visible As Long
    For Each s In ThisWorkbook.Worksheets
        Check s.Name <> "별첨. 동일 상세설비 비교" And s.Name <> "별첨. 기준정보", "Obsolete appendices removed"
        If s.Visible = xlSheetVisible Then visible = visible + 1
    Next s
    Check visible = 7, "Seven report sheets"
    Set overview = ThisWorkbook.Worksheets("별첨. 검토·분류현황")
    Set raw = ThisWorkbook.Worksheets("별첨. 원본 검토표시")
    Check overview.Range("B7").Value2 = 2117, "Review overview analysis count"
    Dim row As Long, first As Long, last As Long, sourceRow As Long, count As Long, col As Long, noteFound As Boolean, legendRow As Long, statusColumn As Long
    statusColumn = overview.AutoFilter.Range.Rows(1).Find(What:="분류 상태", LookAt:=xlWhole).Column
    first = overview.AutoFilter.Range.Row + 1
    last = first + CLng(overview.Range("C7").Value2) - 1
    For row = first To last
        sourceRow = CLng(overview.Cells(row, 2).Value2)
        Check raw.Cells(sourceRow, 1).Interior.Pattern = xlSolid, "Review source row is highlighted"
        Select Case CStr(overview.Cells(row, statusColumn).Value2)
            Case "검토필요": legendRow = 11
            Case "규칙 미일치": legendRow = 12
            Case "비가동코드 미기입": legendRow = 13
            Case Else: legendRow = 14
        End Select
        Check raw.Cells(sourceRow, 1).Interior.Color = overview.Cells(legendRow, 7).Interior.Color, "Source color matches review legend"
        noteFound = False
        For col = 1 To 24
            If Not raw.Cells(sourceRow, col).Comment Is Nothing Then
                If InStr(1, raw.Cells(sourceRow, col).Comment.Text, "검토필요 유형") > 0 Then noteFound = True
            End If
        Next col
        Check noteFound, "Review source row contains its reason memo"
        Check InStr(1, CStr(overview.Cells(row, 2).Formula), "원본 검토표시") > 0, "Source-row hyperlink"
        count = count + 1
    Next row
    Check count = overview.Range("C7").Value2, "Every review links to an annotated source row"
    overview.Activate
    overview.Range("A1").Select
    overview.Range("A1:K19").ExportAsFixedFormat 0, evidence & "/review_summary.pdf"
    sourceRow = CLng(overview.Cells(first, 2).Value2)
    raw.PageSetup.Orientation = xlLandscape
    raw.PageSetup.Zoom = False
    raw.PageSetup.FitToPagesWide = 1
    raw.PageSetup.FitToPagesTall = 1
    raw.Range("S" & CStr(sourceRow) & ":X" & CStr(sourceRow + 3)).ExportAsFixedFormat 0, evidence & "/raw_review.pdf"
End Sub
