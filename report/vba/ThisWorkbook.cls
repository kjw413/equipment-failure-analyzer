Option Explicit

Private Sub Workbook_SheetSelectionChange(ByVal Sh As Object, ByVal Target As Range)
    EFASearch.OpenPicker Target
End Sub

Private Sub Workbook_SheetBeforeDoubleClick(ByVal Sh As Object, ByVal Target As Range, Cancel As Boolean)
    If EFASearch.IsSelector(Target) Then
        Cancel = True
        EFASearch.OpenPicker Target
    End If
End Sub
