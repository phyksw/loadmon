# Prepare-Move.ps1 - 프로그램 정리와 폴더 확인 뒤, 개인 상태를 보존한 이동 ZIP을 만듭니다.
#
# 왜 필요한가: 분석이 끝난 뒤 폴더를 옮기려 하면 "사용 중" 이라 옮겨지지 않는다.
# 잡고 있는 것은 대개 우리 자신이다 - 대시보드(python ui\app.py), 팀 서버(teamserver.py),
# Copilot 전용 Edge(data\copilot_profile), 상시 샘플러(powershell), 그리고 그 폴더를 열어 둔 탐색기.
#
# 중요: 이 스크립트는 %TEMP% 로 복사돼 실행된다. LoadMonitor 폴더 안에서 실행하면
# 스크립트 파일 자체가 폴더를 잡아 '옮길 수 있는가' 시험이 항상 실패한다.
#
# ── 화면 문구 규칙(제보로 고친 것) ────────────────────────────────────────────
# 제보: "작업이 종료되었음에도 cmd 창 멘트 때문에 사람들이 오류가 난 줄 알고 계속 시도한다".
# 감사에서 확인한 원인과 그 처방:
#  · 성공했는데도 '[!] 탐색기가 …' 경고가 성공 배너 **위**에 찍혔다. 이 도구에서 '[!]' 는 오류 표시라
#    사용자가 그것을 먼저 읽고 실패로 판단했고, 창을 닫고 다시 실행하려면 탐색기로 폴더를 또 열어야 해서
#    같은 경고가 또 떴다. → 이동 가능 확인을 **먼저** 하고, 성공하면 탐색기 경고를 아예 찍지 않는다.
#    (성공 경로에서는 '[!]' 를 절대 쓰지 않는다.)
#  · 성공 화면의 유일한 상태 줄이 '종료할 우리 프로그램이 없습니다' 라는 부정문이었다. → 능동 서술로.
#  · 성공·실패 배너가 글자만 다르고 모양이 똑같았다. → 머리표([완료]/[실패])·테두리 문자·색을 다르게.
#  · 화면 어디에도 '완료' 가 없었고 마지막 줄이 설명문이었다. → 마지막 줄에 판정을 다시 찍는다.
#  · PID 나열은 개발자 덤프로 읽힌다. → 화면에는 사람 말 이름만, PID·원문은 move_ready.txt 로.
#  · 실패 사유가 영문 .NET 예외 원문이었다. → 한국어 한 줄로 옮기고 원문은 기록으로.
#  · 창 제목이 비어 있었다. → 스스로 제목을 잡고 끝에 [완료]/[미완료] 를 붙인다.
#  · ZIP 검증이 끝난 뒤에만 완료를 표시하고, 다음 PC에 복사할 경로를 안내한다.
#
# Usage:  powershell -ExecutionPolicy Bypass -File Prepare-Move.ps1 -Root "D:\...\LoadMonitor25"
param(
    [Parameter(Mandatory = $true)][string]$Root,
    [string]$Output,
    [switch]$NoWait,
    [switch]$CheckOnly,
    [int]$CloseSec = 15     # ZIP 경로를 읽을 시간을 준다(0 = 즉시). 실패 시에는 기다린다.
)
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor25 - PC 이동 준비' } catch {}
# 경로 정규화 — bat 가 "…\LoadMonitor25\." 처럼 넘겨도(끝 역슬래시가 닫는 따옴표를 삼키지 않게 붙이던 점)
# '\.'·'..'·끝 역슬래시를 지운 정규 경로로 만든다. 실사고: '…\.' 그대로 Split-Path 하면 부모가 폴더 자신이 되어
# 폴더를 '_이동확인_임시' 로 바꿔 놓고 되돌리지 못한 채, 빈 껍데기 LoadMonitor25\report\move_ready.txt 만 만들었다.
if ($Root -match '^[A-Za-z]:$') { $Root += '\' }          # 'D:' 는 '그 드라이브의 현재 폴더' 라 뜻이 달라진다
try {
    if (-not [System.IO.Path]::IsPathRooted($Root)) { $Root = Join-Path (Get-Location).Path $Root }
    $Root = [System.IO.Path]::GetFullPath($Root)
} catch {}
if ($Root.Length -gt 3) { $Root = $Root.TrimEnd('\') }     # 드라이브 루트('D:\')는 그대로
if (-not (Test-Path -LiteralPath $Root -PathType Container)) { Write-Host "[이동준비] 폴더가 없습니다: $Root"; if (-not $NoWait) { pause }; exit 1 }
if ($Root -match '^[A-Za-z]:\\$') { Write-Host "[이동준비] 드라이브 루트($Root)는 이름을 바꿔 확인할 수 없습니다 - LoadMonitor25 를 하위 폴더에 두세요"; if (-not $NoWait) { pause }; exit 1 }
Set-Location ([System.IO.Path]::GetTempPath())     # 이 창이 폴더를 잡지 않게
# Set-Location 은 PowerShell 의 위치만 바꾸고 프로세스의 현재 폴더(Win32 cwd)는 그대로다 — bat(cd /d "%~dp0" 뒤 start)
# 나 대시보드(app.py 의 cwd)에서 띄우면 우리 프로세스 자신이 LoadMonitor25 안에 서 있어 이름 바꾸기 시험이
# "다른 프로세스가 사용 중" 으로 항상 실패했다(실측). 프로세스 cwd 도 TEMP 로 옮겨 손을 뗀다.
try { [Environment]::CurrentDirectory = [System.IO.Path]::GetTempPath() } catch {}

function Say([string]$text, [string]$color) {
    if ($color) { try { Write-Host $text -ForegroundColor $color; return } catch {} }
    Write-Host $text
}

# 프로세스 이름을 사람 말로 — 화면에는 이것만 쓰고 PID·경로는 기록 파일로 보낸다.
function Friendly([string]$name, [string]$cmdline) {
    $n = ($name -replace '\.exe$', '').ToLower()
    if ($n -eq 'msedge') { return 'Copilot 전용 Edge 창' }
    if ($n -eq 'powershell' -or $n -eq 'pwsh') { return '상시 샘플러' }
    if ($n -eq 'cmd') { return 'LoadMonitor25 실행 창' }
    if ($n -eq 'python' -or $n -eq 'pythonw') {
        if ($cmdline -match 'teamserver\.py') { return '팀 서버' }
        if ($cmdline -match 'app\.py') { return '대시보드' }
        return '분석·수집 프로그램'
    }
    return $name
}

# 영문 .NET 예외를 한국어 한 줄로 — 원문은 화면에 내지 않고 move_ready.txt 에만 남긴다.
function Explain([string]$msg) {
    if (-not $msg) { return '확인이 막혔습니다' }
    if ($msg -match 'being used by another process|다른 프로세스') { return '다른 프로그램이 이 폴더의 파일을 열고 있습니다' }
    if ($msg -match 'is denied|Access to the path|액세스가 거부') { return '이 폴더의 이름을 바꿀 권한이 없습니다' }
    if ($msg -match 'already exists|이미 있') { return '같은 이름의 폴더가 이미 있습니다' }
    if ($msg -match 'could not be found|찾을 수 없') { return '폴더를 찾지 못했습니다' }
    return '확인이 막혔습니다'
}

Write-Host ''
Say '  [PC 이동 준비] 프로그램을 정리하고 이동 ZIP 하나를 만듭니다' 'Cyan'
Write-Host ("  대상: " + $Root)
Write-Host ''
if (-not $NoWait) { Start-Sleep -Milliseconds 800 }   # 우리를 띄운 bat/cmd 가 먼저 닫히도록

function Path-Under([string]$path, [string]$root) {
    try {
        # Drive-relative/root-relative paths depend on an unrelated process's
        # current directory and cannot identify this installation reliably.
        if (-not [System.IO.Path]::IsPathRooted($path) -or $path -notmatch '^(?:[A-Za-z]:[\\/]|\\\\)') { return $false }
        $candidate = [System.IO.Path]::GetFullPath($path).TrimEnd('\')
        return $candidate.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
            $candidate.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

function Command-Arguments([string]$commandLine) {
    if (-not $commandLine) { return @() }
    try {
        if (-not ('LM25MoveCommandLine' -as [type])) {
            # Windows quoting rules distinguish "LoadMonitor25 archive" from
            # LoadMonitor25. A whitespace boundary in a regex cannot do this.
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class LM25MoveCommandLine {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CommandLineToArgvW(string line, out int count);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);
    public static string[] Parse(string line) {
        int count;
        IntPtr memory = CommandLineToArgvW(line, out count);
        if (memory == IntPtr.Zero) return new string[0];
        try {
            string[] values = new string[count];
            for (int i = 0; i < count; i++)
                values[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(memory, i * IntPtr.Size));
            return values;
        } finally { LocalFree(memory); }
    }
}
'@ -ErrorAction Stop
        }
        return [LM25MoveCommandLine]::Parse($commandLine)
    } catch { return @() } # Uncertain command lines never select a process.
}

function Command-Under([string]$commandLine, [string]$root) {
    foreach ($argument in @(Command-Arguments $commandLine)) {
        $path = $argument
        if ($argument -match '^--?[A-Za-z][A-Za-z0-9-]*=(.*)$') { $path = $Matches[1] }
        if (Path-Under $path $root) { return $true }
    }
    return $false
}

function Copilot-Under([string]$commandLine, [string]$root) {
    foreach ($argument in @(Command-Arguments $commandLine)) {
        if ($argument -match '^--user-data-dir=(.+)$') {
            $profile = $Matches[1]
            if ((Path-Under $profile $root) -and $profile -match '[\\/]copilot_profile[\\/]?$') { return $true }
        }
    }
    return $false
}

function Procs-Under([string]$root) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        (Path-Under $_.ExecutablePath $root) -or (Command-Under $_.CommandLine $root)
    }
}

function New-MoveZip([string]$source, [string]$destination) {
    $tool = Join-Path $source 'tools\transfer.py'
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw 'tools\transfer.py가 없습니다. 배포 파일을 확인하세요.'
    }
    $python = Join-Path $source 'python\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $command = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw '내장 Python이 없습니다. 배포 파일을 확인하세요.' }
        $python = $command.Source
    }
    $arguments = @('-B', $tool, '--root', $source, '--json')
    if ($destination) { $arguments += @('--output', $destination) }
    $result = $null
    # PowerShell 5.1 decodes native output with the console code page. --json
    # emits UTF-8, including the ZIP path, regardless of the launcher's code page.
    $previousEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        & $python @arguments 2>&1 | ForEach-Object {
            $line = $_.ToString()
            try { $event = $line | ConvertFrom-Json -ErrorAction Stop } catch { $event = $null }
            if ($event -and $event.status -eq 'progress') {
                Write-Host ('  ZIP 생성: {0}/{1}개 파일' -f $event.processed_files, $event.file_count)
            } elseif ($event -and $event.status -in @('completed', 'failed')) {
                $result = $event
            } elseif ($line) {
                Write-Host ('  ' + $line)
            }
        }
        $code = $LASTEXITCODE
    } finally {
        [Console]::OutputEncoding = $previousEncoding
    }
    if ($code -ne 0 -or -not $result -or $result.status -ne 'completed') {
        if ($result -and $result.error) { throw [string]$result.error }
        throw 'ZIP 생성이 완료되지 않았습니다. 위 메시지를 확인하세요.'
    }
    if (-not $result.output -or -not (Test-Path -LiteralPath $result.output -PathType Leaf)) {
        throw '완료된 ZIP 파일을 확인하지 못했습니다.'
    }
    return $result
}

$killed = New-Object System.Collections.Generic.List[string]     # 화면용 - 사람 말 이름
$killedLog = New-Object System.Collections.Generic.List[string]  # 기록용 - 이름 + PID
if (-not $CheckOnly) {
    # 우리가 띄운 창(대시보드·LoadMonitor25 실행 창)이 곧 사라진다. 예고 없이 사라지면 그것 자체가
    # '오류로 꺼졌다' 로 읽힌다(감사 확정) — 죽이기 전에 먼저 알린다.
    Say '  LoadMonitor25 창(대시보드·팀 서버·샘플러)을 닫습니다 - 창이 사라지는 것은 정상입니다.' 'DarkGray'
    Start-Sleep -Milliseconds 400
    # ① 우리 것부터 - 대시보드·팀 서버·수집기(python), 상시 샘플러(powershell)
    foreach ($p in Procs-Under $Root) {
        if ($p.ProcessId -eq $PID) { continue }
        $nm = $p.Name
        if ($nm -notmatch '^(python|pythonw|powershell|pwsh|cmd)\.exe$') { continue }
        try {
            $fr = Friendly $nm $p.CommandLine
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            $killed.Add($fr)
            $killedLog.Add("$nm (pid $($p.ProcessId)) = $fr")
        } catch {}
    }
    # ② Copilot 전용 Edge - 일반 Edge 는 건드리지 않는다
    Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
        Where-Object { Copilot-Under $_.CommandLine $Root } | ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                $killed.Add('Copilot 전용 Edge 창')
                $killedLog.Add("msedge (Copilot 전용, pid $($_.ProcessId))")
            } catch {}
        }
    if ($killed.Count) {
        # 화면에는 사람 말 이름만, 중복을 지우고 최대 3개까지. PID 는 기록 파일로 보낸다.
        $uniq = @($killed | Select-Object -Unique)
        $show = if ($uniq.Count -gt 3) { ($uniq[0..2] -join ', ') + (' 외 {0}개' -f ($uniq.Count - 3)) } else { $uniq -join ', ' }
        Write-Host ("  닫았습니다: " + $show)
    } else {
        # 부정문('없습니다')은 이 도구에서 오류 문구라 성공 화면에 쓰지 않는다 — 능동 서술로 적는다.
        Write-Host '  확인했습니다: 이 폴더를 쓰고 있는 LoadMonitor25 프로그램은 이미 모두 닫혀 있었습니다'
    }
    Start-Sleep -Milliseconds 700
}

# 탐색기가 그 폴더를 열어 두었는지 - 목록만 모아 두고 화면에는 아직 찍지 않는다.
# 열려 있어도 이동 가능 확인은 대개 통과하므로, 성공했다면 이 경고는 사용자를 헷갈리게 할 뿐이다.
$explorer = @()
try {
    $sh = New-Object -ComObject Shell.Application
    foreach ($w in $sh.Windows()) {
        try {
            $p = $w.Document.Folder.Self.Path
            # 구분자까지 봐야 형제 폴더(LoadMonitor25_old)를 오탐하지 않는다
            if ($p -and ($p -eq $Root -or $p.StartsWith($Root + '\', [System.StringComparison]::OrdinalIgnoreCase))) { $explorer += $p }
        } catch {}
    }
} catch {}

# ── 진짜 시험: 폴더 이름을 잠깐 바꿔 본다. 성공하면 옮길 수 있다는 뜻이다. ──
$parent = Split-Path -Parent $Root
$leaf = Split-Path -Leaf $Root
$probe = Join-Path $parent ($leaf + '_이동확인_임시')
$movable = $false
$restored = $false
$why = ''
$whyRaw = ''
$backRaw = ''
# 방금 죽인 프로그램이 손을 놓는 데 시간이 걸린다 - 한 번 실패했다고 바로 실패로 적으면
# '실제로는 곧 옮길 수 있는데 실패 배너' 가 뜬다(감사 확정). 몇 번 더 기다려 본다.
for ($try = 0; $try -lt 4 -and -not $movable; $try++) {
    if ($try) { Start-Sleep -Milliseconds 900 }
    try {
        Rename-Item -LiteralPath $Root -NewName ($leaf + '_이동확인_임시') -ErrorAction Stop
        $movable = $true
    } catch {
        $whyRaw = $_.Exception.Message
        $why = Explain $whyRaw
    }
}
if ($movable) {
    # 되돌리기 — 백신·탐색기가 새 이름을 잠깐 잡을 수 있어 몇 번 더 시도한다
    for ($i = 0; $i -lt 5 -and -not $restored; $i++) {
        if ($i) { Start-Sleep -Milliseconds 400 }
        try { Rename-Item -LiteralPath $probe -NewName $leaf -ErrorAction Stop; $restored = $true } catch { $backRaw = $_.Exception.Message }
    }
}

Write-Host ''
$zip = $null
$zipError = ''
$success = $false
if ($movable -and $restored) {
    if ($CheckOnly) {
        # Keep the legacy diagnostic switch: rename/restore only, with no
        # process termination or archive creation.
        $success = $true
    } else {
        Say '  폴더 확인과 원래 이름 복원이 끝났습니다. 이동 ZIP을 만듭니다…' 'Cyan'
        Write-Host '  설정·수집 자료·보고서·팀 자료·내장 Python을 보존합니다.'
        Write-Host '  전용 브라우저 프로필과 실행 캐시는 제외합니다.'
        try { $zip = New-MoveZip $Root $Output; $success = $true }
        catch { $zipError = $_.Exception.Message }
    }
} elseif ($movable) {
    $zipError = '폴더의 원래 이름을 되돌리지 못해 ZIP 생성을 멈췄습니다.'
}

if ($success) {
    try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor25 - PC 이동 준비 [완료]' } catch {}
    Say '  ============================================================' 'Green'
    if ($CheckOnly) {
        Say '   [완료] 폴더 이동 가능 확인과 원래 이름 복원이 끝났습니다.' 'Green'
        Write-Host '          확인 전용 실행이므로 프로그램 종료·ZIP 생성은 하지 않았습니다.'
    } else {
        Say '   [완료] PC 이동 준비와 ZIP 검증이 끝났습니다.' 'Green'
        Write-Host ('          ' + $zip.output)
    }
    Say '  ============================================================' 'Green'
    if (-not $CheckOnly) {
        Write-Host ''
        Write-Host '   1) 위 ZIP 하나를 다음 PC로 복사하세요.'
        Write-Host '   2) 빈 폴더에 압축을 풀고 안의 LoadMonitor25-UI.bat을 실행하세요.'
        Write-Host '   3) 추가 수집할 PC에서는 수집을 계속하고, 마지막 PC에서는 수집 자료로 분석하세요.'
        Write-Host '   설정·추가 PC 기록·보고서·업로드 대기 묶음이 함께 들어 있습니다.'
        Write-Host '   새 PC에서는 회사 계정에 다시 로그인할 수 있습니다.'
        Write-Host '   원본 폴더와 자료는 보존되어 있습니다.'
    }
} else {
    try { $Host.UI.RawUI.WindowTitle = 'LoadMonitor25 - PC 이동 준비 [미완료]' } catch {}
    Say '  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' 'Red'
    Say '   [미완료] PC 이동 준비를 마치지 못했습니다.' 'Red'
    Say '  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' 'Red'
    Write-Host ("   사유: " + $(if ($zipError) { $zipError } elseif ($why) { $why } else { '확인이 막혔습니다' }))
    Write-Host ''
    if ($movable -and -not $restored) {
        Say '   원본 자료는 아래 임시 이름의 폴더에 보존되어 있습니다.' 'Yellow'
        Write-Host ('   ' + $probe)
        Write-Host ('   사용 중인 프로그램을 닫고 폴더 이름을 ' + $leaf + '(으)로 되돌린 뒤 다시 실행하세요.')
    } else {
        Write-Host ('   원본 폴더와 자료는 보존되어 있습니다: ' + $Root)
    }
    if (-not $movable -and $explorer.Count) {
        # 실패했을 때에만 탐색기 경로를 보여 준다 - 이때는 실제로 조치가 필요한 정보다.
        Write-Host '   탐색기가 이 폴더를 열어 두고 있습니다 - 그 창을 닫으세요:'
        foreach ($p in ($explorer | Select-Object -Unique)) { Write-Host ("      " + $p) }
        Write-Host ''
    }
    if (-not $movable) {
        Write-Host '   폴더를 연 탐색기·Excel·메모장·명령 프롬프트를 닫고 다시 실행하세요.'
        $left = @(Procs-Under $Root | Where-Object { $_.ProcessId -ne $PID } |
                  ForEach-Object { Friendly $_.Name $_.CommandLine } | Select-Object -Unique)
        if ($left.Count) { Write-Host ('   아직 이 폴더를 쓰는 프로그램: ' + ($left -join ', ')) }
    }
}

# Write the result only after transfer.py has finished its source verification.
# Never recreate a missing original path after a failed rename restoration.
try {
    $where = if ($restored -or -not $movable) { $Root } else { $probe }
    if (Test-Path -LiteralPath $where -PathType Container) {
        $rep = Join-Path $where 'report'
        if (-not (Test-Path -LiteralPath $rep)) { New-Item -ItemType Directory -Path $rep | Out-Null }
        $log = @(
            ('이동 준비 ' + $(if ($success) { '완료' } else { '미완료' }) + '  ' + (Get-Date).ToString('yyyy-MM-dd HH:mm'))
            ('폴더 이동 가능 확인: ' + $movable)
            ('이름 되돌리기: ' + $restored)
            ('확인 전용: ' + [bool]$CheckOnly)
            ('ZIP: ' + $(if ($zip) { $zip.output } else { '(생성하지 않음)' }))
            ('사유: ' + $zipError + ' ' + $whyRaw + ' ' + $backRaw)
            ('종료한 프로그램: ' + ($killedLog -join ', '))
        )
        [System.IO.File]::WriteAllLines((Join-Path $rep 'move_ready.txt'), $log, [System.Text.Encoding]::UTF8)
    }
} catch {}
Write-Host ''
# 다 끝났는데 '아무 키나 누르세요' 로 창이 남아 있으면 그것 자체가 '안 끝났다' 로 읽힌다(제보).
# 성공이면 스스로 닫고, 실패면 사유를 읽어야 하므로 기다린다.
if (-not $NoWait) {
    if ($success) {
        $left = [math]::Max(0, $CloseSec)
        $held = $false
        while ($left -gt 0) {
            Write-Host ("`r  [완료] 정리가 끝났습니다 - {0}초 뒤 이 창이 자동으로 닫힙니다. (읽고 계시면 아무 키나 누르세요)   " -f $left) -NoNewline
            $t0 = [datetime]::Now
            while (([datetime]::Now - $t0).TotalMilliseconds -lt 1000) {
                # 콘솔이 아닌 곳(입력 리디렉션·작업 스케줄러)에서는 KeyAvailable 이 예외를 던진다 -
                # 그때는 키를 못 받는 것이 정상이므로 조용히 카운트다운만 계속한다.
                try { if ($Host.UI.RawUI.KeyAvailable) { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown'); $held = $true; break } }
                catch { Start-Sleep -Milliseconds 920; break }
                Start-Sleep -Milliseconds 80
            }
            if ($held) { break }
            $left--
        }
        Write-Host ''
        if ($held) {
            Write-Host '  자동 닫힘을 멈췄습니다. 창을 닫으려면 아무 키나 누르세요.'
            $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        }
    } else {
        Write-Host '  창을 닫으려면 아무 키나 누르세요.'
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    }
}
if ($success) { exit 0 } else { exit 1 }
