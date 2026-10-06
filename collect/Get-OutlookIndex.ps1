<#
.SYNOPSIS
  mail.index · cal.index — Windows Search 색인(SystemIndex OLE DB)에서 Outlook 메일·일정 메타데이터를 읽는 수집기(CM §6).

.DESCRIPTION
  계약 §2.17 · §7.3 · §8.1, CM §6 · §8 · §10 · §11.2. LM24 Get-OutlookIndex.ps1 을 옮겨 다시 설계했다.
    · 디스크에 쓰지 않는다(L-09). 원시 후보 레코드를 NDJSON 으로 stdout 에만 낸다 — 연결자가 정제 파이프
      (lm27_pipe.py --kind <kind> --src <경로 ID>)의 stdin 으로 잇는다. 원시 필드 이름은 P §10.2(계약 §3.5).
    · stdin 제어 줄 {"_in": {"cursor": …, "cfg": {…}}} 을 받는다(stdin 이 리디렉션되지 않았으면 기본값). 커서·설정·주소를
      명령줄로 받지 않는다(X-300). stdout 첫 줄 {"_meta": {"my_addrs": [...]}}, 레코드 줄, 끝 줄 {"_cursor": {…}}.
    · 결과(숫자·열거·사유 코드만)는 stderr 마지막 줄 {"_status": {…}}(계약 v1.2 §0.7 C1 한 모양 — schema·src·rc·reasons·
      partial·cap_hit·budget_hit·n·counts + 수집기 필드) — 메일·일정을 함께 읽으면 경로마다 한 줄.
    · Outlook 을 띄우지 않는다(마법사 무한 대기 없음). Outlook 항목만(System.ItemUrl LIKE 'mapi%'), 날짜 리터럴은 UTC.
    · 폴더는 경로 조각 단위 정확 일치로 제외(mail.index.excludeFolderNames), '보낸 편지함/Sent' 조각이면 sent.
    · 반복 일정 마스터는 회차가 전개되지 않는다 → 레코드에 recurrence_incomplete, 결과에 그 수 + R-RECURINC + partial
      (계약 v1.2 §0.7 C4 — 부분 결과: rc 는 새 레코드 기준 0·4, 셀은 partial 이라 cal.owa 가 빈 회차를 채운다).
    · 상한(mail.index.capMail·capCal)에 닿으면 조용히 자르지 않고 cap_hit + R-CAP(rc 0, 셀 partial).
    · 막힌 사유가 있으면 항상 rc 3 + 사유: 색인 연결 실패 R-NOIDX · 색인 일시정지 R-IDXPAUSED · 제한 언어 모드 R-CLM ·
      Outlook 항목 0 → R-IDXPOLICY(정책) / R-NEWOL(새 Outlook) / R-ONLINE(온라인 모드 — 그 밖).
  rc: 0 새 레코드 · 1 기간에 항목 없음 · 3 막힘·불완전(사유) · 4 읽었지만 새것 0(커서 이후 0).

  커서(계약 §3.10): {"last_item_ts_utc": UTC, "read_from": UTC} — read_from 은 이미 읽은 범위의 시작(이 수집기가 더한 칸).
  색인은 싸므로 겹침 재조회를 허용하고(마지막 시각 −1일부터 다시 냄) 중복은 정제기의 레코드 id 로 흡수된다.

  시험 주입(계약 §11.3): LM_INDEX_FAKE=<json> — 색인 대신 {"mail": [System.* 행], "calendar": [...]}(시각은 로컬
  'yyyy-MM-dd HH:mm'). 선택 키: "_error" = noidx|paused · "_total_outlook_items"(정수) · "_policy" · "_newol" ·
  "_ext_rejected" · "_my_addrs"(시험용 내 주소 — 실제 PC 신원 조회를 하지 않는다). -TestNow 'yyyy-MM-dd HH:mm'(로컬).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File collect\Get-OutlookIndex.ps1 -Only mail -Pc pc_0123456789abcdef -Since 2026-09-01 -Until 2026-09-30
#>
param(
    [string]$Only = '',
    [string]$Since = '',
    [string]$Until = '',
    [string]$Pc = '',
    [string]$TestNow = ''
)

# ── 제한 언어 모드: .NET 형을 쓰기 전에 먼저 본다(R-CLM, rc 3) ─────────────────────────────────────────────
# 계약 v1.2 §0.7 C1: 상태 줄 한 모양(_status). CLM 에서는 [Console] 호출도 막히므로 stdout 제어 줄(문자열 리터럴)로 낸다.
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    if ($Only -eq 'cal') {
        '{"_status":{"schema":"lm27.collector_status/1","src":"cal.index","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{},"items_total":0,"items_ok":0}}'
    } else {
        '{"_status":{"schema":"lm27.collector_status/1","src":"mail.index","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{},"items_total":0,"items_ok":0}}'
    }
    exit 3
}

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:Inv = [Globalization.CultureInfo]::InvariantCulture
$script:StdOut = [Console]::OpenStandardOutput()
$script:StdErr = [Console]::OpenStandardError()

$SENT_RX = '^(보낸\s*(편지함|메일함|항목)|Sent(\s+(Items|Mail|Messages))?)$'
$INBOX_RX = '^(받은\s*(편지함|메일함)|Inbox)$'
$PREFIX_RX = '^\s*(RE|FW|FWD|답장|전달|회신)\s*[:：]\s*'
$PC_RX = '^pcx?_[0-9a-f]{16}$'
# mail.index.excludeFolderNames 내장 기본값(설정 레지스트리와 같은 목록 — 연결자가 _in.cfg 로 최종 목록을 준다)
$DEFAULT_EXCLUDE = @('지운 편지함', '삭제된 항목', '삭제된 편지함', 'Deleted Items', 'Trash', '정크 메일', 'Junk E-mail',
    'Junk Email', 'Junk', '스팸', 'Spam', '임시 보관함', 'Drafts', 'Draft', '보낼 편지함', 'Outbox', '보관', '보관함',
    'Archive', '동기화 문제', 'Sync Issues', '대화 기록', 'Conversation History', 'RSS 피드', 'RSS Feeds')
$BUSY_OF = @{ '0' = 'free'; '1' = 'tentative'; '2' = 'busy'; '3' = 'oof'; '4' = 'elsewhere' }
$OVERLAP_DAYS = 1          # 마지막 시각에서 이만큼 겹쳐 다시 낸다(늦게 색인된 항목)
$CAL_REFRESH_DAYS = 14     # 일정은 최근 이만큼과 그 뒤를 매번 다시 낸다(시각 변경·취소 반영)

# ── 출력 ──────────────────────────────────────────────────────────────────────────────────────────────
function Find-ClassicOutlook {
    # 클래식 Outlook(OUTLOOK.EXE) 위치 — 판(2010~365)·설치 방식(MSI·Click-to-Run)·32/64비트와 상관없이 찾는다.
    # App Paths 한 곳만 보면 Microsoft 365(Click-to-Run) PC 대부분에서 못 찾아 '새 Outlook 전용' 으로 오판했다(실측).
    # 반환: 있는 OUTLOOK.EXE 전체 경로 또는 $null. 메모리에서만 쓰고 출력하지 않는다.
    # 같은 함수가 Invoke-CapabilityProbe.ps1 · Get-OutlookCom.ps1 · Get-OutlookIndex.ps1 에 똑같이 있다(시험이 대조).
    $cands = New-Object System.Collections.Generic.List[string]
    foreach ($k in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE',
            'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE')) {
        try { $d = (Get-ItemProperty -LiteralPath $k -ErrorAction Stop).'(default)'; if ($d) { $cands.Add([string]$d) } } catch { }
    }
    foreach ($v in @('16.0', '15.0', '14.0')) {
        foreach ($b in @('HKLM:\SOFTWARE\Microsoft\Office', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Office')) {
            try { $ir = (Get-ItemProperty -LiteralPath "$b\$v\Outlook\InstallRoot" -ErrorAction Stop).Path; if ($ir) { $cands.Add((Join-Path $ir 'OUTLOOK.EXE')) } } catch { }
        }
    }
    try {
        $c2r = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration' -ErrorAction Stop).InstallationPath
        if ($c2r) { foreach ($o in @('Office16', 'Office15')) { $cands.Add((Join-Path $c2r "root\$o\OUTLOOK.EXE")) } }
    } catch { }
    foreach ($cls in @('HKLM:\SOFTWARE\Classes', 'HKLM:\SOFTWARE\WOW6432Node\Classes')) {
        try {
            $clsid = (Get-ItemProperty -LiteralPath "$cls\Outlook.Application\CLSID" -ErrorAction Stop).'(default)'
            if ($clsid) {
                $ls = (Get-ItemProperty -LiteralPath "$cls\CLSID\$clsid\LocalServer32" -ErrorAction Stop).'(default)'
                if ($ls) { $cands.Add([string]$ls) }
            }
        } catch { }
    }
    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $pf) { continue }
        foreach ($o in @('root\Office16', 'root\Office15', 'Office16', 'Office15', 'Office14')) { $cands.Add((Join-Path $pf "Microsoft Office\$o\OUTLOOK.EXE")) }
    }
    foreach ($c in $cands) {
        $s = ([string]$c).Trim()
        try { $s = [Environment]::ExpandEnvironmentVariables($s) } catch { }
        if ($s.StartsWith('"')) {
            $e = $s.IndexOf('"', 1)
            if ($e -gt 1) { $s = $s.Substring(1, $e - 1) } else { $s = $s.Trim('"') }
        } else {
            $i = $s.ToLowerInvariant().IndexOf('.exe')
            if ($i -gt 0) { $s = $s.Substring(0, $i + 4) }
        }
        if ($s -and (Test-Path -LiteralPath $s -PathType Leaf)) { return $s }
    }
    return $null
}

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
function ConvertFrom-LocalText([string]$s) {
    # 'yyyy-MM-dd HH:mm[:ss]'(로컬) · ISO 'yyyy-MM-ddTHH:mm:ssZ'(UTC) → UTC datetime 또는 $null
    if (-not $s) { return $null }
    $t = $s.Trim()
    $styles = [Globalization.DateTimeStyles]::None
    $d = [datetime]::MinValue
    foreach ($f in @("yyyy-MM-dd'T'HH:mm:ss'Z'", "yyyy-MM-dd'T'HH:mm'Z'")) {
        if ([datetime]::TryParseExact($t, $f, $script:Inv, $styles, [ref]$d)) { return [DateTime]::SpecifyKind($d, 'Utc') }
    }
    foreach ($f in @('yyyy-MM-dd HH:mm:ss', 'yyyy-MM-dd HH:mm', "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", 'yyyy-MM-dd')) {
        if ([datetime]::TryParseExact($t, $f, $script:Inv, $styles, [ref]$d)) {
            return [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($d, 'Unspecified'), [TimeZoneInfo]::Local)
        }
    }
    return $null
}
function ConvertFrom-UtcText($s) {
    if (-not $s) { return $null }
    $d = [datetime]::MinValue
    if ([datetime]::TryParseExact([string]$s, "yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv, [Globalization.DateTimeStyles]::None, [ref]$d)) {
        return [DateTime]::SpecifyKind($d, 'Utc')
    }
    return $null
}
function Get-LocalDayUtc([string]$day, [int]$addDays) {
    $d = [datetime]::ParseExact($day, 'yyyy-MM-dd', $script:Inv).AddDays($addDays)
    return [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($d, 'Unspecified'), [TimeZoneInfo]::Local)
}

# ── stdin 제어 줄 ─────────────────────────────────────────────────────────────────────────────────────
function Read-InLine {
    # 첫 줄만 읽는다(연결자가 쓰고 닫는다 — 닫지 않아도 줄 끝에서 멈춘다). 리디렉션이 아니면 기본값.
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

# ── 내 주소(CM §6.1 — LM24 :66-121 이식) ─────────────────────────────────────────────────────────────
function Get-MyAddrs([string]$owner, $fake) {
    $me = New-Object System.Collections.Generic.List[string]
    if ($fake) {
        if ($fake.PSObject.Properties['_my_addrs']) { foreach ($a in @($fake._my_addrs)) { if ($a) { $me.Add(([string]$a).Trim().ToLower()) } } }
    } else {
        try {
            $u = (& whoami /upn 2>$null)
            if ($LASTEXITCODE -eq 0 -and $u) { $me.Add(([string]$u).Trim().ToLower()) }
        } catch { }
        try {
            Add-Type -AssemblyName System.DirectoryServices.AccountManagement -ErrorAction Stop
            $up = [System.DirectoryServices.AccountManagement.UserPrincipal]::Current
            if ($up) { foreach ($v in @($up.EmailAddress, $up.UserPrincipalName)) { if ($v) { $me.Add(([string]$v).Trim().ToLower()) } } }
        } catch { }
        try {
            if ($env:USERDNSDOMAIN) {
                $srch = [adsisearcher]('(&(objectCategory=person)(sAMAccountName=' + $env:USERNAME + '))')
                $srch.ClientTimeout = [TimeSpan]::FromSeconds(5)
                $srch.ServerTimeLimit = [TimeSpan]::FromSeconds(5)
                [void]$srch.PropertiesToLoad.AddRange([string[]]@('mail', 'userPrincipalName'))
                $res = $srch.FindOne()
                if ($res) { foreach ($k in @('mail', 'userprincipalname')) { foreach ($v in @($res.Properties[$k])) { if ($v) { $me.Add(([string]$v).Trim().ToLower()) } } } }
            }
        } catch { }
        try {
            foreach ($pp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles', 'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles',
                              'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles')) {
                if (-not (Test-Path -LiteralPath $pp)) { continue }
                foreach ($k in @(Get-ChildItem -LiteralPath $pp -Recurse -ErrorAction SilentlyContinue | Select-Object -First 400)) {
                    foreach ($name in @('Account Name', 'Email')) {
                        $raw = $null
                        try { $raw = $k.GetValue($name) } catch { }
                        if ($raw -is [byte[]] -and $raw.Length -ge 4) { $raw = [System.Text.Encoding]::Unicode.GetString($raw).TrimEnd([char]0) }
                        if ($raw -is [string] -and $raw -match '^[^@\s]+@[^@\s]+\.[^@\s]+$') { $me.Add($raw.Trim().ToLower()) }
                    }
                }
            }
        } catch { }
    }
    if ($owner) { $me.Add($owner.Trim().ToLower()) }
    return @($me | Where-Object { $_ -and $_.Length -ge 3 -and $_ -match '@' } | Select-Object -Unique)
}

# ── 색인 읽기(실물 · 시험 주입) ───────────────────────────────────────────────────────────────────────
function Get-FakeRows($fake, [string]$kind, [bool]$extRejected) {
    $rows = New-Object System.Collections.Generic.List[object]
    $p = $fake.PSObject.Properties[$kind]
    if (-not $p) { return $rows }
    foreach ($o in @($p.Value)) {
        if ($null -eq $o) { continue }
        $h = @{}
        foreach ($q in $o.PSObject.Properties) {
            if ($extRejected -and $q.Name -in @('System.Message.ToName', 'System.Message.CcName', 'System.Calendar.IsRecurring',
                                               'System.Message.ConversationID')) { continue }
            $v = $q.Value
            if ($v -is [string] -and $v -match '^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}') { $v = ConvertFrom-LocalText $v }
            $h[$q.Name] = $v
        }
        $rows.Add($h)
    }
    return $rows
}
function Invoke-Query($conn, [string]$sql, [int]$cap) {
    $rows = New-Object System.Collections.Generic.List[object]
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $sql
    $rd = $cmd.ExecuteReader()
    try {
        while ($rd.Read()) {
            $o = @{}
            for ($i = 0; $i -lt $rd.FieldCount; $i++) {
                $v = $rd.GetValue($i)
                if ($v -is [System.DBNull]) { $v = $null }
                elseif ($v -is [datetime]) { $v = [DateTime]::SpecifyKind($v, 'Utc') }   # 색인 날짜는 UTC
                $o[$rd.GetName($i)] = $v
            }
            $rows.Add($o)
            if ($rows.Count -ge $cap) { break }
        }
    } finally { $rd.Close() }
    return $rows
}
function Get-S($row, [string]$k) {
    $v = $row[$k]
    if ($null -eq $v) { return '' }
    if ($v -is [array]) { return (@($v | Where-Object { $null -ne $_ } | ForEach-Object { [string]$_ }) -join ';') }
    return [string]$v
}
function Get-List($row, [string]$k) {
    $v = $row[$k]
    if ($null -eq $v) { return @() }
    if ($v -is [array] -or ($v -is [System.Collections.IEnumerable] -and -not ($v -is [string]))) {
        return @($v | Where-Object { $null -ne $_ } | ForEach-Object { ([string]$_).Trim() })
    }
    return @(([string]$v).Split(';') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
function Get-D($row, [string]$k) {
    $v = $row[$k]
    if ($v -is [datetime]) { return $v }
    return $null
}
function New-Party([string[]]$addrs, [string[]]$names) {
    $out = New-Object System.Collections.Generic.List[object]
    $n = [math]::Max(@($addrs).Count, @($names).Count)
    for ($i = 0; $i -lt $n -and $i -lt 100; $i++) {
        $a = $null; $nm = $null
        if ($i -lt @($addrs).Count -and $addrs[$i]) { $a = ([string]$addrs[$i]).Trim().ToLower() }
        if ($i -lt @($names).Count -and $names[$i]) { $nm = ([string]$names[$i]).Trim() }
        if ($a -or $nm) { $out.Add([ordered]@{ addr = $a; name = $nm }) }
    }
    return , $out.ToArray()
}

# ── 본문 ──────────────────────────────────────────────────────────────────────────────────────────────
$script:Results = New-Object System.Collections.Generic.List[object]
$script:Cursors = [ordered]@{}
$script:Mixed = $false

function New-Result([string]$src) {
    return [ordered]@{ schema = 'lm27.collector_status/1'; src = $src; rc = 3
        reasons = (New-Object System.Collections.Generic.List[string]); partial = $false; n = 0; items_total = 0
        items_ok = 0; new = 0; cap_hit = $false; budget_hit = $false; horizon_oldest = $null; recurrence_incomplete = 0
        counts = [ordered]@{} }
}
function Add-Reason($res, [string]$code) { if (-not $res.reasons.Contains($code)) { $res.reasons.Add($code) } }
function Write-Record([System.Collections.IDictionary]$rec, [string]$kind) {
    if ($script:Mixed) { $rec['_kind'] = $kind }
    Write-OutLine (ConvertTo-J $rec)
}
function Write-Results {
    foreach ($r in $script:Results) {
        $o = [ordered]@{}
        foreach ($k in $r.Keys) { $o[$k] = $r[$k] }
        $o['reasons'] = @($r.reasons | Sort-Object)
        # C1: partial = 상한·예산·반복 일부(C4), n = 새 레코드 수
        $o['partial'] = [bool]($r.cap_hit -or $r.budget_hit -or ($r.recurrence_incomplete -gt 0) -or $r.reasons.Contains('R-RECURINC'))
        $o['n'] = [int]$r.new
        Write-ErrLine ('{"_status":' + (ConvertTo-J $o) + '}')
    }
}

function Invoke-IndexKind([string]$kind, $ctx) {
    $src = $(if ($kind -eq 'mail') { 'mail.index' } else { 'cal.index' })
    $res = New-Result $src
    $script:Results.Add($res)
    foreach ($r in $ctx.reasons) { Add-Reason $res $r }
    if ($ctx.fatal) { Add-Reason $res $ctx.fatal; $res.rc = 3; return }
    $cur = Get-SrcCursor $ctx.in $src $script:Mixed
    $lastTs = $null; $readFrom = $null
    if ($cur) {
        if ($cur.PSObject.Properties['last_item_ts_utc']) { $lastTs = ConvertFrom-UtcText $cur.last_item_ts_utc }
        if ($cur.PSObject.Properties['read_from']) { $readFrom = ConvertFrom-UtcText $cur.read_from }
    }
    $fmt = 'yyyy-MM-dd HH:mm:ss'
    $sU = $ctx.sinceUtc.ToString($fmt, $script:Inv)
    $uU = $ctx.untilUtc.ToString($fmt, $script:Inv)
    if ($kind -eq 'mail') {
        $cap = [int]$ctx.capMail
        $sel = ("SELECT System.ItemDate, System.Message.DateReceived, System.Message.DateSent, System.Message.FromName, " +
            "System.Message.FromAddress, System.Message.ToAddress, System.Message.CcAddress, System.Subject, " +
            "System.ItemFolderPathDisplay, System.ItemUrl{0} FROM SYSTEMINDEX WHERE System.Kind = 'email' " +
            "AND System.ItemUrl LIKE 'mapi%' AND System.ItemDate >= '{1}' AND System.ItemDate < '{2}' ORDER BY System.ItemDate DESC")
        # 확장 속성이 거부되면 한 단계씩 덜어 다시(LM24 Run-Query) — 마지막 단계(기본 속성)면 fallback
        $sqls = @(($sel -f ', System.Message.ToName, System.Message.CcName, System.Message.ConversationID', $sU, $uU),
                  ($sel -f ', System.Message.ToName, System.Message.CcName', $sU, $uU), ($sel -f '', $sU, $uU))
        $fakeKind = 'mail'
    } else {
        $cap = [int]$ctx.capCal
        $sel = ("SELECT System.StartDate, System.EndDate, System.Subject, System.Calendar.Location, System.Calendar.ShowTimeAs{0}, " +
            "System.ItemUrl FROM SYSTEMINDEX WHERE System.Kind = 'calendar' AND System.ItemUrl LIKE 'mapi%' " +
            "AND System.EndDate >= '{1}' AND System.StartDate < '{2}' ORDER BY System.StartDate DESC")
        $sqls = @(($sel -f ', System.Calendar.IsRecurring', $sU, $uU), ($sel -f '', $sU, $uU))
        $fakeKind = 'calendar'
    }
    $fallback = $false
    if ($ctx.fake) {
        $all = Get-FakeRows $ctx.fake $fakeKind $ctx.extRejected
        $fallback = [bool]$ctx.extRejected
        $tk = $(if ($kind -eq 'mail') { 'System.ItemDate' } else { 'System.StartDate' })
        $rows = New-Object System.Collections.Generic.List[object]
        foreach ($r in $all) {
            $t = $r[$tk]
            if ($kind -eq 'cal') {
                $e = $r['System.EndDate']; if (-not ($e -is [datetime])) { $e = $t }
                if (($t -is [datetime]) -and $t -lt $ctx.untilUtc -and $e -ge $ctx.sinceUtc) { $rows.Add($r) }
            } elseif (($t -is [datetime]) -and $t -ge $ctx.sinceUtc -and $t -lt $ctx.untilUtc) { $rows.Add($r) }
        }
        if ($kind -eq 'mail') { $rows = [System.Collections.Generic.List[object]]@($rows | Sort-Object { $_['System.ItemDate'] } -Descending) }
    } else {
        $rows = $null
        for ($qi = 0; $qi -lt $sqls.Count; $qi++) {
            try { $rows = Invoke-Query $ctx.conn $sqls[$qi] ($cap + 1); break }
            catch { if ($qi -eq $sqls.Count - 1) { throw } }
        }
        $res.counts['query_level'] = $qi
        $fallback = ($qi -eq $sqls.Count - 1)
    }
    $res.counts['fallback'] = $fallback
    # 상한: 한 건 더 읽어 넘치면 절단 — 조용히 자르지 않고 cap_hit + R-CAP(셀 partial, CM §6.2)
    if ($rows.Count -gt $cap) {
        $rows = [System.Collections.Generic.List[object]]@($rows | Select-Object -First $cap)
        $res.cap_hit = $true
        Add-Reason $res 'R-CAP'
    }
    $res.counts['rows'] = $rows.Count
    $res.items_total = $rows.Count
    # 지평선(색인에 있는 가장 오래된 Outlook 항목) — 요청 시작이 더 오래되면 구조적 공백(0건 아님)
    if ($ctx.horizon) {
        $hd = [TimeZoneInfo]::ConvertTimeFromUtc($ctx.horizon, [TimeZoneInfo]::Local).Date
        $res.horizon_oldest = $hd.ToString('yyyy-MM-dd', $script:Inv)
        if ($hd -gt [TimeZoneInfo]::ConvertTimeFromUtc($ctx.sinceUtc, [TimeZoneInfo]::Local).Date) { Add-Reason $res 'R-HORIZON' }
    }
    $nowIso = Format-Utc $ctx.nowUtc
    $emitSent = New-Object System.Collections.Generic.List[object]
    $emitOther = New-Object System.Collections.Generic.List[object]
    $maxTs = $lastTs; $minTs = $null; $nNew = 0; $nEx = 0; $nNoMapi = 0; $nNoTime = 0; $nMasters = 0
    $refreshFrom = $ctx.nowUtc.AddDays(-$CAL_REFRESH_DAYS)
    foreach ($r in $rows) {
        $url = Get-S $r 'System.ItemUrl'
        if ($url -notmatch '^mapi\d*:') { $nNoMapi++; continue }      # 디스크의 메일·일정 파일 제외(이중 안전장치)
        if ($kind -eq 'mail') {
            $segs = @(((Get-S $r 'System.ItemFolderPathDisplay') -split '[\\/]') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            $hit = $false
            foreach ($sg in $segs) { foreach ($x in $ctx.exclude) { if ($sg -ieq $x) { $hit = $true; break } }; if ($hit) { break } }
            if ($hit) { $nEx++; continue }
            $isSent = [bool](@($segs | Where-Object { $_ -match $SENT_RX }).Count)
            $last = $(if ($segs.Count) { $segs[$segs.Count - 1] } else { '' })
            if ($isSent) { $box = 'sent'; $role = $(if ($last -match $SENT_RX) { 'sent' } else { 'subfolder' }) }
            else { $box = 'inbox'; $role = $(if ($last -match $INBOX_RX) { 'inbox' } else { 'subfolder' }) }
            $t = $null
            if ($isSent) { $t = Get-D $r 'System.Message.DateSent' }
            if (-not $t) { $t = Get-D $r 'System.Message.DateReceived' }
            if (-not $t) { $t = Get-D $r 'System.ItemDate' }
            if (-not $t) { $nNoTime++; continue }
            $isNew = (-not $lastTs) -or ($t -gt $lastTs) -or ($readFrom -and $t -lt $readFrom)
            if ($isNew) { $nNew++ }
            if ((-not $maxTs) -or $t -gt $maxTs) { $maxTs = $t }
            if ((-not $minTs) -or $t -lt $minTs) { $minTs = $t }
            if (-not ($isNew -or $t -ge $lastTs.AddDays(-$OVERLAP_DAYS))) { continue }
            $subj = Get-S $r 'System.Subject'
            $topic = $subj
            while ($topic -match $PREFIX_RX) { $topic = $topic -replace $PREFIX_RX, '' }
            $rec = [ordered]@{}
            $cid = Get-S $r 'System.Message.ConversationID'
            if ($cid) { $rec['conversation_id'] = $cid }
            $rec['conversation_topic'] = $topic.Trim()
            $rec['box'] = $box
            $rec['folder_role'] = $role
            $fa = @(Get-List $r 'System.Message.FromAddress'); $fn = @(Get-List $r 'System.Message.FromName')
            if ($fa.Count -and $fa[0]) { $rec['sender_addr'] = $fa[0].ToLower() }
            if ($fn.Count -and $fn[0]) { $rec['sender_name'] = $fn[0] }
            $rec['to'] = New-Party (Get-List $r 'System.Message.ToAddress') (Get-List $r 'System.Message.ToName')
            $rec['cc'] = New-Party (Get-List $r 'System.Message.CcAddress') (Get-List $r 'System.Message.CcName')
            $rec['subject'] = $subj
            $rec['ts_utc'] = Format-Utc $t
            $rec['ts_local_offset'] = Format-Offset $t
            $rec['ts_precision'] = 'minute'
            $rec['observed_at'] = $nowIso
            $rec['confidence'] = 1.0
            if ($box -eq 'sent') { $emitSent.Add($rec) } else { $emitOther.Add($rec) }
        } else {
            $st = Get-D $r 'System.StartDate'; $en = Get-D $r 'System.EndDate'
            if (-not $st) { $nNoTime++; continue }
            if (-not $en -or $en -lt $st) { $en = $st }
            $isRec = $r['System.Calendar.IsRecurring']
            $master = (($isRec -is [bool]) -and $isRec) -or ([string]$isRec -match '^(True|1|-1)$')
            if ($master) { $nMasters++ }
            $isNew = (-not $lastTs) -or ($st -gt $lastTs) -or ($readFrom -and $st -lt $readFrom)
            if ($isNew) { $nNew++ }
            if (((-not $maxTs) -or $st -gt $maxTs) -and $st -le $ctx.nowUtc) { $maxTs = $st }
            if ((-not $minTs) -or $st -lt $minTs) { $minTs = $st }
            if (-not ($isNew -or $st -ge $refreshFrom -or $st -ge $lastTs.AddDays(-$OVERLAP_DAYS))) { continue }
            $loc = [TimeZoneInfo]::ConvertTimeFromUtc($st, [TimeZoneInfo]::Local)
            $allDay = ($loc.TimeOfDay.TotalMinutes -eq 0 -and ($en - $st).TotalHours -ge 23)
            $busyRaw = Get-S $r 'System.Calendar.ShowTimeAs'
            $busy = 'busy'
            if ($BUSY_OF.ContainsKey($busyRaw)) { $busy = $BUSY_OF[$busyRaw] }
            $rec = [ordered]@{}
            $rec['start_utc'] = Format-Utc $st
            $rec['end_utc'] = Format-Utc $en
            $rec['subject'] = Get-S $r 'System.Subject'
            $locTxt = Get-S $r 'System.Calendar.Location'
            if ($locTxt) { $rec['location'] = $locTxt }
            $rec['busy_status'] = $busy
            $rec['is_recurring'] = [bool]$master
            $rec['all_day'] = [bool]$allDay
            $rec['recurrence_incomplete'] = [bool]$master
            $rec['ts_local_offset'] = Format-Offset $st
            $rec['ts_precision'] = $(if ($allDay) { 'date' } else { 'minute' })
            $rec['observed_at'] = $nowIso
            $rec['confidence'] = 1.0
            $emitOther.Add($rec)
        }
    }
    # 보낸 편지함을 먼저 흘린다(왕래 도메인 냉시작 오탐 방지 — CM §10)
    foreach ($rec in $emitSent) { Write-Record $rec $kind }
    foreach ($rec in $emitOther) { Write-Record $rec $kind }
    $emitted = $emitSent.Count + $emitOther.Count
    $res.items_ok = $emitted
    $res.new = $nNew
    $res.counts['emitted'] = $emitted
    $res.counts['excluded_folder'] = $nEx
    $res.counts['non_outlook'] = $nNoMapi
    $res.counts['no_time'] = $nNoTime
    if ($kind -eq 'cal') { $res.recurrence_incomplete = $nMasters; if ($fallback) { $res.counts['recurrence_unknown'] = $true } }
    # 커서: 읽은 범위 [read_from, last_item_ts_utc]
    $oldest = $ctx.sinceUtc
    if ($res.cap_hit -and $minTs) { $oldest = $minTs }
    $newFrom = $oldest
    if ($readFrom -and $lastTs -and $oldest -le $lastTs.AddDays($OVERLAP_DAYS) -and $readFrom -lt $oldest) { $newFrom = $readFrom }
    $c = [ordered]@{ last_item_ts_utc = $null; read_from = (Format-Utc $newFrom) }
    if ($maxTs) { $c['last_item_ts_utc'] = Format-Utc $maxTs }
    $script:Cursors[$src] = $c
    # rc(계약 §8.1 · CM §6.4 · X-120)
    # 반복 마스터만·반복 속성 거부(전개 여부 모름) → R-RECURINC(계약 v1.2 §0.7 C4: 부분 결과 — rc 는 아래 새 레코드 기준).
    # 예전의 'rc 3·사유 없음' 은 연결자에서 R-TRANSPORT(수송 실패)로 접혀 cal.owa 배정 근거가 왜곡됐다.
    if ($kind -eq 'cal' -and ($nMasters -gt 0 -or $fallback)) { Add-Reason $res 'R-RECURINC' }
    if ($nNew -gt 0) { $res.rc = 0; return }
    if ($res.cap_hit) { $res.rc = 0; return }
    if ($rows.Count -gt 0) { $res.rc = 4; return }
    $res.rc = 1
}

$rc = 3
$exitReason = $null
try {
    if ($args.Count) { throw (New-Object System.ArgumentException('unknown-argument')) }
    if ($Only -notin @('', 'mail', 'cal')) { throw (New-Object System.ArgumentException('only')) }
    if ($Pc -and $Pc -notmatch $PC_RX) { throw (New-Object System.ArgumentException('pc')) }
    $in = Read-InLine
    $nowLocal = Get-Date
    if ($TestNow) { $nowLocal = [datetime]::ParseExact($TestNow, 'yyyy-MM-dd HH:mm', $script:Inv) }
    $nowUtc = [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($nowLocal, 'Unspecified'), [TimeZoneInfo]::Local)
    $untilDay = $Until
    if (-not $untilDay) { $untilDay = $nowLocal.ToString('yyyy-MM-dd', $script:Inv) }
    $sinceDay = $Since
    if (-not $sinceDay) { $sinceDay = [datetime]::ParseExact($untilDay, 'yyyy-MM-dd', $script:Inv).AddDays(-89).ToString('yyyy-MM-dd', $script:Inv) }
    $ctx = @{
        in = $in; reasons = (New-Object System.Collections.Generic.List[string]); fatal = $null; nowUtc = $nowUtc
        sinceUtc = (Get-LocalDayUtc $sinceDay 0); untilUtc = (Get-LocalDayUtc $untilDay 1)
        capMail = [int](Get-Cfg $in 'mail.index.capMail' 20000); capCal = [int](Get-Cfg $in 'mail.index.capCal' 8000)
        exclude = @(Get-Cfg $in 'mail.index.excludeFolderNames' $DEFAULT_EXCLUDE | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
        fake = $null; conn = $null; extRejected = $false; horizon = $null
    }
    if ($ctx.untilUtc -le $ctx.sinceUtc) { throw (New-Object System.ArgumentException('range')) }
    $kinds = @('mail', 'cal')
    if ($Only) { $kinds = @($Only) }
    $script:Mixed = ($kinds.Count -gt 1)
    if ($env:LM_INDEX_FAKE) {
        $ctx.fake = (Get-Content -Raw -Encoding UTF8 -LiteralPath $env:LM_INDEX_FAKE) | ConvertFrom-Json
        $ctx.extRejected = [bool]($ctx.fake.PSObject.Properties['_ext_rejected'] -and $ctx.fake._ext_rejected)
    }
    $owner = [string](Get-Cfg $in 'collect.ownerAddress' '')
    $my = @(Get-MyAddrs $owner $ctx.fake)
    Write-OutLine ('{"_meta":{"my_addrs":' + (ConvertTo-J ([object[]]$my)) + '}}')
    if ($my.Count -eq 0 -and $kinds -contains 'mail') { $ctx.reasons.Add('R-NOADDR') }
    # ── 색인 연결·상태 ──
    $total = -1
    if ($ctx.fake) {
        $err = $(if ($ctx.fake.PSObject.Properties['_error']) { [string]$ctx.fake._error } else { '' })
        if ($err -eq 'noidx') { $ctx.fatal = 'R-NOIDX' } elseif ($err -eq 'paused') { $ctx.fatal = 'R-IDXPAUSED' }
        if ($ctx.fake.PSObject.Properties['_total_outlook_items']) { $total = [int]$ctx.fake._total_outlook_items }
        else { $total = @($ctx.fake.mail).Count + @($ctx.fake.calendar).Count }
        $dates = New-Object System.Collections.Generic.List[datetime]
        foreach ($k in @('mail', 'calendar')) {
            foreach ($r in (Get-FakeRows $ctx.fake $k $false)) {
                foreach ($f in @('System.ItemDate', 'System.StartDate')) { if ($r[$f] -is [datetime]) { $dates.Add($r[$f]) } }
            }
        }
        if ($dates.Count) { $ctx.horizon = ($dates | Sort-Object | Select-Object -First 1) }
        $policy = [bool]($ctx.fake.PSObject.Properties['_policy'] -and $ctx.fake._policy)
        $newOl = [bool]($ctx.fake.PSObject.Properties['_newol'] -and $ctx.fake._newol)
        $classicFake = [bool]($ctx.fake.PSObject.Properties['_classic'] -and $ctx.fake._classic)   # 시험: 클래식 유무도 주입값으로(실제 레지스트리를 보지 않는다)
    } else {
        $svc = $null
        try { $svc = Get-Service -Name WSearch -ErrorAction Stop } catch { $svc = $null }
        if ($svc -and [string]$svc.Status -eq 'Paused') { $ctx.fatal = 'R-IDXPAUSED' }
        elseif (-not $svc -or [string]$svc.Status -ne 'Running') { $ctx.fatal = 'R-NOIDX' }
        if (-not $ctx.fatal) {
            try {
                $ctx.conn = New-Object System.Data.OleDb.OleDbConnection("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
                $ctx.conn.Open()
            } catch { $ctx.fatal = 'R-NOIDX' }
        }
        if (-not $ctx.fatal) {
            try {
                $top = Invoke-Query $ctx.conn "SELECT TOP 1 System.ItemDate FROM SYSTEMINDEX WHERE System.ItemUrl LIKE 'mapi%' ORDER BY System.ItemDate ASC" 1
                $total = $top.Count
                if ($top.Count -and ($top[0]['System.ItemDate'] -is [datetime])) { $ctx.horizon = $top[0]['System.ItemDate'] }
            } catch { $total = -1 }
        }
        $policy = $false
        try {
            $pol = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Windows Search' -ErrorAction Stop
            if ($pol.PSObject.Properties['PreventIndexingOutlook'] -and [int]$pol.PreventIndexingOutlook -eq 1) { $policy = $true }
        } catch { }
        $newOl = $false
        try {
            foreach ($rp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
                $pref = Get-ItemProperty -LiteralPath $rp -ErrorAction SilentlyContinue
                if ($pref -and $pref.PSObject.Properties['UseNewOutlook'] -and [int]$pref.UseNewOutlook -eq 1) { $newOl = $true }
            }
        } catch { }
        try { if (Get-Process -Name olk -ErrorAction SilentlyContinue) { $newOl = $true } } catch { }
    }
    if (-not $ctx.fatal -and $total -eq 0) {
        # 색인에 Outlook 항목이 하나도 없다 — 0건이 아니라 막힘(CM §6.4 분해, X-124·X-125)
        # 새 Outlook 전용(클래식 없음)일 때만 R-NEWOL — 클래식이 있는데 색인에 Outlook 항목이 없으면 온라인 모드(캐시 꺼짐)다
        if ($policy) { $ctx.fatal = 'R-IDXPOLICY' } elseif ($newOl -and -not $(if ($ctx.fake) { $classicFake } else { [bool](Find-ClassicOutlook) })) { $ctx.fatal = 'R-NEWOL' } else { $ctx.fatal = 'R-ONLINE' }
    }
    foreach ($k in $kinds) { Invoke-IndexKind $k $ctx }
    if ($script:Cursors.Count) {
        if ($script:Mixed) { Write-OutLine ('{"_cursor":' + (ConvertTo-J $script:Cursors) + '}') }
        else { foreach ($k in $script:Cursors.Keys) { Write-OutLine ('{"_cursor":' + (ConvertTo-J $script:Cursors[$k]) + '}') } }
    }
    $rcs = @($script:Results | ForEach-Object { [int]$_.rc })
    if ($rcs -contains 3) { $rc = 3 } elseif ($rcs -contains 0) { $rc = 0 } elseif ($rcs -contains 4) { $rc = 4 } else { $rc = 1 }
    $n = 0; foreach ($r in $script:Results) { $n += [int]$r.items_ok }
    Write-ErrLine ('[outlook-index] 레코드 {0}건 · rc {1}' -f $n, $rc)
} catch {
    $exitReason = $_.Exception.GetType().Name
    $rc = 3
    if ($script:Results.Count -eq 0) {
        $srcs = @('mail.index', 'cal.index')
        if ($Only -eq 'mail') { $srcs = @('mail.index') } elseif ($Only -eq 'cal') { $srcs = @('cal.index') }
        foreach ($s in $srcs) { $r = New-Result $s; $script:Results.Add($r) }
    }
    foreach ($r in $script:Results) { $r.rc = 3; Add-Reason $r 'R-TRANSPORT'; $r.counts['error'] = $exitReason }
    Write-ErrLine ('[outlook-index] 실패({0}) — 다음 실행에서 다시 시도합니다' -f $exitReason)
} finally {
    try { if ($ctx -and $ctx.conn) { $ctx.conn.Close() } } catch { }
}
Write-Results
exit $rc
