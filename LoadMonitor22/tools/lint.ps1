# lint.ps1 - single lint entry for LoadMonitor: 7 gates in one.
#   1) ruff (python)               2) PowerShell syntax parse
#   3) PAGE/TEAM_PAGE unescaped \n (JS SyntaxError -> 버튼 전멸 실사고 방지)
#   4) bat encoding (CP949 + CRLF, no BOM)
#   5) ps1 encoding (UTF-8 BOM + CRLF - BOM 없으면 CP949 오독으로 한글 끝 줄이 다음 줄을 삼킴)
#   6) 화면 JS 문법(tools\check_page_js.py)
#   7) 개발 PC 실경로 흔적(C:\Users\<실제 계정>·이 PC 프로필·알려진 개발 폴더) - 자리표시자만 허용
# exit 0 = clean, exit 1 = findings. Used by humans and the Claude Code PostToolUse hook.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$fail = 0

# --- 1) python: ruff (policy in ruff.toml) ---
# --no-cache: 트리 안에 .ruff_cache\ 를 만들지 않는다 — '폴더 통째로 복사' 경로에 딸려 갔다(실측).
Push-Location $root
python -m ruff check --no-cache core collect tools *.py --output-format=concise
if ($LASTEXITCODE -ne 0) { $fail = 1 }
Pop-Location

# --- 2) powershell: syntax parse of every collector/runner script ---
$psFiles = @(Get-ChildItem "$root\collect\*.ps1", "$root\tools\*.ps1", "$root\*.ps1" -ErrorAction SilentlyContinue)
foreach ($f in $psFiles) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)
    foreach ($e in $errors) {
        $fail = 1
        Write-Output ("{0}:{1}: {2}" -f $f.Name, $e.Extent.StartLineNumber, $e.Message)
    }
}

# --- 3) ui\app.py PAGE/TEAM_PAGE: 이스케이프 안 된 \n (서빙 시 JS 개행 -> SyntaxError) ---
$app = Join-Path $root 'ui\app.py'
if (Test-Path $app) {
    $src = [System.IO.File]::ReadAllText($app)
    foreach ($name in @('PAGE', 'TEAM_PAGE')) {
        # 'PAGE = """' 는 'TEAM_PAGE = """' 의 부분문자열이라 그냥 IndexOf 하면
        # 두 검사가 모두 TEAM_PAGE 를 잡아 PAGE 가 한 번도 검사되지 않았다(실측).
        $mk = "`n" + $name + ' = """'
        $i0 = $src.IndexOf($mk)
        if ($i0 -lt 0) { continue }
        $i1 = $src.IndexOf('"""', $i0 + $mk.Length)
        if ($i1 -lt 0) { continue }
        $body = $src.Substring($i0, $i1 - $i0)
        $bad = [regex]::Matches($body, '(?<!\\)\\n').Count
        if ($bad -gt 0) {
            $fail = 1
            Write-Output ("ui\app.py {0}: unescaped \n x{1} - JS 문자열 안에서는 \\n 로 써야 합니다" -f $name, $bad)
        }
    }
}

# --- 4) bat: CP949 로 디코드 가능 + CRLF (LF 단독 0) + BOM 없음 ---
foreach ($f in @(Get-ChildItem "$root\*.bat" -ErrorAction SilentlyContinue)) {
    $b = [System.IO.File]::ReadAllBytes($f.FullName)
    if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) {
        $fail = 1; Write-Output ("{0}: BOM 발견 - bat 은 BOM 없는 CP949 이어야 합니다" -f $f.Name)
    }
    $lone = 0
    for ($i = 0; $i -lt $b.Length; $i++) {
        if ($b[$i] -eq 10 -and ($i -eq 0 -or $b[$i - 1] -ne 13)) { $lone++ }
    }
    if ($lone -gt 0) { $fail = 1; Write-Output ("{0}: LF 단독 {1}개 - CRLF 이어야 합니다" -f $f.Name, $lone) }
    try {
        $enc = [System.Text.Encoding]::GetEncoding(949, [System.Text.EncoderFallback]::ExceptionFallback, [System.Text.DecoderFallback]::ExceptionFallback)
        [void]$enc.GetString($b)
    } catch { $fail = 1; Write-Output ("{0}: CP949 로 읽을 수 없는 바이트 존재" -f $f.Name) }
}

# --- 5) ps1: UTF-8 BOM + CRLF ---
foreach ($f in $psFiles) {
    $b = [System.IO.File]::ReadAllBytes($f.FullName)
    if (-not ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)) {
        $fail = 1; Write-Output ("{0}: UTF-8 BOM 없음 - PS5.1 이 CP949 로 오독합니다 (한글 끝 줄이 다음 줄을 삼키는 실사고)" -f $f.Name)
    }
    $lone = 0
    for ($i = 0; $i -lt $b.Length; $i++) {
        if ($b[$i] -eq 10 -and ($i -eq 0 -or $b[$i - 1] -ne 13)) { $lone++ }
    }
    if ($lone -gt 0) { $fail = 1; Write-Output ("{0}: LF 단독 {1}개 - CRLF 이어야 합니다" -f $f.Name, $lone) }
}

# --- gate 6: 화면 스크립트(PAGE/TEAM_PAGE 안의 <script>) JS 문법 ---
# JS 문법 오류가 하나만 있어도 스크립트 전체가 실행되지 않아 **버튼이 전부 죽는다**.
# HTML 은 멀쩡히 그려지므로 눈으로는 구분이 안 되고, 위 5관문 어느 것도 잡지 못한다.
# 실사고: 배너를 넣으며 쓴 변수명이 같은 블록에 이미 있어 버튼 11개가 전부 먹통이 됐다.
$jsChk = Join-Path $PSScriptRoot 'check_page_js.py'
if (Test-Path $jsChk) {
    $py = 'python'
    $embed = Join-Path (Split-Path -Parent $PSScriptRoot) 'python\python.exe'
    if (Test-Path $embed) { $py = $embed }
    $out = & $py $jsChk
    if ($LASTEXITCODE -ne 0) {
        $fail = 1
        $out | ForEach-Object { Write-Output $_ }
    }
}

# --- gate 7: 배포 트리 안의 개발 PC 실경로 ---
# 실측: 주석에 개발 PC 의 실제 폴더(D:\배포 · D:\작업\Release\fw)가 남은 채 배포됐다. 자리표시자
# (<사용자>·%USERNAME%·홍길동·D:\src·D:\작업·D:\LoadMonitor22 …)는 두고, 실제 계정 홈(C:\Users\<ASCII 계정>)·
# 이 PC 의 프로필 경로·알려진 개발 폴더만 잡는다. data\ report\ python\ teamdata\ 와 캐시는 보지 않는다.
# 예시 경로가 필요하면 <사용자>·홍길동 같은 자리표시자를 쓴다(이 파일 자신은 패턴을 담고 있어 검사에서 뺀다).
$skipTop = @('data', 'report', 'python', 'teamdata')
$exts = @('.py', '.ps1', '.bat', '.md', '.json', '.html', '.txt', '.toml')
$selfPath = $MyInvocation.MyCommand.Path
$cp949 = [System.Text.Encoding]::GetEncoding(949)
$rules = @(
    @{ re = '(?i)C:\\Users\\(?!Public(?:\\|\b)|Default(?:\\|\b)|All Users(?:\\|\b))[A-Za-z0-9._-]+(?=\\|\b)'; why = '실제 계정 홈 경로' },
    @{ re = 'D:\\배포(?=\\|\s|$|["''`)])'; why = '개발 PC 배포 폴더' },
    @{ re = '(?i)D:\\작업\\Release(?=\\|\s|$|["''`)])'; why = '개발 PC 저장소 경로' }
)
if ($env:USERPROFILE -and $env:USERPROFILE.Length -gt 3) {
    $rules += @{ re = '(?i)' + [regex]::Escape($env:USERPROFILE.TrimEnd('\')) + '(?=\\|\b)'; why = '이 PC 의 프로필 경로' }
}
foreach ($f in @(Get-ChildItem $root -Recurse -File -ErrorAction SilentlyContinue)) {
    if ($exts -notcontains $f.Extension.ToLower()) { continue }
    if ($f.FullName -eq $selfPath) { continue }
    $rel = $f.FullName.Substring($root.Length).TrimStart('\')
    $segs = $rel -split '\\'
    if ($skipTop -contains $segs[0]) { continue }
    if ($segs -contains '.ruff_cache' -or $segs -contains '__pycache__') { continue }
    # 개인 설정(config\config.json)은 배포 시 템플릿(config.default.json)으로 바꿔 담으므로 내 PC 의 실경로가 있어도 된다
    if ($rel -ieq 'config\config.json') { continue }
    $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
    $text = if ($f.Extension -eq '.bat') { $cp949.GetString($bytes) } else { [System.Text.Encoding]::UTF8.GetString($bytes) }
    $text = $text -replace '\\\\', '\'          # 파이썬·JSON 문자열의 '\\' 를 한 겹으로
    $ln = 0
    foreach ($line in ($text -split "`r?`n")) {
        $ln++
        foreach ($r in $rules) {
            $m = [regex]::Match($line, $r.re)
            if ($m.Success) {
                $fail = 1
                Write-Output ("{0}:{1}: {2} '{3}' - 자리표시자(<사용자>·홍길동·D:\src …)로 바꾸세요" -f $rel, $ln, $r.why, $m.Value)
                break                                   # 한 줄에 한 번만 알린다
            }
        }
    }
}

if ($fail -eq 0) { Write-Output 'lint OK (7 gates)' }
exit $fail
