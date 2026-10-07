# Get-TeamsWindow.ps1
# 켜져 있는 Teams 앱 창에서 '지금 보이는 채팅'을 UI 자동화(UIA)로 읽는다.
# Graph 권한도, 관리자도, Copilot도 필요 없다 — 단 열려 있는 대화의 화면에 렌더된 부분만 읽힌다.
# 읽기 전용이며 네트워크를 쓰지 않는다. 출력: ..\data\m365\teams_window.csv (날짜를 짚은 줄만)
#
# 사용: 팀즈에서 보고 싶은 대화를 열어 스크롤해 두고  ->  powershell -File collect\Get-TeamsWindow.ps1
#  · kind: 본인이 보낸 줄은 sent, 그 외 msg. 본인 판정은 config.teamsSelfNames + owner + 윈도우 계정 +
#    로그온 표시명(AD) + 나/You/본인 (대소문자 무시). 이름을 못 잡으면 msg 로 남는다(수동 흔적).
#  · 날짜: 8/15 · 8월 15일 · 2026. 8. 15. · Aug 15 · 요일(월요일·Mon·月曜日 → 가장 최근 그 요일) · 오늘/어제.
#    LM28(C-19·W1-15): 날짜 표기가 없는 줄은 수집일로 '추정'하지 않는다 — data\m365\undated_teams_window.csv 에만
#    따로 적는다(분석기는 teams_*.csv 만 읽으므로 시간 계산에 들어가지 않는다. 웹 경로가 같은 줄을 버리는 것과 같은 규칙).
#  · 왼쪽 채팅 목록(좁은 열의 ListItem)은 메시지 영역이 보일 때 파싱에서 제외한다(-KeepChatList 로 해제).
# LM28(C-18·C-20·F-30):
#  · 창: 팀즈 프로세스(이 세션)의 **모든 최상위 창**을 본다(MainWindowHandle 하나만 보면 팝아웃 채팅 창이 빠진다).
#    숨김·최소화(iconic)·다른 가상 데스크톱(cloaked)·화면 밖 창은 읽지 않고 counts 와 empty_cause 로 남긴다.
#    제목 끝이 '(free)'·'(무료)' 인 개인용 Teams 창은 읽지 않는다. 요소가 20개 미만이면 1.5초 뒤 1번 다시 읽는다.
#    창 목록은 user32 를 메모리 안 동적 형식으로 부른다(Add-Type 처럼 컴파일러 프로세스를 띄우지 않는다).
#  · 원문 덤프(teams_window_raw.txt)는 config.teamsWindowRawDump=true 일 때만 남긴다(기본 끔 — 채팅 원문).
#  · 중복은 원문 키(time|from|chat|요지 40자)로 본다. 개인정보가 든 줄이 G1(run.py scrub_csv) 뒤 한 번 더 들어오면 그 G1 이
#    key_cols 로 접는다. CSV 열은 더하지 않는다.
#  · 종료 코드 = LMSTATUS rc: 0 새 줄 저장 / 4 읽었지만 새 줄 0 / 1 팀즈 프로세스 없음(R-NOTEAMS)
#    / 3 R-UIAEMPTY(읽을 창이 없거나 창이 비었음 — counts.empty_cause: no_window·hidden·iconic·cloaked·offscreen·excluded·empty_tree).
#    마지막 줄 LMSTATUS {v,src:'teams_window',rc,reason,counts,ranges} — 창 읽기는 그 날을 다 읽었다고 말할 수 없어 ranges 는
#    이번에 날짜를 짚은 날의 partial(증인)뿐이다. counts.teams_present: 새 Teams(Appx MSTeams)·클래식 설치·프로세스가 있나.
#  · 함수로도 쓴다: . collect\Get-TeamsWindow.ps1 (직접 실행 가드 — 점 소싱이면 함수만 정의) 후 Invoke-TeamsWindowRead.
#    상시 샘플러(Start-TeamsSampler.ps1)가 이렇게 1번 불러 루프에서 함수를 부른다(주기마다 powershell 을 띄우지 않는다).
#    시험 주입: -Windows(창 기록 @{title;visible;iconic;cloaked;on_screen;texts;retry}) · -Present · -Cfg · -OutDir · -Today.
param([int]$MaxElements = 4000, [string]$RawFile = '', [switch]$KeepChatList)

$script:TwRoot = Split-Path -Parent $PSScriptRoot
$script:twQuiet = $false
$script:twPersonalRx = 'Microsoft Teams\s*\((?:free|무료)\)\s*$'   # 개인용 Teams 제품 창(회사 창은 '… | Microsoft Teams')

function Write-TwLine([string]$s) {
    if (-not $script:twQuiet) { Write-Host $s }
}

function Get-TwSelfNames([object]$cfg, [bool]$replay) {
    # 본인 판정 이름 집합(소문자·공백 제거 변형 포함). 재생 모드(-RawFile)는 다른 PC 원문일 수 있어 설정값만 쓴다.
    $names = New-Object System.Collections.Generic.List[string]
    try { foreach ($x in @($cfg.teamsSelfNames)) { if ($x) { $names.Add([string]$x) } } } catch {}
    try { if ($cfg.owner) { $names.Add([string]$cfg.owner) } } catch {}
    $nCfg = $names.Count                      # 설정으로 준 이름 수 - 0 이면 AD 표시명까지 시도한다
    if (-not $replay) {
        if ($env:USERNAME) { $names.Add([string]$env:USERNAME) }
        $disp = ''
        # 로그온 화면 표시명(회사 AD 표시명 = Teams 표시명이 대부분) - 레지스트리는 오프라인에서도 즉시 읽힌다
        try {
            $lu = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI' -ErrorAction Stop
            $lastUser = [string]$lu.LastLoggedOnSAMUser
            if (-not $lastUser) { $lastUser = [string]$lu.LastLoggedOnUser }
            if ($lu.LastLoggedOnDisplayName -and $lastUser -and (($lastUser -split '\\')[-1] -ieq [string]$env:USERNAME)) {
                $disp = [string]$lu.LastLoggedOnDisplayName
            }
        } catch {}
        if (-not $disp -and $nCfg -eq 0) {
            # 설정도 레지스트리도 없을 때만 AD 에 묻는다(오프라인 도메인 PC 에서는 느릴 수 있어 마지막 수단)
            try {
                Add-Type -AssemblyName System.DirectoryServices.AccountManagement
                $disp = [string]([System.DirectoryServices.AccountManagement.UserPrincipal]::Current.DisplayName)
            } catch { $disp = '' }
        }
        if ($disp) { $names.Add($disp) }
    }
    foreach ($x in @('나', '본인', 'you', 'me')) { $names.Add($x) }
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($x in $names) {
        $v = ([string]$x).Trim().ToLower()
        if (-not $v) { continue }
        [void]$set.Add($v)
        [void]$set.Add(($v -replace '\s+', ''))
    }
    return ,$set
}
function Is-Self([string]$from) {
    if (-not $from) { return $false }
    $f = $from.Trim().ToLower()
    foreach ($c in @($f, ($f -replace '\s+', ''), ($f -replace '\s*(님|씨)$', ''), (($f -replace '\s*(님|씨)$', '') -replace '\s+', ''))) {
        if ($c -and $script:twMyNames.Contains($c)) { return $true }
    }
    return $false
}

# ── 창 찾기(C-18): 팀즈 프로세스의 모든 최상위 창 ──────────────────────────────────────────
# user32 를 Add-Type(C# 컴파일 = csc.exe 프로세스)이 아니라 메모리 안 동적 형식(DefinePInvokeMethod)으로 부른다 —
# 샘플러가 오래 돌아도 프로세스를 하나도 띄우지 않고, 임시 DLL 을 쓰지 않아 AppLocker 의 DLL 규칙에도 덜 걸린다.
# 콜백이 필요한 EnumWindows 대신 FindWindowEx(바탕 화면 자식 = 최상위 창)를 차례로 부른다(같은 창 목록).
function Get-TwWin32 {
    if ($script:TwWin32) { return $script:TwWin32 }
    $an = New-Object System.Reflection.AssemblyName('Lm28TeamsWin')
    $ab = [AppDomain]::CurrentDomain.DefineDynamicAssembly($an, [System.Reflection.Emit.AssemblyBuilderAccess]::Run)
    $mb = $ab.DefineDynamicModule('Lm28TeamsWin')
    $tb = $mb.DefineType('Lm28TeamsWin.Native', [System.Reflection.TypeAttributes]'Public, Class, Abstract, Sealed')
    $defs = @(
        @('user32.dll', 'FindWindowExW', [IntPtr], @([IntPtr], [IntPtr], [IntPtr], [IntPtr])),
        @('user32.dll', 'GetWindowThreadProcessId', [UInt32], @([IntPtr], [UInt32[]])),
        @('user32.dll', 'IsWindowVisible', [bool], @([IntPtr])),
        @('user32.dll', 'IsIconic', [bool], @([IntPtr])),
        @('user32.dll', 'GetWindowTextLengthW', [int], @([IntPtr])),
        @('user32.dll', 'GetWindowTextW', [int], @([IntPtr], [System.Text.StringBuilder], [int])),
        @('user32.dll', 'GetWindowRect', [bool], @([IntPtr], [Int32[]])),
        @('user32.dll', 'GetWindowLongW', [int], @([IntPtr], [int])),
        @('user32.dll', 'GetSystemMetrics', [int], @([int])),
        @('dwmapi.dll', 'DwmGetWindowAttribute', [int], @([IntPtr], [int], [Int32[]], [int]))
    )
    foreach ($d in $defs) {
        $m = $tb.DefinePInvokeMethod([string]$d[1], [string]$d[0],
            [System.Reflection.MethodAttributes]'Public, Static, PinvokeImpl',
            [System.Reflection.CallingConventions]::Standard, [Type]$d[2], [Type[]]@($d[3]),
            [System.Runtime.InteropServices.CallingConvention]::Winapi, [System.Runtime.InteropServices.CharSet]::Unicode)
        $m.SetImplementationFlags([System.Reflection.MethodImplAttributes]::PreserveSig)
    }
    $script:TwWin32 = $tb.CreateType()
    return $script:TwWin32
}

function Get-TwTopWindows([int[]]$Pids, [int]$Max = 20000) {
    # 최상위 창 → @{hwnd; pid; title; visible; iconic; cloaked; on_screen; tool}. $Pids 가 비면 모든 창(시험·진단용).
    $out = New-Object System.Collections.Generic.List[object]
    $t = Get-TwWin32
    $want = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($p in @($Pids)) { [void]$want.Add([int]$p) }
    $vx = $t::GetSystemMetrics(76); $vy = $t::GetSystemMetrics(77); $vw = $t::GetSystemMetrics(78); $vh = $t::GetSystemMetrics(79)
    $pidBuf = New-Object 'UInt32[]' 1
    $rc = New-Object 'Int32[]' 4
    $cl = New-Object 'Int32[]' 1
    $h = [IntPtr]::Zero
    for ($i = 0; $i -lt $Max; $i++) {
        $h = $t::FindWindowExW([IntPtr]::Zero, $h, [IntPtr]::Zero, [IntPtr]::Zero)
        if ($h -eq [IntPtr]::Zero) { break }
        $pidBuf[0] = 0
        [void]$t::GetWindowThreadProcessId($h, $pidBuf)
        if ($want.Count -gt 0 -and -not $want.Contains([int]$pidBuf[0])) { continue }
        $len = $t::GetWindowTextLengthW($h)
        $title = ''
        if ($len -gt 0) {
            $sb = New-Object System.Text.StringBuilder ($len + 2)
            [void]$t::GetWindowTextW($h, $sb, $sb.Capacity)
            $title = $sb.ToString()
        }
        $cloaked = $false
        $cl[0] = 0
        try { if ($t::DwmGetWindowAttribute($h, 14, $cl, 4) -eq 0) { $cloaked = ($cl[0] -ne 0) } } catch {}
        $on = $false
        if ($t::GetWindowRect($h, $rc)) {
            $ix = [Math]::Min($rc[2], $vx + $vw) - [Math]::Max($rc[0], $vx)
            $iy = [Math]::Min($rc[3], $vy + $vh) - [Math]::Max($rc[1], $vy)
            $on = ($ix -gt 0 -and $iy -gt 0)
        }
        $out.Add(@{ hwnd = $h; pid = [int]$pidBuf[0]; title = $title; visible = [bool]$t::IsWindowVisible($h)
                    iconic = [bool]$t::IsIconic($h); cloaked = $cloaked; on_screen = $on
                    tool = ((($t::GetWindowLongW($h, -20)) -band 0x80) -ne 0) })
    }
    return ,$out
}

function Get-TeamsProcs {
    # 이 세션의 팀즈 프로세스(새 Teams = ms-teams.exe, 클래식 = Teams.exe) — 다른 사용자 세션의 창은 읽지 않는다
    $sid = -1
    try { $sid = [System.Diagnostics.Process]::GetCurrentProcess().SessionId } catch {}
    return @(Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -match '^(ms-teams|Teams|msteams)$' -and ($sid -lt 0 -or $_.SessionId -eq $sid) })
}

function Get-TeamsPresent([object[]]$Procs) {
    # 팀즈를 쓰는 PC 인가(counts.teams_present) — 새 Teams 패키지(MSTeams)·클래식 사용자 설치·실행 중 프로세스. 읽기만 한다.
    $r = @{ present = $false; appx = $false; classic = $false; proc = (@($Procs).Count -gt 0) }
    try {
        $base = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'
        if (Test-Path -LiteralPath $base) {
            $r.appx = (@(Get-ChildItem -LiteralPath $base -Name -ErrorAction SilentlyContinue | Where-Object { $_ -like 'MSTeams_*' }).Count -gt 0)
        }
    } catch {}
    try { if (-not $r.appx -and $env:LOCALAPPDATA -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\ms-teams.exe'))) { $r.appx = $true } } catch {}
    try { if ($env:LOCALAPPDATA -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Microsoft\Teams\current\Teams.exe'))) { $r.classic = $true } } catch {}
    $r.present = ($r.appx -or $r.classic -or $r.proc)
    return $r
}

# ── 창 읽기: ListItem 기하로 '왼쪽 채팅 목록 열'을 찾아 메시지 영역만 남긴다 ─────────────────
function Get-ListColumn([object[]]$rects, [double]$winLeft, [double]$winWidth) {
    # $rects: ListItem 사각형(Left/Right/Width). 왼쪽 '채팅 목록 열'을 찾아 그 x 범위를 돌려준다.
    #
    # ★ 회귀 사고(LM22): 예전에는 '항목이 가장 많은 좁은 그룹'을 목록으로 보고, 마지막 가드가
    #   그룹의 **폭**($rg - $l)만 봤다. 그런데 대화를 스크롤하면 화면에 보이는 **메시지 말풍선**이
    #   채팅 목록 항목보다 많아진다. 그래서 메시지 열이 '가장 많은 그룹'으로 뽑히고,
    #   예: 창 1920 에서 메시지 열이 x 452~1052 이면 시작 23.5%(<40%)·폭 31%(<45%) 라 가드를
    #   전부 통과해 **메시지가 100% 삭제**됐다. 그 결과 시각 패턴 0줄 → 신규 0건 → CSV 헤더만 남고,
    #   스크립트는 exit 0 이라 run.py 는 '성공'으로 기록해 화면 어디에도 실패가 뜨지 않았다.
    #   (창 폭 1024~1920 = 흔한 사내 노트북에서 재현. 초광폭에서만 우연히 무사했다.)
    #
    # 고친 규칙 — 채팅 목록 열은 '창 왼쪽에 붙어 있고 왼쪽 절반 안에서 끝난다':
    #   · 시작이 창 왼쪽 25% 안                     (목록은 좌측 레일 옆에 붙는다)
    #   · **오른쪽 끝도** 창 왼쪽 45% 안             ← 예전에 없어서 사고가 났다(폭만 봤다)
    #   · 항목 3개 이상 · 넓은 항목(메시지)이 하나라도 보일 때만
    #   · 여러 후보가 있으면 '가장 많은' 것이 아니라 **가장 왼쪽** 것을 고른다
    $wide = 0; $groups = @{}
    foreach ($r in $rects) {
        if ($r.Width -le 0) { continue }
        if ($r.Width -ge 0.45 * $winWidth) { $wide++; continue }
        $k = [int][math]::Round(($r.Left - $winLeft) / 24.0)
        if (-not $groups.ContainsKey($k)) { $groups[$k] = New-Object System.Collections.Generic.List[object] }
        $groups[$k].Add($r)
    }
    if ($wide -eq 0) { return $null }          # 메시지 영역이 안 보이면 거를 것도 없다(목록만 띄운 경우)
    $best = $null; $bl = 0.0; $br = 0.0
    foreach ($g in $groups.Values) {
        if ($g.Count -lt 3) { continue }
        $l = [double]::MaxValue; $rg = [double]::MinValue
        foreach ($r in $g) { if ($r.Left -lt $l) { $l = $r.Left }; if ($r.Right -gt $rg) { $rg = $r.Right } }
        if (($l - $winLeft) -gt 0.25 * $winWidth) { continue }      # 창 왼쪽에 붙어 있어야 한다
        if (($rg - $winLeft) -ge 0.45 * $winWidth) { continue }     # 왼쪽 절반 안에서 끝나야 한다
        if ($null -eq $best -or $l -lt $bl) { $best = $g; $bl = $l; $br = $rg }
    }
    if ($null -eq $best) { return $null }
    return @{ left = $bl; right = $br; n = $best.Count }
}
function Initialize-TwUia {
    if ($script:twUiaReady) { return }
    Add-Type -AssemblyName UIAutomationClient      # GAC 어셈블리 적재 — 컴파일러 프로세스를 띄우지 않는다
    Add-Type -AssemblyName UIAutomationTypes
    $script:twUiaReady = $true
}
function Read-TeamsTexts([IntPtr]$hwnd, [int]$maxElements, [bool]$keepList) {
    $res = @{ name = ''; count = 0; texts = (New-Object System.Collections.Generic.List[string]); skipped = 0; column = $null;
              skippedTexts = (New-Object System.Collections.Generic.List[string]) }
    $el = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
    $res.name = [string]$el.Current.Name
    $cond = [System.Windows.Automation.Automation]::ContentViewCondition
    $all = $null; $cached = $false
    try {
        # 이름·종류·사각형을 한 번의 왕복으로 받아온다(요소마다 Current.* 를 부르면 수천 번 왕복)
        $cr = New-Object System.Windows.Automation.CacheRequest
        $cr.Add([System.Windows.Automation.AutomationElement]::NameProperty)
        $cr.Add([System.Windows.Automation.AutomationElement]::ControlTypeProperty)
        $cr.Add([System.Windows.Automation.AutomationElement]::BoundingRectangleProperty)
        $cr.TreeScope = [System.Windows.Automation.TreeScope]::Element
        $act = $cr.Activate()
        try { $all = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond) } finally { $act.Dispose() }
        $cached = $true
    } catch { $all = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond) }
    $res.count = $all.Count
    $wr = $el.Current.BoundingRectangle
    $listId = ([System.Windows.Automation.ControlType]::ListItem).Id
    $col = $null
    if (-not $keepList -and -not $wr.IsEmpty -and $wr.Width -gt 0) {
        $rects = New-Object System.Collections.Generic.List[object]
        $n = 0
        foreach ($e in $all) {
            $n++; if ($n -gt $maxElements) { break }
            try {
                $info = if ($cached) { $e.Cached } else { $e.Current }
                if ($info.ControlType.Id -ne $listId) { continue }
                $r = $info.BoundingRectangle
                if (-not $r.IsEmpty) { $rects.Add([pscustomobject]@{ Left = $r.Left; Right = $r.Right; Width = $r.Width }) }
            } catch {}
        }
        $col = Get-ListColumn $rects.ToArray() $wr.Left $wr.Width
    }
    $res.column = $col
    $n = 0
    foreach ($e in $all) {
        $n++; if ($n -gt $maxElements) { break }
        try {
            $info = if ($cached) { $e.Cached } else { $e.Current }
            $nm = [string]$info.Name
            if (-not ($nm -and $nm.Length -ge 4 -and $nm.Length -le 600)) { continue }
            if ($col) {
                $r = $info.BoundingRectangle
                if (-not $r.IsEmpty -and $r.Width -lt 0.45 * $wr.Width) {
                    $cx = $r.Left + $r.Width / 2
                    if ($cx -ge $col.left -and $cx -le $col.right) { $res.skipped++; $res.skippedTexts.Add($nm); continue }
                }
            }
            $res.texts.Add($nm)
        } catch {}
    }
    return $res
}
function Read-TwInjected($w) {
    # 시험 주입 창 — texts(첫 판독) · retry(다시 읽기, 없으면 같은 내용)
    $res = @{ name = [string]$w.title; count = 0; texts = (New-Object System.Collections.Generic.List[string]); skipped = 0
              column = $null; skippedTexts = (New-Object System.Collections.Generic.List[string]) }
    foreach ($x in @($w.texts)) { if ($x -and ([string]$x).Length -ge 4) { $res.texts.Add([string]$x) } }
    $res.count = $res.texts.Count
    if ($w.ContainsKey('count')) { $res.count = [int]$w.count }
    return $res
}

# ── 메시지 파싱 (best-effort): 이름 + 시각 패턴이 있는 줄을 메시지로 취급 ──
function Csv-Escape([string]$s) {
    $s = $s -replace "[`r`n]+", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}
# ── 시각 정규식은 이 PC 의 Windows 지역 설정에서 자동 구성한다 ───────────────────────────
# 회사 PC 의 원문(raw)은 보안상 밖으로 보낼 수 없다 - 형식을 '그 PC 안에서' 알아내야 한다.
#  · 오전/오후 표기: 고정 목록(한/영/일/중/독) + 현재 문화권의 AMDesignator/PMDesignator
#  · 구분자: 문화권 단시간 형식에 '.' 이 있으면 '14.10' 도 받는다(핀란드 등)
#  · 그래도 0줄이면 일반 형식(숫자:숫자 / 숫자.숫자)으로 한 번 더 시도한다
#  · config.teamsTimeRegex 가 있으면 최우선(그룹: 1=앞 표기, 2=시, 3=분, 4=뒤 표기 - 빈 그룹 허용)
function Initialize-TwParse([object]$cfgObj) {
    $ci = Get-Culture
    $script:twCi = $ci
    $script:twAmD = [string]$ci.DateTimeFormat.AMDesignator; $script:twPmD = [string]$ci.DateTimeFormat.PMDesignator
    $pmSet = @('오후', 'PM', 'pm', 'p.m.', 'P.M.', '午後', '下午', 'nachm.'); if ($script:twPmD) { $pmSet += $script:twPmD }
    $amSet = @('오전', 'AM', 'am', 'a.m.', 'A.M.', '午前', '上午', 'vorm.'); if ($script:twAmD) { $amSet += $script:twAmD }
    $script:twPmSet = $pmSet; $script:twAmSet = $amSet
    $desig = (($amSet + $pmSet) | Where-Object { $_ } | Select-Object -Unique | ForEach-Object { [regex]::Escape($_) }) -join '|'
    $sepRe = ':'
    if ($ci.DateTimeFormat.ShortTimePattern -match '\.') { $sepRe = '[:.]' }
    # 숫자 앞뒤 경계는 \b 가 아니라 '숫자 아님'으로 본다 - '午後2:10' 처럼 CJK 글자 바로 뒤에 숫자가 오면 \b 가 성립하지 않는다(시험 실측)
    $script:twReTime = '(?:(' + $desig + ')\s*)?(?<!\d)(\d{1,2})' + $sepRe + '(\d{2})(?!\d)(?:\s*(' + $desig + '))?'
    $script:twReTimeGeneric = '()?(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)()?'   # 0줄일 때의 마지막 시도 - 구분자·표기 무관(그룹 수 동일)
    $script:twCfgRe = ''
    try { $script:twCfgRe = [string]$cfgObj.teamsTimeRegex } catch {}
    if ($script:twCfgRe) { $script:twReTime = $script:twCfgRe; Write-TwLine '[teams-window] config.teamsTimeRegex 사용' }
    $script:twDayFirst = [bool]($ci.DateTimeFormat.ShortDatePattern -match '^d')      # dd.MM / dd/MM 문화권이면 '15.08' 은 일.월
    # 문화권 월 이름(독일어 Mrz/Okt, 프랑스어 août 등) - 영문은 아래 $reMon 이 엄격하게 처리하므로 영문 외만
    $monC = @{}
    if ($ci.TwoLetterISOLanguageName -notin @('en', 'ko')) {
        $nms = @($ci.DateTimeFormat.AbbreviatedMonthNames) + @($ci.DateTimeFormat.MonthNames)
        for ($i = 0; $i -lt $nms.Count; $i++) {
            $nm = [string]$nms[$i]
            if ($nm -and $nm.Length -ge 2 -and $nm -notmatch '^\d') { $monC[$nm.ToLower()] = ($i % 12) + 1 }
        }
    }
    $script:twMonC = $monC
    $script:twReMonC = ''
    if ($monC.Count) { $script:twReMonC = '(' + (($monC.Keys | Sort-Object { -$_.Length } | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')' }
    # 영문 월 이름: 전체 철자 화이트리스트 + 대소문자 구분(-cmatch) - 'Mark'·'Mary'·'separate' 를 3월/9월로 오인하지 않게(검증 확정)
    $script:twReMon = '(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    $script:twMon = @{jan=1;feb=2;mar=3;apr=4;may=5;jun=6;jul=7;aug=8;sep=9;oct=10;nov=11;dec=12}
    # 요일 토큰(소문자) → .NET DayOfWeek(일=0). 한·영·일·중 고정 + 이 PC 문화권의 요일 이름. 한 글자('월'·'月')는 '8월' 과 섞여 제외
    $dow = @{}
    $fixedDays = @(
        @('일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'),
        @('sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'),
        @('sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'),
        @('sun', 'mon', 'tues', 'wed', 'thur', 'fri', 'sat'),
        @('sun', 'mon', 'tues', 'wed', 'thurs', 'fri', 'sat'),
        @('日曜日', '月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日'),
        @('日曜', '月曜', '火曜', '水曜', '木曜', '金曜', '土曜'),
        @('星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'),
        @('周日', '周一', '周二', '周三', '周四', '周五', '周六'))
    foreach ($arr in $fixedDays) { for ($i = 0; $i -lt 7; $i++) { $dow[$arr[$i]] = $i } }
    foreach ($arr in @(, @($ci.DateTimeFormat.DayNames)) + @(, @($ci.DateTimeFormat.AbbreviatedDayNames))) {
        for ($i = 0; $i -lt 7 -and $i -lt $arr.Count; $i++) {
            $nm = ([string]$arr[$i]).Trim().ToLower()
            if ($nm.Length -ge 2 -and -not $dow.ContainsKey($nm)) { $dow[$nm] = $i }
        }
    }
    $script:twDow = $dow
    $script:twReDow = '(?<![\p{L}])(' + (($dow.Keys | Sort-Object { -$_.Length } | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')(?:에|에는)?(?![\p{L}])[\s,:·-]*(?:at\s+)?$'
    $script:twReToday = '(?<![\p{L}])(오늘|today|今日|今天)(?:에|에는)?(?![\p{L}])'
    $script:twReYesterday = '(?<![\p{L}])(어제|yesterday|昨日|昨天)(?:에|에는)?(?![\p{L}])'
    $script:twRxOpt = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
}
function Day-Of([int]$m, [int]$dd, [datetime]$ref) {
    # 연도 없는 월/일 → 가장 최근의 그 날짜(오늘 포함). 날짜 단위로 비교한다 - 시각까지 비교하면
    # 오늘 날짜 줄이 작년으로 밀리고(검증 확정), 2/30 같은 잘못된 날짜는 무시한다.
    try { $x = [datetime]::new($ref.Year, $m, $dd) } catch { return $null }
    if ($x -gt $ref.Date) { try { $x = [datetime]::new($ref.Year - 1, $m, $dd) } catch { return $null } }
    return $x
}
function Find-HeaderDate([string]$pre, [datetime]$ref) {
    # 시각 앞(헤더) 문자열에서 날짜 토큰 하나를 찾는다 → @{date; idx; len; est}. 본문(시각 뒤)의 '8/15 까지' 는 보지 않는다.
    # est=true 면 날짜 표기가 없다(LM28: 수집일로 추정하지 않고 undated 파일로 보낸다)
    $r = @{ date = $ref.Date; idx = -1; len = 0; est = $true }
    $rxOpt = $script:twRxOpt
    $m = [regex]::Match($pre, '(?<!\d)(\d{4})\s*[.년年/-]\s*(\d{1,2})\s*[.월月/-]\s*(\d{1,2})\s*[.일日]?(?!\d)')
    if ($m.Success) {
        # 2026. 8. 15. / 2026년 8월 15일 / 2026-08-15 - 연도가 있으면 그대로
        try { $x = [datetime]::new([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value) } catch { $x = $null }
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = [regex]::Match($pre, '(?<!\d)(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]')
    if ($m.Success) {
        # 8월 15일 / 8月15日 (한·일·중)
        $x = Day-Of ([int]$m.Groups[1].Value) ([int]$m.Groups[2].Value) $ref
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = [regex]::Match($pre, '(?<!\d)(\d{1,2})\s?[/.]\s?(\d{1,2})\.?(?!\d)')
    if ($m.Success) {
        # 8/15 (월/일, 한국·미국) 또는 15.08 / 15/08 (일.월, 유럽) - 이 PC 의 날짜 순서(dayFirst)를 따르되 12 초과 숫자로 보정
        $a = [int]$m.Groups[1].Value; $b = [int]$m.Groups[2].Value
        $mo = $a; $dd = $b
        if ($script:twDayFirst) { $mo = $b; $dd = $a }
        if ($mo -gt 12 -and $dd -le 12) { $t0 = $mo; $mo = $dd; $dd = $t0 }
        if ($mo -ge 1 -and $mo -le 12 -and $dd -ge 1 -and $dd -le 31) {
            $x = Day-Of $mo $dd $ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
    }
    if ($script:twReMonC) {
        $m = [regex]::Match($pre, ('\b(\d{1,2})\.?\s*' + $script:twReMonC + '\b'), $rxOpt)
        if ($m.Success) {
            # 15. Aug / 15 août (이 PC 문화권의 월 이름, 일-월)
            $x = Day-Of $script:twMonC[$m.Groups[2].Value.ToLower()] ([int]$m.Groups[1].Value) $ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
        $m = [regex]::Match($pre, ('\b' + $script:twReMonC + '\.?\s+(\d{1,2})\b'), $rxOpt)
        if ($m.Success) {
            $x = Day-Of $script:twMonC[$m.Groups[1].Value.ToLower()] ([int]$m.Groups[2].Value) $ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
    }
    $m = [regex]::Match($pre, ('\b(\d{1,2})\s+' + $script:twReMon + '\b'))
    if ($m.Success) {
        # '15 Aug' (일 월) - 월-일 분기보다 먼저 본다(뒤에 두면 'Aug 3' 류 오인)
        $x = Day-Of $script:twMon[$m.Groups[2].Value.Substring(0, 3).ToLower()] ([int]$m.Groups[1].Value) $ref
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = [regex]::Match($pre, ('\b' + $script:twReMon + '\.?\s+(\d{1,2})\b'))
    if ($m.Success) {
        # 'Aug 15' / 'August 15' (월 일)
        $x = Day-Of $script:twMon[$m.Groups[1].Value.Substring(0, 3).ToLower()] ([int]$m.Groups[2].Value) $ref
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = [regex]::Match($pre, $script:twReYesterday, $rxOpt)
    if ($m.Success) { $r.date = $ref.Date.AddDays(-1); $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    $m = [regex]::Match($pre, $script:twReToday, $rxOpt)
    if ($m.Success) { $r.date = $ref.Date; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    $m = [regex]::Match($pre, $script:twReDow, $rxOpt)
    if ($m.Success) {
        # 요일 → 가장 최근 그 요일. Teams 는 오늘 것은 시각만, 어제는 '어제', 그 전 6일은 요일로 보여 주므로
        # 오늘과 같은 요일은 지난주(7일 전)로 본다
        $key = $m.Groups[1].Value.ToLower()
        if ($script:twDow.ContainsKey($key)) {
            $delta = ([int]$ref.DayOfWeek - [int]$script:twDow[$key] + 7) % 7
            if ($delta -eq 0) { $delta = 7 }
            $r.date = $ref.Date.AddDays(-$delta); $r.idx = $m.Index; $r.len = $m.Groups[1].Length; $r.est = $false; return $r
        }
    }
    return $r
}
function Parse-TwLines([object[]]$Lines, [string]$re, [datetime]$Today) {
    # 한 번의 파싱 패스 - 지역 설정 정규식으로 0줄이면 일반 형식으로 다시 부른다.
    # 반환 rows: @{line; time; from; chat; summary; est; kind} 목록, n: 시각 패턴 줄 수
    $out = New-Object System.Collections.Generic.List[object]
    $n = 0; $chat = ''
    $rxOpt = $script:twRxOpt
    foreach ($ln in $Lines) {
    $tm = [regex]::Match($ln, $re, $rxOpt)   # 대소문자 무시(pm/PM) - 첫 시각 패턴이 헤더
    # 대화방 제목 후보 (창 상단): "홍길동 채팅" / "프로젝트A 팀" / "Project A chat" / "홍길동 | Microsoft Teams" - 시각이 있는 줄은 메시지다
    if (-not $tm.Success) {
        if ($ln -match '^(.{2,40})\s(채팅|대화|팀|채널|chat|Chat|team|Team|channel|Channel)$') { $chat = $Matches[1] }
        elseif ($ln -match '^(.{2,40}?)\s*[|·-]\s*Microsoft Teams$') { $chat = $Matches[1] }
        continue
    }
    $n++
    $hh = [int]$tm.Groups[2].Value; $mm = $tm.Groups[3].Value
    $ap = ''
    foreach ($g in @($tm.Groups[1].Value, $tm.Groups[4].Value)) {
        if ($g) { if ($script:twPmSet -contains $g) { $ap = 'PM' } elseif ($script:twAmSet -contains $g) { $ap = 'AM' } }
    }
    if ($ap -eq 'PM' -and $hh -lt 12) { $hh += 12 }
    if ($ap -eq 'AM' -and $hh -eq 12) { $hh = 0 }
    if ($hh -gt 23 -or [int]$mm -gt 59) { continue }
    # 헤더(시각 앞) / 본문(시각 뒤) 로 나눈다 - 날짜·발신자는 헤더에서만 찾고, 본문의 '8/15 까지' 는 날짜로 보지 않는다
    $pre = $ln.Substring(0, $tm.Index)
    $post = $ln.Substring($tm.Index + $tm.Length)
    $fd = Find-HeaderDate $pre $Today
    $d = $fd.date
    $preClean = $pre
    if ($fd.idx -ge 0) {
        $preClean = $pre.Substring(0, $fd.idx) + ' ' + $pre.Substring($fd.idx + $fd.len)
        $preClean = $preClean -replace '(?<!\d)(19|20)\d{2}\s*[년年]?(?!\d)', ' '   # '2026년 8/15' 류의 남은 연도 토큰
    }
    $t = ('{0} {1:d2}:{2}' -f $d.ToString('yyyy-MM-dd'), $hh, $mm)
    # 발신자: 헤더의 첫 토큰(2~20자) - 'Name, 9:30 AM'·'홍길동님이'·'Name says' 를 받는다. 날짜·요일 토큰은 이미 지웠다
    $from = ''
    if ($preClean -match '^\s*([\p{L}0-9 .]{2,20}?)\s*,?\s*(?:님이|says|said|wrote)?\s*[,:·-]?\s*$') { $from = $Matches[1].Trim() }
    $rest = $preClean
    if ($from) { $rest = $rest -replace ('^\s*' + [regex]::Escape($from) + '\s*,?\s*(?:님이|says|said|wrote)?\s*[,:·-]?'), '' }
    $post = $post -replace '^\s*[,:·|-]*\s*', ''
    $body = (($rest.Trim() + ' ' + $post) -replace '\s{2,}', ' ').Trim()
    if ($body.Length -lt 3) { continue }
    $kind = if (Is-Self $from) { 'sent' } else { 'msg' }
    $summary = $body.Substring(0, [Math]::Min(200, $body.Length))
    # replied_time 은 창 읽기로는 측정할 수 없다 - '미응답'이라고 단정하지 않고 빈 값(미측정)으로 둔다
    $line = ('{0},{1},{2},{3},{4},{5}' -f $t, (Csv-Escape $from), (Csv-Escape $chat), $kind, '', (Csv-Escape $summary))
    $out.Add(@{ line = $line; time = $t; hm = $t.Substring(11, 5); from = $from; chat = $chat; summary = $summary; est = $fd.est; kind = $kind })
    }
    return @{ rows = $out; n = $n }
}
# ── 누적 저장 (append + dedupe) ──────────────────────────────────────────
# 덮어쓰면 상시 샘플러(Start-TeamsSampler)가 모아둔 이력이 1회 실행에 지워진다.
# 기존 행을 읽어 (time|from|chat|summary 앞 40자) 키로 중복을 거르고 신규만 보탠다. kind 는 키에 넣지 않는다 -
# 같은 메시지가 본인 판정만 달라져 두 번 들어가지 않게.
function Split-CsvLine([string]$ln2) {
    $f = New-Object System.Collections.Generic.List[string]
    $sb = New-Object System.Text.StringBuilder
    $q = $false
    for ($i = 0; $i -lt $ln2.Length; $i++) {
        $c = $ln2[$i]
        if ($q) {
            if ($c -eq '"') {
                if ($i + 1 -lt $ln2.Length -and $ln2[$i + 1] -eq '"') { [void]$sb.Append('"'); $i++ } else { $q = $false }
            } else { [void]$sb.Append($c) }
        } else {
            if ($c -eq '"') { $q = $true }
            elseif ($c -eq ',') { $f.Add($sb.ToString()); [void]$sb.Clear() }
            else { [void]$sb.Append($c) }
        }
    }
    $f.Add($sb.ToString())
    return ,$f
}
function Sum40([string]$s) { if ($s.Length -gt 40) { return $s.Substring(0, 40) }; return $s }
# 중복 키에 chat(대화방)을 넣는다 - 빼면 서로 다른 방에서 같은 사람이 같은 분에 남긴 같은 문구가
# 한 건으로 뭉쳐, 누적 파일을 다시 쓸 때 기존 행이 조용히 사라진다(감사 확정).
function Key-Of([string]$time, [string]$from, [string]$chat, [string]$summary) {
    return ($time + '|' + $from + '|' + $chat + '|' + (Sum40 $summary))
}
function Save-TwCsv([string]$dst, [string]$hdr, [object[]]$newRows, [scriptblock]$keyOfFields, [scriptblock]$keyOfRow) {
    # 누적 저장 → 새로 더한 행 수. $keyOfFields: 기존 행 칸 목록 → 키, $keyOfRow: 새 행 → 키
    $existing = New-Object System.Collections.Generic.List[string]
    $keys = New-Object 'System.Collections.Generic.HashSet[string]'
    if (Test-Path -LiteralPath $dst) {
        $old = @([System.IO.File]::ReadAllLines($dst, [System.Text.Encoding]::UTF8))
        for ($i = 1; $i -lt $old.Count; $i++) {
            if (-not $old[$i]) { continue }
            $f = Split-CsvLine $old[$i]
            $k = if ($f.Count -ge 6) { [string](& $keyOfFields $f) } else { $old[$i] }
            if (-not $keys.Add($k)) { continue }
            $existing.Add($old[$i])
        }
    }
    $added = 0
    foreach ($r in $newRows) {
        $k = [string](& $keyOfRow $r)
        if (-not $keys.Add($k)) { continue }
        $existing.Add([string]$r.line); $added++
    }
    if ($added -gt 0 -or -not (Test-Path -LiteralPath $dst)) {
        $outLines = New-Object System.Collections.Generic.List[string]
        $outLines.Add($hdr)
        foreach ($ln2 in ($existing | Sort-Object)) { $outLines.Add($ln2) }
        [System.IO.File]::WriteAllLines($dst, $outLines, [System.Text.Encoding]::UTF8)
    }
    return @{ added = $added; total = $existing.Count }
}
function Get-TwRanges($dates) {
    # 날짜(yyyy-MM-dd) 모음 → 이어진 날끼리 [{axis:'teams', from, to, st:'partial'}] — 창 읽기는 증인일 뿐 '읽음'이 아니다
    $out = New-Object System.Collections.Generic.List[object]
    $prev = $null; $cur = $null
    foreach ($s in @($dates | Sort-Object -Unique)) {
        $d = [datetime]::ParseExact([string]$s, 'yyyy-MM-dd', $null)
        if ($null -ne $prev -and ($d - $prev).TotalDays -eq 1) { $cur.to = $d.ToString('yyyy-MM-dd') }
        else { $cur = [ordered]@{ axis = 'teams'; from = $d.ToString('yyyy-MM-dd'); to = $d.ToString('yyyy-MM-dd'); st = 'partial' }; $out.Add($cur) }
        $prev = $d
    }
    return ,$out
}
function Get-TwEmptyCause($C) {
    # 읽은 것이 없을 때 사람에게 가장 쉬운 조치 순: 창이 안 읽힘(보이는데 빔) → 최소화 → 가려짐 → 화면 밖 → 숨김(트레이) → 개인용 창만
    if ($C.windows -eq 0) { if ($C.procs -eq 0) { return 'no_process' } else { return 'no_window' } }
    if ($C.targets -gt 0) { return 'empty_tree' }
    foreach ($k in 'iconic', 'cloaked', 'offscreen', 'hidden') { if ($C[$k] -gt 0) { return $k } }
    if ($C.personal_title -gt 0) { return 'excluded' }
    return 'other'
}

function Invoke-TeamsWindowRead {
    # 창 읽기 1회 → @{rc; reason; counts; ranges; summary}. 화면 줄은 -Quiet 가 아니면 그대로 찍는다(직접 실행).
    param([string]$Root = $script:TwRoot, [int]$MaxElements = 4000, [string]$RawFile = '', [switch]$KeepChatList,
          [object[]]$Windows = $null, [object]$Present = $null, [object]$Cfg = $null, [string]$OutDir = '',
          [datetime]$Today = [datetime]::MinValue, [int]$RetryDelayMs = 1500, [switch]$Quiet)
    $ErrorActionPreference = 'Stop'
    $script:twQuiet = [bool]$Quiet
    $C = [ordered]@{ procs = 0; windows = 0; targets = 0; excluded = 0; personal_title = 0; hidden = 0; iconic = 0; cloaked = 0
                     offscreen = 0; elements = 0; retry_reads = 0; retry_gain = 0; list_skipped = 0; lines = 0; time_lines = 0
                     rows_new = 0; sent = 0; undated = 0; undated_new = 0; total = 0; teams_present = $false; empty_cause = ''
                     win_enum = '' }
    $res = @{ rc = 0; reason = ''; counts = $C; ranges = @(); summary = '' }
    $cfgObj = $Cfg
    if ($null -eq $cfgObj) {
        try { $cfgObj = Get-Content -Raw -Encoding UTF8 (Join-Path $Root 'config\config.json') | ConvertFrom-Json } catch { $cfgObj = $null }
    }
    if ($RawFile -and -not (Test-Path -LiteralPath $RawFile)) {
        Write-TwLine "[teams-window] RawFile 없음: $RawFile"
        $res.rc = 1; $res.reason = 'R-ARGS'; return $res
    }
    $outDir = $OutDir
    if (-not $outDir) { $outDir = Join-Path $Root 'data\m365' }
    if ($RawFile) { $outDir = Join-Path $outDir 'replay' }   # 재생 모드는 실데이터(teams_window.csv)를 건드리지 않는다 - 별도 폴더
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
    $script:twMyNames = Get-TwSelfNames $cfgObj ([bool]$RawFile)
    $selfCfgN = 0   # config 에 적힌 본인 이름 수(안내문 판단용)
    try { $selfCfgN = @(@($cfgObj.teamsSelfNames) | Where-Object { $_ }).Count + $(if ($cfgObj.owner) { 1 } else { 0 }) } catch {}
    $rawDump = $false
    try { $rawDump = ($cfgObj.teamsWindowRawDump -eq $true) } catch {}

    $texts = New-Object System.Collections.Generic.List[string]
    $skippedTexts = New-Object System.Collections.Generic.List[string]   # 채팅목록으로 보고 뺀 줄 - 안전 밸브가 되돌릴 때 쓴다
    $nListSkipped = 0
    if ($RawFile) {
        # 원문 재생 모드 - 다른 PC 의 teams_window_raw.txt 를 받아 파서만 돌린다(원격 진단·회귀용)
        foreach ($ln in [System.IO.File]::ReadAllLines($RawFile, [System.Text.Encoding]::UTF8)) {
            if ($ln -and $ln.Length -ge 4) { $texts.Add($ln) }
        }
        Write-TwLine ("[teams-window] 원문 재생: {0}줄" -f $texts.Count)
    } else {
        $procs = @()
        if ($null -eq $Windows) { $procs = @(Get-TeamsProcs) }
        $pres = $Present
        if ($null -eq $pres) { $pres = Get-TeamsPresent $procs }
        $C.teams_present = [bool]$pres.present
        $wins = New-Object System.Collections.Generic.List[object]
        if ($null -ne $Windows) {
            foreach ($w in $Windows) { $wins.Add($w) }
            $C.procs = @($Windows | ForEach-Object { $_.pid } | Select-Object -Unique).Count
            $C.win_enum = 'injected'
        } else {
            $C.procs = $procs.Count
            if ($procs.Count -gt 0) {
                try {
                    foreach ($w in (Get-TwTopWindows ([int[]]@($procs | ForEach-Object { $_.Id })))) { $wins.Add($w) }
                    $C.win_enum = 'findwindow'
                } catch {
                    # 동적 형식을 못 만드는 PC(제한 언어 모드 등) - LM24 처럼 프로세스의 주 창 하나씩만 본다
                    $C.win_enum = 'mainwindow'
                    foreach ($p in $procs) {
                        if ($p.MainWindowHandle -ne 0) {
                            $wins.Add(@{ hwnd = $p.MainWindowHandle; pid = $p.Id; title = [string]$p.MainWindowTitle; visible = $true
                                         iconic = $false; cloaked = $false; on_screen = $true; tool = $false })
                        }
                    }
                }
            }
        }
        $targets = New-Object System.Collections.Generic.List[object]
        foreach ($w in $wins) {
            $title = [string]$w.title
            if (-not $title -or $w.tool) { continue }                     # 제목 없는 보조 창·도구 창은 대화 창이 아니다
            $C.windows++
            if ($title -match $script:twPersonalRx) { $C.personal_title++; $C.excluded++; continue }   # 개인용 Teams(free)
            $vis = ($null -eq $w.visible) -or [bool]$w.visible
            if (-not $vis) { $C.hidden++; $C.excluded++; continue }
            if ($w.iconic) { $C.iconic++; $C.excluded++; continue }
            if ($w.cloaked) { $C.cloaked++; $C.excluded++; continue }
            if (($null -ne $w.on_screen) -and -not [bool]$w.on_screen) { $C.offscreen++; $C.excluded++; continue }
            $targets.Add($w)
        }
        $C.targets = $targets.Count
        if ($targets.Count -eq 0) {
            $C.empty_cause = Get-TwEmptyCause $C
            if ($C.procs -eq 0) {
                Write-TwLine '[teams-window] Teams 프로세스가 없습니다 - Teams 앱(신·구 무관)을 열어 두고 다시 실행하세요.'
                $res.rc = 1; $res.reason = 'R-NOTEAMS'
            } else {
                $hint = @{ iconic = '최소화돼 있습니다'; cloaked = '다른 가상 데스크톱에 있습니다'; offscreen = '화면 밖에 있습니다'
                           hidden = '트레이에 숨어 있습니다(닫아도 백그라운드)'; excluded = '개인용 Teams(free) 창뿐입니다'; no_window = '창이 없습니다' }[$C.empty_cause]
                Write-TwLine ('[teams-window] Teams 는 실행 중이지만 읽을 창이 없습니다 - 창이 ' + $hint)
                Write-TwLine '               Teams 창을 화면에 열어 두고(읽을 대화를 스크롤) 다시 실행하세요.'
                $res.rc = 3; $res.reason = 'R-UIAEMPTY'
            }
            $res.summary = 'empty_cause=' + $C.empty_cause
            return $res
        }
        foreach ($w in $targets) {
            try {
                $live = ($null -eq $Windows)
                if ($live) { Initialize-TwUia; $rd = Read-TeamsTexts ([IntPtr]$w.hwnd) $MaxElements ([bool]$KeepChatList) }
                else { $rd = Read-TwInjected $w }
                if ($rd.count -lt 20) {
                    # 첫 판독 요소가 적다 - 접근성 트리가 늦게 채워지는 창(렌더 지연)일 수 있어 잠깐 쉬고 한 번 더(더 많이 읽힌 쪽)
                    if ($RetryDelayMs -gt 0) { Start-Sleep -Milliseconds $RetryDelayMs }
                    $C.retry_reads++
                    $rd2 = $null
                    if ($live) { $rd2 = Read-TeamsTexts ([IntPtr]$w.hwnd) $MaxElements ([bool]$KeepChatList) }
                    elseif ($w.ContainsKey('retry')) { $rd2 = Read-TwInjected @{ title = $w.title; texts = $w.retry } }
                    if ($null -ne $rd2 -and $rd2.count -gt $rd.count) { $rd = $rd2; $C.retry_gain++ }
                }
                $C.elements += [int]$rd.count
                Write-TwLine ("[teams-window] '{0}' 창에서 요소 {1}개" -f $rd.name, $rd.count)
                if ($rd.column) {
                    Write-TwLine ("               채팅 목록 열(항목 {0}개, x {1:0}~{2:0}) 안의 {3}줄은 미리보기로 보고 제외 - 메시지 영역만 파싱 (-KeepChatList 로 해제)" -f $rd.column.n, $rd.column.left, $rd.column.right, $rd.skipped)
                    $nListSkipped += [int]$rd.skipped
                }
                foreach ($nm in $rd.texts) { $texts.Add($nm) }
                foreach ($nm in $rd.skippedTexts) { $skippedTexts.Add($nm) }
            } catch {
                Write-TwLine ("[teams-window] 창 읽기 실패: {0}" -f $_.Exception.Message)
            }
        }
    }
    $C.list_skipped = $nListSkipped
    if ($texts.Count -eq 0) {
        Write-TwLine '[teams-window] 텍스트를 읽지 못했습니다 - 팀즈 창을 앞으로 가져온 뒤 재시도하세요.'
        Write-TwLine '               (새 Teams 는 WebView2 안에 그려집니다 - 창이 화면에 보이는 상태여야 UIA 가 읽습니다)'
        if (-not $RawFile) { $C.empty_cause = 'empty_tree' }
        $res.rc = 3; $res.reason = 'R-UIAEMPTY'; $res.summary = 'empty_cause=empty_tree'
        return $res
    }
    $uniq = @($texts | Select-Object -Unique)
    $C.lines = $uniq.Count
    if ($rawDump -and -not $RawFile) {
        # 진단용 원문(config.teamsWindowRawDump=true 일 때만 — 기본 끔). **제외하기 전 화면 그대로** 남긴다: 다른 PC 에서
        # 이 파일을 -RawFile 로 재생해 '채팅목록 제외' 사고를 재현할 수 있어야 한다. 제외된 줄은 따로 적는다.
        $rawAll = New-Object System.Collections.Generic.List[string]
        foreach ($x in $uniq) { $rawAll.Add($x) }
        foreach ($x in $skippedTexts) { if (-not $rawAll.Contains($x)) { $rawAll.Add($x) } }
        [System.IO.File]::WriteAllLines((Join-Path $outDir 'teams_window_raw.txt'), $rawAll, [System.Text.Encoding]::UTF8)
        if ($skippedTexts.Count -gt 0) {
            [System.IO.File]::WriteAllLines((Join-Path $outDir 'teams_window_skipped.txt'),
                [string[]]@($skippedTexts | Select-Object -Unique), [System.Text.Encoding]::UTF8)
        }
    }

    $today = if ($Today -ne [datetime]::MinValue) { $Today } else { Get-Date }
    if ($RawFile -and $Today -eq [datetime]::MinValue) { try { $today = (Get-Item -LiteralPath $RawFile).LastWriteTime } catch {} }   # 재생: 원문이 찍힌 날을 '오늘'로
    Initialize-TwParse $cfgObj
    $pr = Parse-TwLines $uniq $script:twReTime $today
    $nTime = [int]$pr.n
    $usedGeneric = $false
    # 안전 밸브 — 채팅목록으로 보고 뺐는데 남은 줄에 시각이 하나도 없으면, 그 판정이 틀린 것이다
    # (메시지 열을 목록으로 오인한 경우). 뺀 줄을 되돌려 다시 읽는다. 0건으로 끝나는 것보다 낫다.
    $colUndone = $false
    if ($nTime -eq 0 -and $skippedTexts.Count -gt 0) {
        foreach ($nm in $skippedTexts) { if ($uniq -notcontains $nm) { $texts.Add($nm) } }
        $uniq = @($texts | Select-Object -Unique)
        $pr = Parse-TwLines $uniq $script:twReTime $today
        $nTime = [int]$pr.n
        $colUndone = $true
        Write-TwLine ('[teams-window] 채팅 목록으로 보고 뺀 ' + $skippedTexts.Count + '줄을 되돌렸습니다 - 그 판정이 틀렸던 것 같습니다(시각 0줄)')
    }
    if ($nTime -eq 0 -and -not $script:twCfgRe -and $uniq.Count -gt 0) {
        # 지역 설정 기반 형식으로 한 줄도 못 잡았다 - Teams 표시 언어가 Windows 와 다를 수 있다. 일반 형식으로 재시도.
        Write-TwLine '[teams-window] 지역 설정 기반 시각 형식으로 0줄 - 일반 형식(숫자:숫자 / 숫자.숫자)으로 재시도'
        $pr = Parse-TwLines $uniq $script:twReTimeGeneric $today
        $nTime = [int]$pr.n
        $usedGeneric = ($nTime -gt 0)
    }
    $C.time_lines = $nTime
    # 날짜를 짚은 줄만 teams_window.csv 에 — 표기가 없는 줄은 수집일로 추정하지 않고 undated 파일로만(C-19·W1-15)
    $dated = New-Object System.Collections.Generic.List[object]
    $undated = New-Object System.Collections.Generic.List[object]
    foreach ($r in $pr.rows) { if ($r.est) { $undated.Add($r) } else { $dated.Add($r) } }
    $C.undated = $undated.Count
    $dst = Join-Path $outDir 'teams_window.csv'
    $sv = Save-TwCsv $dst 'time,from,chat,kind,replied_time,summary' $dated.ToArray() `
        { param($f) $sm = if ($f.Count -eq 6) { $f[5] } else { ($f.GetRange(5, $f.Count - 5) -join ',') }; Key-Of $f[0] $f[1] $f[2] $sm } `
        { param($r) Key-Of $r.time $r.from $r.chat $r.summary }
    $C.rows_new = [int]$sv.added; $C.total = [int]$sv.total
    $nSent = 0
    foreach ($r in $dated) { if ($r.kind -eq 'sent') { $nSent++ } }
    $C.sent = $nSent
    if ($undated.Count -gt 0) {
        # 날짜 미상 줄: seen(처음 본 날),hm,from,chat,kind,summary — 같은 (시각·보낸이·방·요지)는 한 번만(매 주기 다시 보여도 쌓이지 않게)
        $ud = New-Object System.Collections.Generic.List[object]
        $seen = $today.ToString('yyyy-MM-dd')
        foreach ($r in $undated) {
            $ud.Add(@{ hm = $r.hm; from = $r.from; chat = $r.chat; summary = $r.summary
                       line = ('{0},{1},{2},{3},{4},{5}' -f $seen, $r.hm, (Csv-Escape $r.from), (Csv-Escape $r.chat), $r.kind, (Csv-Escape $r.summary)) })
        }
        $su = Save-TwCsv (Join-Path $outDir 'undated_teams_window.csv') 'seen,hm,from,chat,kind,summary' $ud.ToArray() `
            { param($f) $sm = if ($f.Count -eq 6) { $f[5] } else { ($f.GetRange(5, $f.Count - 5) -join ',') }; Key-Of $f[1] $f[2] $f[3] $sm } `
            { param($r) Key-Of $r.hm $r.from $r.chat $r.summary }
        $C.undated_new = [int]$su.added
    }
    $res.ranges = (Get-TwRanges @($dated | ForEach-Object { $_.time.Substring(0, 10) })).ToArray()
    $res.summary = ("원문 {0}줄 (시각 패턴 {1}줄{6}) -> 신규 {2}건 (본인 발신 {3}건 · 날짜 미상 {4}줄은 따로) / 누적 {5}건" -f $uniq.Count, $nTime, $C.rows_new, $nSent, $undated.Count, $C.total, $(if ($colUndone) { ', 채팅목록 판정 되돌림' } elseif ($nListSkipped) { ', 채팅목록으로 ' + $nListSkipped + '줄 제외' } else { '' }))
    Write-TwLine ('[teams-window] ' + $res.summary)
    if ($usedGeneric) { Write-TwLine '               (일반 형식으로 잡았습니다 - 오전/오후 구분이 없으면 12시간 표기가 오전으로 기록될 수 있음)' }
    if ($nTime -eq 0 -and $uniq.Count -gt 0) {
        if ($nListSkipped -gt 0) {
            Write-TwLine ('               채팅 목록 열로 보고 ' + $nListSkipped + '줄을 제외했습니다 - 잘못 판정했을 수 있습니다.')
            Write-TwLine '               확인: powershell -File collect\Get-TeamsWindow.ps1 -KeepChatList  (제외 없이 다시 읽습니다)'
        }
        Write-TwLine '               시각 패턴이 한 줄도 없습니다 - 팀즈 표기 형식이 이 PC 의 지역 설정과 다를 수 있습니다.'
        Write-TwLine ('               반영된 지역 설정: 오전/오후 "' + $script:twAmD + '"/"' + $script:twPmD + '", 시각 형식 "' + $script:twCi.DateTimeFormat.ShortTimePattern + '" (' + $script:twCi.Name + ')')
        Write-TwLine '               조치(이 PC 안에서): Windows 지역 설정(제어판 > 국가 또는 지역 > 형식)을 Teams 표시 언어와 맞추거나,'
        Write-TwLine '               config.teamsTimeRegex 에 형식을 지정하세요(docs\설정가이드 §7). 원문 파일을 밖으로 보낼 필요는 없습니다.'
    }
    if ($nTime -gt 0 -and $nSent -eq 0 -and $C.rows_new -gt 0 -and $selfCfgN -eq 0) {
        Write-TwLine '               (본인 발신 0건 - 팀즈에 보이는 내 표시명이 계정명과 다르면 config.teamsSelfNames 에 적어 두세요)'
    }
    if ($RawFile) { Write-TwLine ('               (재생 모드 - 결과는 ' + $outDir + ' 에만 기록, 실데이터는 건드리지 않음)') }
    Write-TwLine '               (열려 있는 대화의 화면 렌더분만 - 상시 수집은 Start-TeamsSampler.ps1 을 켜두세요)'
    if ($undated.Count -gt 0) { Write-TwLine ('               (날짜 표기가 없는 ' + $undated.Count + '줄은 수집일로 추정하지 않고 undated_teams_window.csv 에만 적음)') }
    # 종료코드로 '무엇이 됐는지' 를 알린다 - 0: 새 줄을 얻었다 / 4: 읽었지만 새 줄 0건(렌더된 것이 없거나 이미 있음).
    if ($C.rows_new -gt 0) { $res.rc = 0 } else { $res.rc = 4; if ($nTime -eq 0) { $res.reason = 'R-NOTIME' } }
    return $res
}

function Format-TwStatus($res) {
    # 마지막 줄(LM28 P3) — 'LMSTATUS ' + JSON 한 줄
    $o = [ordered]@{ v = 1; src = 'teams_window'; rc = [int]$res.rc; reason = [string]$res.reason; counts = $res.counts
                     ranges = [object[]]@($res.ranges) }
    return ('LMSTATUS ' + (ConvertTo-Json -InputObject $o -Compress -Depth 6))
}
function Write-TwStatus($res) { Write-Host (Format-TwStatus $res) }

# 직접 실행 가드 — 점 소싱(. Get-TeamsWindow.ps1)이면 위 함수만 정의하고 끝난다(샘플러·시험)
if ($MyInvocation.InvocationName -ne '.') {
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
    $r = $null
    try {
        $r = @(Invoke-TeamsWindowRead -MaxElements $MaxElements -RawFile $RawFile -KeepChatList:$KeepChatList)[-1]
    } catch {
        Write-Host ('[teams-window] 실패: ' + $_.Exception.Message)
        $r = @{ rc = 3; reason = 'R-UIAERROR'; counts = @{}; ranges = @() }
    }
    Write-TwStatus $r
    exit ([int]$r.rc)
}
