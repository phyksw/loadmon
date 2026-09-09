# Add-WorkLog.ps1
# One-line manual log for non-PC work (assembly, facility, equipment check, business trip).
# This is the ONLY reliable source for hands-off-keyboard work - keep it to one command a day.
# Usage:
#   .\Add-WorkLog.ps1 -Category 출장 -Hours 8 -Note "고객사 방문"
#   .\Add-WorkLog.ps1 -Category 장비점검 -Hours 2.5 -Date 2026-08-10
param(
    [Parameter(Mandatory = $true)][string]$Category,
    [Parameter(Mandatory = $true)][double]$Hours,
    [string]$Entity = '',
    [string]$Note = '',
    [string]$Date = ''
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = Join-Path $root 'data\manual'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$file = Join-Path $outDir 'worklog.csv'

if ([string]::IsNullOrWhiteSpace($Date)) { $Date = (Get-Date).ToString('yyyy-MM-dd') }
$d = [datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)   # validate

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}

if (-not (Test-Path $file)) {
    [System.IO.File]::AppendAllText($file, "date,category,hours,entity,note,user`r`n", [System.Text.Encoding]::UTF8)
}
$line = ('{0},{1},{2},{3},{4},{5}' -f $d.ToString('yyyy-MM-dd'), (Csv-Escape $Category), $Hours, (Csv-Escape $Entity), (Csv-Escape $Note), (Csv-Escape $env:USERNAME))
[System.IO.File]::AppendAllText($file, $line + "`r`n", [System.Text.Encoding]::UTF8)
Write-Host ("[worklog] {0}" -f $line)
