# Test-StopLM29.ps1 - tools\Stop-LM29.ps1 의 Select-LmTargets 가 이 폴더의 LM29 만 고르는지(시험 p21).
# 가짜 프로세스 목록(실재하지 않는 경로·PID)만 넣는다 - 아무것도 끝내지 않는다(Stop-LmTargets 는 부르지 않는다).
# 실제 목록(WMI)은 한 번 읽어, 없는 폴더로 고르면 0개인지만 본다(이 PowerShell 안에서 - 프로세스를 새로 띄우지 않는다).
# 단언은 tests\test_p21_close_stop.py 가 한다(파이썬 런처 줄기·-KeepPid 는 tests\test_p24_stop_startfail.py).
$lmTestRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
. (Join-Path $lmTestRoot 'tools\Stop-LM29.ps1')

$R = 'C:\LM28test\Load Monitor28'
$O = 'C:\LM28test\Load Monitor28-old'
$t0 = Get-Date '2026-10-14 09:00:00'
$edgeExe = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$psExe = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$cmdExe = 'C:\Windows\System32\cmd.exe'
$py = $R + '\python\python.exe'

function New-FakeProc($id, $ppid, $name, $cmd, $exe, $min) {
    [pscustomobject]@{ ProcessId = $id; ParentProcessId = $ppid; Name = $name; CommandLine = $cmd
        ExecutablePath = $exe; CreationDate = $t0.AddMinutes($min) }
}

$fake = @(
    (New-FakeProc 50 4 'explorer.exe' 'C:\Windows\Explorer.EXE' 'C:\Windows\explorer.exe' 0),
    # 대시보드(LoadMonitor29-UI.bat → 동봉 python ui\app.py) → run.py → 수집기·copilot_auto → 전용 Edge(+렌더러)
    (New-FakeProc 100 50 'cmd.exe' ('C:\Windows\system32\cmd.exe /c ""' + $R + '\LoadMonitor29-UI.bat" "') $cmdExe 1),
    (New-FakeProc 101 100 'python.exe' ('"' + $py + '"  ui\app.py') $py 2),
    (New-FakeProc 107 101 'conhost.exe' '\??\C:\Windows\system32\conhost.exe 0xffffffff -ForceV1' 'C:\Windows\System32\conhost.exe' 2),
    (New-FakeProc 102 101 'python.exe' ('"' + $py + '" "' + $R + '\run.py" --from 2026-01-01 --to 2026-10-14 --ai') $py 3),
    (New-FakeProc 103 102 'powershell.exe' ('powershell -NoProfile -ExecutionPolicy Bypass -File "' + $R + '\collect\Get-OutlookData.ps1" -From 2026-01-01') $psExe 4),
    (New-FakeProc 104 102 'python.exe' ('"' + $py + '" "' + $R + '\tools\copilot_auto.py" --send x.txt') $py 4),
    (New-FakeProc 105 104 'msedge.exe' ('"' + $edgeExe + '" --remote-debugging-port=9543 --user-data-dir="' + $R + '\data\lm29_edge" --no-first-run') $edgeExe 5),
    (New-FakeProc 106 105 'msedge.exe' ('"' + $edgeExe + '" --type=renderer --lang=ko') $edgeExe 5),
    # 팀 서버(대시보드가 띄움) · 사람의 Edge(webbrowser.open 이 띄워 부모가 대시보드) · 이동 준비 창 · 탐색기
    (New-FakeProc 108 101 'python.exe' ('"' + $py + '" "' + $R + '\teamserver.py" --port 9310') $py 6),
    (New-FakeProc 109 101 'msedge.exe' ('"' + $edgeExe + '" --single-argument http://127.0.0.1:9268/') $edgeExe 2),
    (New-FakeProc 150 101 'powershell.exe' ('powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\홍길동\AppData\Local\Temp\LM29-Prepare-Move.ps1" -Root "' + $R + '"') $psExe 7),
    (New-FakeProc 160 101 'explorer.exe' ('explorer "' + $R + '\report"') 'C:\Windows\explorer.exe' 7),
    # PID 재사용 - 부모(102)보다 먼저 생긴 '자식' 은 102 가 띄운 것이 아니다
    (New-FakeProc 140 102 'python.exe' 'python C:\other\x.py' 'C:\Python311\python.exe' -30),
    # 다른 폴더·다른 판·같은 파일 이름
    (New-FakeProc 110 50 'msedge.exe' ('"' + $edgeExe + '" --user-data-dir="C:\Users\홍길동\AppData\Local\Microsoft\Edge\User Data"') $edgeExe 0),
    (New-FakeProc 111 50 'python.exe' ('"' + $O + '\python\python.exe" "' + $O + '\run.py"') ($O + '\python\python.exe') 1),
    (New-FakeProc 112 50 'python.exe' '"C:\LM24\LoadMonitor24\python\python.exe" ui\app.py' 'C:\LM24\LoadMonitor24\python\python.exe' 1),
    (New-FakeProc 113 50 'python.exe' 'python C:\work\run.py --from 2026-01-01' 'C:\Python311\python.exe' 1),
    (New-FakeProc 114 50 'msedge.exe' ('msedge.exe --user-data-dir=C:\LM24\LoadMonitor24\data\lm24_edge') $edgeExe 1),
    # 같은 PC 에 함께 깔린 LM28(다른 폴더) - 그 대시보드·전용 Edge(data\lm28_edge · 포트 9533)도 건드리지 않는다
    (New-FakeProc 115 50 'python.exe' '"C:\LM28\LoadMonitor28\python\python.exe" ui\app.py' 'C:\LM28\LoadMonitor28\python\python.exe' 1),
    (New-FakeProc 116 50 'msedge.exe' ('msedge.exe --remote-debugging-port=9533 --user-data-dir=C:\LM28\LoadMonitor28\data\lm28_edge') $edgeExe 1),
    (New-FakeProc 170 50 'powershell.exe' ('powershell -NoProfile -File "' + $O + '\collect\Get-OutlookData.ps1"') $psExe 1),
    # 이 스크립트 자신(강제종료 bat → powershell)
    (New-FakeProc 119 50 'cmd.exe' ('C:\Windows\system32\cmd.exe /c ""' + $R + '\LoadMonitor29-강제종료.bat" "') $cmdExe 10),
    (New-FakeProc 120 119 'powershell.exe' ('powershell -NoProfile -ExecutionPolicy Bypass -File "' + $R + '\tools\Stop-LM29.ps1"') $psExe 10),
    # PC 에 깔린 python 으로 LoadMonitor29.bat 을 돌린 경우(명령줄에 폴더가 없다 - 부모 bat 으로 안다)
    (New-FakeProc 129 50 'cmd.exe' ('C:\Windows\system32\cmd.exe /c ""' + $R + '\LoadMonitor29.bat" "') $cmdExe 1),
    (New-FakeProc 130 129 'python.exe' 'python  run.py --from 2026-01-01 --to 2026-10-14' 'C:\Python311\python.exe' 2),
    (New-FakeProc 131 130 'powershell.exe' ('powershell -NoProfile -File "' + $R + '\collect\Get-PcOnHistory.ps1"') $psExe 3),
    (New-FakeProc 171 50 'pwsh.exe' ('pwsh -File "' + $R.ToUpper() + '/collect/Get-RecentFiles.ps1"') 'C:\Program Files\PowerShell\7\pwsh.exe' 1),
    # 팀서버 bat 으로 띄운 팀 서버
    (New-FakeProc 180 50 'cmd.exe' ('C:\Windows\system32\cmd.exe /c ""' + $R + '\LoadMonitor29-팀서버.bat" "') $cmdExe 1),
    (New-FakeProc 181 180 'python.exe' ('"' + $py + '" teamserver.py --port 9310') $py 2)
)

function Join-Pids($items) { (@($items | ForEach-Object { [int]$_.Pid }) | Sort-Object) -join ',' }

$a = Select-LmTargets -Processes $fake -Root $R -SelfPid 120
$b = Select-LmTargets -Processes $fake -Root ($R + '\') -SelfPid 120 -IncludeTeamServer
$kinds = (@($a.Targets | Sort-Object Pid | ForEach-Object { '{0}:{1}' -f $_.Pid, $_.Kind }) -join ',')
$lines = @(Format-LmState $a (Get-Date '2026-10-14 10:00:00'))
$none = Format-LmState @{ Targets = @(); Kept = @() } (Get-Date)

# 파이썬 런처를 거친 강제종료(2026-10-15) - 강제종료 bat(190) → 동봉 python tools\stop_lm29.py(191) → powershell Stop-LM29.ps1(192).
# 191 은 이 폴더의 python 이라 고를 대상처럼 보인다 - 부모 줄기(-SelfPid 192)로도, -KeepPid 191 만으로도 빠져야 한다.
$fake2 = @($fake | Where-Object { @(119, 120) -notcontains $_.ProcessId }) + @(
    (New-FakeProc 190 50 'cmd.exe' ('C:\Windows\system32\cmd.exe /c ""' + $R + '\LoadMonitor29-강제종료.bat" "') $cmdExe 10),
    (New-FakeProc 191 190 'python.exe' ('"' + $py + '" -X utf8 -B "' + $R + '\tools\stop_lm29.py"') $py 10),
    (New-FakeProc 192 191 'powershell.exe' ('powershell -NoProfile -ExecutionPolicy Bypass -File "' + $R + '\tools\Stop-LM29.ps1" -KeepPid 191') $psExe 10)
)
$l1 = Select-LmTargets -Processes $fake2 -Root $R -SelfPid 192 -KeepPid (ConvertTo-LmPids '191')
$l2 = Select-LmTargets -Processes $fake2 -Root $R -SelfPid 0 -KeepPid @(191)
$l3 = Select-LmTargets -Processes $fake2 -Root $R -SelfPid 0
$l4 = Select-LmTargets -Processes $fake2 -Root $R -SelfPid 192

$real = @(Get-LmProcesses)
$rs = Select-LmTargets -Processes $real -Root 'C:\LM28test\nonexistent folder 9f3c' -SelfPid $PID

return @{
    launcher   = (Join-Pids $l1.Targets)
    keep_only  = (Join-Pids $l2.Targets)
    no_keep    = (Join-Pids $l3.Targets)
    self_only  = (Join-Pids $l4.Targets)
    keep_parse = ((ConvertTo-LmPids '191, 7;x -3 0 99999999999') -join ',')
    keep_empty = [int](ConvertTo-LmPids '').Length
    targets    = (Join-Pids $a.Targets)
    kept       = (Join-Pids $a.Kept)
    targets_ts = (Join-Pids $b.Targets)
    kept_ts    = (Join-Pids $b.Kept)
    kinds      = $kinds
    lines      = ($lines -join ' | ')
    none       = (@($none) -join ' | ')
    age        = (Format-LmAge (Get-Date '2026-10-14 08:00:00') (Get-Date '2026-10-14 10:05:00'))
    real_n     = $real.Count
    real_self  = (@($real | Where-Object { $_.ProcessId -eq $PID }).Count)
    real_sel   = @($rs.Targets).Count
}
