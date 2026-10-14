# Stop-LM29.ps1 - 이 설치 폴더의 LM29 작업을 묻지 않고 모두 끝낸다(LoadMonitor29-강제종료.bat 이 부른다).
# 왜: 창을 닫아 끝났다고 생각했는데 뒤에서 분석·수집·전용 Edge 가 계속 돌 수 있다(제보). 대시보드·콘솔 창을 닫을 때의 정리
#     (ui\app.py 창 닫기 감시 · ui\app.py·run.py 콘솔 닫기 처리기)가 기본이고, 이것은 그래도 남았을 때 한 번에 끝내는 비상 단추다.
# 무엇을 끝내나 - 이 폴더(bat 이 있는 폴더)의 것만. 프로세스 이름만으로는 고르지 않는다(같은 PC 의 LM24·LM28·다른 폴더 사본·사람이 띄운
# python·Edge 는 그대로). 경로는 대소문자 없이 전체 경로로 비교하고 끝에 \ 를 붙여 'LoadMonitor29-old' 같은 이웃 폴더를 빼낸다.
#   · python/pythonw/py - 명령줄이나 실행 파일이 이 폴더를 가리키는 것(ui\app.py·run.py·mine·judge·수집기·tools\*.py, 동봉 python\python.exe),
#     또는 이 폴더의 bat 이 띄운 것(부모 cmd 의 명령줄이 이 폴더의 .bat - PC 에 깔린 python 으로 상대 경로 실행한 경우)
#   · powershell/pwsh - 이 폴더 안의 .ps1 을 돌리는 것(collect\*.ps1·tools\*.ps1) - 이 스크립트 자신과 그 부모 줄기는 뺀다
#   · msedge - --user-data-dir 가 이 폴더 data\ 아래인 것(전용 프로필 data\lm29_edge)과 그 자식 - 사람의 Edge 는 건드리지 않는다
#   · 위의 자손(ParentProcessId 줄기 · CreationDate 로 PID 재사용을 거른다) - conhost·explorer·사람의 브라우저는 뺀다
#   · 위를 띄운 이 폴더 bat 의 콘솔 창(cmd) - 먼저 닫는다(파이썬이 먼저 죽으면 bat 이 '서버 오류' 안내를 띄우고 멈춰 기다린다)
# 두는 것: 팀 서버(teamserver.py - 팀 전체가 쓴다 · -IncludeTeamServer 면 함께 끈다) · PC 이동 준비 창(Prepare-Move - 폴더 이름을
#   되돌리는 중일 수 있다).
# -Status 는 목록만 보여 준다. 관리자 권한·임시 파일·예약 작업 없음(Stop-Process -Force 는 내 계정 프로세스만). 하나라도 못 끝내면 exit 1.
# -KeepPid '<pid>[,<pid>]' - 그 pid 와 부모 줄기도 끝내지 않는다. 강제종료 bat 은 파이썬(tools\stop_lm29.py)을 거쳐 이 스크립트를
#   띄우고(PowerShell 이 켜지다 실패(0xc0000142)하면 다시 띄우고, 끝내 안 되면 파이썬이 같은 규칙으로 끝낸다 - 2026-10-15), 그 파이썬이
#   자기 pid 를 넘긴다. 이 폴더의 python 이라 고를 대상처럼 보이지만 끝내면 안 된다(부모 줄기로도 빠지지만 한 번 더 못 박는다).
#   문자열로 받는다 - 이상한 인자가 와도 형 변환 오류로 멈추지 않게(숫자가 아닌 조각은 버린다).
# 고르는 규칙을 고치면 tools\stop_lm29.py 의 select_targets(파이썬 사본)도 함께 고친다 - tests\test_p24 가 둘을 대조한다.
# 시험(tests\ps\Test-StopLM29.ps1)은 이 파일을 dot-source 해 Select-LmTargets 에 가짜 프로세스 목록을 넣는다 - 그때는 아래 본문이 돌지 않는다.
param(
    [switch]$Status,
    [switch]$IncludeTeamServer,
    [string]$KeepPid = ''
)

$script:LmPyNames = @('python.exe', 'pythonw.exe', 'py.exe')
$script:LmPsNames = @('powershell.exe', 'pwsh.exe')
$script:LmBrowserNames = @('msedge.exe', 'chrome.exe', 'firefox.exe', 'whale.exe', 'brave.exe', 'opera.exe', 'iexplore.exe')
$script:LmSkipNames = @('conhost.exe', 'explorer.exe')
$script:LmKindKo = [ordered]@{
    console    = '콘솔 창(bat)'
    python     = '파이썬(대시보드·분석·수집)'
    powershell = 'PowerShell(수집기)'
    edge       = '전용 Edge(Copilot·웹 읽기)'
    other      = '그 밖의 자식 프로세스'
}

function ConvertTo-LmNorm([string]$s) {
    if (-not $s) { return '' }
    return $s.Replace('/', '\').ToLowerInvariant()
}

function Get-LmRootKey([string]$Path) {
    # 'c:\...\loadmonitor28\' - 끝 \ 까지 붙여야 'loadmonitor28-old\' 를 이 폴더로 잘못 보지 않는다
    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    return (ConvertTo-LmNorm $full) + '\'
}

function ConvertTo-LmPids([string]$Text) {
    # '123' · '123,456' → 정수 배열(0 이하·숫자가 아닌 조각은 버린다)
    $out = New-Object System.Collections.Generic.List[int]
    foreach ($t in @(([string]$Text) -split '[,;\s]+')) {
        if ($t -match '^\d{1,10}$') {
            $v = [long]$t
            if ($v -gt 0 -and $v -le [int]::MaxValue) { $out.Add([int]$v) }
        }
    }
    return ,$out.ToArray()
}

function Test-LmOlder($Parent, $Child) {
    # 부모가 자식보다 먼저 생겼나 - 아니면 그 PID 는 부모가 끝난 뒤 다른 프로세스에 재사용된 것이다(시각을 모르면 믿는다)
    $a = $Parent.CreationDate; $b = $Child.CreationDate
    if (-not ($a -is [datetime]) -or -not ($b -is [datetime])) { return $true }
    return ($a -le $b)
}

function Get-LmKeep($P) {
    $name = ([string]$P.Name).ToLowerInvariant()
    $cmd = ConvertTo-LmNorm ([string]$P.CommandLine)
    if ($script:LmPyNames -contains $name -and $cmd -match 'teamserver\.py') { return 'teamserver' }
    if ($script:LmPsNames -contains $name -and $cmd -match 'prepare-move\.ps1') { return 'move' }
    return ''
}

function Test-LmDedicatedEdge([string]$Cmd, [string]$DataKey) {
    return ($Cmd -match ('--user-data-dir="?' + [regex]::Escape($DataKey)))
}

function Test-LmRootBat([string]$Cmd, [string]$Key) {
    return ($Cmd -match ([regex]::Escape($Key) + '[^"]*?\.bat'))
}

function Get-LmKind($P, [string]$Key, [string]$DataKey) {
    # 맨 위 단계의 판정 - 이 폴더를 가리키는 python·powershell·전용 Edge 면 그 종류, 아니면 ''
    $name = ([string]$P.Name).ToLowerInvariant()
    $cmd = ConvertTo-LmNorm ([string]$P.CommandLine)
    $exe = ConvertTo-LmNorm ([string]$P.ExecutablePath)
    if ($script:LmPyNames -contains $name) {
        if ($cmd.Contains($Key) -or $exe.StartsWith($Key)) { return 'python' }
        return ''
    }
    if ($script:LmPsNames -contains $name) {
        # 이 폴더 안의 .ps1 을 돌린다(-File "<폴더>\collect\X.ps1") - '-Root "<폴더>"' 처럼 인자로만 나오는 것은 아니다
        if ($cmd -match ([regex]::Escape($Key) + '[^"'']*?\.ps1(?=["''\s]|$)')) { return 'powershell' }
        return ''
    }
    if ($name -eq 'msedge.exe' -and (Test-LmDedicatedEdge $cmd $DataKey)) { return 'edge' }
    return ''
}

function Select-LmTargets {
    # 순수 함수 - 프로세스 목록(Win32_Process 꼴: ProcessId·ParentProcessId·Name·CommandLine·ExecutablePath·CreationDate)에서
    # 이 폴더의 LM29 것을 고른다 → @{ Targets = @(항목); Kept = @(항목) }. 항목 = Pid·Name·Kind·Why·Keep·Created.
    param(
        [object[]]$Processes,
        [string]$Root,
        [switch]$IncludeTeamServer,
        [int]$SelfPid = 0,
        [int[]]$KeepPid = @()
    )
    $key = Get-LmRootKey $Root
    $dataKey = $key + 'data\'
    $byPid = @{}
    $kids = @{}
    foreach ($p in @($Processes)) {
        if ($null -eq $p) { continue }
        $id = [int]$p.ProcessId
        $byPid[$id] = $p
        $pp = [int]$p.ParentProcessId
        if ($pp -eq $id) { continue }
        if (-not $kids.ContainsKey($pp)) { $kids[$pp] = New-Object System.Collections.ArrayList }
        [void]$kids[$pp].Add($p)
    }
    # 자기 줄기 - 이 스크립트의 powershell 과 그것을 띄운 강제종료 bat 의 cmd(…) 는 끝내지 않는다.
    # -KeepPid(그것을 띄운 tools\stop_lm29.py 의 파이썬)와 그 부모 줄기도 같다.
    $self = @{}
    foreach ($start in @(@($SelfPid) + @($KeepPid))) {
        $cur = [int]$start
        for ($n = 0; $n -lt 64 -and $cur -and -not $self.ContainsKey($cur); $n++) {
            $self[$cur] = $true
            if (-not $byPid.ContainsKey($cur)) { break }
            $pp = [int]$byPid[$cur].ParentProcessId
            if (-not $byPid.ContainsKey($pp) -or -not (Test-LmOlder $byPid[$pp] $byPid[$cur])) { break }
            $cur = $pp
        }
    }
    # 해시테이블(정수 키) - [ordered] 는 정수 키를 '몇 번째' 로 읽어 버린다(PS 의 OrderedDictionary 색인 함정)
    $sel = @{}
    $kept = @{}
    $item = {
        param($p, $kind, $why, $keep)
        [pscustomobject]@{ Pid = [int]$p.ProcessId; Name = [string]$p.Name; Kind = $kind; Why = $why; Keep = $keep
            Created = $p.CreationDate; Ppid = [int]$p.ParentProcessId }
    }
    # ① 맨 위 - 이 폴더를 가리키는 것
    foreach ($p in $byPid.Values) {
        $id = [int]$p.ProcessId
        if ($self.ContainsKey($id)) { continue }
        $kind = Get-LmKind $p $key $dataKey
        $why = 'path'
        if (-not $kind -and $script:LmPyNames -contains ([string]$p.Name).ToLowerInvariant()) {
            $par = $byPid[[int]$p.ParentProcessId]
            if ($par -and ([string]$par.Name).ToLowerInvariant() -eq 'cmd.exe' -and (Test-LmOlder $par $p) -and
                (Test-LmRootBat (ConvertTo-LmNorm ([string]$par.CommandLine)) $key)) { $kind = 'python'; $why = 'bat' }
        }
        if (-not $kind) { continue }
        $keep = Get-LmKeep $p
        if ($keep -eq 'move' -or ($keep -eq 'teamserver' -and -not $IncludeTeamServer)) {
            $kept[$id] = & $item $p $kind $why $keep
            continue
        }
        $sel[$id] = & $item $p $kind $why $keep
    }
    # ② 자손 - 고른 것이 띄운 것(PID 재사용은 생성 시각으로 거른다)
    $queue = New-Object System.Collections.Queue
    foreach ($x in @($sel.Values)) { $queue.Enqueue($x) }
    while ($queue.Count -gt 0) {
        $n = $queue.Dequeue()
        if (-not $kids.ContainsKey($n.Pid)) { continue }
        $np = $byPid[$n.Pid]
        foreach ($c in @($kids[$n.Pid])) {
            $cid = [int]$c.ProcessId
            if ($self.ContainsKey($cid) -or $sel.Contains($cid) -or $kept.Contains($cid)) { continue }
            if (-not (Test-LmOlder $np $c)) { continue }
            $cname = ([string]$c.Name).ToLowerInvariant()
            if ($script:LmSkipNames -contains $cname) { continue }
            if ($script:LmBrowserNames -contains $cname) {
                # 대시보드를 연 사람의 브라우저(webbrowser.open 이 띄웠으면 부모가 우리다)는 빼고, 전용 Edge 와 그 자식만
                if ($n.Kind -eq 'edge' -or ($cname -eq 'msedge.exe' -and (Test-LmDedicatedEdge (ConvertTo-LmNorm ([string]$c.CommandLine)) $dataKey))) {
                    $sel[$cid] = & $item $c 'edge' ('child:' + $n.Pid) ''
                    $queue.Enqueue($sel[$cid])
                }
                continue
            }
            $keep = Get-LmKeep $c
            if ($keep -eq 'move' -or ($keep -eq 'teamserver' -and -not $IncludeTeamServer)) {
                $kept[$cid] = & $item $c 'python' ('child:' + $n.Pid) $keep
                continue
            }
            $kind = 'other'
            if ($script:LmPyNames -contains $cname) { $kind = 'python' }
            elseif ($script:LmPsNames -contains $cname) { $kind = 'powershell' }
            elseif ($cname -eq 'cmd.exe') { $kind = 'console' }
            $sel[$cid] = & $item $c $kind ('child:' + $n.Pid) $keep
            $queue.Enqueue($sel[$cid])
        }
    }
    # ③ 위를 띄운 이 폴더 bat 의 콘솔 창
    foreach ($x in @($sel.Values)) {
        $par = $byPid[$x.Ppid]
        if (-not $par) { continue }
        $pid2 = [int]$par.ProcessId
        if ($self.ContainsKey($pid2) -or $sel.Contains($pid2) -or $kept.Contains($pid2)) { continue }
        if (([string]$par.Name).ToLowerInvariant() -ne 'cmd.exe' -or -not (Test-LmOlder $par $byPid[$x.Pid])) { continue }
        $pc = ConvertTo-LmNorm ([string]$par.CommandLine)
        if (-not (Test-LmRootBat $pc $key) -or $pc -match '강제종료') { continue }
        $sel[$pid2] = & $item $par 'console' ('parent:' + $x.Pid) ''
    }
    return @{ Targets = @($sel.Values); Kept = @($kept.Values) }
}

function Get-LmProcesses {
    # Win32_Process 전체(CIM, 안 되면 WMI) → 같은 꼴의 객체 목록. 생성 시각은 DateTime 으로 맞춘다.
    $list = $null
    try { $list = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop) } catch { $list = $null }
    if ($null -eq $list) {
        try { $list = @(Get-WmiObject -Class Win32_Process -ErrorAction Stop) } catch { $list = @() }
    }
    foreach ($p in $list) {
        $cd = $p.CreationDate
        if ($cd -is [string]) {
            try { $cd = [System.Management.ManagementDateTimeConverter]::ToDateTime($cd) } catch { $cd = $null }
        }
        [pscustomobject]@{ ProcessId = [int]$p.ProcessId; ParentProcessId = [int]$p.ParentProcessId; Name = [string]$p.Name
            CommandLine = [string]$p.CommandLine; ExecutablePath = [string]$p.ExecutablePath; CreationDate = $cd }
    }
}

function Format-LmAge($Created, [datetime]$Now) {
    if (-not ($Created -is [datetime])) { return '?' }
    $s = [int][math]::Max(0, ($Now - $Created).TotalSeconds)
    if ($s -lt 60) { return ('{0}초' -f $s) }
    if ($s -lt 3600) { return ('{0}분' -f [int][math]::Floor($s / 60)) }
    return ('{0}시간 {1}분' -f [int][math]::Floor($s / 3600), [int][math]::Floor(($s % 3600) / 60))
}

function Format-LmState($Sel, [datetime]$Now) {
    # 화면에 찍을 줄들(문자열 배열) - 종류별 개수 · PID(띄운 지 얼마나) · 둔 것
    $lines = New-Object System.Collections.Generic.List[string]
    $t = @($Sel.Targets)
    if ($t.Count -eq 0) { $lines.Add('  끝낼 LM29 작업이 없습니다.') }
    else {
        $lines.Add(('  끝낼 것 {0}개' -f $t.Count))
        foreach ($k in $script:LmKindKo.Keys) {
            $g = @($t | Where-Object { $_.Kind -eq $k })
            if ($g.Count -eq 0) { continue }
            $ids = (@($g | ForEach-Object { '{0}({1})' -f $_.Pid, (Format-LmAge $_.Created $Now) }) -join ' ')
            $lines.Add(('   · {0} {1}개 - pid {2}' -f $script:LmKindKo[$k], $g.Count, $ids))
        }
    }
    foreach ($x in @($Sel.Kept)) {
        if ($x.Keep -eq 'teamserver') {
            $lines.Add(('  [둠] 팀 서버 pid {0}({1}) - 팀 전체가 쓰는 서버라 두었습니다(함께 끄려면 LoadMonitor29-강제종료.bat -IncludeTeamServer)' -f $x.Pid, (Format-LmAge $x.Created $Now)))
        } else {
            $lines.Add(('  [둠] PC 이동 준비 창 pid {0} - 폴더 정리 중일 수 있어 두었습니다(그 창의 안내대로 끝내세요)' -f $x.Pid))
        }
    }
    return $lines.ToArray()
}

function Stop-LmTargets($Targets) {
    # 콘솔 창 → 파이썬(대시보드가 먼저 끝나면 Job 의 자식도 함께 끝난다) → PowerShell → 전용 Edge → 나머지 순서.
    # 이미 끝났으면 넘어가고, 생성 시각이 다르면(PID 재사용) 건드리지 않는다. → @{pid = 실패 사유}
    $fail = @{}
    foreach ($k in @('console', 'python', 'powershell', 'edge', 'other')) {
        foreach ($t in @($Targets | Where-Object { $_.Kind -eq $k })) {
            $p = Get-Process -Id $t.Pid -ErrorAction SilentlyContinue
            if ($null -eq $p) { continue }
            if ($t.Created -is [datetime]) {
                $st = $null
                try { $st = $p.StartTime } catch { $st = $null }
                if ($st -and [math]::Abs(($st - $t.Created).TotalSeconds) -gt 2) { continue }
            }
            try { Stop-Process -Id $t.Pid -Force -ErrorAction Stop }
            catch {
                if (Get-Process -Id $t.Pid -ErrorAction SilentlyContinue) { $fail[[int]$t.Pid] = $_.Exception.Message }
            }
        }
    }
    return $fail
}

function Invoke-StopLm([string]$Folder, [bool]$OnlyStatus, [bool]$WithTeamServer, [int[]]$Keep = @()) {
    Write-Host ''
    Write-Host ' =========================================================='
    Write-Host '  LoadMonitor29 강제 종료 - 이 폴더의 LM29 작업만 끝냅니다'
    Write-Host ' =========================================================='
    Write-Host ('  폴더: {0}' -f $Folder)
    Write-Host ''
    $before = Select-LmTargets -Processes @(Get-LmProcesses) -Root $Folder -IncludeTeamServer:$WithTeamServer -SelfPid $PID -KeepPid $Keep
    Write-Host '  [지금]'
    foreach ($ln in (Format-LmState $before (Get-Date))) { Write-Host $ln }
    Write-Host ''
    if ($OnlyStatus) {
        Write-Host '  (-Status - 목록만 보여 주고 아무것도 끝내지 않았습니다)'
        return 0
    }
    $n0 = @($before.Targets).Count
    if ($n0 -eq 0) {
        Write-Host '  [결과] 이미 모두 끝나 있습니다 - 끝낼 LM29 작업이 없습니다.'
        return 0
    }
    Write-Host '  끝내는 중...'
    $fail = Stop-LmTargets @($before.Targets)
    Start-Sleep -Seconds 2
    $after = Select-LmTargets -Processes @(Get-LmProcesses) -Root $Folder -IncludeTeamServer:$WithTeamServer -SelfPid $PID -KeepPid $Keep
    Write-Host ''
    Write-Host '  [끝낸 뒤]'
    foreach ($ln in (Format-LmState $after (Get-Date))) { Write-Host $ln }
    Write-Host ''
    $left = @($after.Targets)
    if ($left.Count -eq 0) {
        Write-Host ('  [결과] LM29 작업을 모두 끝냈습니다({0}개).' -f $n0)
        if (@($after.Kept | Where-Object { $_.Keep -eq 'teamserver' }).Count -gt 0) {
            Write-Host '         팀 서버는 팀 전체가 쓰므로 그대로 두었습니다.'
        }
        return 0
    }
    Write-Host ('  [결과] {0}개가 아직 남아 있습니다:' -f $left.Count)
    foreach ($x in $left) {
        $why = '끝내는 사이에 새로 시작됐습니다 - 한 번 더 실행하세요'
        if ($fail.ContainsKey([int]$x.Pid)) { $why = '끝내지 못했습니다(' + [string]$fail[[int]$x.Pid] + ')' }
        Write-Host ('   · pid {0} {1} - {2}' -f $x.Pid, $x.Name, $why)
    }
    Write-Host '         다른 계정으로 실행됐거나 보안 프로그램이 막았을 수 있습니다. PC 를 다시 시작하면 모두 끝납니다.'
    return 1
}

if ($MyInvocation.InvocationName -ne '.') {
    $rc = 1
    try {
        $rc = Invoke-StopLm (Split-Path -Parent $PSScriptRoot) ([bool]$Status) ([bool]$IncludeTeamServer) (ConvertTo-LmPids $KeepPid)
    } catch {
        Write-Host ('  [!] 강제 종료 중 오류: {0}' -f $_.Exception.Message)
        $rc = 1
    }
    exit ([int](@($rc) | Select-Object -Last 1))
}
