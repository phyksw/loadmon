# Test-OutlookCommon.ps1 - collect\OutlookCommon.ps1 순수 함수(주입 해시) + 수집기 끝단(자가검증·색인 가짜)을 돌려 값만 돌려준다.
# 단언은 tests\test_p1_outlook.py 가 한다. 실 Outlook·레지스트리·색인은 건드리지 않는다(-Reg 해시 · LM_OUTLOOK_SELFTEST 대신
# -SelfTest · LM_INDEX_FAKE + _my_addrs). 임시 폴더는 %TEMP%\lm28_t1_* 하나 - 끝에 지운다.
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
. (Join-Path $root 'collect\OutlookCommon.ps1')
$r = [ordered]@{}

# ── 1) Find-ClassicOutlook ─────────────────────────────────────────────────────
$c2rRoot = 'C:\Program Files\Microsoft Office'
$exeC2r = 'C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE'
$regC2r = @{
    'HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration|InstallationPath' = $c2rRoot
    "FILE|$exeC2r" = $true
    "VER|$exeC2r" = '16.0.19999.1'
}
$f = Find-ClassicOutlook $regC2r
$r.c2r_only = [ordered]@{ found = $f.found; c2r = $f.c2r; msi = $f.msi; ver = $f.ver; n = @($f.paths).Count }
# C2R 이 InstallRoot·App Paths 에 적은 자기 경로(V2) - MSI 로 세지 않는다
$reg2 = $regC2r.Clone()
$reg2['HKLM:\SOFTWARE\Microsoft\Office\16.0\Outlook\InstallRoot|Path'] = 'C:\Program Files\Microsoft Office\root\Office16\'
$reg2['HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE|(default)'] = '"' + $exeC2r + '"'
$f = Find-ClassicOutlook $reg2
$r.c2r_installroot = [ordered]@{ found = $f.found; c2r = $f.c2r; msi = $f.msi; n = @($f.paths).Count }
# MSI(32비트 2013)만
$exeMsi = 'C:\Program Files (x86)\Microsoft Office\Office15\OUTLOOK.EXE'
$f = Find-ClassicOutlook @{ 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Office\15.0\Outlook\InstallRoot|Path' = 'C:\Program Files (x86)\Microsoft Office\Office15\'; "FILE|$exeMsi" = $true }
$r.msi_only = [ordered]@{ found = $f.found; c2r = $f.c2r; msi = $f.msi; path = $f.path }
# COM LocalServer32(인자 붙음)로만 찾음
$clsid = '{0006F03A-0000-0000-C000-000000000046}'
$exeOdd = 'E:\Apps\Office16\OUTLOOK.EXE'
$f = Find-ClassicOutlook @{ 'HKCR:\Outlook.Application\CLSID|(default)' = $clsid; "HKCR:\CLSID\$clsid\LocalServer32|(default)" = ('"' + $exeOdd + '" /automation'); "FILE|$exeOdd" = $true }
$r.com_only = [ordered]@{ found = $f.found; path = $f.path; comReg = $f.comReg; msi = $f.msi }
$f = Find-ClassicOutlook @{}
$r.none = [ordered]@{ found = $f.found; comReg = $f.comReg; c2r = $f.c2r; msi = $f.msi }

# ── 2) 새 Outlook 흔적 · 프로필 · 사전 판정 ─────────────────────────────────────
$P16 = 'HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles'
$pkgKey = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'
$regNew = @{ 'HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences|UseNewOutlook' = 1 }
$trNew = Get-NewOutlookTrace $regNew
$trApp = Get-NewOutlookTrace @{ "$pkgKey|*" = @('Microsoft.WindowsCalculator_1_x64__8wekyb3d8bbwe', 'Microsoft.OutlookForWindows_1.0_x64__8wekyb3d8bbwe') }
$trNone = Get-NewOutlookTrace @{}
$trPol = Get-NewOutlookTrace @{ 'HKCU:\Software\Policies\Microsoft\Office\16.0\Outlook\Options\General|DoNewOutlookAutoMigration' = 1 }
$r.trace = [ordered]@{ useNew = $trNew.useNew; anyNew = $trNew.any; appx = $trApp.appx; anyApp = $trApp.any; none = $trNone.any; autoMig = $trPol.autoMig }
$prof0 = Get-OutlookProfileState @{}
$prof2 = Get-OutlookProfileState @{ "$P16|*" = @('Outlook', 'Work') }
$ab = "$P16\AB\9375CFF0413111d3B88A00104B2A6676"
$profAb = Get-OutlookProfileState @{ "$P16|*" = @('AB'); "$ab|*" = @('00000001');
                                     "$ab\00000001|clsid" = '{ED475414-B0D6-11D2-8C3B-00104B2A6676}'; "$ab\00000001|Service Name" = 'CONTAB' }
$ex = "$P16\Corp\9375CFF0413111d3B88A00104B2A6676"
$profEx = Get-OutlookProfileState @{ "$P16|*" = @('Corp'); "$ex|*" = @('00000002');
                                     "$ex|{ED475418-B0D6-11D2-8C3B-00104B2A6676}" = [byte[]](2, 0, 0, 0);
                                     "$ex\00000002|clsid" = '{ED475414-B0D6-11D2-8C3B-00104B2A6676}'; "$ex\00000002|Service Name" = 'MSEMS' }
$profCv = Get-OutlookProfileState @{ 'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles|*' = @('Old'); 'HKCR:\Outlook.Application\CurVer|(default)' = 'Outlook.Application.16' }
$r.profiles = [ordered]@{ p0 = $prof0.total; p2 = $prof2.total; p2u = $prof2.usable; locs2 = @($prof2.locs); ab = $profAb.total; abu = $profAb.usable;
                          ex = $profEx.usable; cvMismatch = $profCv.curverMismatch; cvLocs = @($profCv.locs) }
$clsOk = @{ found = $true; comReg = $true }
$clsNone = @{ found = $false; comReg = $false }
$r.verdict = [ordered]@{
    newol      = Get-ProfileVerdict -Running $false -Prof $prof0 -Trace $trNew -Classic $clsOk          # 프로필 0 + UseNewOutlook + 미실행
    newol_appx = Get-ProfileVerdict -Running $false -Prof $prof0 -Trace $trApp -Classic $clsNone        # 앱 패키지만 + 클래식 없음
    noprof     = Get-ProfileVerdict -Running $false -Prof $prof0 -Trace $trNone -Classic $clsOk         # 흔적 없음
    noclassic  = Get-ProfileVerdict -Running $false -Prof $prof0 -Trace $trNone -Classic $clsNone
    classic2   = Get-ProfileVerdict -Running $false -Prof $prof2 -Trace $trNew -Classic $clsOk          # 클래식 + UseNewOutlook + 프로필 2
    pol        = Get-ProfileVerdict -Running $false -Prof $prof2 -Trace $trPol -Classic $clsOk          # 전환 정책 + 미실행
    pol_run    = Get-ProfileVerdict -Running $true -Prof $prof2 -Trace $trPol -Classic $clsOk           # 떠 있으면 붙어 본다
    run0       = Get-ProfileVerdict -Running $true -Prof $prof0 -Trace $trNone -Classic $clsOk
    abonly     = Get-ProfileVerdict -Running $false -Prof $profAb -Trace $trNone -Classic $clsOk        # 주소록만(긍정 증거)
    exch       = Get-ProfileVerdict -Running $false -Prof $profEx -Trace $trNone -Classic $clsOk
}

# ── 3) 날짜 필터 카나리아 ────────────────────────────────────────────────────────
$sPlain = Select-DaslFormat -Probe { param($f) if ($f -eq 'plain') { return $true }; if ($f -eq 'iso') { throw 'bad literal' }; return $false }
$sFail = Select-DaslFormat -Probe { param($f) if ($f -eq 'iso') { throw 'bad literal' }; return $false }
$sNone = Select-DaslFormat -Probe { param($f) return $null }
$sG = Select-DaslFormat -Probe { param($f) return $true }
$r.canary = [ordered]@{ plain_fmt = $sPlain.fmt; plain = $sPlain.canary; fail = $sFail.canary; fail_fmt = $sFail.fmt; none = $sNone.canary;
                        none_fmt = $sNone.fmt; g = $sG.fmt; formats = @($script:OC_FORMATS);
                        plain_literal = (Format-OlDate ([datetime]'2026-03-05 14:07') 'plain'); iso_literal = (Format-OlDate ([datetime]'2026-03-05 14:07') 'iso') }

# ── 4) Test-MonthDone · ranges ──────────────────────────────────────────────────
$now = [datetime]'2026-10-07 12:00'
$mS = [datetime]'2026-03-01'; $mE = [datetime]'2026-04-01'
$v1 = Test-MonthDone -Rows 0 -Canary 'ok' -Oldest ([datetime]'2025-01-10 09:00') -Newest $now.AddHours(-1) -Start $mS -End $mE -Now $now
$v2 = Test-MonthDone -Rows 0 -Canary 'ok' -Oldest ([datetime]'2026-05-10 09:00') -Newest $now.AddHours(-1) -Start $mS -End $mE -Now $now
$v3 = Test-MonthDone -Rows 5 -Canary 'ok' -Oldest ([datetime]'2026-03-15 08:00') -Newest $now.AddHours(-1) -Start $mS -End $mE -Now $now
$v4 = Test-MonthDone -Rows 0 -Canary 'none' -Oldest $null -Newest $null -Start $mS -End $mE -Now $now -Cached $false
$v5 = Test-MonthDone -Rows 3 -Canary 'ok' -Oldest ([datetime]'2025-01-10') -Newest $now -Start $mS -End $mE -Now $now -Mismatch 2
$cS = [datetime]'2026-10-01'; $cE = [datetime]'2026-10-08'
$v6 = Test-MonthDone -Rows 0 -Canary 'ok' -Oldest ([datetime]'2025-01-10') -Newest ([datetime]'2026-10-02 18:00') -Start $cS -End $cE -Now $now -StaleH 72
$v7 = Test-MonthDone -Rows 0 -Canary 'ok' -Oldest ([datetime]'2025-01-10') -Newest ([datetime]'2026-10-02 18:00') -Start $cS -End $cE -Now $now -StaleH 72 -Cached $false
$v8 = Test-MonthDone -Rows 0 -Canary 'ok' -Start $mS -End $mE -Now $now -Stopped $true
$v9 = Test-MonthDone -Rows 4 -Canary 'none' -Start $mS -End $mE -Now $now -Cached $false
function Seg($v) { return [ordered]@{ done = [bool]$v.done; st = [string]$v.st } }
$r.month = [ordered]@{ zero_ok = Seg $v1; before_horizon = Seg $v2; horizon_inside = Seg $v3; no_canary = Seg $v4; mismatch = Seg $v5;
                       stale = Seg $v6; online = Seg $v7; stopped = Seg $v8; rows_no_canary = Seg $v9 }
$r.month_ranges = [ordered]@{
    horizon_inside = @(ConvertTo-LmRanges 'mail_in' $mS $mE $v3)
    stale          = @(ConvertTo-LmRanges 'mail_in' $cS $cE $v6)
    before_horizon = @(ConvertTo-LmRanges 'mail_out' $mS $mE $v2)
    days           = @(ConvertTo-DayRanges 'mail_in' @('2026-03-02', '2026-03-01', '2026-03-03', '2026-03-05', '2026-03-03') 'ok')
}

# ── 5) 완료 표 판 검사 ───────────────────────────────────────────────────────────
$ver = 'LM28-COM-1|1'
$jOk = [pscustomobject]@{ version = 3; ver = $ver; writer = 'com'; store_subject = $true }
$jVer = [pscustomobject]@{ version = 3; ver = 'LM28-COM-1|0'; writer = 'com'; store_subject = $true }
$jLm24 = [pscustomobject]@{ version = 2; writer = 'com'; store_subject = $true }
$jW = [pscustomobject]@{ version = 3; ver = $ver; writer = 'selftest'; store_subject = $true }
$r.coverage = [ordered]@{ ok = (Test-CoverageUsable $jOk $ver 'com' $true).ok; ver_mismatch = (Test-CoverageUsable $jVer $ver 'com' $true).ok;
                          lm24 = (Test-CoverageUsable $jLm24 $ver 'com' $true).ok; writer = (Test-CoverageUsable $jW $ver 'com' $true).ok;
                          none = (Test-CoverageUsable $null $ver 'com' $true).ok }

# ── 6) 보호 멤버 ─────────────────────────────────────────────────────────────────
$r.prot = [ordered]@{
    always_warn = Test-ProtectedSafe -Reg @{ 'HKLM:\SOFTWARE\Microsoft\Office\16.0\Outlook\Security|ObjectModelGuard' = 1 } -Av $null
    prompt      = Test-ProtectedSafe -Reg @{ 'HKCU:\Software\Policies\Microsoft\Office\16.0\Outlook\Security|PromptOOMAddressInformationAccess' = 1 } -Av $null
    deny        = Test-ProtectedSafe -Reg @{ 'HKLM:\SOFTWARE\Policies\Microsoft\Office\16.0\Outlook\Security|PromptOOMAddressBookAccess' = 0 } -Av $null
    approve     = Test-ProtectedSafe -Reg @{ 'HKCU:\Software\Policies\Microsoft\Office\16.0\Outlook\Security|PromptOOMAddressInformationAccess' = 2 } -Av @(0x060100)
    no_info     = Test-ProtectedSafe -Reg @{} -Av $null
    av_empty    = Test-ProtectedSafe -Reg @{} -Av @()
    av_off      = Test-ProtectedSafe -Reg @{} -Av @(0x060100)
    av_old      = Test-ProtectedSafe -Reg @{} -Av @(0x061110)
    av_ok       = Test-ProtectedSafe -Reg @{} -Av @(0x060100, 0x061100)
    why_off     = (Get-ProtectedState -Reg @{} -Av @(0x060100)).why
}

# ── 7) 메일 폴더 재귀 ─────────────────────────────────────────────────────────────
function N([string]$id, [string]$name, [int]$type = 0, [int]$count = 1, $kids = @()) {
    return [pscustomobject]@{ EntryID = $id; Name = $name; DefaultItemType = $type; Items = [pscustomobject]@{ Count = $count }; Folders = @($kids) }
}
$tree = N 'ROOT' 'root' 0 0 @(
    (N 'DEL' '지운 편지함' 0 5 @((N 'DELSUB' 'kept deleted' 0 2))),
    (N 'OUT' 'Outbox' 0 1), (N 'DRAFT' 'Drafts' 0 1),
    (N 'SYNC' 'Sync Issues' 0 1 @((N 'CONF' 'Conflicts' 0 1), (N 'LOCF' 'Local Failures' 0 1), (N 'SRVF' 'Server Failures' 0 1))),
    (N 'JUNK' 'Junk Email' 0 1), (N 'RSS' 'RSS Feeds' 0 1), (N 'CONVH' '대화 기록' 0 3),
    (N 'CAL' 'Calendar' 1 10),
    (N 'ARCH' 'Archive' 0 7),
    (N 'INBOX' 'Inbox' 0 10 @((N 'PROJ' 'Projects' 0 3 @((N 'EMPTY' 'empty' 0 0 @((N 'DEEP' 'deep' 0 2))))))),
    (N 'SENT' 'Sent Items' 0 4 @((N 'SENTSUB' 'old sent' 0 2)))
)
$defs = @{ 6 = 'INBOX'; 5 = 'SENT'; 3 = 'DEL'; 4 = 'OUT'; 16 = 'DRAFT'; 19 = 'CONF'; 20 = 'SYNC'; 21 = 'LOCF'; 22 = 'SRVF'; 23 = 'JUNK'; 25 = 'RSS' }
$fl = Get-MailFolderList -Root $tree -Defaults $defs
$flCap = Get-MailFolderList -Root $tree -Defaults $defs -Max 3
# 19~22 가 하위 폴더로만 있어도 제외되는지(상위 SYNC 를 기본 폴더 목록에서 빼고 본다)
$defs2 = $defs.Clone(); $defs2.Remove(20)
$fl2 = Get-MailFolderList -Root $tree -Defaults $defs2
$r.folders = [ordered]@{
    skip_ids = @($script:OC_SKIP_FOLDERS)
    list = @($fl.folders | ForEach-Object { $_.name + ':' + $_.box + ':' + $_.role })
    excluded = $fl.excluded; empty = $fl.empty; capped = $fl.capped
    cap_n = @($flCap.folders).Count; cap_capped = $flCap.capped
    list2 = @($fl2.folders | ForEach-Object { $_.name })
    key_len = @($fl.folders | ForEach-Object { ([string]$_.key).Length } | Select-Object -Unique)
}

# ── 8) 색인 주 저장소 ─────────────────────────────────────────────────────────────
$my = @('me@corp.example', '홍길동')
$scName = Get-StoreScope -Paths @('\\홍길동\Inbox', '\\홍길동\Sent Items', '\\홍길동\Inbox\Projects') -My $my
$scAddr = Get-StoreScope -Paths @('\\me@corp.example\Inbox', '\\shared@corp.example\Inbox', '\Inbox\sub') -My $my
$r.store = [ordered]@{
    name_mode = $scName.mode; name_other = @(@('\\홍길동\Inbox', '\\홍길동\Sent Items') | Where-Object { Test-OtherStore $_ $scName }).Count
    addr_mode = $scAddr.mode; addr_stores = @($scAddr.stores)
    addr_own = (Test-OtherStore '\\Me@Corp.example\Inbox\a' $scAddr); addr_shared = (Test-OtherStore '\\shared@corp.example\Inbox' $scAddr)
    addr_nostore = (Test-OtherStore '\받은 편지함\b' $scAddr)
}

# ── 9) LMSTATUS 한 줄 ────────────────────────────────────────────────────────────
$line = Format-LmStatus -Src 'com' -Rc 3 -Reasons @('R-FILTER', 'R-NOADDR', 'R-FILTER') -Counts ([ordered]@{ filter_fmt = ''; profile_locs = @('16.0'); ol = [ordered]@{ c2r = $true } }) `
                        -Ranges @([ordered]@{ axis = 'mail_in'; from = '2026-03-01'; to = '2026-03-31'; st = 'blocked' })
$r.status_line = $line
$r.status_line_empty = Format-LmStatus -Src 'index' -Rc 1

# ── 10) 수집기 끝단(임시 폴더 - 실 Outlook·색인 없음) ─────────────────────────────
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('lm28_t1_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$gd = Join-Path $root 'collect\Get-OutlookData.ps1'
$gi = Join-Path $root 'collect\Get-OutlookIndex.ps1'
function Run-Col([string]$script, [hashtable]$argv) {
    # 같은 PowerShell 안에서 수집기를 돌린다(프로세스를 띄우지 않는다) - Write-Host(6)·오류(2)를 줄로 모은다
    $lines = @(& $script @argv 6>&1 2>&1 | ForEach-Object { [string]$_ })
    return @{ rc = $LASTEXITCODE; lines = $lines; last = $(if ($lines.Count) { $lines[-1] } else { '' }) }
}
$oldFake = $env:LM_INDEX_FAKE; $oldSt = $env:LM_OUTLOOK_SELFTEST
try {
    $env:LM_OUTLOOK_SELFTEST = $null
    $today = (Get-Date).Date
    $from = (New-Object DateTime ($today.Year, $today.Month, 1)).AddMonths(-2).ToString('yyyy-MM-dd')
    $to = $today.ToString('yyyy-MM-dd')
    $comDir = Join-Path $tmp 'src'
    $a = @{ SelfTest = 4; From = $from; To = $to; OutDir = $comDir; Tag = 'com'; BudgetSec = 120 }
    $c1 = Run-Col $gd $a
    $cov = Join-Path $comDir 'coverage_com.json'
    $c1files = @(Get-ChildItem -LiteralPath $comDir -File | ForEach-Object { $_.Name } | Sort-Object)
    # 색인이 같은 폴더에 자기 상태 파일을 쓴 뒤에도 COM 표가 남고 쓰인다(P5 - 132-139 규칙 삭제)
    Set-Content -LiteralPath (Join-Path $comDir 'mail_source_index.json') -Value '{"source":"index","mail":3}' -Encoding UTF8
    $a.NoRefresh = $true
    $c2 = Run-Col $gd $a
    $covKept = Test-Path -LiteralPath $cov
    # 판이 다르면(규칙 변경·cursorEpoch) 표를 버리고 다시 읽는다
    $cj = Get-Content -Raw -Encoding UTF8 $cov | ConvertFrom-Json
    $cj.ver = 'LM28-COM-0|1'
    ($cj | ConvertTo-Json -Depth 7) | Set-Content -LiteralPath $cov -Encoding UTF8
    $c3 = Run-Col $gd $a
    $src1 = Get-Content -Raw -Encoding UTF8 (Join-Path $comDir 'mail_source_com.json') | ConvertFrom-Json
    $r.com = [ordered]@{ rc1 = $c1.rc; last1 = $c1.last; files = $c1files; rc2 = $c2.rc; last2 = $c2.last; cov_kept = $covKept; rc3 = $c3.rc; last3 = $c3.last;
                         src_keys = @($src1.PSObject.Properties | ForEach-Object { $_.Name }); src_source = $src1.source;
                         data_untouched = -not (Test-Path -LiteralPath (Join-Path $comDir 'mail.csv')) }

    # 색인 가짜 - 주 저장소·반복 마스터·리터럴 여유·막힘 사유
    $ix = Join-Path $tmp 'ix'
    function Run-Idx($fakeObj) {
        $fp = Join-Path $tmp ('fake_' + [guid]::NewGuid().ToString('N').Substring(0, 6) + '.json')
        ($fakeObj | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $fp -Encoding UTF8
        $env:LM_INDEX_FAKE = $fp
        return (Run-Col $gi @{ From = '2026-09-01'; To = '2026-09-30'; OutDir = $ix; Tag = 'index' })
    }
    $mailRows = @(
        [ordered]@{ 'System.ItemUrl' = 'mapi://x/1'; 'System.ItemFolderPathDisplay' = '\\me@corp.example\Inbox'; 'System.ItemDate' = '2026-09-02 10:00'; 'System.Message.DateReceived' = '2026-09-02 10:00'; 'System.Message.FromName' = 'A'; 'System.Message.ToAddress' = 'me@corp.example'; 'System.Subject' = 's1' },
        [ordered]@{ 'System.ItemUrl' = 'mapi://x/2'; 'System.ItemFolderPathDisplay' = '\\me@corp.example\Sent Items'; 'System.ItemDate' = '2026-09-03 11:00'; 'System.Message.DateSent' = '2026-09-03 11:00'; 'System.Message.FromName' = 'Me'; 'System.Subject' = 's2' },
        [ordered]@{ 'System.ItemUrl' = 'mapi://x/3'; 'System.ItemFolderPathDisplay' = '\\shared@corp.example\Inbox'; 'System.ItemDate' = '2026-09-02 12:00'; 'System.Message.DateReceived' = '2026-09-02 12:00'; 'System.Message.FromName' = 'B'; 'System.Subject' = 's3' },
        [ordered]@{ 'System.ItemUrl' = 'mapi://x/4'; 'System.ItemFolderPathDisplay' = '\\me@corp.example\Inbox'; 'System.ItemDate' = '2026-08-31 23:00'; 'System.Message.DateReceived' = '2026-08-31 23:00'; 'System.Message.FromName' = 'C'; 'System.Subject' = 's4' }
    )
    $calRows = @(
        [ordered]@{ 'System.ItemUrl' = 'mapi://x/c1'; 'System.ItemFolderPathDisplay' = '\\me@corp.example\Calendar'; 'System.StartDate' = '2026-09-04 10:00'; 'System.EndDate' = '2026-09-04 11:00'; 'System.Subject' = 'm1'; 'System.Calendar.IsRecurring' = $false },
        [ordered]@{ 'System.ItemUrl' = 'mapi://x/c2'; 'System.ItemFolderPathDisplay' = '\\me@corp.example\Calendar'; 'System.StartDate' = '2026-01-05 09:00'; 'System.EndDate' = '2026-12-31 10:00'; 'System.Subject' = 'weekly'; 'System.Calendar.IsRecurring' = $true }
    )
    $i1 = Run-Idx ([ordered]@{ _my_addrs = @('me@corp.example'); mail = $mailRows; calendar = $calRows })
    $i1mail = @(Get-Content -LiteralPath (Join-Path $ix 'mail_index.csv') -Encoding UTF8 | Where-Object { $_ })
    $i1src = Get-Content -Raw -Encoding UTF8 (Join-Path $ix 'mail_source_index.json') | ConvertFrom-Json
    # 표시명 저장소(주소 일치 0건) → 전부 받고 store_scope=unknown
    $nameRows = @($mailRows[0..2] | ForEach-Object { $h = [ordered]@{}; foreach ($k in $_.Keys) { $h[$k] = $_[$k] }; $h['System.ItemFolderPathDisplay'] = ($h['System.ItemFolderPathDisplay'] -replace '^\\\\[^\\]+', '\\홍길동'); $h })
    $i2 = Run-Idx ([ordered]@{ _my_addrs = @('me@corp.example'); mail = $nameRows; calendar = @($calRows[0]) })
    $i3 = Run-Idx ([ordered]@{ _my_addrs = @('me@corp.example'); _error = 'noidx'; mail = @(); calendar = @() })
    $i4 = Run-Idx ([ordered]@{ _my_addrs = @('me@corp.example'); _policy = 1; mail = $mailRows; calendar = @() })
    $i5 = Run-Idx ([ordered]@{ _my_addrs = @('me@corp.example'); mail = @(); calendar = @() })
    $capRows = @($mailRows[1], $mailRows[0], [ordered]@{ 'System.ItemUrl' = 'mapi://x/5'; 'System.ItemFolderPathDisplay' = '\\me@corp.example\Inbox'; 'System.ItemDate' = '2026-09-01 08:00'; 'System.Message.DateReceived' = '2026-09-01 08:00'; 'System.Subject' = 's5' })
    $i6 = Run-Idx ([ordered]@{ _my_addrs = @('me@corp.example'); _cap = 2; mail = $capRows; calendar = @($calRows[0]) })
    $r.index = [ordered]@{ rc1 = $i1.rc; last1 = $i1.last; mail_lines = $i1mail.Count; src_store = $i1src.store_scope; src_source = $i1src.source;
                           rc2 = $i2.rc; last2 = $i2.last; rc3 = $i3.rc; last3 = $i3.last; rc4 = $i4.rc; last4 = $i4.last;
                           rc5 = $i5.rc; last5 = $i5.last; rc6 = $i6.rc; last6 = $i6.last;
                           lm24_files_absent = -not (Test-Path -LiteralPath (Join-Path $ix 'mail.csv')) }
} finally {
    $env:LM_INDEX_FAKE = $oldFake; $env:LM_OUTLOOK_SELFTEST = $oldSt
    try { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction Stop } catch {}
    $r.tmp_removed = -not (Test-Path -LiteralPath $tmp)
}
return $r
