<#
.SYNOPSIS
  pc.files 수집기(CP §5.1, 계약 §2.17) — 감시 폴더(+ 자동 발견 작업 폴더)에서 기간 안에 수정된 산출물 파일을 NDJSON 으로 낸다.

.DESCRIPTION
  이전 판 Get-FileActivity.ps1 이식 + 수정:
    · 디스크 쓰기 제거 — 이전 판의 스냅숏·이력 CSV·제외 JSON 을 쓰지 않는다. 원시 레코드(전체 경로 원문 포함)는 stdout 으로만
      정제 파이프에 간다(경로·이름은 정제기가 path_key·doc_key·name_masked 로 바꾸고, 사적 폴더 행은 정제기가 폐기·건수만).
    · 자기 제외(X-316) = %LOCALAPPDATA%\LoadMonitor27\ 와 data\bundle.json 이 있는 폴더(프로그램 폴더 — 이름·위치 무관).
    · -LiteralPath / .NET 열거(대괄호 와일드카드 함정 없음), 커서 이후만(_in.cursor.last_ts_utc), 예산 pc.files.budgetSec.
    · 추가 원시 열: op(create·modify), root_id(설정 감시 루트 R01…), folder_role(원시 힌트), pdf_sibling, target_mtime.
  그대로 이식: 자동 발견(Recent .lnk 부모 · 공용 대화상자 MRU PIDL · 도구별 MRU 텍스트 · HKCU 하이브 → 빈도 2 이상 상위 16 폴더,
    깊이 6), 복합 확장자·Creo 판번호, 빌드·패키지 폴더는 표식으로, 폴더명 제외, 같은 분·폴더 뭉치 상한(pc.files.burstN×5+1),
    OOXML docProps(app.xml TotalTime · core.xml revision·lastModifiedBy — 항목 2초·전체 90초, OneDrive 자리표시자는 열지 않음).
  설정(_in.cfg, 계약 §5.2): pc.watchFolders · pc.watchExtensions · pc.autoDiscoverFolders · pc.excludeFolderNames ·
    pc.excludePackageDirs · pc.files.burstN · pc.files.budgetSec · collect.lookbackDays (+ 있으면 privacy.path.excludeKeywords —
    자동 발견 후보 폴더 거르기에만).
  rc(계약 §8.1): 0 새 파일 있음 · 1 대상 없음 · 4 읽었지만 커서 뒤 새 파일 0. 예산 소진 → partial + budget_hit + R-BUDGET
    (커서 그대로), 뭉치 상한 → partial + cap_hit + R-CAP.

.PARAMETER RecentDir
  시험 주입(계약 §11.3): Recent 폴더 대신 이 폴더의 .lnk 로 자동 발견
.PARAMETER MruTextDir
  시험 주입: 도구별 MRU 파일 대신 이 폴더의 텍스트 파일에서 경로 수확(레지스트리 출처는 모두 건너뜀)
.PARAMETER NoToolMru
  시험 주입: 도구·대화상자 MRU 자동 발견 생략(.lnk 만)
.PARAMETER Poll
  열린 문서 저장 폴링(CP §5.2 — 에이전트가 agent.filePoll.intervalSec 마다 부른다): 스캔 대신 Recent 상위 agent.filePoll.topN
  바로가기 대상의 현재 mtime 이 지난 폴링 뒤면 op=save 로 낸다. 커서 = {last_ts_utc(스캔 — 그대로), poll_ts_utc(폴링)}
.PARAMETER TestNow
  시험 주입: '지금'(로컬 'yyyy-MM-dd HH:mm' 또는 UTC 'yyyy-MM-ddTHH:mm:ssZ')
#>
param(
    [string]$Pc = '',
    [string]$Since = '',
    [string]$Until = '',
    [int]$Days = 0,
    [string]$RecentDir = '',
    [string]$MruTextDir = '',
    [switch]$NoToolMru,
    [switch]$Poll,
    [string]$TestNow = ''
)

# ── 제한 언어 모드(CLM) — 다른 어떤 문(New-Object·[Console]·.NET 형·공통 도우미)보다 먼저 본다 ─────────────────────
# 계약 v1.2 §0.7 C1·C4 · §8.1: 막힌 경로는 rc 3 + 사유(R-CLM). CLM 에서는 [Console] 호출도 막히므로 상태 줄을 stdout
# 제어 줄로 낸다(문자열 리터럴 출력만 — 핵심 형으로 충분). 이전에는 New-Object 에서 멈춰 rc 1·출력 0바이트였고
# 원장이 미관측을 '0건 관측(zero_ok)'으로 기록했다(W1 통합 창 결함 수정).
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    '{"_status":{"schema":"lm27.collector_status/1","src":"pc.files","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{}}}'
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

Set-LmOutput

$AuthorItemSec = 2              # OOXML 작성자 읽기 항목 2초 · 전체 90초(계약 §5.3)
$AuthorTotalSec = 90
$AutoDepth = 6                  # 자동 편입 폴더 깊이
$WatchDepth = 64                # 설정 감시 폴더 깊이(사실상 무제한, 순환 방지용)
$OoxmlExts = @('.docx', '.docm', '.dotx', '.pptx', '.pptm', '.potx', '.xlsx', '.xlsm', '.xlsb', '.vsdx')
$PdfSourceExts = @('.docx', '.docm', '.doc', '.pptx', '.pptm', '.ppt', '.xlsx', '.xlsm', '.xls', '.hwp', '.hwpx', '.vsdx', '.vsd')

# ── 자동 발견(작업 폴더 후보) ──────────────────────────────────────────────
$script:Freq = @{}
$script:DirDisp = @{}
$script:SrcStat = [ordered]@{}
$script:DirRecent = @{}
$script:NPrivCand = 0

function Get-LmDirRecentWork([string]$dl, [datetime]$cutUtc, [datetime]$untilUtc) {
    if ($script:DirRecent.ContainsKey($dl)) { return $script:DirRecent[$dl] }
    $c = 0
    try {
        $n = 0
        foreach ($fi in (New-Object IO.DirectoryInfo $dl).EnumerateFiles()) {
            $n++
            if ($n -gt 3000) { break }
            $t = $fi.LastWriteTimeUtc
            if ($t -ge $cutUtc -and $t -lt $untilUtc -and (Get-LmWatchExt $fi.Name)) { $c++; if ($c -ge 2) { break } }
        }
    } catch { }
    $script:DirRecent[$dl] = $c
    return $c
}

function Test-LmCandDir([string]$d) {
    if (-not $d) { return '' }
    $dl = $d.ToLower().TrimEnd('\')
    # 시스템·프로그램 폴더는 폴더명 단위로 뺀다. 시험 주입 실행이면 합성 자료가 있는 %TEMP% 아래만 AppData 규칙에서 풀어 준다.
    $sys = ($d.TrimEnd('\') + '\') -match '\\AppData\\|\\Windows\\|\\Program Files( \([^\\]*\))?\\|\\ProgramData\\'
    if ($sys -and $script:TestMode -and $script:TempRoot -and ($dl + '\').StartsWith($script:TempRoot)) { $sys = $false }
    if ($sys) { return '' }
    $up = ''
    if ($env:USERPROFILE) { $up = $env:USERPROFILE.ToLower().TrimEnd('\') }
    $pub = ''
    if ($env:PUBLIC) { $pub = $env:PUBLIC.ToLower().TrimEnd('\') }
    if ($dl -match '^[a-z]:$' -or ($up -and $dl -eq $up) -or ($pub -and $dl -eq $pub)) { return '' }
    if (Test-LmSelfDir $dl) { return '' }
    if (Test-LmPkgPath ($dl + '\') '') { return '' }
    if (Test-LmFolderName ($dl + '\')) { return '' }
    if (Test-LmPrivate ($dl + '\')) { $script:NPrivCand++; return '' }
    return $dl
}

function Add-LmCand([string]$tgt, [string]$src, [bool]$needRecent, [datetime]$cutUtc, [datetime]$untilUtc, [int]$w = 1) {
    if (-not $tgt -or $tgt -match '^[a-z]+://') { return $false }
    if (-not (Get-LmWatchExt ([IO.Path]::GetFileName($tgt)))) { return $false }
    $isFile = $false
    try { $isFile = [IO.File]::Exists($tgt) } catch { $isFile = $false }
    if (-not $isFile) { return $false }
    $d = [IO.Path]::GetDirectoryName($tgt)
    $dl = Test-LmCandDir $d
    if (-not $dl) { return $false }
    if ($needRecent) {
        $ok = $false
        try { $t = [IO.File]::GetLastWriteTimeUtc($tgt); $ok = ($t -ge $cutUtc -and $t -lt $untilUtc) } catch { $ok = $false }
        if (-not $ok -and (Get-LmDirRecentWork $dl $cutUtc $untilUtc) -lt 1) { return $false }
    }
    $prev = 0
    if ($script:Freq.ContainsKey($dl)) { $prev = $script:Freq[$dl] }
    $script:Freq[$dl] = $prev + $w
    $script:DirDisp[$dl] = $d
    $n0 = 0
    if ($script:SrcStat.Contains($src)) { $n0 = $script:SrcStat[$src] }
    $script:SrcStat[$src] = $n0 + 1
    return $true
}

function Get-LmPathsFromText([string]$text, $harvestRe) {
    $out = New-Object 'Collections.Generic.List[string]'
    if ($null -eq $harvestRe -or -not $text) { return ,$out }
    $t = $text -replace '\\\\', '\'
    try { $t = [Uri]::UnescapeDataString($t) } catch { }
    $t = $t -replace '/', '\'
    $t = $t -replace '(?<=[^\\\r\n])\\{2,}', '\'
    $seen = @{}
    foreach ($m in $harvestRe.Matches($t)) {
        $v = $m.Value
        if ($seen.ContainsKey($v.ToLower())) { continue }
        $seen[$v.ToLower()] = 1
        $out.Add($v)
        if ($out.Count -ge 300) { break }
    }
    return ,$out
}

function Find-LmAutoDirs([datetime]$sinceUtc, [datetime]$untilUtc, [datetime]$nowUtc, [bool]$testMode) {
    $cutUtc = $nowUtc.AddDays(-45)
    if ($sinceUtc -lt $cutUtc) { $cutUtc = $sinceUtc }
    $mruDeadline = [datetime]::UtcNow.AddSeconds(25)
    # ① 최근 열어본 문서(Recent .lnk)의 부모 폴더
    $recent = $RecentDir
    if (-not $recent) { try { $recent = [Environment]::GetFolderPath('Recent') } catch { $recent = '' } }
    if ($recent -and [IO.Directory]::Exists($recent)) {
        foreach ($f in @(Get-ChildItem -LiteralPath $recent -Filter '*.lnk' -File -ErrorAction SilentlyContinue)) {
            if ($f.LastWriteTimeUtc -le $cutUtc) { continue }
            $tgt = Get-LmLnkTarget $f.FullName
            [void](Add-LmCand $tgt 'lnk' $false $cutUtc $untilUtc)
        }
    }
    if (-not $NoToolMru) {
        # ② 공용 열기/저장 대화상자 MRU(PIDL) — 제한 언어 모드에서 Add-Type 이 막히면 건너뛴다. 시험 주입이면 레지스트리를 읽지 않는다.
        if (-not $MruTextDir -and -not $testMode) {
            $pidlOk = $false
            try {
                if (-not ('LM27Files.Shell' -as [type])) {
                    Add-Type -Namespace LM27Files -Name Shell -MemberDefinition '[DllImport("shell32.dll", CharSet = CharSet.Unicode)] public static extern bool SHGetPathFromIDListW(IntPtr pidl, System.Text.StringBuilder pszPath);'
                }
                $pidlOk = $true
            } catch { $pidlOk = $false; $script:St['pidl'] = 'unavailable' }
            if ($pidlOk) {
                $fromPidl = {
                    param([byte[]]$b, [int]$off)
                    if ($null -eq $b -or $b.Length - $off -lt 4) { return '' }
                    $n = $b.Length - $off
                    $p = [Runtime.InteropServices.Marshal]::AllocHGlobal($n)
                    try {
                        [Runtime.InteropServices.Marshal]::Copy($b, $off, $p, $n)
                        $sb = New-Object Text.StringBuilder 2048
                        if ([LM27Files.Shell]::SHGetPathFromIDListW($p, $sb)) { return $sb.ToString() }
                    } catch { } finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($p) }
                    return ''
                }
                try {
                    $k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU'
                    foreach ($sub in @(Get-ChildItem -LiteralPath $k -ErrorAction SilentlyContinue)) {
                        if ([datetime]::UtcNow -gt $mruDeadline) { break }
                        $sn = $sub.PSChildName.ToLower()
                        if ($sn -ne '*' -and -not $script:ExtAny -and -not $script:ExtSet.Contains('.' + $sn)) { continue }
                        $props = Get-ItemProperty -LiteralPath $sub.PSPath -ErrorAction SilentlyContinue
                        foreach ($pr in $props.PSObject.Properties) {
                            if ($pr.Name -notmatch '^\d+$') { continue }
                            [void](Add-LmCand (& $fromPidl ([byte[]]$pr.Value) 0) 'dialog-file' $true $cutUtc $untilUtc)
                        }
                    }
                } catch { }
                try {
                    $k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\LastVisitedPidlMRU'
                    $props = Get-ItemProperty -LiteralPath $k -ErrorAction SilentlyContinue
                    foreach ($pr in $props.PSObject.Properties) {
                        if ($pr.Name -notmatch '^\d+$') { continue }
                        if ([datetime]::UtcNow -gt $mruDeadline) { break }
                        $b = [byte[]]$pr.Value
                        $i = 0
                        while ($i + 1 -lt $b.Length) { if ($b[$i] -eq 0 -and $b[$i + 1] -eq 0) { break }; $i += 2 }
                        $d = & $fromPidl $b ($i + 2)
                        if (-not $d -or $d -match '^[a-z]+://') { continue }
                        $dl = Test-LmCandDir $d
                        if ($dl -and [IO.Directory]::Exists($d) -and (Get-LmDirRecentWork $dl $cutUtc $untilUtc) -ge 2) {
                            $prev = 0
                            if ($script:Freq.ContainsKey($dl)) { $prev = $script:Freq[$dl] }
                            $script:Freq[$dl] = $prev + 2
                            $script:DirDisp[$dl] = $d
                        }
                    }
                } catch { }
            }
        }
        # ③ 도구별 최근 파일 저장소(텍스트) — 경로만 수확한다(없으면 조용히 0건)
        $alt = @(@($script:ExtSet) + @($script:ExtCompound) | ForEach-Object { $_.TrimStart('.') } | Sort-Object -Property Length -Descending |
                ForEach-Object { [regex]::Escape($_) })
        $harvestRe = $null
        if ($alt.Count -gt 0) {
            $harvestRe = New-Object Text.RegularExpressions.Regex ('(?i)(?:[a-z]:|\\\\[^\\/:*?"<>|\r\n]+)\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*?\.(?:' + ($alt -join '|') + ')(?![a-z0-9_])')
        } elseif ($script:ExtAny) {
            $harvestRe = New-Object Text.RegularExpressions.Regex '(?i)(?:[a-z]:|\\\\[^\\/:*?"<>|\r\n]+)\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*?\.[a-z0-9]{1,6}(?![a-z0-9_])'
        }
        $sources = @()
        if ($MruTextDir) { $sources = @(@{ tag = 'test'; glob = (Join-Path $MruTextDir '*') }) }
        elseif (-not $testMode) {
            $sources = @(
                @{ tag = 'matlab'; glob = "$env:APPDATA\MathWorks\MATLAB\R20*\MATLAB_Editor_State.xml" },
                @{ tag = 'matlab'; glob = "$env:APPDATA\MathWorks\MATLAB\R20*\matlab.prf" },
                @{ tag = 'altium'; glob = "$env:APPDATA\Altium\*\DXP.RCS" },
                @{ tag = 'kicad'; glob = "$env:APPDATA\kicad\*\*.json" },
                @{ tag = 'notepad++'; glob = "$env:APPDATA\Notepad++\config.xml" },
                @{ tag = 'vs'; glob = "$env:LOCALAPPDATA\Microsoft\VisualStudio\1*\ApplicationPrivateSettings.xml" },
                @{ tag = 'iar'; glob = "$env:APPDATA\IAR Embedded Workbench\*.xml" },
                @{ tag = 'comsol'; glob = "$env:USERPROFILE\.comsol\v*\prefs.ini" },
                @{ tag = 'labview'; glob = "$env:APPDATA\National Instruments\*\LabVIEW.ini" },
                @{ tag = 'eclipse'; glob = "$env:USERPROFILE\STM32CubeIDE\workspace*\.metadata\.plugins\org.eclipse.core.resources\.projects\*\.location" },
                @{ tag = 'eclipse'; glob = "$env:USERPROFILE\*workspace*\.metadata\.plugins\org.eclipse.core.resources\.projects\*\.location" }
            )
        }
        foreach ($s in $sources) {
            if ([datetime]::UtcNow -gt $mruDeadline) { break }
            $files = @()
            try { $files = @(Get-ChildItem -Path $s.glob -File -ErrorAction SilentlyContinue | Where-Object { $_.Length -le 4MB } | Select-Object -First 20) } catch { $files = @() }
            foreach ($f in $files) {
                try {
                    foreach ($p in (Get-LmPathsFromText ([IO.File]::ReadAllText($f.FullName)) $harvestRe)) {
                        [void](Add-LmCand $p $s.tag $true $cutUtc $untilUtc)
                    }
                } catch { }
            }
        }
        # ④ 도구별 HKCU 하이브 — 깊이 3·1,500키 안의 문자열 값에서 경로 수확
        if (-not $MruTextDir -and -not $testMode) {
            $hives = @(@{ tag = 'solidworks'; root = 'HKCU:\Software\SolidWorks' }, @{ tag = 'zemax'; root = 'HKCU:\Software\Zemax' },
                @{ tag = 'altium'; root = 'HKCU:\Software\Altium' }, @{ tag = 'keil'; root = 'HKCU:\Software\Keil' },
                @{ tag = 'catia'; root = 'HKCU:\Software\Dassault Systemes' }, @{ tag = 'ltspice'; root = 'HKCU:\Software\LTspice' })
            foreach ($r in $hives) {
                if ([datetime]::UtcNow -gt $mruDeadline) { break }
                if (-not (Test-Path -LiteralPath $r.root)) { continue }
                try {
                    $keys = @(Get-Item -LiteralPath $r.root) + @(Get-ChildItem -LiteralPath $r.root -Recurse -Depth 3 -ErrorAction SilentlyContinue | Select-Object -First 1500)
                    $sb = New-Object Text.StringBuilder
                    foreach ($key in $keys) {
                        foreach ($vn in $key.GetValueNames()) {
                            $v = $key.GetValue($vn)
                            if ($v -is [string]) { [void]$sb.AppendLine($v) }
                            elseif ($v -is [string[]]) { foreach ($x in $v) { [void]$sb.AppendLine($x) } }
                        }
                    }
                    foreach ($p in (Get-LmPathsFromText $sb.ToString() $harvestRe)) { [void](Add-LmCand $p $r.tag $true $cutUtc $untilUtc) }
                } catch { }
            }
        }
    }
    $dirs = @($script:Freq.GetEnumerator() | Where-Object { $_.Value -ge 2 } |
            Sort-Object -Property @{ Expression = { $_.Value }; Descending = $true }, @{ Expression = { $_.Key } } |
            Select-Object -First 16 | ForEach-Object { $script:DirDisp[$_.Key] })
    return ,$dirs
}

# ── OOXML(docProps) 읽기 — TotalTime(분)·revision·lastModifiedBy(이름은 메모리에서 정제기 대조에만) ──
$script:ZipOk = $null
$script:AuthorWatch = $null
$script:NAuthorTry = 0
$script:NAuthorSlow = 0
$script:AuthorTimedOut = $false
function Read-LmOoxml($fi) {
    $res = @{ totaltime = $null; revision = $null; by = $null }
    if ($script:AuthorTimedOut) { return $res }
    $attr = [int]$fi.Attributes
    if (($attr -band 0x400000) -or ($attr -band 0x40000) -or ($attr -band 0x1000)) { return $res }   # 자리표시자·오프라인: 열면 내려받기
    if ($null -eq $script:ZipOk) {
        try { Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop; $script:ZipOk = $true } catch { $script:ZipOk = $false }
        $script:AuthorWatch = [Diagnostics.Stopwatch]::StartNew()
    }
    if (-not $script:ZipOk) { return $res }
    if ($script:AuthorWatch.Elapsed.TotalSeconds -gt $AuthorTotalSec) { $script:AuthorTimedOut = $true; return $res }
    $script:NAuthorTry++
    $t0 = $script:AuthorWatch.Elapsed.TotalSeconds
    $z = $null
    try {
        $z = [IO.Compression.ZipFile]::OpenRead($fi.FullName)
        foreach ($nm in @('docProps/core.xml', 'docProps/app.xml')) {
            $e = $z.GetEntry($nm)
            if ($null -eq $e -or $e.Length -gt 1MB) { continue }
            $sr = New-Object IO.StreamReader($e.Open())
            try { $xml = $sr.ReadToEnd() } finally { $sr.Dispose() }
            if ($nm -eq 'docProps/core.xml') {
                if ($xml -match '<cp:lastModifiedBy>([^<]*)</cp:lastModifiedBy>') { $res.by = [Net.WebUtility]::HtmlDecode($Matches[1]).Trim() }
                if ($xml -match '<cp:revision>\s*(\d{1,9})\s*</cp:revision>') { $res.revision = [int]$Matches[1] }
            } else {
                if ($xml -match '<TotalTime>\s*(\d{1,9})\s*</TotalTime>') { $res.totaltime = [int]$Matches[1] }
            }
        }
    } catch { } finally { if ($null -ne $z) { $z.Dispose() } }
    if ($script:AuthorWatch.Elapsed.TotalSeconds - $t0 -gt $AuthorItemSec) { $script:NAuthorSlow++ }
    return $res
}

function Test-LmPdfSibling($fi, [string]$ext) {
    if ($PdfSourceExts -notcontains $ext) { return $false }
    try {
        $stem = [IO.Path]::GetFileNameWithoutExtension($fi.Name)
        $pdf = [IO.Path]::Combine($fi.DirectoryName, $stem + '.pdf')
        if (-not [IO.File]::Exists($pdf)) { return $false }
        $pt = [IO.File]::GetLastWriteTimeUtc($pdf)
        return ($pt -ge $fi.LastWriteTimeUtc.AddMinutes(-1) -and $pt -le $fi.LastWriteTimeUtc.AddDays(1))
    } catch { return $false }
}

# 파일 한 건 → pc_file 원시 레코드(스캔·폴링 공통). 전체 경로 원문은 stdout(정제 파이프)으로만 간다.
function Write-LmFileRecord($fi, [string]$ext, [datetime]$mt, $rid, [string]$op, [string]$obs) {
    $ox = @{ totaltime = $null; revision = $null; by = $null }
    if ($OoxmlExts -contains $ext) { $ox = Read-LmOoxml $fi }
    $fr = Get-LmFolderRole $fi.FullName ($null -ne $rid)
    $flags = [ordered]@{}
    if ($fr.autosave) { $flags['autosave'] = $true }
    if (Test-LmFinalName $fi.FullName) { $flags['final_name'] = $true }
    Write-LmRecord ([ordered]@{
        path = $fi.FullName; op = $op; size = [long]$fi.Length
        ooxml_totaltime = $ox.totaltime; ooxml_revision = $ox.revision; ooxml_last_modified_by = $ox.by
        target_mtime = (Format-LmUtc $mt); pdf_sibling = (Test-LmPdfSibling $fi $ext)
        folder_role = $fr.role; root_id = $rid
        ts_utc = (Format-LmUtc $mt); ts_local_offset = (Format-LmOffset $mt); ts_precision = 'minute'
        observed_at = $obs; confidence = 1.0; flags = $flags
    })
}

# _in.cursor 의 시각 필드 하나(UTC) — 없으면 $null
function Get-LmCursorField([string]$name) {
    $c = $script:InCursor
    if ($null -eq $c) { return $null }
    $p = $c.PSObject.Properties[$name]
    if ($null -eq $p -or $null -eq $p.Value) { return $null }
    return (ConvertFrom-LmTime $p.Value)
}

# 커서 값: 스캔 진전 last_ts_utc + (있으면) 폴링 진전 poll_ts_utc — 한쪽 모드가 다른 쪽 진전을 지우지 않게 둘 다 싣는다
function New-LmFileCursor($lastUtc, $pollUtc) {
    $c = [ordered]@{ last_ts_utc = $null }
    if ($null -ne $lastUtc) { $c['last_ts_utc'] = Format-LmUtc $lastUtc }
    if ($null -ne $pollUtc) { $c['poll_ts_utc'] = Format-LmUtc $pollUtc }
    return $c
}

# 열린 문서 저장 폴링(CP §5.2 — -Poll): 스캔 없이 Recent 상위 agent.filePoll.topN 바로가기 대상의 현재 mtime 만 읽어, 지난 폴링
# (커서 poll_ts_utc — 없으면 스캔 커서, 그것도 없으면 1시간 전) 뒤에 저장된 것을 op=save 로 낸다. 실행 사이 중간 저장이 mtime 에
# 덮여 사라지던 이전 판 결함을 막는다. 스캔 커서(last_ts_utc)는 그대로 둔다(폴링이 스캔 몫을 건너뛰게 하지 않는다).
function Invoke-LmPoll([datetime]$nowUtc, $curUtc) {
    $topN = 40
    try { $topN = [int](Get-LmCfg 'agent.filePoll.topN' 40) } catch { $topN = 40 }
    if ($topN -le 0) { $topN = 40 }
    $pollPrev = Get-LmCursorField 'poll_ts_utc'
    $thr = $pollPrev
    if ($null -eq $thr) { $thr = $curUtc }
    if ($null -eq $thr) { $thr = $nowUtc.AddHours(-1) }
    $roots = New-Object 'Collections.Generic.List[psobject]'
    $watch = @(Get-LmCfg 'pc.watchFolders' @() | Where-Object { $_ })
    for ($i = 0; $i -lt $watch.Count; $i++) {
        $roots.Add([pscustomobject]@{ prefix = ([string]$watch[$i]).ToLower().TrimEnd('\') + '\'; rid = ('R{0:00}' -f ($i + 1)) })
    }
    $recent = $RecentDir
    if (-not $recent) { try { $recent = [Environment]::GetFolderPath('Recent') } catch { $recent = '' } }
    $lnks = @()
    if ($recent -and [IO.Directory]::Exists($recent)) {
        $lnks = @(Get-ChildItem -LiteralPath $recent -Filter '*.lnk' -File -ErrorAction SilentlyContinue |
                Sort-Object -Property @{ Expression = { $_.LastWriteTimeUtc }; Descending = $true }, Name | Select-Object -First $topN)
    }
    $seen = New-Object 'Collections.Generic.HashSet[string]'
    $cands = New-Object 'Collections.Generic.List[psobject]'
    $maxSeen = $pollPrev
    $nPolled = 0
    foreach ($l in $lnks) {
        $tgt = Get-LmLnkTarget $l.FullName
        if (-not $tgt -or $tgt -match '^[a-z]+://') { continue }
        $pl = $tgt.ToLower()
        if (-not $seen.Add($pl)) { continue }
        $ext = Get-LmWatchExt ([IO.Path]::GetFileName($tgt))
        if (-not $ext) { continue }
        $dir = [IO.Path]::GetDirectoryName($tgt)
        if (Test-LmSelfDir $dir) { $script:NSelf++; continue }
        if (Test-LmPkgPath $pl $ext) { $script:NPkg++; continue }
        if (Test-LmFolderName $pl) { $script:NFolderName++; continue }
        $fi = $null
        try { $fi = New-Object IO.FileInfo($tgt) } catch { $fi = $null }
        if ($null -eq $fi -or -not $fi.Exists) { continue }
        $nPolled++
        $mt = $fi.LastWriteTimeUtc
        if ($null -eq $maxSeen -or $mt -gt $maxSeen) { $maxSeen = $mt }
        if ($mt -le $thr) { continue }
        $rid = $null
        foreach ($r in $roots) { if ($pl.StartsWith($r.prefix)) { $rid = $r.rid; break } }
        $cands.Add([pscustomobject]@{ fi = $fi; ext = $ext; mt = $mt; rid = $rid })
    }
    $obs = Format-LmUtc $nowUtc
    $n = 0
    foreach ($c in ($cands | Sort-Object -Property @{ Expression = { $_.mt } }, @{ Expression = { $_.fi.FullName } })) {
        Write-LmFileRecord $c.fi $c.ext $c.mt $c.rid 'save' $obs
        $n++
    }
    Write-LmCursor (New-LmFileCursor $curUtc $maxSeen)
    if ($n -gt 0) { $script:Rc = 0 } elseif ($nPolled -gt 0) { $script:Rc = 4 } else { $script:Rc = 1 }
    $script:St['mode'] = 'poll'
    $script:St['n'] = $n
    $script:St['polled'] = $nPolled
    $script:St['excluded'] = [ordered]@{ self = $script:NSelf; package = $script:NPkg; folder_name = $script:NFolderName }
}

function Invoke-Main {
    $swAll = [Diagnostics.Stopwatch]::StartNew()
    Read-LmIn
    $script:St['in'] = $script:InState
    $nowUtc = Get-LmNow $TestNow
    $testMode = [bool]($TestNow -or $RecentDir -or $MruTextDir)
    $script:TestMode = $testMode
    $script:TempRoot = ''
    if ($env:TEMP) { $script:TempRoot = $env:TEMP.ToLower().TrimEnd('\') + '\' }
    $rg = Get-LmRange $Since $Until $Days $nowUtc
    $script:St['range'] = @($rg.From, $rg.To)
    $curUtc = Get-LmCursorUtc

    $exts = @(Get-LmCfg 'pc.watchExtensions' $null)
    if ($exts.Count -eq 0 -and $script:InState -ne 'ok') { $exts = $script:FallbackExt }
    Initialize-LmExt $exts
    Initialize-LmFolderNames @(Get-LmCfg 'pc.excludeFolderNames' @())
    Initialize-LmPrivate @(Get-LmCfg 'privacy.path.excludeKeywords' @())
    Initialize-LmFinalWords @(Get-LmCfg 'episode.finalWords' @())
    $script:PkgOn = [bool](Get-LmCfg 'pc.excludePackageDirs' $true)
    $autoOn = [bool](Get-LmCfg 'pc.autoDiscoverFolders' $true)
    $burstN = 8
    try { $burstN = [int](Get-LmCfg 'pc.files.burstN' 8) } catch { $burstN = 8 }
    if ($burstN -lt 1) { $burstN = 8 }
    $budgetSec = 180
    try { $budgetSec = [int](Get-LmCfg 'pc.files.budgetSec' 180) } catch { $budgetSec = 180 }
    if ($budgetSec -le 0) { $budgetSec = 180 }
    Initialize-LmKnownDirs $testMode
    if ($Poll) { Invoke-LmPoll $nowUtc $curUtc; return }
    $script:St['mode'] = 'scan'

    # 감시 루트: 설정 폴더(R01…, 순서대로) + 자동 발견(빈도 2 이상 상위 16, 깊이 6)
    $roots = New-Object 'Collections.Generic.List[psobject]'
    $watch = @(Get-LmCfg 'pc.watchFolders' @() | Where-Object { $_ })
    $missing = 0
    for ($i = 0; $i -lt $watch.Count; $i++) {
        $p = [string]$watch[$i]
        if ($p -match '[<>]' -or -not [IO.Directory]::Exists($p)) { $missing++; continue }
        $roots.Add([pscustomobject]@{ path = $p; rid = ('R{0:00}' -f ($i + 1)); depth = $WatchDepth; auto = $false })
    }
    $autoDirs = @()
    if ($autoOn) { $autoDirs = Find-LmAutoDirs $rg.SinceUtc $rg.UntilUtc $nowUtc $testMode }
    foreach ($d in $autoDirs) { $roots.Add([pscustomobject]@{ path = $d; rid = $null; depth = $AutoDepth; auto = $true }) }
    # 겹치는 루트 정리 — 바깥이 설정 감시 폴더이거나 둘 다 자동이면 안쪽을 뺀다(같은 파일 두 번 스캔 방지)
    $final = New-Object 'Collections.Generic.List[psobject]'
    foreach ($r in $roots) {
        $dl = $r.path.ToLower().TrimEnd('\')
        $inner = $false
        foreach ($o in $roots) {
            $ol = $o.path.ToLower().TrimEnd('\')
            if ($ol -eq $dl) {
                if ($o -ne $r -and -not $o.auto -and $r.auto) { $inner = $true; break }
                continue
            }
            if (-not $dl.StartsWith($ol + '\')) { continue }
            if (-not $o.auto -or $r.auto) { $inner = $true; break }
        }
        if (-not $inner) { $final.Add($r) }
    }

    # 스캔(.NET 열거 — 깊이 우선, 폴더 단위 예산 확인, 재분석 지점(junction) 은 내려가지 않는다)
    $cands = New-Object 'Collections.Generic.List[psobject]'
    $seenFiles = New-Object 'Collections.Generic.HashSet[string]'
    $scanWatch = [Diagnostics.Stopwatch]::StartNew()
    $budgetHit = $false
    $nInRange = 0
    $maxSeen = $null
    $nDup = 0
    foreach ($r in $final) {
        if ($budgetHit) { break }
        $stack = New-Object 'Collections.Generic.Stack[psobject]'
        $stack.Push([pscustomobject]@{ d = $r.path; depth = 0 })
        while ($stack.Count -gt 0) {
            if ($scanWatch.Elapsed.TotalSeconds -gt $budgetSec) { $budgetHit = $true; break }
            $it = $stack.Pop()
            $dir = $it.d
            $dl = $dir.ToLower()
            if (Test-LmSelfDir $dl) { $script:NSelf++; continue }
            $di = New-Object IO.DirectoryInfo $dir
            $entries = @()
            try { $entries = @($di.EnumerateFileSystemInfos()) } catch { continue }
            foreach ($e in $entries) {
                if ($e -is [IO.DirectoryInfo]) {
                    if ([int]$e.Attributes -band 0x400) { continue }
                    if ($it.depth + 1 -gt $r.depth) { continue }
                    $sub = $e.FullName.ToLower() + '\'
                    if (Test-LmPkgPath $sub '') { $script:NPkg++; continue }
                    if (Test-LmFolderName $sub) { $script:NFolderName++; continue }
                    $stack.Push([pscustomobject]@{ d = $e.FullName; depth = $it.depth + 1 })
                    continue
                }
                $mt = $e.LastWriteTimeUtc
                if ($mt -lt $rg.SinceUtc -or $mt -ge $rg.UntilUtc) { continue }
                $ext = Get-LmWatchExt $e.Name
                if (-not $ext) { continue }
                $pl = $e.FullName.ToLower()
                if (Test-LmPkgPath $pl $ext) { $script:NPkg++; continue }
                if (Test-LmFolderName $pl) { $script:NFolderName++; continue }
                if (-not $seenFiles.Add($pl)) { $nDup++; continue }
                $nInRange++
                if ($null -eq $maxSeen -or $mt -gt $maxSeen) { $maxSeen = $mt }
                if ($null -ne $curUtc -and $mt -le $curUtc) { continue }
                $cands.Add([pscustomobject]@{ fi = $e; ext = $ext; mt = $mt; rid = $r.rid })
            }
        }
    }

    # 정렬(시각·경로) → 같은 (분, 폴더) 뭉치 상한 → 레코드
    $sorted = @($cands | Sort-Object -Property @{ Expression = { $_.mt } }, @{ Expression = { $_.fi.FullName } })
    $cap = $burstN * 5 + 1
    $perMin = @{}
    $nCapped = 0
    $obs = Format-LmUtc $nowUtc
    $n = 0
    foreach ($c in $sorted) {
        $fi = $c.fi
        $grp = $c.mt.ToString('yyyyMMddHHmm', $script:Inv) + '|' + $fi.DirectoryName.ToLower()
        $k = 0
        if ($perMin.ContainsKey($grp)) { $k = $perMin[$grp] }
        $perMin[$grp] = $k + 1
        if ($k + 1 -gt $cap) { $nCapped++; continue }
        $op = 'modify'
        if ([math]::Abs(($fi.CreationTimeUtc - $c.mt).TotalSeconds) -le 60) { $op = 'create' }
        Write-LmFileRecord $fi $c.ext $c.mt $c.rid $op $obs
        $n++
    }
    $newCur = $curUtc
    if (-not $budgetHit -and $null -ne $maxSeen -and ($null -eq $newCur -or $maxSeen -gt $newCur)) { $newCur = $maxSeen }
    Write-LmCursor (New-LmFileCursor $newCur (Get-LmCursorField 'poll_ts_utc'))

    if ($n -gt 0) { $script:Rc = 0 } elseif ($nInRange -gt 0) { $script:Rc = 4 } else { $script:Rc = 1 }
    if ($budgetHit) { Add-LmReason 'R-BUDGET'; $script:St['partial'] = $true; $script:St['budget_hit'] = $true }
    if ($nCapped -gt 0) { Add-LmReason 'R-CAP'; $script:St['partial'] = $true; $script:St['cap_hit'] = $true }
    $script:St['n'] = $n
    $script:St['in_range'] = $nInRange
    $script:St['roots'] = [ordered]@{ watch = @($final | Where-Object { -not $_.auto }).Count; auto = @($final | Where-Object { $_.auto }).Count;
                                      missing = $missing }
    $script:St['auto_sources'] = $script:SrcStat
    $script:St['excluded'] = [ordered]@{ self = $script:NSelf; package = $script:NPkg; folder_name = $script:NFolderName;
                                         private_candidates = $script:NPrivCand; duplicates = $nDup }
    $script:St['burst_capped'] = $nCapped
    $script:St['ooxml'] = [ordered]@{ tried = $script:NAuthorTry; slow = $script:NAuthorSlow; timed_out = $script:AuthorTimedOut }
    $script:St['scan_ms'] = [int]$scanWatch.Elapsed.TotalMilliseconds
}

$script:St = New-LmStatus 'pc.files'
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
