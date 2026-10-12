# Stop-LMSampler.ps1 - LoadMonitor 샘플러가 돌고 있는지 확인하고 끈다 (판 무관: LM20~LM25 의 창 샘플러·팀즈 샘플러)
#
# 확인 - 명령줄에 Start-ActivitySampler.ps1(창 샘플러)·Start-TeamsSampler.ps1(팀즈 샘플러)이 있는 PowerShell 프로세스와,
#        그 샘플러를 로그온 때마다 띄우는 예약 작업(LoadMonitor<판>-Sampler · LoadMonitor<판>-TeamsSampler).
# 끄기 - 예약 작업을 '사용 안 함'으로 바꾸고(지우지 않는다 - LM24 는 작업이 없으면 다음 분석 때 다시 등록한다),
#        샘플러 프로세스를 종료한다(팀즈 샘플러가 띄운 자식 PowerShell 까지). 관리자 권한 불필요.
#        다른 PowerShell 창·프로그램과 모아 둔 기록(data\activity 등)은 건드리지 않는다.
#
# 사용 - LoadMonitor-샘플러끄기.bat            확인한 뒤 끌지 묻는다
#        LoadMonitor-샘플러끄기.bat -Status    확인만
#        LoadMonitor-샘플러끄기.bat -Yes       묻지 않고 끈다
param(
    [switch]$Status,
    [switch]$Yes,
    [string]$Only = ''          # 시험용 - 이 정규식에 맞는 작업 이름·명령줄만 대상으로 한다
)

$ErrorActionPreference = 'Continue'
$ScriptRx = '(?i)Start-(Activity|Teams)Sampler\.ps1'
$TaskRx = '(?i)^LoadMonitor\d*[-_ ]?(Teams)?Sampler$'

function Get-Ver([string]$s) {
    if ($s -match '(?i)(?:LoadMonitor|loadmon|LM)[ _-]?(\d{2})(?!\d)') { return 'LM' + $Matches[1] }
    return ''
}

function Get-Kind([string]$s) {
    if ($s -match '(?i)TeamsSampler') { return '팀즈 샘플러' }
    return '창 샘플러'
}

function Get-ScriptPath([string]$s) {
    if ($s -match '(?i)"([^"]*Start-(?:Activity|Teams)Sampler\.ps1)') { return $Matches[1] }
    if ($s -match "(?i)'([^']*Start-(?:Activity|Teams)Sampler\.ps1)") { return $Matches[1] }
    if ($s -match '(?i)(\S*Start-(?:Activity|Teams)Sampler\.ps1)') { return $Matches[1] }
    return ''
}

function Get-RecordAge([string]$script) {
    # <설치 폴더>\collect\샘플러.ps1 -> 그 샘플러가 쓰는 기록 파일의 마지막 쓰기(분 전). 모르면 $null
    if (-not $script) { return $null }
    try {
        $root = Split-Path -Parent (Split-Path -Parent $script)
        if ($script -match '(?i)TeamsSampler') {
            $files = @(Get-Item -LiteralPath (Join-Path $root 'data\m365\teams_window.csv') -ErrorAction SilentlyContinue)
        } else {
            $files = @(Get-ChildItem -LiteralPath (Join-Path $root 'data\activity') -Filter 'activity_*.csv' -ErrorAction SilentlyContinue)
        }
        $last = $files | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($last) { return [int][math]::Floor(((Get-Date) - $last.LastWriteTime).TotalMinutes) }
    } catch { }
    return $null
}

function ConvertTo-Time($v) {
    if ($v -is [datetime]) { return $v }
    try { return [Management.ManagementDateTimeConverter]::ToDateTime([string]$v) } catch { return $null }
}

function Get-AllProcesses {
    try { return @(Get-CimInstance Win32_Process -ErrorAction Stop) } catch { }
    try { return @(Get-WmiObject Win32_Process -ErrorAction Stop) } catch { }
    Write-Host '  프로세스 목록을 읽지 못했습니다 - 작업 관리자에서 powershell.exe 를 확인하세요.' -ForegroundColor Yellow
    return @()
}

function Get-Descendants($all, $parent) {
    # 팀즈 샘플러가 5분마다 띄우는 자식 PowerShell(Get-TeamsWindow.ps1) 등. PID 재사용을 피해 부모보다 늦게 생긴 것만.
    $found = New-Object System.Collections.ArrayList
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($parent)
    while ($queue.Count -gt 0) {
        $cur = $queue.Dequeue()
        $t0 = ConvertTo-Time $cur.CreationDate
        foreach ($c in $all) {
            if ([int]$c.ParentProcessId -ne [int]$cur.ProcessId -or [int]$c.ProcessId -eq [int]$cur.ProcessId) { continue }
            if ([string]$c.Name -match '(?i)^conhost\.exe$') { continue }      # 콘솔 창 호스트 - 샘플러가 끝나면 스스로 닫힌다
            if (@($found | Where-Object { [int]$_.ProcessId -eq [int]$c.ProcessId }).Count) { continue }
            $t1 = ConvertTo-Time $c.CreationDate
            if ($t0 -and $t1 -and $t1 -lt $t0) { continue }
            [void]$found.Add($c)
            $queue.Enqueue($c)
        }
    }
    return $found
}

function Get-SamplerProcesses {
    $all = @(Get-AllProcesses)
    foreach ($p in $all) {
        if ([string]$p.Name -notmatch '(?i)^(powershell|pwsh)\.exe$') { continue }
        $cl = [string]$p.CommandLine
        if ($cl -notmatch $ScriptRx -or $cl -match '(?i)Stop-LMSampler') { continue }
        if ([int]$p.ProcessId -eq $PID) { continue }
        if ($Only -and $cl -notmatch $Only) { continue }
        $script = Get-ScriptPath $cl
        [pscustomobject]@{
            Pid = [int]$p.ProcessId; Kind = (Get-Kind $cl); Ver = (Get-Ver $script); Script = $script
            Start = (ConvertTo-Time $p.CreationDate); Kids = @(Get-Descendants $all $p)
        }
    }
}

function Get-SamplerTasks {
    try {
        $svc = New-Object -ComObject 'Schedule.Service'
        $svc.Connect()
        $all = @($svc.GetFolder('\').GetTasks(1))          # 1 = 숨김 작업 포함
    } catch {
        Write-Host ('  작업 스케줄러를 읽지 못했습니다: ' + $_.Exception.Message.Split([char]10)[0].Trim()) -ForegroundColor Yellow
        return
    }
    foreach ($t in $all) {
        $name = [string]$t.Name
        $act = ''
        try { foreach ($a in @($t.Definition.Actions)) { if ([int]$a.Type -eq 0) { $act += [string]$a.Path + ' ' + [string]$a.Arguments + ' ' } } } catch { }
        if ($name -notmatch $TaskRx -and $act -notmatch $ScriptRx) { continue }
        if ($Only -and ($name + ' ' + $act) -notmatch $Only) { continue }
        $script = Get-ScriptPath $act
        $ver = Get-Ver $name
        if (-not $ver) { $ver = Get-Ver $script }
        [pscustomobject]@{
            Name = $name; Task = $t; Enabled = [bool]$t.Enabled; Running = ([int]$t.State -eq 4)
            Kind = (Get-Kind ($name + ' ' + $act)); Ver = $ver
        }
    }
}

function Show-State($procs, $tasks) {
    Write-Host ''
    Write-Host '[샘플러 프로세스]'
    if (-not $procs.Count) { Write-Host '  돌고 있는 샘플러가 없습니다.' -ForegroundColor Green }
    foreach ($p in $procs) {
        $bits = @(($p.Kind + $(if ($p.Ver) { ' ' + $p.Ver } else { '' })), ('PID ' + $p.Pid))
        if ($p.Start) { $bits += ('{0:MM-dd HH:mm} 시작' -f $p.Start) }
        $age = Get-RecordAge $p.Script
        if ($null -ne $age) { $bits += ('마지막 기록 {0}분 전' -f $age) }
        if ($p.Kids.Count) { $bits += ('자식 프로세스 {0}개' -f $p.Kids.Count) }
        Write-Host ('  [실행 중] ' + ($bits -join ' · ')) -ForegroundColor Yellow
        if ($p.Script) { Write-Host ('            ' + $p.Script) }
    }
    Write-Host ''
    Write-Host '[로그온 자동 시작 - 작업 스케줄러]'
    if (-not $tasks.Count) { Write-Host '  등록된 샘플러 작업이 없습니다.' -ForegroundColor Green }
    foreach ($t in $tasks) {
        $tail = $t.Kind + $(if ($t.Ver) { ' ' + $t.Ver } else { '' }) + $(if ($t.Running) { ' · 지금 실행 중' } else { '' })
        if ($t.Enabled) { Write-Host ('  [켜짐] {0} ({1}) - 로그온할 때마다 샘플러를 띄웁니다' -f $t.Name, $tail) -ForegroundColor Yellow }
        else { Write-Host ('  [사용 안 함] {0} ({1})' -f $t.Name, $tail) -ForegroundColor Green }
    }
}

Write-Host ('LoadMonitor 샘플러 확인 - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm'))
$procs = @(Get-SamplerProcesses)
$tasks = @(Get-SamplerTasks)
Show-State $procs $tasks
Write-Host ''
$on = @($tasks | Where-Object { $_.Enabled -or $_.Running })
if (-not $procs.Count -and -not $on.Count) {
    Write-Host '샘플러가 모두 꺼져 있습니다. 바꿀 것이 없습니다.' -ForegroundColor Green
    exit 0
}
if ($Status) { exit 0 }

Write-Host ('끄면: 샘플러 프로세스 {0}개를 종료하고, 로그온 자동 시작 작업 {1}개를 ''사용 안 함''으로 바꿉니다(작업은 지우지 않음).' -f `
    $procs.Count, @($tasks | Where-Object { $_.Enabled }).Count)
$ans = ''
if ($Yes) { $ans = 'Y' }
else { try { $ans = [string](Read-Host '샘플러를 끌까요? (Y/N)') } catch { $ans = '' } }
if ($ans -notmatch '^\s*[Yy]') {
    Write-Host '아무것도 바꾸지 않았습니다.'
    exit 0
}

# 묻는 동안 끝난 프로세스의 PID 가 다른 프로그램에 다시 쓰였을 수 있다 - 끄기 직전에 다시 찾는다
$procs = @(Get-SamplerProcesses)
$tasks = @(Get-SamplerTasks)
$fail = 0
# 1) 자동 시작부터 끈다 - 프로세스를 먼저 끝내면 작업의 '실패 시 다시 시작'(1분)이 곧바로 다시 띄울 수 있다
foreach ($t in $tasks) {
    if ($t.Enabled) {
        $ok = $false
        try { $t.Task.Enabled = $false; $ok = $true } catch { }
        if (-not $ok) {
            cmd.exe /c ('schtasks /Change /TN "{0}" /DISABLE <nul >nul 2>&1' -f $t.Name)
            $ok = ($LASTEXITCODE -eq 0)
        }
        if ($ok) { Write-Host ('  자동 시작 끔: ' + $t.Name) -ForegroundColor Green }
        else {
            $fail++
            Write-Host ('  [!] {0} 을(를) 사용 안 함으로 바꾸지 못했습니다 - 작업 스케줄러(taskschd.msc)에서 직접 바꾸세요.' -f $t.Name) -ForegroundColor Red
        }
    }
    if ($t.Running) { try { $t.Task.Stop(0) } catch { } }
}
# 2) 프로세스 종료 - 샘플러(부모)를 먼저 끝내 새 자식이 생기지 않게 한 뒤 남은 자식을 끝낸다
foreach ($p in $procs) {
    foreach ($id in (@($p.Pid) + @($p.Kids | ForEach-Object { [int]$_.ProcessId }))) {
        try { Stop-Process -Id $id -Force -ErrorAction Stop } catch { }
    }
    Write-Host ('  종료: {0} PID {1}' -f $p.Kind, $p.Pid) -ForegroundColor Green
}
Start-Sleep -Seconds 2

Write-Host ''
Write-Host '---- 끈 뒤 상태 ----'
$procs = @(Get-SamplerProcesses)
$tasks = @(Get-SamplerTasks)
Show-State $procs $tasks
Write-Host ''
if ($procs.Count) {
    $fail++
    Write-Host '[!] 아직 도는 샘플러가 있습니다. LM 대시보드가 켜져 있으면 닫고 이 도구를 다시 실행하세요.' -ForegroundColor Red
} else {
    Write-Host '샘플러를 껐습니다. 남아 있는 PowerShell 창(이미 끝난 창)은 닫으면 됩니다.' -ForegroundColor Green
}
Write-Host 'LM24 를 다시 실행하면 샘플러가 다시 켜질 수 있습니다 - 그때는 이 도구를 다시 실행하세요.'
if ($fail) { exit 1 }
exit 0
