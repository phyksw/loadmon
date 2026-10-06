<#
.SYNOPSIS
  mail.com · cal.com — 클래식 Outlook COM 수집기(CM §5). 모든 COM 호출은 자식 프로세스 + 워치독 안에서 한다.

.DESCRIPTION
  계약 §2.17 · §3.5 · §3.10 · §7.3 · §8.1, CM §5 · §8 · §9 · §10 · §11.1, C §4.3. LM24 Get-OutlookData.ps1 을 옮겨 다시 설계했다
  (최상위 폴더만 읽던 결함 → 모든 메일 폴더 재귀 + EntryID 역할 태그, Stop-Job 대기 → 자식 PID 직접 종료, 수신자 열람 실패 시
  'to' 오판정 → rcv 는 정제기가 정하고 B단 실패는 R-OMG).
  계정 있는 회사 PC 위험(M365 조사 — Microsoft 공식 문서 대조) 반영:
    · DASL 날짜 리터럴은 문서 형식이 먼저다 — 'Outlook 은 지역 설정의 날짜·시각 형식으로, 시각은 초 없이 읽는다. 초를 넣으면
      필터가 기대대로 동작하지 않는다'(filtering-items-using-a-date-time-comparison). 현재 로캘 'g'(VBA Format 'General Date'
      의 초 없는 꼴, 값은 UTC) → 'yyyy-MM-dd HH:mm' → ISO(초 포함) 순. 붙은 직후 **필터 카나리아**가 받은 편지함(없으면 보낸
      편지함) 최신 항목 시각 T 의 [T−2분, T+2분) 을 형식마다 걸어 그 항목이 실제로 돌아오는 첫 형식을 쓴다(counts.filter_fmt).
      문서는 잘못된 필터의 처리를 정하지 않는다(GetTable) — 예외 없이 0건이 와도 그 달을 0건 done 으로 굳히지 않으려는 것.
      아무 형식도 맞지 않으면 메일은 rc 3 + R-TRANSPORT(done 0), 일정은 Jet(로컬 'g')만. 읽은 행이 요청 범위 밖이면 버리고
      (counts.filter_mismatch) 그 달은 done 으로 적지 않는다.
    · 보호 멤버(Object Model Guard — Account.SmtpAddress·NameSpace.CurrentUser·Recipients·PropertyAccessor·Sender*·Body 등)는
      B단(ReadProtected=1)에서만 읽는다. B단 첫 읽기(내 주소)는 'pr_start' 단계 — 부모가 이 단계에만 짧은 워치독
      (mail.com.protectedReadSec × 3, 5~워치독 초)을 걸고, 넘기면(보안 경고창으로 멈춤) 자식을 끊고 B단 없이 한 번 다시 붙는다
      (R-OMG · counts.omg_canary=timeout). 거부(예외)면 그 실행은 B단을 끈다(omg_canary=denied). B단을 끈 실행의 내 주소는
      계정 표시 이름(비보호 — 주소 꼴일 때만)과 collect.ownerAddress.
    · Namespace.Logon 을 부르지 않는다 — 문서: 프로필이 여럿이면 기본 프로필에 Logon 해도 선택 창이 뜬다. 권장대로
      GetNamespace('MAPI') + GetDefaultFolder(받은 편지함)로 MAPI 를 초기화한다. 붙기 세부 단계를 하트비트로 내 멈춘 곳을
      counts.attach_step 에 남긴다(attach:get → attach:new → attach:ns → attach:inbox → attach:stores → pr_start).
    · OlExchangeStoreType 3 = olNotExchange(PST·IMAP — 개인 데이터 파일). 보관 사서함 값은 열거형에 없다 — 기본 저장소만
      읽는다(mail.includeArchiveStore 는 보관 사서함 식별을 실측으로 정하기 전까지 counts.archive_store=unverified 만).
    · 캐시 지평선(가장 오래된 메일)이 든 달은 지평선 뒤만 읽고 cov_months 에 적지 않는다 — 원장이 상태 줄 horizon_oldest 로
      날마다 판정(그 앞 0건 날 = out_of_horizon → 웹 경로가 채움). 캐시 모드인데 받은·보낸 편지함 최신 메일이 probe.ostStaleH
      시간보다 오래됐으면(OST 가 낡음 — 새 Outlook 전환·Outlook 꺼짐) R-STALE + 상태 줄 horizon_newest, 그 뒤 날이 든 달도
      적지 않는다. 이 수집이 Outlook 을 띄웠으면 동기화를 잠깐(하트비트) 기다린다 — 보내기/받기(SyncObject.Start)는 보낼
      편지함까지 보내는 사용자 동작이라 부르지 않는다.
    · 관리자 주도 새 Outlook 전환 정책(DoNewOutlookAutoMigration=1 — admin-controlled-migration-policy)이 켜져 있고 Outlook 이
      꺼져 있으면 COM 으로 띄우지 않는다(R-NEWOL · counts.migration_auto). 떠 있는 클래식에는 붙는다.
    · 폴더 열거·지평선 계산 중에도 하트비트(25폴더마다 'folders', 폴더마다 'horizon'), 폴더 3000개 상한(counts.folders_capped).
    · 일정 회차 전개 순서 = Sort('[Start]') → IncludeRecurrences → Restrict(Items.IncludeRecurrences 문서), 창과 겹치지 않는
      회차는 버린다(counts.cal_out_of_range).

  출력(디스크에 쓰지 않는다 — L-09):
    · stdout 첫 줄 {"_meta":{"my_addrs":[...]}} · 원시 후보 레코드 NDJSON(P §10.2 원시 이름) · 끝 줄 {"_cursor":{…}}.
      연결자가 kind 마다 정제 파이프 하나에 잇는다(-Only mail / -Only cal — COM 2회 붙기, 두 번째는 GetActiveObject 재사용).
      -Only 를 비우면 메일·일정을 한 번에 읽고 줄마다 "_kind" 를 붙인다(혼합 라우팅용, 커서는 {경로 ID: 값}).
    · stderr: 사람용 한 줄(숫자·사유만)과 마지막 줄들 {"_status":{…}}(경로마다 하나 — 계약 v1.2 §0.7 C1 한 모양:
      schema·src·rc·reasons·partial·cap_hit·budget_hit·n·counts + items_total·items_ok·new·subfolder_ratio·horizon_oldest·
      horizon_newest 등).
  입력: stdin 제어 줄 {"_in":{"cursor":…,"cfg":{…}}}(연결자가 쓰고 닫는다, 리디렉션이 아니면 기본값). 커서·설정·주소는
  명령줄로 받지 않는다(X-300). 쓰는 설정: mail.com.budgetSec · mail.com.watchdogSec · mail.com.protectedReadSec ·
  mail.com.capMail · mail.com.capCal · mail.com.readProtected(연결자가 auto 를 0/1 로 정해 넘긴다) · mail.includeArchiveStore ·
  collect.ownerAddress · probe.subfolderRatio(있으면 R-SUBFOLDER 판정) · probe.ostStaleH(OST 신선도).

  구조: 부모(이 스크립트)가 사전 점검(새 Outlook·전환 정책·프로필·COM 등록 — COM 호출 없음)을 하고, 같은 스크립트를 -Worker 로
  자식 PowerShell 에 띄운다. 자식은 COM 에 붙어 레코드·하트비트({"_hb"})·진행 커서({"_cur"})·결과({"_wres"})를 stdout 으로
  낸다. 부모는 레코드를 그대로 통과시키고, -WatchdogSec(기본 mail.com.watchdogSec=20) 동안 아무 줄도 없으면 자식을
  Stop-Process 로 끝낸다 — 붙는 중(attach*)이면 R-DIALOG(Outlook 실행 중)·R-WIZARD, 읽는 중이면 R-TRANSPORT.
  Outlook 이 실행 중인데 붙지 못하면 New-Object 를 부르지 않는다(대화상자). 프로필 0·COM 미등록은 자식을 띄우지 않고 건너뛴다.

  읽기: 달 단위·최신 달부터, 보낸 편지함을 먼저(CM §10). A단(비보호 — GetTable 지정 열)은 항상, B단(보호 — 주소·수신자·헤더·
  본문)은 ReadProtected=1 일 때만, 항목마다 mail.com.protectedReadSec 안에서. B단이 거부·지연되면 R-OMG 로 남기고 A단 행은 낸다.
  상한(capMail·capCal) → cap_hit + R-CAP, 예산(budgetSec, 일정은 절반) → budget_hit + R-BUDGET — 둘 다 rc 0(셀 partial).
  지평선(가장 오래된 항목) 이전 달은 0건이 아니라 out_of_horizon + R-HORIZON.
  rc: 0 새 레코드 · 1 기간에 항목 없음 · 3 막힘(사유 필수: R-NEWOL R-NOPROF R-WIZARD R-DIALOG R-ELEV R-CLM R-COM-BUSY
  R-TRANSPORT) · 4 읽었지만 새것 0.

  커서(계약 §3.10): mail.com {"box":{inbox|sent|other:{last_ts_utc,last_msg_key}},"cov_months":{"YYYY-MM":{status,read_from,
  read_to}}} · cal.com {"last_start_utc","cov_months"}. last_msg_key 는 HMAC 이 필요해 null 로 낸다(파이프가 채운다).
  status ∈ done · partial · out_of_horizon. 이미 읽은 달은 건너뛰고, 최근 달(메일 3일·일정 14일)은 매번 다시 읽는다.
  지평선이 걸친 달 · OST 최신 시각 뒤 날이 든 달 · 필터 범위가 어긋난 달은 적지 않는다(다음 실행이 다시 읽고, 원장은
  상태 줄 지평선으로 날마다 판정).

  시험 주입(계약 §11.3): LM_OUTLOOK_SELFTEST=N[,선택…] — Outlook 없이 달마다 가짜 메일 N건·일정 N/2건(+매주 반복 회의).
  선택: newol · noprof · wizard · dialog · elev · busyall · notrunning · noaddr · omg(보호 멤버 거부) · omgitem(항목 단위 B단만
  거부) · omghang(보호 멤버에서 경고창으로 멈춤) · slowb · archive(PST 저장소 — olNotExchange) · jetfail · online(캐시 모드 아님) ·
  automig(관리자 전환 정책) · recurleak(Restrict 가 창 앞 회차도 줌) · horizon=YYYY-MM[-DD] · stale=YYYY-MM-DD(그날 뒤 메일이
  OST 에 없음) · syncafter=<초>(기다리면 동기화) · syncwait=<초> · daslok=<g+plain+iso|none>(받는 DASL 날짜 형식 — 밖이면 예외
  없이 0건) · daslshift=<분>(리터럴을 어긋나게 읽음) · folders=<N> · fdelay=<ms> · hang=attach|read · delay=<ms>.
  이 모드에서는 레지스트리·프로세스·COM 을 전혀 건드리지 않는다. -TestNow 'yyyy-MM-dd HH:mm'(로컬).
  일정은 DASL(UTC)과 Jet(현재 로캘 'g', 로컬 시각) 두 Restrict 결과의 합집합이다 — 반복 회차 전개를 Jet 으로 보장하고,
  로캘이 어긋나 Jet 이 0건이어도 DASL 이 단발 일정을 지킨다. 키 = GlobalAppointmentID·시작·끝.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File collect\Get-OutlookCom.ps1 -Only mail -Pc pc_0123456789abcdef -Since 2026-09-01 -Until 2026-09-30
#>
param(
    [string]$Only = '',
    [string]$Since = '',
    [string]$Until = '',
    [string]$Pc = '',
    [string]$ReadProtected = '',
    [string]$BudgetSec = '',
    [string]$WatchdogSec = '',
    [string]$TestNow = '',
    [string]$OlState = '',
    [switch]$Worker
)

# ── 제한 언어 모드: .NET 형을 쓰기 전에 먼저 본다(R-CLM, rc 3) ─────────────────────────────────────────────
# 계약 v1.2 §0.7 C1: 상태 줄 한 모양(_status). CLM 에서는 [Console] 호출도 막히므로 stdout 제어 줄(문자열 리터럴)로 낸다.
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    if ($Only -eq 'cal') {
        '{"_status":{"schema":"lm27.collector_status/1","src":"cal.com","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{},"items_total":0,"items_ok":0}}'
    } else {
        '{"_status":{"schema":"lm27.collector_status/1","src":"mail.com","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{},"items_total":0,"items_ok":0}}'
    }
    exit 3
}

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:Inv = [Globalization.CultureInfo]::InvariantCulture
$script:StdOut = [Console]::OpenStandardOutput()
$script:StdErr = [Console]::OpenStandardError()
$script:Clock = [Diagnostics.Stopwatch]::StartNew()
$script:RangeOut = $null

$PC_RX = '^pcx?_[0-9a-f]{16}$'
$PROPTAG = 'http://schemas.microsoft.com/mapi/proptag/'
$P_DELIVERY = $PROPTAG + '0x0E060040'     # PR_MESSAGE_DELIVERY_TIME(UTC)
$P_SUBMIT = $PROPTAG + '0x00390040'       # PR_CLIENT_SUBMIT_TIME(UTC)
$P_IMID = $PROPTAG + '0x1035001F'         # PR_INTERNET_MESSAGE_ID
$P_INREPLY = $PROPTAG + '0x1042001F'      # PR_IN_REPLY_TO_ID
$P_HASATT = $PROPTAG + '0x0E1B000B'       # PR_HASATTACH
$P_CONVID = $PROPTAG + '0x30130102'       # PR_CONVERSATION_ID
$P_SENDER_SMTP = $PROPTAG + '0x5D01001F'  # PR_SENDER_SMTP_ADDRESS(B단)
$P_HEADERS = $PROPTAG + '0x007D001F'      # PR_TRANSPORT_MESSAGE_HEADERS(B단)
$P_SMTP = $PROPTAG + '0x39FE001E'         # PR_SMTP_ADDRESS(수신자, B단)
$DT_START = 'urn:schemas:calendar:dtstart'
$DT_END = 'urn:schemas:calendar:dtend'
$OUTLOOK_START_GRACE_SEC = 120     # 꺼진 Outlook 을 COM 으로 띄울 때 attach 무진전 허용(초) — LM24 는 제한 없이 기다렸다
$RPC_E_CALL_REJECTED = -2147418111        # 0x8001010A
$REGDB_E_CLASSNOTREG = -2147221164        # 0x80040154
$MAIL_REFRESH_DAYS = 3
$CAL_REFRESH_DAYS = 14
$HB_EVERY = 25
$FOLDERS_MAX = 3000                # 메일 폴더 열거 상한(탐침 Measure-Subfolders 와 같은 값) — 넘으면 counts.folders_capped
$DASL_FORMATS = @('g', 'plain', 'iso')    # DASL 날짜 리터럴 형식(문서 형식 먼저 — Format-DaslDate)
$CANARY_MIN = 2                    # 필터 카나리아 창 ±분 · 같은 항목으로 볼 시각 차(초)는 CANARY_TOL_SEC
$CANARY_TOL_SEC = 61
$STALE_SYNC_WAIT_SEC = 30          # 이 수집이 띄운 캐시 모드 Outlook 의 동기화를 기다리는 상한(초)
$PR_LIMIT_MIN = 5                  # B단 카나리아(pr_start) 워치독 하한(초)
$BODY_HEAD = 1000
$BODY_TAIL = 4000
$HEADERS_MAX = 16000
$RCPT_MAX = 100
$ONLINE_RX = '(?i)teams\.microsoft\.com/l/meetup-join|zoom\.us/j/|\.webex\.com/|Microsoft Teams'
$ADDR_RX = '^[^@\s<>"]+@[^@\s<>"]+\.[^@\s<>"]+$'
$BUSY_OF = @{ 0 = 'free'; 1 = 'tentative'; 2 = 'busy'; 3 = 'oof'; 4 = 'elsewhere' }
# 수집 제외(CM §5.3): '대화 기록'(Skype·Lync IM 대화록 폴더 — OlDefaultFolders 값이 없어 이름으로) — 하위 포함.
# 같은 목록이 색인 수집기 기본 제외(mail.index.excludeFolderNames)에도 있다. 클래스로도 한 번 더 거른다(언어 무관).
$CONV_HISTORY_NAMES = @('대화 기록', 'Conversation History')
$IM_CLASS_RX = '^(IPM\.Note\.Microsoft\.(Conversation|Missed)|IPM\.SkypeTeams\.)'

# ── 출력 ──────────────────────────────────────────────────────────────────────────────────────────────
function Write-OutLine([string]$s) {
    $b = $script:Utf8.GetBytes($s + "`n")
    $script:StdOut.Write($b, 0, $b.Length)
    $script:StdOut.Flush()
}
function Write-ErrLine([string]$s) {
    $b = $script:Utf8.GetBytes($s + "`n")
    try { $script:StdErr.Write($b, 0, $b.Length); $script:StdErr.Flush() } catch { }
}
$script:JsonEval = [System.Text.RegularExpressions.MatchEvaluator] { param($m) '\u{0:x4}' -f [int][char]$m.Value }
function ConvertTo-JStr([string]$s) {
    if ($null -eq $s) { return 'null' }
    $t = $s.Replace('\', '\\').Replace('"', '\"')
    if ($t -match '[\x00-\x1f]') { $t = [regex]::Replace($t, '[\x00-\x1f]', $script:JsonEval) }
    return '"' + $t + '"'
}
function ConvertTo-J($v) {
    if ($null -eq $v) { return 'null' }
    if ($v -is [string]) { return (ConvertTo-JStr $v) }
    if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
    if ($v -is [int] -or $v -is [long] -or $v -is [int16] -or $v -is [byte] -or $v -is [uint32] -or $v -is [uint64]) {
        return ([long]$v).ToString($script:Inv)
    }
    if ($v -is [double] -or $v -is [single] -or $v -is [decimal]) {
        $d = [double]$v
        if ([double]::IsNaN($d) -or [double]::IsInfinity($d)) { return 'null' }
        $t = $d.ToString('R', $script:Inv)
        if ($t -notmatch '[.Ee]') { $t += '.0' }
        return $t
    }
    if ($v -is [datetime]) { return (ConvertTo-JStr (Format-Utc $v)) }
    if ($v -is [System.Collections.IDictionary]) {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($k in $v.Keys) { $parts.Add((ConvertTo-JStr ([string]$k)) + ':' + (ConvertTo-J $v[$k])) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v.GetType().FullName -eq 'System.Management.Automation.PSCustomObject') {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($p in $v.PSObject.Properties) { $parts.Add((ConvertTo-JStr $p.Name) + ':' + (ConvertTo-J $p.Value)) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v -is [System.Collections.IEnumerable]) {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($x in $v) { $parts.Add((ConvertTo-J $x)) }
        return '[' + ($parts -join ',') + ']'
    }
    return (ConvertTo-JStr ([string]$v))
}
function ConvertTo-Ascii([string]$s) {
    $sb = New-Object System.Text.StringBuilder ($s.Length + 16)
    foreach ($ch in $s.ToCharArray()) {
        if ([int]$ch -lt 128) { [void]$sb.Append($ch) } else { [void]$sb.Append(('\u{0:x4}' -f [int]$ch)) }
    }
    return $sb.ToString()
}

# ── 시각 ──────────────────────────────────────────────────────────────────────────────────────────────
function Format-Utc([datetime]$u) {
    return ([DateTime]::SpecifyKind($u, 'Utc')).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv)
}
function Format-Offset([datetime]$u) {
    $ts = [TimeZoneInfo]::Local.GetUtcOffset([DateTime]::SpecifyKind($u, 'Utc'))
    $m = [int]$ts.TotalMinutes
    $sign = '+'
    if ($m -lt 0) { $sign = '-'; $m = -$m }
    return ('{0}{1:00}:{2:00}' -f $sign, [math]::Floor($m / 60), ($m % 60))
}
function ConvertTo-UtcFromLocal([datetime]$local) {
    return [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($local, 'Unspecified'), [TimeZoneInfo]::Local)
}
function ConvertTo-LocalFromUtc([datetime]$u) {
    return [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::SpecifyKind($u, 'Utc'), [TimeZoneInfo]::Local)
}
function ConvertFrom-UtcText($s) {
    if (-not $s) { return $null }
    $d = [datetime]::MinValue
    if ([datetime]::TryParseExact([string]$s, "yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv, [Globalization.DateTimeStyles]::None, [ref]$d)) {
        return [DateTime]::SpecifyKind($d, 'Utc')
    }
    return $null
}
function Get-MinDate($a, $b) { if ($null -eq $a) { return $b }; if ($null -eq $b) { return $a }; if ($a -lt $b) { return $a }; return $b }
function Get-MaxDate($a, $b) { if ($null -eq $a) { return $b }; if ($null -eq $b) { return $a }; if ($a -gt $b) { return $a }; return $b }
function Format-DaslDate([datetime]$u, [string]$fmt) {
    # DASL 날짜 리터럴 — 값은 UTC(네임스페이스로 쓴 속성 비교는 UTC). 문서: Outlook 은 지역 설정의 날짜·시각 형식으로, 시각은
    # 초 없이 읽는다('초를 넣으면 필터가 기대대로 동작하지 않는다' — VBA 예제는 Format(…, "General Date")). 그래서 'g'(현재
    # 로캘 짧은 날짜 + 짧은 시각)가 먼저고, 'plain'(yyyy-MM-dd HH:mm)·'iso'(초 포함 — 예전 기본)는 카나리아가 고를 때만 쓴다.
    $d = [DateTime]::SpecifyKind($u, 'Utc')
    if ($fmt -eq 'iso') { return $d.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv) }
    if ($fmt -eq 'plain') { return $d.ToString('yyyy-MM-dd HH:mm', $script:Inv) }
    return $d.ToString('g', [Globalization.CultureInfo]::CurrentCulture)
}
function Get-Dasl([string]$prop, [datetime]$lo, [datetime]$hi, [string]$fmt) {
    $a = Format-DaslDate $lo $fmt
    $b = Format-DaslDate $hi $fmt
    return ('@SQL="{0}" >= ''{1}'' AND "{0}" < ''{2}''' -f $prop, $a, $b)
}
function Get-CalDasl([datetime]$lo, [datetime]$hi, [string]$fmt) {
    $a = Format-DaslDate $lo $fmt
    $b = Format-DaslDate $hi $fmt
    return ('@SQL="{0}" < ''{1}'' AND "{2}" > ''{3}''' -f $DT_START, $b, $DT_END, $a)
}

# ── stdin 제어 줄 · 설정 ──────────────────────────────────────────────────────────────────────────────
function Read-InLine {
    try { if (-not [Console]::IsInputRedirected) { return $null } } catch { return $null }
    $s = [Console]::OpenStandardInput()
    $buf = New-Object System.Collections.Generic.List[byte]
    while ($buf.Count -lt 4194304) {
        $x = $s.ReadByte()
        if ($x -lt 0 -or $x -eq 10) { break }
        $buf.Add([byte]$x)
    }
    $t = $script:Utf8.GetString($buf.ToArray()).Trim([char]0xFEFF, [char]13, ' ')
    if (-not $t) { return $null }
    $o = $t | ConvertFrom-Json
    if ($o -and $o.PSObject.Properties['_in']) { return $o._in }
    return $null
}
function Get-Cfg($in, [string]$key, $default) {
    if ($null -eq $in -or $null -eq $in.PSObject.Properties['cfg'] -or $null -eq $in.cfg) { return $default }
    $p = $in.cfg.PSObject.Properties[$key]
    if ($null -eq $p -or $null -eq $p.Value) { return $default }
    return $p.Value
}
function Get-SrcCursor($in, [string]$src, [bool]$mixed) {
    if ($null -eq $in -or $null -eq $in.PSObject.Properties['cursor'] -or $null -eq $in.cursor) { return $null }
    if ($mixed) {
        $p = $in.cursor.PSObject.Properties[$src]
        if ($p) { return $p.Value }
        return $null
    }
    return $in.cursor
}
function Get-IntArg([string]$v, $fallback, [int]$min) {
    if (-not $v) { $v = [string]$fallback }
    $n = 0
    if (-not [int]::TryParse([string]$v, [ref]$n) -or $n -lt $min) { throw (New-Object System.ArgumentException('int')) }
    return $n
}
function Get-SelfTest {
    # LM_OUTLOOK_SELFTEST=N[,선택…] — 값이 있으면 무조건 시험 모드(실물 COM 을 건드리지 않는다)
    $raw = [string]$env:LM_OUTLOOK_SELFTEST
    if (-not $raw.Trim()) { return $null }
    $parts = @($raw.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $n = 0
    if ($parts.Count) { [void][int]::TryParse($parts[0], [ref]$n) }
    $opt = @{}
    foreach ($p in ($parts | Select-Object -Skip 1)) {
        $kv = $p.Split('=', 2)
        if ($kv.Count -eq 2) { $opt[$kv[0].ToLower()] = $kv[1] } else { $opt[$kv[0].ToLower()] = $true }
    }
    return @{ n = [math]::Max(0, $n); opt = $opt }
}
function New-Result([string]$src) {
    return [ordered]@{ schema = 'lm27.collector_status/1'; src = $src; rc = 3
        reasons = (New-Object System.Collections.Generic.List[string]); partial = $false; n = 0; items_total = 0
        items_ok = 0; new = 0; cap_hit = $false; budget_hit = $false; horizon_oldest = $null; horizon_newest = $null
        subfolder_ratio = $null; recurrence_incomplete = 0; counts = [ordered]@{} }
}
function Add-Reason($res, [string]$code) { if (-not $res.reasons.Contains($code)) { $res.reasons.Add($code) } }
function ConvertTo-ResultJson($r) {
    # 사전(자식 안·부모의 실패 경로)과 PSCustomObject(부모가 자식 _wres 를 ConvertFrom-Json 한 것) 둘 다 받는다
    $o = [ordered]@{}
    if ($r -is [System.Collections.IDictionary]) { foreach ($k in $r.Keys) { $o[$k] = $r[$k] } }
    else { foreach ($pp in $r.PSObject.Properties) { $o[$pp.Name] = $pp.Value } }
    $rs = @($o['reasons'] | Where-Object { $_ } | Sort-Object -Unique)
    $o['reasons'] = $rs
    # 계약 v1.2 §0.7 C1 필수 필드: schema · partial(= 상한·예산·반복 일부) · n(= 새 레코드 수)
    $o['schema'] = 'lm27.collector_status/1'
    if ($script:RangeOut -and -not $o.Contains('range')) { $o['range'] = @($script:RangeOut) }
    $o['partial'] = [bool]($o['cap_hit'] -or $o['budget_hit'] -or ([int]$o['recurrence_incomplete'] -gt 0) -or ($rs -contains 'R-RECURINC'))
    $o['n'] = [int]$o['new']
    if ($null -eq $o['counts']) { $o['counts'] = [ordered]@{} }
    return (ConvertTo-J $o)
}

# ═════════════════════════════════════ 자식(-Worker): COM 읽기 ═════════════════════════════════════
function Write-Hb([string]$phase, [int]$n) { Write-OutLine ('{"_hb":{"phase":"' + $phase + '","n":' + $n + '}}') }
function Write-Rec([System.Collections.IDictionary]$rec, [string]$kind) {
    if ($script:W.mixed) { $rec['_kind'] = $kind }
    Write-OutLine (ConvertTo-J $rec)
}
function Test-Budget([double]$limit) { return ($script:Clock.Elapsed.TotalSeconds -gt $limit) }
function Get-BodyWindow([string]$t) {
    if (-not $t) { return '' }
    $t = $t.Trim()
    if ($t.Length -le $BODY_HEAD + $BODY_TAIL) { return $t }
    return $t.Substring(0, $BODY_HEAD) + "`n" + $t.Substring($t.Length - $BODY_TAIL)
}
function Split-Cats([string]$s) {
    if (-not $s) { return @() }
    return @($s.Split([char[]]@(',', ';')) | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -First 10)
}

function Get-Months([datetime]$sinceLocal, [datetime]$untilLocalExcl) {
    $out = New-Object System.Collections.Generic.List[object]
    $m = New-Object DateTime ($sinceLocal.Year, $sinceLocal.Month, 1)
    while ($m -lt $untilLocalExcl) {
        $n = $m.AddMonths(1)
        $lo = $m; if ($lo -lt $sinceLocal) { $lo = $sinceLocal }
        $hi = $n; if ($hi -gt $untilLocalExcl) { $hi = $untilLocalExcl }
        $out.Add(@{ key = $m.ToString('yyyy-MM', $script:Inv); lo = (ConvertTo-UtcFromLocal $lo); hi = (ConvertTo-UtcFromLocal $hi);
                    first = ($lo -eq $sinceLocal) })
        $m = $n
    }
    $out.Reverse()
    return , $out
}
function Get-CovIn($cur) {
    $h = @{}
    if ($cur -and $cur.PSObject.Properties['cov_months'] -and $cur.cov_months) {
        foreach ($p in $cur.cov_months.PSObject.Properties) {
            $v = $p.Value
            if ($null -eq $v) { continue }
            $h[$p.Name] = @{ status = [string]$v.status; read_from = (ConvertFrom-UtcText $v.read_from); read_to = (ConvertFrom-UtcText $v.read_to) }
        }
    }
    return $h
}
function Get-ReadRange($m, $prior, [datetime]$refreshFrom, [double]$overlapDays) {
    # 이번에 읽을 [lo, hi) — 이미 읽은 범위([read_from, read_to))는 건너뛰고, 최근 구간은 다시 읽는다. 읽을 것이 없으면 $null
    if (-not $prior -or $prior.status -notin @('done', 'partial') -or -not $prior.read_from -or -not $prior.read_to) {
        return @{ lo = $m.lo; hi = $m.hi }
    }
    $a = $prior.read_from; $b = $prior.read_to
    $lowGap = $m.lo -lt $a
    $highGap = $b -lt $m.hi
    $refresh = $m.hi -gt $refreshFrom
    if (-not $lowGap -and -not $highGap -and -not $refresh) { return $null }
    if ($lowGap) { $lo = $m.lo }
    else {
        $lo = $null
        if ($highGap) { $lo = $b.AddDays(-$overlapDays) }
        if ($refresh) { $lo = Get-MinDate $lo $refreshFrom }
        if ($lo -lt $m.lo) { $lo = $m.lo }
    }
    if ($highGap -or $refresh) { $hi = $m.hi } else { $hi = $a.AddMinutes(1); if ($hi -gt $m.hi) { $hi = $m.hi } }
    if ($hi -le $lo) { return $null }
    return @{ lo = $lo; hi = $hi }
}
function Merge-Cov($prior, [datetime]$lo, [datetime]$hi, $m) {
    # 이번에 읽은 [lo, hi) 를 앞 범위와 합친다(붙어 있을 때만). 달 전체를 덮으면 done.
    $a = $lo; $b = $hi
    if ($prior -and $prior.read_from -and $prior.read_to -and $prior.status -in @('done', 'partial')) {
        if ($lo -le $prior.read_to -and $hi -ge $prior.read_from) {
            $a = Get-MinDate $lo $prior.read_from
            $b = Get-MaxDate $hi $prior.read_to
        }
    }
    $st = 'partial'
    if ($a -le $m.lo -and $b -ge $m.hi) { $st = 'done' }
    return @{ status = $st; read_from = $a; read_to = $b }
}
function ConvertTo-CovJson($cov) {
    $o = [ordered]@{}
    foreach ($k in ($cov.Keys | Sort-Object -Descending)) {
        $v = $cov[$k]
        $rf = $null; $rt = $null
        if ($v.read_from) { $rf = Format-Utc $v.read_from }
        if ($v.read_to) { $rt = Format-Utc $v.read_to }
        $o[$k] = [ordered]@{ status = $v.status; read_from = $rf; read_to = $rt }
    }
    return $o
}

# ── 시험 모델(LM_OUTLOOK_SELFTEST) — 실물 COM 과 같은 모양의 폴더·항목 ─────────────────────────────────
function New-StFolder([string]$id, [string]$name, [string]$store, [int]$type) {
    return @{ EntryID = $id; Name = $name; StoreID = $store; DefaultItemType = $type; Children = (New-Object System.Collections.Generic.List[object]);
              Items = (New-Object System.Collections.Generic.List[object]) }
}
function New-SelfModel($st, $w) {
    $n = [int]$st.opt_n
    $o = $st.opt
    $s1 = 'ST-STORE-1'
    $root = New-StFolder 'ST-ROOT-1' 'Top' $s1 0
    $f = @{}
    foreach ($spec in @(@('inbox', '받은 편지함', 0), @('sent', '보낸 편지함', 0), @('deleted', '지운 편지함', 0), @('junk', '정크 메일', 0),
                        @('drafts', '임시 보관함', 0), @('outbox', '보낼 편지함', 0), @('project', '과제A 자료', 0),
                        @('convhist', '대화 기록', 0),
                        @('calendar', '일정', 1), @('contacts', '연락처', 2))) {
        $x = New-StFolder ('ST-F-' + $spec[0]) $spec[1] $s1 $spec[2]
        $f[$spec[0]] = $x
        $root.Children.Add($x)
    }
    $f['rules'] = New-StFolder 'ST-F-rules' '규칙폴더' $s1 0
    $f['inbox'].Children.Add($f['rules'])
    if ($o.folders) {                                                   # 폴더가 많은 사서함(M14)
        for ($k = 1; $k -le [int]$o.folders; $k++) { $f['project'].Children.Add((New-StFolder ('ST-F-x{0}' -f $k) ('폴더{0}' -f $k) $s1 0)) }
    }
    # 저장소 후보(실물 Get-ComStores 와 같은 판정 — Resolve-StoreRole): 기본 사서함 + 선택 archive 면 개인 데이터 파일(PST,
    # OlExchangeStoreType 3 olNotExchange — 사적 메일이 있을 수 있다)
    $cands = New-Object System.Collections.Generic.List[object]
    $cands.Add(@{ id = $s1; root = $root; isDefault = $true; xtype = 0; defaults = @{ inbox = 'ST-F-inbox'; sent = 'ST-F-sent'; deleted = 'ST-F-deleted';
                  junk = 'ST-F-junk'; drafts = 'ST-F-drafts'; outbox = 'ST-F-outbox' } })
    if ($o.archive) {
        $s2 = 'ST-STORE-2'
        $root2 = New-StFolder 'ST-ROOT-2' '개인 폴더' $s2 0
        $f['arch'] = New-StFolder 'ST-F-arch' '받은 편지함' $s2 0
        $f['archdel'] = New-StFolder 'ST-F-archdel' '지운 편지함' $s2 0
        $root2.Children.Add($f['arch']); $root2.Children.Add($f['archdel'])
        $cands.Add(@{ id = $s2; root = $root2; isDefault = $false; xtype = 3; defaults = @{ deleted = 'ST-F-archdel' } })
    }
    $me = @{ addr = 'gildong.hong@corp.example'; name = '홍길동' }
    $peers = @(@{ addr = 'chulsoo.kim@corp.example'; name = '김철수' }, @{ addr = 'peer.b@corp.example'; name = '동료B' },
               @{ addr = 'peer.c@corp.example'; name = '동료C' })
    $cyc = @('inbox', 'inbox', 'inbox', 'rules', 'sent', 'sent', 'project', 'X')
    $junkCyc = @('deleted', 'junk', 'drafts', 'outbox')
    $horizon = $null                                                    # 캐시 지평선(로컬) — 이 앞 메일은 OST 에 없다
    if ($o.horizon) { $hs = [string]$o.horizon; if ($hs.Length -eq 7) { $hs += '-01' }; $horizon = [datetime]::ParseExact($hs, 'yyyy-MM-dd', $script:Inv) }
    $stale = $null                                                      # 이날(로컬 0시) 뒤 메일은 서버에만(OST 가 낡음)
    if ($o.stale) { $stale = [datetime]::ParseExact([string]$o.stale, 'yyyy-MM-dd', $script:Inv) }
    $hidden = New-Object System.Collections.Generic.List[object]
    $nowL = $w.nowLocal
    # 모델 기간 = 요청 기간의 앞 한 달 ~ max(요청 끝, 오늘) — 실물 사서함처럼 요청과 무관하게 지금까지 항목이 있다
    $m = (New-Object DateTime ($w.sinceLocal.Year, $w.sinceLocal.Month, 1)).AddMonths(-1)
    $endL = $w.untilLocal; if ($nowL.Date.AddDays(1) -gt $endL) { $endL = $nowL.Date.AddDays(1) }
    $cal = $f['calendar'].Items
    while ($m -lt $endL) {
        $mEnd = $m.AddMonths(1)
        $mk = $m.ToString('yyyyMM', $script:Inv)
        $anchor = $mEnd; if ($anchor -gt $nowL) { $anchor = $nowL }          # 이번 달 메일은 지금까지만
        $span = ($anchor - $m).TotalMinutes
        for ($i = 0; $i -lt $n -and $m -lt $nowL; $i++) {
            # 0번은 달(또는 지금)의 마지막 1분, 나머지는 달 전체에 고르게(경계·지평선·신선도 판정이 실물처럼 드러나게)
            if ($i -eq 0) { $t = $anchor.AddMinutes(-1) } else { $t = $m.AddMinutes([math]::Floor($span * ($n - $i) / ($n + 1))) }
            if ($t -lt $m) { $t = $m.AddMinutes($i) }
            if ($horizon -and $t -lt $horizon) { continue }
            $key = $cyc[$i % 8]
            if ($key -eq 'X') { $key = $junkCyc[[math]::Floor($i / 8) % 4] }
            $isSent = ($key -eq 'sent')
            $cls = 'IPM.Note'
            if ($isSent -and ($i % 7) -eq 5) { $cls = 'IPM.Schedule.Meeting.Resp.Pos' }
            elseif (-not $isSent -and ($i % 11) -eq 10) { $cls = 'REPORT.IPM.Note.NDR' }
            $peer = $peers[$i % 3]
            $to = @($me); $cc = @()
            if ($isSent) { $to = @($peer) } elseif (($i % 4) -eq 3) { $to = @($peers[2]); $cc = @($me) }
            $sender = $peer; if ($isSent) { $sender = $me }
            $subj = ('selftest mail {0} [{1}]' -f $i, $key)
            if (($i % 3) -eq 0) { $subj = 'RE: ' + $subj }
            $hdr = 'Received: from mx.corp.example by mail.corp.example'
            if (-not $isSent -and ($i % 10) -eq 9) { $hdr = "List-Unsubscribe: <https://shop.example/u>`r`nPrecedence: bulk" }
            $att = @()
            if (($i % 6) -eq 1) { $att = @(('selftest_{0}.pptx' -f $i)) }
            $cat = ''
            if (($i % 7) -eq 2) { $cat = '개인' }
            $item = @{ EntryID = ('ST-{0}-{1}' -f $mk, $i); t = (ConvertTo-UtcFromLocal $t); Subject = $subj; MessageClass = $cls
                       Importance = $(if (($i % 5) -eq 4) { 2 } else { 1 }); Sensitivity = $(if (($i % 9) -eq 8) { 2 } else { 0 })
                       Categories = $cat; ConversationTopic = ($subj -replace '^RE: ', ''); imid = ('<st-{0}-{1}@selftest.example>' -f $mk, $i)
                       inreply = (($i % 3) -eq 0); hasatt = ($att.Count -gt 0); att = $att; convid = ('{0:X32}' -f ($i % 4))
                       sender = $sender; to = $to; cc = $cc; headers = $hdr; body = ('selftest body {0}' -f $i) }
            if ($stale -and $t -ge $stale) { $hidden.Add(@{ key = $key; item = $item }) } else { $f[$key].Items.Add($item) }
        }
        # IM 대화록(CM §5.3 수집 제외): 대화 기록 폴더 항목 1건(폴더 이름으로 제외) + 받은 편지함의 IM 클래스 1건(클래스로 제외)
        if ($m.AddHours(11) -lt $nowL -and -not ($horizon -and $m.AddHours(11) -lt $horizon)) {
            foreach ($im in @(@('convhist', 'IPM.Note.Microsoft.Conversation', 'C'), @('inbox', 'IPM.Note.Microsoft.Missed', 'M'))) {
                $item = @{ EntryID = ('ST-IM{0}-{1}' -f $im[2], $mk); t = (ConvertTo-UtcFromLocal $m.AddHours(11)); Subject = ('selftest im [{0}]' -f $im[0])
                    MessageClass = $im[1]; Importance = 1; Sensitivity = 0; Categories = ''; ConversationTopic = 'im'; imid = $null
                    inreply = $false; hasatt = $false; att = @(); convid = $null; sender = $peers[0]; to = @($me); cc = @(); headers = ''
                    body = 'im' }
                if ($stale -and $m.AddHours(11) -ge $stale) { $hidden.Add(@{ key = $im[0]; item = $item }) } else { $f[$im[0]].Items.Add($item) }
            }
        }
        if ($o.archive -and $m -lt $nowL) {
            for ($i = 0; $i -lt [math]::Max(1, [math]::Floor($n / 4)); $i++) {
                $t = $anchor.AddMinutes(-30 - $i * 211); if ($t -lt $m) { $t = $m.AddMinutes($i) }
                $f['arch'].Items.Add(@{ EntryID = ('ST-A-{0}-{1}' -f $mk, $i); t = (ConvertTo-UtcFromLocal $t); Subject = ('selftest archive {0} [arch]' -f $i)
                    MessageClass = 'IPM.Note'; Importance = 1; Sensitivity = 0; Categories = ''; ConversationTopic = 'archive'
                    imid = ('<st-a-{0}-{1}@selftest.example>' -f $mk, $i); inreply = $false; hasatt = $false; att = @(); convid = 'A0'
                    sender = $peers[0]; to = @($me); cc = @(); headers = ''; body = 'archive' })
            }
        }
        # 일정: 단발 N/2건 + 매주 월요일 10:00 반복 회의(회차 전개, 같은 GlobalAppointmentID)
        $nc = [math]::Max(1, [math]::Floor($n / 2))
        $days = ($mEnd - $m).Days
        for ($i = 0; $i -lt $nc; $i++) {
            $s = $m.AddDays($i % $days).AddHours(9 + ($i % 8))
            $allDay = (($i % 7) -eq 6)
            if ($allDay) { $s = $m.AddDays($i % $days); $e = $s.AddDays(1) } else { $e = $s.AddHours(1) }
            $resp = 3; if (($i % 3) -eq 0) { $resp = 1 }
            $cal.Add(@{ s = (ConvertTo-UtcFromLocal $s); e = (ConvertTo-UtcFromLocal $e); Subject = ('selftest meeting {0}' -f $i)
                AllDayEvent = $allDay; BusyStatus = $(if ($allDay) { 3 } else { 2 }); Categories = ''; Sensitivity = $(if (($i % 9) -eq 8) { 2 } else { 0 })
                GlobalAppointmentID = ('{0:X8}{1}' -f $i, $mk); ResponseStatus = $resp; MeetingStatus = $(if (($i % 10) -eq 9) { 5 } else { 1 })
                Location = $(if (($i % 4) -eq 1) { 'Microsoft Teams 회의' } else { '회의실 2' }); IsRecurring = $false
                organizer = $(if ($resp -eq 1) { $me } else { $peers[0] }); attendees = @($me, $peers[1]); body = 'selftest agenda' })
        }
        $d = $m
        while ($d -lt $mEnd) {
            if ($d.DayOfWeek -eq [DayOfWeek]::Monday) {
                $s = $d.AddHours(10)
                $cal.Add(@{ s = (ConvertTo-UtcFromLocal $s); e = (ConvertTo-UtcFromLocal $s.AddMinutes(30)); Subject = 'selftest weekly'
                    AllDayEvent = $false; BusyStatus = 2; Categories = ''; Sensitivity = 0; GlobalAppointmentID = 'ST-SERIES-0001'
                    ResponseStatus = 1; MeetingStatus = 1; Location = '회의실 1'; IsRecurring = $true; organizer = $me
                    attendees = @($me, $peers[0], $peers[1]); body = 'weekly' })
            }
            $d = $d.AddDays(1)
        }
        $m = $mEnd
    }
    $accts = @()
    if (-not $o.noaddr) { $accts = @($me.addr) }                        # 계정 표시 이름(비보호) — 기본은 주소 꼴
    return @{ cands = $cands; folders = $f; me = $me; hidden = $hidden; accounts = $accts }
}
function Update-StSync {
    # 시험 모델: 선택 syncafter=<초> 면 붙은 뒤 그만큼 지나 OST 에 없던 메일이 들어온다(이 수집이 띄운 Outlook 의 동기화)
    $w = $script:W
    if (-not $w.st.opt.syncafter -or $w.model.hidden.Count -eq 0) { return }
    if (($script:Clock.Elapsed.TotalSeconds - $w.t0) -lt [double]$w.st.opt.syncafter) { return }
    foreach ($h in $w.model.hidden) { $w.model.folders[$h.key].Items.Add($h.item) }
    $w.model.hidden.Clear()
}
function Get-StDaslWindow([string]$flt) {
    # 시험 모델 Outlook 의 DASL 날짜 해석 → @(앞 리터럴, 뒤 리터럴)(UTC). 받는 형식(선택 daslok, 기본 g+plain+iso) 밖이면 예외
    # 없이 0건($null — 문서: 잘못된 필터의 처리는 정의돼 있지 않다), 선택 daslshift=<분> 이면 그만큼 어긋나게 읽는다.
    $lits = [regex]::Matches($flt, "'([^']*)'")
    if ($lits.Count -ne 2) { return $null }
    $vals = New-Object System.Collections.Generic.List[datetime]
    foreach ($l in $lits) {
        $s = $l.Groups[1].Value
        $kind = 'g'
        if ($s -match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$') { $kind = 'iso' } elseif ($s -match '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$') { $kind = 'plain' }
        if ($script:W.daslOk -notcontains $kind) { return $null }
        $d = $null
        try {
            if ($kind -eq 'iso') { $d = ConvertFrom-UtcText $s }
            elseif ($kind -eq 'plain') { $d = [DateTime]::SpecifyKind([datetime]::ParseExact($s, 'yyyy-MM-dd HH:mm', $script:Inv), 'Utc') }
            else { $d = [DateTime]::SpecifyKind([datetime]::Parse($s, [Globalization.CultureInfo]::CurrentCulture), 'Utc') }
        } catch { return $null }
        if ($null -eq $d) { return $null }
        $vals.Add($d.AddMinutes($script:W.daslShift))
    }
    return , $vals.ToArray()
}

# ── 공급자(시험 모델 · 실물 COM) ─────────────────────────────────────────────────────────────────────
function Get-NodeChildren($node) {
    if ($script:W.st) { return , $node.Children }
    $out = New-Object System.Collections.Generic.List[object]
    try { foreach ($c in $node.Folders) { $out.Add($c) } } catch { }
    return , $out
}
function Get-NodeType($node) { try { return [int]$node.DefaultItemType } catch { return -1 } }
function Resolve-StoreRole([bool]$isDefault, [int]$xtype) {
    # 저장소 역할 — 기본 저장소만 읽는다. OlExchangeStoreType: 0 기본 사서함 · 1 위임 · 2 공용 폴더 · 3 olNotExchange(Exchange
    # 아님 — PST·IMAP 개인 데이터 파일) · 4 추가 사서함. 보관 사서함을 가리키는 값은 이 열거형에 없다(문서). 예전에는 3 을 보관
    # 사서함으로 보고 includeArchiveStore 면 읽어 개인 PST(사적 메일)가 role=archive 로 나갈 수 있었다(M365 조사 M16).
    if ($isDefault) { return 'primary' }
    if ($xtype -eq 3) { return 'non_exchange' }
    return 'other'
}
function Select-Stores($cands) {
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($c in $cands) {
        $role = Resolve-StoreRole ([bool]$c.isDefault) ([int]$c.xtype)
        if ($role -eq 'primary') { $out.Add($c) } else { $script:W.storeSkip[$role] = [int]$script:W.storeSkip[$role] + 1 }
    }
    return , $out
}
function Get-MailFolders {
    # 저장소마다 루트(보이는 트리 — 숨김 폴더 없음)에서 메일 폴더를 재귀로 모으고 역할을 EntryID 로 정한다(이름 아님, CM §5.3).
    # 폴더가 수백~수천인 회사 사서함·온라인 모드에서도 워치독(무진전)에 걸리지 않게 25폴더마다 하트비트, 3000개 상한(M14).
    # 너비 우선 + 받은·보낸 편지함 먼저 — 상한에 닿아도 기본 폴더는 빠지지 않는다.
    $out = New-Object System.Collections.Generic.List[object]
    $nf = 0
    foreach ($store in $script:W.stores) {
        if ($script:W.foldersCapped) { break }
        $def = $store.defaults
        $skip = @{}
        foreach ($k in @('deleted', 'junk', 'drafts', 'outbox', 'conflicts', 'syncissues', 'localfail', 'serverfail', 'rss')) {
            if ($def.ContainsKey($k) -and $def[$k]) { $skip[[string]$def[$k]] = $k }
        }
        $first = @(); $rest = @()
        foreach ($c in (Get-NodeChildren $store.root)) {
            $cid = ''
            try { $cid = [string]$c.EntryID } catch { }
            if ($cid -and (($def.ContainsKey('inbox') -and $cid -eq [string]$def['inbox']) -or ($def.ContainsKey('sent') -and $cid -eq [string]$def['sent']))) { $first += , $c }
            else { $rest += , $c }
        }
        $queue = New-Object System.Collections.Generic.Queue[object]
        foreach ($c in @($first + $rest)) { $queue.Enqueue(@{ node = $c; under = '' }) }
        while ($queue.Count) {
            if ($nf -ge $FOLDERS_MAX) { $script:W.foldersCapped = $true; break }
            $e = $queue.Dequeue()
            $node = $e.node
            $nf++
            if (($nf % $HB_EVERY) -eq 0) { Write-Hb 'folders' $nf }
            if ($script:W.st -and $script:W.st.opt.fdelay) { Start-Sleep -Milliseconds ([int]$script:W.st.opt.fdelay) }
            $id = ''
            try { $id = [string]$node.EntryID } catch { continue }
            if ($skip.ContainsKey($id)) { $script:W.excluded++; continue }     # 지운·정크·임시 보관·보낼 편지함(하위 포함) 제외
            $fname = ''
            try { $fname = ([string]$node.Name).Trim() } catch { $fname = '' }
            if ($CONV_HISTORY_NAMES -contains $fname) { $script:W.excluded++; continue }   # 대화 기록(IM 대화록, 하위 포함)
            if ((Get-NodeType $node) -ne 0) { continue }                          # 메일 폴더만
            $under = $e.under
            $role = 'subfolder'; $box = 'inbox'
            if ($def.ContainsKey('inbox') -and $id -eq [string]$def['inbox']) { $role = 'inbox'; $under = 'inbox' }
            elseif ($def.ContainsKey('sent') -and $id -eq [string]$def['sent']) { $role = 'sent'; $box = 'sent'; $under = 'sent' }
            elseif ($under -eq 'sent') { $box = 'sent' }
            $cnt = -1
            try { $cnt = [int]$node.Items.Count } catch { $cnt = -1 }
            if ($cnt -ne 0) { $out.Add(@{ node = $node; role = $role; box = $box; store = $store.id; sent = ($box -eq 'sent') }) }
            else { $script:W.emptyFolders++ }
            foreach ($c in (Get-NodeChildren $node)) { $queue.Enqueue(@{ node = $c; under = $under }) }
        }
    }
    $script:W.foldersSeen = $nf
    return , $out
}
function Read-FolderRowsFmt($fd, [datetime]$lo, [datetime]$hi, [string]$fmt, [int]$max) {
    # 그 폴더의 [lo, hi) 행(A단 열만)을 날짜 형식 $fmt 의 DASL 로. GetTable 이 필터를 거부하면 $null(예외), 받으면 행 목록
    # (0건일 수 있다 — 문서는 잘못된 필터의 처리를 정하지 않는다). $max > 0 이면 그만큼만(카나리아).
    $prop = $P_DELIVERY; if ($fd.sent) { $prop = $P_SUBMIT }
    $flt = Get-Dasl $prop $lo $hi $fmt
    $rows = New-Object System.Collections.Generic.List[object]
    if ($script:W.st) {
        $win = Get-StDaslWindow $flt
        if ($null -eq $win) { return , $rows }                                # 시험 모델 Outlook: 예외 없이 0건
        foreach ($it in $fd.node.Items) {
            if ($it.t -ge $win[0] -and $it.t -lt $win[1]) {
                $rows.Add(@{ id = $it.EntryID; store = $fd.store; t = $it.t; subject = $it.Subject; cls = $it.MessageClass; imp = $it.Importance
                             sens = $it.Sensitivity; cats = $it.Categories; topic = $it.ConversationTopic; imid = $it.imid; inreply = $it.inreply
                             hasatt = $it.hasatt; convid = $it.convid; fd = $fd; st = $it })
                if ($max -gt 0 -and $rows.Count -ge $max) { break }
            }
        }
        return , $rows
    }
    $tbl = $null
    try { $tbl = $fd.node.GetTable($flt, 0) } catch { return $null }
    $tbl.Columns.RemoveAll()
    $cols = @('EntryID', 'Subject', 'MessageClass', 'Importance', 'Sensitivity', 'Categories', 'ConversationTopic', $prop, $P_IMID, $P_INREPLY,
              $P_HASATT, $P_CONVID)
    $ok = @{}
    foreach ($c in $cols) { try { [void]$tbl.Columns.Add($c); $ok[$c] = $true } catch { } }
    $timeCol = $prop; $timeLocal = $false
    if (-not $ok[$prop]) {                                   # UTC proptag 열이 거부되면 로컬 시각 열로(UTC 환산 + 의심 표시)
        $alt = 'ReceivedTime'; if ($fd.sent) { $alt = 'SentOn' }
        try { [void]$tbl.Columns.Add($alt); $timeCol = $alt; $timeLocal = $true } catch { }
    }
    while (-not $tbl.EndOfTable) {
        $r = $tbl.GetNextRow()
        $t = $null
        try {
            if ($timeLocal) { $t = ConvertTo-UtcFromLocal ([datetime]$r.Item($timeCol)) }
            else { $t = [DateTime]::SpecifyKind([datetime]$r.Item($timeCol), 'Utc') }
        } catch { $t = $null }
        if (-not $t) { continue }
        $h = @{ id = ''; store = $fd.store; t = $t; subject = ''; cls = ''; imp = 1; sens = 0; cats = ''; topic = ''; imid = ''; inreply = $false
                hasatt = $false; convid = ''; fd = $fd; st = $null; utcSuspect = $timeLocal }
        try { $h.id = [string]$r.Item('EntryID') } catch { }
        try { $h.subject = [string]$r.Item('Subject') } catch { }
        try { $h.cls = [string]$r.Item('MessageClass') } catch { }
        try { $h.imp = [int]$r.Item('Importance') } catch { }
        try { $h.sens = [int]$r.Item('Sensitivity') } catch { }
        try { $h.cats = [string]$r.Item('Categories') } catch { }
        try { $h.topic = [string]$r.Item('ConversationTopic') } catch { }
        if ($ok[$P_IMID]) { try { $h.imid = [string]$r.Item($P_IMID) } catch { } }
        if ($ok[$P_INREPLY]) { try { $h.inreply = [bool]([string]$r.Item($P_INREPLY)) } catch { } }
        if ($ok[$P_HASATT]) { try { $h.hasatt = [bool]$r.Item($P_HASATT) } catch { } }
        if ($ok[$P_CONVID]) { try { $h.convid = [string]$r.BinaryToString($P_CONVID) } catch { } }
        $rows.Add($h)
        if ($max -gt 0 -and $rows.Count -ge $max) { break }
    }
    return , $rows
}
function Read-FolderRows($fd, [datetime]$lo, [datetime]$hi) {
    # 카나리아가 고른 형식으로 읽는다(못 골랐으면 문서 순서대로 — 예외가 나면 다음 형식). 요청 범위 밖 행은 버리고 센다
    # (filter_mismatch — 그 달은 done 으로 적지 않는다).
    $rows = $null
    if ($script:W.daslFmt) { $rows = Read-FolderRowsFmt $fd $lo $hi $script:W.daslFmt 0 }
    else {
        foreach ($f in $DASL_FORMATS) {
            $rows = Read-FolderRowsFmt $fd $lo $hi $f 0
            if ($null -ne $rows) { break }
        }
    }
    $keep = New-Object System.Collections.Generic.List[object]
    if ($null -eq $rows) { $script:W.tableErrors++; return , $keep }
    foreach ($r in $rows) {
        if ($r.t -lt $lo -or $r.t -ge $hi) { $script:W.mismatch++ } else { $keep.Add($r) }
    }
    return , $keep
}
function Open-MailItem($row) {
    if ($script:W.st) { return $row.st }
    return $script:W.ns.GetItemFromID($row.id, $row.store)
}
function Read-AttachNames($row) {
    $names = New-Object System.Collections.Generic.List[string]
    if (-not $row.hasatt) { return , $names }
    if ($script:W.st) { foreach ($a in $row.st.att) { $names.Add($a) }; return , $names }
    try {
        $it = Open-MailItem $row
        foreach ($a in $it.Attachments) { if ($names.Count -ge 10) { break }; try { if ($a.FileName) { $names.Add([string]$a.FileName) } } catch { } }
    } catch { }
    return , $names
}
function Read-Protected($row) {
    # B단(보호 열) — 발신 SMTP·이름·수신자·헤더·본문. 실패는 예외로 올린다(부르는 쪽이 R-OMG 로 센다)
    if ($script:W.st) {
        if ($script:W.st.opt.omg -or $script:W.st.opt.omgitem) { throw (New-Object System.UnauthorizedAccessException('omg')) }
        if ($script:W.st.opt.slowb) { Start-Sleep -Milliseconds ([int]($script:W.protSec * 1000) + 300) }
        $x = $row.st
        $to = @($x.to | ForEach-Object { [ordered]@{ addr = $_.addr; name = $_.name } })
        $cc = @($x.cc | ForEach-Object { [ordered]@{ addr = $_.addr; name = $_.name } })
        return @{ sender_addr = $x.sender.addr; sender_name = $x.sender.name; to_list = $to; cc_list = $cc; headers = $x.headers; body_text = $x.body }
    }
    $it = Open-MailItem $row
    $sa = ''
    try { $sa = [string]$it.PropertyAccessor.GetProperty($P_SENDER_SMTP) } catch { }
    if (-not $sa) {
        try { if ([string]$it.SenderEmailType -eq 'EX') { $sa = [string]$it.Sender.GetExchangeUser().PrimarySmtpAddress } else { $sa = [string]$it.SenderEmailAddress } } catch { }
    }
    $to = New-Object System.Collections.Generic.List[object]
    $cc = New-Object System.Collections.Generic.List[object]
    $k = 0
    foreach ($r in $it.Recipients) {
        if ($k -ge $RCPT_MAX) { break }
        $k++
        $addr = ''
        try { $addr = [string]$r.PropertyAccessor.GetProperty($P_SMTP) } catch { }
        if (-not $addr) { try { $addr = [string]$r.Address } catch { } }
        if ($addr -notmatch '@') { $addr = '' }
        $p = [ordered]@{ addr = $(if ($addr) { $addr.ToLower() } else { $null }); name = [string]$r.Name }
        if ([int]$r.Type -eq 2) { $cc.Add($p) } elseif ([int]$r.Type -eq 1) { $to.Add($p) }
    }
    $hd = ''
    try { $hd = [string]$it.PropertyAccessor.GetProperty($P_HEADERS) } catch { }
    $bd = ''
    try { $bd = [string]$it.Body } catch { }
    return @{ sender_addr = $(if ($sa) { $sa.ToLower() } else { $null }); sender_name = [string]$it.SenderName; to_list = $to.ToArray()
              cc_list = $cc.ToArray(); headers = $hd; body_text = $bd }
}

function Connect-Outlook {
    # 붙기(CM §5.2 — LM24 :567-601 이식). 실행 중인데 못 붙으면 대화상자(New-Object 금지). 반환 @{ok; reason}.
    # 세부 단계를 하트비트로 낸다(attach:get → attach:new → attach:ns → attach:inbox) — 부모가 멈춘 단계를 counts.attach_step
    # 에 남겨 회사 PC 에서 프로필 선택·인증·전환 창 중 어디서 멈췄는지 가른다(M365 조사 L6).
    if ($script:W.st) {
        $o = $script:W.st.opt
        Write-Hb 'attach:get' 0
        if ($o.dialog) { return @{ ok = $false; reason = 'R-DIALOG' } }
        if ($o.elev) { return @{ ok = $false; reason = 'R-ELEV' } }
        if ($o.busyall) { return @{ ok = $false; reason = 'R-COM-BUSY' } }
        Write-Hb 'attach:ns' 0
        Write-Hb 'attach:inbox' 0
        if ($o.hang -eq 'attach') { Start-Sleep -Seconds 3600 }
        return @{ ok = $true }
    }
    $running = $false
    try { $running = [bool](Get-Process -Name outlook -ErrorAction SilentlyContinue) } catch { }
    $elevated = $false
    try { $elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } catch { }
    $ol = $null; $hr = 0
    Write-Hb 'attach:get' 0
    for ($i = 1; $i -le 3 -and -not $ol; $i++) {
        try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
        catch {
            $e = $_.Exception
            while ($e.InnerException) { $e = $e.InnerException }
            $hr = $e.HResult
            $ol = $null
        }
        if (-not $ol -and $i -lt 3) { Start-Sleep -Seconds 2; Write-Hb 'attach:get' 0 }
    }
    if ($hr) { $script:W.attachHr = ('0x{0:X8}' -f $hr) }
    if (-not $ol -and $running) {
        if ($hr -eq $RPC_E_CALL_REJECTED) { return @{ ok = $false; reason = 'R-COM-BUSY' } }
        if ($elevated) { return @{ ok = $false; reason = 'R-ELEV' } }
        return @{ ok = $false; reason = 'R-DIALOG' }        # 시작 마법사·프로필 선택·암호 창 — New-Object 를 부르지 않는다
    }
    if (-not $ol) {
        Write-Hb 'attach:new' 0
        try { $ol = New-Object -ComObject Outlook.Application }
        catch {
            $e = $_.Exception
            while ($e.InnerException) { $e = $e.InnerException }
            $script:W.attachHr = ('0x{0:X8}' -f $e.HResult)
            if ($e.HResult -eq $REGDB_E_CLASSNOTREG) { return @{ ok = $false; reason = 'R-WIZARD' } }
            return @{ ok = $false; reason = 'R-TRANSPORT' }
        }
    }
    $script:W.ol = $ol
    Write-Hb 'attach:ns' 0
    $script:W.ns = $ol.GetNamespace('MAPI')
    # Namespace.Logon 은 부르지 않는다 — 문서: 'Outlook 2010 부터 프로필이 여럿이면, 기본 프로필을 쓰도록 했고 Logon 으로 묻지
    # 않고 기본 프로필에 로그온해도 프로필 선택 창이 뜬다. 피하려면 Logon 을 쓰지 말라'. 권장대로 기본 폴더로 MAPI 를 초기화한다(H8).
    Write-Hb 'attach:inbox' 0
    try { [void]$script:W.ns.GetDefaultFolder(6) }
    catch {
        $e = $_.Exception
        while ($e.InnerException) { $e = $e.InnerException }
        $script:W.attachHr = ('0x{0:X8}' -f $e.HResult)
        return @{ ok = $false; reason = 'R-TRANSPORT' }
    }
    return @{ ok = $true }
}
function Get-ComStores {
    $cands = New-Object System.Collections.Generic.List[object]
    $ns = $script:W.ns
    $defStoreId = ''
    try { $defStoreId = [string]$ns.DefaultStore.StoreID } catch { }
    try { $script:W.cached = [bool]$ns.DefaultStore.IsCachedExchange } catch { $script:W.cached = $false }
    foreach ($s in $ns.Stores) {
        $isDef = $false; $xtype = -1
        try { $isDef = ([string]$s.StoreID -eq $defStoreId) } catch { }
        try { $xtype = [int]$s.ExchangeStoreType } catch { }
        if ((Resolve-StoreRole $isDef $xtype) -ne 'primary') { $cands.Add(@{ isDefault = $isDef; xtype = $xtype }); continue }
        $def = @{}
        foreach ($pair in @(@('inbox', 6), @('sent', 5), @('deleted', 3), @('junk', 23), @('drafts', 16), @('outbox', 4), @('conflicts', 19),
                            @('syncissues', 20), @('localfail', 21), @('serverfail', 22), @('rss', 25))) {
            try { $def[$pair[0]] = [string]$s.GetDefaultFolder($pair[1]).EntryID } catch { }
        }
        $root = $null
        try { $root = $s.GetRootFolder() } catch { continue }
        $cands.Add(@{ id = [string]$s.StoreID; root = $root; isDefault = $isDef; xtype = $xtype; defaults = $def })
    }
    return (Select-Stores $cands)
}
function Get-AccountNames {
    # 계정 표시 이름(Account.DisplayName — 보호 목록 밖) 중 주소 꼴인 것. Exchange·M365 계정은 대개 주소가 표시 이름이다.
    # B단을 끈 실행에서도 내 주소를 알기 위해서다(보호 멤버 SmtpAddress·CurrentUser 는 B단에서만 — Get-ProtectedAddrs).
    $out = New-Object System.Collections.Generic.List[string]
    if ($script:W.st) { foreach ($a in $script:W.model.accounts) { $out.Add([string]$a) }; return , $out }
    try { foreach ($a in $script:W.ns.Accounts) { try { $d = ([string]$a.DisplayName).Trim(); if ($d -match $ADDR_RX) { $out.Add($d.ToLower()) } } catch { } } } catch { }
    return , $out
}
function Get-ProtectedAddrs {
    # B단(보호) 내 주소 — Account.SmtpAddress · NameSpace.CurrentUser · ExchangeUser.PrimarySmtpAddress 는 Object Model Guard 보호
    # 멤버다(백신 상태가 정상이 아니거나 정책이 '항상 경고'면 주소록 경고창이 떠 사람이 답할 때까지 멈춘다). readProt 1 이고
    # 'pr_start' 단계(부모의 짧은 워치독) 안에서만 부른다(M365 조사 H6 — 예전에는 B단을 끈 실행도 붙기 단계에서 읽었다).
    $out = New-Object System.Collections.Generic.List[string]
    if ($script:W.st) {
        $o = $script:W.st.opt
        if ($o.omghang) { Start-Sleep -Seconds 3600 }                          # 경고창이 떠 멈춘 것
        if ($o.omg) { throw (New-Object System.UnauthorizedAccessException('omg')) }   # 정책 '자동 거부'
        if (-not $o.noaddr) { $out.Add($script:W.model.me.addr) }
        return , $out
    }
    foreach ($a in $script:W.ns.Accounts) { try { if ($a.SmtpAddress) { $out.Add(([string]$a.SmtpAddress).ToLower()) } } catch { } }
    try {
        $xu = $script:W.ns.CurrentUser.AddressEntry.GetExchangeUser()
        if ($xu -and $xu.PrimarySmtpAddress) { $out.Add(([string]$xu.PrimarySmtpAddress).ToLower()) }
    } catch { }
    return , $out
}
function Get-WorkerAddrs {
    $me = New-Object System.Collections.Generic.List[string]
    foreach ($x in (Get-AccountNames)) { $me.Add($x) }
    if ($script:W.readProt) {
        Write-Hb 'pr_start' 0                       # B단 카나리아 — 부모가 이 단계에만 짧은 워치독을 건다(경고창이면 B단 없이 다시)
        try { foreach ($x in (Get-ProtectedAddrs)) { $me.Add($x) } }
        catch { $script:W.readProt = $false; $script:W.omgCanary = 'denied' }      # 거부 — 이번 실행은 B단 끔 + R-OMG
        Write-Hb 'pr_done' 0
    }
    if ($script:W.owner) { $me.Add($script:W.owner) }
    return @($me | Where-Object { $_ -and $_ -match '@' -and $_.Length -ge 3 } | Select-Object -Unique)
}
function Get-CanaryItem {
    # 필터 카나리아 기준 항목 — 기본 저장소 받은 편지함(비었으면 보낸 편지함)의 가장 최근 항목 시각(UTC)
    $w = $script:W
    if ($w.st) {
        foreach ($k in @('inbox', 'sent')) {
            $t = $null
            foreach ($it in $w.model.folders[$k].Items) { $t = Get-MaxDate $t $it.t }
            if ($t) { return @{ fd = @{ node = $w.model.folders[$k]; sent = ($k -eq 'sent'); store = 'ST-STORE-1' }; t = $t } }
        }
        return $null
    }
    $defId = ''
    try { $defId = [string]$w.ns.DefaultStore.StoreID } catch { }
    foreach ($pair in @(@(6, $false, '[ReceivedTime]'), @(5, $true, '[SentOn]'))) {
        try {
            $node = $w.ns.GetDefaultFolder($pair[0])
            $items = $node.Items
            $items.Sort($pair[2], $true)                                        # 내림차순 — 맨 앞이 가장 최근
            $first = $items.GetFirst()
            if ($first) {
                $loc = $first.ReceivedTime; if ($pair[1]) { $loc = $first.SentOn }
                return @{ fd = @{ node = $node; sent = $pair[1]; store = $defId }; t = (ConvertTo-UtcFromLocal ([datetime]$loc)) }
            }
        } catch { }
    }
    return $null
}
function Select-DaslFormat {
    # 필터 카나리아(M365 조사 H9): 기준 항목 시각 T 로 [T−2분, T+2분) 을 형식마다 걸어 그 항목이 실제로 돌아오는 첫 형식을
    # 이 실행의 형식으로 쓴다. 항목이 하나도 없으면 'none'(문서 순서 + 예외 대체), 모두 못 맞히면 'fail'.
    $w = $script:W
    Write-Hb 'canary' 0
    $c = Get-CanaryItem
    if (-not $c) { $w.canary = 'none'; return }
    foreach ($f in $DASL_FORMATS) {
        Write-Hb 'canary' 0
        $rows = Read-FolderRowsFmt $c.fd ($c.t.AddMinutes(-$CANARY_MIN)) ($c.t.AddMinutes($CANARY_MIN)) $f 50
        if ($null -eq $rows) { continue }
        foreach ($r in $rows) {
            if ([math]::Abs(($r.t - $c.t).TotalSeconds) -le $CANARY_TOL_SEC) { $w.daslFmt = $f; $w.canary = 'ok'; return }
        }
    }
    $w.canary = 'fail'
}
function Get-FolderNewest($fd) {
    if ($script:W.st) {
        $t = $null
        foreach ($it in $fd.node.Items) { $t = Get-MaxDate $t $it.t }
        return $t
    }
    try {
        $items = $fd.node.Items
        $field = '[ReceivedTime]'; if ($fd.sent) { $field = '[SentOn]' }
        $items.Sort($field, $true)
        $first = $items.GetFirst()
        if ($first) {
            $loc = $first.ReceivedTime; if ($fd.sent) { $loc = $first.SentOn }
            return (ConvertTo-UtcFromLocal ([datetime]$loc))
        }
    } catch { }
    return $null
}
function Get-MailHorizon($folders) {
    # 가장 오래된·가장 최근 메일(기본 저장소 받은·보낸 편지함) — 캐시 동기화 기간(지평선)·OST 신선도 판정용. 폴더마다 하트비트(M14)
    $min = $null; $max = $null
    foreach ($fd in $folders) {
        if ($fd.role -notin @('inbox', 'sent')) { continue }
        Write-Hb 'horizon' 0
        if ($script:W.st) {
            foreach ($it in $fd.node.Items) { $min = Get-MinDate $min $it.t; $max = Get-MaxDate $max $it.t }
            continue
        }
        try {
            $items = $fd.node.Items
            $field = '[ReceivedTime]'; if ($fd.sent) { $field = '[SentOn]' }
            $items.Sort($field, $false)
            $first = $items.GetFirst()
            if ($first) {
                $loc = $first.ReceivedTime; if ($fd.sent) { $loc = $first.SentOn }
                $min = Get-MinDate $min (ConvertTo-UtcFromLocal ([datetime]$loc))
            }
            $last = $items.GetLast()
            if ($last) {
                $loc = $last.ReceivedTime; if ($fd.sent) { $loc = $last.SentOn }
                $max = Get-MaxDate $max (ConvertTo-UtcFromLocal ([datetime]$loc))
            }
        } catch { }
    }
    return @{ oldest = $min; newest = $max }
}
function Test-OstStale($newest, $folders, $res) {
    # OST 신선도(M365 조사 H10): 캐시 모드인데 받은·보낸 편지함의 가장 최근 메일이 probe.ostStaleH 시간보다 오래됐으면 그 시각
    # 뒤의 날을 '메일 0건'으로 굳히지 않는다(상태 줄 horizon_newest + R-STALE → 원장 out_of_horizon → 웹 경로가 채움). 문서:
    # 캐시 범위 밖 항목은 서버에만 있고, 색인은 Outlook 이 떠 있을 때만 갱신된다. 이 수집이 Outlook 을 띄웠으면 캐시 모드
    # Outlook 이 서버와 맞추는 동안 잠깐(하트비트를 내며) 기다린다. 보내기/받기(SyncObject.Start)는 부르지 않는다 — 보낼
    # 편지함의 메일까지 보내는 사용자 동작이라 읽기 전용 원칙에 어긋난다. 반환 = 낡았으면 그 최신 시각(UTC), 아니면 $null.
    $w = $script:W
    if (-not $newest -or -not $w.cached -or [double]$w.staleH -le 0) { return $null }
    $ageH = ($w.nowUtc - $newest).TotalHours
    if ($ageH -gt $w.staleH -and $w.olStarted -and $w.syncWait -gt 0) {
        $t0 = $script:Clock.Elapsed.TotalSeconds
        $step = 5; if ($w.st) { $step = 1 }
        $news = @($folders | Where-Object { $_.role -in @('inbox', 'sent') })
        while (($script:Clock.Elapsed.TotalSeconds - $t0) -lt $w.syncWait) {
            Start-Sleep -Seconds $step
            Write-Hb 'sync' 0
            if ($w.st) { Update-StSync }
            foreach ($fd in $news) { $newest = Get-MaxDate $newest (Get-FolderNewest $fd) }
            $ageH = ($w.nowUtc - $newest).TotalHours
            if ($ageH -le $w.staleH) { break }
        }
        $res.counts['sync_wait_s'] = [int][math]::Round($script:Clock.Elapsed.TotalSeconds - $t0)
    }
    $res.counts['newest_age_h'] = [int][math]::Floor($ageH)
    if ($ageH -le $w.staleH) { return $null }
    Add-Reason $res 'R-STALE'
    $res.horizon_newest = (ConvertTo-LocalFromUtc $newest).ToString('yyyy-MM-dd', $script:Inv)
    return $newest
}

function Invoke-MailKind {
    $w = $script:W
    $res = New-Result 'mail.com'
    $w.results['mail.com'] = $res
    if ($w.canary -eq 'fail') {
        # 필터 카나리아 실패 — 이 PC 의 Outlook 이 받는 DASL 날짜 형식을 찾지 못했다. 0건을 '그 달 메일 없음'으로 굳히지 않도록
        # 아무 달도 적지 않고 수송 실패로 끝낸다(원장 미관측 → 색인·웹 경로가 채운다, M365 조사 H9)
        Add-Reason $res 'R-TRANSPORT'
        $res.rc = 3
        return
    }
    if ($w.my.Count -eq 0) { Add-Reason $res 'R-NOADDR' }
    $cur = Get-SrcCursor $w.in 'mail.com' $w.mixed
    $covIn = Get-CovIn $cur
    $box = [ordered]@{}
    foreach ($b in @('inbox', 'sent', 'other')) {
        $last = $null
        if ($cur -and $cur.PSObject.Properties['box'] -and $cur.box -and $cur.box.PSObject.Properties[$b] -and $cur.box.$b) { $last = ConvertFrom-UtcText $cur.box.$b.last_ts_utc }
        $box[$b] = $last
    }
    $covOut = @{}
    foreach ($k in $covIn.Keys) { $covOut[$k] = $covIn[$k] }
    $folders = Get-MailFolders
    $hz = Get-MailHorizon $folders
    $horizon = $hz.oldest
    if ($horizon) { $res.horizon_oldest = (ConvertTo-LocalFromUtc $horizon).ToString('yyyy-MM-dd', $script:Inv) }
    $stale = Test-OstStale $hz.newest $folders $res
    $refreshFrom = $w.nowUtc.AddDays(-$MAIL_REFRESH_DAYS)
    $emitted = 0; $nNew = 0; $seen = 0; $nSub = 0; $nSkipCls = 0; $nResp = 0; $nAtt = 0; $bFail = 0; $bCons = 0; $bOn = $w.readProt
    $stop = $null; $monthsRead = 0; $monthsSkipped = 0; $monthsHeld = 0; $hb = 0
    foreach ($m in $w.months) {
        $prior = $covIn[$m.key]
        if ($horizon -and $m.hi -le $horizon) {
            $covOut[$m.key] = @{ status = 'out_of_horizon'; read_from = $null; read_to = $null }
            Add-Reason $res 'R-HORIZON'
            continue
        }
        # 지평선이 걸친 달(M365 조사 M15): 지평선 앞은 캐시에 없다(서버에만) — 지평선 뒤만 읽고 그 달은 적지 않는다(원장이 날마다)
        $straddle = [bool]($horizon -and $m.lo -lt $horizon)
        $rr = Get-ReadRange $m $prior $refreshFrom 1
        if ($rr -and $straddle -and $rr.lo -lt $horizon) { $rr = @{ lo = $horizon; hi = $rr.hi } }
        if (-not $rr -or $rr.hi -le $rr.lo) { $monthsSkipped++; continue }
        if (Test-Budget $w.mailBudget) { $stop = 'budget'; break }
        $mis0 = $w.mismatch
        $sentRows = New-Object System.Collections.Generic.List[object]
        $otherRows = New-Object System.Collections.Generic.List[object]
        foreach ($fd in $folders) {
            $rows = Read-FolderRows $fd $rr.lo $rr.hi
            foreach ($r in $rows) { if ($fd.sent) { $sentRows.Add($r) } else { $otherRows.Add($r) } }
            $hb++; Write-Hb 'read' $emitted
        }
        $ordered = @(@($sentRows | Sort-Object { $_.t } -Descending) + @($otherRows | Sort-Object { $_.t } -Descending))
        $oldestOther = $null; $inOther = $false
        foreach ($r in $ordered) {
            if ($null -eq $r) { continue }
            if (-not $r.fd.sent) { $inOther = $true }
            if ($emitted -ge $w.capMail) { $stop = 'cap'; break }
            if (Test-Budget $w.mailBudget) { $stop = 'budget'; break }
            if ($w.st -and $w.st.opt.delay) { Start-Sleep -Milliseconds ([int]$w.st.opt.delay) }
            $seen++
            $cls = [string]$r.cls
            if (-not (($cls -match '^IPM\.Note' -and $cls -notmatch '^IPM\.Note\.Rules') -or $cls -match '^IPM\.Schedule\.Meeting\.')) { $nSkipCls++; continue }
            if ($cls -match $IM_CLASS_RX) { $nSkipCls++; continue }            # IM 대화록·부재중 대화 클래스(CM §5.3 — 메일 아님)
            $rec = [ordered]@{}
            if ($r.imid) { $rec['internet_message_id'] = [string]$r.imid }
            if ($r.convid) { $rec['conversation_id'] = [string]$r.convid }
            $rec['conversation_topic'] = [string]$r.topic
            $rec['box'] = $r.fd.box
            $rec['folder_role'] = $r.fd.role
            if ($bOn) {
                $t0 = $script:Clock.Elapsed.TotalSeconds
                $bp = $null
                try { $bp = Read-Protected $r; $bCons = 0 } catch { $bp = $null; $bFail++; $bCons++; Add-Reason $res 'R-OMG' }
                if (($script:Clock.Elapsed.TotalSeconds - $t0) -gt $w.protSec) { $bOn = $false; Add-Reason $res 'R-OMG'; $res.counts['omg_slow'] = $true }
                if ($bCons -ge 3) { $bOn = $false }
                if ($bp) {
                    if ($bp.sender_addr) { $rec['sender_addr'] = $bp.sender_addr }
                    if ($bp.sender_name) { $rec['sender_name'] = $bp.sender_name }
                    $rec['to'] = @($bp.to_list)
                    $rec['cc'] = @($bp.cc_list)
                    if ($bp.headers) { $h = [string]$bp.headers; if ($h.Length -gt $HEADERS_MAX) { $h = $h.Substring(0, $HEADERS_MAX) }; $rec['headers_text'] = $h }
                    $bw = Get-BodyWindow ([string]$bp.body_text)
                    if ($bw) { $rec['body_text'] = $bw }
                }
            }
            $rec['subject'] = [string]$r.subject
            if ($r.hasatt) {
                $names = Read-AttachNames $r
                if ($names.Count) { $rec['attach_names'] = @($names); $nAtt++ }
            }
            $rec['has_attach'] = [bool]$r.hasatt
            $rec['sensitivity'] = [int]$r.sens
            $rec['categories'] = @(Split-Cats ([string]$r.cats))
            $imp = [int]$r.imp; if ($imp -lt 0 -or $imp -gt 2) { $imp = 1 }
            $rec['importance'] = $imp
            $rec['in_reply_to'] = [bool]$r.inreply
            $rec['ts_utc'] = Format-Utc $r.t
            $rec['ts_local_offset'] = Format-Offset $r.t
            $rec['ts_precision'] = 'minute'
            $rec['observed_at'] = $w.nowIso
            $rec['confidence'] = 1.0
            $fl = [ordered]@{}
            if ($r.fd.sent -and $cls -match '^IPM\.Schedule\.Meeting\.Resp\.') { $fl['meeting_response'] = $true; $nResp++ }
            if ($r.utcSuspect) { $fl['utc_suspect'] = $true }
            if ($fl.Count) { $rec['flags'] = $fl }
            Write-Rec $rec 'mail'
            $emitted++
            if ($r.fd.role -eq 'subfolder') { $nSub++ }
            $isNew = -not ($prior -and $prior.status -in @('done', 'partial') -and $prior.read_from -and $prior.read_to -and $r.t -ge $prior.read_from -and $r.t -lt $prior.read_to)
            if ($isNew) { $nNew++ }
            $bk = [string]$r.fd.box
            if (-not $box.Contains($bk)) { $bk = 'other' }
            $box[$bk] = Get-MaxDate $box[$bk] $r.t
            if ($inOther) { $oldestOther = Get-MinDate $oldestOther $r.t }
            if (($emitted % $HB_EVERY) -eq 0) { Write-Hb 'read' $emitted }
            if ($w.st -and $w.st.opt.hang -eq 'read' -and $monthsRead -ge 1) { Start-Sleep -Seconds 3600 }
        }
        # 이 달을 적지 않는 경우: 지평선이 걸침 · OST 최신 시각 뒤 날이 듦(낡음) · 필터가 범위 밖 행을 돌려줌 — 다음 실행이
        # 다시 읽고, 원장은 상태 줄 horizon_oldest·horizon_newest 로 날마다 판정한다(0건 날을 zero_ok 로 굳히지 않는다)
        $hold = $straddle -or ($stale -and $m.hi -gt $stale) -or ($w.mismatch -gt $mis0)
        if ($straddle) { Add-Reason $res 'R-HORIZON'; $res.counts['horizon_month'] = $m.key }
        if ($stop) {
            if ($hold) { [void]$covOut.Remove($m.key) }
            elseif ($inOther -and $oldestOther) { $covOut[$m.key] = Merge-Cov $prior $oldestOther $rr.hi $m; $covOut[$m.key].status = 'partial' }
            Write-MailCursor $box $covOut
            break
        }
        if ($hold) { [void]$covOut.Remove($m.key); $monthsHeld++ } else { $covOut[$m.key] = Merge-Cov $prior $rr.lo $rr.hi $m }
        $monthsRead++
        Write-MailCursor $box $covOut
    }
    if (-not $stop) { Write-MailCursor $box $covOut }
    $res.items_total = $seen
    $res.items_ok = $emitted
    $res.new = $nNew
    if ($stop -eq 'cap') { $res.cap_hit = $true; Add-Reason $res 'R-CAP' }
    if ($stop -eq 'budget') { $res.budget_hit = $true; Add-Reason $res 'R-BUDGET' }
    if ($emitted -gt 0) { $res.subfolder_ratio = [math]::Round($nSub / $emitted, 4) }
    if ($null -ne $w.subRatio -and $null -ne $res.subfolder_ratio -and $res.subfolder_ratio -ge [double]$w.subRatio) { Add-Reason $res 'R-SUBFOLDER' }
    $res.counts['months_read'] = $monthsRead
    $res.counts['months_skipped'] = $monthsSkipped
    $res.counts['months_held'] = $monthsHeld
    $res.counts['folders'] = $folders.Count
    $res.counts['folders_seen'] = $w.foldersSeen
    $res.counts['folders_capped'] = [bool]$w.foldersCapped
    $res.counts['excluded_folders'] = $w.excluded
    $res.counts['empty_folders'] = $w.emptyFolders
    $res.counts['skipped_class'] = $nSkipCls
    $res.counts['meeting_response'] = $nResp
    $res.counts['with_attach_names'] = $nAtt
    $res.counts['protected_fail'] = $bFail
    $res.counts['protected_read'] = [bool]$w.readProt
    $res.counts['table_errors'] = $w.tableErrors
    $res.counts['filter_mismatch'] = $w.mismatch
    if ($nNew -gt 0 -or $stop) { $res.rc = 0 }
    elseif ($emitted -gt 0 -or $monthsSkipped -gt 0) { $res.rc = 4 }
    else { $res.rc = 1 }
}
function Write-MailCursor($box, $covOut) {
    $b = [ordered]@{}
    foreach ($k in $box.Keys) {
        $v = $null; if ($box[$k]) { $v = Format-Utc $box[$k] }
        $b[$k] = [ordered]@{ last_ts_utc = $v; last_msg_key = $null }
    }
    $c = [ordered]@{ box = $b; cov_months = (ConvertTo-CovJson $covOut) }
    Write-OutLine ('{"_cur":{"src":"mail.com","cursor":' + (ConvertTo-J $c) + '}}')
}

function Invoke-CalKind {
    $w = $script:W
    $res = New-Result 'cal.com'
    $w.results['cal.com'] = $res
    $cur = Get-SrcCursor $w.in 'cal.com' $w.mixed
    $covIn = Get-CovIn $cur
    $last = $null
    if ($cur -and $cur.PSObject.Properties['last_start_utc']) { $last = ConvertFrom-UtcText $cur.last_start_utc }
    $covOut = @{}
    foreach ($k in $covIn.Keys) { $covOut[$k] = $covIn[$k] }
    $refreshFrom = $w.nowUtc.AddDays(-$CAL_REFRESH_DAYS)
    $emitted = 0; $nNew = 0; $seen = 0; $stop = $null; $monthsRead = 0; $monthsSkipped = 0; $nCancel = 0; $nRec = 0; $bOn = $w.readProt; $bFail = 0
    foreach ($m in $w.months) {
        $prior = $covIn[$m.key]
        $rr = Get-ReadRange $m $prior $refreshFrom 1
        if (-not $rr) { $monthsSkipped++; continue }
        if (Test-Budget $w.calBudget) { $stop = 'budget'; break }
        $entries = Get-CalEntries $rr.lo $rr.hi
        $lastRead = $null
        foreach ($en in $entries) {
            if ($emitted -ge $w.capCal) { $stop = 'cap'; break }
            if (Test-Budget $w.calBudget) { $stop = 'budget'; break }
            if ($w.st -and $w.st.opt.delay) { Start-Sleep -Milliseconds ([int]$w.st.opt.delay) }
            # 앞 달에서 시작한 회의는 그 달이 낸다(경계 중복 방지) — 기간 첫 달만 창과 겹치는 앞선 시작을 받는다(L5)
            if (-not (($en.s -ge $rr.lo) -or ($m.first -and $en.e -gt $rr.lo))) { continue }
            $rec = Convert-CalItem $en.it ([ref]$bOn) ([ref]$bFail) $res
            if ($null -eq $rec) { continue }
            $s = $rec['_s']; $rec.Remove('_s')
            $seen++
            if ($rec['meeting_status'] -in @(5, 7)) { $nCancel++ }
            if ($rec['is_recurring']) { $nRec++ }
            Write-Rec $rec 'cal'
            $emitted++
            $isNew = -not ($prior -and $prior.status -in @('done', 'partial') -and $prior.read_from -and $prior.read_to -and $s -ge $prior.read_from -and $s -lt $prior.read_to)
            if ($isNew) { $nNew++ }
            if ($s -le $w.nowUtc) { $last = Get-MaxDate $last $s }
            $lastRead = $s
            if (($emitted % $HB_EVERY) -eq 0) { Write-Hb 'read' $emitted }
        }
        Write-Hb 'read' $emitted
        if ($stop) {
            if ($lastRead) { $covOut[$m.key] = Merge-Cov $prior $rr.lo $lastRead $m; $covOut[$m.key].status = 'partial' }
            Write-CalCursor $last $covOut
            break
        }
        $covOut[$m.key] = Merge-Cov $prior $rr.lo $rr.hi $m
        $monthsRead++
        Write-CalCursor $last $covOut
    }
    if (-not $stop) { Write-CalCursor $last $covOut }
    $res.items_total = $seen
    $res.items_ok = $emitted
    $res.new = $nNew
    if ($stop -eq 'cap') { $res.cap_hit = $true; Add-Reason $res 'R-CAP' }
    if ($stop -eq 'budget') { $res.budget_hit = $true; Add-Reason $res 'R-BUDGET' }
    $res.counts['months_read'] = $monthsRead
    $res.counts['months_skipped'] = $monthsSkipped
    $res.counts['cancelled'] = $nCancel
    $res.counts['recurring_occurrences'] = $nRec
    $res.counts['protected_fail'] = $bFail
    $res.counts['protected_read'] = [bool]$w.readProt
    $res.counts['cal_out_of_range'] = $w.calOutOfRange
    if ($nNew -gt 0 -or $stop) { $res.rc = 0 }
    elseif ($emitted -gt 0 -or $monthsSkipped -gt 0) { $res.rc = 4 }
    else { $res.rc = 1 }
}
function Get-CalJet([datetime]$lo, [datetime]$hi) {
    # Jet 필터(로컬 시각, 현재 로캘의 짧은 날짜·시각 'g' — 문서 예제와 같은 꼴) — Outlook 의 회차 전개(IncludeRecurrences)는
    # 이 꼴에서 확실하다. 로캘이 어긋나면 0건일 수 있으므로 DASL 결과와 합집합으로만 쓴다(CM §5.5 · LM24 'g' 결함 보완).
    $cc = [Globalization.CultureInfo]::CurrentCulture
    $a = (ConvertTo-LocalFromUtc $lo).ToString('g', $cc)
    $b = (ConvertTo-LocalFromUtc $hi).ToString('g', $cc)
    return ("[Start] < '{0}' AND [End] > '{1}'" -f $b, $a)
}
function Get-StCalItems([string]$mode, [datetime]$lo, [datetime]$hi, [string]$fmt) {
    # 시험 모델의 Restrict 흉내 — DASL 은 받는 날짜 형식만 이해하고 반복 회차를 전개하지 않는다(실물의 비관적 가정),
    # Jet 은 현재 로캘 'g' 문자열(로컬)을 이해하고 회차를 전개한다(선택 jetfail = 로캘 불일치로 0건, recurleak = 창 앞에서
    # 시작해 창과 겹치지 않는 회차도 함께 돌려줌 — 문서는 DASL·IncludeRecurrences 의 전개 범위를 정하지 않는다).
    $out = New-Object System.Collections.Generic.List[object]
    $w = $script:W
    if ($mode -eq 'dasl') {
        $win = Get-StDaslWindow (Get-CalDasl $lo $hi $fmt)
        if ($null -eq $win) { return , $out }
        $b = $win[0]; $a = $win[1]
        foreach ($it in $w.model.folders['calendar'].Items) { if (-not $it.IsRecurring -and $it.s -lt $b -and $it.e -gt $a) { $out.Add($it) } }
        return , $out
    }
    if ($w.st.opt.jetfail) { return , $out }
    $lits = [regex]::Matches((Get-CalJet $lo $hi), "'([^']+)'")
    if ($lits.Count -ne 2) { return , $out }
    $cc = [Globalization.CultureInfo]::CurrentCulture
    $b = ConvertTo-UtcFromLocal ([datetime]::Parse($lits[0].Groups[1].Value, $cc))
    $a = ConvertTo-UtcFromLocal ([datetime]::Parse($lits[1].Groups[1].Value, $cc))
    foreach ($it in $w.model.folders['calendar'].Items) {
        if ($it.s -lt $b -and $it.e -gt $a) { $out.Add($it) }
        elseif ($w.st.opt.recurleak -and $it.IsRecurring -and $it.s -lt $a -and $it.s -ge $a.AddDays(-7)) { $out.Add($it) }
    }
    return , $out
}
function Get-CalEntries([datetime]$lo, [datetime]$hi) {
    # 그 범위와 겹치는 일정(회차 포함) — DASL 과 Jet 결과의 합집합, 시작 오름차순. 키 = GlobalAppointmentID·시작·끝.
    # 창과 겹치지 않는 회차(끝 ≤ lo · 시작 ≥ hi)는 버린다(counts.cal_out_of_range — L5). DASL 날짜 형식은 필터 카나리아가
    # 고른 것(없으면 문서 순서 + 예외 대체), 카나리아가 실패한 PC 는 DASL 을 건너뛰고 Jet 만.
    $w = $script:W
    $seen = @{}
    $list = New-Object System.Collections.Generic.List[object]
    $guard = [int]$w.capCal * 3 + 100                                  # 깨진 반복(끝 없는 회차) 가드
    $fmts = $DASL_FORMATS; if ($w.daslFmt) { $fmts = @($w.daslFmt) }
    foreach ($mode in @('dasl', 'jet')) {
        if ($mode -eq 'dasl' -and $w.canary -eq 'fail') { continue }
        if ($w.st) {
            $src = $null
            if ($mode -eq 'jet') { $src = Get-StCalItems 'jet' $lo $hi '' }
            else { foreach ($f in $fmts) { $src = Get-StCalItems 'dasl' $lo $hi $f; if ($src.Count) { break } } }
            foreach ($x in $src) {
                if ($x.e -le $lo -or $x.s -ge $hi) { $w.calOutOfRange++; continue }
                $key = '{0}|{1}|{2}' -f $x.GlobalAppointmentID, $x.s.Ticks, $x.e.Ticks
                if (-not $seen.ContainsKey($key)) { $seen[$key] = 1; $list.Add(@{ s = $x.s; e = $x.e; it = $x }) }
            }
            continue
        }
        try {
            $citems = $w.ns.GetDefaultFolder(9).Items
            # 문서(Items.IncludeRecurrences): 반복 일정을 정렬·필터하려면 '시작 오름차순 정렬 → IncludeRecurrences=True → 필터' 순서
            $citems.Sort('[Start]')
            $citems.IncludeRecurrences = $true
            $sel = $null
            if ($mode -eq 'dasl') {
                foreach ($f in $fmts) { try { $sel = $citems.Restrict((Get-CalDasl $lo $hi $f)); break } catch { $sel = $null } }
            } else {
                try { $sel = $citems.Restrict((Get-CalJet $lo $hi)) } catch { $sel = $null }
            }
            if ($null -eq $sel) { $w.tableErrors++; continue }
            $it = $sel.GetFirst()
            $n = 0
            while ($null -ne $it) {
                $n++
                if ($n -gt $guard) { break }
                $s = $null; $e = $null; $gaid = ''
                try {
                    $s = [DateTime]::SpecifyKind([datetime]$it.StartUTC, 'Utc'); $e = [DateTime]::SpecifyKind([datetime]$it.EndUTC, 'Utc')
                    $gaid = [string]$it.GlobalAppointmentID
                } catch { $s = $null }
                if ($null -ne $s) {
                    if ($s -ge $hi) { break }
                    if ($e -le $lo) { $w.calOutOfRange++ }
                    else {
                        $tag = ''; if (-not $gaid) { try { $tag = [string]$it.Subject } catch { } }
                        $key = '{0}|{1}|{2}|{3}' -f $gaid, $s.Ticks, $e.Ticks, $tag.GetHashCode()
                        if (-not $seen.ContainsKey($key)) { $seen[$key] = 1; $list.Add(@{ s = $s; e = $e; it = $it }) }
                    }
                }
                if (($n % $HB_EVERY) -eq 0) { Write-Hb 'read' $n }
                $it = $sel.GetNext()
            }
        } catch { $w.tableErrors++ }
    }
    return , @($list | Sort-Object { $_.s })
}
function Convert-CalItem($it, [ref]$bOn, [ref]$bFail, $res) {
    $w = $script:W
    if ($w.st) {
        $s = $it.s; $e = $it.e
        $h = @{ Subject = $it.Subject; AllDayEvent = $it.AllDayEvent; BusyStatus = $it.BusyStatus; Categories = $it.Categories
                Sensitivity = $it.Sensitivity; GlobalAppointmentID = $it.GlobalAppointmentID; ResponseStatus = $it.ResponseStatus
                MeetingStatus = $it.MeetingStatus; Location = $it.Location; IsRecurring = $it.IsRecurring }
    } else {
        try {
            $s = [DateTime]::SpecifyKind([datetime]$it.StartUTC, 'Utc'); $e = [DateTime]::SpecifyKind([datetime]$it.EndUTC, 'Utc')
            $h = @{ Subject = [string]$it.Subject; AllDayEvent = [bool]$it.AllDayEvent; BusyStatus = [int]$it.BusyStatus; Categories = [string]$it.Categories
                    Sensitivity = [int]$it.Sensitivity; GlobalAppointmentID = [string]$it.GlobalAppointmentID; ResponseStatus = [int]$it.ResponseStatus
                    MeetingStatus = [int]$it.MeetingStatus; Location = [string]$it.Location; IsRecurring = [bool]$it.IsRecurring }
        } catch { return $null }
    }
    if ($e -lt $s) { $e = $s }
    $rec = [ordered]@{}
    $rec['_s'] = $s
    if ($h.GlobalAppointmentID) { $rec['global_appointment_id'] = [string]$h.GlobalAppointmentID }
    $rec['start_utc'] = Format-Utc $s
    $rec['end_utc'] = Format-Utc $e
    $rec['subject'] = [string]$h.Subject
    $online = ([string]$h.Location -match $ONLINE_RX)
    if ($bOn.Value) {
        $t0 = $script:Clock.Elapsed.TotalSeconds
        try {
            if ($w.st) {
                if ($w.st.opt.omg -or $w.st.opt.omgitem) { throw (New-Object System.UnauthorizedAccessException('omg')) }
                $org = [ordered]@{ addr = $it.organizer.addr; name = $it.organizer.name }
                $att = @($it.attendees | ForEach-Object { [ordered]@{ addr = $_.addr; name = $_.name } })
                $body = [string]$it.body
            } else {
                $org = $null
                $att = New-Object System.Collections.Generic.List[object]
                $k = 0
                foreach ($r in $it.Recipients) {
                    if ($k -ge $RCPT_MAX) { break }
                    $k++
                    $addr = ''
                    try { $addr = [string]$r.PropertyAccessor.GetProperty($P_SMTP) } catch { }
                    if (-not $addr) { try { $addr = [string]$r.Address } catch { } }
                    if ($addr -notmatch '@') { $addr = '' }
                    $p = [ordered]@{ addr = $(if ($addr) { $addr.ToLower() } else { $null }); name = [string]$r.Name }
                    if ([int]$r.Type -eq 0) { $org = $p } else { $att.Add($p) }          # olOrganizer = 0
                }
                if (-not $org) { try { $org = [ordered]@{ addr = $null; name = [string]$it.Organizer } } catch { } }
                $att = $att.ToArray()
                $body = ''
                try { $body = [string]$it.Body } catch { }
            }
            if ($org) { $rec['organizer'] = $org }
            $rec['attendees'] = @($att)
            if ($body) {
                $bt = $body.Trim(); if ($bt.Length -gt $BODY_HEAD) { $bt = $bt.Substring(0, $BODY_HEAD) }
                $rec['body_text'] = $bt
                if ($body -match $ONLINE_RX) { $online = $true }
            }
        } catch { $bFail.Value++; Add-Reason $res 'R-OMG'; if ($bFail.Value -ge 3) { $bOn.Value = $false } }
        if (($script:Clock.Elapsed.TotalSeconds - $t0) -gt $w.protSec) { $bOn.Value = $false; Add-Reason $res 'R-OMG' }
    }
    $busy = 'busy'
    if ($BUSY_OF.ContainsKey([int]$h.BusyStatus)) { $busy = $BUSY_OF[[int]$h.BusyStatus] }
    $rec['busy_status'] = $busy
    $resp = [int]$h.ResponseStatus; if ($resp -lt 0 -or $resp -gt 5) { $resp = 0 }
    $rec['response_status'] = $resp
    $ms = [int]$h.MeetingStatus; if ($ms -lt 0 -or $ms -gt 7) { $ms = 0 }
    $rec['meeting_status'] = $ms
    if ($h.Location) { $rec['location'] = [string]$h.Location }
    $rec['is_recurring'] = [bool]$h.IsRecurring
    $rec['all_day'] = [bool]$h.AllDayEvent
    $rec['online'] = [bool]$online
    $rec['sensitivity'] = [int]$h.Sensitivity
    $rec['categories'] = @(Split-Cats ([string]$h.Categories))
    $rec['ts_local_offset'] = Format-Offset $s
    $rec['ts_precision'] = $(if ($h.AllDayEvent) { 'date' } else { 'minute' })
    $rec['observed_at'] = $w.nowIso
    $rec['confidence'] = 1.0
    if ($resp -eq 1) { $rec['flags'] = [ordered]@{ organizer_me = $true } }
    return $rec
}
function Write-CalCursor($last, $covOut) {
    $v = $null; if ($last) { $v = Format-Utc $last }
    $c = [ordered]@{ last_start_utc = $v; cov_months = (ConvertTo-CovJson $covOut) }
    Write-OutLine ('{"_cur":{"src":"cal.com","cursor":' + (ConvertTo-J $c) + '}}')
}

function Invoke-Worker($a) {
    $script:W = @{ in = $a.in; mixed = $a.mixed; st = $a.st; readProt = ($a.readProt -eq 1); protSec = $a.protSec; owner = $a.owner
                   capMail = $a.capMail; capCal = $a.capCal; includeArchive = $a.includeArchive; subRatio = $a.subRatio
                   nowUtc = $a.nowUtc; nowLocal = $a.nowLocal; nowIso = (Format-Utc $a.nowUtc); sinceLocal = $a.sinceLocal
                   untilLocal = $a.untilLocal; months = (Get-Months $a.sinceLocal $a.untilLocal); results = [ordered]@{}; excluded = 0
                   emptyFolders = 0; tableErrors = 0; mismatch = 0; calOutOfRange = 0; foldersSeen = 0; foldersCapped = $false
                   storeSkip = @{}; ol = $null; ns = $null; model = $null; stores = $null; my = @(); attachHr = $null
                   daslFmt = $null; canary = 'none'; omgCanary = $null; cached = $true; olStarted = ($a.olState -eq 'started')
                   staleH = [double]$a.staleH; syncWait = $STALE_SYNC_WAIT_SEC; daslOk = @($DASL_FORMATS); daslShift = 0
                   t0 = $script:Clock.Elapsed.TotalSeconds }
    if ($a.st) {
        $script:W.st = @{ opt = $a.st.opt; opt_n = $a.st.n }
        $o = $a.st.opt
        if ($o.daslok) { $script:W.daslOk = @(([string]$o.daslok).Split('+') | Where-Object { $_ }) }
        if ($o.daslshift) { $script:W.daslShift = [int]$o.daslshift }
        if ($o.syncwait) { $script:W.syncWait = [int]$o.syncwait }
        $script:W.cached = -not $o.online
    }
    $kinds = $a.kinds
    # 예산: 일정은 절반까지, 메일은 전체 예산 안에서(혼합이면 일정 다음 남은 시간)
    $script:W.calBudget = [double]$a.budget / 2
    $script:W.mailBudget = [double]$a.budget
    Write-Hb 'attach' 0
    try {
        $att = Connect-Outlook
        if (-not $att.ok) {
            foreach ($k in $kinds) {
                $src = $(if ($k -eq 'mail') { 'mail.com' } else { 'cal.com' })
                $r = New-Result $src; Add-Reason $r $att.reason; $r.counts['attach'] = 'failed'; $r.rc = 3
                if ($script:W.attachHr) { $r.counts['attach_hr'] = $script:W.attachHr }
                Write-OutLine ('{"_wres":' + (ConvertTo-ResultJson $r) + '}')
            }
            return 3
        }
        Write-Hb 'attach:stores' 0
        if ($script:W.st) {
            $script:W.model = New-SelfModel $script:W.st $script:W
            $script:W.stores = Select-Stores $script:W.model.cands
        } else {
            $script:W.stores = Get-ComStores
        }
        $script:W.my = @(Get-WorkerAddrs)
        Write-OutLine ('{"_meta":{"my_addrs":' + (ConvertTo-J ([object[]]$script:W.my)) + '}}')
        Select-DaslFormat
        Write-Hb 'read' 0
        foreach ($k in $kinds) {
            if ($k -eq 'cal') { Invoke-CalKind } else { Invoke-MailKind }
        }
        foreach ($k in $script:W.results.Keys) {
            $r = $script:W.results[$k]
            $r.counts['filter_canary'] = $script:W.canary
            $r.counts['filter_fmt'] = $script:W.daslFmt
            $r.counts['stores_non_exchange'] = [int]$script:W.storeSkip['non_exchange']
            $r.counts['stores_other'] = [int]$script:W.storeSkip['other']
            if ($script:W.includeArchive) { $r.counts['archive_store'] = 'unverified' }
            if ($script:W.omgCanary) { $r.counts['omg_canary'] = $script:W.omgCanary; Add-Reason $r 'R-OMG' }
            Write-OutLine ('{"_wres":' + (ConvertTo-ResultJson $r) + '}')
        }
        return 0
    } finally {
        if ($script:W.ns) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($script:W.ns) } catch { } }
        if ($script:W.ol) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($script:W.ol) } catch { } }
    }
}

# ═════════════════════════════════════ 부모: 사전 점검 · 워치독 ═════════════════════════════════════
function Get-OutlookProfileState {
    # Outlook 프로필 수와 '쓸 수 있는' 프로필 수 — 계약 v1.3 §0.8 V7. 계정 관리자 레지스트리 모양은 문서화돼 있지 않다(계정 관리
    # API 는 CLSID 상수만 정의 — M365 조사 H7). 그래서 '쓸 수 없음'은 주소록만 든 긍정 증거가 있을 때만 센다: 메일 계정 목록
    # {ED475418}·데이터 파일 목록{ED475420}이 없거나 비었고, 계정 하위 키가 모두 주소록(LDAP 계정 CLSID 또는 MAPI 계정의 서비스
    # 이름 CONTAB·EMABLT)이며, 주소록 계정이나 주소록 목록{ED475419}이 하나라도 있을 때. 그 밖(Exchange·POP·IMAP·Hotmail/EAS·
    # 서비스 이름 없는 MAPI 계정·모르는 모양·계정 관리자 키 없음)은 쓸 수 있다고 본다 — 회사 PC 의 Exchange 프로필을 막힘으로
    # 오판하지 않게(모르면 막힘으로 단정하지 않는다). 주소록만 든 프로필은 띄우면 'Outlook 시작' 마법사가 뜬다(개발 PC 실측).
    # -Shapes = 시험 주입(레지스트리에서 읽은 것과 같은 모양 @{am; vals; accts}). 같은 함수가 탐침·COM·색인 수집기에 같다.
    param([string[]]$Roots = @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles',
                               'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles',
                               'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles'),
          [object[]]$Shapes = $null)
    $MAPI = '{ED475414-B0D6-11D2-8C3B-00104B2A6676}'                   # OlkMAPIAccount(Exchange·주소록 모두 이 CLSID)
    $LDAP = '{4DB5CBF2-3B77-4852-BC8E-BB81908861F3}'                   # OlkLDAPAccount
    $LISTS = @('{ED475418-B0D6-11D2-8C3B-00104B2A6676}', '{ED475420-B0D6-11D2-8C3B-00104B2A6676}')   # 메일 계정 목록 · 데이터 파일 목록
    $ABLIST = '{ED475419-B0D6-11D2-8C3B-00104B2A6676}'                 # 주소록 목록
    if ($null -eq $Shapes) {
        $sh = New-Object System.Collections.Generic.List[object]
        foreach ($root in $Roots) {
            foreach ($pk in @(Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
                $am = $null
                try { $am = Get-Item -LiteralPath (Join-Path $pk.PSPath '9375CFF0413111d3B88A00104B2A6676') -ErrorAction Stop } catch { $am = $null }
                if ($null -eq $am) { $sh.Add(@{ am = $false }); continue }
                $vals = @{}
                foreach ($n in @($LISTS + $ABLIST)) { $vals[$n] = $am.GetValue($n) }
                $accts = New-Object System.Collections.Generic.List[object]
                foreach ($ak in @(Get-ChildItem -LiteralPath $am.PSPath -ErrorAction SilentlyContinue)) {
                    $accts.Add(@{ clsid = $ak.GetValue('clsid'); svc = $ak.GetValue('Service Name') })
                }
                $sh.Add(@{ am = $true; vals = $vals; accts = $accts.ToArray() })
            }
        }
        $Shapes = $sh.ToArray()
    }
    $r = @{ total = 0; usable = 0 }
    foreach ($p in $Shapes) {
        $r.total++
        if (-not $p.am) { $r.usable++; continue }
        $listed = 0
        foreach ($n in $LISTS) {
            $v = $p.vals[$n]
            if ($v -is [byte[]]) { $listed += $v.Length } elseif ($null -ne $v -and [string]$v) { $listed++ }
        }
        $ab = 0
        $v = $p.vals[$ABLIST]
        if (($v -is [byte[]] -and $v.Length -gt 0) -or ($v -isnot [byte[]] -and $null -ne $v -and [string]$v)) { $ab = 1 }
        $other = 0
        foreach ($ac in @($p.accts)) {
            if ($null -eq $ac) { continue }
            $svc = $ac.svc
            if ($svc -is [byte[]]) { $svc = [Text.Encoding]::Unicode.GetString($svc) }
            $svc = ([string]$svc).Trim([char]0).Trim().ToUpperInvariant()
            $cls = ([string]$ac.clsid).Trim().ToUpperInvariant()
            if ($cls -eq $LDAP -or ($cls -eq $MAPI -and @('CONTAB', 'EMABLT') -contains $svc)) { $ab++ } else { $other++ }
        }
        if ($listed -gt 0 -or $other -gt 0 -or $ab -eq 0) { $r.usable++ }
    }
    return $r
}

function Get-MigrationPolicy {
    # 관리자 주도 새 Outlook 전환 정책(문서 admin-controlled-migration-policy) — 정책 키가 사용자 키보다 우선. 값만 읽는다.
    # DoNewOutlookAutoMigration=1: 클래식을 띄울 때 전환 안내(3단계 — 마지막은 막는 프롬프트, 그 뒤 다음 실행에서 새 Outlook 으로
    # 넘어감). NewOutlookAutoMigrationRetryIntervals=1: 클래식을 띄울 때마다 막는 프롬프트. 같은 함수가 탐침에도 같다.
    $r = @{ auto = $null; retry = $null }
    foreach ($k in @('HKCU:\Software\Policies\Microsoft\Office\16.0\Outlook\Options\General',
                     'HKCU:\Software\Microsoft\Office\16.0\Outlook\Options\General')) {
        $p = $null
        try { $p = Get-ItemProperty -LiteralPath $k -ErrorAction Stop } catch { $p = $null }
        if ($null -eq $p) { continue }
        if ($null -eq $r.auto -and $p.PSObject.Properties['DoNewOutlookAutoMigration']) { try { $r.auto = [int]$p.DoNewOutlookAutoMigration } catch { } }
        if ($null -eq $r.retry -and $p.PSObject.Properties['NewOutlookAutoMigrationRetryIntervals']) { try { $r.retry = [int]$p.NewOutlookAutoMigrationRetryIntervals } catch { } }
    }
    return $r
}

function Find-ClassicOutlook {
    # 클래식 Outlook(OUTLOOK.EXE) 위치 — 판(2010~365)·설치 방식(MSI·Click-to-Run)·32/64비트와 상관없이 찾는다.
    # App Paths 한 곳만 보면 Microsoft 365(Click-to-Run) PC 대부분에서 못 찾아 '새 Outlook 전용' 으로 오판했다(실측).
    # 반환: 있는 OUTLOOK.EXE 전체 경로 또는 $null. 메모리에서만 쓰고 출력하지 않는다.
    # 같은 함수가 Invoke-CapabilityProbe.ps1 · Get-OutlookCom.ps1 · Get-OutlookIndex.ps1 에 똑같이 있다(시험이 대조).
    $cands = New-Object System.Collections.Generic.List[string]
    foreach ($k in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE',
            'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE')) {
        try { $d = (Get-ItemProperty -LiteralPath $k -ErrorAction Stop).'(default)'; if ($d) { $cands.Add([string]$d) } } catch { }
    }
    foreach ($v in @('16.0', '15.0', '14.0')) {
        foreach ($b in @('HKLM:\SOFTWARE\Microsoft\Office', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Office')) {
            try { $ir = (Get-ItemProperty -LiteralPath "$b\$v\Outlook\InstallRoot" -ErrorAction Stop).Path; if ($ir) { $cands.Add((Join-Path $ir 'OUTLOOK.EXE')) } } catch { }
        }
    }
    try {
        $c2r = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration' -ErrorAction Stop).InstallationPath
        if ($c2r) { foreach ($o in @('Office16', 'Office15')) { $cands.Add((Join-Path $c2r "root\$o\OUTLOOK.EXE")) } }
    } catch { }
    foreach ($cls in @('HKLM:\SOFTWARE\Classes', 'HKLM:\SOFTWARE\WOW6432Node\Classes')) {
        try {
            $clsid = (Get-ItemProperty -LiteralPath "$cls\Outlook.Application\CLSID" -ErrorAction Stop).'(default)'
            if ($clsid) {
                $ls = (Get-ItemProperty -LiteralPath "$cls\CLSID\$clsid\LocalServer32" -ErrorAction Stop).'(default)'
                if ($ls) { $cands.Add([string]$ls) }
            }
        } catch { }
    }
    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $pf) { continue }
        foreach ($o in @('root\Office16', 'root\Office15', 'Office16', 'Office15', 'Office14')) { $cands.Add((Join-Path $pf "Microsoft Office\$o\OUTLOOK.EXE")) }
    }
    foreach ($c in $cands) {
        $s = ([string]$c).Trim()
        try { $s = [Environment]::ExpandEnvironmentVariables($s) } catch { }
        if ($s.StartsWith('"')) {
            $e = $s.IndexOf('"', 1)
            if ($e -gt 1) { $s = $s.Substring(1, $e - 1) } else { $s = $s.Trim('"') }
        } else {
            $i = $s.ToLowerInvariant().IndexOf('.exe')
            if ($i -gt 0) { $s = $s.Substring(0, $i + 4) }
        }
        if ($s -and (Test-Path -LiteralPath $s -PathType Leaf)) { return $s }
    }
    return $null
}

function Get-Precheck($st) {
    # COM 을 부르지 않는 점검(레지스트리·프로세스). 새 Outlook 전용·전환 정책·프로필 0·COM 미등록이면 자식을 띄우지 않는다.
    $p = @{ fatal = $null; running = $true; migAuto = $null; migRetry = $null; profTotal = $null; profUsable = $null }
    if ($st) {
        if ($st.opt.automig) { $p.migAuto = 1 }
        $p.running = -not $st.opt.notrunning
        if ($st.opt.newol) { $p.fatal = 'R-NEWOL' } elseif ($st.opt.noprof) { $p.fatal = 'R-NOPROF' } elseif ($st.opt.wizard) { $p.fatal = 'R-WIZARD' }
        elseif (-not $p.running -and $p.migAuto -eq 1) { $p.fatal = 'R-NEWOL' }
        return $p
    }
    $running = $false
    try { $running = [bool](Get-Process -Name outlook -ErrorAction SilentlyContinue) } catch { }
    $p.running = $running
    $mig = Get-MigrationPolicy
    $p.migAuto = $mig.auto; $p.migRetry = $mig.retry
    $pst = Get-OutlookProfileState
    $p.profTotal = $pst.total; $p.profUsable = $pst.usable
    $newOl = $false
    try {
        foreach ($rp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
            $pref = Get-ItemProperty -LiteralPath $rp -ErrorAction SilentlyContinue
            if ($pref -and $pref.PSObject.Properties['UseNewOutlook'] -and [int]$pref.UseNewOutlook -eq 1) { $newOl = $true }
        }
    } catch { }
    try { if (Get-Process -Name olk -ErrorAction SilentlyContinue) { $newOl = $true } } catch { }
    if ($running) { return $p }                                      # 떠 있으면 거기에 붙어 본다(실패 판정은 자식이)
    # 새 Outlook 흔적(전환 토글·olk 실행)만으로 멈추지 않는다 — 클래식 Outlook 이 설치돼 있으면 COM 으로 띄워 읽는다(LM24 와 같음).
    if ($newOl -and -not (Find-ClassicOutlook)) { $p.fatal = 'R-NEWOL'; return $p }
    # 관리자 주도 전환 정책이 켜진 PC 에서 꺼진 클래식을 COM 으로 띄우지 않는다 — 문서상 클래식을 띄우면 전환 안내(막는 프롬프트)가
    # 뜨거나 새 Outlook 으로 넘어간다(M365 조사 M13). 색인·웹 경로가 채운다. 떠 있는 클래식에는 위에서 붙는다.
    if ($p.migAuto -eq 1) { $p.fatal = 'R-NEWOL'; return $p }
    if ($newOl) { [Console]::Error.WriteLine('[outlook] 새 Outlook 사용 흔적이 있지만 클래식 Outlook 이 설치돼 있어 COM 으로 읽습니다') }
    $profVers = New-Object System.Collections.Generic.List[int]
    $legacy = $false
    foreach ($v in @(16, 15)) {
        try { if (Get-ChildItem -LiteralPath ('HKCU:\Software\Microsoft\Office\{0}.0\Outlook\Profiles' -f $v) -ErrorAction SilentlyContinue | Select-Object -First 1) { $profVers.Add($v) } } catch { }
    }
    try { if (Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles' -ErrorAction SilentlyContinue | Select-Object -First 1) { $legacy = $true } } catch { }
    if ($profVers.Count -eq 0 -and -not $legacy) { $p.fatal = 'R-NOPROF'; return $p }
    if ($pst.total -gt 0 -and $pst.usable -eq 0) { $p.fatal = 'R-NOPROF'; return $p }   # 주소록만 든 프로필 — 띄우면 '시작' 마법사(v1.3 §0.8 V7)
    $curVer = ''
    try { $curVer = [string](Get-ItemProperty -LiteralPath 'Registry::HKEY_CLASSES_ROOT\Outlook.Application\CurVer' -ErrorAction Stop).'(default)' } catch { $curVer = '' }
    if (-not $curVer) { $p.fatal = 'R-WIZARD'; return $p }             # COM 미등록 — New-Object 가 마법사·오류로 멈춘다
    $m = [regex]::Match($curVer, '(\d+)$')
    if ($m.Success) {
        $rv = [int]$m.Groups[1].Value
        if ($rv -ge 15 -and $profVers.Count -and -not $profVers.Contains($rv)) { $p.fatal = 'R-WIZARD' }   # 등록된 판에 프로필 없음(구판 MSI 병존)
    }
    return $p
}

$WINCLOSE_CS = @'
using System;
using System.Runtime.InteropServices;
namespace Lm27Com {
    public static class Win {
        delegate bool EnumProc(IntPtr h, IntPtr l);
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
        [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
        public static int CloseTop(int pid) {
            int n = 0;
            EnumProc cb = delegate(IntPtr h, IntPtr l) {
                uint p;
                GetWindowThreadProcessId(h, out p);
                if (p == (uint)pid && IsWindowVisible(h) && PostMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero)) { n++; }
                return true;
            };
            EnumWindows(cb, IntPtr.Zero);
            GC.KeepAlive(cb);
            return n;
        }
    }
}
'@
function Close-ProcessWindows([int]$procId) {
    # 그 프로세스의 보이는 최상위 창(시작 마법사·프로필 선택·경고 대화상자)에 WM_CLOSE(= 취소)를 보낸다. 반환 = 보낸 창 수.
    try { if (-not ('Lm27Com.Win' -as [type])) { Add-Type -TypeDefinition $WINCLOSE_CS -Language CSharp -ErrorAction Stop } } catch { return 0 }
    try { return [int][Lm27Com.Win]::CloseTop($procId) } catch { return 0 }
}
function Stop-OutlookWeStarted([datetime]$Since) {
    # 꺼져 있던 Outlook 을 이 수집이 COM 으로 띄웠는데 붙기에서 멈췄으면(설정 마법사·암호 창 등) 화면에 남기지 않는다 —
    # 계약 v1.3 §0.8 V8. COM 이 띄운 것(명령줄 -Embedding — LocalServer32 문서)이고 자식을 띄운 뒤 생긴 것만: 먼저 그 프로세스의
    # 보이는 창에 WM_CLOSE(취소), 없으면 주 창 닫기 → 10초 안에 안 끝나면 끝낸다(L6 — 강제 종료는 counts.forced_kill).
    # 사용자가 직접 띄운 Outlook(-Embedding 없음)·그 전부터 떠 있던 Outlook 은 건드리지 않는다. 반환 @{closed; forced}.
    $r = @{ closed = 0; forced = 0 }
    $procs = @()
    try { $procs = @(Get-CimInstance -ClassName Win32_Process -Filter "Name='OUTLOOK.EXE'" -ErrorAction Stop) } catch { return $r }
    foreach ($w in $procs) {
        if ([string]$w.CommandLine -notmatch '(?i)[-/]embedding') { continue }
        if ($null -ne $w.CreationDate -and $w.CreationDate -lt $Since.AddSeconds(-2)) { continue }
        try {
            $gp = Get-Process -Id ([int]$w.ProcessId) -ErrorAction Stop
            if ((Close-ProcessWindows $gp.Id) -eq 0) { [void]$gp.CloseMainWindow() }
            if (-not $gp.WaitForExit(10000)) { Stop-Process -Id $gp.Id -Force -ErrorAction Stop; $r.forced++ }
            $r.closed++
        } catch { }
    }
    return $r
}

function Set-Count($r, [string]$k, $v) {
    # 결과(사전 또는 자식 _wres 의 PSCustomObject)의 counts 에 값 하나
    if ($r -is [System.Collections.IDictionary]) {
        if ($null -eq $r['counts']) { $r['counts'] = [ordered]@{} }
        $r['counts'][$k] = $v
        return
    }
    if ($null -eq $r.counts) { $r | Add-Member -NotePropertyName counts -NotePropertyValue ([ordered]@{}) -Force }
    if ($r.counts -is [System.Collections.IDictionary]) { $r.counts[$k] = $v }
    else { $r.counts | Add-Member -NotePropertyName $k -NotePropertyValue $v -Force }
}
function Add-ReasonAny($r, [string]$code) {
    if ($r -is [System.Collections.IDictionary]) { Add-Reason $r $code; return }
    $r.reasons = @(@($r.reasons) + $code | Where-Object { $_ } | Select-Object -Unique)
}

function Invoke-ChildRun($a, [int]$readProt, $pre) {
    # 자식(-Worker) 한 번 — 줄을 통과시키며 워치독을 건다. 붙는 중(attach*)이고 이 수집이 Outlook 을 띄우면 시동 여유,
    # B단 카나리아(pr_start)는 짧은 워치독(경고창 추정).
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    $onlyArg = $(if ($a.mixed) { 'both' } else { $a.kinds[0] })
    $olState = $(if ($pre.running) { 'running' } else { 'started' })
    $argv = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Worker -Only {1} -Since {2} -Until {3} -ReadProtected {4} -BudgetSec {5} -TestNow "{6}" -OlState {7}' -f
             $PSCommandPath, $onlyArg, $a.sinceDay, $a.untilDay, $readProt, $a.budget, $a.nowLocalText, $olState)
    $psi.Arguments = $argv
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $script:Utf8
    $psi.StandardErrorEncoding = $script:Utf8
    $psi.CreateNoWindow = $true
    $launchedAt = Get-Date
    $p = [Diagnostics.Process]::Start($psi)
    $inJson = 'null'
    if ($a.in) { $inJson = ConvertTo-J $a.in }
    $p.StandardInput.WriteLine((ConvertTo-Ascii ('{"_in":' + $inJson + '}')))
    $p.StandardInput.Close()
    $errTask = $p.StandardError.ReadToEndAsync()
    $task = $p.StandardOutput.ReadLineAsync()
    $last = $script:Clock.Elapsed.TotalSeconds
    $hard = $last + [double]$a.budget + [double]$a.watchdog + 30
    $prLimit = [Math]::Min([double]$a.watchdog, [Math]::Max($PR_LIMIT_MIN, [double]$a.protSec * 3))
    $phase = 'attach'; $killed = $null
    $results = [ordered]@{}; $cursors = [ordered]@{}; $nRec = @{ 'mail.com' = 0; 'cal.com' = 0 }
    while ($true) {
        if ($task.Wait(200)) {
            $line = $task.Result
            if ($null -eq $line) { break }
            $last = $script:Clock.Elapsed.TotalSeconds
            if ($line.StartsWith('{"_hb"')) {
                try { $phase = [string](($line | ConvertFrom-Json)._hb.phase) } catch { }
            } elseif ($line.StartsWith('{"_cur"')) {
                try { $o = ($line | ConvertFrom-Json)._cur; $cursors[[string]$o.src] = $o.cursor } catch { }
            } elseif ($line.StartsWith('{"_wres"')) {
                try { $o = ($line | ConvertFrom-Json)._wres; $results[[string]$o.src] = $o } catch { }
            } elseif ($line) {
                Write-OutLine $line
                if (-not $line.StartsWith('{"_')) {
                    $s = $a.srcs[0]
                    if ($a.mixed) { if ($line.Contains('"_kind":"cal"')) { $s = 'cal.com' } else { $s = 'mail.com' } }
                    $nRec[$s]++
                }
            }
            $task = $p.StandardOutput.ReadLineAsync()
        } else {
            $now = $script:Clock.Elapsed.TotalSeconds
            # Outlook 이 꺼져 있던 PC 에서 COM 으로 띄우는 동안(attach*)은 시동·프로필·서버 연결에 수십 초가 걸린다 —
            # 그 사이 워치독(무진전 mail.com.watchdogSec, 기본 20초)이 자식을 죽여 '마법사'로 오판했다(실측). 시동 여유를 준다.
            $limit = $a.watchdog
            if ($phase -like 'attach*' -and -not $pre.running) { $limit = [Math]::Max($a.watchdog, $OUTLOOK_START_GRACE_SEC) }
            elseif ($phase -eq 'pr_start') { $limit = $prLimit }
            if (($now - $last) -gt $limit) { $killed = 'watchdog' }
            elseif ($now -gt $hard) { $killed = 'hard' }
            if ($killed) {
                try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch { }
                break
            }
        }
    }
    [void]$p.WaitForExit(5000)
    try { if ($errTask.Wait(2000)) { foreach ($ln in ($errTask.Result -split "`r?`n")) { if ($ln) { Write-ErrLine $ln } } } } catch { }
    return @{ results = $results; cursors = $cursors; phase = $phase; killed = $killed; nRec = $nRec; launchedAt = $launchedAt }
}

function Invoke-Parent($a) {
    $srcs = @($a.kinds | ForEach-Object { if ($_ -eq 'mail') { 'mail.com' } else { 'cal.com' } })
    $a.srcs = $srcs
    $results = [ordered]@{}
    $pre = Get-Precheck $a.st
    if ($pre.fatal) {
        foreach ($s in $srcs) { $r = New-Result $s; Add-Reason $r $pre.fatal; $r.counts['attach'] = 'skipped'; $r.rc = 3; $results[$s] = $r }
        if ($pre.migAuto -eq 1 -and $pre.fatal -eq 'R-NEWOL') {
            Write-ErrLine '[outlook-com] 건너뜀(R-NEWOL) — 관리자 새 Outlook 전환 정책이 켜져 있어 꺼진 클래식 Outlook 을 띄우지 않습니다. 색인·웹 경로가 빈칸을 채웁니다'
        } else {
            Write-ErrLine ('[outlook-com] 건너뜀({0}) — 이 PC 에서는 Outlook COM 을 쓸 수 없습니다. 다른 경로가 빈칸을 채웁니다' -f $pre.fatal)
        }
    } else {
        if ($a.includeArchive) { Write-ErrLine '[outlook-com] 보관 사서함 읽기(mail.includeArchiveStore)는 보관 사서함 식별을 확인하기 전까지 쓰지 않습니다 — 기본 사서함만 읽습니다' }
        $omgTimeout = $false
        $run = Invoke-ChildRun $a ([int]$a.readProt) $pre
        if ($run.killed -and $run.phase -eq 'pr_start' -and [int]$a.readProt -eq 1) {
            # B단 첫 보호 읽기(내 주소)가 멈췄다 — Object Model Guard 경고창 추정(백신 상태·정책). 이번 실행은 B단 없이 다시 붙는다
            Write-ErrLine '[outlook-com] 보호 주소 읽기가 응답하지 않아(보안 경고창 추정) 주소·본문 없이 다시 읽습니다'
            $omgTimeout = $true
            $run = Invoke-ChildRun $a 0 $pre
        }
        $results = $run.results
        $phase = $run.phase
        $closed = @{ closed = 0; forced = 0 }
        if (-not $a.st -and -not $pre.running -and $phase -like 'attach*') {
            # 꺼져 있던 Outlook 을 이 수집이 띄웠는데 붙기에서 멈췄다 — 그 창(마법사·대화상자)을 화면에 남기지 않는다(v1.3 §0.8 V8)
            $closed = Stop-OutlookWeStarted $run.launchedAt
            if ($closed.closed -gt 0) { Write-ErrLine ('[outlook-com] 이 수집이 띄운 Outlook 이 시작 단계에서 멈춰 닫았습니다({0}개)' -f $closed.closed) }
        }
        foreach ($s in $srcs) {
            if (-not $results.Contains($s)) {
                # 자식이 결과 없이 끝났다(워치독·예외) — 붙는 중이면 대화상자·마법사, 읽는 중이면 수송 실패
                $r = New-Result $s
                $why = 'R-TRANSPORT'
                if ($phase -like 'attach*') { if ($pre.running) { $why = 'R-DIALOG' } else { $why = 'R-WIZARD' } }
                Add-Reason $r $why
                $r.items_ok = $run.nRec[$s]
                $r.counts['watchdog'] = [bool]($run.killed)
                $r.counts['phase'] = $phase
                if ($phase -like 'attach*') { $r.counts['attach_step'] = $phase }
                if ($closed.forced -gt 0) { $r.counts['forced_kill'] = $true }
                $r.rc = 3
                $results[$s] = $r
                Write-ErrLine ('[outlook-com] {0}: 응답 없음({1}) — 자식을 끝냈습니다. 다음 실행에서 다시 시도합니다' -f $s, $phase)
            }
        }
        if ($omgTimeout) {
            foreach ($s in @($results.Keys)) {
                Add-ReasonAny $results[$s] 'R-OMG'
                Set-Count $results[$s] 'omg_canary' 'timeout'
                Set-Count $results[$s] 'protected_read' $false
            }
        }
        $script:CursorsOut = $run.cursors
    }
    foreach ($s in @($results.Keys)) {
        $r = $results[$s]
        Set-Count $r 'started_outlook' (-not $pre.running)
        if ($null -ne $pre.migAuto) { Set-Count $r 'migration_auto' $pre.migAuto }
        if ($null -ne $pre.migRetry) { Set-Count $r 'migration_retry' $pre.migRetry }
        if ($null -ne $pre.profTotal) { Set-Count $r 'profiles_total' $pre.profTotal; Set-Count $r 'profiles_usable' $pre.profUsable }
    }
    $cursors = @{}
    if ($script:CursorsOut) { $cursors = $script:CursorsOut }
    return @{ rc = 0; results = $results; cursors = $cursors }
}

# ═════════════════════════════════════ 진입 ═════════════════════════════════════
$code = 3
$kindsOut = @('mail.com', 'cal.com')
$script:CursorsOut = $null
try {
    if ($args.Count) { throw (New-Object System.ArgumentException('unknown-argument')) }
    $onlyN = $Only
    if ($Worker -and $Only -eq 'both') { $onlyN = '' }
    if ($onlyN -notin @('', 'mail', 'cal')) { throw (New-Object System.ArgumentException('only')) }
    if ($Pc -and $Pc -notmatch $PC_RX) { throw (New-Object System.ArgumentException('pc')) }
    if ($OlState -notin @('', 'running', 'started')) { throw (New-Object System.ArgumentException('olstate')) }
    $kinds = @('cal', 'mail')
    if ($onlyN) { $kinds = @($onlyN) }
    $kindsOut = @($kinds | ForEach-Object { if ($_ -eq 'mail') { 'mail.com' } else { 'cal.com' } })
    $in = Read-InLine
    $st = Get-SelfTest
    $nowLocal = Get-Date
    if ($TestNow) { $nowLocal = [datetime]::ParseExact($TestNow, 'yyyy-MM-dd HH:mm', $script:Inv) }
    $untilDay = $Until; if (-not $untilDay) { $untilDay = $nowLocal.ToString('yyyy-MM-dd', $script:Inv) }
    if (-not $Since) {
        # 기본 창 = collect.lookbackDays(오늘 포함 n 일 — 원장 기본 시작일과 같은 셈). 연결자는 늘 -Since 를 넘긴다(v1.3 §0.8 V6)
        $lb = 120
        try { $lb = [int](Get-Cfg $in 'collect.lookbackDays' 120) } catch { $lb = 120 }
        if ($lb -lt 1) { $lb = 120 }
        $sinceDay = [datetime]::ParseExact($untilDay, 'yyyy-MM-dd', $script:Inv).AddDays(-($lb - 1)).ToString('yyyy-MM-dd', $script:Inv)
    } else { $sinceDay = $Since }
    $script:RangeOut = @($sinceDay, $untilDay)          # 상태 줄 range — 이번에 맡은 창(원장 관측을 이 창으로, V6 · T-09)
    $sinceLocal = [datetime]::ParseExact($sinceDay, 'yyyy-MM-dd', $script:Inv)
    $untilLocal = [datetime]::ParseExact($untilDay, 'yyyy-MM-dd', $script:Inv).AddDays(1)
    if ($untilLocal -le $sinceLocal) { throw (New-Object System.ArgumentException('range')) }
    $rpRaw = $ReadProtected
    if ($rpRaw -eq '') { $rpRaw = [string](Get-Cfg $in 'mail.com.readProtected' '0') }
    $readProt = 0; if ($rpRaw -eq '1') { $readProt = 1 }                # auto 는 연결자가 탐침으로 정한다 — 못 받았으면 안전하게 0
    $sub = Get-Cfg $in 'probe.subfolderRatio' $null
    $staleH = 72
    try { $staleH = [double](Get-Cfg $in 'probe.ostStaleH' 72) } catch { $staleH = 72 }
    $a = @{
        in = $in; st = $st; kinds = $kinds; mixed = ($kinds.Count -gt 1); readProt = $readProt
        budget = (Get-IntArg $BudgetSec (Get-Cfg $in 'mail.com.budgetSec' 360) 1)
        watchdog = (Get-IntArg $WatchdogSec (Get-Cfg $in 'mail.com.watchdogSec' 20) 1)
        protSec = [double](Get-Cfg $in 'mail.com.protectedReadSec' 2)
        capMail = [int](Get-Cfg $in 'mail.com.capMail' 20000); capCal = [int](Get-Cfg $in 'mail.com.capCal' 8000)
        includeArchive = [bool](Get-Cfg $in 'mail.includeArchiveStore' $false)
        owner = ([string](Get-Cfg $in 'collect.ownerAddress' '')).Trim().ToLower()
        subRatio = $sub; staleH = $staleH; olState = $OlState
        sinceDay = $sinceDay; untilDay = $untilDay; sinceLocal = $sinceLocal; untilLocal = $untilLocal
        nowLocalText = $nowLocal.ToString('yyyy-MM-dd HH:mm', $script:Inv); nowLocal = $nowLocal; nowUtc = (ConvertTo-UtcFromLocal $nowLocal)
    }
    if ($Worker) {
        $code = Invoke-Worker $a
        exit $code
    }
    $out = Invoke-Parent $a
    # 진행 커서(자식이 달마다 낸 마지막 값)를 끝 줄로 — 파이프가 기록 성공 뒤에만 저장한다(계약 §7.3)
    if ($out.cursors.Count) {
        if ($a.mixed) { Write-OutLine ('{"_cursor":' + (ConvertTo-J $out.cursors) + '}') }
        else { foreach ($k in $out.cursors.Keys) { Write-OutLine ('{"_cursor":' + (ConvertTo-J $out.cursors[$k]) + '}') } }
    }
    $rcs = New-Object System.Collections.Generic.List[int]
    foreach ($k in $out.results.Keys) {
        $r = $out.results[$k]
        $rcs.Add([int]$r.rc); Write-ErrLine ('{"_status":' + (ConvertTo-ResultJson $r) + '}')
    }
    if ($rcs.Contains(3)) { $code = 3 } elseif ($rcs.Contains(0)) { $code = 0 } elseif ($rcs.Contains(4)) { $code = 4 } else { $code = 1 }
} catch {
    $why = $_.Exception.GetType().Name
    foreach ($s in $kindsOut) {
        $r = New-Result $s; Add-Reason $r 'R-TRANSPORT'; $r.counts['error'] = $why; $r.rc = 3
        if ($Worker) { Write-OutLine ('{"_wres":' + (ConvertTo-ResultJson $r) + '}') }
        else { Write-ErrLine ('{"_status":' + (ConvertTo-ResultJson $r) + '}') }
    }
    $code = 3
}
exit $code
