# Get-RecentFiles.ps1
# Retroactive file-activity evidence WITHOUT configuring watch folders:
#   1) Windows Recent items (%APPDATA%\...\Recent\*.lnk) - every file opened via Explorer/Office,
#      regardless of drive or network share. Reaches back weeks~months.
#   2) Office File MRU registry (Word/Excel/PowerPoint) - per-app recent files with timestamps.
#      Office signed in with a M365/organisation account writes ONLY under
#      <App>\User MRU\{LiveId_|ADAL_}<id>\File MRU - the top-level <App>\File MRU stays empty (measured: 0 vs 139).
# This is the main fix for "file evidence too thin" - work files live everywhere, not one folder.
# Output: ..\data\files\recent.csv          (overwrite)  mtime,ext,size_kb,folder,name,src,target_mtime
#           mtime = 열람 시각(.lnk 갱신 / MRU 시각), src = lnk|mru,
#           target_mtime = 대상 파일의 현재 LastWriteTime ('' = 없음·URL) - extract 가 '열람만' 과 '열어서 편집' 을 구분
#         ..\data\files\recent_history.csv  (accumulated union of every run, same header, 400 days)
#         ..\data\files_excluded.json      ("recent" section)
# ext:    watchExtensions 판정은 이름 끝 기준(Get-FileActivity.ps1 과 같은 규칙) - 복합 확장자(.cas.gz)·Creo 판번호(bracket.prt.12 → .prt)
param(
    [string]$From = '',
    [string]$To = '',
    [int]$Days = 90,
    [string]$RecentDir = '',     # 시험용: Recent 폴더 대신 이 폴더의 .lnk
    [switch]$NoMru               # 시험용: 레지스트리 MRU 생략
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$cfg = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json
$outDir = Join-Path $root 'data\files'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

if ($From) { $since = [datetime]::ParseExact($From, 'yyyy-MM-dd', $null) } else { $since = (Get-Date).Date.AddDays(-$Days) }
if ($To)   { $until = ([datetime]::ParseExact($To, 'yyyy-MM-dd', $null)).AddDays(1) } else { $until = (Get-Date).Date.AddDays(1) }
# config 에 키가 없으면 $null 이 흘러 .ToLower() 에서 즉사한다 - null 을 먼저 걸러낸다
$exts = @(@($cfg.watchExtensions) | Where-Object { $_ } | ForEach-Object { ([string]$_).Trim().ToLower() } | Where-Object { $_.StartsWith('.') } | Select-Object -Unique)
$excl = @(@($cfg.excludePathKeywords) | Where-Object { $_ } | ForEach-Object { $_.ToLower() })

# ── 확장자 판정 (Get-FileActivity.ps1 과 같은 규칙) - 단일(.zmx)·복합(.cas.gz)·Creo 판번호(bracket.prt.12) 를 이름 끝으로 본다.
#    thumbs.db·desktop.ini·JS 소스맵(*.js.map) 은 확장자가 맞아도 제외 ──
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

# 관측 누적 - Recent .lnk 는 약 150건만 보관되고 매 실행 스냅샷만 남던 것을 (mtime,folder,name) 합집합으로 보관
function Merge-History([string]$histPath, [string[]]$header, $newLines, $newKeys, [string]$tag) {
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
    foreach ($k in ($byKey.Keys | Sort-Object)) { $out.Add($byKey[$k]); $months[$k.Substring(0, 7)] = 1 }
    Write-Lines $histPath $out
    return @{ total = $byKey.Count; old = $nOld; months = $months.Count }
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

# ── excludePathKeywords 판정 - 세 수집기(파일·Recent·git)·core/extract._text_filter 와 같은 규칙 ──
#  · 경로 전용 토큰(temp·downloads·임시·다운로드)은 폴더명 완전 일치 ('temp'⊄'Temperature_Test'·'template')
#  · ASCII 키워드는 단어 경계 · 한글은 부분일치 유지 ('개인'⊂'개인자료' - 마지막 방어선)
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
$exclStat = @{}
function Note-Excl([string]$k, [string]$dir) {
    if (-not $exclStat.ContainsKey($k)) { $exclStat[$k] = @{ files = 0; dirs = @{} } }
    $exclStat[$k]['files']++
    $exclStat[$k]['dirs'][$dir.ToLower()] = 1
}
# ── 폴더명 제외 (config.excludeFolderNames) - 폴더명 완전 일치·대소문자 무시. Get-FileActivity.ps1 과 같은 규칙 ──
$folderNames = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($n in @(@($cfg.excludeFolderNames) | Where-Object { $_ })) { [void]$folderNames.Add(([string]$n).Trim().ToLower().Trim('\')) }
$fnStat = @{}
function Test-FolderName([string]$pl) {    # $pl: 소문자 전체 경로(끝이 파일명) → 걸린 폴더명 또는 ''
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
# ── 패키지·빌드 폴더 제외 (config.excludePackageDirs, 기본 true) - Get-FileActivity.ps1 과 같은 규칙 ──
#  · 이름만으로 확정: .venv·venv·site-packages·node_modules·__pycache__·.git·.idea·.vs·.vscode·.conda·cmake-build-*
#  · build·dist·target·release·debug·x64·env·packages 는 그 폴더(또는 바로 위)에 빌드 표식이 있을 때만 - Release\ 에 둔 해석 결과·도면 배포본 보존
#  · 펌웨어·FPGA 빌드 산출물(.hex .elf .bin .map .bit .sof)은 빌드 폴더 안이라도 통과(빌드 시각 = 작업 흔적)
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

$seen = @{}
$header = @('mtime', 'ext', 'size_kb', 'folder', 'name', 'src', 'target_mtime')
$rows = New-Object System.Collections.Generic.List[string]
$rows.Add(($header -join ','))
$rowKeys = New-Object System.Collections.Generic.List[string]
$script:nSelf = 0

# 자기 설치 폴더 제외 - 결과 CSV·MD 를 '열어보기만 해도' Recent/MRU 를 타고
# 다음 수집에 업무 신호로 들어온다(자기 출력의 되먹임). LoadMonitor25.bat 이
# 결과 폴더를 자동으로 열어주므로 이 경로는 반드시 막아야 한다. 다른 LoadMonitor 설치는 산출물
# 폴더(data|report|teamdata|python)만 - core|collect|ui 까지 막으면 이 도구의 개발 흔적이 지워진다.
$selfRoot = $root.ToLower()
function Test-SelfPath([string]$pl) {
    if ($pl.StartsWith($selfRoot)) { return $true }
    if ($pl -match '\\loadmonitor[^\\]*\\(data|report|teamdata|python)\\') { return $true }
    return $false
}

function Add-Row([datetime]$t, [string]$path, [string]$src) {
    if ($t -lt $since -or $t -ge $until) { return }
    # privacy filter: personal/sensitive paths never reach disk
    $pl = $path.ToLower()
    if (Test-SelfPath $pl) { $script:nSelf++; return }
    $name = [IO.Path]::GetFileName($path)
    $ext = Get-WatchExt $name              # 복합 확장자·Creo 판번호 포함, 내용은 열지 않는다
    if (-not $ext) { return }
    if ($name -like '~$*') { return }
    $folder = [IO.Path]::GetDirectoryName($path)
    $k = Test-PkgPath $pl $ext
    if ($k) { Note-Pkg $k $folder; return }
    $k = Test-FolderName $pl
    if ($k) { Note-FolderName $k $folder; return }
    $k = Test-ExclPath $pl
    if ($k) { Note-Excl $k $folder; return }
    $mt = $t.ToString('yyyy-MM-dd HH:mm')
    $key = "$folder|$name|$mt"
    if ($script:seen.ContainsKey($key)) { return }
    $script:seen[$key] = 1
    $kb = 0; $tm = ''
    try {
        # 대상 파일의 현재 수정 시각을 보존한다 - '열람만'(target_mtime 이 열람 시각보다 오래됨) 과
        # '열어서 편집'(≈ 열람 시각) 을 extract 가 구분하는 유일한 근거. URL(SharePoint 온라인) 은 ''.
        if ($path -notmatch '^[a-z]+://' -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            $it = Get-Item -LiteralPath $path -Force
            $kb = [math]::Round($it.Length / 1KB, 0)
            $tm = $it.LastWriteTime.ToString('yyyy-MM-dd HH:mm')
        }
    } catch {}
    $rows.Add(('{0},{1},{2},{3},{4},{5},{6}' -f $mt, $ext, $kb,
              (Csv-Escape $folder), (Csv-Escape $name), $src, $tm))
    $rowKeys.Add($mt + '|' + $folder + '|' + $name)
}

# --- 1) Recent .lnk ---
$nRecent = 0
try {
    $recent = if ($RecentDir) { $RecentDir } else { [Environment]::GetFolderPath('Recent') }
    $sh = New-Object -ComObject WScript.Shell
    foreach ($lnk in Get-ChildItem -LiteralPath $recent -Filter '*.lnk' -ErrorAction SilentlyContinue) {
        try {
            $target = $sh.CreateShortcut($lnk.FullName).TargetPath
            if ($target) { Add-Row $lnk.LastWriteTime $target 'lnk'; $nRecent++ }
        } catch {}
    }
} catch { Write-Host "[recent] Recent folder scan failed: $($_.Exception.Message)" }

# --- 2) Office File MRU (registry, [T<hex FILETIME>]*<path>) ---
$nMru = 0; $nMruKeys = 0
if (-not $NoMru) {
    $mruKeys = New-Object System.Collections.Generic.List[string]
    foreach ($app in @('Word', 'Excel', 'PowerPoint')) {
        $base = "HKCU:\Software\Microsoft\Office\16.0\$app"
        $mruKeys.Add("$base\File MRU")                       # 로컬 계정(로그인 안 한 Office)
        # M365/조직 계정으로 로그인한 Office 는 User MRU\{LiveId_|ADAL_}<id>\File MRU 에만 쓴다 (Place MRU 는 폴더 목록이라 제외)
        foreach ($u in @(Get-ChildItem -Path "$base\User MRU" -ErrorAction SilentlyContinue)) {
            $mruKeys.Add((Join-Path $u.PSPath 'File MRU'))
        }
    }
    foreach ($key in $mruKeys) {
        if (-not (Test-Path -LiteralPath $key)) { continue }
        $nMruKeys++
        try { $props = Get-ItemProperty -LiteralPath $key } catch { continue }
        foreach ($p in $props.PSObject.Properties) {
            if ($p.Name -notlike 'Item*') { continue }
            if ([string]$p.Value -match '\[T([0-9A-Fa-f]{16})\]\[?[^\]]*\]?\*(.+)$') {
                try {
                    $ft = [DateTime]::FromFileTime([Convert]::ToInt64($Matches[1], 16))
                    Add-Row $ft $Matches[2] 'mru'
                    $nMru++
                } catch {}
            }
        }
    }
}

Write-Lines (Join-Path $outDir 'recent.csv') $rows
Write-Host ("[recent] lnk scanned={0}, mru keys={1}, mru scanned={2}, rows in range={3}" -f $nRecent, $nMruKeys, $nMru, ($rows.Count - 1))
if (-not $NoMru -and $nMruKeys -eq 0) { Write-Host '[recent] Office File MRU 키 없음 (Office 16 미설치 또는 아직 문서를 연 적 없음)' }

$kwStat = [ordered]@{}
foreach ($k in ($exclStat.Keys | Sort-Object)) { $kwStat[$k] = @{ files = $exclStat[$k]['files']; folders = $exclStat[$k]['dirs'].Count } }
if ($kwStat.Count -gt 0) {
    Write-Host ("[recent] 제외: " + (($kwStat.Keys | ForEach-Object { "{0} {1}폴더 {2}건" -f $_, $kwStat[$_]['folders'], $kwStat[$_]['files'] }) -join ' · '))
}
$fnOut = [ordered]@{}
foreach ($k in ($fnStat.Keys | Sort-Object)) { $fnOut[$k] = @{ files = $fnStat[$k]['files']; folders = $fnStat[$k]['dirs'].Count } }
if ($fnOut.Count -gt 0) {
    Write-Host ("[recent] 폴더명 제외(excludeFolderNames): " + (($fnOut.Keys | ForEach-Object { "{0} {1}폴더 {2}건" -f $_, $fnOut[$_]['folders'], $fnOut[$_]['files'] }) -join ' · '))
}
$pkgOut = [ordered]@{}
foreach ($k in ($pkgStat.Keys | Sort-Object)) { $pkgOut[$k] = @{ files = $pkgStat[$k]['files']; folders = $pkgStat[$k]['dirs'].Count } }
if ($pkgOut.Count -gt 0) {
    Write-Host ("[recent] 패키지·빌드 폴더 제외: " + (($pkgOut.Keys | ForEach-Object { "{0} {1}폴더 {2}건" -f $_, $pkgOut[$_]['folders'], $pkgOut[$_]['files'] }) -join ' · ') + '  (build·release·target 류는 빌드 표식이 있을 때만)')
}
try {
    Update-ExcludedJson 'recent' ([ordered]@{
        updated = (Get-Date).ToString('yyyy-MM-dd HH:mm')
        period = @($since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'))
        rows = ($rows.Count - 1)
        lnk_scanned = $nRecent
        mru_keys = $nMruKeys
        mru_scanned = $nMru
        by_keyword = $kwStat
        folder_names = $fnOut
        package_dirs = $pkgOut
        package_dirs_on = $pkgOn
        self_excluded = $script:nSelf
        note = 'by_keyword/folder_names/package_dirs: 제외된 파일·폴더 수. 경로는 남기지 않는다'
    })
} catch { Write-Host ("[recent] files_excluded.json 기록 실패: " + $_.Exception.Message) }

# 관측 누적 (recent_history.csv)
try {
    $h = Merge-History (Join-Path $outDir 'recent_history.csv') $header @($rows | Select-Object -Skip 1) $rowKeys 'recent'
    Write-Host ("[recent] history: {0:n0}행 ({1}개월 · 이전 {2:n0}행과 합집합 · 400일 보관)" -f $h['total'], $h['months'], $h['old'])
} catch { Write-Host ("[recent] recent_history.csv 누적 실패: " + $_.Exception.Message) }
