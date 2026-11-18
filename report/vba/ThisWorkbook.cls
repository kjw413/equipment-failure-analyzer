Option Explicit

Private Sub Workbook_Open()
    EFASearch.Initialize
End Sub

Private Sub Workbook_SheetChange(ByVal Sh As Object, ByVal Target As Range)
    EFASearch.HandleChange Sh, Target
End Sub

Private Sub Workbook_SheetSelectionChange(ByVal Sh As Object, ByVal Target As Range)
    EFASearch.OpenPicker Target
End Sub

Private Sub Workbook_SheetBeforeDoubleClick(ByVal Sh As Object, ByVal Target As Range, Cancel As Boolean)
    If EFASearch.FollowPeriodTarget(Target) Then
        Cancel = True
    ElseIf EFASearch.IsSelector(Target) Then
        Cancel = True
        EFASearch.OpenPicker Target
    ElseIf EFASearch.FollowRank(Target) Then
        Cancel = True
    ElseIf EFASearch.FollowCompareTarget(Target) Then
        Cancel = True
    End If
End Sub
