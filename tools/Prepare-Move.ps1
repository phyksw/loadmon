# Prepare-Move.ps1 - 이 폴더를 다른 PC 로 통째로 옮길 수 있게 '잡고 있는 것'을 놓아 준다.
#
# 왜 필요한가: 분석이 끝난 뒤 폴더를 옮기려 하면 "사용 중" 이라 옮겨지지 않는다.
# 잡고 있는 것은 대개 우리 자신이다 - 대시보드(python ui\app.py), 팀 서버(teamserver.py),
# Copilot 전용 Edge(data\copilot_profile), 상시 샘플러(powershell), 그리고 그 폴더를 열어 둔 탐색기.
#
# 중요: 이 스크립트는 %TEMP% 로 복사돼 실행된다. LoadMonitor 폴더 안에서 실행하면
# 스크립트 파일 자체가 폴더를 잡아 '옮길 수 있는가' 시험이 항상 실패한다.
#
# Usage:  powershell -ExecutionPolicy Bypass -File Prepare-Move.ps1 -Root "D:\...\LoadMonitor22"
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [switch]$NoWait,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
# 경로 정규화 — bat 가 "…\LoadMonitor22\." 처럼 넘겨도(끝 역슬래시가 닫는 따옴표를 삼키지 않게 붙이던 점)
# '\.'·'..'·끝 역슬래시를 지운 정규 경로로 만든다. 실사고: '…\.' 그대로 Split-Path 하면 부모가 폴더 자신이 되어
# 폴더를 '_이동확인_임시' 로 바꿔 놓고 되돌리지 못한 채, 빈 껍데기 LoadMonitor22\report\move_ready.txt 만 만들었다.
if ($Root -match '^[A-Za-z]:$') { $Root += '\' }          # 'D:' 는 '그 드라이브의 현재 폴더' 라 뜻이 달라진다
try {
    if (-not [System.IO.Path]::IsPathRooted($Root)) { $Root = Join-Path (Get-Location).Path $Root }
    $Root = [System.IO.Path]::GetFullPath($Root)
} catch {}
if ($Root.Length -gt 3) { $Root = $Root.TrimEnd('\') }     # 드라이브 루트('D:\')는 그대로
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { Write-Host "[이동준비] 폴더가 없습니다: $Root"; if (-not $NoWait) { pause }; exit 1 }
if ($Root -match '^[A-Za-z]:\\$') { Write-Host "[이동준비] 드라이브 루트($Root)는 이름을 바꿔 확인할 수 없습니다 - LoadMonitor22 를 하위 폴더에 두세요"; if (-not $NoWait) { pause }; exit 1 }
Set-Location ([System.IO.Path]::GetTempPath())     # 이 창이 폴더를 잡지 않게
# Set-Location 은 PowerShell 의 위치만 바꾸고 프로세스의 현재 폴더(Win32 cwd)는 그대로다 — bat(cd /d "%~dp0" 뒤 start)
# 나 대시보드(app.py 의 cwd)에서 띄우면 우리 프로세스 자신이 LoadMonitor22 안에 서 있어 이름 바꾸기 시험이
# "다른 프로세스가 사용 중" 으로 항상 실패했다(실측). 프로세스 cwd 도 TEMP 로 옮겨 손을 뗀다.
try { [Environment]::CurrentDirectory = [System.IO.Path]::GetTempPath() } catch {}

Write-Host ''
Write-Host '  [PC 이동 준비] 폴더를 잡고 있는 프로그램을 정리합니다'
Write-Host ("  대상: " + $Root)
Write-Host ''
if (-not $NoWait) { Start-Sleep -Milliseconds 800 }   # 우리를 띄운 bat/cmd 가 먼저 닫히도록

function Procs-Under([string]$root) {
    # 실행 파일이 이 폴더 안에 있거나(내장 파이썬), 명령줄이 이 폴더를 가리키는 프로세스
    $esc = [regex]::Escape($root)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath -match $esc) -or
        ($_.CommandLine -and $_.CommandLine -match $esc)
    }
}

$killed = New-Object System.Collections.Generic.List[string]
if (-not $CheckOnly) {
    # ① 우리 것부터 - 대시보드·팀 서버·수집기(python), 상시 샘플러(powershell)
    foreach ($p in Procs-Under $Root) {
        if ($p.ProcessId -eq $PID) { continue }
        $nm = $p.Name
        if ($nm -notmatch '^(python|pythonw|powershell|pwsh|cmd)\.exe$') { continue }
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            $killed.Add("$nm (pid $($p.ProcessId))")
        } catch {}
    }
    # ② Copilot 전용 Edge - 일반 Edge 는 건드리지 않는다
    Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*copilot_profile*' } | ForEach-Object {
            try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $killed.Add("msedge (Copilot 전용, pid $($_.ProcessId))") } catch {}
        }
    if ($killed.Count) {
        Write-Host ("  종료함: " + ($killed -join ', '))
    } else {
        Write-Host '  종료할 우리 프로그램이 없습니다 (이미 다 닫혀 있음)'
    }
    Start-Sleep -Milliseconds 700
}

# ③ 탐색기가 그 폴더를 열어 두면 옮길 수 없다 - 죽이지 않고 알려만 준다
$explorer = @()
try {
    $sh = New-Object -ComObject Shell.Application
    foreach ($w in $sh.Windows()) {
        try {
            $p = $w.Document.Folder.Self.Path
            if ($p -and $p.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) { $explorer += $p }
        } catch {}
    }
} catch {}
if ($explorer.Count) {
    Write-Host ''
    Write-Host '  [!] 탐색기가 이 폴더를 열어 두고 있습니다 - 그 창을 닫아 주세요:'
    foreach ($p in ($explorer | Select-Object -Unique)) { Write-Host ("      " + $p) }
}

# ④ 진짜 시험: 폴더 이름을 잠깐 바꿔 본다. 성공하면 옮길 수 있다는 뜻이다.
$parent = Split-Path -Parent $Root
$leaf = Split-Path -Leaf $Root
$probe = Join-Path $parent ($leaf + '_이동확인_임시')
$movable = $false
$restored = $false
$why = ''
try {
    Rename-Item -LiteralPath $Root -NewName ($leaf + '_이동확인_임시') -ErrorAction Stop
    $movable = $true
    # 되돌리기 — 백신·탐색기가 새 이름을 잠깐 잡을 수 있어 몇 번 더 시도한다
    $back = ''
    for ($i = 0; $i -lt 5 -and -not $restored; $i++) {
        if ($i) { Start-Sleep -Milliseconds 400 }
        try { Rename-Item -LiteralPath $probe -NewName $leaf -ErrorAction Stop; $restored = $true } catch { $back = $_.Exception.Message }
    }
    if (-not $restored) {
        # 사용자가 찾을 수 있게 '실제로 존재하는' 경로를 보여 준다(실사고: 없는 경로를 안내했다)
        $now = if (Test-Path -LiteralPath $probe) { $probe } else {
            $hit = @(Get-ChildItem -LiteralPath $parent -Directory -Filter ($leaf + '_이동확인_임시*') -ErrorAction SilentlyContinue | Select-Object -First 1)
            if ($hit.Count) { $hit[0].FullName } else { $probe }
        }
        Write-Host ''
        Write-Host '  [!] 이름을 되돌리지 못했습니다. 폴더가 지금 이 이름입니다:'
        Write-Host ("      " + $now)
        if ($back) { Write-Host ("      (사유: " + $back + ")") }
        Write-Host ("      직접 '" + $leaf + "' 로 이름을 바꾸거나, 그대로 옮기셔도 됩니다.")
    }
} catch {
    $why = $_.Exception.Message
}

Write-Host ''
if ($movable) {
    Write-Host '  ============================================================'
    Write-Host '   이제 이 폴더를 통째로 옮기거나 복사할 수 있습니다.'
    Write-Host '  ============================================================'
    Write-Host ''
    Write-Host '   · 다른 PC 로 옮긴 뒤 LoadMonitor22-UI.bat 을 실행하면'
    Write-Host '     지난 PC 의 수집 데이터는 자동으로 data\추가PC\ 로 보관되고'
    Write-Host '     분석은 두 PC 를 합쳐 계산합니다.'
    Write-Host '   · report\upload_pending\ 의 업로드 대기 묶음도 함께 따라갑니다.'
    try {
        # 기록은 '지금 실제로 있는' 폴더 안에만 쓴다 — 되돌리지 못했으면 아직 $probe 이름이다.
        # 없는 경로에 report\ 를 새로 만들면 빈 껍데기 폴더가 생겨 사용자가 그것을 옮긴다(실사고).
        $where = if ($restored) { $Root } else { $probe }
        if (Test-Path -LiteralPath $where -PathType Container) {
            $rep = Join-Path $where 'report'
            if (-not (Test-Path -LiteralPath $rep)) { New-Item -ItemType Directory -Force -Path $rep | Out-Null }
            $log = @("이동 준비 완료  " + (Get-Date).ToString('yyyy-MM-dd HH:mm'),
                     "종료한 프로그램: " + (($killed -join ', ')) ,
                     "폴더 이동 가능 확인: 예")
            [System.IO.File]::WriteAllLines((Join-Path $rep 'move_ready.txt'), $log, [System.Text.Encoding]::UTF8)
        }
    } catch {}
} else {
    Write-Host '  ============================================================'
    Write-Host '   아직 무언가가 이 폴더를 잡고 있습니다.'
    Write-Host '  ============================================================'
    Write-Host ("   사유: " + $why)
    Write-Host ''
    Write-Host '   흔한 원인과 조치:'
    Write-Host '   1) 탐색기에서 이 폴더(또는 하위 폴더)를 열어 두었다  -> 그 창을 닫으세요'
    Write-Host '   2) 이 폴더의 파일을 Excel·메모장 등으로 열어 두었다  -> 닫으세요'
    Write-Host '   3) 명령 프롬프트가 이 폴더에 들어가 있다             -> 그 창을 닫으세요'
    Write-Host '   4) 백신 검사가 진행 중이다                           -> 잠시 뒤 다시 실행'
    $left = @(Procs-Under $Root | Where-Object { $_.ProcessId -ne $PID } |
              ForEach-Object { $_.Name + ' (pid ' + $_.ProcessId + ')' } | Select-Object -Unique)
    if ($left.Count) {
        Write-Host ''
        Write-Host ('   아직 이 폴더를 쓰는 프로세스: ' + ($left -join ', '))
    }
}
Write-Host ''
if (-not $NoWait) { Write-Host '  창을 닫으려면 아무 키나 누르세요.'; $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') }
exit 0
