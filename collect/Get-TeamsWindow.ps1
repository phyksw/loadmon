<#
.SYNOPSIS
  teams.uia — Teams 데스크톱 창을 UI Automation(접근성 API)으로 읽는 수집기(CT §7 · 계약 §2.17 · §3.5 · §7.3 · §8.1).

.DESCRIPTION
  ms-teams(새)·Teams(클래식) 프로세스의 **모든 최상위·팝아웃 창**을 열거하고, 가시(IsWindowVisible + 비최소화 +
  화면 교집합 + 가림 아님) 창만 UIA ContentView 요소를 CacheRequest 로 읽는다. 원문은 메모리에서만 다루고
  **원시 레코드(P §10.2 teams 원시 이름)를 stdout NDJSON 으로만** 낸다 — 파일·임시 파일 쓰기 없음(L-09).
  연결자(에이전트 감독 루프 · 전경 lm27.collect.run)가 이 stdout 을 정제 파이프 lm27_pipe.py 의 stdin 으로 잇는다.

  입력(stdin 제어 줄, 계약 §7.3 · X-300 · X-306) — 한 줄, 리디렉션되지 않았으면 기본값으로 돈다:
    {"_in": {"cursor": {"last_ts_utc": "...Z"} | null,
             "cfg": {"teams.timeRegex": "", "teams.uia.visibleOnly": true, "teams.uia.maxElements": 4000,
                     "teams.uia.windowWatchdogSec": 15, "teams.uia.budgetSec": 60},
             "self_names": ["..."]}}            # lm27.privacy.context.self_name_set() 결과 하나만 쓴다
  출력(stdout, UTF-8 BOM 없음, 한 줄 = JSON 하나):
    레코드 줄들   message_id · chat_id · chat_type · n_participants · reply_to_id · author_addr · author_name · is_me ·
                  participants · mentions_me · file_names · body_text · chat_title · ts_utc · ts_local_offset ·
                  ts_precision · observed_at · confidence · flags{n_part_est, author_inherited}
    마지막 줄     {"_cursor": {"last_ts_utc": "...Z" | null}}   (원문·원 ID 없음 — 계약 §3.10)
  상태(stderr, 마지막 줄 한 개 — 숫자·사유 코드만, 원문 없음):
    {"_status": {"src": "teams.uia", "rc": n, "reasons": [R-*], "counts": {...}}}
  종료 코드(계약 §8.1): 0 신규 레코드 · 1 Teams 프로세스 없음 · 3 막힘·불완전(사유 코드 필수 — 창 숨김·최소화·
  트레이 R-UIAEMPTY, 관리자 창 R-UIAELEV, 판독 실패 R-TRANSPORT, 제한 언어 모드 R-CLM) · 4 읽었지만 신규 0(커서
  이후 0·메시지 줄 0).
  상한(teams.uia.maxElements)·창 워치독(teams.uia.windowWatchdogSec) 초과는 R-CAP, 예산(teams.uia.budgetSec) 소진은
  R-BUDGET(rc 0/4 + partial). exit 0 고정 금지.

  판정(구조만 — CT §4): 방향은 본인 이름 집합(_in.self_names) 또는 작성자 생략 + 오른쪽 정렬(내 쪽 말풍선)로만 정하고,
  못 정하면 is_me = null(수신 단정 금지). 이름 집합이 없으면 R-NOADDR. 작성자 없는 연속 메시지는 직전 작성자를 상속
  (flags.author_inherited, confidence 0.3). 대화 유형은 창 구조 단서(참가자 수 단추·채널 게시물 탭·모임 단서·'(나)')로만,
  미상이면 group + n_participants 2 + flags.n_part_est(쉼표 수·방 이름으로 판정하지 않는다). 날짜·작성자는 시각 앞
  머리말에서만 찾고(본문의 '8/15 까지'는 날짜가 아님), 날짜 구분선(오늘·어제·요일·날짜만 있는 줄)은 같은 창의 뒤
  메시지에 적용한다. 날짜를 끝내 못 짚은 줄은 ts_precision = unknown 으로 격리해 넘긴다(수집일로 추정하지 않는다 —
  ts_utc 는 수집일 00:00 로컬의 자리값이며 시간 근거가 아니다).

  시험 주입(계약 §11.3): -RawFile <파일> 은 창 대신 합성 판독 결과를 읽는다(UIA·Add-Type 를 쓰지 않음).
    · 일반 텍스트 = 한 줄이 UIA 요소 이름 하나인 가시 창 하나(WP-05 write_teams_rawfile 형).
    · JSON = 창 열거·판독 스냅숏 {"procs": n, "windows": [{"title", "class", "visible", "iconic", "on_screen",
      "cloaked", "elevated", "hang", "error", "read_ms", "rect": [l, t, w, h], "elements": [{"name", "type", "rect"}]}]}
      (read_ms = 그 창 판독에 걸리는 시간 — 창 워치독·예산을 실제 시간으로 흉내 낸다).
  -TestNow <ISO 시각(오프셋 포함)> 은 '지금'(관측 시각·수집 순간 오프셋·상대 날짜 기준)을 고정한다.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File collect\Get-TeamsWindow.ps1 -Pc pc_0123456789abcdef
#>
[CmdletBinding()]
param(
    [string]$Pc = '',
    [string]$Since = '',
    [string]$Until = '',
    [switch]$KeepChatList,
    [string]$RawFile = '',
    [string]$TestNow = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$script:Src = 'teams.uia'
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $script:Utf8 } catch { }
$script:Inv = [System.Globalization.CultureInfo]::InvariantCulture
$script:Clock = [System.Diagnostics.Stopwatch]::StartNew()
$script:Rc = 3
$script:Reasons = New-Object 'System.Collections.Generic.SortedSet[string]' ([System.StringComparer]::Ordinal)
$script:C = [ordered]@{
    procs = 0; windows = 0; visible = 0; read = 0; empty = 0; elevated = 0; timeout = 0; capped = 0; errors = 0
    elements = 0; lines = 0; list_skipped = 0; list_restored = 0; time_lines = 0; generic = 0; cfg_regex = 0
    rows = 0; n_minute = 0; n_unknown = 0; n_inherited = 0; n_self = 0; n_new = 0; dup = 0; out_of_range = 0
    budget_hit = 0; in_given = 0; self_given = 0
}
$script:OutLines = New-Object 'System.Collections.Generic.List[string]'
$script:PrevCursor = $null
$script:NewCursor = $null

# ── 출력: stdout = NDJSON(레코드·_cursor), stderr = 상태 한 줄. 표준 스트림에 바이트로 직접 쓴다(파일 아님) ──
function Send-Bytes($Stream, [string]$Text) {
    $b = $script:Utf8.GetBytes($Text + "`n")
    $Stream.Write($b, 0, $b.Length)
    $Stream.Flush()
}

$script:JsonEscRe = New-Object System.Text.RegularExpressions.Regex('[\u0000-\u001f"\\  ]')
$script:JsonEsc = [System.Text.RegularExpressions.MatchEvaluator] {
    param($m)
    $c = [int][char]$m.Value
    switch ($c) {
        34 { return '\"' }
        92 { return '\\' }
        10 { return '\n' }
        13 { return '\r' }
        9 { return '\t' }
        8 { return '\b' }
        12 { return '\f' }
        default { return ('\u{0:x4}' -f $c) }
    }
}

function Format-JsonString([string]$Text) {
    return '"' + $script:JsonEscRe.Replace($Text, $script:JsonEsc) + '"'
}

function ConvertTo-LmJson($Value) {
    # 결정적 JSON(키 순서 = 넣은 순서, 숫자 = 불변 문화권). PS 5.1 ConvertTo-Json 의 배열 풀림·깊이 제한을 피한다.
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [string]) { return (Format-JsonString $Value) }
    if ($Value -is [bool]) { if ($Value) { return 'true' } else { return 'false' } }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [int16] -or $Value -is [byte]) {
        return ([long]$Value).ToString($script:Inv)
    }
    if ($Value -is [double] -or $Value -is [single] -or $Value -is [decimal]) {
        return ([double]$Value).ToString('R', $script:Inv)
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $parts = New-Object 'System.Collections.Generic.List[string]'
        foreach ($k in $Value.Keys) { $parts.Add((Format-JsonString ([string]$k)) + ':' + (ConvertTo-LmJson $Value[$k])) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $parts = New-Object 'System.Collections.Generic.List[string]'
        foreach ($x in $Value) { $parts.Add((ConvertTo-LmJson $x)) }
        return '[' + ($parts -join ',') + ']'
    }
    return (Format-JsonString ([string]$Value))
}

function Add-Reason([string]$Code) { [void]$script:Reasons.Add($Code) }

# ── 입력 제어 줄 _in(계약 §7.3) ─────────────────────────────────────────────
function Read-InControl {
    $res = @{ cursor = $null; cfg = $null; self_names = $null; given = $false }
    $redirected = $false
    try { $redirected = [Console]::IsInputRedirected } catch { $redirected = $false }
    if (-not $redirected) { return $res }
    $line = $null
    try {
        $sr = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), $script:Utf8)
        $line = $sr.ReadLine()
    } catch { $line = $null }
    if ($null -eq $line) { return $res }
    $line = $line.TrimStart([char]0xFEFF).Trim()
    if (-not $line) { return $res }
    try { $o = ConvertFrom-Json -InputObject $line } catch { $script:C.in_given = -1; return $res }
    if ($null -eq $o) { $script:C.in_given = -1; return $res }
    $p = $o.PSObject.Properties['_in']
    if ($null -eq $p -or $null -eq $p.Value) { $script:C.in_given = -1; return $res }
    $res.given = $true
    $script:C.in_given = 1
    foreach ($k in 'cursor', 'cfg', 'self_names') {
        $q = $p.Value.PSObject.Properties[$k]
        if ($null -ne $q) { $res[$k] = $q.Value }
    }
    return $res
}

function Get-CfgRaw($Cfg, [string]$Key) {
    if ($null -eq $Cfg) { return $null }
    $p = $Cfg.PSObject.Properties[$Key]
    if ($null -eq $p) { return $null }
    return $p.Value
}

function Get-CfgInt($Cfg, [string]$Key, [int]$Default, [int]$Min, [int]$Max) {
    $v = Get-CfgRaw $Cfg $Key
    if ($null -eq $v -or $v -is [bool] -or $v -is [string]) { return $Default }
    try { $d = [double]$v } catch { return $Default }
    if ([double]::IsNaN($d) -or $d -ne [Math]::Floor($d) -or $d -lt $Min -or $d -gt $Max) { return $Default }
    return [int]$d
}

function Get-CfgBool($Cfg, [string]$Key, [bool]$Default) {
    $v = Get-CfgRaw $Cfg $Key
    if ($v -is [bool]) { return $v }
    return $Default
}

function Get-CfgString($Cfg, [string]$Key, [string]$Default) {
    $v = Get-CfgRaw $Cfg $Key
    if ($v -is [string]) { return $v }
    return $Default
}

# ── 본인 이름 집합(CT §4.4 — 호출자가 넘긴 값만, X-306) ──────────────────────
$script:FixedSelf = @('나', '본인', 'you', 'me')

function Get-NameNorm([string]$Name) {
    if ($null -eq $Name) { return '' }
    return $Name.Normalize([System.Text.NormalizationForm]::FormKC).Trim().ToLowerInvariant()
}

function Add-NameVariants($Set, [string]$Norm) {
    $a = $Norm
    $b = $Norm -replace '\s+', ''
    $c = ($Norm -replace '\s*(님|씨)$', '').Trim()
    $d = $c -replace '\s+', ''
    foreach ($y in @($a, $b, $c, $d)) { if ($y) { [void]$Set.Add($y) } }
}

function New-SelfSet($Names) {
    $set = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $fixed = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($x in $script:FixedSelf) { Add-NameVariants $fixed $x; Add-NameVariants $set $x }
    $given = 0
    if ($null -ne $Names) {
        foreach ($x in @($Names)) {
            if ($null -eq $x -or -not ($x -is [string])) { continue }
            $v = Get-NameNorm $x
            if (-not $v) { continue }
            if (-not $fixed.Contains($v)) { $given++ }
            Add-NameVariants $set $v
        }
    }
    return @{ set = $set; given = $given }
}

function Test-Self([string]$Name) {
    if (-not $Name) { return $false }
    $tmp = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    Add-NameVariants $tmp (Get-NameNorm $Name)
    foreach ($c in $tmp) { if ($script:SelfSet.Contains($c)) { return $true } }
    return $false
}

function Resolve-IsMe([string]$Name) {
    # 표시명 집합 단계(CT §4.1 ③). 이름 집합이 없으면(R-NOADDR) 이 단계를 건너뛰어 미상(null)으로 둔다.
    if (Test-Self $Name) { return $true }
    if ($script:SelfGiven -gt 0) { return $false }
    return $null
}

# ── 시각·날짜(지역 설정에서 자동 구성 — LM24 계승, CT §7.3) ─────────────────
$script:Ci = Get-Culture
$amD = [string]$script:Ci.DateTimeFormat.AMDesignator
$pmD = [string]$script:Ci.DateTimeFormat.PMDesignator
$script:PmSet = @('오후', 'PM', 'pm', 'p.m.', 'P.M.', '午後', '下午', 'nachm.')
if ($pmD) { $script:PmSet += $pmD }
$script:AmSet = @('오전', 'AM', 'am', 'a.m.', 'A.M.', '午前', '上午', 'vorm.')
if ($amD) { $script:AmSet += $amD }
$desig = (($script:AmSet + $script:PmSet) | Where-Object { $_ } | Select-Object -Unique |
    Sort-Object -Property @{ Expression = { $_.Length }; Descending = $true } |
    ForEach-Object { [regex]::Escape($_) }) -join '|'
$sepRe = ':'
if ($script:Ci.DateTimeFormat.ShortTimePattern -match '\.') { $sepRe = '[:.]' }
# 숫자 앞뒤 경계는 \b 가 아니라 '숫자 아님' — '午後2:10' 처럼 CJK 글자 바로 뒤 숫자(LM24 실측)
$script:ReTimeCulture = '(?:(' + $desig + ')\s*)?(?<!\d)(\d{1,2})' + $sepRe + '(\d{2})(?!\d)(?:\s*(' + $desig + '))?'
$script:ReTimeGeneric = '()?(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)()?'
$script:DayFirst = [bool]($script:Ci.DateTimeFormat.ShortDatePattern -match '^d')
$script:MonC = @{}
if ($script:Ci.TwoLetterISOLanguageName -notin @('en', 'ko')) {
    $nms = @($script:Ci.DateTimeFormat.AbbreviatedMonthNames) + @($script:Ci.DateTimeFormat.MonthNames)
    for ($i = 0; $i -lt $nms.Count; $i++) {
        $nm = [string]$nms[$i]
        if ($nm -and $nm.Length -ge 2 -and $nm -notmatch '^\d') { $script:MonC[$nm.ToLower()] = ($i % 12) + 1 }
    }
}
$script:ReMonC = ''
if ($script:MonC.Count) {
    $script:ReMonC = '(' + (($script:MonC.Keys | Sort-Object { -1 * $_.Length } | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')'
}
# 영문 월 이름: 전체 철자 화이트리스트 + 대소문자 구분 — 'Mark'·'Mary'·'separate' 를 3월·9월로 오인하지 않게(LM24 검증)
$script:ReMon = '(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
$script:Mon = @{ jan = 1; feb = 2; mar = 3; apr = 4; may = 5; jun = 6; jul = 7; aug = 8; sep = 9; oct = 10; nov = 11; dec = 12 }
$script:Dow = @{}
$fixedDays = @(
    @('일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'),
    @('sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'),
    @('sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'),
    @('sun', 'mon', 'tues', 'wed', 'thur', 'fri', 'sat'),
    @('sun', 'mon', 'tues', 'wed', 'thurs', 'fri', 'sat'),
    @('日曜日', '月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日'),
    @('日曜', '月曜', '火曜', '水曜', '木曜', '金曜', '土曜'),
    @('星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'),
    @('周日', '周一', '周二', '周三', '周四', '周五', '周六'))
foreach ($arr in $fixedDays) { for ($i = 0; $i -lt 7; $i++) { $script:Dow[$arr[$i]] = $i } }
foreach ($arr in @(, @($script:Ci.DateTimeFormat.DayNames)) + @(, @($script:Ci.DateTimeFormat.AbbreviatedDayNames))) {
    for ($i = 0; $i -lt 7 -and $i -lt $arr.Count; $i++) {
        $nm = ([string]$arr[$i]).Trim().ToLower()
        if ($nm.Length -ge 2 -and -not $script:Dow.ContainsKey($nm)) { $script:Dow[$nm] = $i }
    }
}
$dowAlt = ($script:Dow.Keys | Sort-Object { -1 * $_.Length } | ForEach-Object { [regex]::Escape($_) }) -join '|'
$script:ReDow = '(?<![\p{L}])(' + $dowAlt + ')(?:에|에는)?(?![\p{L}])[\s,:·-]*(?:at\s+)?$'
$script:ReDowAny = '(?<![\p{L}])(?:' + $dowAlt + ')(?![\p{L}])|\((?:일|월|화|수|목|금|토)\)'
$script:ReToday = '(?<![\p{L}])(오늘|today|今日|今天)(?:에|에는)?(?![\p{L}])'
$script:ReYesterday = '(?<![\p{L}])(어제|yesterday|昨日|昨天)(?:에|에는)?(?![\p{L}])'
$script:RxOpt = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
$script:RxTimeout = [TimeSpan]::FromMilliseconds(250)

function New-Rx([string]$Pattern, [bool]$IgnoreCase = $true) {
    $opt = [System.Text.RegularExpressions.RegexOptions]::None
    if ($IgnoreCase) { $opt = $script:RxOpt }
    return (New-Object System.Text.RegularExpressions.Regex($Pattern, $opt, $script:RxTimeout))
}

function Get-Match($Rx, [string]$Text) {
    # 정규식 시간 초과(설정 정규식의 병적 역추적 방어)는 '불일치'로 본다
    try { return $Rx.Match($Text) } catch { return [System.Text.RegularExpressions.Match]::Empty }
}

$script:RxDateYmd = New-Rx '(?<!\d)(\d{4})\s*[.년年/-]\s*(\d{1,2})\s*[.월月/-]\s*(\d{1,2})\s*[.일日]?(?!\d)'
$script:RxDateKo = New-Rx '(?<!\d)(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]'
$script:RxDateNum = New-Rx '(?<!\d)(\d{1,2})\s?[/.]\s?(\d{1,2})\.?(?!\d)'
$script:RxDayMonEn = New-Rx ('\b(\d{1,2})\s+' + $script:ReMon + '\b') $false
$script:RxMonDayEn = New-Rx ('\b' + $script:ReMon + '\.?\s+(\d{1,2})\b') $false
$script:RxDayMonC = $null
$script:RxMonDayC = $null
if ($script:ReMonC) {
    $script:RxDayMonC = New-Rx ('\b(\d{1,2})\.?\s*' + $script:ReMonC + '\b')
    $script:RxMonDayC = New-Rx ('\b' + $script:ReMonC + '\.?\s+(\d{1,2})\b')
}
$script:RxYesterday = New-Rx $script:ReYesterday
$script:RxToday = New-Rx $script:ReToday
$script:RxDow = New-Rx $script:ReDow
$script:RxDowAny = New-Rx $script:ReDowAny
$script:RxYearLeft = New-Rx '(?<!\d)(19|20)\d{2}\s*[년年]?(?!\d)'

function Get-DayOf([int]$Month, [int]$Day, [datetime]$Ref) {
    # 연도 없는 월/일 → 기준일 이전(포함) 가장 최근의 그 날짜. 잘못된 날짜(2/30)는 무시
    try { $x = New-Object DateTime($Ref.Year, $Month, $Day) } catch { return $null }
    if ($x -gt $Ref.Date) { try { $x = New-Object DateTime(($Ref.Year - 1), $Month, $Day) } catch { return $null } }
    return $x
}

function Find-HeaderDate([string]$Pre, [datetime]$Ref) {
    # 시각 앞(머리말) 문자열에서 날짜 토큰 하나 → @{date; idx; len; est}. est = 날짜 표기 없음.
    $r = @{ date = $null; idx = -1; len = 0; est = $true }
    $m = Get-Match $script:RxDateYmd $Pre
    if ($m.Success) {
        try { $x = New-Object DateTime([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value) } catch { $x = $null }
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = Get-Match $script:RxDateKo $Pre
    if ($m.Success) {
        $x = Get-DayOf ([int]$m.Groups[1].Value) ([int]$m.Groups[2].Value) $Ref
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = Get-Match $script:RxDateNum $Pre
    if ($m.Success) {
        # 8/15(월/일) 또는 15.08(일.월) — 이 PC 의 날짜 순서를 따르되 12 초과 숫자로 보정
        $a = [int]$m.Groups[1].Value; $b = [int]$m.Groups[2].Value
        $mo = $a; $dd = $b
        if ($script:DayFirst) { $mo = $b; $dd = $a }
        if ($mo -gt 12 -and $dd -le 12) { $t0 = $mo; $mo = $dd; $dd = $t0 }
        if ($mo -ge 1 -and $mo -le 12 -and $dd -ge 1 -and $dd -le 31) {
            $x = Get-DayOf $mo $dd $Ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
    }
    if ($null -ne $script:RxDayMonC) {
        $m = Get-Match $script:RxDayMonC $Pre
        if ($m.Success) {
            $x = Get-DayOf $script:MonC[$m.Groups[2].Value.ToLower()] ([int]$m.Groups[1].Value) $Ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
        $m = Get-Match $script:RxMonDayC $Pre
        if ($m.Success) {
            $x = Get-DayOf $script:MonC[$m.Groups[1].Value.ToLower()] ([int]$m.Groups[2].Value) $Ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
    }
    $m = Get-Match $script:RxDayMonEn $Pre
    if ($m.Success) {
        $x = Get-DayOf $script:Mon[$m.Groups[2].Value.Substring(0, 3).ToLower()] ([int]$m.Groups[1].Value) $Ref
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = Get-Match $script:RxMonDayEn $Pre
    if ($m.Success) {
        $x = Get-DayOf $script:Mon[$m.Groups[1].Value.Substring(0, 3).ToLower()] ([int]$m.Groups[2].Value) $Ref
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = Get-Match $script:RxYesterday $Pre
    if ($m.Success) { $r.date = $Ref.Date.AddDays(-1); $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    $m = Get-Match $script:RxToday $Pre
    if ($m.Success) { $r.date = $Ref.Date; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    $m = Get-Match $script:RxDow $Pre
    if ($m.Success) {
        # 요일 → 가장 최근 그 요일. Teams 는 오늘은 시각만·어제는 '어제'·그 전 6일은 요일이므로 같은 요일 = 7일 전
        $key = $m.Groups[1].Value.ToLower()
        if ($script:Dow.ContainsKey($key)) {
            $delta = ([int]$Ref.DayOfWeek - [int]$script:Dow[$key] + 7) % 7
            if ($delta -eq 0) { $delta = 7 }
            $r.date = $Ref.Date.AddDays(-$delta); $r.idx = $m.Index; $r.len = $m.Groups[1].Length; $r.est = $false
            return $r
        }
    }
    return $r
}

function Get-Separator([string]$Text) {
    # 날짜 구분선 — 날짜 토큰(+요일·괄호·구두점)만 있는 줄이면 그 날짜, 아니면 $null
    $s = $Text.Trim()
    if ($s.Length -lt 2 -or $s.Length -gt 40) { return $null }
    $fd = Find-HeaderDate $s $script:Today
    if ($fd.est) { return $null }
    $rest = $s.Remove($fd.idx, $fd.len)
    $rest = $script:RxDowAny.Replace($rest, ' ')
    $rest = $script:RxYearLeft.Replace($rest, ' ')
    $rest = $rest -replace '[\s,.·\-()\[\]]+', ''
    if ($rest -eq '') { return $fd.date }
    return $null
}

# ── 방(대화방)·창 구조 단서 ─────────────────────────────────────────────────
$script:SectionWords = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach ($x in @('채팅', 'chat', '활동', 'activity', '팀', 'teams', 'team', '일정', 'calendar', '통화', 'calls', '파일',
        'files', '모임', 'meet', '앱', 'apps', '커뮤니티', 'communities', 'onedrive', '도움말', 'help')) {
    [void]$script:SectionWords.Add($x)
}
$script:RxSelfRoom = New-Rx '\((?:나|본인|you|me)\)'
$script:RxRoomLine1 = New-Rx '^(.{2,40})\s(채팅|대화|팀|채널|chat|team|channel)$'
$script:RxRoomLine2 = New-Rx '^(.{2,40}?)\s*[|·-]\s*Microsoft Teams$'
$script:RxCount = New-Rx '(?:참가자|참여자|구성원|participants?|people|members)\D{0,12}?(\d{1,4})(?!\d)|(?<!\d)(\d{1,4})\s*(?:명|participants|people|members)'
$script:RxChannelCue = New-Rx '^(?:게시물|posts|채널 정보|channel info)$'
$script:RxMeetingCue = New-Rx '^(?:모임 채팅|meeting chat|모임 노트|meeting notes|회의 채팅|참가|join)$'
$script:CueTypes = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach ($x in @('Button', 'SplitButton', 'MenuItem', 'TabItem', 'Hyperlink', 'Header', 'HeaderItem')) { [void]$script:CueTypes.Add($x) }
$script:CtlTypes = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach ($x in @('Button', 'SplitButton', 'MenuItem', 'TabItem', 'Hyperlink', 'CheckBox', 'RadioButton', 'ComboBox', 'Edit')) {
    [void]$script:CtlTypes.Add($x)
}
$script:RxFileExt = '(?:docx?|docm|xlsx?|xlsm|xlsb|pptx?|pptm|pdf|hwpx?|txt|csv|zip|7z|png|jpe?g|gif|bmp|dwg|dxf|stp|step|igs|iges|prt|asm|drw|sldprt|sldasm|vsdx?|mpp|msg|eml|xml|json|log|mp4|wav)'
$script:RxFileInBody = New-Rx ('(?<![\w.])([^\s\\/:*?"<>|,]{1,120}\.' + $script:RxFileExt + ')(?![\w])')
$script:RxFileCard = New-Rx ('^(?:(?:첨부 ?파일|파일|file|attachment)\s*[:,]\s*)?([^\\/:*?"<>|]{1,150}\.' + $script:RxFileExt + ')$')
$script:RxMention = New-Rx '(?:mentioned you|멘션했|님을 언급|님이 언급|님을 멘션)'
$script:RxAuthor = '^\s*([\p{L}0-9 .]{2,20}?)\s*,?\s*(?:님이|says|said|wrote)?\s*[,:·-]?\s*$'
$script:RxNotAuthor = New-Rx '(?:니다|세요|어요|아요|해요|네요|군요|에요|예요|죠|까요|나요|래요|게요)$'
$script:RxAttachedParticle = New-Rx '^\s*(?:에는|에|까지|부터|경|쯤)(?![\p{L}\p{N}])'

function Get-TitleNorm([string]$Name) {
    if (-not $Name) { return '' }
    $v = $Name.Normalize([System.Text.NormalizationForm]::FormKC).ToLowerInvariant()
    $v = ($v -replace '\s+', ' ').Trim()
    if ($v.Length -gt 120) { $v = $v.Substring(0, 120) }
    return $v
}

function Get-RoomFromTitle([string]$Title) {
    # 창 제목 'Section | 방 이름 | … | Microsoft Teams' → 방 이름(섹션 낱말·'Microsoft Teams'·주소 모양 조각 제외)
    $res = @{ name = ''; self = $false }
    if (-not $Title) { return $res }
    if ((Get-Match $script:RxSelfRoom $Title).Success) { $res.self = $true }
    foreach ($part in ($Title -split '\|')) {
        $p = $part.Trim()
        if (-not $p) { continue }
        if ($p -match 'Microsoft Teams') { continue }
        if ($p.Contains('@')) { continue }
        if ($script:SectionWords.Contains($p)) { continue }
        $res.name = ($script:RxSelfRoom.Replace($p, '')).Trim()
        break
    }
    return $res
}

function Get-RoomHeader([string]$Text) {
    $m = Get-Match $script:RxRoomLine1 $Text
    if ($m.Success) { return $m.Groups[1].Value.Trim() }
    $m = Get-Match $script:RxRoomLine2 $Text
    if ($m.Success) { return $m.Groups[1].Value.Trim() }
    return $null
}

function Use-Room([string]$Name, [bool]$SelfFlag, $Cues) {
    $norm = Get-TitleNorm ($script:RxSelfRoom.Replace([string]$Name, ''))
    $id = 'uia:unknown'
    if ($norm) { $id = 'uia:' + $norm }
    if (-not $script:Rooms.Contains($id)) {
        $script:Rooms[$id] = @{
            id = $id; title = ($script:RxSelfRoom.Replace([string]$Name, '')).Trim(); self = $SelfFlag
            count = $null; channel = $false; meeting = $false
            authors = (New-Object 'System.Collections.Generic.SortedSet[string]' ([System.StringComparer]::Ordinal))
        }
    }
    $room = $script:Rooms[$id]
    if ($SelfFlag) { $room.self = $true }
    if ($null -ne $Cues) {
        if ($null -ne $Cues.count -and ($null -eq $room.count -or $Cues.count -gt $room.count)) { $room.count = $Cues.count }
        if ($Cues.channel) { $room.channel = $true }
        if ($Cues.meeting) { $room.meeting = $true }
    }
    return $room
}

function Get-WindowCues($Lines) {
    # 창 구조 단서 — 단추·탭 같은 컨트롤 요소의 이름에서만(본문 텍스트에서 찾지 않는다)
    $cues = @{ count = $null; channel = $false; meeting = $false }
    foreach ($ln in $Lines) {
        if ($ln.skipped -or -not $script:CueTypes.Contains([string]$ln.type)) { continue }
        $t = $ln.text.Trim()
        if ((Get-Match $script:RxChannelCue $t).Success) { $cues.channel = $true; continue }
        if ((Get-Match $script:RxMeetingCue $t).Success) { $cues.meeting = $true; continue }
        $m = Get-Match $script:RxCount $t
        if ($m.Success) {
            $v = $m.Groups[1].Value
            if (-not $v) { $v = $m.Groups[2].Value }
            $n = [int]$v
            if ($n -ge 1 -and $n -le 10000 -and ($null -eq $cues.count -or $n -gt $cues.count)) { $cues.count = $n }
        }
    }
    return $cues
}

# ── 채팅 목록 열 제외(LM24 Get-ListColumn 계승 + LM22 회귀 가드) ─────────────
function Get-ListColumn($Lines, $Win) {
    # 목록 열 = 창 왼쪽 25% 안에서 시작하고 왼쪽 45% 안에서 끝남, 항목 3개 이상, 넓은 메시지 항목이 하나라도
    # 보일 때만. 후보가 여럿이면 '가장 많은' 것이 아니라 **가장 왼쪽**(LM22 사고: 메시지 열을 목록으로 오인).
    if (-not $Win.hasRect -or $Win.W -le 0) { return $null }
    $wide = 0
    $groups = @{}
    foreach ($ln in $Lines) {
        if (-not $ln.hasRect -or [string]$ln.type -ne 'ListItem' -or $ln.W -le 0) { continue }
        if ($ln.W -ge 0.45 * $Win.W) { $wide++; continue }
        $k = [int][Math]::Round(($ln.L - $Win.L) / 24.0)
        if (-not $groups.ContainsKey($k)) { $groups[$k] = New-Object 'System.Collections.Generic.List[object]' }
        $groups[$k].Add($ln)
    }
    if ($wide -eq 0) { return $null }
    $best = $null; $bl = 0.0; $br = 0.0
    foreach ($g in $groups.Values) {
        if ($g.Count -lt 3) { continue }
        $l = [double]::MaxValue; $rg = [double]::MinValue
        foreach ($r in $g) { if ($r.L -lt $l) { $l = $r.L }; if (($r.L + $r.W) -gt $rg) { $rg = $r.L + $r.W } }
        if (($l - $Win.L) -gt 0.25 * $Win.W) { continue }
        if (($rg - $Win.L) -ge 0.45 * $Win.W) { continue }
        if ($null -eq $best -or $l -lt $bl) { $best = $g; $bl = $l; $br = $rg }
    }
    if ($null -eq $best) { return $null }
    return @{ left = $bl; right = $br; n = $best.Count }
}

function Test-RightAligned($Ln, $Win) {
    # 작성자 생략 + 오른쪽 정렬(내 쪽 말풍선) — 좁은 요소가 창 오른쪽 절반에서 시작해 오른쪽 끝 10% 안에서 끝남
    if (-not $Ln.hasRect -or -not $Win.hasRect -or $Win.W -le 0 -or $Ln.W -le 0) { return $false }
    $left = $Ln.L - $Win.L
    $right = $left + $Ln.W
    return ($left -gt 0.5 * $Win.W -and $right -ge 0.9 * $Win.W -and $Ln.W -lt 0.6 * $Win.W)
}

function Add-FileName($Row, [string]$Name) {
    $n = $Name.Trim()
    if (-not $n -or $Row.files.Count -ge 10) { return }
    foreach ($f in $Row.files) { if ($f -eq $n) { return } }
    $Row.files.Add($n)
}

function Test-MentionsMe([string]$Body) {
    if ((Get-Match $script:RxMention $Body).Success) { return $true }
    $low = $Body.Normalize([System.Text.NormalizationForm]::FormKC).ToLowerInvariant()
    if (-not $low.Contains('@')) { return $false }
    foreach ($n in $script:SelfSet) {
        if ($n.Length -lt 2 -or $script:FixedSelf -contains $n) { continue }
        if ($low.Contains('@' + $n)) { return $true }
    }
    return $false
}

# ── 한 창의 줄 → 메시지(머리말/본문 분리 · 날짜 구분선 · 연속 메시지 상속) ──────────
function Invoke-ParseLines($Win, $Lines, $Rx, $Cues) {
    $rows = New-Object 'System.Collections.Generic.List[object]'
    $n = 0
    $room = Use-Room $Win.roomName $Win.roomSelf $Cues
    $ctxDate = $null
    $last = $null
    foreach ($ln in $Lines) {
        $t = $ln.text
        $tm = Get-Match $Rx $t
        if (-not $tm.Success) {
            # 방 머리·날짜 구분선은 글 요소에서만 — '모임 채팅'·'오늘' 같은 단추·탭 이름을 방·날짜로 보지 않는다
            $isCtl = $script:CtlTypes.Contains([string]$ln.type)
            $hdr = $null
            if (-not $isCtl) { $hdr = Get-RoomHeader $t }
            if ($null -ne $hdr) {
                $room = Use-Room $hdr ((Get-Match $script:RxSelfRoom $hdr).Success) $Cues
                $ctxDate = $null; $last = $null
                continue
            }
            $sep = $null
            if (-not $isCtl) { $sep = Get-Separator $t }
            if ($null -ne $sep) { $ctxDate = $sep; $last = $null; continue }
            if ($null -ne $last -and $null -ne $last.row) {
                $fm = Get-Match $script:RxFileCard $t.Trim()
                if ($fm.Success) { Add-FileName $last.row $fm.Groups[1].Value }
            }
            continue
        }
        $n++
        $hh = [int]$tm.Groups[2].Value
        $mm = [int]$tm.Groups[3].Value
        $ap = ''
        foreach ($g in @($tm.Groups[1].Value, $tm.Groups[4].Value)) {
            if ($g) { if ($script:PmSet -contains $g) { $ap = 'PM' } elseif ($script:AmSet -contains $g) { $ap = 'AM' } }
        }
        if ($ap -eq 'PM' -and $hh -lt 12) { $hh += 12 }
        if ($ap -eq 'AM' -and $hh -eq 12) { $hh = 0 }
        if ($hh -gt 23 -or $mm -gt 59) { continue }
        $pre = $t.Substring(0, $tm.Index)
        $postRaw = $t.Substring($tm.Index + $tm.Length)
        if ((Get-Match $script:RxAttachedParticle $postRaw).Success) { continue }   # '3:00 에'·'8:30 까지' = 본문 속 시각
        # 머리말(시각 앞)에서만 날짜·작성자를 찾는다 — 본문의 '8/15 까지'는 날짜가 아니다
        $fd = Find-HeaderDate $pre $script:Today
        $preClean = $pre
        if ($fd.idx -ge 0) {
            $preClean = $pre.Substring(0, $fd.idx) + ' ' + $pre.Substring($fd.idx + $fd.len)
            $preClean = $script:RxYearLeft.Replace($preClean, ' ')
        }
        $from = ''
        if ($preClean -match $script:RxAuthor) {
            $cand = $Matches[1].Trim()
            if (-not (Get-Match $script:RxNotAuthor $cand).Success -and $cand -notmatch '^[\d .]+$') { $from = $cand }
        }
        $rest = $preClean
        if ($from) { $rest = $rest -replace ('^\s*' + [regex]::Escape($from) + '\s*,?\s*(?:님이|says|said|wrote)?\s*[,:·-]?'), '' }
        $post = $postRaw -replace '^\s*[,:·|-]*\s*', ''
        $body = (($rest.Trim() + ' ' + $post) -replace '\s{2,}', ' ').Trim()
        if (-not $body) { continue }
        if (-not $from -and $body.Length -lt 2) { continue }
        if (-not $fd.est) { $d = $fd.date; $prec = 'minute' }
        elseif ($null -ne $ctxDate) { $d = $ctxDate; $prec = 'minute' }
        else { $d = $null; $prec = 'unknown' }
        $author = $null; $isMe = $null; $inherited = $false
        if ($from) {
            $author = $from; $isMe = Resolve-IsMe $from
        } elseif (Test-RightAligned $ln $Win) {
            $isMe = $true
        } elseif ($null -ne $last) {
            $author = $last.author; $isMe = $last.isMe; $inherited = $true
        }
        $row = @{
            room = $room; author = $author; isMe = $isMe; inherited = $inherited; prec = $prec; body = $body
            date = $d; hh = $hh; mm = $mm; mentions = (Test-MentionsMe $body)
            files = (New-Object 'System.Collections.Generic.List[string]')
        }
        try { foreach ($fm in $script:RxFileInBody.Matches($body)) { Add-FileName $row $fm.Groups[1].Value } } catch { }
        if ($author -and $isMe -ne $true) { [void]$room.authors.Add($author) }
        $rows.Add($row)
        if ($inherited) { $last.row = $row }
        else { $last = @{ author = $author; isMe = $isMe; row = $row } }
    }
    return @{ rows = $rows; n = $n }
}

function Invoke-Window($Win) {
    # 판독한 창 하나 → 행 목록. 목록 열 제외 → 지역 시각 정규식 → (0줄이면) 제외 되돌림 → 일반 형식 재시도
    $lines = New-Object 'System.Collections.Generic.List[object]'
    foreach ($it in $Win.items) {
        $nm = [string]$it.Name
        if (-not $nm) { continue }
        $nm = ($nm -replace '[\r\n\t]+', ' ').Trim()
        if ($nm.Length -lt 2 -or $nm.Length -gt 1000) { continue }
        $lines.Add(@{ text = $nm; type = [string]$it.Type; hasRect = [bool]$it.HasRect; L = [double]$it.L; W = [double]$it.W; skipped = $false })
    }
    $col = $null
    if (-not $KeepChatList) { $col = Get-ListColumn $lines $Win }
    if ($null -ne $col) {
        foreach ($ln in $lines) {
            if ($ln.hasRect -and $ln.W -gt 0 -and $ln.W -lt 0.45 * $Win.W) {
                $cx = $ln.L + $ln.W / 2
                if ($cx -ge $col.left -and $cx -le $col.right) { $ln.skipped = $true }
            }
        }
    }
    $kept = New-Object 'System.Collections.Generic.List[object]'
    $all = New-Object 'System.Collections.Generic.List[object]'
    $seenK = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $seenA = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $nSkip = 0
    foreach ($ln in $lines) {
        if ($seenA.Add($ln.text)) { $all.Add($ln) }
        if ($ln.skipped) { $nSkip++; continue }
        if ($seenK.Add($ln.text)) { $kept.Add($ln) }
    }
    $script:C.lines += $kept.Count
    $script:C.list_skipped += $nSkip
    $cues = Get-WindowCues $kept
    $res = Invoke-ParseLines $Win $kept $script:RxTime $cues
    if ($res.n -eq 0 -and $nSkip -gt 0) {
        # 안전 밸브 — 목록으로 보고 뺐는데 남은 줄에 시각이 0줄이면 그 판정이 틀렸다(LM22). 원래 순서로 되돌려 다시 읽는다
        $script:C.list_restored += $nSkip
        $kept = $all
        $res = Invoke-ParseLines $Win $kept $script:RxTime $cues
    }
    if ($res.n -eq 0 -and -not $script:CfgRegex -and $kept.Count -gt 0) {
        # 지역 설정 형식으로 0줄 — Teams 표시 언어가 Windows 지역과 다를 수 있다. 일반 형식(숫자:숫자 / 숫자.숫자)
        $res2 = Invoke-ParseLines $Win $kept $script:RxTimeGeneric $cues
        if ($res2.n -gt 0) { $script:C.generic++; $res = $res2 }
    }
    $script:C.time_lines += $res.n
    return $res.rows
}

# ── 창 열거·판독: 실제(UIA) 또는 시험 주입(-RawFile) ───────────────────────────
$script:UiaSource = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Automation;

namespace Lm27Teams
{
    public class WinInfo
    {
        public IntPtr Hwnd; public int Pid; public string Title; public string ClassName;
        public bool Visible; public bool Iconic; public bool OnScreen; public bool Cloaked; public bool Tool;
    }

    public class UiaItem
    {
        public string Name; public string Type; public bool HasRect; public double L; public double T; public double W; public double H;
    }

    public class UiaRead
    {
        public List<UiaItem> Items = new List<UiaItem>();
        public bool TimedOut; public bool Capped; public string Error; public int Total;
        public bool HasRect; public double L; public double T; public double W; public double H;
    }

    public static class Native
    {
        private delegate bool EnumProc(IntPtr hwnd, IntPtr lparam);
        [StructLayout(LayoutKind.Sequential)] private struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
        [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc cb, IntPtr lparam);
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr hwnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowTextLength(IntPtr hwnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr hwnd, StringBuilder sb, int max);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr hwnd, StringBuilder sb, int max);
        [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hwnd, out RECT rc);
        [DllImport("user32.dll")] private static extern int GetSystemMetrics(int index);
        [DllImport("user32.dll", EntryPoint = "GetWindowLongW")] private static extern int GetWindowLong(IntPtr hwnd, int index);
        [DllImport("dwmapi.dll")] private static extern int DwmGetWindowAttribute(IntPtr hwnd, int attr, out int value, int size);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
        [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr h);
        [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
        [DllImport("advapi32.dll", SetLastError = true)] private static extern bool GetTokenInformation(IntPtr token, int cls, out int info, int len, out int ret);

        public static List<WinInfo> TopWindows(int[] pids)
        {
            Dictionary<uint, bool> want = new Dictionary<uint, bool>();
            foreach (int p in pids) { want[(uint)p] = true; }
            List<WinInfo> list = new List<WinInfo>();
            int vx = GetSystemMetrics(76), vy = GetSystemMetrics(77), vw = GetSystemMetrics(78), vh = GetSystemMetrics(79);
            EnumProc cb = delegate (IntPtr h, IntPtr l)
            {
                uint pid;
                GetWindowThreadProcessId(h, out pid);
                if (!want.ContainsKey(pid)) { return true; }
                WinInfo w = new WinInfo();
                w.Hwnd = h; w.Pid = (int)pid;
                int len = GetWindowTextLength(h);
                StringBuilder sb = new StringBuilder(Math.Max(len, 0) + 2);
                GetWindowText(h, sb, sb.Capacity);
                w.Title = sb.ToString();
                StringBuilder cn = new StringBuilder(260);
                GetClassName(h, cn, cn.Capacity);
                w.ClassName = cn.ToString();
                w.Visible = IsWindowVisible(h);
                w.Iconic = IsIconic(h);
                w.Tool = (GetWindowLong(h, -20) & 0x80) != 0;
                try { int cl; if (DwmGetWindowAttribute(h, 14, out cl, 4) == 0) { w.Cloaked = cl != 0; } } catch (Exception) { }
                RECT rc;
                if (GetWindowRect(h, out rc))
                {
                    int ix = Math.Min(rc.Right, vx + vw) - Math.Max(rc.Left, vx);
                    int iy = Math.Min(rc.Bottom, vy + vh) - Math.Max(rc.Top, vy);
                    w.OnScreen = ix > 0 && iy > 0;
                }
                list.Add(w);
                return true;
            };
            EnumWindows(cb, IntPtr.Zero);
            GC.KeepAlive(cb);
            return list;
        }

        // 1 = 권한 상승 프로세스, 0 = 아님, -1 = 알 수 없음(토큰 조회 거부 — 대개 상승된 프로세스)
        public static int Elevation(int pid)
        {
            IntPtr hp = OpenProcess(0x1000, false, (uint)pid);
            if (hp == IntPtr.Zero) { return -1; }
            try
            {
                IntPtr tok;
                if (!OpenProcessToken(hp, 0x0008, out tok)) { return -1; }
                try
                {
                    int e, ret;
                    if (!GetTokenInformation(tok, 20, out e, 4, out ret)) { return -1; }
                    return e != 0 ? 1 : 0;
                }
                finally { CloseHandle(tok); }
            }
            finally { CloseHandle(hp); }
        }
    }

    public static class Reader
    {
        // 창 하나의 ContentView 요소(이름·컨트롤 종류·사각형)를 한 번의 캐시 요청으로 읽는다. timeoutMs 를 넘으면 버린다(창 워치독)
        public static UiaRead Read(IntPtr hwnd, int max, int timeoutMs)
        {
            Task<UiaRead> task = Task.Run<UiaRead>(delegate () { return ReadCore(hwnd, max); });
            UiaRead r;
            try
            {
                if (!task.Wait(timeoutMs)) { r = new UiaRead(); r.TimedOut = true; return r; }
                return task.Result;
            }
            catch (AggregateException ae)
            {
                r = new UiaRead();
                Exception inner = ae.InnerException != null ? ae.InnerException : ae;
                r.Error = inner.GetType().Name;
                return r;
            }
        }

        private static UiaRead ReadCore(IntPtr hwnd, int max)
        {
            UiaRead r = new UiaRead();
            AutomationElement root = AutomationElement.FromHandle(hwnd);
            System.Windows.Rect rr = root.Current.BoundingRectangle;
            if (!rr.IsEmpty && !double.IsInfinity(rr.Width))
            {
                r.HasRect = true; r.L = rr.Left; r.T = rr.Top; r.W = rr.Width; r.H = rr.Height;
            }
            CacheRequest cr = new CacheRequest();
            cr.Add(AutomationElement.NameProperty);
            cr.Add(AutomationElement.ControlTypeProperty);
            cr.Add(AutomationElement.BoundingRectangleProperty);
            cr.TreeScope = TreeScope.Element;
            AutomationElementCollection all;
            using (cr.Activate())
            {
                all = root.FindAll(TreeScope.Descendants, Automation.ContentViewCondition);
            }
            r.Total = all.Count;
            int n = 0;
            foreach (AutomationElement e in all)
            {
                if (n >= max) { r.Capped = true; break; }
                n++;
                try
                {
                    UiaItem it = new UiaItem();
                    it.Name = e.Cached.Name ?? "";
                    ControlType ct = e.Cached.ControlType;
                    string tn = ct != null ? ct.ProgrammaticName : "";
                    it.Type = tn.StartsWith("ControlType.") ? tn.Substring(12) : tn;
                    System.Windows.Rect b = e.Cached.BoundingRectangle;
                    if (!b.IsEmpty && !double.IsInfinity(b.Width))
                    {
                        it.HasRect = true; it.L = b.Left; it.T = b.Top; it.W = b.Width; it.H = b.Height;
                    }
                    r.Items.Add(it);
                }
                catch (ElementNotAvailableException) { }
            }
            return r;
        }
    }
}
'@

function Initialize-UiaHelper {
    if ('Lm27Teams.Reader' -as [type]) { return }
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, WindowsBase
    $refs = @(
        [System.Windows.Automation.AutomationElement].Assembly.Location,
        [System.Windows.Automation.ControlType].Assembly.Location,
        [System.Windows.Rect].Assembly.Location)
    Add-Type -TypeDefinition $script:UiaSource -ReferencedAssemblies $refs -Language CSharp
}

$script:DenyClass = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
foreach ($x in @('IME', 'MSCTFIME UI', 'tooltips_class32', 'GDI+ Hook Window Class', 'Default IME')) { [void]$script:DenyClass.Add($x) }

function New-WinRecord {
    return @{
        live = $false; hwnd = [IntPtr]::Zero; title = ''; cls = ''; visible = $true; iconic = $false; on_screen = $true
        cloaked = $false; elev = 0; hang = $false; error = $null; readMs = 0; hasRect = $false; L = 0.0; T = 0.0; W = 0.0; H = 0.0
        items = (New-Object 'System.Collections.Generic.List[object]'); total = 0; capped = $false
        roomName = ''; roomSelf = $false
    }
}

function ConvertTo-Rect($Win, $Rect) {
    $a = @($Rect)
    if ($a.Count -ge 4) {
        $Win.hasRect = $true
        $Win.L = [double]$a[0]; $Win.T = [double]$a[1]; $Win.W = [double]$a[2]; $Win.H = [double]$a[3]
    }
}

function Get-JsonProp($Obj, [string]$Name, $Default) {
    if ($null -eq $Obj) { return $Default }
    $p = $Obj.PSObject.Properties[$Name]
    if ($null -eq $p -or $null -eq $p.Value) { return $Default }
    return $p.Value
}

function Read-RawFileSnapshot([string]$Path) {
    # 시험 주입(-RawFile) — 일반 텍스트(줄 = 요소 이름) 또는 JSON 창 스냅숏. 실제 창·UIA 는 건드리지 않는다
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw (New-Object System.IO.FileNotFoundException('RawFile')) }
    $text = [System.IO.File]::ReadAllText($Path, $script:Utf8)
    $snap = @{ procs = 0; windows = (New-Object 'System.Collections.Generic.List[object]') }
    if ($text.TrimStart([char]0xFEFF).TrimStart().StartsWith('{')) {
        $o = ConvertFrom-Json -InputObject ($text.TrimStart([char]0xFEFF))
        foreach ($w in @(Get-JsonProp $o 'windows' @())) {
            if ($null -eq $w) { continue }
            $win = New-WinRecord
            $win.title = [string](Get-JsonProp $w 'title' '')
            $win.cls = [string](Get-JsonProp $w 'class' '')
            $win.visible = [bool](Get-JsonProp $w 'visible' $true)
            $win.iconic = [bool](Get-JsonProp $w 'iconic' $false)
            $win.on_screen = [bool](Get-JsonProp $w 'on_screen' $true)
            $win.cloaked = [bool](Get-JsonProp $w 'cloaked' $false)
            if ([bool](Get-JsonProp $w 'elevated' $false)) { $win.elev = 1 }
            $win.hang = [bool](Get-JsonProp $w 'hang' $false)
            $win.readMs = [int](Get-JsonProp $w 'read_ms' 0)
            $err = Get-JsonProp $w 'error' $null
            if ($null -ne $err) { $win.error = [string]$err }
            ConvertTo-Rect $win (Get-JsonProp $w 'rect' @())
            foreach ($e in @(Get-JsonProp $w 'elements' @())) {
                if ($null -eq $e) { continue }
                $it = @{ Name = [string](Get-JsonProp $e 'name' ''); Type = [string](Get-JsonProp $e 'type' 'Text'); HasRect = $false; L = 0.0; T = 0.0; W = 0.0; H = 0.0 }
                $er = @(Get-JsonProp $e 'rect' @())
                if ($er.Count -ge 4) { $it.HasRect = $true; $it.L = [double]$er[0]; $it.T = [double]$er[1]; $it.W = [double]$er[2]; $it.H = [double]$er[3] }
                $win.items.Add($it)
            }
            $snap.windows.Add($win)
        }
        $pv = Get-JsonProp $o 'procs' $null
        if ($null -ne $pv) { $snap.procs = [int]$pv } elseif ($snap.windows.Count -gt 0) { $snap.procs = 1 }
    } else {
        $win = New-WinRecord
        foreach ($ln in ($text.TrimStart([char]0xFEFF) -split "`r?`n")) {
            if ($ln.Trim()) { $win.items.Add(@{ Name = $ln; Type = 'Text'; HasRect = $false; L = 0.0; T = 0.0; W = 0.0; H = 0.0 }) }
        }
        $snap.procs = 1
        $snap.windows.Add($win)
    }
    return $snap
}

function Get-LiveSnapshot {
    $snap = @{ procs = 0; windows = (New-Object 'System.Collections.Generic.List[object]') }
    $procs = @(Get-Process -Name 'ms-teams', 'Teams', 'msteams' -ErrorAction SilentlyContinue)
    $snap.procs = $procs.Count
    if ($procs.Count -eq 0) { return $snap }
    Initialize-UiaHelper
    $pids = [int[]]@($procs | ForEach-Object { $_.Id })
    $selfElev = [Lm27Teams.Native]::Elevation($PID)
    $elevBy = @{}
    foreach ($p in $pids) { $elevBy[$p] = [Lm27Teams.Native]::Elevation($p) }
    foreach ($w in [Lm27Teams.Native]::TopWindows($pids)) {
        if (-not $w.Title -or $w.Tool -or $script:DenyClass.Contains([string]$w.ClassName)) { continue }
        $win = New-WinRecord
        $win.live = $true; $win.hwnd = $w.Hwnd; $win.title = [string]$w.Title; $win.cls = [string]$w.ClassName
        $win.visible = [bool]$w.Visible; $win.iconic = [bool]$w.Iconic; $win.on_screen = [bool]$w.OnScreen; $win.cloaked = [bool]$w.Cloaked
        $e = $elevBy[$w.Pid]
        if ($selfElev -ne 1 -and $e -eq 1) { $win.elev = 1 } elseif ($selfElev -ne 1 -and $e -eq -1) { $win.elev = -1 }
        $snap.windows.Add($win)
    }
    return $snap
}

function Read-LiveWindow($Win, [int]$Max, [int]$TimeoutMs) {
    $r = [Lm27Teams.Reader]::Read($Win.hwnd, $Max, $TimeoutMs)
    $Win.hang = [bool]$r.TimedOut
    if ($r.Error) { $Win.error = [string]$r.Error }
    $Win.capped = [bool]$r.Capped
    $Win.total = [int]$r.Total
    if ($r.HasRect) { $Win.hasRect = $true; $Win.L = $r.L; $Win.T = $r.T; $Win.W = $r.W; $Win.H = $r.H }
    foreach ($it in $r.Items) { $Win.items.Add($it) }
}

# ── 본체 ───────────────────────────────────────────────────────────────────
function Get-UtcText([datetime]$Wall) {
    $dto = New-Object DateTimeOffset($Wall.Ticks, $script:Offset)
    return $dto.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv)
}

function ConvertFrom-UtcText($Text) {
    if (-not ($Text -is [string]) -or -not $Text) { return $null }
    $styles = [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor [System.Globalization.DateTimeStyles]::AssumeUniversal
    $d = [datetime]::MinValue
    if ([datetime]::TryParse($Text, $script:Inv, $styles, [ref]$d)) { return $d }
    return $null
}

function Get-DateArg([string]$Text) {
    if (-not $Text) { return $null }
    $d = [datetime]::MinValue
    if ([datetime]::TryParseExact($Text, 'yyyy-MM-dd', $script:Inv, [System.Globalization.DateTimeStyles]::None, [ref]$d)) { return $d.Date }
    return $null
}

function Invoke-Main {
    # 지금·수집 순간 오프셋(-TestNow 로 고정 가능)
    if ($TestNow) {
        $nowDto = [DateTimeOffset]::Parse($TestNow, $script:Inv, [System.Globalization.DateTimeStyles]::AssumeLocal)
    } else {
        $nowDto = [DateTimeOffset]::Now
    }
    $script:NowLocal = $nowDto.DateTime
    $script:Today = $script:NowLocal.Date
    $script:Offset = $nowDto.Offset
    $tot = [int][Math]::Round($script:Offset.TotalMinutes)
    $sign = '+'
    if ($tot -lt 0) { $sign = '-' }
    $abs = [Math]::Abs($tot)
    $script:OffText = '{0}{1}:{2}' -f $sign, ([int][Math]::Floor($abs / 60)).ToString('00', $script:Inv), ($abs % 60).ToString('00', $script:Inv)
    $observed = $nowDto.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv)
    $sinceD = Get-DateArg $Since
    $untilD = Get-DateArg $Until

    # 제어 줄 _in(설정·커서·본인 이름 — 명령줄에 싣지 않는다)
    $inp = Read-InControl
    $cfg = $inp.cfg
    # 범위 = 설정 레지스트리(계약 §5.2) — 범위 밖·형 불일치 값은 기본값
    $maxEl = Get-CfgInt $cfg 'teams.uia.maxElements' 4000 100 100000
    $wdSec = Get-CfgInt $cfg 'teams.uia.windowWatchdogSec' 15 1 120
    $budgetSec = Get-CfgInt $cfg 'teams.uia.budgetSec' 60 5 300
    $visibleOnly = Get-CfgBool $cfg 'teams.uia.visibleOnly' $true
    $script:CfgRegex = ''
    $cfgRe = Get-CfgString $cfg 'teams.timeRegex' ''
    $script:RxTime = New-Rx $script:ReTimeCulture
    $script:RxTimeGeneric = New-Rx $script:ReTimeGeneric
    if ($cfgRe) {
        try {
            $rx = New-Rx $cfgRe
            if ($rx.GetGroupNumbers().Count -ge 4) { $script:RxTime = $rx; $script:CfgRegex = $cfgRe; $script:C.cfg_regex = 1 }
            else { $script:C.cfg_regex = -1 }
        } catch { $script:C.cfg_regex = -1 }
    }
    $ss = New-SelfSet $inp.self_names
    $script:SelfSet = $ss.set
    $script:SelfGiven = $ss.given
    $script:C.self_given = $ss.given
    $prevTs = $null
    if ($null -ne $inp.cursor) {
        $script:PrevCursor = $inp.cursor
        $prevTs = ConvertFrom-UtcText (Get-JsonProp $inp.cursor 'last_ts_utc' $null)
    }

    # 창 열거
    if ($RawFile) { $snap = Read-RawFileSnapshot $RawFile } else { $snap = Get-LiveSnapshot }
    $script:C.procs = [int]$snap.procs
    $script:Rooms = [ordered]@{}
    $allRows = New-Object 'System.Collections.Generic.List[object]'
    $budgetMs = [long]$budgetSec * 1000
    $wdMs = $wdSec * 1000
    $readable = 0
    foreach ($win in $snap.windows) {
        $script:C.windows++
        $isVis = $win.visible -and -not $win.iconic -and $win.on_screen -and -not $win.cloaked
        if ($isVis) { $script:C.visible++ }
        if ($visibleOnly -and -not $isVis) { continue }
        if ($win.elev -eq 1) { $script:C.elevated++; Add-Reason 'R-UIAELEV'; continue }
        $readable++
        $left = $budgetMs - $script:Clock.ElapsedMilliseconds
        if ($budgetMs -gt 0 -and $left -le 0) { $script:C.budget_hit = 1; Add-Reason 'R-BUDGET'; break }
        # 창 워치독 = min(창당 상한, 남은 예산). 남은 예산이 자른 판독은 워치독 초과(R-CAP)가 아니라 예산 소진(R-BUDGET)
        $to = $wdMs
        $budgetCut = $false
        if ($budgetMs -gt 0 -and $left -lt $wdMs) { $to = [int][Math]::Max(1000, [double]$left); $budgetCut = $true }
        if ($win.live) {
            Read-LiveWindow $win $maxEl $to
        } else {
            if ($win.readMs -gt 0) {
                Start-Sleep -Milliseconds ([int][Math]::Min([double]$win.readMs, [double]$to))
                if ($win.readMs -gt $to) { $win.hang = $true }
            }
            $win.total = $win.items.Count
            if ($win.items.Count -gt $maxEl) {
                $win.capped = $true
                $win.items.RemoveRange($maxEl, $win.items.Count - $maxEl)
            }
        }
        if ($win.hang -and $budgetCut) { $script:C.budget_hit = 1; Add-Reason 'R-BUDGET'; break }
        if ($win.hang) { $script:C.timeout++; Add-Reason 'R-CAP'; continue }
        if ($win.error -or $win.items.Count -eq 0) {
            if ($win.elev -eq -1) { $script:C.elevated++; Add-Reason 'R-UIAELEV'; continue }
            if ($win.error) { $script:C.errors++; continue }
            $script:C.empty++; continue
        }
        if ($win.capped) { $script:C.capped++; Add-Reason 'R-CAP' }
        $script:C.read++
        $script:C.elements += $win.items.Count
        $room = Get-RoomFromTitle $win.title
        $win.roomName = $room.name
        $win.roomSelf = $room.self
        foreach ($r in (Invoke-Window $win)) { $allRows.Add($r) }
    }

    # 방 마무리 — 대화 유형은 구조 단서로만, 미상이면 group + 2 + n_part_est(CT §4.2 · X-088)
    foreach ($room in $script:Rooms.Values) {
        $room.est = $false; $room.typeEst = $false
        if ($room.self) { $room.type = 'self'; $room.n = 1 }
        elseif ($room.channel) { $room.type = 'channel'; if ($null -ne $room.count) { $room.n = $room.count } else { $room.n = 2; $room.est = $true } }
        elseif ($room.meeting) { $room.type = 'meeting'; if ($null -ne $room.count) { $room.n = $room.count } else { $room.n = 2; $room.est = $true } }
        elseif ($null -ne $room.count -and $room.count -ge 3) { $room.type = 'group'; $room.n = $room.count }
        elseif ($null -ne $room.count -and $room.count -eq 2) { $room.type = '1:1'; $room.n = 2 }
        elseif ($script:SelfGiven -gt 0 -and $room.id -ne 'uia:unknown' -and $room.authors.Count -ge 2) { $room.type = 'group'; $room.n = $room.authors.Count + 1; $room.est = $true }
        else { $room.type = 'group'; $room.n = 2; $room.est = $true; $room.typeEst = $true }
        $room.showTitle = ($room.type -in @('group', 'channel', 'meeting')) -and -not $room.typeEst -and [bool]$room.title
        $parts = New-Object 'System.Collections.Generic.List[object]'
        if ($room.id -ne 'uia:unknown') {
            foreach ($a in $room.authors) { if ($parts.Count -ge 20) { break }; $parts.Add([ordered]@{ name = $a }) }
        }
        $room.parts = $parts
    }

    # 레코드(원시 — P §10.2 teams 원시 이름) 조립·중복 제거·커서
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $maxTs = $null
    foreach ($r in $allRows) {
        $room = $r.room
        if ($r.prec -eq 'minute') {
            if (($null -ne $sinceD -and $r.date -lt $sinceD) -or ($null -ne $untilD -and $r.date -gt $untilD)) { $script:C.out_of_range++; continue }
            $wall = $r.date.AddHours($r.hh).AddMinutes($r.mm)
            $ts = Get-UtcText $wall
        } else {
            $ts = Get-UtcText $script:Today          # 자리값(수집일 00:00 로컬) — 시간 근거 아님(ts_precision unknown)
        }
        $hm = '{0}:{1}' -f $r.hh.ToString('00', $script:Inv), $r.mm.ToString('00', $script:Inv)
        $key = [string]::Join([string][char]31, @($room.id, $r.prec, $ts, $hm, [string]$r.author, $r.body))
        if (-not $seen.Add($key)) { $script:C.dup++; continue }
        $flags = [ordered]@{}
        if ($room.est) { $flags.n_part_est = $true }
        if ($r.inherited) { $flags.author_inherited = $true }
        $conf = 0.8
        if ($r.prec -ne 'minute' -or $r.inherited) { $conf = 0.3 }
        $title = $null
        if ($room.showTitle) { $title = $room.title }
        $rec = [ordered]@{
            message_id = $null
            chat_id = $room.id
            chat_type = $room.type
            n_participants = [int]$room.n
            reply_to_id = $null
            author_addr = $null
            author_name = $r.author
            is_me = $r.isMe
            participants = $room.parts
            mentions_me = [bool]$r.mentions
            file_names = $r.files
            body_text = $r.body
            chat_title = $title
            ts_utc = $ts
            ts_local_offset = $script:OffText
            ts_precision = $r.prec
            observed_at = $observed
            confidence = $conf
            flags = $flags
        }
        $script:OutLines.Add((ConvertTo-LmJson $rec))
        $script:C.rows++
        if ($r.prec -eq 'minute') {
            $script:C.n_minute++
            $tsd = ConvertFrom-UtcText $ts
            if ($null -eq $prevTs -or $tsd -gt $prevTs) { $script:C.n_new++ }
            if ($null -eq $maxTs -or $tsd -gt $maxTs) { $maxTs = $tsd }
        } else {
            $script:C.n_unknown++
            if ($null -eq $prevTs) { $script:C.n_new++ }
        }
        if ($r.inherited) { $script:C.n_inherited++ }
        if ($r.isMe -eq $true) { $script:C.n_self++ }
    }
    $last = $prevTs
    if ($null -ne $maxTs -and ($null -eq $last -or $maxTs -gt $last)) { $last = $maxTs }
    if ($null -ne $last) { $script:NewCursor = $last.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv) }

    # rc(계약 §8.1) — 막힌 사유가 있으면 rc 3, exit 0 고정 금지
    if ($script:C.rows -gt 0 -and $script:SelfGiven -eq 0) { Add-Reason 'R-NOADDR' }
    if ($script:C.procs -le 0 -and $script:C.windows -eq 0) { $script:Rc = 1; return }
    if ($script:C.windows -eq 0) { Add-Reason 'R-UIAEMPTY'; $script:Rc = 3; return }
    if ($script:C.read -eq 0) {
        if ($readable -eq 0 -and $script:C.elevated -eq 0) { Add-Reason 'R-UIAEMPTY' }
        elseif ($script:C.empty -gt 0) { Add-Reason 'R-UIAEMPTY' }
        if ($script:C.errors -gt 0 -or $script:C.timeout -gt 0) { Add-Reason 'R-TRANSPORT' }
        if ($script:Reasons.Count -eq 0) { Add-Reason 'R-UIAEMPTY' }
        $script:Rc = 3
        return
    }
    if ($script:C.n_new -gt 0) { $script:Rc = 0 } else { $script:Rc = 4 }
}

function Send-Status {
    $st = [ordered]@{ src = $script:Src; rc = [int]$script:Rc; reasons = @($script:Reasons); counts = $script:C }
    Send-Bytes ([Console]::OpenStandardError()) (ConvertTo-LmJson ([ordered]@{ _status = $st }))
}

try {
    $null = Invoke-Main
} catch {
    $script:Rc = 3
    # 제한 언어 모드(Add-Type·.NET 호출 차단)면 구조 사유 R-CLM, 그 밖은 수송·드라이버 실패
    $lm = 'FullLanguage'
    try { $lm = [string]$ExecutionContext.SessionState.LanguageMode } catch { }
    if ($lm -ne 'FullLanguage') { Add-Reason 'R-CLM' } else { Add-Reason 'R-TRANSPORT' }
    $script:C.fatal = $_.Exception.GetType().Name          # 유형 이름만(메시지에 원문이 섞일 수 있다)
    $script:OutLines.Clear()
    $script:NewCursor = $null
}
if ($null -eq $script:NewCursor -and $null -ne $script:PrevCursor) {
    $script:NewCursor = Get-JsonProp $script:PrevCursor 'last_ts_utc' $null
}
try {
    $out = [Console]::OpenStandardOutput()
    foreach ($ln in $script:OutLines) { Send-Bytes $out $ln }
    Send-Bytes $out (ConvertTo-LmJson ([ordered]@{ _cursor = [ordered]@{ last_ts_utc = $script:NewCursor } }))
} catch {
    $script:Rc = 3
    Add-Reason 'R-TRANSPORT'
    $script:C.fatal = $_.Exception.GetType().Name
}
try { Send-Status } catch { }
exit $script:Rc
