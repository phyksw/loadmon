# Diagnose-Collectors.ps1 - AgentFinder32 수집 진단: 켜 둔 수집 경로(config collect.channels)가 이 PC 에서 어디서 막혔는지 한 장으로.
# 담는 것: Outlook 앱이 붙거나 뜰 수 있는지(설치·새 Outlook 흔적·프로필·실행·권한·주소 읽기), 전용 Edge 창과 Outlook 웹·Copilot
#   로그인 대기 여부, 지난 실행의 수집 단계 결과 코드(rc·사유), 설정 준비(사내 도메인 수·제한 고객 목록 유무).
# 담지 않는 것: 메일·일정 내용·제목·주소·이름, 날짜·달별 건수, 창 제목, 백신·보안 센터·정책 목록, 다른 프로그램.
# 쓰는 곳: <설치 폴더>\report\collect_diag.txt 하나뿐(설치 폴더 밖에는 아무것도 쓰지 않는다). 내 자료가 아니거나 지우는 중이면 아무것도 보지 않는다(종료 코드 3).
# Usage:  .\Diagnose-Collectors.ps1 [-OutFile report\collect_diag.txt]
param([string]$OutFile = '')
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
. (Join-Path $here 'LmName.ps1')          # Get-LmNames · Test-Af32Consent
. (Join-Path $here 'OutlookCommon.ps1')   # 판 판정·주소 읽기 시험 - 수집기와 같은 함수
if (-not (Test-Af32Consent $root)) {
    # 시작 확인은 core\consent.py --status 와 같은 판정(내 자료 · 지우는 중이 아님) - 파이썬이 없으면 확인할 수 없어 진단하지 않는다
    if ($script:Af32ConsentWhy -eq 'nopython') { Write-Host '내 자료인지 확인할 파이썬(python\python.exe)이 없어 수집 진단을 하지 않았습니다 - tools\Get-EmbeddedPython.ps1 로 받을 수 있습니다.' }
    elseif ($script:Af32ConsentWhy -eq 'other') { Write-Host '이 설치 폴더의 자료가 다른 Windows 사용자의 것이거나 누구의 것인지 확인할 수 없어 수집 진단을 하지 않았습니다.' }
    elseif ($script:Af32ConsentWhy -eq 'wiping') { Write-Host '자료를 지우는 중이라 수집 진단을 하지 않았습니다 - 다 지운 뒤 다시 시작할 수 있습니다.' }
    else { Write-Host '내 자료인지 확인하지 못해(core\consent.py 실행 실패) 수집 진단을 하지 않았습니다.' }
    exit 3
}
$nm = Get-LmNames $root
$repDir = [System.IO.Path]::GetFullPath((Join-Path $root 'report'))
$outP = Join-Path $repDir 'collect_diag.txt'
if ($OutFile) {
    # 설치 폴더의 report\ 아래만 받는다 - 그 밖이면 기본 경로에 쓴다
    $cand = $(if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path $root $OutFile })
    try { $cand = [System.IO.Path]::GetFullPath($cand) } catch { $cand = '' }
    if ($cand -and $cand.StartsWith($repDir.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { $outP = $cand }
}
$L = New-Object System.Collections.Generic.List[string]
function W([string]$s) { $L.Add($s); Write-Host $s }
$findings = New-Object System.Collections.Generic.List[string]

$cfg = $null
foreach ($cn in @('config.json', 'config.default.json')) {
    $cp = Join-Path $root ('config\' + $cn)
    if (-not (Test-Path -LiteralPath $cp)) { continue }
    try { $cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $cp | ConvertFrom-Json; break } catch { $cfg = $null }
}
$chans = @(Get-OcCfgList $cfg 'collect' 'channels' @('com', 'owa', 'copilot') | ForEach-Object { $_.ToLowerInvariant() } | Where-Object { @('com', 'owa', 'copilot') -contains $_ } | Select-Object -Unique)
$chKo = @{ com = 'Outlook 앱'; owa = 'Outlook 웹'; copilot = 'M365 Copilot' }

W ("{0} 수집 진단  {1}" -f $nm.Product, (Get-Date).ToString('yyyy-MM-dd'))   # report\ 아래는 날짜만(D10)
W ("  켜 둔 수집 경로(collect.channels): {0}" -f $(if ($chans.Count) { ($chans | ForEach-Object { $chKo[$_] }) -join ' · ' } else { '없음' }))
if (-not $chans.Count) { $findings.Add('수집 경로가 하나도 켜져 있지 않습니다 - 설정의 collect.channels 에 com·owa·copilot 중 하나 이상을 두세요.') }

# ── 설정 준비 ────────────────────────────────────────────────────────────────
W '[설정]'
$doms = @(Get-OcCfgList $cfg 'privacy' 'internalDomains' @())
W ("  사내 메일 도메인(privacy.internalDomains): {0}개{1}" -f $doms.Count, $(if (-not $doms.Count) { ' - Outlook 앱이 내 주소를 읽으면 그 도메인을 씁니다' } else { '' }))
$rel = [string](Get-OcCfg $cfg 'privacy' 'restrictedCustomersFile' 'config\restricted_customers.json')
if (-not $rel) { $rel = 'config\restricted_customers.json' }
$rp = $(if ([System.IO.Path]::IsPathRooted($rel)) { $rel } else { Join-Path $root $rel })
$rt = Test-OcRestrictedList $rp          # 수집기와 같은 판정 - 배포 견본 그대로·날짜가 아닌 confirmed 도 받지 않는다
$rOk = [bool]$rt.ok
W ("  제한 고객 목록 파일: {0}" -f $(switch ([string]$rt.why) {
    'ok' { '있음(형식 맞음)' } 'template' { '배포 견본 그대로(쓰지 않음)' } 'date' { '확인 날짜(confirmed) 오류' } 'future' { '확인 날짜(confirmed)가 오늘보다 뒤' }
    default { '없음 또는 형식 오류' } }))
if ([string]$rt.why -eq 'template') { $findings.Add('제한 고객 목록이 배포 견본(restricted_customers.example.json) 그대로입니다 - 운영 담당이 배포한 config\restricted_customers.json 을 넣으세요.') }
elseif ([string]$rt.why -eq 'date' -or [string]$rt.why -eq 'future') { $findings.Add('제한 고객 목록의 확인 날짜(confirmed)가 올바르지 않습니다 - 운영 담당이 배포한 config\restricted_customers.json 을 넣으세요.') }
elseif (-not $rOk) { $findings.Add('제한 고객 목록 파일이 없습니다 - 운영 담당이 배포한 config\restricted_customers.json 을 넣으세요(제한 고객이 없으면 빈 목록 파일).') }
$cbv = Get-OcCfg $cfg 'calendar' 'collectBody' $false
W ("  일정 본문 수집(calendar.collectBody): {0}" -f $(if ($cbv -eq $true -or ([string]$cbv) -match '^\s*(true|1|yes|on)\s*$') { '켜짐' } else { '꺼짐' }))

# ── Outlook 앱(COM) ──────────────────────────────────────────────────────────
$pOl = @(); $comMsg = ''; $classicOk = $true; $nProf = 0; $prof = $null; $trace = $null; $elev = $false; $pr = $null
if ($chans -contains 'com') {
    W '[Outlook 앱]'
    $classic = Find-ClassicOutlook
    $classicOk = [bool]$classic.found
    if ($classicOk) {
        W ("  클래식 Outlook: 설치됨  v{0}  설치 방식: {1}" -f $classic.ver,
           $(if ($classic.c2r -and $classic.msi) { 'Click-to-Run + MSI(두 벌)' } elseif ($classic.c2r) { 'Click-to-Run(M365)' } else { 'MSI' }))
    } else {
        W ("  클래식 Outlook: 찾지 못함(의심) · COM 등록: {0}" -f $(if ($classic.comReg) { '있음(' + $classic.curVer + ')' } else { '없음' }))
    }
    $trace = Get-NewOutlookTrace
    W ("  새 Outlook: 앱 {0} · UseNewOutlook 토글 {1} · 전환 정책 {2}" -f $(if ($trace.appx) { '설치됨' } else { '없음' }),
       $(if ($trace.useNew) { '켜짐' } else { '꺼짐' }), $(if ($null -eq $trace.autoMig) { '없음' } else { [string]$trace.autoMig }))
    $pOl = @(Get-Process outlook -ErrorAction SilentlyContinue)
    W ("  실행 중 클래식 Outlook: {0}개" -f $pOl.Count)
    $prof = Get-OutlookProfileState
    $nProf = [int]$prof.total
    W ("  메일 프로필: {0}개 (쓸 수 있음 {1}개){2}" -f $nProf, $prof.usable, $(if ($prof.curverMismatch) { ' · 등록된 판에 프로필 없음(구판 병존 의심)' } else { '' }))
    $elev = Test-OcElevated
    W ("  이 진단의 권한: {0}" -f $(if ($elev) { '관리자(상승) - 일반 권한 Outlook 에 붙지 못합니다(R-ELEV)' } else { '일반' }))
    $verdict = Get-ProfileVerdict -Running ($pOl.Count -gt 0) -Prof $prof -Trace $trace -Classic $classic
    W ("  수집기 사전 판정: {0}" -f $(if ($verdict) { $verdict + ' - Outlook 이 꺼져 있고 띄우면 모달이 확실해 띄우지 않습니다' } else { '시도함(먼저 붙어 보고 결과로 판정)' }))
    $comMsg = '시도 안 함(클래식 Outlook 이 실행 중이 아님 - 수집할 때 수집기가 띄웁니다)'
    if ($pOl.Count) {
        # 같은 프로세스의 다른 스레드에서 25초까지만 기다린다(New-Object 는 부르지 않는다 - 마법사를 띄워 멈출 수 있다)
        $tr = Invoke-OcTimed -Sec 25 -Script { try { $o = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application'); '붙음 (버전 ' + $o.Version + ')' } catch { $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }; ('실행 중이지만 붙지 못함 - 0x{0:X8}' -f $e.HResult) } }
        if ($tr.done) { $comMsg = [string](@($tr.out) | Select-Object -Last 1); if (-not $comMsg) { $comMsg = '응답 없음' } }
        else { $comMsg = '25초 무응답 (대화상자·멈춤 의심)' }
        if ($comMsg -match '^붙음') {
            $pr = Test-OcProtectedRead -Sec 15
            W ("  주소 읽기(보낸 사람·받는 사람 - 사내/사외 판정 재료): {0}" -f $(switch ($pr.why) {
                'read' { '읽힘' } 'none' { '읽을 메일 없음(읽어도 됨)' } 'deny' { '거부됨 - 사내 메일임을 확인할 수 없어 메일·회의가 빠집니다' }
                'prompt' { 'Outlook 보안 확인 창이 떴습니다 - 창에서 허용·거부를 고르세요' } default { '붙지 못함' } }))
        }
    }
    W ("  COM 연결: {0}" -f $comMsg)
    $skp = Join-Path $root 'data\outlook\outlook_skip.json'
    if (Test-Path -LiteralPath $skp) { try { $sj = Get-Content -Raw -Encoding UTF8 -LiteralPath $skp | ConvertFrom-Json; W ("  지난 건너뜀 까닭: {0}" -f [string]$sj.reason) } catch {} }
    if (-not $classicOk -and ($trace.appx -or $trace.useNew)) { $findings.Add('클래식 Outlook 을 찾지 못함(새 Outlook 흔적 있음 - 의심) → Outlook 앱 경로는 실패할 가능성이 큽니다. Outlook 웹·Copilot 경로(collect.channels)가 대신 읽습니다.') }
    elseif (-not $classicOk) { $findings.Add('클래식 Outlook 을 찾지 못함(의심) → 수집기는 그래도 시도하고, 실패하면 Outlook 웹·Copilot 경로가 읽습니다.') }
    if ($classicOk -and $nProf -eq 0) { $findings.Add('메일 프로필 0개 → Outlook 을 직접 실행해 계정 설정을 마치세요.') }
    elseif ($nProf -gt 0 -and $prof.usable -eq 0) { $findings.Add('모든 메일 프로필이 주소록만 든 것으로 보입니다(R-NOPROF) → Outlook 을 직접 실행해 메일 계정을 추가하세요.') }
    if ($null -ne $trace.autoMig -and [int]$trace.autoMig -eq 1) { $findings.Add('새 Outlook 전환 정책이 켜져 있습니다 → Outlook 이 꺼져 있으면 수집기는 띄우지 않습니다(R-NEWOLPOL). 클래식 Outlook 을 켜 둔 채로 수집하세요.') }
    if ($elev -and $pOl.Count) { $findings.Add('관리자 권한으로 돌고 있어 일반 권한 Outlook 에 붙지 못할 수 있습니다(R-ELEV) → AgentFinder32 를 일반 권한으로 실행하세요.') }
    if ($pOl.Count -and $comMsg -notmatch '^붙음') { $findings.Add('클래식 Outlook 이 실행 중인데 붙지 못함 → 마법사·프로필 선택·암호 창이 떠 있을 가능성(의심). 그 창을 닫고 메일 화면까지 연 뒤 다시 수집하세요.') }
    if ($pr -and -not $pr.ok) { $findings.Add('Outlook 이 주소 읽기를 허용하지 않습니다(' + $pr.why + ') → 사내 메일인지 확인할 수 없어 메일·회의가 분석에서 빠집니다. Outlook 보안 확인 창에서 허용하거나 Outlook 웹 경로를 쓰세요.') }
}

# ── 전용 Edge(Outlook 웹·Copilot) ────────────────────────────────────────────
if ($chans -contains 'owa' -or $chans -contains 'copilot') {
    W '[전용 Edge - Outlook 웹·Copilot]'
    $edgeDir = Join-Path $root 'data\af32_edge'
    $hasProf = Test-Path -LiteralPath $edgeDir -PathType Container
    W ("  전용 Edge 프로필(data\af32_edge): {0}" -f $(if ($hasProf) { '있음(한 번 이상 열었음)' } else { '없음(아직 연 적 없음 - 첫 수집 때 만들고 회사 계정 로그인을 한 번 받습니다)' }))
    $own = Join-Path $edgeDir 'owner.json'
    $pend = ''
    if (Test-Path -LiteralPath $own) { try { $oj = Get-Content -Raw -Encoding UTF8 -LiteralPath $own | ConvertFrom-Json; $pend = [string]$oj.login_pending } catch {} }
    if ($pend.Length -gt 10) { $pend = $pend.Substring(0, 10) }   # 날짜만 - report\ 아래에는 시각을 쓰지 않는다(D10)
    W ("  로그인 대기: {0}" -f $(if ($pend) { '있음(' + $pend + ') - 전용 Edge 창에서 회사 계정으로 로그인하세요' } else { '없음' }))
    if ($pend) { $findings.Add('전용 Edge 가 로그인을 기다립니다 → 전용 Edge 창에서 회사 계정으로 한 번 로그인한 뒤 다시 수집하세요.') }
    $port = [int](Get-OcCfg $cfg 'copilotAuto' 'port' 9573)
    $up = $false
    try {
        $req = [System.Net.WebRequest]::Create(('http://127.0.0.1:{0}/json/version' -f $port))
        $req.Timeout = 2000; $req.Proxy = $null
        $resp = $req.GetResponse(); $up = $true; $resp.Close()
    } catch { $up = $false }
    W ("  전용 Edge 창(디버그 포트 {0}): {1}" -f $port, $(if ($up) { '열려 있음' } else { '닫혀 있음(수집할 때 띄웁니다)' }))
    $una = Join-Path $root 'data\outlook\src\mail_copilot_unavailable.json'
    if ($chans -contains 'copilot' -and (Test-Path -LiteralPath $una)) {
        try { $uj = Get-Content -Raw -Encoding UTF8 -LiteralPath $una | ConvertFrom-Json; if ($uj.until) { W ("  Copilot 메일 조회 불가 기억: {0} 까지 생략" -f [string]$uj.until); $findings.Add('Copilot 이 메일 조회 불가로 두 번 답해 ' + [string]$uj.until + ' 까지 묻지 않습니다 → 회사 Copilot 의 메일 접근 설정을 확인하세요.') } } catch {}
    }
}

# ── 지난 실행의 수집 단계(결과 코드만) ─────────────────────────────────────────
W '[지난 수집 단계]'
$lr = Join-Path $root 'report\last_run.json'
$bad = @{}
if (Test-Path -LiteralPath $lr) {
    try {
        $j = Get-Content -LiteralPath $lr -Raw -Encoding UTF8 | ConvertFrom-Json
        W ("  실행 시작 {0}" -f [string]$j.started)
        $n = 0
        foreach ($s in @($j.stages)) {
            if ($null -eq $s.rc) { continue }
            $n++
            W ("  {0} {1} - rc {2}{3}" -f $(if ($s.ok) { 'OK' } else { 'NG' }), [string]$s.name, [string]$s.rc, $(if ($s.reason) { ' · ' + [string]$s.reason } else { '' }))
            # 웹 경로 화면 구조 줄('구조:'·'구조+:' - 구조만, 글자는 x) - 사진에 담아 보내면 원인이 확정된다
            if ($s.census) { foreach ($cl in ([string]$s.census -split "`n")) { if ($cl.Trim()) { W ('      ' + $cl.Trim()) } } }
            if (-not $s.ok) { foreach ($r in (([string]$s.reason) -split ',')) { if ($r) { $bad[$r.Trim()] = $true } } }
        }
        if (-not $n) { W '  수집 단계 기록 없음' }
    } catch { W '  last_run.json 해석 실패' }
} else { W '  last_run.json 없음 (아직 실행 전)' }
if ($bad.ContainsKey('R-NODOMAIN')) { $findings.Add('사내 메일 도메인을 알 수 없어 분석하지 않았습니다 → 설정의 privacy.internalDomains 를 채우세요.') }
if ($bad.ContainsKey('R-LOGIN') -or $bad.ContainsKey('R-PERSONAL')) { $findings.Add('웹 경로가 로그인을 기다렸습니다 → 전용 Edge 창에서 회사 계정으로 로그인하세요(개인 Microsoft 계정은 읽지 않습니다).') }
if ($bad.ContainsKey('R-OMG')) { $findings.Add('Outlook 이 주소 읽기를 막았습니다(R-OMG) → Outlook 보안 확인 창에서 허용하거나 Outlook 웹 경로를 쓰세요.') }

# ── 판정 ─────────────────────────────────────────────────────────────────────
W '[판정]'
if (-not $findings.Count) { $findings.Add('특이사항 없음 - 켜 둔 수집 경로가 막혀 있지 않습니다. 그래도 비면 기간 안에 자료가 없거나 수집 중 오류입니다(지난 수집 단계의 rc·사유 참고).') }
$i = 0
foreach ($f in $findings) { $i++; W ("  {0}. {1}" -f $i, $f) }

try {
    if (-not (Test-Path -LiteralPath $repDir)) { New-Item -ItemType Directory -Force -Path $repDir | Out-Null }
    # report\ 아래에는 날짜만(D10) - 지난 실행 기록·화면 구조 줄에 섞인 하루 중 시각(14:30 · 14시 30분)은 [시각] 으로 가린다
    $clock = '(?<![\d:])(?:[01]?\d|2[0-3])(?:\s?:\s?|\s?시\s?)[0-5]\d(?::[0-5]\d)?(?:\s?분)?(?![\d:])'
    [System.IO.File]::WriteAllLines($outP, [string[]]@($L | ForEach-Object { $_ -replace $clock, '[시각]' }), (New-Object System.Text.UTF8Encoding($true)))
    Write-Host ("→ 저장: {0}  (메일·일정 내용·주소·날짜별 건수는 담지 않았습니다 - [판정]대로 이 PC 안에서 조치하면 됩니다)" -f $outP)
} catch { Write-Host ('→ 저장 실패: ' + $_.Exception.Message) }
exit 0
