# Get-FileActivity.ps1
# Scans configured work folders for recently modified files (proxy for untracked work,
# e.g. verbally-ordered tasks that only show up as file edits).
# Output: ..\data\files\files.csv          (overwrite, UTF-8)  mtime,ext,size_kb,folder,name,author
#         ..\data\files\files_history.csv  (accumulated union of every run, same header, 400 days)
#         ..\data\files_excluded.json      ("files" section: what was dropped, by keyword / package dir)
# author: Office(OOXML) 문서는 docProps/core.xml 의 lastModifiedBy, UNC 공유의 다른 파일은 NTFS 소유자,
#         로컬 폴더의 그 외 파일은 '' (ACL 비용 회피). 동료가 동기화 폴더에 저장한 파일을 extract 가 거른다.
# ext:    watchExtensions 판정은 이름 끝 기준 - 복합 확장자(.cas.gz)·Creo 판번호(bracket.prt.12 → .prt)도 잡는다.
#         내용은 열지 않는다(수 GB 해석 결과도 시각·크기만) - Office author 읽기만 예외.
param(
    [string]$From = '',
    [string]$To = '',
    [int]$Days = 90,
    [string]$RecentDir = '',     # 시험용: Recent 폴더 대신 이 폴더의 .lnk 로 자동 발견
    [string]$MruTextDir = '',    # 시험용: 도구별 MRU 파일 대신 이 폴더의 텍스트 파일에서 경로를 수확
    [switch]$NoToolMru           # 시험용: 도구·대화상자 MRU 자동 발견 생략 (.lnk 만)
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$cfg  = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json
$outDir = Join-Path $root 'data\files'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}

# .tmp 에 쓰고 성공 시 교체 - 수집기가 중간에 죽어도 지난 CSV 가 반쪽으로 남지 않는다.
# 임시 이름에 $PID - UI [분석 실행] 과 bat 수집이 겹치면 고정 이름 .tmp 를 두 인스턴스가 함께 써서 뒤 인스턴스가
# WriteAllLines 의 IOException 으로 rc 1 로 죽었다(C4). 교체 단계는 상대가 잠깐 잡고 있을 수 있어 짧게 재시도한다.
function Move-TempFile([string]$tmp, [string]$path) {
    for ($try = 1; $try -le 25; $try++) {
        try {
            if (Test-Path -LiteralPath $path) { [System.IO.File]::Replace($tmp, $path, $null) }
            else { [System.IO.File]::Move($tmp, $path) }
            return
        } catch {
            $err = $_          # 안쪽 try/catch 뒤의 맨몸 throw 는 원래 오류를 잃을 수 있어 잡아 둔다
            try { [System.IO.File]::Copy($tmp, $path, $true); [System.IO.File]::Delete($tmp); return } catch {}
            if ($try -ge 25) { throw $err }
            Start-Sleep -Milliseconds 200
        }
    }
}
# 동시 실행 중 상대 인스턴스가 파일을 교체하는 순간이면 열기가 잠깐 실패한다 - 옛 이력을 '읽기 실패' 로 버리지 않도록 재시도
function Read-CsvRetry([string]$path) {
    for ($try = 1; $try -le 5; $try++) {
        try { return @(Import-Csv -LiteralPath $path -Encoding UTF8) }
        catch { if ($try -ge 5) { throw $_ }; Start-Sleep -Milliseconds 300 }
    }
}
function Write-Lines([string]$path, $lines) {
    $tmp = '{0}.{1}.tmp' -f $path, $PID
    [System.IO.File]::WriteAllLines($tmp, [string[]]$lines, [System.Text.Encoding]::UTF8)
    Move-TempFile $tmp $path
}

# 관측 누적 - 다음 수정으로 mtime 이 덮이기 전에 이번 실행이 본 (mtime,folder,name) 을 보관한다.
# 매 실행 통째로 덮어쓰던 예전 방식은 3개월 분석에서 앞 달의 파일 근거를 버렸다(실측 -10pt).
# capPerMin: 같은 (분, 폴더) 에 이 수를 넘는 행은 이력에 보관하지 않는다 - 시뮬레이션 결과 폴더·OneDrive 재동기화가
#   한 분에 수천 행을 남겨 400일 이력이 부풀던 것 방지. 상한은 extract 의 '기계 생성' 문턱(fileBurstN×5)보다 크게 잡아
#   버스트·기계 생성 판정은 그대로다(스냅샷 files.csv 는 자르지 않는다).
function Merge-History([string]$histPath, [string[]]$header, $newLines, $newKeys, [string]$tag, [int]$capPerMin = 0) {
    $keepFrom = (Get-Date).AddDays(-400)
    $byKey = New-Object 'System.Collections.Generic.Dictionary[string,string]'
    $nOld = 0
    if (Test-Path -LiteralPath $histPath) {
        try {
            foreach ($o in @(Read-CsvRetry $histPath)) {
                $mt = [string]$o.mtime
                if (-not $mt) { continue }
                $t = $null
                try { $t = [datetime]::ParseExact($mt, 'yyyy-MM-dd HH:mm', $null) } catch { continue }
                if ($t -lt $keepFrom) { continue }
                $vals = New-Object System.Collections.Generic.List[string]
                foreach ($h in $header) {        # 옛 스키마(열 부족)는 빈 값으로 채운다 - extract 는 열 수 부족 행을 버린다
                    $v = $o.$h
                    if ($null -eq $v) { $vals.Add('') } else { $vals.Add((Csv-Escape ([string]$v))) }
                }
                $byKey[($mt + '|' + [string]$o.folder + '|' + [string]$o.name)] = ($vals -join ',')
                $nOld++
            }
        } catch { Write-Host ("[{0}] history 읽기 실패({1}) - 이번 실행분으로 새로 만듭니다" -f $tag, $_.Exception.Message) }
    }
    for ($i = 0; $i -lt $newLines.Count; $i++) { $byKey[$newKeys[$i]] = $newLines[$i] }
    $out = New-Object System.Collections.Generic.List[string]
    $out.Add(($header -join ','))
    $months = @{}
    $nCap = 0; $grp = ''; $nGrp = 0
    foreach ($k in ($byKey.Keys | Sort-Object)) {      # 키가 mtime|folder|name 순이라 같은 (분, 폴더) 가 연속한다
        if ($capPerMin -gt 0) {
            $g = $k.Substring(0, $k.LastIndexOf('|'))
            if ($g -eq $grp) { $nGrp++ } else { $grp = $g; $nGrp = 1 }
            if ($nGrp -gt $capPerMin) { $nCap++; continue }
        }
        $out.Add($byKey[$k]); $months[$k.Substring(0, 7)] = 1
    }
    Write-Lines $histPath $out
    return @{ total = ($out.Count - 1); old = $nOld; months = $months.Count; capped = $nCap }
}

# data\files_excluded.json - 파일·Recent·git 수집기가 각자 절(section)만 바꿔 쓴다
function Update-ExcludedJson([string]$section, $payload) {
    $p = Join-Path $root 'data\files_excluded.json'
    $doc = [ordered]@{}
    if (Test-Path -LiteralPath $p) {
        try {
            $j = Get-Content -Raw -Encoding UTF8 -LiteralPath $p | ConvertFrom-Json
            foreach ($pr in $j.PSObject.Properties) { $doc[$pr.Name] = $pr.Value }
        } catch {}
    }
    $doc[$section] = $payload
    $json = $doc | ConvertTo-Json -Depth 8
    $tmp = '{0}.{1}.tmp' -f $p, $PID       # 고정 이름 .tmp 는 동시 실행에서 충돌한다(C4)
    [System.IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding($false)))
    Move-TempFile $tmp $p
}

if ($From) { $since = [datetime]::ParseExact($From, 'yyyy-MM-dd', $null) } else { $since = (Get-Date).Date.AddDays(-$Days) }
if ($To)   { $until = ([datetime]::ParseExact($To, 'yyyy-MM-dd', $null)).AddDays(1) } else { $until = (Get-Date).Date.AddDays(1) }
# config 에 키가 없으면 $null 이 파이프로 흘러 .ToLower() 가 터진다($ErrorActionPreference='Stop'
# 이라 수집기 전체가 즉사) - null 을 먼저 걸러낸다.
$exts = @(@($cfg.watchExtensions) | Where-Object { $_ } | ForEach-Object { ([string]$_).Trim().ToLower() } | Where-Object { $_.StartsWith('.') } | Select-Object -Unique)
$excl = @(@($cfg.excludePathKeywords) | Where-Object { $_ } | ForEach-Object { $_.ToLower() })

# ── 확장자 판정 (Get-RecentFiles.ps1 과 같은 규칙) - 세 종류를 이름 끝으로 본다 ──
#  · 단일(.zmx) : HashSet - 목록이 180개라 -contains 선형 탐색은 5만 파일에서 수 초를 먹는다
#  · 복합(.cas.gz .dat.gz) : $_.Extension 은 .gz 만 주므로 이름 끝 일치 - Fluent 는 기본이 압축 저장
#  · Creo 판번호(bracket.prt.12 · .asm.3 · .drw.7) : 확장자가 .12 가 되어 통째로 빠지던 것 - 기본 확장자로 기록
#  · thumbs.db(사진 폴더마다 자동 생성)·desktop.ini·JS 소스맵(app.js.map ≠ 링커 .map) 은 확장자가 맞아도 제외
$extSet = New-Object 'System.Collections.Generic.HashSet[string]'
$extCompound = New-Object System.Collections.Generic.List[string]
foreach ($e in $exts) { if (($e.TrimStart('.') -split '\.').Count -gt 1) { $extCompound.Add($e) } else { [void]$extSet.Add($e) } }
$creoRe = New-Object System.Text.RegularExpressions.Regex '\.(prt|asm|drw|frm|sec|lay|mfg|gph|neu)\.\d{1,4}$'
$ignoreNames = @('thumbs.db', 'ehthumbs.db', 'ehthumbs_vista.db', 'desktop.ini', '.ds_store')
function Get-WatchExt([string]$name) {     # 감시 대상이면 CSV 에 적을 확장자(소문자), 아니면 ''
    if (-not $name) { return '' }
    $nl = $name.ToLower()
    if ($ignoreNames -contains $nl) { return '' }
    if ($nl.EndsWith('.map') -and $nl -match '\.(js|css|mjs|cjs|ts|tsx)\.map$') { return '' }
    foreach ($ce in $extCompound) { if ($nl.EndsWith($ce)) { return $ce } }
    $m = $creoRe.Match($nl)
    if ($m.Success) { $b = '.' + $m.Groups[1].Value; if ($extSet.Contains($b)) { return $b } else { return '' } }
    $i = $nl.LastIndexOf('.')
    if ($i -lt 0) { return '' }
    $e = $nl.Substring($i)
    if ($extSet.Contains($e)) { return $e }
    return ''
}

# ── excludePathKeywords 판정 - 세 수집기(파일·Recent·git)·core/extract._text_filter 와 같은 규칙 ──
#  · 경로 전용 토큰(temp·downloads·임시·다운로드)은 폴더명 완전 일치 - 'temp' 부분일치가
#    Temperature_Test·template·temp_sensor 를 조용히 지우던 실측 경로 차단
#  · ASCII 키워드는 단어 경계 ('resume'⊄'presume')
#  · 한글은 부분일치 유지 ('개인'⊂'개인자료' - 마지막 방어선)
$pathOnly  = @('temp', 'downloads', '임시', '다운로드')
$exclSeg   = @($excl | Where-Object { $pathOnly -contains $_ })
$exclKr    = @($excl | Where-Object { $_ -notmatch '^[\x00-\x7F]+$' -and $pathOnly -notcontains $_ })
$exclAscii = @($excl | Where-Object { $_ -match '^[\x00-\x7F]+$' -and $pathOnly -notcontains $_ })
$exclRe = $null
if ($exclAscii.Count -gt 0) {
    $exclRe = New-Object System.Text.RegularExpressions.Regex ('(?<![a-z0-9])(' + (($exclAscii | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')(?![a-z0-9])')
}
$sepChars = [char[]]@('\', '/')
function Test-ExclPath([string]$pl) {      # $pl: 소문자 전체 경로 → 걸린 키워드 또는 ''
    if ($exclSeg.Count -gt 0) {
        $segs = $pl.Split($sepChars)
        foreach ($k in $exclSeg) { if ($segs -contains $k) { return $k } }
    }
    foreach ($k in $exclKr) { if ($pl.Contains($k)) { return $k } }
    if ($null -ne $exclRe) { $m = $exclRe.Match($pl); if ($m.Success) { return $m.Groups[1].Value } }
    return ''
}
# 무엇이 빠졌는지 (키워드 → 파일 수·폴더 수) 집계 - 조용한 삭제 금지. 경로 자체는 남기지 않는다(개인정보)
$exclStat = @{}
function Note-Excl([string]$k, [string]$dir) {
    if (-not $exclStat.ContainsKey($k)) { $exclStat[$k] = @{ files = 0; dirs = @{} } }
    $exclStat[$k]['files']++
    $exclStat[$k]['dirs'][$dir.ToLower()] = 1
}

# ── 폴더명 제외 (config.excludeFolderNames) - 폴더명 완전 일치·대소문자 무시. 사용자가 고른 이름만 ──
$folderNames = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($n in @(@($cfg.excludeFolderNames) | Where-Object { $_ })) { [void]$folderNames.Add(([string]$n).Trim().ToLower().Trim('\')) }
$fnStat = @{}
function Test-FolderName([string]$pl) {    # $pl: 소문자 전체 경로(끝이 파일명 또는 '\') → 걸린 폴더명 또는 ''
    if ($folderNames.Count -eq 0) { return '' }
    $segs = $pl.Split($sepChars)
    for ($i = 0; $i -lt $segs.Length - 1; $i++) { if ($segs[$i] -and $folderNames.Contains($segs[$i])) { return $segs[$i] } }
    return ''
}
function Note-FolderName([string]$k, [string]$dir) {
    if (-not $fnStat.ContainsKey($k)) { $fnStat[$k] = @{ files = 0; dirs = @{} } }
    $fnStat[$k]['files']++
    $fnStat[$k]['dirs'][$dir.ToLower()] = 1
}

# ── 패키지·빌드 폴더 제외 (config.excludePackageDirs, 기본 true) - 설치 시각 수천 .py 가 '파일(코드)' 로
#    과제 배분을 지배하던 결함. 파일·Recent 수집기가 같은 규칙을 쓴다 ──
#  · 이름만으로 확정: .venv·venv·site-packages·node_modules·__pycache__·.git·.idea·.vs·.vscode·.conda·cmake-build-*
#  · 이름이 업무 폴더와 겹치는 build·dist·target·release·debug·x64·env·packages 는 그 폴더(또는 바로 위 폴더)에
#    빌드 표식(CMakeCache.txt·pyvenv.cfg·*.obj/*.pdb/*.o·*.sln/*.vcxproj·package.json·Cargo.toml …)이 있을 때만 -
#    해석 결과를 Release\ 에, 도면 배포본을 release\ 에 두는 조직에서 그날 작업이 통째로 사라지던 것 방지.
#    (예전 정규식은 이름만 보고 지웠다 - 실측 우려: 'x64·release·target' 이름의 시뮬레이션 결과 폴더)
#  · 펌웨어·FPGA 빌드 산출물(.hex .elf .bin .map .bit .sof)은 빌드 폴더 안에 있는 것이 정상 - 빌드 시각이 곧 작업 흔적이라 통과
$pkgOn = $true
if ($null -ne $cfg.excludePackageDirs) { $pkgOn = [bool]$cfg.excludePackageDirs }
$pkgAlwaysRe = New-Object System.Text.RegularExpressions.Regex '\\(\.venv|venv|\.env|node_modules|site-packages|__pycache__|\.git|\.tox|\.nox|\.mypy_cache|\.pytest_cache|\.idea|\.vs|\.vscode|\.conda|conda-meta|cmake-build-[^\\]*)(?=\\)'
$pkgMaybeRe  = New-Object System.Text.RegularExpressions.Regex '\\(env|build|dist|target|packages|x64|debug|release)(?=\\)'
$markIn    = @('cmakecache.txt', 'cachedir.tag', 'pyvenv.cfg', 'build.ninja', '.ninja_log', 'compile_commands.json', 'objects.list',
               'repositories.config', 'makefile', 'cmakefiles', 'maven-status', 'conda-meta', 'site-packages', 'node_modules')
$markInSfx = @('.pdb', '.obj', '.ilk', '.idb', '.o', '.d', '.su', '.pch', '.whl', '.nupkg', '.jar', '.class', '.tlog', '.recipe', '.pyc', '.exp')
$markUp    = @('cmakelists.txt', 'package.json', 'setup.py', 'pyproject.toml', 'setup.cfg', 'cargo.toml', 'pom.xml', 'build.gradle',
               'build.gradle.kts', 'tsconfig.json', '.cproject', '.git', 'meson.build', 'sconstruct')
$markUpSfx = @('.sln', '.vcxproj', '.csproj', '.vbproj', '.fsproj', '.uvprojx', '.uvproj', '.ewp', '.ioc', '.pro', '.cbp')
$artefactExts = @('.hex', '.elf', '.bin', '.map', '.bit', '.sof')
$buildDirCache = @{}
function Test-Marks([string]$dir, [string[]]$exact, [string[]]$sfx) {
    try {
        $n = 0
        foreach ($p in [System.IO.Directory]::EnumerateFileSystemEntries($dir)) {
            if (++$n -gt 5000) { break }
            $b = [System.IO.Path]::GetFileName($p).ToLower()
            if ($exact -contains $b) { return $true }
            foreach ($s in $sfx) { if ($b.EndsWith($s)) { return $true } }
        }
    } catch {}
    return $false
}
function Test-BuildDir([string]$dir) {      # $dir: 소문자, 끝 구분자 없음. 폴더당 1회만 본다(캐시)
    if ($buildDirCache.ContainsKey($dir)) { return $buildDirCache[$dir] }
    $r = Test-Marks $dir $markIn $markInSfx
    if (-not $r) { $up = Split-Path -Parent $dir; if ($up) { $r = Test-Marks $up $markUp $markUpSfx } }
    $buildDirCache[$dir] = $r
    return $r
}
function Test-PkgPath([string]$pl, [string]$ext) {   # $pl: 소문자 전체 경로 → 걸린 토큰 또는 ''
    if (-not $pkgOn) { return '' }
    $m = $pkgAlwaysRe.Match($pl)
    if ($m.Success) { return $m.Groups[1].Value }
    if ($ext -and $artefactExts -contains $ext) { return '' }
    foreach ($mm in $pkgMaybeRe.Matches($pl)) {
        $dir = $pl.Substring(0, $mm.Index + $mm.Length)
        if (Test-BuildDir $dir) { return $mm.Groups[1].Value }
    }
    return ''
}
$pkgStat = @{}
function Note-Pkg([string]$tok, [string]$dir) {
    if (-not $pkgStat.ContainsKey($tok)) { $pkgStat[$tok] = @{ files = 0; dirs = @{} } }
    $pkgStat[$tok]['files']++
    $pkgStat[$tok]['dirs'][$dir.ToLower()] = 1
}

# 자기 설치 폴더 제외 - report\ 의 결과 CSV·내장 python\ 수천 파일이 '업무 파일'로
# 수집되면(실측 의심: 회사 PC 파일 6,662건) 자기 출력이 다음 분석의 입력이 되는
# 되먹임이 생긴다. 이 설치본 전체와, 다른 LoadMonitor 설치의 산출물 폴더(data|report|teamdata|python)를
# 스캔에서 뺀다. core|collect|ui 까지 막던 예전 패턴은 이 도구를 개발하는 사람의 개발 흔적을 지웠다.
$selfRoot = $root.ToLower()
$script:nSelf = 0
function Test-SelfPath([string]$pl) {
    if ($pl.StartsWith($selfRoot)) { return $true }
    if ($pl -match '\\loadmonitor[^\\]*\\(data|report|teamdata|python)\\') { return $true }
    return $false
}

# ── 공유·동기화 폴더 판정 (UNC · OneDrive/SharePoint 동기화 루트) - author 판단 범위와 경고에 쓴다 ──
$syncRoots = New-Object System.Collections.Generic.List[string]
try {
    foreach ($acc in @(Get-ChildItem 'HKCU:\Software\Microsoft\OneDrive\Accounts' -ErrorAction SilentlyContinue)) {
        $uf = (Get-ItemProperty -LiteralPath $acc.PSPath -ErrorAction SilentlyContinue).UserFolder
        if ($uf) { $syncRoots.Add(([string]$uf).ToLower().TrimEnd('\') + '\') }
        $c = Join-Path $acc.PSPath 'ScopeIdToMountPointPathCache'
        if (Test-Path -LiteralPath $c) {
            foreach ($pr in (Get-ItemProperty -LiteralPath $c).PSObject.Properties) {
                if ($pr.Name -notlike 'PS*' -and $pr.Value) { $syncRoots.Add(([string]$pr.Value).ToLower().TrimEnd('\') + '\') }
            }
        }
    }
} catch {}
function Get-SharedRoot([string]$dir) {   # → @{ kind = 'unc'|'sync'; root = 공유 루트(소문자) } 또는 $null
    $dl = $dir.ToLower().TrimEnd('\') + '\'
    if ($dl.StartsWith('\\')) {
        $m = [regex]::Match($dl, '^\\\\[^\\]+\\[^\\]+\\')
        return @{ kind = 'unc'; root = $(if ($m.Success) { $m.Value } else { $dl }) }
    }
    foreach ($r in $syncRoots) { if ($dl.StartsWith($r)) { return @{ kind = 'sync'; root = $r } } }
    $m = [regex]::Match($dl, '^.*?\\onedrive( - [^\\]+)?\\')
    if (-not $m.Success) { $m = [regex]::Match($dl, '^.*? - (documents|문서)\\') }
    if ($m.Success) { return @{ kind = 'sync'; root = $m.Value } }
    return $null
}

# ── author - Office(OOXML) 는 lastModifiedBy, UNC 공유의 그 외 파일은 NTFS 소유자 ──
$zipOk = $false
try { Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop; $zipOk = $true }
catch { Write-Host '[files] 주의: ZIP 라이브러리 로드 실패 - Office 문서 author 를 읽지 못합니다' }
$ooxml = @('.docx', '.docm', '.dotx', '.pptx', '.pptm', '.potx', '.xlsx', '.xlsm', '.xlsb', '.vsdx')
$genericOwners = @('administrators', 'system', 'trustedinstaller', 'everyone', 'users', 'authenticated users',
                   'local service', 'network service', 'domain admins')
$authorDeadline = (Get-Date).AddSeconds(90)    # 큰 공유 폴더에서 run.py 단계 제한(300s)을 넘기지 않는다
$script:nAuthorTry = 0; $script:nAuthor = 0; $script:authorTimedOut = $false
$script:localAuthors = @{}
function Clean-Owner([string]$o) {
    if (-not $o) { return '' }
    if ($o -match '^(S-1-|O:)') { return '' }             # 풀리지 않은 SID
    $n = ($o -replace '^.*\\', '').Trim()
    if ($genericOwners -contains $n.ToLower()) { return '' }
    return $n
}
function Get-Author($fi, [string]$shared) {
    if ($script:authorTimedOut) { return '' }
    $ext = $fi.Extension.ToLower()
    $isOffice = $ooxml -contains $ext
    if (-not $isOffice -and $shared -ne 'unc') { return '' }   # 로컬·동기화 폴더의 비 Office 파일: 소유자는 늘 나 - 비용만 든다
    $attr = [int]$fi.Attributes
    # 자리표시자(OneDrive Files On-Demand 0x400000/0x40000)·오프라인(0x1000) 파일은 열면 내려받기가 시작된다
    if (($attr -band 0x400000) -or ($attr -band 0x40000) -or ($attr -band 0x1000)) { return '' }
    if ((Get-Date) -gt $authorDeadline) { $script:authorTimedOut = $true; return '' }
    $script:nAuthorTry++
    if ($isOffice) {
        if (-not $zipOk) { return '' }
        $z = $null
        try {
            $z = [System.IO.Compression.ZipFile]::OpenRead($fi.FullName)
            $e = $z.GetEntry('docProps/core.xml')
            if ($null -eq $e) { return '' }
            $sr = New-Object System.IO.StreamReader($e.Open())
            try { $xml = $sr.ReadToEnd() } finally { $sr.Dispose() }
            if ($xml -match '<cp:lastModifiedBy>([^<]*)</cp:lastModifiedBy>') {
                return [System.Net.WebUtility]::HtmlDecode($Matches[1]).Trim()
            }
        } catch {} finally { if ($null -ne $z) { $z.Dispose() } }
        return ''
    }
    try { return (Clean-Owner ((Get-Acl -LiteralPath $fi.FullName).Owner)) } catch { return '' }
}

$header = @('mtime', 'ext', 'size_kb', 'folder', 'name', 'author')
$rows = New-Object System.Collections.Generic.List[string]
$rows.Add(($header -join ','))
$rowKeys = New-Object System.Collections.Generic.List[string]     # history 합집합 키 (mtime|folder|name)

# ── 실제 작업 폴더 자동 발견 - watchFolders 가 기본값 그대로면 파일 신호가 통째로 빈다(실측) ──
# ① 최근 열어본 문서(Recent .lnk)의 부모 폴더 중 자주 쓰는 곳을 감시 대상에 보탠다.
# ② 시뮬레이션·CAD·EDA 도구는 Recent .lnk 를 남기지 않는다(Explorer·Office 만 남긴다) - 그 폴더는 ①로는 영영 안 보였다.
#    Windows 공용 열기/저장 대화상자 MRU(ComDlg32 OpenSavePidlMRU·LastVisitedPidlMRU - 대화상자를 쓰는 모든 프로그램이
#    남긴다)와 도구별 최근 파일 저장소(MATLAB·Altium·KiCad·Notepad++·VS·IAR·COMSOL·LabVIEW·Eclipse/STM32CubeIDE 의
#    텍스트·XML·JSON, SolidWorks·Zemax·Altium·Keil·CATIA·LTspice 의 HKCU 하이브)에서 경로를 수확해 폴더만 쓴다.
#    시각이 없는 출처라 '그 파일 또는 그 폴더의 감시 파일이 기간 안에 수정됐을 때만' 후보로 센다. 행은 만들지 않는다 -
#    폴더가 감시 대상이 되면 스캔이 실제 mtime 으로 모든 산출물을 잡는다.
$autoDirs = @()
# 개인 폴더가 자동 편입될 수 있다(배포용 기본 excludePathKeywords 는 개인 폴더명을 모른다).
# 끄려면 config.json 에 "autoDiscoverFolders": false 를 넣으면 된다.
$autoOn = $true
if ($null -ne $cfg.autoDiscoverFolders) { $autoOn = [bool]$cfg.autoDiscoverFolders }
$userProfile = ''; if ($env:USERPROFILE) { $userProfile = $env:USERPROFILE.ToLower().TrimEnd('\') }
$publicDir = '';   if ($env:PUBLIC) { $publicDir = $env:PUBLIC.ToLower().TrimEnd('\') }
# 자동 발견 관찰 창을 분석 기간과 연동한다 - 45일 고정이면 3개월 분석에서 앞 달의
# 작업 폴더(그 사이에 이사한 폴더 등)를 놓친다(실측 지적: '최근 것만 보면 3개월치 누락')
$cut = (Get-Date).AddDays(-45)
if ($since -lt $cut) { $cut = $since }
$freq = @{}; $dirDisp = @{}
$srcStat = [ordered]@{}
$dirRecentCache = @{}
$mruDeadline = (Get-Date).AddSeconds(25)   # 도구 MRU 수확 예산 - 닿지 않는 UNC 경로가 Test-Path 에서 오래 걸릴 수 있다
function Get-DirRecentWork([string]$dl) {    # 폴더 바로 아래에 기간 안에 수정된 감시 파일 수(최대 2, 캐시)
    if ($dirRecentCache.ContainsKey($dl)) { return $dirRecentCache[$dl] }
    $c = 0
    try {
        $n = 0
        foreach ($fi in (New-Object System.IO.DirectoryInfo $dl).EnumerateFiles()) {
            if (++$n -gt 3000) { break }
            if ($fi.LastWriteTime -ge $cut -and $fi.LastWriteTime -lt $until -and (Get-WatchExt $fi.Name)) { $c++; if ($c -ge 2) { break } }
        }
    } catch {}
    $dirRecentCache[$dl] = $c
    return $c
}
function Test-CandDir([string]$d) {          # 후보 폴더 공통 관문 → 소문자 경로 또는 ''
    # 시스템 폴더 제외는 폴더명 단위로 - 옛 '\\Program' 접두 매치는 Programming\·Program_Docs\ 같은 업무 폴더까지
    # 영영 자동 편입에서 빼놓았다(C3). 끝에 '\' 를 붙여 마지막 세그먼트도 같은 규칙으로 본다.
    if (-not $d -or ($d.TrimEnd('\') + '\') -match '\\AppData\\|\\Windows\\|\\Program Files( \([^\\]*\))?\\|\\ProgramData\\') { return '' }
    $dl = $d.ToLower().TrimEnd('\')
    # 드라이브 루트·프로필 루트·Public 은 편입하지 않는다 - 드라이브 전체 재귀 스캔 방지
    if ($dl -match '^[a-z]:$' -or ($userProfile -and $dl -eq $userProfile) -or ($publicDir -and $dl -eq $publicDir)) { return '' }
    if (Test-SelfPath ($dl + '\')) { return '' }   # 도구 자신은 업무 폴더가 아니다
    if (Test-PkgPath ($dl + '\') '') { return '' }
    if (Test-FolderName ($dl + '\')) { return '' }
    if (Test-ExclPath ($dl + '\')) { return '' }
    return $dl
}
function Add-Cand([string]$tgt, [string]$src, [bool]$needRecent, [int]$w = 1) {
    # 업무 확장자(watchExtensions)인 문서·코드만 집계 - 사진(.jpg 등) 폴더가
    # 감시 대상으로 자동 편입되면 개인 폴더 유출 위험이 커진다(실측: 사진 폴더 발견됨)
    if (-not $tgt -or $tgt -match '^[a-z]+://') { return $false }
    if (-not (Get-WatchExt ([System.IO.Path]::GetFileName($tgt)))) { return $false }
    if (-not (Test-Path -LiteralPath $tgt -PathType Leaf)) { return $false }
    $d = Split-Path -Parent $tgt
    $dl = Test-CandDir $d
    if (-not $dl) { return $false }
    if ($needRecent) {      # 시각 없는 MRU: 그 파일 또는 그 폴더의 감시 파일이 기간 안에 수정됐을 때만
        $ok = $false
        try { $t = [System.IO.File]::GetLastWriteTime($tgt); $ok = ($t -ge $cut -and $t -lt $until) } catch {}
        if (-not $ok -and (Get-DirRecentWork $dl) -lt 1) { return $false }
    }
    $freq[$dl] = $w + $(if ($freq.ContainsKey($dl)) { $freq[$dl] } else { 0 })
    $dirDisp[$dl] = $d
    $srcStat[$src] = 1 + $(if ($srcStat.Contains($src)) { $srcStat[$src] } else { 0 })
    return $true
}
# 텍스트(INI·XML·JSON·레지스트리 문자열)에서 감시 확장자 절대 경로를 수확 - JSON 이스케이프(\\)·URI(file:///D%3A/…)·슬래시 정규화
$altList = @($extSet | ForEach-Object { $_.TrimStart('.') }) + @($extCompound | ForEach-Object { $_.TrimStart('.') })
$harvestRe = $null
if ($altList.Count -gt 0) {
    $alt = ($altList | Sort-Object -Property Length -Descending | ForEach-Object { [regex]::Escape($_) }) -join '|'
    $harvestRe = New-Object System.Text.RegularExpressions.Regex ('(?i)(?:[a-z]:|\\\\[^\\/:*?"<>|\r\n]+)\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*?\.(?:' + $alt + ')(?![a-z0-9_])')
}
function Get-PathsFromText([string]$text) {
    if ($null -eq $harvestRe -or -not $text) { return @() }
    $t = $text -replace '\\\\', '\'
    try { $t = [System.Uri]::UnescapeDataString($t) } catch {}
    $t = $t -replace '/', '\'
    $t = $t -replace '(?<=[^\\\r\n])\\{2,}', '\'      # 겹친 구분자(W:\\Tool\\x) 는 하나로 - 맨 앞 UNC(\\server) 는 유지
    $seen = @{}; $out = New-Object System.Collections.Generic.List[string]
    foreach ($m in $harvestRe.Matches($t)) {
        $v = $m.Value
        if ($seen.ContainsKey($v.ToLower())) { continue }
        $seen[$v.ToLower()] = 1
        $out.Add($v)
        if ($out.Count -ge 300) { break }
    }
    return @($out)
}
if ($autoOn) {
try {
    $sh = New-Object -ComObject WScript.Shell
    $recent = if ($RecentDir) { $RecentDir } else { [Environment]::GetFolderPath('Recent') }
    Get-ChildItem -LiteralPath $recent -Filter *.lnk -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -gt $cut } |
        ForEach-Object {
            try { $tgt = $sh.CreateShortcut($_.FullName).TargetPath; [void](Add-Cand $tgt 'lnk' $false) } catch {}
        }
} catch {}
if (-not $NoToolMru) {
    # ② 공용 대화상자 MRU - REG_BINARY PIDL 을 SHGetPathFromIDList 로 경로로 푼다 (제한 언어 모드·AppLocker 에서 Add-Type 이 막히면 건너뛴다)
    #    -MruTextDir(시험용) 이 있으면 레지스트리 출처는 모두 건너뛰고 그 폴더의 텍스트만 수확한다
    $pidlOk = $false
    if ($MruTextDir) { $pidlOk = $false } else {
    try {
        if (-not ('LMFiles.Shell' -as [type])) {
            Add-Type -Namespace LMFiles -Name Shell -MemberDefinition @'
[DllImport("shell32.dll", CharSet = CharSet.Unicode)]
public static extern bool SHGetPathFromIDListW(IntPtr pidl, System.Text.StringBuilder pszPath);
'@
        }
        $pidlOk = $true
    } catch { Write-Host '[files] 대화상자 MRU 생략: PIDL 해석기(Add-Type) 사용 불가' }
    }
    function ConvertFrom-Pidl([byte[]]$b, [int]$off = 0) {
        if (-not $pidlOk -or $null -eq $b -or $b.Length - $off -lt 4) { return '' }
        $n = $b.Length - $off
        $p = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($n)
        try {
            [System.Runtime.InteropServices.Marshal]::Copy($b, $off, $p, $n)
            $sb = New-Object System.Text.StringBuilder 2048
            if ([LMFiles.Shell]::SHGetPathFromIDListW($p, $sb)) { return $sb.ToString() }
        } catch {} finally { [System.Runtime.InteropServices.Marshal]::FreeHGlobal($p) }
        return ''
    }
    if ($pidlOk) {
        try {   # 열기/저장한 파일 (확장자별 최근 20건, 모든 대화상자 프로그램)
            $k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU'
            foreach ($sub in @(Get-ChildItem -LiteralPath $k -ErrorAction SilentlyContinue)) {
                if ((Get-Date) -gt $mruDeadline) { break }
                $sn = $sub.PSChildName.ToLower()
                if ($sn -ne '*' -and -not $extSet.Contains('.' + $sn) -and -not ($extCompound | Where-Object { $_.EndsWith('.' + $sn) })) { continue }
                $props = Get-ItemProperty -LiteralPath $sub.PSPath -ErrorAction SilentlyContinue
                foreach ($pr in $props.PSObject.Properties) {
                    if ($pr.Name -notmatch '^\d+$') { continue }
                    [void](Add-Cand (ConvertFrom-Pidl ([byte[]]$pr.Value)) 'dialog-file' $true)
                }
            }
        } catch {}
        try {   # 프로그램별 마지막 대화상자 폴더 (<exe UTF-16 null 종료><PIDL>) - 폴더 바로 아래에 기간 안 감시 파일이 2개 이상일 때만
            $k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\LastVisitedPidlMRU'
            $props = Get-ItemProperty -LiteralPath $k -ErrorAction SilentlyContinue
            foreach ($pr in $props.PSObject.Properties) {
                if ($pr.Name -notmatch '^\d+$') { continue }
                if ((Get-Date) -gt $mruDeadline) { break }
                $b = [byte[]]$pr.Value
                $i = 0; while ($i + 1 -lt $b.Length) { if ($b[$i] -eq 0 -and $b[$i + 1] -eq 0) { break }; $i += 2 }
                $d = ConvertFrom-Pidl $b ($i + 2)
                if (-not $d -or $d -match '^[a-z]+://') { continue }
                $dl = Test-CandDir $d
                if ($dl -and (Test-Path -LiteralPath $d -PathType Container) -and (Get-DirRecentWork $dl) -ge 2) {
                    $freq[$dl] = 2 + $(if ($freq.ContainsKey($dl)) { $freq[$dl] } else { 0 })
                    $dirDisp[$dl] = $d
                    $srcStat['dialog-folder'] = 1 + $(if ($srcStat.Contains('dialog-folder')) { $srcStat['dialog-folder'] } else { 0 })
                }
            }
        } catch {}
    }
    # ③ 도구별 최근 파일 저장소(텍스트) - 경로만 수확한다. 위치는 도구 버전에 따라 다를 수 있어 없으면 조용히 0건
    $mruText = @(
        @{ tag = 'matlab';    glob = "$env:APPDATA\MathWorks\MATLAB\R20*\MATLAB_Editor_State.xml" },
        @{ tag = 'matlab';    glob = "$env:APPDATA\MathWorks\MATLAB\R20*\matlab.prf" },
        @{ tag = 'altium';    glob = "$env:APPDATA\Altium\*\DXP.RCS" },
        @{ tag = 'kicad';     glob = "$env:APPDATA\kicad\*\*.json" },
        @{ tag = 'notepad++'; glob = "$env:APPDATA\Notepad++\config.xml" },
        @{ tag = 'vs';        glob = "$env:LOCALAPPDATA\Microsoft\VisualStudio\1*\ApplicationPrivateSettings.xml" },
        @{ tag = 'iar';       glob = "$env:APPDATA\IAR Embedded Workbench\*.xml" },
        @{ tag = 'comsol';    glob = "$env:USERPROFILE\.comsol\v*\prefs.ini" },
        @{ tag = 'labview';   glob = "$env:APPDATA\National Instruments\*\LabVIEW.ini" },
        @{ tag = 'eclipse';   glob = "$env:USERPROFILE\STM32CubeIDE\workspace*\.metadata\.plugins\org.eclipse.core.resources\.projects\*\.location" },
        @{ tag = 'eclipse';   glob = "$env:USERPROFILE\*workspace*\.metadata\.plugins\org.eclipse.core.resources\.projects\*\.location" }
    )
    if ($MruTextDir) { $mruText = @(@{ tag = 'test'; glob = (Join-Path $MruTextDir '*') }) }
    foreach ($s in $mruText) {
        if ((Get-Date) -gt $mruDeadline) { break }
        $files = @()
        try { $files = @(Get-ChildItem -Path $s.glob -File -ErrorAction SilentlyContinue | Where-Object { $_.Length -le 4MB } | Select-Object -First 20) } catch {}
        foreach ($f in $files) {
            try {
                foreach ($p in (Get-PathsFromText ([System.IO.File]::ReadAllText($f.FullName)))) { [void](Add-Cand $p $s.tag $true) }
            } catch {}
        }
    }
    # ④ 도구별 HKCU 하이브 - 키 이름을 모르는 도구도 있어 깊이 3·1,500키 안의 모든 문자열 값에서 경로를 수확한다(수확 관문이 잡음을 거른다)
    if (-not $MruTextDir) {
        foreach ($r in @(@{ tag = 'solidworks'; root = 'HKCU:\Software\SolidWorks' }, @{ tag = 'zemax'; root = 'HKCU:\Software\Zemax' },
                         @{ tag = 'altium'; root = 'HKCU:\Software\Altium' }, @{ tag = 'keil'; root = 'HKCU:\Software\Keil' },
                         @{ tag = 'catia'; root = 'HKCU:\Software\Dassault Systemes' }, @{ tag = 'ltspice'; root = 'HKCU:\Software\LTspice' })) {
            if ((Get-Date) -gt $mruDeadline) { break }
            if (-not (Test-Path -LiteralPath $r.root)) { continue }
            try {
                $keys = @(Get-Item -LiteralPath $r.root) + @(Get-ChildItem -LiteralPath $r.root -Recurse -Depth 3 -ErrorAction SilentlyContinue | Select-Object -First 1500)
                $sb = New-Object System.Text.StringBuilder
                foreach ($key in $keys) {
                    foreach ($vn in $key.GetValueNames()) {
                        $v = $key.GetValue($vn)
                        if ($v -is [string]) { [void]$sb.AppendLine($v) }
                        elseif ($v -is [string[]]) { foreach ($x in $v) { [void]$sb.AppendLine($x) } }
                    }
                }
                foreach ($p in (Get-PathsFromText $sb.ToString())) { [void](Add-Cand $p $r.tag $true) }
            } catch {}
        }
    }
}
$autoDirs = @($freq.GetEnumerator() | Where-Object { $_.Value -ge 2 } |
    Sort-Object -Property Value -Descending | Select-Object -First 16 | ForEach-Object { $dirDisp[$_.Key] })
if ($autoDirs.Count -gt 0) {
    Write-Host ("[files] auto-discovered {0} work folders from Recent/MRU:" -f $autoDirs.Count)
    $autoDirs | ForEach-Object { Write-Host ("        + " + $_) }
    Write-Host '        ^ 개인 폴더가 섞였으면 config.excludePathKeywords 에 그 폴더명을 추가하거나'
    Write-Host '          config 에 "autoDiscoverFolders": false 를 넣어 자동 발견을 끄세요.'
}
if ($srcStat.Count -gt 0) {
    Write-Host ("[files] 자동 발견 출처(후보 파일 수): " + (($srcStat.Keys | ForEach-Object { "{0} {1}" -f $_, $srcStat[$_] }) -join ' · '))
}
} else { Write-Host '[files] auto-discover off (config.autoDiscoverFolders=false)' }
$autoSet = @{}
foreach ($a in $autoDirs) { $autoSet[$a.ToLower().TrimEnd('\')] = 1 }
$watchList = @(@($cfg.watchFolders) | Where-Object { $_ })
# 겹치는 루트 정리 - 자동 편입 폴더가 감시 폴더 안에 있으면(흔함) 같은 파일이 두 번 스캔돼 표본·버스트 계산이 왜곡됐다.
# 바깥 루트가 감시 폴더(깊이 제한 없음)이거나 둘 다 자동 편입이면 안쪽을 뺀다.
$allDirs = New-Object System.Collections.Generic.List[string]
foreach ($d in @($watchList + $autoDirs | Select-Object -Unique)) {
    $dl = $d.ToLower().TrimEnd('\')
    $inner = $false
    foreach ($o in @($watchList + $autoDirs | Select-Object -Unique)) {
        $ol = $o.ToLower().TrimEnd('\')
        if ($ol -eq $dl -or -not $dl.StartsWith($ol + '\')) { continue }
        if (-not $autoSet.ContainsKey($ol) -or $autoSet.ContainsKey($dl)) { $inner = $true; break }
    }
    if (-not $inner) { $allDirs.Add($d) }
}

$sharedSeen = [ordered]@{}   # 공유·동기화 루트 → kind
$script:nSharedFiles = 0
$dirShared = @{}             # 디렉터리별 공유 판정 캐시
$rowSeen = New-Object 'System.Collections.Generic.HashSet[string]'
$script:nDup = 0
$perDir = [ordered]@{}
$perMin = @{}                # (분|폴더) → 건수 - 시뮬레이션 결과 폴더·동기화 뭉치 안내용
$scanWatch = [System.Diagnostics.Stopwatch]::StartNew()
foreach ($f in $allDirs) {
    if ($f -match '[<>]') { Write-Host ("[files] skip placeholder: " + $f + "  (config.watchFolders 를 실제 폴더로 바꾸세요)"); continue }
    if (-not (Test-Path -LiteralPath $f)) { Write-Host ("[files] skip missing folder: {0}" -f $f); continue }
    # -Path 는 [ ] 를 와일드카드로 해석해 대괄호가 든 폴더가 조용히 0건이 된다(경고도 없음)
    $gci = @{ LiteralPath = $f; Recurse = $true; File = $true; ErrorAction = 'SilentlyContinue' }
    if ($autoSet.ContainsKey($f.ToLower().TrimEnd('\'))) { $gci['Depth'] = 6 }   # 자동 편입 폴더는 깊이 6 까지
    $n0 = $rows.Count
    Get-ChildItem @gci |
        ForEach-Object {
            if ($_.LastWriteTime -lt $since -or $_.LastWriteTime -ge $until) { return }
            if ($_.Name -like '~$*') { return }
            $ext = Get-WatchExt $_.Name          # 내용은 열지 않는다 - 수 GB 이진 결과도 여기서는 이름·시각·크기만
            if (-not $ext) { return }
            $pl = $_.FullName.ToLower()
            if (Test-SelfPath $pl) { $script:nSelf++; return }   # 자기 설치 폴더 제외
            $k = Test-PkgPath $pl $ext
            if ($k) { Note-Pkg $k $_.DirectoryName; return }
            $k = Test-FolderName $pl
            if ($k) { Note-FolderName $k $_.DirectoryName; return }
            $k = Test-ExclPath $pl
            if ($k) { Note-Excl $k $_.DirectoryName; return }     # privacy filter
            $dir = $_.DirectoryName
            $mt = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm')
            $key = $mt + '|' + $dir + '|' + $_.Name
            if (-not $rowSeen.Add($key)) { $script:nDup++; return }      # 같은 파일이 두 루트에서 - 1건만
            $dk = $dir.ToLower()
            if (-not $dirShared.ContainsKey($dk)) {
                $sr = Get-SharedRoot $dir
                $dirShared[$dk] = $(if ($null -ne $sr) { $sr['kind'] } else { '' })
                if ($null -ne $sr) { $sharedSeen[$sr['root']] = $sr['kind'] }
            }
            $shared = $dirShared[$dk]
            if ($shared) { $script:nSharedFiles++ }
            $author = Get-Author $_ $shared
            if ($author) {
                $script:nAuthor++
                if (-not $shared) { $script:localAuthors[$author] = 1 + $(if ($script:localAuthors.ContainsKey($author)) { $script:localAuthors[$author] } else { 0 }) }
            }
            $rows.Add(('{0},{1},{2},{3},{4},{5}' -f `
                $mt, $ext, [math]::Round($_.Length / 1KB, 0), `
                (Csv-Escape $dir), (Csv-Escape $_.Name), (Csv-Escape $author)))
            $rowKeys.Add($key)
            $pk = $mt + '|' + $dk
            $perMin[$pk] = 1 + $(if ($perMin.ContainsKey($pk)) { $perMin[$pk] } else { 0 })
        }
    $n = $rows.Count - $n0
    $perDir[$f] = $n
    if ($n -gt 5000) {
        Write-Host ("[files] 주의: {0} 에서 {1:n0}행 - 기계 생성·동기화 뭉치가 섞였을 수 있습니다 (하위 폴더명을 excludePathKeywords 또는 excludeFolderNames 에 넣어 제외 가능)" -f $f, $n)
    }
}
$scanWatch.Stop()
Write-Lines (Join-Path $outDir 'files.csv') $rows
$rowsNote = "[files] rows: {0} (스캔 {1:n1}s)" -f ($rows.Count - 1), $scanWatch.Elapsed.TotalSeconds
if ($script:nDup -gt 0) { $rowsNote += " (겹치는 루트의 중복 {0}건 제거)" -f $script:nDup }
Write-Host $rowsNote
# 같은 분에 fileBurstN×5 건 이상 쓰인 폴더 - 시뮬레이션 결과·기록 장비·동기화. 분석(core/extract)이 '일괄' 로 축약하니 여기서 지우지는 않는다
$burstN = 8
try { $bn = [int]$cfg.mm.fileBurstN; if ($bn -ge 2 -and $bn -le 100000) { $burstN = $bn } } catch {}
$histCap = $burstN * 5 + 1
$burstDirs = @{}
foreach ($pk in $perMin.Keys) { if ($perMin[$pk] -ge $histCap) { $burstDirs[$pk.Substring($pk.IndexOf('|') + 1)] = 1 } }
if ($burstDirs.Count -gt 0) {
    Write-Host ("[files] 참고: 같은 분에 {0}건 이상 쓰인 폴더 {1}곳 (시뮬레이션 결과·기록 장비·동기화 - 분석이 폴더·날당 대표 1건 '파일(일괄)' 로 축약)" -f $histCap, $burstDirs.Count)
}
$sharedList = @($sharedSeen.Keys | ForEach-Object { "{0} ({1})" -f $_, $sharedSeen[$_] })
if ($sharedList.Count -gt 0) {
    Write-Host ("[files] 주의: 공유·동기화 폴더 {0}곳(파일 {1}건) - 동료가 저장한 파일은 author 열로 걸러집니다 (Office 문서: lastModifiedBy · UNC: 소유자 · PDF/CAD 등은 구분 불가)" -f $sharedList.Count, $script:nSharedFiles)
    $sharedList | ForEach-Object { Write-Host ("        ~ " + $_) }
}
$authorNote = "[files] author 채움: {0}건 / 시도 {1}건" -f $script:nAuthor, $script:nAuthorTry
if ($script:authorTimedOut) { $authorNote += ' (90초 예산 소진 - 이후 파일은 빈 값)' }
Write-Host $authorNote

# 제외 집계 출력 - 무엇이 빠졌는지 확인 가능해야 한다 (예: 'temp' 가 Temperature_Test 를 지우는지)
$kwStat = [ordered]@{}
foreach ($k in ($exclStat.Keys | Sort-Object)) { $kwStat[$k] = @{ files = $exclStat[$k]['files']; folders = $exclStat[$k]['dirs'].Count } }
if ($kwStat.Count -gt 0) {
    Write-Host ("[files] 제외: " + (($kwStat.Keys | ForEach-Object { "{0} {1}폴더 {2}건" -f $_, $kwStat[$_]['folders'], $kwStat[$_]['files'] }) -join ' · '))
}
$fnOut = [ordered]@{}
foreach ($k in ($fnStat.Keys | Sort-Object)) { $fnOut[$k] = @{ files = $fnStat[$k]['files']; folders = $fnStat[$k]['dirs'].Count } }
if ($fnOut.Count -gt 0) {
    Write-Host ("[files] 폴더명 제외(excludeFolderNames): " + (($fnOut.Keys | ForEach-Object { "{0} {1}폴더 {2}건" -f $_, $fnOut[$_]['folders'], $fnOut[$_]['files'] }) -join ' · '))
}
$pkgOut = [ordered]@{}
foreach ($k in ($pkgStat.Keys | Sort-Object)) { $pkgOut[$k] = @{ files = $pkgStat[$k]['files']; folders = $pkgStat[$k]['dirs'].Count } }
if ($pkgOut.Count -gt 0) {
    Write-Host ("[files] 패키지·빌드 폴더 제외: " + (($pkgOut.Keys | ForEach-Object { "{0} {1}폴더 {2}건" -f $_, $pkgOut[$_]['folders'], $pkgOut[$_]['files'] }) -join ' · ') + '  (build·release·target 류는 빌드 표식이 있을 때만 · config.excludePackageDirs=false 로 끌 수 있음)')
}
$buildChecked = @($buildDirCache.Keys).Count
$buildHit = @($buildDirCache.Keys | Where-Object { $buildDirCache[$_] }).Count
if ($buildChecked -gt 0) {
    Write-Host ("[files] 이름이 겹치는 폴더(build·dist·target·release·debug·x64·env·packages) {0}곳 검사 - 빌드 표식 있음 {1}곳(제외) · 없음 {2}곳(업무 폴더로 유지)" -f $buildChecked, $buildHit, ($buildChecked - $buildHit))
}
$authorsTop = @($script:localAuthors.GetEnumerator() | Sort-Object -Property Value -Descending | Select-Object -First 3 | ForEach-Object { ,@($_.Key, $_.Value) })
$autoSrc = [ordered]@{}
foreach ($k in $srcStat.Keys) { $autoSrc[$k] = $srcStat[$k] }
try {
    Update-ExcludedJson 'files' ([ordered]@{
        updated = (Get-Date).ToString('yyyy-MM-dd HH:mm')
        period = @($since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'))
        rows = ($rows.Count - 1)
        scan_seconds = [math]::Round($scanWatch.Elapsed.TotalSeconds, 1)
        rows_by_folder = $perDir
        by_keyword = $kwStat
        folder_names = $fnOut
        package_dirs = $pkgOut
        package_dirs_on = $pkgOn
        build_marker_dirs = @{ checked = $buildChecked; excluded = $buildHit }
        burst_dirs = $burstDirs.Count
        auto_discover = @{ folders = $autoDirs.Count; candidates_by_source = $autoSrc }
        self_excluded = $script:nSelf
        duplicates_removed = $script:nDup
        shared_roots = $sharedList
        shared_files = $script:nSharedFiles
        author_filled = $script:nAuthor
        author_timed_out = $script:authorTimedOut
        authors_local_top = $authorsTop
        note = 'by_keyword/folder_names/package_dirs: 제외된 파일·폴더 수. 경로는 남기지 않는다. build_marker_dirs: 이름이 겹치는 폴더 중 빌드 표식으로 제외된 수. burst_dirs: 같은 분에 fileBurstN×5 건 이상 쓰인 폴더 수(분석이 축약). auto_discover: 자동 발견 출처별 후보 파일 수. authors_local_top: 로컬 폴더 Office 문서의 lastModifiedBy 최빈값(= 본인 이름 추정 근거)'
    })
} catch { Write-Host ("[files] files_excluded.json 기록 실패: " + $_.Exception.Message) }

# 관측 누적 (files_history.csv) - 이번 실행 행을 (mtime,folder,name) 키로 합집합, 400일 이전 행 제거, 같은 (분,폴더) 는 fileBurstN×5+1 행까지
try {
    $h = Merge-History (Join-Path $outDir 'files_history.csv') $header @($rows | Select-Object -Skip 1) $rowKeys 'files' $histCap
    Write-Host ("[files] history: {0:n0}행 ({1}개월 · 이전 {2:n0}행과 합집합 · 400일 보관{3})" -f $h['total'], $h['months'], $h['old'], $(if ($h['capped'] -gt 0) { " · 같은 분·폴더 {0}행 초과분 {1:n0}행은 이력에 보관하지 않음" -f $histCap, $h['capped'] } else { '' }))
} catch { Write-Host ("[files] files_history.csv 누적 실패: " + $_.Exception.Message) }

# 기간 커버리지 진단 - mtime 은 '마지막 수정'만 남으므로 여러 달에 걸쳐 고친 파일은
# 마지막 달에만 잡힌다. 앞쪽 달이 비면 숨기지 말고 알린다(회의·메일·샘플러가 보완).
$byMon = @{}
foreach ($ln in $rows) {
    if ($ln -match '^(\d{4}-\d{2})') { $byMon[$Matches[1]] = 1 + $(if ($byMon.ContainsKey($Matches[1])) { $byMon[$Matches[1]] } else { 0 }) }
}
$mons = New-Object System.Collections.Generic.List[string]
$m = New-Object datetime $since.Year, $since.Month, 1
while ($m -lt $until) { $mons.Add($m.ToString('yyyy-MM')); $m = $m.AddMonths(1) }
$cover = ($mons | ForEach-Object { "{0} {1}건" -f $_, $(if ($byMon.ContainsKey($_)) { $byMon[$_] } else { 0 }) }) -join ' · '
Write-Host ("[files] 월별 커버: {0}" -f $cover)
$empty = @($mons | Where-Object { -not $byMon.ContainsKey($_) })
if ($empty.Count -gt 0 -and ($rows.Count - 1) -gt 0) {
    Write-Host ("[files] 주의: {0} 월의 파일 흔적이 0건 - 파일 mtime 은 마지막 수정만 남습니다 (files_history.csv 의 지난 관측이 있으면 분석이 보완)." -f ($empty -join ', '))
    Write-Host '        그 달에도 일했다면 같은 파일을 이후에 또 고쳤을 가능성이 큽니다 (메일·회의·창 샘플러가 그 달을 보완).'
}
