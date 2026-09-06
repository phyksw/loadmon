# Get-OutlookData.ps1
# Read-only export of Outlook calendar + mail metadata via COM (works without Graph API).
# Mail/calendar history reaches back YEARS (cached OST) - main source for retrospective analysis.
# Output: ..\data\outlook\calendar.csv , mail.csv (UTF-8) + coverage.json (달별 수집 완료 표)
# Usage:  .\Get-OutlookData.ps1 -From 2026-01-01 -To 2026-06-30 [-BudgetSec 360] [-Force]   (or -Days 90)
#
# 달 단위 이어서 수집(LM22 2차): 기간을 달로 쪼개 **최신 달부터** 읽고, 달 하나를 다 읽을 때마다 CSV 와
#   coverage.json 을 쓴다. 시간 예산(-BudgetSec)에 닿으면 거기서 멈추되, 다 읽은 달은 다음 실행에서
#   건너뛰므로 실행을 거듭하면 기간 전체가 채워진다. 예전에는 매번 최신순으로 처음부터 읽다가 예산에
#   닿으면 오래된 달이 **영영** 빠졌다(실측 제보: '주간 활동이 1월부터 안 나온다' - 1~5월 메일·회의 공백).
#   최신 2개월은 매번 다시 읽는다(새 메일·일정 변경). -Force 면 전부 다시 읽는다.
#   기존 CSV 의 다른 달 행은 그대로 보존하고 KeepDays(400일)보다 오래된 행만 버린다.
# 중간 저장: 달마다 CSV 를 다시 쓰므로 강제 종료돼도 그때까지 읽은 달이 남는다(mail.csv.part 는 더 쓰지 않는다).
# 일정은 예산의 절반까지만 쓴다(메일이 굶지 않게) - 남은 달은 역시 다음 실행이 잇는다.
# storeMailSubject: 키가 없으면 true(다른 세 경로와 동일). false 면 제목·일정 제목을 비우고 conversation 도
#   원문 대신 짧은 해시로 남긴다(회신 이력 판정만 유지).
# -SelfTest N: Outlook 없이 달마다 N건의 가짜 메일·일정을 만들어 예산·이어서 수집·병합 논리를 검증한다(테스트 전용).
param(
    [string]$From = '',
    [string]$To = '',
    [int]$Days = 90,
    [int]$BudgetSec = 360,
    [switch]$Force,
    [int]$KeepDays = 400,
    [int]$SelfTest = 0,
    [int]$SelfTestDelayMs = 0
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$sw = [System.Diagnostics.Stopwatch]::StartNew()       # 시간 예산은 COM 연결까지 포함해 잰다(run.py 의 시계와 같다)
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$cfg  = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json
$storeSubject = $true
if ($cfg -and $cfg.PSObject.Properties['storeMailSubject'] -and -not $cfg.storeMailSubject) { $storeSubject = $false }
if ($BudgetSec -le 0) { $BudgetSec = 360 }
if ($KeepDays -le 0) { $KeepDays = 400 }
# 테스트 전용(run.py 를 거쳐도 자가검증을 돌릴 수 있게) - LM_COPILOT_STUB 과 같은 관례
if ($SelfTest -le 0 -and $env:LM_OUTLOOK_SELFTEST) { try { $SelfTest = [int]$env:LM_OUTLOOK_SELFTEST } catch {} }
if ($SelfTestDelayMs -le 0 -and $env:LM_OUTLOOK_SELFTEST_DELAY_MS) { try { $SelfTestDelayMs = [int]$env:LM_OUTLOOK_SELFTEST_DELAY_MS } catch {} }
$outDir = Join-Path $root 'data\outlook'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$mailP = Join-Path $outDir 'mail.csv'
$calP  = Join-Path $outDir 'calendar.csv'
$covP  = Join-Path $outDir 'coverage.json'
$MAIL_HEADER = 'box,time,sender,subject,conversation,rcv'
$CAL_HEADER  = 'start,end,all_day,busy_status,subject,categories,location,response,meeting_status'
$REFRESH_MONTHS = 2          # 최신 N개월은 이미 읽었어도 매번 다시 읽는다

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}
function Conv-Token([string]$s) {
    # storeMailSubject=false 일 때 conversation 열의 대체값 - 원문 대신 짧은 해시(회신 이력 판정만 유지).
    # 정규화(공백 접기·trim·소문자)와 SHA1 앞 10자리는 웹·Copilot·색인 경로와 같은 규칙이다.
    $n = (([string]$s -replace '\s+', ' ').Trim()).ToLower()
    if (-not $n) { return '' }
    $sha = [System.Security.Cryptography.SHA1]::Create()
    try { $h = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($n)) } finally { $sha.Dispose() }
    return '#' + ((($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 10))
}
function Test-MeInList([string]$list, [string[]]$ids) {
    # To/CC 표시 문자열("홍길동; 김철수 <kim@corp.com>") 에 내 이름·주소가 한 항목으로 있는가
    if (-not $list) { return $false }
    foreach ($tok in ($list -split ';')) {
        $t = $tok.Trim().ToLower()
        if (-not $t) { continue }
        foreach ($mid in $ids) {
            if (-not $mid) { continue }
            if ($t -eq $mid -or $t.EndsWith('<' + $mid + '>') -or $t.EndsWith('(' + $mid + ')') -or $t.StartsWith($mid + ' <')) { return $true }
        }
    }
    return $false
}

if ($From) { $since = [datetime]::ParseExact($From, 'yyyy-MM-dd', $null) } else { $since = (Get-Date).Date.AddDays(-$Days) }
if ($To)   { $until = ([datetime]::ParseExact($To, 'yyyy-MM-dd', $null)).AddDays(1) } else { $until = (Get-Date).Date.AddDays(1) }
if ($until -le $since) { $until = $since.AddDays(1) }
$fmt = 'g'  # locale short date+time, what Outlook Restrict expects
$ol = $null

# ── 달 목록: 기간과 겹치는 달을 최신 달부터. 각 달의 [start, end) 는 기간에 맞춰 자른다 ─────────────
$months = New-Object System.Collections.Generic.List[object]
$mCur = New-Object DateTime ($since.Year, $since.Month, 1)
while ($mCur -lt $until) {
    $mNext = $mCur.AddMonths(1)
    $ws = $mCur; if ($ws -lt $since) { $ws = $since }
    $we = $mNext; if ($we -gt $until) { $we = $until }
    $months.Add([pscustomobject]@{ key = $mCur.ToString('yyyy-MM'); start = $ws; end = $we })
    $mCur = $mNext
}
$months.Reverse()          # 최신 달 먼저
$monthKeys = @($months | ForEach-Object { $_.key })

# ── 지난 실행의 달별 수집 완료 표 ──────────────────────────────────────────────
function Load-Coverage {
    $c = @{ mail = @{}; calendar = @{} }
    if (-not (Test-Path $covP)) { return $c }
    try {
        $j = Get-Content -Raw -Encoding UTF8 $covP | ConvertFrom-Json
        foreach ($kind in @('mail', 'calendar')) {
            $sec = $j.PSObject.Properties[$kind]
            if (-not $sec -or -not $sec.Value) { continue }
            foreach ($p in $sec.Value.PSObject.Properties) {
                if ($p.Name -match '^\d{4}-\d{2}$') {
                    $rows = 0; $when = ''
                    try { $rows = [int]$p.Value.rows } catch {}
                    try { $when = [string]$p.Value.when } catch {}
                    $c[$kind][$p.Name] = @{ rows = $rows; when = $when }
                }
            }
        }
    } catch { Write-Host ("[outlook] coverage.json 을 읽지 못해 처음부터 읽습니다: {0}" -f $_.Exception.Message) }
    return $c
}
function Save-Coverage($c) {
    try {
        $o = [ordered]@{ version = 1; keep_days = $KeepDays; when = (Get-Date).ToString('yyyy-MM-dd HH:mm'); mail = [ordered]@{}; calendar = [ordered]@{} }
        foreach ($kind in @('mail', 'calendar')) {
            foreach ($k in ($c[$kind].Keys | Sort-Object -Descending)) {
                $o[$kind][$k] = [ordered]@{ rows = [int]$c[$kind][$k].rows; when = [string]$c[$kind][$k].when }
            }
        }
        ($o | ConvertTo-Json -Depth 4) | Set-Content -Path $covP -Encoding UTF8
    } catch { Write-Host ("[outlook] coverage.json 저장 실패: {0}" -f $_.Exception.Message) }
}

# ── 기존 CSV 를 달별로 나눠 든다(행은 원문 그대로) - 다시 읽는 달만 바꾸고 나머지는 보존 ────────────
function Load-CsvByMonth([string]$path, [string]$header, [int]$timeCol) {
    # timeCol: 시각 열 위치(0부터). 앞 열들에는 쉼표가 없다(box 는 inbox/sent, start 는 시각) - 정규식으로 충분하다
    $by = @{}
    if (-not (Test-Path $path)) { return $by }
    $cut = (Get-Date).Date.AddDays(-$KeepDays)
    $re = '^' + ('[^,]*,' * $timeCol) + '(\d{4})-(\d{2})-(\d{2})'
    $n = 0
    foreach ($line in [System.IO.File]::ReadAllLines($path)) {
        $n++
        if ($n -eq 1) { continue }                          # 머리말
        if (-not $line) { continue }
        $m = [regex]::Match($line, $re)
        if (-not $m.Success) { continue }                   # 형식이 어긋난 행은 버린다(구판 헤더 등)
        $d = $null
        try { $d = New-Object DateTime ([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value) } catch { continue }
        if ($d -lt $cut) { continue }                       # KeepDays 보다 오래된 행은 버린다
        $k = $m.Groups[1].Value + '-' + $m.Groups[2].Value
        if (-not $by.ContainsKey($k)) { $by[$k] = New-Object System.Collections.Generic.List[string] }
        $by[$k].Add($line)
    }
    return $by
}
function Write-CsvByMonth([string]$path, [string]$header, $by) {
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add($header)
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($k in ($by.Keys | Sort-Object -Descending)) {
        foreach ($line in $by[$k]) {
            if ($seen.Add($line)) { $lines.Add($line) }    # 달 경계에 걸친 일정 등 중복은 한 번만
        }
    }
    $tmp = $path + '.tmp'
    [System.IO.File]::WriteAllLines($tmp, $lines, [System.Text.Encoding]::UTF8)
    Move-Item -LiteralPath $tmp -Destination $path -Force
    return ($lines.Count - 1)
}

$cov = Load-Coverage
if ($Force) { $cov = @{ mail = @{}; calendar = @{} } }
$mailBy = Load-CsvByMonth $mailP $MAIL_HEADER 1
$calBy  = Load-CsvByMonth $calP  $CAL_HEADER  0
# 지난 표에 '완료'로 남았는데 CSV 에 그 달 행이 하나도 없으면 표를 믿지 않는다(파일만 지운 경우)
foreach ($kind in @('mail', 'calendar')) {
    $by = $(if ($kind -eq 'mail') { $mailBy } else { $calBy })
    foreach ($k in @($cov[$kind].Keys)) {
        if (-not $by.ContainsKey($k) -and [int]$cov[$kind][$k].rows -gt 0) { $cov[$kind].Remove($k) }
    }
}
function Months-ToRead([string]$kind) {
    # 읽는 순서: ① 최신 달(새 메일이 붙는 달) → ② 아직 못 읽은 달(최신→과거) → ③ 나머지 재수집 달.
    # 못 읽은 달을 재수집 달보다 앞에 둔다 - 재수집 달을 먼저 읽으면 예산이 거기서 다 닳아 실행을 거듭해도
    # 옛 달에 영영 못 간다(자가검증에서 실측). 최신 달은 보통 며칠분이라 가볍다.
    $out = New-Object System.Collections.Generic.List[object]
    $added = @{}
    if ($Force) {
        foreach ($mo in $months) { $out.Add($mo); $added[$mo.key] = $true }
        return $out
    }
    if ($months.Count -gt 0) { $out.Add($months[0]); $added[$months[0].key] = $true }
    foreach ($mo in $months) {
        if (-not $added.ContainsKey($mo.key) -and -not $cov[$kind].ContainsKey($mo.key)) { $out.Add($mo); $added[$mo.key] = $true }
    }
    $i = 0
    foreach ($mo in $months) {
        if ($i -lt $REFRESH_MONTHS -and -not $added.ContainsKey($mo.key)) { $out.Add($mo); $added[$mo.key] = $true }
        $i++
    }
    return $out
}
$mailTodo = Months-ToRead 'mail'
$calTodo  = Months-ToRead 'calendar'
Write-Host ("[outlook] 기간 {0} ~ {1} · {2}개월 · 읽을 달: 메일 {3} / 일정 {4} (완료된 달은 건너뜀{5}) · 예산 {6}초" -f `
    $since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'), $months.Count, $mailTodo.Count, $calTodo.Count, `
    $(if ($Force) { ' - Force 로 전부 다시' } else { '' }), $BudgetSec)

# ── 버전 강건성: 2016/2019/2021/365 '클래식' Outlook 은 전부 동일한 COM(Outlook.Application)
# 을 쓰므로 버전 구분이 필요 없다. 문제는 '새 Outlook'(olk.exe) - COM 인터페이스 자체가 없어
# 어떤 버전 표기든 수집이 통째로 빈다(실측: 'PC마다 메일 누락'의 주원인 후보).
$newOutlook = $false
if (-not $SelfTest) {
    try {
        # 공식 위치는 Office\16.0\Outlook\Preferences - 구형 경로도 함께 본다
        foreach ($rp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
            $pref = Get-ItemProperty -Path $rp -ErrorAction SilentlyContinue
            if ($pref -and $pref.UseNewOutlook -eq 1) { $newOutlook = $true }
        }
    } catch {}
    if (Get-Process olk -ErrorAction SilentlyContinue) { $newOutlook = $true }
    if ($newOutlook) {
        Write-Host '[outlook] 주의: "새 Outlook" 사용이 감지되었습니다 - 새 Outlook 은 데이터 접근(COM)을 제공하지 않습니다.'
        Write-Host '          클래식 Outlook 을 함께 두면 됩니다: 새 Outlook 우상단 [새 Outlook] 토글을 끄거나,'
        Write-Host '          클래식 Outlook(2016~365)을 실행해 두고 다시 수집하세요. (계속 시도합니다)'
    }
}

# 건너뛴/실패한 사유를 남긴다 - 대시보드가 이것을 읽어 '메일 0건'의 이유를 말해 준다.
# 없으면 화면은 "Outlook 을 켜세요"라고만 하는데, 마법사에 막힌 PC 는 이미 켜져 있어
# 그 안내가 오히려 원인을 가린다(실측).
function Set-SkipReason([string]$reason) {
    try {
        $f = Join-Path $outDir 'outlook_skip.json'
        $o = [ordered]@{ reason = $reason; when = (Get-Date).ToString('yyyy-MM-dd HH:mm') }
        ($o | ConvertTo-Json -Compress) | Set-Content -Path $f -Encoding UTF8
    } catch {}
}
function Clear-SkipReason {
    try { Remove-Item (Join-Path $outDir 'outlook_skip.json') -ErrorAction SilentlyContinue } catch {}
}

# ── 프로필 사전 점검 (버전 불일치 대응) ─────────────────────────────────────
# COM 기동은 '등록된' Outlook 을 띄운다. 실제로 쓰는 것이 365 여도 구형 2016 설치본이
# 등록돼 있으면 그쪽이 뜨고, 그 설치본에 프로필이 없으면 '첫 실행 마법사'(모달)가 떠서
# 응답이 없다 - 그 PC 의 수집이 통째로 비고 스크립트는 무한정 대기한다(실측).
# 마법사를 띄우는 주체가 이 호출이므로, 프로필이 없으면 COM 을 건드리지 않는다.
$olRunning = $false
$hasProfile = $false
if (-not $SelfTest) {
    $olRunning = [bool](Get-Process outlook -ErrorAction SilentlyContinue)
    foreach ($pp in @('HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles',
                      'HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles',
                      'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles')) {
        try {
            if (Get-ChildItem -Path $pp -ErrorAction SilentlyContinue | Select-Object -First 1) {
                $hasProfile = $true
                break
            }
        } catch {}
    }
    if (-not $olRunning -and -not $hasProfile) {
        Write-Host '[outlook] 건너뜀: 메일 프로필이 구성되지 않았습니다.'
        Write-Host '          이 상태에서 COM 으로 Outlook 을 띄우면 "Outlook 시작" 설정 마법사가 떠서'
        Write-Host '          응답이 없고 수집이 멈춥니다. Outlook 을 직접 실행해 계정을 설정한 뒤,'
        Write-Host '          Outlook 을 켜 둔 채로 다시 수집하세요.'
        Write-Host '          (평소 쓰는 Outlook 이 따로 있다면, 그 Outlook 을 열어 두면 그쪽에 붙습니다.)'
        Set-SkipReason 'Outlook 메일 프로필이 구성되지 않았습니다 — Outlook 을 직접 실행해 계정 설정을 마친 뒤 다시 수집하세요'
        exit 0
    }
}

# ── 달 하나를 읽는 함수들 - COM 과 자가검증(SelfTest) 두 갈래. 둘 다 CSV 행 목록과 중단 사유를 돌려준다 ──
$script:stopReason = ''
function Read-CalendarMonth($ns, $mo) {
    # 반환: 이 달과 겹치는 일정의 CSV 행 목록. 예산(절반)에 닿으면 $script:stopReason 을 채우고 그때까지의 행만.
    $rows = New-Object System.Collections.Generic.List[string]
    $script:stopReason = ''
    $halfBudget = $BudgetSec * 0.5
    if ($SelfTest) {
        $n = [math]::Max(1, [int]($SelfTest / 2))
        for ($i = 0; $i -lt $n; $i++) {
            if ($SelfTestDelayMs -gt 0) { Start-Sleep -Milliseconds $SelfTestDelayMs }
            if ($sw.Elapsed.TotalSeconds -gt $halfBudget) { $script:stopReason = ('일정 시간 예산({0}초) 도달' -f [int]$halfBudget); break }
            $st = $mo.start.AddDays($i % [math]::Max(1, ($mo.end - $mo.start).Days)).AddHours(9 + ($i % 8))
            $rows.Add(('{0},{1},False,2,{2},,,3,1' -f $st.ToString('yyyy-MM-dd HH:mm'), $st.AddHours(1).ToString('yyyy-MM-dd HH:mm'), ('selftest meeting ' + $i)))
        }
        return $rows
    }
    $cal = $ns.GetDefaultFolder(9)  # olFolderCalendar
    $items = $cal.Items
    $items.IncludeRecurrences = $true
    $items.Sort('[Start]', $true)                   # 최신 회차부터 - 예산에 닿으면 그 달의 앞쪽이 빠지고 달은 미완료로 남는다
    $flt = ("[Start] < '{0}' AND [End] >= '{1}'" -f $mo.end.ToString($fmt), $mo.start.ToString($fmt))
    $sel = $items.Restrict($flt)
    $count = 0
    foreach ($it in $sel) {
        $count++
        if ($count -gt 8000) { $script:stopReason = '일정 상한 8000건(깨진 반복 일정?)'; break }   # runaway guard for broken recurrences
        if (($count % 100) -eq 0 -and $sw.Elapsed.TotalSeconds -gt $halfBudget) {
            $script:stopReason = ('일정 시간 예산({0}초) 도달' -f [int]$halfBudget); break
        }
        try {
            $subj = ''
            if ($storeSubject) { $subj = [string]$it.Subject }
            # LM22: 응답 상태(0 없음/1 주최/2 미정/3 수락/4 거절/5 미응답)와 회의 상태(5·7 = 취소).
            # '미정(busy 1)'은 대부분 미응답 초대라 extract 가 참석 판정(tentativeMeetings)에 쓴다. 못 읽으면 빈칸.
            $resp = ''; $mst = ''
            try { $resp = [string][int]$it.ResponseStatus } catch {}
            try { $mst = [string][int]$it.MeetingStatus } catch {}
            $rows.Add(('{0},{1},{2},{3},{4},{5},{6},{7},{8}' -f `
                $it.Start.ToString('yyyy-MM-dd HH:mm'), $it.End.ToString('yyyy-MM-dd HH:mm'), `
                $it.AllDayEvent, $it.BusyStatus, (Csv-Escape $subj), `
                (Csv-Escape ([string]$it.Categories)), (Csv-Escape ([string]$it.Location)), $resp, $mst))
        } catch {}
    }
    return $rows
}
function Read-MailMonth($ns, $mo, [string[]]$me) {
    # 반환: 이 달의 inbox+sent CSV 행 목록. 예산에 닿으면 $script:stopReason 을 채우고 그때까지의 행만.
    # rcv = 수신 구분: to(직접 수신) / cc(참조) / bulk(내 주소가 To/CC에 없음 - 배포리스트·공지)
    # CC·단체발송이 본인 업무로 계상되는 오류를 분석기에서 분리하기 위한 핵심 열이다.
    $rows = New-Object System.Collections.Generic.List[string]
    $script:stopReason = ''
    if ($SelfTest) {
        foreach ($bx in @('inbox', 'sent')) {
            for ($i = 0; $i -lt $SelfTest; $i++) {
                if ($SelfTestDelayMs -gt 0) { Start-Sleep -Milliseconds $SelfTestDelayMs }
                if ($sw.Elapsed.TotalSeconds -gt $BudgetSec) { $script:stopReason = ('시간 예산 {0}초' -f $BudgetSec); return $rows }
                $t = $mo.end.AddMinutes(-1 - $i * 97)
                if ($t -lt $mo.start) { $t = $mo.start.AddMinutes($i) }
                $rows.Add(('{0},{1},{2},{3},{4},{5}' -f $bx, $t.ToString('yyyy-MM-dd HH:mm'), 'selftest', ('selftest mail ' + $i), ('conv ' + ($i % 3)), $(if ($bx -eq 'inbox') { 'to' } else { '' })))
            }
        }
        return $rows
    }
    $boxes = @(
        @{ name = 'inbox'; folder = $ns.GetDefaultFolder(6); field = '[ReceivedTime]' },
        @{ name = 'sent';  folder = $ns.GetDefaultFolder(5); field = '[SentOn]' }
    )
    foreach ($b in $boxes) {
        $mi = $b.folder.Items
        $mi.Sort($b.field, $true)                   # 최신순 - 예산에 닿으면 이 달의 앞쪽이 빠지고 달은 미완료로 남는다
        $mflt = ("{0} >= '{1}' AND {0} < '{2}'" -f $b.field, $mo.start.ToString($fmt), $mo.end.ToString($fmt))
        $msel = $mi.Restrict($mflt)
        $n = 0
        foreach ($m in $msel) {
            $n++
            if ($n -gt 20000) { $script:stopReason = ('{0} 상한 20000건' -f $b.name); return $rows }
            if (($n % 50) -eq 0 -and $sw.Elapsed.TotalSeconds -gt $BudgetSec) { $script:stopReason = ('시간 예산 {0}초' -f $BudgetSec); return $rows }
            try {
                if ($m.Class -ne 43) { continue }  # olMail only
                $t = if ($b.name -eq 'inbox') { $m.ReceivedTime } else { $m.SentOn }
                $subj = ''
                $conv = [string]$m.ConversationTopic
                if ($storeSubject) { $subj = [string]$m.Subject } else { $conv = Conv-Token $conv }
                $rcv = ''
                if ($b.name -eq 'inbox') {
                    # 수신자 판정은 To/CC 표시 문자열(PR_DISPLAY_TO/CC) 1회 조회로 - 수신자마다 PropertyAccessor 를
                    # 부르던 왕복(N배)을 없앤다. 표시 이름으로 못 찾을 때만 소규모 수신자 목록을 주소로 정밀 확인.
                    $rcv = 'bulk'
                    $toS = ''; $ccS = ''
                    try { $toS = [string]$m.To } catch {}
                    try { $ccS = [string]$m.CC } catch {}
                    if (Test-MeInList $toS $me) { $rcv = 'to' }
                    elseif (Test-MeInList $ccS $me) { $rcv = 'cc' }
                    elseif (-not $me.Count) { $rcv = 'unknown' }      # 내 주소를 모른다 - bulk 로 버리지 않는다
                    else {
                        $nRcpt = 0
                        try { $nRcpt = [int]$m.Recipients.Count } catch {}
                        if ($nRcpt -le 12) {
                            try {
                                foreach ($rc in $m.Recipients) {
                                    $addr = ''
                                    try { $addr = $rc.PropertyAccessor.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x39FE001E') } catch {}
                                    if (-not $addr) { $addr = $rc.Address }
                                    $nm = [string]$rc.Name
                                    $hitMe = $false
                                    foreach ($meid in $me) {
                                        if (($addr -and $addr.ToLower() -eq $meid) -or ($nm -and $nm.ToLower() -eq $meid)) { $hitMe = $true; break }
                                    }
                                    if ($hitMe) {
                                        if ($rc.Type -eq 1) { $rcv = 'to'; break }          # olTo
                                        elseif ($rc.Type -eq 2) { $rcv = 'cc' }             # olCC (To 매칭이 있으면 to 우선)
                                    }
                                }
                            } catch { $rcv = 'to' }   # 수신자 열람 실패 시 보수적으로 직접 수신 취급
                        }
                    }
                }
                $rows.Add(('{0},{1},{2},{3},{4},{5}' -f `
                    $b.name, $t.ToString('yyyy-MM-dd HH:mm'), (Csv-Escape ([string]$m.SenderName)), `
                    (Csv-Escape $subj), (Csv-Escape $conv), $rcv))
            } catch {}
        }
    }
    return $rows
}

try {
    $ns = $null
    $me = @()
    if ($SelfTest) {
        Write-Host ("[outlook] 자가검증 모드 - Outlook 없이 달마다 가짜 메일 {0}건·일정 {1}건" -f $SelfTest, [math]::Max(1, [int]($SelfTest / 2)))
        $me = @('selftest@corp.local')
    } else {
        # 이미 떠 있는 Outlook 에 먼저 붙는다 - 사용자가 실제로 쓰는 버전이 그것이고,
        # 새 인스턴스 기동은 등록된(다를 수 있는) 설치본을 띄우기 때문이다.
        # 떠 있는 Outlook 에 붙기를 먼저 시도한다. 바쁜 순간에는 거부(RPC_E_CALL_REJECTED)될
        # 수 있는데 영구 실패가 아니므로 짧게 재시도한다.
        for ($try = 1; $try -le 3 -and -not $ol; $try++) {
            try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') } catch { $ol = $null }
            if (-not $ol -and $try -lt 3) { Start-Sleep -Seconds 2 }
        }
        if (-not $ol -and $olRunning) {
            # Outlook 이 실행 중인데 붙을 수 없다 = COM 을 아직 등록하지 않았다 = 시작 마법사·
            # 프로필 선택·암호 입력 같은 대화상자에 막혀 있다는 뜻이다. 이때 New-Object 를
            # 부르면 그 창이 닫힐 때까지 **반환되지 않는다**(실측: 300초 무응답). 부르지 않는다.
            $wins = @()
            try {
                $wins = @(Get-Process outlook -ErrorAction SilentlyContinue |
                          ForEach-Object { $_.MainWindowTitle } | Where-Object { $_ })
            } catch {}
            Write-Host '[outlook] 건너뜀: Outlook 이 실행 중이지만 아직 사용할 준비가 안 됐습니다.'
            if ($wins.Count) { Write-Host ("          열려 있는 창: {0}" -f ($wins -join ' / ')) }
            Write-Host '          보통 "Outlook 시작" 설정 마법사·프로필 선택·암호 입력 창이 떠 있을 때입니다.'
            Write-Host '          그 창을 닫거나 설정을 끝내고 메일 화면까지 연 다음 다시 수집하세요.'
            Write-Host '          (설치 문제가 아닙니다 - 재설치하지 마세요)'
            Set-SkipReason ("Outlook 이 대화상자에 막혀 있습니다" +
                $(if ($wins.Count) { " (열린 창: " + ($wins -join ' / ') + ")" } else { '' }) +
                " — 그 창을 닫고 메일 화면까지 연 다음 다시 수집하세요")
            exit 0
        }
        if (-not $ol) {
            if (-not $hasProfile) {
                Write-Host '[outlook] 건너뜀: 붙을 Outlook 도, 구성된 프로필도 없습니다.'
                Set-SkipReason '붙을 Outlook 도, 구성된 프로필도 없습니다'
                exit 0
            }
            $ol = New-Object -ComObject Outlook.Application
        }
        $ns = $ol.GetNamespace('MAPI')
        # ShowDialog=$false - 프로필 선택창·설정 마법사를 원천 차단한다. 이미 로그온된
        # 세션이면 무시되고, 아니면 기본 프로필로 조용히 붙는다.
        try { $ns.Logon($null, $null, $false, $false) } catch {}
        # 어느 설치본이 잡혔는지 남긴다 - 'PC 마다 누락'을 원격으로 판별하는 유일한 단서다.
        try {
            $exe = ''
            try { $exe = (Get-Process outlook -ErrorAction SilentlyContinue |
                          Select-Object -First 1).Path } catch {}
            Write-Host ("[outlook] 연결: 버전 {0}{1}" -f $ol.Version,
                        $(if ($exe) { " ($exe)" } else { '' }))
        } catch {}
        # 내 주소·이름(수신 구분용)
        try {
            $acc = $ns.Accounts
            foreach ($a in $acc) { if ($a.SmtpAddress) { $me += $a.SmtpAddress.ToLower() } }
        } catch {}
        try { $me += $ns.CurrentUser.Name.ToLower() } catch {}
        try { if ($ns.CurrentUser.Address) { $me += ([string]$ns.CurrentUser.Address).ToLower() } } catch {}
        try {
            $xu = $ns.CurrentUser.AddressEntry.GetExchangeUser()
            if ($xu -and $xu.PrimarySmtpAddress) { $me += ([string]$xu.PrimarySmtpAddress).ToLower() }
        } catch {}
        try { if ($cfg.owner) { $me += ([string]$cfg.owner).Trim().ToLower() } } catch {}
        $me = @($me | Where-Object { $_ -and $_.Length -ge 2 } | Select-Object -Unique)
    }
    try { Remove-Item -LiteralPath (Join-Path $outDir 'mail.csv.part') -ErrorAction SilentlyContinue } catch {}   # 구판의 중간 저장은 더 쓰지 않는다

    $warnings = New-Object System.Collections.Generic.List[string]
    $now = (Get-Date).ToString('yyyy-MM-dd HH:mm')
    $readCal = 0; $readMail = 0

    # ---------- calendar: 최신 달부터, 예산의 절반까지 ----------
    foreach ($mo in $calTodo) {
        if ($sw.Elapsed.TotalSeconds -gt ($BudgetSec * 0.5)) { break }
        $rows = Read-CalendarMonth $ns $mo
        if ($script:stopReason) {
            # 미완료 달: 예전에 완료한 달이면 그 행을 지키고, 아니면 부분 행이라도 남긴다(부분 > 공백). 완료 표시는 안 한다
            if (-not $cov.calendar.ContainsKey($mo.key)) { $calBy[$mo.key] = $rows }
            $warnings.Add(('일정 {0}: {1} - 이 달은 다음 실행에서 이어서 읽습니다' -f $mo.key, $script:stopReason))
            Write-Host ('[outlook] 경고: ' + $warnings[$warnings.Count - 1])
            $null = Write-CsvByMonth $calP $CAL_HEADER $calBy
            Save-Coverage $cov
            break
        }
        $calBy[$mo.key] = $rows
        $cov.calendar[$mo.key] = @{ rows = $rows.Count; when = $now }
        $readCal++
        $null = Write-CsvByMonth $calP $CAL_HEADER $calBy
        Save-Coverage $cov
        Write-Host ("[outlook] 일정 {0}: {1}건 (경과 {2}초)" -f $mo.key, $rows.Count, [int]$sw.Elapsed.TotalSeconds)
    }
    if (-not (Test-Path $calP)) { $null = Write-CsvByMonth $calP $CAL_HEADER $calBy }

    # ---------- mail (inbox + sent): 최신 달부터, 예산까지 ----------
    foreach ($mo in $mailTodo) {
        if ($sw.Elapsed.TotalSeconds -gt $BudgetSec) { break }
        $rows = Read-MailMonth $ns $mo $me
        if ($script:stopReason) {
            if (-not $cov.mail.ContainsKey($mo.key)) { $mailBy[$mo.key] = $rows }
            $warnings.Add(('메일 {0}: {1} 도달 - 이 달부터 오래된 달은 다음 실행에서 이어서 읽습니다' -f $mo.key, $script:stopReason))
            Write-Host ('[outlook] 경고: ' + $warnings[$warnings.Count - 1])
            $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy
            Save-Coverage $cov
            break
        }
        $mailBy[$mo.key] = $rows
        $cov.mail[$mo.key] = @{ rows = $rows.Count; when = $now }
        $readMail++
        $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy
        Save-Coverage $cov
        Write-Host ("[outlook] 메일 {0}: {1}건 (경과 {2}초)" -f $mo.key, $rows.Count, [int]$sw.Elapsed.TotalSeconds)
    }
    if (-not (Test-Path $mailP)) { $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy }
    Save-Coverage $cov

    # ---------- 요약: 기간 안에서 아직 못 읽은 달 ----------
    $uncMail = @($monthKeys | Where-Object { -not $cov.mail.ContainsKey($_) })
    $uncCal  = @($monthKeys | Where-Object { -not $cov.calendar.ContainsKey($_) })
    $unc = @($uncMail + $uncCal | Select-Object -Unique | Sort-Object)
    $complete = ($unc.Count -eq 0)
    $nMail = 0; foreach ($k in $mailBy.Keys) { $nMail += $mailBy[$k].Count }
    $nCal = 0;  foreach ($k in $calBy.Keys)  { $nCal  += $calBy[$k].Count }
    Clear-SkipReason            # 성공했으니 지난 사유는 지운다
    try {                       # 어느 경로가 채웠는지 기록 - 폴백(색인/Copilot)이 남긴 'index/copilot' 표식을 덮는다
        $src = [ordered]@{ source = 'com'; when = $now; mail = $nMail; calendar = $nCal;
                           calendar_complete = ($uncCal.Count -eq 0); calendar_recurring_masters = 0; me = @($me);
                           mail_truncated = ($uncMail.Count -gt 0); warnings = @($warnings);
                           coverage_complete = $complete; uncovered_months = @($unc);
                           uncovered_mail = @($uncMail); uncovered_calendar = @($uncCal);
                           months_read = [ordered]@{ mail = $readMail; calendar = $readCal };
                           period = @($since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'));
                           budget_sec = $BudgetSec; elapsed_sec = [int]$sw.Elapsed.TotalSeconds }
        ($src | ConvertTo-Json -Compress -Depth 4) | Set-Content -Path (Join-Path $outDir 'mail_source.json') -Encoding UTF8
    } catch {}
    Write-Host ("[outlook] mail rows: {0} · calendar rows: {1} (이번에 읽은 달: 메일 {2} / 일정 {3}, 경과 {4}초)" -f $nMail, $nCal, $readMail, $readCal, [int]$sw.Elapsed.TotalSeconds)
    if ($complete) {
        Write-Host '[outlook] coverage: complete - 기간의 모든 달을 읽었습니다'
        Write-Host '[outlook] done.'
    } else {
        Write-Host ("[outlook] coverage: partial - 미수집 달 {0}개: {1}" -f $unc.Count, ($unc -join ','))
        Write-Host '[outlook] done. (부분 수집 - 다음 실행이 남은 달을 이어서 읽습니다. 화면의 수집 데이터 현황에 표시됩니다)'
    }
}
catch {
    Write-Host ("[outlook] 수집 실패: {0}" -f $_.Exception.Message)
    Set-SkipReason ("수집 실패: " + $_.Exception.Message)
    if ($newOutlook) {
        Write-Host '          원인: "새 Outlook"(COM 미지원) - 클래식 Outlook 으로 전환/실행 후 재시도하세요.'
    } elseif ($_.Exception.Message -match '80010001|8001010A|RPC_E_CALL_REJECTED|RPC_E_SERVERCALL') {
        Write-Host '          원인: Outlook 이 응답하지 않습니다 - 보통 Outlook 이 대화상자를 띄우고 있을 때입니다.'
        Write-Host '          ("Outlook 시작" 설정 마법사, 프로필 선택, 암호 입력, 복구 창 등)'
        Write-Host '          Outlook 화면을 열어 떠 있는 창을 닫거나 설정을 끝낸 뒤 다시 수집하세요.'
        Write-Host '          (설치 문제가 아닙니다 - 재설치하지 마세요)'
    } elseif ($_.Exception.Message -match '80040154|REGDB_E_CLASSNOTREG') {
        Write-Host '          원인: 클래식 Outlook 이 설치돼 있지 않음(COM 미등록) - Microsoft 365 설치 옵션에서'
        Write-Host '          클래식 Outlook 을 추가하거나, 관리자에게 클래식 Outlook 배포를 요청하세요.'
    } else {
        Write-Host '          클래식 Outlook(2016~365)을 실행해 프로필 로그인까지 마친 상태에서 재시도하세요.'
        Write-Host '          (버전은 무관 - 2016/2019/2021/365 모두 동일하게 동작합니다)'
    }
    exit 1
}
finally {
    if ($ol) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ol) }
}
