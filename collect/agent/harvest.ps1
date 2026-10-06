<#
.SYNOPSIS
  ps 구현 수확·연결자(계약 §7.3 · §8.2 · X-300 · X-307 · TAB §1.6.1 ②·§8.3) — 에이전트 bin 사본의 ps\harvest.ps1.

.DESCRIPTION
  감독 루프(ps 구현 agent.ps1)가 자식으로 띄운다. 흐름(경로 ID)마다 PS 수집기와 정제 파이프를 둘 다 띄우고 잇는다:
    1. 수집기 stdin 에 제어 줄 _in 한 줄(커서·설정·본인 이름 — 내용은 사본 파이썬 agent_main.py --in-line 이 만든다. 어떤 키를
       넘길지는 파이썬 연결자와 같은 표 하나 — lm27.agent.harvest.COLLECTORS).
    2. 수집기 stdout(NDJSON + _cursor)을 사본 lm27_pipe.py --kind <kind> --src <경로 ID> --pc <pc_id> --mode append stdin 으로 그대로.
    3. 수집기가 예산 + 기동 여유를 넘기면 taskkill /T /F, 수집기 EOF 뒤 파이프가 privacy.pipe.waitSec 안에 끝나지 않으면 끊고 99.
    4. 결과는 숫자·열거·사유 코드만. 수확 흐름(pc.events · pc.files · pc.mru · pc.recent)이 하나라도 있으면 run\.harvest.lock 을 쥐고
       돌린 뒤 run\harvest_done.json(lm27.harvest_done/1)을 원자 교체한다. teams.uia·열린 문서 폴링(-Poll)은 결과를 로그에만.
  디스크 쓰기는 원문 없는 운영 파일(run\harvest_done.json · run\.harvest.lock · logs\)뿐이다(L-09 · X-307). 원문은 파이프에만.

.PARAMETER InstallId
  32자리 16진 install_id(agent.json 과 같아야 한다)
.PARAMETER Streams
  '<kind>/<경로 ID>' 를 쉼표로(예: pc_session/pc.events,pc_file/pc.files,pc_file/pc.mru,pc_file/pc.recent · teams/teams.uia)
.PARAMETER Poll
  열린 문서 저장 폴링(Get-FileActivity.ps1 -Poll — 커서는 pc.files 칸)
.PARAMETER Requested
  전경 [수집]의 harvest_now.flag 로 시작된 수확
.PARAMETER TestNow
  시험 주입(계약 §11.3): harvest_done.json 의 시각 기준
#>
param(
    [string]$InstallId = '',
    [string]$Streams = '',
    [switch]$Poll,
    [switch]$Requested,
    [string]$TestNow = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Off
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $script:Utf8 } catch { }
$script:Inv = [Globalization.CultureInfo]::InvariantCulture

# ───────────────────────── 위치(사본 기준 — 프로그램 폴더를 보지 않는다) ─────────────────────────
$script:PsDir = $PSScriptRoot
$script:Bin = Split-Path -Parent $script:PsDir
$script:AgentDir = Split-Path -Parent (Split-Path -Parent $script:Bin)
$script:Py = Join-Path (Join-Path $script:Bin 'py311') 'python.exe'
$script:Pipe = Join-Path $script:Bin 'lm27_pipe.py'
$script:Main = Join-Path $script:Bin 'agent_main.py'
$script:RunDir = Join-Path $script:AgentDir 'run'
$script:PsExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

# 흐름 표 — 파이썬 lm27.agent.harvest.COLLECTORS 와 같은 수집기·kind
$script:Spec = @{
    'pc.events' = @{ kind = 'pc_session'; script = 'Get-EventActivity.ps1'; harvest = $true }
    'pc.files'  = @{ kind = 'pc_file'; script = 'Get-FileActivity.ps1'; harvest = $true }
    'pc.mru'    = @{ kind = 'pc_file'; script = 'Get-OfficeMru.ps1'; harvest = $true }
    'pc.recent' = @{ kind = 'pc_file'; script = 'Get-RecentFiles.ps1'; harvest = $true }
    'teams.uia' = @{ kind = 'teams'; script = 'Get-TeamsWindow.ps1'; harvest = $false }
}
$PsSlackSec = 30
$EventsMaxSec = 60
$OoxmlTotalSec = 90
$ScanMaxSec = 120

# ───────────────────────── JSON(결정적, 숫자·문자열·목록·사전) ─────────────────────────
function ConvertTo-LmJsonString([string]$s) {
    $s = $s.Replace('\', '\\').Replace('"', '\"')
    if ($s -match '[\x00-\x1f]') {
        $s = [regex]::Replace($s, '[\x00-\x1f]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
    }
    return '"' + $s + '"'
}

function ConvertTo-LmJson($v) {
    if ($null -eq $v) { return 'null' }
    if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
    if ($v -is [string]) { return (ConvertTo-LmJsonString $v) }
    if ($v -is [double] -or $v -is [single] -or $v -is [decimal]) {
        $t = ([double]$v).ToString('R', $script:Inv)
        if ($t -notmatch '[.eE]') { $t += '.0' }
        return $t
    }
    if ($v -is [int] -or $v -is [long] -or $v -is [int16] -or $v -is [byte]) { return ([long]$v).ToString($script:Inv) }
    $parts = New-Object 'Collections.Generic.List[string]'
    if ($v -is [Collections.IDictionary]) {
        foreach ($k in @($v.Keys)) { $parts.Add((ConvertTo-LmJsonString ([string]$k)) + ':' + (ConvertTo-LmJson $v[$k])) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v -is [Management.Automation.PSCustomObject]) {
        foreach ($p in $v.PSObject.Properties) { $parts.Add((ConvertTo-LmJsonString $p.Name) + ':' + (ConvertTo-LmJson $p.Value)) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v -is [Collections.IEnumerable]) {
        foreach ($x in $v) { $parts.Add((ConvertTo-LmJson $x)) }
        return '[' + ($parts -join ',') + ']'
    }
    return (ConvertTo-LmJsonString ([string]$v))
}

function Format-LmUtc([datetime]$dt) {
    if ($dt.Kind -ne [DateTimeKind]::Utc) { $dt = $dt.ToUniversalTime() }
    return $dt.ToString("yyyy'-'MM'-'dd'T'HH':'mm':'ss'Z'", $script:Inv)
}

function Get-LmNow {
    if ($TestNow) {
        try { return [datetime]::Parse($TestNow, $script:Inv, [Globalization.DateTimeStyles]'AdjustToUniversal, AssumeUniversal') } catch { }
    }
    return [datetime]::UtcNow
}

# ───────────────────────── 순수 판정(시험이 AST 로 꺼내 쓴다) ─────────────────────────
# 흐름 문자열 → 실행 계획 목록(@{src; kind; script; poll; harvest}). 형식이 틀린 흐름은 건너뛴다.
function Get-LmPlan([string]$streams, [bool]$poll, $spec) {
    $out = New-Object 'Collections.Generic.List[object]'
    if ($poll) {
        $out.Add([ordered]@{ src = 'pc.files'; kind = 'pc_file'; script = 'Get-FileActivity.ps1'; poll = $true; harvest = $false })
        return , $out.ToArray()
    }
    foreach ($s in ($streams -split ',')) {
        $t = $s.Trim()
        if (-not $t) { continue }
        $kp = $t.Split('/')
        if ($kp.Count -ne 2) { continue }
        $e = $spec[$kp[1]]
        if ($null -eq $e -or $e.kind -ne $kp[0]) { continue }
        $out.Add([ordered]@{ src = $kp[1]; kind = $e.kind; script = $e.script; poll = $false; harvest = [bool]$e.harvest })
    }
    return , $out.ToArray()
}

# 수집기를 끊는 시각(초) = 예산 + 기동 여유(파이썬 lm27.agent.harvest.collector_timeout 과 같다)
function Get-LmCollectorTimeout($plan, $cfg) {
    if ($plan.src -eq 'teams.uia') { return ((Get-LmCfgInt $cfg 'teams.uia.budgetSec' 60 5 300) + $PsSlackSec) }
    if ($plan.src -eq 'pc.events') { return ($EventsMaxSec + $PsSlackSec) }
    if ($plan.src -eq 'pc.files' -and -not $plan.poll) {
        return ((Get-LmCfgInt $cfg 'pc.files.budgetSec' 180 10 3600) + $OoxmlTotalSec + $PsSlackSec)
    }
    return ($ScanMaxSec + $PsSlackSec)
}

function Get-LmCfgInt($cfg, [string]$key, [int]$default, [int]$lo, [int]$hi) {
    $v = $default
    if ($null -ne $cfg) {
        $p = $cfg.PSObject.Properties[$key]
        if ($null -ne $p -and ($p.Value -is [int] -or $p.Value -is [long] -or $p.Value -is [double])) { $v = [int]$p.Value }
    }
    if ($v -lt $lo) { $v = $lo }
    if ($v -gt $hi) { $v = $hi }
    return $v
}

# 수집기 stderr 의 마지막 {"_status": {...}} · 파이프 stdout 의 요약 줄(마지막 JSON)
function Get-LmLastJson([string]$text, [string]$key) {
    $lines = @($text -split "`n")
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        $ln = $lines[$i].Trim().TrimStart([char]0xFEFF)
        if (-not $ln.StartsWith('{')) { continue }
        try { $o = ConvertFrom-Json -InputObject $ln } catch { continue }
        if ($key) {
            $p = $o.PSObject.Properties[$key]
            if ($null -ne $p) { return $p.Value }
            continue
        }
        return $o
    }
    return $null
}

# 파이프 종료 코드 → 사유(계약 §8.2)
function Get-LmPipeReason($code) {
    if ($null -eq $code) { return $null }
    if ($code -eq 6) { return 'R-NOKEY' }
    if ($code -eq 3 -or $code -eq 5 -or $code -eq 99) { return 'R-TRANSPORT' }
    return $null
}

# ───────────────────────── 프로세스 ─────────────────────────
function Start-LmProc([string]$file, [string]$argline, [bool]$redirect) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $file
    $psi.Arguments = $argline
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $script:AgentDir
    if ($redirect) {
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = $script:Utf8
        $psi.StandardErrorEncoding = $script:Utf8
    }
    return [Diagnostics.Process]::Start($psi)
}

function Stop-LmTree([int]$procId) {
    try { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /T /F /PID $procId 2>&1 | Out-Null } catch { }
}

function Send-LmBytes($stream, [string]$text) {
    $b = $script:Utf8.GetBytes($text)
    $stream.Write($b, 0, $b.Length)
    $stream.Flush()
}

# 수집기 제어 줄 _in(사본 파이썬이 agent_config·context_cache·raw_cursor 로 만든다). 설정이 없으면 $null(그 흐름 건너뜀)
function Get-LmInLine($plan) {
    $a = '-X utf8 -I -B "' + $script:Main + '" --install-id ' + $InstallId + ' --in-line ' + $plan.src
    if ($plan.poll) { $a += ' --poll' }
    $p = Start-LmProc $script:Py $a $true
    $p.StandardInput.Close()
    $errTask = $p.StandardError.ReadToEndAsync()
    $out = $p.StandardOutput.ReadToEnd()
    if (-not $p.WaitForExit(30000)) { Stop-LmTree $p.Id; return $null }
    if ($p.ExitCode -ne 0) { return $null }
    $line = @($out -split "`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
    if ($line.Count -eq 0) { return $null }
    return $line[0].Trim()
}

function Invoke-LmStream($plan, $cfg, [string]$pc) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $res = [ordered]@{ src = $plan.src; kind = $plan.kind; rc = $null; pipe = $null; stored = 0; cursor_saved = $false;
                       timed_out = $false; skipped = ''; reasons = @(); elapsed_s = 0.0 }
    $inLine = $null
    try { $inLine = Get-LmInLine $plan } catch { $inLine = $null }
    if (-not $inLine) { $res.skipped = 'settings_missing'; return $res }
    $colArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $script:PsDir $plan.script) + '" -Pc ' + $pc
    if ($plan.poll) { $colArgs += ' -Poll' }
    $pipeArgs = '-X utf8 -I -B "' + $script:Pipe + '" --kind ' + $plan.kind + ' --src ' + $plan.src + ' --pc ' + $pc + ' --mode append'
    $pipe = $null; $col = $null
    try { $pipe = Start-LmProc $script:Py $pipeArgs $true } catch { $res.skipped = 'spawn_pipe'; $res.reasons = @('R-TRANSPORT'); return $res }
    try { $col = Start-LmProc $script:PsExe $colArgs $true } catch {
        Stop-LmTree $pipe.Id
        $res.skipped = 'spawn_collector'; $res.reasons = @('R-TRANSPORT'); return $res
    }
    $colErr = $col.StandardError.ReadToEndAsync()
    $pipeOut = $pipe.StandardOutput.ReadToEndAsync()
    $pipeErr = $pipe.StandardError.ReadToEndAsync()
    try { Send-LmBytes $col.StandardInput.BaseStream ($inLine + "`n") } catch { }
    try { $col.StandardInput.Close() } catch { }
    $copy = $col.StandardOutput.BaseStream.CopyToAsync($pipe.StandardInput.BaseStream)
    $limit = Get-LmCollectorTimeout $plan $cfg
    if ($col.WaitForExit([int]($limit * 1000))) { $res.rc = $col.ExitCode } else { Stop-LmTree $col.Id; $res.timed_out = $true }
    try { [void]$copy.Wait(10000) } catch { }
    try { $pipe.StandardInput.Close() } catch { }
    $waitMs = [int]((Get-LmCfgInt $cfg 'privacy.pipe.waitSec' 120 30 1800) * 1000)
    if ($pipe.WaitForExit($waitMs)) { $res.pipe = $pipe.ExitCode } else { Stop-LmTree $pipe.Id; $res.pipe = 99 }
    $errText = ''; $outText = ''
    try { if ($colErr.Wait(5000)) { $errText = $colErr.Result } } catch { }
    try { if ($pipeOut.Wait(5000)) { $outText = $pipeOut.Result } } catch { }
    try { [void]$pipeErr.Wait(2000) } catch { }
    $reasons = New-Object 'Collections.Generic.SortedSet[string]' ([StringComparer]::Ordinal)
    $st = Get-LmLastJson $errText '_status'
    $sm = Get-LmLastJson $outText ''
    if ($null -eq $st -and $null -ne $sm -and $null -ne $sm.PSObject.Properties['collector_status']) {
        $st = $sm.collector_status                  # CLM 모드: 상태 줄이 stdout 제어 줄로 와 파이프 요약에 실린다(C1)
    }
    if ($null -ne $st -and $null -ne $st.PSObject.Properties['reasons']) {
        foreach ($r in @($st.reasons)) { if ([string]$r -match '^R-[A-Z]') { [void]$reasons.Add([string]$r) } }
    }
    if ($st -is [Management.Automation.PSCustomObject]) { $res['status'] = $st }    # py 구현 as_dict 와 같이 — 있을 때만
    if ($null -ne $sm) {
        if ($null -ne $sm.PSObject.Properties['stored']) { $res.stored = [int]$sm.stored }
        if ($null -ne $sm.PSObject.Properties['cursor_saved']) { $res.cursor_saved = [bool]$sm.cursor_saved }
    }
    if ($res.timed_out) { [void]$reasons.Add('R-TRANSPORT') }
    $pr = Get-LmPipeReason $res.pipe
    if ($pr) { [void]$reasons.Add($pr) }
    $res.reasons = @($reasons)
    $res.elapsed_s = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    return $res
}

# ───────────────────────── 운영 파일(원문 없음 — L-09 예외) ─────────────────────────
function Write-LmLog([string]$text) {
    try {
        $d = (Get-LmNow).ToString('yyyyMMdd', $script:Inv)
        $logDir = Join-Path $script:AgentDir 'logs'
        if (-not [IO.Directory]::Exists($logDir)) { [void][IO.Directory]::CreateDirectory($logDir) }
        $logPath = Join-Path $logDir ('agent_' + $d + '.log')
        [IO.File]::AppendAllText($logPath, ((Format-LmUtc (Get-LmNow)) + ' ' + $text + "`n"), $script:Utf8)
    } catch { }
}

function Save-LmDone($done) {
    $donePath = Join-Path $script:RunDir 'harvest_done.json'
    $tmpPath = $donePath + '.' + $PID + '.part'
    $bytes = $script:Utf8.GetBytes((ConvertTo-LmJson $done) + "`n")
    [IO.File]::WriteAllBytes($tmpPath, $bytes)
    for ($i = 0; $i -lt 4; $i++) {
        try { Move-Item -LiteralPath $tmpPath -Destination $donePath -Force; return } catch { Start-Sleep -Milliseconds (100 * ($i + 1)) }
    }
    try { Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue } catch { }
}

function Read-LmJsonFile([string]$path) {
    if (-not [IO.File]::Exists($path)) { return $null }
    try { return ([IO.File]::ReadAllText($path, $script:Utf8) | ConvertFrom-Json) } catch { return $null }
}

# ───────────────────────── 본체 ─────────────────────────
function Invoke-Main {
    if ($InstallId -cnotmatch '^[0-9a-f]{32}$') { return 5 }
    $aj = Read-LmJsonFile (Join-Path $script:AgentDir 'agent.json')
    if ($null -eq $aj -or [string]$aj.install_id -ne $InstallId) { return 3 }
    $pc = [string]$aj.pc_id
    if ($pc -cnotmatch '^pcx?_[0-9a-f]{16}$') { return 3 }
    $cfg = Read-LmJsonFile (Join-Path $script:AgentDir 'agent_config.json')
    $plans = Get-LmPlan $Streams ([bool]$Poll) $script:Spec
    if ($plans.Count -eq 0) { return 5 }
    $isHarvest = @($plans | Where-Object { $_.harvest }).Count -gt 0
    $lockFs = $null
    if ($isHarvest) {
        if (-not [IO.Directory]::Exists($script:RunDir)) { [void][IO.Directory]::CreateDirectory($script:RunDir) }
        $lockPath = Join-Path $script:RunDir '.harvest.lock'
        try { $lockFs = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { Write-LmLog 'harvest_busy'; return 4 }
    }
    try {
        $started = Format-LmUtc (Get-LmNow)
        $out = [ordered]@{}
        $bad = 0
        foreach ($plan in $plans) {
            $r = Invoke-LmStream $plan $cfg $pc
            $out[[string]$plan.src] = $r
            if ($r.skipped -or $r.timed_out -or ($r.pipe -ne 0 -and $r.pipe -ne 2) -or ($r.rc -ne 0 -and $r.rc -ne 1 -and $r.rc -ne 4)) { $bad++ }
            Write-LmLog ('ps_' + $plan.src + ' rc=' + $r.rc + ' pipe=' + $r.pipe + ' stored=' + $r.stored)
        }
        $rc = 0
        if ($bad -gt 0) { $rc = 3 }
        if ($isHarvest) {
            $done = [ordered]@{ schema = 'lm27.harvest_done/1'; install_id = $InstallId; pc_id = $pc; requested = [bool]$Requested;
                                started_at = $started; finished_at = (Format-LmUtc (Get-LmNow)); rc = $rc; streams = $out }
            Save-LmDone $done
        }
        return $rc
    } finally {
        if ($null -ne $lockFs) { try { $lockFs.Dispose() } catch { } }
    }
}

$code = 3
try { $code = Invoke-Main } catch { Write-LmLog ('harvest_error ' + $_.Exception.GetType().Name); $code = 3 }
exit $code
