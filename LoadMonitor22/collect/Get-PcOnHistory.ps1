# Get-PcOnHistory.ps1
# Reconstructs past PC-on periods from the Windows event log (no admin needed):
#   System 6005/6006  = event log service start/stop (boot / shutdown)
#   Kernel-Power 42   = entering sleep · Power-Troubleshooter 1 = wake · Kernel-Power 506/507 = Modern Standby
#   Winlogon 7001/7002 · Kernel-General 12/13 · Kernel-Power 107 · Diag-Perf 100/200 · Security 4800/4801 (잠금 — 권한 필요)
# Output (..\data\pc\):
#   pc_on.csv       date, on_hours, first_on, last_off, night_hours, weekend   (구간의 일별 파생값 - 헤더 불변)
#   pc_spans.csv    start, end, src   (켜짐 구간 원본 - 로컬 시각, 자정 분할 없음, src=event|event-gap|event-cap|live|boot)
#   pc_source.json  lock_events(ok|unauthorized|none) · diag_perf · live_session · warnings[] … (수집 환경 진단)
# 짝 없는 마지막 'on' 이 현재 부팅 세션(LastBootUpTime 이후)이면 20h 캡 없이 '지금까지 켜짐' 으로 잇고 자정 분할한다 -
# 항상 켜두고 잠그기만 하는 데스크톱이 부팅일에만 행을 갖던 결함(감사 A3) 수정. 20h 캡은 종료 이벤트 없이 다음 부팅이
# 나타난 세션(전원 차단·로그 공백)에만 남는다. 잠금(4800/4801)·Diag-Perf 읽기 실패는 숨기지 않고 pc_source.json 에 남긴다.
# The System log usually covers the last 2-6 months - the script prints actual coverage.
# Usage:  .\Get-PcOnHistory.ps1 -From 2026-02-01 -To 2026-07-31   (or -Days 120)
#   테스트(이벤트 로그 대신 합성 이벤트): -EventsCsv ev.csv(t,kind[,src]) -Now '2026-06-05 18:30' -BootTime '2026-06-01 08:00' -OutDir <폴더>
param(
    [string]$From = '',
    [string]$To = '',
    [int]$Days = 120,
    [string]$OutDir = '',        # 출력 폴더 대체 (기본 ..\data\pc) - 테스트용
    [string]$EventsCsv = '',     # 이벤트 로그 대신 읽을 CSV (t,kind[,src]) - 테스트용
    [string]$Now = '',           # '지금' 대체 (yyyy-MM-dd HH:mm[:ss]) - 테스트용
    [string]$BootTime = ''       # LastBootUpTime 대체 - 테스트용
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $OutDir) { $OutDir = Join-Path $root 'data\pc' }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null }

function Parse-Dt([string]$s) {
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    return [datetime]::ParseExact($s.Trim(), [string[]]@('yyyy-MM-dd HH:mm', 'yyyy-MM-dd HH:mm:ss', 'yyyy-MM-dd'), $inv, [System.Globalization.DateTimeStyles]::None)
}

if ($From) { $since = [datetime]::ParseExact($From, 'yyyy-MM-dd', $null) } else { $since = (Get-Date).Date.AddDays(-$Days) }
if ($To)   { $until = ([datetime]::ParseExact($To, 'yyyy-MM-dd', $null)).AddDays(1) } else { $until = (Get-Date).Date.AddDays(1) }
$nowT = if ($Now) { Parse-Dt $Now } else { Get-Date }
$bootNow = $null
if ($BootTime) { $bootNow = Parse-Dt $BootTime }
else { try { $bootNow = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime } catch {} }

Write-Host ("[pc-on] querying event log {0} .. {1}" -f $since.ToString('yyyy-MM-dd'), $until.ToString('yyyy-MM-dd'))

# 이벤트 분류: boot = 전원 켜짐(부팅) 계열 - 켜짐 중에 또 나타나면 앞 세션의 종료 이벤트가 유실된 것.
#              sleep/shutdown 계열이 기간 내 하나도 없으면 '항상 켜두는 PC' 로 본다.
$BOOT_IDS  = @(6005, 12, 100)
$SLEEP_IDS = @(42, 506, 6006, 13, 1074, 6008, 200)
$events = New-Object System.Collections.Generic.List[object]
$srcStatus = [ordered]@{}
$mySid = ''
try { $mySid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value } catch {}

function Read-Src([hashtable]$filter, [scriptblock]$kindOf, [bool]$perUser = $false) {
    # 반환: ok | none | unauthorized | error: … (조용히 삼키지 않는다 - pc_source.json 에 기록)
    try {
        $got = 0
        Get-WinEvent -FilterHashtable $filter -ErrorAction Stop | ForEach-Object {
            $ev = $_
            if ($perUser -and $mySid) {
                # 로그온/로그오프(7001/7002)는 이 PC 의 모든 세션이 남긴다 - 다른 사용자의 로그오프가 내 구간을 닫지 않게
                try {
                    $x = [xml]$ev.ToXml()
                    $sidNode = $x.Event.EventData.Data | Where-Object { $_.Name -eq 'UserSid' } | Select-Object -First 1
                    if ($sidNode -and $sidNode.'#text' -and $sidNode.'#text' -ne $mySid) { return }
                } catch {}
            }
            $events.Add([pscustomobject]@{ t = $ev.TimeCreated; kind = (& $kindOf $ev.Id); src = [string]$ev.Id; boot = ($BOOT_IDS -contains $ev.Id) })
            $got++
        }
        if ($got) { return 'ok' } else { return 'none' }
    } catch {
        $fq = [string]$_.FullyQualifiedErrorId
        if ($fq -like 'NoMatchingEventsFound*') { return 'none' }
        if ($fq -match 'Unauthorized' -or ($_.Exception -is [System.UnauthorizedAccessException]) -or
            $_.Exception.Message -match 'unauthorized|denied|권한|거부') { return 'unauthorized' }
        return ('error: ' + $_.Exception.Message.Split([char]10)[0].Trim())
    }
}

if ($EventsCsv) {
    # 합성 이벤트(테스트) - t,kind[,src]
    foreach ($r in @(Import-Csv -LiteralPath $EventsCsv)) {
        if (-not $r.t -or -not $r.kind) { continue }
        $t = Parse-Dt ([string]$r.t)
        if ($t -lt $since -or $t -ge $until) { continue }
        $k = ([string]$r.kind).Trim().ToLower()
        $s = if ($r.src) { [string]$r.src } else { $(if ($k -eq 'on') { '6005' } else { '6006' }) }
        $isBoot = ($s -eq 'boot') -or (($s -match '^\d+$') -and ($BOOT_IDS -contains [int]$s))
        $events.Add([pscustomobject]@{ t = $t; kind = $k; src = $s; boot = $isBoot })
    }
    $srcStatus['synthetic'] = 'ok'
} else {
    $srcStatus['boot_6005_6006'] = Read-Src @{ LogName='System'; Id=@(6005,6006); StartTime=$since; EndTime=$until } { param($id) if ($id -eq 6005) { 'on' } else { 'off' } }
    $srcStatus['sleep_42'] = Read-Src @{ LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=42; StartTime=$since; EndTime=$until } { param($id) 'off' }
    $srcStatus['wake_1'] = Read-Src @{ LogName='System'; ProviderName='Microsoft-Windows-Power-Troubleshooter'; Id=1; StartTime=$since; EndTime=$until } { param($id) 'on' }
    # Modern Standby 노트북은 6005/6006(부팅/종료)이 거의 안 남는다 - 실측 'PC 가동 없음'의 주원인.
    # Kernel-Power 506/507 = Modern Standby 진입/이탈, 1074/6008 = 종료/비정상 종료.
    $srcStatus['modern_standby_506_507'] = Read-Src @{ LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=@(506,507); StartTime=$since; EndTime=$until } { param($id) if ($id -eq 506) { 'off' } else { 'on' } }
    $srcStatus['shutdown_1074_6008'] = Read-Src @{ LogName='System'; Id=@(1074,6008); StartTime=$since; EndTime=$until } { param($id) 'off' }
    # 회사 PC는 System 로그가 빨리 롤오버돼 과거가 통째로 빈다(실측 '기간 3개월에 2건') -
    # 남아 있는 다른 소스를 전부 긁는다: 로그온/로그오프, OS 시작/종료, 절전 해제, 부팅 채널.
    $srcStatus['logon_7001_7002'] = Read-Src @{ LogName='System'; ProviderName='Microsoft-Windows-Winlogon'; Id=@(7001,7002); StartTime=$since; EndTime=$until } { param($id) if ($id -eq 7001) { 'on' } else { 'off' } } $true
    $srcStatus['os_12_13'] = Read-Src @{ LogName='System'; ProviderName='Microsoft-Windows-Kernel-General'; Id=@(12,13); StartTime=$since; EndTime=$until } { param($id) if ($id -eq 12) { 'on' } else { 'off' } }
    $srcStatus['resume_107'] = Read-Src @{ LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=107; StartTime=$since; EndTime=$until } { param($id) 'on' }
    # 별도 채널 - System 이 롤오버돼도 여기는 수개월 남는 경우가 많다 (부팅 100 / 종료 200). 관리자가 아니면 못 읽는 PC 가 있다.
    $srcStatus['diag_perf_100_200'] = Read-Src @{ LogName='Microsoft-Windows-Diagnostics-Performance/Operational'; Id=@(100,200); StartTime=$since; EndTime=$until } { param($id) if ($id -eq 100) { 'on' } else { 'off' } }
    # 잠금/해제(Security 4800/4801) - 권한이 있으면 가장 정확한 근무 구간. 없으면 '없음' 이 아니라 'unauthorized' 로 남긴다.
    $srcStatus['lock_4800_4801'] = Read-Src @{ LogName='Security'; Id=@(4800,4801); StartTime=$since; EndTime=$until } { param($id) if ($id -eq 4801) { 'on' } else { 'off' } }
}
$lockStatus = if ($srcStatus.Contains('lock_4800_4801')) { [string]$srcStatus['lock_4800_4801'] } else { 'none' }
$diagStatus = if ($srcStatus.Contains('diag_perf_100_200')) { [string]$srcStatus['diag_perf_100_200'] } else { 'none' }
Write-Host ("[pc-on] sources: " + (($srcStatus.GetEnumerator() | ForEach-Object { '{0}={1}' -f $_.Key, $_.Value }) -join ' · '))

$warnings = New-Object System.Collections.Generic.List[string]
$fallbackBoot = $false
if ($events.Count -eq 0) {
    Write-Host '[pc-on] no events found in range (log may not reach that far back).'
    # 최후 폴백: 이벤트 로그가 비어도(권한/롤오버/Modern Standby) 현재 부팅 이후 구간만은 기록한다
    if ($bootNow -and $bootNow -lt $until) {
        $bs = if ($bootNow -gt $since) { $bootNow } else { $since }
        $events.Add([pscustomobject]@{ t = $bs; kind = 'on'; src = 'boot'; boot = $true })
        $fallbackBoot = $true
        Write-Host ("[pc-on] fallback: current boot session since {0}" -f $bs.ToString('yyyy-MM-dd HH:mm'))
        Write-Host '[pc-on] TIP: 과거 이력까지 정확하려면 창 샘플러(Start-ActivitySampler.ps1)를 켜 두세요.'
    }
}
$sorted = @($events | Sort-Object t)
$covDays = 0; $rangeDays = [math]::Max(1, [int]($until.Date - $since.Date).TotalDays); $reachStart = ''
if ($sorted.Count -gt 0 -and -not $fallbackBoot) {
    # 커버리지 진단 - '기간을 못 찾는' 상황을 숨기지 않는다. 이벤트가 있어도 기간 앞부분이
    # 통째로 비면(롤오버) 브라우저 힌트(Get-PcOnHints.py)가 이어서 보강한다.
    $covDays = @($sorted | ForEach-Object { $_.t.Date } | Sort-Object -Unique).Count
    $reachStart = $sorted[0].t.ToString('yyyy-MM-dd')
    Write-Host ("[pc-on] events: {0}, coverage {1}/{2}일, 도달 시작 {3}" -f $sorted.Count, $covDays, $rangeDays, $reachStart)
    if ($covDays * 2 -lt $rangeDays) {
        $w = '이벤트 로그가 기간의 절반도 못 덮습니다(롤오버) - 브라우저 사용기록 힌트로 보강합니다.'
        Write-Host ("[pc-on] 주의: " + $w); $warnings.Add($w)
    }
}

# build on-spans: 'on' opens, 'off' closes. 켜짐 중의 부팅(boot) = 앞 세션 종료 유실(전원 차단·로그 공백) → 그 부팅 시각
# (20h 를 넘으면 20h 캡)에서 닫는다. 같은 부팅의 12/6005/100 은 몇 분 간격으로 잇따르므로 30분 안의 boot 는 같은 부팅으로 본다.
$spans = New-Object System.Collections.Generic.List[object]
$open = $null
$capped = 0      # 20h 로 잘린 구간 수
$gapClosed = 0   # 종료 이벤트 없이 다음 부팅에서 닫힌 구간 수 (끝 시각 불확실)
foreach ($e in $sorted) {
    if ($e.kind -eq 'on') {
        if ($null -eq $open) { $open = $e.t }
        elseif ($e.boot -and ($e.t - $open).TotalMinutes -gt 30) {
            $b = $e.t; $lab = 'event-gap'; $gapClosed++
            if (($b - $open).TotalHours -gt 20) { $b = $open.AddHours(20); $lab = 'event-cap'; $capped++ }
            $spans.Add([pscustomobject]@{ a = $open; b = $b; src = $lab })
            $open = $e.t
        }
    } else {
        if ($null -ne $open) {
            if ($e.t -gt $open) { $spans.Add([pscustomobject]@{ a = $open; b = $e.t; src = 'event' }) }
            $open = $null
        }
    }
}
$live = $false
if ($null -ne $open) {
    # 짝 없는 마지막 on: 기간 끝(-To 가 과거면 그 자정)과 지금 중 이른 쪽까지.
    # 현재 부팅 세션(LastBootUpTime 이후의 on)이면 캡 없이 '지금까지 켜짐' - 항상 켜두는 데스크톱의 며칠이 통째로 살아난다.
    $end = if ($nowT -lt $until) { $nowT } else { $until }
    $isLive = ($null -ne $bootNow) -and ($open -ge $bootNow.AddMinutes(-10))
    if ($end -gt $open) {
        if ($isLive) {
            $spans.Add([pscustomobject]@{ a = $open; b = $end; src = $(if ($fallbackBoot) { 'boot' } else { 'live' }) }); $live = $true
        } else {
            $b = $end
            if (($b - $open).TotalHours -gt 20) { $b = $open.AddHours(20) }
            $spans.Add([pscustomobject]@{ a = $open; b = $b; src = 'event-cap' }); $capped++
        }
    }
}
# 1분 미만 조각 제거 + 겹침 병합(정렬) - 어떤 이벤트 순서에서도 구간이 서로 겹치지 않게 (하루 on ≤ 24h 보장)
$clean = New-Object System.Collections.Generic.List[object]
foreach ($s in @($spans | Where-Object { ($_.b - $_.a).TotalMinutes -ge 1 } | Sort-Object a)) {
    if ($clean.Count -gt 0 -and $s.a -le $clean[$clean.Count - 1].b) {
        $last = $clean[$clean.Count - 1]
        if ($s.b -gt $last.b) { $last.b = $s.b }
        if ($s.src -eq 'live') { $last.src = 'live' }
    } else {
        $clean.Add([pscustomobject]@{ a = $s.a; b = $s.b; src = $s.src })
    }
}
$spans = $clean

# 진단: 켜짐(부팅) 이벤트는 있는데 절전·종료 이벤트가 하나도 없으면 '항상 켜두는 PC' - 잠금 이벤트 없이는 켜짐=근무가 된다
$nSleep = @($sorted | Where-Object { ($_.src -match '^\d+$') -and ($SLEEP_IDS -contains [int]$_.src) }).Count
$nBoot = @($sorted | Where-Object { $_.boot }).Count
$alwaysOn = ($nBoot -gt 0 -and $nSleep -eq 0 -and -not $fallbackBoot -and $rangeDays -ge 2)
if ($lockStatus -eq 'unauthorized') {
    $w = '잠금/해제(Security 4800/4801) 이벤트를 읽을 권한이 없습니다 - 잠긴 시간도 켜짐으로 남습니다.'
    Write-Host ("[pc-on] " + $w); $warnings.Add($w)
}
if ($alwaysOn) {
    $w = '절전·종료 이벤트 없음(항상 켜두는 PC) - 정확한 근무 구간은 창 샘플러(Start-ActivitySampler.ps1) 필요.'
    Write-Host ("[pc-on] " + $w); $warnings.Add($w)
}
if ($diagStatus -like 'unauthorized*' -or $diagStatus -like 'error*') {
    Write-Host ("[pc-on] Diagnostics-Performance 채널 읽기 불가({0}) - System 로그 롤오버 시 과거 부팅 기록을 보강하지 못합니다." -f $diagStatus)
}

# split spans at midnight, aggregate per day (night = 08:00 이전 · 19:00 이후 - extract 의 dayWindow 기본과 같은 경계)
$daily = @{}
foreach ($s in $spans) {
    $a = $s.a; $b = $s.b
    $cur = $a
    while ($cur -lt $b) {
        $dayEnd = $cur.Date.AddDays(1)
        $segEnd = if ($b -lt $dayEnd) { $b } else { $dayEnd }
        $key = $cur.Date.ToString('yyyy-MM-dd')
        if (-not $daily.ContainsKey($key)) {
            $daily[$key] = @{ on=0.0; night=0.0; first=$cur; last=$segEnd }
        }
        $h = ($segEnd - $cur).TotalHours
        $daily[$key].on += $h
        if ($cur -lt $daily[$key].first) { $daily[$key].first = $cur }
        if ($segEnd -gt $daily[$key].last) { $daily[$key].last = $segEnd }
        # night portion: before 08:00 or after 19:00
        $m8  = $cur.Date.AddHours(8); $m19 = $cur.Date.AddHours(19)
        $nightA = if ($cur -lt $m8) { [math]::Min($segEnd.Ticks, $m8.Ticks) } else { $cur.Ticks }
        if ($cur -lt $m8) { $daily[$key].night += ([datetime]$nightA - $cur).TotalHours }
        if ($segEnd -gt $m19) {
            $st = if ($cur -gt $m19) { $cur } else { $m19 }
            $daily[$key].night += ($segEnd - $st).TotalHours
        }
        $cur = $dayEnd
    }
}

$rows = New-Object System.Collections.Generic.List[string]
$rows.Add('date,on_hours,first_on,last_off,night_hours,weekend')
foreach ($k in ($daily.Keys | Sort-Object)) {
    $d = $daily[$k]
    $dow = ([datetime]$k).DayOfWeek
    $we = if ($dow -eq 'Saturday' -or $dow -eq 'Sunday') { 1 } else { 0 }
    # 자정으로 끝난 구간은 '24:00' - '00:00' 으로 쓰면 문자열 비교에서 가장 이른 시각이 돼
    # 병합(Get-PcOnHints)에서 마지막 사용 시각이 영원히 반영되지 않는다
    $lastStr = if ($d.last.Date -gt ([datetime]$k).Date) { '24:00' } else { $d.last.ToString('HH:mm') }
    $rows.Add(('{0},{1},{2},{3},{4},{5}' -f $k, [math]::Round($d.on,2), `
        $d.first.ToString('HH:mm'), $lastStr, [math]::Round($d.night,2), $we))
}
[System.IO.File]::WriteAllLines((Join-Path $OutDir 'pc_on.csv'), $rows, [System.Text.Encoding]::UTF8)

# 구간 원본 - extract 가 '언제 켜져 있었는지' 를 직접 쓴다(점심·회의 시간과의 겹침 계산). Get-PcOnHints 가 힌트 구간(src=hint)을 보탠다.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$srows = New-Object System.Collections.Generic.List[string]
$srows.Add('start,end,src')
foreach ($s in $spans) { $srows.Add(('{0},{1},{2}' -f $s.a.ToString('yyyy-MM-dd HH:mm:ss'), $s.b.ToString('yyyy-MM-dd HH:mm:ss'), $s.src)) }
[System.IO.File]::WriteAllLines((Join-Path $OutDir 'pc_spans.csv'), $srows, $utf8NoBom)

# 수집 환경 진단 - 권한·전원 정책 차이를 사람 차이로 읽지 않게 리포트·진단이 참조한다
$srcInfo = [ordered]@{
    generated = $nowT.ToString('yyyy-MM-dd HH:mm')
    range = @($since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'))
    lock_events = $lockStatus
    diag_perf = $diagStatus
    live_session = [bool]$live
    boot_time = $(if ($bootNow) { $bootNow.ToString('yyyy-MM-dd HH:mm') } else { '' })
    events = [int]$sorted.Count
    boot_events = [int]$nBoot
    sleep_shutdown_events = [int]$nSleep
    always_on_suspect = [bool]$alwaysOn
    fallback_boot = [bool]$fallbackBoot
    coverage_days = [int]$covDays
    range_days = [int]$rangeDays
    reach_start = $reachStart
    capped_spans = [int]$capped
    gap_closed_spans = [int]$gapClosed
    spans = [int]$spans.Count
    days = [int]($rows.Count - 1)
    sources = $srcStatus
    warnings = @($warnings)
}
try {
    [System.IO.File]::WriteAllText((Join-Path $OutDir 'pc_source.json'), ($srcInfo | ConvertTo-Json -Depth 5), $utf8NoBom)
} catch { Write-Host ('[pc-on] pc_source.json 저장 실패: ' + $_.Exception.Message) }
Write-Host ("[pc-on] days written: {0} (spans {1}, live={2}, gap-closed={3}, capped={4})" -f ($rows.Count - 1), $spans.Count, $live, $gapClosed, $capped)
