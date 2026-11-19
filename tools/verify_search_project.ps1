param([Parameter(Mandatory=$true)][string]$ReportPath, [switch]$AllowTemporaryVbaAccess, [string]$EvidenceDirectory='output/report_v122_qa', [switch]$PreviewPdf)
$ErrorActionPreference = 'Stop'
if (-not $AllowTemporaryVbaAccess) { throw 'Explicit authorization required.' }
$root = Split-Path -Parent $PSScriptRoot
$securityPath = 'HKCU:\Software\Microsoft\Office\16.0\Excel\Security'
$existed = Test-Path -LiteralPath $securityPath
$old = Get-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -ErrorAction SilentlyContinue
$excel = $null
$book = $null
$ownedProcess = $null
$hashBefore = (Get-FileHash -LiteralPath $ReportPath -Algorithm SHA256).Hash
try {
    if (-not $existed) { [void](New-Item -Path $securityPath -Force) }
    [void](New-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -PropertyType DWord -Value 1 -Force)
    $ownedProcess = Start-Process 'C:/Program Files/Microsoft Office/Root/Office16/EXCEL.EXE' -ArgumentList '/x', '/automation' -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $book = $excel.Workbooks.Open($ReportPath, 0, $true)
    $probe = $book.VBProject.VBComponents.Add(1)
    $probe.Name = 'NativeSearchQA'
    $probe.CodeModule.AddFromString([IO.File]::ReadAllText((Join-Path $root 'tests/native_excel_search.vba')))
    $probe.CodeModule.AddFromString([IO.File]::ReadAllText((Join-Path $root 'tests/native_period_search.vba')))
    # QA-only entry point calls the same private handler used by TextBox.KeyDown.
    $formCode = [IO.File]::ReadAllText((Join-Path $root 'report/vba/EFAPicker.vba')).Replace('Query.SetFocus', "Query.SetFocus`r`n    NativeSearchQA.ObservePicker Me")
    $formModule = $book.VBProject.VBComponents.Item('EFAPicker').CodeModule
    $formModule.DeleteLines(1, $formModule.CountOfLines)
    $formModule.AddFromString($formCode + "`r`nPublic Function ProbeKey(ByVal code As Integer) As Integer`r`nProbeKey = HandleKey(code)`r`nEnd Function")
    # Do not leave an unattended test blocked by a production error message box.
    $searchCode = [IO.File]::ReadAllText((Join-Path $root 'report/vba/EFASearch.bas'))
    $searchCode = [regex]::Replace($searchCode, '(?m)^\s*MsgBox .*$', '    NativeSearchQA.RecordPickerFailure Err.Description')
    $searchCode = $searchCode.Replace('picker.Prepare Target.Cells(1, 1)', "NativeSearchQA.Trace `"Before Prepare`"`r`n    picker.Prepare Target.Cells(1, 1)`r`n    NativeSearchQA.Trace `"After Prepare`"")
    $searchCode = $searchCode.Replace('picker.Show vbModal', "NativeSearchQA.Trace `"Before Show`"`r`n    picker.Show vbModal`r`n    NativeSearchQA.Trace `"After Show`"")
    $searchModule = $book.VBProject.VBComponents.Item('EFASearch').CodeModule
    $searchModule.DeleteLines(1, $searchModule.CountOfLines)
    $searchModule.AddFromString($searchCode)
    $searchModule.AddFromString("`r`nPublic Function ProbeChartBindingCount() As Long`r`nInitialize`r`nProbeChartBindingCount = ChartHandlers.Count`r`nEnd Function")
    $chartModule = $book.VBProject.VBComponents.Item('EFADrillChart').CodeModule
    $chartModule.AddFromString("`r`nPublic Function ProbeDoubleClick(ByVal point As Long) As Boolean`r`nDim cancelled As Boolean`r`nWatched_BeforeDoubleClick xlSeries, 1, point, cancelled`r`nProbeDoubleClick = cancelled`r`nEnd Function")
    # Route a probe through the bound handler so the real BeforeDoubleClick procedure runs.
    $searchModule.AddFromString("`r`nPublic Function ProbeChartDoubleClick(ByVal sheetName As String, ByVal chartIndex As Long, ByVal point As Long) As Boolean`r`nInitialize`r`nDim handler As EFADrillChart`r`nFor Each handler In ChartHandlers`r`nIf handler.Watched.Parent.Parent.Name = sheetName And handler.Watched.Parent.Index = chartIndex Then ProbeChartDoubleClick = handler.ProbeDoubleClick(point): Exit Function`r`nNext handler`r`nEnd Function")
    $excel.CalculateFull()
    if ($PreviewPdf) { $excel.Run("'" + $book.Name + "'!NativeSearchQA.SetPreviewDirectory", (Join-Path $root $EvidenceDirectory)) }
    $result = $excel.Run("'" + $book.Name + "'!NativeSearchQA.VerifySearch")
    if ($result -notlike 'PASS;*') { throw "Native Excel verification failed: $result" }
    Write-Output $result
    $drill = $excel.Run("'" + $book.Name + "'!NativeSearchQA.VerifyDrilldown")
    Write-Output $drill
    if ($drill -notlike 'PASS;*') { throw "Drilldown verification failed: $drill" }
    $comparison = $excel.Run("'" + $book.Name + "'!NativeSearchQA.VerifyComparisonSort")
    Write-Output $comparison
    if ($comparison -notlike 'PASS;*') { throw "Comparison sort verification failed: $comparison" }
    $period = $excel.Run("'" + $book.Name + "'!NativeSearchQA.VerifyPeriod")
    Write-Output $period
    if ($period -notlike 'PASS;*') { throw "Month/day verification failed: $period" }
    $excel.Visible = $true
    $events = $excel.Run("'" + $book.Name + "'!NativeSearchQA.VerifyWorkbookEvents")
    Write-Output $events
    if ($events -notlike 'PASS;*') { throw "Native workbook event verification failed: $events" }
    if ($PreviewPdf) {
        $book.Worksheets.Item('01.종합현황').ExportAsFixedFormat(0, (Join-Path $root ($EvidenceDirectory + '/summary_native.pdf')))
        $book.Worksheets.Item('03.월별 주요이슈').ExportAsFixedFormat(0, (Join-Path $root ($EvidenceDirectory + '/trend_native.pdf')))
        $book.Worksheets.Item('04.고장비교').ExportAsFixedFormat(0, (Join-Path $root ($EvidenceDirectory + '/comparison_native.pdf')))
        $book.Worksheets.Item('별첨. 동일 상세설비 비교').ExportAsFixedFormat(0, (Join-Path $root ($EvidenceDirectory + '/module_compare_native.pdf')))
    }
    $book.Close($false)
    $book = $null
    if ((Get-FileHash -LiteralPath $ReportPath -Algorithm SHA256).Hash -ne $hashBefore) { throw 'Report changed during verification.' }
    $evidence = [ordered]@{ passed=$true; native_excel_version=$excel.Version; result=$result; drilldown=$drill; comparison_sort=$comparison; period_drilldown=$period; workbook_selection_event=$events; source_sha256=$hashBefore; source_unchanged=$true; keyboard_handlers_tested=$true; keyboard_visual_test=$false }
    $evidence | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root ($EvidenceDirectory + '/native_verification.json')) -Encoding utf8
} finally {
    try {
        if ($book) { $book.Close($false) }
        if ($excel) { $excel.Quit(); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
        if ($ownedProcess -and -not $ownedProcess.HasExited) { Stop-Process -Id $ownedProcess.Id -ErrorAction SilentlyContinue }
    } finally {
        if ($old) { [void](New-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -PropertyType DWord -Value $old.AccessVBOM -Force) }
        else { Remove-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -ErrorAction SilentlyContinue }
        if (-not $existed) {
            $key = Get-Item -LiteralPath $securityPath -ErrorAction SilentlyContinue
            if ($key -and $key.Property.Count -eq 0 -and $key.SubKeyCount -eq 0) { Remove-Item -LiteralPath $securityPath }
        }
        Write-Output 'Excel VBA access setting restored.'
    }
}
