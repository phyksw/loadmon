# Start-ActivitySampler.ps1
# Samples foreground window / running solver processes / idle time at a fixed interval.
# Output: ..\data\activity\activity_YYYYMMDD.csv  (append, UTF-8)
#           time,process,title,idle_sec,solvers_running,user,host,gap_s,sess,solver_cpu_s
#           (LM28 에서 끝에 세 열을 더했다 - 읽는 쪽은 열 이름으로 읽으므로 옛 7열 파일과 섞여도 된다)
#           gap_s        = 직전 샘플과의 실제 간격(초). 이 프로세스의 첫 샘플은 '' - config 간격 가정 대신 실측 간격으로 계상
#           sess         = locked(전경이 LockApp/LogonUI 이거나 이 세션에 LogonUI 가 떠 있음) | WTS ConnectState 원값
#                          (active·connected·disconnected·idle … 소문자, 못 읽으면 '') - OS 판마다 다를 수 있어 원값만 남기고 해석은 분석 쪽
#           solver_cpu_s = 솔버 프로세스들의 CPU 시간(TotalProcessorTime) 직전 샘플 대비 증가분(초). 첫 샘플은 ''
#                          - '떠 있기만 한' 라이선스 대리자와 실제로 계산하는 솔버를 가르는 근거(C-28)
#         ..\data\activity\sampler_status.json  (상태 - UTF-8, BOM 이 붙을 수 있다 → 읽는 쪽은 utf-8-sig)
#           샘플러: ok · reason(R-CLM 제한 언어 모드 | R-ADDTYPE Add-Type 거부·AppLocker) · lang · pid · interval_s ·
#                   started · heartbeat(매 틱, 로컬 'yyyy-MM-dd HH:mm:ss') · samples · failed_at · error
#           Register-Samplers.ps1: registered · task · at  - 샘플러는 이 키를 지우지 않는다(읽어서 합친 뒤 쓴다)
# 외부 프로세스는 띄우지 않는다(매 틱 Get-Process·Win32 API 만). Add-Type 컴파일은 시작할 때 1회.
# Usage:
#   .\Start-ActivitySampler.ps1                 # run forever (등록: collect\Register-Samplers.ps1 - 로그온 시 자동 시작, 실행 시간 제한 없음)
#   .\Start-ActivitySampler.ps1 -TestSamples 3  # smoke test: 3 samples then exit (상태 파일에는 실패만 남긴다)
# 같은 사용자 세션에 이미 한 인스턴스가 돌고 있으면 새 인스턴스는 바로 끝난다(뮤텍스) - UI/run.py 가
# '샘플러 멈춤' 을 보고 재기동해도 두 겹으로 돌지 않는다.
param(
    [int]$IntervalSec = 0,       # 0 = use config value (없거나 0 이면 60)
    [int]$TestSamples = 0,       # >0 = take N samples then exit (short interval)
    [int]$DurationMin = 0,       # >0 = stop after N minutes
    [string]$OutDir = '',        # 출력 폴더 대체 (기본 ..\data\activity) - 시험용
    [switch]$LibOnly             # 함수만 정의하고 돌아간다 - Register-Samplers.ps1·tests\ps 가 dot-source 해서 쓴다
)

# ───────────────────────── 함수 (부작용 없음 - -LibOnly 로 dot-source 해도 아무것도 쓰지 않는다) ─────────────────────────

function Get-ActivityHeader { return 'time,process,title,idle_sec,solvers_running,user,host,gap_s,sess,solver_cpu_s' }

function ConvertTo-IdleSeconds([int64]$tick, [int64]$lastInput) {
    # TickCount(int32) 는 가동 24.9일에 음수로 랩되고 dwTime 은 uint32 - 둘 다 GetTickCount 의 하위 32비트이므로
    # 2^32 모듈로 차이가 정답이다. 예전 `Max(0, TickCount - dwTime)` 은 가동 24.9~49.7일(74.5~99.4일…) 동안
    # 항상 0 → 점심·이석·야간까지 '활동' 으로 계상됐다(감사 A1). 빠른 시작 PC 는 종료해도 TickCount 가 이어진다.
    $diff = $tick - $lastInput
    $diff = (($diff % 4294967296) + 4294967296) % 4294967296
    return $diff / 1000.0
}

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}

function Format-Num($v, [string]$fmt = '0.#') {
    # 지역 설정이 소수점을 ',' 로 쓰는 PC 에서 CSV 열이 밀리지 않게 숫자는 늘 InvariantCulture 로 쓴다
    if ($null -eq $v -or '' -eq $v) { return '' }
    return ([double]$v).ToString($fmt, [System.Globalization.CultureInfo]::InvariantCulture)
}

function Test-SolverName([string]$n, $names, $skip) {
    # 앞부분 일치 - 단 solverProcessesExclude(라이선스 대리자 등)에 걸리면 솔버가 아니다
    if (-not $n) { return $false }
    foreach ($s in @($skip)) { if ($s -and $n -like ($s + '*')) { return $false } }
    foreach ($s in @($names)) { if ($s -and $n -like ($s + '*')) { return $true } }
    return $false
}

function Get-WtsStateName([int]$v) {
    # WTS_CONNECTSTATE_CLASS 원값 → 소문자 이름. 모르는 값은 숫자 그대로, 못 읽음(-1)은 ''
    $names = @('active', 'connected', 'connectquery', 'shadow', 'disconnected', 'idle', 'listen', 'reset', 'down', 'init')
    if ($v -lt 0) { return '' }
    if ($v -lt $names.Count) { return $names[$v] }
    return [string]$v
}

function Get-SessState([string]$fgProc, $sessProcs, [int]$wts) {
    # 잠금 판정(C-24): 잠금 화면(LockApp)·자격 증명 화면(LogonUI)이 전경이거나, 이 세션에 LogonUI 가 떠 있으면 locked.
    # (잠긴 동안 GetForegroundWindow 는 대개 0 을 돌려 전경 이름이 비므로 LogonUI 존재도 본다. LockApp 은 풀린 뒤에도
    #  일시 중지 상태로 남는 판이 있어 존재만으로는 보지 않는다.) 그 밖은 WTS ConnectState 원값.
    $fg = ([string]$fgProc).ToLower()
    if ($fg -eq 'lockapp' -or $fg -eq 'logonui') { return 'locked' }
    foreach ($n in @($sessProcs)) { if (([string]$n).ToLower() -eq 'logonui') { return 'locked' } }
    return (Get-WtsStateName $wts)
}

function Get-SolverCpuDelta($prev, $now, $prevTime) {
    # 솔버 CPU 시간 차분(C-28) - $prev: 직전 틱 {pid → CPU 초}(첫 틱은 $null) · $now: [{id; cpu; start}] · $prevTime: 직전 틱 시각
    # → @{ delta = 초(첫 틱은 $null); next = 이번 틱 {pid → CPU 초} }
    # 직전에 없던 pid 는 직전 틱 뒤에 뜬 솔버로 보고 그동안 쓴 CPU 를 모두 센다(시작 시각이 직전 틱보다 앞이면 0 - 기준 없음).
    $next = @{}
    foreach ($p in @($now)) { if ($null -ne $p -and $null -ne $p.cpu) { $next[[int]$p.id] = [double]$p.cpu } }
    if ($null -eq $prev) { return @{ delta = $null; next = $next } }
    $sum = 0.0
    foreach ($p in @($now)) {
        if ($null -eq $p -or $null -eq $p.cpu) { continue }
        $id = [int]$p.id
        if ($prev.ContainsKey($id)) {
            $d = [double]$p.cpu - [double]$prev[$id]
            if ($d -gt 0) { $sum += $d }            # pid 재사용(줄어듦)은 0
        } elseif ($null -eq $p.start -or $null -eq $prevTime -or $p.start -ge $prevTime) {
            $sum += [double]$p.cpu
        }
    }
    return @{ delta = [math]::Round($sum, 1); next = $next }
}

function Read-SamplerStatus([string]$dir) {
    # sampler_status.json → 해시테이블(없거나 깨졌으면 빈 해시테이블)
    $h = @{}
    $p = Join-Path $dir 'sampler_status.json'
    try {
        if (Test-Path -LiteralPath $p) {
            $j = Get-Content -Raw -Encoding UTF8 -LiteralPath $p | ConvertFrom-Json
            foreach ($pr in $j.PSObject.Properties) { $h[$pr.Name] = $pr.Value }
        }
    } catch {}
    return $h
}

function Write-SamplerStatus([string]$dir, $fields) {
    # 읽어서 합친 뒤 임시 파일 → 교체(읽는 쪽이 반쪽 JSON 을 보지 않게). 제한 언어 모드에서도 돌도록 cmdlet 만 쓴다.
    # 샘플러(heartbeat)와 Register-Samplers(registered)가 같은 파일을 쓰므로 남의 키는 지우지 않는다.
    $doc = Read-SamplerStatus $dir
    foreach ($k in @($fields.Keys)) { $doc[$k] = $fields[$k] }
    $p = Join-Path $dir 'sampler_status.json'
    $tmp = $p + '.' + $PID + '.tmp'
    try {
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        Set-Content -LiteralPath $tmp -Value ($doc | ConvertTo-Json -Depth 4) -Encoding UTF8
        Move-Item -LiteralPath $tmp -Destination $p -Force
        return $true
    } catch {
        # 읽는 쪽이 잡고 있어 교체가 막힌 순간 - 다음 틱에 다시 쓴다. 임시 파일은 남기지 않는다
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        return $false
    }
}

function Update-ActivityHeader([string]$file, [string]$header) {
    # 같은 날 옛 7열 머리말 파일에 10열 행을 덧붙이면 읽는 쪽(core\extract._read)이 '열이 남는 행' 으로 버린다 -
    # 머리말 한 줄만 새 것으로 바꾼다(옛 행은 열이 모자라 빈칸으로 읽힌다). 바꾸지 못하면 $false → 그 파일엔 옛 7열로 쓴다.
    try {
        $lines = [System.IO.File]::ReadAllLines($file, [System.Text.Encoding]::UTF8)
        if ($lines.Count -eq 0) { return $false }
        $h0 = $lines[0].TrimStart([char]0xFEFF)
        if ($h0 -eq $header) { return $true }
        if ($h0 -notlike 'time,process,*') { return $false }       # 모르는 머리말 - 손대지 않는다
        $lines[0] = $header
        $tmp = $file + '.hdr.tmp'
        [System.IO.File]::WriteAllLines($tmp, $lines, [System.Text.Encoding]::UTF8)
        Move-Item -LiteralPath $tmp -Destination $file -Force
        return $true
    } catch { return $false }
}

if ($LibOnly) { return }

# ───────────────────────── 본체 ─────────────────────────
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = if ($OutDir) { $OutDir } else { Join-Path (Join-Path $root 'data') 'activity' }
$isTest = ($TestSamples -gt 0)

# 제한 언어 모드(C-22) - Add-Type·.NET 호출이 막혀 루프 전에 죽고 로그도 안 남던 것. 이유를 상태 파일에 남기고 끝낸다.
$lang = [string]$ExecutionContext.SessionState.LanguageMode
if ($lang -ne 'FullLanguage') {
    # 이 블록은 제한 언어 모드에서 돈다 - .NET 메서드·형 변환 없이 cmdlet 만 쓴다
    $null = Write-SamplerStatus $outDir @{ ok = $false; reason = 'R-CLM'; lang = $lang; pid = $PID; failed_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); error = '' }
    Write-Host ('[sampler] 중단(R-CLM): PowerShell 이 제한 언어 모드(' + $lang + ')라 창 샘플러를 돌릴 수 없습니다 - 보안 정책(AppLocker·WDAC) 확인 필요. 기록: sampler_status.json')
    exit 3
}

# config 가 없거나 깨져도 샘플러는 죽지 않는다 - 기본값(60초·제목 저장)으로 돈다
$cfg = $null
try { $cfg = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json } catch { Write-Host ('[sampler] config.json 읽기 실패 - 기본값 사용: ' + $_.Exception.Message) }
if ($IntervalSec -le 0) { try { $IntervalSec = [int]$cfg.samplerIntervalSec } catch { $IntervalSec = 0 } }
# samplerIntervalSec 이 0·누락·음수면 Start-Sleep 0 → 초당 수십 행을 쓰며 CPU 를 먹는 무한 루프가 된다(감사 A38) → 60초
if ($IntervalSec -le 0) { $IntervalSec = 60 }
if ($TestSamples -gt 0) { $IntervalSec = 2 }
elseif ($IntervalSec -lt 5) { Write-Host ("[sampler] interval {0}s 는 너무 짧아 5s 로 올립니다" -f $IntervalSec); $IntervalSec = 5 }
$storeTitle = $true
try { if ($null -ne $cfg -and $null -ne $cfg.storeWindowTitle) { $storeTitle = [bool]$cfg.storeWindowTitle } } catch {}

# 단일 인스턴스 - 작업 스케줄러(IgnoreNew)와 별개로, 수동 실행·UI 재기동이 겹쳐도 한 개만 남는다. 테스트 실행은 예외.
$mutex = $null
if ($TestSamples -le 0) {
    try {
        $created = $false
        # 뮤텍스 이름에 판(LM28)과 폴더 해시를 넣는다 - LM24 샘플러·다른 폴더의 LM28 샘플러가 돌아도 이 폴더 샘플러는 뜬다
        . (Join-Path $root 'collect\LmName.ps1')
        $mutex = New-Object System.Threading.Mutex($true, (Get-LmNames $root).MutexActivity, [ref]$created)
        if (-not $created) {
            Write-Host '[sampler] already running in this session - exit (single instance)'
            exit 0
        }
    } catch { $mutex = $null }
}

# Win32 API - AppLocker·보안 정책이 컴파일(csc)을 막으면 여기서 실패한다(C-22: R-ADDTYPE 로 남긴다)
try {
    if (-not ('LM28WinApi' -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class LM28WinApi {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LM28WinApi.LASTINPUTINFO plii);
    [DllImport("wtsapi32.dll", SetLastError=true)] static extern bool WTSQuerySessionInformationW(IntPtr hServer, int sessionId, int infoClass, out IntPtr buffer, out int bytes);
    [DllImport("wtsapi32.dll")] static extern void WTSFreeMemory(IntPtr memory);
    // WTSConnectState(8) - 이 세션(WTS_CURRENT_SESSION = -1)의 연결 상태 원값(0 Active … 4 Disconnected …). 못 읽으면 -1
    public static int ConnectState() {
        IntPtr buf; int n;
        if (!WTSQuerySessionInformationW(IntPtr.Zero, -1, 8, out buf, out n)) return -1;
        try { return (buf != IntPtr.Zero && n >= 4) ? Marshal.ReadInt32(buf) : -1; }
        finally { if (buf != IntPtr.Zero) WTSFreeMemory(buf); }
    }
}
"@
    }
} catch {
    $em = $_.Exception.Message.Split([char]10)[0].Trim()
    [void](Write-SamplerStatus $outDir @{ ok = $false; reason = 'R-ADDTYPE'; lang = $lang; pid = $PID; failed_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); error = $em })
    Write-Host ('[sampler] 중단(R-ADDTYPE): Win32 API 를 불러오지 못했습니다(Add-Type 거부 - AppLocker 등): ' + $em)
    if ($mutex) { try { $mutex.ReleaseMutex(); $mutex.Dispose() } catch {} }
    exit 3
}

function Get-IdleSeconds {
    $lii = New-Object LM28WinApi+LASTINPUTINFO
    $lii.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($lii)
    [void][LM28WinApi]::GetLastInputInfo([ref]$lii)
    return ConvertTo-IdleSeconds ([int64][Environment]::TickCount) ([int64]$lii.dwTime)
}

# config 에 solverProcesses 가 없어도 죽지 않는다 - null 을 그대로 돌리면 시작 즉시 죽는다(검증 확정).
# v22.1 부터 배포 config 에 기본 목록이 들어 있다(core\programs.py 의 SOLVER_HINTS 와 같은 목록).
$solverNames = @()
try { $solverNames = @(@($cfg.solverProcesses) | Where-Object { $_ } | ForEach-Object { $_.ToString().ToLower() }) } catch { $solverNames = @() }
# 앞부분 일치가 잘못 잡는 것을 뺀다 - 'ansys' 는 라이선스 대리자 ansysli_client 까지 잡는데 그것은 로그온 내내
# 떠 있어서, 빼지 않으면 solvers_running 이 늘 참이 되어 '해석을 하루 종일 돌렸다' 가 된다.
$solverSkip = @()
try { $solverSkip = @(@($cfg.solverProcessesExclude) | Where-Object { $_ } | ForEach-Object { $_.ToString().ToLower() }) } catch { $solverSkip = @() }
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

$deadline = if ($DurationMin -gt 0) { (Get-Date).AddMinutes($DurationMin) } else { [datetime]::MaxValue }
$taken = 0
$hdr = Get-ActivityHeader
$wide = @{}              # 파일 → 새 머리말(10열)인가
$prevT = $null           # 직전 샘플 시각(gap_s)
$cpuPrev = $null         # 직전 틱 솔버 CPU {pid → 초}
$mySess = -1
try { $mySess = [System.Diagnostics.Process]::GetCurrentProcess().SessionId } catch {}
Write-Host ("[sampler] interval={0}s testSamples={1} out={2} pid={3} uptime={4:N1}d" -f $IntervalSec, $TestSamples, $outDir, $PID, ([Environment]::TickCount64 / 86400000.0))
if (-not $isTest) {
    $t0s = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    [void](Write-SamplerStatus $outDir @{ ok = $true; reason = ''; error = ''; failed_at = ''; lang = $lang; pid = $PID; interval_s = $IntervalSec; started = $t0s; heartbeat = $t0s; samples = 0 })
}

while ((Get-Date) -lt $deadline) {
    try {
        $now = Get-Date
        # test samples go to a separate file so they never pollute real data
        $prefix = 'activity'
        if ($TestSamples -gt 0) { $prefix = 'test_activity' }
        # 폴더가 사라졌을 수 있다 - [추가 PC 취합]이 data 아래 activity 폴더를 통째로 보관 폴더로 옮긴다.
        # 루프 밖에서 한 번만 만들면 그 뒤로는 살아서 한 줄도 못 쓰는 좀비가 된다(실측). 매 틱 확인한다.
        if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
        $file = Join-Path $outDir ("{0}_{1}.csv" -f $prefix, $now.ToString('yyyyMMdd'))
        if (-not (Test-Path $file)) {
            [System.IO.File]::AppendAllText($file, $hdr + "`r`n", [System.Text.Encoding]::UTF8)
            $wide[$file] = $true
        } elseif (-not $wide.ContainsKey($file)) {
            $wide[$file] = Update-ActivityHeader $file $hdr
        }

        $hwnd = [LM28WinApi]::GetForegroundWindow()
        $procName = ''
        $title = ''
        if ($hwnd -ne [IntPtr]::Zero) {
            $procId = 0
            [void][LM28WinApi]::GetWindowThreadProcessId($hwnd, [ref]$procId)
            try { $procName = (Get-Process -Id $procId -ErrorAction Stop).ProcessName.ToLower() } catch { $procName = '' }
            if ($storeTitle) {
                $sb = New-Object System.Text.StringBuilder 512
                [void][LM28WinApi]::GetWindowText($hwnd, $sb, $sb.Capacity)
                $title = $sb.ToString()
            }
        }

        $procs = @(Get-Process)
        $running = @($procs | ForEach-Object { $_.ProcessName.ToLower() } | Select-Object -Unique)
        $solvers = @($running | Where-Object { Test-SolverName $_ $solverNames $solverSkip })
        $idle = [math]::Round((Get-IdleSeconds), 0)

        # 솔버 CPU 차분 - 떠 있는 것만으로는 계산 중인지 모른다(라이선스 대리자·대기 중 솔버)
        $cpuNow = New-Object System.Collections.Generic.List[object]
        if ($solvers.Count -gt 0) {
            foreach ($p in $procs) {
                if (-not (Test-SolverName $p.ProcessName.ToLower() $solverNames $solverSkip)) { continue }
                $c = $null; $st = $null
                try { $c = $p.TotalProcessorTime.TotalSeconds } catch {}      # 관리자 권한으로 뜬 솔버는 못 읽을 수 있다
                try { $st = $p.StartTime } catch {}
                $cpuNow.Add(@{ id = $p.Id; cpu = $c; start = $st })
            }
        }
        $cd = Get-SolverCpuDelta $cpuPrev $cpuNow.ToArray() $prevT
        $cpuPrev = $cd.next
        # 세션 상태 - 잠금·RDP 끊김을 idle 추정과 따로 남긴다(C-24)
        $logon = @($procs | Where-Object { $_.ProcessName -eq 'LogonUI' -and $_.SessionId -eq $mySess } | ForEach-Object { $_.ProcessName })
        $wts = -1
        try { $wts = [LM28WinApi]::ConnectState() } catch { $wts = -1 }
        $sess = Get-SessState $procName $logon $wts
        $gapS = if ($null -ne $prevT) { Format-Num ($now - $prevT).TotalSeconds '0' } else { '' }
        $cpuS = Format-Num $cd.delta
        $prevT = $now

        $cols = @($now.ToString('yyyy-MM-dd HH:mm:ss'), (Csv-Escape $procName), (Csv-Escape $title), (Format-Num $idle '0'),
                  (Csv-Escape ($solvers -join ';')), (Csv-Escape $env:USERNAME), (Csv-Escape $env:COMPUTERNAME))
        if ($wide[$file]) { $cols += @($gapS, $sess, $cpuS) }
        [System.IO.File]::AppendAllText($file, ($cols -join ',') + "`r`n", [System.Text.Encoding]::UTF8)

        $taken++
        if ($TestSamples -gt 0) {
            Write-Host ("[sample {0}] proc={1} idle={2}s solvers={3} sess={4} gap={5} solver_cpu={6}" -f $taken, $procName, $idle, ($solvers -join ';'), $sess, $gapS, $cpuS)
            if ($taken -ge $TestSamples) { break }
        } else {
            # heartbeat - 대시보드·run.py 가 CSV 시각과 별개로 '살아 있음' 을 본다(Register-Samplers 는 최대 20초 이것만 확인)
            [void](Write-SamplerStatus $outDir @{ ok = $true; reason = ''; heartbeat = $now.ToString('yyyy-MM-dd HH:mm:ss'); pid = $PID; interval_s = $IntervalSec; samples = $taken })
        }
    } catch {
        # never die inside the loop; log and continue
        try {
            $elog = Join-Path $outDir 'sampler_errors.log'
            Add-Content -Path $elog -Value ("{0} {1}" -f (Get-Date -Format s), $_.Exception.Message)
        } catch {}
    }
    Start-Sleep -Seconds $IntervalSec
}
if ($mutex) { try { $mutex.ReleaseMutex(); $mutex.Dispose() } catch {} }
Write-Host ("[sampler] done. samples={0}" -f $taken)
