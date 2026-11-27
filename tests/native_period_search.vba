' Appended to the NativeSearchQA module by the native Excel verifier.
Private Sub PeriodCheck(ByVal valid As Boolean, ByVal message As String)
    If Not valid Then Err.Raise vbObjectError + 1901, "Period QA", message
End Sub

Public Function VerifyPeriod() As String
    Dim previousEvents As Boolean
    previousEvents = Application.EnableEvents
    On Error GoTo Failed
    Application.EnableEvents = False
    Dim sheet As Worksheet, labels As Range, months As Range, modeCell As Range, monthCell As Range
    Dim key As Variant, saved(0 To 3) As String, index As Long, point As Long, count As Long
    Dim nMonths As Long, nDays As Long, firstMonth As String, nextMonth As String, scopedMonth As String
    Dim monthCount As Double, monthTime As Variant, scopedCount As Double, chartLabels As Variant
    Set sheet = ThisWorkbook.Worksheets("03.월별 주요이슈")
    Set labels = ThisWorkbook.Names("_Period_Rows").RefersToRange
    Set months = ThisWorkbook.Names("_Period_Months").RefersToRange
    Set modeCell = ThisWorkbook.Names("_Period_Mode").RefersToRange.Cells(1, 1)
    Set monthCell = ThisWorkbook.Names("_Period_Month").RefersToRange.Cells(1, 1)
    EFASearch.Initialize
    For Each key In Array("factory", "team", "asset", "module")
        PeriodCheck EFASearch.CommitSelection(EFASearch.ControlCell(sheet, CStr(key)), "(전체)"), "Initial period filter reset"
    Next key
    Application.EnableEvents = True
    modeCell.Value2 = "월별"
    nMonths = CLng(ThisWorkbook.Names("_Period_ActiveCount").RefersToRange.Value2)
    PeriodCheck nMonths > 0, "Monthly calendar exists"
    PeriodCheck Not EFASearch.ProbeChartDoubleClick(sheet.Name, 1, 1), "The month chart has no double-click navigation"
    PeriodCheck Not ThisWorkbook.ProbeSheetDoubleClick(labels.Cells(1, 1)), "The month table has no double-click navigation"
    PeriodCheck modeCell.Value2 = "월별", "Month data clicks keep the view"
    If Len(PreviewDirectory) > 0 Then sheet.ExportAsFixedFormat 0, PreviewDirectory & "\monthly_native.pdf"
    PeriodCheck sheet.ChartObjects(1).Chart.SeriesCollection(1).Points.Count = nMonths, "Monthly chart point count"
    firstMonth = CStr(labels.Cells(1, 1).Value2)
    monthCount = sheet.Cells(labels.Row, 2).Value2
    monthTime = sheet.Cells(labels.Row, 3).Value2
    monthCell.Value2 = "'" & firstMonth
    modeCell.Value2 = "일별"
    nDays = Day(DateSerial(CLng(Left$(firstMonth, 4)), CLng(Right$(firstMonth, 2)) + 1, 0))
    PeriodCheck modeCell.Value2 = "일별" And monthCell.Value2 = firstMonth, "Selected month committed"
    PeriodCheck ThisWorkbook.Names("_Period_ActiveCount").RefersToRange.Value2 = nDays, "All calendar days represented"
    PeriodCheck sheet.ChartObjects(1).Chart.SeriesCollection(1).Points.Count = nDays, "Daily chart has all days"
    PeriodCheck sheet.ChartObjects(2).Chart.SeriesCollection(1).Points.Count = nDays, "Both daily charts refresh"
    PeriodCheck labels.Cells(1, 1).Value2 = firstMonth & "-01", "First daily label"
    chartLabels = sheet.ChartObjects(1).Chart.SeriesCollection(1).XValues
    PeriodCheck CStr(chartLabels(LBound(chartLabels))) = "01", "Daily chart labels follow the view"
    PeriodCheck labels.Cells(nDays, 1).Value2 = firstMonth & "-" & Format$(nDays, "00"), "Last daily label"
    If Len(PreviewDirectory) > 0 Then sheet.ExportAsFixedFormat 0, PreviewDirectory & "\daily_native.pdf"
    PeriodCheck Application.Sum(sheet.Range(sheet.Cells(labels.Row, 2), sheet.Cells(labels.Row + nDays - 1, 2))) = monthCount, "Daily counts reconcile to selected month"
    If IsNumeric(monthTime) Then
        PeriodCheck Application.Sum(sheet.Range(sheet.Cells(labels.Row, 3), sheet.Cells(labels.Row + nDays - 1, 3))) = CDbl(monthTime), "Daily minutes reconcile to selected month"
    End If
    PeriodCheck Not EFASearch.ProbeChartDoubleClick(sheet.Name, 1, 1), "The daily chart has no navigation"
    modeCell.Value2 = "월별"
    PeriodCheck modeCell.Value2 = "월별" And ThisWorkbook.Names("_Period_ActiveCount").RefersToRange.Value2 = nMonths, "Monthly calendar restored"
    chartLabels = sheet.ChartObjects(1).Chart.SeriesCollection(1).XValues
    PeriodCheck CStr(chartLabels(LBound(chartLabels))) = "'" & Right$(firstMonth, 5), "Monthly chart labels restored"

    ' Native change events handle mode/month dropdowns, invalid edits and short months.
    Application.EnableEvents = True
    nextMonth = firstMonth
    If months.Cells.Count > 1 Then nextMonth = CStr(months.Cells(2, 1).Value2)
    monthCell.Value2 = "'" & nextMonth
    count = Day(DateSerial(CLng(Left$(nextMonth, 4)), CLng(Right$(nextMonth, 2)) + 1, 0))
    PeriodCheck modeCell.Value2 = "일별" And monthCell.Value2 = nextMonth, "Selecting month activates daily mode"
    PeriodCheck ThisWorkbook.Names("_Period_ActiveCount").RefersToRange.Value2 = count, "Selected month has its real number of days"
    PeriodCheck sheet.ChartObjects(1).Chart.SeriesCollection(1).Points.Count = count, "Short-month chart updates point count"
    If count < labels.Rows.Count Then PeriodCheck labels.Cells(count + 1, 1).EntireRow.Hidden, "Unused day rows hidden"
    modeCell.Value2 = "월별"
    PeriodCheck modeCell.Value2 = "월별", "Mode dropdown returns monthly"
    monthCell.Value2 = "2026-99"
    PeriodCheck monthCell.Value2 = nextMonth And modeCell.Value2 = "월별", "Invalid month reverts to prior valid selection"
    modeCell.Value2 = "잘못된 단위"
    PeriodCheck modeCell.Value2 = "월별", "Invalid mode reverts"
    Application.EnableEvents = False

    ' Select one actual hierarchy, then query a month with a record.
    index = 0
    For Each key In Array("factory", "team", "asset", "module")
        Dim control As Range, source As Range
        Set control = EFASearch.ControlCell(sheet, CStr(key))
        Set source = EFASearch.SourceRange(control)
        If source.Cells.Count > 1 Then
            PeriodCheck EFASearch.CommitSelection(control, CStr(source.Cells(2, 1).Value2)), "Scoped period categorical selection"
        End If
        saved(index) = CStr(control.Value2)
        index = index + 1
    Next key
    PeriodCheck modeCell.Value2 = "월별", "Monthly mode is retained while filtering"
    point = 0
    For index = 1 To nMonths
        If sheet.Cells(labels.Row + index - 1, 2).Value2 > 0 Then
            point = index: Exit For
        End If
    Next index
    PeriodCheck point > 0, "Scoped history has an observed month"
    scopedMonth = CStr(labels.Cells(point, 1).Value2)
    scopedCount = sheet.Cells(labels.Row + point - 1, 2).Value2
    Application.EnableEvents = True
    monthCell.Value2 = "'" & scopedMonth
    PeriodCheck modeCell.Value2 = "일별" And monthCell.Value2 = scopedMonth, "Scoped selected month shown"
    index = 0
    For Each key In Array("factory", "team", "asset", "module")
        PeriodCheck CStr(EFASearch.ControlCell(sheet, CStr(key)).Value2) = saved(index), "All categorical filters preserved when changing the month"
        index = index + 1
    Next key
    count = CLng(ThisWorkbook.Names("_Period_ActiveCount").RefersToRange.Value2)
    PeriodCheck Application.Sum(sheet.Range(sheet.Cells(labels.Row, 2), sheet.Cells(labels.Row + count - 1, 2))) = scopedCount, "Scoped day totals reconcile"
    PeriodCheck EFASearch.CommitSelection(EFASearch.ControlCell(sheet, "factory"), "(전체)"), "Parent filter changed from daily"
    PeriodCheck modeCell.Value2 = "일별" And monthCell.Value2 = scopedMonth, "Parent reset keeps the period filters"
    For Each key In Array("team", "asset", "module")
        PeriodCheck EFASearch.CommitSelection(EFASearch.ControlCell(sheet, CStr(key)), "(전체)"), "Final period filter reset"
    Next key
    monthCell.Value2 = "'" & firstMonth
    modeCell.Value2 = "월별"

    Application.EnableEvents = previousEvents
    VerifyPeriod = "PASS; month=" & firstMonth & "; monthly_count=" & CStr(monthCount) & "; daily_days=" & CStr(nDays) & "; scoped_count=" & CStr(scopedCount) & "; no_click_navigation; categorical_and_period_filters_preserved; invalid_input_reverted"
    Exit Function
Failed:
    Application.EnableEvents = previousEvents
    VerifyPeriod = "FAIL; " & Err.Description
End Function
