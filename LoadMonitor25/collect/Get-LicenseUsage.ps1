# Get-LicenseUsage.ps1
# FlexLM license server snapshot: which features are checked out by whom, since when.
# Ansys(HFSS/Maxwell/SIwave)/new Zemax use ansyslmd (FlexLM); CodeV uses SCL (also FlexLM-based).
# Server PCs invisible to the local sampler become measurable here - per-user, per-feature.
# Run every 5 min via Task Scheduler; analyzer reconstructs sessions from snapshots.
# Config: config\workitems.json > simTracking { lmutilPath, licenseServers }
# Usage:
#   .\Get-LicenseUsage.ps1                          # poll all configured servers once
#   .\Get-LicenseUsage.ps1 -ParseFile sample.txt    # parse a saved lmstat output (test)
param(
    [string]$ParseFile = ''
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$wi = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\workitems.json') | ConvertFrom-Json
$sim = $wi.simTracking
$outDir = Join-Path $root 'data\license'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}

# lmstat user line, e.g.:
#   user1 HOSTPC1 HOSTPC1 (v2024.0512) (licsrv/1055 1234), start Mon 8/17 9:05
$lineRe = '^\s+(\S+)\s+(\S+)\s+\S+\s+\(v[^)]*\)\s+\(([^/]+)/\d+\s+\d+\),\s+start\s+\S+\s+(\d+)/(\d+)\s+(\d+):(\d+)'
$featRe = '^Users of (\S+):'

function Parse-Lmstat([string[]]$lines, [string]$server, [System.Collections.Generic.List[string]]$rows, [datetime]$poll) {
    $feature = ''
    $found = 0
    foreach ($ln in $lines) {
        if ($ln -match $featRe) { $feature = $Matches[1]; continue }
        if ($feature -and $ln -match $lineRe) {
            $mo = [int]$Matches[4]; $dy = [int]$Matches[5]
            $hh = [int]$Matches[6]; $mi = [int]$Matches[7]
            $yr = $poll.Year
            if ($mo -gt $poll.Month) { $yr-- }        # start month after poll month -> last year
            try { $start = Get-Date -Year $yr -Month $mo -Day $dy -Hour $hh -Minute $mi -Second 0 } catch { continue }
            $rows.Add(('{0},{1},{2},{3},{4},{5}' -f `
                $poll.ToString('yyyy-MM-dd HH:mm'), (Csv-Escape $server), (Csv-Escape $feature), `
                (Csv-Escape $Matches[1]), (Csv-Escape $Matches[2]), $start.ToString('yyyy-MM-dd HH:mm')))
            $found++
        }
    }
    return $found
}

$poll = Get-Date
$rows = New-Object System.Collections.Generic.List[string]
$file = Join-Path $outDir ("license_{0}.csv" -f $poll.ToString('yyyyMMdd'))
if (-not (Test-Path $file)) {
    [System.IO.File]::AppendAllText($file, "poll,server,feature,user,host,start`r`n", [System.Text.Encoding]::UTF8)
}

if ($ParseFile) {
    if (-not (Test-Path $ParseFile)) { Write-Host "[license] file not found: $ParseFile"; exit 1 }
    $n = Parse-Lmstat (Get-Content $ParseFile) 'testfile' $rows $poll
    Write-Host ("[license] parsed {0} checkout(s) from file" -f $n)
}
else {
    $lmutil = [string]$sim.lmutilPath
    $servers = @($sim.licenseServers)
    if (-not $lmutil -or -not (Test-Path $lmutil) -or $servers.Count -eq 0) {
        Write-Host '[license] simTracking not configured (lmutilPath / licenseServers in config\workitems.json) - skipped'
        exit 0
    }
    foreach ($srv in $servers) {
        try {
            $out = & $lmutil lmstat -a -c $srv 2>&1
            $n = Parse-Lmstat $out $srv $rows $poll
            Write-Host ("[license] {0}: {1} checkout(s)" -f $srv, $n)
        } catch {
            Write-Host ("[license] {0} FAILED: {1}" -f $srv, $_.Exception.Message)
        }
    }
}

if ($rows.Count -gt 0) {
    [System.IO.File]::AppendAllText($file, (($rows -join "`r`n") + "`r`n"), [System.Text.Encoding]::UTF8)
}
Write-Host ("[license] appended {0} row(s) -> {1}" -f $rows.Count, $file)
