$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetUnhandledExceptionMode('ThrowException')

$form = [System.Windows.Forms.Form]::new()
$form.Text = '설비 고장 분석기'
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.AutoScaleMode = 'Dpi'
$form.ClientSize = [System.Drawing.Size]::new(440, 220)
$form.Font = [System.Drawing.Font]::new('맑은 고딕', 10)

$dropArea = [System.Windows.Forms.Label]::new()
$dropArea.SetBounds(20, 20, 400, 94)
$dropArea.Text = 'Excel 파일을 여기에 끌어놓으세요'
$dropArea.TextAlign = 'MiddleCenter'
$dropArea.BackColor = [System.Drawing.Color]::FromArgb(233, 243, 238)
$dropArea.ForeColor = [System.Drawing.Color]::FromArgb(20, 90, 70)
$dropArea.BorderStyle = 'FixedSingle'

$formats = [System.Windows.Forms.Label]::new()
$formats.SetBounds(20, 120, 400, 23)
$formats.Text = '.xlsx 또는 .xlsm 파일 1개'
$formats.TextAlign = 'MiddleCenter'

$status = [System.Windows.Forms.Label]::new()
$status.SetBounds(20, 146, 400, 23)
$status.TextAlign = 'MiddleCenter'
$status.ForeColor = [System.Drawing.Color]::Firebrick

$browse = [System.Windows.Forms.Button]::new()
$browse.SetBounds(158, 173, 124, 30)
$browse.Text = '파일 선택'
$form.AcceptButton = $browse
$form.Controls.AddRange(@($dropArea, $formats, $status, $browse))

$acceptFile = {
    param([string[]]$Paths)

    if ($Paths.Count -ne 1) {
        $status.Text = 'Excel 파일을 한 개만 끌어놓으세요.'
        return
    }
    $filePath = $Paths[0]
    if ([System.IO.Path]::GetExtension($filePath) -notin '.xlsx', '.xlsm') {
        $status.Text = '.xlsx 또는 .xlsm 파일을 선택하세요.'
        return
    }
    if ([System.IO.Path]::GetFileName($filePath).StartsWith('~$') -or
        -not (Test-Path -LiteralPath $filePath -PathType Leaf -ErrorAction SilentlyContinue)) {
        $status.Text = '열 수 있는 Excel 원본 파일을 선택하세요.'
        return
    }

    $form.Tag = $filePath
    # Let the drag callback finish before closing the dialog.
    [void]$form.BeginInvoke([Action]{ $form.DialogResult = 'OK' })
}

$fileDrop = [System.Windows.Forms.DataFormats]::FileDrop
$copyEffect = [System.Windows.Forms.DragDropEffects]::Copy
foreach ($control in @($form, $dropArea)) {
    $control.AllowDrop = $true
    $control.Add_DragEnter({
        param($sender, $eventArgs)
        if ($eventArgs.Data.GetDataPresent($fileDrop, $false) -and
            ($eventArgs.AllowedEffect -band $copyEffect)) {
            $eventArgs.Effect = $copyEffect
        }
    })
    $control.Add_DragDrop({
        param($sender, $eventArgs)
        if ($eventArgs.Data.GetDataPresent($fileDrop, $false)) {
            & $acceptFile ($eventArgs.Data.GetData($fileDrop, $false))
        }
    })
}

$browse.Add_Click({
    $dialog = [System.Windows.Forms.OpenFileDialog]::new()
    try {
        $dialog.Title = '분석할 Excel 고장이력 선택'
        $dialog.Filter = 'Excel 파일 (*.xlsx;*.xlsm)|*.xlsx;*.xlsm'
        if ($dialog.ShowDialog($form) -eq 'OK') {
            & $acceptFile @($dialog.FileName)
        }
    } finally {
        $dialog.Dispose()
    }
})

try {
    if ($form.ShowDialog() -eq 'OK') {
        [Console]::WriteLine([string]$form.Tag)
    }
} finally {
    $form.Dispose()
}
