# Test-TeamsWindow.ps1 - collect\Get-TeamsWindow.ps1 (WP3 C-18·C-19·C-20) - 창 주입(실 Teams 를 띄우지 않는다).
# 단언은 tests\test_p3_teams.py 가 한다. 결과 값만 돌려준다.
#  · 창 주입(일반·팝아웃·개인용 free·최소화) → 대상 2 · 제외 2 · 날짜 미상 줄은 undated 파일로만 · 다시 읽기(요소 20개 미만)
#  · 읽을 창이 없을 때 rc 3 R-UIAEMPTY · empty_cause / 팀즈 없음 rc 1
#  · 점 소싱한 함수 호출 1회 - 새 프로세스(powershell·csc) 0
#  · user32 동적 형식(Add-Type 없이)으로 최상위 창 열거가 되는가(읽기만)
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
. (Join-Path $root 'collect\Get-TeamsWindow.ps1')
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('lm28_tw_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$tmp2 = Join-Path $tmp 'inproc'
New-Item -ItemType Directory -Force -Path $tmp2 | Out-Null
try {
    $today = [datetime]'2026-10-07'
    $cfg = @{ owner = '테스트사용자' }          # 설정 이름이 있으면 AD 조회를 하지 않는다(네트워크 없음)
    $win1 = @{ hwnd = [IntPtr]1; pid = 100; title = '채팅 | 홍길동 | Microsoft Teams'; visible = $true; iconic = $false; cloaked = $false; on_screen = $true
               texts = @('홍길동, 2026. 10. 5. 오후 3:24 회의 자료 공유드립니다', '김철수, 오후 4:10 날짜 없는 메시지입니다') }
    $win2 = @{ hwnd = [IntPtr]2; pid = 100; title = '이영희 | 팝아웃 | Microsoft Teams'; visible = $true; iconic = $false; cloaked = $false; on_screen = $true
               texts = @('이영희, 2026. 10. 6. 오전 9:15 팝아웃 창의 메시지입니다')
               retry = @('이영희, 2026. 10. 6. 오전 9:15 팝아웃 창의 메시지입니다', '이영희, 2026. 10. 6. 오전 9:20 두 번째 메시지입니다') }
    $win3 = @{ hwnd = [IntPtr]3; pid = 200; title = 'Microsoft Teams (free)'; visible = $true; iconic = $false; cloaked = $false; on_screen = $true
               texts = @('개인, 2026. 10. 6. 오후 1:00 개인 계정 메시지입니다') }
    $win4 = @{ hwnd = [IntPtr]4; pid = 100; title = '다른 대화 | Microsoft Teams'; visible = $true; iconic = $true; cloaked = $false; on_screen = $true
               texts = @('박민수, 2026. 10. 6. 오후 2:00 최소화 창 메시지입니다') }
    $pres = @{ present = $true; appx = $true; classic = $false; proc = $true }
    $common = @{ Root = $root; Present = $pres; Cfg = $cfg; OutDir = $tmp; Today = $today; RetryDelayMs = 0; Quiet = $true }

    $r1 = @(Invoke-TeamsWindowRead -Windows @($win1, $win2, $win3, $win4) @common)[-1]
    $csv = @([System.IO.File]::ReadAllLines((Join-Path $tmp 'teams_window.csv'), [System.Text.Encoding]::UTF8))
    $ud = @()
    $udp = Join-Path $tmp 'undated_teams_window.csv'
    if (Test-Path -LiteralPath $udp) { $ud = @([System.IO.File]::ReadAllLines($udp, [System.Text.Encoding]::UTF8)) }
    $status = Format-TwStatus $r1
    $r1b = @(Invoke-TeamsWindowRead -Windows @($win1, $win2, $win3, $win4) @common)[-1]       # 같은 화면 다시 - 새 줄 0
    $ud2 = @([System.IO.File]::ReadAllLines($udp, [System.Text.Encoding]::UTF8))
    $r2 = @(Invoke-TeamsWindowRead -Windows @($win3, $win4) @common)[-1]                        # 개인용·최소화 창뿐
    $c3 = @{}; foreach ($k in $common.Keys) { $c3[$k] = $common[$k] }
    $c3.Present = @{ present = $false; appx = $false; classic = $false; proc = $false }
    $r3 = @(Invoke-TeamsWindowRead -Windows @() @c3)[-1]                                        # 팀즈 없음

    # 점 소싱한 함수를 새 폴더로 1회 - 함수 호출만(새 프로세스 0). powershell 을 부르면 세는 가로채기 함수를 잠깐 둔다.
    $names = '^(powershell|pwsh|csc|cvtres)$'
    $before = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match $names } | ForEach-Object { $_.Id })
    $global:LmTwSpawnCalls = 0
    function global:powershell { $global:LmTwSpawnCalls++ }
    try {
        $ra = @{ Windows = @($win1, $win2); Root = $root; Present = $pres; Cfg = $cfg; OutDir = $tmp2; Today = $today; RetryDelayMs = 0; Quiet = $true }
        $null = @(Invoke-TeamsWindowRead @ra)
    } finally {
        Remove-Item -Path function:global:powershell -ErrorAction SilentlyContinue
    }
    $after = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match $names } | ForEach-Object { $_.Id })
    $spawned = @($after | Where-Object { $before -notcontains $_ }).Count
    $ipCsv = Join-Path $tmp2 'teams_window.csv'
    $ipRows = 0
    if (Test-Path -LiteralPath $ipCsv) { $ipRows = @([System.IO.File]::ReadAllLines($ipCsv, [System.Text.Encoding]::UTF8)).Count - 1 }

    # 직접 실행 가드 - & 로 부르면 본체가 돌고 마지막 줄이 LMSTATUS, 종료 코드 = rc (없는 원문 파일 → rc 1, 폴더를 만들지 않는다)
    $direct = @(& (Join-Path $root 'collect\Get-TeamsWindow.ps1') -RawFile (Join-Path $tmp 'nope_raw.txt') 6>&1 | ForEach-Object { [string]$_ })
    $directRc = $LASTEXITCODE
    $directStatus = @($direct | Where-Object { $_ -like 'LMSTATUS *' }) | Select-Object -Last 1

    # user32 동적 형식으로 최상위 창 열거(읽기만 - 창을 띄우거나 바꾸지 않는다)
    $wc = 0; $wt = 0; $werr = ''
    try {
        $all = Get-TwTopWindows @() 400
        $wc = $all.Count
        $wt = @($all | Where-Object { $_.title }).Count
    } catch { $werr = $_.Exception.Message }

    return @{
        r1_rc = [int]$r1.rc; r1_targets = [int]$r1.counts.targets; r1_excluded = [int]$r1.counts.excluded
        r1_personal = [int]$r1.counts.personal_title; r1_iconic = [int]$r1.counts.iconic; r1_rows_new = [int]$r1.counts.rows_new
        r1_undated = [int]$r1.counts.undated; r1_retry_reads = [int]$r1.counts.retry_reads; r1_retry_gain = [int]$r1.counts.retry_gain
        r1_present = [bool]$r1.counts.teams_present; r1_cause = [string]$r1.counts.empty_cause
        r1_ranges = (@($r1.ranges | ForEach-Object { $_.axis + ':' + $_.from + '~' + $_.to + ':' + $_.st }) -join ';')
        csv_rows = $csv.Count - 1; csv_has_undated = [bool](@($csv | Where-Object { $_ -match '날짜 없는' }).Count)
        csv_has_free = [bool](@($csv | Where-Object { $_ -match '개인 계정' }).Count)
        undated_rows = $ud.Count - 1; undated_rows_again = $ud2.Count - 1
        undated_has = [bool](@($ud | Where-Object { $_ -match '날짜 없는' }).Count)
        status = $status
        r1b_rc = [int]$r1b.rc; r1b_rows_new = [int]$r1b.counts.rows_new
        r2_rc = [int]$r2.rc; r2_reason = [string]$r2.reason; r2_cause = [string]$r2.counts.empty_cause
        r3_rc = [int]$r3.rc; r3_reason = [string]$r3.reason; r3_cause = [string]$r3.counts.empty_cause
        inproc_rows = $ipRows; spawned = $spawned; spawn_calls = [int]$global:LmTwSpawnCalls
        win32_count = $wc; win32_titled = $wt; win32_error = $werr
        direct_rc = [int]$directRc; direct_status = [string]$directStatus
    }
} finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Variable -Name LmTwSpawnCalls -Scope Global -ErrorAction SilentlyContinue
}
