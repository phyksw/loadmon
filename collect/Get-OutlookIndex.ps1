<#
.SYNOPSIS
  mail.index · cal.index — Windows Search 색인(SystemIndex OLE DB)에서 Outlook 메일·일정 메타데이터를 읽는 수집기(CM §6).

.DESCRIPTION
  계약 §2.17 · §7.3 · §8.1, CM §6 · §8 · §10 · §11.2. LM24 Get-OutlookIndex.ps1 을 옮겨 다시 설계했다.
    · 디스크에 쓰지 않는다(L-09). 원시 후보 레코드를 NDJSON 으로 stdout 에만 낸다 — 연결자가 정제 파이프
      (lm27_pipe.py --kind <kind> --src <경로 ID>)의 stdin 으로 잇는다. 원시 필드 이름은 P §10.2(계약 §3.5).
    · stdin 제어 줄 {"_in": {"cursor": …, "cfg": {…}}} 을 받는다(stdin 이 리디렉션되지 않았으면 기본값). 커서·설정·주소를
      명령줄로 받지 않는다(X-300). stdout 첫 줄 {"_meta": {"my_addrs": [...]}}, 레코드 줄, 끝 줄 {"_cursor": {…}}.
    · 결과(숫자·열거·사유 코드만)는 stderr 마지막 줄 {"_status": {…}}(계약 v1.2 §0.7 C1 한 모양 — schema·src·rc·reasons·
      partial·cap_hit·budget_hit·n·counts + 수집기 필드) — 메일·일정을 함께 읽으면 경로마다 한 줄.
    · Outlook 을 띄우지 않는다(마법사 무한 대기 없음). Outlook 항목만(System.ItemUrl LIKE 'mapi%'), 날짜 리터럴은 UTC.
      리터럴을 UTC 로 해석한다는 것은 문서에 없다(LM24 실측) — 앞뒤 하루 여유로 묻고 행을 정확한 창으로 다시 거른다.
      여유 밖 행이 오면 해석이 다르다는 뜻이라 R-TZ(경고 — counts.literal_mismatch).
    · 내 것만 낸다. 캐시 모드는 공유·추가 메일함과 공유 일정을 로컬에 받아 두고 그것도 색인된다(Microsoft 문서
      shared-mail-folders-in-cached-exchange-mode). 폴더 표시 경로의 첫 조각이 메일함 계정(저장소)이다
      (props-system-itemfolderpathdisplay 예 '/Mailbox Account/Inbox'). 주 저장소 = 내 주소와 이름이 같은 저장소, 없으면
      내 주소로 보낸 편지함이 있는 저장소, 저장소가 하나뿐이면 그것. 다른 저장소 행은 뺀다(counts.other_store). 정하지 못하면
      버리지 않는다(counts.store_scope=unknown — 내 메일을 잃어 0건으로 확정하는 쪽이 더 나쁘다). mapi URL 의 사용자 SID
      (SCOPE 예 'mapi://{S-1-5-21-…}/Mailbox user/')가 내 SID 와 다르면 뺀다 — 표본에 내 SID 행이 하나도 없으면 거르지 않는다.
    · 폴더는 경로 조각 단위 정확 일치로 제외(mail.index.excludeFolderNames), '보낸 편지함/Sent' 조각이면 sent. 일정도 같은
      제외를 하고, 받은·보낸 편지함에 있는 일정 항목(모임 요청·응답)과 같은 (시작·끝·제목) 중복은 뺀다(counts.cal_mail_folder ·
      cal_dup).
    · 지평선(색인에 있는 가장 오래된 날)은 종류별이다. 메일은 메일만 — 캐시 동기화 창은 메일에만 걸리고 일정·연락처에는 걸리지
      않는다(only-subset-items-synchronized) — 주 저장소·SID·제외 폴더 밖에서 가장 오래된 항목. 정책 동기화 창
      (HKCU\Software\Policies\Microsoft\Office\<v>\Outlook\Cached Mode 의 SyncWindowSetting 개월 · SyncWindowSettingDays 일)이
      있으면 메일 지평선은 그 창의 시작보다 이르지 않다. 지평선 질의가 실패하면 창 안 가장 이른 항목 날짜(보수적).
      요청 시작이 지평선보다 이르면 R-HORIZON — 그 앞 0건인 날은 out_of_horizon(관측 못 한 날을 0건으로 확정하지 않는다).
    · 질의 시간 제한(OleDbCommand.CommandTimeout — 문서 기본 30초, 0 = 무제한은 쓰지 않는다): 본 질의 $QUERY_TIMEOUT_SEC ·
      보조 질의 $AUX_TIMEOUT_SEC(감시 상한 600초 안). 시간 초과는 확장 속성 사다리로 내려가지 않고 rc 3 + R-BUDGET(커서 그대로 —
      다음 실행이 다시). 없는 속성(DB_E_NOCOLUMN)·모르는 오류만 한 단계씩 덜어 다시 묻는다(counts.query_error·query_hresult).
    · 반복 일정 마스터는 회차가 전개되지 않는다 → 레코드에 recurrence_incomplete, 결과에 그 수 + R-RECURINC + partial
      (계약 v1.2 §0.7 C4 — 부분 결과: rc 는 새 레코드 기준 0·4, 셀은 partial 이라 cal.owa 가 빈 회차를 채운다).
    · 상한(mail.index.capMail·capCal)에 닿으면 조용히 자르지 않고 cap_hit + R-CAP(rc 0, 셀 partial).
    · 막힌 사유가 있으면 항상 rc 3 + 사유 — 탐침 Invoke-CapabilityProbe.ps1 Decide-Index 와 같은 판정(v1.3 §0.8 V4):
      색인 연결 실패 R-NOIDX · 서비스 일시 중지·카탈로그 종료 중 R-IDXPAUSED · 제한 언어 모드 R-CLM · Outlook 색인 금지 정책
      (HKLM — 건수와 무관: 남은 옛 색인을 최신으로 믿지 않는다) R-IDXPOLICY · 그 종류의 최근 365일 Outlook 항목 0(탐침 n365) →
      카탈로그 일시정지·복구·전체 색인 중이면 R-IDXPAUSED, 아니면 R-NEWOL / R-NOAPP / R-NOPROF / R-ONLINE.
      항목이 있어도 카탈로그가 복구·전체 색인 중(CatalogStatus 2·3)이면 R-IDXPAUSED(일시 — 0건인 날은 미관측). 일시정지(1)는
      사용자 활동 등 back-off 로도 나므로(문서) 항목이 있으면 counts.catalog_status 만 남긴다.
  rc: 0 새 레코드 · 1 기간에 항목 없음 · 3 막힘·불완전(사유) · 4 읽었지만 새것 0(커서 이후 0).

  커서(계약 §3.10): {"last_item_ts_utc": UTC, "read_from": UTC} — read_from 은 이미 읽은 범위의 시작(이 수집기가 더한 칸).
  색인은 싸므로 겹침 재조회를 허용하고(마지막 시각 −1일부터 다시 냄) 중복은 정제기의 레코드 id 로 흡수된다.

  시험 주입(계약 §11.3): LM_INDEX_FAKE=<json> — 색인 대신 {"mail": [System.* 행], "calendar": [...]}(시각은 로컬
  'yyyy-MM-dd HH:mm'). 같은 질의 단계(표본·건수·지평선·본 질의 사다리)를 흉내 낸다. 선택 키: "_error" = noidx|paused ·
  "_total_outlook_items"(정수 — 종류별 최근 365일 건수 대신) · "_policy" · "_policy_hkcu" · "_newol" · "_classic" · "_noprof" ·
  "_ext_rejected" · "_my_addrs"(시험용 내 주소 — 실제 PC 신원 조회를 하지 않는다) · "_catalog_status"(0~6) ·
  "_sync_window_months" · "_sync_window_days" · "_sid"(내 SID — 없으면 SID 로 거르지 않음) · "_query_error"('<종류>@<단계>' 쉼표
  목록 — 종류 column|timeout|other, 단계 = 본 질의 사다리 0~ 또는 aux(보조 질의)) · "_literal_shift_min"(색인이 날짜 리터럴을
  UTC+분으로 해석한다고 가정). -TestNow 'yyyy-MM-dd HH:mm'(로컬).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File collect\Get-OutlookIndex.ps1 -Only mail -Pc pc_0123456789abcdef -Since 2026-09-01 -Until 2026-09-30
#>
param(
    [string]$Only = '',
    [string]$Since = '',
    [string]$Until = '',
    [string]$Pc = '',
    [string]$TestNow = ''
)

# ── 제한 언어 모드: .NET 형을 쓰기 전에 먼저 본다(R-CLM, rc 3) ─────────────────────────────────────────────
# 계약 v1.2 §0.7 C1: 상태 줄 한 모양(_status). CLM 에서는 [Console] 호출도 막히므로 stdout 제어 줄(문자열 리터럴)로 낸다.
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    if ($Only -eq 'cal') {
        '{"_status":{"schema":"lm27.collector_status/1","src":"cal.index","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{},"items_total":0,"items_ok":0}}'
    } else {
        '{"_status":{"schema":"lm27.collector_status/1","src":"mail.index","rc":3,"reasons":["R-CLM"],"partial":false,"cap_hit":false,"budget_hit":false,"n":0,"counts":{},"items_total":0,"items_ok":0}}'
    }
    exit 3
}

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:Inv = [Globalization.CultureInfo]::InvariantCulture
$script:StdOut = [Console]::OpenStandardOutput()
$script:StdErr = [Console]::OpenStandardError()

$SENT_RX = '^(보낸\s*(편지함|메일함|항목)|Sent(\s+(Items|Mail|Messages))?)$'
$INBOX_RX = '^(받은\s*(편지함|메일함)|Inbox)$'
$CAL_RX = '^(일정|Calendar)$'
$PREFIX_RX = '^\s*(RE|FW|FWD|답장|전달|회신)\s*[:：]\s*'
$PC_RX = '^pcx?_[0-9a-f]{16}$'
# mail.index.excludeFolderNames 내장 기본값(설정 레지스트리와 같은 목록 — 연결자가 _in.cfg 로 최종 목록을 준다)
$DEFAULT_EXCLUDE = @('지운 편지함', '삭제된 항목', '삭제된 편지함', 'Deleted Items', 'Trash', '정크 메일', 'Junk E-mail',
    'Junk Email', 'Junk', '스팸', 'Spam', '임시 보관함', 'Drafts', 'Draft', '보낼 편지함', 'Outbox', '보관', '보관함',
    'Archive', '동기화 문제', 'Sync Issues', '대화 기록', 'Conversation History', 'RSS 피드', 'RSS Feeds')
$BUSY_OF = @{ '0' = 'free'; '1' = 'tentative'; '2' = 'busy'; '3' = 'oof'; '4' = 'elsewhere' }
$OVERLAP_DAYS = 1          # 마지막 시각에서 이만큼 겹쳐 다시 낸다(늦게 색인된 항목)
$CAL_REFRESH_DAYS = 14     # 일정은 최근 이만큼과 그 뒤를 매번 다시 낸다(시각 변경·취소 반영)
$EDGE_DAYS = 1             # 날짜 리터럴 해석 차이(UTC·로컬)를 덮는 질의 여유 — 행은 정확한 창으로 다시 거른다
$RECENT_DAYS = 365         # '그 종류 항목이 있다' 기준 창(탐침 Read-IdxQuery n365 와 같다)
$AUX_TOP = 2000            # 표본·지평선 질의 행 수
$QUERY_TIMEOUT_SEC = 180   # 본 질의 OleDbCommand.CommandTimeout(문서 기본 30초 · 0 = 무제한은 쓰지 않는다 · 감시 상한 600초 안)
$AUX_TIMEOUT_SEC = 60      # 표본·건수·지평선 질의(본 질의와 합쳐도 감시 상한 안)
$COLUMN_HR = @('0x80040E55', '0x80040E11')   # DB_E_NOCOLUMN(개발 PC 실측: 없는 속성) · DB_E_BADCOLUMNID — 한 단계 덜어 다시
$TIMEOUT_HR = @('0x80040E31', '0x80041607')  # DB_E_ABORTLIMITREACHED · QUERY_E_TIMEDOUT — 사다리로 내려가지 않는다
$SID_RX = '^mapi\d*://\{(S-1-[0-9-]+)\}'
# 카탈로그 상태(ISearchManager::GetCatalog("SystemIndex") → ISearchCatalogManager::GetCatalogStatus) — 탐침 NATIVE_CS 와 같은 interop
$CATALOG_CS = @'
using System;
using System.Runtime.InteropServices;
namespace Lm27Idx {
    [ComImport, Guid("AB310581-AC80-11D1-8DF3-00C04FB6EF50"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface ISearchCatalogManager {
        void Slot1(); void Slot2(); void Slot3();
        void GetCatalogStatus(out int status, out int pausedReason);
    }
    [ComImport, Guid("AB310581-AC80-11D1-8DF3-00C04FB6EF69"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface ISearchManager {
        void Slot1(); void Slot2(); void Slot3(); void Slot4(); void Slot5(); void Slot6(); void Slot7();
        [return: MarshalAs(UnmanagedType.Interface)]
        ISearchCatalogManager GetCatalog([MarshalAs(UnmanagedType.LPWStr)] string catalog);
    }
    public static class Catalog {
        public static int[] Status() {
            Type t = Type.GetTypeFromCLSID(new Guid("7D096C5F-AC08-4F1F-BEB7-5C22C517CE39"));
            object o = Activator.CreateInstance(t);
            try {
                ISearchCatalogManager c = ((ISearchManager)o).GetCatalog("SystemIndex");
                int s, r;
                c.GetCatalogStatus(out s, out r);
                Marshal.ReleaseComObject(c);
                return new int[] { s, r };
            } finally { Marshal.ReleaseComObject(o); }
        }
    }
}
'@

# ── 출력 ──────────────────────────────────────────────────────────────────────────────────────────────
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

# 색인에 Outlook 항목이 0 일 때의 막힘 사유(탐침 Invoke-CapabilityProbe.ps1 Decide-Index 와 같은 규칙 — v1.3 §0.8 V3·V4).
function Get-ZeroItemsReason([bool]$policy, [bool]$classic, [bool]$newOl, [bool]$noprof) {
    if ($policy) { return 'R-IDXPOLICY' }
    if (-not $classic) { if ($newOl) { return 'R-NEWOL' } else { return 'R-NOAPP' } }
    if ($noprof) { return 'R-NOPROF' }
    return 'R-ONLINE'
}
# 새 Outlook 흔적(탐침 P-OL-INST 와 같은 세 가지): 전환 토글(UseNewOutlook=1) · 실행 중(olk) · 설치 패키지(Microsoft.OutlookForWindows_*).
function Test-NewOutlookTrace {
    try {
        foreach ($rp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
            $pref = Get-ItemProperty -LiteralPath $rp -ErrorAction SilentlyContinue
            if ($pref -and $pref.PSObject.Properties['UseNewOutlook'] -and [int]$pref.UseNewOutlook -eq 1) { return $true }
        }
    } catch { }
    try { if (Get-Process -Name olk -ErrorAction SilentlyContinue) { return $true } } catch { }
    try {
        $pkRoot = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'
        $pk = @(Get-ChildItem -LiteralPath $pkRoot -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -like 'Microsoft.OutlookForWindows_*' })
        if ($pk.Count -gt 0) { return $true }
    } catch { }
    return $false
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

# ── 색인 상태(실물 전용 — 읽기만) ─────────────────────────────────────────────────────────────────────
function Get-CatalogStatus {
    # [상태, 일시정지 사유] 또는 $null(interop 컴파일·호출 실패 = 모름). 탐침 P-IDX 와 같은 문서화된 흐름.
    try { Add-Type -TypeDefinition $CATALOG_CS -Language CSharp -ErrorAction Stop } catch { return $null }
    try { return [Lm27Idx.Catalog]::Status() } catch { return $null }
}
function Get-SyncWindowPolicy {
    # 그룹 정책이 정한 캐시 모드 메일 동기화 창(only-subset-items-synchronized · KB 3115009): SyncWindowSetting(개월, 0 = 전체) ·
    # SyncWindowSettingDays(일 — 3일·1주·2주). 정책 경로만 본다 — 비정책 경로는 '새 계정 기본값'이라 실제 창이 아니다(문서).
    foreach ($v in @('16.0', '15.0')) {
        $p = $null
        try { $p = Get-ItemProperty -LiteralPath "HKCU:\Software\Policies\Microsoft\Office\$v\Outlook\Cached Mode" -ErrorAction Stop } catch { continue }
        $m = $null; $d = $null
        if ($p.PSObject.Properties['SyncWindowSetting']) { try { $m = [int]$p.SyncWindowSetting } catch { } }
        if ($p.PSObject.Properties['SyncWindowSettingDays']) { try { $d = [int]$p.SyncWindowSettingDays } catch { } }
        if ($null -ne $m -or $null -ne $d) { return @{ months = $m; days = $d } }
    }
    return $null
}
function Get-SyncStart($sync, [datetime]$nowUtc) {
    # 동기화 창의 시작(UTC) — 둘 다 있으면 짧은 쪽(늦은 시작 = 지평선을 늦추는 보수적인 쪽). 0·없음 = 전체(시작 없음).
    if ($null -eq $sync) { return $null }
    $st = $null
    if ($sync.months -gt 0) { $st = $nowUtc.AddMonths(-[int]$sync.months) }
    if ($sync.days -gt 0) { $d = $nowUtc.AddDays(-[int]$sync.days); if ($null -eq $st -or $d -gt $st) { $st = $d } }
    return $st
}

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
function ConvertFrom-LocalText([string]$s) {
    # 'yyyy-MM-dd HH:mm[:ss]'(로컬) · ISO 'yyyy-MM-ddTHH:mm:ssZ'(UTC) → UTC datetime 또는 $null
    if (-not $s) { return $null }
    $t = $s.Trim()
    $styles = [Globalization.DateTimeStyles]::None
    $d = [datetime]::MinValue
    foreach ($f in @("yyyy-MM-dd'T'HH:mm:ss'Z'", "yyyy-MM-dd'T'HH:mm'Z'")) {
        if ([datetime]::TryParseExact($t, $f, $script:Inv, $styles, [ref]$d)) { return [DateTime]::SpecifyKind($d, 'Utc') }
    }
    foreach ($f in @('yyyy-MM-dd HH:mm:ss', 'yyyy-MM-dd HH:mm', "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", 'yyyy-MM-dd')) {
        if ([datetime]::TryParseExact($t, $f, $script:Inv, $styles, [ref]$d)) {
            return [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($d, 'Unspecified'), [TimeZoneInfo]::Local)
        }
    }
    return $null
}
function ConvertFrom-UtcText($s) {
    if (-not $s) { return $null }
    $d = [datetime]::MinValue
    if ([datetime]::TryParseExact([string]$s, "yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Inv, [Globalization.DateTimeStyles]::None, [ref]$d)) {
        return [DateTime]::SpecifyKind($d, 'Utc')
    }
    return $null
}
function Get-LocalDayUtc([string]$day, [int]$addDays) {
    $d = [datetime]::ParseExact($day, 'yyyy-MM-dd', $script:Inv).AddDays($addDays)
    return [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($d, 'Unspecified'), [TimeZoneInfo]::Local)
}
function Get-LocalDate([datetime]$u) {
    return [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::SpecifyKind($u, 'Utc'), [TimeZoneInfo]::Local).Date
}

# ── stdin 제어 줄 ─────────────────────────────────────────────────────────────────────────────────────
function Read-InLine {
    # 첫 줄만 읽는다(연결자가 쓰고 닫는다 — 닫지 않아도 줄 끝에서 멈춘다). 리디렉션이 아니면 기본값.
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

# ── 내 주소(CM §6.1 — LM24 :66-121 이식) ─────────────────────────────────────────────────────────────
function Get-MyAddrs([string]$owner, $fake) {
    $me = New-Object System.Collections.Generic.List[string]
    if ($fake) {
        if ($fake.PSObject.Properties['_my_addrs']) { foreach ($a in @($fake._my_addrs)) { if ($a) { $me.Add(([string]$a).Trim().ToLower()) } } }
    } else {
        try {
            $u = (& whoami /upn 2>$null)
            if ($LASTEXITCODE -eq 0 -and $u) { $me.Add(([string]$u).Trim().ToLower()) }
        } catch { }
        try {
            Add-Type -AssemblyName System.DirectoryServices.AccountManagement -ErrorAction Stop
            $up = [System.DirectoryServices.AccountManagement.UserPrincipal]::Current
            if ($up) { foreach ($v in @($up.EmailAddress, $up.UserPrincipalName)) { if ($v) { $me.Add(([string]$v).Trim().ToLower()) } } }
        } catch { }
        try {
            if ($env:USERDNSDOMAIN) {
                $srch = [adsisearcher]('(&(objectCategory=person)(sAMAccountName=' + $env:USERNAME + '))')
                $srch.ClientTimeout = [TimeSpan]::FromSeconds(5)
                $srch.ServerTimeLimit = [TimeSpan]::FromSeconds(5)
                [void]$srch.PropertiesToLoad.AddRange([string[]]@('mail', 'userPrincipalName'))
                $res = $srch.FindOne()
                if ($res) { foreach ($k in @('mail', 'userprincipalname')) { foreach ($v in @($res.Properties[$k])) { if ($v) { $me.Add(([string]$v).Trim().ToLower()) } } } }
            }
        } catch { }
        try {
            foreach ($pp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles', 'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles',
                              'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles')) {
                if (-not (Test-Path -LiteralPath $pp)) { continue }
                foreach ($k in @(Get-ChildItem -LiteralPath $pp -Recurse -ErrorAction SilentlyContinue | Select-Object -First 400)) {
                    foreach ($name in @('Account Name', 'Email')) {
                        $raw = $null
                        try { $raw = $k.GetValue($name) } catch { }
                        if ($raw -is [byte[]] -and $raw.Length -ge 4) { $raw = [System.Text.Encoding]::Unicode.GetString($raw).TrimEnd([char]0) }
                        if ($raw -is [string] -and $raw -match '^[^@\s]+@[^@\s]+\.[^@\s]+$') { $me.Add($raw.Trim().ToLower()) }
                    }
                }
            }
        } catch { }
    }
    if ($owner) { $me.Add($owner.Trim().ToLower()) }
    return @($me | Where-Object { $_ -and $_.Length -ge 3 -and $_ -match '@' } | Select-Object -Unique)
}

# ── 색인 질의(실물 · 시험 주입 — 같은 모양 @{ ok; rows | err }) ─────────────────────────────────────────
function Invoke-Query($conn, [string]$sql, [int]$cap, [int]$timeout) {
    # 결과는 늘 목록(List)이다 — `return , $rows`. 그냥 돌려주면 PowerShell 이 풀어 1행 결과가 해시표가 되고, 예전 지평선
    # `$top[0]` 은 늘 $null(예외 → 지평선 없음)이었다.
    $rows = New-Object System.Collections.Generic.List[object]
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $sql
    $cmd.CommandTimeout = $timeout
    $rd = $cmd.ExecuteReader()
    try {
        while ($rd.Read()) {
            $o = @{}
            for ($i = 0; $i -lt $rd.FieldCount; $i++) {
                $v = $rd.GetValue($i)
                if ($v -is [System.DBNull]) { $v = $null }
                elseif ($v -is [datetime]) { $v = [DateTime]::SpecifyKind($v, 'Utc') }   # 색인 날짜는 UTC
                $o[$rd.GetName($i)] = $v
            }
            $rows.Add($o)
            if ($rows.Count -ge $cap) { break }
        }
    } finally { $rd.Close() }
    return , $rows
}
function Get-QueryError($err, [double]$sec, [int]$timeout) {
    # 질의 예외 → @{ cls = column|timeout|other; hr = '0x########'; type } — 원문·메시지는 남기지 않는다.
    # column = 없는 속성(개발 PC 실측: Search.CollatorDSO 가 OleDbException 0x80040E55 DB_E_NOCOLUMN 을 MethodInvocationException 에
    # 싸서 던진다) · timeout = 시간 제한 가까이 가서 난 실패 또는 시간 초과 HRESULT · 그 밖 = other.
    $ex = $err
    if ($ex -is [System.Management.Automation.ErrorRecord]) { $ex = $ex.Exception }
    while ($ex -is [System.Management.Automation.MethodInvocationException] -and $null -ne $ex.InnerException) { $ex = $ex.InnerException }
    $hr = '0x{0:X8}' -f [int]$ex.HResult
    $cls = 'other'
    if ($timeout -gt 0 -and $sec -ge 0.9 * $timeout) { $cls = 'timeout' }
    elseif ($TIMEOUT_HR -contains $hr -or $ex -is [System.TimeoutException]) { $cls = 'timeout' }
    elseif ($COLUMN_HR -contains $hr) { $cls = 'column' }
    return @{ cls = $cls; hr = $hr; type = $ex.GetType().Name }
}
function Get-FakeRows($fake, [string]$kind, [string[]]$drop) {
    $rows = New-Object System.Collections.Generic.List[object]
    $p = $fake.PSObject.Properties[$kind]
    if (-not $p) { return , $rows }
    foreach ($o in @($p.Value)) {
        if ($null -eq $o) { continue }
        $h = @{}
        foreach ($q in $o.PSObject.Properties) {
            if ($drop -and $drop -contains $q.Name) { continue }
            $v = $q.Value
            if ($v -is [string] -and $v -match '^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}') { $v = ConvertFrom-LocalText $v }
            $h[$q.Name] = $v
        }
        $rows.Add($h)
    }
    return , $rows
}
function Get-FakeError($ctx, [string]$level) {
    # '_query_error' 주입 — 'timeout@0,column@1,other@aux': 그 단계에서 날 오류 종류(없으면 '')
    if (-not $ctx.fake -or -not $ctx.fake.PSObject.Properties['_query_error']) { return '' }
    foreach ($t in ([string]$ctx.fake._query_error -split ',')) {
        $p = @($t.Trim() -split '@')
        if ($p.Count -eq 2 -and $p[1].Trim() -eq $level) { return $p[0].Trim() }
    }
    return ''
}
function Get-FakeAnswer($ctx, [string]$purpose, [string]$kind, [int]$level, [bool]$isLast, [string[]]$drop, [int]$cap) {
    # 색인 질의 흉내: sample(최근 메일 표본, 최신순) · recent(최근 365일 건수) · horizon(가장 오래된 행부터, 날짜 NULL 제외) ·
    # main(본 질의 — 여유 창 [qSince, qUntil), _literal_shift_min 이면 색인이 리터럴을 그만큼 늦은 UTC 로 본 것처럼 민다).
    # main 은 SQL 의 mapi 조건을 흉내 내지 않는다 — 줄 단위 이중 검사(non_outlook)를 시험하려고.
    $lv = $(if ($purpose -eq 'main') { [string]$level } else { 'aux' })
    $cls = Get-FakeError $ctx $lv
    if (-not $cls -and $purpose -eq 'main' -and $ctx.extRejected -and -not $isLast) { $cls = 'column' }
    if ($cls) { return @{ ok = $false; err = @{ cls = $cls; hr = ''; type = 'fake' } } }
    $col = $(if ($kind -eq 'mail') { 'System.ItemDate' } else { 'System.StartDate' })
    $fk = $(if ($kind -eq 'mail') { 'mail' } else { 'calendar' })
    if (-not $ctx.fakeRows.ContainsKey($fk)) { $ctx.fakeRows[$fk] = Get-FakeRows $ctx.fake $fk @() }   # 행 변환은 종류마다 한 번
    $all = $ctx.fakeRows[$fk]
    if ($drop -and $drop.Count) {
        $cut = New-Object System.Collections.Generic.List[object]
        foreach ($r in $all) { $h = @{}; foreach ($k in $r.Keys) { if ($drop -notcontains $k) { $h[$k] = $r[$k] } }; $cut.Add($h) }
        $all = $cut
    }
    $hits = New-Object System.Collections.Generic.List[object]
    if ($purpose -eq 'main') {
        $lo = $ctx.qSince.AddMinutes(-$ctx.literalShift); $hi = $ctx.qUntil.AddMinutes(-$ctx.literalShift)
        foreach ($r in $all) {
            $t = $r[$col]
            if (-not ($t -is [datetime])) { continue }
            if ($kind -eq 'cal') {
                $e = $r['System.EndDate']; if (-not ($e -is [datetime])) { $e = $t }
                if ($t -lt $hi -and $e -ge $lo) { $hits.Add($r) }
            } elseif ($t -ge $lo -and $t -lt $hi) { $hits.Add($r) }
        }
    } else {
        $from = $ctx.nowUtc.AddDays(-$RECENT_DAYS)
        foreach ($r in $all) {
            $t = $r[$col]
            if (-not ($t -is [datetime]) -or -not ((Get-S $r 'System.ItemUrl') -like 'mapi*')) { continue }
            if ($purpose -ne 'horizon' -and $t -lt $from) { continue }
            $hits.Add($r)
        }
    }
    $sorted = @($hits | Sort-Object { $_[$col] } -Descending:($purpose -ne 'horizon'))
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($r in $sorted) { if ($out.Count -ge $cap) { break }; $out.Add($r) }
    return @{ ok = $true; rows = $out }
}
function Invoke-IdxQuery($ctx, [string]$purpose, [string]$kind, [int]$level, [bool]$isLast, [string[]]$drop, [string]$sql, [int]$cap, [int]$timeout) {
    if ($ctx.fake) { return (Get-FakeAnswer $ctx $purpose $kind $level $isLast $drop $cap) }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $rows = Invoke-Query $ctx.conn $sql $cap $timeout
        return @{ ok = $true; rows = $rows }
    } catch {
        return @{ ok = $false; err = (Get-QueryError $_ $sw.Elapsed.TotalSeconds $timeout) }
    }
}
function Get-S($row, [string]$k) {
    $v = $row[$k]
    if ($null -eq $v) { return '' }
    if ($v -is [array]) { return (@($v | Where-Object { $null -ne $_ } | ForEach-Object { [string]$_ }) -join ';') }
    return [string]$v
}
function Get-List($row, [string]$k) {
    $v = $row[$k]
    if ($null -eq $v) { return @() }
    if ($v -is [array] -or ($v -is [System.Collections.IEnumerable] -and -not ($v -is [string]))) {
        return @($v | Where-Object { $null -ne $_ } | ForEach-Object { ([string]$_).Trim() })
    }
    return @(([string]$v).Split(';') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
function Get-D($row, [string]$k) {
    $v = $row[$k]
    if ($v -is [datetime]) { return $v }
    return $null
}
function New-Party([string[]]$addrs, [string[]]$names) {
    $out = New-Object System.Collections.Generic.List[object]
    $n = [math]::Max(@($addrs).Count, @($names).Count)
    for ($i = 0; $i -lt $n -and $i -lt 100; $i++) {
        $a = $null; $nm = $null
        if ($i -lt @($addrs).Count -and $addrs[$i]) { $a = ([string]$addrs[$i]).Trim().ToLower() }
        if ($i -lt @($names).Count -and $names[$i]) { $nm = ([string]$names[$i]).Trim() }
        if ($a -or $nm) { $out.Add([ordered]@{ addr = $a; name = $nm }) }
    }
    return , $out.ToArray()
}

# ── 범위: 주 저장소 · 사용자 SID · 폴더 ──────────────────────────────────────────────────────────────
function Get-Segs([string]$path) {
    # 배열 그대로 돌려준다(`, `) — 조각이 하나면 PowerShell 이 풀어 문자열이 되고 `$segs[0]` 이 글자 하나가 된다
    return , [string[]]@(($path -split '[\\/]') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
function Test-Excluded($segs, $exclude) {
    foreach ($sg in $segs) { foreach ($x in $exclude) { if ($sg -ieq $x) { return $true } } }
    return $false
}
function Test-MailFolder($segs) {
    # 받은·보낸 편지함 조각 — 일정 행이 여기 있으면 모임 요청·응답이지 일정 항목이 아니다
    foreach ($sg in $segs) { if ($sg -match $INBOX_RX -or $sg -match $SENT_RX) { return $true } }
    return $false
}
function Test-StoreSeg($segs, $exclude) {
    # 첫 조각이 저장소일 수 있는가 — 조각이 둘 이상이고 첫 조각이 잘 알려진 폴더 이름(받은·보낸 편지함·일정·제외 폴더)이 아닐 때만.
    # 경로에 저장소 조각이 없는 모양('\받은 편지함\…', '\일정')이면 저장소로 거르지 않는다(내 것을 잃지 않게).
    if (@($segs).Count -lt 2) { return $false }
    $f = $segs[0]
    if ($f -match $INBOX_RX -or $f -match $SENT_RX -or $f -match $CAL_RX) { return $false }
    foreach ($x in $exclude) { if ($f -ieq $x) { return $false } }
    return $true
}
function Get-StoreScope($rows, [string[]]$my, $exclude) {
    # 최근 메일 표본으로 주 저장소(폴더 표시 경로 첫 조각, 소문자)를 정한다 → @{ mode; store; stores }.
    # mode: addr(내 주소와 이름이 같은 저장소) · sent(내 주소로 보낸 편지함 행이 가장 많은 저장소) · single(저장소 하나) ·
    # nostore(첫 조각이 받은·보낸 편지함 — 경로에 저장소 조각이 없는 모양: 거르지 않음) · unknown(못 정함: 거르지 않음) · none(표본 없음).
    # 저장소 이름에 내 주소가 '들어 있는' 것만으로는 고르지 않는다('Online Archive - <주소>' 를 주 저장소로 오인하지 않게).
    $sc = @{ mode = 'none'; store = $null; stores = 0 }
    $names = @{}
    $votes = @{}
    foreach ($r in $rows) {
        $segs = Get-Segs (Get-S $r 'System.ItemFolderPathDisplay')
        if ($segs.Count -eq 0) { continue }
        if ($segs[0] -match $INBOX_RX -or $segs[0] -match $SENT_RX) { $sc.mode = 'nostore'; $sc.stores = 0; return $sc }
        if (-not (Test-StoreSeg $segs $exclude)) { continue }
        $k = $segs[0].ToLowerInvariant()
        $names[$k] = $true
        $sent = $false
        for ($i = 1; $i -lt $segs.Count; $i++) { if ($segs[$i] -match $SENT_RX) { $sent = $true; break } }
        if ($sent) {
            $fa = @(Get-List $r 'System.Message.FromAddress')
            if ($fa.Count -and $my -contains $fa[0].ToLowerInvariant()) { $votes[$k] = 1 + [int]$votes[$k] }
        }
    }
    $sc.stores = $names.Count
    if ($names.Count -eq 0) { return $sc }
    if ($names.Count -eq 1) { $sc.mode = 'single'; $sc.store = @($names.Keys)[0]; return $sc }
    $hit = @($names.Keys | Where-Object { $my -contains $_ })
    if ($hit.Count -eq 1) { $sc.mode = 'addr'; $sc.store = $hit[0]; return $sc }
    if ($votes.Count) {
        $top = @($votes.GetEnumerator() | Sort-Object -Property Value -Descending)
        if ($top.Count -eq 1 -or $top[0].Value -gt $top[1].Value) { $sc.mode = 'sent'; $sc.store = [string]$top[0].Key; return $sc }
    }
    $sc.mode = 'unknown'
    return $sc
}
function Get-RowSid([string]$url) {
    if ($url -match $SID_RX) { return $Matches[1].ToUpperInvariant() }
    return $null
}
function Get-SidScope($rows, [string]$sid) {
    # match(행 가운데 내 SID 가 있다 — 다른 SID 행은 뺀다) · nomatch(SID 는 있으나 내 것이 없다 — 형식이 다를 수 있어 거르지
    # 않는다) · none(URL 에 SID 가 없거나 내 SID 를 모름)
    if (-not $sid) { return 'none' }
    $any = $false
    foreach ($r in $rows) {
        $s = Get-RowSid (Get-S $r 'System.ItemUrl')
        if ($s) { $any = $true; if ($s -eq $sid) { return 'match' } }
    }
    if ($any) { return 'nomatch' }
    return 'none'
}
function Get-OutOfScope($r, $ctx, [string]$sidMode) {
    # '' = 내 것 · other_sid · other_store
    if ($sidMode -eq 'match') {
        $s = Get-RowSid (Get-S $r 'System.ItemUrl')
        if ($s -and $s -ne $ctx.sid) { return 'other_sid' }
    }
    if ($ctx.scope.store) {
        $segs = Get-Segs (Get-S $r 'System.ItemFolderPathDisplay')
        if ((Test-StoreSeg $segs $ctx.exclude) -and $segs[0].ToLowerInvariant() -ne $ctx.scope.store) { return 'other_store' }
    }
    return ''
}

# ── 종류별 보조 사실: 최근 365일 건수 · 지평선 ──────────────────────────────────────────────────────────
function Get-KindAux($ctx, [string]$kind, [int]$fakeTotal) {
    # n = 그 종류의 최근 365일 Outlook 항목 수(탐침 n365 와 같은 기준 — 저장소·SID 를 가리지 않는다, 0 이면 막힘 사유) ·
    # horizon = 주 저장소·SID·제외 폴더 밖에서 가장 오래된 항목(일정은 받은·보낸 편지함 행도 뺀다). 모르면 $null.
    $a = @{ n = $null; horizon = $null }
    $col = $(if ($kind -eq 'mail') { 'System.ItemDate' } else { 'System.StartDate' })
    $kindSql = $(if ($kind -eq 'mail') { 'email' } else { 'calendar' })
    if ($kind -eq 'mail') { $a.n = $ctx.sampleN }
    else {
        $recent = $ctx.nowUtc.AddDays(-$RECENT_DAYS).ToString('yyyy-MM-dd HH:mm:ss', $script:Inv)
        $q = Invoke-IdxQuery $ctx 'recent' $kind 0 $true @() ("SELECT TOP 1 $col FROM SYSTEMINDEX WHERE System.Kind = 'calendar' " +
            "AND System.ItemUrl LIKE 'mapi%' AND $col >= '$recent'") 1 $AUX_TIMEOUT_SEC
        if ($q.ok) { $a.n = $q.rows.Count } elseif (-not $ctx.auxError) { $ctx.auxError = $q.err.cls }
    }
    if ($fakeTotal -ge 0) { $a.n = $fakeTotal }
    if ($null -ne $a.n -and $a.n -eq 0) { return $a }
    $q = Invoke-IdxQuery $ctx 'horizon' $kind 0 $true @() ("SELECT TOP $AUX_TOP $col, System.ItemFolderPathDisplay, System.ItemUrl " +
        "FROM SYSTEMINDEX WHERE System.Kind = '$kindSql' AND System.ItemUrl LIKE 'mapi%' AND $col IS NOT NULL ORDER BY $col ASC") $AUX_TOP $AUX_TIMEOUT_SEC
    if (-not $q.ok) { if (-not $ctx.auxError) { $ctx.auxError = $q.err.cls }; return $a }
    $sidMode = $ctx.sidMode
    if ($sidMode -eq 'none') { $sidMode = Get-SidScope $q.rows $ctx.sid }
    foreach ($r in $q.rows) {
        $d = Get-D $r $col
        if (-not $d -or (Get-S $r 'System.ItemUrl') -notmatch '^mapi\d*:') { continue }
        if (Get-OutOfScope $r $ctx $sidMode) { continue }
        $segs = Get-Segs (Get-S $r 'System.ItemFolderPathDisplay')
        if (Test-Excluded $segs $ctx.exclude) { continue }
        if ($kind -eq 'cal' -and (Test-MailFolder $segs)) { continue }
        $a.horizon = $d
        break
    }
    return $a
}

# ── 본문 ──────────────────────────────────────────────────────────────────────────────────────────────
$script:Results = New-Object System.Collections.Generic.List[object]
$script:Cursors = [ordered]@{}
$script:Mixed = $false

function New-Result([string]$src) {
    return [ordered]@{ schema = 'lm27.collector_status/1'; src = $src; rc = 3
        reasons = (New-Object System.Collections.Generic.List[string]); partial = $false; n = 0; items_total = 0
        items_ok = 0; new = 0; cap_hit = $false; budget_hit = $false; horizon_oldest = $null; recurrence_incomplete = 0
        counts = [ordered]@{} }
}
function Add-Reason($res, [string]$code) { if (-not $res.reasons.Contains($code)) { $res.reasons.Add($code) } }
function Write-Record([System.Collections.IDictionary]$rec, [string]$kind) {
    if ($script:Mixed) { $rec['_kind'] = $kind }
    Write-OutLine (ConvertTo-J $rec)
}
function Write-Results {
    foreach ($r in $script:Results) {
        $o = [ordered]@{}
        foreach ($k in $r.Keys) { $o[$k] = $r[$k] }
        $o['reasons'] = @($r.reasons | Sort-Object)
        # C1: partial = 상한·예산·반복 일부(C4), n = 새 레코드 수
        $o['partial'] = [bool]($r.cap_hit -or $r.budget_hit -or ($r.recurrence_incomplete -gt 0) -or $r.reasons.Contains('R-RECURINC'))
        $o['n'] = [int]$r.new
        Write-ErrLine ('{"_status":' + (ConvertTo-J $o) + '}')
    }
}
function Get-Levels([string]$kind) {
    # 확장 속성 사다리(LM24 Run-Query): 단계마다 SELECT 에 더하는 열(cols)과 그 단계에서 빠지는 열(drop — 시험 주입이 흉내)
    if ($kind -eq 'mail') {
        return @(@{ cols = ', System.Message.ToName, System.Message.CcName, System.Message.ConversationID'; drop = @() },
                 @{ cols = ', System.Message.ToName, System.Message.CcName'; drop = @('System.Message.ConversationID') },
                 @{ cols = ''; drop = @('System.Message.ToName', 'System.Message.CcName', 'System.Message.ConversationID') })
    }
    return @(@{ cols = ', System.Calendar.IsRecurring'; drop = @() }, @{ cols = ''; drop = @('System.Calendar.IsRecurring') })
}

function Invoke-IndexKind([string]$kind, $ctx) {
    $src = $(if ($kind -eq 'mail') { 'mail.index' } else { 'cal.index' })
    $res = New-Result $src
    $res['range'] = @($ctx.sinceDay, $ctx.untilDay)          # 이번에 맡은 창(로컬 날짜) — 원장 관측을 이 창으로(V6 · T-09)
    $script:Results.Add($res)
    foreach ($r in $ctx.reasons) { Add-Reason $res $r }
    foreach ($r in $ctx.kindReasons[$kind]) { Add-Reason $res $r }
    # 판정 재료(숫자·열거만 — 주소·저장소 이름·SID 는 내지 않는다)
    if ($null -ne $ctx.catalog) { $res.counts['catalog_status'] = $ctx.catalog; $res.counts['paused_reason'] = $ctx.pausedReason }
    if ($ctx.policyHkcu) { $res.counts['policy_hkcu'] = $true }
    $res.counts['store_scope'] = $ctx.scope.mode
    $res.counts['stores'] = $ctx.scope.stores
    if ($null -ne $ctx.syncDays) { $res.counts['sync_window_days'] = $ctx.syncDays }
    if ($ctx.auxError) { $res.counts['aux_error'] = $ctx.auxError }
    if ($ctx.fatal) { Add-Reason $res $ctx.fatal; $res.rc = 3; return }
    if ($ctx.kindFatal[$kind]) { Add-Reason $res $ctx.kindFatal[$kind]; $res.rc = 3; return }
    $cur = Get-SrcCursor $ctx.in $src $script:Mixed
    $lastTs = $null; $readFrom = $null
    if ($cur) {
        if ($cur.PSObject.Properties['last_item_ts_utc']) { $lastTs = ConvertFrom-UtcText $cur.last_item_ts_utc }
        if ($cur.PSObject.Properties['read_from']) { $readFrom = ConvertFrom-UtcText $cur.read_from }
    }
    $fmt = 'yyyy-MM-dd HH:mm:ss'
    $qs = $ctx.qSince.ToString($fmt, $script:Inv)
    $qu = $ctx.qUntil.ToString($fmt, $script:Inv)
    if ($kind -eq 'mail') {
        $cap = [int]$ctx.capMail
        $sel = ("SELECT System.ItemDate, System.Message.DateReceived, System.Message.DateSent, System.Message.FromName, " +
            "System.Message.FromAddress, System.Message.ToAddress, System.Message.CcAddress, System.Subject, " +
            "System.ItemFolderPathDisplay, System.ItemUrl{0} FROM SYSTEMINDEX WHERE System.Kind = 'email' " +
            "AND System.ItemUrl LIKE 'mapi%' AND System.ItemDate >= '{1}' AND System.ItemDate < '{2}' ORDER BY System.ItemDate DESC")
    } else {
        $cap = [int]$ctx.capCal
        $sel = ("SELECT System.StartDate, System.EndDate, System.Subject, System.Calendar.Location, System.Calendar.ShowTimeAs, " +
            "System.ItemFolderPathDisplay, System.ItemUrl{0} FROM SYSTEMINDEX WHERE System.Kind = 'calendar' " +
            "AND System.ItemUrl LIKE 'mapi%' AND System.EndDate >= '{1}' AND System.StartDate < '{2}' ORDER BY System.StartDate DESC")
    }
    # 확장 속성이 거부되면(없는 속성 · 모르는 오류) 한 단계씩 덜어 다시 — 시간 초과는 내려가지 않는다(같은 질의라 또 넘긴다)
    $levels = @(Get-Levels $kind)
    $rows = $null; $qerr = $null
    for ($qi = 0; $qi -lt $levels.Count; $qi++) {
        $lv = $levels[$qi]
        $q = Invoke-IdxQuery $ctx 'main' $kind $qi ($qi -eq $levels.Count - 1) $lv.drop ($sel -f $lv.cols, $qs, $qu) ($cap + 1) $QUERY_TIMEOUT_SEC
        if ($q.ok) { $rows = $q.rows; break }
        $qerr = $q.err
        if ($qerr.cls -eq 'timeout') { break }
    }
    $res.counts['query_level'] = $qi
    if ($qerr) { $res.counts['query_error'] = $qerr.cls; if ($qerr.hr) { $res.counts['query_hresult'] = $qerr.hr } }
    if ($null -eq $rows) {
        # 읽은 것이 없다 — 커서를 두지 않는다(다음 실행이 같은 창을 다시). 시간 초과는 일시(R-BUDGET), 그 밖은 수송 실패
        if ($qerr -and $qerr.cls -eq 'timeout') { Add-Reason $res 'R-BUDGET' } else { Add-Reason $res 'R-TRANSPORT' }
        $res.rc = 3
        return
    }
    $fallback = ($qi -gt 0 -and $qi -eq $levels.Count - 1)
    $res.counts['fallback'] = $fallback
    # 상한: 한 건 더 읽어 넘치면 절단 — 조용히 자르지 않고 cap_hit + R-CAP(셀 partial, CM §6.2)
    if ($rows.Count -gt $cap) {
        $rows = [System.Collections.Generic.List[object]]@($rows | Select-Object -First $cap)
        $res.cap_hit = $true
        Add-Reason $res 'R-CAP'
    }
    $res.counts['rows'] = $rows.Count
    $sidMode = $ctx.sidMode
    if ($sidMode -eq 'none') { $sidMode = Get-SidScope $rows $ctx.sid }
    $nowIso = Format-Utc $ctx.nowUtc
    $emitSent = New-Object System.Collections.Generic.List[object]
    $emitOther = New-Object System.Collections.Generic.List[object]
    $maxTs = $lastTs; $minTs = $null; $nNew = 0; $nEx = 0; $nNoMapi = 0; $nNoTime = 0; $nMasters = 0
    $nWin = 0; $nOut = 0; $nLit = 0; $nSid = 0; $nStore = 0; $nCalMail = 0; $nDup = 0
    $seen = @{}
    $refreshFrom = $ctx.nowUtc.AddDays(-$CAL_REFRESH_DAYS)
    foreach ($r in $rows) {
        # 범위 사후 검사(L9): 리터럴 경계 밖 행 = 색인이 리터럴을 다르게 해석(R-TZ), 정확한 창 밖 행은 내지 않는다
        if ($kind -eq 'mail') {
            $td = Get-D $r 'System.ItemDate'
            if ($td) {
                if ($td -lt $ctx.qSince -or $td -ge $ctx.qUntil) { $nLit++ }
                if ($td -lt $ctx.sinceUtc -or $td -ge $ctx.untilUtc) { $nOut++; continue }
            }
        } else {
            $s0 = Get-D $r 'System.StartDate'
            if ($s0) {
                $e0 = Get-D $r 'System.EndDate'
                if (-not $e0 -or $e0 -lt $s0) { $e0 = $s0 }
                if ($s0 -ge $ctx.qUntil -or $e0 -lt $ctx.qSince) { $nLit++ }
                if ($s0 -ge $ctx.untilUtc -or $e0 -lt $ctx.sinceUtc) { $nOut++; continue }
            }
        }
        $nWin++
        $url = Get-S $r 'System.ItemUrl'
        if ($url -notmatch '^mapi\d*:') { $nNoMapi++; continue }      # 디스크의 메일·일정 파일 제외(이중 안전장치)
        $why = Get-OutOfScope $r $ctx $sidMode
        if ($why -eq 'other_sid') { $nSid++; continue }
        if ($why -eq 'other_store') { $nStore++; continue }
        $segs = Get-Segs (Get-S $r 'System.ItemFolderPathDisplay')
        if (Test-Excluded $segs $ctx.exclude) { $nEx++; continue }
        if ($kind -eq 'mail') {
            $isSent = [bool](@($segs | Where-Object { $_ -match $SENT_RX }).Count)
            $last = $(if ($segs.Count) { $segs[$segs.Count - 1] } else { '' })
            if ($isSent) { $box = 'sent'; $role = $(if ($last -match $SENT_RX) { 'sent' } else { 'subfolder' }) }
            else { $box = 'inbox'; $role = $(if ($last -match $INBOX_RX) { 'inbox' } else { 'subfolder' }) }
            $t = $null
            if ($isSent) { $t = Get-D $r 'System.Message.DateSent' }
            if (-not $t) { $t = Get-D $r 'System.Message.DateReceived' }
            if (-not $t) { $t = Get-D $r 'System.ItemDate' }
            if (-not $t) { $nNoTime++; continue }
            $isNew = (-not $lastTs) -or ($t -gt $lastTs) -or ($readFrom -and $t -lt $readFrom)
            if ($isNew) { $nNew++ }
            if ((-not $maxTs) -or $t -gt $maxTs) { $maxTs = $t }
            if ((-not $minTs) -or $t -lt $minTs) { $minTs = $t }
            if (-not ($isNew -or $t -ge $lastTs.AddDays(-$OVERLAP_DAYS))) { continue }
            $subj = Get-S $r 'System.Subject'
            $topic = $subj
            while ($topic -match $PREFIX_RX) { $topic = $topic -replace $PREFIX_RX, '' }
            $rec = [ordered]@{}
            $cid = Get-S $r 'System.Message.ConversationID'
            if ($cid) { $rec['conversation_id'] = $cid }
            $rec['conversation_topic'] = $topic.Trim()
            $rec['box'] = $box
            $rec['folder_role'] = $role
            $fa = @(Get-List $r 'System.Message.FromAddress'); $fn = @(Get-List $r 'System.Message.FromName')
            if ($fa.Count -and $fa[0]) { $rec['sender_addr'] = $fa[0].ToLower() }
            if ($fn.Count -and $fn[0]) { $rec['sender_name'] = $fn[0] }
            $rec['to'] = New-Party (Get-List $r 'System.Message.ToAddress') (Get-List $r 'System.Message.ToName')
            $rec['cc'] = New-Party (Get-List $r 'System.Message.CcAddress') (Get-List $r 'System.Message.CcName')
            $rec['subject'] = $subj
            $rec['ts_utc'] = Format-Utc $t
            $rec['ts_local_offset'] = Format-Offset $t
            $rec['ts_precision'] = 'minute'
            $rec['observed_at'] = $nowIso
            $rec['confidence'] = 1.0
            if ($box -eq 'sent') { $emitSent.Add($rec) } else { $emitOther.Add($rec) }
        } else {
            if (Test-MailFolder $segs) { $nCalMail++; continue }      # 받은·보낸 편지함의 모임 요청·응답(일정 항목 아님)
            $st = Get-D $r 'System.StartDate'; $en = Get-D $r 'System.EndDate'
            if (-not $st) { $nNoTime++; continue }
            if (-not $en -or $en -lt $st) { $en = $st }
            $dk = (Format-Utc $st) + '|' + (Format-Utc $en) + '|' + (Get-S $r 'System.Subject').Trim().ToLowerInvariant()
            if ($seen.ContainsKey($dk)) { $nDup++; continue }         # 같은 회의가 두 일정 폴더에(복사·하위 일정)
            $seen[$dk] = $true
            $isRec = $r['System.Calendar.IsRecurring']
            $master = (($isRec -is [bool]) -and $isRec) -or ([string]$isRec -match '^(True|1|-1)$')
            if ($master) { $nMasters++ }
            $isNew = (-not $lastTs) -or ($st -gt $lastTs) -or ($readFrom -and $st -lt $readFrom)
            if ($isNew) { $nNew++ }
            if (((-not $maxTs) -or $st -gt $maxTs) -and $st -le $ctx.nowUtc) { $maxTs = $st }
            if ((-not $minTs) -or $st -lt $minTs) { $minTs = $st }
            if (-not ($isNew -or $st -ge $refreshFrom -or $st -ge $lastTs.AddDays(-$OVERLAP_DAYS))) { continue }
            $loc = [TimeZoneInfo]::ConvertTimeFromUtc($st, [TimeZoneInfo]::Local)
            $allDay = ($loc.TimeOfDay.TotalMinutes -eq 0 -and ($en - $st).TotalHours -ge 23)
            $busyRaw = Get-S $r 'System.Calendar.ShowTimeAs'
            $busy = 'busy'
            if ($BUSY_OF.ContainsKey($busyRaw)) { $busy = $BUSY_OF[$busyRaw] }
            $rec = [ordered]@{}
            $rec['start_utc'] = Format-Utc $st
            $rec['end_utc'] = Format-Utc $en
            $rec['subject'] = Get-S $r 'System.Subject'
            $locTxt = Get-S $r 'System.Calendar.Location'
            if ($locTxt) { $rec['location'] = $locTxt }
            $rec['busy_status'] = $busy
            $rec['is_recurring'] = [bool]$master
            $rec['all_day'] = [bool]$allDay
            $rec['recurrence_incomplete'] = [bool]$master
            $rec['ts_local_offset'] = Format-Offset $st
            $rec['ts_precision'] = $(if ($allDay) { 'date' } else { 'minute' })
            $rec['observed_at'] = $nowIso
            $rec['confidence'] = 1.0
            $emitOther.Add($rec)
        }
    }
    # 보낸 편지함을 먼저 흘린다(왕래 도메인 냉시작 오탐 방지 — CM §10)
    foreach ($rec in $emitSent) { Write-Record $rec $kind }
    foreach ($rec in $emitOther) { Write-Record $rec $kind }
    $emitted = $emitSent.Count + $emitOther.Count
    $res.items_total = $nWin
    $res.items_ok = $emitted
    $res.new = $nNew
    $res.counts['emitted'] = $emitted
    $res.counts['excluded_folder'] = $nEx
    $res.counts['non_outlook'] = $nNoMapi
    $res.counts['no_time'] = $nNoTime
    $res.counts['out_of_range'] = $nOut
    $res.counts['literal_mismatch'] = $nLit
    $res.counts['other_store'] = $nStore
    $res.counts['other_sid'] = $nSid
    $res.counts['sid_check'] = $sidMode
    if ($nLit -gt 0) { Add-Reason $res 'R-TZ' }
    if ($kind -eq 'cal') {
        $res.recurrence_incomplete = $nMasters
        $res.counts['cal_mail_folder'] = $nCalMail
        $res.counts['cal_dup'] = $nDup
        if ($fallback) { $res.counts['recurrence_unknown'] = $true }
    }
    # 지평선(H11): 종류별 색인 지평선 → 메일은 정책 동기화 창의 시작보다 이르지 않게 → 모르면 창 안 가장 이른 항목(보수적)
    $aux = $ctx.aux[$kind]
    $hz = $null; $hsrc = 'none'
    if ($aux -and $aux.horizon) { $hz = $aux.horizon; $hsrc = 'index' }
    if ($kind -eq 'mail' -and $ctx.syncStart -and ((-not $hz) -or $ctx.syncStart -gt $hz)) { $hz = $ctx.syncStart; $hsrc = 'policy' }
    if ((-not $hz) -and $minTs) { $hz = $minTs; $hsrc = 'window' }
    $res.counts['horizon_src'] = $hsrc
    if ($hz) {
        $hd = Get-LocalDate $hz
        $res.horizon_oldest = $hd.ToString('yyyy-MM-dd', $script:Inv)
        if ($hd -gt (Get-LocalDate $ctx.sinceUtc)) { Add-Reason $res 'R-HORIZON' }
    }
    # 커서: 읽은 범위 [read_from, last_item_ts_utc]
    $oldest = $ctx.sinceUtc
    if ($res.cap_hit -and $minTs) { $oldest = $minTs }
    $newFrom = $oldest
    if ($readFrom -and $lastTs -and $oldest -le $lastTs.AddDays($OVERLAP_DAYS) -and $readFrom -lt $oldest) { $newFrom = $readFrom }
    $c = [ordered]@{ last_item_ts_utc = $null; read_from = (Format-Utc $newFrom) }
    if ($maxTs) { $c['last_item_ts_utc'] = Format-Utc $maxTs }
    $script:Cursors[$src] = $c
    # rc(계약 §8.1 · CM §6.4 · X-120)
    # 반복 마스터만·반복 속성 거부(전개 여부 모름) → R-RECURINC(계약 v1.2 §0.7 C4: 부분 결과 — rc 는 아래 새 레코드 기준).
    # 예전의 'rc 3·사유 없음' 은 연결자에서 R-TRANSPORT(수송 실패)로 접혀 cal.owa 배정 근거가 왜곡됐다.
    if ($kind -eq 'cal' -and ($nMasters -gt 0 -or $fallback)) { Add-Reason $res 'R-RECURINC' }
    if ($nNew -gt 0) { $res.rc = 0; return }
    if ($res.cap_hit) { $res.rc = 0; return }
    if ($nWin -gt 0) { $res.rc = 4; return }
    $res.rc = 1
}

$rc = 3
$exitReason = $null
try {
    if ($args.Count) { throw (New-Object System.ArgumentException('unknown-argument')) }
    if ($Only -notin @('', 'mail', 'cal')) { throw (New-Object System.ArgumentException('only')) }
    if ($Pc -and $Pc -notmatch $PC_RX) { throw (New-Object System.ArgumentException('pc')) }
    $in = Read-InLine
    $nowLocal = Get-Date
    if ($TestNow) { $nowLocal = [datetime]::ParseExact($TestNow, 'yyyy-MM-dd HH:mm', $script:Inv) }
    $nowUtc = [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($nowLocal, 'Unspecified'), [TimeZoneInfo]::Local)
    $untilDay = $Until
    if (-not $untilDay) { $untilDay = $nowLocal.ToString('yyyy-MM-dd', $script:Inv) }
    $sinceDay = $Since
    if (-not $sinceDay) {
        # 기본 창 = collect.lookbackDays(원장 기본 시작일과 같은 셈 — 오늘 포함 n 일). 연결자는 늘 -Since 를 넘긴다(v1.3 §0.8 V6)
        $lb = 120
        try { $lb = [int](Get-Cfg $in 'collect.lookbackDays' 120) } catch { $lb = 120 }
        if ($lb -lt 1) { $lb = 120 }
        $sinceDay = [datetime]::ParseExact($untilDay, 'yyyy-MM-dd', $script:Inv).AddDays(-($lb - 1)).ToString('yyyy-MM-dd', $script:Inv)
    }
    $sinceUtc = Get-LocalDayUtc $sinceDay 0
    $untilUtc = Get-LocalDayUtc $untilDay 1
    $ctx = @{
        in = $in; reasons = (New-Object System.Collections.Generic.List[string]); fatal = $null; nowUtc = $nowUtc
        sinceUtc = $sinceUtc; untilUtc = $untilUtc; sinceDay = $sinceDay; untilDay = $untilDay
        qSince = $sinceUtc.AddDays(-$EDGE_DAYS); qUntil = $untilUtc.AddDays($EDGE_DAYS)
        capMail = [int](Get-Cfg $in 'mail.index.capMail' 20000); capCal = [int](Get-Cfg $in 'mail.index.capCal' 8000)
        exclude = @(Get-Cfg $in 'mail.index.excludeFolderNames' $DEFAULT_EXCLUDE | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
        fake = $null; fakeRows = @{}; conn = $null; extRejected = $false; literalShift = 0
        kindFatal = @{}; kindReasons = @{ mail = (New-Object System.Collections.Generic.List[string]); cal = (New-Object System.Collections.Generic.List[string]) }
        aux = @{}; scope = @{ mode = 'none'; store = $null; stores = 0 }; sid = $null; sidMode = 'none'; sampleN = $null; auxError = $null
        catalog = $null; pausedReason = $null; policyHkcu = $false; syncStart = $null; syncDays = $null
    }
    if ($ctx.untilUtc -le $ctx.sinceUtc) { throw (New-Object System.ArgumentException('range')) }
    $kinds = @('mail', 'cal')
    if ($Only) { $kinds = @($Only) }
    $script:Mixed = ($kinds.Count -gt 1)
    if ($env:LM_INDEX_FAKE) {
        $ctx.fake = (Get-Content -Raw -Encoding UTF8 -LiteralPath $env:LM_INDEX_FAKE) | ConvertFrom-Json
        $ctx.extRejected = [bool]($ctx.fake.PSObject.Properties['_ext_rejected'] -and $ctx.fake._ext_rejected)
        if ($ctx.fake.PSObject.Properties['_literal_shift_min']) { $ctx.literalShift = [int]$ctx.fake._literal_shift_min }
    }
    $owner = [string](Get-Cfg $in 'collect.ownerAddress' '')
    $my = @(Get-MyAddrs $owner $ctx.fake)
    Write-OutLine ('{"_meta":{"my_addrs":' + (ConvertTo-J ([object[]]$my)) + '}}')
    if ($my.Count -eq 0 -and $kinds -contains 'mail') { $ctx.reasons.Add('R-NOADDR') }
    # ── 색인 연결·상태 ──
    $policy = $false; $newOl = $null; $classicFake = $false; $noprofFake = $false; $fakeTotal = -1; $sync = $null
    if ($ctx.fake) {
        $f = $ctx.fake
        $err = $(if ($f.PSObject.Properties['_error']) { [string]$f._error } else { '' })
        if ($err -eq 'noidx') { $ctx.fatal = 'R-NOIDX' } elseif ($err -eq 'paused') { $ctx.fatal = 'R-IDXPAUSED' }
        if ($f.PSObject.Properties['_total_outlook_items']) { $fakeTotal = [int]$f._total_outlook_items }
        $policy = [bool]($f.PSObject.Properties['_policy'] -and $f._policy)
        $ctx.policyHkcu = [bool]($f.PSObject.Properties['_policy_hkcu'] -and $f._policy_hkcu)
        $newOl = [bool]($f.PSObject.Properties['_newol'] -and $f._newol)
        $noprofFake = [bool]($f.PSObject.Properties['_noprof'] -and $f._noprof)
        $classicFake = [bool]($f.PSObject.Properties['_classic'] -and $f._classic)   # 시험: 클래식 유무도 주입값으로(실제 레지스트리를 보지 않는다)
        if ($f.PSObject.Properties['_catalog_status'] -and $null -ne $f._catalog_status) { $ctx.catalog = [int]$f._catalog_status }
        if ($f.PSObject.Properties['_sid'] -and $f._sid) { $ctx.sid = ([string]$f._sid).ToUpperInvariant() }
        if ($f.PSObject.Properties['_sync_window_months'] -or $f.PSObject.Properties['_sync_window_days']) {
            $sync = @{ months = $null; days = $null }
            if ($f.PSObject.Properties['_sync_window_months']) { $sync.months = [int]$f._sync_window_months }
            if ($f.PSObject.Properties['_sync_window_days']) { $sync.days = [int]$f._sync_window_days }
        }
    } else {
        $svc = $null
        try { $svc = Get-Service -Name WSearch -ErrorAction Stop } catch { $svc = $null }
        if ($svc -and [string]$svc.Status -eq 'Paused') { $ctx.fatal = 'R-IDXPAUSED' }
        elseif (-not $svc -or [string]$svc.Status -ne 'Running') { $ctx.fatal = 'R-NOIDX' }
        if (-not $ctx.fatal) {
            try {
                $ctx.conn = New-Object System.Data.OleDb.OleDbConnection("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
                $ctx.conn.Open()
            } catch { $ctx.fatal = 'R-NOIDX' }
        }
        if (-not $ctx.fatal) {
            $cs = @(Get-CatalogStatus)
            if ($cs.Count -ge 2) { $ctx.catalog = [int]$cs[0]; $ctx.pausedReason = [int]$cs[1] }
        }
        # Outlook 색인 금지 정책은 문서 경로(HKLM)만 막힘으로 본다. HKCU 정책 경로는 문서에 없어 counts 에만 남긴다.
        try {
            $pol = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Windows Search' -ErrorAction Stop
            if ($pol.PSObject.Properties['PreventIndexingOutlook'] -and [int]$pol.PreventIndexingOutlook -eq 1) { $policy = $true }
        } catch { }
        try {
            $pol = Get-ItemProperty -LiteralPath 'HKCU:\SOFTWARE\Policies\Microsoft\Windows\Windows Search' -ErrorAction Stop
            if ($pol.PSObject.Properties['PreventIndexingOutlook'] -and [int]$pol.PreventIndexingOutlook -eq 1) { $ctx.policyHkcu = $true }
        } catch { }
        try { $ctx.sid = ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value).ToUpperInvariant() } catch { $ctx.sid = $null }
        $sync = Get-SyncWindowPolicy
    }
    $ctx.syncStart = Get-SyncStart $sync $ctx.nowUtc
    if ($ctx.syncStart) { $ctx.syncDays = [int][math]::Round(($ctx.nowUtc - $ctx.syncStart).TotalDays) }
    if (-not $ctx.fatal -and $ctx.catalog -eq 6) { $ctx.fatal = 'R-IDXPAUSED' }    # CATALOG_STATUS_SHUTTING_DOWN — 질의할 수 없다(문서)
    if (-not $ctx.fatal -and $policy) { $ctx.fatal = 'R-IDXPOLICY' }               # 건수와 무관(탐침과 같다)
    if (-not $ctx.fatal) {
        # 주 저장소·SID 범위와 메일 건수 — 최근 365일 메일 표본(최신순)
        $recent = $ctx.nowUtc.AddDays(-$RECENT_DAYS).ToString('yyyy-MM-dd HH:mm:ss', $script:Inv)
        $q = Invoke-IdxQuery $ctx 'sample' 'mail' 0 $true @() ("SELECT TOP $AUX_TOP System.ItemFolderPathDisplay, System.Message.FromAddress, " +
            "System.ItemUrl FROM SYSTEMINDEX WHERE System.Kind = 'email' AND System.ItemUrl LIKE 'mapi%' AND System.ItemDate >= '$recent' " +
            "ORDER BY System.ItemDate DESC") $AUX_TOP $AUX_TIMEOUT_SEC
        if ($q.ok) {
            $ctx.sampleN = $q.rows.Count
            $ctx.scope = Get-StoreScope $q.rows $my $ctx.exclude
            $ctx.sidMode = Get-SidScope $q.rows $ctx.sid
        } else { $ctx.auxError = $q.err.cls }
        # 그 종류의 최근 365일 Outlook 항목 0 — 0건이 아니라 막힘(CM §6.4 분해, X-124·X-125). 탐침 Decide-Index 와 같은 판정
        # (v1.3 §0.8 V3·V4): 카탈로그 일시정지·복구·전체 색인 중 R-IDXPAUSED · 클래식 없음 → 새 Outlook 흔적이면 R-NEWOL, 없으면
        # R-NOAPP · 클래식은 있으나 쓸 수 있는 프로필 없음 R-NOPROF · 그 밖(클래식 있음) R-ONLINE.
        $needZero = $false
        foreach ($k in $kinds) {
            $a = Get-KindAux $ctx $k $fakeTotal
            $ctx.aux[$k] = $a
            if ($null -ne $a.n -and $a.n -eq 0) {
                if ($null -ne $ctx.catalog -and $ctx.catalog -ge 1 -and $ctx.catalog -le 3) { $ctx.kindFatal[$k] = 'R-IDXPAUSED' }
                else { $ctx.kindFatal[$k] = '?'; $needZero = $true }
            } elseif ($ctx.catalog -eq 2 -or $ctx.catalog -eq 3) { $ctx.kindReasons[$k].Add('R-IDXPAUSED') }   # 복구·전체 색인 중 — 0건을 믿지 않는다
        }
        if ($needZero) {
            if ($ctx.fake) { $classicNow = $classicFake } else { $classicNow = [bool](Find-ClassicOutlook) }
            if ($ctx.fake) { $noprofNow = $noprofFake } else { $noprofNow = ($classicNow -and (Get-OutlookProfileState).usable -eq 0) }
            if (-not $ctx.fake) { $newOl = Test-NewOutlookTrace }
            $zr = Get-ZeroItemsReason $false $classicNow ([bool]$newOl) $noprofNow
            foreach ($k in $kinds) { if ($ctx.kindFatal[$k] -eq '?') { $ctx.kindFatal[$k] = $zr } }
        }
    }
    foreach ($k in $kinds) { Invoke-IndexKind $k $ctx }
    if ($script:Cursors.Count) {
        if ($script:Mixed) { Write-OutLine ('{"_cursor":' + (ConvertTo-J $script:Cursors) + '}') }
        else { foreach ($k in $script:Cursors.Keys) { Write-OutLine ('{"_cursor":' + (ConvertTo-J $script:Cursors[$k]) + '}') } }
    }
    $rcs = @($script:Results | ForEach-Object { [int]$_.rc })
    if ($rcs -contains 3) { $rc = 3 } elseif ($rcs -contains 0) { $rc = 0 } elseif ($rcs -contains 4) { $rc = 4 } else { $rc = 1 }
    $n = 0; foreach ($r in $script:Results) { $n += [int]$r.items_ok }
    Write-ErrLine ('[outlook-index] 레코드 {0}건 · rc {1}' -f $n, $rc)
} catch {
    $exitReason = $_.Exception.GetType().Name
    $rc = 3
    if ($script:Results.Count -eq 0) {
        $srcs = @('mail.index', 'cal.index')
        if ($Only -eq 'mail') { $srcs = @('mail.index') } elseif ($Only -eq 'cal') { $srcs = @('cal.index') }
        foreach ($s in $srcs) { $r = New-Result $s; $script:Results.Add($r) }
    }
    foreach ($r in $script:Results) { $r.rc = 3; Add-Reason $r 'R-TRANSPORT'; $r.counts['error'] = $exitReason }
    Write-ErrLine ('[outlook-index] 실패({0}) — 다음 실행에서 다시 시도합니다' -f $exitReason)
} finally {
    try { if ($ctx -and $ctx.conn) { $ctx.conn.Close() } } catch { }
}
Write-Results
exit $rc
