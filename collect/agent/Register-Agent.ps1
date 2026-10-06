<#
.SYNOPSIS
  에이전트 작업 등록(계약 §7.3 · §4.7 · TAB §1.6.4 · CP §1.4 · L-15) — 작업 스케줄러 작업은 하나(감독 루프), 이름은 LM27-<install_id>.

.DESCRIPTION
  이전 판 Register-Samplers.ps1 의 실측 결정체를 잇되 두 곳을 고쳤다:
    · 작업 폴더(WorkingDirectory)와 실행 파일은 에이전트 폴더(%LOCALAPPDATA%\LoadMonitor27\agent\)와 그 bin 사본 — 프로그램 폴더를
      가리키지 않는다(이전 판은 프로그램 폴더를 작업 폴더로 잡아 폴더 이동·이름 바꾸기를 막았다).
    · 판 공통 이름 대신 install_id 가 든 이름(작업·뮤텍스) — 다른 폴더의 에이전트를 '살아 있음'으로 오판하지 않는다.
  그대로: XML 1.4 정의 · ExecutionTimeLimit PT0S(무제한 — 기본 PT72H 로 3일 뒤 조용히 멈춘 사고) · IgnoreNew · RestartOnFailure
  PT1M×99 · 배터리 제한 해제 · 로그온 트리거(이 사용자, PT30S 지연) · InteractiveToken · LeastPrivilege · 관리자 권한 불필요 ·
  COM RegisterTaskDefinition(7인자) 실패 시 schtasks /Create /XML 폴백(임시 XML 은 UTF-16 LE BOM, 등록 직후 삭제 — SID·경로가 든
  파일을 남기지 않는다).
  옛 작업 정리(X-028): agent.json 의 prior_install_ids 에 있는 install_id 의 작업 중 Action 이 이 에이전트 폴더를 가리키는 것만
  지운다. 다른 경로를 가리키는 같은 꼴 이름, 이전 판·다른 도구의 작업은 건드리지 않는다.

  디스크 쓰기는 schtasks 폴백의 임시 XML(%TEMP%)뿐이다(L-09 예외). 결과는 stdout 한 줄 {"_register": {...}}(숫자·열거만 —
  -DryRun 일 때만 사용자 칸을 '{user}' 로 바꾼 XML 을 함께 낸다).

.PARAMETER InstallId
  32자리 16진 install_id
.PARAMETER AgentVer
  bin 사본 판(agent\bin\<판>\) — 등록·DryRun 에 필요
.PARAMETER Impl
  py(사본 pythonw + agent_main.py) · ps(powershell + ps\agent.ps1)
.PARAMETER Remove
  이 설치의 작업을 지운다
.PARAMETER NoStart
  등록만(지금 시작하지 않음)
.PARAMETER DryRun
  등록·삭제 없이 XML 을 만들어 작업 스케줄러 파서로 검증만(읽기)
.PARAMETER TaskPrefix
  작업 이름 접두(기본 LM27, 시험은 LM27T)

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File collect\agent\Register-Agent.ps1 -InstallId <32hex> -AgentVer 0.1.0-1a2b3c4d -Impl py
#>
[CmdletBinding()]
param(
    [string]$InstallId = '',
    [string]$AgentVer = '',
    [string]$Impl = '',
    [switch]$Remove,
    [switch]$NoStart,
    [switch]$DryRun,
    [string]$TaskPrefix = 'LM27'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Off
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $script:Utf8 } catch { }
$script:Inv = [Globalization.CultureInfo]::InvariantCulture
$script:TaskNs = 'http://schemas.microsoft.com/windows/2004/02/mit/task'

# ───────────────────────── 출력(stdout 한 줄 JSON) ─────────────────────────
function ConvertTo-LmJsonString([string]$s) {
    $s = $s.Replace('\', '\\').Replace('"', '\"')
    if ($s -match '[\x00-\x1f]') {
        $s = [regex]::Replace($s, '[\x00-\x1f]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
    }
    return '"' + $s + '"'
}

function ConvertTo-LmJson($v) {
    if ($null -eq $v) { return 'null' }
    if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
    if ($v -is [string]) { return (ConvertTo-LmJsonString $v) }
    if ($v -is [int] -or $v -is [long]) { return ([long]$v).ToString($script:Inv) }
    $parts = New-Object 'Collections.Generic.List[string]'
    if ($v -is [Collections.IDictionary]) {
        foreach ($k in @($v.Keys)) { $parts.Add((ConvertTo-LmJsonString ([string]$k)) + ':' + (ConvertTo-LmJson $v[$k])) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v -is [Collections.IEnumerable]) {
        foreach ($x in $v) { $parts.Add((ConvertTo-LmJson $x)) }
        return '[' + ($parts -join ',') + ']'
    }
    return (ConvertTo-LmJsonString ([string]$v))
}

function Send-LmResult($res) {
    $b = $script:Utf8.GetBytes((ConvertTo-LmJson ([ordered]@{ _register = $res })) + "`n")
    $o = [Console]::OpenStandardOutput()
    $o.Write($b, 0, $b.Length)
    $o.Flush()
}

function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }

# ───────────────────────── 순수 판정(시험이 AST 로 꺼내 쓴다) ─────────────────────────
function Test-LmInstallId([string]$id) { return [bool]($id -cmatch '^[0-9a-f]{32}$') }
function Test-LmAgentVer([string]$v) { return [bool]($v -match '^[0-9A-Za-z][0-9A-Za-z._-]{0,31}$') }
function Test-LmPrefix([string]$p) { return [bool]($p -cmatch '^LM27T?$') }

# 작업 Action(파이썬 lm27.agent.install.agent_entry 와 같은 문자열)
function Get-LmEntry([string]$agentDir, [string]$ver, [string]$impl, [string]$id) {
    $bin = Join-Path (Join-Path $agentDir 'bin') $ver
    if ($impl -eq 'ps') {
        $sysroot = $env:SystemRoot
        if (-not $sysroot) { $sysroot = 'C:\Windows' }
        $scr = Join-Path (Join-Path $bin 'ps') 'agent.ps1'
        return [ordered]@{
            command = (Join-Path $sysroot 'System32\WindowsPowerShell\v1.0\powershell.exe')
            arguments = ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $scr + '" -InstallId ' + $id)
            script = $scr; workdir = $agentDir
        }
    }
    $main = Join-Path $bin 'agent_main.py'
    return [ordered]@{
        command = (Join-Path (Join-Path $bin 'py311') 'pythonw.exe')
        arguments = ('-X utf8 -I -B "' + $main + '" --install-id ' + $id)
        script = $main; workdir = $agentDir
    }
}

# 지울 옛 작업(X-028): 이름이 <접두>-<옛 install_id>(prior 에 있고 지금 것이 아님)이고 Action 이 이 에이전트 폴더를 가리키는 것만.
# $tasks = @([pscustomobject]@{ name; command; arguments }) — 작업 스케줄러에서 읽은 것(또는 시험 자료)
function Select-LmStaleTask($tasks, [string]$agentDir, [string]$id, $priorIds, [string]$prefix) {
    $out = New-Object 'Collections.Generic.List[string]'
    $want = @{}
    foreach ($p in @($priorIds)) {
        $s = [string]$p
        if ((Test-LmInstallId $s) -and $s -ne $id) { $want[$prefix + '-' + $s] = $true }
    }
    $root = $agentDir.TrimEnd('\').ToLowerInvariant() + '\'
    foreach ($t in @($tasks)) {
        if ($null -eq $t) { continue }
        $n = [string]$t.name
        if (-not $want.ContainsKey($n)) { continue }
        $cmd = ([string]$t.command).Trim('"').ToLowerInvariant()
        $arg = ([string]$t.arguments).Replace('"', '').ToLowerInvariant()
        if ($cmd.StartsWith($root) -or $arg.Contains($root)) { $out.Add($n) }
    }
    return , $out.ToArray()
}

function New-LmTaskXml([string]$name, $entry, [string]$userId, [string]$sid, [string]$author) {
    $desc = 'LoadMonitor27 PC 기록 에이전트(감독 루프) - 로그온 시 자동 시작, 실행 시간 제한 없음, 프로그램 폴더를 잡지 않음'
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$(Esc $author)</Author>
    <Description>$(Esc $desc)</Description>
    <URI>\$(Esc $name)</URI>
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
      <Command>$(Esc ([string]$entry.command))</Command>
      <Arguments>$(Esc ([string]$entry.arguments))</Arguments>
      <WorkingDirectory>$(Esc ([string]$entry.workdir))</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

# ───────────────────────── 작업 스케줄러(COM 1순위 · schtasks 2순위) ─────────────────────────
function Get-LmFolder {
    $svc = New-Object -ComObject 'Schedule.Service'
    $svc.Connect()
    return @($svc, $svc.GetFolder('\'))
}

function Get-LmTaskInfo($folder, [string]$name) {
    try { $t = $folder.GetTask('\' + $name) } catch { return $null }
    $cmd = ''; $arg = ''
    foreach ($a in @($t.Definition.Actions)) {
        if ($a.Type -eq 0) { $cmd = [string]$a.Path; $arg = [string]$a.Arguments; break }
    }
    return [pscustomobject]@{ name = $name; command = $cmd; arguments = $arg; task = $t }
}

function Invoke-LmSchtasks([string[]]$argv) {
    $o = & { $ErrorActionPreference = 'Continue'; & schtasks.exe @argv 2>&1 }
    return [bool]($LASTEXITCODE -eq 0)
}

function Read-LmPriorIds([string]$agentDir) {
    $p = Join-Path $agentDir 'agent.json'
    if (-not [IO.File]::Exists($p)) { return @() }
    try {
        $j = [IO.File]::ReadAllText($p, $script:Utf8) | ConvertFrom-Json
        return @($j.prior_install_ids | Where-Object { $_ })
    } catch { return @() }
}

# ───────────────────────── 본체 ─────────────────────────
function Invoke-Main {
    $res = [ordered]@{ task = $null; op = 'register'; ok = $false; via = $null; started = $false; removed_prior = 0;
                       valid = $null; reason = $null }
    if ($Remove) { $res.op = 'remove' } elseif ($DryRun) { $res.op = 'dry_run' }
    if (-not (Test-LmInstallId $InstallId) -or -not (Test-LmPrefix $TaskPrefix)) { $res.reason = 'bad_args'; return $res }
    $name = $TaskPrefix + '-' + $InstallId
    $res.task = $name
    $lad = $env:LOCALAPPDATA
    if (-not $lad) { $lad = [Environment]::GetFolderPath('LocalApplicationData') }
    $agentDir = Join-Path (Join-Path $lad 'LoadMonitor27') 'agent'

    $svc = $null; $folder = $null
    try { $pair = Get-LmFolder; $svc = $pair[0]; $folder = $pair[1] } catch { $svc = $null; $folder = $null }

    if ($Remove) {
        $ok = $false
        if ($folder) {
            try { $folder.DeleteTask($name, 0); $ok = $true; $res.via = 'com' } catch { $ok = $false }
            if (-not $ok -and $null -eq (Get-LmTaskInfo $folder $name)) { $ok = $true; $res.via = 'none' }
        }
        if (-not $ok) {
            $ok = Invoke-LmSchtasks @('/Delete', '/TN', $name, '/F')
            if ($ok) { $res.via = 'schtasks' }
        }
        $res.ok = $ok
        if (-not $ok) { $res.reason = 'remove_failed' }
        return $res
    }

    if (-not (Test-LmAgentVer $AgentVer) -or ($Impl -ne 'py' -and $Impl -ne 'ps')) { $res.reason = 'bad_args'; return $res }
    $entry = Get-LmEntry $agentDir $AgentVer $Impl $InstallId
    if (-not $DryRun -and (-not [IO.File]::Exists([string]$entry.command) -or -not [IO.File]::Exists([string]$entry.script))) {
        $res.reason = 'bin_missing'; return $res
    }
    $userId = "$env:USERDOMAIN\$env:USERNAME"
    $sid = ''
    try { $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value } catch { $sid = '' }
    if (-not $sid) { $sid = $userId }
    $xml = New-LmTaskXml $name $entry $userId $sid $userId

    # 정의 검증(등록 없이 파서만)
    $def = $null
    if ($svc) {
        try { $def = $svc.NewTask(0); $def.XmlText = $xml; $res.valid = $true } catch { $res.valid = $false; $def = $null }
    }
    $prior = @(Read-LmPriorIds $agentDir)
    $stale = @()
    if ($folder -and $prior.Count -gt 0) {
        $infos = @()
        foreach ($p in $prior) {
            $pn = $TaskPrefix + '-' + [string]$p
            $info = Get-LmTaskInfo $folder $pn
            if ($info) { $infos += $info }
        }
        $stale = Select-LmStaleTask $infos $agentDir $InstallId $prior $TaskPrefix
    }

    if ($DryRun) {
        $res.ok = ($res.valid -ne $false)
        $res['would_remove'] = $stale
        $res['entry'] = $entry
        $res['xml'] = (New-LmTaskXml $name $entry '{user}' '{user}' '{user}')
        return $res
    }
    if ($res.valid -eq $false) { $res.reason = 'xml_invalid'; return $res }

    foreach ($n in $stale) {
        try { $folder.DeleteTask($n, 0); $res.removed_prior++ } catch { }
    }

    # 등록 — TASK_CREATE_OR_UPDATE=6, TASK_LOGON_INTERACTIVE_TOKEN=3(7인자, 이전 판 실측 호출과 같게)
    $ok = $false
    if ($folder -and $def) {
        try { [void]$folder.RegisterTaskDefinition($name, $def, 6, $null, $null, 3, $null); $ok = $true; $res.via = 'com' } catch { $ok = $false }
    }
    if (-not $ok) {
        $xmlPath = Join-Path $env:TEMP ('lm27_task_' + [guid]::NewGuid().ToString('N') + '.xml')
        try {
            [IO.File]::WriteAllText($xmlPath, $xml, [Text.Encoding]::Unicode)
            $ok = Invoke-LmSchtasks @('/Create', '/TN', $name, '/XML', $xmlPath, '/F')
            if ($ok) { $res.via = 'schtasks' }
        } catch { $ok = $false } finally {
            try { Remove-Item -LiteralPath $xmlPath -Force -ErrorAction SilentlyContinue } catch { }
        }
    }
    $res.ok = $ok
    if (-not $ok) { $res.reason = 'register_failed'; return $res }
    if (-not $NoStart) {
        $started = $false
        if ($folder) { try { $t = $folder.GetTask('\' + $name); [void]$t.Run($null); $started = $true } catch { $started = $false } }
        if (-not $started) { $started = Invoke-LmSchtasks @('/Run', '/TN', $name) }
        $res.started = $started
    }
    return $res
}

$result = $null
try { $result = Invoke-Main } catch {
    $result = [ordered]@{ task = $null; op = 'register'; ok = $false; reason = ('error_' + $_.Exception.GetType().Name) }
}
Send-LmResult $result
if ($result.ok) { exit 0 }
exit 1
