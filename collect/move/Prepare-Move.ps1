<#
.SYNOPSIS
  LoadMonitor27 이동 시험 도우미 — 이 폴더를 다른 PC 로 통째로 옮길 수 있는지 '이름 바꾸기'로 확인한다(TAB §1.11).

.DESCRIPTION
  [이동 준비](lm27 move-prepare · LoadMonitor27-이동준비.bat)가 이 스크립트를 %TEMP%\lm27_move_<rand>.ps1 사본으로
  보이는 콘솔 창에 띄운다. 프로그램 폴더 안에서 직접 실행하면 이 스크립트 파일이 폴더를 잡아 시험이 늘 실패하므로
  반드시 사본으로 실행한다.

  하는 일:
    0. -WaitPid 없이 시작되면(LoadMonitor27-이동준비.bat 경로) 먼저 "<ROOT>\python\python.exe" -X utf8 -B
       "<ROOT>\lm27_cli.py" move-prepare 를 불러 TAB §1.11 1~3단계(마지막 내보내기·sha 검증·move_ready.json)를 돌린다.
       그 명령이 -WaitPid 를 붙인 새 도우미 창을 띄우면 이 창은 끝난다(X-332 — bat 경로와 화면 경로가 같은 단계를 거친다).
       파이썬·진입 스크립트가 없거나 그 명령이 도우미를 띄우지 못하면(rc 1·3) 이 창에서 이름 바꾸기 시험을 이어 간다.
    1. 경로 정규화(…\. 꼬리·끝 역슬래시 제거 — 빈 껍데기 폴더 사고 방어), 작업 폴더를 %TEMP% 로.
    2. -WaitPid(화면 서버·CLI) 가 끝나기를 최대 -StopWaitSec 초 기다린다.
    3. 이 폴더의 python 으로 팀 서버가 돌고 있으면 멈추고 안내한다 — -Proceed(또는 창에서 Y) 전에는 아무것도
       종료하지 않는다(조용히 죽이지 않는다).
    4. 실행 파일·명령줄이 이 폴더 아래인 python.exe·pythonw.exe·powershell.exe·cmd.exe 만 종료한다(자기 자신·부모 제외,
       트리 종료 없음). 에이전트는 실행 경로가 폴더 밖이라 대상이 아니다. 탐색기·사용자가 연 Office 창은 절대 종료하지 않는다.
    5. 이름 바꾸기 시험: ROOT → ROOT.__mvtest_<rand> → 원래 이름(각 -RenameRetries 회, 0.5·1·2·4초 간격).
       되돌리기는 5회까지 다시 시도하고, 그래도 실패하면 바뀐 이름을 크게 알린다(폴더를 잃지 않게).
    6. 실패하면 Restart Manager 로 이 폴더의 파일을 쥔 프로세스(이름·pid)와 이 폴더를 실행 경로로 가진 프로세스를 보이고
       "탐색기 창이나 명령 창이 이 폴더를 열어 두고 있을 수 있습니다" 를 안내한다.
  이 스크립트는 디스크에 아무것도 쓰지 않는다(L-09) — move_ready.json 은 파이썬(lm27.bundle.move)이 미리 쓴다.
  결과는 이 창에만 보인다. 성공 경로에서는 '[!]' 표기를 쓰지 않는다.

  종료 코드: 0 옮길 수 있음 · 1 무언가가 폴더를 잡고 있음 · 2 팀 서버 동거로 멈춤 · 3 인자 오류(폴더 없음·드라이브 루트).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File %TEMP%\lm27_move_1a2b3c4d.ps1 -Root "D:\도구\LoadMonitor27" -WaitPid 1234 -Gen 17
#>
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [int]$WaitPid = 0,
    [int]$Gen = -1,
    [int]$RenameRetries = 4,
    [int]$StopWaitSec = 15,
    [int]$CloseSec = 60,
    [switch]$CheckOnly,
    [switch]$Proceed,
    [switch]$NoWait
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor27 - 이동 준비' } catch { }

function Say([string]$Text, [string]$Color) {
    if ($Color) { try { Write-Host $Text -ForegroundColor $Color; return } catch { } }
    Write-Host $Text
}

function Hold-Window([bool]$Ok) {
    if ($NoWait) { return }
    if ($Ok) {
        $left = [Math]::Max(0, $CloseSec)
        while ($left -gt 0) {
            Write-Host ("`r  {0}초 뒤 이 창이 자동으로 닫힙니다. (읽고 계시면 아무 키나 누르세요)   " -f $left) -NoNewline
            $t0 = [DateTime]::Now
            $held = $false
            while (([DateTime]::Now - $t0).TotalMilliseconds -lt 1000) {
                try {
                    if ($Host.UI.RawUI.KeyAvailable) { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown'); $held = $true; break }
                } catch { Start-Sleep -Milliseconds 900; break }
                Start-Sleep -Milliseconds 80
            }
            if ($held) {
                Write-Host ''
                Write-Host '  자동 닫힘을 멈췄습니다. 창을 닫으려면 아무 키나 누르세요.'
                try { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') } catch { }
                return
            }
            $left--
        }
        Write-Host ''
    } else {
        Write-Host '  창을 닫으려면 아무 키나 누르세요.'
        try { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') } catch { }
    }
}

# ── 1. 경로 정규화 ──────────────────────────────────────────────────────────────
if ($Root -match '^[A-Za-z]:$') { $Root += '\' }
try {
    if (-not [System.IO.Path]::IsPathRooted($Root)) { $Root = Join-Path (Get-Location).Path $Root }
    $Root = [System.IO.Path]::GetFullPath($Root)
} catch { }
if ($Root.Length -gt 3) { $Root = $Root.TrimEnd('\') }
$TempDir = [System.IO.Path]::GetTempPath()
try { Set-Location -LiteralPath $TempDir } catch { }
try { [Environment]::CurrentDirectory = $TempDir } catch { }

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    Say '  [실패] 프로그램 폴더를 찾지 못했습니다.' 'Red'
    Write-Host ('  대상: ' + $Root)
    Hold-Window $false
    exit 3
}
if ($Root -match '^[A-Za-z]:\\$' -or $Root -match '^\\\\[^\\]+\\[^\\]+$') {
    Say '  [실패] 드라이브 루트는 이름을 바꿔 확인할 수 없습니다 - LoadMonitor27 를 하위 폴더에 두세요.' 'Red'
    Hold-Window $false
    exit 3
}
$RootSlash = $Root + '\'

Write-Host ''
Say '  [이동 준비] 이 폴더를 다른 PC 로 옮길 수 있는지 확인합니다' 'Cyan'
Write-Host ('  대상: ' + $Root)
Write-Host ''

# ── 0. bat 경로(-WaitPid 없음): 파이썬 move-prepare 로 1~3단계를 먼저(X-332) ──────────
if ($WaitPid -le 0 -and -not $CheckOnly) {
    $py = Join-Path $Root 'python\python.exe'
    $cli = Join-Path $Root 'lm27_cli.py'
    if ((Test-Path -LiteralPath $py -PathType Leaf) -and (Test-Path -LiteralPath $cli -PathType Leaf)) {
        Say '  마지막 내보내기와 검증을 합니다 - 잠시 기다려 주세요.' 'Cyan'
        & $py -X utf8 -B $cli move-prepare
        $prc = $LASTEXITCODE
        if ($prc -eq 0 -or $prc -eq 2) {
            Write-Host '  이동 시험 창을 새로 열었습니다 - 그 창의 결과를 확인하세요.'
            exit 0
        }
        Say '  준비 단계를 마치지 못해 이 창에서 이동 시험만 합니다.' 'Yellow'
    }
}

# ── 2. 화면 서버·CLI 종료 대기 ───────────────────────────────────────────────────
if ($WaitPid -gt 0 -and $WaitPid -ne $PID) {
    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $StopWaitSec))
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    }
}

# ── 이 폴더 아래 프로세스 ───────────────────────────────────────────────────────
$KillNames = @('python.exe', 'pythonw.exe', 'powershell.exe', 'cmd.exe')
$MyParent = 0
try { $MyParent = [int](Get-CimInstance Win32_Process -Filter ("ProcessId=" + $PID) -ErrorAction Stop).ParentProcessId } catch { }

function Test-UnderRoot([string]$Text) {
    if (-not $Text) { return $false }
    if ($Text.IndexOf($RootSlash, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    foreach ($q in @('"', "'")) {
        if ($Text.IndexOf($Root + $q, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    }
    return $Text.EndsWith($Root, [StringComparison]::OrdinalIgnoreCase)
}

function Get-RootProcs {
    # 종료 대상 이름(python·pythonw·powershell·cmd)만 WMI 에서 거른다 — 전체 프로세스 열거보다 훨씬 빠르다
    $out = @()
    $flt = (($KillNames | ForEach-Object { "Name='" + $_ + "'" }) -join ' OR ')
    foreach ($p in @(Get-CimInstance Win32_Process -Filter $flt -ErrorAction SilentlyContinue)) {
        if ($p.ProcessId -eq $PID) { continue }
        $exe = [string]$p.ExecutablePath
        $cmd = [string]$p.CommandLine
        $byExe = $exe -and $exe.StartsWith($RootSlash, [StringComparison]::OrdinalIgnoreCase)
        if ($byExe -or (Test-UnderRoot $cmd)) { $out += $p }
    }
    return $out
}

function Friendly($p) {
    $n = ([string]$p.Name).ToLower()
    $c = [string]$p.CommandLine
    if ($n -eq 'python.exe' -or $n -eq 'pythonw.exe') {
        if ($c -match '(?i)\bteam-server\b') { return '팀 서버' }
        if ($c -match '(?i)\bui\b') { return '화면(대시보드)' }
        return '분석·수집 프로그램'
    }
    if ($n -eq 'powershell.exe') { return 'PowerShell 창' }
    if ($n -eq 'cmd.exe') { return '명령 창' }
    return [string]$p.Name
}

# ── 3. 팀 서버 동거 확인 ────────────────────────────────────────────────────────
$procs = @(Get-RootProcs)
$servers = @($procs | Where-Object { ([string]$_.CommandLine) -match '(?i)\bteam-server\b' })
if ($servers.Count -gt 0 -and -not $Proceed -and -not $CheckOnly) {
    Say '  이 폴더의 파이썬으로 팀 서버가 실행 중입니다 - 폴더를 옮기면 팀 서버가 멈춥니다.' 'Yellow'
    Write-Host '  팀 서버는 옮기지 않는 별도 설치 폴더에서 운영하세요.'
    foreach ($s in $servers) { Write-Host ('    - 팀 서버 (pid ' + $s.ProcessId + ')') }
    $go = $false
    if (-not $NoWait) {
        try {
            $ans = Read-Host '  그래도 진행하려면 Y 를 입력하세요(그 밖은 중단)'
            $go = ($ans -match '^\s*[Yy]\s*$')
        } catch { $go = $false }
    }
    if (-not $go) {
        Say '  [중단] 아무것도 종료하지 않았습니다. 팀 서버를 다른 폴더로 옮긴 뒤 다시 실행하세요.' 'Yellow'
        Hold-Window $false
        exit 2
    }
}

# ── 4. 이 폴더를 쓰는 우리 프로그램 종료 ────────────────────────────────────────
$closed = New-Object System.Collections.Generic.List[string]
if (-not $CheckOnly) {
    foreach ($p in $procs) {
        if ($p.ProcessId -eq $PID -or $p.ProcessId -eq $MyParent) { continue }
        if ($KillNames -notcontains ([string]$p.Name).ToLower()) { continue }
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            $closed.Add((Friendly $p))
        } catch { }
    }
    if ($closed.Count -gt 0) {
        $uniq = @($closed | Select-Object -Unique)
        Write-Host ('  이 폴더를 쓰던 프로그램을 닫았습니다: ' + ($uniq -join ', '))
        Start-Sleep -Milliseconds 700
    } else {
        Write-Host '  확인했습니다: 이 폴더를 쓰는 LoadMonitor27 프로그램은 모두 닫혀 있습니다'
    }
}

# ── 5. 이름 바꾸기 시험 ─────────────────────────────────────────────────────────
$parent = Split-Path -Parent $Root
$leaf = Split-Path -Leaf $Root
$probeLeaf = $leaf + '.__mvtest_' + ([Guid]::NewGuid().ToString('N').Substring(0, 6))
$probe = Join-Path $parent $probeLeaf
$waits = @(500, 1000, 2000, 4000)
$movable = $false
$restored = $false
$why = ''
for ($i = 0; $i -lt [Math]::Max(1, $RenameRetries) -and -not $movable; $i++) {
    if ($i -gt 0) { Start-Sleep -Milliseconds $waits[[Math]::Min($i - 1, $waits.Count - 1)] }
    try {
        Rename-Item -LiteralPath $Root -NewName $probeLeaf -ErrorAction Stop
        $movable = $true
    } catch {
        $msg = [string]$_.Exception.Message
        if ($msg -match 'being used by another process|다른 프로세스') { $why = '다른 프로그램이 이 폴더의 파일을 열고 있습니다' }
        elseif ($msg -match 'is denied|Access to the path|액세스가 거부') { $why = '이 폴더의 이름을 바꿀 권한이 없거나 무언가가 폴더를 잡고 있습니다' }
        else { $why = '이름 바꾸기 시험이 막혔습니다' }
    }
}
if ($movable) {
    for ($j = 0; $j -lt 5 -and -not $restored; $j++) {
        if ($j -gt 0) { Start-Sleep -Milliseconds (400 * $j) }
        try { Rename-Item -LiteralPath $probe -NewName $leaf -ErrorAction Stop; $restored = $true } catch { }
    }
}

# ── 6. 결과 ──────────────────────────────────────────────────────────────────────
Write-Host ''
if ($movable) {
    $where = if ($restored) { $Root } else { $probe }
    $mb = 0.0
    try {
        $sum = (Get-ChildItem -LiteralPath $where -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
        if ($sum) { $mb = [Math]::Round($sum / 1MB, 1) }
    } catch { }
    try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor27 - 이동 준비 [완료]' } catch { }
    Say '  ============================================================' 'Green'
    Say ('   [완료] 이 폴더를 다음 PC 로 옮겨도 됩니다 (크기 {0} MB)' -f $mb) 'Green'
    Say '  ============================================================' 'Green'
    Write-Host '   · 탐색기에서 이 폴더를 그대로 드래그해 옮기세요. 원본은 새 PC 가 잘 도는 것을 확인한 뒤 정리하세요.'
    Write-Host '   · 이 PC 의 기록 에이전트는 계속 돕니다 - 나중에 이 PC 에서 [수집]하면 그동안의 기록이 들어옵니다.'
    if ($Gen -ge 0) { Write-Host ('   · 이동 목록 판: ' + $Gen) }
    if (-not $restored) {
        Write-Host ''
        Say '   [참고] 폴더 이름이 지금 임시 이름으로 남아 있습니다 - 옮기는 데는 지장이 없습니다.' 'Yellow'
        Write-Host ('          ' + $probe)
        Write-Host ("          그대로 옮기셔도 되고, '" + $leaf + "' 로 이름을 바꾸셔도 됩니다.")
    }
    Hold-Window $true
    exit 0
}

try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor27 - 이동 준비 [미완료]' } catch { }
Say '  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' 'Red'
Say '   [실패] 아직 무언가가 이 폴더를 잡고 있습니다.' 'Red'
Say '  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' 'Red'
Write-Host ('   사유: ' + $(if ($why) { $why } else { '이름 바꾸기 시험이 막혔습니다' }))

# Restart Manager — 이 폴더의 파일을 쥔 프로세스(비관리자도 파일 보유자는 찾는다. 폴더 cwd 는 못 찾는다 — 실측)
$rmSrc = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class Lm27Rm {
    [StructLayout(LayoutKind.Sequential)]
    struct RM_UNIQUE_PROCESS { public int dwProcessId; public System.Runtime.InteropServices.ComTypes.FILETIME ProcessStartTime; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct RM_PROCESS_INFO {
        public RM_UNIQUE_PROCESS Process;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string strAppName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string strServiceShortName;
        public int ApplicationType; public uint AppStatus; public uint TSSessionId;
        [MarshalAs(UnmanagedType.Bool)] public bool bRestartable;
    }
    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)] static extern int RmStartSession(out uint h, int f, string key);
    [DllImport("rstrtmgr.dll")] static extern int RmEndSession(uint h);
    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)] static extern int RmRegisterResources(uint h, uint nFiles, string[] files, uint nApps, IntPtr apps, uint nSvc, string[] svcs);
    [DllImport("rstrtmgr.dll")] static extern int RmGetList(uint h, out uint need, ref uint have, [In, Out] RM_PROCESS_INFO[] info, ref uint reasons);
    public static string[] Holders(string[] files) {
        var res = new List<string>();
        uint h; string key = Guid.NewGuid().ToString();
        if (RmStartSession(out h, 0, key) != 0) { return res.ToArray(); }
        try {
            if (RmRegisterResources(h, (uint)files.Length, files, 0, IntPtr.Zero, 0, null) != 0) { return res.ToArray(); }
            uint need = 0, have = 0, reasons = 0;
            int r = RmGetList(h, out need, ref have, null, ref reasons);
            if (r == 234 && need > 0) {
                var info = new RM_PROCESS_INFO[need]; have = need;
                if (RmGetList(h, out need, ref have, info, ref reasons) == 0) {
                    for (int i = 0; i < have; i++) { res.Add(info[i].strAppName + "|" + info[i].Process.dwProcessId); }
                }
            }
        } finally { RmEndSession(h); }
        return res.ToArray();
    }
}
'@
$holders = @()
try {
    if (-not ('Lm27Rm' -as [type])) { Add-Type -TypeDefinition $rmSrc -ErrorAction Stop }
    $files = New-Object System.Collections.Generic.List[string]
    foreach ($rel in @('data\.bundle.lock', 'config\config.json', 'python\python311.dll', 'lm27_cli.py')) {
        $f = Join-Path $Root $rel
        if (Test-Path -LiteralPath $f -PathType Leaf) { $files.Add($f) }
    }
    $dataDir = Join-Path $Root 'data'
    if (Test-Path -LiteralPath $dataDir -PathType Container) {
        foreach ($f in @(Get-ChildItem -LiteralPath $dataDir -Recurse -File -Force -ErrorAction SilentlyContinue | Select-Object -First 1500)) {
            if (-not $files.Contains($f.FullName)) { $files.Add($f.FullName) }
        }
    }
    if ($files.Count -gt 0) { $holders = @([Lm27Rm]::Holders($files.ToArray()) | Select-Object -Unique) }
} catch { $holders = @() }
if ($holders.Count -gt 0) {
    Write-Host ''
    Write-Host '   이 폴더의 파일을 열고 있는 프로그램:'
    foreach ($h in $holders) {
        $parts = ([string]$h).Split('|')
        Write-Host ('      - ' + $parts[0] + ' (pid ' + $parts[-1] + ')')
    }
}
$left = @(Get-RootProcs | Where-Object { $_.ProcessId -ne $MyParent })
if ($left.Count -gt 0) {
    Write-Host ''
    Write-Host '   이 폴더를 실행 경로로 쓰는 프로그램:'
    foreach ($p in $left) { Write-Host ('      - ' + (Friendly $p) + ' (pid ' + $p.ProcessId + ')') }
}
Write-Host ''
Write-Host '   탐색기 창이나 명령 창이 이 폴더를 열어 두고 있을 수 있습니다 - 그 창을 닫고 다시 실행하세요.'
Write-Host '   이 폴더의 파일을 Excel·메모장 등으로 열어 두었다면 닫으세요. 백신 검사 중이면 잠시 뒤 다시 실행하세요.'
if (-not (Test-Path -LiteralPath $Root -PathType Container) -and (Test-Path -LiteralPath $probe -PathType Container)) {
    Write-Host ''
    Say ('   [알림] 폴더 이름이 임시 이름으로 바뀌어 있습니다: ' + $probe) 'Yellow'
}
Write-Host ''
Say '   [미완료] 위 원인을 정리한 뒤 다시 실행하세요.' 'Red'
Hold-Window $false
exit 1
