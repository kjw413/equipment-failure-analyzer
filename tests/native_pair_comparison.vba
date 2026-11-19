Option Explicit
Private Sub Check(ByVal condition As Boolean, ByVal message As String)
    If Not condition Then Err.Raise vbObjectError + 1900, "FaultComparisonQA", message
End Sub

Public Function VerifyFaultComparison(ByVal evidence As String) As String
    On Error GoTo Failed
    Dim ws As Worksheet, facts As Worksheet, units As Worksheet, s As Worksheet, errors As Range
    Dim last As Long, finish As Long, r As Long, n As Long, total As Double, phase As String
    Dim org1 As String, org2 As String, line1 As String, line2 As String, foreign As String, factory As String
    Dim lines As Object, teams As Object, families As Object, candidates As Object, counts As Object
    Dim cell As Range, key As Variant, maxLines As Long, expected As Long, baseline As Long, before As Double
    phase = "initialize"
    Set ws = ThisWorkbook.Worksheets("04.고장비교")
    Set facts = ThisWorkbook.Worksheets("_fault_facts")
    Set units = ThisWorkbook.Worksheets("_fault_units")
    finish = facts.Cells(facts.Rows.Count, 1).End(xlUp).Row
    last = ThisWorkbook.Names("_Fault_TableRows").RefersToRange.Row + ThisWorkbook.Names("_Fault_TableRows").RefersToRange.Rows.Count - 1
    EFASearch.Initialize
    Application.CalculateFull
    Check ws.Range("B6").Value2 = "부서", "Department default"
    Check Not EFASearch.IsSelector(ws.Range("B6")), "Mode uses native list, no search popup"
    Check ws.Range("B6").Validation.Type = xlValidateList, "Native mode dropdown"
    Check EFASearch.SourceRange(ws.Range("B6")).Cells.Count = 2, "Exactly two mode choices"
    VerifyFaultFilterView ws
    Check Application.Sum(ws.Range("E25:E" & last)) = finish - 1, "All department records"
    Check Application.Sum(ws.Range("F25:F" & last)) = Application.Sum(facts.Range("L2:L" & finish)), "All department minutes"
    org1 = CStr(ws.Range("D6").Value2)
    For Each cell In EFASearch.SourceRange(ws.Range("D7")).Cells
        If CStr(cell.Value2) <> "(전체)" And CStr(cell.Value2) <> org1 Then org2 = CStr(cell.Value2): Exit For
    Next cell
    phase = "department pair"
    Check EFASearch.CommitSelection(ws.Range("D7"), org2), "Compare department selection"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = 2, "Two departments only"
    For r = 25 To last
        If Len(CStr(ws.Cells(r, 13).Value2)) > 0 Then
            key = CStr(ws.Cells(r, 1).Value2) & " / " & CStr(ws.Cells(r, 2).Value2)
            Check key = org1 Or key = org2, "Chosen departments displayed"
        End If
    Next r
    VerifyCharts ws
    Check EFASearch.CommitSelection(ws.Range("D7"), org1), "Same department allowed"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = 1, "Same department not duplicated"
    Check EFASearch.CommitSelection(ws.Range("D7"), "(전체)"), "All department reset"
    ws.Activate: ws.Select Replace:=True: ws.Range("A1").Select
    ws.ExportAsFixedFormat 0, evidence & "/fault_department.pdf"
    phase = "line mode"
    Check EFASearch.CommitSelection(ws.Range("B6"), "라인"), "Line mode"
    VerifyFaultFilterView ws
    Check Not EFASearch.CommitSelection(ws.Range("D6"), org1), "Inactive department cannot be edited"
    Set counts = CreateObject("Scripting.Dictionary")
    For r = 2 To units.Cells(units.Rows.Count, 1).End(xlUp).Row
        key = CStr(units.Cells(r, 2).Value2)
        If Not counts.Exists(key) Then counts(key) = 0
        counts(key) = counts(key) + 1
    Next r
    For Each key In counts.Keys
        If counts(key) > maxLines Then maxLines = counts(key): factory = CStr(key)
    Next key
    Set lines = CreateObject("Scripting.Dictionary")
    Set teams = CreateObject("Scripting.Dictionary")
    Set families = CreateObject("Scripting.Dictionary")
    For r = 2 To finish
        If CStr(facts.Cells(r, 3).Value2) = factory Then
            lines(CStr(facts.Cells(r, 5).Value2)) = True
            teams(CStr(facts.Cells(r, 4).Value2)) = True
            families(CStr(facts.Cells(r, 15).Value2)) = True
            expected = expected + 1
        Else
            foreign = CStr(facts.Cells(r, 5).Value2)
        End If
    Next r
    key = lines.Keys: line1 = CStr(key(0)): line2 = CStr(key(UBound(key)))
    Check EFASearch.CommitSelection(ws.Range("G6"), line1), "Baseline line selects factory"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B2").Value2 = factory, "Baseline factory inferred"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = lines.Count, "All factory lines across teams"
    Check Application.Sum(ws.Range("E25:E" & last)) = expected, "Factory records reconcile"
    Set candidates = CreateObject("Scripting.Dictionary")
    For Each cell In EFASearch.SourceRange(ws.Range("G7")).Cells
        If CStr(cell.Value2) <> "(전체)" Then candidates(CStr(cell.Value2)) = True
    Next cell
    Check candidates.Count = lines.Count, "Compare list scoped to factory"
    Check Not candidates.Exists(foreign), "Foreign line excluded"
    Check Not EFASearch.CommitSelection(ws.Range("G7"), foreign), "Foreign line rejected"
    before = Application.Sum(ws.Range("E25:E" & last))
    Check EFASearch.CommitSelection(ws.Range("G6"), line2), "Other baseline line"
    Check Application.Sum(ws.Range("E25:E" & last)) = before, "Baseline independent population"
    Check ws.Range("G7").Value2 = "(전체)", "New baseline resets comparisonOrg target"
    Check ws.PageSetup.FitToPagesTall = False, "Line print keeps readable multipage rows"
    VerifyCharts ws
    ws.Range("A1").Select
    ws.ExportAsFixedFormat 0, evidence & "/fault_line.pdf"
    phase = "line pair"
    Check EFASearch.CommitSelection(ws.Range("G7"), line1), "Specific comparison line"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = 2, "Two lines displayed"
    baseline = CLng(ThisWorkbook.Worksheets("_fault_state").Range("B5").Value2)
    For r = 25 To last
        If Len(CStr(ws.Cells(r, 13).Value2)) > 0 Then
            Check ws.Cells(r, 3).Value2 = line1 Or ws.Cells(r, 3).Value2 = line2, "Chosen line identities"
            Check ws.Cells(r, 8).Value2 = ws.Cells(r, 5).Value2 - baseline, "Baseline count delta"
        End If
    Next r
    VerifyCharts ws
    Check ws.PageSetup.FitToPagesTall = 1, "Two selected lines print together on one page"
    ws.ExportAsFixedFormat 0, evidence & "/fault_pair.pdf"
    Check EFASearch.CommitSelection(ws.Range("G7"), line2), "Same baseline comparison"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = 1, "Same line appears once"
    Check EFASearch.CommitSelection(ws.Range("G7"), "(전체)"), "All lines restored"
    phase = "independent moduleName scopes"
    Check EFASearch.CommitSelection(ws.Range("G7"), line1), "Module comparison line"
    Dim baseModule As String, compareModule As String, otherModule As String, sourceModules As Object
    For Each cell In EFASearch.SourceRange(ws.Range("D8")).Cells
        If CStr(cell.Value2) <> "(전체)" Then baseModule = CStr(cell.Value2): Exit For
    Next cell
    For Each cell In EFASearch.SourceRange(ws.Range("G8")).Cells
        If CStr(cell.Value2) <> "(전체)" Then compareModule = CStr(cell.Value2): Exit For
    Next cell
    Check Len(baseModule) > 0 And Len(compareModule) > 0, "Scoped moduleName candidates"
    VerifyModuleCandidates ws.Range("D8"), facts, line2
    VerifyModuleCandidates ws.Range("G8"), facts, line1
    Check EFASearch.CommitSelection(ws.Range("D8"), baseModule), "Baseline moduleName"
    Check EFASearch.CommitSelection(ws.Range("G8"), compareModule), "Comparison moduleName"
    Check ws.Range("D8").Value2 = baseModule, "Comparison moduleName preserves baseline moduleName"
    For r = 25 To last
        If Len(CStr(ws.Cells(r, 13).Value2)) > 0 Then
            key = CStr(ws.Cells(r, 3).Value2)
            Check ws.Cells(r, 12).Value2 = IIf(key = line2, baseModule, compareModule), "Displayed per-line moduleName"
            n = ModuleCount(facts, CStr(key), CStr(ws.Cells(r, 12).Value2))
            Check ws.Cells(r, 5).Value2 = n, "Each line uses its own moduleName count"
        End If
    Next r
    VerifyCharts ws
    ws.ExportAsFixedFormat 0, evidence & "/fault_modules.pdf"
    phase = "same line different modules"
    Check EFASearch.CommitSelection(ws.Range("G7"), line2), "Same line with different modules"
    Check EFASearch.CommitSelection(ws.Range("G8"), baseModule), "Same line same moduleName"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = 1, "Identical line-moduleName pair deduplicated"
    For Each cell In EFASearch.SourceRange(ws.Range("G8")).Cells
        If CStr(cell.Value2) <> "(전체)" And CStr(cell.Value2) <> baseModule Then otherModule = CStr(cell.Value2): Exit For
    Next cell
    If Len(otherModule) > 0 Then
        Check EFASearch.CommitSelection(ws.Range("G8"), otherModule), "Other moduleName on same line"
        Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = 2, "Different modules on one line comparisonOrg as two rows"
        VerifyCharts ws
    End If
    Check EFASearch.CommitSelection(ws.Range("D8"), "(전체)"), "Baseline moduleName reset"
    Check EFASearch.CommitSelection(ws.Range("G8"), "(전체)"), "Compare moduleName reset"
    Check EFASearch.CommitSelection(ws.Range("G7"), "(전체)"), "All lines reset"
    Check Application.Sum(ws.Range("E25:E" & last)) = expected, "Module reset restores factory total"
    Check EFASearch.CommitSelection(ws.Range("D8"), baseModule), "Select module before mode switch"
    phase = "native changes"
    Application.EnableEvents = True
    ws.Range("B6").Value2 = "unsupported"
    Check ws.Range("B6").Value2 = "라인", "Invalid native dropdown reverted"
    ws.Range("B6").Value2 = "부서"
    Check ws.Range("B6").Value2 = "부서", "Native dropdown change event"
    Check ws.Range("D8").Value2 = "(전체)" And ws.Range("G8").Value2 = "(전체)", "Department switch clears line modules"
    VerifyFaultFilterView ws
    Check Application.Sum(ws.Range("E25:E" & last)) = finish - 1, "Dept restored"
    ws.Range("D7").Value2 = org2
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = 2, "Native comparisonOrg department event"
    Application.EnableEvents = False
    Check EFASearch.CommitSelection(ws.Range("D7"), "(전체)"), "Final department reset"
    phase = "department moduleName scopes"
    VerifyDepartmentTotals ws, facts, org1, org2, last
    Check EFASearch.CommitSelection(ws.Range("D7"), "(전체)"), "Final comparisonOrg department reset"
    VerifyCompanyNumberFormats
    phase = "related views"
    VerifyRelatedViews
    VerifyCompanyNumberFormats
    For Each s In ThisWorkbook.Worksheets
        If s.Visible = xlSheetVisible Then
            s.Activate
            Check Not ActiveWindow.FreezePanes, "No unrequested frozen panes: " & s.Name
        End If
        Set errors = Nothing
        On Error Resume Next
        Set errors = s.UsedRange.SpecialCells(xlCellTypeFormulas, xlErrors)
        On Error GoTo Failed
        Check errors Is Nothing, "No formula errors: " & s.Name
    Next s
    VerifyFaultComparison = "PASS; records=" & finish - 1 & "; factory=" & factory & "; all_factory_lines=" & lines.Count & "; teams=" & teams.Count & "; groups=" & families.Count & "; baseline_independent=ok; pair_comparison=ok; independent_modules=ok; same_line_modules=ok; native_mode_list=ok; borders=ok; related_views=ok"
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
        Check EFASearch.IsSelector(cell) = (active And cell.Address(False, False) <> "B6"), "Only active filter fields have dropdown/search"
        If active Then count = count + 1
        For Each area In Array(metadata.Cells(r, 4).Value2, metadata.Cells(r, 5).Value2)
            Set box = sheet.Range(CStr(area))
            If active Then
                Check box.Font.Color <> RGB(255, 255, 255), "Visible filter text restored"
                For Each edge In Array(xlEdgeLeft, xlEdgeTop, xlEdgeRight, xlEdgeBottom)
                    Check box.Borders(CLng(edge)).LineStyle = xlContinuous, "Complete border: " & CStr(area)
                Next edge
            Else
                Check box.NumberFormat <> ";;;", "Inactive filter content stays visible"
                Check box.Font.Color = RGB(128, 128, 128), "Inactive filter stays visible in gray"
                For Each edge In Array(xlEdgeLeft, xlEdgeTop, xlEdgeRight, xlEdgeBottom)
                    Check box.Borders(CLng(edge)).LineStyle = xlContinuous, "Inactive box keeps photographed border"
                Next edge
            End If
        Next area
    Next r
    Check count = IIf(mode = "부서", 3, 5), "Mode-specific filter count"
End Sub

Private Sub VerifyDepartmentTotals(ByVal sheet As Worksheet, ByVal facts As Worksheet, ByVal baselineOrg As String, ByVal comparisonOrg As String, ByVal last As Long)
    Dim r As Long, f As Long, n As Long, organization As String, total As Double
    Check Not EFASearch.CommitSelection(sheet.Range("D8"), "(전체)"), "Department baseline module disabled"
    Check Not EFASearch.CommitSelection(sheet.Range("G8"), "(전체)"), "Department comparison module disabled"
    Check EFASearch.SourceRange(sheet.Range("D8")).Count = 1, "Department module list only contains all"
    sheet.Range("D8").Value2 = "stale baseline module"
    sheet.Range("G8").Value2 = "stale comparison module"
    Application.CalculateFull
    Check Application.Sum(sheet.Range("E25:E" & last)) = facts.Cells(facts.Rows.Count, 1).End(xlUp).Row - 1, "Stale module values cannot narrow department population"
    Check EFASearch.CommitSelection(sheet.Range("D7"), baselineOrg), "Same department test"
    Check ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2 = 1, "Different stale modules cannot duplicate a department"
    Check EFASearch.CommitSelection(sheet.Range("D7"), comparisonOrg), "Department comparison pair"
    For r = 25 To last
        If Len(CStr(sheet.Cells(r, 13).Value2)) > 0 Then
            organization = CStr(sheet.Cells(r, 1).Value2) & " / " & CStr(sheet.Cells(r, 2).Value2)
            Check CStr(sheet.Cells(r, 12).Value2) = "(전체)", "Department row covers all modules"
            n = 0: total = 0
            For f = 2 To facts.Cells(facts.Rows.Count, 1).End(xlUp).Row
                If CStr(facts.Cells(f, 3).Value2) & " / " & CStr(facts.Cells(f, 4).Value2) = organization Then
                    n = n + 1
                    If IsNumeric(facts.Cells(f, 12).Value2) Then total = total + CDbl(facts.Cells(f, 12).Value2)
                End If
            Next f
            Check sheet.Cells(r, 5).Value2 = n, "Department whole count reconciles"
            Check Abs(CDbl(sheet.Cells(r, 6).Value2) - total) < 0.00001, "Department whole time reconciles"
        End If
    Next r
    sheet.Range("D8").Value2 = "(전체)"
    sheet.Range("G8").Value2 = "(전체)"
    Application.CalculateFull
    VerifyCharts sheet
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
    Check charts = 8, "Every analysis chart checked"
    Check grouped > 0, "Thousands separators appear in rendered label text"
End Sub
