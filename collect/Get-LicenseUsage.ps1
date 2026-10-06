<#
.SYNOPSIS
  pc.compute 라이선스 수집기(CP §8, 옵트인 — pc.license.enabled) — FlexLM lmstat 에서 **본인 사용자·본인 호스트 행만** NDJSON 으로 낸다.

.DESCRIPTION
  이전 판은 호출·소비 없이 모든 사용자의 체크아웃을 기록했다(동료 정보 수집). LM27 은(X-146):
    · lmutil lmstat -a -c <서버> 출력에서 사용자 = 이 PC 로그인 계정, 호스트 = 이 PC 이름 인 행만 메모리에서 고른다.
    · 원시 레코드에 user·host·server(사용자명·호스트명·서버 주소)를 넣지 않는다(P §10.2 금지 원시 필드).
    · app_id 는 카탈로그 slug(아래 기능 이름 접두 표) — 제품명 평문이 아니다(X-071). 모르는 기능은 unknown:lic_<기능 slug>.
    · 구간 = 체크아웃 시작 ~ 조회 시각(끝은 모름 → flags.end_uncertain), flags.license.
  설정(_in.cfg): pc.license.lmutilPath · pc.license.servers(· pc.license.enabled 가 false 면 건너뜀).
  rc(계약 §8.1): 0 본인 행 있음 · 1 설정 없음·본인 행 0 · 3 lmutil 없음·모든 서버 실패(R-TRANSPORT).
  서버당 대기 30초(lmutil 이 응답하지 않으면 끊는다). 디스크에 쓰지 않는다(L-09).

.PARAMETER TestNow
  시험 주입: 조회 시각('지금')
#>
param(
    [string]$Pc = '',
    [string]$TestNow = ''
)

# ── 제한 언어 모드(CLM) — 다른 어떤 문(New-Object·[Console]·.NET 형·공통 도우미)보다 먼저 본다 ─────────────────────
# 계약 v1.2 §0.7 C1·C4 · §8.1: 막힌 경로는 rc 3 + 사유(R-CLM). CLM 에서는 [Console] 호출도 막히므로 상태 줄을 stdout
# 제어 줄로 낸다(문자열 리터럴 출력만 — 핵심 형으로 충분). 이전에는 New-Object 에서 멈춰 rc 1·출력 0바이트였고
# 원장이 미관측을 '0건 관측(zero_ok)'으로 기록했다(W1 통합 창 결함 수정).
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    '{"_status":{"schema":"lm27.collector_status/1","src":"pc.compute","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{}}}'
    exit 3
}

$ErrorActionPreference = 'Stop'
Set-StrictMode -Off

# ───────────────────────── 공통 도우미 ─────────────────────────
# 수집기마다 같은 사본이다 — 에이전트 bin\<ver>\ps\ 에 스크립트가 낱개로 복사되므로 공용 모듈을 두지 않는다(계약 §1.3).
# 출력 규약(계약 §7.3 · X-300): stdout = NDJSON 레코드 줄 + 마지막 줄 {"_cursor": …}. 상태는 stderr 마지막 줄
# {"_status": {rc, reasons, partial, cap_hit, budget_hit, n, …}} — 숫자·열거·사유 코드만(원문·경로 없음).
# 디스크에는 아무것도 쓰지 않는다(L-09). Write-Host 는 stdout 으로 새므로 쓰지 않는다.
$script:Inv = [Globalization.CultureInfo]::InvariantCulture
$script:InCfg = $null
$script:InCursor = $null
$script:InSelfNames = @()
$script:InState = 'none'
$script:Reasons = New-Object 'Collections.Generic.List[string]'

function Set-LmOutput {
    try { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) } catch { }
}

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
    if ($v -is [string] -or $v -is [char]) { return (ConvertTo-LmJsonString ([string]$v)) }
    if ($v -is [datetime]) { return (ConvertTo-LmJsonString (Format-LmUtc $v)) }
    if ($v -is [double] -or $v -is [single] -or $v -is [decimal]) {
        $d = [double]$v
        if ([double]::IsNaN($d) -or [double]::IsInfinity($d)) { return 'null' }
        $t = $d.ToString('R', $script:Inv)
        if ($t -notmatch '[.eE]') { $t += '.0' }
        return $t
    }
    if ($v -is [int] -or $v -is [long] -or $v -is [int16] -or $v -is [byte] -or $v -is [sbyte] -or
        $v -is [uint16] -or $v -is [uint32] -or $v -is [uint64]) {
        return ([Convert]::ToString($v, $script:Inv))
    }
    $parts = New-Object 'Collections.Generic.List[string]'
    if ($v -is [Collections.IDictionary]) {
        foreach ($k in @($v.PSBase.Keys)) { $parts.Add((ConvertTo-LmJsonString ([string]$k)) + ':' + (ConvertTo-LmJson $v[$k])) }
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

function Write-LmLine([string]$line) { [Console]::Out.Write($line + "`n") }
function Write-LmRecord($rec) { Write-LmLine (ConvertTo-LmJson $rec) }
function Write-LmCursor($cur) { Write-LmLine (ConvertTo-LmJson ([ordered]@{ _cursor = $cur })) }
function Write-LmNote([string]$text) { try { [Console]::Error.WriteLine($text) } catch { } }
# 계약 v1.2 §0.7 C1 — 상태 줄 필수 counts{}: 최상위 정수 필드(rc·n·elapsed_ms 제외)와 정수만 담은 사전을 counts 에도 싣는다
function Complete-LmStatusCounts($st) {
    if ($null -eq $st['counts']) { $st['counts'] = [ordered]@{} }
    foreach ($k in @($st.Keys)) {
        if (@('rc', 'n', 'elapsed_ms', 'counts') -contains $k) { continue }
        $v = $st[$k]
        if ($null -eq $v -or $v -is [bool] -or $st['counts'].Contains($k)) { continue }
        if ($v -is [int] -or $v -is [long]) { $st['counts'][$k] = $v; continue }
        if ($v -is [Collections.IDictionary] -and $v.Count -gt 0) {
            $allInt = $true
            foreach ($x in @($v.Values)) { if (-not ($x -is [int] -or $x -is [long]) -or $x -is [bool]) { $allInt = $false; break } }
            if ($allInt) { $st['counts'][$k] = $v }
        }
    }
}

function Write-LmStatus($st) {
    try { [Console]::Out.Flush() } catch { }
    try { Complete-LmStatusCounts $st } catch { }
    try { [Console]::Error.WriteLine((ConvertTo-LmJson ([ordered]@{ _status = $st }))); [Console]::Error.Flush() } catch { }
}
function Add-LmReason([string]$code) { if (-not $script:Reasons.Contains($code)) { $script:Reasons.Add($code) } }

# 연결자가 stdin 에 쓰는 한 줄 {"_in": {"cursor": …, "cfg": {…}, "self_names": […]}}(계약 §7.3). stdin 이 리디렉션되지
# 않았거나 비었으면 기본값으로 돈다(시험 편의). 커서·설정·이름은 명령줄에 싣지 않는다.
function Read-LmIn {
    $redir = $false
    try { $redir = [Console]::IsInputRedirected } catch { $redir = $false }
    if (-not $redir) { return }
    $line = $null
    try {
        $sr = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding($false)))
        $line = $sr.ReadLine()
    } catch { $line = $null }
    if ([string]::IsNullOrWhiteSpace($line)) { return }
    $line = $line.Trim().TrimStart([char]0xFEFF)
    $o = $null
    try { $o = ConvertFrom-Json -InputObject $line } catch { $o = $null }
    if ($null -eq $o -or $null -eq $o.PSObject.Properties['_in']) { $script:InState = 'bad'; return }
    $in = $o._in
    $script:InState = 'ok'
    if ($null -eq $in) { return }
    if ($null -ne $in.PSObject.Properties['cursor']) { $script:InCursor = $in.cursor }
    if ($null -ne $in.PSObject.Properties['cfg']) { $script:InCfg = $in.cfg }
    if ($null -ne $in.PSObject.Properties['self_names']) { $script:InSelfNames = @($in.self_names | Where-Object { $_ }) }
}

# _in.cfg 의 계약 §5.2 키 값. 없거나 null 이면 기본값. 목록 키는 호출자가 @( … ) 로 감싼다.
function Get-LmCfg([string]$Key, $Default) {
    if ($null -ne $script:InCfg) {
        $p = $script:InCfg.PSObject.Properties[$Key]
        if ($null -ne $p -and $null -ne $p.Value) { return $p.Value }
    }
    return $Default
}

function Format-LmUtc([datetime]$dt) {
    if ($dt.Kind -ne [DateTimeKind]::Utc) { $dt = $dt.ToUniversalTime() }
    return $dt.ToString("yyyy'-'MM'-'dd'T'HH':'mm':'ss'Z'", $script:Inv)
}

# 그 순간의 이 PC 오프셋 '+09:00'(zoneinfo 없이 .NET TimeZoneInfo — 계약 §9.1)
function Format-LmOffset([datetime]$utc) {
    if ($utc.Kind -ne [DateTimeKind]::Utc) { $utc = $utc.ToUniversalTime() }
    $m = [int][math]::Round([TimeZoneInfo]::Local.GetUtcOffset($utc).TotalMinutes)
    $sg = '+'
    if ($m -lt 0) { $sg = '-'; $m = -$m }
    return ('{0}{1:00}:{2:00}' -f $sg, [int][math]::Floor($m / 60), ($m % 60))
}

# 'yyyy-MM-ddTHH:mm:ssZ'(UTC) 또는 로컬 'yyyy-MM-dd HH:mm[:ss]' → UTC DateTime. 못 읽으면 $null.
function ConvertFrom-LmTime($s) {
    if ($null -eq $s) { return $null }
    if ($s -is [datetime]) { return $s.ToUniversalTime() }
    $t = ([string]$s).Trim()
    if (-not $t) { return $null }
    try {
        if ($t.EndsWith('Z')) {
            $d = [datetime]::ParseExact($t, [string[]]@("yyyy-MM-dd'T'HH:mm:ss'Z'", "yyyy-MM-dd'T'HH:mm'Z'",
                    "yyyy-MM-dd'T'HH:mm:ss.FFFFFFF'Z'"), $script:Inv,
                [Globalization.DateTimeStyles]'AdjustToUniversal, AssumeUniversal')
            return [datetime]::SpecifyKind($d, [DateTimeKind]::Utc)
        }
        $d = [datetime]::ParseExact($t, [string[]]@('yyyy-MM-dd HH:mm:ss', 'yyyy-MM-dd HH:mm', "yyyy-MM-dd'T'HH:mm:ss",
                "yyyy-MM-dd'T'HH:mm", 'yyyy-MM-dd'), $script:Inv, [Globalization.DateTimeStyles]::None)
        return [datetime]::SpecifyKind($d, [DateTimeKind]::Local).ToUniversalTime()
    } catch { return $null }
}

# 지금(UTC) — 시험 주입 -TestNow(또는 스크립트별 -Now)가 있으면 그 값
function Get-LmNow([string]$Override) {
    $t = ConvertFrom-LmTime $Override
    if ($null -ne $t) { return $t }
    return [datetime]::UtcNow
}

# 수집 기간: -Since/-Until(로컬 날짜, 끝 포함) · 없으면 오늘 − collect.lookbackDays(기본 120) ~ 오늘
function Get-LmRange([string]$Since, [string]$Until, [int]$Days, [datetime]$NowUtc) {
    $nowLocal = $NowUtc.ToLocalTime()
    if ($Days -le 0) {
        $Days = 120
        try { $Days = [int](Get-LmCfg 'collect.lookbackDays' 120) } catch { $Days = 120 }
        if ($Days -le 0) { $Days = 120 }
    }
    $s = $nowLocal.Date.AddDays(-$Days)
    if ($Since) { $s = [datetime]::ParseExact($Since.Trim(), 'yyyy-MM-dd', $script:Inv) }
    $u = $nowLocal.Date.AddDays(1)
    if ($Until) { $u = [datetime]::ParseExact($Until.Trim(), 'yyyy-MM-dd', $script:Inv).AddDays(1) }
    $sl = [datetime]::SpecifyKind($s, [DateTimeKind]::Local)
    $ul = [datetime]::SpecifyKind($u, [DateTimeKind]::Local)
    return @{ SinceUtc = $sl.ToUniversalTime(); UntilUtc = $ul.ToUniversalTime(); Days = $Days;
              From = $sl.ToString('yyyy-MM-dd', $script:Inv); To = $ul.AddDays(-1).ToString('yyyy-MM-dd', $script:Inv) }
}

# _in.cursor.last_ts_utc → UTC DateTime 또는 $null(계약 §3.10 pc.* 커서 {last_ts_utc})
function Get-LmCursorUtc {
    $c = $script:InCursor
    if ($null -eq $c) { return $null }
    $p = $c.PSObject.Properties['last_ts_utc']
    if ($null -eq $p -or $null -eq $p.Value) { return $null }
    return (ConvertFrom-LmTime $p.Value)
}

function New-LmStatus([string]$Src) {
    return [ordered]@{ schema = 'lm27.collector_status/1'; src = $Src; rc = 3; reasons = @(); partial = $false;
                       cap_hit = $false; budget_hit = $false; n = 0; counts = [ordered]@{}; in = 'none'; elapsed_ms = 0 }
}

Set-LmOutput

$ServerWaitSec = 30
# lmstat 사용자 줄:  <user> <host> <display> (v<ver>) (<server>/<port> <handle>), start <요일> <월>/<일> <시>:<분>
$LineRe = '^\s+(\S+)\s+(\S+)\s+\S+.*?\(v[^)]*\)\s+\(([^/\s]+)/\d+\s+\d+\)(?:,\s*\d+\s+licenses?)?,\s+start\s+\S+\s+(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})'
$FeatRe = '^Users of ([^:\s]+):'
# FlexLM 기능 이름 접두 → 카탈로그 app_id(lm27\catalog.py 의 slug). 긴 접두 먼저.
$FeatureMap = @(
    @('elec_solve', 'ansys_electronics_desktop'), @('electronics', 'ansys_electronics_desktop'), @('hfss', 'ansys_electronics_desktop'),
    @('maxwell', 'ansys_electronics_desktop'), @('siwave', 'ansys_electronics_desktop'), @('icepak', 'ansys_icepak'),
    @('fluent', 'ansys_fluent'), @('acfd', 'ansys_fluent'), @('cfd_', 'ansys_fluent'), @('cfx', 'ansys_cfx'),
    @('ane3fl', 'ansys_mechanical_apdl'), @('mech_', 'ansys_mechanical_apdl'), @('ansys', 'ansys_mechanical_apdl'),
    @('dyna', 'ls_dyna'), @('spaceclaim', 'spaceclaim'), @('discovery', 'ansys_discovery'),
    @('zemax', 'zemax_opticstudio'), @('opticstudio', 'zemax_opticstudio'), @('optic', 'zemax_opticstudio'),
    @('codev', 'code_v'), @('lighttools', 'lighttools'), @('lumerical', 'lumerical'), @('fdtd', 'lumerical'),
    @('abaqus', 'abaqus'), @('comsol', 'comsol_multiphysics'), @('matlab', 'matlab_simulink'), @('simulink', 'matlab_simulink'),
    @('nastran', 'msc_nastran_patran_femap'), @('patran', 'msc_nastran_patran_femap'), @('hyperworks', 'altair_hyperworks'),
    @('starccm', 'simcenter_star_ccm'), @('floefd', 'floefd_flotherm'), @('flotherm', 'floefd_flotherm'),
    @('vivado', 'vivado_vitis'), @('quartus', 'quartus'), @('allegro', 'cadence_allegro_orcad'), @('orcad', 'cadence_allegro_orcad'),
    @('pspice', 'cadence_allegro_orcad'), @('altium', 'altium_designer'), @('ads', 'keysight_ads'),
    @('modelsim', 'modelsim_questa'), @('questa', 'modelsim_questa'), @('catia', 'catia'), @('solidworks', 'solidworks'),
    @('creo', 'creo_parametric'), @('proe', 'creo_parametric'), @('nx', 'nx'), @('inventor', 'inventor'), @('autocad', 'autocad')
)

function Get-LmFeatureAppId([string]$feature) {
    $f = $feature.ToLower()
    $best = $null
    foreach ($m in $FeatureMap) {
        if ($f.StartsWith($m[0]) -and ($null -eq $best -or $m[0].Length -gt $best[0].Length)) { $best = $m }
    }
    if ($null -ne $best) { return $best[1] }
    $s = ($f -replace '[^a-z0-9]+', '_').Trim('_')
    if ($s.Length -gt 36) { $s = $s.Substring(0, 36) }
    if (-not $s) { $s = 'feature' }
    return ('unknown:lic_' + $s)
}

# lmutil 출력 줄 → 본인 행 [{feature, start(local)}]. 남의 행은 세기만 하고 버린다.
function Select-LmOwnRows([string[]]$lines, [datetime]$pollLocal, [string]$me, [string]$myHost) {
    $out = New-Object 'Collections.Generic.List[psobject]'
    $feature = ''
    foreach ($ln in $lines) {
        if ($ln -match $FeatRe) { $feature = $Matches[1]; continue }
        if (-not $feature -or $ln -notmatch $LineRe) { continue }
        $u = $Matches[1].ToLower(); $h = $Matches[2].ToLower()
        $mo = [int]$Matches[4]; $dy = [int]$Matches[5]; $hh = [int]$Matches[6]; $mi = [int]$Matches[7]
        if ($u -ne $me -or $h -ne $myHost) { $script:NOther++; continue }
        $yr = $pollLocal.Year
        if ($mo -gt $pollLocal.Month) { $yr-- }
        $start = $null
        try { $start = New-Object DateTime ($yr, $mo, $dy, $hh, $mi, 0, [DateTimeKind]::Local) } catch { $start = $null }
        if ($null -eq $start -or $start -gt $pollLocal) { continue }
        $out.Add([pscustomobject]@{ feature = $feature; start = $start })
    }
    return ,$out
}

function Invoke-LmLmstat([string]$exe, [string]$server) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = 'lmstat -a -c "' + $server.Replace('"', '') + '"'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $p = [Diagnostics.Process]::Start($psi)
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit($ServerWaitSec * 1000)) {
        try { & taskkill.exe /T /F /PID $p.Id | Out-Null } catch { }
        return $null
    }
    [void]$errTask.Wait(2000)
    if (-not $outTask.Wait(2000)) { return $null }
    if ($p.ExitCode -ne 0 -and -not $outTask.Result) { return $null }
    return ($outTask.Result -split "`r?`n")
}

function Invoke-Main {
    Read-LmIn
    $script:St['in'] = $script:InState
    $script:NOther = 0
    $nowUtc = Get-LmNow $TestNow
    $pollLocal = $nowUtc.ToLocalTime()
    $enabled = [bool](Get-LmCfg 'pc.license.enabled' $true)
    $lmutil = [string](Get-LmCfg 'pc.license.lmutilPath' '')
    $servers = @(Get-LmCfg 'pc.license.servers' @() | Where-Object { $_ } | ForEach-Object { [string]$_ })
    $me = ([string]$env:USERNAME).ToLower()
    $myHost = ([string]$env:COMPUTERNAME).ToLower()
    $script:St['servers'] = $servers.Count
    if (-not $enabled -or -not $lmutil -or $servers.Count -eq 0) {
        $script:St['configured'] = $false
        Write-LmCursor ([ordered]@{ last_ts_utc = $null })
        $script:Rc = 1
        return
    }
    $script:St['configured'] = $true
    if (-not [IO.File]::Exists($lmutil)) {
        Add-LmReason 'R-TRANSPORT'
        $script:St['lmutil'] = 'missing'
        $script:Rc = 3
        return
    }
    $rows = New-Object 'Collections.Generic.List[psobject]'
    $ok = 0
    $failed = 0
    foreach ($srv in $servers) {
        $lines = $null
        try { $lines = Invoke-LmLmstat $lmutil $srv } catch { $lines = $null }
        if ($null -eq $lines) { $failed++; continue }
        $ok++
        foreach ($r in (Select-LmOwnRows $lines $pollLocal $me $myHost)) { $rows.Add($r) }
    }
    $obs = Format-LmUtc $nowUtc
    $seen = New-Object 'Collections.Generic.HashSet[string]'
    $n = 0
    foreach ($r in ($rows | Sort-Object -Property @{ Expression = { $_.start } }, @{ Expression = { $_.feature } })) {
        $appId = Get-LmFeatureAppId $r.feature
        $su = $r.start.ToUniversalTime()
        if (-not $seen.Add($appId + '|' + (Format-LmUtc $su))) { continue }
        Write-LmRecord ([ordered]@{
            app_id = $appId; ts_utc = (Format-LmUtc $su); ts_end = $obs; ts_local_offset = (Format-LmOffset $su)
            ts_precision = 'minute'; observed_at = $obs; confidence = 0.8
            flags = [ordered]@{ license = $true; end_uncertain = $true }
        })
        $n++
    }
    Write-LmCursor ([ordered]@{ last_ts_utc = $obs })
    if ($ok -eq 0) { Add-LmReason 'R-TRANSPORT'; $script:Rc = 3 }
    elseif ($n -gt 0) { $script:Rc = 0 }
    else { $script:Rc = 1 }
    $script:St['n'] = $n
    $script:St['servers_ok'] = $ok
    $script:St['servers_failed'] = $failed
    $script:St['others_excluded'] = $script:NOther
}

$script:St = New-LmStatus 'pc.compute'
$script:Rc = 3
$swAll = [Diagnostics.Stopwatch]::StartNew()
try {
    Invoke-Main | Out-Null
} catch {
    $script:Rc = 3
    Add-LmReason 'R-TRANSPORT'
    $script:St['error'] = $_.Exception.GetType().Name
    $script:St['error_line'] = [int]$_.InvocationInfo.ScriptLineNumber
}
$script:St['rc'] = $script:Rc
$script:St['reasons'] = @($script:Reasons)
$script:St['elapsed_ms'] = [int]$swAll.Elapsed.TotalMilliseconds
Write-LmStatus $script:St
exit $script:Rc
