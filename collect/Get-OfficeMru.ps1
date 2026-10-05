<#
.SYNOPSIS
  pc.mru 수집기(CP §5.3, 계약 §2.17) — Office 최근 문서 MRU(14.0·15.0·16.0 전수) + Windows Jump Lists 를 NDJSON 으로 낸다.

.DESCRIPTION
  이전 판은 Office\16.0 하드코딩이라 Office 2013(15.0)·2010(14.0) PC 가 0건이었다(실측). LM27 은 pc.mru.officeVersions
  (기본 14.0·15.0·16.0)를 전수 열거한다.
    · HKCU\Software\Microsoft\Office\<ver>\<App>\File MRU(로컬 계정) 그리고 …\<App>\User MRU\<LiveId_*|ADAL_*>\File MRU
      (M365·조직 로그인 — 최상위 File MRU 는 0건, User MRU 아래만 실측). Place MRU(폴더 목록)는 제외.
    · 값 '[F…][T<16진 FILETIME>][O…]*<경로>' → 열람 시각(UTC) · 경로. 대상의 현재 수정 시각(target_mtime)이 열람보다
      2분 넘게 과거면 op=open(열람만), 아니면 modify.
    · Jump Lists(%APPDATA%\Microsoft\Windows\Recent\AutomaticDestinations\*.automaticDestinations-ms)의 DestList —
      CAD·해석 도구 .lnk 미생성 보완(pc.mru.jumpList, -NoJumpList 로 끔).
  자기 제외(X-316)·빌드 폴더·폴더명 제외는 파일 수집기와 같은 규칙. 원시 경로는 stdout 으로만(디스크 쓰기 없음 — L-09).
  rc(계약 §8.1): 0 새 항목 있음 · 1 MRU·Jump List 0건(R-MRUEMPTY — 경고) · 4 읽었지만 커서 뒤 새 항목 0.

.PARAMETER MruRegFile
  시험 주입(계약 §11.3 · X-142): 레지스트리 대신 이 reg 내보내기 텍스트(UTF-16 LE BOM 또는 UTF-8)를 읽는다
.PARAMETER NoJumpList
  Jump Lists 를 읽지 않는다(pc.mru.jumpList=false 와 같다)
.PARAMETER TestNow
  시험 주입: '지금'(로컬 'yyyy-MM-dd HH:mm' 또는 UTC 'yyyy-MM-ddTHH:mm:ssZ')
#>
param(
    [string]$Pc = '',
    [string]$Since = '',
    [string]$Until = '',
    [int]$Days = 0,
    [string]$MruRegFile = '',
    [switch]$NoJumpList,
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
# ───────────────────────── Jump Lists(AutomaticDestinations-ms) — 복합 문서(CFB) 의 DestList 스트림 ─────────────────────────
# CAD·해석 도구가 Recent .lnk 를 남기지 않는 빈자리를 메우는 보조 출처(CP §5.3). 파일은 읽기만 한다(다른 프로세스가 쓰는 중이어도
# 공유 읽기). DestList 항목의 경로·마지막 사용 시각(FILETIME)만 쓰고, 항목 안 NetBIOS 이름 등은 읽지 않는다.
function Read-LmFileShared([string]$p) {
    $fs = $null
    try {
        $fs = [IO.File]::Open($p, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        if ($fs.Length -gt 16MB) { return $null }
        $buf = New-Object byte[] ([int]$fs.Length)
        $got = 0
        while ($got -lt $buf.Length) {
            $n = $fs.Read($buf, $got, $buf.Length - $got)
            if ($n -le 0) { break }
            $got += $n
        }
        return ,$buf
    } catch { return $null } finally { if ($null -ne $fs) { $fs.Dispose() } }
}

function Get-LmChain($fat, [int]$start) {
    $out = New-Object 'Collections.Generic.List[int]'
    $s = $start
    while ($s -ge 0 -and $s -lt $fat.Count -and $out.Count -le $fat.Count) { $out.Add($s); $s = $fat[$s] }
    return ,$out
}

function Read-LmSectors([byte[]]$b, $chain, [int]$size, [long]$len) {
    $ms = New-Object IO.MemoryStream
    foreach ($s in $chain) {
        $o = [long]($s + 1) * $size
        if ($o -ge $b.Length) { break }
        $n = [int][math]::Min($size, $b.Length - $o)
        $ms.Write($b, [int]$o, $n)
    }
    $r = $ms.ToArray()
    if ($len -ge 0 -and $r.Length -gt $len) {
        $t = New-Object byte[] ([int]$len)
        [Array]::Copy($r, $t, [int]$len)
        $r = $t
    }
    return ,$r
}

# CFB 안의 스트림 하나(이름 일치)를 바이트로. 형식이 아니거나 없으면 $null.
function Read-LmCfbStream([byte[]]$b, [string]$want) {
    if ($null -eq $b -or $b.Length -lt 512) { return $null }
    $sig = @(0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1)
    for ($i = 0; $i -lt 8; $i++) { if ($b[$i] -ne $sig[$i]) { return $null } }
    $shift = [BitConverter]::ToUInt16($b, 0x1E)
    if ($shift -ne 9 -and $shift -ne 12) { return $null }
    $ss = 1 -shl $shift
    $mss = 1 -shl [BitConverter]::ToUInt16($b, 0x20)
    $dirStart = [BitConverter]::ToInt32($b, 0x30)
    $cutoff = [BitConverter]::ToUInt32($b, 0x38)
    $miniFatStart = [BitConverter]::ToInt32($b, 0x3C)
    $dif = [BitConverter]::ToInt32($b, 0x44)
    $fatSecs = New-Object 'Collections.Generic.List[int]'
    for ($i = 0; $i -lt 109; $i++) { $s = [BitConverter]::ToInt32($b, 0x4C + 4 * $i); if ($s -ge 0) { $fatSecs.Add($s) } }
    $guard = 0
    while ($dif -ge 0 -and $guard -lt 1024) {
        $guard++
        $o = [long]($dif + 1) * $ss
        if ($o + $ss -gt $b.Length) { break }
        $per = $ss / 4 - 1
        for ($i = 0; $i -lt $per; $i++) { $s = [BitConverter]::ToInt32($b, [int]$o + 4 * $i); if ($s -ge 0) { $fatSecs.Add($s) } }
        $dif = [BitConverter]::ToInt32($b, [int]$o + 4 * $per)
    }
    $fat = New-Object 'Collections.Generic.List[int]'
    foreach ($fs in $fatSecs) {
        $o = [long]($fs + 1) * $ss
        if ($o + $ss -gt $b.Length) { continue }
        for ($i = 0; $i -lt $ss / 4; $i++) { $fat.Add([BitConverter]::ToInt32($b, [int]$o + 4 * $i)) }
    }
    $dir = Read-LmSectors $b (Get-LmChain $fat $dirStart) $ss -1
    $root = $null
    $hit = $null
    for ($e = 0; $e + 128 -le $dir.Length; $e += 128) {
        $nl = [BitConverter]::ToUInt16($dir, $e + 0x40)
        $type = $dir[$e + 0x42]
        $name = ''
        if ($nl -ge 2 -and $nl -le 64) { $name = [Text.Encoding]::Unicode.GetString($dir, $e, $nl - 2) }
        $st = [BitConverter]::ToInt32($dir, $e + 0x74)
        $sz = [long][BitConverter]::ToUInt32($dir, $e + 0x78)
        if ($type -eq 5) { $root = @{ start = $st; size = $sz } }
        elseif ($type -eq 2 -and $name -eq $want) { $hit = @{ start = $st; size = $sz } }
    }
    if ($null -eq $hit) { return $null }
    if ($hit.size -lt $cutoff -and $null -ne $root) {
        $mini = Read-LmSectors $b (Get-LmChain $fat $root.start) $ss $root.size
        $mfBytes = Read-LmSectors $b (Get-LmChain $fat $miniFatStart) $ss -1
        $mfat = New-Object 'Collections.Generic.List[int]'
        for ($i = 0; $i + 4 -le $mfBytes.Length; $i += 4) { $mfat.Add([BitConverter]::ToInt32($mfBytes, $i)) }
        $ms = New-Object IO.MemoryStream
        foreach ($s in (Get-LmChain $mfat $hit.start)) {
            $o = $s * $mss
            if ($o -ge $mini.Length) { break }
            $ms.Write($mini, $o, [int][math]::Min($mss, $mini.Length - $o))
        }
        $r = $ms.ToArray()
        if ($r.Length -gt $hit.size) {
            $t = New-Object byte[] ([int]$hit.size)
            [Array]::Copy($r, $t, [int]$hit.size)
            $r = $t
        }
        return ,$r
    }
    return (Read-LmSectors $b (Get-LmChain $fat $hit.start) $ss $hit.size)
}

# DestList → [{path, utc}] — 판 1·2(Windows 7·8: 경로 길이 0x6C) · 판 3 이상(Windows 10·11: 0x7C, 항목 끝 4바이트)
function Read-LmDestList([byte[]]$d) {
    $out = New-Object 'Collections.Generic.List[psobject]'
    if ($null -eq $d -or $d.Length -lt 32) { return ,$out }
    $ver = [BitConverter]::ToInt32($d, 0)
    $n = [BitConverter]::ToInt32($d, 4)
    if ($ver -ge 3) { $lenOff = 0x7C; $pathOff = 0x7E; $tail = 4 } else { $lenOff = 0x6C; $pathOff = 0x6E; $tail = 0 }
    $pos = 32
    for ($i = 0; $i -lt $n -and $pos + $pathOff -le $d.Length; $i++) {
        $ft = [BitConverter]::ToInt64($d, $pos + 0x60)
        $len = [BitConverter]::ToUInt16($d, $pos + $lenOff)
        if ($pos + $pathOff + 2 * $len -gt $d.Length) { break }
        $path = [Text.Encoding]::Unicode.GetString($d, $pos + $pathOff, 2 * $len)
        $utc = $null
        if ($ft -gt 0) { try { $utc = [datetime]::FromFileTimeUtc($ft) } catch { $utc = $null } }
        $out.Add([pscustomobject]@{ path = $path; utc = $utc })
        $pos += $pathOff + 2 * $len + $tail
    }
    return ,$out
}

Set-LmOutput

$OpenSlackMin = 2               # target_mtime 이 열람보다 이만큼 넘게 과거면 '열람만'(CP §5.3)
$MruKeyRe = '\\software\\microsoft\\office\\(\d+\.\d+)\\([^\\]+)\\(?:user mru\\([^\\]+)\\)?file mru$'
$MruValRe = '\[T([0-9A-Fa-f]{16})\](?:\[[^\]]*\])*\*(.+)$'

$script:Items = New-Object 'Collections.Generic.List[psobject]'

function Add-LmMruValue([string]$val, [string]$src) {
    if ($val -notmatch $MruValRe) { return }
    $hex = $Matches[1]
    $path = $Matches[2].Trim()
    if (-not $path) { return }
    $utc = $null
    try { $utc = [datetime]::FromFileTimeUtc([Convert]::ToInt64($hex, 16)) } catch { $utc = $null }
    if ($null -eq $utc) { return }
    $script:Items.Add([pscustomobject]@{ path = $path; utc = $utc; src = $src })
}

# 레지스트리(또는 reg 내보내기 재생)에서 MRU 항목. → 읽은 MRU 키 수
function Read-LmOfficeMru([string[]]$versions) {
    $nKeys = 0
    $vset = @($versions | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    if ($MruRegFile) {
        $reg = Read-LmRegFile $MruRegFile
        foreach ($k in @($reg.PSBase.Keys | Sort-Object)) {
            if ($k -notmatch $MruKeyRe) { continue }
            if ($vset -notcontains $Matches[1]) { continue }
            $nKeys++
            foreach ($vn in @($reg[$k].PSBase.Keys)) {
                if ($vn -notlike 'Item *') { continue }
                Add-LmMruValue ([string]$reg[$k][$vn]) 'mru'
            }
        }
        return $nKeys
    }
    foreach ($ver in $vset) {
        $base = 'HKCU:\Software\Microsoft\Office\' + $ver
        if (-not (Test-Path -LiteralPath $base)) { continue }
        foreach ($app in @(Get-ChildItem -LiteralPath $base -ErrorAction SilentlyContinue)) {
            $keys = New-Object 'Collections.Generic.List[string]'
            $keys.Add((Join-Path $app.PSPath 'File MRU'))
            $um = Join-Path $app.PSPath 'User MRU'
            if (Test-Path -LiteralPath $um) {
                foreach ($u in @(Get-ChildItem -LiteralPath $um -ErrorAction SilentlyContinue)) { $keys.Add((Join-Path $u.PSPath 'File MRU')) }
            }
            foreach ($key in $keys) {
                if (-not (Test-Path -LiteralPath $key)) { continue }
                $nKeys++
                $props = $null
                try { $props = Get-ItemProperty -LiteralPath $key -ErrorAction Stop } catch { continue }
                foreach ($p in $props.PSObject.Properties) {
                    if ($p.Name -notlike 'Item *') { continue }
                    Add-LmMruValue ([string]$p.Value) 'mru'
                }
            }
        }
    }
    return $nKeys
}

# Jump Lists → 읽은 파일 수
function Read-LmJumpLists {
    $base = ''
    if ($env:APPDATA) { $base = Join-Path $env:APPDATA 'Microsoft\Windows\Recent\AutomaticDestinations' }
    if (-not $base -or -not [IO.Directory]::Exists($base)) { return 0 }
    $nFiles = 0
    foreach ($f in @(Get-ChildItem -LiteralPath $base -Filter '*.automaticDestinations-ms' -File -ErrorAction SilentlyContinue | Sort-Object Name)) {
        $b = Read-LmFileShared $f.FullName
        if ($null -eq $b) { $script:NJumpErr++; continue }
        $d = Read-LmCfbStream $b 'DestList'
        if ($null -eq $d) { $script:NJumpErr++; continue }
        $nFiles++
        foreach ($e in (Read-LmDestList $d)) {
            if ($null -eq $e.utc -or -not $e.path) { continue }
            if ($e.path -notmatch '^(?:[A-Za-z]:\\|\\\\)') { continue }      # knownfolder:·shell: 표기·URL 은 건너뜀
            if (-not (Get-LmWatchExt ([IO.Path]::GetFileName($e.path)))) { continue }
            $script:Items.Add([pscustomobject]@{ path = $e.path; utc = $e.utc; src = 'jumplist' })
        }
    }
    return $nFiles
}

function Invoke-Main {
    Read-LmIn
    $script:St['in'] = $script:InState
    $nowUtc = Get-LmNow $TestNow
    $rg = Get-LmRange $Since $Until $Days $nowUtc
    $script:St['range'] = @($rg.From, $rg.To)
    $curUtc = Get-LmCursorUtc
    $script:NJumpErr = 0
    Initialize-LmExt @(Get-LmCfg 'pc.watchExtensions' $null)
    Initialize-LmFolderNames @(Get-LmCfg 'pc.excludeFolderNames' @())
    Initialize-LmFinalWords @(Get-LmCfg 'episode.finalWords' @())
    $script:PkgOn = [bool](Get-LmCfg 'pc.excludePackageDirs' $true)
    Initialize-LmKnownDirs ([bool]($TestNow -or $MruRegFile))
    $versions = @(Get-LmCfg 'pc.mru.officeVersions' @('14.0', '15.0', '16.0'))
    if ($versions.Count -eq 0) { $versions = @('14.0', '15.0', '16.0') }
    $useJump = [bool](Get-LmCfg 'pc.mru.jumpList' $true) -and -not $NoJumpList

    $nKeys = Read-LmOfficeMru $versions
    $nMru = $script:Items.Count
    $nJump = 0
    if ($useJump) { $nJump = Read-LmJumpLists }
    $nJumpItems = $script:Items.Count - $nMru

    $obs = Format-LmUtc $nowUtc
    $seen = New-Object 'Collections.Generic.HashSet[string]'
    $nInRange = 0
    $maxSeen = $null
    $out = New-Object 'Collections.Generic.List[psobject]'
    foreach ($it in ($script:Items | Sort-Object -Property @{ Expression = { $_.utc } }, @{ Expression = { $_.path } })) {
        if ($it.utc -lt $rg.SinceUtc -or $it.utc -ge $rg.UntilUtc) { continue }
        $pl = $it.path.ToLower()
        if (-not $seen.Add($pl + '|' + (Format-LmUtc $it.utc))) { continue }
        if ($pl -notmatch '^[a-z]+://') {
            $dir = ''
            try { $dir = [IO.Path]::GetDirectoryName($it.path) } catch { $dir = '' }
            if ($dir -and (Test-LmSelfDir $dir)) { $script:NSelf++; continue }
            $ext = Get-LmWatchExt ([IO.Path]::GetFileName($it.path))
            if (Test-LmPkgPath $pl $ext) { $script:NPkg++; continue }
            if (Test-LmFolderName $pl) { $script:NFolderName++; continue }
        }
        $nInRange++
        if ($null -eq $maxSeen -or $it.utc -gt $maxSeen) { $maxSeen = $it.utc }
        if ($null -ne $curUtc -and $it.utc -le $curUtc) { continue }
        $out.Add($it)
    }
    foreach ($it in $out) {
        $st = Get-LmTargetStat $it.path
        $op = 'open'
        $size = $null
        $tm = $null
        if ($null -ne $st) {
            $size = $st.size
            $tm = Format-LmUtc $st.mtime
            if ($st.mtime -ge $it.utc.AddMinutes(-$OpenSlackMin)) { $op = 'modify' }
        }
        $fr = Get-LmFolderRole $it.path $false
        $flags = [ordered]@{}
        if ($fr.autosave) { $flags['autosave'] = $true }
        if (Test-LmFinalName $it.path) { $flags['final_name'] = $true }
        Write-LmRecord ([ordered]@{
            path = $it.path; op = $op; size = $size
            target_mtime = $tm; pdf_sibling = $false; folder_role = $fr.role; root_id = $null
            ts_utc = (Format-LmUtc $it.utc); ts_local_offset = (Format-LmOffset $it.utc); ts_precision = 'minute'
            observed_at = $obs; confidence = 0.8; flags = $flags
        })
    }
    $newCur = $curUtc
    if ($null -ne $maxSeen -and ($null -eq $newCur -or $maxSeen -gt $newCur)) { $newCur = $maxSeen }
    $curVal = $null
    if ($null -ne $newCur) { $curVal = Format-LmUtc $newCur }
    Write-LmCursor ([ordered]@{ last_ts_utc = $curVal })

    if ($out.Count -gt 0) { $script:Rc = 0 }
    elseif ($nInRange -gt 0) { $script:Rc = 4 }
    else {
        $script:Rc = 1
        if ($script:Items.Count -eq 0) { Add-LmReason 'R-MRUEMPTY' }
    }
    $script:St['n'] = $out.Count
    $script:St['in_range'] = $nInRange
    $script:St['mru'] = [ordered]@{ versions = @($versions); key_count = $nKeys; items = $nMru }
    $script:St['jumplist'] = [ordered]@{ on = [bool]$useJump; files = $nJump; items = $nJumpItems; errors = $script:NJumpErr }
    $script:St['excluded'] = [ordered]@{ self = $script:NSelf; package = $script:NPkg; folder_name = $script:NFolderName }
}

$script:St = New-LmStatus 'pc.mru'
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
