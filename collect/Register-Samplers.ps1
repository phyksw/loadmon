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
# 등록은 사용자 동작(LoadMonitor28-샘플러등록.bat · 대시보드 버튼)에서만 부른다 - 분석 실행이 동의 없이 부르지 않는다.
# 등록·해제 결과는 data 아래 activity\sampler_status.json 의 registered·task·at 에 남긴다(run.py 자동 재기동은 registered 일 때만).
param(
    [switch]$Teams,
    [switch]$Remove,
    [switch]$NoStart,
    [switch]$DryRun,
    [string]$TaskPrefix = 'LM28',
    [switch]$LibOnly             # 함수만 정의하고 돌아간다 - tests\ps 가 dot-source 해서 쓴다(작업 스케줄러는 건드리지 않음)
)
# 아래에서 샘플러 스크립트를 dot-source 하면 그 param(-LibOnly 등)이 이 범위의 같은 이름 변수를 덮는다 - 먼저 잡아 둔다
$regLibOnly = [bool]$LibOnly

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$here = Join-Path $root 'collect'
# 작업 이름은 LM28-Sampler-<폴더해시6> - LM24(LoadMonitor<숫자>-Sampler)의 정리 정규식 밖이라 서로 지우지 않고,
# 같은 PC 의 LM28 두 벌(개발 사본·배포본)도 겹치지 않는다(collect\LmName.ps1 = core\lmname.py 와 같은 규칙).
. (Join-Path $here 'LmName.ps1')
$lmNames = Get-LmNames $root
$h6 = $lmNames.H6
# 상태 파일 규칙(Read-/Write-SamplerStatus)은 샘플러 것 한 벌을 쓴다
. (Join-Path $here 'Start-ActivitySampler.ps1') -LibOnly
# 샘플러가 쓰는 폴더 - Join-Path 로 조립한다(예전 리터럴은 역슬래시+a 가 BEL(0x07) 로 깨져 확인이 늘 실패하고 60초를 허비했다)
$actDir = Join-Path (Join-Path $root 'data') 'activity'

function Set-SamplerRegistered([string]$dir, [string]$task, [bool]$on) {
    # 등록(또는 해제) 흔적 - run.py 자동 재기동은 이것이 참일 때만 한다(사용자가 등록하지 않은 PC 에서 몰래 띄우지 않는다)
    return (Write-SamplerStatus $dir @{ registered = $on; task = $task; at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') })
}

function Test-SamplerHeartbeat([string]$dir, [datetime]$since) {
    # → 'ok'(since 이후 heartbeat) | 'R-CLM' · 'R-ADDTYPE'(since 이후 실패 기록) | ''(아직 모름)
    # 이미 돌던 인스턴스(뮤텍스·IgnoreNew 로 새 인스턴스는 바로 끝남)는 간격마다 쓰므로 간격+15초 이내면 살아 있다고 본다
    $st = Read-SamplerStatus $dir
    $fmt = 'yyyy-MM-dd HH:mm:ss'
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    if ($st.ContainsKey('ok') -and $st['ok'] -eq $false -and $st['reason']) {
        try { if ([datetime]::ParseExact([string]$st['failed_at'], $fmt, $inv) -ge $since.AddSeconds(-2)) { return [string]$st['reason'] } } catch {}
    }
    $iv = 60
    try { if ([int]$st['interval_s'] -gt 0) { $iv = [int]$st['interval_s'] } } catch {}
    try {
        $hb = [datetime]::ParseExact([string]$st['heartbeat'], $fmt, $inv)
        if ($hb -ge $since.AddSeconds(-($iv + 15))) { return 'ok' }
    } catch {}
    return ''
}

if ($regLibOnly) { return }

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

$jobs = @(@{ name = "$TaskPrefix-Sampler-$h6"; activity = $true; script = (Join-Path $here 'Start-ActivitySampler.ps1'); desc = ('LoadMonitor28 창 샘플러(' + $root + ') - 로그온 시 자동 시작, 실행 시간 제한 없음 (1분마다 활성 창·무입력 시간을 로컬 CSV 에 기록)') })
if ($Teams) {
    $jobs += @{ name = "$TaskPrefix-TeamsSampler-$h6"; script = (Join-Path $here 'Start-TeamsSampler.ps1'); desc = ('LoadMonitor28 팀즈 상시 샘플러(' + $root + ') - 로그온 시 자동 시작, 실행 시간 제한 없음 (열린 팀즈 대화를 5분마다 읽어 로컬 CSV 에 누적)') }
}

$svc = $null; $folder = $null
try { $svc = New-Object -ComObject 'Schedule.Service'; $svc.Connect(); $folder = $svc.GetFolder('\') }
catch { Write-Host ('[register] 작업 스케줄러 연결 실패: ' + $_.Exception.Message); if (-not $DryRun) { exit 1 } }

# 버려진 LM28 작업 정리 - 폴더를 옮기거나 지우면 그 폴더 해시의 작업이 **없는 스크립트를 계속 부른다**.
# 지우는 것은 '^LM28-(Teams)?Sampler-<6자리>$' 이면서 작업 동작의 폴더가 더는 없는 것뿐이다.
# 폴더가 살아 있는 다른 LM28(개발 사본·배포본)과 LoadMonitor<숫자>-* (LM24 등 다른 판 - 공존 정상)는 절대 건드리지 않는다.
function Get-TaskActionDir($task) {
    # 0 = TASK_ACTION_EXEC. 작업 폴더가 비었으면 -File "<스크립트>" 의 폴더. 알아내지 못하면 '' (그러면 지우지 않는다)
    try {
        foreach ($a in @($task.Definition.Actions)) {
            if ([int]$a.Type -ne 0) { continue }
            $wd = [string]$a.WorkingDirectory
            if ($wd) { return $wd }
            if ([string]$a.Arguments -match '-File\s+"([^"]+)"') { return (Split-Path -Parent $Matches[1]) }
        }
    } catch {}
    return ''
}
if (-not $DryRun -and $folder) {
    $mine = $lmNames.TaskRegex
    foreach ($t in @($folder.GetTasks(1))) {          # 1 = 숨김 작업 포함
        $tn = [string]$t.Name
        if ($tn -cnotmatch $mine) { continue }        # LoadMonitor\d+-* 는 여기서 걸러진다
        if ($tn -like "*-$h6") { continue }           # 이 폴더 것은 아래에서 갱신한다
        $adir = Get-TaskActionDir $t
        if (-not $adir -or (Test-Path -LiteralPath $adir)) { continue }   # 폴더가 살아 있는(또는 모르는) 작업은 남긴다
        try { $folder.DeleteTask($tn, 0); Write-Host ("[register] 폴더가 없어진 LM28 작업 해제: {0} ({1})" -f $tn, $adir) }
        catch { Write-Host ("[register] 작업 {0} 을 지우지 못했습니다 - 작업 스케줄러에서 손으로 지우세요" -f $tn) }
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
        # 해제했으면 자동 재기동 조건도 거둔다
        if ($j.activity) { [void](Set-SamplerRegistered $actDir $name $false) }
        continue
    }
    if (-not (Test-Path -LiteralPath $j.script)) { Write-Host ("[register] 스크립트 없음: {0}" -f $j.script); $fail = 1; continue }
    $xml = New-TaskXml $name ([string]$j.script) ([string]$j.desc)
    # XML 파일은 schtasks 폴백에서만 잠깐 쓰고 바로 지운다 - 계정 SID·도메인\사용자·설치 경로가 든 파일을 %TEMP% 에
    # 남기지 않는다. 예전엔 먼저 써 두고 등록 뒤에 지워 -DryRun·검증 실패 경로가 파일을 남겼다(C5).
    $xmlPath = Join-Path $env:TEMP ("lm28_task_{0}.xml" -f $name)
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
    # 등록 흔적(WP6 자동 재기동 조건) - 창 샘플러 작업만
    if ($j.activity -and -not (Set-SamplerRegistered $actDir $name $true)) {
        Write-Host '[register] 주의: 등록 흔적(sampler_status.json)을 쓰지 못했습니다 - 자동 재기동이 이 등록을 모를 수 있습니다'
    }
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
# 샘플러는 시작하자마자 sampler_status.json 에 heartbeat(또는 R-CLM·R-ADDTYPE 실패 사유)를 쓴다 - 60초 고정 대기 대신 최대 20초만 본다.
if (-not $NoStart -and -not $DryRun) {
    $since = (Get-Date).AddSeconds(-1)
    $hb = ''
    for ($i = 0; $i -lt 20 -and -not $hb; $i++) {
        Start-Sleep -Seconds 1
        $hb = Test-SamplerHeartbeat $actDir $since
    }
    # 샘플러의 첫 heartbeat 와 등록 기록이 같은 순간 겹쳐 한쪽이 지워졌을 수 있다 - 등록 흔적을 한 번 더 확인한다
    $stNow = Read-SamplerStatus $actDir
    if ($stNow['registered'] -ne $true) { [void](Set-SamplerRegistered $actDir ([string]$jobs[0].name) $true) }
    $testCmd = 'powershell -ExecutionPolicy Bypass -File "' + (Join-Path $here 'Start-ActivitySampler.ps1') + '" -TestSamples 3'
    if ($hb -eq 'ok') {
        Write-Host '[register] 확인: 샘플러가 기록을 시작했습니다(heartbeat).'
    } elseif ($hb -eq 'R-CLM') {
        Write-Host '[register] [!] 샘플러가 시작하자마자 멈췄습니다: PowerShell 제한 언어 모드(R-CLM).'
        Write-Host '           보안 정책(AppLocker·WDAC)이 스크립트를 제한합니다 - 회사 IT 에 이 스크립트 허용을 요청하세요.'
    } elseif ($hb -eq 'R-ADDTYPE') {
        Write-Host '[register] [!] 샘플러가 시작하자마자 멈췄습니다: Win32 API 를 불러오지 못함(R-ADDTYPE - AppLocker 등이 컴파일을 막음).'
        Write-Host ('           자세한 오류: ' + $testCmd)
    } else {
        Write-Host '[register] [!] 등록은 됐지만 20초 안에 샘플러 heartbeat 를 확인하지 못했습니다(아직 시작 중일 수 있음).'
        Write-Host '           1~2분 뒤 LoadMonitor28-수집진단.bat 로 확인하거나, 아래를 그대로 실행해 오류를 보세요:'
        Write-Host ('           ' + $testCmd)
    }
}
Write-Host '[register] 완료 - 상태 확인: LoadMonitor28-수집진단.bat ([창 샘플러] 절)'
exit 0
