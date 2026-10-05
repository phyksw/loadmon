<#
.SYNOPSIS
  pc.events 수집기(CP §4, 계약 §2.17) — 사용자 권한 이벤트 로그에서 전원(L0)·세션(L1) 구간을 만들어 NDJSON 으로 낸다.

.DESCRIPTION
  읽는 곳(사용자 권한 채널만, 관리자 권한·정책 우회 없음):
    System            6005·6006·6008·1074·12·13·41·42·506·507·107·1·7001·7002(7001/7002 는 내 SID 만)
    Diagnostics-Performance/Operational  100·200(System 롤오버 보완 — 권한이 없을 수 있다)
    TerminalServices-LocalSessionManager/Operational  21·23·24·25(내 계정만 — VDI·클라우드PC RDP)
    Security          4800·4801(잠금·해제 — 읽히면 보너스. 못 읽으면 채널 상태 unauthorized 로 드러낸다 — 보너스 채널이라
                      사유 코드는 붙이지 않는다: System 채널을 못 읽을 때만 R-NOEVT)
  이벤트 ID → event_class·layer(계약 X-077): 6005·12·100 boot / 6006·13·1074·200 shutdown / 6008·41 crash /
    42·506 sleep / 1·107·507 wake / 7001·21·25 logon(원격 주소면 rdp_connect) / 7002·23 logoff / 24 rdp_disconnect /
    4800 lock · 4801 unlock. boot·shutdown·sleep·wake·crash = L0, 나머지 L1.
  구간화(CP §4.2): on 이 열고 off 가 닫는다. 켜짐 중의 부팅이 30분 넘게 뒤면 앞 구간은 그 부팅에서 끝(end_uncertain).
    지어낸 끝을 만들지 않는다 — 20시간 상한 절단 없음. 현재 부팅 세션(부팅 시각 이후 짝 없는 on)은 지금까지(live).
    L1 세션은 종료 이벤트 또는 다음 부팅(30분 넘게 뒤)에서 닫는다. crash(6008·41)는 다음 부팅 때 남는 표식이라 구간을 닫지 않는다.
  출력: stdout NDJSON — pc_session 원시 레코드(무텍스트: event_class·layer·session_state·시각·flags) + 마지막 줄 _cursor
    {last_ts_utc}. 이벤트 메시지·사용자명·컴퓨터 이름은 내지 않는다(P §10.2 금지 원시 필드). 디스크에 쓰지 않는다(L-09).
  rc(계약 §8.1): 0 새 구간 있음 · 1 이벤트 0건 · 3 System 채널을 읽지 못함(R-NOEVT) · 4 읽었지만 커서 뒤 새 구간 0.
    수확 예산 60초(계약 §5.3)를 넘기면 남은 채널을 건너뛰고 partial + budget_hit + R-BUDGET.
  채널 상태는 stderr 상태 줄 channels 에 ok·none·unauthorized·error 열거로만(X-317 — 예외 유형명은 channel_errors).

.PARAMETER Pc
  pc_id(연결자가 넘기는 공통 인자 — 레코드에는 정제 파이프가 붙인다)
.PARAMETER Since
  수집 시작 로컬 날짜(yyyy-MM-dd). 없으면 오늘 − collect.lookbackDays(_in.cfg, 기본 120일)
.PARAMETER Until
  수집 끝 로컬 날짜(포함)
.PARAMETER Days
  기간 일수(collect.lookbackDays 를 연결자가 -Days 로 넘길 때)
.PARAMETER EventsCsv
  시험 주입(계약 §11.3): 이벤트 로그 대신 읽을 CSV(t,kind[,src]) — t 는 로컬 'yyyy-MM-dd HH:mm', src 는 이벤트 ID.
  kind=channel 줄(t 비움, src='<채널>:<ok|none|unauthorized|error>[:<예외 유형명>]')은 채널 상태 주입이다
.PARAMETER Now
  시험 주입: '지금'(로컬 'yyyy-MM-dd HH:mm' 또는 UTC 'yyyy-MM-ddTHH:mm:ssZ')
.PARAMETER BootTime
  시험 주입: 현재 부팅 시각(LastBootUpTime 대체, 로컬)
.PARAMETER OutDir
  시험 주입: 주면 그 폴더에 상태 요약(event_status.json — 숫자·열거만)을 쓴다. 기본 빈 값 = 디스크 쓰기 없음
.PARAMETER TestNow
  시험 주입(ps 스크립트 공통 -TestNow): -Now 와 같다
#>
param(
    [string]$Pc = '',
    [string]$Since = '',
    [string]$Until = '',
    [int]$Days = 0,
    [string]$EventsCsv = '',
    [string]$Now = '',
    [string]$BootTime = '',
    [string]$OutDir = '',
    [string]$TestNow = ''
)

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
function Write-LmStatus($st) {
    try { [Console]::Out.Flush() } catch { }
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
                       cap_hit = $false; budget_hit = $false; n = 0; in = 'none'; elapsed_ms = 0 }
}

Set-LmOutput

$HarvestBudgetSec = 60          # 이벤트 수확 한 번 ≤ 60초(계약 §5.3 코드 상수)
$BootGroupMin = 30              # 같은 부팅의 12·6005·100 묶음 · 종료 유실 판정 간격(CP §4.2)
$LiveSlackMin = 10              # 부팅 시각 − 10분 이후에 열린 구간은 현재 부팅 세션(live)

# 이벤트 ID → @(event_class, on/off, layer, 공급자 낱말). 공급자 낱말이 있으면 ProviderName 에 그 낱말이 있어야 한다.
$EvMap = @{
    '6005' = @('boot', $true, 'L0', 'EventLog');           '6006' = @('shutdown', $false, 'L0', 'EventLog')
    '6008' = @('crash', $false, 'L0', 'EventLog');         '1074' = @('shutdown', $false, 'L0', 'User32')
    '12'   = @('boot', $true, 'L0', 'Kernel-General');     '13'   = @('shutdown', $false, 'L0', 'Kernel-General')
    '41'   = @('crash', $false, 'L0', 'Kernel-Power');     '42'   = @('sleep', $false, 'L0', 'Kernel-Power')
    '506'  = @('sleep', $false, 'L0', 'Kernel-Power');     '507'  = @('wake', $true, 'L0', 'Kernel-Power')
    '107'  = @('wake', $true, 'L0', 'Kernel-Power');       '1'    = @('wake', $true, 'L0', 'Power-Troubleshooter')
    '7001' = @('logon', $true, 'L1', 'Winlogon');          '7002' = @('logoff', $false, 'L1', 'Winlogon')
    '100'  = @('boot', $true, 'L0', 'Diagnostics-Performance'); '200' = @('shutdown', $false, 'L0', 'Diagnostics-Performance')
    '21'   = @('logon', $true, 'L1', 'LocalSessionManager');    '25'  = @('rdp_connect', $true, 'L1', 'LocalSessionManager')
    '23'   = @('logoff', $false, 'L1', 'LocalSessionManager');  '24'  = @('rdp_disconnect', $false, 'L1', 'LocalSessionManager')
    '4800' = @('lock', $false, 'L1', 'Security-Auditing'); '4801' = @('unlock', $true, 'L1', 'Security-Auditing')
}
$L0Classes = @('boot', 'shutdown', 'sleep', 'wake', 'crash')

$script:Events = New-Object 'Collections.Generic.List[psobject]'
$script:Channels = [ordered]@{}
$script:ChannelErrors = [ordered]@{}
$script:Seen = New-Object 'Collections.Generic.HashSet[string]'
$script:SkippedChannels = 0

function Add-LmEvent([datetime]$utc, [string]$cls, [bool]$on, [string]$id, [bool]$remote) {
    $layer = 'L1'
    if ($L0Classes -contains $cls) { $layer = 'L0' }
    $k = (Format-LmUtc $utc) + '|' + $id + '|' + $cls
    if (-not $script:Seen.Add($k)) { return }
    $script:Events.Add([pscustomobject]@{ t = $utc; cls = $cls; on = $on; id = $id; layer = $layer; remote = $remote })
}

function Get-LmEventStatus($err) {
    $fq = [string]$err.FullyQualifiedErrorId
    $ex = $err.Exception
    if ($fq -like 'NoMatchingEventsFound*') { return @('none', '') }
    if ($ex -is [UnauthorizedAccessException] -or $fq -match 'Unauthorized') { return @('unauthorized', '') }
    $tn = $ex.GetType().Name
    if ($tn -eq 'EventLogNotFoundException') { return @('none', '') }
    if ($tn -match 'Unauthorized') { return @('unauthorized', '') }
    return @('error', $tn)
}

# 한 채널을 읽는다 → 상태 열거. 이벤트 메시지는 읽지 않는다(XML 은 SID·사용자·주소 대조에만 메모리에서 쓰고 버린다).
function Read-LmChannel([string]$name, [hashtable]$filter, [scriptblock]$keep) {
    $got = 0
    try {
        $evs = @(Get-WinEvent -FilterHashtable $filter -ErrorAction Stop)
        foreach ($ev in $evs) {
            $id = [string]$ev.Id
            if (-not $EvMap.ContainsKey($id)) { continue }
            $m = $EvMap[$id]
            if ($m[3] -and ([string]$ev.ProviderName) -notlike ('*' + $m[3] + '*')) { continue }
            $res = & $keep $ev $m
            if ($null -eq $res -or -not $res.ok) { continue }
            Add-LmEvent $ev.TimeCreated.ToUniversalTime() $res.cls $m[1] $id $res.remote
            $got++
        }
        if ($evs.Count -gt 0) { $script:Channels[$name] = 'ok' } else { $script:Channels[$name] = 'none' }
    } catch {
        $st = Get-LmEventStatus $_
        $script:Channels[$name] = $st[0]
        if ($st[1]) { $script:ChannelErrors[$name] = $st[1] }
    }
    return $got
}

function Get-LmXmlData($ev, [string]$field) {
    try {
        $x = [xml]$ev.ToXml()
        $n = $x.Event.EventData.Data | Where-Object { $_.Name -eq $field } | Select-Object -First 1
        if ($n) { return [string]$n.'#text' }
    } catch { }
    return ''
}

function Read-LmLive([datetime]$fromUtc, [datetime]$toUtc, [System.Diagnostics.Stopwatch]$sw) {
    $from = $fromUtc.ToLocalTime()
    $to = $toUtc.ToLocalTime()
    $mySid = ''
    try { $mySid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value } catch { $mySid = '' }
    $myUser = ''
    try { $myUser = ([string]$env:USERNAME).ToLower() } catch { $myUser = '' }
    $keepAll = { param($ev, $m) return @{ ok = $true; cls = $m[0]; remote = $false } }
    $keepSys = {
        param($ev, $m)
        if ($ev.Id -eq 7001 -or $ev.Id -eq 7002) {
            # 로그온·로그오프는 이 PC 의 모든 세션이 남긴다 — 다른 사용자의 로그오프가 내 구간을 닫지 않게(이전 판 keep)
            $sid = Get-LmXmlData $ev 'UserSid'
            if ($mySid -and $sid -and $sid -ne $mySid) { return $null }
        }
        return @{ ok = $true; cls = $m[0]; remote = $false }
    }
    $keepTs = {
        param($ev, $m)
        $u = ''; $addr = ''
        try {
            $x = [xml]$ev.ToXml()
            $u = [string]$x.Event.UserData.EventXML.User
            $addr = [string]$x.Event.UserData.EventXML.Address
        } catch { }
        if ($u) {
            $un = ($u -split '\\')[-1].ToLower()
            if ($myUser -and $un -ne $myUser) { return $null }
        }
        $cls = $m[0]
        $remote = $false
        if (($ev.Id -eq 21 -or $ev.Id -eq 25) -and $addr -and $addr -ne 'LOCAL') { $cls = 'rdp_connect'; $remote = $true }
        elseif ($ev.Id -eq 25 -and $addr -eq 'LOCAL') { $cls = 'logon' }
        return @{ ok = $true; cls = $cls; remote = $remote }
    }
    $keepSec = {
        param($ev, $m)
        $sid = Get-LmXmlData $ev 'TargetUserSid'
        if ($mySid -and $sid -and $sid -ne $mySid) { return $null }
        return @{ ok = $true; cls = $m[0]; remote = $false }
    }
    $plan = @(
        @{ name = 'system'; filter = @{ LogName = 'System'; Id = @(6005, 6006, 6008, 1074, 12, 13, 41, 42, 506, 507, 107, 1, 7001, 7002);
                                        StartTime = $from; EndTime = $to }; keep = $keepSys },
        @{ name = 'diag_perf'; filter = @{ LogName = 'Microsoft-Windows-Diagnostics-Performance/Operational'; Id = @(100, 200);
                                           StartTime = $from; EndTime = $to }; keep = $keepAll },
        @{ name = 'ts_session'; filter = @{ LogName = 'Microsoft-Windows-TerminalServices-LocalSessionManager/Operational';
                                            Id = @(21, 23, 24, 25); StartTime = $from; EndTime = $to }; keep = $keepTs },
        @{ name = 'security_lock'; filter = @{ LogName = 'Security'; Id = @(4800, 4801); StartTime = $from; EndTime = $to };
           keep = $keepSec }
    )
    foreach ($p in $plan) {
        if ($sw.Elapsed.TotalSeconds -gt $HarvestBudgetSec) {
            # 예산 소진 — 남은 채널은 읽지 않는다(상태 열거에 넣지 않고 건수만: X-317 열거는 ok·none·unauthorized·error)
            $script:SkippedChannels++
            $script:BudgetHit = $true
            continue
        }
        [void](Read-LmChannel $p.name $p.filter $p.keep)
    }
}

function Read-LmCsv([string]$path, [datetime]$fromUtc, [datetime]$toUtc) {
    $script:Channels['synthetic'] = 'ok'
    foreach ($r in @(Import-Csv -LiteralPath $path)) {
        if (-not $r.kind) { continue }
        if (([string]$r.kind).Trim().ToLower() -eq 'channel') {
            # 채널 상태 주입 줄(t 비움, src='<채널>:<ok|none|unauthorized|error>[:<예외 유형명>]') — 권한·롤오버 갈래 시험용
            $parts = ([string]$r.src).Split(':')
            if ($parts.Count -ge 2 -and $parts[0] -match '^[a-z_]{2,24}$' -and @('ok', 'none', 'unauthorized', 'error') -contains $parts[1]) {
                $script:Channels[$parts[0]] = $parts[1]
                if ($parts.Count -ge 3 -and $parts[2] -match '^[A-Za-z]{1,64}$') { $script:ChannelErrors[$parts[0]] = $parts[2] }
            }
            continue
        }
        if (-not $r.t) { continue }
        $u = ConvertFrom-LmTime ([string]$r.t)
        if ($null -eq $u -or $u -lt $fromUtc -or $u -ge $toUtc) { continue }
        $k = ([string]$r.kind).Trim().ToLower()
        $on = ($k -eq 'on')
        $src = ''
        if ($r.PSObject.Properties['src']) { $src = ([string]$r.src).Trim() }
        if (-not $src) { if ($on) { $src = '6005' } else { $src = '6006' } }
        $cls = ''
        if ($src -eq 'boot') { $cls = 'boot'; $src = '6005' }
        elseif ($EvMap.ContainsKey($src)) { $cls = $EvMap[$src][0] }
        if (-not $cls) { if ($on) { $cls = 'boot' } else { $cls = 'shutdown' } }
        Add-LmEvent $u $cls $on $src ($cls -eq 'rdp_connect')
    }
}

function New-LmSpan($ev) {
    return [pscustomobject]@{ a = $ev.t; b = $null; cls = $ev.cls; layer = $ev.layer; unc = $false; conf = 1.0;
                              remote = [bool]$ev.remote; open = $true; live = $false }
}

# 이벤트 → 구간(L0 전원, L1 세션). 반환: 구간 목록(열린 채 끝난 것은 open=$true)
function Build-LmSpans($events) {
    $spans = New-Object 'Collections.Generic.List[psobject]'
    $sorted = @($events | Sort-Object -Property @{ Expression = { $_.t } }, @{ Expression = { [int]$_.on } }, @{ Expression = { $_.id } })
    $o0 = $null
    $o1 = $null
    foreach ($e in $sorted) {
        if ($e.layer -eq 'L0') {
            if ($e.on) {
                if ($null -eq $o0) { $o0 = New-LmSpan $e }
                elseif ($e.cls -eq 'boot' -and ($e.t - $o0.a).TotalMinutes -gt $BootGroupMin) {
                    $o0.b = $e.t; $o0.unc = $true; $o0.conf = 0.4; $o0.open = $false; $spans.Add($o0)
                    $o0 = New-LmSpan $e
                }
            } elseif ($e.cls -ne 'crash' -and $null -ne $o0) {
                if ($e.t -gt $o0.a) { $o0.b = $e.t; $o0.open = $false; $spans.Add($o0) }
                $o0 = $null
            }
            # 세션은 종료·다음 부팅을 넘어 이어지지 않는다
            if ($null -ne $o1) {
                if ($e.cls -eq 'shutdown' -and $e.t -gt $o1.a) {
                    $o1.b = $e.t; $o1.open = $false; $spans.Add($o1); $o1 = $null
                } elseif ($e.cls -eq 'boot' -and ($e.t - $o1.a).TotalMinutes -gt $BootGroupMin) {
                    $o1.b = $e.t; $o1.unc = $true; $o1.conf = 0.4; $o1.open = $false; $spans.Add($o1); $o1 = $null
                }
            }
        } else {
            if ($e.on) {
                if ($null -eq $o1) { $o1 = New-LmSpan $e }
            } elseif ($null -ne $o1) {
                if ($e.t -gt $o1.a) { $o1.b = $e.t; $o1.open = $false; $spans.Add($o1) }
                $o1 = $null
            }
        }
    }
    foreach ($o in @($o0, $o1)) { if ($null -ne $o) { $spans.Add($o) } }
    return ,$spans
}

function Invoke-Main {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $script:BudgetHit = $false
    Read-LmIn
    $script:St['in'] = $script:InState
    $nowArg = $Now
    if (-not $nowArg) { $nowArg = $TestNow }
    $nowUtc = Get-LmNow $nowArg
    $rg = Get-LmRange $Since $Until $Days $nowUtc
    $script:St['range'] = @($rg.From, $rg.To)
    $endUtc = $rg.UntilUtc
    if ($nowUtc -lt $endUtc) { $endUtc = $nowUtc }
    $curUtc = Get-LmCursorUtc
    $readFrom = $rg.SinceUtc
    if ($null -ne $curUtc -and $curUtc.AddMinutes(-$BootGroupMin) -gt $readFrom) { $readFrom = $curUtc.AddMinutes(-$BootGroupMin) }

    $bootUtc = $null
    if ($BootTime) { $bootUtc = ConvertFrom-LmTime $BootTime }
    elseif (-not $EventsCsv) {
        try { $bootUtc = (Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime.ToUniversalTime() } catch { $bootUtc = $null }
    }

    if ($EventsCsv) { Read-LmCsv $EventsCsv $readFrom $rg.UntilUtc }
    else { Read-LmLive $readFrom $rg.UntilUtc $sw }

    $events = @($script:Events)
    $spans = Build-LmSpans $events
    $fallback = $false
    if ($events.Count -eq 0 -and $null -ne $bootUtc -and $bootUtc -lt $endUtc) {
        # 최후 폴백: 이벤트가 하나도 없어도(권한·롤오버·Modern Standby) 현재 부팅 이후 구간만은 남긴다 — 추정(0.4)
        $a = $bootUtc
        if ($a -lt $rg.SinceUtc) { $a = $rg.SinceUtc }
        $spans.Add([pscustomobject]@{ a = $a; b = $null; cls = 'boot'; layer = 'L0'; unc = $false; conf = 0.4; remote = $false;
                                      open = $true; live = $false })
        $fallback = $true
    }
    # 열린 채 끝난 구간: 현재 부팅 세션이면 지금까지(live), 아니면 수확 시점까지 + end_uncertain(시간으로 세지 않게 신호만)
    foreach ($s in $spans) {
        if (-not $s.open) { continue }
        $s.b = $endUtc
        if ($null -ne $bootUtc -and $s.a -ge $bootUtc.AddMinutes(-$LiveSlackMin)) { $s.live = $true }
        else { $s.unc = $true; $s.conf = 0.4 }
    }
    $nBoot = @($events | Where-Object { $_.cls -eq 'boot' }).Count
    $nOff = @($events | Where-Object { $_.cls -eq 'sleep' -or $_.cls -eq 'shutdown' }).Count
    $rangeDays = [int][math]::Max(1, ($rg.UntilUtc - $rg.SinceUtc).TotalDays)
    $alwaysOn = ($nBoot -gt 0 -and $nOff -eq 0 -and -not $fallback -and $rangeDays -ge 2)

    $obs = Format-LmUtc $nowUtc
    $emit = @($spans | Where-Object { $_.b -gt $_.a -and ($null -eq $curUtc -or $_.a -ge $curUtc) } |
              Sort-Object -Property @{ Expression = { $_.a } }, @{ Expression = { $_.layer } })
    foreach ($s in $emit) {
        $state = 'active'
        if ($s.remote) { $state = 'remote' }
        Write-LmRecord ([ordered]@{
            event_class = $s.cls; session_state = $state; layer = $s.layer
            ts_utc = (Format-LmUtc $s.a); ts_end = (Format-LmUtc $s.b); ts_local_offset = (Format-LmOffset $s.a)
            ts_precision = 'minute'; observed_at = $obs; confidence = [double]$s.conf
            flags = [ordered]@{ end_uncertain = [bool]$s.unc; always_on = [bool]($alwaysOn -and $s.layer -eq 'L0'); remote = [bool]$s.remote }
        })
    }
    # 커서: 열린 채 끝난(현재 진행 중) 구간이 있으면 그 시작(다음 수확이 그 구간을 다시 읽어 끝을 늘린다), 없으면 마지막 끝.
    $openStarts = @($spans | Where-Object { $_.open } | ForEach-Object { $_.a } | Sort-Object)
    $newCur = $curUtc
    if ($openStarts.Count -gt 0) { $newCur = $openStarts[0] }
    elseif ($spans.Count -gt 0) { $newCur = (@($spans | ForEach-Object { $_.b } | Sort-Object))[-1] }
    if ($null -ne $curUtc -and $null -ne $newCur -and $newCur -lt $curUtc) { $newCur = $curUtc }
    $curVal = $null
    if ($null -ne $newCur) { $curVal = Format-LmUtc $newCur }
    Write-LmCursor ([ordered]@{ last_ts_utc = $curVal })

    $sys = 'ok'
    if ($script:Channels.Contains('system')) { $sys = [string]$script:Channels['system'] }
    if ($sys -eq 'unauthorized' -or $sys -eq 'error') {
        # 핵심 채널(System)을 읽지 못하면 막힌 경로 — 다른 채널 구간이 있어도 rc 3 + 사유(계약 §8.1). Security·Diag·TS 채널의
        # 권한 없음은 보너스 채널이라 사유 코드 없이 상태 열거로만 남긴다(확정 '불가' 근거가 되지 않게).
        Add-LmReason 'R-NOEVT'
        $script:Rc = 3
    } elseif ($emit.Count -gt 0) { $script:Rc = 0 }
    elseif ($events.Count -gt 0) { $script:Rc = 4 }
    else { $script:Rc = 1 }
    if ($script:BudgetHit) {
        Add-LmReason 'R-BUDGET'
        $script:St['partial'] = $true
        $script:St['budget_hit'] = $true
    }
    $script:St['n'] = $emit.Count
    $script:St['events'] = $events.Count
    $script:St['spans'] = [ordered]@{ L0 = @($emit | Where-Object { $_.layer -eq 'L0' }).Count; L1 = @($emit | Where-Object { $_.layer -eq 'L1' }).Count }
    $script:St['live'] = (@($emit | Where-Object { $_.live }).Count -gt 0)
    $script:St['end_uncertain'] = @($emit | Where-Object { $_.unc }).Count
    $script:St['always_on'] = [bool]$alwaysOn
    $script:St['fallback_boot'] = [bool]$fallback
    $script:St['channels'] = $script:Channels
    $script:St['channels_skipped'] = $script:SkippedChannels
    $script:St['channel_errors'] = $script:ChannelErrors
}

$script:St = New-LmStatus 'pc.events'
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
if ($OutDir) {
    try {
        [IO.File]::WriteAllText((Join-Path $OutDir 'event_status.json'), (ConvertTo-LmJson $script:St), (New-Object Text.UTF8Encoding($false)))
    } catch { Write-LmNote ('[events] OutDir 쓰기 실패: ' + $_.Exception.GetType().Name) }
}
Write-LmStatus $script:St
exit $script:Rc
