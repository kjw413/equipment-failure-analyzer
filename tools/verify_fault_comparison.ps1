param([Parameter(Mandatory=$true)][string]$ReportPath,[switch]$AllowTemporaryVbaAccess,[string]$EvidenceDirectory='tmp/qa/fault-comparison',[string]$ProbePath='tests/native_hierarchical_comparison.vba')
$ErrorActionPreference='Stop'
if (-not $AllowTemporaryVbaAccess) { throw 'Explicit authorization required.' }
$root=Split-Path -Parent $PSScriptRoot
[void][IO.Directory]::CreateDirectory((Join-Path $root $EvidenceDirectory))
$securityPath='HKCU:\Software\Microsoft\Office\16.0\Excel\Security'
$existed=Test-Path -LiteralPath $securityPath
$old=Get-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -ErrorAction SilentlyContinue
$excel=$null; $book=$null; $ownedProcess=$null
$hashBefore=(Get-FileHash -LiteralPath $ReportPath -Algorithm SHA256).Hash
try {
    if (-not $existed) { [void](New-Item -Path $securityPath -Force) }
    [void](New-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -PropertyType DWord -Value 1 -Force)
    $ownedProcess=Start-Process 'C:/Program Files/Microsoft Office/Root/Office16/EXCEL.EXE' -ArgumentList '/x','/automation' -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $excel=New-Object -ComObject Excel.Application
    $excel.Visible=$false; $excel.DisplayAlerts=$false; $excel.EnableEvents=$false
    $book=$excel.Workbooks.Open($ReportPath,0,$true)
    $probe=$book.VBProject.VBComponents.Add(1)
    $probe.Name='FaultComparisonQA'
    $probe.CodeModule.AddFromString([IO.File]::ReadAllText((Join-Path $root $ProbePath)))
    $excel.CalculateFull()
    $result=$excel.Run("'"+$book.Name+"'!FaultComparisonQA.VerifyFaultComparison",(Join-Path $root $EvidenceDirectory))
    Write-Output $result
    if ($result -notlike 'PASS;*') { throw "Native comparison verification failed: $result" }
    $book.Worksheets.Item('03.월별 주요이슈').ExportAsFixedFormat(0,(Join-Path $root ($EvidenceDirectory+'/monthly.pdf')))
    $book.Worksheets.Item('02.팀별 주요이슈').ExportAsFixedFormat(0,(Join-Path $root ($EvidenceDirectory+'/team.pdf')))
    $book.Close($false);$book=$null
    if ((Get-FileHash -LiteralPath $ReportPath -Algorithm SHA256).Hash -ne $hashBefore) { throw 'Source report changed.' }
    [ordered]@{passed=$true;result=$result;source_sha256=$hashBefore;source_unchanged=$true;excel_version=$excel.Version;physical_mouse_test=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root ($EvidenceDirectory+'/native_verification.json')) -Encoding utf8
} finally {
    try {
        if ($book) { $book.Close($false) }
        if ($excel) { $excel.Quit();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
        if ($ownedProcess -and -not $ownedProcess.HasExited) { Stop-Process -Id $ownedProcess.Id -ErrorAction SilentlyContinue }
    } finally {
        if ($old) { [void](New-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -PropertyType DWord -Value $old.AccessVBOM -Force) }
        else { Remove-ItemProperty -LiteralPath $securityPath -Name AccessVBOM -ErrorAction SilentlyContinue }
        if (-not $existed) {
            $key=Get-Item -LiteralPath $securityPath -ErrorAction SilentlyContinue
            if ($key -and $key.Property.Count -eq 0 -and $key.SubKeyCount -eq 0) { Remove-Item -LiteralPath $securityPath }
        }
        Write-Output 'Excel VBA access setting restored.'
    }
}
