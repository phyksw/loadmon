# Start-TeamsSampler.ps1 - 팀즈 채팅 상시 수집기 (Copilot 팀즈 조회가 막힌 계정용)
# 회사 Copilot 에 Teams 데이터 커넥터가 없으면(실측: "연결된 Microsoft Teams 데이터 조회
# 도구가 없어…") 과거 이력을 일괄로 가져올 방법이 없다. 대신 이 샘플러를 켜두면
# 화면에 열린 대화가 주기적으로 읽혀 data\m365\teams_window.csv 에 **중복 없이 누적**된다 -
# 쓰는 동안 자연스럽게 팀즈 이력이 쌓이는 방식이다(창 샘플러와 같은 원리).
#
# 사용:  powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File collect\Start-TeamsSampler.ps1
# 상시:  로그온 시 자동 시작(설정가이드의 schtasks 예시 참고). 읽기 전용·네트워크 미사용.
param(
    [int]$IntervalSec = 300,      # 5분 주기 - 대화 전환 속도 대비 충분, 부하는 무시 수준
    [double]$MaxHours = 0         # 0 = 무한 (테스트용으로 소수 시간 제한 가능)
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$reader = Join-Path $here 'Get-TeamsWindow.ps1'
if (-not (Test-Path $reader)) { Write-Host '[teams-sampler] Get-TeamsWindow.ps1 이 없습니다'; exit 1 }

Write-Host ("[teams-sampler] 시작 - {0}초 주기로 열린 팀즈 대화를 누적 수집합니다 (Ctrl+C 종료)" -f $IntervalSec)
$t0 = Get-Date
while ($true) {
    if ($MaxHours -gt 0 -and ((Get-Date) - $t0).TotalHours -ge $MaxHours) { break }
    try {
        # 창이 없거나 트레이면 Get-TeamsWindow 가 exit 1 - 샘플러는 조용히 다음 주기로
        $o = & powershell -NoProfile -ExecutionPolicy Bypass -File $reader 2>&1
        $line = @($o | Where-Object { $_ -match '신규 \d+건' }) | Select-Object -Last 1
        if ($line) { Write-Host ("[teams-sampler] {0:HH:mm} {1}" -f (Get-Date), $line) }
    } catch {
        Write-Host ("[teams-sampler] 이번 주기 실패: {0}" -f $_.Exception.Message)
    }
    Start-Sleep -Seconds $IntervalSec
}
Write-Host '[teams-sampler] 종료'
