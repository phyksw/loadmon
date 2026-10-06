<#
.SYNOPSIS
  pc.recent 수집기(CP §5.4, 계약 §2.17) — Windows 최근 문서 바로가기(%APPDATA%\Microsoft\Windows\Recent\*.lnk)를 NDJSON 으로 낸다.

.DESCRIPTION
  이전 판 Get-RecentFiles.ps1 이식 — Office MRU 는 Get-OfficeMru.ps1 로 나눴다(이 수집기는 .lnk 전담).
    · .lnk 의 수정 시각 = 열람 시각(UTC), 대상 경로는 WScript.Shell(막히면 LinkInfo 직접 해석)로. .lnk 는 약 150건 롤링 —
      주기 수확이 과거를 원장에 남긴다.
    · 대상의 현재 수정 시각(target_mtime)이 열람보다 2분 넘게 과거면 op=open(열람만), 아니면 modify. 대상이 없거나 URL 이면 open.
    · 자기 제외(X-316)·빌드 폴더·폴더명 제외는 파일 수집기와 같은 규칙. 원시 경로는 stdout 으로만(디스크 쓰기 없음 — L-09).
  최근 문서 정책(HKCU\…\Policies\Explorer — NoRecentDocsHistory·ClearRecentDocsOnExit)이 기록을 막으면 rc 3 + R-RECENTPOLICY.
  rc(계약 §8.1): 0 새 항목 · 1 바로가기 0건(R-MRUEMPTY — 경고) · 3 정책 차단 · 4 읽었지만 커서 뒤 새 항목 0.

.PARAMETER RecentDir
  시험 주입(계약 §11.3): Recent 폴더 대신 이 폴더의 .lnk
.PARAMETER MruRegFile
  시험 주입(계약 §11.3 의 레지스트리 재생과 같은 방식): 정책 값을 레지스트리 대신 이 reg 내보내기 텍스트에서 읽는다
.PARAMETER TestNow
  시험 주입: '지금'
#>
param(
    [string]$Pc = '',
    [string]$Since = '',
    [string]$Until = '',
    [int]$Days = 0,
    [string]$RecentDir = '',
    [string]$MruRegFile = '',
    [string]$TestNow = ''
)

# ── 제한 언어 모드(CLM) — 다른 어떤 문(New-Object·[Console]·.NET 형·공통 도우미)보다 먼저 본다 ─────────────────────
# 계약 v1.2 §0.7 C1·C4 · §8.1: 막힌 경로는 rc 3 + 사유(R-CLM). CLM 에서는 [Console] 호출도 막히므로 상태 줄을 stdout
# 제어 줄로 낸다(문자열 리터럴 출력만 — 핵심 형으로 충분). 이전에는 New-Object 에서 멈춰 rc 1·출력 0바이트였고
# 원장이 미관측을 '0건 관측(zero_ok)'으로 기록했다(W1 통합 창 결함 수정).
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    '{"_status":{"schema":"lm27.collector_status/1","src":"pc.recent","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{}}}'
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

# _in.cursor.read_from — 이 경로가 빠짐없이 낸 범위의 시작(UTC). 창이 그보다 이르면(기본 시작일이 앞당겨짐 — v1.3 §0.8 V6) 그
# 앞쪽은 아직 낸 적이 없다: 이번에는 last_ts_utc 를 무시하고 창 전체를 다시 낸다(중복은 정제기의 레코드 id 로 흡수). read_from
# 이 없는 예전 커서도 같다(한 번). 그래야 상태 줄 range(= 이번에 맡은 창)를 원장이 '읽었다'고 적어도 거짓이 아니다(T-09).
function Get-LmReadFrom {
    $c = $script:InCursor
    if ($null -eq $c) { return $null }
    $p = $c.PSObject.Properties['read_from']
    if ($null -eq $p -or $null -eq $p.Value) { return $null }
    return (ConvertFrom-LmTime $p.Value)
}
function Get-LmFromGap($curUtc, $rfPrev, [datetime]$sinceUtc) {
    return (($null -ne $curUtc) -and (($null -eq $rfPrev) -or ($sinceUtc -lt $rfPrev)))
}
function Get-LmNewReadFrom($rfPrev, [datetime]$sinceUtc, [bool]$gap, [bool]$incomplete) {
    if ($incomplete) { return $rfPrev }                    # 끝까지 못 냈다(예산) — 앞당기지 않는다
    if ($null -ne $rfPrev -and -not $gap -and $rfPrev -lt $sinceUtc) { return $rfPrev }
    return $sinceUtc
}

function New-LmStatus([string]$Src) {
    return [ordered]@{ schema = 'lm27.collector_status/1'; src = $Src; rc = 3; reasons = @(); partial = $false;
                       cap_hit = $false; budget_hit = $false; n = 0; counts = [ordered]@{}; in = 'none'; elapsed_ms = 0 }
}
# ───────────────────────── 파일 판정 도우미(파일·MRU·Recent 수집기 공통 규칙) ─────────────────────────
# 확장자: 단일(HashSet)·복합(.cas.gz — Fluent 기본 압축 저장)·Creo 판번호(bracket.prt.12 → .prt)를 이름 끝으로 본다.
$script:ExtSet = New-Object 'Collections.Generic.HashSet[string]'
$script:ExtCompound = New-Object 'Collections.Generic.List[string]'
$script:ExtAny = $true
$script:CreoRe = New-Object Text.RegularExpressions.Regex '\.(prt|asm|drw|frm|sec|lay|mfg|gph|neu)\.\d{1,4}$'
$script:IgnoreNames = @('thumbs.db', 'ehthumbs.db', 'ehthumbs_vista.db', 'desktop.ini', '.ds_store')
$script:DenyExt = @('.exe', '.dll', '.lnk', '.url', '.ini', '.tmp', '.sys', '.cat', '.msi', '.log', '.dat', '.db')
# _in 이 없을 때(단독 실행)만 쓰는 최소 목록 — 정본 기본값은 설정 레지스트리 pc.watchExtensions(연결자가 _in.cfg 로 넘긴다)
$script:FallbackExt = @('.docx', '.docm', '.doc', '.xlsx', '.xlsm', '.xlsb', '.xls', '.pptx', '.pptm', '.ppt', '.pdf',
    '.hwp', '.hwpx', '.vsdx', '.one', '.txt', '.md', '.csv', '.dwg', '.dxf', '.step', '.stp', '.igs', '.prt', '.asm',
    '.drw', '.sldprt', '.sldasm', '.slddrw', '.catpart', '.catproduct', '.ipt', '.iam', '.wbpj', '.mph', '.cas', '.dat.gz',
    '.cas.gz', '.zmx', '.zos', '.schdoc', '.pcbdoc', '.brd', '.kicad_pcb', '.py', '.c', '.cpp', '.h', '.m', '.slx')

function Initialize-LmExt($exts) {
    $list = @($exts | Where-Object { $null -ne $_ })
    if ($list.Count -eq 0) { $script:ExtAny = $true; return }
    $script:ExtAny = $false
    foreach ($e in $list) {
        $x = ([string]$e).Trim().ToLower()
        if (-not $x.StartsWith('.')) { continue }
        if (($x.TrimStart('.') -split '\.').Count -gt 1) { $script:ExtCompound.Add($x) } else { [void]$script:ExtSet.Add($x) }
    }
}

# 감시 대상이면 확장자(소문자), 아니면 ''. 목록이 없으면(ExtAny) 확장자가 있는 파일 중 실행·바로가기·임시류만 뺀다.
function Get-LmWatchExt([string]$name) {
    if (-not $name) { return '' }
    $nl = $name.ToLower()
    if ($script:IgnoreNames -contains $nl -or $nl.StartsWith('~$')) { return '' }
    if ($nl.EndsWith('.map') -and $nl -match '\.(js|css|mjs|cjs|ts|tsx)\.map$') { return '' }
    foreach ($ce in $script:ExtCompound) { if ($nl.EndsWith($ce)) { return $ce } }
    $m = $script:CreoRe.Match($nl)
    if ($m.Success) {
        $b = '.' + $m.Groups[1].Value
        if ($script:ExtAny -or $script:ExtSet.Contains($b)) { return $b }
        return ''
    }
    $i = $nl.LastIndexOf('.')
    if ($i -le 0) { return '' }
    $e = $nl.Substring($i)
    if ($script:ExtAny) {
        if ($script:DenyExt -contains $e -or $e.Length -gt 12) { return '' }
        return $e
    }
    if ($script:ExtSet.Contains($e)) { return $e }
    return ''
}

# 자기 제외(계약 §2.17 · X-316): %LOCALAPPDATA%\LoadMonitor27\ 아래, 또는 data\bundle.json 이 있는 폴더(프로그램 폴더 —
# 이름·위치와 무관) 아래. 자기 출력이 다음 수집의 업무 신호로 되먹지 않게 한다.
$script:LadRoot = ''
try {
    if ($env:LOCALAPPDATA) { $script:LadRoot = (Join-Path $env:LOCALAPPDATA 'LoadMonitor27').ToLower().TrimEnd('\') + '\' }
} catch { $script:LadRoot = '' }
$script:SelfCache = @{}
$script:NSelf = 0

function Test-LmSelfDir([string]$dir) {
    if (-not $dir) { return $false }
    $dl = $dir.ToLower().TrimEnd('\')
    if ($script:LadRoot -and ($dl + '\').StartsWith($script:LadRoot)) { return $true }
    if ($dl -match '^[a-z]+://') { return $false }
    $cur = $dl
    $seen = New-Object 'Collections.Generic.List[string]'
    $hit = $false
    $guard = 0
    while ($cur -and $guard -lt 64) {
        $guard++
        if ($script:SelfCache.ContainsKey($cur)) { $hit = [bool]$script:SelfCache[$cur]; break }
        $seen.Add($cur)
        $base = $cur
        if ($base -match '^[a-z]:$') { $base += '\' }
        $marker = $false
        try { $marker = [IO.File]::Exists([IO.Path]::Combine($base, 'data', 'bundle.json')) } catch { $marker = $false }
        if ($marker) { $hit = $true; break }
        $parent = $null
        try { $parent = [IO.Path]::GetDirectoryName($base) } catch { $parent = $null }
        if (-not $parent) { break }
        $parent = $parent.ToLower().TrimEnd('\')
        if ($parent -eq $cur) { break }
        $cur = $parent
    }
    foreach ($s in $seen) { $script:SelfCache[$s] = $hit }
    return $hit
}

# 폴더명 제외(pc.excludeFolderNames — 폴더명 완전 일치, 대소문자 무시)
$script:FolderNames = New-Object 'Collections.Generic.HashSet[string]'
$script:SepChars = [char[]]@('\', '/')
$script:NFolderName = 0
function Initialize-LmFolderNames($names) {
    foreach ($n in @($names | Where-Object { $_ })) { [void]$script:FolderNames.Add(([string]$n).Trim().ToLower().Trim('\')) }
}
function Test-LmFolderName([string]$pl) {
    if ($script:FolderNames.Count -eq 0) { return '' }
    $segs = $pl.Split($script:SepChars)
    for ($i = 0; $i -lt $segs.Length - 1; $i++) {
        if ($segs[$i] -and $script:FolderNames.Contains($segs[$i])) { return $segs[$i] }
    }
    return ''
}

# 사적 폴더 낱말(privacy.path.excludeKeywords — _in.cfg 에 있을 때만, 자동 발견 후보 폴더를 거르는 데만 쓴다. 파일 행의
# 사적 폴더 폐기·건수는 정제기 path_excluded 가 한다 — P §10.4). 경로 전용 토큰은 폴더명 완전 일치, ASCII 는 단어 경계, 한글은 부분.
$script:PathOnly = @('temp', 'downloads', '임시', '다운로드')
$script:PrivSeg = @()
$script:PrivKr = @()
$script:PrivRe = $null
function Initialize-LmPrivate($kws) {
    $kw = @($kws | Where-Object { $_ } | ForEach-Object { ([string]$_).Trim().ToLower() } | Where-Object { $_ })
    $script:PrivSeg = @($kw | Where-Object { $script:PathOnly -contains $_ })
    $script:PrivKr = @($kw | Where-Object { $_ -notmatch '^[\x00-\x7F]+$' -and $script:PathOnly -notcontains $_ })
    $asc = @($kw | Where-Object { $_ -match '^[\x00-\x7F]+$' -and $script:PathOnly -notcontains $_ })
    if ($asc.Count -gt 0) {
        $script:PrivRe = New-Object Text.RegularExpressions.Regex ('(?<![a-z0-9])(' + (($asc | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')(?![a-z0-9])')
    }
}
function Test-LmPrivate([string]$pl) {
    if ($script:PrivSeg.Count -gt 0) {
        $segs = $pl.Split($script:SepChars)
        foreach ($k in $script:PrivSeg) { if ($segs -contains $k) { return $true } }
    }
    foreach ($k in $script:PrivKr) { if ($pl.Contains($k)) { return $true } }
    if ($null -ne $script:PrivRe -and $script:PrivRe.IsMatch($pl)) { return $true }
    return $false
}

# 패키지·빌드 폴더(pc.excludePackageDirs, 기본 true) — 이름만으로 확정되는 것과, 이름이 업무 폴더와 겹쳐 빌드 표식이 있을 때만
# 빼는 것(build·dist·target·release·debug·x64·env·packages). 'temp'→Temperature_Test 오삭제 같은 이름 규칙 사고를 막는다.
$script:PkgOn = $true
$script:PkgAlwaysRe = New-Object Text.RegularExpressions.Regex '\\(\.venv|venv|\.env|node_modules|site-packages|__pycache__|\.git|\.tox|\.nox|\.mypy_cache|\.pytest_cache|\.idea|\.vs|\.vscode|\.conda|conda-meta|cmake-build-[^\\]*)(?=\\)'
$script:PkgMaybeRe = New-Object Text.RegularExpressions.Regex '\\(env|build|dist|target|packages|x64|debug|release)(?=\\)'
$script:MarkIn = @('cmakecache.txt', 'cachedir.tag', 'pyvenv.cfg', 'build.ninja', '.ninja_log', 'compile_commands.json',
    'objects.list', 'repositories.config', 'makefile', 'cmakefiles', 'maven-status', 'conda-meta', 'site-packages', 'node_modules')
$script:MarkInSfx = @('.pdb', '.obj', '.ilk', '.idb', '.o', '.d', '.su', '.pch', '.whl', '.nupkg', '.jar', '.class', '.tlog',
    '.recipe', '.pyc', '.exp')
$script:MarkUp = @('cmakelists.txt', 'package.json', 'setup.py', 'pyproject.toml', 'setup.cfg', 'cargo.toml', 'pom.xml',
    'build.gradle', 'build.gradle.kts', 'tsconfig.json', '.cproject', '.git', 'meson.build', 'sconstruct')
$script:MarkUpSfx = @('.sln', '.vcxproj', '.csproj', '.vbproj', '.fsproj', '.uvprojx', '.uvproj', '.ewp', '.ioc', '.pro', '.cbp')
$script:ArtefactExts = @('.hex', '.elf', '.bin', '.map', '.bit', '.sof')
$script:BuildDirCache = @{}
$script:NPkg = 0

function Test-LmMarks([string]$dir, [string[]]$exact, [string[]]$sfx) {
    try {
        $n = 0
        foreach ($p in [IO.Directory]::EnumerateFileSystemEntries($dir)) {
            $n++
            if ($n -gt 5000) { break }
            $b = [IO.Path]::GetFileName($p).ToLower()
            if ($exact -contains $b) { return $true }
            foreach ($s in $sfx) { if ($b.EndsWith($s)) { return $true } }
        }
    } catch { }
    return $false
}
function Test-LmBuildDir([string]$dir) {
    if ($script:BuildDirCache.ContainsKey($dir)) { return $script:BuildDirCache[$dir] }
    $r = Test-LmMarks $dir $script:MarkIn $script:MarkInSfx
    if (-not $r) {
        $up = $null
        try { $up = [IO.Path]::GetDirectoryName($dir) } catch { $up = $null }
        if ($up) { $r = Test-LmMarks $up $script:MarkUp $script:MarkUpSfx }
    }
    $script:BuildDirCache[$dir] = $r
    return $r
}
function Test-LmPkgPath([string]$pl, [string]$ext) {
    if (-not $script:PkgOn) { return '' }
    $m = $script:PkgAlwaysRe.Match($pl)
    if ($m.Success) { return $m.Groups[1].Value }
    if ($ext -and $script:ArtefactExts -contains $ext) { return '' }
    foreach ($mm in $script:PkgMaybeRe.Matches($pl)) {
        $dir = $pl.Substring(0, $mm.Index + $mm.Length)
        if (Test-LmBuildDir $dir) { return $mm.Groups[1].Value }
    }
    return ''
}

# 폴더 역할(folder_role 원시 힌트 — desktop·documents·downloads·onedrive·sharepoint·root·other)과 자동 저장(flags.autosave).
# OneDrive·SharePoint 동기화 루트는 환경 변수 + HKCU OneDrive 계정 키(시험 모드에서는 레지스트리를 읽지 않는다).
$script:KnownDirs = New-Object 'Collections.Generic.List[psobject]'
function Add-LmKnownDir([string]$role, $p) {
    if (-not $p) { return }
    $k = ([string]$p).ToLower().TrimEnd('\') + '\'
    if ($k.Length -lt 4) { return }
    $script:KnownDirs.Add([pscustomobject]@{ prefix = $k; role = $role })
}
function Initialize-LmKnownDirs([bool]$TestMode) {
    try { Add-LmKnownDir 'desktop' ([Environment]::GetFolderPath('Desktop')) } catch { }
    try { Add-LmKnownDir 'documents' ([Environment]::GetFolderPath('MyDocuments')) } catch { }
    try { if ($env:USERPROFILE) { Add-LmKnownDir 'downloads' (Join-Path $env:USERPROFILE 'Downloads') } } catch { }
    foreach ($v in @($env:OneDrive, $env:OneDriveCommercial, $env:OneDriveConsumer)) { Add-LmKnownDir 'onedrive' $v }
    if ($TestMode) { return }
    try {
        foreach ($acc in @(Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\OneDrive\Accounts' -ErrorAction SilentlyContinue)) {
            $uf = $null
            try { $uf = (Get-ItemProperty -LiteralPath $acc.PSPath -ErrorAction SilentlyContinue).UserFolder } catch { $uf = $null }
            Add-LmKnownDir 'onedrive' $uf
            $c = Join-Path $acc.PSPath 'ScopeIdToMountPointPathCache'
            if (Test-Path -LiteralPath $c) {
                foreach ($pr in (Get-ItemProperty -LiteralPath $c -ErrorAction SilentlyContinue).PSObject.Properties) {
                    if ($pr.Name -notlike 'PS*' -and $pr.Value -and ([string]$pr.Value) -ne [string]$uf) { Add-LmKnownDir 'sharepoint' $pr.Value }
                }
            }
        }
    } catch { }
}
# → @{ role; autosave }
function Get-LmFolderRole([string]$path, [bool]$InRoot) {
    $pl = $path.ToLower()
    if ($pl -match '^https?://') {
        if ($pl -match '^https?://[^/]*sharepoint\.com/') { return @{ role = 'sharepoint'; autosave = $true } }
        return @{ role = 'other'; autosave = $false }
    }
    $best = $null
    foreach ($k in $script:KnownDirs) {
        if ($pl.StartsWith($k.prefix) -and ($null -eq $best -or $k.prefix.Length -gt $best.prefix.Length)) { $best = $k }
    }
    $auto = $false
    foreach ($k in $script:KnownDirs) {
        if (($k.role -eq 'onedrive' -or $k.role -eq 'sharepoint') -and $pl.StartsWith($k.prefix)) { $auto = $true; break }
    }
    if ($null -ne $best) { return @{ role = $best.role; autosave = $auto } }
    if ($InRoot) { return @{ role = 'root'; autosave = $auto } }
    return @{ role = 'other'; autosave = $auto }
}

# 최종 이름 판정(flags.final_name — 계약 §5.2 episode.finalWords · X-145): 확장자를 뺀 원 이름에 낱말이 있으면(대소문자 무시).
# 낱말 목록은 연결자가 _in.cfg 로 넘긴다(에이전트는 context_cache.json 의 값). 목록이 없으면 판정하지 않는다(정제기 몫).
$script:FinalWords = @()
function Initialize-LmFinalWords($words) {
    $script:FinalWords = @($words | Where-Object { $_ } | ForEach-Object { ([string]$_).Trim().ToLower() } | Where-Object { $_ })
}
function Test-LmFinalName([string]$path) {
    if ($script:FinalWords.Count -eq 0 -or -not $path) { return $false }
    $stem = ''
    try { $stem = [IO.Path]::GetFileNameWithoutExtension(($path -split '[\\/]')[-1]).ToLower() } catch { $stem = '' }
    foreach ($w in $script:FinalWords) { if ($stem.Contains($w)) { return $true } }
    return $false
}

# 대상 파일 상태(크기·현재 수정 시각 UTC). URL·없음·예산 소진이면 $null. 닿지 않는 UNC 가 오래 걸릴 수 있어 전체 예산을 둔다.
$script:StatDeadline = [datetime]::UtcNow.AddSeconds(60)
function Get-LmTargetStat([string]$path) {
    if (-not $path -or $path -match '^[a-z]+://') { return $null }
    if ($path.StartsWith('\\') -and [datetime]::UtcNow -gt $script:StatDeadline) { return $null }
    try {
        $fi = New-Object IO.FileInfo($path)
        if (-not $fi.Exists) { return $null }
        return @{ size = [long]$fi.Length; mtime = $fi.LastWriteTimeUtc; ctime = $fi.CreationTimeUtc; attr = [int]$fi.Attributes }
    } catch { return $null }
}
# ───────────────────────── 바로가기(.lnk) 대상 경로 ─────────────────────────
# WScript.Shell 로 먼저 읽고(이전 판 실측 방식), COM 이 막히면(제한 언어 모드 등) Shell Link 이진 형식의 LinkInfo 를 직접 푼다.
# 대상 경로 원문은 메모리에만 있다(레코드 path 원시 필드로 stdout → 정제 파이프).
$script:Shell = $null
$script:ShellTried = $false
$script:AnsiEnc = [Text.Encoding]::Default

function Read-LmUtf16Z([byte[]]$b, [int]$o) {
    if ($o -lt 0 -or $o -ge $b.Length) { return '' }
    $e = $o
    while ($e + 1 -lt $b.Length -and ($b[$e] -ne 0 -or $b[$e + 1] -ne 0)) { $e += 2 }
    return [Text.Encoding]::Unicode.GetString($b, $o, $e - $o)
}
function Read-LmAnsiZ([byte[]]$b, [int]$o) {
    if ($o -lt 0 -or $o -ge $b.Length) { return '' }
    $e = [Array]::IndexOf($b, [byte]0, $o)
    if ($e -lt 0) { $e = $b.Length }
    return $script:AnsiEnc.GetString($b, $o, $e - $o)
}

# Shell Link(MS-SHLLINK) LinkInfo → 로컬 기본 경로 + 공통 접미, 또는 네트워크 이름 + 접미. 못 풀면 ''.
function Read-LmLnkInfo([string]$p) {
    try {
        $b = [IO.File]::ReadAllBytes($p)
        if ($b.Length -lt 0x4C -or [BitConverter]::ToUInt32($b, 0) -ne 0x4C) { return '' }
        $flags = [BitConverter]::ToUInt32($b, 0x14)
        $off = 0x4C
        if ($flags -band 0x1) { $off += 2 + [BitConverter]::ToUInt16($b, $off) }
        if (-not ($flags -band 0x2) -or $off + 0x1C -gt $b.Length) { return '' }
        $li = $off
        $hdr = [BitConverter]::ToUInt32($b, $li + 4)
        $lif = [BitConverter]::ToUInt32($b, $li + 8)
        $uni = $hdr -ge 0x24
        $suffix = ''
        if ($uni) { $suffix = Read-LmUtf16Z $b ($li + [int][BitConverter]::ToUInt32($b, $li + 0x20)) }
        else { $suffix = Read-LmAnsiZ $b ($li + [int][BitConverter]::ToUInt32($b, $li + 0x18)) }
        if ($lif -band 0x1) {
            if ($uni) { $base = Read-LmUtf16Z $b ($li + [int][BitConverter]::ToUInt32($b, $li + 0x1C)) }
            else { $base = Read-LmAnsiZ $b ($li + [int][BitConverter]::ToUInt32($b, $li + 0x10)) }
            if ($base) {
                if ($suffix) { return ($base.TrimEnd('\') + '\' + $suffix) }
                return $base
            }
        }
        if ($lif -band 0x2) {
            $cn = $li + [int][BitConverter]::ToUInt32($b, $li + 0x14)
            $nnOff = [int][BitConverter]::ToUInt32($b, $cn + 8)
            $net = ''
            if ($nnOff -gt 0x14) { $net = Read-LmUtf16Z $b ($cn + [int][BitConverter]::ToUInt32($b, $cn + 0x14)) }
            if (-not $net) { $net = Read-LmAnsiZ $b ($cn + $nnOff) }
            if ($net) {
                if ($suffix) { return ($net.TrimEnd('\') + '\' + $suffix) }
                return $net
            }
        }
    } catch { }
    return ''
}

function Get-LmLnkTarget([string]$lnkPath) {
    if (-not $script:ShellTried) {
        $script:ShellTried = $true
        try { $script:Shell = New-Object -ComObject WScript.Shell } catch { $script:Shell = $null }
    }
    $t = ''
    if ($null -ne $script:Shell) {
        try { $t = [string]$script:Shell.CreateShortcut($lnkPath).TargetPath } catch { $t = '' }
    }
    if (-not $t) { $t = Read-LmLnkInfo $lnkPath }
    return $t
}
# ───────────────────────── 레지스트리 내보내기 텍스트 재생(시험 주입 -MruRegFile, 계약 §11.3 · X-142) ─────────────────────────
# reg.exe export 모양(UTF-16 LE BOM 또는 UTF-8): [키] 줄과 "이름"="문자열" · "이름"=dword:XXXXXXXX 줄만 읽는다.
# → @{ '<키 소문자>' = [ordered]@{ '<값 이름>' = 값 } }. 실제 레지스트리를 읽지 않는 시험 경로다.
function Read-LmRegFile([string]$path) {
    $res = @{}
    $bytes = [IO.File]::ReadAllBytes($path)
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $text = [Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    } elseif ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $text = [Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    } else {
        $text = [Text.Encoding]::UTF8.GetString($bytes)
    }
    $key = $null
    foreach ($raw in ($text -split "`r?`n")) {
        $ln = $raw.Trim()
        if (-not $ln) { continue }
        if ($ln -match '^\[(.+)\]$') {
            $key = $Matches[1].ToLower()
            if (-not $res.ContainsKey($key)) { $res[$key] = [ordered]@{} }
            continue
        }
        if ($null -eq $key) { continue }
        if ($ln -match '^"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"$') {
            $res[$key][($Matches[1] -replace '\\(.)', '$1')] = ($Matches[2] -replace '\\(.)', '$1')
        } elseif ($ln -match '^"((?:[^"\\]|\\.)*)"\s*=\s*dword:([0-9a-fA-F]{8})$') {
            $res[$key][($Matches[1] -replace '\\(.)', '$1')] = [Convert]::ToInt64($Matches[2], 16)
        }
    }
    return $res
}

Set-LmOutput

$OpenSlackMin = 2
$PolicyKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer'

# 최근 문서 정책 → @{ no_history; clear_on_exit }
function Get-LmRecentPolicy([bool]$testMode) {
    $r = @{ no_history = $false; clear_on_exit = $false }
    if ($MruRegFile) {
        $reg = Read-LmRegFile $MruRegFile
        $k = 'hkey_current_user\software\microsoft\windows\currentversion\policies\explorer'
        if ($reg.ContainsKey($k)) {
            $v = $reg[$k]
            if ($v.Contains('NoRecentDocsHistory') -and [long]$v['NoRecentDocsHistory'] -ne 0) { $r.no_history = $true }
            if ($v.Contains('ClearRecentDocsOnExit') -and [long]$v['ClearRecentDocsOnExit'] -ne 0) { $r.clear_on_exit = $true }
        }
        return $r
    }
    if ($testMode) { return $r }
    try {
        $p = Get-ItemProperty -LiteralPath $PolicyKey -ErrorAction Stop
        if ($p.PSObject.Properties['NoRecentDocsHistory'] -and [long]$p.NoRecentDocsHistory -ne 0) { $r.no_history = $true }
        if ($p.PSObject.Properties['ClearRecentDocsOnExit'] -and [long]$p.ClearRecentDocsOnExit -ne 0) { $r.clear_on_exit = $true }
    } catch { }
    return $r
}

function Invoke-Main {
    Read-LmIn
    $script:St['in'] = $script:InState
    $nowUtc = Get-LmNow $TestNow
    $testMode = [bool]($TestNow -or $RecentDir)
    $rg = Get-LmRange $Since $Until $Days $nowUtc
    $script:St['range'] = @($rg.From, $rg.To)
    $curUtc = Get-LmCursorUtc
    $rfPrev = Get-LmReadFrom
    $gap = Get-LmFromGap $curUtc $rfPrev $rg.SinceUtc
    if ($gap) { $script:St['from_gap'] = $true }
    $curEmit = $curUtc
    if ($gap) { $curEmit = $null }                       # 앞쪽 공백 — 창 전체를 다시 낸다
    Initialize-LmExt @(Get-LmCfg 'pc.watchExtensions' $null)
    Initialize-LmFolderNames @(Get-LmCfg 'pc.excludeFolderNames' @())
    Initialize-LmFinalWords @(Get-LmCfg 'episode.finalWords' @())
    $script:PkgOn = [bool](Get-LmCfg 'pc.excludePackageDirs' $true)
    Initialize-LmKnownDirs $testMode
    $pol = Get-LmRecentPolicy $testMode

    $recent = $RecentDir
    if (-not $recent) { try { $recent = [Environment]::GetFolderPath('Recent') } catch { $recent = '' } }
    $lnks = @()
    if ($recent -and [IO.Directory]::Exists($recent)) {
        $lnks = @(Get-ChildItem -LiteralPath $recent -Filter '*.lnk' -File -ErrorAction SilentlyContinue |
                Sort-Object -Property LastWriteTimeUtc, Name)
    }
    $obs = Format-LmUtc $nowUtc
    $seen = New-Object 'Collections.Generic.HashSet[string]'
    $nInRange = 0
    $nNoTarget = 0
    $maxSeen = $null
    $n = 0
    foreach ($l in $lnks) {
        $t = $l.LastWriteTimeUtc
        if ($t -lt $rg.SinceUtc -or $t -ge $rg.UntilUtc) { continue }
        $tgt = Get-LmLnkTarget $l.FullName
        if (-not $tgt) { $nNoTarget++; continue }
        $name = ''
        try { $name = [IO.Path]::GetFileName($tgt) } catch { $name = '' }
        $ext = Get-LmWatchExt $name
        if (-not $ext) { continue }
        $pl = $tgt.ToLower()
        if ($pl -notmatch '^[a-z]+://') {
            $dir = ''
            try { $dir = [IO.Path]::GetDirectoryName($tgt) } catch { $dir = '' }
            if ($dir -and (Test-LmSelfDir $dir)) { $script:NSelf++; continue }
            if (Test-LmPkgPath $pl $ext) { $script:NPkg++; continue }
            if (Test-LmFolderName $pl) { $script:NFolderName++; continue }
        }
        if (-not $seen.Add($pl + '|' + (Format-LmUtc $t))) { continue }
        $nInRange++
        if ($null -eq $maxSeen -or $t -gt $maxSeen) { $maxSeen = $t }
        if ($null -ne $curEmit -and $t -le $curEmit) { continue }
        $st = Get-LmTargetStat $tgt
        $op = 'open'
        $size = $null
        $tm = $null
        if ($null -ne $st) {
            $size = $st.size
            $tm = Format-LmUtc $st.mtime
            if ($st.mtime -ge $t.AddMinutes(-$OpenSlackMin)) { $op = 'modify' }
        }
        $fr = Get-LmFolderRole $tgt $false
        $flags = [ordered]@{}
        if ($fr.autosave) { $flags['autosave'] = $true }
        if (Test-LmFinalName $tgt) { $flags['final_name'] = $true }
        Write-LmRecord ([ordered]@{
            path = $tgt; op = $op; size = $size
            target_mtime = $tm; pdf_sibling = $false; folder_role = $fr.role; root_id = $null
            ts_utc = (Format-LmUtc $t); ts_local_offset = (Format-LmOffset $t); ts_precision = 'minute'
            observed_at = $obs; confidence = 0.8; flags = $flags
        })
        $n++
    }
    $newCur = $curUtc
    if ($null -ne $maxSeen -and ($null -eq $newCur -or $maxSeen -gt $newCur)) { $newCur = $maxSeen }
    $curVal = $null
    if ($null -ne $newCur) { $curVal = Format-LmUtc $newCur }
    $rfNew = Get-LmNewReadFrom $rfPrev $rg.SinceUtc $gap $false
    Write-LmCursor ([ordered]@{ last_ts_utc = $curVal; read_from = (Format-LmUtc $rfNew) })

    if ($pol.no_history -or ($pol.clear_on_exit -and $lnks.Count -eq 0)) {
        Add-LmReason 'R-RECENTPOLICY'
        $script:Rc = 3
    } elseif ($n -gt 0) { $script:Rc = 0 }
    elseif ($nInRange -gt 0) { $script:Rc = 4 }
    else {
        $script:Rc = 1
        if ($lnks.Count -eq 0) { Add-LmReason 'R-MRUEMPTY' }
    }
    $script:St['n'] = $n
    $script:St['in_range'] = $nInRange
    $script:St['lnk'] = [ordered]@{ found = $lnks.Count; no_target = $nNoTarget; shell = [bool]($null -ne $script:Shell) }
    $script:St['policy'] = [ordered]@{ no_history = [bool]$pol.no_history; clear_on_exit = [bool]$pol.clear_on_exit }
    $script:St['excluded'] = [ordered]@{ self = $script:NSelf; package = $script:NPkg; folder_name = $script:NFolderName }
}

$script:St = New-LmStatus 'pc.recent'
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
