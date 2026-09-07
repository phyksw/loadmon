# Diagnose-Collectors.ps1 - 수집 진단: 이 PC 의 Outlook·Teams 버전/상태에서 무엇이 막혔는지 한 장으로.
# PC 마다 Outlook(클래식/새 Outlook/2016 마법사)·Teams(클래식/새 Teams·지역 형식)가 달라 수집이
# 비는데, 개발자가 그 PC 를 직접 볼 수 없다. 이 스크립트는 원인을 판별할 사실만 모아 report\collect_diag.txt
# 에 적는다. 채팅·메일 내용은 담지 않는다(형식 보존 마스킹: 글자는 x, 숫자·구두점·AM/PM/오전/오후만 유지).
# Usage:  .\Diagnose-Collectors.ps1 [-OutFile path]
param([string]$OutFile = '')
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $OutFile) { $OutFile = Join-Path $root 'report\collect_diag.txt' }
$L = New-Object System.Collections.Generic.List[string]
function W([string]$s) { $L.Add($s); Write-Host $s }
function Mask([string]$s) {
    if (-not $s) { return '' }
    # 모든 문자 체계의 '글자'(\p{L}: 한글·한자·가나·키릴 포함)를 x 로 - 시각 토큰만 남긴다
    $s = [regex]::Replace($s, '오전|오후|어제|Yesterday|AM|PM|am|pm|\p{L}', { param($m) if ($m.Value.Length -gt 1) { $m.Value } else { 'x' } })
    if ($s.Length -gt 90) { $s = $s.Substring(0, 90) + '...' }
    return $s
}
function Rows([string]$p) { if (Test-Path -LiteralPath $p) { try { return ((Get-Content -LiteralPath $p | Where-Object { $_.Trim() }).Count - 1) } catch { return -1 } } ; return -1 }
function RowsTxt([string]$p) { $n = Rows $p; if ($n -lt 0) { return '없음' } ; return ('{0}행' -f $n) }
function Ver([string]$p) { try { return (Get-Item -LiteralPath $p).VersionInfo.ProductVersion } catch { return '?' } }
$findings = New-Object System.Collections.Generic.List[string]
# 팀즈 창 읽기(Get-TeamsWindow.ps1)와 같은 규칙으로 시각 패턴을 구성한다(지역 설정 기반).
# ※ 여기서 몇 줄 잡혔다고 수집기도 그만큼 남기는 것은 아니다 - 수집기는 '왼쪽 채팅목록 열'을 추가로
#   제외한다(이 진단은 제외하지 않는다). 그래서 아래에서 수집기가 실제 남긴 CSV 행과 반드시 대조한다.
$ci0 = Get-Culture
$amD0 = [string]$ci0.DateTimeFormat.AMDesignator; $pmD0 = [string]$ci0.DateTimeFormat.PMDesignator
$desig0 = ((@('오전', '오후', 'AM', 'PM', 'am', 'pm', 'a.m.', 'p.m.', 'A.M.', 'P.M.', '午前', '午後', '上午', '下午', 'vorm.', 'nachm.', $amD0, $pmD0) | Where-Object { $_ } | Select-Object -Unique | ForEach-Object { [regex]::Escape($_) }) -join '|')
$sep0 = ':'
if ($ci0.DateTimeFormat.ShortTimePattern -match '\.') { $sep0 = '[:.]' }
$reTime = '(?:(' + $desig0 + ')\s*)?(?<!\d)(\d{1,2})' + $sep0 + '(\d{2})(?!\d)(?:\s*(' + $desig0 + '))?'
$reTimeGeneric = '(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)'
$cfgRe0 = ''
try { $cfgRe0 = [string]((Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json).teamsTimeRegex) } catch {}
if ($cfgRe0) { $reTime = $cfgRe0 }

W ("LoadMonitor 수집 진단  {0}  PC={1}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm'), $env:COMPUTERNAME)
W '[환경]'
W ("  OS: {0}   PowerShell: {1}" -f [Environment]::OSVersion.VersionString, $PSVersionTable.PSVersion)
$cu = Get-Culture; $ui = Get-UICulture
W ("  문화권: {0} (UI {1})   시각 형식: '{2}'   오전/오후 표기: '{3}'/'{4}'   날짜 형식: '{5}'" -f $cu.Name, $ui.Name, $cu.DateTimeFormat.ShortTimePattern, $cu.DateTimeFormat.AMDesignator, $cu.DateTimeFormat.PMDesignator, $cu.DateTimeFormat.ShortDatePattern)

# ── Outlook ──────────────────────────────────────────────────────────────────
W '[Outlook]'
$classicExe = ''
try { $classicExe = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE' -ErrorAction Stop).'(default)' } catch {}
if (-not $classicExe) { try { $classicExe = (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE' -ErrorAction Stop).'(default)' } catch {} }
$classicOk = [bool]($classicExe -and (Test-Path -LiteralPath $classicExe))
if ($classicOk) { W ("  클래식 Outlook: 설치됨  v{0}  ({1})" -f (Ver $classicExe), $classicExe) } else { W '  클래식 Outlook: 설치 안 됨 (App Paths 에 OUTLOOK.EXE 없음)' }
$newOl = $null
try { $newOl = Get-AppxPackage -Name 'Microsoft.OutlookForWindows' -ErrorAction SilentlyContinue | Select-Object -First 1 } catch {}
$useNew = $false
foreach ($rp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
    try { $pref = Get-ItemProperty $rp -ErrorAction SilentlyContinue; if ($pref -and $pref.UseNewOutlook -eq 1) { $useNew = $true } } catch {}
}
if ($newOl) { W ("  새 Outlook(olk): 설치됨  v{0}   UseNewOutlook 토글: {1}" -f $newOl.Version, $(if ($useNew) { '켜짐' } else { '꺼짐' })) } else { W ("  새 Outlook(olk): 설치 안 됨   UseNewOutlook 토글: {0}" -f $(if ($useNew) { '켜짐' } else { '꺼짐' })) }
$pOl = @(Get-Process outlook -ErrorAction SilentlyContinue); $pOlk = @(Get-Process olk -ErrorAction SilentlyContinue)
W ("  실행 중: 클래식 {0}개 / 새 Outlook {1}개" -f $pOl.Count, $pOlk.Count)
if ($pOl.Count) { $ttl = @($pOl | ForEach-Object { $_.MainWindowTitle } | Where-Object { $_ }); if ($ttl.Count) { W ("    클래식 창 제목: " + (($ttl | ForEach-Object { Mask $_ }) -join ' / ')) } }
$nProf = 0
foreach ($pp in @('HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles', 'HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles', 'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles')) {
    try { $nProf += @(Get-ChildItem -Path $pp -ErrorAction SilentlyContinue).Count } catch {}
}
W ("  메일 프로필: {0}개" -f $nProf)
# COM: 떠 있는 Outlook 에 '붙기'만 시도한다 (New-Object 는 마법사를 띄워 무한 대기 - 절대 호출 안 함)
$comMsg = '시도 안 함 (클래식 Outlook 이 실행 중이 아님)'
if ($pOl.Count) {
    # 잡이 먼저 자기 PID 를 내보낸다 - 막힌 COM 호출은 Stop-Job 으로 멈추지 않는다(검증: 100초 블로킹 호출에 97초 대기).
    # 시간 초과면 잡 프로세스를 직접 끝낸다.
    $job = Start-Job -ScriptBlock { $PID; try { $o = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application'); '붙음 (버전 ' + $o.Version + ')' } catch { '실행 중이지만 붙지 못함 - ' + $_.Exception.Message.Split([char]10)[0] } }
    if (Wait-Job $job -Timeout 25) {
        $comMsg = [string](@(Receive-Job $job) | Select-Object -Last 1)
    } else {
        $comMsg = '25초 무응답 (Outlook 이 COM 호출에 응답하지 않음 - 대화상자/멈춤 의심)'
        try { $cpid = [int](@(Receive-Job $job -Keep) | Select-Object -First 1); if ($cpid) { Stop-Process -Id $cpid -Force -ErrorAction SilentlyContinue } } catch {}
    }
    Remove-Job $job -Force -ErrorAction SilentlyContinue
}
W ("  COM 연결: {0}" -f $comMsg)
# Windows Search 색인 - 최근 30일 메일·일정 건수
$idxMail = -1; $idxCal = -1; $idxNewest = ''
try {
    $conn = New-Object System.Data.OleDb.OleDbConnection("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
    $conn.Open()
    $d30 = (Get-Date).AddDays(-30).ToString('yyyy-MM-dd HH:mm:ss')
    $cmd = $conn.CreateCommand(); $cmd.CommandText = "SELECT TOP 2000 System.ItemDate FROM SYSTEMINDEX WHERE System.Kind='email' AND System.ItemUrl LIKE 'mapi%' AND System.ItemDate >= '$d30' ORDER BY System.ItemDate DESC"
    $rd = $cmd.ExecuteReader(); $idxMail = 0
    while ($rd.Read()) { if ($idxMail -eq 0) { try { $idxNewest = ([datetime]$rd.GetValue(0)).ToLocalTime().ToString('yyyy-MM-dd') } catch {} } ; $idxMail++ }
    $rd.Close()
    $cmd.CommandText = "SELECT TOP 2000 System.StartDate FROM SYSTEMINDEX WHERE System.Kind='calendar' AND System.ItemUrl LIKE 'mapi%' AND System.StartDate >= '$d30'"
    $rd = $cmd.ExecuteReader(); $idxCal = 0
    while ($rd.Read()) { $idxCal++ }
    $rd.Close(); $conn.Close()
    W ("  Windows Search 색인: 최근 30일 Outlook 메일 {0}건{1} / 일정 {2}건 (2000 상한, 디스크의 .msg/.ics 파일 제외)" -f $idxMail, $(if ($idxNewest) { " (최신 $idxNewest)" } else { '' }), $idxCal)
} catch { W ('  Windows Search 색인: 연결 불가 - ' + $_.Exception.Message.Split([char]10)[0]) }
$dO = Join-Path $root 'data\outlook'
W ("  수집 파일: mail.csv {0} / calendar.csv {1}" -f (RowsTxt (Join-Path $dO 'mail.csv')), (RowsTxt (Join-Path $dO 'calendar.csv')))
foreach ($jf in @('outlook_skip.json', 'mail_source.json', 'mail_copilot_unavailable.json')) {
    $p = Join-Path $dO $jf
    if (Test-Path -LiteralPath $p) {
        try {
            $jt = ((Get-Content -LiteralPath $p -Raw -Encoding UTF8).Trim() -replace '\s+', ' ')
            # outlook_skip.json 의 '열린 창: ...' 은 Outlook 창 제목(메일 제목·계정 주소 포함 가능) - 마스킹
            $jt = [regex]::Replace($jt, '\(열린 창: ([^)]*)\)', { param($m) '(열린 창: ' + (Mask $m.Groups[1].Value) + ')' })
            W ("  {0}: {1}" -f $jf, $jt)
        } catch {}
    }
}

# ── Teams ────────────────────────────────────────────────────────────────────
W '[Teams]'
$tp = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(ms-teams|Teams|msteams)$' })
$newTeams = $null
try { $newTeams = Get-AppxPackage -Name 'MSTeams' -ErrorAction SilentlyContinue | Select-Object -First 1 } catch {}
if ($newTeams) { W ("  새 Teams(MSTeams 앱): 설치됨  v{0}" -f $newTeams.Version) } else { W '  새 Teams(MSTeams 앱): 설치 안 됨' }
$classicTeams = Join-Path $env:LOCALAPPDATA 'Microsoft\Teams\current\Teams.exe'
if (Test-Path -LiteralPath $classicTeams) { W ("  클래식 Teams: 설치됨  v{0}" -f (Ver $classicTeams)) } else { W '  클래식 Teams: 설치 안 됨' }
$wv2 = @(Get-Process msedgewebview2 -ErrorAction SilentlyContinue).Count
W ("  실행 중 Teams 프로세스: {0}개   WebView2 프로세스: {1}개" -f $tp.Count, $wv2)
$vis = @()
foreach ($p in $tp) {
    $pv = '?'
    try { $pv = $p.MainModule.FileVersionInfo.ProductVersion } catch {}
    W ("    {0} (pid {1}) v{2}  창 핸들 {3}  제목 '{4}'" -f $p.ProcessName, $p.Id, $pv, $p.MainWindowHandle, (Mask $p.MainWindowTitle))
    if ($p.MainWindowHandle -ne 0) { $vis += $p }
}
$texts = New-Object System.Collections.Generic.List[string]
$uiaNote = ''
if ($vis.Count) {
    try {
        Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
        foreach ($p in $vis) {
            try {
                $rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
                $all = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Automation]::ContentViewCondition)
                $n = 0
                foreach ($e in $all) {
                    $n++; if ($n -gt 4000) { break }
                    try { $nm = $e.Current.Name; if ($nm -and $nm.Length -ge 4) { $texts.Add($nm) } } catch {}
                }
                W ("  UIA: pid {0} 요소 {1}개 → 텍스트 {2}줄" -f $p.Id, $all.Count, $texts.Count)
            } catch { W ("  UIA: pid {0} 읽기 실패 - {1}" -f $p.Id, $_.Exception.Message.Split([char]10)[0]) }
        }
    } catch { $uiaNote = 'UIA 어셈블리 로드 실패 - ' + $_.Exception.Message.Split([char]10)[0]; W ("  " + $uiaNote) }
} else { W '  UIA: 읽을 창 없음 (Teams 가 꺼져 있거나 창이 최소화/트레이 상태 - 핸들 0)' }
$nTime = 0; $nGen = 0; $samp = New-Object System.Collections.Generic.List[string]; $odd = New-Object System.Collections.Generic.List[string]
foreach ($t in $texts) {
    if ($t -match $reTime) { $nTime++; if ($samp.Count -lt 8) { $samp.Add((Mask $t)) } }
    elseif ($t -match $reTimeGeneric) { $nGen++; if ($odd.Count -lt 6) { $odd.Add((Mask $t)) } }
}
if ($texts.Count) {
    W ("  수집기 시각 형식(이 PC 지역 설정 {0}: 오전/오후 '{1}'/'{2}', '{3}'{4}) 일치: {5}줄 / {6}줄 · 일반 형식(숫자:숫자)만 일치: {7}줄" -f $ci0.Name, $amD0, $pmD0, $ci0.DateTimeFormat.ShortTimePattern, $(if ($cfgRe0) { ', config.teamsTimeRegex 적용' } else { '' }), $nTime, $texts.Count, $nGen)
    foreach ($s in $samp) { W ("    일치 예: " + $s) }
    foreach ($s in $odd) { W ("    불일치(숫자:숫자 포함) 예: " + $s) }
}
$dM = Join-Path $root 'data\m365'
W ("  수집 파일: teams_window.csv {0} / teams_copilot.csv {1} / teams_window_raw.txt {2}줄" -f (RowsTxt (Join-Path $dM 'teams_window.csv')), (RowsTxt (Join-Path $dM 'teams_copilot.csv')), ((Rows (Join-Path $dM 'teams_window_raw.txt')) + 1))
# 진단이 읽은 줄은 있는데 수집기가 남긴 행이 0이면, 둘 사이(채팅목록 제외·시각 형식)에서 사라진 것이다.
# 예전에는 이 대조가 없어 진단이 '건강함'으로 보이는데 수집은 0건인 상태를 설명하지 못했다.
$csvRows = 0
try {
    $cp = Join-Path $dM 'teams_window.csv'
    if (Test-Path -LiteralPath $cp) { $csvRows = [math]::Max(0, (@(Get-Content -LiteralPath $cp -Encoding UTF8 | Where-Object { $_.Trim() })).Count - 1) }
} catch {}
$skipP = Join-Path $dM 'teams_window_skipped.txt'
$nSkip = 0
try { if (Test-Path -LiteralPath $skipP) { $nSkip = @(Get-Content -LiteralPath $skipP -Encoding UTF8 | Where-Object { $_.Trim() }).Count } } catch {}
if ($nSkip -gt 0) { W ("  수집기가 '채팅 목록 열'로 보고 제외한 줄: {0}줄 (teams_window_skipped.txt)" -f $nSkip) }
if ($nTime -gt 0 -and $csvRows -eq 0) {
    W '  [!] 이 진단은 시각 패턴을 잡았는데 수집기가 남긴 행은 0입니다 - 둘 사이에서 사라졌습니다.'
    W '      확인: powershell -ExecutionPolicy Bypass -File collect\Get-TeamsWindow.ps1 -KeepChatList'
    W '      (채팅 목록 제외를 끄고 다시 읽습니다. 이걸로 건수가 살아나면 그 판정이 원인입니다.)'
}
$rawP = Join-Path $dM 'teams_window_raw.txt'
if (Test-Path -LiteralPath $rawP) {
    try {
        $rl = @(Get-Content -LiteralPath $rawP -Encoding UTF8 | Where-Object { $_.Trim() })
        $rt = @($rl | Where-Object { $_ -match $reTime }).Count
        W ("    raw 원문 중 시각 패턴 일치: {0}줄 / {1}줄" -f $rt, $rl.Count)
        $k = 0
        foreach ($x in $rl) { if ($x -match '\d') { W ("    raw 예: " + (Mask $x)); $k++; if ($k -ge 5) { break } } }
    } catch {}
}
$uf = Join-Path $dM 'teams_copilot_unavailable.json'
if (Test-Path -LiteralPath $uf) { try { W ("  teams_copilot_unavailable.json: " + ((Get-Content -LiteralPath $uf -Raw -Encoding UTF8).Trim() -replace '\s+', ' ')) } catch {} }
$sampler = 0
try { $sampler = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'powershell%'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'TeamsSampler' }).Count } catch {}
W ("  상시 샘플러(Start-TeamsSampler) 실행: {0}" -f $(if ($sampler) { "예 ($sampler)" } else { '아니오' }))

# ── PC 가동 ──────────────────────────────────────────────────────────────────
# PC 가동 하한은 로드율의 주 추정기인데 그 재료(이벤트 로그·권한·전원 정책)가 PC 마다 다르다.
# 어떤 소스가 막혔는지, 옛 20h 캡 흔적이 남았는지, 항상 켜두는 PC 인지를 사실로 남긴다.
W '[PC 가동]'
$dP = Join-Path $root 'data\pc'
function Probe-Log([hashtable]$flt) {
    try { $e = Get-WinEvent -FilterHashtable $flt -MaxEvents 1 -ErrorAction Stop; return ('ok (최근 ' + $e.TimeCreated.ToString('yyyy-MM-dd HH:mm') + ')') }
    catch {
        $fq = [string]$_.FullyQualifiedErrorId
        if ($fq -like 'NoMatchingEventsFound*') { return '없음 (이벤트 0건 - 감사 정책 꺼짐 또는 로그 밖)' }
        if ($fq -match 'Unauthorized' -or $_.Exception.Message -match 'unauthorized|denied|권한|거부') { return 'unauthorized (관리자 아님 - 잠긴 시간도 켜짐으로 남음)' }
        return ('오류: ' + $_.Exception.Message.Split([char]10)[0].Trim())
    }
}
function Count-Ev([hashtable]$flt) { try { return @(Get-WinEvent -FilterHashtable $flt -MaxEvents 2000 -ErrorAction Stop).Count } catch { return 0 } }
$sysOldest = ''; $reachDays = -1
try { $sysOldest = (Get-WinEvent -LogName System -Oldest -MaxEvents 1 -ErrorAction Stop).TimeCreated.ToString('yyyy-MM-dd'); $reachDays = [int]((Get-Date) - [datetime]$sysOldest).TotalDays } catch {}
$sysLog = $null; try { $sysLog = Get-WinEvent -ListLog System -ErrorAction Stop } catch {}
W ("  System 로그 도달일: {0}{1}{2}" -f $(if ($sysOldest) { $sysOldest } else { '? (읽기 실패)' }), $(if ($reachDays -ge 0) { " (${reachDays}일 전)" } else { '' }),
    $(if ($sysLog) { '   크기 {0:N1}/{1:N1} MB · {2}건' -f ($sysLog.FileSize / 1MB), ($sysLog.MaximumSizeInBytes / 1MB), $sysLog.RecordCount } else { '' }))
$lockP = Probe-Log @{ LogName='Security'; Id=@(4800,4801) }
$diagP = Probe-Log @{ LogName='Microsoft-Windows-Diagnostics-Performance/Operational'; Id=@(100,200) }
W ("  잠금/해제(Security 4800/4801) 접근: {0}" -f $lockP)
W ("  Diag-Perf(100/200) 접근: {0}" -f $diagP)
$d30 = (Get-Date).AddDays(-30)
$nBoot = Count-Ev @{ LogName='System'; Id=@(6005); StartTime=$d30 }
$nShut = Count-Ev @{ LogName='System'; Id=@(6006,1074,6008); StartTime=$d30 }
$nSleep = (Count-Ev @{ LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=@(42,506); StartTime=$d30 })
$nWake = (Count-Ev @{ LogName='System'; ProviderName='Microsoft-Windows-Power-Troubleshooter'; Id=1; StartTime=$d30 }) + (Count-Ev @{ LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=@(507,107); StartTime=$d30 })
W ("  최근 30일 이벤트: 부팅 {0} · 종료 {1} · 절전/대기 진입 {2} · 해제 {3}{4}" -f $nBoot, $nShut, $nSleep, $nWake, $(if ($nBoot -gt 0 -and $nSleep -eq 0 -and $nShut -le 1) { ' ← 절전·종료 없음(항상 켜두는 PC)' } else { '' }))
$boot = $null; try { $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime } catch {}
$upDays = [Environment]::TickCount64 / 86400000.0
$tick32Neg = ([Environment]::TickCount -lt 0)
$hiber = '?'; try { $hiber = [string](Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -ErrorAction Stop).HiberbootEnabled } catch {}
W ("  마지막 부팅: {0}   가동 {1:N1}일(TickCount)   빠른 시작(HiberbootEnabled): {2}{3}" -f $(if ($boot) { $boot.ToString('yyyy-MM-dd HH:mm') } else { '?' }), $upDays, $hiber, $(if ($hiber -eq '1') { ' - 종료해도 TickCount 가 이어짐' } else { '' }))
if ($tick32Neg) { W ("  ※ 가동 24.85~49.7일 구간(int32 TickCount 음수): 2026-09 이전 창 샘플러는 이 구간에서 idle 이 항상 0 으로 기록됨 - 이 버전은 보정됨(아래 idle=0 비율 확인)") }
$powerAvail = ''
try {
    $pa = @(& powercfg /a 2>$null)
    $avail = New-Object System.Collections.Generic.List[string]
    for ($k = 1; $k -lt $pa.Count; $k++) { if (-not $pa[$k].Trim()) { break }; if ($pa[$k] -match 'S[0-4]') { $avail.Add($pa[$k].Trim()) } }
    $powerAvail = ($avail -join ' / ')
} catch {}
if ($powerAvail) { W ("  가용 절전 상태(powercfg /a): {0}" -f $powerAvail) }
$pcOnP = Join-Path $dP 'pc_on.csv'; $spP = Join-Path $dP 'pc_spans.csv'; $srcP = Join-Path $dP 'pc_source.json'
$pcRows = @(); if (Test-Path -LiteralPath $pcOnP) { try { $pcRows = @(Import-Csv -LiteralPath $pcOnP -Encoding UTF8) } catch {} }
$n20 = 0; $nGe20 = 0
foreach ($r in $pcRows) { $v = 0.0; if ([double]::TryParse([string]$r.on_hours, [ref]$v)) { if ($v -ge 20) { $nGe20++ }; if ($v -eq 20) { $n20++ } } }
if ($pcRows.Count) { W ("  pc_on.csv: {0}행 ({1} ~ {2}) · on≥20h {3}행 · on=20h 정확히 {4}행(옛 20h 캡 흔적)" -f $pcRows.Count, $pcRows[0].date, $pcRows[-1].date, $nGe20, $n20) }
else { W ("  pc_on.csv: {0}" -f (RowsTxt $pcOnP)) }
if (Test-Path -LiteralPath $spP) {
    $spRows = @(); try { $spRows = @(Import-Csv -LiteralPath $spP -Encoding UTF8) } catch {}
    $bySrc = (($spRows | Group-Object src | ForEach-Object { '{0} {1}' -f $_.Name, $_.Count }) -join ', ')
    W ("  pc_spans.csv: {0}행 ({1})" -f $spRows.Count, $bySrc)
} else { W '  pc_spans.csv: 없음 (구버전 수집분 - 다음 수집에서 생성)' }
$pcSrc = $null; if (Test-Path -LiteralPath $srcP) { try { $pcSrc = Get-Content -LiteralPath $srcP -Raw -Encoding UTF8 | ConvertFrom-Json } catch {} }
if ($pcSrc) {
    W ("  pc_source.json: lock_events={0} diag_perf={1} live_session={2} always_on_suspect={3} coverage {4}/{5}일 capped={6} (수집 {7})" -f $pcSrc.lock_events, $pcSrc.diag_perf, $pcSrc.live_session, $pcSrc.always_on_suspect, $pcSrc.coverage_days, $pcSrc.range_days, $pcSrc.capped_spans, $pcSrc.generated)
    foreach ($wm in @($pcSrc.warnings)) { if ($wm) { W ("    경고: " + $wm) } }
}

# ── 창 샘플러 ────────────────────────────────────────────────────────────────
# schtasks 기본 등록은 3일 실행 제한(PT72H)으로 조용히 멈춘다 - 작업 설정·프로세스·마지막 샘플·idle 고착을 함께 본다.
W '[창 샘플러]'
$dA = Join-Path $root 'data\activity'
function Task-Info([string]$name) {
    try {
        $svc = New-Object -ComObject 'Schedule.Service'; $svc.Connect()
        $t = $svc.GetFolder('\').GetTask($name)
        $st = @('알 수 없음', '사용 안 함', '대기열', '준비', '실행 중')[[int]$t.State]
        $lrt = '?'; try { $lrt = $t.LastRunTime.ToString('yyyy-MM-dd HH:mm') } catch {}
        # TASK_INSTANCES_POLICY: 0 Parallel · 1 Queue · 2 IgnoreNew · 3 StopExisting
        $mi = @('Parallel', 'Queue', 'IgnoreNew', 'StopExisting')[[int]$t.Definition.Settings.MultipleInstances]
        return [pscustomobject]@{ found=$true; state=$st; etl=[string]$t.Definition.Settings.ExecutionTimeLimit; mi=$mi; last=$lrt; result=[int]$t.LastTaskResult }
    } catch { return [pscustomobject]@{ found=$false } }
}
$tiS = $null
foreach ($tn in @('LoadMonitor22-Sampler', 'LoadMonitor22-TeamsSampler')) {
    $ti = Task-Info $tn
    if ($tn -eq 'LoadMonitor22-Sampler') { $tiS = $ti }
    if ($ti.found) {
        $etlNote = if (-not $ti.etl -or $ti.etl -eq 'PT0S') { 'PT0S(제한 없음)' } else { $ti.etl + ' ← 실행 시간 제한(이 시간 뒤 조용히 정지)' }
        W ("  작업 {0}: 등록됨 · 상태 {1} · 마지막 실행 {2} (결과 {3}) · ExecutionTimeLimit {4} · 겹침 {5}" -f $tn, $ti.state, $ti.last, $ti.result, $etlNote, $ti.mi)
    } else { W ("  작업 {0}: 미등록" -f $tn) }
}
# 샘플러는 `powershell … -File <경로>\Start-ActivitySampler.ps1` 로 뜬다 - 이 문자열을 인자로 품은 다른 셸(진단·테스트)은 세지 않는다
$sp = @(); try { $sp = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'powershell%'" -ErrorAction SilentlyContinue | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match '(?i)-File\s+"?[^"\s]*Start-ActivitySampler\.ps1' }) } catch {}
$spTxt = if ($sp.Count) { (($sp | ForEach-Object { 'pid {0} 시작 {1}' -f $_.ProcessId, $(if ($_.CreationDate) { $_.CreationDate.ToString('MM-dd HH:mm') } else { '?' }) }) -join ', ') } else { '' }
W ("  샘플러 프로세스(Start-ActivitySampler): {0}개 {1}" -f $sp.Count, $spTxt)
$actF = @(); try { $actF = @(Get-ChildItem -LiteralPath $dA -Filter 'activity_*.csv' -ErrorAction Stop | Sort-Object LastWriteTime -Descending) } catch {}
$age = -1; $tot = 0; $zero = 0; $ratio = 0
if ($actF.Count) {
    $lf = $actF[0]
    $lastLine = ''; try { $lastLine = [string](Get-Content -LiteralPath $lf.FullName -Tail 1) } catch {}
    $lastT = $null; if ($lastLine -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') { $lastT = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', $null) }
    if ($lastT) { $age = [int]((Get-Date) - $lastT).TotalMinutes }
    W ("  최신 파일 {0}: 마지막 샘플 {1}{2} · 파일 {3}개 (가장 오래된 {4})" -f $lf.Name, $(if ($lastT) { $lastT.ToString('yyyy-MM-dd HH:mm') } else { '?' }), $(if ($age -ge 0) { " (${age}분 전)" } else { '' }), $actF.Count, $actF[-1].Name)
    # idle=0 비율은 파일(하루) 단위로 본다 - 고착된 하루가 정상 이틀에 섞여 희석되지 않게. 300행 이상인데 98% 이상이면 TickCount 랩 고착.
    $stuckNames = New-Object System.Collections.Generic.List[string]
    foreach ($f in ($actF | Select-Object -First 3)) {
        $ft = 0; $fz = 0
        try {
            foreach ($r in @(Import-Csv -LiteralPath $f.FullName -Encoding UTF8)) {
                $ft++
                $iv = 0.0; if ([double]::TryParse([string]$r.idle_sec, [ref]$iv) -and $iv -eq 0) { $fz++ }
            }
        } catch {}
        $tot += $ft; $zero += $fz
        if ($ft -ge 300 -and $fz * 100.0 / $ft -ge 98) { $stuckNames.Add($f.Name); $ratio = [math]::Max($ratio, [math]::Round(100.0 * $fz / $ft, 1)) }
    }
    if ($tot -and -not $stuckNames.Count) { $ratio = [math]::Round(100.0 * $zero / $tot, 1) }
    W ("  idle=0 비율(최근 {0}개 파일 {1}행): {2}%{3}" -f [math]::Min(3, $actF.Count), $tot, $ratio, $(if ($stuckNames.Count) { ' ← 고착 의심(TickCount 랩 - 모든 샘플이 활동으로 계상): ' + ($stuckNames -join ', ') } else { '' }))
} else { W '  activity_*.csv 없음 (창 샘플러가 한 번도 돌지 않음 - 선택 기능)' }
$elog = Join-Path $dA 'sampler_errors.log'
if (Test-Path -LiteralPath $elog) { try { W ("  sampler_errors.log: {0:N1} KB · 마지막: {1}" -f ((Get-Item -LiteralPath $elog).Length / 1KB), (Mask ([string](Get-Content -LiteralPath $elog -Tail 1)))) } catch {} }

# ── git ──────────────────────────────────────────────────────────────────────
# git 이 PATH 에 없으면 커밋 신호가 조용히 0건이 된다(감사 A2) - 어디에 있는지 찾아 보여준다.
W '[git]'
$cfgObj = $null; try { $cfgObj = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json } catch {}
$gitExeCfg = ''; try { $gitExeCfg = [string]$cfgObj.gitExe } catch {}
$gitPath = ''; try { $gitPath = (Get-Command git.exe -ErrorAction Stop).Source } catch {}
$cands = @("$env:ProgramFiles\Git\cmd\git.exe", "${env:ProgramFiles(x86)}\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe",
    "$env:LOCALAPPDATA\GitHubDesktop\app-*\resources\app\git\cmd\git.exe", "$env:LOCALAPPDATA\Atlassian\SourceTree\git_local\cmd\git.exe",
    "$env:ProgramFiles\Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe",
    "${env:ProgramFiles(x86)}\Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe")
$found = @()
foreach ($c in $cands) { if ($c) { try { $found += @(Get-Item -Path $c -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }) } catch {} } }
W ("  config.gitExe: {0}" -f $(if ($gitExeCfg) { $gitExeCfg + $(if (Test-Path -LiteralPath $gitExeCfg) { ' (존재)' } else { ' (파일 없음!)' }) } else { '(비어 있음 - PATH 탐색)' }))
W ("  PATH 의 git.exe: {0}" -f $(if ($gitPath) { $gitPath } else { '없음' }))
if ($found.Count) { W ("  설치 후보: " + (($found | Select-Object -First 4) -join ' ; ')) }
$gitUse = if ($gitExeCfg -and (Test-Path -LiteralPath $gitExeCfg)) { $gitExeCfg } elseif ($gitPath) { $gitPath } elseif ($found.Count) { $found[0] } else { '' }
$gitVer = ''; if ($gitUse) { try { $gitVer = [string](& $gitUse --version 2>$null) } catch {} }
W ("  사용 가능 git: {0}" -f $(if ($gitUse) { "$gitUse ($gitVer)" } else { '없음 → 커밋 신호 0건' }))
$nRepos = 0; try { $nRepos = @($cfgObj.gitRepos | Where-Object { $_ }).Count } catch {}
W ("  config.gitRepos {0}개 · git_commits.csv {1}" -f $nRepos, (RowsTxt (Join-Path $root 'data\files\git_commits.csv')))

# ── 최근 실행 기록 ─────────────────────────────────────────────────────────
W '[최근 실행]'
$lr = Join-Path $root 'report\last_run.json'
if (Test-Path -LiteralPath $lr) {
    try {
        $j = Get-Content -LiteralPath $lr -Raw -Encoding UTF8 | ConvertFrom-Json
        W ("  기간 {0}  시작 {1}" -f ($j.period -join '~'), $j.started)
        foreach ($s in $j.stages) { if ($s.name -match 'Outlook|팀즈|메일') { W ("  {0} {1}{2}" -f $(if ($s.ok) { 'OK ' } else { 'NG ' }), $s.name, $(if ($s.note) { ' - ' + $s.note } else { '' })) } }
    } catch { W '  last_run.json 해석 실패' }
} else { W '  last_run.json 없음 (아직 실행 전)' }

# ── 판정 ─────────────────────────────────────────────────────────────────────
W '[판정]'
if (-not $classicOk -and $newOl) { $findings.Add('클래식 Outlook 없음(새 Outlook 만) → COM 수집 불가. Windows Search 색인 폴백 → Copilot 메일 수집(config.mailViaCopilot) 순으로 자동 대체됩니다. 새 Outlook 은 색인도 제공하지 않는 경우가 많아 Copilot 경로가 핵심입니다.') }
elseif (-not $classicOk) { $findings.Add('클래식 Outlook 을 찾지 못함 → COM 수집 불가. 색인·Copilot 폴백이 대신 동작합니다.') }
if ($classicOk -and $nProf -eq 0) { $findings.Add('메일 프로필 0개 → COM 기동 시 "Outlook 시작" 마법사가 뜹니다. Outlook 을 직접 실행해 계정 설정을 마치세요.') }
if ($pOl.Count -and $comMsg -notmatch '^붙음') { $findings.Add('클래식 Outlook 이 실행 중인데 COM 에 붙지 못함 → 마법사·프로필 선택·암호 창이 떠 있을 가능성. 그 창을 닫고 메일 화면까지 연 뒤 재수집.') }
if ($classicOk -and $useNew) { $findings.Add('UseNewOutlook 토글 켜짐 → 평소 새 Outlook 을 쓰는 PC. 클래식 Outlook 을 한 번 실행해 두면 COM 으로 붙습니다.') }
if ($idxMail -eq 0 -and (-not $classicOk -or $comMsg -notmatch '^붙음')) { $findings.Add('Windows Search 색인에 최근 30일 Outlook 메일 0건 → COM 이 안 되는 PC 에서는 색인 폴백이 비므로 Copilot 메일 수집이 쓰입니다(제어판 > 색인 옵션에서 Outlook 포함 여부 확인). COM 이 정상인 PC 면 무관합니다.') }
if ((Rows (Join-Path $dO 'mail.csv')) -le 0) { $findings.Add('mail.csv 가 비어 있음 → 메일 수집이 아직 성공한 적 없음.') }
if (-not $tp.Count) { $findings.Add('Teams 프로세스 없음 → Teams 를 켜고 채팅 창을 띄운 뒤 수집하세요(창 읽기 경로).') }
elseif (-not $vis.Count) { $findings.Add('Teams 는 켜져 있지만 창 핸들 0 → 최소화/트레이 상태. 창을 화면에 띄운 상태로 수집하세요(새 Teams 는 WebView2 안에 그려져 보여야 읽힙니다).') }
elseif (-not $texts.Count) { $findings.Add('Teams 창은 있으나 UIA 텍스트 0줄 → 접근성 트리가 비어 있음(보안 정책·앱 버전). Copilot 팀즈 경로(config.teamsViaCopilot) 또는 Graph 를 쓰세요.') }
elseif ($nTime -eq 0 -and $nGen -gt 0) { $findings.Add('Teams 시각 표기가 이 PC 의 지역 설정 형식과 다릅니다(일반 형식 숫자:숫자는 ' + $nGen + '줄 일치) → 수집기가 일반 형식으로 자동 재시도하므로 대개 그대로 수집됩니다. 더 정확히 하려면 Windows 지역 설정(제어판 > 국가 또는 지역 > 형식)을 Teams 표시 언어와 맞추세요.') }
elseif ($nTime -eq 0) { $findings.Add('Teams 텍스트는 읽히는데 시각 패턴이 0줄 → 메시지 영역이 아직 화면에 그려지지 않았거나(대화를 열어 스크롤) 표기 형식이 특수합니다. 조치(이 PC 안에서): 채팅 창을 열어 메시지가 보이는 상태로 다시 실행 → 그래도 0이면 위 "불일치 예"(마스킹)의 형식을 보고 config.teamsTimeRegex 에 지정(docs\설정가이드 §7). 원문을 밖으로 보낼 필요는 없습니다.') }
# PC 가동 · 창 샘플러 · git
if ($nBoot -gt 0 -and $nSleep -eq 0 -and $nShut -le 1 -and $lockP -notlike 'ok*') { $findings.Add('최근 30일 절전·종료 이벤트 없음 + 잠금 이벤트(' + $lockP.Split(' ')[0] + ') → 항상 켜두는 PC 는 켜짐=근무가 되어 과대 위험. 창 샘플러를 등록하세요: powershell -ExecutionPolicy Bypass -File collect\Register-Samplers.ps1') }
if ($reachDays -ge 0 -and $reachDays -lt 45) { $findings.Add("System 로그가 ${reachDays}일 전까지만 남아 있음(롤오버) → 그 이전 PC 가동은 브라우저 방문 힌트·창 샘플러로만 보강됩니다.") }
if ($n20 -gt 0) { $findings.Add("pc_on.csv 에 on=20h 행 ${n20}개(옛 20h 캡 흔적) → 이 버전 수집기로 재수집하면 항상 켜진 날의 기록이 살아납니다.") }
if ($actF.Count -or $tiS.found -or $sp.Count) {
    if (-not $tiS.found) { $findings.Add('창 샘플러 작업(LoadMonitor22-Sampler) 미등록 → 로그온 때마다 수동 시작해야 합니다. 등록: powershell -ExecutionPolicy Bypass -File collect\Register-Samplers.ps1 (관리자 불필요, 실행 시간 제한 없음)') }
    elseif ($tiS.etl -and $tiS.etl -ne 'PT0S') { $findings.Add('창 샘플러 작업에 실행 시간 제한 ' + $tiS.etl + ' → 로그온 3일 뒤 조용히 정지합니다. Register-Samplers.ps1 로 재등록하세요(제한 없음·겹침 무시로 덮어씀).') }
    if ($age -gt 10 -and -not $sp.Count) { $findings.Add("창 샘플러 멈춤(마지막 샘플 ${age}분 전, 프로세스 없음) → 재시작: powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File collect\Start-ActivitySampler.ps1 (등록돼 있으면 schtasks /Run /TN LoadMonitor22-Sampler)") }
    if ($stuckNames.Count) { $findings.Add("창 샘플러 idle=0 고착(${ratio}%, " + ($stuckNames -join ', ') + ") → 구버전 샘플러의 TickCount 랩(가동 " + [math]::Round($upDays, 1) + "일). 샘플러를 이 버전으로 재시작하세요. 분석은 고착일을 PC 하한 모드로 대체합니다.") }
} elseif (-not $tiS.found) { $findings.Add('창 샘플러 미사용(선택) → 켜면 하한 추정 대신 실측이 쓰여 정확도가 크게 오릅니다: powershell -ExecutionPolicy Bypass -File collect\Register-Samplers.ps1') }
if (-not $gitUse) { $findings.Add('git.exe 를 찾지 못함 → 커밋 신호가 0건이 됩니다. Git 설치 후 config.gitExe 에 경로를 적거나 PATH 에 추가하세요(GitHub Desktop·SourceTree 내장 git 경로도 가능).') }
elseif (-not $gitPath -and -not $gitExeCfg) { $findings.Add('git 이 PATH 에 없고 config.gitExe 도 비어 있음(후보 ' + $gitUse + ') → config.gitExe 에 이 경로를 적으세요.') }
if (-not $findings.Count) { $findings.Add('특이사항 없음 - 수집 경로가 막혀 있지 않습니다. 그래도 비면 기간 안에 자료가 없거나 수집 중 오류입니다(last_run.json 의 note 참고).') }
$i = 0
foreach ($f in $findings) { $i++; W ("  {0}. {1}" -f $i, $f) }

try {
    $d = Split-Path -Parent $OutFile
    if ($d -and -not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
    [System.IO.File]::WriteAllLines($OutFile, $L, [System.Text.Encoding]::UTF8)
    Write-Host ("→ 저장: {0}  (채팅·메일 내용은 마스킹됨 - [판정]대로 이 PC 안에서 조치하면 되고, 밖으로 보낼 필요 없음)" -f $OutFile)
} catch { Write-Host ('→ 저장 실패: ' + $_.Exception.Message) }
exit 0
