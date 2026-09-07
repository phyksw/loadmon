# Get-TeamsWindow.ps1
# 켜져 있는 Teams 앱 창에서 '지금 보이는 채팅'을 UI 자동화(UIA)로 읽는다.
# Graph 권한도, 관리자도, Copilot도 필요 없다 — 단 열려 있는 대화의 화면에 렌더된 부분만 읽힌다.
# 읽기 전용이며 네트워크를 쓰지 않는다. 출력: ..\data\m365\teams_window.csv (+ 원문 raw.txt)
#
# 사용: 팀즈에서 보고 싶은 대화를 열어 스크롤해 두고  ->  powershell -File collect\Get-TeamsWindow.ps1
#  · kind: 본인이 보낸 줄은 sent, 그 외 msg. 본인 판정은 config.teamsSelfNames + owner + 윈도우 계정 +
#    로그온 표시명(AD) + 나/You/본인 (대소문자 무시). 이름을 못 잡으면 msg 로 남는다(수동 흔적).
#  · 날짜: 8/15 · 8월 15일 · 2026. 8. 15. · Aug 15 · 요일(월요일·Mon·月曜日 → 가장 최근 그 요일) · 오늘/어제.
#    표기가 없는 줄은 수집일로 '추정'하고, 같은 (발신자·시각·요지)가 7일 안에 이미 있으면 다시 넣지 않는다
#    (채팅 목록 미리보기가 매일 새 신호가 되던 문제).
#  · 왼쪽 채팅 목록(좁은 열의 ListItem)은 메시지 영역이 보일 때 파싱에서 제외한다(-KeepChatList 로 해제).
param([int]$MaxElements = 4000, [string]$RawFile = '', [switch]$KeepChatList)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = Join-Path $root 'data\m365'
if ($RawFile) { $outDir = Join-Path $outDir 'replay' }   # 재생 모드는 실데이터(teams_window.csv/raw)를 건드리지 않는다 - 별도 폴더
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

# ── config.json 은 한 번만 읽는다 (teamsTimeRegex · teamsSelfNames · owner) ──────────────────
$cfgObj = $null
try { $cfgObj = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json } catch {}

function Get-SelfNames([object]$cfg, [bool]$replay) {
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
$myNames = Get-SelfNames $cfgObj ([bool]$RawFile)
$selfCfgN = 0   # config 에 적힌 본인 이름 수(안내문 판단용)
try { $selfCfgN = @(@($cfgObj.teamsSelfNames) | Where-Object { $_ }).Count + $(if ($cfgObj.owner) { 1 } else { 0 }) } catch {}
function Is-Self([string]$from) {
    if (-not $from) { return $false }
    $f = $from.Trim().ToLower()
    foreach ($c in @($f, ($f -replace '\s+', ''), ($f -replace '\s*(님|씨)$', ''), (($f -replace '\s*(님|씨)$', '') -replace '\s+', ''))) {
        if ($c -and $myNames.Contains($c)) { return $true }
    }
    return $false
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

$texts = New-Object System.Collections.Generic.List[string]
$skippedTexts = New-Object System.Collections.Generic.List[string]   # 채팅목록으로 보고 뺀 줄 - 안전 밸브가 되돌릴 때 쓴다
$nListSkipped = 0
if ($RawFile) {
    # 원문 재생 모드 - 다른 PC 의 teams_window_raw.txt 를 받아 파서만 돌린다(원격 진단·회귀용)
    if (-not (Test-Path -LiteralPath $RawFile)) { Write-Host "[teams-window] RawFile 없음: $RawFile"; exit 1 }
    foreach ($ln in [System.IO.File]::ReadAllLines($RawFile, [System.Text.Encoding]::UTF8)) {
        if ($ln -and $ln.Length -ge 4) { $texts.Add($ln) }
    }
    Write-Host ("[teams-window] 원문 재생: {0}줄" -f $texts.Count)
    $procs = @()
} else {
$procs = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -match '^(ms-teams|Teams|msteams)$' })
# 신·구 Teams 모두 커버(새 Teams=ms-teams.exe, 클래식=Teams.exe). 실행은 됐지만 트레이에
# 최소화된 경우(MainWindowHandle=0)를 '미실행'과 구분해 안내한다 - 'PC마다 팀즈 누락' 진단용.
$vis = @($procs | Where-Object { $_.MainWindowHandle -ne 0 })
if (-not $vis) {
    if ($procs) {
        Write-Host '[teams-window] Teams 는 실행 중이지만 창이 트레이에 최소화되어 읽을 수 없습니다.'
        Write-Host '               Teams 창을 화면에 열어 두고(읽을 대화를 스크롤) 다시 실행하세요.'
    } else {
        Write-Host '[teams-window] Teams 프로세스가 없습니다 - Teams 앱(신·구 무관)을 열어 두고 다시 실행하세요.'
    }
    exit 1
}
$procs = $vis

foreach ($p in $procs) {
    try {
        $rd = Read-TeamsTexts $p.MainWindowHandle $MaxElements ([bool]$KeepChatList)
        Write-Host ("[teams-window] '{0}' 창에서 요소 {1}개" -f $rd.name, $rd.count)
        if ($rd.column) {
            Write-Host ("               채팅 목록 열(항목 {0}개, x {1:0}~{2:0}) 안의 {3}줄은 미리보기로 보고 제외 - 메시지 영역만 파싱 (-KeepChatList 로 해제)" -f $rd.column.n, $rd.column.left, $rd.column.right, $rd.skipped)
            $nListSkipped += [int]$rd.skipped
        }
        foreach ($nm in $rd.texts) { $texts.Add($nm) }
        foreach ($nm in $rd.skippedTexts) { $skippedTexts.Add($nm) }
    } catch {
        Write-Host ("[teams-window] 창 읽기 실패: {0}" -f $_.Exception.Message)
    }
}
}   # RawFile 분기 끝
if ($texts.Count -eq 0) {
    Write-Host '[teams-window] 텍스트를 읽지 못했습니다 - 팀즈 창을 앞으로 가져온 뒤 재시도하세요.'
    Write-Host '               (새 Teams 는 WebView2 안에 그려집니다 - 창이 화면에 보이는 상태여야 UIA 가 읽습니다)'
    exit 1
}
$uniq = @($texts | Select-Object -Unique)
[System.IO.File]::WriteAllLines((Join-Path $outDir 'teams_window_raw.txt'), $uniq, [System.Text.Encoding]::UTF8)

# ── 메시지 파싱 (best-effort): 이름 + 시각 패턴이 있는 줄을 메시지로 취급 ──
function Csv-Escape([string]$s) {
    $s = $s -replace "[`r`n]+", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}
$today = Get-Date
if ($RawFile) { try { $today = (Get-Item -LiteralPath $RawFile).LastWriteTime } catch {} }   # 재생: 원문이 찍힌 날을 '오늘'로
$todayD = $today.Date
$nTime = 0
# ── 시각 정규식은 이 PC 의 Windows 지역 설정에서 자동 구성한다 ───────────────────────────
# 회사 PC 의 원문(raw)은 보안상 밖으로 보낼 수 없다 - 형식을 '그 PC 안에서' 알아내야 한다.
#  · 오전/오후 표기: 고정 목록(한/영/일/중/독) + 현재 문화권의 AMDesignator/PMDesignator
#  · 구분자: 문화권 단시간 형식에 '.' 이 있으면 '14.10' 도 받는다(핀란드 등)
#  · 그래도 0줄이면 일반 형식(숫자:숫자 / 숫자.숫자)으로 한 번 더 시도한다
#  · config.teamsTimeRegex 가 있으면 최우선(그룹: 1=앞 표기, 2=시, 3=분, 4=뒤 표기 - 빈 그룹 허용)
$ci = Get-Culture
$amD = [string]$ci.DateTimeFormat.AMDesignator; $pmD = [string]$ci.DateTimeFormat.PMDesignator
$pmSet = @('오후', 'PM', 'pm', 'p.m.', 'P.M.', '午後', '下午', 'nachm.'); if ($pmD) { $pmSet += $pmD }
$amSet = @('오전', 'AM', 'am', 'a.m.', 'A.M.', '午前', '上午', 'vorm.'); if ($amD) { $amSet += $amD }
$desig = (($amSet + $pmSet) | Where-Object { $_ } | Select-Object -Unique | ForEach-Object { [regex]::Escape($_) }) -join '|'
$sepRe = ':'
if ($ci.DateTimeFormat.ShortTimePattern -match '\.') { $sepRe = '[:.]' }
# 숫자 앞뒤 경계는 \b 가 아니라 '숫자 아님'으로 본다 - '午後2:10' 처럼 CJK 글자 바로 뒤에 숫자가 오면 \b 가 성립하지 않는다(시험 실측)
$reTime = '(?:(' + $desig + ')\s*)?(?<!\d)(\d{1,2})' + $sepRe + '(\d{2})(?!\d)(?:\s*(' + $desig + '))?'
$reTimeGeneric = '()?(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)()?'   # 0줄일 때의 마지막 시도 - 구분자·표기 무관(그룹 수 동일)
$cfgRe = ''
try { $cfgRe = [string]$cfgObj.teamsTimeRegex } catch {}
if ($cfgRe) { $reTime = $cfgRe; Write-Host '[teams-window] config.teamsTimeRegex 사용' }
$dayFirst = [bool]($ci.DateTimeFormat.ShortDatePattern -match '^d')      # dd.MM / dd/MM 문화권이면 '15.08' 은 일.월
# 문화권 월 이름(독일어 Mrz/Okt, 프랑스어 août 등) - 영문은 아래 $reMon 이 엄격하게 처리하므로 영문 외만
$monC = @{}
if ($ci.TwoLetterISOLanguageName -notin @('en', 'ko')) {
    $nms = @($ci.DateTimeFormat.AbbreviatedMonthNames) + @($ci.DateTimeFormat.MonthNames)
    for ($i = 0; $i -lt $nms.Count; $i++) {
        $nm = [string]$nms[$i]
        if ($nm -and $nm.Length -ge 2 -and $nm -notmatch '^\d') { $monC[$nm.ToLower()] = ($i % 12) + 1 }
    }
}
$reMonC = ''
if ($monC.Count) { $reMonC = '(' + (($monC.Keys | Sort-Object { -$_.Length } | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')' }
# 영문 월 이름: 전체 철자 화이트리스트 + 대소문자 구분(-cmatch) - 'Mark'·'Mary'·'separate' 를 3월/9월로 오인하지 않게(검증 확정)
$reMon = '(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
$mon = @{jan=1;feb=2;mar=3;apr=4;may=5;jun=6;jul=7;aug=8;sep=9;oct=10;nov=11;dec=12}
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
$reDow = '(?<![\p{L}])(' + (($dow.Keys | Sort-Object { -$_.Length } | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')(?:에|에는)?(?![\p{L}])[\s,:·-]*(?:at\s+)?$'
$reToday = '(?<![\p{L}])(오늘|today|今日|今天)(?:에|에는)?(?![\p{L}])'
$reYesterday = '(?<![\p{L}])(어제|yesterday|昨日|昨天)(?:에|에는)?(?![\p{L}])'
$rxOpt = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
function Day-Of([int]$m, [int]$dd, [datetime]$ref) {
    # 연도 없는 월/일 → 가장 최근의 그 날짜(오늘 포함). 날짜 단위로 비교한다 - 시각까지 비교하면
    # 오늘 날짜 줄이 작년으로 밀리고(검증 확정), 2/30 같은 잘못된 날짜는 무시한다.
    try { $x = [datetime]::new($ref.Year, $m, $dd) } catch { return $null }
    if ($x -gt $ref.Date) { try { $x = [datetime]::new($ref.Year - 1, $m, $dd) } catch { return $null } }
    return $x
}
function Find-HeaderDate([string]$pre, [datetime]$ref) {
    # 시각 앞(헤더) 문자열에서 날짜 토큰 하나를 찾는다 → @{date; idx; len; est}. 본문(시각 뒤)의 '8/15 까지' 는 보지 않는다.
    # est=true 면 날짜 표기가 없어 수집일로 추정한 것
    $r = @{ date = $ref.Date; idx = -1; len = 0; est = $true }
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
        if ($dayFirst) { $mo = $b; $dd = $a }
        if ($mo -gt 12 -and $dd -le 12) { $t0 = $mo; $mo = $dd; $dd = $t0 }
        if ($mo -ge 1 -and $mo -le 12 -and $dd -ge 1 -and $dd -le 31) {
            $x = Day-Of $mo $dd $ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
    }
    if ($reMonC) {
        $m = [regex]::Match($pre, ('\b(\d{1,2})\.?\s*' + $reMonC + '\b'), $rxOpt)
        if ($m.Success) {
            # 15. Aug / 15 août (이 PC 문화권의 월 이름, 일-월)
            $x = Day-Of $monC[$m.Groups[2].Value.ToLower()] ([int]$m.Groups[1].Value) $ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
        $m = [regex]::Match($pre, ('\b' + $reMonC + '\.?\s+(\d{1,2})\b'), $rxOpt)
        if ($m.Success) {
            $x = Day-Of $monC[$m.Groups[1].Value.ToLower()] ([int]$m.Groups[2].Value) $ref
            if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
        }
    }
    $m = [regex]::Match($pre, ('\b(\d{1,2})\s+' + $reMon + '\b'))
    if ($m.Success) {
        # '15 Aug' (일 월) - 월-일 분기보다 먼저 본다(뒤에 두면 'Aug 3' 류 오인)
        $x = Day-Of $mon[$m.Groups[2].Value.Substring(0, 3).ToLower()] ([int]$m.Groups[1].Value) $ref
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = [regex]::Match($pre, ('\b' + $reMon + '\.?\s+(\d{1,2})\b'))
    if ($m.Success) {
        # 'Aug 15' / 'August 15' (월 일)
        $x = Day-Of $mon[$m.Groups[1].Value.Substring(0, 3).ToLower()] ([int]$m.Groups[2].Value) $ref
        if ($x) { $r.date = $x; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    }
    $m = [regex]::Match($pre, $reYesterday, $rxOpt)
    if ($m.Success) { $r.date = $ref.Date.AddDays(-1); $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    $m = [regex]::Match($pre, $reToday, $rxOpt)
    if ($m.Success) { $r.date = $ref.Date; $r.idx = $m.Index; $r.len = $m.Length; $r.est = $false; return $r }
    $m = [regex]::Match($pre, $reDow, $rxOpt)
    if ($m.Success) {
        # 요일 → 가장 최근 그 요일. Teams 는 오늘 것은 시각만, 어제는 '어제', 그 전 6일은 요일로 보여 주므로
        # 오늘과 같은 요일은 지난주(7일 전)로 본다
        $key = $m.Groups[1].Value.ToLower()
        if ($dow.ContainsKey($key)) {
            $delta = ([int]$ref.DayOfWeek - [int]$dow[$key] + 7) % 7
            if ($delta -eq 0) { $delta = 7 }
            $r.date = $ref.Date.AddDays(-$delta); $r.idx = $m.Index; $r.len = $m.Groups[1].Length; $r.est = $false; return $r
        }
    }
    return $r
}
function Parse-Lines([string]$re) {
    # 한 번의 파싱 패스 - 지역 설정 정규식으로 0줄이면 일반 형식으로 다시 부른다.
    # 반환 rows: @{line; time; from; summary; est} 목록, n: 시각 패턴 줄 수
    $out = New-Object System.Collections.Generic.List[object]
    $n = 0; $chat = ''
    foreach ($ln in $uniq) {
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
        if ($g) { if ($pmSet -contains $g) { $ap = 'PM' } elseif ($amSet -contains $g) { $ap = 'AM' } }
    }
    if ($ap -eq 'PM' -and $hh -lt 12) { $hh += 12 }
    if ($ap -eq 'AM' -and $hh -eq 12) { $hh = 0 }
    if ($hh -gt 23 -or [int]$mm -gt 59) { continue }
    # 헤더(시각 앞) / 본문(시각 뒤) 로 나눈다 - 날짜·발신자는 헤더에서만 찾고, 본문의 '8/15 까지' 는 날짜로 보지 않는다
    $pre = $ln.Substring(0, $tm.Index)
    $post = $ln.Substring($tm.Index + $tm.Length)
    $fd = Find-HeaderDate $pre $today
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
    $out.Add(@{ line = $line; time = $t; from = $from; chat = $chat; summary = $summary; est = $fd.est; kind = $kind })
    }
    return @{ rows = $out; n = $n }
}
$res = Parse-Lines $reTime
$nTime = [int]$res.n
$usedGeneric = $false
# 안전 밸브 — 채팅목록으로 보고 뺐는데 남은 줄에 시각이 하나도 없으면, 그 판정이 틀린 것이다
# (메시지 열을 목록으로 오인한 경우). 뺀 줄을 되돌려 다시 읽는다. 0건으로 끝나는 것보다 낫다.
$colUndone = $false
if ($nTime -eq 0 -and $skippedTexts.Count -gt 0) {
    foreach ($nm in $skippedTexts) { if (-not $uniq.Contains($nm)) { $texts.Add($nm) } }
    $uniq = @($texts | Select-Object -Unique)
    [System.IO.File]::WriteAllLines((Join-Path $outDir 'teams_window_raw.txt'), $uniq, [System.Text.Encoding]::UTF8)
    $res = Parse-Lines $reTime
    $nTime = [int]$res.n
    $colUndone = $true
    Write-Host ('[teams-window] 채팅 목록으로 보고 뺀 ' + $skippedTexts.Count + '줄을 되돌렸습니다 - 그 판정이 틀렸던 것 같습니다(시각 0줄)')
}
if ($nTime -eq 0 -and -not $cfgRe -and $uniq.Count -gt 0) {
    # 지역 설정 기반 형식으로 한 줄도 못 잡았다 - Teams 표시 언어가 Windows 와 다를 수 있다. 일반 형식으로 재시도.
    Write-Host '[teams-window] 지역 설정 기반 시각 형식으로 0줄 - 일반 형식(숫자:숫자 / 숫자.숫자)으로 재시도'
    $res = Parse-Lines $reTimeGeneric
    $nTime = [int]$res.n
    $usedGeneric = ($nTime -gt 0)
}
# ── 누적 저장 (append + dedupe) ──────────────────────────────────────────
# 덮어쓰면 상시 샘플러(Start-TeamsSampler)가 모아둔 이력이 1회 실행에 지워진다.
# 기존 행을 읽어 (time|from|summary 앞 40자) 키로 중복을 거르고 신규만 보탠다. chat·kind 는 키에 넣지 않는다 -
# 같은 메시지가 대화방 제목이나 본인 판정만 달라져 두 번 들어가지 않게.
# 날짜를 추정한 행(표기 없음)은 (from|HH:mm|summary40) 이 7일 안에 이미 있으면 같은 메시지의 재노출로 보고 넣지 않는다.
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
function Key2-Of([string]$time, [string]$from, [string]$chat, [string]$summary) {
    $hm = if ($time.Length -ge 16) { $time.Substring(11, 5) } else { '' }
    return ($from + '|' + $hm + '|' + $chat + '|' + (Sum40 $summary))
}
$dst = Join-Path $outDir 'teams_window.csv'
$existing = New-Object System.Collections.Generic.List[string]
$keys = New-Object 'System.Collections.Generic.HashSet[string]'
$k2dates = @{}
function Note-Row([string]$k, [string]$k2, [string]$time) {
    [void]$keys.Add($k)
    if (-not $k2) { return }
    $dd = $null
    try { $dd = [datetime]::ParseExact($time.Substring(0, 10), 'yyyy-MM-dd', $null) } catch { return }
    if (-not $k2dates.ContainsKey($k2)) { $k2dates[$k2] = New-Object System.Collections.Generic.List[datetime] }
    $k2dates[$k2].Add($dd)
}
if (Test-Path $dst) {
    $old = @([System.IO.File]::ReadAllLines($dst, [System.Text.Encoding]::UTF8))
    for ($i = 1; $i -lt $old.Count; $i++) {
        if (-not $old[$i]) { continue }
        $f = Split-CsvLine $old[$i]
        if ($f.Count -ge 6) {
            $sm = if ($f.Count -eq 6) { $f[5] } else { ($f.GetRange(5, $f.Count - 5) -join ',') }
            $k = Key-Of $f[0] $f[1] $f[2] $sm
            if ($keys.Contains($k)) { continue }
            Note-Row $k (Key2-Of $f[0] $f[1] $f[2] $sm) $f[0]
        } else {
            $k = $old[$i]
            if ($keys.Contains($k)) { continue }
            [void]$keys.Add($k)
        }
        $existing.Add($old[$i])
    }
}
$added = 0; $nSent = 0; $nEst = 0; $nEstDup = 0
foreach ($r in $res.rows) {
    $k = Key-Of $r.time $r.from $r.chat $r.summary
    if ($keys.Contains($k)) { continue }
    $k2 = Key2-Of $r.time $r.from $r.chat $r.summary
    if ($r.est) {
        $nEst++
        $dd = [datetime]::ParseExact($r.time.Substring(0, 10), 'yyyy-MM-dd', $null)
        $dup = $false
        if ($k2dates.ContainsKey($k2)) {
            foreach ($x in $k2dates[$k2]) { $gap = ($dd - $x).TotalDays; if ($gap -gt 0 -and $gap -le 7) { $dup = $true; break } }
        }
        if ($dup) { $nEstDup++; [void]$keys.Add($k); continue }
    }
    Note-Row $k $k2 $r.time
    $existing.Add($r.line); $added++
    if ($r.kind -eq 'sent') { $nSent++ }
}
$outLines = New-Object System.Collections.Generic.List[string]
$outLines.Add('time,from,chat,kind,replied_time,summary')
foreach ($ln2 in ($existing | Sort-Object)) { $outLines.Add($ln2) }
[System.IO.File]::WriteAllLines($dst, $outLines, [System.Text.Encoding]::UTF8)
Write-Host ("[teams-window] 원문 {0}줄 (시각 패턴 {1}줄{7}) -> 신규 {2}건 (본인 발신 {3}건 · 날짜 추정 {4}건 · 추정 중복 제외 {5}건) / 누적 {6}건" -f $uniq.Count, $nTime, $added, $nSent, $nEst, $nEstDup, ($outLines.Count - 1), $(if ($colUndone) { ', 채팅목록 판정 되돌림' } elseif ($nListSkipped) { ', 채팅목록으로 ' + $nListSkipped + '줄 제외' } else { '' }))
if ($usedGeneric) { Write-Host '               (일반 형식으로 잡았습니다 - 오전/오후 구분이 없으면 12시간 표기가 오전으로 기록될 수 있음)' }
if ($nTime -eq 0 -and $uniq.Count -gt 0) {
    if ($nListSkipped -gt 0) {
        Write-Host ('               채팅 목록 열로 보고 ' + $nListSkipped + '줄을 제외했습니다 - 잘못 판정했을 수 있습니다.')
        Write-Host '               확인: powershell -File collect\Get-TeamsWindow.ps1 -KeepChatList  (제외 없이 다시 읽습니다)'
    }
    Write-Host '               시각 패턴이 한 줄도 없습니다 - 팀즈 표기 형식이 이 PC 의 지역 설정과 다를 수 있습니다.'
    Write-Host ('               반영된 지역 설정: 오전/오후 "' + $amD + '"/"' + $pmD + '", 시각 형식 "' + $ci.DateTimeFormat.ShortTimePattern + '" (' + $ci.Name + ')')
    Write-Host '               조치(이 PC 안에서): Windows 지역 설정(제어판 > 국가 또는 지역 > 형식)을 Teams 표시 언어와 맞추거나,'
    Write-Host '               config.teamsTimeRegex 에 형식을 지정하세요(docs\설정가이드 §7). 원문 파일을 밖으로 보낼 필요는 없습니다.'
}
if ($nTime -gt 0 -and $nSent -eq 0 -and $added -gt 0 -and $selfCfgN -eq 0) {
    Write-Host '               (본인 발신 0건 - 팀즈에 보이는 내 표시명이 계정명과 다르면 config.teamsSelfNames 에 적어 두세요)'
}
if ($RawFile) { Write-Host ('               (재생 모드 - 결과는 ' + $outDir + ' 에만 기록, 실데이터는 건드리지 않음)') }
Write-Host '               (열려 있는 대화의 화면 렌더분만 - 상시 수집은 Start-TeamsSampler.ps1 을 켜두세요)'
Write-Host '               (날짜 표기가 없는 줄은 수집일 날짜로 추정 - 같은 줄이 7일 안에 다시 보이면 넣지 않음)'
