param(
    [string]$DevelopmentPython = 'python',
    [switch]$Quick
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskDevExe = (Get-Command $DevelopmentPython -ErrorAction Stop).Source
$taskLogDir = Join-Path $taskRoot 'verification'
[IO.Directory]::CreateDirectory($taskLogDir) | Out-Null
$taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$taskLog = Join-Path $taskLogDir ("lm25-check-$taskStamp.txt")
$taskMode = if ($Quick) { '--quick' } else { '--full' }
$taskSavedEncoding = [Console]::OutputEncoding
$taskSavedUtf8 = $env:PYTHONUTF8
$taskSavedIOEncoding = $env:PYTHONIOENCODING
$taskExit = 1
$taskTranscript = $false

try {
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    Start-Transcript -LiteralPath $taskLog | Out-Null
    $taskTranscript = $true
    Write-Host "LM25 quality checks: $taskMode"
    & $taskDevExe -B (Join-Path $PSScriptRoot 'quality.py') $taskMode --root $taskRoot
    $taskExit = $LASTEXITCODE
    Write-Host "Log: $taskLog"
}
finally {
    if ($taskTranscript) { Stop-Transcript | Out-Null }
    [Console]::OutputEncoding = $taskSavedEncoding
    $env:PYTHONUTF8 = $taskSavedUtf8
    $env:PYTHONIOENCODING = $taskSavedIOEncoding
}
exit $taskExit
