Option Explicit

Private Destination As Range
Private Options As Range
Private Ready As Boolean

Public Sub Prepare(ByVal Target As Range)
    Dim control As MSForms.Control
    For Each control In Me.Controls
        control.Font.Name = "맑은 고딕"
        control.Font.Size = 10
    Next control
    Set Destination = Target
    Set Options = ThisWorkbook.Names(Mid$(Target.Validation.Formula1, 2)).RefersToRange
    Me.Caption = "필터 검색 · " & Target.Worksheet.Name
    CurrentValue.Caption = "현재 선택: " & CStr(Target.Value2)
    Query.Text = ""
    If CStr(Target.Value2) <> "(전체)" Then Query.Text = CStr(Target.Value2)
    Ready = True
    RefreshCandidates
    Query.SelStart = 0
    Query.SelLength = Len(Query.Text)
    ' Position the search input and suggestion list beneath the selected filter.
    Me.StartUpPosition = 0
    Me.Left = Application.Left + 40 + Target.Left * ActiveWindow.Zoom / 100
    Me.Top = Application.Top + 170 + Target.Top * ActiveWindow.Zoom / 100
    If Me.Left + Me.Width > Application.Left + Application.Width - 10 Then _
        Me.Left = Application.Left + Application.Width - Me.Width - 10
    If Me.Top + Me.Height > Application.Top + Application.Height - 20 Then _
        Me.Top = Application.Top + Application.Height - Me.Height - 20
    If Me.Left < Application.Left Then Me.Left = Application.Left
    If Me.Top < Application.Top Then Me.Top = Application.Top
End Sub

Private Sub UserForm_Activate()
    Query.SetFocus
End Sub

Private Sub Query_Change()
    If Ready Then RefreshCandidates
End Sub

Public Sub RefreshCandidates()
    Dim ranked As Variant, i As Long
    ranked = EFASearch.RankedCandidates(Query.Text, Options)
    Candidates.Clear
    If Not IsEmpty(ranked) Then
        For i = LBound(ranked) To UBound(ranked)
            Candidates.AddItem ranked(i)
        Next i
        Candidates.ListIndex = 0
    End If
    Status.Caption = CStr(Candidates.ListCount) & "개 후보 · 클릭 또는 ↑↓ 후 Enter · Esc 취소"
End Sub

Private Sub Query_KeyDown(ByVal KeyCode As MSForms.ReturnInteger, ByVal Shift As Integer)
    KeyCode = HandleKey(CInt(KeyCode))
End Sub

Private Sub Candidates_KeyDown(ByVal KeyCode As MSForms.ReturnInteger, ByVal Shift As Integer)
    Select Case KeyCode
        Case vbKeyReturn: ApplyChoice: KeyCode = 0
        Case vbKeyEscape: Me.Hide: KeyCode = 0
    End Select
End Sub

Private Function HandleKey(ByVal code As Integer) As Integer
    HandleKey = code
    Select Case code
        Case vbKeyDown
            If Candidates.ListIndex < Candidates.ListCount - 1 Then _
                Candidates.ListIndex = Candidates.ListIndex + 1
            HandleKey = 0
        Case vbKeyUp
            If Candidates.ListIndex > 0 Then Candidates.ListIndex = Candidates.ListIndex - 1
            HandleKey = 0
        Case vbKeyReturn: ApplyChoice: HandleKey = 0
        Case vbKeyEscape: Me.Hide: HandleKey = 0
    End Select
End Function

Private Sub Candidates_MouseUp(ByVal Button As Integer, ByVal Shift As Integer, ByVal X As Single, ByVal Y As Single)
    If Button = 1 Then ApplyChoice
End Sub

Private Sub ApplyButton_Click()
    ApplyChoice
End Sub

Private Sub CancelButton_Click()
    Me.Hide
End Sub

Private Sub AllButton_Click()
    If EFASearch.CommitSelection(Destination, "(전체)") Then Me.Hide
End Sub

Public Sub ApplyChoice()
    If Candidates.ListIndex < 0 Then Exit Sub
    If EFASearch.CommitSelection(Destination, Candidates.List(Candidates.ListIndex)) Then Me.Hide
End Sub
