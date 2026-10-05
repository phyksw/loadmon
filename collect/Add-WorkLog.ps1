<#
.SYNOPSIS
  manual 수집기(CP §10, 계약 §2.17) — 키보드 밖 업무(오프라인 지시·보고·출장·장비 점검·현장) 한 건을 NDJSON 원시 레코드로 낸다.

.DESCRIPTION
  이전 판 Add-WorkLog.ps1 이식 — 이제 CSV 를 쓰지 않는다. 원시 레코드 한 줄(+ 마지막 줄 _cursor)을 stdout 으로 내면 연결자
  (화면 /api/worklog · 수집 연결자)가 정제 파이프(lm27_pipe.py --kind manual --src manual)로 넘긴다. 메모(Note)·대상(Entity)
  원문은 파이프 메모리에서만 정제된다(text_masked). 계정명은 넣지 않는다(이전 판의 user 열 폐지 — P §10.2).
    -Category  업무 범주(자리표시자 문구, 사람 이름·번호 금지 — 정제기 check_team_label)
    -Hours     투입 시간(0~24)
    -Date      로컬 날짜(기본 오늘) · -Start/-End  HH:mm(구간 투입 — 없으면 그날 00:00, ts_precision=date)
    -Kind      man_kind(work·offsite·instr·report·absence·exclude·attended·must_link·cannot_link·retract, 기본 work)
    -ProjectId · -RoleField · -RoleFunc  레지스트리 ID·어휘 코드(선택)
  rc: 0 기록 한 줄을 냈다 · 1 입력이 틀려 아무것도 내지 않았다(사유는 stderr 상태 줄 invalid 에 필드 이름만).

.PARAMETER TestNow
  시험 주입: '지금'(observed_at·기본 날짜)
#>
param(
    [string]$Category = '',
    [double]$Hours = -1,
    [string]$Entity = '',
    [string]$Note = '',
    [string]$Date = '',
    [string]$Start = '',
    [string]$End = '',
    [string]$Kind = 'work',
    [string]$ProjectId = '',
    [string]$RoleField = '',
    [string]$RoleFunc = '',
    [string]$Pc = '',
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

$ManKinds = @('work', 'offsite', 'instr', 'report', 'absence', 'exclude', 'attended', 'must_link', 'cannot_link', 'retract')
$HhmmRe = '^(?:[01]\d|2[0-3]):[0-5]\d$'
$RegIdRe = '^[A-Za-z][A-Za-z0-9_\-]{0,15}$'
$VocabRe = '^[0-9A-Za-z가-힣_]{1,20}$'

function Invoke-Main {
    Read-LmIn
    $script:St['in'] = $script:InState
    $nowUtc = Get-LmNow $TestNow
    $bad = New-Object 'Collections.Generic.List[string]'
    $cat = $Category.Trim()
    if (-not $cat -or $cat.Length -gt 20) { $bad.Add('category') }
    if ($Hours -lt 0 -or $Hours -gt 24 -or [double]::IsNaN($Hours)) { $bad.Add('hours') }
    $day = $nowUtc.ToLocalTime().Date
    if ($Date) {
        try { $day = [datetime]::ParseExact($Date.Trim(), 'yyyy-MM-dd', $script:Inv) } catch { $bad.Add('date') }
    }
    $st = $null; $en = $null
    if ($Start) { if ($Start.Trim() -match $HhmmRe) { $st = $Start.Trim() } else { $bad.Add('start') } }
    if ($End) { if ($End.Trim() -match $HhmmRe) { $en = $End.Trim() } else { $bad.Add('end') } }
    if (($null -ne $st) -xor ($null -ne $en)) { $bad.Add('start_end') }
    elseif ($null -ne $st -and [string]::CompareOrdinal($en, $st) -le 0) { $bad.Add('start_end') }
    $k = $Kind.Trim().ToLower()
    if ($ManKinds -notcontains $k) { $bad.Add('kind') }
    $pid0 = $null; $rf = $null; $rfn = $null
    if ($ProjectId) { if ($ProjectId.Trim() -match $RegIdRe) { $pid0 = $ProjectId.Trim() } else { $bad.Add('project_id') } }
    if ($RoleField) { if ($RoleField.Trim() -match $VocabRe) { $rf = $RoleField.Trim() } else { $bad.Add('role_field') } }
    if ($RoleFunc) { if ($RoleFunc.Trim() -match $VocabRe) { $rfn = $RoleFunc.Trim() } else { $bad.Add('role_func') } }
    if ($bad.Count -gt 0) {
        $script:St['invalid'] = @($bad)
        $script:Rc = 1
        return
    }
    # 그날(또는 시작 시각)의 로컬 오프셋
    $hm = '00:00'
    if ($null -ne $st) { $hm = $st }
    $localAt = [datetime]::SpecifyKind($day.Add([TimeSpan]::ParseExact($hm, 'hh\:mm', $script:Inv)), [DateTimeKind]::Local)
    $obs = Format-LmUtc $nowUtc
    Write-LmRecord ([ordered]@{
        category = $cat; hours = [double]$Hours; date = $day.ToString('yyyy-MM-dd', $script:Inv); start = $st; end = $en
        note = $Note; entity = $Entity; project_id = $pid0; role_field = $rf; role_func = $rfn
        man_kind = $k; ref_keys = @(); retract_of = $null
        ts_local_offset = (Format-LmOffset $localAt.ToUniversalTime()); observed_at = $obs; confidence = 1.0
    })
    Write-LmCursor ([ordered]@{ last_ts_utc = $obs })
    $script:St['n'] = 1
    $script:Rc = 0
}

$script:St = New-LmStatus 'manual'
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
