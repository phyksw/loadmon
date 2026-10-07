# Start-TeamsSampler.ps1 - 팀즈 채팅 상시 수집기 (Copilot 팀즈 조회가 막힌 계정용)
# 회사 Copilot 에 Teams 데이터 커넥터가 없으면(실측: "연결된 Microsoft Teams 데이터 조회
# 도구가 없어…") 과거 이력을 일괄로 가져올 방법이 없다. 대신 이 샘플러를 켜두면
# 화면에 열린 대화가 주기적으로 읽혀 data\m365\teams_window.csv 에 **중복 없이 누적**된다 -
# 쓰는 동안 자연스럽게 팀즈 이력이 쌓이는 방식이다(창 샘플러와 같은 원리).
#
# 사용:  powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File collect\Start-TeamsSampler.ps1
# 상시:  사용자가 등록할 때만(LoadMonitor28-샘플러등록.bat · 대시보드 단추 — 동의 없이 예약 작업을 만들지 않는다). 읽기 전용·네트워크 미사용.
# LM28(C-20):
#  · Get-TeamsWindow.ps1 을 **한 번만** 점 소싱하고 루프에서 Invoke-TeamsWindowRead 를 부른다 — 예전에는 주기마다
#    powershell 을 새로 띄웠다(이 PC 처럼 끝난 프로세스가 남는 환경에서는 그대로 쌓인다). 매 주기 끝에 [GC]::Collect().
#  · 단일 인스턴스: 뮤텍스 Local\LM28-TeamsSampler-<폴더해시6>(collect\LmName.ps1) — LM24 샘플러와 겹치지 않는다.
#  · 주기마다 rc(0 새 줄 · 4 새 줄 0 · 1 팀즈 없음 · 3 읽을 창 없음)와 요약 한 줄을 남긴다(실패를 숨기지 않는다).
param(
    [int]$IntervalSec = 300,      # 5분 주기 - 대화 전환 속도 대비 충분, 부하는 무시 수준
    [double]$MaxHours = 0,        # 0 = 무한 (테스트용으로 소수 시간 제한 가능)
    [int]$MaxLoops = 0,           # 0 = 무한 (시험은 1)
    [hashtable]$ReadArgs = $null  # 시험 주입: Invoke-TeamsWindowRead 에 더 넘길 인자(창 주입·출력 폴더 등) - 주면 시험용 뮤텍스 이름
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$lmRoot = Split-Path -Parent $here
$reader = Join-Path $here 'Get-TeamsWindow.ps1'
if (-not (Test-Path $reader)) { Write-Host '[teams-sampler] Get-TeamsWindow.ps1 이 없습니다'; exit 1 }

# 단일 인스턴스 - 같은 폴더의 팀즈 샘플러가 이미 돌면 조용히 끝낸다
. (Join-Path $here 'LmName.ps1')
$mxName = (Get-LmNames $lmRoot).MutexTeams
if ($ReadArgs) { $mxName += '-test' }
$mutex = $null; $created = $true
try { $mutex = New-Object System.Threading.Mutex($true, $mxName, [ref]$created) } catch { $mutex = $null; $created = $true }
if (-not $created) {
    Write-Host '[teams-sampler] 이미 실행 중 - 종료(단일 인스턴스)'
    if ($mutex) { $mutex.Dispose() }
    exit 0
}

. $reader          # 함수만 정의된다(직접 실행 가드) - 이후 주기마다 프로세스를 띄우지 않는다
$ra = @{ Root = $lmRoot; Quiet = $true }
if ($ReadArgs) { foreach ($k in $ReadArgs.Keys) { $ra[$k] = $ReadArgs[$k] } }

Write-Host ("[teams-sampler] 시작 - {0}초 주기로 열린 팀즈 대화를 누적 수집합니다 (Ctrl+C 종료)" -f $IntervalSec)
$t0 = Get-Date
$loops = 0
try {
    while ($true) {
        if ($MaxHours -gt 0 -and ((Get-Date) - $t0).TotalHours -ge $MaxHours) { break }
        try {
            # 창이 없거나 트레이면 rc 1·3 - 샘플러는 그 사유만 남기고 다음 주기로
            $r = @(Invoke-TeamsWindowRead @ra)[-1]
            Write-Host ("[teams-sampler] {0:HH:mm} rc={1}{2} {3}" -f (Get-Date), $r.rc, $(if ($r.reason) { ' ' + $r.reason } else { '' }), $r.summary)
        } catch {
            Write-Host ("[teams-sampler] 이번 주기 실패: {0}" -f $_.Exception.Message)
        }
        $r = $null
        [GC]::Collect()    # 주기마다 UIA 요소·문자열을 놓아 준다(상주 프로세스의 메모리가 늘지 않게)
        $loops++
        if ($MaxLoops -gt 0 -and $loops -ge $MaxLoops) { break }
        Start-Sleep -Seconds $IntervalSec
    }
} finally {
    if ($mutex) { try { $mutex.ReleaseMutex() } catch {}; $mutex.Dispose() }
}
Write-Host '[teams-sampler] 종료'
