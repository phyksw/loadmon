# Get-OutlookData.ps1 - AgentFinder32 Outlook 앱(COM) 수집기: 내 기본 사서함의 메일·일정 머리 정보를 읽어 원자료 파일(§5.0)로 쓴다.
# 원자료는 잠깐만 있다 - run.py 가 이 수집기가 끝나자마자 core\mailmerge.g1_com(→ privacy.g1_file)으로 G1 정제한 뒤 지운다.
#   data\outlook\raw\mail_com.csv : box,time,sender_name,sender_addr,to,cc,rcv,time_precision,subject,conversation,sensitivity,categories,folder
#   data\outlook\raw\cal_com.csv  : start,end,all_day,busy_status,subject,categories,location,response,meeting_status,sensitivity,organizer,attendees[,body]
#   data\outlook\raw\com_manifest.json : 이번에 읽은 달 구간(replace·append)·새 완료 표(coverage)·내 주소(me)·건수 - G1 이 정제 파일
#     (data\outlook\src\mail_com.csv·cal_com.csv)에 합치고 완료 표(data\outlook\src\coverage_com.json)를 확정한다(G1 이 실패하면
#     그 달들은 다음 실행이 다시 읽는다).
#   data\outlook\src\mail_source_com.json : 수집 요약(건수·달·내 주소 me[] - 사내 도메인의 근거). 메일·일정 글은 없다.
# Usage:  .\Get-OutlookData.ps1 -From 2026-08-01 -To 2026-10-31 [-BudgetSec 360] [-Force] [-NoRefresh] [-OutDir data\outlook\src] [-RawDir data\outlook\raw]
#
# AgentFinder32 규칙(spec D1·D2·D3·D4·D7·D8·D10·§5.0):
#   · 시작 확인(LmName.ps1 Test-Af32Consent - core\consent.py --status 와 같은 판정): 이 설치 폴더의 자료가 다른 Windows 사용자의
#     것이거나 주인을 모르거나 지우는 중이면 아무것도 읽지 않고 종료 코드 3(R-CONSENT). 파이썬이 없어 확인할 수 없어도 3.
#   · -OutDir 는 설치 폴더의 data\outlook 아래, -RawDir 는 data\outlook\raw 만 받는다(그 밖이면 종료 코드 3 R-ARGS) - 원자료는
#     G1·[중지]·보관기한 정리가 지우는 곳에만 둔다.
#   · 요청 기간만 읽는다 - 끝은 어제까지(오늘은 넣지 않는다), 길이는 period.maxDays(92일 이하). -From 이 없으면 어제까지 92일.
#   · 이 PC 를 훑지 않는다 - 레지스트리·프로세스는 Outlook 을 붙이거나 띄울 수 있는지만 본다(창 제목·백신·보안 센터·정책 목록 없음).
#   · 사내/사외 판정 재료로 보낸 사람·받는 사람·참조·주최자·참석자 주소를 읽는다. Exchange 주소는 SMTP 로 바꾼다. 보호 멤버를 경고창
#     없이 읽을 수 없으면(Test-OcProtectedRead) 주소를 비워 둔다 - G1 이 증명할 수 없는 메일·회의를 external_unknown 으로 뺀다.
#   · 사내 도메인(config privacy.internalDomains ∪ 내 주소의 도메인 - 공용 개인 메일 도메인은 뺀다)이 비면 읽지 않고 종료 코드
#     4(R-NODOMAIN). 내 주소(me[])는 내 기본 사서함의 계정 것만 - 프로필의 다른 계정은 사내 도메인의 근거가 아니다.
#   · 받은 메일의 받는 사람을 하나도 읽지 못하면 참조에 '? <>'(증명 불가)를 적는다 - 보낸 사람 주소만으로 사내 메일이 되지 않는다.
#   · 수집기는 구조 규칙만 미리 뺀다(건수는 AF32STATUS counts.excluded): 개인·비공개·기밀(Sensitivity 1/2/3) · 제외 범주
#     (privacy.excludeCategories) · 제외 폴더(privacy.excludeMailFolders - 폴더째) · 일정의 한가함·부재중·다른 곳에서 작업(busy 0/3/4)
#     · 종일 · 취소 · 거절. 나머지(제한 고객·근태 낱말·사외·민감정보·식별번호·이름 가림·가명)는 G1 이 한다.
#   · 메일 본문은 읽지 않는다. 일정 본문은 config.calendar.collectBody 가 켜졌을 때만 앞 600자(Get-CalBody).
# 달 단위 이어서 수집(LM22~LM30 규칙 유지): 기간을 달로 쪼개 최신 달부터 읽고, 시간 예산(-BudgetSec)에 닿으면 거기서 멈춘다. 다 읽은
#   달은 완료 표(coverage_com.json)에 남아 다음 실행이 건너뛴다. 예산에 닿아 절반만 읽은 달은 이어서 읽는다(메일: 폴더별 '여기까지
#   읽음' 경계 분, 일정: 마지막 시작 시각). 최신 달은 매번 다시 읽고, 그다음 못 읽은 달(최신→과거), 마지막에 최신 2개월 재수집.
#   run.py 의 연속 회차는 -NoRefresh 로 못 읽은 달만 잇는다. -Force 면 전부 다시. 완료 표의 판(수집기판|collect.cursorEpoch)·작성자·
#   제목 저장 설정이 바뀌었거나 정제 파일이 없으면 표를 버리고 처음부터 읽는다.
#   날짜 필터 카나리아('g' → yyyy-MM-dd HH:mm → ISO)·Restrict 결과 재검사·캐시 지평선·OST 신선도·차가운 COM(이 수집이 띄운 캐시
#   Outlook) 판정은 그대로다 - 0행 달은 검증된 경우에만 zero_ok 로 완료.
# 붙기: GetActiveObject 3회 → 실행 중인데 못 붙으면 R-ELEV(관리자 권한)·R-BUSY·R-DIALOG(New-Object 하지 않는다). 미실행일 때만
#   New-Object - 무진전 attachWaitSec 이면 이 수집이 띄운 Outlook(-Embedding)만 끝내고 R-WIZARD. 우리가 띄운 Outlook 만 닫는다.
# 마지막 줄 AF32STATUS(rc 0 정상 · 1 대상 없음 · 3 불가·불완전·시작 거부(내 자료 아님·지우는 중) · 4 설정 거부 - R-NODOMAIN·R-NORESTRICTED) - 종료 코드 = rc.
# -SelfTest N: Outlook 없이 달마다 N건의 가짜 메일·일정(사내 주소 corp.local)으로 예산·이어서 수집·원자료 형식을 검증한다(시험 전용).
param(
    [string]$From = '',
    [string]$To = '',
    [int]$BudgetSec = 360,
    [switch]$Force,
    [switch]$NoRefresh,
    [int]$SelfTest = 0,
    [int]$SelfTestDelayMs = 0,
    [string]$OutDir = '',     # 정제 파일 폴더(기본 data\outlook\src) - 완료 표·mail_source_com.json
    [string]$RawDir = '',     # 원자료 폴더(기본 data\outlook\raw)
    [string]$Tag = 'com'      # 출처 표식 - mail_<tag>.csv·cal_<tag>.csv·<tag>_manifest.json·coverage_<tag>.json·mail_source_<tag>.json
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$sw = [System.Diagnostics.Stopwatch]::StartNew()       # 시간 예산은 COM 연결까지 포함해 잰다(run.py 의 시계와 같다)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
. (Join-Path $here 'LmName.ps1')          # Test-Af32Consent
. (Join-Path $here 'OutlookCommon.ps1')   # 판 판정·카나리아·폴더 재귀·주소·AF32STATUS
if ($Tag -notmatch '^[A-Za-z0-9_-]{1,24}$') {
    Write-Host ("[outlook] -Tag 값이 올바르지 않습니다: {0}" -f $Tag)
    Write-LmStatus -Src 'com' -Rc 3 -Reasons @('R-ARGS')
    exit 3
}
$srcName = $Tag
# (PowerShell 변수는 대소문자를 가리지 않는다 - 매개변수 $OutDir·$RawDir 와 겹치지 않는 이름을 쓴다)
$srcDirP = Resolve-OcDir $root $OutDir 'data\outlook\src' 'data\outlook'
$rawDirP = Resolve-OcDir $root $RawDir 'data\outlook\raw' 'data\outlook\raw' -Exact
if (-not $srcDirP -or -not $rawDirP) {
    Write-Host '[outlook] -OutDir 는 설치 폴더의 data\outlook 아래, -RawDir 는 data\outlook\raw 만 받습니다 - 아무것도 읽지 않았습니다 (R-ARGS)'
    Write-LmStatus -Src $srcName -Rc 3 -Reasons @('R-ARGS')
    exit 3
}
if (-not (Test-Af32Consent $root)) {
    if ($script:Af32ConsentWhy -eq 'nopython') { Write-Host '[outlook] 내 자료인지 확인할 파이썬(python\python.exe)이 없어 메일·일정을 읽지 않았습니다 - tools\Get-EmbeddedPython.ps1 로 받을 수 있습니다.' }
    elseif ($script:Af32ConsentWhy -eq 'other') { Write-Host '[outlook] 이 설치 폴더의 자료가 다른 Windows 사용자의 것이거나 누구의 것인지 확인할 수 없어 메일·일정을 읽지 않았습니다.' }
    elseif ($script:Af32ConsentWhy -eq 'wiping') { Write-Host '[outlook] 자료를 지우는 중이라 메일·일정을 읽지 않았습니다 - 다 지운 뒤 다시 시작할 수 있습니다.' }
    else { Write-Host '[outlook] 내 자료인지 확인하지 못해(core\consent.py 실행 실패) 메일·일정을 읽지 않았습니다.' }
    Write-LmStatus -Src $srcName -Rc 3 -Reasons @('R-CONSENT')
    exit 3
}
$cfg = $null
foreach ($cn in @('config.json', 'config.default.json')) {
    $cp = Join-Path $root ('config\' + $cn)
    if (-not (Test-Path -LiteralPath $cp)) { continue }
    try { $cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $cp | ConvertFrom-Json; break } catch { $cfg = $null }
}
$script:restrictedWhy = ''
function Test-RestrictedList {
    # 제한 고객 목록(D9 - privacy.restrictedCustomersFile)이 있고 {"confirmed":"YYYY-MM-DD","customers":[…]} 꼴인가(Test-OcRestrictedList).
    # 배포 견본을 그대로 복사한 것('_template'·confirmed 자리표)·실제 날짜가 아니거나 오늘보다 뒤인 confirmed 도 받지 않는다.
    # 이름은 여기서 쓰지 않는다(G1 이 메모리에서 맞댄다) - 받지 않으면 읽지 않고 종료 코드 4(R-NORESTRICTED).
    $rel = [string](Get-OcCfg $cfg 'privacy' 'restrictedCustomersFile' 'config\restricted_customers.json')
    if (-not $rel) { $rel = 'config\restricted_customers.json' }
    $rp = $(if ([System.IO.Path]::IsPathRooted($rel)) { $rel } else { Join-Path $root $rel })
    $t = Test-OcRestrictedList $rp
    $script:restrictedWhy = [string]$t.why
    return [bool]$t.ok
}
if (-not (Test-RestrictedList)) {
    if ($script:restrictedWhy -eq 'template') { Write-Host '[outlook] 제한 고객 목록이 배포 견본 그대로입니다 — 운영 담당이 배포한 config\restricted_customers.json 을 넣으세요 (R-NORESTRICTED)' }
    elseif ($script:restrictedWhy -eq 'date' -or $script:restrictedWhy -eq 'future') { Write-Host '[outlook] 제한 고객 목록의 확인 날짜(confirmed)가 올바르지 않습니다 — 운영 담당이 배포한 config\restricted_customers.json 을 넣으세요 (R-NORESTRICTED)' }
    else { Write-Host '[outlook] 제한 고객 목록 파일이 없습니다 — 운영 담당이 배포한 config\restricted_customers.json 을 넣으세요. 제한 고객이 없으면 빈 목록 파일을 받습니다 (R-NORESTRICTED)' }
    Write-LmStatus -Src $srcName -Rc 4 -Reasons @('R-NORESTRICTED')
    exit 4
}
$storeSubject = $true
if ($cfg -and $cfg.PSObject.Properties['storeMailSubject'] -and -not $cfg.storeMailSubject) { $storeSubject = $false }
if ($BudgetSec -le 0) { $BudgetSec = 360 }
if ($SelfTest -le 0 -and $env:AF32_OUTLOOK_SELFTEST) { try { $SelfTest = [int]$env:AF32_OUTLOOK_SELFTEST } catch {} }
if ($SelfTestDelayMs -le 0 -and $env:AF32_OUTLOOK_SELFTEST_DELAY_MS) { try { $SelfTestDelayMs = [int]$env:AF32_OUTLOOK_SELFTEST_DELAY_MS } catch {} }
$writer = $(if ($SelfTest) { 'selftest' } else { 'com' })
$COLLECTOR_VER = 'AF32-COM-1'          # 완료 표 판정 규칙의 판 - 규칙을 바꾸면 올린다(옛 표의 '완료'를 버린다)
$covVer = '{0}|{1}' -f $COLLECTOR_VER, [int](Get-OcCfg $cfg 'collect' 'cursorEpoch' 1)
$attachWait = [math]::Max(20, [math]::Min(600, [int](Get-OcCfg $cfg 'outlook' 'attachWaitSec' 120)))
$staleH = [double](Get-OcCfg $cfg 'outlook' 'ostStaleH' 72)
$subOn = [bool](Get-OcCfg $cfg 'outlook' 'subfolders' $true)
$maxDays = 92
try { $md = [int](Get-OcCfg $cfg 'period' 'maxDays' 92); if ($md -ge 1 -and $md -lt 92) { $maxDays = $md } } catch {}
$PRIVATE_WORDS = @('개인', 'Personal', 'Private', '사적')
# D3·D22 - 설정의 제외 범주·폴더는 기본 목록에 더하기만 한다(설정으로 기본 항목을 뺄 수 없다 · core\afcfg 의 ADD_ONLY_LISTS 와 같다)
$exCats = @(@($PRIVATE_WORDS) + @(Get-OcCfgList $cfg 'privacy' 'excludeCategories' @()))
$exFolders = @(@($PRIVATE_WORDS) + @(Get-OcCfgList $cfg 'privacy' 'excludeMailFolders' @()))
$cfgDomains = @(Get-OcCfgList $cfg 'privacy' 'internalDomains' @() | ForEach-Object { $_.ToLowerInvariant().TrimStart('@').TrimEnd('.') } | Where-Object { $_ -match '^[a-z0-9\-]+(\.[a-z0-9\-]+)+$' })
# 일정 본문(D18): config.calendar.collectBody 가 참일 때만(기본 false). Body 는 보호 멤버라 주소 읽기 판정($protOk)을 따른다.
$cbv = Get-OcCfg $cfg 'calendar' 'collectBody' $false
$calBodyOn = [bool]($cbv -eq $true -or ([string]$cbv) -match '^\s*(true|1|yes|y|on)\s*$')
$script:calBody = [ordered]@{ ok = 0; empty = 0; private = 0; prot = 0; err = 0 }
$script:calBodyOff = $false    # 본문 읽기에서 예외가 한 번 나면 이 실행의 나머지 일정은 읽지 않는다
$skipDir = Join-Path $root 'data\outlook'    # outlook_skip.json(화면이 읽는 '건너뛴 까닭' 한 줄)
# $srcDirP·$rawDirP 는 시작 확인 앞에서 정했다(Resolve-OcDir - data\outlook 아래만)
foreach ($d in @($srcDirP, $rawDirP)) { if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null } }
$rawMailP = Join-Path $rawDirP ('mail_' + $Tag + '.csv')
$rawCalP  = Join-Path $rawDirP ('cal_' + $Tag + '.csv')
$manP     = Join-Path $rawDirP ($Tag + '_manifest.json')
$covP     = Join-Path $srcDirP ('coverage_' + $Tag + '.json')
$srcP     = Join-Path $srcDirP ('mail_source_' + $Tag + '.json')
$cleanMailP = Join-Path $srcDirP ('mail_' + $Tag + '.csv')
$cleanCalP  = Join-Path $srcDirP ('cal_' + $Tag + '.csv')
# 지난 실행이 남긴 원자료(G1 전에 끊긴 것)는 이번 실행이 다시 읽으므로 먼저 지운다 - 원자료는 한 벌만, 잠깐만 둔다
foreach ($p in @($rawMailP, $rawCalP, $manP)) { try { if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force } } catch {} }
$MAIL_HEADER = 'box,time,sender_name,sender_addr,to,cc,rcv,time_precision,subject,conversation,sensitivity,categories,folder'
$CAL_HEADER  = 'start,end,all_day,busy_status,subject,categories,location,response,meeting_status,sensitivity,organizer,attendees' + $(if ($calBodyOn) { ',body' } else { '' })
$REFRESH_MONTHS = 2          # 최신 N개월은 이미 읽었어도 매번 다시 읽는다(-NoRefresh 면 안 한다)
$TS = 'yyyy-MM-dd HH:mm:ss'  # 표에 적는 시각 형식
$DAYF = 'yyyy-MM-dd'
$RCPT_MAX = 100              # 한 메일·회의에서 읽는 사람 수 상한(넘으면 증명 불가로 남긴다)

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}
function Test-MeInList([string]$list, [string[]]$ids) {
    # 'Name <addr>; …' 목록에 내 이름·주소가 한 항목으로 있는가
    if (-not $list) { return $false }
    foreach ($tok in ($list -split ';')) {
        $t = $tok.Trim().ToLower()
        if (-not $t) { continue }
        foreach ($mid in $ids) {
            if (-not $mid) { continue }
            if ($t -eq $mid -or $t.EndsWith('<' + $mid + '>') -or $t.StartsWith($mid + ' <')) { return $true }
        }
    }
    return $false
}
function Get-Domain([string]$a) {
    $i = $a.LastIndexOf('@')
    if ($i -lt 0) { return '' }
    return $a.Substring($i + 1).Trim().ToLowerInvariant()
}
function Test-InternalAddr([string]$a, [string[]]$Doms) {
    $d = Get-Domain $a
    if (-not $d) { return $false }
    foreach ($x in $Doms) { if ($d -eq $x -or $d.EndsWith('.' + $x)) { return $true } }
    return $false
}

# ── 기간(D2): 끝은 어제까지, 길이는 maxDays ───────────────────────────────────────────────
$today = (Get-Date).Date
$until = $today                                           # [since, until) - until 은 포함하지 않는다(오늘 제외)
if ($To) { try { $u = ([datetime]::ParseExact($To, $DAYF, $null)).AddDays(1); if ($u -lt $until) { $until = $u } } catch {} }
$since = $until.AddDays(-$maxDays)
if ($From) { try { $s0 = [datetime]::ParseExact($From, $DAYF, $null); if ($s0 -gt $since) { $since = $s0 } } catch {} }
if ($until -le $since) { $since = $until.AddDays(-1) }
$fmt = 'g'  # Restrict 날짜 리터럴 - 필터 카나리아가 이 PC 에서 통하는 형식으로 바꾼다
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

# ── 지난 실행의 달별 완료 표(v3) - G1 이 확정한 것(data\outlook\src\coverage_com.json)만 믿는다 ─────────────
#   mail/calendar: { 'yyyy-MM': { rows, when, start, end, (메일) rows_in·rows_out·st_in·st_out | (일정) st } }
#   partial: { mail: { 'yyyy-MM': { done: [폴더 표식], before: { 폴더 표식: 경계 시각 }, start, end, rows_in, rows_out } },
#              calendar: { 'yyyy-MM': { from, start, end, rows } } }
function New-Coverage { return @{ mail = @{}; calendar = @{}; partial = @{ mail = @{}; calendar = @{} } } }
function Load-Coverage {
    $c = New-Coverage
    if (-not (Test-Path -LiteralPath $covP)) { return $c }
    try {
        $j = Get-Content -Raw -Encoding UTF8 -LiteralPath $covP | ConvertFrom-Json
        $u = Test-CoverageUsable $j $covVer $writer $storeSubject
        if (-not $u.ok) {
            Write-Host ("[outlook] 완료 표가 이번 실행과 맞지 않아({0}) 처음부터 읽습니다" -f $u.why)
            return $c
        }
        $kinds = [System.Collections.Generic.List[string]]::new()
        # 정제 파일이 없으면(지웠거나 보관기한이 지나 지워짐) 그 종류의 표는 믿지 않는다
        if (Test-Path -LiteralPath $cleanMailP) { $kinds.Add('mail') }
        if (Test-Path -LiteralPath $cleanCalP) {
            $cbOld = $false; try { $cbOld = [bool]$j.cal_body } catch {}
            if ($cbOld -eq $calBodyOn) { $kinds.Add('calendar') }
            else { Write-Host '[outlook] 일정 본문 설정이 지난 수집과 달라 일정은 처음부터 다시 읽습니다(메일 달은 그대로)' }
        }
        foreach ($kind in $kinds) {
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
            foreach ($kind in $kinds) {
                $sec = $ps.Value.PSObject.Properties[$kind]
                if (-not $sec -or -not $sec.Value) { continue }
                foreach ($p in $sec.Value.PSObject.Properties) {
                    if ($p.Name -notmatch '^\d{4}-\d{2}$') { continue }
                    try {
                        $e = @{ start = [datetime]::ParseExact([string]$p.Value.start, $TS, $null);
                                end = [datetime]::ParseExact([string]$p.Value.end, $TS, $null) }
                        if ($kind -eq 'mail') {
                            $e.done = @{}; $e.before = @{}
                            foreach ($fk in @($p.Value.done)) { if ($fk) { $e.done[[string]$fk] = $true } }
                            if ($p.Value.before) { foreach ($bp in $p.Value.before.PSObject.Properties) { $e.before[$bp.Name] = [string]$bp.Value } }
                            $e.rows_in = 0; $e.rows_out = 0
                            try { $e.rows_in = [int]$p.Value.rows_in; $e.rows_out = [int]$p.Value.rows_out } catch {}
                        } else {
                            $e.from = [string]$p.Value.from
                            $e.rows = 0; try { $e.rows = [int]$p.Value.rows } catch {}
                        }
                        $c.partial[$kind][$p.Name] = $e
                    } catch {}
                }
            }
        }
    } catch { Write-Host ("[outlook] 완료 표를 읽지 못해 처음부터 읽습니다: {0}" -f $_.Exception.Message); return (New-Coverage) }
    return $c
}
function ConvertTo-CoverageJson($c) {
    # when(읽은 날)은 날짜만 적는다 - 읽은 시각은 어디에도 쓰이지 않는다. 옛 표에 남은 시각 꼴도 다시 쓸 때 날짜로 줄인다.
    $o = [ordered]@{ version = 3; ver = $covVer; writer = $writer; store_subject = $storeSubject; cal_body = [bool]$calBodyOn;
                     when = (Get-Date).ToString('yyyy-MM-dd'); filter_fmt = $fmt; mail = [ordered]@{}; calendar = [ordered]@{};
                     partial = [ordered]@{ mail = [ordered]@{}; calendar = [ordered]@{} } }
    foreach ($kind in @('mail', 'calendar')) {
        foreach ($k in ($c[$kind].Keys | Sort-Object -Descending)) {
            $e = $c[$kind][$k]
            $x = [ordered]@{ rows = [int]$e.rows; when = (([string]$e.when) -replace '^(\d{4}-\d{2}-\d{2}).*$', '$1');
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
                $x.before = $bo; $x.rows_in = [int]$e.rows_in; $x.rows_out = [int]$e.rows_out
            } else { $x.from = [string]$e.from; $x.rows = [int]$e.rows }
            $o.partial[$kind][$k] = $x
        }
    }
    return $o
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

# ── 원자료 쓰기: 이번 실행이 읽은 행만(달마다 다시 쓴다 - 강제 종료돼도 그때까지 읽은 달과 그 구간 표가 함께 남는다) ──────────
$script:rawMail = [System.Collections.Generic.List[string]]::new()
$script:rawCal = [System.Collections.Generic.List[string]]::new()
$script:span = @{ mail = @{ replace = [System.Collections.Generic.List[object]]::new(); append = [System.Collections.Generic.List[object]]::new() };
                  cal  = @{ replace = [System.Collections.Generic.List[object]]::new(); append = [System.Collections.Generic.List[object]]::new() } }
$script:excl = [ordered]@{ private = 0; admin = 0 }        # 구조 규칙으로 미리 뺀 건수(G1 의 excluded 와 같은 키)
$script:exclWhy = [ordered]@{ sensitivity = 0; category = 0; folder = 0; busy = 0; all_day = 0; cancelled = 0; declined = 0 }
function Add-Span([string]$kind, [string]$mode, $mo) {
    $script:span[$kind][$mode].Add(@($mo.start.ToString($DAYF), $mo.end.ToString($DAYF)))
}
function Write-Lines([string]$path, [string]$header, $rows) {
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add($header)
    foreach ($ln in $rows) { $lines.Add($ln) }
    $tmp = $path + '.tmp'
    [System.IO.File]::WriteAllLines($tmp, $lines, (New-Object System.Text.UTF8Encoding($true)))
    $ok = $false
    for ($i = 0; $i -lt 5 -and -not $ok; $i++) {
        try { Move-Item -LiteralPath $tmp -Destination $path -Force; $ok = $true } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $ok) {
        try { [System.IO.File]::WriteAllLines($path, $lines, (New-Object System.Text.UTF8Encoding($true))) } catch { Write-Host ("[outlook] 경고: {0} 저장 실패 - {1}" -f (Split-Path -Leaf $path), $_.Exception.Message) }
        try { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue } catch {}
    }
}
function Save-Raw {
    # 원자료 두 파일 + 구간 표(manifest). 행이 없어도 쓴다 - '이 달은 0건으로 다시 읽었다'(replace)도 G1 이 반영해야 한다
    Write-Lines $rawMailP $MAIL_HEADER $script:rawMail
    Write-Lines $rawCalP $CAL_HEADER $script:rawCal
    try {
        $o = [ordered]@{ product = 'AgentFinder32'; src = $srcName; v = 1; when = (Get-Date).ToString('yyyy-MM-dd');
                         period = @($since.ToString($DAYF), $until.AddDays(-1).ToString($DAYF)); me = @($script:me);
                         mail = [ordered]@{ replace = @($script:span.mail.replace); append = @($script:span.mail.append) };
                         cal = [ordered]@{ replace = @($script:span.cal.replace); append = @($script:span.cal.append) };
                         excluded = $script:excl; coverage = (ConvertTo-CoverageJson $script:cov) }
        $txt = $o | ConvertTo-Json -Depth 8 -Compress
        [System.IO.File]::WriteAllText($manP, $txt, (New-Object System.Text.UTF8Encoding($false)))
    } catch { Write-Host ("[outlook] 경고: 구간 표 저장 실패 - {0}" -f $_.Exception.Message) }
}

# ── 붙기 전 판정(띄우면 모달이 확실한가 - 진단과 사유 표기 전용) ─────────────────────────────────
$counts = [ordered]@{ elevated = $false; profiles = 0; profiles_usable = 0;
                      ol = [ordered]@{ found = $false; c2r = $false; msi = $false; ver = '' };
                      new_ol = [ordered]@{ useNew = $false; olk = $false; appx = $false; autoMig = $null };
                      running = $false; launched = $false; attach_hr = ''; filter_fmt = ''; canary = ''; filter_mismatch = 0;
                      folders = 0; folders_excluded = 0; folders_private = 0; folders_capped = $false; prot = ''; rcv_unknown = 0;
                      addr_unknown = 0; rcpt_capped = 0 }
$reasons = [System.Collections.Generic.List[string]]::new()
$ranges = [System.Collections.Generic.List[object]]::new()
$stRc = 0
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
    $counts.profiles = [int]$prof.total; $counts.profiles_usable = [int]$prof.usable
    $counts.ol = [ordered]@{ found = [bool]$classic.found; c2r = [bool]$classic.c2r; msi = [bool]$classic.msi; ver = [string]$classic.ver }
    $counts.new_ol = [ordered]@{ useNew = [bool]$trace.useNew; olk = [bool]$trace.olk; appx = [bool]$trace.appx; autoMig = $trace.autoMig }
    if ($newOutlook) {
        Write-Host '[outlook] 주의: "새 Outlook" 사용이 감지되었습니다 - 새 Outlook 은 데이터 접근(COM)을 제공하지 않습니다.'
        Write-Host '          클래식 Outlook(2016~365)을 실행해 두고 다시 수집하세요. (계속 시도합니다)'
    }
}

function Set-SkipReason([string]$reason) {
    if ($SelfTest) { return }
    try {
        $f = Join-Path $skipDir 'outlook_skip.json'
        if (-not (Test-Path -LiteralPath $skipDir)) { New-Item -ItemType Directory -Force -Path $skipDir | Out-Null }
        $o = [ordered]@{ reason = $reason; when = (Get-Date).ToString('yyyy-MM-dd') }
        ($o | ConvertTo-Json -Compress) | Set-Content -LiteralPath $f -Encoding UTF8
    } catch {}
}
function Clear-SkipReason {
    if ($SelfTest) { return }
    try { Remove-Item -LiteralPath (Join-Path $skipDir 'outlook_skip.json') -ErrorAction SilentlyContinue } catch {}
}
function Get-BlockedRanges([string]$st) {
    $o = [System.Collections.Generic.List[object]]::new()
    foreach ($ax in @('mail_in', 'mail_out', 'cal')) {
        $o.Add([ordered]@{ axis = $ax; from = $since.ToString($DAYF); to = $until.AddDays(-1).ToString($DAYF); st = $st })
    }
    return $o
}

# 프로필 사전 점검: 띄우면 모달이 확실할 때(Outlook 미실행 + 프로필 0 · 주소록만 · 관리자 전환 정책)는 COM 을 건드리지 않는다
if (-not $SelfTest -and $verdict) {
    $msg = ''
    switch ($verdict) {
        'R-NEWOL' {
            Write-Host '[outlook] 건너뜀: 새 Outlook 을 쓰는 PC 로 보입니다(새 Outlook 흔적 있음 · 클래식 Outlook 메일 프로필 0개).'
            Write-Host '          새 Outlook 은 COM 을 제공하지 않습니다 - Outlook 웹·Copilot 경로가 읽습니다(설정 collect.channels).'
            $msg = '새 Outlook 사용(의심) — 클래식 Outlook 메일 프로필이 없어 Outlook 앱 경로를 건너뜁니다'
        }
        'R-NEWOLPOL' {
            Write-Host '[outlook] 건너뜀: 관리자 새 Outlook 전환 정책이 켜져 있고 Outlook 이 꺼져 있습니다 - 띄우면 전환 안내 창이 떠 멈출 수 있습니다.'
            Write-Host '          클래식 Outlook 을 직접 켜 두면 거기에 붙어 읽습니다.'
            $msg = '새 Outlook 전환 정책이 켜져 있어 꺼진 클래식 Outlook 을 띄우지 않았습니다 — 클래식 Outlook 을 켜 둔 채로 다시 수집하세요'
        }
        'R-NOCLASSIC' {
            Write-Host '[outlook] 건너뜀: 클래식 Outlook 설치도 메일 프로필도 찾지 못했습니다(의심).'
            $msg = '클래식 Outlook 을 찾지 못했습니다(의심) — Outlook 웹·Copilot 경로가 읽습니다'
        }
        default {
            Write-Host '[outlook] 건너뜀: 쓸 수 있는 메일 프로필이 없는 것으로 보입니다(의심). 지금 띄우면 "Outlook 시작" 마법사가 떠 멈춥니다.'
            Write-Host '          Outlook 을 직접 실행해 계정을 설정한 뒤, Outlook 을 켜 둔 채로 다시 수집하세요.'
            $msg = 'Outlook 메일 프로필이 구성되지 않은 것으로 보입니다 — Outlook 을 직접 실행해 계정 설정을 마친 뒤 다시 수집하세요'
        }
    }
    Set-SkipReason $msg
    Write-LmStatus -Src $srcName -Rc 3 -Reasons @($verdict) -Counts $counts -Ranges (Get-BlockedRanges 'blocked')
    exit 3
}

# ── 행 만들기 ─────────────────────────────────────────────────────────────────────────────
$script:stopReason = ''
$script:calLast = ''          # 일정: 이번에 읽은 마지막 시작 시각(TS) - 이어 읽기 표식
$script:calOut = 0            # 일정: 그 달에 시작하지 않아 버린 회차 수(시작한 달이 그 회의를 읽는다)
$script:monthMismatch = 0     # 메일: 그 달을 읽는 동안 Restrict 가 준 범위 밖 행 수
$script:protErr = 0           # 보호 멤버 접근 예외 수
$script:rcvUnknown = 0        # rcv=unknown 으로 남긴 받은 메일 수
$protOk = $true               # 보호 멤버(주소)를 읽어도 되는가(Test-OcProtectedRead)
$script:folders = @()
$script:me = @()
function Test-Struct-Mail($m) {
    # 메일 구조 규칙(D3) → 빼면 $true(건수를 센다). 민감도·범주는 보호 멤버가 아니다.
    $sens = 0; try { $sens = [int]$m.Sensitivity } catch {}
    if ($sens -ge 1 -and $sens -le 3) { $script:excl.private++; $script:exclWhy.sensitivity++; return $true }
    $cat = ''; try { $cat = [string]$m.Categories } catch {}
    if ($exCats.Count -and (Test-OcCategoryHit $cat $exCats)) { $script:excl.private++; $script:exclWhy.category++; return $true }
    return $false
}
function Test-Struct-Cal($it) {
    # 일정 구조 규칙(D3·D4) → 빼면 $true. 개인·비공개·기밀 · 제외 범주 · 종일 · 한가함·부재중·다른 곳에서 작업 · 취소 · 거절
    $sens = 0; try { $sens = [int]$it.Sensitivity } catch {}
    if ($sens -ge 1 -and $sens -le 3) { $script:excl.private++; $script:exclWhy.sensitivity++; return $true }
    $cat = ''; try { $cat = [string]$it.Categories } catch {}
    if ($exCats.Count -and (Test-OcCategoryHit $cat $exCats)) { $script:excl.private++; $script:exclWhy.category++; return $true }
    $ad = $false; try { $ad = [bool]$it.AllDayEvent } catch {}
    if ($ad) { $script:excl.admin++; $script:exclWhy.all_day++; return $true }
    $bs = 2; try { $bs = [int]$it.BusyStatus } catch {}
    if ($bs -eq 0 -or $bs -eq 3 -or $bs -eq 4) { $script:excl.admin++; $script:exclWhy.busy++; return $true }
    $ms = 0; try { $ms = [int]$it.MeetingStatus } catch {}
    if ($ms -eq 5 -or $ms -eq 7) { $script:excl.admin++; $script:exclWhy.cancelled++; return $true }
    $rs = 0; try { $rs = [int]$it.ResponseStatus } catch {}
    if ($rs -eq 4) { $script:excl.admin++; $script:exclWhy.declined++; return $true }
    return $false
}
function Get-SelfTestPeople([int]$i) {
    # 자가검증의 사람들 - 대개 사내(corp.local), 다섯에 하나는 사외(ext.example) 참조
    $to = 'selftest <selftest@corp.local>'
    $cc = $(if ($i % 5 -eq 4) { 'outsider <x@ext.example>' } else { ('colleague{0} <c{0}@corp.local>' -f ($i % 3)) })
    return @{ sender_name = ('colleague{0}' -f ($i % 3)); sender_addr = ('c{0}@corp.local' -f ($i % 3)); to = $to; cc = $cc }
}
function Read-CalendarMonth($ns, $mo, [string]$resumeFrom) {
    # 반환: 이 달에 시작하는 일정의 원자료 행 목록(resumeFrom 이 있으면 그 시작 시각부터). 예산(절반)에 닿으면 $script:stopReason.
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
            $att = $(if ($i % 4 -eq 3) { 'outsider <x@ext.example>; selftest <selftest@corp.local>' } else { 'selftest <selftest@corp.local>; colleague1 <c1@corp.local>' })
            $f = @($st.ToString('yyyy-MM-dd HH:mm'), $st.AddHours(1).ToString('yyyy-MM-dd HH:mm'), 'False', '2', ('selftest meeting ' + $i), '', '', '3', '1', '0',
                   'colleague1 <c1@corp.local>', $att)
            if ($calBodyOn) { $f += ('selftest agenda ' + $i) }
            $rows.Add((($f | ForEach-Object { Csv-Escape ([string]$_) }) -join ','))
            $script:calLast = $st.ToString($TS)
        }
        return $rows
    }
    $cal = $ns.GetDefaultFolder(9)  # olFolderCalendar
    $items = $cal.Items
    $items.IncludeRecurrences = $true
    $items.Sort('[Start]')           # IncludeRecurrences 는 [Start] 오름차순을 요구한다
    $flt = ("[Start] < '{0}' AND [End] >= '{1}' AND [Start] >= '{2}'" -f (Format-OlDate $mo.end $fmt), (Format-OlDate $mo.start $fmt), (Format-OlDate $lo $fmt))
    if ($lo -le $mo.start) { $flt = ("[Start] < '{0}' AND [End] >= '{1}'" -f (Format-OlDate $mo.end $fmt), (Format-OlDate $mo.start $fmt)) }
    $sel = $items.Restrict($flt)
    $count = 0
    foreach ($it in $sel) {
        $count++
        if ($count -gt 8000) { $script:stopReason = '일정 상한 8000건(깨진 반복 일정?)'; break }
        if (($count % 100) -eq 0 -and $sw.Elapsed.TotalSeconds -gt $halfBudget) {
            $script:stopReason = ('일정 시간 예산({0}초) 도달' -f [math]::Round($halfBudget, 1)); break
        }
        try {
            # 그 달에 시작한 회차만(앞 달에 시작한 회의는 앞 달이 읽는다) - 결과 재검사로 창 밖 회차도 버린다(셈만)
            if ($it.Start -ge $mo.end -or $it.Start -lt $mo.start) { $script:calOut++; continue }
            if (Test-Struct-Cal $it) { try { $script:calLast = $it.Start.ToString($TS) } catch {}; continue }
            $resp = ''; $mst = ''; $sens = '0'
            try { $resp = [string][int]$it.ResponseStatus } catch {}
            try { $mst = [string][int]$it.MeetingStatus } catch {}
            try { $sens = [string][int]$it.Sensitivity } catch {}
            # 참여자: 회의(MeetingStatus 1·3)는 주최자·참석자 주소를 읽는다. 내 약속(0 - 다른 사람 없음)은 둘 다 빈칸(G1 이 사내로 본다).
            # 보호 멤버를 읽을 수 없으면 회의는 '? <>'(증명 불가 - G1 이 뺀다).
            $org = ''; $att = ''
            if ($mst -ne '0') {
                if ($protOk) {
                    try {
                        $oa = $null; try { $oa = $it.GetOrganizer() } catch {}
                        if ($oa) { $on = ''; try { $on = [string]$oa.Name } catch {}; $org = Format-OcPerson $on (Get-OcSmtp $oa) }
                        $pp = Get-OcPeople $it.Recipients $RCPT_MAX
                        $att = (@($pp.to, $pp.cc) | Where-Object { $_ }) -join '; '
                        if ($pp.capped) { $counts.rcpt_capped++ }
                    } catch { $script:protErr++; $att = '? <>' }
                    if (-not $att -and -not $org) { $att = '? <>' }
                } else { $att = '? <>' }
            }
            $body = ''
            if ($calBodyOn) {
                $cb = Get-CalBody -Item $it -ProtOk ($protOk -and -not $script:calBodyOff)
                $script:calBody[$cb.why] = [int]$script:calBody[$cb.why] + 1
                if ($cb.why -eq 'err') { $script:calBodyOff = $true }
                $body = [string]$cb.body
            }
            $f = @($it.Start.ToString('yyyy-MM-dd HH:mm'), $it.End.ToString('yyyy-MM-dd HH:mm'), [string]$it.AllDayEvent, [string][int]$it.BusyStatus,
                   [string]$it.Subject, [string]$it.Categories, [string]$it.Location, $resp, $mst, $sens, $org, $att)
            if ($calBodyOn) { $f += $body }
            $rows.Add((($f | ForEach-Object { Csv-Escape ([string]$_) }) -join ','))
            try { $script:calLast = $it.Start.ToString($TS) } catch {}
        } catch {}
    }
    return $rows
}
function Read-MailMonth($mo, [string[]]$me, $state) {
    # 반환: 이 달의 메일 원자료 행 목록. 폴더(EntryID 표식)마다 '다 읽음'·'여기까지 읽음' 표식을 state 에 남긴다.
    # 예산에 닿으면 멈춘 폴더의 경계 분(같은 분의 행은 버리고 다음에 그 분부터 다시 읽는다)을 state.before 에 둔다.
    # rcv = 수신 구분: to(직접 수신) / cc(참조) / bulk(내 주소가 받는 사람·참조에 없음) / unknown(주소를 못 읽음·내 주소 모름)
    $rows = [System.Collections.Generic.List[string]]::new()
    $script:stopReason = ''
    foreach ($b in $script:folders) {
        $fk = [string]$b.key
        if ($state.done.ContainsKey($fk)) { continue }
        $upper = $mo.end
        if ($state.before.ContainsKey($fk) -and $state.before[$fk]) {
            try { $upper = ([datetime]::ParseExact([string]$state.before[$fk], $TS, $null)).AddMinutes(1) } catch {}
            if ($upper -gt $mo.end) { $upper = $mo.end }
        }
        $boxRows = [System.Collections.Generic.List[object]]::new()      # @{ t; line }
        $stop = ''; $lastT = $null
        $fname = [string]$b.name
        if ($SelfTest) {
            for ($i = 0; $i -lt $SelfTest; $i++) {
                $t = $mo.end.AddMinutes(-1 - $i * 97)
                if ($t -lt $mo.start) { $t = $mo.start.AddMinutes($i) }
                if ($t -ge $upper) { continue }
                if ($SelfTestDelayMs -gt 0) { Start-Sleep -Milliseconds $SelfTestDelayMs }
                if ($sw.Elapsed.TotalSeconds -gt $BudgetSec) { $stop = ('시간 예산 {0}초' -f $BudgetSec); break }
                $pp = Get-SelfTestPeople $i
                if ($b.box -eq 'sent') { $f = @('sent', $t.ToString('yyyy-MM-dd HH:mm'), 'selftest', 'selftest@corp.local', $pp.cc, '', '', 'minute') }
                else { $f = @('inbox', $t.ToString('yyyy-MM-dd HH:mm'), $pp.sender_name, $pp.sender_addr, $pp.to, $pp.cc, 'to', 'minute') }
                $f += @(('selftest mail ' + $i), ('conv ' + ($i % 3)), '0', '', $fname)
                $boxRows.Add(@{ t = $t; line = (($f | ForEach-Object { Csv-Escape ([string]$_) }) -join ',') })
                $lastT = $t
            }
        } else {
            $mi = $b.node.Items
            $mi.Sort($b.field, $true)                   # 최신순 - 예산에 닿으면 '여기까지 읽음' 경계를 남긴다
            $mflt = ("{0} >= '{1}' AND {0} < '{2}'" -f $b.field, (Format-OlDate $mo.start $fmt), (Format-OlDate $upper $fmt))
            $msel = $mi.Restrict($mflt)
            $n = 0
            foreach ($m in $msel) {
                $n++
                if ($n -gt 20000) { $stop = ('{0} 상한 20000건' -f $b.box); break }
                if (($n % 25) -eq 0 -and $sw.Elapsed.TotalSeconds -gt $BudgetSec) { $stop = ('시간 예산 {0}초' -f $BudgetSec); break }
                try {
                    if ($m.Class -ne 43) { continue }  # olMail only
                    $t = if ($b.box -eq 'inbox') { $m.ReceivedTime } else { $m.SentOn }
                    if ($t -lt $mo.start -or $t -ge $upper) { $script:monthMismatch++; continue }   # Restrict 결과 재검사
                    $lastT = $t
                    if (Test-Struct-Mail $m) { continue }
                    $subj = [string]$m.Subject
                    $conv = [string]$m.ConversationTopic
                    $cat = ''; try { $cat = [string]$m.Categories } catch {}
                    $sens = '0'; try { $sens = [string][int]$m.Sensitivity } catch {}
                    $sn = ''; $sa = ''; $toS = ''; $ccS = ''; $rcv = ''; $noRcpt = $false
                    if ($protOk) {
                        try { $sn = [string]$m.SenderName } catch { $script:protErr++ }
                        try { $sa = Get-OcSenderAddr $m } catch { $script:protErr++ }
                        # 받은 메일의 보낸 사람이 사외(또는 주소를 못 읽음)면 G1 이 어차피 뺀다 - 받는 사람 목록은 읽지 않는다
                        $needRcpt = ($b.box -eq 'sent') -or ($sa -and (Test-InternalAddr $sa $script:internal))
                        if ($needRcpt) {
                            # 받는 사람을 하나도 읽지 못하면 참조에 '? <>'(증명 불가): 보낸 사람 주소만으로 사내 메일임을 증명하지 않는다
                            try {
                                $pp = Get-OcMailRecipients $m.Recipients $RCPT_MAX
                                $toS = $pp.to; $ccS = $pp.cc; $noRcpt = [bool]$pp.none
                                if ($pp.capped) { $counts.rcpt_capped++ }
                            } catch { $script:protErr++; $ccS = '? <>'; $noRcpt = $true }
                        }
                        if (-not $sa) { $counts.addr_unknown++ }
                    }
                    if ($b.box -eq 'inbox') {
                        if (-not $protOk -or $noRcpt -or (-not $toS -and -not $ccS)) { $rcv = 'unknown' }
                        elseif (Test-MeInList $toS $me) { $rcv = 'to' }
                        elseif (Test-MeInList $ccS $me) { $rcv = 'cc' }
                        elseif (-not $me.Count) { $rcv = 'unknown' }
                        else { $rcv = 'bulk' }
                        if ($rcv -eq 'unknown') { $script:rcvUnknown++ }
                    }
                    $f = @($b.box, $t.ToString('yyyy-MM-dd HH:mm'), $sn, $sa, $toS, $ccS, $rcv, 'minute', $subj, $conv, $sens, $cat, $fname)
                    $boxRows.Add(@{ t = $t; line = (($f | ForEach-Object { Csv-Escape ([string]$_) }) -join ',') })
                } catch {}
            }
        }
        if ($stop) {
            # 경계 분의 행은 버리고 표식만 남긴다 - 다음 실행이 그 분부터(포함) 다시 읽으므로 빠짐도 중복도 없다
            if ($lastT) {
                $bm = $lastT.ToString('yyyy-MM-dd HH:mm')
                foreach ($x in $boxRows) { if ($x.t.ToString('yyyy-MM-dd HH:mm') -ne $bm) { $rows.Add($x.line) } }
                $state.before[$fk] = $lastT.ToString($TS)
            } else { foreach ($x in $boxRows) { $rows.Add($x.line) } }
            $script:stopReason = $stop
            return $rows
        }
        foreach ($x in $boxRows) { $rows.Add($x.line) }
        $state.done[$fk] = $true
    }
    return $rows
}
function Months-ToRead([string]$kind) {
    # 읽는 순서: ① 최신 달 → ② 아직 못 읽은 달(최신→과거) → ③ 나머지 재수집 달. -NoRefresh 면 ②만. -Force 면 전부.
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
    $script:fatal = $code
    throw (New-Object System.OperationCanceledException $code)
}
function Add-Verdict([string]$axis, $mo, $v) { $script:verd[$axis + '|' + $mo.key] = $v }
function Build-Ranges {
    # 기간의 달마다 축별 ranges - 이번에 읽은 달은 판정으로, 읽지 않았지만 완료 표에 있는 달은 표의 st 로. 둘 다 아니면 싣지 않는다.
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
            $out.Add([ordered]@{ axis = $ax; from = $mo.start.ToString($DAYF); to = $mo.end.AddDays(-1).ToString($DAYF); st = $st })
        }
    }
    return $out
}
$script:verd = @{}
$script:fatal = ''
$script:internal = @()
$launched = $false; $launchT = $null; $wd = $null
$hz = @{ oldest = $null; newest = $null }
$cached = $false
$script:coldCom = $false
$readCal = 0; $readMail = 0
$warnings = [System.Collections.Generic.List[string]]::new()
$refreshIncomplete = [System.Collections.Generic.List[string]]::new()

try {
    $script:cov = Load-Coverage
    if ($Force) { $script:cov = New-Coverage }
    $mailTodo = @(Months-ToRead 'mail')
    $calTodo  = @(Months-ToRead 'calendar')
    Write-Host ("[outlook] 기간 {0} ~ {1} · {2}개월 · 읽을 달: 메일 {3} / 일정 {4} (완료된 달은 건너뜀{5}{6}) · 예산 {7}초" -f `
        $since.ToString($DAYF), $until.AddDays(-1).ToString($DAYF), $months.Count, $mailTodo.Count, $calTodo.Count, `
        $(if ($Force) { ' - Force 로 전부 다시' } else { '' }), $(if ($NoRefresh) { ' - 이어서 읽기 회차' } else { '' }), $BudgetSec)

    $ns = $null
    $me = @()
    if ($SelfTest) {
        Write-Host ("[outlook] 자가검증 모드 - Outlook 없이 달마다 가짜 메일 {0}건·일정 {1}건" -f $SelfTest, [math]::Max(1, [int]($SelfTest / 2)))
        $me = @('selftest@corp.local')
        $canary = 'ok'; $hz = @{ oldest = $since.AddDays(-1); newest = (Get-Date) }
        $script:folders = @(@{ key = 'inbox'; box = 'inbox'; role = 'inbox'; field = '[ReceivedTime]'; name = 'inbox' },
                            @{ key = 'sent'; box = 'sent'; role = 'sent'; field = '[SentOn]'; name = 'sent' })
        $counts.filter_fmt = $fmt; $counts.canary = $canary; $counts.folders = 2; $counts.prot = 'selftest'
    } else {
        # 떠 있는 Outlook 에 먼저 붙는다(사용자가 실제로 쓰는 판). 바쁜 순간의 거부는 짧게 재시도한다.
        $hr = ''
        for ($try = 1; $try -le 3 -and -not $ol; $try++) {
            try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') } catch { $ol = $null; $hr = Get-OcHResult $_ }
            if (-not $ol -and $try -lt 3) { Start-Sleep -Seconds 2 }
        }
        if (-not $ol -and $olRunning) {
            # 실행 중인데 붙을 수 없다 - 관리자 권한(R-ELEV) · 바쁨(R-BUSY, attachWaitSec 까지 다시) · 막 뜸(ROT 등록 지연) · 대화상자(R-DIALOG).
            # 이때 New-Object 를 부르면 그 창이 닫힐 때까지 반환되지 않으므로 부르지 않는다.
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
                if ($why -eq 'R-ELEV') {
                    Write-Host '[outlook] 건너뜀: 이 수집이 관리자 권한으로 돌고 있어 일반 권한으로 뜬 Outlook 에 붙지 못합니다(R-ELEV).'
                    Write-Host '          AgentFinder32 를 관리자 권한 없이(일반 실행) 다시 실행하세요.'
                    Set-SkipReason '수집이 관리자 권한으로 돌아 Outlook 에 붙지 못했습니다 — 일반 권한으로 다시 실행하세요'
                } elseif ($why -eq 'R-BUSY') {
                    Write-Host ("[outlook] 건너뜀: Outlook 이 {0}초 동안 바쁨 응답만 했습니다(R-BUSY {1}) - 잠시 뒤 다시 수집하세요." -f $attachWait, $hr)
                    Set-SkipReason 'Outlook 이 계속 바쁨 응답을 했습니다 — 잠시 뒤 다시 수집하세요'
                } else {
                    Write-Host '[outlook] 건너뜀: Outlook 이 실행 중이지만 아직 사용할 준비가 안 됐습니다.'
                    Write-Host '          보통 "Outlook 시작" 설정 마법사·프로필 선택·암호 입력 창이 떠 있을 때입니다.'
                    Write-Host '          그 창을 닫거나 설정을 끝내고 메일 화면까지 연 다음 다시 수집하세요. (재설치하지 마세요)'
                    Set-SkipReason 'Outlook 이 대화상자에 막혀 있습니다 — 그 창을 닫고 메일 화면까지 연 다음 다시 수집하세요'
                }
                Stop-Collect $why
            }
        }
        if (-not $ol) {
            # Outlook 미실행일 때만 이 수집이 띄운다. 무진전 확인: attachWaitSec 안에 받은 편지함까지 못 가면 우리가 띄운 것만 끝낸다.
            $launchT = Get-Date
            $launched = $true; $counts.launched = $true
            $wd = Start-OcLaunchWatchdog -Sec $attachWait -Since $launchT
            try {
                $ol = New-Object -ComObject Outlook.Application
                $ns = $ol.GetNamespace('MAPI')
                try { $ns.Logon($null, $null, $false, $false) } catch {}     # ShowDialog=$false - 프로필 선택창을 띄우지 않는다
                [void]$ns.GetDefaultFolder(6)
            } catch {
                $hr = Get-OcHResult $_
                $counts.attach_hr = $hr
                $fired = [bool]$wd.sync.fired
                Stop-OcLaunchWatchdog $wd; $wd = $null
                if ($fired) {
                    Write-Host ("[outlook] 건너뜀: Outlook 을 띄웠지만 {0}초 안에 메일 화면까지 가지 못해 이 수집이 띄운 Outlook 을 닫았습니다(R-WIZARD)." -f $attachWait)
                    Set-SkipReason 'Outlook 을 띄웠지만 메일 화면까지 가지 못했습니다(시작 마법사·프로필 선택 창 의심) — Outlook 을 직접 실행해 확인하세요'
                    Stop-Collect 'R-WIZARD'
                }
                if ($hr -eq '0x80040154') {
                    Write-Host '[outlook] 건너뜀: 클래식 Outlook 이 COM 에 등록돼 있지 않습니다(R-NOCLASSIC - 미설치 의심).'
                    Set-SkipReason '클래식 Outlook 이 COM 에 등록돼 있지 않습니다(미설치 의심) — Outlook 웹·Copilot 경로가 읽습니다'
                    Stop-Collect 'R-NOCLASSIC'
                }
                $nk = Stop-OutlookWeStarted -Since $launchT
                Write-Host ("[outlook] 건너뜀: Outlook 을 띄우지 못했습니다(R-LAUNCH {0}){1}" -f $hr, $(if ($nk) { (' - 이 수집이 띄운 Outlook {0}개 정리' -f $nk) } else { '' }))
                Set-SkipReason ('Outlook 을 띄우지 못했습니다(' + $hr + ') — 클래식 Outlook 을 직접 실행해 메일 화면까지 연 뒤 다시 수집하세요')
                Stop-Collect 'R-LAUNCH'
            }
            $fired = [bool]$wd.sync.fired
            Stop-OcLaunchWatchdog $wd; $wd = $null
            if ($fired) { Stop-Collect 'R-WIZARD' }
        } else {
            $ns = $ol.GetNamespace('MAPI')
            try { [void]$ns.GetDefaultFolder(6) } catch {}     # 떠 있는 Outlook 에는 Logon 을 부르지 않는다
        }
        try { Write-Host ("[outlook] 연결: 버전 {0}" -f $ol.Version) } catch {}
        # 보호 멤버(주소) - 실제로 한 번 읽어 본다(정책·백신은 보지 않는다). 무응답이면 보안 확인 창이 떠 있다 - 이번 수집은 멈춘다.
        $pr = Test-OcProtectedRead -Sec 20
        $protOk = [bool]$pr.ok; $counts.prot = [string]$pr.why
        if ($pr.why -eq 'prompt') {
            Write-Host '[outlook] 멈춤: Outlook 보안 확인 창("다른 프로그램이 전자 메일 주소 정보에 액세스하려고 합니다")이 떠 있습니다(R-OMG).'
            Write-Host '          그 창에서 허용을 고르면 다음 수집부터 읽습니다. 거부하면 사내 메일인지 확인할 수 없어 메일·회의가 분석에서 빠집니다.'
            Set-SkipReason 'Outlook 보안 확인 창이 떠 있습니다 — 창에서 허용 또는 거부를 고른 뒤 다시 수집하세요'
            Stop-Collect 'R-OMG'
        }
        if (-not $protOk) {
            $reasons.Add('R-OMG')
            Write-Host ("[outlook] 주의: 주소(보낸 사람·받는 사람·참석자)를 읽지 못합니다({0}) - 사내 메일인지 확인할 수 없는 메일·회의는 분석에서 빠집니다" -f $pr.why)
        }
        # 내 주소 - 내 기본 사서함의 계정 SMTP·CurrentUser 의 Exchange 기본 주소·표시 이름만(Get-OcMyAddresses · 보호 멤버라
        # 읽을 수 있을 때만). 프로필의 다른 계정·주소 꼴 계정 표시 이름·config owner 는 사내 도메인의 근거로 쓰지 않는다.
        $me = @(Get-OcMyAddresses -Ns $ns -ProtOk $protOk)
        if (-not @($me | Where-Object { $_ -match $script:OC_ADDR_RX }).Count) {
            $reasons.Add('R-NOADDR')
            Write-Host '[outlook] 주의: 내 메일 주소를 확정하지 못했습니다(R-NOADDR) - 받은 메일의 수신 구분(to/cc/bulk)은 unknown 으로 둡니다'
        }
    }
    $script:me = @($me)
    # 사내 도메인(D7) = privacy.internalDomains ∪ 내 주소의 도메인 - 공용 개인 메일 도메인은 뺀다(Get-OcInternalDomains).
    # 비면 읽지 않는다(종료 코드 4) - 내 기본 사서함이 개인 메일 계정뿐이면 그 사서함을 읽지 않는다.
    $doms = @(Get-OcInternalDomains $cfgDomains $me)
    $script:internal = @($doms)
    if (-not $doms.Count) {
        Write-Host '[outlook] 사내 메일 도메인을 알 수 없어 분석하지 않았습니다 — 설정의 privacy.internalDomains 를 채우세요 (R-NODOMAIN)'
        Set-SkipReason '사내 메일 도메인을 알 수 없어 분석하지 않았습니다 — 설정의 privacy.internalDomains 를 채우세요'
        Stop-Collect 'R-NODOMAIN'
    }
    if (-not $SelfTest) {
        # 읽을 메일 폴더: 기본 저장소 루트에서 재귀(outlook.subfolders=false 면 받은·보낸 편지함 최상위만). PST·공유·보관 사서함은 읽지 않는다.
        $store = $null; try { $store = $ns.DefaultStore } catch {}
        try { $cached = [bool]$store.IsCachedExchange } catch { $cached = $false }
        $script:coldCom = ($launched -and ($cached -or $newOutlook))
        $counts.cached = $cached; $counts.cold = $script:coldCom
        $defs = @{}
        foreach ($n in (@(6, 5) + $script:OC_SKIP_FOLDERS)) {
            $fd = $null
            try { $fd = $store.GetDefaultFolder($n) } catch { try { $fd = $ns.GetDefaultFolder($n) } catch {} }
            if ($fd) { try { $defs[$n] = [string]$fd.EntryID } catch {} }
        }
        $base = @(@{ node = $ns.GetDefaultFolder(6); key = $(if ($defs[6]) { Get-OcKey $defs[6] } else { 'inbox' }); box = 'inbox'; role = 'inbox'; field = '[ReceivedTime]'; name = 'inbox' },
                  @{ node = $ns.GetDefaultFolder(5); key = $(if ($defs[5]) { Get-OcKey $defs[5] } else { 'sent' }); box = 'sent'; role = 'sent'; field = '[SentOn]'; name = 'sent' })
        $script:folders = $base
        if ($subOn -and $store) {
            $fl = $null
            try { $fl = Get-MailFolderList -Root $store.GetRootFolder() -Defaults $defs -Exclude $exFolders } catch { $fl = $null }
            if ($fl -and $fl.folders.Count) {
                $script:folders = @($fl.folders)
                $counts.folders_excluded = [int]$fl.excluded; $counts.folders_private = [int]$fl.private; $counts.folders_capped = [bool]$fl.capped
            }
        }
        $counts.folders = @($script:folders).Count
        if ($counts.folders_private) { Write-Host ('[outlook] 제외 폴더(privacy.excludeMailFolders) {0}개와 그 하위는 읽지 않습니다' -f $counts.folders_private) }
        if ($counts.folders_capped) { Write-Host ('[outlook] 경고: 메일 폴더 상한 {0}개에 닿아 나머지 폴더는 읽지 않았습니다' -f $script:OC_FOLDERS_MAX) }
        # 캐시 지평선·OST 신선도: 받은·보낸 편지함의 가장 오래된·최근 메일. 우리가 띄운 캐시 Outlook 이 낡았으면 동기화를 잠깐(30초) 기다린다.
        $hz = Get-MailHorizon $base
        if ($launched -and $cached -and $staleH -gt 0 -and ($null -eq $hz.newest -or $hz.newest -lt (Get-Date).AddHours(-$staleH))) {
            $tw = [System.Diagnostics.Stopwatch]::StartNew()
            while ($tw.Elapsed.TotalSeconds -lt 30) {
                Start-Sleep -Seconds 5
                $c2 = Get-CanaryItem $base
                if ($c2 -and $c2.t -ge (Get-Date).AddHours(-$staleH)) { $hz.newest = $c2.t; break }
            }
        }
        # 날짜 필터 카나리아: 가장 최근 항목 시각 T 의 [T-2분, T+2분) 을 형식마다 걸어 그 항목이 돌아오는 첫 형식을 쓴다
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
            Write-Host '[outlook] 수집 중단: 날짜 필터 카나리아 실패 - 이 PC 의 Outlook 이 받는 날짜 형식을 찾지 못했습니다(R-FILTER).'
            Set-SkipReason 'Outlook 날짜 필터 형식을 찾지 못했습니다(로캘 의심) — Outlook 웹·Copilot 경로가 메일을 읽습니다'
            Stop-Collect 'R-FILTER'
        }
        $fmt = [string]$sel.fmt
        $counts.filter_fmt = $fmt
        if ($canary -eq 'none') { $reasons.Add('R-NOCANARY') }
        Write-Host ("[outlook] 날짜 필터 형식 {0} (카나리아 {1}) · 메일 폴더 {2}개{3} · 지평선 {4} ~ {5}{6}" -f $fmt, $canary, $counts.folders,
            $(if ($subOn) { '(하위 폴더 포함)' } else { '' }),
            $(if ($hz.oldest) { $hz.oldest.ToString($DAYF) } else { '?' }), $(if ($hz.newest) { $hz.newest.ToString($DAYF) } else { '?' }),
            $(if ($cached) { ' · 캐시 모드' } else { '' }))
        if ($script:coldCom) {
            $reasons.Add('R-COMCOLD')
            Write-Host '[outlook] 주의: 이 수집이 Outlook 을 직접 띄웠습니다 - 캐시가 사서함 전체를 담았는지 알 수 없어 "읽음"으로 적지 않습니다(R-COMCOLD).'
        }
    }
    $now = (Get-Date).ToString('yyyy-MM-dd')     # 완료 표·수집 요약의 when - 날짜만
    if ($counts.folders_capped) { $warnings.Add(('메일 폴더 상한 {0}개 - 나머지 폴더는 읽지 않음' -f $script:OC_FOLDERS_MAX)) }

    # ---------- calendar: 최신 달부터, 예산의 절반까지 ----------
    foreach ($mo in $calTodo) {
        if ($sw.Elapsed.TotalSeconds -gt ($BudgetSec * 0.5)) { break }
        $wasComplete = Test-Covered 'calendar' $mo
        $p = Get-Partial 'calendar' $mo
        $rows = @(Read-CalendarMonth $ns $mo $(if ($p) { $p.from } else { '' }))
        $prev = $(if ($p) { [int]$p.rows } else { 0 })
        if ($script:stopReason) {
            if ($wasComplete) {
                # 완료했던 달의 재수집이 끊겼다 - 지난 정제분을 지키고(이번 행은 버림) 다음 실행이 처음부터 다시 읽는다
                $refreshIncomplete.Add('일정 ' + $mo.key)
                $warnings.Add(('일정 {0}: {1} - 지난 수집분을 그대로 두고 다음 실행에서 다시 읽습니다' -f $mo.key, $script:stopReason))
            } else {
                foreach ($ln in $rows) { $script:rawCal.Add($ln) }
                Add-Span 'cal' $(if ($p) { 'append' } else { 'replace' }) $mo
                $script:cov.partial.calendar[$mo.key] = @{ from = $script:calLast; start = $mo.start; end = $mo.end; rows = $prev + $rows.Count }
                $script:cov.calendar.Remove($mo.key)
                $warnings.Add(('일정 {0}: {1} - 이 달은 다음 실행에서 이어서 읽습니다' -f $mo.key, $script:stopReason))
                Add-Verdict 'cal' $mo (Test-MonthDone -Rows 0 -Canary $canary -Start $mo.start -End $mo.end -Cached $false -Stopped $true)
            }
            $reasons.Add($(if ($script:stopReason -match '상한') { 'R-CAP' } else { 'R-BUDGET' }))
            Write-Host ('[outlook] 경고: ' + $warnings[$warnings.Count - 1])
            Save-Raw
            break
        }
        foreach ($ln in $rows) { $script:rawCal.Add($ln) }
        Add-Span 'cal' $(if ($p) { 'append' } else { 'replace' }) $mo
        $cnt = $prev + $rows.Count
        # 0행 달은 카나리아가 성공했을 때만 완료(zero_ok). 구조 규칙으로 뺀 회의도 '읽은' 것이다(행 수에 넣지 않는다)
        $v = Limit-ColdVerdict (Test-MonthDone -Rows $cnt -Canary $canary -Start $mo.start -End $mo.end -Cached $false) $script:coldCom
        Add-Verdict 'cal' $mo $v
        if ($v.done) { $script:cov.calendar[$mo.key] = @{ rows = $cnt; when = $now; start = $mo.start; end = $mo.end; st = $v.st } }
        else { $script:cov.calendar.Remove($mo.key) }
        $script:cov.partial.calendar.Remove($mo.key)
        $readCal++
        Save-Raw
        Write-Host ("[outlook] 일정 {0}: {1}건 [{2}] (경과 {3}초)" -f $mo.key, $cnt, $v.st, [int]$sw.Elapsed.TotalSeconds)
    }
    if ($calBodyOn -and -not $SelfTest -and ($script:calBody.Values | Measure-Object -Sum).Sum -gt 0) {
        Write-Host ("[outlook] 일정 본문: 읽음 {0} · 빈 본문 {1} · 개인·비공개 {2} · 주소 읽기 불가라 안 읽음 {3} · 오류 {4}" -f `
            $script:calBody.ok, $script:calBody.empty, $script:calBody.private, $script:calBody.prot, $script:calBody.err)
    }

    # ---------- mail (기본 저장소 메일 폴더 - 받은 쪽 + 보낸 쪽): 최신 달부터, 예산까지 ----------
    foreach ($mo in $mailTodo) {
        if ($sw.Elapsed.TotalSeconds -gt $BudgetSec) { break }
        if (-not $SelfTest -and $cached -and $hz.oldest -and $mo.end -le ([datetime]$hz.oldest).Date) {
            # 캐시 지평선 앞의 달 - 로컬(OST)에 없으니 읽어도 0건이다. 0건으로 확정하지 않는다(웹 경로가 채운다)
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
        if ($script:monthMismatch -gt 0) { $warnings.Add(('메일 {0}: 날짜 필터 범위 밖 행 {1}건을 버림(이 달은 완료로 적지 않음)' -f $mo.key, $script:monthMismatch)) }
        $cIn = 0; $cOut = 0
        foreach ($ln in $rows) { if ($ln.StartsWith('sent,')) { $cOut++ } else { $cIn++ } }
        if ($p) { $cIn += [int]$p.rows_in; $cOut += [int]$p.rows_out }
        if ($script:stopReason) {
            if ($wasComplete) {
                $refreshIncomplete.Add('메일 ' + $mo.key)
                $warnings.Add(('메일 {0}: {1} 도달 - 지난 수집분을 그대로 두고 다음 실행에서 다시 읽습니다' -f $mo.key, $script:stopReason))
            } else {
                foreach ($ln in $rows) { $script:rawMail.Add($ln) }
                Add-Span 'mail' $(if ($p) { 'append' } else { 'replace' }) $mo
                $script:cov.partial.mail[$mo.key] = @{ done = $state.done; before = $state.before; start = $mo.start; end = $mo.end; rows_in = $cIn; rows_out = $cOut }
                $script:cov.mail.Remove($mo.key)
                $warnings.Add(('메일 {0}: {1} 도달 - 이 달은 다음 실행에서 이어서 읽습니다' -f $mo.key, $script:stopReason))
                $vs = Test-MonthDone -Rows 0 -Canary $canary -Start $mo.start -End $mo.end -Stopped $true
                Add-Verdict 'mail_in' $mo $vs; Add-Verdict 'mail_out' $mo $vs
            }
            $reasons.Add($(if ($script:stopReason -match '상한') { 'R-CAP' } else { 'R-BUDGET' }))
            Write-Host ('[outlook] 경고: ' + $warnings[$warnings.Count - 1])
            Save-Raw
            break
        }
        foreach ($ln in $rows) { $script:rawMail.Add($ln) }
        Add-Span 'mail' $(if ($p) { 'append' } else { 'replace' }) $mo
        $cnt = $cIn + $cOut
        $vIn = Test-MonthDone -Rows $cIn -Canary $canary -Oldest $hz.oldest -Newest $hz.newest -Start $mo.start -End $mo.end -StaleH $staleH -Cached $cached -Mismatch $script:monthMismatch
        $vOut = Test-MonthDone -Rows $cOut -Canary $canary -Oldest $hz.oldest -Newest $hz.newest -Start $mo.start -End $mo.end -StaleH $staleH -Cached $cached -Mismatch $script:monthMismatch
        $vIn = Limit-ColdVerdict $vIn $script:coldCom; $vOut = Limit-ColdVerdict $vOut $script:coldCom
        Add-Verdict 'mail_in' $mo $vIn; Add-Verdict 'mail_out' $mo $vOut
        if ($vIn.done -and $vOut.done) {
            $script:cov.mail[$mo.key] = @{ rows = $cnt; rows_in = $cIn; rows_out = $cOut; st_in = $vIn.st; st_out = $vOut.st; when = $now; start = $mo.start; end = $mo.end }
        } else { $script:cov.mail.Remove($mo.key) }
        $script:cov.partial.mail.Remove($mo.key)
        $readMail++
        Save-Raw
        Write-Host ("[outlook] 메일 {0}: {1}건 (받은 {2} [{3}] / 보낸 {4} [{5}]) (경과 {6}초)" -f $mo.key, $cnt, $cIn, $vIn.st, $cOut, $vOut.st, [int]$sw.Elapsed.TotalSeconds)
    }
    Save-Raw

    # ---------- 요약: 기간 안에서 아직 못 읽은 달 ----------
    $uncMail = @($months | Where-Object { -not (Test-Covered 'mail' $_) } | ForEach-Object { $_.key })
    $uncCal  = @($months | Where-Object { -not (Test-Covered 'calendar' $_) } | ForEach-Object { $_.key })
    $unc = @($uncMail + $uncCal | Select-Object -Unique | Sort-Object)
    $partialMonths = @(@($script:cov.partial.mail.Keys) + @($script:cov.partial.calendar.Keys) | Select-Object -Unique | Sort-Object)
    $complete = ($unc.Count -eq 0)
    $nMail = $script:rawMail.Count; $nCal = $script:rawCal.Count
    foreach ($x in @(Build-Ranges)) { $ranges.Add($x) }
    if (@($ranges | Where-Object { $_.st -eq 'out_of_horizon' }).Count) {
        if ($cached -and $staleH -gt 0 -and ($null -eq $hz.newest -or $hz.newest -lt (Get-Date).AddHours(-$staleH))) { $reasons.Add('R-STALE') }
        if ($hz.oldest -and ([datetime]$hz.oldest).Date -gt $since) { $reasons.Add('R-HORIZON') }
    }
    if ($script:rcvUnknown -gt 0) { $warnings.Add(('받은 메일 {0}건 rcv=unknown(주소를 못 읽음·내 주소 미확정)' -f $script:rcvUnknown)) }
    $stRc = $(if ($nMail + $nCal -eq 0 -and ($readMail + $readCal) -gt 0 -and ($script:excl.private + $script:excl.admin) -eq 0) { 1 } else { 0 })
    Clear-SkipReason
    try {
        # 수집 요약(글 없음) - run.py 가 이어서 수집할지 정하는 키(coverage_complete·uncovered_months·partial_months·refresh_incomplete)와
        # 내 주소(me - 사내 도메인의 근거). 완료 표는 G1 이 확정한다(coverage_com.json).
        $src = [ordered]@{ product = 'AgentFinder32'; source = $srcName; when = $now; mail = $nMail; calendar = $nCal; me = @($me);
                           calendar_complete = ($uncCal.Count -eq 0); mail_truncated = ($uncMail.Count -gt 0); warnings = @($warnings);
                           coverage_complete = $complete; uncovered_months = @($unc); uncovered_mail = @($uncMail); uncovered_calendar = @($uncCal);
                           partial_months = @($partialMonths); refresh_incomplete = @($refreshIncomplete);
                           months_read = [ordered]@{ mail = $readMail; calendar = $readCal };
                           period = @($since.ToString($DAYF), $until.AddDays(-1).ToString($DAYF));
                           budget_sec = $BudgetSec; elapsed_sec = [int]$sw.Elapsed.TotalSeconds; selftest = [bool]$SelfTest; no_refresh = [bool]$NoRefresh;
                           ver = $covVer; rc = $stRc; reason = ((@($reasons) | Select-Object -Unique) -join ',');
                           filter_fmt = $fmt; canary = $canary; folders = [int]$counts.folders; prot = [string]$counts.prot;
                           excluded = $script:excl; internal_domains = @($script:internal);
                           me_known = [bool](@($me | Where-Object { $_ -match $script:OC_ADDR_RX }).Count) }
        $txt = $src | ConvertTo-Json -Compress -Depth 4
        [System.IO.File]::WriteAllText($srcP, $txt, (New-Object System.Text.UTF8Encoding($false)))
    } catch {}
    Write-Host ("[outlook] 원자료: 메일 {0}건 · 일정 {1}건 · 미리 뺌 개인 {2}·휴가·행방/참석 아님 {3} (이번에 읽은 달: 메일 {4} / 일정 {5}, 경과 {6}초) - G1 정제 뒤 지웁니다" -f `
        $nMail, $nCal, $script:excl.private, $script:excl.admin, $readMail, $readCal, [int]$sw.Elapsed.TotalSeconds)
    if ($refreshIncomplete.Count) { Write-Host ("[outlook] 재수집 미완 {0} - 지난 수집분 유지" -f ($refreshIncomplete -join ', ')) }
    if ($complete) { Write-Host '[outlook] coverage: complete - 기간의 모든 달을 읽었습니다' }
    else {
        Write-Host ("[outlook] coverage: partial - 미수집 달 {0}개: {1}{2}" -f $unc.Count, ($unc -join ','), $(if ($partialMonths.Count) { ' (이어 읽는 중: ' + ($partialMonths -join ',') + ')' } else { '' }))
    }
}
catch {
  $err = $_
  if ($err.Exception -is [System.OperationCanceledException] -and $script:fatal) {
    # 계획된 중단 - 사유와 안내는 이미 남겼다. 이번 실행의 원자료는 남기지 않는다
    $stRc = $(if ($script:fatal -eq 'R-NODOMAIN') { 4 } else { 3 })
    $reasons.Insert(0, $script:fatal)
    $ranges.Clear(); foreach ($x in @(Get-BlockedRanges 'blocked')) { $ranges.Add($x) }
    foreach ($p in @($rawMailP, $rawCalP, $manP)) { try { if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force } } catch {} }
  } else {
    $hrF = Get-OcHResult $err
    if (-not $counts.attach_hr) { $counts.attach_hr = $hrF }
    $stRc = 3
    $reasons.Insert(0, $(if ($hrF -eq '0x80010001' -or $hrF -eq '0x8001010A') { 'R-BUSY' } elseif ($hrF -eq '0x80040154') { 'R-NOCLASSIC' } else { 'R-COMFAIL' }))
    # 실패 전에 읽은 달은 원자료·구간 표에 이미 있다(G1 이 반영). ranges 는 그 판정만, 하나도 없으면 기간 전체를 unverified 로
    try { $ranges.Clear(); foreach ($x in @(Build-Ranges)) { $ranges.Add($x) } } catch {}
    if (-not $ranges.Count) { foreach ($x in @(Get-BlockedRanges 'unverified')) { $ranges.Add($x) } }
    Write-Host ("[outlook] 수집 실패: {0}" -f $err.Exception.Message)
    Set-SkipReason ("수집 실패: " + $err.Exception.Message)
    if ($newOutlook) {
        Write-Host '          원인: "새 Outlook"(COM 미지원) - 클래식 Outlook 으로 전환/실행 후 재시도하세요.'
    } elseif ($err.Exception.Message -match '80010001|8001010A|RPC_E_CALL_REJECTED|RPC_E_SERVERCALL') {
        Write-Host '          원인: Outlook 이 응답하지 않습니다 - 보통 Outlook 이 대화상자를 띄우고 있을 때입니다. 떠 있는 창을 닫은 뒤 다시 수집하세요.'
    } elseif ($err.Exception.Message -match '80040154|REGDB_E_CLASSNOTREG') {
        Write-Host '          원인: 클래식 Outlook 이 설치돼 있지 않음(COM 미등록) - 클래식 Outlook 을 설치하거나 Outlook 웹·Copilot 경로를 쓰세요.'
    } else {
        Write-Host '          클래식 Outlook(2016~365)을 실행해 프로필 로그인까지 마친 상태에서 재시도하세요.'
    }
  }
}
finally {
    if ($wd) { Stop-OcLaunchWatchdog $wd; $wd = $null }
    # 이 수집이 띄운 Outlook 은 창(Explorer·Inspector)이 0개일 때만 닫는다. 사용자가 띄운 Outlook 은 놓기만 한다.
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
# 마지막 줄 = AF32STATUS - run.py 가 rc·사유·달별 검증 범위·미리 뺀 건수를 읽는다. 종료 코드 = rc
$counts.rcv_unknown = [int]$script:rcvUnknown; $counts.prot_err = [int]$script:protErr; $counts.cal_out_of_month = [int]$script:calOut
$counts.horizon_oldest = $(if ($hz.oldest) { ([datetime]$hz.oldest).ToString($DAYF) } else { '' })
$counts.horizon_newest = $(if ($hz.newest) { ([datetime]$hz.newest).ToString($DAYF) } else { '' })
$counts.cached = [bool]$cached; $counts.ver = $covVer; $counts.selftest = [bool]$SelfTest
$counts.months_read = [ordered]@{ mail = [int]$readMail; calendar = [int]$readCal }
$counts.rows = [ordered]@{ mail = [int]$script:rawMail.Count; cal = [int]$script:rawCal.Count }
$counts.excluded = $script:excl; $counts.excluded_why = $script:exclWhy
$counts.cal_body = $script:calBody; $counts.cal_body_on = [bool]$calBodyOn
Write-LmStatus -Src $srcName -Rc $stRc -Reasons @($reasons) -Counts $counts -Ranges @($ranges)
exit $stRc
