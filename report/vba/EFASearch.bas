Option Explicit

Private Opening As Boolean
Private Const AllLabel As String = "(전체)"

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
    ' Revalidate the exact value against this field's own list before writing.
    Dim source As Range, c As Range, events As Boolean
    If Not IsSelector(Target) Then Exit Function
    Set source = ThisWorkbook.Names(Mid$(Target.Validation.Formula1, 2)).RefersToRange
    For Each c In source.Cells
        If StrComp(CStr(c.Value2), value, vbBinaryCompare) = 0 Then
            events = Application.EnableEvents
            On Error GoTo Restore
            Application.EnableEvents = False
            ' Preserve names beginning with '=' as literal categories as well.
            Target.Value2 = "'" & value
            CommitSelection = True
Restore:
            Application.EnableEvents = events
            If CommitSelection Then Application.Calculate
            Exit Function
        End If
    Next c
End Function
