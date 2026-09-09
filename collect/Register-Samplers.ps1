# Register-Samplers.ps1 - 창 샘플러(·팀즈 샘플러)를 작업 스케줄러에 등록한다 (관리자 권한 불필요).
# 설정가이드의 `schtasks /Create /SC ONLOGON …` 한 줄은 기본 '3일 실행 제한(PT72H)' 을 그대로 물려받아
# 로그오프 없이 절전·잠금만 쓰는 사용자는 로그온 3일 뒤부터 다음 재부팅까지 샘플러가 조용히 멈췄다(감사 A26).
# 여기서는 XML 정의로 등록한다: ExecutionTimeLimit PT0S(무제한) · MultipleInstancesPolicy IgnoreNew(겹침 방지) ·
# RestartOnFailure 1분×99 · 배터리 제한 해제 · 로그온 트리거(이 사용자) · InteractiveToken(화면 창을 읽어야 하므로).
# Usage:
#   powershell -ExecutionPolicy Bypass -File collect\Register-Samplers.ps1            # 창 샘플러 등록 + 지금 시작
#   powershell -ExecutionPolicy Bypass -File collect\Register-Samplers.ps1 -Teams     # 팀즈 상시 샘플러도 함께
#   powershell -ExecutionPolicy Bypass -File collect\Register-Samplers.ps1 -Remove    # 등록 해제 (-Teams 로 팀즈 것도)
#   -NoStart: 등록만(다음 로그온부터)   -DryRun: 등록하지 않고 XML 정의를 스케줄러 파서로 검증만(진단용 · 파일은 남기지 않음)
param(
    [switch]$Teams,
    [switch]$Remove,
    [switch]$NoStart,
    [switch]$DryRun,
    [string]$TaskPrefix = 'LoadMonitor24'
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$here = Join-Path $root 'collect'

$userId = "$env:USERDOMAIN\$env:USERNAME"
$sid = ''
try { $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value } catch {}
if (-not $sid) { $sid = $userId }

function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }

function New-TaskXml([string]$taskName, [string]$script, [string]$desc) {
    # 작업 스케줄러 XML(v1.4) - 요소 순서는 스키마 순서(Settings 안 순서가 어긋나면 등록이 거부된다)
    $args = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '"'
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$(Esc $userId)</Author>
    <Description>$(Esc $desc)</Description>
    <URI>\$(Esc $taskName)</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$(Esc $userId)</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$(Esc $sid)</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>99</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>$(Esc $args)</Arguments>
      <WorkingDirectory>$(Esc $root)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

$jobs = @(@{ name = "$TaskPrefix-Sampler"; script = (Join-Path $here 'Start-ActivitySampler.ps1'); desc = 'LoadMonitor24 창 샘플러 - 로그온 시 자동 시작, 실행 시간 제한 없음 (1분마다 활성 창·무입력 시간을 로컬 CSV 에 기록)' })
if ($Teams) {
    $jobs += @{ name = "$TaskPrefix-TeamsSampler"; script = (Join-Path $here 'Start-TeamsSampler.ps1'); desc = 'LoadMonitor24 팀즈 상시 샘플러 - 로그온 시 자동 시작, 실행 시간 제한 없음 (열린 팀즈 대화를 5분마다 읽어 로컬 CSV 에 누적)' }
}

$svc = $null; $folder = $null
try { $svc = New-Object -ComObject 'Schedule.Service'; $svc.Connect(); $folder = $svc.GetFolder('\') }
catch { Write-Host ('[register] 작업 스케줄러 연결 실패: ' + $_.Exception.Message); if (-not $DryRun) { exit 1 } }

# 옛 버전 작업 정리 - 버전마다 작업 이름이 바뀌므로(LoadMonitor20-Sampler, LoadMonitor22-Sampler …)
# 새 폴더에서 등록만 하면 옛 작업이 **옛 폴더의 스크립트를 계속 돌린다**. 그러면 샘플러가 둘이 되어
# 같은 시각을 두 CSV 에 쓰고, 사용자는 옛 폴더를 지운 뒤에도 '왜 아직 도는지' 알 수 없다.
# 이름이 우리 것인 작업만 지운다(LoadMonitor<숫자>-Sampler / -TeamsSampler, 이번 버전 제외).
if (-not $DryRun -and $folder) {
    $mine = "^LoadMonitor\d+-(Teams)?Sampler$"
    foreach ($t in @($folder.GetTasks(1))) {          # 1 = 숨김 작업 포함
        $tn = [string]$t.Name
        if ($tn -notmatch $mine) { continue }
        if ($tn -like "$TaskPrefix-*") { continue }   # 이번 버전 것은 아래에서 갱신한다
        try { $folder.DeleteTask($tn, 0); Write-Host ("[register] 옛 버전 작업 해제: {0} (이 버전은 {1}-Sampler)" -f $tn, $TaskPrefix) }
        catch { Write-Host ("[register] 옛 버전 작업 {0} 을 지우지 못했습니다 - 작업 스케줄러에서 손으로 지우세요" -f $tn) }
    }
}

$fail = 0
foreach ($j in $jobs) {
    $name = [string]$j.name
    if ($Remove) {
        try { $folder.DeleteTask($name, 0); Write-Host ("[register] 해제: {0}" -f $name) }
        catch {
            # COM 이 못 지우면 schtasks 로 한 번 더 (없는 작업이면 그냥 알린다)
            # 2>&1 을 쓰면 $ErrorActionPreference='Stop' 아래에서 stderr 한 줄이 종료 오류로 던져져
            # 이 catch 안에서 그대로 죽는다(실측). stderr 는 잠시 Continue 로 낮춰 받는다.
            $o = & { $ErrorActionPreference = 'Continue'; & schtasks /Delete /TN $name /F 2>&1 }
            if ($LASTEXITCODE -eq 0) { Write-Host ("[register] 해제: {0}" -f $name) } else { Write-Host ("[register] {0}: 등록돼 있지 않음" -f $name) }
        }
        continue
    }
    if (-not (Test-Path -LiteralPath $j.script)) { Write-Host ("[register] 스크립트 없음: {0}" -f $j.script); $fail = 1; continue }
    $xml = New-TaskXml $name ([string]$j.script) ([string]$j.desc)
    # XML 파일은 schtasks 폴백에서만 잠깐 쓰고 바로 지운다 - 계정 SID·도메인\사용자·설치 경로가 든 파일을 %TEMP% 에
    # 남기지 않는다. 예전엔 먼저 써 두고 등록 뒤에 지워 -DryRun·검증 실패 경로가 파일을 남겼다(C5).
    $xmlPath = Join-Path $env:TEMP ("lm_task_{0}.xml" -f $name)
    try { if (Test-Path -LiteralPath $xmlPath) { Remove-Item -LiteralPath $xmlPath -Force -ErrorAction SilentlyContinue } } catch {}   # 옛 판이 남긴 것
    # 1) 정의 검증 - 등록 없이 스케줄러 파서에 통과시킨다(DryRun 은 여기서 끝)
    $def = $null
    try {
        if ($svc) { $def = $svc.NewTask(0); $def.XmlText = $xml }
    } catch { Write-Host ("[register] {0}: XML 검증 실패 - {1}" -f $name, $_.Exception.Message); $fail = 1; continue }
    if ($def) {
        # TASK_INSTANCES_POLICY: 0 Parallel · 1 Queue · 2 IgnoreNew · 3 StopExisting
        $miName = @('Parallel', 'Queue', 'IgnoreNew', 'StopExisting')[[int]$def.Settings.MultipleInstances]
        Write-Host ("[register] {0}: 정의 OK - ExecutionTimeLimit={1} MultipleInstances={2} RestartOnFailure={3}x{4} DisallowStartIfOnBatteries={5} StopIfGoingOnBatteries={6} Triggers={7}" -f `
            $name, $def.Settings.ExecutionTimeLimit, $miName, $def.Settings.RestartInterval, $def.Settings.RestartCount, `
            $def.Settings.DisallowStartIfOnBatteries, $def.Settings.StopIfGoingOnBatteries, $def.Triggers.Count)
    }
    if ($DryRun) { Write-Host ("[register] DryRun - 등록하지 않음 (XML 정의 검증만 · 파일은 남기지 않음): {0}" -f $name); continue }
    # 2) 등록 - 이 사용자 원칙(InteractiveToken)이라 관리자 승격 없이 만들어진다. TASK_CREATE_OR_UPDATE=6, TASK_LOGON_INTERACTIVE_TOKEN=3
    $ok = $false
    try {
        [void]$folder.RegisterTaskDefinition($name, $def, 6, $null, $null, 3, $null)
        $ok = $true
    } catch {
        Write-Host ("[register] COM 등록 실패({0}) - schtasks 로 재시도" -f $_.Exception.Message.Split([char]10)[0].Trim())
        try {
            [System.IO.File]::WriteAllText($xmlPath, $xml, [System.Text.Encoding]::Unicode)
            $o = & { $ErrorActionPreference = 'Continue'; & schtasks /Create /TN $name /XML $xmlPath /F 2>&1 }
            if ($LASTEXITCODE -eq 0) { $ok = $true } else { Write-Host ("[register] schtasks 실패: " + ($o -join ' ')) }
        } finally { try { Remove-Item -LiteralPath $xmlPath -Force -ErrorAction SilentlyContinue } catch {} }
    }
    if (-not $ok) { $fail = 1; continue }
    Write-Host ("[register] 등록: {0}  (로그온 시 자동 시작 · 실행 시간 제한 없음 · 겹침 무시)" -f $name)
    if (-not $NoStart) {
        # 지금 시작 - 이미 돌고 있으면 IgnoreNew 로 무시된다(샘플러 자체도 뮤텍스로 단일 인스턴스)
        try { $t = $folder.GetTask($name); [void]$t.Run($null); Write-Host ("[register] 시작: {0}" -f $name) }
        catch { Write-Host ("[register] {0} 시작 실패(다음 로그온부터 자동 시작): {1}" -f $name, $_.Exception.Message.Split([char]10)[0].Trim()) }
    }
}
if ($Remove) { exit 0 }
if ($fail) { Write-Host '[register] 일부 작업이 등록되지 않았습니다.'; exit 1 }
# 등록·시작이 성공해도 실제로 기록이 쌓이는지는 별개다(실행 정책·보안 정책이 루프 진입 전에 막으면
# 로그조차 안 남는다). 여기서 짧게 확인해 주지 않으면 사용자는 대시보드의 '샘플러 꺼짐' 만 다시 본다.
if (-not $NoStart) {
    $actDir = Join-Path (Split-Path -Parent $here) 'datactivity'
    $seen = $false
    for ($i = 0; $i -lt 12 -and -not $seen; $i++) {
        Start-Sleep -Seconds 5
        $seen = @(Get-ChildItem -LiteralPath $actDir -Filter 'activity_*.csv' -ErrorAction SilentlyContinue |
                  Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-3) }).Count -gt 0
    }
    if ($seen) {
        Write-Host '[register] 확인: 샘플이 쌓이기 시작했습니다.'
    } else {
        Write-Host '[register] [!] 등록은 됐는데 60초 안에 샘플이 쌓이지 않았습니다.'
        Write-Host '           실행 정책·보안 정책이 막았을 수 있습니다. 아래를 그대로 실행해 오류를 보세요:'
        Write-Host ('           powershell -ExecutionPolicy Bypass -File "' + (Join-Path $here 'Start-ActivitySampler.ps1') + '" -TestSamples 3')
    }
}
Write-Host '[register] 완료 - 상태 확인: LoadMonitor24-수집진단.bat ([창 샘플러] 절)'
exit 0
