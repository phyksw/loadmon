# OutlookCommon.ps1 - Outlook 수집기 공용 함수(dot-source). Get-OutlookData·Diagnose-Collectors 가 함께 쓴다.
# LM27 Get-OutlookCom.ps1 의 판 판정(Find-ClassicOutlook·전환 정책·프로필 상태)·필터 카나리아·메일 폴더 재귀·지평선 판정을
# 한 벌로 모았다. AF32(D1): 이 PC 를 훑지 않는다 - 레지스트리·프로세스는 Outlook 을 붙이거나 띄울 수 있는지(띄우면 모달이
#   확실한지)만 보고, 창 제목·백신·보안 센터·정책 목록은 읽지 않는다. 보호 멤버(주소) 읽기는 실제로 한 번 읽어 보고 정한다.
# 원칙(LM24 와 같다): 판 판정은 진단과 사유 표기에만 쓰고, 수집은 먼저 시도한 결과로 판정한다. 띄우면 모달이 확실한 경우
#   (Outlook 미실행 + 프로필 0 · 관리자 전환 정책)만 시도하지 않는다. 실측 전 '불가'는 '의심'으로 적는다.
# 순수 함수 위주 - 레지스트리·파일·프로세스는 -Reg 해시로 주입할 수 있다(시험: tests\ps\Test-OutlookCommon.ps1).
#   -Reg 키: '<키>|<값 이름>' = 값 · '<키>|*' = 하위 키 이름 목록 · 'FILE|<경로>' = $true(있는 파일) · 'VER|<경로>' = 파일 판 ·
#   'PROC|<이름>' = $true(실행 중). <키> 는 'HKLM:\…' · 'HKCU:\…' · 'HKCR:\…' 꼴. $Reg 를 주면 실제 레지스트리를 읽지 않는다.
# 이 파일은 프로세스를 띄우지 않는다(Add-Type·외부 명령 없음 - 개발 PC 는 끝난 프로세스가 커널에 남는다). CIM 은 인프로세스.
# 목록 규칙: 제네릭 List 는 [List[T]]::new() 로 만든다 - New-Object 로 만든(PSObject 로 싼) List[object] 를 @($list) 로 바꾸면
#   'Argument types do not match' 예외가 난다(PS 5.1·7 실측, List[string] 은 괜찮다 - try 안이면 조용히 삼켜진다).
# 수집기 마지막 줄: AF32STATUS {"v":1,"src","rc","reason","counts","ranges":[{"axis","from","to","st"}]} (Format-LmStatus)
#   rc 0 정상 · 1 대상 없음 · 3 불가·불완전·시작 거부(reason 필수) · 4 설정 거부(사내 도메인 없음 R-NODOMAIN).
#   reason = 사유 코드를 쉼표로(첫 코드가 주 사유).
#   axis = mail_in · mail_out · cal, from·to = 'yyyy-MM-dd'(둘 다 포함), st = ok · zero_ok · partial · unverified ·
#   out_of_horizon · blocked.

$script:OC_FORMATS = @('g', 'plain', 'iso')              # Restrict 날짜 리터럴 형식(카나리아가 이 순서로 시험)
# 메일 폴더 재귀에서 빼는 기본 폴더(OlDefaultFolders): 3 지운 편지함 · 4 보낼 편지함 · 16 임시 보관함 · 19 충돌 ·
# 20 동기화 문제 · 21 로컬 실패 · 22 서버 실패 · 23 정크 메일 · 25 RSS 피드 - 하위 폴더 포함
$script:OC_SKIP_FOLDERS = @(3, 4, 16, 19, 20, 21, 22, 23, 25)
$script:OC_CONV_HISTORY = @('대화 기록', 'Conversation History')   # Skype·Lync IM 대화록(기본 폴더 번호가 없어 이름으로)
$script:OC_FOLDERS_MAX = 3000
$script:OC_INBOX_RX = '^(받은\s*(편지함|메일함)|Inbox)$'
$script:OC_SENT_RX = '^(보낸\s*(편지함|메일함|항목)|Sent(\s+(Items|Mail|Messages))?)$'
$script:OC_CAL_RX = '^(일정|Calendar)$'
$script:OC_ADDR_RX = '^[^@\s<>"]+@[^@\s<>"]+\.[^@\s<>"]+$'
# 공용 개인 메일 도메인 - 사내 도메인이 될 수 없다(D7). core\afcfg.py PERSONAL_MAIL_DOMAINS 와 같은 목록이다 - 하나를 바꾸면 둘 다 바꾼다
$script:OC_PERSONAL_DOMAINS = @('gmail.com', 'naver.com', 'daum.net', 'hanmail.net', 'kakao.com', 'nate.com', 'outlook.com',
                                'hotmail.com', 'live.com', 'yahoo.com', 'icloud.com', 'me.com', 'proton.me')

# ── 주입 가능한 읽기(레지스트리·파일·프로세스) ─────────────────────────────────────────────
function ConvertTo-OcRegPath([string]$Key) {
    if ($Key -match '^HKCR:\\') { return ('Registry::HKEY_CLASSES_ROOT\' + $Key.Substring(6)) }   # HKCR: 드라이브는 기본으로 없다
    return $Key
}
function Get-OcReg($Reg, [string]$Key, [string]$Name) {
    # 레지스트리 값 하나(없으면 $null). 기본값은 Name '(default)'.
    if ($null -ne $Reg) { $k = $Key + '|' + $Name; if ($Reg.ContainsKey($k)) { return $Reg[$k] }; return $null }
    try {
        $p = Get-ItemProperty -LiteralPath (ConvertTo-OcRegPath $Key) -ErrorAction Stop
        if ($p.PSObject.Properties[$Name]) { return $p.PSObject.Properties[$Name].Value }
    } catch {}
    return $null
}
function Get-OcSubKeys($Reg, [string]$Key) {
    if ($null -ne $Reg) { $k = $Key + '|*'; if ($Reg.ContainsKey($k)) { return @($Reg[$k]) }; return @() }
    try { return @(Get-ChildItem -LiteralPath (ConvertTo-OcRegPath $Key) -ErrorAction Stop | ForEach-Object { $_.PSChildName }) } catch { return @() }
}
function Test-OcKey($Reg, [string]$Key) {
    if ($null -ne $Reg) {
        foreach ($k in $Reg.Keys) { if (([string]$k).StartsWith($Key + '|', [StringComparison]::OrdinalIgnoreCase)) { return $true } }
        return $false
    }
    try { return [bool](Test-Path -LiteralPath (ConvertTo-OcRegPath $Key)) } catch { return $false }
}
function Test-OcFile($Reg, [string]$Path) {
    if ($null -ne $Reg) { return [bool]$Reg['FILE|' + $Path] }
    try { return [bool](Test-Path -LiteralPath $Path -PathType Leaf) } catch { return $false }
}
function Test-OcProc($Reg, [string]$Name) {
    if ($null -ne $Reg) { return [bool]$Reg['PROC|' + $Name] }
    try { return [bool](Get-Process -Name $Name -ErrorAction SilentlyContinue) } catch { return $false }
}
function Get-OcCfg($Cfg, [string]$Sec, [string]$Key, $Default) {
    # config.json 의 섹션 키 하나(없으면 기본값 - 새 키는 config.default.json 에만 있고 개인 config.json 에는 없을 수 있다)
    try {
        $s = $Cfg.PSObject.Properties[$Sec]
        if ($s -and $null -ne $s.Value) { $v = $s.Value.PSObject.Properties[$Key]; if ($v -and $null -ne $v.Value) { return $v.Value } }
    } catch {}
    return $Default
}
function Get-OcCfgList($Cfg, [string]$Sec, [string]$Key, [string[]]$Default) {
    # config.json 의 섹션 목록 키(문자열 목록) - 없으면 기본값. 빈 값은 뺀다.
    $v = Get-OcCfg $Cfg $Sec $Key $null
    if ($null -eq $v) { return @($Default) }
    return @(@($v) | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
}
function Test-OcNameHit([string]$Text, [string[]]$Words) {
    # 범주·폴더 이름이 제외 목록에 걸리나 - 범주는 ';'·',' 로 나눠 낱낱이 같을 때(대소문자 무시), 폴더 이름은 낱말을 품을 때
    if (-not $Text) { return $false }
    foreach ($w in $Words) {
        if (-not $w) { continue }
        if ($Text.IndexOf($w, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    }
    return $false
}
function Test-OcCategoryHit([string]$Categories, [string[]]$Words) {
    if (-not $Categories) { return $false }
    foreach ($c in ($Categories -split '[;,]')) {
        $c = $c.Trim()
        if (-not $c) { continue }
        foreach ($w in $Words) { if ($w -and $c -ieq $w) { return $true } }
    }
    return $false
}
function Test-OcElevated {
    # 관리자 권한(UAC 상승)으로 도는가 - 상승한 PowerShell 은 일반 권한 Outlook 의 COM(ROT)에 붙지 못한다
    try { return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) } catch { return $false }
}
function Get-OcHResult($Err) {
    # 예외 → '0x########'(안쪽 예외까지 풀어서). 원문 메시지는 남기지 않는다.
    $e = $Err
    if ($e -is [System.Management.Automation.ErrorRecord]) { $e = $e.Exception }
    try { while ($e.InnerException) { $e = $e.InnerException } } catch {}
    try { return ('0x{0:X8}' -f [int]$e.HResult) } catch { return '' }
}
function Get-OcKey([string]$s) {
    # 폴더 EntryID 같은 긴 값의 짧은 표식(sha1 앞 12자리) - 완료 표에 원문 대신 적는다
    $sha = [System.Security.Cryptography.SHA1]::Create()
    try { $h = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes([string]$s)) } finally { $sha.Dispose() }
    return ((($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12))
}
function Resolve-OcDir([string]$Root, [string]$Value, [string]$Default, [string]$Base, [switch]$Exact) {
    # 수집기 -OutDir·-RawDir 값 → 전체 경로 | ''(받지 않음). 값이 없으면 <설치 폴더>\$Default. 상대 경로는 설치 폴더 기준.
    # <설치 폴더>\$Base 아래만 받는다(-Exact 면 $Base 그 자체만) - '..'·다른 드라이브·UNC 는 GetFullPath 뒤 비교로 걸러진다.
    # 원자료가 G1·[중지]·보관기한 정리가 지우는 곳(data\outlook\raw) 밖에 남지 않게 한다.
    try {
        $rootF = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
        $baseF = [System.IO.Path]::GetFullPath((Join-Path $rootF $Base)).TrimEnd('\')
        $v = $(if ($Value) { $Value } else { $Default })
        $cand = $(if ([System.IO.Path]::IsPathRooted($v)) { $v } else { Join-Path $rootF $v })
        $cand = [System.IO.Path]::GetFullPath($cand).TrimEnd('\')
    } catch { return '' }
    if ($cand -ieq $baseF) { return $cand }
    if (-not $Exact -and $cand.StartsWith($baseF + '\', [StringComparison]::OrdinalIgnoreCase)) { return $cand }
    return ''
}
function Test-OcRestrictedList([string]$Path, $Today = $null) {
    # 제한 고객 목록 파일(D9 - privacy.restrictedCustomersFile)의 형식만 본다. 이름은 여기서 쓰지 않는다(G1 이 메모리에서 맞댄다).
    # 반환 @{ ok; why } - why: ok · missing(없음) · invalid(JSON·customers 목록·항목 꼴이 아님 - 항목은 name 또는 domains 가 든 개체 ·
    #   모르는 키가 있음) · template(배포 견본을 그대로 쓴 것 - '_template' 키가 있거나 confirmed 가 'YYYY-MM-DD' 자리표)
    #   · date(confirmed 가 실제 날짜가 아님 - 2026-99-99·0000-00-00) · future(confirmed 가 오늘보다 뒤).
    # core\privacy.py load_restricted 가 받지 않는 파일을 여기서 받지 않게 한다('_' 로 시작하는 키는 설명 - '_template' 만 견본 표식).
    # 이름 길이·약칭·도메인 꼴 같은 세부 검사는 파이썬(G1) 쪽이 한다 - 여기서 받은 파일도 거기서 받지 않으면 정제하지 않는다.
    $day = $(if ($Today) { ([datetime]$Today).Date } else { (Get-Date).Date })
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return @{ ok = $false; why = 'missing' } }
    $j = $null
    try {
        $txt = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        # 맨 위가 개체({…})가 아니면 받지 않는다 - 한 칸짜리 배열을 개체로 풀어 주는 PowerShell 판에서도 같은 판정이 되게 글로 먼저 본다
        if (-not $txt.TrimStart([char]0xFEFF, ' ', "`t", "`r", "`n").StartsWith('{', [StringComparison]::Ordinal)) { return @{ ok = $false; why = 'invalid' } }
        $j = $txt | ConvertFrom-Json
    } catch { $j = $null }
    if ($null -eq $j -or $j -isnot [System.Management.Automation.PSCustomObject]) { return @{ ok = $false; why = 'invalid' } }
    $ord = [StringComparison]::Ordinal
    foreach ($p in @($j.PSObject.Properties)) {
        if ($p.Name -ceq '_template') { return @{ ok = $false; why = 'template' } }      # 값과 상관없이 - 견본에서 그 줄을 지워야 목록이다
        if (-not $p.Name.StartsWith('_', $ord) -and @('confirmed', 'customers') -cnotcontains $p.Name) { return @{ ok = $false; why = 'invalid' } }
    }
    $conf = ([string]$j.confirmed).Trim()
    if ($conf -match '^(?i)y{4}-m{2}-d{2}$') { return @{ ok = $false; why = 'template' } }
    $cp = $j.PSObject.Properties['customers']
    if (-not $cp -or $null -eq $cp.Value -or $cp.Value -is [string] -or $cp.Value -isnot [System.Collections.IEnumerable]) { return @{ ok = $false; why = 'invalid' } }
    foreach ($c in @($cp.Value)) {
        if ($c -isnot [System.Management.Automation.PSCustomObject]) { return @{ ok = $false; why = 'invalid' } }
        foreach ($p in @($c.PSObject.Properties)) {
            if (-not $p.Name.StartsWith('_', $ord) -and @('name', 'aliases', 'domains') -cnotcontains $p.Name) { return @{ ok = $false; why = 'invalid' } }
        }
        $nm = ([string]$c.name).Trim()
        $dm = @(@($c.domains) | Where-Object { $_ -and ([string]$_).Trim() })
        if (-not $nm -and -not $dm.Count) { return @{ ok = $false; why = 'invalid' } }
    }
    if ($conf -notmatch '^\d{4}-\d{2}-\d{2}$') { return @{ ok = $false; why = 'invalid' } }
    $d = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($conf, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$d)) {
        return @{ ok = $false; why = 'date' }
    }
    if ($d.Date -gt $day) { return @{ ok = $false; why = 'future' } }
    return @{ ok = $true; why = 'ok' }
}

# ── 판 판정(진단·사유 표기 전용) ─────────────────────────────────────────────────────────
function Find-ClassicOutlook($Reg = $null) {
    # 클래식 Outlook(OUTLOOK.EXE) - 판(2010~365)·설치 방식(MSI·Click-to-Run)·32/64비트와 상관없이 찾는다(LM27 :1587 이식).
    # App Paths 한 곳만 보면 M365(C2R) PC 대부분에서 못 찾아 '새 Outlook 전용'으로 오판했다(현장 V1). C2R 이 InstallRoot 에 적은
    # 자기 경로를 'MSI 구판 병존'으로 세던 것(V2)은 c2r 로 센다. 반환 @{ found; path; paths; c2r; msi; ver; comReg; c2rRoot }.
    $cands = [System.Collections.Generic.List[string]]::new()
    foreach ($k in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE',
                     'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE',
                     'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE')) {
        $d = Get-OcReg $Reg $k '(default)'; if ($d) { $cands.Add([string]$d) }
    }
    foreach ($v in @('16.0', '15.0', '14.0')) {
        foreach ($b in @('HKLM:\SOFTWARE\Microsoft\Office', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Office')) {
            $ir = Get-OcReg $Reg "$b\$v\Outlook\InstallRoot" 'Path'
            if ($ir) { $cands.Add((Join-Path ([string]$ir) 'OUTLOOK.EXE')) }
        }
    }
    $c2rRoot = [string](Get-OcReg $Reg 'HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration' 'InstallationPath')
    if ($c2rRoot) { foreach ($o in @('Office16', 'Office15')) { $cands.Add((Join-Path $c2rRoot "root\$o\OUTLOOK.EXE")) } }
    $clsid = [string](Get-OcReg $Reg 'HKCR:\Outlook.Application\CLSID' '(default)')
    $curVer = [string](Get-OcReg $Reg 'HKCR:\Outlook.Application\CurVer' '(default)')
    if ($clsid) {
        foreach ($ck in @("HKCR:\CLSID\$clsid\LocalServer32", "HKLM:\SOFTWARE\WOW6432Node\Classes\CLSID\$clsid\LocalServer32")) {
            $ls = Get-OcReg $Reg $ck '(default)'; if ($ls) { $cands.Add([string]$ls) }
        }
    }
    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $pf) { continue }
        foreach ($o in @('root\Office16', 'root\Office15', 'Office16', 'Office15', 'Office14')) { $cands.Add((Join-Path $pf "Microsoft Office\$o\OUTLOOK.EXE")) }
    }
    $paths = [System.Collections.Generic.List[string]]::new()
    foreach ($c in $cands) {
        $s = ([string]$c).Trim()
        try { $s = [Environment]::ExpandEnvironmentVariables($s) } catch {}
        if ($s.StartsWith('"')) {
            $e = $s.IndexOf('"', 1)
            if ($e -gt 1) { $s = $s.Substring(1, $e - 1) } else { $s = $s.Trim('"') }
        } else {
            $i = $s.ToLowerInvariant().IndexOf('.exe')
            if ($i -gt 0) { $s = $s.Substring(0, $i + 4) }                      # LocalServer32 의 '/automation' 같은 인자 떼기
        }
        if (-not $s) { continue }
        $dup = $false
        foreach ($p in $paths) { if ($p -ieq $s) { $dup = $true; break } }
        if (-not $dup -and (Test-OcFile $Reg $s)) { $paths.Add($s) }
    }
    $r = @{ found = ($paths.Count -gt 0); path = ''; paths = @($paths); c2r = $false; msi = $false; ver = '';
            comReg = [bool]($clsid -or $curVer); curVer = $curVer; c2rRoot = $c2rRoot }
    $rootN = ''
    if ($c2rRoot) { $rootN = $c2rRoot.TrimEnd('\') + '\' }
    foreach ($p in $paths) {
        # C2R 배치(…\root\Office16\)거나 C2R 설치 폴더 아래면 c2r, 그 밖에 실존하는 OUTLOOK.EXE 가 있을 때만 msi
        if (($rootN -and $p.StartsWith($rootN, [StringComparison]::OrdinalIgnoreCase)) -or $p -match '(?i)\\root\\Office1\d\\') { $r.c2r = $true }
        else { $r.msi = $true }
    }
    if ($r.found) {
        $r.path = $paths[0]
        if ($null -ne $Reg) { $r.ver = [string]$Reg['VER|' + $r.path] }
        else { try { $r.ver = [string](Get-Item -LiteralPath $r.path).VersionInfo.ProductVersion } catch {} }
    }
    return $r
}

function Get-MigrationPolicy($Reg = $null) {
    # 관리자 주도 새 Outlook 전환 정책(LM27 :1571) - 정책 키가 사용자 키보다 우선. DoNewOutlookAutoMigration=1 이면 클래식을 띄울 때
    # 전환 안내(마지막 단계는 막는 프롬프트)가 뜬다. NewOutlookAutoMigrationRetryIntervals 는 진단에만 적는다.
    $r = @{ auto = $null; retry = $null }
    foreach ($k in @('HKCU:\Software\Policies\Microsoft\Office\16.0\Outlook\Options\General',
                     'HKCU:\Software\Microsoft\Office\16.0\Outlook\Options\General')) {
        if ($null -eq $r.auto) { $v = Get-OcReg $Reg $k 'DoNewOutlookAutoMigration'; if ($null -ne $v) { try { $r.auto = [int]$v } catch {} } }
        if ($null -eq $r.retry) { $v = Get-OcReg $Reg $k 'NewOutlookAutoMigrationRetryIntervals'; if ($null -ne $v) { try { $r.retry = [int]$v } catch {} } }
    }
    return $r
}

function Get-NewOutlookTrace($Reg = $null) {
    # 새 Outlook(olk) 흔적 3가지 + 전환 정책. 반환 @{ useNew; olk; appx; autoMig; migRetry; any }.
    # 흔적만으로 수집을 막지 않는다 - 클래식이 있으면 COM 으로 읽는다(LM24). 프로필 0 일 때 R-NOPROF 대신 R-NEWOL 로 적는 데 쓴다.
    $r = @{ useNew = $false; olk = $false; appx = $false; autoMig = $null; migRetry = $null; any = $false }
    foreach ($k in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
        $v = Get-OcReg $Reg $k 'UseNewOutlook'
        if ($null -ne $v) { try { if ([int]$v -eq 1) { $r.useNew = $true } } catch {} }
    }
    $r.olk = Test-OcProc $Reg 'olk'
    # 설치된 앱 패키지(Get-AppxPackage 대신 사용자 레지스트리 - 빠르고 모듈을 불러오지 않는다)
    $pk = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'
    $r.appx = [bool](@(Get-OcSubKeys $Reg $pk | Where-Object { [string]$_ -like 'Microsoft.OutlookForWindows_*' }).Count)
    $mig = Get-MigrationPolicy $Reg
    $r.autoMig = $mig.auto; $r.migRetry = $mig.retry
    $r.any = ($r.useNew -or $r.olk -or $r.appx)
    return $r
}

function Get-OutlookProfileState($Reg = $null) {
    # Outlook 프로필 수와 '쓸 수 있는' 프로필 수(LM27 :1511 이식). '쓸 수 없음'은 주소록만 든 긍정 증거가 있을 때만 센다: 메일 계정
    # 목록{ED475418}·데이터 파일 목록{ED475420}이 비었고, 계정이 모두 주소록(LDAP 계정 CLSID 또는 서비스 이름 CONTAB·EMABLT)이며,
    # 주소록이 하나라도 있을 때. 그 밖(Exchange·POP·IMAP·모르는 모양·계정 관리자 키 없음)은 쓸 수 있다고 본다 - 모르면 막힘으로
    # 단정하지 않는다. 주소록만 든 프로필은 띄우면 'Outlook 시작' 마법사가 뜬다(개발 PC 실측).
    # CurVer(등록된 COM 판) ↔ 프로필 판 대조는 진단(curverMismatch)에만 쓴다 - 첫 실행 때 프로필을 옮겨 오는 판이 있어 모달이 확실하지 않다.
    # 반환 @{ total; usable; locs(프로필이 있던 위치 '16.0'·'15.0'·'WMS'); vers; curver; curverMismatch }.
    $MAPI = '{ED475414-B0D6-11D2-8C3B-00104B2A6676}'
    $LDAP = '{4DB5CBF2-3B77-4852-BC8E-BB81908861F3}'
    $LISTS = @('{ED475418-B0D6-11D2-8C3B-00104B2A6676}', '{ED475420-B0D6-11D2-8C3B-00104B2A6676}')
    $ABLIST = '{ED475419-B0D6-11D2-8C3B-00104B2A6676}'
    $roots = [ordered]@{ '16.0' = 'HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles'
                         '15.0' = 'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles'
                         'WMS'  = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles' }
    $r = @{ total = 0; usable = 0; locs = @(); vers = @(); curver = ''; curverMismatch = $false }
    $locs = [System.Collections.Generic.List[string]]::new()
    $vers = [System.Collections.Generic.List[int]]::new()
    foreach ($loc in $roots.Keys) {
        $root = $roots[$loc]
        $profs = @(Get-OcSubKeys $Reg $root)
        if ($profs.Count) { $locs.Add($loc); if ($loc -ne 'WMS') { $vers.Add([int]$loc.Split('.')[0]) } }
        foreach ($pn in $profs) {
            $r.total++
            $am = "$root\$pn\9375CFF0413111d3B88A00104B2A6676"
            if (-not (Test-OcKey $Reg $am)) { $r.usable++; continue }
            $listed = 0
            foreach ($n in $LISTS) {
                $v = Get-OcReg $Reg $am $n
                if ($v -is [byte[]]) { $listed += $v.Length } elseif ($null -ne $v -and [string]$v) { $listed++ }
            }
            $ab = 0
            $v = Get-OcReg $Reg $am $ABLIST
            if (($v -is [byte[]] -and $v.Length -gt 0) -or ($v -isnot [byte[]] -and $null -ne $v -and [string]$v)) { $ab = 1 }
            $other = 0
            foreach ($ak in @(Get-OcSubKeys $Reg $am)) {
                $svc = Get-OcReg $Reg "$am\$ak" 'Service Name'
                if ($svc -is [byte[]]) { $svc = [Text.Encoding]::Unicode.GetString($svc) }
                $svc = ([string]$svc).Trim([char]0).Trim().ToUpperInvariant()
                $cls = ([string](Get-OcReg $Reg "$am\$ak" 'clsid')).Trim().ToUpperInvariant()
                if ($cls -eq $LDAP -or ($cls -eq $MAPI -and @('CONTAB', 'EMABLT') -contains $svc)) { $ab++ } else { $other++ }
            }
            if ($listed -gt 0 -or $other -gt 0 -or $ab -eq 0) { $r.usable++ }
        }
    }
    $r.locs = @($locs); $r.vers = @($vers)
    $r.curver = [string](Get-OcReg $Reg 'HKCR:\Outlook.Application\CurVer' '(default)')
    $m = [regex]::Match($r.curver, '(\d+)$')
    if ($m.Success) {
        $rv = [int]$m.Groups[1].Value
        if ($rv -ge 15 -and $vers.Count -and -not $vers.Contains($rv)) { $r.curverMismatch = $true }   # 등록된 판에 프로필 없음(구판 병존 의심)
    }
    return $r
}

function Get-ProfileVerdict {
    # Outlook 이 꺼져 있을 때 COM 으로 띄우면 모달이 확실한가 → 건너뛸 사유 코드, 아니면 ''(먼저 시도하고 결과로 판정).
    #   R-NEWOLPOL  관리자 전환 정책(DoNewOutlookAutoMigration=1) - 클래식을 띄우면 전환 안내 프롬프트(F-12·C-02)
    #   R-NEWOL     프로필 0 + 새 Outlook 흔적(토글·olk·앱 패키지) - '계정 미설정'이 아니라 새 Outlook 사용(F-02)
    #   R-NOCLASSIC 프로필 0 + 흔적 없음 + 클래식 OUTLOOK.EXE·COM 등록 모두 없음(설치 안 됨 의심)
    #   R-NOPROF    프로필 0 + 흔적 없음, 또는 모든 프로필이 주소록만(긍정 증거) - 띄우면 'Outlook 시작' 마법사
    # 떠 있으면 늘 '' - 거기에 붙어 본다(실패 판정은 붙기 결과로). 클래식이 있으면 새 Outlook 흔적이 있어도 ''(LM24).
    param([bool]$Running, $Prof, $Trace = $null, $Classic = $null)
    if ($Running) { return '' }
    if ($Trace -and $Trace.autoMig -eq 1) { return 'R-NEWOLPOL' }
    if ([int]$Prof.total -eq 0) {
        if ($Trace -and $Trace.any) { return 'R-NEWOL' }
        if ($Classic -and -not $Classic.found -and -not $Classic.comReg) { return 'R-NOCLASSIC' }
        return 'R-NOPROF'
    }
    if ([int]$Prof.usable -eq 0) { return 'R-NOPROF' }
    return ''
}

function Test-OcProtectedRead {
    # 보호 멤버(Object Model Guard - 보낸 사람 주소·받는 사람·참석자)를 경고창 없이 읽을 수 있는가(AF32 D1·D7).
    # 정책·백신·보안 센터는 보지 않는다 - 같은 프로세스의 다른 스레드(런스페이스)가 따로 Outlook 에 붙어 받은 편지함(비었으면 보낸
    # 편지함)의 메일 하나의 보낸 사람 주소를 -Sec 초 안에 실제로 읽어 본다. 막힌 COM 호출은 멈출 수 없어 그 스레드는 버린다.
    # 반환 @{ ok; why } - why: read(읽힘) · none(읽을 메일 없음 - 읽어도 된다고 본다) · deny(예외 - 읽기 거부) ·
    #   noattach(그 스레드가 붙지 못함) · prompt(-Sec 초 무응답 - 보안 확인 창이 떠 있다고 본다). ok = read·none 일 때만.
    #   ok 가 아니면 수집기는 주소를 읽지 않는다 - 사내/사외를 증명할 수 없는 메일·회의는 G1 이 external_unknown 으로 뺀다.
    param([int]$Sec = 20)
    $r = Invoke-OcTimed -Sec $Sec -Script {
        $o = $null
        try { $o = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') } catch { return 'noattach' }
        try {
            $ns = $o.GetNamespace('MAPI')
            foreach ($n in @(6, 5)) {
                $items = $null
                try { $items = $ns.GetDefaultFolder($n).Items } catch { continue }
                $it = $null; try { $it = $items.GetFirst() } catch {}
                $k = 0
                while ($null -ne $it -and $k -lt 20) {
                    $k++
                    $cls = 0; try { $cls = [int]$it.Class } catch {}
                    if ($cls -eq 43) {
                        $null = [string]$it.SenderEmailAddress
                        return 'read'
                    }
                    try { $it = $items.GetNext() } catch { $it = $null }
                }
            }
            return 'none'
        } catch { return 'deny' }
    }
    if (-not $r.done) { return @{ ok = $false; why = 'prompt' } }
    $w = [string](@($r.out) | Select-Object -Last 1)
    if (-not $w) { $w = 'deny' }
    return @{ ok = ($w -eq 'read' -or $w -eq 'none'); why = $w }
}
function Get-CalBody {
    # 일정 본문(회의 안건) 한 칸 - config.calendar.collectBody 가 켜졌을 때만 부른다(AF32 D18 - 기본은 읽지 않는다).
    # AppointmentItem.Body 는 보호 멤버라 주소와 같은 판정(-ProtOk = Test-OcProtectedRead.ok)을 따른다: $false 면 Body 를 건드리지 않는다.
    # 개인(Sensitivity 1)·비공개(2)·기밀(3) 일정은 읽지 않는다(그 일정은 수집기가 행째 뺀다).
    # 앞 -Max 자만(줄바꿈·탭·제어 문자 → 공백, 연속 공백 접기 - 끝의 반쪽 서로게이트는 버린다). 원자료 파일(data\outlook\raw)의 이 칸은
    # G1(core\mailmerge.g1_com → meetnote.prep_raw_body → privacy.g1_file)이 정리·가린 뒤 원자료와 함께 지운다.
    # 반환 @{ body; why } - why: ok · empty · private · prot · err (호출측은 why 별 건수만 센다).
    param($Item, [bool]$ProtOk, [int]$Max = 600)
    $sens = 0
    try { $sens = [int]$Item.Sensitivity } catch {}
    if ($sens -ge 1 -and $sens -le 3) { return @{ body = ''; why = 'private' } }
    if (-not $ProtOk) { return @{ body = ''; why = 'prot' } }
    $b = ''
    try { $b = [string]$Item.Body } catch { return @{ body = ''; why = 'err' } }
    $b = (($b -replace '[\x00-\x1F\x7F]+', ' ') -replace ' {2,}', ' ').Trim()
    if ($Max -gt 0 -and $b.Length -gt $Max) {
        $b = $b.Substring(0, $Max)
        if ([char]::IsHighSurrogate($b[$b.Length - 1])) { $b = $b.Substring(0, $b.Length - 1) }
    }
    if (-not $b) { return @{ body = ''; why = 'empty' } }
    return @{ body = $b; why = 'ok' }
}

# ── 날짜 필터 카나리아 · 완료 판정 ─────────────────────────────────────────────────────────
function Format-OlDate([datetime]$d, [string]$Fmt) {
    # Restrict(Jet) 날짜 리터럴 - 값은 로컬 시각(LM24 와 같다). 'g' = 현재 로캘 짧은 날짜+시각(문서 형식·초 없음 - LM24 기본) ·
    # 'plain' = yyyy-MM-dd HH:mm · 'iso' = yyyy-MM-ddTHH:mm:ss. 어느 것을 쓸지는 필터 카나리아가 정한다(Select-DaslFormat).
    $inv = [Globalization.CultureInfo]::InvariantCulture
    if ($Fmt -eq 'iso') { return $d.ToString("yyyy-MM-dd'T'HH:mm:ss", $inv) }
    if ($Fmt -eq 'plain') { return $d.ToString('yyyy-MM-dd HH:mm', $inv) }
    return $d.ToString('g')
}
function Select-DaslFormat {
    # 필터 카나리아(C-06·F-28): 기준 항목(받은 편지함 - 없으면 보낸 편지함의 가장 최근 항목) 시각 T 의 [T-2분, T+2분) 을 형식마다
    # 걸어 그 항목이 실제로 돌아오는 첫 형식을 쓴다. 로캘과 안 맞는 리터럴은 예외 없이 0건을 주므로, 맞는 형식을 못 찾으면
    # 0건을 '그 달 메일 없음'으로 굳히지 않는다(canary=fail → R-FILTER · 완료 기록 0).
    # -Probe = { param($fmt) … } → $true(기준 항목이 돌아옴) · $false(안 옴) · $null(기준 항목 없음 - 판정 불가). 예외 = 그 형식 거부.
    # 반환 @{ fmt; canary = ok | none | fail }. none 이면 문서 형식('g')을 쓰되 0건 달은 unverified 로 둔다.
    param([scriptblock]$Probe, [string[]]$Formats = $script:OC_FORMATS)
    foreach ($f in $Formats) {
        $ok = $false
        try { $ok = & $Probe $f } catch { $ok = $false }
        if ($null -eq $ok) { return @{ fmt = $Formats[0]; canary = 'none' } }
        if ($ok) { return @{ fmt = $f; canary = 'ok' } }
    }
    return @{ fmt = ''; canary = 'fail' }
}
function Test-MonthDone {
    # 한 달·한 축(받은·보낸 메일·일정)의 판정. 반환 @{ done; st; lo; hi } - [lo, hi) = 그 달에서 근거가 있는 창.
    #   지평선(캐시에 있는 가장 오래된 메일 날) 앞과, 최근 달인데 OST 의 가장 최근 메일이 ostStaleH 보다 오래됐으면 그 뒤는
    #   창 밖(out_of_horizon - 관측 못 한 날을 0건으로 확정하지 않는다, C-08). 창이 비면 st=out_of_horizon.
    #   창의 st: 행 있음 → ok(필터 범위 밖 행이 섞였으면 partial) · 0행 → 카나리아 성공일 때만 zero_ok, 아니면 unverified ·
    #   예산·상한으로 끊김 → partial. done(완료 표에 적음) = 창이 그 달 전체이고 st 가 ok·zero_ok 일 때만(F-09·W1-02).
    #   일정은 -Cached $false -Oldest $null 로 부른다(동기화 창은 메일에만 걸린다).
    param([int]$Rows, [string]$Canary, $Oldest = $null, $Newest = $null, [datetime]$Start, [datetime]$End,
          [datetime]$Now = (Get-Date), [double]$StaleH = 72, [bool]$Cached = $true, [int]$Mismatch = 0, [bool]$Stopped = $false)
    $lo = $Start; $hi = $End
    if ($Stopped) { return @{ done = $false; st = 'partial'; lo = $lo; hi = $hi } }
    if ($null -ne $Oldest -and ([datetime]$Oldest).Date -gt $lo) { $lo = ([datetime]$Oldest).Date }
    if ($Cached -and $StaleH -gt 0 -and $End -gt $Now.AddHours(-$StaleH)) {
        if ($null -eq $Newest -or ([datetime]$Newest) -lt $Now.AddHours(-$StaleH)) {
            $cut = $Start
            if ($null -ne $Newest) { $cut = ([datetime]$Newest).Date.AddDays(1) }
            if ($cut -lt $hi) { $hi = $cut }
        }
    }
    if ($hi -le $lo) { return @{ done = $false; st = 'out_of_horizon'; lo = $lo; hi = $lo } }
    if ($Canary -eq 'fail') { return @{ done = $false; st = 'unverified'; lo = $lo; hi = $hi } }
    $st = 'ok'
    if ($Rows -le 0) { if ($Canary -eq 'ok' -and $Mismatch -eq 0) { $st = 'zero_ok' } else { $st = 'unverified' } }
    elseif ($Mismatch -gt 0) { $st = 'partial' }
    $whole = ($lo -eq $Start -and $hi -eq $End)
    return @{ done = ($whole -and ($st -eq 'ok' -or $st -eq 'zero_ok')); st = $st; lo = $lo; hi = $hi }
}
function Limit-ColdVerdict($V, [bool]$Cold) {
    # 이 수집이 직접 띄운 Outlook(캐시 모드이거나 새 Outlook 흔적이 있는 PC - '차가운 COM')의 판정을 낮춘다(LM28 회사 PC 실측:
    # 새 Outlook 을 쓰는 PC 에서 클래식을 띄워 읽었더니 받은 53건·보낸 0건으로 열 달을 '0건 확인' 했다). 그 캐시(OST)가 사서함 전체를
    # 담았는지 이 수집은 증명할 수 없다 - 행이 있는 창은 partial(행은 쓰되 확인 아님), 0행 창은 unverified, 완료 표에는 적지 않는다.
    # 원장은 그 날들을 Outlook 웹으로 계속 확인한다. 지평선 밖(out_of_horizon)·미확인은 그대로.
    if (-not $Cold -or $null -eq $V) { return $V }
    $st = [string]$V.st
    if ($st -eq 'ok') { $st = 'partial' } elseif ($st -eq 'zero_ok') { $st = 'unverified' }
    return @{ done = $false; st = $st; lo = $V.lo; hi = $V.hi }
}
function Test-CoverageUsable($J, [string]$Ver, [string]$Writer, [bool]$StoreSubject) {
    # 달별 완료 표 머리 검사 - 형식 3 · 판('수집기판|collect.cursorEpoch') · 작성자(com/selftest) · 제목 저장 설정이 이번 실행과 같을
    # 때만 쓴다. 판이 다르면(규칙이 바뀌었거나 cursorEpoch 를 올림) 그 표의 '완료'를 믿지 않는다(F-09). 다른 경로(웹·Copilot)
    # 가 무엇을 썼는지는 보지 않는다 - 출처마다 자기 파일만 쓴다(P5). 반환 @{ ok; why }.
    # (변수 이름 주의: PowerShell 변수는 대소문자를 가리지 않는다 - $Ver 매개변수와 겹치지 않게 $jver)
    if ($null -eq $J) { return @{ ok = $false; why = '표 없음' } }
    $v = 0; try { $v = [int]$J.version } catch {}
    $jver = ''; try { $jver = [string]$J.ver } catch {}
    $w = ''; try { $w = [string]$J.writer } catch {}
    $ss = $true; try { $ss = [bool]$J.store_subject } catch {}
    if ($v -ne 3) { return @{ ok = $false; why = ('형식 {0}' -f $v) } }
    if ($jver -ne $Ver) { return @{ ok = $false; why = ('판 {0} ≠ {1}' -f $jver, $Ver) } }
    if ($w -ne $Writer) { return @{ ok = $false; why = ('작성 {0}' -f $w) } }
    if ($ss -ne $StoreSubject) { return @{ ok = $false; why = ('제목 저장 {0}' -f $ss) } }
    return @{ ok = $true; why = '' }
}

# ── 메일 폴더 재귀(C-07·W1-03) ─────────────────────────────────────────────────────────────
function Get-MailFolderList {
    # 기본 저장소 루트에서 메일 폴더를 너비 우선으로 모은다(LM27 :611 이식 - 하트비트 없음). 규칙으로 하위 폴더에 옮긴 메일까지 읽는다.
    # 제외: $Defaults 의 OC_SKIP_FOLDERS(지운·보낼·임시·충돌·동기화 문제·실패·정크·RSS - 하위 포함, 역할은 이름이 아니라 EntryID 로) ·
    # '대화 기록' · DefaultItemType≠0(메일 폴더 아님 - 하위는 계속 본다) · 항목 0개(하위는 계속 본다). 상한 $Max(넘으면 capped).
    # 받은·보낸 편지함을 먼저 넣어 상한에 닿아도 기본 폴더는 빠지지 않는다. 보낸 편지함 하위는 box=sent, 그 밖은 inbox.
    # $Root·노드: EntryID·Name·DefaultItemType·Items.Count·Folders 를 가진 COM 폴더(시험은 같은 모양의 개체).
    # $Defaults = @{ <OlDefaultFolders 번호> = EntryID }(6 받은 · 5 보낸 · 제외 목록). -Exclude = privacy.excludeMailFolders(이름에 그
    # 낱말이 든 폴더와 그 하위는 읽지 않는다 - 개인 폴더, AF32 D3). 반환 @{ folders; seen; excluded; private; empty; capped }.
    param($Root, [hashtable]$Defaults, [int]$Max = $script:OC_FOLDERS_MAX, [string[]]$Exclude = @())
    $r = @{ folders = ([System.Collections.Generic.List[object]]::new()); seen = 0; excluded = 0; private = 0; empty = 0; capped = $false }
    $skip = @{}
    foreach ($n in $script:OC_SKIP_FOLDERS) { if ($Defaults.ContainsKey($n) -and $Defaults[$n]) { $skip[[string]$Defaults[$n]] = $n } }
    $inId = ''; if ($Defaults.ContainsKey(6)) { $inId = [string]$Defaults[6] }
    $sentId = ''; if ($Defaults.ContainsKey(5)) { $sentId = [string]$Defaults[5] }
    $first = [System.Collections.Generic.List[object]]::new(); $rest = [System.Collections.Generic.List[object]]::new()
    foreach ($c in (Get-OcChildren $Root)) {                                           # 목록을 그대로(@() 로 감싸면 목록 하나가 원소가 된다)
        $cid = ''; try { $cid = [string]$c.EntryID } catch {}
        if ($cid -and ($cid -eq $inId -or $cid -eq $sentId)) { $first.Add($c) } else { $rest.Add($c) }
    }
    $queue = [System.Collections.Generic.Queue[object]]::new()
    foreach ($c in $first) { $queue.Enqueue(@{ node = $c; under = '' }) }    # @($list) + @($list) 대신 따로 넣는다(아래 목록 규칙 참고)
    foreach ($c in $rest) { $queue.Enqueue(@{ node = $c; under = '' }) }
    while ($queue.Count) {
        if ($r.seen -ge $Max) { $r.capped = $true; break }
        $e = $queue.Dequeue()
        $node = $e.node
        $r.seen++
        $id = ''
        try { $id = [string]$node.EntryID } catch { continue }
        if ($skip.ContainsKey($id)) { $r.excluded++; continue }                       # 하위 포함 제외
        $fname = ''; try { $fname = ([string]$node.Name).Trim() } catch {}
        if ($script:OC_CONV_HISTORY -contains $fname) { $r.excluded++; continue }     # 대화 기록(하위 포함)
        if ($id -ne $inId -and $id -ne $sentId -and (Test-OcNameHit $fname $Exclude)) { $r.private++; continue }   # 개인 폴더(하위 포함)
        $under = $e.under
        $role = 'subfolder'; $box = 'inbox'
        if ($inId -and $id -eq $inId) { $role = 'inbox'; $under = 'inbox' }
        elseif ($sentId -and $id -eq $sentId) { $role = 'sent'; $box = 'sent'; $under = 'sent' }
        elseif ($under -eq 'sent') { $box = 'sent' }
        $type = -1; try { $type = [int]$node.DefaultItemType } catch {}
        if ($type -eq 0) {
            $cnt = -1; try { $cnt = [int]$node.Items.Count } catch {}
            if ($cnt -ne 0) {
                $field = '[ReceivedTime]'; if ($box -eq 'sent') { $field = '[SentOn]' }
                $r.folders.Add(@{ node = $node; key = (Get-OcKey $id); box = $box; role = $role; field = $field; name = $fname })
            } else { $r.empty++ }
        }
        foreach ($c in (Get-OcChildren $node)) { $queue.Enqueue(@{ node = $c; under = $under }) }
    }
    return $r
}
function Get-OcChildren($node) {
    $out = [System.Collections.Generic.List[object]]::new()
    try { foreach ($c in $node.Folders) { if ($null -ne $c) { $out.Add($c) } } } catch {}
    return , $out
}
function Get-OcItemTime($it, [string]$Field) {
    try { if ($Field -eq '[SentOn]') { return [datetime]$it.SentOn } ; return [datetime]$it.ReceivedTime } catch { return $null }
}
function Get-MailHorizon($Folders) {
    # 가장 오래된·가장 최근 메일 시각(로컬) - 기본 받은·보낸 편지함(LM27 :974 이식). 캐시 동기화 지평선·OST 신선도 판정용.
    # $Folders = @(@{ node; field }). 반환 @{ oldest; newest }(없으면 $null).
    $min = $null; $max = $null
    foreach ($fd in $Folders) {
        try {
            $items = $fd.node.Items
            $items.Sort($fd.field, $false)
            $t = $null; $f = $items.GetFirst(); if ($f) { $t = Get-OcItemTime $f $fd.field }
            if ($t -and ($null -eq $min -or $t -lt $min)) { $min = $t }
            $t = $null; $l = $items.GetLast(); if ($l) { $t = Get-OcItemTime $l $fd.field }
            if ($t -and ($null -eq $max -or $t -gt $max)) { $max = $t }
        } catch {}
    }
    return @{ oldest = $min; newest = $max }
}
function Get-CanaryItem($Folders) {
    # 필터 카나리아 기준 항목 - 받은 편지함(비었으면 보낸 편지함)의 가장 최근 항목(LM27 :912 이식). 반환 @{ node; field; t } 또는 $null.
    foreach ($fd in $Folders) {
        try {
            $items = $fd.node.Items
            $items.Sort($fd.field, $true)
            $f = $items.GetFirst()
            if ($f) { $t = Get-OcItemTime $f $fd.field; if ($t) { return @{ node = $fd.node; field = $fd.field; t = $t } } }
        } catch {}
    }
    return $null
}

# ── 참여자 주소(AF32 D7·D8) ──────────────────────────────────────────────────────────────
$script:OC_PR_SMTP = 'http://schemas.microsoft.com/mapi/proptag/0x39FE001E'          # PR_SMTP_ADDRESS
$script:OC_PR_SENDER_SMTP = 'http://schemas.microsoft.com/mapi/proptag/0x5D01001F'   # PR_SENDER_SMTP_ADDRESS
function ConvertTo-OcAddr($v) {
    # 주소 꼴이면 소문자로, 아니면 ''(Exchange 내부 주소 '/o=…' 는 주소가 아니다 - 사내/사외를 그것만으로 정하지 않는다)
    $s = ([string]$v).Trim()
    if ($s -match $script:OC_ADDR_RX) { return $s.ToLowerInvariant() }
    return ''
}
function Get-OcSmtp($Ae) {
    # AddressEntry → SMTP 주소(소문자) | ''. PR_SMTP_ADDRESS → Exchange 사용자(0·5)·목록(1)의 PrimarySmtpAddress → Address 순.
    # 보호 멤버라 부르는 쪽이 Test-OcProtectedRead 가 ok 일 때만 부른다. 못 읽으면 '' - G1 이 external_unknown 으로 뺀다.
    if ($null -eq $Ae) { return '' }
    $a = ''
    try { $a = ConvertTo-OcAddr ($Ae.PropertyAccessor.GetProperty($script:OC_PR_SMTP)) } catch {}
    if (-not $a) {
        $t = -1; try { $t = [int]$Ae.AddressEntryUserType } catch {}
        if ($t -eq 0 -or $t -eq 5) { try { $x = $Ae.GetExchangeUser(); if ($x) { $a = ConvertTo-OcAddr $x.PrimarySmtpAddress } } catch {} }
        elseif ($t -eq 1) { try { $x = $Ae.GetExchangeDistributionList(); if ($x) { $a = ConvertTo-OcAddr $x.PrimarySmtpAddress } } catch {} }
    }
    if (-not $a) { try { $a = ConvertTo-OcAddr $Ae.Address } catch {} }
    return $a
}
function Get-OcRecipientAddr($Rc) {
    # Recipient → SMTP 주소 | '' (PR_SMTP_ADDRESS 한 번이 대개 답 - 아니면 AddressEntry 로)
    $a = ''
    try { $a = ConvertTo-OcAddr ($Rc.PropertyAccessor.GetProperty($script:OC_PR_SMTP)) } catch {}
    if (-not $a) { try { $a = ConvertTo-OcAddr $Rc.Address } catch {} }
    if (-not $a) { try { $a = Get-OcSmtp $Rc.AddressEntry } catch {} }
    return $a
}
function Get-OcSenderAddr($Item) {
    # 메일 보낸 사람 → SMTP 주소 | ''. SMTP 형식이면 SenderEmailAddress, Exchange 면 PR_SENDER_SMTP_ADDRESS → Sender(AddressEntry).
    $a = ''
    $typ = ''; try { $typ = [string]$Item.SenderEmailType } catch {}
    if ($typ -ne 'EX') { try { $a = ConvertTo-OcAddr $Item.SenderEmailAddress } catch {} }
    if (-not $a) { try { $a = ConvertTo-OcAddr ($Item.PropertyAccessor.GetProperty($script:OC_PR_SENDER_SMTP)) } catch {} }
    if (-not $a) { try { $a = Get-OcSmtp $Item.Sender } catch {} }
    return $a
}
function Format-OcPerson([string]$Name, [string]$Addr) {
    # 원자료 칸의 한 사람 'Name <addr>' - 이름의 ';'·'<'·'>'·따옴표는 지운다(목록 구분자). 주소를 못 읽었으면 'Name <>'(증명 불가).
    $n = ([string]$Name -replace '[;<>"\r\n]+', ' ').Trim()
    return ('{0} <{1}>' -f $n, ([string]$Addr).Trim()).Trim()
}
function Get-OcPeople($Recipients, [int]$Max = 100) {
    # Recipients → @{ to; cc; n; capped } - to = 받는 사람(1), cc = 참조(2)·숨은 참조(3)·그 밖. ';' 로 이은 'Name <addr>'.
    # $Max 명을 넘으면 나머지는 읽지 않고 '? <>' 를 하나 더한다(증명 불가 - G1 이 뺀다). 예외가 나면 그 사람은 'Name <>'.
    $to = [System.Collections.Generic.List[string]]::new(); $cc = [System.Collections.Generic.List[string]]::new()
    $n = 0; $capped = $false
    foreach ($rc in $Recipients) {
        $n++
        if ($n -gt $Max) { $capped = $true; break }
        $nm = ''; try { $nm = [string]$rc.Name } catch {}
        $typ = 1; try { $typ = [int]$rc.Type } catch {}
        $p = Format-OcPerson $nm (Get-OcRecipientAddr $rc)
        if ($typ -eq 1) { $to.Add($p) } else { $cc.Add($p) }
    }
    if ($capped) { $cc.Add('? <>') }
    return @{ to = ($to -join '; '); cc = ($cc -join '; '); n = $n; capped = $capped }
}
function Get-OcMailRecipients($Recipients, [int]$Max = 100) {
    # 메일 받는 사람·참조(D7) - Get-OcPeople 에 더해, 한 사람도 읽지 못했으면(받는 사람 목록이 빔·숨은 참조로만 받음 등)
    # 참조에 '? <>'(증명 불가)를 둔다 - 보낸 사람 주소만으로 사내 메일임을 증명하지 않는다(G1 이 external_unknown 으로 뺀다).
    # 반환 = Get-OcPeople 의 값 + none($true 면 받는 사람을 하나도 읽지 못함 - 받은 메일의 수신 구분은 unknown).
    $pp = Get-OcPeople $Recipients $Max
    $pp.none = (-not $pp.to -and -not $pp.cc)
    if ($pp.none) { $pp.cc = '? <>' }
    return $pp
}
function Get-OcMyAddresses($Ns, [bool]$ProtOk) {
    # 내 주소(me[] - 사내 도메인(D7)의 근거 · 받은 메일의 수신 구분) - 내 기본 사서함의 것만:
    #   ① 기본 저장소로 메일이 배달되는 계정(Account.DeliveryStore.StoreID = Namespace.DefaultStore.StoreID)의 SMTP 주소
    #   ② CurrentUser 의 Exchange 기본 SMTP 주소(AddressEntry.GetExchangeUser().PrimarySmtpAddress)
    #   ③ CurrentUser 표시 이름 - 주소 꼴이 아닐 때만(수신 구분과 내 이름 가림에만 쓴다 - 도메인 근거가 아니다). 주소 꼴이면
    #      ①②에 이미 있는 주소일 때만 남는다(표시 이름이 다른 도메인의 주소여도 그 도메인이 사내가 되지 않는다).
    #   프로필의 다른 계정(개인·협력사 메일 계정)·주소 꼴 계정 표시 이름·config owner 는 넣지 않는다 - 그 도메인이 사내가 되면
    #   개인·사외 메일이 모든 경로에서 사내로 통과한다. 모두 보호 멤버라 -ProtOk(Test-OcProtectedRead.ok)일 때만 읽는다.
    #   반환 = 소문자 목록(중복 없음 · 두 글자 이상 · 주소 먼저).
    $out = [System.Collections.Generic.List[string]]::new()
    if (-not $ProtOk -or $null -eq $Ns) { return @() }
    $sid = ''
    try { $sid = [string]$Ns.DefaultStore.StoreID } catch {}
    if ($sid) {
        try {
            foreach ($a in $Ns.Accounts) {
                $ds = ''
                try { $ds = [string]$a.DeliveryStore.StoreID } catch {}
                if ($ds -and $ds -eq $sid) {
                    $x = ''
                    try { $x = ConvertTo-OcAddr $a.SmtpAddress } catch {}
                    if ($x) { $out.Add($x) }
                }
            }
        } catch {}
    }
    try {
        $xu = $Ns.CurrentUser.AddressEntry.GetExchangeUser()
        if ($xu) { $x = ConvertTo-OcAddr $xu.PrimarySmtpAddress; if ($x) { $out.Add($x) } }
    } catch {}
    try {
        $nm = ([string]$Ns.CurrentUser.Name).Trim().ToLower()
        if ($nm -and ($nm -notmatch $script:OC_ADDR_RX -or $out.Contains($nm))) { $out.Add($nm) }
    } catch {}
    return @($out | Where-Object { $_.Length -ge 2 } | Select-Object -Unique)
}
function Get-OcInternalDomains([string[]]$CfgDomains, [string[]]$Me) {
    # 사내 도메인(D7) = privacy.internalDomains ∪ 내 주소(me[])의 도메인 - 공용 개인 메일 도메인($script:OC_PERSONAL_DOMAINS)은 뺀다
    # (core\privacy.py internal_domains 와 같다). 내 기본 사서함이 개인 메일 계정이어도 그 도메인 사람 모두가 사내가 되지 않는다.
    # 비면 수집기는 아무것도 읽지 않는다(R-NODOMAIN). 반환 = 소문자 도메인 목록(중복 없음 · 설정 먼저).
    $out = [System.Collections.Generic.List[string]]::new()
    $cand = [System.Collections.Generic.List[string]]::new()
    foreach ($x in @($CfgDomains)) { if ($x) { $cand.Add(([string]$x).Trim().ToLowerInvariant().TrimStart('@').TrimEnd('.')) } }
    foreach ($a in @($Me)) {
        if ($a -and ([string]$a) -match $script:OC_ADDR_RX) {
            $s = [string]$a
            $cand.Add($s.Substring($s.LastIndexOf('@') + 1).Trim().ToLowerInvariant().TrimEnd('.'))
        }
    }
    foreach ($d in $cand) {
        if ($d -and $script:OC_PERSONAL_DOMAINS -notcontains $d -and -not $out.Contains($d)) { $out.Add($d) }
    }
    return @($out)
}

# ── 프로세스 규율(F-15) ────────────────────────────────────────────────────────────────────
function Stop-OutlookWeStarted {
    # 이 수집이 COM 으로 띄운 Outlook(명령줄 -Embedding, $Since 이후 시작)만 끝낸다. 사용자가 직접 띄운 Outlook·그 전부터 떠 있던
    # Outlook 은 건드리지 않는다. taskkill 은 띄우지 않는다(Stop-Process·CIM 은 인프로세스). 반환 = 끝낸 수.
    param([datetime]$Since)
    $n = 0
    $procs = @()
    try { $procs = @(Get-CimInstance -ClassName Win32_Process -Filter "Name='OUTLOOK.EXE'" -ErrorAction Stop) } catch { return 0 }
    foreach ($w in $procs) {
        if ([string]$w.CommandLine -notmatch '(?i)(^|\s)[-/]embedding') { continue }
        if ($null -eq $w.CreationDate -or $w.CreationDate -lt $Since.AddSeconds(-2)) { continue }
        try { Stop-Process -Id ([int]$w.ProcessId) -Force -ErrorAction Stop; $n++ } catch {}
    }
    return $n
}
function Start-OcLaunchWatchdog {
    # 꺼진 Outlook 을 COM 으로 띄울 때의 무진전 확인(F-15·V8). 같은 프로세스의 다른 스레드(런스페이스)에서 $Sec 초를 재고,
    # 그 안에 $w.sync.attached 가 서지 않으면(시작 마법사·프로필 선택·암호 창에서 멈춤) 이 수집이 띄운 Outlook 만 끝낸다 -
    # 막힌 New-Object·GetNamespace 가 RPC 오류로 풀린다. 자식 프로세스를 띄우지 않는다. 반환 = Stop-OcLaunchWatchdog 에 넘길 값.
    param([int]$Sec, [datetime]$Since)
    $sync = [hashtable]::Synchronized(@{ attached = $false; fired = $false; killed = 0 })
    $code = "function Stop-OutlookWeStarted {`n" + ${function:Stop-OutlookWeStarted}.ToString() + "`n}`n" + @'
$t0 = [datetime]::Now
while (-not $sync.attached -and ([datetime]::Now - $t0).TotalSeconds -lt $sec) { Start-Sleep -Milliseconds 500 }
if (-not $sync.attached) { $sync.fired = $true; $sync.killed = Stop-OutlookWeStarted $since }
'@
    $rs = [runspacefactory]::CreateRunspace()
    $rs.Open()
    $rs.SessionStateProxy.SetVariable('sync', $sync)
    $rs.SessionStateProxy.SetVariable('sec', $Sec)
    $rs.SessionStateProxy.SetVariable('since', $Since)
    $ps = [powershell]::Create(); $ps.Runspace = $rs
    [void]$ps.AddScript($code)
    $h = $ps.BeginInvoke()
    return @{ sync = $sync; ps = $ps; rs = $rs; h = $h }
}
function Stop-OcLaunchWatchdog($W) {
    if ($null -eq $W) { return }
    $W.sync.attached = $true
    try { [void]$W.h.AsyncWaitHandle.WaitOne(5000) } catch {}
    try { $W.ps.Dispose() } catch {}
    try { $W.rs.Dispose() } catch {}
}
function Invoke-OcTimed {
    # 스크립트를 같은 프로세스의 다른 스레드(런스페이스)에서 돌리고 $Sec 초까지만 기다린다 - Start-Job 은 powershell 프로세스를
    # 하나 더 띄운다. 시간이 넘으면 그 스레드는 버린다(막힌 COM 호출은 멈출 수 없다 - 이 프로세스가 끝날 때 함께 사라진다).
    # 반환 @{ done; out; error }.
    param([scriptblock]$Script, [int]$Sec, [hashtable]$Vars = @{})
    $rs = [runspacefactory]::CreateRunspace()
    $rs.Open()
    foreach ($k in $Vars.Keys) { $rs.SessionStateProxy.SetVariable($k, $Vars[$k]) }
    $ps = [powershell]::Create(); $ps.Runspace = $rs
    [void]$ps.AddScript($Script.ToString())
    $h = $ps.BeginInvoke()
    if (-not $h.AsyncWaitHandle.WaitOne([math]::Max(1, $Sec) * 1000)) { return @{ done = $false; out = @(); error = '' } }
    $out = @(); $err = ''
    try { $out = @($ps.EndInvoke($h)) } catch { $err = $_.Exception.Message }
    if (-not $err -and $ps.HadErrors) { try { $err = [string]$ps.Streams.Error[0].Exception.Message } catch {} }
    try { $ps.Dispose(); $rs.Dispose() } catch {}
    return @{ done = $true; out = $out; error = $err }
}

# ── AF32STATUS ────────────────────────────────────────────────────────────────────────────────
function ConvertTo-LmRanges {
    # 한 달·한 축의 Test-MonthDone 결과 → ranges 조각(창 앞뒤는 out_of_horizon). $Start·$End = 그 달에서 이번에 다룬 [start, end).
    # 조각을 하나씩 내보낸다 - 호출측은 @(…) 로 받는다.
    param([string]$Axis, [datetime]$Start, [datetime]$End, $V)
    if ($End -le $Start) { return }
    $d = 'yyyy-MM-dd'
    if ($V.st -eq 'out_of_horizon' -or $V.hi -le $V.lo) {
        return ([ordered]@{ axis = $Axis; from = $Start.ToString($d); to = $End.AddDays(-1).ToString($d); st = 'out_of_horizon' })
    }
    if ($V.lo -gt $Start) { [ordered]@{ axis = $Axis; from = $Start.ToString($d); to = $V.lo.AddDays(-1).ToString($d); st = 'out_of_horizon' } }
    [ordered]@{ axis = $Axis; from = $V.lo.ToString($d); to = $V.hi.AddDays(-1).ToString($d); st = $V.st }
    if ($V.hi -lt $End) { [ordered]@{ axis = $Axis; from = $V.hi.ToString($d); to = $End.AddDays(-1).ToString($d); st = 'out_of_horizon' } }
}
function Format-LmStatus {
    # 수집기 마지막 줄(P3) - 'AF32STATUS ' + JSON 한 줄. reason 은 사유 코드 목록을 쉼표로(첫 코드가 주 사유).
    param([string]$Src, [int]$Rc, [string[]]$Reasons = @(), $Counts = @{}, $Ranges = @())
    $o = [ordered]@{ v = 1; src = $Src; rc = $Rc; reason = ((@($Reasons) | Where-Object { $_ } | Select-Object -Unique) -join ',');
                     counts = $Counts; ranges = @($Ranges) }
    return ('AF32STATUS ' + ($o | ConvertTo-Json -Compress -Depth 8))
}
function Write-LmStatus {
    param([string]$Src, [int]$Rc, [string[]]$Reasons = @(), $Counts = @{}, $Ranges = @())
    Write-Host (Format-LmStatus -Src $Src -Rc $Rc -Reasons $Reasons -Counts $Counts -Ranges $Ranges)
}
