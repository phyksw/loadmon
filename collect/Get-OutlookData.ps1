# Get-OutlookData.ps1
# Read-only export of Outlook calendar + mail metadata via COM (works without Graph API).
# Mail/calendar history reaches back YEARS (cached OST) - main source for retrospective analysis.
# Output: ..\data\outlook\calendar.csv , mail.csv  (overwrite, UTF-8)
# Usage:  .\Get-OutlookData.ps1 -From 2026-01-01 -To 2026-06-30 [-BudgetSec 360]   (or -Days 90)
# 시간 예산(-BudgetSec, 기본 360 = run.py 의 420초 안): 편지함은 최신순으로 읽다가 예산·상한(20000건)에 닿으면
#   그때까지의 행으로 mail.csv 를 쓰고 '오래된 달 N건 미수집' 을 경고·mail_source.json 에 남긴다. 500건마다,
#   그리고 편지함 하나를 마칠 때마다 mail.csv.part 에 중간 저장하므로 강제 종료돼도 부분 수집이 남는다
#   (run.py 가 대체 경로도 모두 실패했을 때 .part 를 mail.csv 로 승격).
# storeMailSubject: 키가 없으면 true(다른 세 경로와 동일). false 면 제목·일정 제목을 비우고 conversation 도
#   원문 대신 짧은 해시로 남긴다(회신 이력 판정만 유지).
param(
    [string]$From = '',
    [string]$To = '',
    [int]$Days = 90,
    [int]$BudgetSec = 360
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$sw = [System.Diagnostics.Stopwatch]::StartNew()       # 시간 예산은 COM 연결까지 포함해 잰다(run.py 의 시계와 같다)
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$cfg  = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json
$storeSubject = $true
if ($cfg -and $cfg.PSObject.Properties['storeMailSubject'] -and -not $cfg.storeMailSubject) { $storeSubject = $false }
if ($BudgetSec -le 0) { $BudgetSec = 360 }
$outDir = Join-Path $root 'data\outlook'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

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
$fmt = 'g'  # locale short date+time, what Outlook Restrict expects
$ol = $null

# ── 버전 강건성: 2016/2019/2021/365 '클래식' Outlook 은 전부 동일한 COM(Outlook.Application)
# 을 쓰므로 버전 구분이 필요 없다. 문제는 '새 Outlook'(olk.exe) - COM 인터페이스 자체가 없어
# 어떤 버전 표기든 수집이 통째로 빈다(실측: 'PC마다 메일 누락'의 주원인 후보).
$newOutlook = $false
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
$olRunning = [bool](Get-Process outlook -ErrorAction SilentlyContinue)
$hasProfile = $false
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

try {
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

    # ---------- calendar ----------
    $cal = $ns.GetDefaultFolder(9)  # olFolderCalendar
    $items = $cal.Items
    $items.IncludeRecurrences = $true
    $items.Sort('[Start]')
    $flt = ("[Start] <= '{0}' AND [End] >= '{1}'" -f $until.ToString($fmt), $since.ToString($fmt))
    $sel = $items.Restrict($flt)

    $calRows = New-Object System.Collections.Generic.List[string]
    $calRows.Add('start,end,all_day,busy_status,subject,categories,location,response,meeting_status')
    $count = 0
    $warnings = New-Object System.Collections.Generic.List[string]
    foreach ($it in $sel) {
        $count++
        if ($count -gt 8000) { $warnings.Add('일정 상한 8000건 도달 - 이후 회차 미수집(깨진 반복 일정?)'); break }   # runaway guard for broken recurrences
        if (($count % 100) -eq 0 -and $sw.Elapsed.TotalSeconds -gt ($BudgetSec * 0.5)) {
            $warnings.Add(('일정 시간 예산({0}초) 도달 - {1}건 이후 미수집' -f [int]($BudgetSec * 0.5), $count)); break
        }
        try {
            $subj = ''
            if ($storeSubject) { $subj = [string]$it.Subject }
            # LM22: 응답 상태(0 없음/1 주최/2 미정/3 수락/4 거절/5 미응답)와 회의 상태(5·7 = 취소).
            # '미정(busy 1)'은 대부분 미응답 초대라 extract 가 참석 판정(tentativeMeetings)에 쓴다. 못 읽으면 빈칸.
            $resp = ''; $mst = ''
            try { $resp = [string][int]$it.ResponseStatus } catch {}
            try { $mst = [string][int]$it.MeetingStatus } catch {}
            $calRows.Add(('{0},{1},{2},{3},{4},{5},{6},{7},{8}' -f `
                $it.Start.ToString('yyyy-MM-dd HH:mm'), $it.End.ToString('yyyy-MM-dd HH:mm'), `
                $it.AllDayEvent, $it.BusyStatus, (Csv-Escape $subj), `
                (Csv-Escape ([string]$it.Categories)), (Csv-Escape ([string]$it.Location)), $resp, $mst))
        } catch {}
    }
    [System.IO.File]::WriteAllLines((Join-Path $outDir 'calendar.csv'), $calRows, [System.Text.Encoding]::UTF8)
    Write-Host ("[outlook] calendar rows: {0}{1}" -f ($calRows.Count - 1), $(if ($warnings.Count) { ' - ' + ($warnings -join ' / ') } else { '' }))

    # ---------- mail (inbox + sent) ----------
    # rcv = 수신 구분: to(직접 수신) / cc(참조) / bulk(내 주소가 To/CC에 없음 - 배포리스트·공지)
    # CC·단체발송이 본인 업무로 계상되는 오류를 분석기에서 분리하기 위한 핵심 열이다.
    $me = @()
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

    $mailRows = New-Object System.Collections.Generic.List[string]
    $mailRows.Add('box,time,sender,subject,conversation,rcv')
    $partP = Join-Path $outDir 'mail.csv.part'       # 중간 저장 - 강제 종료돼도 남는다(run.py 가 최후에 승격)
    try { Remove-Item -LiteralPath $partP -ErrorAction SilentlyContinue } catch {}
    $truncated = $false

    $boxes = @(
        @{ name = 'inbox'; folder = $ns.GetDefaultFolder(6); field = '[ReceivedTime]' },
        @{ name = 'sent';  folder = $ns.GetDefaultFolder(5); field = '[SentOn]' }
    )
    foreach ($b in $boxes) {
        $mi = $b.folder.Items
        $mi.Sort($b.field, $true)                   # 최신순 - 예산에 닿으면 오래된 달부터 빠진다(경고에 그 경계를 적는다)
        $mflt = ("{0} >= '{1}' AND {0} <= '{2}'" -f $b.field, $since.ToString($fmt), $until.ToString($fmt))
        $msel = $mi.Restrict($mflt)
        $expected = -1
        try { $expected = [int]$msel.Count } catch {}
        Write-Host ("[outlook] {0}: 기간 내 {1}건 예상 (경과 {2}초)" -f $b.name, $(if ($expected -ge 0) { $expected } else { '?' }), [int]$sw.Elapsed.TotalSeconds)
        $n = 0; $nRow = 0; $oldest = $null; $stop = ''
        foreach ($m in $msel) {
            $n++
            if ($n -gt 20000) { $stop = '상한 20000건'; break }
            if (($n % 50) -eq 0 -and $sw.Elapsed.TotalSeconds -gt $BudgetSec) { $stop = ('시간 예산 {0}초' -f $BudgetSec); break }
            try {
                if ($m.Class -ne 43) { continue }  # olMail only
                $t = if ($b.name -eq 'inbox') { $m.ReceivedTime } else { $m.SentOn }
                $oldest = $t
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
                $mailRows.Add(('{0},{1},{2},{3},{4},{5}' -f `
                    $b.name, $t.ToString('yyyy-MM-dd HH:mm'), (Csv-Escape ([string]$m.SenderName)), `
                    (Csv-Escape $subj), (Csv-Escape $conv), $rcv))
                $nRow++
                if (($nRow % 500) -eq 0) { try { [System.IO.File]::WriteAllLines($partP, $mailRows, [System.Text.Encoding]::UTF8) } catch {} }
            } catch {}
        }
        if ($stop) {
            $truncated = $true
            $left = -1
            if ($expected -ge 0) { $left = [math]::Max(0, $expected - $n + 1) }
            $msg = ("{0}: {1} 도달 - {2} 이전 {3}건 미수집(오래된 달부터 빠짐)" -f $b.name, $stop,
                    $(if ($oldest) { $oldest.ToString('yyyy-MM-dd') } else { '?' }), $(if ($left -ge 0) { $left } else { '?' }))
            Write-Host ('[outlook] 경고: ' + $msg)
            $warnings.Add($msg)
        }
        Write-Host ("[outlook] {0} rows: {1} (경과 {2}초)" -f $b.name, $nRow, [int]$sw.Elapsed.TotalSeconds)
        try { [System.IO.File]::WriteAllLines($partP, $mailRows, [System.Text.Encoding]::UTF8) } catch {}   # 편지함 하나를 마칠 때마다 저장
    }
    [System.IO.File]::WriteAllLines((Join-Path $outDir 'mail.csv'), $mailRows, [System.Text.Encoding]::UTF8)
    try { Remove-Item -LiteralPath $partP -ErrorAction SilentlyContinue } catch {}
    Clear-SkipReason            # 성공했으니 지난 사유는 지운다
    try {                       # 어느 경로가 채웠는지 기록 - 폴백(색인/Copilot)이 남긴 'index/copilot' 표식을 덮는다
        $src = [ordered]@{ source = 'com'; when = (Get-Date).ToString('yyyy-MM-dd HH:mm'); mail = ($mailRows.Count - 1); calendar = ($calRows.Count - 1);
                           calendar_complete = $true; calendar_recurring_masters = 0; me = @($me);
                           mail_truncated = [bool]$truncated; warnings = @($warnings) }
        ($src | ConvertTo-Json -Compress) | Set-Content -Path (Join-Path $outDir 'mail_source.json') -Encoding UTF8
    } catch {}
    Write-Host ("[outlook] done.{0}" -f $(if ($truncated) { ' (부분 수집 - 위 경고 참고)' } else { '' }))
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
