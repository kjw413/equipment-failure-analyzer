Option Explicit

Public WithEvents Watched As Excel.Chart

Private Sub Watched_Select(ByVal ElementID As Long, ByVal Arg1 As Long, ByVal Arg2 As Long)
    On Error GoTo Done
    If Watched.Parent.Parent.Name <> "04.월별 주요이슈" Then Exit Sub
    If ElementID <> xlSeries And ElementID <> xlDataLabel Then Exit Sub
    If Arg2 > 0 Then EFASearch.FollowChart Watched, Arg2
Done:
End Sub

Private Sub Watched_BeforeDoubleClick(ByVal ElementID As Long, ByVal Arg1 As Long, ByVal Arg2 As Long, Cancel As Boolean)
    If ElementID <> xlSeries And ElementID <> xlDataLabel Then Exit Sub
    If Arg2 < 1 Then Exit Sub
    If Watched.Parent.Parent.Name = "04.월별 주요이슈" Then
        Cancel = True
        EFASearch.FollowChart Watched, Arg2
        Exit Sub
    End If
    Cancel = EFASearch.FollowChart(Watched, Arg2)
End Sub

Private Sub Watched_MouseUp(ByVal Button As Long, ByVal Shift As Long, ByVal x As Long, ByVal y As Long)
    On Error GoTo Done
    If Watched.Parent.Parent.Name <> "04.월별 주요이슈" Then Exit Sub
    If Button <> 1 Then Exit Sub
    Dim element As Long, series As Long, point As Long
    Watched.GetChartElement x, y, element, series, point
    If element <> xlSeries And element <> xlDataLabel Then Exit Sub
    If point < 1 Then Exit Sub
    EFASearch.FollowChart Watched, point
Done:
End Sub
