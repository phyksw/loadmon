# Prepare-Move.ps1 - 이 폴더를 다른 PC 로 통째로 옮길 수 있게 '잡고 있는 것'을 놓아 준다.
#
# 왜 필요한가: 분석이 끝난 뒤 폴더를 옮기려 하면 "사용 중" 이라 옮겨지지 않는다.
# 잡고 있는 것은 대개 우리 자신이다 - 대시보드(python ui\app.py), 팀 서버(teamserver.py),
# Copilot 전용 Edge(data\copilot_profile), 상시 샘플러(powershell), 그리고 그 폴더를 열어 둔 탐색기.
#
# 중요: 이 스크립트는 %TEMP% 로 복사돼 실행된다. LoadMonitor 폴더 안에서 실행하면
# 스크립트 파일 자체가 폴더를 잡아 '옮길 수 있는가' 시험이 항상 실패한다.
#
# ── 화면 문구 규칙(제보로 고친 것) ────────────────────────────────────────────
# 제보: "작업이 종료되었음에도 cmd 창 멘트 때문에 사람들이 오류가 난 줄 알고 계속 시도한다".
# 감사에서 확인한 원인과 그 처방:
#  · 성공했는데도 '[!] 탐색기가 …' 경고가 성공 배너 **위**에 찍혔다. 이 도구에서 '[!]' 는 오류 표시라
#    사용자가 그것을 먼저 읽고 실패로 판단했고, 창을 닫고 다시 실행하려면 탐색기로 폴더를 또 열어야 해서
#    같은 경고가 또 떴다. → 이동 가능 확인을 **먼저** 하고, 성공하면 탐색기 경고를 아예 찍지 않는다.
#    (성공 경로에서는 '[!]' 를 절대 쓰지 않는다.)
#  · 성공 화면의 유일한 상태 줄이 '종료할 우리 프로그램이 없습니다' 라는 부정문이었다. → 능동 서술로.
#  · 성공·실패 배너가 글자만 다르고 모양이 똑같았다. → 머리표([완료]/[실패])·테두리 문자·색을 다르게.
#  · 화면 어디에도 '완료' 가 없었고 마지막 줄이 설명문이었다. → 마지막 줄에 판정을 다시 찍는다.
#  · PID 나열은 개발자 덤프로 읽힌다. → 화면에는 사람 말 이름만, PID·원문은 move_ready.txt 로.
#  · 실패 사유가 영문 .NET 예외 원문이었다. → 한국어 한 줄로 옮기고 원문은 기록으로.
#  · 창 제목이 비어 있었다. → 스스로 제목을 잡고 끝에 [완료]/[미완료] 를 붙인다.
#  · 이미 준비된 상태를 몰라 반복 실행을 못 막았다. → 지난 기록을 읽어 '이미 준비돼 있습니다' 를 알린다.
#
# Usage:  powershell -ExecutionPolicy Bypass -File Prepare-Move.ps1 -Root "D:\...\LoadMonitor24"
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [switch]$NoWait,
    [switch]$CheckOnly,
    [int]$CloseSec = 20     # 성공 시 이 초 뒤 창을 스스로 닫는다(0 = 즉시). 실패 시에는 기다린다.
                        # 5초였는데 마지막 안내(옮기는 방법)를 읽기 전에 닫힌다는 제보로 늘렸다.
)
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor24 - PC 이동 준비' } catch {}
# 경로 정규화 — bat 가 "…\LoadMonitor24\." 처럼 넘겨도(끝 역슬래시가 닫는 따옴표를 삼키지 않게 붙이던 점)
# '\.'·'..'·끝 역슬래시를 지운 정규 경로로 만든다. 실사고: '…\.' 그대로 Split-Path 하면 부모가 폴더 자신이 되어
# 폴더를 '_이동확인_임시' 로 바꿔 놓고 되돌리지 못한 채, 빈 껍데기 LoadMonitor24\report\move_ready.txt 만 만들었다.
if ($Root -match '^[A-Za-z]:$') { $Root += '\' }          # 'D:' 는 '그 드라이브의 현재 폴더' 라 뜻이 달라진다
try {
    if (-not [System.IO.Path]::IsPathRooted($Root)) { $Root = Join-Path (Get-Location).Path $Root }
    $Root = [System.IO.Path]::GetFullPath($Root)
} catch {}
if ($Root.Length -gt 3) { $Root = $Root.TrimEnd('\') }     # 드라이브 루트('D:\')는 그대로
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { Write-Host "[이동준비] 폴더가 없습니다: $Root"; if (-not $NoWait) { pause }; exit 1 }
if ($Root -match '^[A-Za-z]:\\$') { Write-Host "[이동준비] 드라이브 루트($Root)는 이름을 바꿔 확인할 수 없습니다 - LoadMonitor24 를 하위 폴더에 두세요"; if (-not $NoWait) { pause }; exit 1 }
Set-Location ([System.IO.Path]::GetTempPath())     # 이 창이 폴더를 잡지 않게
# Set-Location 은 PowerShell 의 위치만 바꾸고 프로세스의 현재 폴더(Win32 cwd)는 그대로다 — bat(cd /d "%~dp0" 뒤 start)
# 나 대시보드(app.py 의 cwd)에서 띄우면 우리 프로세스 자신이 LoadMonitor24 안에 서 있어 이름 바꾸기 시험이
# "다른 프로세스가 사용 중" 으로 항상 실패했다(실측). 프로세스 cwd 도 TEMP 로 옮겨 손을 뗀다.
try { [Environment]::CurrentDirectory = [System.IO.Path]::GetTempPath() } catch {}

function Say([string]$text, [string]$color) {
    if ($color) { try { Write-Host $text -ForegroundColor $color; return } catch {} }
    Write-Host $text
}

# 프로세스 이름을 사람 말로 — 화면에는 이것만 쓰고 PID·경로는 기록 파일로 보낸다.
function Friendly([string]$name, [string]$cmdline) {
    $n = ($name -replace '\.exe$', '').ToLower()
    if ($n -eq 'msedge') { return 'Copilot 전용 Edge 창' }
    if ($n -eq 'powershell' -or $n -eq 'pwsh') { return '상시 샘플러' }
    if ($n -eq 'cmd') { return 'LoadMonitor24 실행 창' }
    if ($n -eq 'python' -or $n -eq 'pythonw') {
        if ($cmdline -match 'teamserver\.py') { return '팀 서버' }
        if ($cmdline -match 'app\.py') { return '대시보드' }
        return '분석·수집 프로그램'
    }
    return $name
}

# 영문 .NET 예외를 한국어 한 줄로 — 원문은 화면에 내지 않고 move_ready.txt 에만 남긴다.
function Explain([string]$msg) {
    if (-not $msg) { return '확인이 막혔습니다' }
    if ($msg -match 'being used by another process|다른 프로세스') { return '다른 프로그램이 이 폴더의 파일을 열고 있습니다' }
    if ($msg -match 'is denied|Access to the path|액세스가 거부') { return '이 폴더의 이름을 바꿀 권한이 없습니다' }
    if ($msg -match 'already exists|이미 있') { return '같은 이름의 폴더가 이미 있습니다' }
    if ($msg -match 'could not be found|찾을 수 없') { return '폴더를 찾지 못했습니다' }
    return '확인이 막혔습니다'
}

# 파일 수·용량을 잰다. 배열로 돌려주면 PowerShell 이 풀어 버려 호출부에서 값이 섞인다(실사고) - 객체로 돌려준다.
function Folder-Size([string]$path) {
    $r = [pscustomobject]@{ N = 0; MB = 0.0 }
    if (-not (Test-Path -LiteralPath $path)) { return $r }
    $f = @(Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue)
    $r.N = $f.Count
    if ($f.Count) { $r.MB = [math]::Round((($f | Measure-Object Length -Sum).Sum) / 1MB, 1) }
    return $r
}

# 옮기기 전에 프로필에서 '옮길 필요가 없는 것' 을 지운다.
# 지울 목록을 나열하지 않고 **남길 것만 남긴다** — Edge 는 버전이 오를 때마다 새 컴포넌트 폴더를
# 만들어서(ProvenanceData·Edge Entity Extraction·Edge Wallet·Subresource Filter…) 이름 목록 방식은
# 반드시 낡는다. 실측: 예전 목록의 DawnCache·optimization_guide_model_store 는 지금 프로필에 없는
# 이름이고, 그 목록으로는 529MB 중 244MB 밖에 못 걷어냈다(반전 규칙은 510MB).
# 로그인은 Default 폴더 안(Cookies·Local Storage 의 MSAL 토큰)과 루트 Local State(암호 키)에 있고
# 둘 다 남긴다. 이름 비교는 반드시 완전 일치 — '*Wallet*' 같은 와일드카드는 루트 'Edge Wallet'(지워도 됨)과
# Default\EdgeWallet(보존)을, '*crx_cache*' 는 component_crx_cache(지움)와 extensions_crx_cache(보존)를 뒤섞는다.
$script:KEEP_ROOT = @('Default', 'Local State', 'Last Browser', 'Last Version',
                      'first_party_sets.db', 'Variations')
$script:DEL_IN_DEFAULT = @('Cache', 'Code Cache', 'GPUCache', 'ShaderCache', 'DawnCache',
                           'DawnGraphiteCache', 'DawnWebGPUCache', 'GrShaderCache',
                           'component_crx_cache', 'optimization_guide_hint_cache_store',
                           'optimization_guide_model_store', 'EdgeCoupons')
# 저장된 비밀번호·자동완성·방문 이력은 옮길 폴더에 있을 이유가 없다 — 실측해 보니 전용 프로필에도
# 동기화로 개인 비밀번호와 방문 이력이 들어와 있었다(공개 저장소라 건수는 적지 않는다).
# 로그인 세션은 Cookies·Local State 로 유지되므로 이 PC 에서 계속 써도 다시 로그인하지 않는다.
$script:DEL_FILES_IN_DEFAULT = @('Login Data', 'Login Data For Account', 'Web Data', 'History')

# Remove-Item -Recurse 는 260자(MAX_PATH)를 넘는 경로에서 조용히 실패한다 — Service Worker\CacheStorage 의
# GUID 경로가 쉽게 넘는다(실측: 267자에서 DirectoryNotFoundException 'the-real-index', 21.4MB 가 그대로 남았다).
# 도구 폴더가 깊은 곳(OneDrive\문서\…)에 있으면 흔한 일이라 \\?\ 접두사로 한 번 더 시도한다.
function Remove-Tree([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    try { Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop; return } catch {}
    $long = if ($path -like '\\*') { '\\?\UNC' + $path.Substring(1) } else { '\\?\' + $path }
    try { [System.IO.Directory]::Delete($long, $true); return } catch {}
    try { [System.IO.File]::Delete($long) } catch {}
}

function Trim-Profile([string]$prof) {
    foreach ($it in @(Get-ChildItem -LiteralPath $prof -Force -ErrorAction SilentlyContinue)) {
        if ($script:KEEP_ROOT -contains $it.Name) { continue }
        Remove-Tree $it.FullName
    }
    $def = Join-Path $prof 'Default'
    if (-not (Test-Path -LiteralPath $def -PathType Container)) { return }
    foreach ($d in $script:DEL_IN_DEFAULT) { Remove-Tree (Join-Path $def $d) }
    Remove-Tree (Join-Path $def 'Service Worker\CacheStorage')   # 등록부(Database·ScriptCache)는 남긴다
    foreach ($f in $script:DEL_FILES_IN_DEFAULT) { Remove-Tree (Join-Path $def $f) }
}

Write-Host ''
Say '  [PC 이동 준비] 이 폴더를 다른 PC 로 옮길 수 있게 정리합니다' 'Cyan'
Write-Host ("  대상: " + $Root)
Write-Host ''
if (-not $NoWait) { Start-Sleep -Milliseconds 800 }   # 우리를 띄운 bat/cmd 가 먼저 닫히도록

# 지난 준비 기록 — 이미 끝난 것을 모르고 또 누르는 것을 막는다(제보의 '계속 시도').
$prevWhen = $null
try {
    $rp = Join-Path $Root 'report\move_ready.txt'
    if (Test-Path -LiteralPath $rp) {
        $age = (Get-Date) - (Get-Item -LiteralPath $rp).LastWriteTime
        if ($age.TotalHours -lt 12) { $prevWhen = (Get-Item -LiteralPath $rp).LastWriteTime }
    }
} catch {}

function Procs-Under([string]$root) {
    # 실행 파일이 이 폴더 안에 있거나(내장 파이썬), 명령줄이 이 폴더를 가리키는 프로세스
    $esc = [regex]::Escape($root)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath -match $esc) -or
        ($_.CommandLine -and $_.CommandLine -match $esc)
    }
}

$killed = New-Object System.Collections.Generic.List[string]     # 화면용 - 사람 말 이름
$killedLog = New-Object System.Collections.Generic.List[string]  # 기록용 - 이름 + PID
if (-not $CheckOnly) {
    # 우리가 띄운 창(대시보드·LoadMonitor24 실행 창)이 곧 사라진다. 예고 없이 사라지면 그것 자체가
    # '오류로 꺼졌다' 로 읽힌다(감사 확정) — 죽이기 전에 먼저 알린다.
    Say '  LoadMonitor24 창(대시보드·팀 서버·샘플러)을 닫습니다 - 창이 사라지는 것은 정상입니다.' 'DarkGray'
    Start-Sleep -Milliseconds 400
    # ① 우리 것부터 - 대시보드·팀 서버·수집기(python), 상시 샘플러(powershell)
    foreach ($p in Procs-Under $Root) {
        if ($p.ProcessId -eq $PID) { continue }
        $nm = $p.Name
        if ($nm -notmatch '^(python|pythonw|powershell|pwsh|cmd)\.exe$') { continue }
        try {
            $fr = Friendly $nm $p.CommandLine
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            $killed.Add($fr)
            $killedLog.Add("$nm (pid $($p.ProcessId)) = $fr")
        } catch {}
    }
    # ② Copilot 전용 Edge - 일반 Edge 는 건드리지 않는다
    Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*copilot_profile*' } | ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                $killed.Add('Copilot 전용 Edge 창')
                $killedLog.Add("msedge (Copilot 전용, pid $($_.ProcessId))")
            } catch {}
        }
    if ($killed.Count) {
        # 화면에는 사람 말 이름만, 중복을 지우고 최대 3개까지. PID 는 기록 파일로 보낸다.
        $uniq = @($killed | Select-Object -Unique)
        $show = if ($uniq.Count -gt 3) { ($uniq[0..2] -join ', ') + (' 외 {0}개' -f ($uniq.Count - 3)) } else { $uniq -join ', ' }
        Write-Host ("  닫았습니다: " + $show)
    } else {
        # 부정문('없습니다')은 이 도구에서 오류 문구라 성공 화면에 쓰지 않는다 — 능동 서술로 적는다.
        Write-Host '  확인했습니다: 이 폴더를 쓰고 있는 LoadMonitor24 프로그램은 이미 모두 닫혀 있었습니다'
    }
    Start-Sleep -Milliseconds 700
}

# 탐색기가 그 폴더를 열어 두었는지 - 목록만 모아 두고 화면에는 아직 찍지 않는다.
# 열려 있어도 이동 가능 확인은 대개 통과하므로, 성공했다면 이 경고는 사용자를 헷갈리게 할 뿐이다.
$explorer = @()
try {
    $sh = New-Object -ComObject Shell.Application
    foreach ($w in $sh.Windows()) {
        try {
            $p = $w.Document.Folder.Self.Path
            # 구분자까지 봐야 형제 폴더(LoadMonitor24_old)를 오탐하지 않는다
            if ($p -and ($p -eq $Root -or $p.StartsWith($Root + '\', [System.StringComparison]::OrdinalIgnoreCase))) { $explorer += $p }
        } catch {}
    }
} catch {}

# ── 진짜 시험: 폴더 이름을 잠깐 바꿔 본다. 성공하면 옮길 수 있다는 뜻이다. ──
$parent = Split-Path -Parent $Root
$leaf = Split-Path -Leaf $Root
$probe = Join-Path $parent ($leaf + '_이동확인_임시')
$movable = $false
$restored = $false
$why = ''
$whyRaw = ''
$backRaw = ''
# 방금 죽인 프로그램이 손을 놓는 데 시간이 걸린다 - 한 번 실패했다고 바로 실패로 적으면
# '실제로는 곧 옮길 수 있는데 실패 배너' 가 뜬다(감사 확정). 몇 번 더 기다려 본다.
for ($try = 0; $try -lt 4 -and -not $movable; $try++) {
    if ($try) { Start-Sleep -Milliseconds 900 }
    try {
        Rename-Item -LiteralPath $Root -NewName ($leaf + '_이동확인_임시') -ErrorAction Stop
        $movable = $true
    } catch {
        $whyRaw = $_.Exception.Message
        $why = Explain $whyRaw
    }
}
if ($movable) {
    # 되돌리기 — 백신·탐색기가 새 이름을 잠깐 잡을 수 있어 몇 번 더 시도한다
    for ($i = 0; $i -lt 5 -and -not $restored; $i++) {
        if ($i) { Start-Sleep -Milliseconds 400 }
        try { Rename-Item -LiteralPath $probe -NewName $leaf -ErrorAction Stop; $restored = $true } catch { $backRaw = $_.Exception.Message }
    }
}

Write-Host ''
if ($movable) {
    try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor24 - PC 이동 준비 [완료]' } catch {}
    Say '  ============================================================' 'Green'
    Say '   [완료] PC 이동 준비가 끝났습니다.' 'Green'
    Say '          이제 이 폴더를 통째로 옮기거나 복사하세요.' 'Green'
    Say '  ============================================================' 'Green'
    if ($prevWhen) {
        Write-Host ''
        Write-Host ("   이미 " + $prevWhen.ToString('M월 d일 HH:mm') + " 에 준비를 마친 폴더입니다 - 다시 확인해도 옮길 수 있는 상태입니다.")
    }
    Write-Host ''
    Write-Host '   · 다른 PC 로 옮긴 뒤 LoadMonitor24-UI.bat 을 실행하면'
    Write-Host '     지난 PC 의 수집 데이터는 자동으로 data\추가PC\ 로 보관되고'
    Write-Host '     분석은 두 PC 를 합쳐 계산합니다.'
    Write-Host '   · report\upload_pending\ 의 업로드 대기 묶음도 함께 따라갑니다.'

    # ── 옮기기 전 정리 — 폴더 용량의 대부분은 옮길 필요가 없는 Edge 컴포넌트다 ──────────────
    # 실측(설치본 8개): data\copilot_profile 이 폴더 용량의 96%(LoadMonitor18 은 2,679개 551.6MB 중
    # 2,507개 529.2MB). 그 안에서 ProvenanceData 168.6MB + component_crx_cache 168~185MB 가 65% 인데
    # 둘 다 Edge 가 새 PC 에서 다시 받는 컴포넌트다. 로그인 세션은 Local State 의 암호 키가 DPAPI 로
    # '이 PC·이 계정' 에 묶여 있어(마스터키는 %APPDATA%\Microsoft\Protect\) 폴더째 복사로 따라가지 않는다.
    # 예전에는 '캐시를 빼면 N MB' 라고 알려만 주고 지우는 일은 사용자에게 떠넘겼다 — 실제로는 아무도
    # 지우지 않고 그대로 드래그했다(제보). 그래서 여기서 직접 지운다(규칙은 파일 앞 Trim-Profile).
    if (-not $CheckOnly) {
        try {
            $where2 = if ($restored) { $Root } else { $probe }
            $profDir = Join-Path $where2 'data\copilot_profile'
            if (Test-Path -LiteralPath $profDir -PathType Container) {
                $before = Folder-Size $where2
                Write-Host ''
                Say '   옮길 준비로 Copilot 캐시를 정리하는 중입니다 - 수십 초 걸릴 수 있습니다...' 'Cyan'
                Trim-Profile $profDir
                # 회수량은 **삭제 후 재측정**으로 낸다. 삭제 전에 세면 잠겨서 못 지운 것까지 '지웠다' 로
                # 집계돼 "정리했다는데 폴더는 그대로" 가 된다(옛 Make-MovePack.trim_profile 의 결함).
                $after = Folder-Size $where2
                Say ("   정리했습니다: {0:N0}개 · {1:N1} MB 회수" -f ($before.N - $after.N),
                     [math]::Round($before.MB - $after.MB, 1)) 'Green'
                Write-Host ("   지금 옮길 크기: 파일 {0:N0}개 · {1:N1} MB" -f $after.N, $after.MB)
                Write-Host '   Copilot 로그인은 이 PC 에 그대로 남습니다 - 새 PC 에서는 [AI 연결 진단] 으로 한 번 로그인하세요.'
            }
        } catch {}
    }
    # 옮기는 방법은 한 가지만 말한다. 실제 사용자는 zip 도 robocopy 도 쓰지 않고 탐색기로 폴더를
    # 드래그한다(제보: zip 을 따로 옮기거나 푸는 것은 못 한다). 위에서 이미 폴더를 줄여 뒀으므로
    # 드래그로도 빠르다. zip(tools\Make-MovePack.py)·robocopy 는 docs 의 설정가이드로 내렸다.
    Write-Host ''
    Say '   [옮기는 방법] 이 폴더를 탐색기에서 그대로 드래그해 옮기세요.' 'Cyan'
    Write-Host '      새 PC 에서 LoadMonitor24-UI.bat 을 실행하면 이어서 바로 쓸 수 있습니다.'
    Write-Host '      원본 폴더는 지우지 마세요 - 새 PC 가 잘 도는 것을 확인한 뒤에 정리하시면 됩니다.'
    if (-not $restored) {
        # 이것은 실패가 아니다 - 옮길 수 있다는 사실은 이미 증명됐고, 이름만 임시 이름으로 남았다.
        # 예전에는 '[!] 되돌리지 못했습니다' 가 성공 배너 위에 찍혀 실패로 읽혔다(감사 확정).
        $now = if (Test-Path -LiteralPath $probe) { $probe } else {
            $hit = @(Get-ChildItem -LiteralPath $parent -Directory -Filter ($leaf + '_이동확인_임시*') -ErrorAction SilentlyContinue | Select-Object -First 1)
            if ($hit.Count) { $hit[0].FullName } else { $probe }
        }
        Write-Host ''
        Say '   [참고] 폴더 이름이 지금 임시 이름으로 남아 있습니다 - 옮기는 데는 지장이 없습니다.' 'Yellow'
        Write-Host ("          " + $now)
        Write-Host ("          그대로 옮기셔도 되고, '" + $leaf + "' 로 이름을 바꾸셔도 됩니다.")
    }
    try {
        # 기록은 '지금 실제로 있는' 폴더 안에만 쓴다 — 되돌리지 못했으면 아직 $probe 이름이다.
        # 없는 경로에 report\ 를 새로 만들면 빈 껍데기 폴더가 생겨 사용자가 그것을 옮긴다(실사고).
        $where = if ($restored) { $Root } else { $probe }
        if (Test-Path -LiteralPath $where -PathType Container) {
            $rep = Join-Path $where 'report'
            if (-not (Test-Path -LiteralPath $rep)) { New-Item -ItemType Directory -Force -Path $rep | Out-Null }
            # PID·영문 원문은 화면이 아니라 여기에 남긴다(화면은 사람 말로만).
            $log = @("이동 준비 완료  " + (Get-Date).ToString('yyyy-MM-dd HH:mm'),
                     "폴더 이동 가능 확인: 예",
                     "이름 되돌리기: " + $(if ($restored) { "성공" } else { "실패 - 임시 이름 유지 (" + $backRaw + ")" }),
                     "종료한 프로그램: " + $(if ($killedLog.Count) { $killedLog -join ', ' } else { "(없음 - 이미 모두 닫혀 있었음)" }),
                     "옮길 크기(캐시 포함): " + $(try { $a = Folder-Size $where; "{0}개 {1}MB" -f $a.N, $a.MB } catch { "(재지 못함)" }),
                     "탐색기가 열어 둔 창: " + $(if ($explorer.Count) { (@($explorer | Select-Object -Unique) -join ', ') } else { "(없음)" }))
            [System.IO.File]::WriteAllLines((Join-Path $rep 'move_ready.txt'), $log, [System.Text.Encoding]::UTF8)
        }
    } catch {}
    Write-Host ''
    Say '   [완료] 준비 끝 - 다시 실행하지 않으셔도 됩니다. 대시보드·팀 서버·샘플러는 모두 닫혔습니다.' 'Green'
} else {
    try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor24 - PC 이동 준비 [미완료]' } catch {}
    Say '  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' 'Red'
    Say '   [실패] 아직 무언가가 이 폴더를 잡고 있습니다.' 'Red'
    Say '  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' 'Red'
    Write-Host ("   사유: " + $(if ($why) { $why } else { '확인이 막혔습니다' }))
    Write-Host ''
    if ($explorer.Count) {
        # 실패했을 때에만 탐색기 경로를 보여 준다 - 이때는 실제로 조치가 필요한 정보다.
        Write-Host '   탐색기가 이 폴더를 열어 두고 있습니다 - 그 창을 닫으세요:'
        foreach ($p in ($explorer | Select-Object -Unique)) { Write-Host ("      " + $p) }
        Write-Host ''
    }
    Write-Host '   흔한 원인과 조치:'
    Write-Host '   1) 탐색기에서 이 폴더(또는 하위 폴더)를 열어 두었다  -> 그 창을 닫으세요'
    Write-Host '   2) 이 폴더의 파일을 Excel·메모장 등으로 열어 두었다  -> 닫으세요'
    Write-Host '   3) 명령 프롬프트가 이 폴더에 들어가 있다             -> 그 창을 닫으세요'
    Write-Host '   4) 백신 검사가 진행 중이다                           -> 잠시 뒤 다시 실행'
    $left = @(Procs-Under $Root | Where-Object { $_.ProcessId -ne $PID } |
              ForEach-Object { Friendly $_.Name $_.CommandLine } | Select-Object -Unique)
    if ($left.Count) {
        Write-Host ''
        Write-Host ('   아직 이 폴더를 쓰는 프로그램: ' + ($left -join ', '))
    }
    Write-Host ''
    Say '   [미완료] 위 1~4 를 조치한 뒤 다시 실행하세요.' 'Red'
}
Write-Host ''
# 다 끝났는데 '아무 키나 누르세요' 로 창이 남아 있으면 그것 자체가 '안 끝났다' 로 읽힌다(제보).
# 성공이면 스스로 닫고, 실패면 사유를 읽어야 하므로 기다린다.
if (-not $NoWait) {
    if ($movable) {
        $left = [math]::Max(0, $CloseSec)
        $held = $false
        while ($left -gt 0) {
            Write-Host ("`r  [완료] 정리가 끝났습니다 - {0}초 뒤 이 창이 자동으로 닫힙니다. (읽고 계시면 아무 키나 누르세요)   " -f $left) -NoNewline
            $t0 = [datetime]::Now
            while (([datetime]::Now - $t0).TotalMilliseconds -lt 1000) {
                # 콘솔이 아닌 곳(입력 리디렉션·작업 스케줄러)에서는 KeyAvailable 이 예외를 던진다 -
                # 그때는 키를 못 받는 것이 정상이므로 조용히 카운트다운만 계속한다.
                try { if ($Host.UI.RawUI.KeyAvailable) { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown'); $held = $true; break } }
                catch { Start-Sleep -Milliseconds 920; break }
                Start-Sleep -Milliseconds 80
            }
            if ($held) { break }
            $left--
        }
        Write-Host ''
        if ($held) {
            Write-Host '  자동 닫힘을 멈췄습니다. 창을 닫으려면 아무 키나 누르세요.'
            $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        }
    } else {
        Write-Host '  창을 닫으려면 아무 키나 누르세요.'
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    }
}
if ($movable) { exit 0 } else { exit 1 }
