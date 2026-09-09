# Start-ActivitySampler.ps1
# Samples foreground window / running solver processes / idle time at a fixed interval.
# Output: ..\data\activity\activity_YYYYMMDD.csv  (append, UTF-8)
# Usage:
#   .\Start-ActivitySampler.ps1                 # run forever (등록: collect\Register-Samplers.ps1 - 로그온 시 자동 시작, 실행 시간 제한 없음)
#   .\Start-ActivitySampler.ps1 -TestSamples 3  # smoke test: 3 samples then exit
# 같은 사용자 세션에 이미 한 인스턴스가 돌고 있으면 새 인스턴스는 바로 끝난다(뮤텍스) - UI/run.py 가
# '샘플러 멈춤' 을 보고 재기동해도 두 겹으로 돌지 않는다.
param(
    [int]$IntervalSec = 0,       # 0 = use config value (없거나 0 이면 60)
    [int]$TestSamples = 0,       # >0 = take N samples then exit (short interval)
    [int]$DurationMin = 0        # >0 = stop after N minutes
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
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
        $mutex = New-Object System.Threading.Mutex($true, 'Local\LoadMonitor25-ActivitySampler', [ref]$created)
        if (-not $created) {
            Write-Host '[sampler] already running in this session - exit (single instance)'
            exit 0
        }
    } catch { $mutex = $null }
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class LMWinApi {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LMWinApi.LASTINPUTINFO plii);
}
"@

function ConvertTo-IdleSeconds([int64]$tick, [int64]$lastInput) {
    # TickCount(int32) 는 가동 24.9일에 음수로 랩되고 dwTime 은 uint32 - 둘 다 GetTickCount 의 하위 32비트이므로
    # 2^32 모듈로 차이가 정답이다. 예전 `Max(0, TickCount - dwTime)` 은 가동 24.9~49.7일(74.5~99.4일…) 동안
    # 항상 0 → 점심·이석·야간까지 '활동' 으로 계상됐다(감사 A1). 빠른 시작 PC 는 종료해도 TickCount 가 이어진다.
    $diff = $tick - $lastInput
    $diff = (($diff % 4294967296) + 4294967296) % 4294967296
    return $diff / 1000.0
}

function Get-IdleSeconds {
    $lii = New-Object LMWinApi+LASTINPUTINFO
    $lii.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($lii)
    [void][LMWinApi]::GetLastInputInfo([ref]$lii)
    return ConvertTo-IdleSeconds ([int64][Environment]::TickCount) ([int64]$lii.dwTime)
}

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}

# config 에 solverProcesses 가 없어도 죽지 않는다 - null 을 그대로 돌리면 시작 즉시 죽는다(검증 확정).
# v22.1 부터 배포 config 에 기본 목록이 들어 있다(core\programs.py 의 SOLVER_HINTS 와 같은 목록).
$solverNames = @()
try { $solverNames = @(@($cfg.solverProcesses) | Where-Object { $_ } | ForEach-Object { $_.ToString().ToLower() }) } catch { $solverNames = @() }
# 앞부분 일치가 잘못 잡는 것을 뺀다 - 'ansys' 는 라이선스 대리자 ansysli_client 까지 잡는데 그것은 로그온 내내
# 떠 있어서, 빼지 않으면 solvers_running 이 늘 참이 되어 '해석을 하루 종일 돌렸다' 가 된다.
$solverSkip = @()
try { $solverSkip = @(@($cfg.solverProcessesExclude) | Where-Object { $_ } | ForEach-Object { $_.ToString().ToLower() }) } catch { $solverSkip = @() }
$outDir = Join-Path $root 'data\activity'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

$deadline = if ($DurationMin -gt 0) { (Get-Date).AddMinutes($DurationMin) } else { [datetime]::MaxValue }
$taken = 0
Write-Host ("[sampler] interval={0}s testSamples={1} out={2} pid={3} uptime={4:N1}d" -f $IntervalSec, $TestSamples, $outDir, $PID, ([Environment]::TickCount64 / 86400000.0))

while ((Get-Date) -lt $deadline) {
    try {
        $now = Get-Date
        # test samples go to a separate file so they never pollute real data
        $prefix = 'activity'
        if ($TestSamples -gt 0) { $prefix = 'test_activity' }
        # 폴더가 사라졌을 수 있다 - [추가 PC 취합]이 datactivity 를 통째로 보관 폴더로 옮긴다.
        # 루프 밖에서 한 번만 만들면 그 뒤로는 살아서 한 줄도 못 쓰는 좀비가 된다(실측). 매 틱 확인한다.
        if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
        $file = Join-Path $outDir ("{0}_{1}.csv" -f $prefix, $now.ToString('yyyyMMdd'))
        if (-not (Test-Path $file)) {
            [System.IO.File]::AppendAllText($file, "time,process,title,idle_sec,solvers_running,user,host`r`n", [System.Text.Encoding]::UTF8)
        }

        $hwnd = [LMWinApi]::GetForegroundWindow()
        $procName = ''
        $title = ''
        if ($hwnd -ne [IntPtr]::Zero) {
            $procId = 0
            [void][LMWinApi]::GetWindowThreadProcessId($hwnd, [ref]$procId)
            try { $procName = (Get-Process -Id $procId -ErrorAction Stop).ProcessName.ToLower() } catch { $procName = '' }
            if ($storeTitle) {
                $sb = New-Object System.Text.StringBuilder 512
                [void][LMWinApi]::GetWindowText($hwnd, $sb, $sb.Capacity)
                $title = $sb.ToString()
            }
        }

        $running = Get-Process | Select-Object -ExpandProperty ProcessName -Unique | ForEach-Object { $_.ToLower() }
        $solvers = @($running | Where-Object {
            $n = $_
            if (($solverSkip | Where-Object { $n -like ($_ + '*') }).Count -gt 0) { return $false }
            ($solverNames | Where-Object { $n -like ($_ + '*') }).Count -gt 0
        })
        $idle = [math]::Round((Get-IdleSeconds), 0)

        $line = ('{0},{1},{2},{3},{4},{5},{6}' -f `
            $now.ToString('yyyy-MM-dd HH:mm:ss'), (Csv-Escape $procName), (Csv-Escape $title), `
            $idle, (Csv-Escape ($solvers -join ';')), (Csv-Escape $env:USERNAME), (Csv-Escape $env:COMPUTERNAME))
        [System.IO.File]::AppendAllText($file, $line + "`r`n", [System.Text.Encoding]::UTF8)

        $taken++
        if ($TestSamples -gt 0) {
            Write-Host ("[sample {0}] proc={1} idle={2}s solvers={3}" -f $taken, $procName, $idle, ($solvers -join ';'))
            if ($taken -ge $TestSamples) { break }
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
