param([switch]$AllowTemporaryVbaAccess)
$ErrorActionPreference = 'Stop'
if (-not $AllowTemporaryVbaAccess) {
    throw 'Explicit authorization is required: -AllowTemporaryVbaAccess'
}
$root = Split-Path -Parent $PSScriptRoot
$securityPath = 'HKCU:\Software\Microsoft\Office\16.0\Excel\Security'
$securityExisted = Test-Path -LiteralPath $securityPath
$old = Get-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -ErrorAction SilentlyContinue
$hadValue = $null -ne $old
$excel = $null
$book = $null
$ownedProcess = $null
$work = Join-Path $root 'output/search_project_build'
[void][IO.Directory]::CreateDirectory($work)
$macroBook = Join-Path $work 'search_project.xlsm'
try {
    if (-not $securityExisted) { [void](New-Item -Path $securityPath -Force) }
    [void](New-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -PropertyType DWord -Value 1 -Force)
    # /x creates a separate instance so an already-open user's Excel keeps its settings.
    $ownedProcess = Start-Process 'C:/Program Files/Microsoft Office/Root/Office16/EXCEL.EXE' -ArgumentList '/x', '/automation' -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $book = $excel.Workbooks.Add()
    $project = $book.VBProject
    if ($null -eq $project) { throw 'Excel VBA project access is unavailable.' }
    $module = $project.VBComponents.Add(1)
    $module.Name = 'EFASearch'
    $module.CodeModule.AddFromString([IO.File]::ReadAllText((Join-Path $root 'report/vba/EFASearch.bas')))
    $workbookModule = $project.VBComponents.Item($book.CodeName)
    # Localized Office names this document module, e.g. '현재_통합_문서'.
    # A workbook.xml codeName that differs prevents workbook events from firing.
    $workbookModule.Name = 'ThisWorkbook'
    $workbookCodeName = $workbookModule.Name
    if ($workbookCodeName -ne 'ThisWorkbook') { throw 'Workbook event module rename failed.' }
    $workbookModule.CodeModule.AddFromString([IO.File]::ReadAllText((Join-Path $root 'report/vba/ThisWorkbook.cls')))
    $form = $project.VBComponents.Add(3)
    $form.Name = 'EFAPicker'
    $designer = $form.Designer
    $form.Properties.Item('Width').Value = 440
    $form.Properties.Item('Height').Value = 350
    $form.Properties.Item('Caption').Value = '필터 검색'
    $controls = @(
        @('Forms.Label.1', 'CurrentValue', 12, 10, 404, 20, '현재 선택'),
        @('Forms.TextBox.1', 'Query', 12, 34, 404, 26, ''),
        @('Forms.ListBox.1', 'Candidates', 12, 66, 404, 182, ''),
        @('Forms.Label.1', 'Status', 12, 252, 404, 20, ''),
        @('Forms.CommandButton.1', 'AllButton', 12, 278, 100, 26, '전체 선택'),
        @('Forms.CommandButton.1', 'ApplyButton', 206, 278, 100, 26, '선택'),
        @('Forms.CommandButton.1', 'CancelButton', 316, 278, 100, 26, '취소')
    )
    foreach ($spec in $controls) {
        $control = $designer.Controls.Add($spec[0], $spec[1], $true)
        $control.Left = $spec[2]
        $control.Top = $spec[3]
        $control.Width = $spec[4]
        $control.Height = $spec[5]
        if ($spec[0] -ne 'Forms.TextBox.1' -and $spec[0] -ne 'Forms.ListBox.1') { $control.Caption = $spec[6] }
    }
    $designer.Controls.Item('Candidates').IntegralHeight = $false
    $designer.Controls.Item('Candidates').ColumnWidths = '390'
    $designer.Controls.Item('CancelButton').Cancel = $true
    $form.CodeModule.AddFromString([IO.File]::ReadAllText((Join-Path $root 'report/vba/EFAPicker.vba')))
    $book.SaveAs($macroBook, 52)
    # Invoke a public function: compile and run, rather than shipping unchecked VBA.
    $score = $excel.Run("'search_project.xlsm'!EFASearch.MatchScore", '모터', '모터')
    if ($score -ne 10000) { throw "VBA compilation/scoring failed: $score" }
    $book.Close($true)
    $book = $null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($macroBook)
    try {
        $entry = $archive.GetEntry('xl/vbaProject.bin')
        if ($null -eq $entry) { throw 'VBA project missing from generated workbook.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $root 'config/report_search_vba.bin'), $true)
    } finally { $archive.Dispose() }
    $sourceHashes = [ordered]@{}
    foreach ($name in @('ThisWorkbook.cls', 'EFASearch.bas', 'EFAPicker.vba')) {
        $sourceHashes[$name] = (Get-FileHash -LiteralPath (Join-Path $root ('report/vba/' + $name)) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    [ordered]@{
        workbook_codename = $workbookCodeName
        project_sha256 = (Get-FileHash -LiteralPath (Join-Path $root 'config/report_search_vba.bin') -Algorithm SHA256).Hash.ToLowerInvariant()
        source_sha256 = $sourceHashes
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'config/report_search_vba.json') -Encoding utf8NoBOM
    Write-Output 'Search VBA project created and executed successfully.'
} finally {
    try {
        if ($book) { $book.Close($false) }
        if ($excel) { $excel.Quit(); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
        if ($ownedProcess -and -not $ownedProcess.HasExited) { Stop-Process -Id $ownedProcess.Id -ErrorAction SilentlyContinue }
    } finally {
        if ($hadValue) {
            [void](New-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -PropertyType DWord -Value $old.AccessVBOM -Force)
        } else {
            Remove-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -ErrorAction SilentlyContinue
        }
        if (-not $securityExisted) {
            $key = Get-Item -LiteralPath $securityPath -ErrorAction SilentlyContinue
            if ($key -and $key.Property.Count -eq 0 -and $key.SubKeyCount -eq 0) { Remove-Item -LiteralPath $securityPath }
        }
        Write-Output 'Excel VBA access setting restored.'
    }
}
