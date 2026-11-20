Option Explicit

Private Opening As Boolean
Private Updating As Boolean
Private ChartHandlers As Collection
Private Const AllLabel As String = "(전체)"
Private Const PeriodSheetName As String = "03.월별 주요이슈"
Private Const MainSheetName As String = "02.팀별 주요이슈"
Private Const CompareSheetName As String = "별첨. 동일 상세설비 비교"
Private Const FaultSheetName As String = "04.고장비교"
Private LastPeriodMode As String
Private LastPeriodMonth As String

Public Sub Initialize()
    On Error GoTo Done
    If ChartHandlers Is Nothing Then
        Set ChartHandlers = New Collection
        Dim item As ChartObject, handler As EFADrillChart, key As Variant, sheet As Worksheet
        For Each key In Array(MainSheetName, PeriodSheetName, CompareSheetName, FaultSheetName)
            Set sheet = Nothing
            On Error Resume Next
            Set sheet = ThisWorkbook.Worksheets(CStr(key))
            On Error GoTo Done
            If Not sheet Is Nothing Then
                For Each item In sheet.ChartObjects
                    Set handler = New EFADrillChart
                    Set handler.Watched = item.Chart
                    ChartHandlers.Add handler
                Next item
            End If
        Next key
    End If
    RememberPeriodState
    RefreshPeriods
    RefreshFaultComparison
Done:
End Sub

Public Function SourceRange(ByVal Target As Range) As Range
    ' Worksheet-local names narrow the native dropdown and the search window alike.
    Dim label As String, scoped As Name, faultRow As Long
    If Target.Parent.Name = FaultSheetName Then
        faultRow = FaultControlRow(Target)
        If faultRow > 0 Then label = "_Fault_List_" & CStr(ThisWorkbook.Worksheets("_fault_controls").Cells(faultRow, 1).Value2)
    End If
    If Len(label) = 0 Then label = Mid$(Target.Validation.Formula1, 2)
    On Error Resume Next
    Set scoped = ThisWorkbook.Names("'" & Replace(Target.Parent.Name, "'", "''") & "'!" & label)
    On Error GoTo 0
    If scoped Is Nothing Then Set scoped = ThisWorkbook.Names(label)
    Set SourceRange = scoped.RefersToRange
End Function

Private Function ControlRow(ByVal Target As Range) As Long
    On Error GoTo Done
    Dim ws As Worksheet, row As Long
    Set ws = ThisWorkbook.Worksheets("_report_controls")
    For row = 2 To ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
        If CStr(ws.Cells(row, 1).Value2) = Target.Parent.Name Then
            If CStr(ws.Cells(row, 3).Value2) = Target.Cells(1, 1).Address(False, False) Then
                ControlRow = row: Exit Function
            End If
        End If
    Next row
Done:
End Function

Public Function ControlCell(ByVal sheet As Worksheet, ByVal field As String) As Range
    Dim metadata As Worksheet, row As Long
    Set metadata = ThisWorkbook.Worksheets("_report_controls")
    For row = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        If metadata.Cells(row, 1).Value2 = sheet.Name And metadata.Cells(row, 2).Value2 = field Then
            Set ControlCell = sheet.Range(metadata.Cells(row, 3).Value2): Exit Function
        End If
    Next row
End Function

Private Sub ResetChildren(ByVal Target As Range, ByVal changed As Long)
    If changed = 0 Then Exit Sub
    Dim metadata As Worksheet, row As Long, child As Range
    Set metadata = ThisWorkbook.Worksheets("_report_controls")
    For row = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        If metadata.Cells(row, 1).Value2 = Target.Parent.Name Then
            If metadata.Cells(row, 4).Value2 > metadata.Cells(changed, 4).Value2 Then
                Set child = Target.Parent.Range(metadata.Cells(row, 3).Value2)
                child.Value2 = "'" & AllLabel
                metadata.Cells(row, 6).Value2 = AllLabel
            End If
        End If
    Next row
End Sub

Public Sub HandleChange(ByVal sheet As Object, ByVal Target As Range)
    If Updating Then Exit Sub
    If HandleFaultChange(sheet, Target) Then Exit Sub
    If HandlePeriodChange(sheet, Target) Then Exit Sub
    On Error GoTo Done
    Dim metadata As Worksheet, row As Long, cell As Range, incoming As String, events As Boolean, changedEvents As Boolean
    Set metadata = ThisWorkbook.Worksheets("_report_controls")
    For row = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        If metadata.Cells(row, 1).Value2 = sheet.Name Then
            Set cell = sheet.Range(metadata.Cells(row, 3).Value2)
            If Not Application.Intersect(Target, cell.MergeArea) Is Nothing Then
                incoming = CStr(cell.Value2)
                If Len(incoming) = 0 Then incoming = AllLabel
                events = Application.EnableEvents
                changedEvents = True
                Application.EnableEvents = False
                cell.Value2 = "'" & CStr(metadata.Cells(row, 6).Value2)
                Application.EnableEvents = events
                changedEvents = False
                CommitSelection cell, incoming
                Exit Sub
            End If
        End If
    Next row
Done:
    If changedEvents Then Application.EnableEvents = events
    If Not Updating Then
        Application.Calculate
        RefreshTables
    End If
End Sub

Public Function IsSelector(ByVal Target As Range) As Boolean
    On Error GoTo Done
    Dim c As Range, source As String
    Set c = Target.Cells(1, 1)
    If Target.Areas.Count <> 1 Then Exit Function
    If Target.CountLarge > 1 Then
        If Target.Address <> c.MergeArea.Address Then Exit Function
    End If
    If c.HasFormula Then Exit Function
    If c.Validation.Type <> xlValidateList Then Exit Function
    source = c.Validation.Formula1
    If Left$(source, 13) = "=_Fault_List_" Then
        IsSelector = True
        Exit Function
    End If
    Select Case source
        Case "=_Issue_factory", "=_Issue_team", "=_Issue_asset", _
             "=_Issue_module", "=_Issue_part", "=_Issue_organization"
            IsSelector = True
    End Select
Done:
End Function

Public Sub OpenPicker(ByVal Target As Range)
    If Opening Then Exit Sub
    If Not IsSelector(Target) Then Exit Sub
    On Error GoTo Failed
    Opening = True
    Initialize
    Application.Calculate
    Dim picker As EFAPicker
    Set picker = New EFAPicker
    picker.Prepare Target.Cells(1, 1)
    picker.Show vbModal
Done:
    On Error Resume Next
    Unload picker
    Opening = False
    Exit Sub
Failed:
    MsgBox "검색창을 열지 못했습니다. 셀의 기본 목록에서 선택할 수 있습니다." & vbCrLf & Err.Description, vbExclamation
    Resume Done
End Sub

Public Function Normalize(ByVal value As String) As String
    Dim i As Long, ch As String, result As String
    value = LCase$(Trim$(value))
    For i = 1 To Len(value)
        ch = Mid$(value, i, 1)
        Select Case ch
            Case " ", vbTab, "-", "_", "#", "/", ".", "(", ")", "[", "]", ChrW(160)
            Case Else: result = result & ch
        End Select
    Next i
    Normalize = result
End Function

Private Function EditDistance(ByVal a As String, ByVal b As String) As Long
    Dim previous() As Long, current() As Long
    Dim i As Long, j As Long, cost As Long, best As Long
    ReDim previous(0 To Len(b))
    ReDim current(0 To Len(b))
    ' Free leading/trailing candidate text: compare a query with its closest substring.
    For j = 0 To Len(b): previous(j) = 0: Next j
    For i = 1 To Len(a)
        current(0) = i
        For j = 1 To Len(b)
            cost = 1
            If Mid$(a, i, 1) = Mid$(b, j, 1) Then cost = 0
            best = previous(j) + 1
            If current(j - 1) + 1 < best Then best = current(j - 1) + 1
            If previous(j - 1) + cost < best Then best = previous(j - 1) + cost
            current(j) = best
        Next j
        For j = 0 To Len(b): previous(j) = current(j): Next j
    Next i
    best = Len(a)
    For j = 0 To Len(b)
        If previous(j) < best Then best = previous(j)
    Next j
    EditDistance = best
End Function

Public Function MatchScore(ByVal query As String, ByVal candidate As String) As Double
    Dim a As String, b As String, distance As Long, threshold As Double
    a = Normalize(query): b = Normalize(candidate)
    If Len(a) = 0 Then
        MatchScore = 1
        If candidate = AllLabel Then MatchScore = 2
    ElseIf a = b Then
        MatchScore = 10000
    ElseIf Left$(b, Len(a)) = a Then
        MatchScore = 8000 + Len(a) / (Len(b) + 1)
    ElseIf InStr(1, b, a, vbBinaryCompare) > 0 Then
        MatchScore = 6000 + Len(a) / (Len(b) + 1)
    ElseIf candidate <> AllLabel Then
        distance = EditDistance(a, b)
        ' A one-character query must match literally; do not suggest unrelated items.
        threshold = 0.4
        If Len(a) = 2 Then threshold = 0.5
        If Len(a) >= 2 Then
            If distance / Len(a) <= threshold Then MatchScore = 1000 * (1 - distance / Len(a))
        End If
    End If
End Function

Public Function RankedCandidates(ByVal query As String, ByVal source As Range) As Variant
    Dim labels() As String, scores() As Double, count As Long
    Dim c As Range, score As Double, i As Long, j As Long
    Dim label As String, tempScore As Double, tempLabel As String
    ReDim labels(1 To source.Cells.Count)
    ReDim scores(1 To source.Cells.Count)
    For Each c In source.Cells
        label = CStr(c.Value2)
        score = MatchScore(query, label)
        If score > 0 Then
            count = count + 1: labels(count) = label: scores(count) = score
        End If
    Next c
    ' Small classification lists: stable insertion sort, label order breaks ties.
    For i = 2 To count
        tempLabel = labels(i): tempScore = scores(i): j = i - 1
        Do While j >= 1
            If scores(j) > tempScore Then Exit Do
            If scores(j) = tempScore Then
                If StrComp(labels(j), tempLabel, vbTextCompare) <= 0 Then Exit Do
            End If
            labels(j + 1) = labels(j): scores(j + 1) = scores(j): j = j - 1
        Loop
        labels(j + 1) = tempLabel: scores(j + 1) = tempScore
    Next i
    If count = 0 Then
        RankedCandidates = Empty
    Else
        ReDim Preserve labels(1 To count)
        RankedCandidates = labels
    End If
End Function

Public Function CommitSelection(ByVal Target As Range, ByVal value As String) As Boolean
    If Target.Parent.Name = FaultSheetName Then
        CommitSelection = CommitFaultSelection(Target, value)
        Exit Function
    End If
    ' Revalidate the exact value against this field's own list before writing.
    Dim source As Range, c As Range, events As Boolean, changed As Long, previous As String
    If Not IsSelector(Target) Then Exit Function
    Application.Calculate
    Set source = SourceRange(Target)
    For Each c In source.Cells
        If StrComp(CStr(c.Value2), value, vbBinaryCompare) = 0 Then
            events = Application.EnableEvents
            On Error GoTo Restore
            Application.EnableEvents = False
            Updating = True
            changed = ControlRow(Target)
            previous = CStr(Target.Value2)
            ' Preserve names beginning with '=' as literal categories as well.
            Target.Value2 = "'" & value
            If StrComp(previous, value, vbBinaryCompare) <> 0 Then
                ResetChildren Target, changed
                If Target.Parent.Name = PeriodSheetName Then
                    PeriodCell("_Period_Mode").Value2 = "'월별"
                    LastPeriodMode = "월별"
                End If
            End If
            If changed > 0 Then ThisWorkbook.Worksheets("_report_controls").Cells(changed, 6).Value2 = "'" & value
            CommitSelection = True
Restore:
            Application.EnableEvents = events
            Updating = False
            If CommitSelection Then
                Application.Calculate
                RefreshTables
            End If
            Exit Function
        End If
    Next c
End Function

Public Sub RefreshTables()
    On Error GoTo Done
    Dim key As Variant, labels As Range, other As Range, row As Long, count As Long, ws As Worksheet
    For Each key In Array("_Drill_CountLabels", "_Compare_TableLabels")
        Set labels = Nothing
        On Error Resume Next
        Set labels = ThisWorkbook.Names(CStr(key)).RefersToRange
        On Error GoTo Done
        If labels Is Nothing Then GoTo NextKey
        Set ws = labels.Parent
        Set other = Nothing
        If CStr(key) = "_Drill_CountLabels" Then Set other = ThisWorkbook.Names("_Drill_TimeLabels").RefersToRange
        count = 0
        For row = 1 To labels.Rows.Count
            If Len(CStr(labels.Cells(row, 1).Value2)) > 0 Then count = row
            If Not other Is Nothing Then
                If Len(CStr(other.Cells(row, 1).Value2)) > 0 Then count = row
            End If
        Next row
        labels.EntireRow.Hidden = True
        If count > 0 Then labels.Cells(1, 1).Resize(count, 1).EntireRow.Hidden = False
        ws.PageSetup.PrintArea = "$A$1:$" & IIf(other Is Nothing, "M", "L") & "$" & CStr(labels.Row + IIf(count > 0, count, 1) - 1)
        If other Is Nothing Then ws.PageSetup.FitToPagesTall = IIf(count > 12, 0, 1)
NextKey:
    Next key
Done:
    RefreshPeriods
End Sub

Private Function PeriodRange(ByVal label As String) As Range
    Set PeriodRange = ThisWorkbook.Names(label).RefersToRange
End Function

Private Function PeriodCell(ByVal label As String) As Range
    Set PeriodCell = PeriodRange(label).Cells(1, 1)
End Function

Private Function MonthSyntax(ByVal value As String) As Boolean
    If Not value Like "####-##" Then Exit Function
    MonthSyntax = Val(Left$(value, 4)) >= 1000 And Val(Right$(value, 2)) >= 1 And Val(Right$(value, 2)) <= 12
End Function

Private Function ValidPeriodMonth(ByVal value As String) As Boolean
    If Not MonthSyntax(value) Then Exit Function
    On Error GoTo Done
    Dim cell As Range
    For Each cell In PeriodRange("_Period_Months").Cells
        If Not IsError(cell.Value2) Then
            If CStr(cell.Value2) = value Then ValidPeriodMonth = True: Exit Function
        End If
    Next cell
Done:
End Function

Private Function FirstPeriodMonth() As String
    On Error GoTo Done
    Dim cell As Range
    For Each cell In PeriodRange("_Period_Months").Cells
        If Not IsError(cell.Value2) Then
            If MonthSyntax(CStr(cell.Value2)) Then FirstPeriodMonth = CStr(cell.Value2): Exit Function
        End If
    Next cell
Done:
End Function

Private Function SafePeriodMonth(ByVal value As String) As String
    If ValidPeriodMonth(value) Then
        SafePeriodMonth = value
    ElseIf ValidPeriodMonth(LastPeriodMonth) Then
        SafePeriodMonth = LastPeriodMonth
    Else
        SafePeriodMonth = FirstPeriodMonth
    End If
End Function

Private Function ValidPeriodMode(ByVal mode As String) As Boolean
    ' 일별 is reached from a single month and returns with 월별로 돌아가기.
    ValidPeriodMode = (mode = "월별" Or mode = "일별")
End Function

Private Sub RememberPeriodState()
    On Error GoTo Done
    Dim value As String
    value = CStr(PeriodCell("_Period_Mode").Value2)
    If ValidPeriodMode(value) Then LastPeriodMode = value
    LastPeriodMonth = SafePeriodMonth(CStr(PeriodCell("_Period_Month").Value2))
    If Not ValidPeriodMode(LastPeriodMode) Then LastPeriodMode = "월별"
Done:
End Sub

Private Function SetPeriodView(ByVal mode As String, ByVal month As String) As Boolean
    Dim events As Boolean, changedEvents As Boolean
    On Error GoTo Restore
    If Not ValidPeriodMode(mode) Then Exit Function
    If mode = "일별" And Not ValidPeriodMonth(month) Then Exit Function
    month = SafePeriodMonth(month)
    events = Application.EnableEvents
    changedEvents = True
    Application.EnableEvents = False
    Updating = True
    PeriodCell("_Period_Month").Value2 = "'" & month
    PeriodCell("_Period_Mode").Value2 = "'" & mode
    LastPeriodMode = mode
    LastPeriodMonth = month
    SetPeriodView = True
Restore:
    If changedEvents Then Application.EnableEvents = events
    Updating = False
    If SetPeriodView Then
        Application.Calculate
        RefreshPeriods
    End If
End Function

Private Function HandlePeriodChange(ByVal sheet As Object, ByVal Target As Range) As Boolean
    On Error GoTo Done
    If sheet.Name <> PeriodSheetName Then Exit Function
    Dim modeCell As Range, monthCell As Range, touchesMode As Boolean, touchesMonth As Boolean
    Dim mode As String, month As String, validMonth As Boolean
    Set modeCell = PeriodCell("_Period_Mode")
    Set monthCell = PeriodCell("_Period_Month")
    touchesMode = Not Application.Intersect(Target, modeCell.MergeArea) Is Nothing
    touchesMonth = Not Application.Intersect(Target, monthCell.MergeArea) Is Nothing
    If Not touchesMode And Not touchesMonth Then Exit Function
    HandlePeriodChange = True
    mode = LastPeriodMode
    If Not ValidPeriodMode(mode) Then mode = "월별"
    If Not IsError(modeCell.Value2) Then
        If ValidPeriodMode(CStr(modeCell.Value2)) Then mode = CStr(modeCell.Value2)
    End If
    month = LastPeriodMonth
    If Not IsError(monthCell.Value2) Then
        validMonth = ValidPeriodMonth(CStr(monthCell.Value2))
        If validMonth Then month = CStr(monthCell.Value2)
    End If
    month = SafePeriodMonth(month)
    If touchesMonth And validMonth Then mode = "일별"
    If mode = "일별" And Not ValidPeriodMonth(month) Then mode = "월별"
    SetPeriodView mode, month
Done:
End Function

Public Function FollowPeriodMonth(ByVal month As String) As Boolean
    FollowPeriodMonth = SetPeriodView("일별", month)
End Function

Public Function BackToMonths() As Boolean
    On Error GoTo Done
    BackToMonths = SetPeriodView("월별", CStr(PeriodCell("_Period_Month").Value2))
Done:
End Function

Public Function FollowPeriodChart(ByVal point As Long) As Boolean
    On Error GoTo Done
    Dim labels As Range, count As Long
    If CStr(PeriodCell("_Period_Mode").Value2) <> "월별" Then Exit Function
    Set labels = PeriodRange("_Period_Rows")
    count = CLng(PeriodCell("_Period_ActiveCount").Value2)
    If point < 1 Or point > labels.Rows.Count Or point > count Then Exit Function
    FollowPeriodChart = FollowPeriodMonth(CStr(labels.Cells(point, 1).Value2))
Done:
End Function

Public Function FollowPeriodTarget(ByVal Target As Range) As Boolean
    On Error GoTo Done
    If Target.Parent.Name <> PeriodSheetName Then Exit Function
    If Not Application.Intersect(Target, PeriodRange("_Period_Back")) Is Nothing Then
        FollowPeriodTarget = BackToMonths(): Exit Function
    End If
    If Target.CountLarge <> 1 Then Exit Function
    If CStr(PeriodCell("_Period_Mode").Value2) <> "월별" Then Exit Function
    If Not Application.Intersect(Target, PeriodRange("_Period_Rows")) Is Nothing Then
        FollowPeriodTarget = FollowPeriodMonth(CStr(Target.Value2))
    End If
Done:
End Function

Public Sub RefreshPeriods()
    On Error GoTo Done
    Dim labels As Range, count As Long, value As Variant, chart As ChartObject
    Set labels = PeriodRange("_Period_Rows")
    value = PeriodCell("_Period_ActiveCount").Value2
    If IsError(value) Then Exit Sub
    If Not IsNumeric(value) Then Exit Sub
    count = CLng(value)
    If count < 0 Then count = 0
    If count > labels.Rows.Count Then count = labels.Rows.Count
    labels.EntireRow.Hidden = True
    If count > 0 Then labels.Cells(1, 1).Resize(count, 1).EntireRow.Hidden = False
    labels.Parent.PageSetup.PrintArea = "$A$1:$L$" & CStr(labels.Row + IIf(count > 0, count, 1) - 1)
    If CStr(PeriodCell("_Period_Mode").Value2) = "일별" Then
        labels.Parent.PageSetup.FitToPagesTall = False
    Else
        labels.Parent.PageSetup.FitToPagesTall = 1
    End If
    For Each chart In labels.Parent.ChartObjects
        chart.Chart.Refresh
    Next chart
Done:
End Sub

Public Function FollowRank(ByVal Target As Range) As Boolean
    If Target.Parent.Name <> "02.팀별 주요이슈" Then Exit Function
    Dim labels As Range, key As Variant
    For Each key In Array("_Drill_CountLabels", "_Drill_TimeLabels")
        Set labels = ThisWorkbook.Names(CStr(key)).RefersToRange
        If Not Application.Intersect(Target, labels) Is Nothing Then
            FollowRank = DrillValue(CStr(Target.Cells(1, 1).Value2)): Exit Function
        End If
    Next key
End Function

Public Function FollowChart(ByVal chart As Excel.Chart, ByVal point As Long) As Boolean
    Dim labels As Range
    If chart.Parent.Parent.Name = PeriodSheetName Then
        FollowChart = FollowPeriodChart(point): Exit Function
    End If
    If chart.Parent.Parent.Name = CompareSheetName Then
        FollowChart = FollowCompareChart(chart, point): Exit Function
    End If
    If chart.Parent.Parent.Name <> MainSheetName Then Exit Function
    If chart.Parent.TopLeftCell.Column < 7 Then
        Set labels = ThisWorkbook.Names("_Drill_CountLabels").RefersToRange
    Else
        Set labels = ThisWorkbook.Names("_Drill_TimeLabels").RefersToRange
    End If
    If point < 1 Or point > labels.Cells.Count Then Exit Function
    FollowChart = DrillValue(CStr(labels.Cells(point, 1).Value2))
End Function

Private Function FollowCompareChart(ByVal chart As Excel.Chart, ByVal point As Long) As Boolean
    On Error GoTo Done
    Dim ranked As Range, key As String
    ' The count chart is the left one; ranked rows carry factory, team and line.
    key = "_Compare_TimeRows"
    If chart.Parent.TopLeftCell.Column < 7 Then key = "_Compare_CountRows"
    Set ranked = ThisWorkbook.Names(key).RefersToRange
    If point < 1 Or point > ranked.Rows.Count Then Exit Function
    FollowCompareChart = FollowCompareRow(ranked.Rows(point))
Done:
End Function

Public Function FollowCompareTarget(ByVal Target As Range) As Boolean
    On Error GoTo Done
    If Target.Parent.Name <> CompareSheetName Then Exit Function
    If Target.Areas.Count <> 1 Then Exit Function
    If Target.Rows.Count <> 1 Then Exit Function
    Dim table As Range
    Set table = ThisWorkbook.Names("_Compare_TableRows").RefersToRange
    If Application.Intersect(Target.Cells(1, 1).EntireRow, table) Is Nothing Then Exit Function
    FollowCompareTarget = FollowCompareRow(table.Rows(Target.Row - table.Row + 1))
Done:
End Function

Private Function FollowCompareRow(ByVal source As Range) As Boolean
    Dim asset As String
    asset = CStr(source.Cells(1, 3).Value2)
    If Len(asset) = 0 Then Exit Function
    FollowCompareRow = FollowLine(CStr(source.Cells(1, 1).Value2), CStr(source.Cells(1, 2).Value2), asset)
End Function

Private Function SelectedValue(ByVal sheet As Worksheet, ByVal field As String) As String
    SelectedValue = CStr(ControlCell(sheet, field).Value2)
    If Len(SelectedValue) = 0 Then SelectedValue = AllLabel
End Function

Private Function FollowLine(ByVal factory As String, ByVal team As String, ByVal asset As String) As Boolean
    ' Hand the compared line to 02: its part ranking, or the history once a part is chosen.
    On Error GoTo Done
    Dim compareSheet As Worksheet, main As Worksheet, moduleName As String, part As String
    Set compareSheet = ThisWorkbook.Worksheets(CompareSheetName)
    Set main = ThisWorkbook.Worksheets(MainSheetName)
    moduleName = SelectedValue(compareSheet, "module")
    part = SelectedValue(compareSheet, "part")
    If Not CommitSelection(ControlCell(main, "factory"), factory) Then Exit Function
    If Not CommitSelection(ControlCell(main, "team"), team) Then Exit Function
    If Not CommitSelection(ControlCell(main, "asset"), asset) Then Exit Function
    If Not CommitSelection(ControlCell(main, "module"), moduleName) Then Exit Function
    If Not CommitSelection(ControlCell(main, "part"), part) Then Exit Function
    FollowLine = True
    If part <> AllLabel Then
        ShowHistory
    Else
        main.Activate
        Application.Goto main.Range("A1"), True
    End If
Done:
End Function

Private Function DrillValue(ByVal label As String) As Boolean
    If Len(label) = 0 Then Exit Function
    Application.Calculate
    Dim field As String, main As Worksheet
    Set main = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    field = CStr(ThisWorkbook.Worksheets("_drill_state").Range("B2").Value2)
    DrillValue = CommitSelection(ControlCell(main, field), label)
    If DrillValue And field = "part" Then ShowHistory
End Function

Private Sub ShowHistory()
    Dim main As Worksheet, history As Worksheet, trends As Worksheet
    Dim data As Variant, included As Variant, ids() As String, i As Long, count As Long
    Dim header As Range, idField As Long, textColumn As Long, key As Variant
    Set main = ThisWorkbook.Worksheets("02.팀별 주요이슈")
    Set trends = ThisWorkbook.Worksheets(PeriodSheetName)
    For Each key In Array("factory", "team", "asset", "module", "part")
        CommitSelection ControlCell(trends, CStr(key)), CStr(ControlCell(main, CStr(key)).Value2)
    Next key
    BackToMonths
    Set history = ThisWorkbook.Worksheets("별첨. 고장이력")
    data = ThisWorkbook.Worksheets("_issue_facts").Range("A2:A" & ThisWorkbook.Worksheets("_issue_facts").Cells(Rows.Count, 1).End(xlUp).Row).Value2
    included = ThisWorkbook.Worksheets("_issue_filter_1").Range("A2:A" & ThisWorkbook.Worksheets("_issue_facts").Cells(Rows.Count, 1).End(xlUp).Row).Value2
    ' A single-record array is returned as a scalar by Excel.
    If Not IsArray(data) Then
        ReDim ids(0 To 0): ids(0) = CStr(data)
        If included = 1 Then count = 1
    Else
        ReDim ids(0 To UBound(data, 1) - 1)
        For i = 1 To UBound(data, 1)
            If included(i, 1) = 1 Then ids(count) = CStr(data(i, 1)): count = count + 1
        Next i
    End If
    For Each header In history.AutoFilter.Range.Rows(1).Cells
        If header.Value2 = "원본 기록 ID" Then idField = header.Column - history.AutoFilter.Range.Column + 1
        If header.Value2 = "고장내용(표준화 후)" Then textColumn = header.Column
    Next header
    If history.FilterMode Then history.ShowAllData
    If count > 0 Then
        ReDim Preserve ids(0 To count - 1)
        history.AutoFilter.Range.AutoFilter Field:=idField, Criteria1:=ids, Operator:=xlFilterValues
    Else
        history.AutoFilter.Range.AutoFilter Field:=idField, Criteria1:="=__EFA_no_record__"
    End If
    history.Activate
    If textColumn > 0 Then Application.Goto history.Cells(6, textColumn), True
End Sub

Private Function FaultControlRow(ByVal Target As Range) As Long
    On Error GoTo Done
    If Target.Parent.Name <> FaultSheetName Then Exit Function
    Dim metadata As Worksheet, r As Long
    Set metadata = ThisWorkbook.Worksheets("_fault_controls")
    For r = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        If metadata.Cells(r, 2).Value2 = Target.Cells(1, 1).Address(False, False) Then FaultControlRow = r: Exit Function
    Next r
Done:
End Function

Private Sub ResetFaultControl(ByVal key As String, Optional ByVal value As String = "(전체)")
    Dim metadata As Worksheet, r As Long, sheet As Worksheet
    Set metadata = ThisWorkbook.Worksheets("_fault_controls")
    Set sheet = ThisWorkbook.Worksheets(FaultSheetName)
    For r = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        If metadata.Cells(r, 1).Value2 = key Then
            sheet.Range(metadata.Cells(r, 2).Value2).Value2 = "'" & value
            metadata.Cells(r, 3).Value2 = value
            Exit Sub
        End If
    Next r
End Sub

Private Function CommitFaultSelection(ByVal Target As Range, ByVal value As String) As Boolean
    Dim r As Long, candidate As Range, accepted As Boolean, events As Boolean, guarded As Boolean
    Dim metadata As Worksheet, key As String, previous As String, sheet As Worksheet
    On Error GoTo Restore
    r = FaultControlRow(Target)
    If r = 0 Then Exit Function
    If Not FaultFieldActive(r) Then Exit Function
    Application.Calculate
    For Each candidate In SourceRange(Target).Cells
        If Not IsError(candidate.Value2) Then
            If StrComp(CStr(candidate.Value2), value, vbBinaryCompare) = 0 Then accepted = True: Exit For
        End If
    Next candidate
    If Not accepted Then Exit Function
    Set metadata = ThisWorkbook.Worksheets("_fault_controls")
    Set sheet = Target.Parent
    key = CStr(metadata.Cells(r, 1).Value2)
    previous = CStr(metadata.Cells(r, 3).Value2)
    events = Application.EnableEvents
    guarded = True
    Application.EnableEvents = False
    Updating = True
    Target.Value2 = "'" & value
    metadata.Cells(r, 3).Value2 = value
    If previous <> value Then
        If sheet.FilterMode Then sheet.AutoFilter.ShowAllData
        Select Case key
            Case "organization"
                ResetFaultControl "asset"
                ResetFaultControl "baseline_module"
            Case "compare_organization"
                ResetFaultControl "compare_asset"
                ResetFaultControl "compare_module"
            Case "asset"
                ResetFaultControl "baseline_module"
            Case "compare_asset"
                ResetFaultControl "compare_module"
        End Select
    End If
    Application.Calculate
    Select Case CStr(ThisWorkbook.Worksheets("_fault_state").Range("B3").Value2)
        Case "부서"
            ResetFaultControl "compare_asset"
            ResetFaultControl "compare_module"
        Case "라인"
            ResetFaultControl "compare_module"
    End Select
    Application.Calculate
    CommitFaultSelection = True
Restore:
    If guarded Then Application.EnableEvents = events
    Updating = False
    If CommitFaultSelection Then
        Application.Calculate
        RefreshFaultComparison
    End If
End Function

Private Function HandleFaultChange(ByVal sheet As Object, ByVal Target As Range) As Boolean
    If sheet.Name <> FaultSheetName Then Exit Function
    Dim metadata As Worksheet, r As Long, cell As Range, incoming As String, events As Boolean, guarded As Boolean
    On Error GoTo Restore
    Set metadata = ThisWorkbook.Worksheets("_fault_controls")
    For r = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        Set cell = sheet.Range(metadata.Cells(r, 2).Value2)
        If Not Application.Intersect(Target, cell.MergeArea) Is Nothing Then
            HandleFaultChange = True
            If Not IsError(cell.Value2) Then incoming = CStr(cell.Value2)
            events = Application.EnableEvents
            guarded = True
            Application.EnableEvents = False
            cell.Value2 = "'" & CStr(metadata.Cells(r, 3).Value2)
            Application.EnableEvents = events
            guarded = False
            CommitFaultSelection cell, incoming
        End If
    Next r
Restore:
    If guarded Then Application.EnableEvents = events
End Function

Public Sub RefreshFaultComparison()
    On Error GoTo Done
    Dim labels As Range, count As Long, sheet As Worksheet, item As ChartObject, metric As Long, available As Long
    Set labels = ThisWorkbook.Names("_Fault_Labels").RefersToRange
    Set sheet = labels.Parent
    RenderFaultFilters
    count = CLng(ThisWorkbook.Worksheets("_fault_state").Range("B4").Value2)
    labels.EntireRow.RowHeight = 21
    labels.EntireRow.Hidden = True
    If count > 0 Then labels.Cells(1, 1).Resize(count, 1).EntireRow.Hidden = False

Done:
    On Error Resume Next
    If Not sheet Is Nothing Then
          sheet.PageSetup.PrintArea = "A1:L" & CStr(labels.Row + IIf(count > 0, count, 1) - 1)
        sheet.PageSetup.Zoom = False
        sheet.PageSetup.FitToPagesWide = 1
          If CStr(ThisWorkbook.Worksheets("_fault_state").Range("B3").Value2) = "부서" Or count <= 5 Then
            sheet.PageSetup.FitToPagesTall = 1
        Else
            sheet.PageSetup.FitToPagesTall = False
        End If
        Application.Calculate
        For metric = 1 To sheet.ChartObjects.Count
            Set item = sheet.ChartObjects(metric)
            available = Application.Count(ThisWorkbook.Worksheets("_fault_chart_rank").Columns(IIf(metric = 1, "E", "F")))
            With item.Chart.SeriesCollection(1)
                .HasDataLabels = True
                .DataLabels.ShowValue = (available > 0)
                .DataLabels.NumberFormat = "#,##0"
                .DataLabels.NumberFormatLinked = False
            End With
            item.Chart.Refresh
        Next metric
    End If
End Sub

Private Function FaultFieldActive(ByVal row As Long) As Boolean
    Dim metadata As Worksheet, level As String, key As String
    Set metadata = ThisWorkbook.Worksheets("_fault_controls")
    level = CStr(ThisWorkbook.Worksheets("_fault_state").Range("B3").Value2)
    key = CStr(metadata.Cells(row, 1).Value2)
    Select Case key
        Case "baseline_module"
            FaultFieldActive = CStr(FaultControlValue("asset")) <> AllLabel
        Case "compare_asset"
            FaultFieldActive = level <> "부서"
        Case "compare_module"
            FaultFieldActive = level = "상세설비" And CStr(FaultControlValue("compare_asset")) <> AllLabel
        Case Else
            FaultFieldActive = True
    End Select
End Function

Private Function FaultControlValue(ByVal key As String) As Variant
    Dim metadata As Worksheet, r As Long
    Set metadata = ThisWorkbook.Worksheets("_fault_controls")
    For r = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        If metadata.Cells(r, 1).Value2 = key Then
            FaultControlValue = ThisWorkbook.Worksheets(FaultSheetName).Range(metadata.Cells(r, 2).Value2).Value2
            Exit Function
        End If
    Next r
End Function

Private Sub DrawFaultFilterBox(ByVal sheet As Worksheet, ByVal reference As Worksheet, ByVal address As String)
    Dim area As Range, source As Range, edge As Variant
    Set area = sheet.Range(address)
    Set source = reference.Range(address)
    area.NumberFormat = source.NumberFormat
    area.Font.Color = source.Font.Color
    area.Interior.Color = source.Interior.Color
    area.Interior.Pattern = source.Interior.Pattern
    For Each edge In Array(xlEdgeLeft, xlEdgeTop, xlEdgeRight, xlEdgeBottom)
        With area.Borders(CLng(edge))
            .LineStyle = xlContinuous
            .Weight = xlThin
            .Color = RGB(0, 0, 0)
        End With
    Next edge
End Sub

Private Sub RenderFaultFilters()
    Dim sheet As Worksheet, reference As Worksheet, metadata As Worksheet, row As Long
    Dim caption As String, edit As String, key As String, cell As Range, updatingScreen As Boolean
    On Error GoTo Done
    updatingScreen = Application.ScreenUpdating
    Application.ScreenUpdating = False
    Set sheet = ThisWorkbook.Worksheets(FaultSheetName)
    Set reference = ThisWorkbook.Worksheets("_fault_filter_styles")
    Set metadata = ThisWorkbook.Worksheets("_fault_controls")
    For row = 2 To metadata.Cells(metadata.Rows.Count, 1).End(xlUp).Row
        key = CStr(metadata.Cells(row, 1).Value2)
        caption = CStr(metadata.Cells(row, 4).Value2)
        edit = CStr(metadata.Cells(row, 5).Value2)
        Set cell = sheet.Range(metadata.Cells(row, 2).Value2)
        On Error Resume Next
        cell.Validation.Delete
        On Error GoTo Done
        DrawFaultFilterBox sheet, reference, caption
        DrawFaultFilterBox sheet, reference, edit
        If FaultFieldActive(row) Then
            cell.Validation.Add Type:=xlValidateList, AlertStyle:=xlValidAlertStop, Formula1:="=_Fault_List_" & key
            cell.Validation.InCellDropdown = True
            cell.Validation.ShowError = True
            cell.Validation.ErrorMessage = "목록에서 선택하세요."
        Else
            With sheet.Range(caption & "," & edit)
                .Font.Color = RGB(128, 128, 128)
                .Interior.Pattern = xlSolid
                .Interior.Color = RGB(242, 242, 242)
            End With
        End If
    Next row
Done:
    Application.ScreenUpdating = updatingScreen
End Sub
