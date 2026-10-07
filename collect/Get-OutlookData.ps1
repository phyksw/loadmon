# Get-OutlookData.ps1
# Read-only export of Outlook calendar + mail metadata via COM (works without Graph API).
# Mail/calendar history reaches back YEARS (cached OST) - main source for retrospective analysis.
# Output: ..\data\outlook\calendar.csv , mail.csv (UTF-8) + coverage.json (달별 수집 완료 표 v2)
# Usage:  .\Get-OutlookData.ps1 -From 2026-01-01 -To 2026-06-30 [-BudgetSec 360] [-Force] [-NoRefresh]   (or -Days 90)
#
# 달 단위 이어서 수집(LM22 2차): 기간을 달로 쪼개 **최신 달부터** 읽고, 달 하나를 다 읽을 때마다 CSV 와
#   coverage.json 을 쓴다. 시간 예산(-BudgetSec)에 닿으면 거기서 멈추되, 다 읽은 달은 다음 실행에서
#   건너뛰므로 실행을 거듭하면 기간 전체가 채워진다. 예전에는 매번 최신순으로 처음부터 읽다가 예산에
#   닿으면 오래된 달이 **영영** 빠졌다(실측 제보: '주간 활동이 1월부터 안 나온다' - 1~5월 메일·회의 공백).
#   · 완료 표는 달마다 실제로 읽은 [start, end) 를 함께 적는다 - 기간 시작·끝에 걸려 일부만 읽은 달은 나중에
#     더 넓은 기간으로 부르면 다시 읽는다(재검증 실측: '3개월' 뒤 '올해'에서 3월 앞부분이 영영 빠지던 것).
#   · 예산에 닿아 절반만 읽은 달은 **이어서** 읽는다(메일: 편지함별 '여기까지 읽음' 경계, 일정: 마지막 시작 시각) -
#     달 하나가 예산보다 크면 처음부터 다시 읽느라 영영 못 끝내던 것(재검증 실측).
#   · 최신 달(이번 달)은 매번 먼저 다시 읽고, 그다음 못 읽은 달(최신→과거), 마지막에 최신 2개월 재수집.
#     run.py 의 연속 회차는 -NoRefresh 로 못 읽은 달만 잇는다. -Force 면 전부 다시.
#   · 기존 CSV 의 다른 달 행은 그대로 보존하고 KeepDays(400일)보다 오래된 행만 버린다. 메일 행은 절대 중복 제거하지
#     않는다(같은 분에 같은 제목으로 두 번 오는 알림·배포 메일은 실제 2건) - 달 경계에 걸친 일정 회차만 한 번으로.
#   · 표는 '누가 썼는지'(com / selftest)·storeMailSubject·판('수집기판|collect.cursorEpoch')과 함께 저장하고, 판·설정이
#     바뀌었으면 표를 버리고 처음부터 읽는다(LM28 F-09 - 옛 판이 잘못 '완료'로 적은 달을 다시 읽는다).
#     다른 경로(색인·웹·Copilot)가 무엇을 썼는지는 보지 않는다 - 출처마다 자기 파일만 쓴다(-OutDir·-Tag, LM28 P5).
# LM28 보강(WP1 - 공용 함수는 collect\OutlookCommon.ps1):
#   · 사전 건너뜀은 'Outlook 미실행 + 띄우면 모달이 확실함'일 때만 - 프로필 0(새 Outlook 흔적 있음 R-NEWOL · 없음 R-NOPROF) ·
#     관리자 전환 정책(R-NEWOLPOL). exit 3 + 사유. 클래식이 있으면 새 Outlook 흔적이 있어도 COM 을 시도한다(LM24).
#   · 붙기: GetActiveObject 3회 → 실행 중인데 못 붙으면 권한 상승 R-ELEV · 바쁨(8001010A/80010001)은 attachWaitSec 까지 재시도
#     후 R-BUSY · 그 밖 R-DIALOG(New-Object 하지 않는다). 미실행일 때만 New-Object - 무진전 attachWaitSec 이면 이 수집이 띄운
#     Outlook(-Embedding)만 끝내고 R-WIZARD. Logon 은 우리가 띄웠을 때만.
#   · 날짜 필터 카나리아('g' → yyyy-MM-dd HH:mm → ISO) - 모두 실패면 R-FILTER(rc 3, 완료 기록 0). Restrict 결과를 [start, end) 로
#     다시 걸러 밖의 행은 filter_mismatch 로 센다. 0행 달은 카나리아 성공·지평선·OST 신선도를 모두 만족할 때만 zero_ok 로 완료.
#   · 기본 저장소의 메일 폴더를 재귀로 읽는다(outlook.subfolders, 상한 3000). 보호 멤버는 위험의 긍정 증거가 있으면 읽지 않는다
#     (rcv=unknown). 끝에 LMSTATUS 한 줄(rc 0 정상 · 1 대상 없음 · 3 불가·불완전). 우리가 띄운 Outlook 만 닫는다.
# 중간 저장: 달마다 CSV 를 다시 쓰므로 강제 종료돼도 그때까지 읽은 달이 남는다(mail.csv.part 는 더 쓰지 않는다).
#   CSV 는 임시 파일 뒤 교체하되, 화면이 파일을 읽고 있어 교체가 막히면 잠시 기다렸다가 제자리에 쓴다(실행을 끊지 않는다).
# 일정은 예산의 절반까지만 쓴다(메일이 굶지 않게) - 남은 달은 역시 다음 실행이 잇는다.
# storeMailSubject: 키가 없으면 true(다른 세 경로와 동일). false 면 제목·일정 제목을 비우고 conversation 도
#   원문 대신 짧은 해시로 남긴다(회신 이력 판정만 유지).
# -SelfTest N: Outlook 없이 달마다 N건의 가짜 메일·일정을 만들어 예산·이어서 수집·병합 논리를 검증한다(테스트 전용 -
#   표·mail_source.json 에 selftest 표식이 남아 실제 수집과 섞이지 않는다).
param(
    [string]$From = '',
    [string]$To = '',
    [int]$Days = 90,
    [int]$BudgetSec = 360,
    [switch]$Force,
    [switch]$NoRefresh,
    [int]$KeepDays = 400,
    [int]$SelfTest = 0,
    [int]$SelfTestDelayMs = 0,
    [string]$OutDir = '',     # LM28: 출처별 폴더(예 data\outlook\src) - 없으면 data\outlook
    [string]$Tag = ''         # LM28: 출처 표식(예 com) - 주면 mail_<tag>.csv·cal_<tag>.csv·mail_source_<tag>.json·coverage_<tag>.json
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
$writer = $(if ($SelfTest) { 'selftest' } else { 'com' })
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'OutlookCommon.ps1')   # 판 판정·카나리아·폴더 재귀·LMSTATUS
$COLLECTOR_VER = 'LM28-COM-1'          # 완료 표 판정 규칙의 판 - 규칙을 바꾸면 올린다(옛 표의 '완료'를 버린다, F-09)
$covVer = '{0}|{1}' -f $COLLECTOR_VER, [int](Get-OcCfg $cfg 'collect' 'cursorEpoch' 1)
$attachWait = [math]::Max(20, [math]::Min(600, [int](Get-OcCfg $cfg 'outlook' 'attachWaitSec' 120)))
$staleH = [double](Get-OcCfg $cfg 'outlook' 'ostStaleH' 72)
$subOn = [bool](Get-OcCfg $cfg 'outlook' 'subfolders' $true)
$outArg = $OutDir                            # PowerShell 변수는 대소문자를 가리지 않는다 - 아래 $outDir 가 덮기 전에 받아 둔다
$skipDir = Join-Path $root 'data\outlook'    # outlook_skip.json 은 늘 여기(화면이 읽는다)
$outDir = $skipDir
if ($outArg) { $outDir = $(if ([System.IO.Path]::IsPathRooted($outArg)) { $outArg } else { Join-Path $root $outArg }) }
if ($Tag -and $Tag -notmatch '^[A-Za-z0-9_-]{1,24}$') {
    Write-Host ("[outlook] -Tag 값이 올바르지 않습니다: {0}" -f $Tag)
    Write-LmStatus -Src 'com' -Rc 3 -Reasons @('R-ARGS')
    exit 3
}
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$sfx = $(if ($Tag) { '_' + $Tag } else { '' })
$mailP = Join-Path $outDir ('mail' + $sfx + '.csv')
$calP  = Join-Path $outDir $(if ($Tag) { 'cal' + $sfx + '.csv' } else { 'calendar.csv' })
$covP  = Join-Path $outDir ('coverage' + $sfx + '.json')
$srcP  = Join-Path $outDir ('mail_source' + $sfx + '.json')
$srcName = $(if ($Tag) { $Tag } else { 'com' })
# time_precision - COM 의 ReceivedTime/SentOn 은 항상 분 단위라 'minute'. 열을 안 쓰면 웹·Copilot 이 만든
# 7열 파일과 섞일 때 그 파일의 '날짜만' 행이 정오 발신으로 승격돼(세션 20분) 없는 근무가 생긴다(감사 실측).
$MAIL_HEADER = 'box,time,sender,subject,conversation,rcv,time_precision'
$CAL_HEADER  = 'start,end,all_day,busy_status,subject,categories,location,response,meeting_status'
$REFRESH_MONTHS = 2          # 최신 N개월은 이미 읽었어도 매번 다시 읽는다(-NoRefresh 면 안 한다)
$TS = 'yyyy-MM-dd HH:mm:ss'  # 표에 적는 시각 형식

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
$tomorrow = (Get-Date).Date.AddDays(1)
if ($until -gt $tomorrow) { $until = $tomorrow }     # 미래 종료일은 내일까지만 - 미래 달을 '완료'로 두면 이번 달이 영영 갱신되지 않는다
if ($until -le $since) { $until = $since.AddDays(1) }
$fmt = 'g'  # locale short date+time, what Outlook Restrict expects - LM28: 필터 카나리아가 이 PC 에서 통하는 형식으로 바꾼다
$canary = 'none'
$ol = $null

# ── 달 목록: 기간과 겹치는 달을 최신 달부터. 각 달의 [start, end) 는 기간에 맞춰 자른다 ─────────────
$months = [System.Collections.Generic.List[object]]::new()
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

# ── 파일 읽기: UTF-8 로 엄격히, 실패하면(Excel 이 CP949 로 다시 저장한 파일) 시스템 인코딩으로 ─────────
function Read-Lines([string]$path) {
    $strict = New-Object System.Text.UTF8Encoding($false, $true)
    try { return [System.IO.File]::ReadAllLines($path, $strict) }
    catch [System.Text.DecoderFallbackException] { return [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::Default) }
}

# ── 지난 실행의 달별 수집 완료 표(v3 - LM28) ───────────────────────────────────────────
#   머리: version 3 · ver('수집기판|collect.cursorEpoch') · writer · store_subject - 하나라도 다르면 표를 버린다(Test-CoverageUsable)
#   mail/calendar: { 'yyyy-MM': { rows, when, start, end, (메일) rows_in·rows_out·st_in·st_out | (일정) st } }
#     - start/end = 실제로 읽은 [start, end). 검증된 달(Test-MonthDone 의 done - st 가 ok·zero_ok)만 적는다.
#   partial: { mail: { 'yyyy-MM': { done: [폴더 표식], before: { 폴더 표식: 경계 시각 }, start, end } },
#              calendar: { 'yyyy-MM': { from, start, end } } }  - 예산에 닿아 절반만 읽은 달의 '여기까지' 표식
function New-Coverage { return @{ mail = @{}; calendar = @{}; partial = @{ mail = @{}; calendar = @{} } } }
function Load-Coverage {
    $c = New-Coverage
    if (-not (Test-Path $covP)) { return $c }
    try {
        # 다른 경로(색인·웹·Copilot)의 mail_source 를 보고 표를 버리던 규칙은 없앴다(LM28) - 출처마다 자기 파일만 쓰고, 표의
        # 신뢰는 판('수집기판|cursorEpoch')·작성자·제목 저장 설정으로만 가린다
        $j = Get-Content -Raw -Encoding UTF8 $covP | ConvertFrom-Json
        $u = Test-CoverageUsable $j $covVer $writer $storeSubject
        if (-not $u.ok) {
            Write-Host ("[outlook] 완료 표가 이번 실행과 맞지 않아({0}) 처음부터 읽습니다" -f $u.why)
            return $c
        }
        foreach ($kind in @('mail', 'calendar')) {
            $sec = $j.PSObject.Properties[$kind]
            if (-not $sec -or -not $sec.Value) { continue }
            foreach ($p in $sec.Value.PSObject.Properties) {
                if ($p.Name -notmatch '^\d{4}-\d{2}$') { continue }
                try {
                    $e = @{ rows = [int]$p.Value.rows; when = [string]$p.Value.when;
                            start = [datetime]::ParseExact([string]$p.Value.start, $TS, $null);
                            end = [datetime]::ParseExact([string]$p.Value.end, $TS, $null) }
                    if ($kind -eq 'mail') {
                        $e.rows_in = [int]$p.Value.rows_in; $e.rows_out = [int]$p.Value.rows_out
                        $e.st_in = [string]$p.Value.st_in; $e.st_out = [string]$p.Value.st_out
                    } else { $e.st = [string]$p.Value.st }
                    $c[$kind][$p.Name] = $e
                } catch {}
            }
        }
        $ps = $j.PSObject.Properties['partial']
        if ($ps -and $ps.Value) {
            foreach ($kind in @('mail', 'calendar')) {
                $sec = $ps.Value.PSObject.Properties[$kind]
                if (-not $sec -or -not $sec.Value) { continue }
                foreach ($p in $sec.Value.PSObject.Properties) {
                    if ($p.Name -notmatch '^\d{4}-\d{2}$') { continue }
                    try {
                        $e = @{ start = [datetime]::ParseExact([string]$p.Value.start, $TS, $null);
                                end = [datetime]::ParseExact([string]$p.Value.end, $TS, $null) }
                        if ($kind -eq 'mail') {
                            # 폴더(EntryID 표식)별 '다 읽음'·'여기까지 읽음' - 하위 폴더 재귀(LM28)로 편지함 단위 표식을 바꿨다
                            $e.done = @{}; $e.before = @{}
                            foreach ($fk in @($p.Value.done)) { if ($fk) { $e.done[[string]$fk] = $true } }
                            if ($p.Value.before) { foreach ($bp in $p.Value.before.PSObject.Properties) { $e.before[$bp.Name] = [string]$bp.Value } }
                        } else {
                            $e.from = [string]$p.Value.from
                        }
                        $c.partial[$kind][$p.Name] = $e
                    } catch {}
                }
            }
        }
    } catch { Write-Host ("[outlook] coverage.json 을 읽지 못해 처음부터 읽습니다: {0}" -f $_.Exception.Message); return (New-Coverage) }
    return $c
}
function Save-Coverage($c) {
    try {
        $o = [ordered]@{ version = 3; ver = $covVer; writer = $writer; store_subject = $storeSubject; keep_days = $KeepDays;
                         when = (Get-Date).ToString('yyyy-MM-dd HH:mm'); filter_fmt = $fmt; mail = [ordered]@{}; calendar = [ordered]@{};
                         partial = [ordered]@{ mail = [ordered]@{}; calendar = [ordered]@{} } }
        foreach ($kind in @('mail', 'calendar')) {
            foreach ($k in ($c[$kind].Keys | Sort-Object -Descending)) {
                $e = $c[$kind][$k]
                $x = [ordered]@{ rows = [int]$e.rows; when = [string]$e.when;
                                 start = $e.start.ToString($TS); end = $e.end.ToString($TS) }
                if ($kind -eq 'mail') {
                    $x.rows_in = [int]$e.rows_in; $x.rows_out = [int]$e.rows_out; $x.st_in = [string]$e.st_in; $x.st_out = [string]$e.st_out
                } else { $x.st = [string]$e.st }
                $o[$kind][$k] = $x
            }
            foreach ($k in ($c.partial[$kind].Keys | Sort-Object -Descending)) {
                $e = $c.partial[$kind][$k]
                $x = [ordered]@{ start = $e.start.ToString($TS); end = $e.end.ToString($TS) }
                if ($kind -eq 'mail') {
                    $x.done = @($e.done.Keys); $bo = [ordered]@{}
                    foreach ($bk in $e.before.Keys) { $bo[$bk] = [string]$e.before[$bk] }
                    $x.before = $bo
                } else { $x.from = [string]$e.from }
                $o.partial[$kind][$k] = $x
            }
        }
        ($o | ConvertTo-Json -Depth 7) | Set-Content -Path $covP -Encoding UTF8
    } catch { Write-Host ("[outlook] coverage.json 저장 실패: {0}" -f $_.Exception.Message) }
}
function Test-Covered([string]$kind, $mo) {
    # 완료 표의 달이 이번에 부른 [start, end) 를 전부 덮을 때만 '읽었다'로 본다
    $e = $script:cov[$kind][$mo.key]
    if (-not $e) { return $false }
    return (($e.start -le $mo.start) -and ($e.end -ge $mo.end))
}
function Get-Partial([string]$kind, $mo) {
    # 같은 [start, end) 로 읽다 멈춘 표식만 유효 - 기간이 달라졌으면 처음부터
    $e = $script:cov.partial[$kind][$mo.key]
    if (-not $e) { return $null }
    if (($e.start -ne $mo.start) -or ($e.end -ne $mo.end)) { return $null }
    return $e
}

# ── 기존 CSV 를 달별로 나눠 든다(행은 원문 그대로) - 다시 읽는 달만 바꾸고 나머지는 보존 ────────────
function Month-Of([string]$line, [int]$timeCol) {
    # timeCol: 시각 열 위치(0부터). 앞 열들에는 쉼표가 없다(box 는 inbox/sent, start 는 시각) - 정규식으로 충분하다
    $re = '^' + ('[^,]*,' * $timeCol) + '(\d{4})-(\d{2})-(\d{2})'
    $m = [regex]::Match($line, $re)
    if (-not $m.Success) { return $null }
    try { $d = New-Object DateTime ([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value) } catch { return $null }
    return @{ key = ($m.Groups[1].Value + '-' + $m.Groups[2].Value); date = $d }
}
function Load-CsvByMonth([string]$path, [int]$timeCol) {
    $by = @{}
    if (-not (Test-Path $path)) { return $by }
    $cut = (Get-Date).Date.AddDays(-$KeepDays)
    $n = 0
    foreach ($line in (Read-Lines $path)) {
        $n++
        if ($n -eq 1) { continue }                          # 머리말
        if (-not $line) { continue }
        $mo = Month-Of $line $timeCol
        if (-not $mo) { continue }                          # 형식이 어긋난 행은 버린다(구판 헤더 등)
        if ($mo.date -lt $cut) { continue }                 # KeepDays 보다 오래된 행은 버린다
        if (-not $by.ContainsKey($mo.key)) { $by[$mo.key] = [System.Collections.Generic.List[string]]::new() }
        $by[$mo.key].Add($line)
    }
    return $by
}
function Add-Rows($by, $rows, [int]$timeCol, [string]$defaultKey) {
    # 읽어 온 행을 '그 행의 달'로 넣는다 - 달 경계에 걸친 일정 회차(6/30 시작)는 6월 버킷으로. 형식이 어긋나면 읽던 달로
    foreach ($line in $rows) {
        $mo = Month-Of $line $timeCol
        $k = $(if ($mo) { $mo.key } else { $defaultKey })
        if (-not $by.ContainsKey($k)) { $by[$k] = [System.Collections.Generic.List[string]]::new() }
        $by[$k].Add($line)
    }
}
function Write-CsvByMonth([string]$path, [string]$header, $by, [bool]$dedupe) {
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add($header)
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($k in ($by.Keys | Sort-Object -Descending)) {
        foreach ($line in $by[$k]) {
            if ($dedupe) { if ($seen.Add($line)) { $lines.Add($line) } }   # 일정: 달 경계·이어 읽기 경계의 같은 회차만 한 번
            else { $lines.Add($line) }                                      # 메일: 같은 분·같은 제목의 두 통도 실제 2건
        }
    }
    $tmp = $path + '.tmp'
    [System.IO.File]::WriteAllLines($tmp, $lines, [System.Text.Encoding]::UTF8)
    $ok = $false
    for ($i = 0; $i -lt 5 -and -not $ok; $i++) {
        try { Move-Item -LiteralPath $tmp -Destination $path -Force; $ok = $true }
        catch { Start-Sleep -Milliseconds 200 }             # 화면(/api/dash)이 CSV 를 읽는 중 - 잠시 뒤 다시
    }
    if (-not $ok) {
        # 교체가 계속 막히면 제자리에 쓴다(예전 방식) - 한 달 쓰기 실패로 수집 전체를 끊지 않는다
        try { [System.IO.File]::WriteAllLines($path, $lines, [System.Text.Encoding]::UTF8) } catch { Write-Host ("[outlook] 경고: {0} 저장 실패 - {1}" -f (Split-Path -Leaf $path), $_.Exception.Message) }
        try { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue } catch {}
    }
    return ($lines.Count - 1)
}

# ── 버전 강건성: 2016/2019/2021/365 '클래식' Outlook 은 전부 동일한 COM(Outlook.Application)
# 을 쓰므로 버전 구분이 필요 없다. 문제는 '새 Outlook'(olk.exe) - COM 인터페이스 자체가 없어
# 어떤 버전 표기든 수집이 통째로 빈다(실측: 'PC마다 메일 누락'의 주원인 후보).
# LM28: 판·설치 방식(C2R/MSI)·새 Outlook 흔적·프로필·권한은 OutlookCommon 으로 한 번 모아 LMSTATUS counts 에 늘 싣는다(REQ-17·W1-18).
# 판정은 진단·사유 표기에만 쓴다 - 클래식이 있으면 새 Outlook 흔적이 있어도 COM 을 시도한다(LM24).
$counts = [ordered]@{ elevated = $false; profile_locs = @(); profiles = 0; profiles_usable = 0; curver = ''; curver_mismatch = $false;
                      ol = [ordered]@{ found = $false; c2r = $false; msi = $false; ver = '' };
                      new_ol = [ordered]@{ useNew = $false; olk = $false; appx = $false; autoMig = $null };
                      running = $false; launched = $false; attach_hr = ''; filter_fmt = ''; canary = ''; filter_mismatch = 0;
                      folders = 0; folders_excluded = 0; folders_capped = $false; prot = ''; rcv_unknown = 0 }
$reasons = [System.Collections.Generic.List[string]]::new()
$ranges = [System.Collections.Generic.List[object]]::new()
$stRc = 0                     # LMSTATUS rc(= 종료 코드)
$newOutlook = $false
$olRunning = $false
if (-not $SelfTest) {
    $olRunning = Test-OcProc $null 'outlook'
    $classic = Find-ClassicOutlook
    $trace = Get-NewOutlookTrace
    $prof = Get-OutlookProfileState
    $verdict = Get-ProfileVerdict -Running $olRunning -Prof $prof -Trace $trace -Classic $classic
    $newOutlook = [bool]$trace.any
    $counts.elevated = [bool](Test-OcElevated); $counts.running = $olRunning
    $counts.profile_locs = @($prof.locs); $counts.profiles = [int]$prof.total; $counts.profiles_usable = [int]$prof.usable
    $counts.curver = [string]$prof.curver; $counts.curver_mismatch = [bool]$prof.curverMismatch
    $counts.ol = [ordered]@{ found = [bool]$classic.found; c2r = [bool]$classic.c2r; msi = [bool]$classic.msi; ver = [string]$classic.ver }
    $counts.new_ol = [ordered]@{ useNew = [bool]$trace.useNew; olk = [bool]$trace.olk; appx = [bool]$trace.appx; autoMig = $trace.autoMig }
    if ($newOutlook) {
        Write-Host '[outlook] 주의: "새 Outlook" 사용이 감지되었습니다 - 새 Outlook 은 데이터 접근(COM)을 제공하지 않습니다.'
        Write-Host '          클래식 Outlook 을 함께 두면 됩니다: 새 Outlook 우상단 [새 Outlook] 토글을 끄거나,'
        Write-Host '          클래식 Outlook(2016~365)을 실행해 두고 다시 수집하세요. (계속 시도합니다)'
    }
    if ($classic.found) {
        Write-Host ("[outlook] 클래식 Outlook: v{0} ({1}){2}" -f $classic.ver, $(if ($classic.c2r -and $classic.msi) { 'C2R+MSI' } elseif ($classic.c2r) { 'C2R' } else { 'MSI' }),
                    $(if ($counts.elevated) { ' · 관리자 권한 실행' } else { '' }))
    }
}

# 건너뛴/실패한 사유를 남긴다 - 대시보드가 이것을 읽어 '메일 0건'의 이유를 말해 준다.
# 없으면 화면은 "Outlook 을 켜세요"라고만 하는데, 마법사에 막힌 PC 는 이미 켜져 있어
# 그 안내가 오히려 원인을 가린다(실측). LM28: 파일은 늘 data\outlook\ 에(-OutDir 와 무관 - 화면이 읽는 곳), 자가검증은 건드리지 않는다.
function Set-SkipReason([string]$reason) {
    if ($SelfTest) { return }
    try {
        $f = Join-Path $skipDir 'outlook_skip.json'
        if (-not (Test-Path $skipDir)) { New-Item -ItemType Directory -Force -Path $skipDir | Out-Null }
        $o = [ordered]@{ reason = $reason; when = (Get-Date).ToString('yyyy-MM-dd HH:mm') }
        ($o | ConvertTo-Json -Compress) | Set-Content -Path $f -Encoding UTF8
    } catch {}
}
function Clear-SkipReason {
    if ($SelfTest) { return }
    try { Remove-Item (Join-Path $skipDir 'outlook_skip.json') -ErrorAction SilentlyContinue } catch {}
}
function Get-BlockedRanges([string]$st) {
    # 이번 실행이 아무것도 읽지 못했을 때의 ranges - 기간 전체 × 세 축
    $o = [System.Collections.Generic.List[object]]::new()
    foreach ($ax in @('mail_in', 'mail_out', 'cal')) {
        $o.Add([ordered]@{ axis = $ax; from = $since.ToString('yyyy-MM-dd'); to = $until.AddDays(-1).ToString('yyyy-MM-dd'); st = $st })
    }
    return $o
}

# ── 프로필 사전 점검 (버전 불일치 대응) ─────────────────────────────────────
# COM 기동은 '등록된' Outlook 을 띄운다. 실제로 쓰는 것이 365 여도 구형 2016 설치본이
# 등록돼 있으면 그쪽이 뜨고, 그 설치본에 프로필이 없으면 '첫 실행 마법사'(모달)가 떠서
# 응답이 없다 - 그 PC 의 수집이 통째로 비고 스크립트는 무한정 대기한다(실측).
# 마법사를 띄우는 주체가 이 호출이므로, 띄우면 모달이 확실할 때(Outlook 미실행 + 프로필 0 · 주소록만 든 프로필 ·
# 관리자 전환 정책)는 COM 을 건드리지 않는다(LM28 - exit 3 + 사유. LM24 는 exit 0 으로 실패를 가렸다).
# 프로필이 0 인데 새 Outlook 흔적이 있으면 '계정 미설정'이 아니라 새 Outlook 사용이다(F-02 - R-NEWOL).
if (-not $SelfTest -and $verdict) {
    $msg = ''
    switch ($verdict) {
        'R-NEWOL' {
            Write-Host '[outlook] 건너뜀: 새 Outlook 을 쓰는 PC 로 보입니다(새 Outlook 흔적 있음 · 클래식 Outlook 메일 프로필 0개).'
            Write-Host '          새 Outlook 은 COM 을 제공하지 않습니다 - 메일·일정은 색인·Outlook 웹 경로가 읽습니다.'
            Write-Host '          클래식 Outlook 으로 읽으려면 클래식 Outlook 을 한 번 실행해 계정을 설정한 뒤 다시 수집하세요.'
            $msg = '새 Outlook 사용(의심) — 클래식 Outlook 메일 프로필이 없어 COM 경로를 건너뜁니다(Outlook 웹 경로가 읽습니다)'
        }
        'R-NEWOLPOL' {
            Write-Host '[outlook] 건너뜀: 관리자 새 Outlook 전환 정책(DoNewOutlookAutoMigration=1)이 켜져 있고 Outlook 이 꺼져 있습니다.'
            Write-Host '          이 상태에서 클래식 Outlook 을 띄우면 전환 안내 창이 떠 수집이 멈출 수 있어 띄우지 않습니다.'
            Write-Host '          클래식 Outlook 을 직접 켜 두면 거기에 붙어 읽습니다.'
            $msg = '새 Outlook 전환 정책이 켜져 있어 꺼진 클래식 Outlook 을 띄우지 않았습니다 — 클래식 Outlook 을 켜 둔 채로 다시 수집하세요'
        }
        'R-NOCLASSIC' {
            Write-Host '[outlook] 건너뜀: 클래식 Outlook 설치(OUTLOOK.EXE·COM 등록)도 메일 프로필도 찾지 못했습니다(의심).'
            $msg = '클래식 Outlook 을 찾지 못했습니다(의심) — 색인·Outlook 웹 경로가 메일을 읽습니다'
        }
        default {
            Write-Host '[outlook] 건너뜀: 쓸 수 있는 메일 프로필이 없는 것으로 보입니다(의심 - 다른 Windows 계정·관리자 권한 실행이면 안 보일 수 있음).'
            Write-Host '          이 상태에서 COM 으로 Outlook 을 띄우면 "Outlook 시작" 설정 마법사가 떠서'
            Write-Host '          응답이 없고 수집이 멈춥니다. Outlook 을 직접 실행해 계정을 설정한 뒤,'
            Write-Host '          Outlook 을 켜 둔 채로 다시 수집하세요.'
            Write-Host '          (평소 쓰는 Outlook 이 따로 있다면, 그 Outlook 을 열어 두면 그쪽에 붙습니다.)'
            $msg = 'Outlook 메일 프로필이 구성되지 않은 것으로 보입니다 — Outlook 을 직접 실행해 계정 설정을 마친 뒤 다시 수집하세요'
        }
    }
    Set-SkipReason $msg
    Write-LmStatus -Src $srcName -Rc 3 -Reasons @($verdict) -Counts $counts -Ranges (Get-BlockedRanges 'blocked')
    exit 3
}

# ── 달 하나를 읽는 함수들 - COM 과 자가검증(SelfTest) 두 갈래. 둘 다 CSV 행 목록과 중단 사유를 돌려준다 ──
$script:stopReason = ''
$script:calLast = ''          # 일정: 이번에 읽은 마지막 시작 시각(TS) - 이어 읽기 표식
$script:calOut = 0            # 일정: 그 달과 겹치지 않아 버린 회차 수(LM28)
$script:monthMismatch = 0     # 메일: 그 달을 읽는 동안 Restrict 가 준 범위 밖 행 수(LM28 - 필터 리터럴 어긋남)
$script:protErr = 0           # 보호 멤버 접근 예외 수(LM28 - 그 행의 rcv 는 unknown)
$script:rcvUnknown = 0        # rcv=unknown 으로 남긴 받은 메일 수(LM28)
$protOk = $true               # 보호 멤버를 읽어도 되는가(LM28 - Get-ProtectedState, 위험의 긍정 증거가 있을 때만 $false)
$script:folders = @()         # 읽을 메일 폴더(LM28 - 기본 저장소 재귀) @{ node; key; box; role; field }
function Read-CalendarMonth($ns, $mo, [string]$resumeFrom) {
    # 반환: 이 달과 겹치는 일정의 CSV 행 목록(resumeFrom 이 있으면 그 시작 시각부터). 예산(절반)에 닿으면
    # $script:stopReason 을 채우고 그때까지의 행만.
    $rows = [System.Collections.Generic.List[string]]::new()
    $script:stopReason = ''; $script:calLast = ''
    $halfBudget = $BudgetSec * 0.5
    $lo = $mo.start
    if ($resumeFrom) { try { $lo = [datetime]::ParseExact($resumeFrom, $TS, $null) } catch {} }
    if ($SelfTest) {
        $n = [math]::Max(1, [int]($SelfTest / 2))
        $span = [math]::Max(1, ($mo.end - $mo.start).Days)
        for ($i = 0; $i -lt $n; $i++) {
            $st = $mo.start.AddDays($i % $span).AddHours(9 + ($i % 8))
            if ($st -lt $lo) { continue }
            if ($SelfTestDelayMs -gt 0) { Start-Sleep -Milliseconds $SelfTestDelayMs }
            if ($sw.Elapsed.TotalSeconds -gt $halfBudget) { $script:stopReason = ('일정 시간 예산({0}초) 도달' -f [math]::Round($halfBudget, 1)); break }
            $rows.Add(('{0},{1},False,2,{2},,,3,1' -f $st.ToString('yyyy-MM-dd HH:mm'), $st.AddHours(1).ToString('yyyy-MM-dd HH:mm'), ('selftest meeting ' + $i)))
            $script:calLast = $st.ToString($TS)
        }
        return $rows
    }
    $cal = $ns.GetDefaultFolder(9)  # olFolderCalendar
    $items = $cal.Items
    $items.IncludeRecurrences = $true
    # IncludeRecurrences 는 [Start] 오름차순 정렬을 요구한다(COM 규칙 - 내림차순이면 회차 전개가 깨진다). 예산에 닿으면
    # 마지막 시작 시각을 표식으로 남겨 다음 실행이 거기서부터 잇는다.
    $items.Sort('[Start]')
    # 날짜 리터럴 형식은 필터 카나리아가 고른 것(LM28 - LM24 는 'g' 고정)
    $flt = ("[Start] < '{0}' AND [End] >= '{1}' AND [Start] >= '{2}'" -f (Format-OlDate $mo.end $fmt), (Format-OlDate $mo.start $fmt), (Format-OlDate $lo $fmt))
    if ($lo -le $mo.start) { $flt = ("[Start] < '{0}' AND [End] >= '{1}'" -f (Format-OlDate $mo.end $fmt), (Format-OlDate $mo.start $fmt)) }
    $sel = $items.Restrict($flt)
    $count = 0
    foreach ($it in $sel) {
        $count++
        if ($count -gt 8000) { $script:stopReason = '일정 상한 8000건(깨진 반복 일정?)'; break }   # runaway guard for broken recurrences
        if (($count % 100) -eq 0 -and $sw.Elapsed.TotalSeconds -gt $halfBudget) {
            $script:stopReason = ('일정 시간 예산({0}초) 도달' -f [math]::Round($halfBudget, 1)); break
        }
        try {
            # 결과 재검사(LM28): 그 달과 겹치지 않는 회차는 버린다(반복 전개가 창 밖 회차를 주기도 한다 - 셈만)
            if ($it.Start -ge $mo.end -or $it.End -lt $mo.start) { $script:calOut++; continue }
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
            try { $script:calLast = $it.Start.ToString($TS) } catch {}
        } catch {}
    }
    return $rows
}
function Read-MailMonth($mo, [string[]]$me, $state) {
    # 반환: 이 달의 메일 CSV 행 목록(state 에 '여기까지 읽음' 표식이 있으면 그 이전만). 예산에 닿으면
    # $script:stopReason 을 채우고, 멈춘 폴더의 경계 분(같은 분의 행은 버리고 다음에 다시 읽는다)을 state 에 남긴다.
    # LM28: 받은·보낸 편지함 최상위만이 아니라 $script:folders(기본 저장소 메일 폴더 재귀 - 보낸 편지함 하위는 sent, 그 밖은 inbox)
    #   를 읽고, '다 읽음'·'여기까지' 표식은 폴더(EntryID 표식)마다 둔다. state = @{ done = @{ 표식 = $true }; before = @{ 표식 = TS } }.
    # rcv = 수신 구분: to(직접 수신) / cc(참조) / bulk(내 주소가 To/CC에 없음 - 배포리스트·공지) / unknown(보호 멤버를 못 읽음·내 주소 모름)
    # CC·단체발송이 본인 업무로 계상되는 오류를 분석기에서 분리하기 위한 핵심 열이다.
    $rows = [System.Collections.Generic.List[string]]::new()
    $script:stopReason = ''
    foreach ($b in $script:folders) {
        $fk = [string]$b.key
        if ($state.done.ContainsKey($fk)) { continue }
        $upper = $mo.end
        if ($state.before.ContainsKey($fk) -and $state.before[$fk]) {
            # 경계 분 '이하'를 다시 읽는다 - Restrict 는 분 단위 문자열이라 (경계 + 1분) 미만으로 잡아야 그 분의 행이 전부 든다
            try { $upper = ([datetime]::ParseExact([string]$state.before[$fk], $TS, $null)).AddMinutes(1) } catch {}
            if ($upper -gt $mo.end) { $upper = $mo.end }
        }
        $boxRows = [System.Collections.Generic.List[string]]::new()
        $stop = ''; $lastT = $null
        if ($SelfTest) {
            for ($i = 0; $i -lt $SelfTest; $i++) {
                $t = $mo.end.AddMinutes(-1 - $i * 97)
                if ($t -lt $mo.start) { $t = $mo.start.AddMinutes($i) }
                if ($t -ge $upper) { continue }
                if ($SelfTestDelayMs -gt 0) { Start-Sleep -Milliseconds $SelfTestDelayMs }
                if ($sw.Elapsed.TotalSeconds -gt $BudgetSec) { $stop = ('시간 예산 {0}초' -f $BudgetSec); break }
                $boxRows.Add(('{0},{1},{2},{3},{4},{5},minute' -f $b.box, $t.ToString('yyyy-MM-dd HH:mm'), 'selftest', ('selftest mail ' + $i), ('conv ' + ($i % 3)), $(if ($b.box -eq 'inbox') { 'to' } else { '' })))
                $lastT = $t
            }
        } else {
            $mi = $b.node.Items
            $mi.Sort($b.field, $true)                   # 최신순 - 예산에 닿으면 '여기까지 읽음' 경계를 남기고 다음 실행이 그 아래를 잇는다
            $mflt = ("{0} >= '{1}' AND {0} < '{2}'" -f $b.field, (Format-OlDate $mo.start $fmt), (Format-OlDate $upper $fmt))
            $msel = $mi.Restrict($mflt)
            $n = 0
            foreach ($m in $msel) {
                $n++
                if ($n -gt 20000) { $stop = ('{0} 상한 20000건' -f $b.box); break }
                if (($n % 50) -eq 0 -and $sw.Elapsed.TotalSeconds -gt $BudgetSec) { $stop = ('시간 예산 {0}초' -f $BudgetSec); break }
                try {
                    if ($m.Class -ne 43) { continue }  # olMail only
                    $t = if ($b.box -eq 'inbox') { $m.ReceivedTime } else { $m.SentOn }
                    # 결과 재검사(LM28 C-06): Restrict 결과를 [start, upper) 로 다시 거른다 - 로캘 리터럴이 어긋나면 범위 밖 행이 온다
                    if ($t -lt $mo.start -or $t -ge $upper) { $script:monthMismatch++; continue }
                    $subj = ''
                    $conv = [string]$m.ConversationTopic
                    if ($storeSubject) { $subj = [string]$m.Subject } else { $conv = Conv-Token $conv }
                    # 보낸 사람 이름은 보호 멤버 - 위험의 긍정 증거가 있으면 읽지 않고, 예외면 빈칸(행은 버리지 않는다)
                    $sender = ''
                    if ($protOk) { try { $sender = [string]$m.SenderName } catch { $script:protErr++ } }
                    $rcv = ''
                    if ($b.box -eq 'inbox' -and -not $protOk) {
                        $rcv = 'unknown'                                  # 보호 멤버(To·CC·Recipients)를 읽지 않는다(C-05)
                    } elseif ($b.box -eq 'inbox') {
                        # 수신자 판정은 To/CC 표시 문자열(PR_DISPLAY_TO/CC) 1회 조회로 - 수신자마다 PropertyAccessor 를
                        # 부르던 왕복(N배)을 없앤다. 표시 이름으로 못 찾을 때만 소규모 수신자 목록을 주소로 정밀 확인.
                        $rcv = 'bulk'
                        $toS = ''; $ccS = ''; $pe = $false
                        try { $toS = [string]$m.To } catch { $pe = $true }
                        try { $ccS = [string]$m.CC } catch { $pe = $true }
                        if ($pe) { $rcv = 'unknown'; $script:protErr++ }  # 보호 멤버 접근 실패 - 'to' 로 올리지 않는다(LM28)
                        elseif (Test-MeInList $toS $me) { $rcv = 'to' }
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
                                } catch { $rcv = 'unknown'; $script:protErr++ }   # 수신자 열람 실패 - LM24 는 'to' 로 올렸다(오판, C-05)
                            }
                        }
                    }
                    if ($rcv -eq 'unknown') { $script:rcvUnknown++ }
                    $boxRows.Add(('{0},{1},{2},{3},{4},{5},minute' -f `
                        $b.box, $t.ToString('yyyy-MM-dd HH:mm'), (Csv-Escape $sender), `
                        (Csv-Escape $subj), (Csv-Escape $conv), $rcv))
                    $lastT = $t
                } catch {}
            }
        }
        if ($stop) {
            # 경계 분의 행은 버리고 표식만 남긴다 - 다음 실행이 그 분부터(포함) 다시 읽으므로 빠짐도 중복도 없다
            if ($lastT) {
                $bm = $lastT.ToString('yyyy-MM-dd HH:mm')
                $kept = [System.Collections.Generic.List[string]]::new()
                foreach ($line in $boxRows) { if (-not $line.StartsWith($b.box + ',' + $bm + ',')) { $kept.Add($line) } }
                $boxRows = $kept
                $state.before[$fk] = $lastT.ToString($TS)
            }
            foreach ($line in $boxRows) { $rows.Add($line) }
            $script:stopReason = $stop
            return $rows
        }
        foreach ($line in $boxRows) { $rows.Add($line) }
        $state.done[$fk] = $true
    }
    return $rows
}
function Months-ToRead([string]$kind) {
    # 읽는 순서: ① 최신 달(새 메일이 붙는 달) → ② 아직 못 읽은 달(최신→과거) → ③ 나머지 재수집 달.
    # 못 읽은 달을 재수집 달보다 앞에 둔다 - 재수집 달을 먼저 읽으면 예산이 거기서 다 닳아 실행을 거듭해도
    # 옛 달에 영영 못 간다(자가검증에서 실측). -NoRefresh(run.py 연속 회차)면 ②만.
    # 반환은 목록을 풀어서(호출측 @()) - ',$list' 로 돌리면 목록 하나가 원소가 돼 $mo 가 달이 아니라 목록이 된다(재검증 실측).
    $out = [System.Collections.Generic.List[object]]::new()
    $added = @{}
    if ($Force) {
        foreach ($mo in $months) { $out.Add($mo); $added[$mo.key] = $true }
        return $out
    }
    if (-not $NoRefresh -and $months.Count -gt 0) { $out.Add($months[0]); $added[$months[0].key] = $true }
    foreach ($mo in $months) {
        if (-not $added.ContainsKey($mo.key) -and -not (Test-Covered $kind $mo)) { $out.Add($mo); $added[$mo.key] = $true }
    }
    if (-not $NoRefresh) {
        $i = 0
        foreach ($mo in $months) {
            if ($i -lt $REFRESH_MONTHS -and -not $added.ContainsKey($mo.key)) { $out.Add($mo); $added[$mo.key] = $true }
            $i++
        }
    }
    return $out
}
function Stop-Collect([string]$code) {
    # 계획된 중단(LM28) - 사유를 남기고 아래 catch 로 간다. finally(이 수집이 띄운 Outlook 정리) 뒤에 LMSTATUS 를 한 번만 낸다.
    $script:fatal = $code
    throw (New-Object System.OperationCanceledException $code)
}
function Add-Verdict([string]$axis, $mo, $v) { $script:verd[$axis + '|' + $mo.key] = $v }
function Build-Ranges {
    # 기간의 달마다 축별 ranges - 이번에 읽은 달은 판정(Test-MonthDone)으로, 읽지 않았지만 완료 표에 있는 달은 표의 st 로.
    # 둘 다 아니면(예산으로 못 간 달) 싣지 않는다 - 원장의 지난 상태를 덮지 않게.
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($mo in $months) {
        foreach ($ax in @('mail_in', 'mail_out', 'cal')) {
            $k = $ax + '|' + $mo.key
            if ($script:verd.ContainsKey($k)) { foreach ($x in @(ConvertTo-LmRanges $ax $mo.start $mo.end $script:verd[$k])) { $out.Add($x) }; continue }
            $kind = $(if ($ax -eq 'cal') { 'calendar' } else { 'mail' })
            if (-not (Test-Covered $kind $mo)) { continue }
            $e = $script:cov[$kind][$mo.key]
            $st = $(if ($ax -eq 'mail_in') { $e.st_in } elseif ($ax -eq 'mail_out') { $e.st_out } else { $e.st })
            if (-not $st) { $st = 'ok' }
            $out.Add([ordered]@{ axis = $ax; from = $mo.start.ToString('yyyy-MM-dd'); to = $mo.end.AddDays(-1).ToString('yyyy-MM-dd'); st = $st })
        }
    }
    return $out
}
$script:verd = @{}             # '<축>|yyyy-MM' → Test-MonthDone 결과(이번에 읽은 달)
$script:fatal = ''
$launched = $false; $launchT = $null; $wd = $null
$hz = @{ oldest = $null; newest = $null }
$cached = $false

try {
    # ── 지난 표·CSV 읽기(여기서 실패해도 사유가 남게 try 안) ──
    $script:cov = Load-Coverage
    if ($Force) { $script:cov = New-Coverage }
    $mailBy = Load-CsvByMonth $mailP 1
    $calBy  = Load-CsvByMonth $calP  0
    # 지난 표에 '완료'로 남았는데 CSV 에 그 달 행이 하나도 없으면 표를 믿지 않는다(파일만 지운 경우).
    # LM28: 'rows 0 이면 완료 보존' 예외는 없앴다 - 0행으로 남겨도 되는 달은 카나리아·지평선·OST 신선도로 검증된 zero_ok 뿐이다(W1-02)
    foreach ($kind in @('mail', 'calendar')) {
        $by = $(if ($kind -eq 'mail') { $mailBy } else { $calBy })
        foreach ($k in @($script:cov[$kind].Keys)) {
            if ($by.ContainsKey($k)) { continue }
            $e = $script:cov[$kind][$k]
            $zok = $(if ($kind -eq 'mail') { $e.st_in -eq 'zero_ok' -and $e.st_out -eq 'zero_ok' } else { $e.st -eq 'zero_ok' })
            if ([int]$e.rows -gt 0 -or -not $zok) { $script:cov[$kind].Remove($k) }
        }
    }
    $mailTodo = @(Months-ToRead 'mail')
    $calTodo  = @(Months-ToRead 'calendar')
    Write-Host ("[outlook] 기간 {0} ~ {1} · {2}개월 · 읽을 달: 메일 {3} / 일정 {4} (완료된 달은 건너뜀{5}{6}) · 예산 {7}초" -f `
        $since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'), $months.Count, $mailTodo.Count, $calTodo.Count, `
        $(if ($Force) { ' - Force 로 전부 다시' } else { '' }), $(if ($NoRefresh) { ' - 이어서 읽기 회차' } else { '' }), $BudgetSec)

    $ns = $null
    $me = @()
    if ($SelfTest) {
        Write-Host ("[outlook] 자가검증 모드 - Outlook 없이 달마다 가짜 메일 {0}건·일정 {1}건 (표·mail_source 에 selftest 표식)" -f $SelfTest, [math]::Max(1, [int]($SelfTest / 2)))
        $me = @('selftest@corp.local')
        # 레지스트리·프로세스·COM 을 건드리지 않는다 - 카나리아 성공·지평선은 기간 앞·캐시 모드 아님으로 둔다
        $canary = 'ok'; $hz = @{ oldest = $since.AddDays(-1); newest = (Get-Date) }
        $script:folders = @(@{ key = 'inbox'; box = 'inbox'; role = 'inbox'; field = '[ReceivedTime]' },
                            @{ key = 'sent'; box = 'sent'; role = 'sent'; field = '[SentOn]' })
        $counts.filter_fmt = $fmt; $counts.canary = $canary; $counts.folders = 2; $counts.prot = 'selftest'
    } else {
        # 이미 떠 있는 Outlook 에 먼저 붙는다 - 사용자가 실제로 쓰는 버전이 그것이고,
        # 새 인스턴스 기동은 등록된(다를 수 있는) 설치본을 띄우기 때문이다.
        # 떠 있는 Outlook 에 붙기를 먼저 시도한다. 바쁜 순간에는 거부(RPC_E_CALL_REJECTED)될
        # 수 있는데 영구 실패가 아니므로 짧게 재시도한다.
        $hr = ''
        for ($try = 1; $try -le 3 -and -not $ol; $try++) {
            try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') } catch { $ol = $null; $hr = Get-OcHResult $_ }
            if (-not $ol -and $try -lt 3) { Start-Sleep -Seconds 2 }
        }
        if (-not $ol -and $olRunning) {
            # Outlook 이 실행 중인데 붙을 수 없다 = COM 을 아직 등록하지 않았다 = 시작 마법사·
            # 프로필 선택·암호 입력 같은 대화상자에 막혀 있다는 뜻이다. 이때 New-Object 를
            # 부르면 그 창이 닫힐 때까지 **반환되지 않는다**(실측: 300초 무응답). 부르지 않는다.
            # LM28(C-04·W1-18): 원인을 가른다 - 이 셸이 관리자 권한이면 R-ELEV(상승한 셸은 일반 권한 Outlook 의 COM 을 못 본다) ·
            # 바쁨(0x80010001 RPC_E_CALL_REJECTED · 0x8001010A RPC_E_SERVERCALL_RETRYLATER)은 attachWaitSec 까지 다시 붙어 본 뒤 R-BUSY ·
            # 막 뜬 Outlook 은 COM 등록(ROT)이 늦을 수 있어 시작 뒤 attachWaitSec 까지 기다린다 · 그 밖은 대화상자(R-DIALOG).
            $why = ''
            if ($counts.elevated) { $why = 'R-ELEV' }
            else {
                $olStart = $null
                try { $olStart = @(Get-Process outlook -ErrorAction SilentlyContinue | ForEach-Object { try { $_.StartTime } catch {} } | Where-Object { $_ } | Sort-Object)[-1] } catch {}
                $tw = [System.Diagnostics.Stopwatch]::StartNew()
                while (-not $ol -and $tw.Elapsed.TotalSeconds -lt $attachWait) {
                    $busy = ($hr -eq '0x8001010A' -or $hr -eq '0x80010001')
                    $young = ($null -ne $olStart -and ((Get-Date) - $olStart).TotalSeconds -lt $attachWait)
                    if (-not $busy -and -not $young) { break }
                    Start-Sleep -Seconds 3
                    try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') } catch { $ol = $null; $hr = Get-OcHResult $_ }
                }
                if (-not $ol) { $why = $(if ($hr -eq '0x8001010A' -or $hr -eq '0x80010001') { 'R-BUSY' } else { 'R-DIALOG' }) }
            }
            if (-not $ol) {
                $counts.attach_hr = $hr
                $wins = @()
                try {
                    $wins = @(Get-Process outlook -ErrorAction SilentlyContinue |
                              ForEach-Object { $_.MainWindowTitle } | Where-Object { $_ })
                } catch {}
                if ($why -eq 'R-ELEV') {
                    Write-Host '[outlook] 건너뜀: 이 수집이 관리자 권한으로 돌고 있어 일반 권한으로 뜬 Outlook 에 붙지 못합니다(R-ELEV).'
                    Write-Host '          LoadMonitor28 을 관리자 권한 없이(일반 실행) 다시 실행하세요.'
                    Set-SkipReason '수집이 관리자 권한으로 돌아 Outlook 에 붙지 못했습니다 — 일반 권한으로 다시 실행하세요'
                } elseif ($why -eq 'R-BUSY') {
                    Write-Host ("[outlook] 건너뜀: Outlook 이 {0}초 동안 바쁨 응답만 했습니다(R-BUSY {1}) - 잠시 뒤 다시 수집하세요." -f $attachWait, $hr)
                    Set-SkipReason 'Outlook 이 계속 바쁨 응답을 했습니다 — 잠시 뒤 다시 수집하세요'
                } else {
                    Write-Host '[outlook] 건너뜀: Outlook 이 실행 중이지만 아직 사용할 준비가 안 됐습니다.'
                    if ($wins.Count) { Write-Host ("          열려 있는 창: {0}" -f ($wins -join ' / ')) }
                    Write-Host '          보통 "Outlook 시작" 설정 마법사·프로필 선택·암호 입력 창이 떠 있을 때입니다.'
                    Write-Host '          그 창을 닫거나 설정을 끝내고 메일 화면까지 연 다음 다시 수집하세요.'
                    Write-Host '          (설치 문제가 아닙니다 - 재설치하지 마세요)'
                    Set-SkipReason ("Outlook 이 대화상자에 막혀 있습니다" +
                        $(if ($wins.Count) { " (열린 창: " + ($wins -join ' / ') + ")" } else { '' }) +
                        " — 그 창을 닫고 메일 화면까지 연 다음 다시 수집하세요")
                }
                Stop-Collect $why
            }
        }
        if (-not $ol) {
            # Outlook 미실행일 때만 이 수집이 띄운다(LM28 F-15). 띄운 시각을 남겨 끝에 이 수집이 띄운 것만 닫는다.
            # 무진전 감시: attachWaitSec 안에 받은 편지함(MAPI 초기화)까지 못 가면 이 수집이 띄운 Outlook(-Embedding)만 끝낸다 -
            # 시작 마법사·프로필 선택 창이 화면에 남아 다음 사람을 막던 것(현장 V8).
            $launchT = Get-Date
            $launched = $true; $counts.launched = $true
            $wd = Start-OcLaunchWatchdog -Sec $attachWait -Since $launchT
            try {
                $ol = New-Object -ComObject Outlook.Application
                $ns = $ol.GetNamespace('MAPI')
                # ShowDialog=$false - 프로필 선택창·설정 마법사를 원천 차단한다. 이미 로그온된
                # 세션이면 무시되고, 아니면 기본 프로필로 조용히 붙는다. LM28: 우리가 띄웠을 때만 부른다(떠 있는 Outlook 에는 부르지 않는다).
                try { $ns.Logon($null, $null, $false, $false) } catch {}
                [void]$ns.GetDefaultFolder(6)
            } catch {
                $hr = Get-OcHResult $_
                $counts.attach_hr = $hr
                $fired = [bool]$wd.sync.fired
                Stop-OcLaunchWatchdog $wd; $wd = $null
                if ($fired) {
                    Write-Host ("[outlook] 건너뜀: Outlook 을 띄웠지만 {0}초 안에 메일 화면까지 가지 못해 이 수집이 띄운 Outlook 을 닫았습니다(R-WIZARD)." -f $attachWait)
                    Write-Host '          보통 "Outlook 시작" 설정 마법사·프로필 선택·암호 입력 창입니다(의심). Outlook 을 직접 실행해 확인하세요.'
                    Set-SkipReason 'Outlook 을 띄웠지만 메일 화면까지 가지 못했습니다(시작 마법사·프로필 선택 창 의심) — Outlook 을 직접 실행해 확인하세요'
                    Stop-Collect 'R-WIZARD'
                }
                if ($hr -eq '0x80040154') {
                    Write-Host '[outlook] 건너뜀: 클래식 Outlook 이 COM 에 등록돼 있지 않습니다(R-NOCLASSIC - 미설치 의심).'
                    Set-SkipReason '클래식 Outlook 이 COM 에 등록돼 있지 않습니다(미설치 의심) — 색인·Outlook 웹 경로가 메일을 읽습니다'
                    Stop-Collect 'R-NOCLASSIC'
                }
                $nk = Stop-OutlookWeStarted -Since $launchT
                Write-Host ("[outlook] 건너뜀: Outlook 을 띄우지 못했습니다(R-LAUNCH {0}){1}" -f $hr, $(if ($nk) { (' - 이 수집이 띄운 Outlook {0}개 정리' -f $nk) } else { '' }))
                Set-SkipReason ('Outlook 을 띄우지 못했습니다(' + $hr + ') — 클래식 Outlook 을 직접 실행해 메일 화면까지 연 뒤 다시 수집하세요')
                Stop-Collect 'R-LAUNCH'
            }
            $fired = [bool]$wd.sync.fired
            Stop-OcLaunchWatchdog $wd; $wd = $null
            if ($fired) { Stop-Collect 'R-WIZARD' }       # 막 붙은 순간 감시가 끝냈다 - 이번 실행은 쓰지 않는다
        } else {
            $ns = $ol.GetNamespace('MAPI')
            # 떠 있는 Outlook - Logon 을 부르지 않는다(문서: 프로필이 여럿이면 기본 프로필 Logon 에도 선택 창이 뜬다). 받은 편지함으로 MAPI 를 연다
            try { [void]$ns.GetDefaultFolder(6) } catch {}
        }
        # 어느 설치본이 잡혔는지 남긴다 - 'PC 마다 누락'을 원격으로 판별하는 유일한 단서다.
        try {
            $exe = ''
            try { $exe = (Get-Process outlook -ErrorAction SilentlyContinue |
                          Select-Object -First 1).Path } catch {}
            Write-Host ("[outlook] 연결: 버전 {0}{1}" -f $ol.Version,
                        $(if ($exe) { " ($exe)" } else { '' }))
        } catch {}
        # 보호 멤버(LM28 C-05): 위험의 긍정 증거(정책 '묻기·거부'·'항상 경고'·백신 꺼짐)가 있으면 읽지 않는다 - 경고창에 멈추지 않게
        $pst = Get-ProtectedState
        $protOk = [bool]$pst.safe; $counts.prot = [string]$pst.why
        if (-not $protOk) {
            $reasons.Add('R-OMG')
            Write-Host ("[outlook] 주의: 보호 멤버(받는 사람·보낸 사람 이름·내 주소)를 읽지 않습니다 - 경고창 위험 근거 {0} (받은 메일 rcv=unknown)" -f $pst.why)
        }
        # 내 주소·이름(수신 구분용) - 계정 표시 이름(보호 멤버 아님 - 주소 꼴일 때만)은 늘, 보호 멤버(SmtpAddress·CurrentUser)는 안전할 때만
        try { foreach ($a in $ns.Accounts) { try { $dn = ([string]$a.DisplayName).Trim(); if ($dn -match $script:OC_ADDR_RX) { $me += $dn.ToLower() } } catch {} } } catch {}
        if ($protOk) {
            try {
                $acc = $ns.Accounts
                foreach ($a in $acc) { if ($a.SmtpAddress) { $me += $a.SmtpAddress.ToLower() } }
            } catch { $script:protErr++ }
            try { $me += $ns.CurrentUser.Name.ToLower() } catch {}
            try { if ($ns.CurrentUser.Address) { $me += ([string]$ns.CurrentUser.Address).ToLower() } } catch {}
            try {
                $xu = $ns.CurrentUser.AddressEntry.GetExchangeUser()
                if ($xu -and $xu.PrimarySmtpAddress) { $me += ([string]$xu.PrimarySmtpAddress).ToLower() }
            } catch {}
        }
        try { if ($cfg.owner) { $me += ([string]$cfg.owner).Trim().ToLower() } } catch {}
        $me = @($me | Where-Object { $_ -and $_.Length -ge 2 } | Select-Object -Unique)
        if (-not @($me | Where-Object { $_ -match $script:OC_ADDR_RX }).Count) {
            # 내 주소를 확정하지 못했다(C-12) - 이름으로만 대조하고, 못 가리면 unknown(bulk 로 버리거나 to 로 올리지 않는다)
            $reasons.Add('R-NOADDR')
            Write-Host '[outlook] 주의: 내 메일 주소를 확정하지 못했습니다(R-NOADDR) - config.owner 에 주소를 적으면 수신 구분(to/cc/bulk)이 정확해집니다'
        }

        # 읽을 메일 폴더(LM28 C-07·W1-03): 기본 저장소 루트에서 재귀(outlook.subfolders=false 면 LM24 처럼 받은·보낸 편지함 최상위만).
        # PST·IMAP·공유·보관 사서함은 읽지 않는다(기본 저장소만).
        $store = $null; try { $store = $ns.DefaultStore } catch {}
        try { $cached = [bool]$store.IsCachedExchange } catch { $cached = $false }
        $defs = @{}
        foreach ($n in (@(6, 5) + $script:OC_SKIP_FOLDERS)) {
            $fd = $null
            try { $fd = $store.GetDefaultFolder($n) } catch { try { $fd = $ns.GetDefaultFolder($n) } catch {} }
            if ($fd) { try { $defs[$n] = [string]$fd.EntryID } catch {} }
        }
        $base = @(@{ node = $ns.GetDefaultFolder(6); key = $(if ($defs[6]) { Get-OcKey $defs[6] } else { 'inbox' }); box = 'inbox'; role = 'inbox'; field = '[ReceivedTime]' },
                  @{ node = $ns.GetDefaultFolder(5); key = $(if ($defs[5]) { Get-OcKey $defs[5] } else { 'sent' }); box = 'sent'; role = 'sent'; field = '[SentOn]' })
        $script:folders = $base
        if ($subOn -and $store) {
            $fl = $null
            try { $fl = Get-MailFolderList -Root $store.GetRootFolder() -Defaults $defs } catch { $fl = $null }
            if ($fl -and $fl.folders.Count) {
                $script:folders = @($fl.folders)
                $counts.folders_excluded = [int]$fl.excluded; $counts.folders_capped = [bool]$fl.capped
            }
        }
        $counts.folders = @($script:folders).Count
        if ($counts.folders_capped) { Write-Host ('[outlook] 경고: 메일 폴더 상한 {0}개에 닿아 나머지 폴더는 읽지 않았습니다' -f $script:OC_FOLDERS_MAX) }

        # 캐시 지평선·OST 신선도(LM28 C-08): 받은·보낸 편지함의 가장 오래된·최근 메일. 이 수집이 띄운 캐시 모드 Outlook 이 낡았으면
        # 동기화를 잠깐(30초) 기다린다 - 보내기/받기(SyncObject)는 부르지 않는다(보낼 편지함까지 보내는 사용자 동작).
        $hz = Get-MailHorizon $base
        if ($launched -and $cached -and $staleH -gt 0 -and ($null -eq $hz.newest -or $hz.newest -lt (Get-Date).AddHours(-$staleH))) {
            $tw = [System.Diagnostics.Stopwatch]::StartNew()
            while ($tw.Elapsed.TotalSeconds -lt 30) {
                Start-Sleep -Seconds 5
                $c2 = Get-CanaryItem $base
                if ($c2 -and $c2.t -ge (Get-Date).AddHours(-$staleH)) { $hz.newest = $c2.t; break }
            }
        }

        # 날짜 필터 카나리아(LM28 C-06·F-28): 가장 최근 항목 시각 T 의 [T-2분, T+2분) 을 형식마다 걸어 그 항목이 돌아오는 첫 형식을 쓴다
        $canItem = Get-CanaryItem $base
        $probe = {
            param($f)
            if (-not $canItem) { return $null }
            $flt = ("{0} >= '{1}' AND {0} < '{2}'" -f $canItem.field, (Format-OlDate $canItem.t.AddMinutes(-2) $f), (Format-OlDate $canItem.t.AddMinutes(2) $f))
            $k = 0
            foreach ($it in $canItem.node.Items.Restrict($flt)) {
                $k++; if ($k -gt 50) { break }
                $t = Get-OcItemTime $it $canItem.field
                if ($t -and [math]::Abs(($t - $canItem.t).TotalSeconds) -le 61) { return $true }
            }
            return $false
        }
        $sel = Select-DaslFormat -Probe $probe
        $canary = [string]$sel.canary
        $counts.canary = $canary
        if ($canary -eq 'fail') {
            Write-Host '[outlook] 수집 중단: 날짜 필터 카나리아 실패 - 이 PC 의 Outlook 이 받는 날짜 형식(g · yyyy-MM-dd HH:mm · ISO)을 찾지 못했습니다(R-FILTER).'
            Write-Host '          0건을 "메일 없음"으로 굳히지 않도록 이번에는 아무 달도 완료로 적지 않습니다 - 색인·Outlook 웹 경로가 채웁니다.'
            Set-SkipReason 'Outlook 날짜 필터 형식을 찾지 못했습니다(로캘 의심) — 색인·Outlook 웹 경로가 메일을 읽습니다'
            Stop-Collect 'R-FILTER'
        }
        $fmt = [string]$sel.fmt
        $counts.filter_fmt = $fmt
        if ($canary -eq 'none') { $reasons.Add('R-NOCANARY') }     # 받은·보낸 편지함이 비었다 - 0행 달은 검증 못 함(unverified)
        Write-Host ("[outlook] 날짜 필터 형식 {0} (카나리아 {1}) · 메일 폴더 {2}개{3} · 지평선 {4} ~ {5}{6}" -f $fmt, $canary, $counts.folders,
            $(if ($subOn) { '(하위 폴더 포함)' } else { '' }),
            $(if ($hz.oldest) { $hz.oldest.ToString('yyyy-MM-dd') } else { '?' }), $(if ($hz.newest) { $hz.newest.ToString('yyyy-MM-dd') } else { '?' }),
            $(if ($cached) { ' · 캐시 모드' } else { '' }))
    }
    try { Remove-Item -LiteralPath (Join-Path $outDir 'mail.csv.part') -ErrorAction SilentlyContinue } catch {}   # 구판의 중간 저장은 더 쓰지 않는다

    $warnings = [System.Collections.Generic.List[string]]::new()
    $refreshIncomplete = [System.Collections.Generic.List[string]]::new()   # 완료했던 달을 다시 읽다 끊긴 것(옛 행 유지)
    $now = (Get-Date).ToString('yyyy-MM-dd HH:mm')
    $readCal = 0; $readMail = 0
    if ($counts.folders_capped) { $warnings.Add(('메일 폴더 상한 {0}개 - 나머지 폴더는 읽지 않음' -f $script:OC_FOLDERS_MAX)) }

    # ---------- calendar: 최신 달부터, 예산의 절반까지 ----------
    foreach ($mo in $calTodo) {
        if ($sw.Elapsed.TotalSeconds -gt ($BudgetSec * 0.5)) { break }
        $wasComplete = Test-Covered 'calendar' $mo
        $p = Get-Partial 'calendar' $mo
        $rows = @(Read-CalendarMonth $ns $mo $(if ($p) { $p.from } else { '' }))
        if ($script:stopReason) {
            if ($wasComplete) {
                # 완료했던 달의 재수집이 끊겼다 - 옛 행을 지키고 다음 실행이 처음부터 다시 읽는다
                $refreshIncomplete.Add('일정 ' + $mo.key)
                $warnings.Add(('일정 {0}: {1} - 지난 수집분을 그대로 두고 다음 실행에서 다시 읽습니다' -f $mo.key, $script:stopReason))
            } else {
                # 부분: 이어 읽던 행(있으면) + 이번 행. 완료 표시는 안 하고 '여기까지' 표식만 남긴다
                if (-not $p) { $calBy.Remove($mo.key) }
                Add-Rows $calBy $rows 0 $mo.key
                $script:cov.partial.calendar[$mo.key] = @{ from = $script:calLast; start = $mo.start; end = $mo.end }
                $warnings.Add(('일정 {0}: {1} - 이 달은 다음 실행에서 이어서 읽습니다' -f $mo.key, $script:stopReason))
                Add-Verdict 'cal' $mo (Test-MonthDone -Rows 0 -Canary $canary -Start $mo.start -End $mo.end -Cached $false -Stopped $true)
            }
            $reasons.Add($(if ($script:stopReason -match '상한') { 'R-CAP' } else { 'R-BUDGET' }))
            Write-Host ('[outlook] 경고: ' + $warnings[$warnings.Count - 1])
            $null = Write-CsvByMonth $calP $CAL_HEADER $calBy $true
            Save-Coverage $script:cov
            break
        }
        if (-not $p) { $calBy.Remove($mo.key) }
        Add-Rows $calBy $rows 0 $mo.key
        $cnt = $(if ($calBy.ContainsKey($mo.key)) { $calBy[$mo.key].Count } else { 0 })
        # LM28: 0행 달은 카나리아가 성공했을 때만 완료(zero_ok) - 일정은 동기화 창이 걸리지 않아 지평선은 보지 않는다
        $v = Test-MonthDone -Rows $cnt -Canary $canary -Start $mo.start -End $mo.end -Cached $false
        Add-Verdict 'cal' $mo $v
        if ($v.done) { $script:cov.calendar[$mo.key] = @{ rows = $cnt; when = $now; start = $mo.start; end = $mo.end; st = $v.st } }
        else { $script:cov.calendar.Remove($mo.key) }
        $script:cov.partial.calendar.Remove($mo.key)
        $readCal++
        $null = Write-CsvByMonth $calP $CAL_HEADER $calBy $true
        Save-Coverage $script:cov
        Write-Host ("[outlook] 일정 {0}: {1}건 [{2}] (경과 {3}초)" -f $mo.key, $cnt, $v.st, [int]$sw.Elapsed.TotalSeconds)
    }
    if (-not (Test-Path $calP)) { $null = Write-CsvByMonth $calP $CAL_HEADER $calBy $true }

    # ---------- mail (기본 저장소 메일 폴더 - 받은 쪽 + 보낸 쪽): 최신 달부터, 예산까지 ----------
    foreach ($mo in $mailTodo) {
        if ($sw.Elapsed.TotalSeconds -gt $BudgetSec) { break }
        if (-not $SelfTest -and $cached -and $hz.oldest -and $mo.end -le ([datetime]$hz.oldest).Date) {
            # 캐시 지평선 앞의 달 - 로컬(OST)에 없으니 읽어도 0건이다. 0건으로 확정하지 않고 out_of_horizon 으로만 둔다(웹 경로가 채운다)
            $vo = Test-MonthDone -Rows 0 -Canary $canary -Oldest $hz.oldest -Start $mo.start -End $mo.end -Cached $false
            Add-Verdict 'mail_in' $mo $vo; Add-Verdict 'mail_out' $mo $vo
            $script:cov.mail.Remove($mo.key)
            continue
        }
        $wasComplete = Test-Covered 'mail' $mo
        $p = Get-Partial 'mail' $mo
        $state = @{ done = @{}; before = @{} }
        if ($p) { foreach ($x in $p.done.Keys) { $state.done[$x] = $true }; foreach ($x in $p.before.Keys) { $state.before[$x] = $p.before[$x] } }
        $script:monthMismatch = 0
        $rows = @(Read-MailMonth $mo $me $state)
        $counts.filter_mismatch = [int]$counts.filter_mismatch + $script:monthMismatch
        if ($script:monthMismatch -gt 0) { $warnings.Add(('메일 {0}: 날짜 필터 범위 밖 행 {1}건을 버림(필터 리터럴 어긋남 의심 - 이 달은 완료로 적지 않음)' -f $mo.key, $script:monthMismatch)) }
        if ($script:stopReason) {
            if ($wasComplete) {
                $refreshIncomplete.Add('메일 ' + $mo.key)
                $warnings.Add(('메일 {0}: {1} 도달 - 지난 수집분을 그대로 두고 다음 실행에서 다시 읽습니다' -f $mo.key, $script:stopReason))
            } else {
                if (-not $p) { $mailBy.Remove($mo.key) }
                Add-Rows $mailBy $rows 1 $mo.key
                $script:cov.partial.mail[$mo.key] = @{ done = $state.done; before = $state.before; start = $mo.start; end = $mo.end }
                $warnings.Add(('메일 {0}: {1} 도달 - 이 달은 다음 실행에서 이어서 읽습니다(그다음 오래된 달도)' -f $mo.key, $script:stopReason))
                $vs = Test-MonthDone -Rows 0 -Canary $canary -Start $mo.start -End $mo.end -Stopped $true
                Add-Verdict 'mail_in' $mo $vs; Add-Verdict 'mail_out' $mo $vs
            }
            $reasons.Add($(if ($script:stopReason -match '상한') { 'R-CAP' } else { 'R-BUDGET' }))
            Write-Host ('[outlook] 경고: ' + $warnings[$warnings.Count - 1])
            $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy $false
            Save-Coverage $script:cov
            break
        }
        if (-not $p) { $mailBy.Remove($mo.key) }
        Add-Rows $mailBy $rows 1 $mo.key
        $cnt = $(if ($mailBy.ContainsKey($mo.key)) { $mailBy[$mo.key].Count } else { 0 })
        $cIn = 0; $cOut = 0
        if ($mailBy.ContainsKey($mo.key)) { foreach ($ln in $mailBy[$mo.key]) { if ($ln.StartsWith('sent,')) { $cOut++ } else { $cIn++ } } }
        # LM28(W1-02·C-08): 축마다 판정 - 행이 있으면 ok, 0행은 카나리아 성공·지평선 ≤ 달 시작·(최근 달이면) OST 최신 ≥ now-ostStaleH
        # 일 때만 zero_ok. 두 축이 모두 검증된 달만 완료 표에 적는다(나머지는 다음 실행이 다시 읽고 원장은 웹 경로를 돌린다)
        $vIn = Test-MonthDone -Rows $cIn -Canary $canary -Oldest $hz.oldest -Newest $hz.newest -Start $mo.start -End $mo.end -StaleH $staleH -Cached $cached -Mismatch $script:monthMismatch
        $vOut = Test-MonthDone -Rows $cOut -Canary $canary -Oldest $hz.oldest -Newest $hz.newest -Start $mo.start -End $mo.end -StaleH $staleH -Cached $cached -Mismatch $script:monthMismatch
        Add-Verdict 'mail_in' $mo $vIn; Add-Verdict 'mail_out' $mo $vOut
        if ($vIn.done -and $vOut.done) {
            $script:cov.mail[$mo.key] = @{ rows = $cnt; rows_in = $cIn; rows_out = $cOut; st_in = $vIn.st; st_out = $vOut.st; when = $now; start = $mo.start; end = $mo.end }
        } else { $script:cov.mail.Remove($mo.key) }
        $script:cov.partial.mail.Remove($mo.key)
        $readMail++
        $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy $false
        Save-Coverage $script:cov
        Write-Host ("[outlook] 메일 {0}: {1}건 (받은 {2} [{3}] / 보낸 {4} [{5}]) (경과 {6}초)" -f $mo.key, $cnt, $cIn, $vIn.st, $cOut, $vOut.st, [int]$sw.Elapsed.TotalSeconds)
    }
    if (-not (Test-Path $mailP)) { $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy $false }
    Save-Coverage $script:cov

    # ---------- 요약: 기간 안에서 아직 못 읽은 달 ----------
    $uncMail = @($months | Where-Object { -not (Test-Covered 'mail' $_) } | ForEach-Object { $_.key })
    $uncCal  = @($months | Where-Object { -not (Test-Covered 'calendar' $_) } | ForEach-Object { $_.key })
    $unc = @($uncMail + $uncCal | Select-Object -Unique | Sort-Object)
    $partialMonths = @(@($script:cov.partial.mail.Keys) + @($script:cov.partial.calendar.Keys) | Select-Object -Unique | Sort-Object)
    $complete = ($unc.Count -eq 0)
    $nMail = 0; foreach ($k in $mailBy.Keys) { $nMail += $mailBy[$k].Count }
    $nCal = 0;  foreach ($k in $calBy.Keys)  { $nCal  += $calBy[$k].Count }
    # LMSTATUS(LM28): 달·축별 ranges + 사유. rc 0 정상(예산·지평선으로 덜 읽은 날은 ranges 가 말한다) · 1 기간에 메일·일정 0건
    foreach ($x in @(Build-Ranges)) { $ranges.Add($x) }
    if (@($ranges | Where-Object { $_.st -eq 'out_of_horizon' }).Count) {
        if ($cached -and $staleH -gt 0 -and ($null -eq $hz.newest -or $hz.newest -lt (Get-Date).AddHours(-$staleH))) { $reasons.Add('R-STALE') }
        if ($hz.oldest -and ([datetime]$hz.oldest).Date -gt $since) { $reasons.Add('R-HORIZON') }
    }
    if ($script:rcvUnknown -gt 0) { $warnings.Add(('받은 메일 {0}건 rcv=unknown(보호 멤버 미열람·내 주소 미확정 - 직접 수신처럼 계상)' -f $script:rcvUnknown)) }
    $stRc = $(if ($nMail + $nCal -eq 0) { 1 } else { 0 })
    Clear-SkipReason            # 성공했으니 지난 사유는 지운다
    try {                       # 어느 경로가 채웠는지 기록 - LM24 키 그대로 + LM28 키(ver·rc·reason·filter_fmt·canary·folders·지평선)
        $src = [ordered]@{ source = 'com'; when = $now; mail = $nMail; calendar = $nCal;
                           calendar_complete = ($uncCal.Count -eq 0); calendar_recurring_masters = 0; me = @($me);
                           mail_truncated = ($uncMail.Count -gt 0); warnings = @($warnings);
                           coverage_complete = $complete; uncovered_months = @($unc);
                           uncovered_mail = @($uncMail); uncovered_calendar = @($uncCal);
                           partial_months = @($partialMonths); refresh_incomplete = @($refreshIncomplete);
                           months_read = [ordered]@{ mail = $readMail; calendar = $readCal };
                           period = @($since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'));
                           budget_sec = $BudgetSec; elapsed_sec = [int]$sw.Elapsed.TotalSeconds;
                           selftest = [bool]$SelfTest; no_refresh = [bool]$NoRefresh;
                           ver = $covVer; rc = $stRc; reason = ((@($reasons) | Select-Object -Unique) -join ',');
                           filter_fmt = $fmt; canary = $canary; folders = [int]$counts.folders; filter_mismatch = [int]$counts.filter_mismatch;
                           horizon_oldest = $(if ($hz.oldest) { ([datetime]$hz.oldest).ToString('yyyy-MM-dd') } else { '' });
                           horizon_newest = $(if ($hz.newest) { ([datetime]$hz.newest).ToString('yyyy-MM-dd') } else { '' });
                           cached = [bool]$cached; prot = [string]$counts.prot; rcv_unknown = [int]$script:rcvUnknown;
                           me_known = [bool](@($me | Where-Object { $_ -match $script:OC_ADDR_RX }).Count) }
        ($src | ConvertTo-Json -Compress -Depth 4) | Set-Content -Path $srcP -Encoding UTF8
    } catch {}
    Write-Host ("[outlook] mail rows: {0} · calendar rows: {1} (이번에 읽은 달: 메일 {2} / 일정 {3}, 경과 {4}초)" -f $nMail, $nCal, $readMail, $readCal, [int]$sw.Elapsed.TotalSeconds)
    if ($refreshIncomplete.Count) { Write-Host ("[outlook] 재수집 미완 {0} - 지난 수집분 유지(새 메일·일정 변경은 다음 실행에서)" -f ($refreshIncomplete -join ', ')) }
    if ($complete) {
        Write-Host '[outlook] coverage: complete - 기간의 모든 달을 읽었습니다'
        Write-Host '[outlook] done.'
    } else {
        Write-Host ("[outlook] coverage: partial - 미수집 달 {0}개: {1}{2}" -f $unc.Count, ($unc -join ','), $(if ($partialMonths.Count) { ' (이어 읽는 중: ' + ($partialMonths -join ',') + ')' } else { '' }))
        Write-Host '[outlook] done. (부분 수집 - 다음 실행이 남은 달을 이어서 읽습니다. 화면의 수집 데이터 현황에 표시됩니다)'
    }
}
catch {
  $err = $_
  if ($err.Exception -is [System.OperationCanceledException] -and $script:fatal) {
    # 계획된 중단(Stop-Collect) - 사유와 안내는 이미 남겼다. 이번 실행은 아무 달도 완료로 적지 않았다
    $stRc = 3
    $reasons.Insert(0, $script:fatal)
    $ranges.Clear(); foreach ($x in @(Get-BlockedRanges 'blocked')) { $ranges.Add($x) }
  } else {
    $hrF = Get-OcHResult $err
    if (-not $counts.attach_hr) { $counts.attach_hr = $hrF }
    $stRc = 3
    $reasons.Insert(0, $(if ($hrF -eq '0x80010001' -or $hrF -eq '0x8001010A') { 'R-BUSY' } elseif ($hrF -eq '0x80040154') { 'R-NOCLASSIC' } else { 'R-COMFAIL' }))
    # 실패 전에 검증한 달은 그대로 싣고, 하나도 없으면 기간 전체를 unverified 로
    try { $ranges.Clear(); foreach ($x in @(Build-Ranges)) { $ranges.Add($x) } } catch {}
    if (-not $ranges.Count) { foreach ($x in @(Get-BlockedRanges 'unverified')) { $ranges.Add($x) } }
    Write-Host ("[outlook] 수집 실패: {0}" -f $err.Exception.Message)
    Set-SkipReason ("수집 실패: " + $err.Exception.Message)
    if ($newOutlook) {
        Write-Host '          원인: "새 Outlook"(COM 미지원) - 클래식 Outlook 으로 전환/실행 후 재시도하세요.'
    } elseif ($err.Exception.Message -match '80010001|8001010A|RPC_E_CALL_REJECTED|RPC_E_SERVERCALL') {
        Write-Host '          원인: Outlook 이 응답하지 않습니다 - 보통 Outlook 이 대화상자를 띄우고 있을 때입니다.'
        Write-Host '          ("Outlook 시작" 설정 마법사, 프로필 선택, 암호 입력, 복구 창 등)'
        Write-Host '          Outlook 화면을 열어 떠 있는 창을 닫거나 설정을 끝낸 뒤 다시 수집하세요.'
        Write-Host '          (설치 문제가 아닙니다 - 재설치하지 마세요)'
    } elseif ($err.Exception.Message -match '80040154|REGDB_E_CLASSNOTREG') {
        Write-Host '          원인: 클래식 Outlook 이 설치돼 있지 않음(COM 미등록) - Microsoft 365 설치 옵션에서'
        Write-Host '          클래식 Outlook 을 추가하거나, 관리자에게 클래식 Outlook 배포를 요청하세요.'
    } else {
        Write-Host '          클래식 Outlook(2016~365)을 실행해 프로필 로그인까지 마친 상태에서 재시도하세요.'
        Write-Host '          (버전은 무관 - 2016/2019/2021/365 모두 동일하게 동작합니다)'
    }
  }
}
finally {
    if ($wd) { Stop-OcLaunchWatchdog $wd; $wd = $null }
    # LM28(F-15): 이 수집이 띄운 Outlook 은 창(Explorer·Inspector)이 0개일 때만 닫는다 - 그사이 사용자가 창을 열었으면 그대로 둔다.
    # 사용자가 띄운 Outlook 은 놓기만 한다(ReleaseComObject).
    $quit = $false
    if ($ol -and $launched) {
        $nEx = -1; $nIn = -1
        try { $nEx = [int]$ol.Explorers.Count } catch {}
        try { $nIn = [int]$ol.Inspectors.Count } catch {}
        if ($nEx -eq 0 -and $nIn -eq 0) { try { $ol.Quit(); $quit = $true } catch {} }
    }
    if ($ns) { try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ns) } catch {} }
    if ($ol) { try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ol) } catch {} }
    if ($quit) {
        $ns = $null; $ol = $null; $script:folders = @(); $base = $null; $canItem = $null
        [GC]::Collect(); [GC]::WaitForPendingFinalizers()
        # 30초 안에 스스로 끝나기를 기다린 뒤, 남은 것 중 이 수집이 띄운 것(-Embedding · 띄운 뒤 시작)만 끝낸다(taskkill 없음)
        $tw = [System.Diagnostics.Stopwatch]::StartNew()
        while ($tw.Elapsed.TotalSeconds -lt 30) {
            $left = @(Get-Process outlook -ErrorAction SilentlyContinue | Where-Object { try { $_.StartTime -ge $launchT.AddSeconds(-2) } catch { $false } })
            if (-not $left.Count) { break }
            Start-Sleep -Seconds 1
        }
        $nk = Stop-OutlookWeStarted -Since $launchT
        if ($nk) { Write-Host ("[outlook] 이 수집이 띄운 Outlook {0}개가 30초 안에 닫히지 않아 끝냈습니다" -f $nk) }
    }
}
# 마지막 줄 = LMSTATUS(LM28 P3) - run.py 가 rc·사유·달별 검증 범위를 읽는다. 종료 코드 = rc
$counts.rcv_unknown = [int]$script:rcvUnknown; $counts.prot_err = [int]$script:protErr; $counts.cal_out_of_range = [int]$script:calOut
$counts.horizon_oldest = $(if ($hz.oldest) { ([datetime]$hz.oldest).ToString('yyyy-MM-dd') } else { '' })
$counts.horizon_newest = $(if ($hz.newest) { ([datetime]$hz.newest).ToString('yyyy-MM-dd') } else { '' })
$counts.cached = [bool]$cached; $counts.ver = $covVer; $counts.selftest = [bool]$SelfTest
$counts.months_read = [ordered]@{ mail = [int]$readMail; calendar = [int]$readCal }
Write-LmStatus -Src $srcName -Rc $stRc -Reasons @($reasons) -Counts $counts -Ranges @($ranges)
exit $stRc
