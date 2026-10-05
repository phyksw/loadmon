<#
.SYNOPSIS
  mail.com · cal.com — 클래식 Outlook COM 수집기(CM §5). 모든 COM 호출은 자식 프로세스 + 워치독 안에서 한다.

.DESCRIPTION
  계약 §2.17 · §3.5 · §3.10 · §7.3 · §8.1, CM §5 · §8 · §9 · §10 · §11.1, C §4.3. LM24 Get-OutlookData.ps1 을 옮겨 다시 설계했다
  (최상위 폴더만 읽던 결함 → 모든 메일 폴더 재귀 + EntryID 역할 태그, 로캘 'g' 날짜 필터 → DASL ISO UTC 리터럴,
  Stop-Job 대기 → 자식 PID 직접 종료, 수신자 열람 실패 시 'to' 오판정 → rcv 는 정제기가 정하고 B단 실패는 R-OMG).

  출력(디스크에 쓰지 않는다 — L-09):
    · stdout 첫 줄 {"_meta":{"my_addrs":[...]}} · 원시 후보 레코드 NDJSON(P §10.2 원시 이름) · 끝 줄 {"_cursor":{…}}.
      연결자가 kind 마다 정제 파이프 하나에 잇는다(-Only mail / -Only cal — COM 2회 붙기, 두 번째는 GetActiveObject 재사용).
      -Only 를 비우면 메일·일정을 한 번에 읽고 줄마다 "_kind" 를 붙인다(혼합 라우팅용, 커서는 {경로 ID: 값}).
    · stderr: 사람용 한 줄(숫자·사유만)과 마지막 줄들 {"_result":{…}}(경로마다 하나 — rc·사유 코드·건수·subfolder_ratio).
  입력: stdin 제어 줄 {"_in":{"cursor":…,"cfg":{…}}}(연결자가 쓰고 닫는다, 리디렉션이 아니면 기본값). 커서·설정·주소는
  명령줄로 받지 않는다(X-300). 쓰는 설정: mail.com.budgetSec · mail.com.watchdogSec · mail.com.protectedReadSec ·
  mail.com.capMail · mail.com.capCal · mail.com.readProtected(연결자가 auto 를 0/1 로 정해 넘긴다) · mail.includeArchiveStore ·
  collect.ownerAddress · probe.subfolderRatio(있으면 R-SUBFOLDER 판정).

  구조: 부모(이 스크립트)가 사전 점검(새 Outlook·프로필·COM 등록 — COM 호출 없음)을 하고, 같은 스크립트를 -Worker 로 자식
  PowerShell 에 띄운다. 자식은 COM 에 붙어 레코드·하트비트({"_hb"})·진행 커서({"_cur"})·결과({"_wres"})를 stdout 으로 낸다.
  부모는 레코드를 그대로 통과시키고, -WatchdogSec(기본 mail.com.watchdogSec=20) 동안 아무 줄도 없으면 자식을
  Stop-Process 로 끝낸다 — 붙는 중(attach)이면 R-DIALOG(Outlook 실행 중)·R-WIZARD, 읽는 중이면 R-TRANSPORT.
  Outlook 이 실행 중인데 붙지 못하면 New-Object 를 부르지 않는다(대화상자). 프로필 0·COM 미등록은 자식을 띄우지 않고 건너뛴다.

  읽기: 달 단위·최신 달부터, 보낸 편지함을 먼저(CM §10). A단(비보호 — GetTable 지정 열)은 항상, B단(보호 — 주소·수신자·헤더·
  본문)은 ReadProtected=1 일 때만, 항목마다 mail.com.protectedReadSec 안에서. B단이 거부·지연되면 R-OMG 로 남기고 A단 행은 낸다.
  상한(capMail·capCal) → cap_hit + R-CAP, 예산(budgetSec, 일정은 절반) → budget_hit + R-BUDGET — 둘 다 rc 0(셀 partial).
  지평선(가장 오래된 항목) 이전 달은 0건이 아니라 out_of_horizon + R-HORIZON.
  rc: 0 새 레코드 · 1 기간에 항목 없음 · 3 막힘(사유 필수: R-NEWOL R-NOPROF R-WIZARD R-DIALOG R-ELEV R-CLM R-COM-BUSY
  R-TRANSPORT) · 4 읽었지만 새것 0.

  커서(계약 §3.10): mail.com {"box":{inbox|sent|other:{last_ts_utc,last_msg_key}},"cov_months":{"YYYY-MM":{status,read_from,
  read_to}}} · cal.com {"last_start_utc","cov_months"}. last_msg_key 는 HMAC 이 필요해 null 로 낸다(파이프가 채운다).
  status ∈ done · partial · out_of_horizon. 이미 읽은 달은 건너뛰고, 최근 달(메일 3일·일정 14일)은 매번 다시 읽는다.

  시험 주입(계약 §11.3): LM_OUTLOOK_SELFTEST=N[,선택…] — Outlook 없이 달마다 가짜 메일 N건·일정 N/2건(+매주 반복 회의).
  선택: newol · noprof · wizard · dialog · elev · busyall · notrunning · noaddr · omg · slowb · archive · jetfail ·
  horizon=YYYY-MM · hang=attach|read · delay=<ms>. 이 모드에서는 레지스트리·프로세스·COM 을 전혀 건드리지 않는다.
  -TestNow 'yyyy-MM-dd HH:mm'(로컬).
  일정은 DASL(ISO UTC)과 Jet(현재 로캘 'g', 로컬 시각) 두 Restrict 결과의 합집합이다 — 반복 회차 전개를 Jet 으로 보장하고,
  로캘이 어긋나 Jet 이 0건이어도 DASL 이 단발 일정을 지킨다. 키 = GlobalAppointmentID·시작·끝.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File collect\Get-OutlookCom.ps1 -Only mail -Pc pc_0123456789abcdef -Since 2026-09-01 -Until 2026-09-30
#>
param(
    [string]$Only = '',
    [string]$Since = '',
    [string]$Until = '',
    [string]$Pc = '',
    [string]$ReadProtected = '',
    [string]$BudgetSec = '',
    [string]$WatchdogSec = '',
    [string]$TestNow = '',
    [switch]$Worker
)

# ── 제한 언어 모드: .NET 형을 쓰기 전에 먼저 본다(R-CLM, rc 3) ─────────────────────────────────────────────
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    $clmSrc = 'mail.com'
    if ($Only -eq 'cal') { $clmSrc = 'cal.com' }
    $clm = '{"_result":{"src":"' + $clmSrc + '","rc":3,"reasons":["R-CLM"],"items_total":0,"items_ok":0}}'
    try { [Console]::Error.WriteLine($clm) } catch { try { $host.UI.WriteErrorLine($clm) } catch { Write-Output $clm } }
    exit 3
}

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:Inv = [Globalization.CultureInfo]::InvariantCulture
$script:StdOut = [Console]::OpenStandardOutput()
$script:StdErr = [Console]::OpenStandardError()
$script:Clock = [Diagnostics.Stopwatch]::StartNew()

$PC_RX = '^pcx?_[0-9a-f]{16}$'
$PROPTAG = 'http://schemas.microsoft.com/mapi/proptag/'
$P_DELIVERY = $PROPTAG + '0x0E060040'     # PR_MESSAGE_DELIVERY_TIME(UTC)
$P_SUBMIT = $PROPTAG + '0x00390040'       # PR_CLIENT_SUBMIT_TIME(UTC)
$P_IMID = $PROPTAG + '0x1035001F'         # PR_INTERNET_MESSAGE_ID
$P_INREPLY = $PROPTAG + '0x1042001F'      # PR_IN_REPLY_TO_ID
$P_HASATT = $PROPTAG + '0x0E1B000B'       # PR_HASATTACH
$P_CONVID = $PROPTAG + '0x30130102'       # PR_CONVERSATION_ID
$P_SENDER_SMTP = $PROPTAG + '0x5D01001F'  # PR_SENDER_SMTP_ADDRESS(B단)
$P_HEADERS = $PROPTAG + '0x007D001F'      # PR_TRANSPORT_MESSAGE_HEADERS(B단)
$P_SMTP = $PROPTAG + '0x39FE001E'         # PR_SMTP_ADDRESS(수신자, B단)
$DT_START = 'urn:schemas:calendar:dtstart'
$DT_END = 'urn:schemas:calendar:dtend'
$RPC_E_CALL_REJECTED = -2147418111        # 0x8001010A
$REGDB_E_CLASSNOTREG = -2147221164        # 0x80040154
$MAIL_REFRESH_DAYS = 3
$CAL_REFRESH_DAYS = 14
$HB_EVERY = 25
$BODY_HEAD = 1000
$BODY_TAIL = 4000
$HEADERS_MAX = 16000
$RCPT_MAX = 100
$ONLINE_RX = '(?i)teams\.microsoft\.com/l/meetup-join|zoom\.us/j/|\.webex\.com/|Microsoft Teams'
$BUSY_OF = @{ 0 = 'free'; 1 = 'tentative'; 2 = 'busy'; 3 = 'oof'; 4 = 'elsewhere' }

# ── 출력 ──────────────────────────────────────────────────────────────────────────────────────────────
function Write-OutLine([string]$s) {
    $b = $script:Utf8.GetBytes($s + "`n")
    $script:StdOut.Write($b, 0, $b.Length)
    $script:StdOut.Flush()
}
function Write-ErrLine([string]$s) {
    $b = $script:Utf8.GetBytes($s + "`n")
    try { $script:StdErr.Write($b, 0, $b.Length); $script:StdErr.Flush() } catch { }
}
$script:JsonEval = [System.Text.RegularExpressions.MatchEvaluator] { param($m) '\u{0:x4}' -f [int][char]$m.Value }
function ConvertTo-JStr([string]$s) {
    if ($null -eq $s) { return 'null' }
    $t = $s.Replace('\', '\\').Replace('"', '\"')
    if ($t -match '[\x00-\x1f]') { $t = [regex]::Replace($t, '[\x00-\x1f]', $script:JsonEval) }
    return '"' + $t + '"'
}
function ConvertTo-J($v) {
    if ($null -eq $v) { return 'null' }
    if ($v -is [string]) { return (ConvertTo-JStr $v) }
    if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
    if ($v -is [int] -or $v -is [long] -or $v -is [int16] -or $v -is [byte] -or $v -is [uint32] -or $v -is [uint64]) {
        return ([long]$v).ToString($script:Inv)
    }
    if ($v -is [double] -or $v -is [single] -or $v -is [decimal]) {
        $d = [double]$v
        if ([double]::IsNaN($d) -or [double]::IsInfinity($d)) { return 'null' }
        $t = $d.ToString('R', $script:Inv)
        if ($t -notmatch '[.Ee]') { $t += '.0' }
        return $t
    }
    if ($v -is [datetime]) { return (ConvertTo-JStr (Format-Utc $v)) }
    if ($v -is [System.Collections.IDictionary]) {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($k in $v.Keys) { $parts.Add((ConvertTo-JStr ([string]$k)) + ':' + (ConvertTo-J $v[$k])) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v.GetType().FullName -eq 'System.Management.Automation.PSCustomObject') {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($p in $v.PSObject.Properties) { $parts.Add((ConvertTo-JStr $p.Name) + ':' + (ConvertTo-J $p.Value)) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v -is [System.Collections.IEnumerable]) {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($x in $v) { $parts.Add((ConvertTo-J $x)) }
        return '[' + ($parts -join ',') + ']'
    }
    return (ConvertTo-JStr ([string]$v))
}
function ConvertTo-Ascii([string]$s) {
    $sb = New-Object System.Text.StringBuilder ($s.Length + 16)
    foreach ($ch in $s.ToCharArray()) {
        if ([int]$ch -lt 128) { [void]$sb.Append($ch) } else { [void]$sb.Append(('\u{0:x4}' -f [int]$ch)) }
    }
    return $sb.ToString()
}

# ── 시각 ──────────────────────────────────────────────────────────────────────────────────────────────
function Format-Utc([datetime]$u) {
    return ([DateTime]::SpecifyKind($u, 'Utc')).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv)
}
function Format-Offset([datetime]$u) {
    $ts = [TimeZoneInfo]::Local.GetUtcOffset([DateTime]::SpecifyKind($u, 'Utc'))
    $m = [int]$ts.TotalMinutes
    $sign = '+'
    if ($m -lt 0) { $sign = '-'; $m = -$m }
    return ('{0}{1:00}:{2:00}' -f $sign, [math]::Floor($m / 60), ($m % 60))
}
function ConvertTo-UtcFromLocal([datetime]$local) {
    return [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($local, 'Unspecified'), [TimeZoneInfo]::Local)
}
function ConvertTo-LocalFromUtc([datetime]$u) {
    return [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::SpecifyKind($u, 'Utc'), [TimeZoneInfo]::Local)
}
function ConvertFrom-UtcText($s) {
    if (-not $s) { return $null }
    $d = [datetime]::MinValue
    if ([datetime]::TryParseExact([string]$s, "yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv, [Globalization.DateTimeStyles]::None, [ref]$d)) {
        return [DateTime]::SpecifyKind($d, 'Utc')
    }
    return $null
}
function Get-MinDate($a, $b) { if ($null -eq $a) { return $b }; if ($null -eq $b) { return $a }; if ($a -lt $b) { return $a }; return $b }
function Get-MaxDate($a, $b) { if ($null -eq $a) { return $b }; if ($null -eq $b) { return $a }; if ($a -gt $b) { return $a }; return $b }
function Get-Dasl([string]$prop, [datetime]$lo, [datetime]$hi, [bool]$plain) {
    # 로캘 무관 DASL — 날짜 리터럴은 UTC(ISO). 실물 Outlook 이 ISO 를 거부하면 'yyyy-MM-dd HH:mm'(역시 UTC)로 다시(CM §5.5)
    if ($plain) { $f = 'yyyy-MM-dd HH:mm' } else { $f = "yyyy-MM-dd'T'HH:mm:ss'Z'" }
    $a = ([DateTime]::SpecifyKind($lo, 'Utc')).ToString($f, $script:Inv)
    $b = ([DateTime]::SpecifyKind($hi, 'Utc')).ToString($f, $script:Inv)
    return ('@SQL="{0}" >= ''{1}'' AND "{0}" < ''{2}''' -f $prop, $a, $b)
}
function Get-CalDasl([datetime]$lo, [datetime]$hi, [bool]$plain) {
    if ($plain) { $f = 'yyyy-MM-dd HH:mm' } else { $f = "yyyy-MM-dd'T'HH:mm:ss'Z'" }
    $a = ([DateTime]::SpecifyKind($lo, 'Utc')).ToString($f, $script:Inv)
    $b = ([DateTime]::SpecifyKind($hi, 'Utc')).ToString($f, $script:Inv)
    return ('@SQL="{0}" < ''{1}'' AND "{2}" > ''{3}''' -f $DT_START, $b, $DT_END, $a)
}

# ── stdin 제어 줄 · 설정 ──────────────────────────────────────────────────────────────────────────────
function Read-InLine {
    try { if (-not [Console]::IsInputRedirected) { return $null } } catch { return $null }
    $s = [Console]::OpenStandardInput()
    $buf = New-Object System.Collections.Generic.List[byte]
    while ($buf.Count -lt 4194304) {
        $x = $s.ReadByte()
        if ($x -lt 0 -or $x -eq 10) { break }
        $buf.Add([byte]$x)
    }
    $t = $script:Utf8.GetString($buf.ToArray()).Trim([char]0xFEFF, [char]13, ' ')
    if (-not $t) { return $null }
    $o = $t | ConvertFrom-Json
    if ($o -and $o.PSObject.Properties['_in']) { return $o._in }
    return $null
}
function Get-Cfg($in, [string]$key, $default) {
    if ($null -eq $in -or $null -eq $in.PSObject.Properties['cfg'] -or $null -eq $in.cfg) { return $default }
    $p = $in.cfg.PSObject.Properties[$key]
    if ($null -eq $p -or $null -eq $p.Value) { return $default }
    return $p.Value
}
function Get-SrcCursor($in, [string]$src, [bool]$mixed) {
    if ($null -eq $in -or $null -eq $in.PSObject.Properties['cursor'] -or $null -eq $in.cursor) { return $null }
    if ($mixed) {
        $p = $in.cursor.PSObject.Properties[$src]
        if ($p) { return $p.Value }
        return $null
    }
    return $in.cursor
}
function Get-IntArg([string]$v, $fallback, [int]$min) {
    if (-not $v) { $v = [string]$fallback }
    $n = 0
    if (-not [int]::TryParse([string]$v, [ref]$n) -or $n -lt $min) { throw (New-Object System.ArgumentException('int')) }
    return $n
}
function Get-SelfTest {
    # LM_OUTLOOK_SELFTEST=N[,선택…] — 값이 있으면 무조건 시험 모드(실물 COM 을 건드리지 않는다)
    $raw = [string]$env:LM_OUTLOOK_SELFTEST
    if (-not $raw.Trim()) { return $null }
    $parts = @($raw.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $n = 0
    if ($parts.Count) { [void][int]::TryParse($parts[0], [ref]$n) }
    $opt = @{}
    foreach ($p in ($parts | Select-Object -Skip 1)) {
        $kv = $p.Split('=', 2)
        if ($kv.Count -eq 2) { $opt[$kv[0].ToLower()] = $kv[1] } else { $opt[$kv[0].ToLower()] = $true }
    }
    return @{ n = [math]::Max(0, $n); opt = $opt }
}
function New-Result([string]$src) {
    return [ordered]@{ src = $src; rc = 3; reasons = (New-Object System.Collections.Generic.List[string]); items_total = 0;
        items_ok = 0; new = 0; cap_hit = $false; budget_hit = $false; horizon_oldest = $null; subfolder_ratio = $null;
        recurrence_incomplete = 0; counts = [ordered]@{} }
}
function Add-Reason($res, [string]$code) { if (-not $res.reasons.Contains($code)) { $res.reasons.Add($code) } }
function ConvertTo-ResultJson($r) {
    $o = [ordered]@{}
    foreach ($k in $r.Keys) { $o[$k] = $r[$k] }
    $o['reasons'] = @($r.reasons | Sort-Object)
    return (ConvertTo-J $o)
}

# ═════════════════════════════════════ 자식(-Worker): COM 읽기 ═════════════════════════════════════
function Write-Hb([string]$phase, [int]$n) { Write-OutLine ('{"_hb":{"phase":"' + $phase + '","n":' + $n + '}}') }
function Write-Rec([System.Collections.IDictionary]$rec, [string]$kind) {
    if ($script:W.mixed) { $rec['_kind'] = $kind }
    Write-OutLine (ConvertTo-J $rec)
}
function Test-Budget([double]$limit) { return ($script:Clock.Elapsed.TotalSeconds -gt $limit) }
function Get-BodyWindow([string]$t) {
    if (-not $t) { return '' }
    $t = $t.Trim()
    if ($t.Length -le $BODY_HEAD + $BODY_TAIL) { return $t }
    return $t.Substring(0, $BODY_HEAD) + "`n" + $t.Substring($t.Length - $BODY_TAIL)
}
function Split-Cats([string]$s) {
    if (-not $s) { return @() }
    return @($s.Split([char[]]@(',', ';')) | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -First 10)
}

function Get-Months([datetime]$sinceLocal, [datetime]$untilLocalExcl) {
    $out = New-Object System.Collections.Generic.List[object]
    $m = New-Object DateTime ($sinceLocal.Year, $sinceLocal.Month, 1)
    while ($m -lt $untilLocalExcl) {
        $n = $m.AddMonths(1)
        $lo = $m; if ($lo -lt $sinceLocal) { $lo = $sinceLocal }
        $hi = $n; if ($hi -gt $untilLocalExcl) { $hi = $untilLocalExcl }
        $out.Add(@{ key = $m.ToString('yyyy-MM', $script:Inv); lo = (ConvertTo-UtcFromLocal $lo); hi = (ConvertTo-UtcFromLocal $hi);
                    first = ($lo -eq $sinceLocal) })
        $m = $n
    }
    $out.Reverse()
    return , $out
}
function Get-CovIn($cur) {
    $h = @{}
    if ($cur -and $cur.PSObject.Properties['cov_months'] -and $cur.cov_months) {
        foreach ($p in $cur.cov_months.PSObject.Properties) {
            $v = $p.Value
            if ($null -eq $v) { continue }
            $h[$p.Name] = @{ status = [string]$v.status; read_from = (ConvertFrom-UtcText $v.read_from); read_to = (ConvertFrom-UtcText $v.read_to) }
        }
    }
    return $h
}
function Get-ReadRange($m, $prior, [datetime]$refreshFrom, [double]$overlapDays) {
    # 이번에 읽을 [lo, hi) — 이미 읽은 범위([read_from, read_to))는 건너뛰고, 최근 구간은 다시 읽는다. 읽을 것이 없으면 $null
    if (-not $prior -or $prior.status -notin @('done', 'partial') -or -not $prior.read_from -or -not $prior.read_to) {
        return @{ lo = $m.lo; hi = $m.hi }
    }
    $a = $prior.read_from; $b = $prior.read_to
    $lowGap = $m.lo -lt $a
    $highGap = $b -lt $m.hi
    $refresh = $m.hi -gt $refreshFrom
    if (-not $lowGap -and -not $highGap -and -not $refresh) { return $null }
    if ($lowGap) { $lo = $m.lo }
    else {
        $lo = $null
        if ($highGap) { $lo = $b.AddDays(-$overlapDays) }
        if ($refresh) { $lo = Get-MinDate $lo $refreshFrom }
        if ($lo -lt $m.lo) { $lo = $m.lo }
    }
    if ($highGap -or $refresh) { $hi = $m.hi } else { $hi = $a.AddMinutes(1); if ($hi -gt $m.hi) { $hi = $m.hi } }
    if ($hi -le $lo) { return $null }
    return @{ lo = $lo; hi = $hi }
}
function Merge-Cov($prior, [datetime]$lo, [datetime]$hi, $m) {
    # 이번에 읽은 [lo, hi) 를 앞 범위와 합친다(붙어 있을 때만). 달 전체를 덮으면 done.
    $a = $lo; $b = $hi
    if ($prior -and $prior.read_from -and $prior.read_to -and $prior.status -in @('done', 'partial')) {
        if ($lo -le $prior.read_to -and $hi -ge $prior.read_from) {
            $a = Get-MinDate $lo $prior.read_from
            $b = Get-MaxDate $hi $prior.read_to
        }
    }
    $st = 'partial'
    if ($a -le $m.lo -and $b -ge $m.hi) { $st = 'done' }
    return @{ status = $st; read_from = $a; read_to = $b }
}
function ConvertTo-CovJson($cov) {
    $o = [ordered]@{}
    foreach ($k in ($cov.Keys | Sort-Object -Descending)) {
        $v = $cov[$k]
        $rf = $null; $rt = $null
        if ($v.read_from) { $rf = Format-Utc $v.read_from }
        if ($v.read_to) { $rt = Format-Utc $v.read_to }
        $o[$k] = [ordered]@{ status = $v.status; read_from = $rf; read_to = $rt }
    }
    return $o
}

# ── 시험 모델(LM_OUTLOOK_SELFTEST) — 실물 COM 과 같은 모양의 폴더·항목 ─────────────────────────────────
function New-StFolder([string]$id, [string]$name, [string]$store, [int]$type) {
    return @{ EntryID = $id; Name = $name; StoreID = $store; DefaultItemType = $type; Children = (New-Object System.Collections.Generic.List[object]);
              Items = (New-Object System.Collections.Generic.List[object]) }
}
function New-SelfModel($st, $w) {
    $n = [int]$st.opt_n
    $s1 = 'ST-STORE-1'
    $root = New-StFolder 'ST-ROOT-1' 'Top' $s1 0
    $f = @{}
    foreach ($spec in @(@('inbox', '받은 편지함', 0), @('sent', '보낸 편지함', 0), @('deleted', '지운 편지함', 0), @('junk', '정크 메일', 0),
                        @('drafts', '임시 보관함', 0), @('outbox', '보낼 편지함', 0), @('project', '과제A 자료', 0),
                        @('calendar', '일정', 1), @('contacts', '연락처', 2))) {
        $x = New-StFolder ('ST-F-' + $spec[0]) $spec[1] $s1 $spec[2]
        $f[$spec[0]] = $x
        $root.Children.Add($x)
    }
    $f['rules'] = New-StFolder 'ST-F-rules' '규칙폴더' $s1 0
    $f['inbox'].Children.Add($f['rules'])
    $stores = New-Object System.Collections.Generic.List[object]
    $stores.Add(@{ id = $s1; root = $root; archive = $false; defaults = @{ inbox = 'ST-F-inbox'; sent = 'ST-F-sent'; deleted = 'ST-F-deleted';
                   junk = 'ST-F-junk'; drafts = 'ST-F-drafts'; outbox = 'ST-F-outbox' } })
    if ($st.opt.archive) {
        $s2 = 'ST-STORE-2'
        $root2 = New-StFolder 'ST-ROOT-2' 'Archive' $s2 0
        $f['arch'] = New-StFolder 'ST-F-arch' '받은 편지함' $s2 0
        $f['archdel'] = New-StFolder 'ST-F-archdel' '지운 편지함' $s2 0
        $root2.Children.Add($f['arch']); $root2.Children.Add($f['archdel'])
        $stores.Add(@{ id = $s2; root = $root2; archive = $true; defaults = @{ deleted = 'ST-F-archdel' } })
    }
    $me = @{ addr = 'gildong.hong@corp.example'; name = '홍길동' }
    $peers = @(@{ addr = 'chulsoo.kim@corp.example'; name = '김철수' }, @{ addr = 'peer.b@corp.example'; name = '동료B' },
               @{ addr = 'peer.c@corp.example'; name = '동료C' })
    $cyc = @('inbox', 'inbox', 'inbox', 'rules', 'sent', 'sent', 'project', 'X')
    $junkCyc = @('deleted', 'junk', 'drafts', 'outbox')
    $horizon = $null
    if ($st.opt.horizon) { $horizon = [datetime]::ParseExact([string]$st.opt.horizon + '-01', 'yyyy-MM-dd', $script:Inv) }
    # 모델 기간 = 요청 기간의 앞 한 달 ~ 요청 끝(실물 사서함처럼 요청과 무관하게 항목이 있다)
    $m = (New-Object DateTime ($w.sinceLocal.Year, $w.sinceLocal.Month, 1)).AddMonths(-1)
    $cal = $f['calendar'].Items
    while ($m -lt $w.untilLocal) {
        $mEnd = $m.AddMonths(1)
        if ($horizon -and $m -lt $horizon) { $m = $mEnd; continue }
        $mk = $m.ToString('yyyyMM', $script:Inv)
        for ($i = 0; $i -lt $n; $i++) {
            $t = $mEnd.AddMinutes(-1 - $i * 97)
            if ($t -lt $m) { $t = $m.AddMinutes($i) }
            $key = $cyc[$i % 8]
            if ($key -eq 'X') { $key = $junkCyc[[math]::Floor($i / 8) % 4] }
            $isSent = ($key -eq 'sent')
            $cls = 'IPM.Note'
            if ($isSent -and ($i % 7) -eq 5) { $cls = 'IPM.Schedule.Meeting.Resp.Pos' }
            elseif (-not $isSent -and ($i % 11) -eq 10) { $cls = 'REPORT.IPM.Note.NDR' }
            $peer = $peers[$i % 3]
            $to = @($me); $cc = @()
            if ($isSent) { $to = @($peer) } elseif (($i % 4) -eq 3) { $to = @($peers[2]); $cc = @($me) }
            $sender = $peer; if ($isSent) { $sender = $me }
            $subj = ('selftest mail {0} [{1}]' -f $i, $key)
            if (($i % 3) -eq 0) { $subj = 'RE: ' + $subj }
            $hdr = 'Received: from mx.corp.example by mail.corp.example'
            if (-not $isSent -and ($i % 10) -eq 9) { $hdr = "List-Unsubscribe: <https://shop.example/u>`r`nPrecedence: bulk" }
            $att = @()
            if (($i % 6) -eq 1) { $att = @(('selftest_{0}.pptx' -f $i)) }
            $cat = ''
            if (($i % 7) -eq 2) { $cat = '개인' }
            $item = @{ EntryID = ('ST-{0}-{1}' -f $mk, $i); t = (ConvertTo-UtcFromLocal $t); Subject = $subj; MessageClass = $cls
                       Importance = $(if (($i % 5) -eq 4) { 2 } else { 1 }); Sensitivity = $(if (($i % 9) -eq 8) { 2 } else { 0 })
                       Categories = $cat; ConversationTopic = ($subj -replace '^RE: ', ''); imid = ('<st-{0}-{1}@selftest.example>' -f $mk, $i)
                       inreply = (($i % 3) -eq 0); hasatt = ($att.Count -gt 0); att = $att; convid = ('{0:X32}' -f ($i % 4))
                       sender = $sender; to = $to; cc = $cc; headers = $hdr; body = ('selftest body {0}' -f $i) }
            $f[$key].Items.Add($item)
        }
        if ($st.opt.archive) {
            for ($i = 0; $i -lt [math]::Max(1, [math]::Floor($n / 4)); $i++) {
                $t = $mEnd.AddMinutes(-30 - $i * 211); if ($t -lt $m) { $t = $m.AddMinutes($i) }
                $f['arch'].Items.Add(@{ EntryID = ('ST-A-{0}-{1}' -f $mk, $i); t = (ConvertTo-UtcFromLocal $t); Subject = ('selftest archive {0} [arch]' -f $i)
                    MessageClass = 'IPM.Note'; Importance = 1; Sensitivity = 0; Categories = ''; ConversationTopic = 'archive'
                    imid = ('<st-a-{0}-{1}@selftest.example>' -f $mk, $i); inreply = $false; hasatt = $false; att = @(); convid = 'A0'
                    sender = $peers[0]; to = @($me); cc = @(); headers = ''; body = 'archive' })
            }
        }
        # 일정: 단발 N/2건 + 매주 월요일 10:00 반복 회의(회차 전개, 같은 GlobalAppointmentID)
        $nc = [math]::Max(1, [math]::Floor($n / 2))
        $days = ($mEnd - $m).Days
        for ($i = 0; $i -lt $nc; $i++) {
            $s = $m.AddDays($i % $days).AddHours(9 + ($i % 8))
            $allDay = (($i % 7) -eq 6)
            if ($allDay) { $s = $m.AddDays($i % $days); $e = $s.AddDays(1) } else { $e = $s.AddHours(1) }
            $resp = 3; if (($i % 3) -eq 0) { $resp = 1 }
            $cal.Add(@{ s = (ConvertTo-UtcFromLocal $s); e = (ConvertTo-UtcFromLocal $e); Subject = ('selftest meeting {0}' -f $i)
                AllDayEvent = $allDay; BusyStatus = $(if ($allDay) { 3 } else { 2 }); Categories = ''; Sensitivity = $(if (($i % 9) -eq 8) { 2 } else { 0 })
                GlobalAppointmentID = ('{0:X8}{1}' -f $i, $mk); ResponseStatus = $resp; MeetingStatus = $(if (($i % 10) -eq 9) { 5 } else { 1 })
                Location = $(if (($i % 4) -eq 1) { 'Microsoft Teams 회의' } else { '회의실 2' }); IsRecurring = $false
                organizer = $(if ($resp -eq 1) { $me } else { $peers[0] }); attendees = @($me, $peers[1]); body = 'selftest agenda' })
        }
        $d = $m
        while ($d -lt $mEnd) {
            if ($d.DayOfWeek -eq [DayOfWeek]::Monday) {
                $s = $d.AddHours(10)
                $cal.Add(@{ s = (ConvertTo-UtcFromLocal $s); e = (ConvertTo-UtcFromLocal $s.AddMinutes(30)); Subject = 'selftest weekly'
                    AllDayEvent = $false; BusyStatus = 2; Categories = ''; Sensitivity = 0; GlobalAppointmentID = 'ST-SERIES-0001'
                    ResponseStatus = 1; MeetingStatus = 1; Location = '회의실 1'; IsRecurring = $true; organizer = $me
                    attendees = @($me, $peers[0], $peers[1]); body = 'weekly' })
            }
            $d = $d.AddDays(1)
        }
        $m = $mEnd
    }
    return @{ stores = $stores; folders = $f; me = $me }
}

# ── 공급자(시험 모델 · 실물 COM) ─────────────────────────────────────────────────────────────────────
function Get-NodeChildren($node) {
    if ($script:W.st) { return , $node.Children }
    $out = New-Object System.Collections.Generic.List[object]
    try { foreach ($c in $node.Folders) { $out.Add($c) } } catch { }
    return , $out
}
function Get-NodeType($node) { try { return [int]$node.DefaultItemType } catch { return -1 } }
function Get-MailFolders {
    # 저장소마다 루트(보이는 트리 — 숨김 폴더 없음)에서 메일 폴더를 재귀로 모으고 역할을 EntryID 로 정한다(이름 아님, CM §5.3)
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($store in $script:W.stores) {
        if ($store.archive -and -not $script:W.includeArchive) { continue }
        $def = $store.defaults
        $skip = @{}
        foreach ($k in @('deleted', 'junk', 'drafts', 'outbox', 'conflicts', 'syncissues', 'localfail', 'serverfail', 'rss')) {
            if ($def.ContainsKey($k) -and $def[$k]) { $skip[[string]$def[$k]] = $k }
        }
        $stack = New-Object System.Collections.Generic.Stack[object]
        foreach ($c in (Get-NodeChildren $store.root)) { $stack.Push(@{ node = $c; under = '' }) }
        while ($stack.Count) {
            $e = $stack.Pop()
            $node = $e.node
            $id = ''
            try { $id = [string]$node.EntryID } catch { continue }
            if ($skip.ContainsKey($id)) { $script:W.excluded++; continue }     # 지운·정크·임시 보관·보낼 편지함(하위 포함) 제외
            if ((Get-NodeType $node) -ne 0) { continue }                          # 메일 폴더만
            $under = $e.under
            $role = 'subfolder'; $box = 'inbox'
            if ($store.archive) { $role = 'archive' }
            elseif ($def.ContainsKey('inbox') -and $id -eq [string]$def['inbox']) { $role = 'inbox'; $under = 'inbox' }
            elseif ($def.ContainsKey('sent') -and $id -eq [string]$def['sent']) { $role = 'sent'; $box = 'sent'; $under = 'sent' }
            elseif ($under -eq 'sent') { $box = 'sent' }
            $cnt = -1
            try { $cnt = [int]$node.Items.Count } catch { $cnt = -1 }
            if ($cnt -ne 0) { $out.Add(@{ node = $node; role = $role; box = $box; store = $store.id; sent = ($box -eq 'sent') }) }
            else { $script:W.emptyFolders++ }
            foreach ($c in (Get-NodeChildren $node)) { $stack.Push(@{ node = $c; under = $under }) }
        }
    }
    return , $out
}
function Read-FolderRows($fd, [datetime]$lo, [datetime]$hi) {
    $prop = $P_DELIVERY; if ($fd.sent) { $prop = $P_SUBMIT }
    $rows = New-Object System.Collections.Generic.List[object]
    if ($script:W.st) {
        $flt = Get-Dasl $prop $lo $hi $false
        $lits = [regex]::Matches($flt, "'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)'")
        if ($lits.Count -ne 2) { return , $rows }          # 시험 모델은 ISO UTC 리터럴만 이해한다(로캘 의존 필터면 0건)
        $a = ConvertFrom-UtcText $lits[0].Groups[1].Value
        $b = ConvertFrom-UtcText $lits[1].Groups[1].Value
        foreach ($it in $fd.node.Items) {
            if ($it.t -ge $a -and $it.t -lt $b) {
                $rows.Add(@{ id = $it.EntryID; store = $fd.store; t = $it.t; subject = $it.Subject; cls = $it.MessageClass; imp = $it.Importance
                             sens = $it.Sensitivity; cats = $it.Categories; topic = $it.ConversationTopic; imid = $it.imid; inreply = $it.inreply
                             hasatt = $it.hasatt; convid = $it.convid; fd = $fd; st = $it })
            }
        }
        return , $rows
    }
    $tbl = $null
    foreach ($plain in @($false, $true)) {
        try { $tbl = $fd.node.GetTable((Get-Dasl $prop $lo $hi $plain), 0); break } catch { $tbl = $null }
    }
    if (-not $tbl) { $script:W.tableErrors++; return , $rows }
    $tbl.Columns.RemoveAll()
    $cols = @('EntryID', 'Subject', 'MessageClass', 'Importance', 'Sensitivity', 'Categories', 'ConversationTopic', $prop, $P_IMID, $P_INREPLY,
              $P_HASATT, $P_CONVID)
    $ok = @{}
    foreach ($c in $cols) { try { [void]$tbl.Columns.Add($c); $ok[$c] = $true } catch { } }
    $timeCol = $prop; $timeLocal = $false
    if (-not $ok[$prop]) {                                   # UTC proptag 열이 거부되면 로컬 시각 열로(UTC 환산 + 의심 표시)
        $alt = 'ReceivedTime'; if ($fd.sent) { $alt = 'SentOn' }
        try { [void]$tbl.Columns.Add($alt); $timeCol = $alt; $timeLocal = $true } catch { }
    }
    while (-not $tbl.EndOfTable) {
        $r = $tbl.GetNextRow()
        $t = $null
        try {
            if ($timeLocal) { $t = ConvertTo-UtcFromLocal ([datetime]$r.Item($timeCol)) }
            else { $t = [DateTime]::SpecifyKind([datetime]$r.Item($timeCol), 'Utc') }
        } catch { $t = $null }
        if (-not $t) { continue }
        $h = @{ id = ''; store = $fd.store; t = $t; subject = ''; cls = ''; imp = 1; sens = 0; cats = ''; topic = ''; imid = ''; inreply = $false
                hasatt = $false; convid = ''; fd = $fd; st = $null; utcSuspect = $timeLocal }
        try { $h.id = [string]$r.Item('EntryID') } catch { }
        try { $h.subject = [string]$r.Item('Subject') } catch { }
        try { $h.cls = [string]$r.Item('MessageClass') } catch { }
        try { $h.imp = [int]$r.Item('Importance') } catch { }
        try { $h.sens = [int]$r.Item('Sensitivity') } catch { }
        try { $h.cats = [string]$r.Item('Categories') } catch { }
        try { $h.topic = [string]$r.Item('ConversationTopic') } catch { }
        if ($ok[$P_IMID]) { try { $h.imid = [string]$r.Item($P_IMID) } catch { } }
        if ($ok[$P_INREPLY]) { try { $h.inreply = [bool]([string]$r.Item($P_INREPLY)) } catch { } }
        if ($ok[$P_HASATT]) { try { $h.hasatt = [bool]$r.Item($P_HASATT) } catch { } }
        if ($ok[$P_CONVID]) { try { $h.convid = [string]$r.BinaryToString($P_CONVID) } catch { } }
        $rows.Add($h)
    }
    return , $rows
}
function Open-MailItem($row) {
    if ($script:W.st) { return $row.st }
    return $script:W.ns.GetItemFromID($row.id, $row.store)
}
function Read-AttachNames($row) {
    $names = New-Object System.Collections.Generic.List[string]
    if (-not $row.hasatt) { return , $names }
    if ($script:W.st) { foreach ($a in $row.st.att) { $names.Add($a) }; return , $names }
    try {
        $it = Open-MailItem $row
        foreach ($a in $it.Attachments) { if ($names.Count -ge 10) { break }; try { if ($a.FileName) { $names.Add([string]$a.FileName) } } catch { } }
    } catch { }
    return , $names
}
function Read-Protected($row) {
    # B단(보호 열) — 발신 SMTP·이름·수신자·헤더·본문. 실패는 예외로 올린다(부르는 쪽이 R-OMG 로 센다)
    if ($script:W.st) {
        if ($script:W.st.opt.omg) { throw (New-Object System.UnauthorizedAccessException('omg')) }
        if ($script:W.st.opt.slowb) { Start-Sleep -Milliseconds ([int]($script:W.protSec * 1000) + 300) }
        $x = $row.st
        $to = @($x.to | ForEach-Object { [ordered]@{ addr = $_.addr; name = $_.name } })
        $cc = @($x.cc | ForEach-Object { [ordered]@{ addr = $_.addr; name = $_.name } })
        return @{ sender_addr = $x.sender.addr; sender_name = $x.sender.name; to = $to; cc = $cc; headers = $x.headers; body = $x.body }
    }
    $it = Open-MailItem $row
    $sa = ''
    try { $sa = [string]$it.PropertyAccessor.GetProperty($P_SENDER_SMTP) } catch { }
    if (-not $sa) {
        try { if ([string]$it.SenderEmailType -eq 'EX') { $sa = [string]$it.Sender.GetExchangeUser().PrimarySmtpAddress } else { $sa = [string]$it.SenderEmailAddress } } catch { }
    }
    $to = New-Object System.Collections.Generic.List[object]
    $cc = New-Object System.Collections.Generic.List[object]
    $k = 0
    foreach ($r in $it.Recipients) {
        if ($k -ge $RCPT_MAX) { break }
        $k++
        $addr = ''
        try { $addr = [string]$r.PropertyAccessor.GetProperty($P_SMTP) } catch { }
        if (-not $addr) { try { $addr = [string]$r.Address } catch { } }
        if ($addr -notmatch '@') { $addr = '' }
        $p = [ordered]@{ addr = $(if ($addr) { $addr.ToLower() } else { $null }); name = [string]$r.Name }
        if ([int]$r.Type -eq 2) { $cc.Add($p) } elseif ([int]$r.Type -eq 1) { $to.Add($p) }
    }
    $hd = ''
    try { $hd = [string]$it.PropertyAccessor.GetProperty($P_HEADERS) } catch { }
    $bd = ''
    try { $bd = [string]$it.Body } catch { }
    return @{ sender_addr = $(if ($sa) { $sa.ToLower() } else { $null }); sender_name = [string]$it.SenderName; to = $to.ToArray(); cc = $cc.ToArray()
              headers = $hd; body = $bd }
}

function Connect-Outlook {
    # 붙기(CM §5.2 — LM24 :567-601 이식). 실행 중인데 못 붙으면 대화상자(New-Object 금지). 반환 @{ok; reason}
    if ($script:W.st) {
        $o = $script:W.st.opt
        if ($o.hang -eq 'attach') { Start-Sleep -Seconds 3600 }
        if ($o.dialog) { return @{ ok = $false; reason = 'R-DIALOG' } }
        if ($o.elev) { return @{ ok = $false; reason = 'R-ELEV' } }
        if ($o.busyall) { return @{ ok = $false; reason = 'R-COM-BUSY' } }
        return @{ ok = $true }
    }
    $running = $false
    try { $running = [bool](Get-Process -Name outlook -ErrorAction SilentlyContinue) } catch { }
    $elevated = $false
    try { $elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } catch { }
    $ol = $null; $hr = 0
    for ($i = 1; $i -le 3 -and -not $ol; $i++) {
        try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
        catch {
            $e = $_.Exception
            while ($e.InnerException) { $e = $e.InnerException }
            $hr = $e.HResult
            $ol = $null
        }
        if (-not $ol -and $i -lt 3) { Start-Sleep -Seconds 2; Write-Hb 'attach' 0 }
    }
    if (-not $ol -and $running) {
        if ($hr -eq $RPC_E_CALL_REJECTED) { return @{ ok = $false; reason = 'R-COM-BUSY' } }
        if ($elevated) { return @{ ok = $false; reason = 'R-ELEV' } }
        return @{ ok = $false; reason = 'R-DIALOG' }        # 시작 마법사·프로필 선택·암호 창 — New-Object 를 부르지 않는다
    }
    if (-not $ol) {
        try { $ol = New-Object -ComObject Outlook.Application }
        catch {
            $e = $_.Exception
            while ($e.InnerException) { $e = $e.InnerException }
            if ($e.HResult -eq $REGDB_E_CLASSNOTREG) { return @{ ok = $false; reason = 'R-WIZARD' } }
            return @{ ok = $false; reason = 'R-TRANSPORT' }
        }
    }
    $script:W.ol = $ol
    $script:W.ns = $ol.GetNamespace('MAPI')
    try { $script:W.ns.Logon($null, $null, $false, $false) } catch { }
    return @{ ok = $true }
}
function Get-ComStores {
    $out = New-Object System.Collections.Generic.List[object]
    $ns = $script:W.ns
    $defStoreId = ''
    try { $defStoreId = [string]$ns.DefaultStore.StoreID } catch { }
    foreach ($s in $ns.Stores) {
        $isDef = $false; $isArch = $false
        try { $isDef = ([string]$s.StoreID -eq $defStoreId) } catch { }
        try { $isArch = ([int]$s.ExchangeStoreType -eq 3) } catch { }       # olExchangeArchiveMailbox
        if (-not $isDef -and -not $isArch) { continue }
        $def = @{}
        foreach ($pair in @(@('inbox', 6), @('sent', 5), @('deleted', 3), @('junk', 23), @('drafts', 16), @('outbox', 4), @('conflicts', 19),
                            @('syncissues', 20), @('localfail', 21), @('serverfail', 22), @('rss', 25))) {
            try { $def[$pair[0]] = [string]$s.GetDefaultFolder($pair[1]).EntryID } catch { }
        }
        $root = $null
        try { $root = $s.GetRootFolder() } catch { continue }
        $out.Add(@{ id = [string]$s.StoreID; root = $root; archive = $isArch; defaults = $def })
    }
    return , $out
}
function Get-WorkerAddrs {
    $me = New-Object System.Collections.Generic.List[string]
    if ($script:W.st) {
        if (-not $script:W.st.opt.noaddr) { $me.Add($script:W.model.me.addr) }
    } else {
        try { foreach ($a in $script:W.ns.Accounts) { try { if ($a.SmtpAddress) { $me.Add(([string]$a.SmtpAddress).ToLower()) } } catch { } } } catch { }
        if ($script:W.readProt) {
            try {
                $xu = $script:W.ns.CurrentUser.AddressEntry.GetExchangeUser()
                if ($xu -and $xu.PrimarySmtpAddress) { $me.Add(([string]$xu.PrimarySmtpAddress).ToLower()) }
            } catch { }
        }
    }
    if ($script:W.owner) { $me.Add($script:W.owner) }
    return @($me | Where-Object { $_ -and $_ -match '@' -and $_.Length -ge 3 } | Select-Object -Unique)
}
function Get-MailHorizon($folders) {
    # 가장 오래된 메일(받은·보낸 편지함) — 캐시 동기화 기간 밖 판정용
    $min = $null
    foreach ($fd in $folders) {
        if ($fd.role -notin @('inbox', 'sent')) { continue }
        if ($script:W.st) {
            foreach ($it in $fd.node.Items) { $min = Get-MinDate $min $it.t }
            continue
        }
        try {
            $items = $fd.node.Items
            $field = '[ReceivedTime]'; if ($fd.sent) { $field = '[SentOn]' }
            $items.Sort($field, $false)
            $first = $items.GetFirst()
            if ($first) {
                $loc = $first.ReceivedTime; if ($fd.sent) { $loc = $first.SentOn }
                $min = Get-MinDate $min (ConvertTo-UtcFromLocal ([datetime]$loc))
            }
        } catch { }
    }
    return $min
}

function Invoke-MailKind {
    $w = $script:W
    $res = New-Result 'mail.com'
    $w.results['mail.com'] = $res
    if ($w.my.Count -eq 0) { Add-Reason $res 'R-NOADDR' }
    $cur = Get-SrcCursor $w.in 'mail.com' $w.mixed
    $covIn = Get-CovIn $cur
    $box = [ordered]@{}
    foreach ($b in @('inbox', 'sent', 'other')) {
        $last = $null
        if ($cur -and $cur.PSObject.Properties['box'] -and $cur.box -and $cur.box.PSObject.Properties[$b] -and $cur.box.$b) { $last = ConvertFrom-UtcText $cur.box.$b.last_ts_utc }
        $box[$b] = $last
    }
    $covOut = @{}
    foreach ($k in $covIn.Keys) { $covOut[$k] = $covIn[$k] }
    $folders = Get-MailFolders
    $horizon = Get-MailHorizon $folders
    if ($horizon) { $res.horizon_oldest = (ConvertTo-LocalFromUtc $horizon).ToString('yyyy-MM-dd', $script:Inv) }
    $refreshFrom = $w.nowUtc.AddDays(-$MAIL_REFRESH_DAYS)
    $emitted = 0; $nNew = 0; $seen = 0; $nSub = 0; $nSkipCls = 0; $nResp = 0; $nAtt = 0; $bFail = 0; $bCons = 0; $bOn = $w.readProt
    $stop = $null; $monthsRead = 0; $monthsSkipped = 0; $hb = 0
    foreach ($m in $w.months) {
        $prior = $covIn[$m.key]
        if ($horizon -and $m.hi -le $horizon) {
            $covOut[$m.key] = @{ status = 'out_of_horizon'; read_from = $null; read_to = $null }
            Add-Reason $res 'R-HORIZON'
            continue
        }
        $rr = Get-ReadRange $m $prior $refreshFrom 1
        if (-not $rr) { $monthsSkipped++; continue }
        if (Test-Budget $w.mailBudget) { $stop = 'budget'; break }
        $sentRows = New-Object System.Collections.Generic.List[object]
        $otherRows = New-Object System.Collections.Generic.List[object]
        foreach ($fd in $folders) {
            $rows = Read-FolderRows $fd $rr.lo $rr.hi
            foreach ($r in $rows) { if ($fd.sent) { $sentRows.Add($r) } else { $otherRows.Add($r) } }
            $hb++; Write-Hb 'read' $emitted
        }
        $ordered = @(@($sentRows | Sort-Object { $_.t } -Descending) + @($otherRows | Sort-Object { $_.t } -Descending))
        $oldestOther = $null; $inOther = $false
        foreach ($r in $ordered) {
            if ($null -eq $r) { continue }
            if (-not $r.fd.sent) { $inOther = $true }
            if ($emitted -ge $w.capMail) { $stop = 'cap'; break }
            if (Test-Budget $w.mailBudget) { $stop = 'budget'; break }
            if ($w.st -and $w.st.opt.delay) { Start-Sleep -Milliseconds ([int]$w.st.opt.delay) }
            $seen++
            $cls = [string]$r.cls
            if (-not (($cls -match '^IPM\.Note' -and $cls -notmatch '^IPM\.Note\.Rules') -or $cls -match '^IPM\.Schedule\.Meeting\.')) { $nSkipCls++; continue }
            $rec = [ordered]@{}
            if ($r.imid) { $rec['internet_message_id'] = [string]$r.imid }
            if ($r.convid) { $rec['conversation_id'] = [string]$r.convid }
            $rec['conversation_topic'] = [string]$r.topic
            $rec['box'] = $r.fd.box
            $rec['folder_role'] = $r.fd.role
            if ($bOn) {
                $t0 = $script:Clock.Elapsed.TotalSeconds
                $bp = $null
                try { $bp = Read-Protected $r; $bCons = 0 } catch { $bp = $null; $bFail++; $bCons++; Add-Reason $res 'R-OMG' }
                if (($script:Clock.Elapsed.TotalSeconds - $t0) -gt $w.protSec) { $bOn = $false; Add-Reason $res 'R-OMG'; $res.counts['omg_slow'] = $true }
                if ($bCons -ge 3) { $bOn = $false }
                if ($bp) {
                    if ($bp.sender_addr) { $rec['sender_addr'] = $bp.sender_addr }
                    if ($bp.sender_name) { $rec['sender_name'] = $bp.sender_name }
                    $rec['to'] = @($bp.to)
                    $rec['cc'] = @($bp.cc)
                    if ($bp.headers) { $h = [string]$bp.headers; if ($h.Length -gt $HEADERS_MAX) { $h = $h.Substring(0, $HEADERS_MAX) }; $rec['headers_text'] = $h }
                    $bw = Get-BodyWindow ([string]$bp.body)
                    if ($bw) { $rec['body_text'] = $bw }
                }
            }
            $rec['subject'] = [string]$r.subject
            if ($r.hasatt) {
                $names = Read-AttachNames $r
                if ($names.Count) { $rec['attach_names'] = @($names); $nAtt++ }
            }
            $rec['has_attach'] = [bool]$r.hasatt
            $rec['sensitivity'] = [int]$r.sens
            $rec['categories'] = @(Split-Cats ([string]$r.cats))
            $imp = [int]$r.imp; if ($imp -lt 0 -or $imp -gt 2) { $imp = 1 }
            $rec['importance'] = $imp
            $rec['in_reply_to'] = [bool]$r.inreply
            $rec['ts_utc'] = Format-Utc $r.t
            $rec['ts_local_offset'] = Format-Offset $r.t
            $rec['ts_precision'] = 'minute'
            $rec['observed_at'] = $w.nowIso
            $rec['confidence'] = 1.0
            $fl = [ordered]@{}
            if ($r.fd.sent -and $cls -match '^IPM\.Schedule\.Meeting\.Resp\.') { $fl['meeting_response'] = $true; $nResp++ }
            if ($r.utcSuspect) { $fl['utc_suspect'] = $true }
            if ($fl.Count) { $rec['flags'] = $fl }
            Write-Rec $rec 'mail'
            $emitted++
            if ($r.fd.role -eq 'subfolder') { $nSub++ }
            $isNew = -not ($prior -and $prior.status -in @('done', 'partial') -and $prior.read_from -and $prior.read_to -and $r.t -ge $prior.read_from -and $r.t -lt $prior.read_to)
            if ($isNew) { $nNew++ }
            $bk = [string]$r.fd.box
            if (-not $box.Contains($bk)) { $bk = 'other' }
            $box[$bk] = Get-MaxDate $box[$bk] $r.t
            if ($inOther) { $oldestOther = Get-MinDate $oldestOther $r.t }
            if (($emitted % $HB_EVERY) -eq 0) { Write-Hb 'read' $emitted }
            if ($w.st -and $w.st.opt.hang -eq 'read' -and $monthsRead -ge 1) { Start-Sleep -Seconds 3600 }
        }
        if ($stop) {
            if ($inOther -and $oldestOther) { $covOut[$m.key] = Merge-Cov $prior $oldestOther $rr.hi $m; $covOut[$m.key].status = 'partial' }
            Write-MailCursor $box $covOut
            break
        }
        $covOut[$m.key] = Merge-Cov $prior $rr.lo $rr.hi $m
        $monthsRead++
        Write-MailCursor $box $covOut
    }
    if (-not $stop) { Write-MailCursor $box $covOut }
    $res.items_total = $seen
    $res.items_ok = $emitted
    $res.new = $nNew
    if ($stop -eq 'cap') { $res.cap_hit = $true; Add-Reason $res 'R-CAP' }
    if ($stop -eq 'budget') { $res.budget_hit = $true; Add-Reason $res 'R-BUDGET' }
    if ($emitted -gt 0) { $res.subfolder_ratio = [math]::Round($nSub / $emitted, 4) }
    if ($null -ne $w.subRatio -and $null -ne $res.subfolder_ratio -and $res.subfolder_ratio -ge [double]$w.subRatio) { Add-Reason $res 'R-SUBFOLDER' }
    $res.counts['months_read'] = $monthsRead
    $res.counts['months_skipped'] = $monthsSkipped
    $res.counts['folders'] = $folders.Count
    $res.counts['excluded_folders'] = $w.excluded
    $res.counts['empty_folders'] = $w.emptyFolders
    $res.counts['skipped_class'] = $nSkipCls
    $res.counts['meeting_response'] = $nResp
    $res.counts['with_attach_names'] = $nAtt
    $res.counts['protected_fail'] = $bFail
    $res.counts['protected_read'] = [bool]$w.readProt
    $res.counts['table_errors'] = $w.tableErrors
    if ($nNew -gt 0 -or $stop) { $res.rc = 0 }
    elseif ($emitted -gt 0 -or $monthsSkipped -gt 0) { $res.rc = 4 }
    else { $res.rc = 1 }
}
function Write-MailCursor($box, $covOut) {
    $b = [ordered]@{}
    foreach ($k in $box.Keys) {
        $v = $null; if ($box[$k]) { $v = Format-Utc $box[$k] }
        $b[$k] = [ordered]@{ last_ts_utc = $v; last_msg_key = $null }
    }
    $c = [ordered]@{ box = $b; cov_months = (ConvertTo-CovJson $covOut) }
    Write-OutLine ('{"_cur":{"src":"mail.com","cursor":' + (ConvertTo-J $c) + '}}')
}

function Invoke-CalKind {
    $w = $script:W
    $res = New-Result 'cal.com'
    $w.results['cal.com'] = $res
    $cur = Get-SrcCursor $w.in 'cal.com' $w.mixed
    $covIn = Get-CovIn $cur
    $last = $null
    if ($cur -and $cur.PSObject.Properties['last_start_utc']) { $last = ConvertFrom-UtcText $cur.last_start_utc }
    $covOut = @{}
    foreach ($k in $covIn.Keys) { $covOut[$k] = $covIn[$k] }
    $refreshFrom = $w.nowUtc.AddDays(-$CAL_REFRESH_DAYS)
    $emitted = 0; $nNew = 0; $seen = 0; $stop = $null; $monthsRead = 0; $monthsSkipped = 0; $nCancel = 0; $nRec = 0; $bOn = $w.readProt; $bFail = 0
    foreach ($m in $w.months) {
        $prior = $covIn[$m.key]
        $rr = Get-ReadRange $m $prior $refreshFrom 1
        if (-not $rr) { $monthsSkipped++; continue }
        if (Test-Budget $w.calBudget) { $stop = 'budget'; break }
        $entries = Get-CalEntries $rr.lo $rr.hi
        $lastRead = $null
        foreach ($en in $entries) {
            if ($emitted -ge $w.capCal) { $stop = 'cap'; break }
            if (Test-Budget $w.calBudget) { $stop = 'budget'; break }
            if ($w.st -and $w.st.opt.delay) { Start-Sleep -Milliseconds ([int]$w.st.opt.delay) }
            if (-not ($en.s -ge $rr.lo -or $m.first)) { continue }      # 앞 달에서 시작한 회의는 그 달이 낸다(경계 중복 방지)
            $rec = Convert-CalItem $en.it ([ref]$bOn) ([ref]$bFail) $res
            if ($null -eq $rec) { continue }
            $s = $rec['_s']; $rec.Remove('_s')
            $seen++
            if ($rec['meeting_status'] -in @(5, 7)) { $nCancel++ }
            if ($rec['is_recurring']) { $nRec++ }
            Write-Rec $rec 'cal'
            $emitted++
            $isNew = -not ($prior -and $prior.status -in @('done', 'partial') -and $prior.read_from -and $prior.read_to -and $s -ge $prior.read_from -and $s -lt $prior.read_to)
            if ($isNew) { $nNew++ }
            if ($s -le $w.nowUtc) { $last = Get-MaxDate $last $s }
            $lastRead = $s
            if (($emitted % $HB_EVERY) -eq 0) { Write-Hb 'read' $emitted }
        }
        Write-Hb 'read' $emitted
        if ($stop) {
            if ($lastRead) { $covOut[$m.key] = Merge-Cov $prior $rr.lo $lastRead $m; $covOut[$m.key].status = 'partial' }
            Write-CalCursor $last $covOut
            break
        }
        $covOut[$m.key] = Merge-Cov $prior $rr.lo $rr.hi $m
        $monthsRead++
        Write-CalCursor $last $covOut
    }
    if (-not $stop) { Write-CalCursor $last $covOut }
    $res.items_total = $seen
    $res.items_ok = $emitted
    $res.new = $nNew
    if ($stop -eq 'cap') { $res.cap_hit = $true; Add-Reason $res 'R-CAP' }
    if ($stop -eq 'budget') { $res.budget_hit = $true; Add-Reason $res 'R-BUDGET' }
    $res.counts['months_read'] = $monthsRead
    $res.counts['months_skipped'] = $monthsSkipped
    $res.counts['cancelled'] = $nCancel
    $res.counts['recurring_occurrences'] = $nRec
    $res.counts['protected_fail'] = $bFail
    if ($nNew -gt 0 -or $stop) { $res.rc = 0 }
    elseif ($emitted -gt 0 -or $monthsSkipped -gt 0) { $res.rc = 4 }
    else { $res.rc = 1 }
}
function Get-CalJet([datetime]$lo, [datetime]$hi) {
    # Jet 필터(로컬 시각, 현재 로캘의 짧은 날짜·시각 'g') — Outlook 의 회차 전개(IncludeRecurrences)는 이 꼴에서 확실하다.
    # 로캘이 어긋나면 0건일 수 있으므로 DASL(ISO UTC) 결과와 합집합으로만 쓴다(CM §5.5 · LM24 'g' 결함 보완).
    $cc = [Globalization.CultureInfo]::CurrentCulture
    $a = (ConvertTo-LocalFromUtc $lo).ToString('g', $cc)
    $b = (ConvertTo-LocalFromUtc $hi).ToString('g', $cc)
    return ("[Start] < '{0}' AND [End] > '{1}'" -f $b, $a)
}
function Get-StCalItems([string]$mode, [datetime]$lo, [datetime]$hi) {
    # 시험 모델의 Restrict 흉내 — DASL 은 ISO UTC 리터럴만 이해하고 반복 회차를 전개하지 않는다(실물의 비관적 가정),
    # Jet 은 현재 로캘 'g' 문자열(로컬)을 이해하고 회차를 전개한다(선택 jetfail = 로캘 불일치로 0건).
    $out = New-Object System.Collections.Generic.List[object]
    $w = $script:W
    if ($mode -eq 'dasl') {
        $lits = [regex]::Matches((Get-CalDasl $lo $hi $false), "'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)'")
        if ($lits.Count -ne 2) { return , $out }
        $b = ConvertFrom-UtcText $lits[0].Groups[1].Value; $a = ConvertFrom-UtcText $lits[1].Groups[1].Value
        foreach ($it in $w.model.folders['calendar'].Items) { if (-not $it.IsRecurring -and $it.s -lt $b -and $it.e -gt $a) { $out.Add($it) } }
        return , $out
    }
    if ($w.st.opt.jetfail) { return , $out }
    $lits = [regex]::Matches((Get-CalJet $lo $hi), "'([^']+)'")
    if ($lits.Count -ne 2) { return , $out }
    $cc = [Globalization.CultureInfo]::CurrentCulture
    $b = ConvertTo-UtcFromLocal ([datetime]::Parse($lits[0].Groups[1].Value, $cc))
    $a = ConvertTo-UtcFromLocal ([datetime]::Parse($lits[1].Groups[1].Value, $cc))
    foreach ($it in $w.model.folders['calendar'].Items) { if ($it.s -lt $b -and $it.e -gt $a) { $out.Add($it) } }
    return , $out
}
function Get-CalEntries([datetime]$lo, [datetime]$hi) {
    # 그 범위와 겹치는 일정(회차 포함) — DASL 과 Jet 결과의 합집합, 시작 오름차순. 키 = GlobalAppointmentID·시작·끝
    $w = $script:W
    $seen = @{}
    $list = New-Object System.Collections.Generic.List[object]
    $guard = [int]$w.capCal * 3 + 100                                  # 깨진 반복(끝 없는 회차) 가드
    foreach ($mode in @('dasl', 'jet')) {
        if ($w.st) {
            foreach ($x in (Get-StCalItems $mode $lo $hi)) {
                $key = '{0}|{1}|{2}' -f $x.GlobalAppointmentID, $x.s.Ticks, $x.e.Ticks
                if (-not $seen.ContainsKey($key)) { $seen[$key] = 1; $list.Add(@{ s = $x.s; e = $x.e; it = $x }) }
            }
            continue
        }
        try {
            $citems = $w.ns.GetDefaultFolder(9).Items
            $citems.IncludeRecurrences = $true
            $citems.Sort('[Start]')                                       # 회차 전개는 오름차순 정렬이 먼저(COM 규칙)
            $sel = $null
            if ($mode -eq 'dasl') {
                foreach ($plain in @($false, $true)) { try { $sel = $citems.Restrict((Get-CalDasl $lo $hi $plain)); break } catch { $sel = $null } }
            } else {
                try { $sel = $citems.Restrict((Get-CalJet $lo $hi)) } catch { $sel = $null }
            }
            if ($null -eq $sel) { $w.tableErrors++; continue }
            $it = $sel.GetFirst()
            $n = 0
            while ($null -ne $it) {
                $n++
                if ($n -gt $guard) { break }
                $s = $null; $e = $null; $gaid = ''
                try {
                    $s = [DateTime]::SpecifyKind([datetime]$it.StartUTC, 'Utc'); $e = [DateTime]::SpecifyKind([datetime]$it.EndUTC, 'Utc')
                    $gaid = [string]$it.GlobalAppointmentID
                } catch { $s = $null }
                if ($null -ne $s) {
                    if ($s -ge $hi) { break }
                    $tag = ''; if (-not $gaid) { try { $tag = [string]$it.Subject } catch { } }
                    $key = '{0}|{1}|{2}|{3}' -f $gaid, $s.Ticks, $e.Ticks, $tag.GetHashCode()
                    if (-not $seen.ContainsKey($key)) { $seen[$key] = 1; $list.Add(@{ s = $s; e = $e; it = $it }) }
                }
                if (($n % $HB_EVERY) -eq 0) { Write-Hb 'read' $n }
                $it = $sel.GetNext()
            }
        } catch { $w.tableErrors++ }
    }
    return , @($list | Sort-Object { $_.s })
}
function Convert-CalItem($it, [ref]$bOn, [ref]$bFail, $res) {
    $w = $script:W
    if ($w.st) {
        $s = $it.s; $e = $it.e
        $h = @{ Subject = $it.Subject; AllDayEvent = $it.AllDayEvent; BusyStatus = $it.BusyStatus; Categories = $it.Categories
                Sensitivity = $it.Sensitivity; GlobalAppointmentID = $it.GlobalAppointmentID; ResponseStatus = $it.ResponseStatus
                MeetingStatus = $it.MeetingStatus; Location = $it.Location; IsRecurring = $it.IsRecurring }
    } else {
        try {
            $s = [DateTime]::SpecifyKind([datetime]$it.StartUTC, 'Utc'); $e = [DateTime]::SpecifyKind([datetime]$it.EndUTC, 'Utc')
            $h = @{ Subject = [string]$it.Subject; AllDayEvent = [bool]$it.AllDayEvent; BusyStatus = [int]$it.BusyStatus; Categories = [string]$it.Categories
                    Sensitivity = [int]$it.Sensitivity; GlobalAppointmentID = [string]$it.GlobalAppointmentID; ResponseStatus = [int]$it.ResponseStatus
                    MeetingStatus = [int]$it.MeetingStatus; Location = [string]$it.Location; IsRecurring = [bool]$it.IsRecurring }
        } catch { return $null }
    }
    if ($e -lt $s) { $e = $s }
    $rec = [ordered]@{}
    $rec['_s'] = $s
    if ($h.GlobalAppointmentID) { $rec['global_appointment_id'] = [string]$h.GlobalAppointmentID }
    $rec['start_utc'] = Format-Utc $s
    $rec['end_utc'] = Format-Utc $e
    $rec['subject'] = [string]$h.Subject
    $online = ([string]$h.Location -match $ONLINE_RX)
    if ($bOn.Value) {
        $t0 = $script:Clock.Elapsed.TotalSeconds
        try {
            if ($w.st) {
                if ($w.st.opt.omg) { throw (New-Object System.UnauthorizedAccessException('omg')) }
                $org = [ordered]@{ addr = $it.organizer.addr; name = $it.organizer.name }
                $att = @($it.attendees | ForEach-Object { [ordered]@{ addr = $_.addr; name = $_.name } })
                $body = [string]$it.body
            } else {
                $org = $null
                $att = New-Object System.Collections.Generic.List[object]
                $k = 0
                foreach ($r in $it.Recipients) {
                    if ($k -ge $RCPT_MAX) { break }
                    $k++
                    $addr = ''
                    try { $addr = [string]$r.PropertyAccessor.GetProperty($P_SMTP) } catch { }
                    if (-not $addr) { try { $addr = [string]$r.Address } catch { } }
                    if ($addr -notmatch '@') { $addr = '' }
                    $p = [ordered]@{ addr = $(if ($addr) { $addr.ToLower() } else { $null }); name = [string]$r.Name }
                    if ([int]$r.Type -eq 0) { $org = $p } else { $att.Add($p) }          # olOrganizer = 0
                }
                if (-not $org) { try { $org = [ordered]@{ addr = $null; name = [string]$it.Organizer } } catch { } }
                $att = $att.ToArray()
                $body = ''
                try { $body = [string]$it.Body } catch { }
            }
            if ($org) { $rec['organizer'] = $org }
            $rec['attendees'] = @($att)
            if ($body) {
                $bt = $body.Trim(); if ($bt.Length -gt $BODY_HEAD) { $bt = $bt.Substring(0, $BODY_HEAD) }
                $rec['body_text'] = $bt
                if ($body -match $ONLINE_RX) { $online = $true }
            }
        } catch { $bFail.Value++; Add-Reason $res 'R-OMG'; if ($bFail.Value -ge 3) { $bOn.Value = $false } }
        if (($script:Clock.Elapsed.TotalSeconds - $t0) -gt $w.protSec) { $bOn.Value = $false; Add-Reason $res 'R-OMG' }
    }
    $busy = 'busy'
    if ($BUSY_OF.ContainsKey([int]$h.BusyStatus)) { $busy = $BUSY_OF[[int]$h.BusyStatus] }
    $rec['busy_status'] = $busy
    $resp = [int]$h.ResponseStatus; if ($resp -lt 0 -or $resp -gt 5) { $resp = 0 }
    $rec['response_status'] = $resp
    $ms = [int]$h.MeetingStatus; if ($ms -lt 0 -or $ms -gt 7) { $ms = 0 }
    $rec['meeting_status'] = $ms
    if ($h.Location) { $rec['location'] = [string]$h.Location }
    $rec['is_recurring'] = [bool]$h.IsRecurring
    $rec['all_day'] = [bool]$h.AllDayEvent
    $rec['online'] = [bool]$online
    $rec['sensitivity'] = [int]$h.Sensitivity
    $rec['categories'] = @(Split-Cats ([string]$h.Categories))
    $rec['ts_local_offset'] = Format-Offset $s
    $rec['ts_precision'] = $(if ($h.AllDayEvent) { 'date' } else { 'minute' })
    $rec['observed_at'] = $w.nowIso
    $rec['confidence'] = 1.0
    if ($resp -eq 1) { $rec['flags'] = [ordered]@{ organizer_me = $true } }
    return $rec
}
function Write-CalCursor($last, $covOut) {
    $v = $null; if ($last) { $v = Format-Utc $last }
    $c = [ordered]@{ last_start_utc = $v; cov_months = (ConvertTo-CovJson $covOut) }
    Write-OutLine ('{"_cur":{"src":"cal.com","cursor":' + (ConvertTo-J $c) + '}}')
}

function Invoke-Worker($a) {
    $script:W = @{ in = $a.in; mixed = $a.mixed; st = $a.st; readProt = ($a.readProt -eq 1); protSec = $a.protSec; owner = $a.owner
                   capMail = $a.capMail; capCal = $a.capCal; includeArchive = $a.includeArchive; subRatio = $a.subRatio
                   nowUtc = $a.nowUtc; nowIso = (Format-Utc $a.nowUtc); sinceLocal = $a.sinceLocal; untilLocal = $a.untilLocal
                   months = (Get-Months $a.sinceLocal $a.untilLocal); results = [ordered]@{}; excluded = 0; emptyFolders = 0; tableErrors = 0
                   ol = $null; ns = $null; model = $null; stores = $null; my = @() }
    if ($a.st) { $script:W.st = @{ opt = $a.st.opt; opt_n = $a.st.n } }
    $kinds = $a.kinds
    # 예산: 일정은 절반까지, 메일은 전체 예산 안에서(혼합이면 일정 다음 남은 시간)
    $script:W.calBudget = [double]$a.budget / 2
    $script:W.mailBudget = [double]$a.budget
    Write-Hb 'attach' 0
    try {
        $att = Connect-Outlook
        if (-not $att.ok) {
            foreach ($k in $kinds) {
                $src = $(if ($k -eq 'mail') { 'mail.com' } else { 'cal.com' })
                $r = New-Result $src; Add-Reason $r $att.reason; $r.counts['attach'] = 'failed'; $r.rc = 3
                Write-OutLine ('{"_wres":' + (ConvertTo-ResultJson $r) + '}')
            }
            return 3
        }
        if ($script:W.st) {
            $script:W.model = New-SelfModel $script:W.st $script:W
            $script:W.stores = $script:W.model.stores
        } else {
            $script:W.stores = Get-ComStores
        }
        $script:W.my = @(Get-WorkerAddrs)
        Write-OutLine ('{"_meta":{"my_addrs":' + (ConvertTo-J ([object[]]$script:W.my)) + '}}')
        Write-Hb 'read' 0
        foreach ($k in $kinds) {
            if ($k -eq 'cal') { Invoke-CalKind } else { Invoke-MailKind }
        }
        foreach ($k in $script:W.results.Keys) {
            Write-OutLine ('{"_wres":' + (ConvertTo-ResultJson $script:W.results[$k]) + '}')
        }
        return 0
    } finally {
        if ($script:W.ns) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($script:W.ns) } catch { } }
        if ($script:W.ol) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($script:W.ol) } catch { } }
    }
}

# ═════════════════════════════════════ 부모: 사전 점검 · 워치독 ═════════════════════════════════════
function Get-Precheck($st) {
    # COM 을 부르지 않는 점검(레지스트리·프로세스). 새 Outlook 전용·프로필 0·COM 미등록이면 자식을 띄우지 않는다.
    $p = @{ fatal = $null; running = $true }
    if ($st) {
        if ($st.opt.newol) { $p.fatal = 'R-NEWOL' } elseif ($st.opt.noprof) { $p.fatal = 'R-NOPROF' } elseif ($st.opt.wizard) { $p.fatal = 'R-WIZARD' }
        $p.running = -not $st.opt.notrunning
        return $p
    }
    $running = $false
    try { $running = [bool](Get-Process -Name outlook -ErrorAction SilentlyContinue) } catch { }
    $p.running = $running
    $newOl = $false
    try {
        foreach ($rp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
            $pref = Get-ItemProperty -LiteralPath $rp -ErrorAction SilentlyContinue
            if ($pref -and $pref.PSObject.Properties['UseNewOutlook'] -and [int]$pref.UseNewOutlook -eq 1) { $newOl = $true }
        }
    } catch { }
    try { if (Get-Process -Name olk -ErrorAction SilentlyContinue) { $newOl = $true } } catch { }
    if ($running) { return $p }                                      # 떠 있으면 거기에 붙어 본다(실패 판정은 자식이)
    if ($newOl) { $p.fatal = 'R-NEWOL'; return $p }
    $profVers = New-Object System.Collections.Generic.List[int]
    $legacy = $false
    foreach ($v in @(16, 15)) {
        try { if (Get-ChildItem -LiteralPath ('HKCU:\Software\Microsoft\Office\{0}.0\Outlook\Profiles' -f $v) -ErrorAction SilentlyContinue | Select-Object -First 1) { $profVers.Add($v) } } catch { }
    }
    try { if (Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles' -ErrorAction SilentlyContinue | Select-Object -First 1) { $legacy = $true } } catch { }
    if ($profVers.Count -eq 0 -and -not $legacy) { $p.fatal = 'R-NOPROF'; return $p }
    $curVer = ''
    try { $curVer = [string](Get-ItemProperty -LiteralPath 'Registry::HKEY_CLASSES_ROOT\Outlook.Application\CurVer' -ErrorAction Stop).'(default)' } catch { $curVer = '' }
    if (-not $curVer) { $p.fatal = 'R-WIZARD'; return $p }             # COM 미등록 — New-Object 가 마법사·오류로 멈춘다
    $m = [regex]::Match($curVer, '(\d+)$')
    if ($m.Success) {
        $rv = [int]$m.Groups[1].Value
        if ($rv -ge 15 -and $profVers.Count -and -not $profVers.Contains($rv)) { $p.fatal = 'R-WIZARD' }   # 등록된 판에 프로필 없음(구판 MSI 병존)
    }
    return $p
}

function Invoke-Parent($a) {
    $srcs = @($a.kinds | ForEach-Object { if ($_ -eq 'mail') { 'mail.com' } else { 'cal.com' } })
    $results = [ordered]@{}
    $pre = Get-Precheck $a.st
    if ($pre.fatal) {
        foreach ($s in $srcs) { $r = New-Result $s; Add-Reason $r $pre.fatal; $r.counts['attach'] = 'skipped'; $r.rc = 3; $results[$s] = $r }
        Write-ErrLine ('[outlook-com] 건너뜀({0}) — 이 PC 에서는 Outlook COM 을 쓸 수 없습니다. 다른 경로가 빈칸을 채웁니다' -f $pre.fatal)
        return @{ rc = 3; results = $results; cursors = @{} }
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    $onlyArg = $(if ($a.mixed) { 'both' } else { $a.kinds[0] })
    $argv = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Worker -Only {1} -Since {2} -Until {3} -ReadProtected {4} -BudgetSec {5} -TestNow "{6}"' -f
             $PSCommandPath, $onlyArg, $a.sinceDay, $a.untilDay, $a.readProt, $a.budget, $a.nowLocalText)
    $psi.Arguments = $argv
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $script:Utf8
    $psi.StandardErrorEncoding = $script:Utf8
    $psi.CreateNoWindow = $true
    $p = [Diagnostics.Process]::Start($psi)
    $inJson = 'null'
    if ($a.in) { $inJson = ConvertTo-J $a.in }
    $p.StandardInput.WriteLine((ConvertTo-Ascii ('{"_in":' + $inJson + '}')))
    $p.StandardInput.Close()
    $errTask = $p.StandardError.ReadToEndAsync()
    $task = $p.StandardOutput.ReadLineAsync()
    $last = $script:Clock.Elapsed.TotalSeconds
    $hard = [double]$a.budget + [double]$a.watchdog + 30
    $phase = 'attach'; $killed = $null
    $cursors = [ordered]@{}; $nRec = @{ 'mail.com' = 0; 'cal.com' = 0 }
    while ($true) {
        if ($task.Wait(200)) {
            $line = $task.Result
            if ($null -eq $line) { break }
            $last = $script:Clock.Elapsed.TotalSeconds
            if ($line.StartsWith('{"_hb"')) {
                try { $phase = [string](($line | ConvertFrom-Json)._hb.phase) } catch { }
            } elseif ($line.StartsWith('{"_cur"')) {
                try { $o = ($line | ConvertFrom-Json)._cur; $cursors[[string]$o.src] = $o.cursor } catch { }
            } elseif ($line.StartsWith('{"_wres"')) {
                try { $o = ($line | ConvertFrom-Json)._wres; $results[[string]$o.src] = $o } catch { }
            } elseif ($line) {
                Write-OutLine $line
                if (-not $line.StartsWith('{"_')) {
                    $s = $srcs[0]
                    if ($a.mixed) { if ($line.Contains('"_kind":"cal"')) { $s = 'cal.com' } else { $s = 'mail.com' } }
                    $nRec[$s]++
                }
            }
            $task = $p.StandardOutput.ReadLineAsync()
        } else {
            $now = $script:Clock.Elapsed.TotalSeconds
            if (($now - $last) -gt $a.watchdog) { $killed = 'watchdog' }
            elseif ($now -gt $hard) { $killed = 'hard' }
            if ($killed) {
                try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch { }
                break
            }
        }
    }
    [void]$p.WaitForExit(5000)
    try { if ($errTask.Wait(2000)) { foreach ($ln in ($errTask.Result -split "`r?`n")) { if ($ln) { Write-ErrLine $ln } } } } catch { }
    $rc = 0
    foreach ($s in $srcs) {
        if (-not $results.Contains($s)) {
            # 자식이 결과 없이 끝났다(워치독·예외) — 붙는 중이면 대화상자·마법사, 읽는 중이면 수송 실패
            $r = New-Result $s
            $why = 'R-TRANSPORT'
            if ($phase -eq 'attach') { if ($pre.running) { $why = 'R-DIALOG' } else { $why = 'R-WIZARD' } }
            Add-Reason $r $why
            $r.items_ok = $nRec[$s]
            $r.counts['watchdog'] = [bool]($killed)
            $r.counts['phase'] = $phase
            $r.rc = 3
            $results[$s] = $r
            Write-ErrLine ('[outlook-com] {0}: 응답 없음({1}) — 자식을 끝냈습니다. 다음 실행에서 다시 시도합니다' -f $s, $phase)
        }
    }
    return @{ rc = $rc; results = $results; cursors = $cursors }
}

# ═════════════════════════════════════ 진입 ═════════════════════════════════════
$code = 3
$kindsOut = @('mail.com', 'cal.com')
try {
    if ($args.Count) { throw (New-Object System.ArgumentException('unknown-argument')) }
    $onlyN = $Only
    if ($Worker -and $Only -eq 'both') { $onlyN = '' }
    if ($onlyN -notin @('', 'mail', 'cal')) { throw (New-Object System.ArgumentException('only')) }
    if ($Pc -and $Pc -notmatch $PC_RX) { throw (New-Object System.ArgumentException('pc')) }
    $kinds = @('cal', 'mail')
    if ($onlyN) { $kinds = @($onlyN) }
    $kindsOut = @($kinds | ForEach-Object { if ($_ -eq 'mail') { 'mail.com' } else { 'cal.com' } })
    $in = Read-InLine
    $st = Get-SelfTest
    $nowLocal = Get-Date
    if ($TestNow) { $nowLocal = [datetime]::ParseExact($TestNow, 'yyyy-MM-dd HH:mm', $script:Inv) }
    $untilDay = $Until; if (-not $untilDay) { $untilDay = $nowLocal.ToString('yyyy-MM-dd', $script:Inv) }
    $sinceDay = $Since; if (-not $sinceDay) { $sinceDay = [datetime]::ParseExact($untilDay, 'yyyy-MM-dd', $script:Inv).AddDays(-89).ToString('yyyy-MM-dd', $script:Inv) }
    $sinceLocal = [datetime]::ParseExact($sinceDay, 'yyyy-MM-dd', $script:Inv)
    $untilLocal = [datetime]::ParseExact($untilDay, 'yyyy-MM-dd', $script:Inv).AddDays(1)
    if ($untilLocal -le $sinceLocal) { throw (New-Object System.ArgumentException('range')) }
    $rpRaw = $ReadProtected
    if ($rpRaw -eq '') { $rpRaw = [string](Get-Cfg $in 'mail.com.readProtected' '0') }
    $readProt = 0; if ($rpRaw -eq '1') { $readProt = 1 }                # auto 는 연결자가 탐침으로 정한다 — 못 받았으면 안전하게 0
    $sub = Get-Cfg $in 'probe.subfolderRatio' $null
    $a = @{
        in = $in; st = $st; kinds = $kinds; mixed = ($kinds.Count -gt 1); readProt = $readProt
        budget = (Get-IntArg $BudgetSec (Get-Cfg $in 'mail.com.budgetSec' 360) 1)
        watchdog = (Get-IntArg $WatchdogSec (Get-Cfg $in 'mail.com.watchdogSec' 20) 1)
        protSec = [double](Get-Cfg $in 'mail.com.protectedReadSec' 2)
        capMail = [int](Get-Cfg $in 'mail.com.capMail' 20000); capCal = [int](Get-Cfg $in 'mail.com.capCal' 8000)
        includeArchive = [bool](Get-Cfg $in 'mail.includeArchiveStore' $false)
        owner = ([string](Get-Cfg $in 'collect.ownerAddress' '')).Trim().ToLower()
        subRatio = $sub
        sinceDay = $sinceDay; untilDay = $untilDay; sinceLocal = $sinceLocal; untilLocal = $untilLocal
        nowLocalText = $nowLocal.ToString('yyyy-MM-dd HH:mm', $script:Inv); nowUtc = (ConvertTo-UtcFromLocal $nowLocal)
    }
    if ($Worker) {
        $code = Invoke-Worker $a
        exit $code
    }
    $out = Invoke-Parent $a
    # 진행 커서(자식이 달마다 낸 마지막 값)를 끝 줄로 — 파이프가 기록 성공 뒤에만 저장한다(계약 §7.3)
    if ($out.cursors.Count) {
        if ($a.mixed) { Write-OutLine ('{"_cursor":' + (ConvertTo-J $out.cursors) + '}') }
        else { foreach ($k in $out.cursors.Keys) { Write-OutLine ('{"_cursor":' + (ConvertTo-J $out.cursors[$k]) + '}') } }
    }
    $rcs = New-Object System.Collections.Generic.List[int]
    foreach ($k in $out.results.Keys) {
        $r = $out.results[$k]
        if ($r -is [System.Collections.IDictionary]) { $rcs.Add([int]$r.rc); Write-ErrLine ('{"_result":' + (ConvertTo-ResultJson $r) + '}') }
        else { $rcs.Add([int]$r.rc); Write-ErrLine ('{"_result":' + (ConvertTo-J $r) + '}') }
    }
    if ($rcs.Contains(3)) { $code = 3 } elseif ($rcs.Contains(0)) { $code = 0 } elseif ($rcs.Contains(4)) { $code = 4 } else { $code = 1 }
} catch {
    $why = $_.Exception.GetType().Name
    foreach ($s in $kindsOut) {
        $r = New-Result $s; Add-Reason $r 'R-TRANSPORT'; $r.counts['error'] = $why; $r.rc = 3
        if ($Worker) { Write-OutLine ('{"_wres":' + (ConvertTo-ResultJson $r) + '}') }
        else { Write-ErrLine ('{"_result":' + (ConvertTo-ResultJson $r) + '}') }
    }
    $code = 3
}
exit $code
