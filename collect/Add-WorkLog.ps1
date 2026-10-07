# Add-WorkLog.ps1
# One-line manual log for non-PC work (assembly, facility, equipment check, business trip).
# This is the ONLY reliable source for hands-off-keyboard work - keep it to one command a day.
# Usage:
#   .\Add-WorkLog.ps1 -Category 출장 -Hours 8 -Note "고객사 방문"
#   .\Add-WorkLog.ps1 -Category 장비점검 -Hours 2.5 -Date 2026-08-10
#   .\Add-WorkLog.ps1 -Category 현장 -Start 09:30 -End 12:00 -Note "라인 점검"     # 구간(LM28) - 시간은 구간 길이
# Output: ..\data\manual\worklog.csv  date,category,hours,entity,note,user,start,end
#   start·end(HH:mm)는 LM28 에서 끝에 더한 열이다 - 구간을 모르면 ''. 읽는 쪽(core\extract)은 열 이름으로 읽는다.
#   옛 6열 머리말 파일이면 머리말 한 줄만 새 것으로 바꾼다(그대로 8열 행을 덧붙이면 '열이 남는 행' 으로 버려진다).
#   -End 가 -Start 보다 이르면 자정을 넘긴 구간으로 본다. -Hours 를 함께 주면 그 값을 쓴다(구간은 기록만).
param(
    [Parameter(Mandatory = $true)][string]$Category,
    [double]$Hours = -1,
    [string]$Entity = '',
    [string]$Note = '',
    [string]$Date = '',
    [string]$Start = '',         # HH:mm (LM28)
    [string]$End = '',           # HH:mm (LM28)
    [string]$OutDir = ''         # 출력 폴더 대체 (기본 ..\data\manual) - 시험용
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = if ($OutDir) { $OutDir } else { Join-Path $root 'data\manual' }
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$file = Join-Path $outDir 'worklog.csv'
$header = 'date,category,hours,entity,note,user,start,end'

if ([string]::IsNullOrWhiteSpace($Date)) { $Date = (Get-Date).ToString('yyyy-MM-dd') }
$d = [datetime]::ParseExact($Date, 'yyyy-MM-dd', $null)   # validate

# 구간(-Start·-End) - 둘 다 주거나 둘 다 비운다
$inv = [System.Globalization.CultureInfo]::InvariantCulture
$s0 = ''; $e0 = ''
if ($Start -or $End) {
    if (-not ($Start -and $End)) { throw '-Start 와 -End 는 함께 주세요 (HH:mm)' }
    $ts = [datetime]::ParseExact($Start.Trim(), 'H:mm', $inv)
    $te = [datetime]::ParseExact($End.Trim(), 'H:mm', $inv)
    $span = ($te - $ts).TotalHours
    if ($span -le 0) { $span += 24 }                       # 자정을 넘긴 구간(야간 현장)
    $s0 = $ts.ToString('HH:mm'); $e0 = $te.ToString('HH:mm')
    if ($Hours -lt 0) { $Hours = [math]::Round($span, 2) }
}
if ($Hours -le 0) { throw '-Hours 또는 -Start/-End 로 0 보다 큰 시간을 주세요' }

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}

if (-not (Test-Path $file)) {
    [System.IO.File]::AppendAllText($file, $header + "`r`n", [System.Text.Encoding]::UTF8)
} else {
    # 옛 6열 머리말(date,category,hours,entity,note,user) → 새 머리말로 한 줄만 바꾼다
    $lines = [System.IO.File]::ReadAllLines($file, [System.Text.Encoding]::UTF8)
    if ($lines.Count -gt 0 -and $lines[0].TrimStart([char]0xFEFF) -eq 'date,category,hours,entity,note,user') {
        $lines[0] = $header
        [System.IO.File]::WriteAllLines($file, $lines, [System.Text.Encoding]::UTF8)
    }
}
$line = ('{0},{1},{2},{3},{4},{5},{6},{7}' -f $d.ToString('yyyy-MM-dd'), (Csv-Escape $Category), $Hours.ToString($inv), (Csv-Escape $Entity), (Csv-Escape $Note), (Csv-Escape $env:USERNAME), $s0, $e0)
[System.IO.File]::AppendAllText($file, $line + "`r`n", [System.Text.Encoding]::UTF8)
Write-Host ("[worklog] {0}" -f $line)
