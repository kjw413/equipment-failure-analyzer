Option Explicit

Public WithEvents Watched As Excel.Chart

' Every report chart drills on double-click only. A single click merely selects
' the point, so browsing or printing a chart never changes the view by accident.
Private Sub Watched_BeforeDoubleClick(ByVal ElementID As Long, ByVal Arg1 As Long, ByVal Arg2 As Long, Cancel As Boolean)
    If ElementID <> xlSeries And ElementID <> xlDataLabel Then Exit Sub
    If Arg2 < 1 Then Exit Sub
    If Watched.Parent.Parent.Name = "03.월별 주요이슈" Then
        Cancel = True
        EFASearch.FollowChart Watched, Arg2
        Exit Sub
    End If
    Cancel = EFASearch.FollowChart(Watched, Arg2)
End Sub
