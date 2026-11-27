Option Explicit

Public WithEvents Watched As Excel.Chart

Private Sub Watched_BeforeDoubleClick(ByVal ElementID As Long, ByVal Arg1 As Long, ByVal Arg2 As Long, Cancel As Boolean)
    If ElementID <> xlSeries And ElementID <> xlDataLabel Then Exit Sub
    If Arg2 < 1 Then Exit Sub
    Cancel = EFASearch.FollowChart(Watched, Arg2)
End Sub
