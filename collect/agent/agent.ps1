<#
.SYNOPSIS
  ps 구현 감독 루프·샘플러(계약 §2.4 · §7.3 · X-017 · X-029 · X-307 · TAB §1.6.1 ②·§1.6.7 · CP §3) — 에이전트 bin 사본의 ps\agent.ps1.

.DESCRIPTION
  py 구현(사본 agent_main.py)이 자기 시험에 실패한 PC 에서 작업 스케줄러가 이 스크립트를 띄운다. 구조는 py 구현과 같다:
    · 뮤텍스 Local\LM27-<install_id>-agent(이미 있으면 끝) · cwd = 에이전트 폴더 · 프로그램 폴더를 보지 않는다(사본·에이전트 파일만).
    · 매 틱(agent.sampleIntervalSec): Add-Type(user32·kernel32·wtsapi32)로 전경 창·유휴(2^32 모듈로)·세션(WTS) 원시 틱을
      메모리에만 만들고, 직전 틱 레코드를 실제 간격으로 확정해 버퍼에 쌓는다. 제목 원문은 메모리 버퍼에만 있다.
    · 플러시(첫 레코드 · agent.flushIntervalSec · agent.flushMaxRows · 세션 잠금 · 절전 복귀 · 종료): 버퍼를 NDJSON 으로 사본 파이프
      lm27_pipe.py --kind pc_session --src pc.sampler --mode append 의 stdin 에 넘긴다 — PS 는 store 에 직접 쓰지 않는다(TAB-B22).
      연산 구간(솔버 CPU)은 --kind pc_compute --src pc.compute 로 같은 방식. 파이프가 privacy.pipe.waitSec 안에 끝나지 않으면 끊는다(99).
    · 카탈로그 판정(app_id·app_class·솔버)은 사본 파이썬(agent_main.py --classify — lm27.catalog 한 곳)에 묻고 캐시한다.
    · heartbeat.json 매 틱 원자 교체(last_error 는 유형·코드만) · 자식: 수확·teams.uia·열린 문서 폴링 = ps\harvest.ps1(연결자) ·
      보존 정리 = agent_main.py --maintain(하루 한 번) · 시작 점검 = agent_main.py --start-check(규칙 해시 R-RULESMISMATCH ·
      pc_id 변동 TAB-B26).
  디스크 쓰기는 원문 없는 운영 파일(heartbeat.json · logs\)뿐이다(L-09 · X-307).

  -TestSamples N(계약 §11.3 주입점): 뮤텍스·저장 없이 표본 N 개 + 언어 모드·Add-Type 확인 + 파이프 왕복 1건(%TEMP% 임시 출력,
  끝나면 지움) → stdout 한 줄 {"_selftest": {...}}(숫자·참거짓·사유 코드만). 제한 언어 모드·Add-Type 실패는 R-CLM, 사본 파이썬이
  실행되지 않으면 R-APPLOCKER.

.PARAMETER InstallId
  32자리 16진 install_id
.PARAMETER TestSamples
  자기 시험 표본 수(0 = 상주)
.PARAMETER TestNow
  시험 주입: 표본 시각 기준(UTC ISO)
#>
param(
    [string]$InstallId = '',
    [int]$TestSamples = 0,
    [string]$TestNow = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Off
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $script:Utf8 } catch { }
$script:Inv = [Globalization.CultureInfo]::InvariantCulture

# ───────────────────────── 위치(사본 기준) ─────────────────────────
$script:PsDir = $PSScriptRoot
$script:Bin = Split-Path -Parent $script:PsDir
$script:AgentDir = Split-Path -Parent (Split-Path -Parent $script:Bin)
$script:Py = Join-Path (Join-Path $script:Bin 'py311') 'python.exe'
$script:Pipe = Join-Path $script:Bin 'lm27_pipe.py'
$script:Main = Join-Path $script:Bin 'agent_main.py'
$script:RunDir = Join-Path $script:AgentDir 'run'
$script:PsExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

$GapCap = 1.5
$IdleMax = 4294968
$TitleMax = 1024
$HarvestStreams = 'pc_session/pc.events,pc_file/pc.files,pc_file/pc.mru,pc_file/pc.recent'
$HarvestMaxSec = 1800
$MaintEverySec = 86400
$TestGapMs = 1000

# ───────────────────────── JSON ─────────────────────────
function ConvertTo-LmJsonString([string]$s) {
    $s = $s.Replace('\', '\\').Replace('"', '\"')
    if ($s -match '[\x00-\x1f]') {
        $s = [regex]::Replace($s, '[\x00-\x1f]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
    }
    return '"' + $s + '"'
}

function ConvertTo-LmJson($v) {
    if ($null -eq $v) { return 'null' }
    if ($v -is [bool]) { if ($v) { return 'true' } else { return 'false' } }
    if ($v -is [string]) { return (ConvertTo-LmJsonString $v) }
    if ($v -is [double] -or $v -is [single] -or $v -is [decimal]) {
        $t = ([double]$v).ToString('R', $script:Inv)
        if ($t -notmatch '[.eE]') { $t += '.0' }
        return $t
    }
    if ($v -is [int] -or $v -is [long] -or $v -is [int16] -or $v -is [byte] -or $v -is [uint32] -or $v -is [uint64]) {
        return ([Convert]::ToString($v, $script:Inv))
    }
    $parts = New-Object 'Collections.Generic.List[string]'
    if ($v -is [Collections.IDictionary]) {
        foreach ($k in @($v.Keys)) { $parts.Add((ConvertTo-LmJsonString ([string]$k)) + ':' + (ConvertTo-LmJson $v[$k])) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v -is [Management.Automation.PSCustomObject]) {
        foreach ($p in $v.PSObject.Properties) { $parts.Add((ConvertTo-LmJsonString $p.Name) + ':' + (ConvertTo-LmJson $p.Value)) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($v -is [Collections.IEnumerable]) {
        foreach ($x in $v) { $parts.Add((ConvertTo-LmJson $x)) }
        return '[' + ($parts -join ',') + ']'
    }
    return (ConvertTo-LmJsonString ([string]$v))
}

function Format-LmUtc([datetime]$dt) {
    if ($dt.Kind -ne [DateTimeKind]::Utc) { $dt = $dt.ToUniversalTime() }
    return $dt.ToString("yyyy'-'MM'-'dd'T'HH':'mm':'ss'Z'", $script:Inv)
}

# 분 → '+09:00'(파이썬 lm27.util.tz.fmt_offset 과 같다)
function Format-LmOffset([int]$m) {
    $sg = '+'
    if ($m -lt 0) { $sg = '-'; $m = -$m }
    return ('{0}{1:00}:{2:00}' -f $sg, [int][math]::Floor($m / 60), ($m % 60))
}

# ───────────────────────── 순수 판정(파이썬 lm27.agent.sampler 와 같은 값 — 시험이 AST 로 꺼내 대조한다) ─────────────────────────
# 유휴 초 = ((GetTickCount64 − dwTime) mod 2^32) / 1000 반올림(짝수 쪽), 상한 4294968
function Get-LmIdleSec($tick64, $lastInput) {
    $d = [double]$tick64 - [double]$lastInput
    $m = (($d % 4294967296.0) + 4294967296.0) % 4294967296.0
    $s = [long][math]::Round($m / 1000.0, [MidpointRounding]::ToEven)
    if ($s -gt $IdleMax) { $s = $IdleMax }
    return $s
}

# WTS 값 → @(session_state, remote): 끊김 > 잠김 > 원격 > 활성
function Get-LmSession($state, $flags, $proto) {
    $remote = ($null -ne $proto -and [int]$proto -eq 2)
    if ($null -ne $state -and [int]$state -eq 4) { return @('disconnected', $remote) }
    if ($null -ne $flags -and [int]$flags -eq 0) { return @('locked', $remote) }
    if ($remote) { return @('remote', $true) }
    return @('active', $false)
}

# 원시 틱 + 확정 간격 + 카탈로그 판정 → pc_session(pc.sampler) 원시 레코드(파이썬 tick_record 와 같은 필드·값)
# $tick = @{ ts(UTC DateTime); off_min; fg_exe; fg_title; session_state; remote; idle_sec } · $cat = @{ fg_exe; app_id; app_class } 또는 $null
function New-LmTickRecord($tick, [int]$interval, $cat, [string]$docPath) {
    $fg = $null; $aid = $null; $ac = 'idle'
    if ($tick.fg_exe) {
        if ($null -ne $cat) { $fg = $cat.fg_exe; $aid = $cat.app_id; $ac = [string]$cat.app_class } else { $ac = 'other' }
        if (-not $ac) { $ac = 'other' }
    }
    $layer = 'L3'
    if ($ac -eq 'idle' -or $ac -eq 'system') { $layer = 'L2' }
    if ($interval -lt 1) { $interval = 1 }
    $ts = Format-LmUtc $tick.ts
    $rec = [ordered]@{
        ts_utc = $ts; ts_local_offset = (Format-LmOffset ([int]$tick.off_min)); ts_precision = 'exact'; observed_at = $ts
        confidence = 1.0; fg_exe = $fg; app_id = $aid; app_class = $ac; fg_title = [string]$tick.fg_title
        session_state = [string]$tick.session_state; layer = $layer; interval_sec = $interval
    }
    if ($null -ne $tick.idle_sec) { $rec['idle_sec'] = [long]$tick.idle_sec }
    if ($docPath) {
        $rec['fg_doc_path'] = $docPath
        $rec['fg_doc_name'] = @($docPath -split '[\\/]')[-1]
    }
    $flags = [ordered]@{}
    if ($tick.remote) { $flags['remote'] = $true }
    if ([int]$tick.off_min -eq 0) { $flags['utc_suspect'] = $true }
    if ($flags.Count -gt 0) { $rec['flags'] = $flags }
    return $rec
}

# 직전 틱의 확정 간격(초): 실제 간격이 명목 × 1.5 를 넘거나 0 이하면 명목(절전·멈춤 — 파이썬 감독 루프와 같다)
function Get-LmInterval([double]$dt, [int]$nominal) {
    if ($dt -le 0 -or $dt -gt ($nominal * $GapCap)) { return $nominal }
    return [int][math]::Round($dt, [MidpointRounding]::ToEven)
}

# ───────────────────────── Win32(Add-Type) ─────────────────────────
$script:Native = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class Lm27AgentNative {
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowTextLengthW(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [StructLayout(LayoutKind.Sequential)] struct LII { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LII l);
    [DllImport("kernel32.dll")] static extern ulong GetTickCount64();
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint a, bool i, uint pid);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool QueryFullProcessImageNameW(IntPtr h, uint f, StringBuilder s, ref uint n);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("wtsapi32.dll", SetLastError = true)]
    static extern bool WTSQuerySessionInformationW(IntPtr srv, int sid, int cls, out IntPtr buf, out uint bytes);
    [DllImport("wtsapi32.dll")] static extern void WTSFreeMemory(IntPtr p);
    public static long[] Foreground() {
        IntPtr h = GetForegroundWindow(); uint pid = 0;
        if (h != IntPtr.Zero) { GetWindowThreadProcessId(h, out pid); }
        return new long[] { h.ToInt64(), (long)pid };
    }
    public static string Title(long hwnd) {
        IntPtr h = new IntPtr(hwnd);
        if (h == IntPtr.Zero) return "";
        int n = GetWindowTextLengthW(h);
        if (n <= 0) return "";
        if (n > 1024) n = 1024;
        StringBuilder sb = new StringBuilder(n + 1);
        GetWindowTextW(h, sb, n + 1);
        return sb.ToString();
    }
    public static string Image(long pid) {
        if (pid <= 0) return "";
        IntPtr h = OpenProcess(0x1000, false, (uint)pid);
        if (h == IntPtr.Zero) return "";
        try { StringBuilder sb = new StringBuilder(1024); uint n = 1024; return QueryFullProcessImageNameW(h, 0, sb, ref n) ? sb.ToString() : ""; }
        finally { CloseHandle(h); }
    }
    public static ulong Tick64() { return GetTickCount64(); }
    public static long LastInput() { LII l = new LII(); l.cbSize = (uint)Marshal.SizeOf(l); return GetLastInputInfo(ref l) ? (long)l.dwTime : -1; }
    public static long[] Session() {
        long st = -99, fl = -99, pr = -99; IntPtr p; uint n;
        if (WTSQuerySessionInformationW(IntPtr.Zero, -1, 25, out p, out n) && p != IntPtr.Zero) {
            try { if (n >= 24 && Marshal.ReadInt32(p, 0) == 1) { st = Marshal.ReadInt32(p, 12); fl = Marshal.ReadInt32(p, 16); } }
            finally { WTSFreeMemory(p); }
        }
        if (WTSQuerySessionInformationW(IntPtr.Zero, -1, 16, out p, out n) && p != IntPtr.Zero) {
            try { if (n >= 2) { pr = (ushort)Marshal.ReadInt16(p, 0); } } finally { WTSFreeMemory(p); }
        }
        return new long[] { st, fl, pr };
    }
}
'@

function Initialize-LmNative {
    if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { return 'R-CLM' }
    try { Add-Type -TypeDefinition $script:Native -Language CSharp -ErrorAction Stop } catch { return 'R-CLM' }
    return $null
}

function Get-LmTick([datetime]$nowUtc) {
    $nowUtc = $nowUtc.AddTicks(-($nowUtc.Ticks % [TimeSpan]::TicksPerSecond))
    $fgv = [Lm27AgentNative]::Foreground()
    $title = ''; $exe = ''
    if ($fgv[0] -ne 0) {
        $title = [Lm27AgentNative]::Title($fgv[0])
        if ($title.Length -gt $TitleMax) { $title = $title.Substring(0, $TitleMax) }
        $img = [Lm27AgentNative]::Image($fgv[1])
        if ($img) { $exe = ([IO.Path]::GetFileName($img)).ToLowerInvariant() }
    }
    $last = [Lm27AgentNative]::LastInput()
    $idle = $null
    if ($last -ge 0) { $idle = Get-LmIdleSec ([Lm27AgentNative]::Tick64()) $last }
    $sv = [Lm27AgentNative]::Session()
    $st = $null; $fl = $null; $pr = $null
    if ($sv[0] -ne -99) { $st = $sv[0]; $fl = $sv[1] }
    if ($sv[2] -ne -99) { $pr = $sv[2] }
    $sess = Get-LmSession $st $fl $pr
    $off = [int][math]::Round([TimeZoneInfo]::Local.GetUtcOffset($nowUtc).TotalMinutes)
    return [pscustomobject]@{ ts = $nowUtc; off_min = $off; fg_exe = $exe; fg_title = $title; session_state = $sess[0];
                              remote = [bool]$sess[1]; idle_sec = $idle; ok_fg = $true; ok_idle = ($null -ne $idle);
                              ok_session = ($null -ne $st) }
}

# ───────────────────────── 사본 파이썬 도우미 ─────────────────────────
function Start-LmProc([string]$file, [string]$argline, [bool]$redirect) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $file
    $psi.Arguments = $argline
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $script:AgentDir
    if ($redirect) {
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = $script:Utf8
        $psi.StandardErrorEncoding = $script:Utf8
    }
    return [Diagnostics.Process]::Start($psi)
}

function Stop-LmTree([int]$procId) {
    try { & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /T /F /PID $procId 2>&1 | Out-Null } catch { }
}

# 사본 파이썬 한 번(입력 텍스트 → (종료 코드, stdout)). 실행이 막히면 $null
function Invoke-LmPy([string]$argline, [string]$inputText, [int]$waitMs) {
    try { $p = Start-LmProc $script:Py $argline $true } catch { return $null }
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()
    try {
        if ($inputText) {
            $b = $script:Utf8.GetBytes($inputText)
            $p.StandardInput.BaseStream.Write($b, 0, $b.Length)
        }
        $p.StandardInput.Close()
    } catch { }
    if (-not $p.WaitForExit($waitMs)) { Stop-LmTree $p.Id; return @(99, '') }
    $out = ''
    try { if ($outTask.Wait(5000)) { $out = $outTask.Result } } catch { }
    try { [void]$errTask.Wait(2000) } catch { }
    return @($p.ExitCode, $out)
}

function Get-LmLastJson([string]$text) {
    $lines = @($text -split "`n")
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        $ln = $lines[$i].Trim().TrimStart([char]0xFEFF)
        if (-not $ln.StartsWith('{')) { continue }
        try { return (ConvertFrom-Json -InputObject $ln) } catch { continue }
    }
    return $null
}

# 카탈로그 판정 캐시(실행 파일 이름 → @{fg_exe; app_id; app_class; solver}) — 판정은 사본 파이썬 lm27.catalog 한 곳
$script:Cat = @{}
function Update-LmCatalog($names) {
    $want = @($names | Where-Object { $_ -and -not $script:Cat.ContainsKey($_) } | Select-Object -Unique)
    if ($want.Count -eq 0) { return }
    $r = Invoke-LmPy ('-X utf8 -I -B "' + $script:Main + '" --install-id ' + $InstallId + ' --classify') (($want -join "`n") + "`n") 30000
    if ($null -eq $r -or $r[0] -ne 0) { return }
    foreach ($ln in ($r[1] -split "`n")) {
        $t = $ln.Trim()
        if (-not $t.StartsWith('{')) { continue }
        try { $o = ConvertFrom-Json -InputObject $t } catch { continue }
        $script:Cat[[string]$o.exe] = @{ fg_exe = $o.fg_exe; app_id = $o.app_id; app_class = [string]$o.app_class; solver = [bool]$o.solver }
    }
}

# 정제 파이프 한 번(--mode append): 레코드 목록 → 종료 코드(끊으면 99, 실행이 막히면 $null)
function Send-LmPipe([string]$kind, [string]$src, [string]$pc, $records, [int]$waitSec) {
    if ($null -eq $records -or $records.Count -eq 0) { return 0 }        # @(제네릭 List) 는 PS 5.1 에서 ArgumentException
    $sb = New-Object System.Text.StringBuilder
    foreach ($rec in $records) { [void]$sb.Append((ConvertTo-LmJson $rec)).Append("`n") }
    $argline = '-X utf8 -I -B "' + $script:Pipe + '" --kind ' + $kind + ' --src ' + $src + ' --pc ' + $pc + ' --mode append'
    $r = Invoke-LmPy $argline $sb.ToString() ($waitSec * 1000)
    $sb = $null
    if ($null -eq $r) { return $null }
    return $r[0]
}

# ───────────────────────── 문서 경로 색인(C15 — 제목 안 절대 경로 · Recent 바로가기) ─────────────────────────
$script:DocMap = @{}
$script:DocAt = [datetime]::MinValue
$script:KeepClasses = @('office', 'cad', 'sim', 'eda', 'ide', 'pdf', 'viewer')
function Get-LmDocPath([string]$title, [string]$appClass) {
    if (-not $title -or $script:KeepClasses -notcontains $appClass) { return $null }
    $pieces = @($title -split ' - ' | ForEach-Object { $_.Trim().Trim('*').Trim() })
    foreach ($p in $pieces) {
        if ($p -match '^(?:[A-Za-z]:\\|\\\\[^\\]+\\)' -and $p -match '\.[0-9A-Za-z]{1,8}$') { return $p }
    }
    if ($pieces.Count -eq 0 -or -not $pieces[0]) { return $null }
    if (([datetime]::UtcNow - $script:DocAt).TotalSeconds -ge 600) {
        $script:DocAt = [datetime]::UtcNow
        $script:DocMap = @{}
        try {
            $sh = New-Object -ComObject WScript.Shell
            $dir = [Environment]::GetFolderPath('Recent')
            $lnks = @(Get-ChildItem -LiteralPath $dir -Filter '*.lnk' -File -ErrorAction SilentlyContinue |
                    Sort-Object -Property LastWriteTimeUtc -Descending | Select-Object -First 200)
            foreach ($l in $lnks) {
                $t = ''
                try { $t = [string]$sh.CreateShortcut($l.FullName).TargetPath } catch { $t = '' }
                if (-not $t -or $t -match '://') { continue }
                $k = ([IO.Path]::GetFileName($t)).ToLowerInvariant()
                if ($k -and -not $script:DocMap.ContainsKey($k)) { $script:DocMap[$k] = $t }
            }
        } catch { }
    }
    $key = $pieces[0].ToLowerInvariant()
    if ($script:DocMap.ContainsKey($key)) { return $script:DocMap[$key] }
    return $null
}

# ───────────────────────── 운영 파일(원문 없음 — L-09 예외) ─────────────────────────
function Write-LmLog([string]$text) {
    try {
        $d = [datetime]::UtcNow.ToString('yyyyMMdd', $script:Inv)
        $logDir = Join-Path $script:AgentDir 'logs'
        if (-not [IO.Directory]::Exists($logDir)) { [void][IO.Directory]::CreateDirectory($logDir) }
        $logPath = Join-Path $logDir ('agent_' + $d + '.log')
        [IO.File]::AppendAllText($logPath, ((Format-LmUtc ([datetime]::UtcNow)) + ' ' + $text + "`n"), $script:Utf8)
    } catch { }
}

function Save-LmHeartbeat($hb) {
    $hbPath = Join-Path $script:AgentDir 'heartbeat.json'
    $tmpPath = $hbPath + '.' + $PID + '.part'
    try {
        [IO.File]::WriteAllBytes($tmpPath, $script:Utf8.GetBytes((ConvertTo-LmJson $hb) + "`n"))
        for ($i = 0; $i -lt 3; $i++) {
            try { Move-Item -LiteralPath $tmpPath -Destination $hbPath -Force; return } catch { Start-Sleep -Milliseconds 100 }
        }
    } catch { }
    try { Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue } catch { }
}

function Read-LmJsonFile([string]$path) {
    if (-not [IO.File]::Exists($path)) { return $null }
    try { return ([IO.File]::ReadAllText($path, $script:Utf8) | ConvertFrom-Json) } catch { return $null }
}

function Get-LmCfgNum($cfg, [string]$key, $default, $lo, $hi) {
    $v = $default
    if ($null -ne $cfg) {
        $p = $cfg.PSObject.Properties[$key]
        if ($null -ne $p -and ($p.Value -is [int] -or $p.Value -is [long] -or $p.Value -is [double])) { $v = $p.Value }
    }
    if ($v -lt $lo) { $v = $lo }
    if ($v -gt $hi) { $v = $hi }
    return $v
}

function Start-LmChild([string]$streams, [bool]$poll, [bool]$requested) {
    $a = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $script:PsDir 'harvest.ps1') +
         '" -InstallId ' + $InstallId + ' -Streams ' + $streams
    if ($poll) { $a += ' -Poll' }
    if ($requested) { $a += ' -Requested' }
    try { return (Start-LmProc $script:PsExe $a $false) } catch { return $null }
}

# ───────────────────────── 자기 시험(-TestSamples) ─────────────────────────
function Invoke-LmSelfTest([int]$n) {
    $res = [ordered]@{ impl = 'ps'; ok = $false; reason = $null; samples = 0; fg = 0; idle = 0; session = 0; pipe = $null }
    $why = Initialize-LmNative
    if ($why) { $res.reason = $why; return $res }
    $aj = Read-LmJsonFile (Join-Path $script:AgentDir 'agent.json')
    $pc = 'pc_0000000000000000'
    if ($null -ne $aj -and [string]$aj.pc_id -cmatch '^pcx?_[0-9a-f]{16}$') { $pc = [string]$aj.pc_id }
    $ticks = @()
    for ($i = 0; $i -lt [math]::Max(1, $n); $i++) {
        if ($i -gt 0) { Start-Sleep -Milliseconds $TestGapMs }
        try {
            $t = Get-LmTick ([datetime]::UtcNow)
            $ticks += $t
            $res.samples++
            if ($t.ok_fg) { $res.fg++ }
            if ($t.ok_idle) { $res.idle++ }
            if ($t.ok_session) { $res.session++ }
        } catch { $res.reason = 'R-CLM' }
    }
    Update-LmCatalog @($ticks | ForEach-Object { $_.fg_exe })
    $recs = @($ticks | ForEach-Object { New-LmTickRecord $_ 1 $script:Cat[$_.fg_exe] $null })
    $outPath = Join-Path $env:TEMP ('lm27_selftest_' + [guid]::NewGuid().ToString('N') + '.jsonl')
    $sb = New-Object System.Text.StringBuilder
    foreach ($rec in $recs) { [void]$sb.Append((ConvertTo-LmJson $rec)).Append("`n") }
    $argline = '-X utf8 -I -B "' + $script:Pipe + '" --kind pc_session --src pc.sampler --pc ' + $pc + ' --mode new --out "' + $outPath + '"'
    $r = Invoke-LmPy $argline $sb.ToString() 60000
    try { if ([IO.File]::Exists($outPath)) { Remove-Item -LiteralPath $outPath -Force } } catch { }
    if ($null -eq $r) { $res.reason = 'R-APPLOCKER'; return $res }
    $res.pipe = $r[0]
    $sm = Get-LmLastJson $r[1]
    $res.ok = ($null -eq $res.reason -and $res.samples -ge 1 -and $res.fg -gt 0 -and $res.idle -gt 0 -and $res.session -gt 0 -and
               $r[0] -eq 0 -and $null -ne $sm -and [bool]$sm.ok)
    if (-not $res.ok -and $null -eq $res.reason) { $res.reason = 'R-CLM' }
    return $res
}

# ───────────────────────── 감독 루프 ─────────────────────────
function Invoke-LmAgent {
    $why = Initialize-LmNative
    if ($why) { Write-LmLog ('start_failed ' + $why); return 3 }
    $created = $false
    $mutex = New-Object System.Threading.Mutex($false, "Local\LM27-$InstallId-agent", [ref]$created)
    if (-not $created) { $mutex.Dispose(); return 0 }
    try {
        $stopFlag = Join-Path $script:RunDir 'stop.flag'
        $nowFlag = Join-Path $script:RunDir 'harvest_now.flag'
        if ([IO.File]::Exists($stopFlag)) { return 0 }
        $chk = Invoke-LmPy ('-X utf8 -I -B "' + $script:Main + '" --install-id ' + $InstallId + ' --start-check') '' 60000
        $chkObj = $null
        if ($null -ne $chk -and $chk[0] -eq 0) { $chkObj = Get-LmLastJson $chk[1] }
        if ($null -eq $chkObj) { Write-LmLog 'start_failed R-APPLOCKER'; return 3 }
        $pc = [string]$chkObj.pc_id
        $rulesOk = [bool]$chkObj.rules_ok
        $aj = Read-LmJsonFile (Join-Path $script:AgentDir 'agent.json')
        $ver = ''
        if ($null -ne $aj) { $ver = [string]$aj.agent_ver }
        $cfg = Read-LmJsonFile (Join-Path $script:AgentDir 'agent_config.json')
        # 일정(틱·수확·teams.uia·폴링·플러시·설정 다시 읽기·보존 정리)은 단조 시계(초)로 잰다 — 벽시계가 뒤로 보정돼도
        # 그 폭만큼 표본·heartbeat 가 멈추지 않게(W1b). 벽시계(UtcNow)는 표본·heartbeat·로그의 시각 기록에만 쓴다.
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $cfgAtM = 0.0
        $old = Read-LmJsonFile (Join-Path $script:AgentDir 'heartbeat.json')
        $lastErr = ''; $lastErrAt = [datetime]::MinValue
        if ($null -ne $old -and [string]$old.install_id -eq $InstallId -and [int]$old.buffered -gt 0 -and [int]$old.pid -ne $PID) {
            $lastErr = 'unflushed_lost'; $lastErrAt = [datetime]::UtcNow
        }
        $started = [datetime]::UtcNow
        $buf = New-Object 'Collections.Generic.List[object]'
        $comp = New-Object 'Collections.Generic.List[object]'
        $pending = $null; $firstDone = $false; $flushWhy = ''; $lastFlushM = $null; $noKey = $false
        $samplesToday = 0; $day = ''
        $runs = @{}; $prevCpu = @{}
        $harvestChild = $null; $harvestStartedM = $null
        $done = Read-LmJsonFile (Join-Path $script:RunDir 'harvest_done.json')
        $hInfo = [ordered]@{ last_at = $null; last_rc = $null; next_at = $null }
        $nextHarvestM = $sw.Elapsed.TotalSeconds
        if ($null -ne $done -and [string]$done.install_id -eq $InstallId) {
            $hInfo.last_at = [string]$done.finished_at; $hInfo.last_rc = $done.rc
            try {
                $fin = [datetime]::Parse([string]$done.finished_at, $script:Inv, [Globalization.DateTimeStyles]'AdjustToUniversal, AssumeUniversal')
                $h = Get-LmCfgNum $cfg 'agent.harvestIntervalH' 6 1 48
                # 마지막 수확이 '미래'(시계 역행)여도 한 주기 안에 다시 돈다
                $left = [math]::Min([math]::Max(($fin.AddHours($h) - $started).TotalSeconds, 0.0), $h * 3600.0)
                $nextHarvestM = $sw.Elapsed.TotalSeconds + $left
            } catch { }
        }
        $teamsChild = $null; $teamsAtM = -1e9; $pollChild = $null; $pollAtM = -1e9
        $catAtM = -1e9
        $maintAtM = $sw.Elapsed.TotalSeconds + 120
        Write-LmLog ('start impl=ps rules=' + [int]$rulesOk)
        $nextTickM = $sw.Elapsed.TotalSeconds
        while (-not [IO.File]::Exists($stopFlag)) {
            $m = $sw.Elapsed.TotalSeconds
            if ($m -lt $nextTickM) { Start-Sleep -Milliseconds ([int][math]::Min(1000, ($nextTickM - $m) * 1000) + 1); continue }
            $now = [datetime]::UtcNow
            $interval = [int](Get-LmCfgNum $cfg 'agent.sampleIntervalSec' 60 5 600)
            if (($m - $cfgAtM) -ge 60) { $cfg = Read-LmJsonFile (Join-Path $script:AgentDir 'agent_config.json'); $cfgAtM = $m }
            if ($rulesOk) {
                try {
                    $tick = Get-LmTick $now
                    if ($null -eq $pending -and -not $firstDone) {
                        $buf.Add(@{ tick = $tick; interval = $interval }); $flushWhy = 'first'
                    } else {
                        if ($null -ne $pending) {
                            $dt = ($tick.ts - $pending.ts).TotalSeconds
                            $buf.Add(@{ tick = $pending; interval = (Get-LmInterval $dt $interval) })
                            if ($dt -gt $interval * $GapCap) { $flushWhy = 'gap' }
                            if ($tick.session_state -ne $pending.session_state -and ($tick.session_state -eq 'locked' -or $tick.session_state -eq 'disconnected')) {
                                if (-not $flushWhy) { $flushWhy = 'session' }
                            }
                        }
                        $pending = $tick
                    }
                    $d = $tick.ts.AddMinutes($tick.off_min).ToString('yyyy-MM-dd', $script:Inv)
                    if ($d -ne $day) { $day = $d; $samplesToday = 0 }
                    $samplesToday++
                    # 연산 구간(솔버 CPU — 판정은 카탈로그 캐시, 실행 중 프로세스 이름은 10분마다 한꺼번에 판정)
                    $procs = @(Get-Process -ErrorAction SilentlyContinue)
                    if (($m - $catAtM) -ge 600) {
                        $catAtM = $m
                        Update-LmCatalog @($procs | ForEach-Object { ([string]$_.ProcessName).ToLowerInvariant() + '.exe' })
                    }
                    $cpu = @{}
                    foreach ($p in $procs) {
                        $nm = ([string]$p.ProcessName).ToLowerInvariant() + '.exe'
                        if (-not $script:Cat.ContainsKey($nm)) { continue }
                        if (-not $script:Cat[$nm].solver -or -not $script:Cat[$nm].app_id) { continue }
                        try { $cpu[[int]$p.Id] = @($nm, [double]$p.TotalProcessorTime.TotalSeconds) } catch { }
                    }
                    $per = @{}
                    foreach ($k in $cpu.Keys) {
                        $pv = $prevCpu[$k]
                        if ($null -ne $pv -and $pv[0] -eq $cpu[$k][0] -and $cpu[$k][1] -ge $pv[1]) {
                            $dts = $m - $pv[3]
                            if ($dts -gt 0) {
                                $aid = $script:Cat[$cpu[$k][0]].app_id
                                if (-not $per.ContainsKey($aid)) { $per[$aid] = @(0.0, $cpu[$k][0], $pv[2], $dts) }
                                $per[$aid][0] += ($cpu[$k][1] - $pv[1])
                            }
                        }
                    }
                    $prevCpu = @{}
                    foreach ($k in $cpu.Keys) { $prevCpu[$k] = @($cpu[$k][0], $cpu[$k][1], $now, $m) }
                    $thr = [double](Get-LmCfgNum $cfg 'pc.compute.cpuCoreThreshold' 0.5 0.05 256.0)
                    $need = [int](Get-LmCfgNum $cfg 'pc.compute.consecutiveTicks' 3 1 100)
                    foreach ($aid in @($runs.Keys)) {
                        if (-not $per.ContainsKey($aid) -or ($per[$aid][0] / $per[$aid][3]) -lt $thr) {
                            if ($runs[$aid].ticks -ge $need) { $comp.Add((New-LmComputeRecord $runs[$aid] $tick.off_min $now $true)) }
                            $runs.Remove($aid)
                        }
                    }
                    foreach ($aid in @($per.Keys)) {
                        if (($per[$aid][0] / $per[$aid][3]) -lt $thr) { continue }
                        if (-not $runs.ContainsKey($aid)) { $runs[$aid] = @{ app_id = $aid; exe = $per[$aid][1]; start = $per[$aid][2]; last = $now; ticks = 0; core = 0.0; wall = 0.0 } }
                        $runs[$aid].last = $now; $runs[$aid].ticks++; $runs[$aid].core += $per[$aid][0]; $runs[$aid].wall += $per[$aid][3]
                    }
                    # 플러시
                    $age = $null
                    if ($null -ne $lastFlushM) { $age = $m - $lastFlushM }
                    $due = (-not $firstDone) -or $flushWhy -or ($null -eq $age) -or ($age -ge (Get-LmCfgNum $cfg 'agent.flushIntervalSec' 300 30 3600)) -or
                           ($buf.Count -ge (Get-LmCfgNum $cfg 'agent.flushMaxRows' 120 1 10000))
                    if ($due -and ($buf.Count -gt 0 -or $comp.Count -gt 0)) {
                        $flushOk = Invoke-LmFlush $buf $comp $runs $need $pc $cfg $tick.off_min $now $false
                        $noKey = ($flushOk -eq 6)
                        if ($flushOk -eq 0 -or $flushOk -eq 2 -or $flushOk -eq 6) {
                            $buf.Clear(); $comp.Clear(); $firstDone = $true; $flushWhy = ''; $lastFlushM = $m
                        } else {
                            $lastErr = 'R-TRANSPORT'; $lastErrAt = $now
                            $cap = [int](Get-LmCfgNum $cfg 'agent.flushMaxRows' 120 1 10000) * 20
                            if ($buf.Count -gt $cap) { $buf.RemoveRange(0, $buf.Count - $cap) }
                        }
                    }
                    # 자식: 수확(별도 프로세스) · teams.uia · 열린 문서 폴링(세션이 잠기면 쉰다)
                    if ($null -ne $harvestChild -and $harvestChild.HasExited) {
                        $dn = Read-LmJsonFile (Join-Path $script:RunDir 'harvest_done.json')
                        if ($null -ne $dn) { $hInfo.last_at = [string]$dn.finished_at; $hInfo.last_rc = $dn.rc }
                        $harvestChild = $null
                    } elseif ($null -ne $harvestChild -and ($m - $harvestStartedM) -gt $HarvestMaxSec) {
                        Stop-LmTree $harvestChild.Id; $harvestChild = $null
                    }
                    $req = [IO.File]::Exists($nowFlag)
                    if ($null -eq $harvestChild -and ($req -or $m -ge $nextHarvestM)) {
                        $harvestChild = Start-LmChild $HarvestStreams $false $req
                        $harvestStartedM = $m
                        $nextHarvestM = $m + 3600.0 * (Get-LmCfgNum $cfg 'agent.harvestIntervalH' 6 1 48)
                        if ($req -and $null -ne $harvestChild) { try { Remove-Item -LiteralPath $nowFlag -Force } catch { } }
                    }
                    $hInfo.next_at = Format-LmUtc ($now.AddSeconds($nextHarvestM - $m))
                    if ($tick.session_state -ne 'locked' -and $tick.session_state -ne 'disconnected') {
                        if (($null -eq $teamsChild -or $teamsChild.HasExited) -and ($m - $teamsAtM) -ge (Get-LmCfgNum $cfg 'teams.uia.intervalSec' 300 120 300)) {
                            $teamsChild = Start-LmChild 'teams/teams.uia' $false $false; $teamsAtM = $m
                        }
                        if (($null -eq $pollChild -or $pollChild.HasExited) -and ($m - $pollAtM) -ge (Get-LmCfgNum $cfg 'agent.filePoll.intervalSec' 300 30 3600)) {
                            $pollChild = Start-LmChild 'pc_file/pc.files' $true $false; $pollAtM = $m
                        }
                    }
                    if ($m -ge $maintAtM) {
                        $maintAtM = $m + $MaintEverySec
                        [void](Invoke-LmPy ('-X utf8 -I -B "' + $script:Main + '" --install-id ' + $InstallId + ' --maintain') '' 120000)
                    }
                } catch { $lastErr = $_.Exception.GetType().Name; $lastErrAt = $now; Write-LmLog ('tick_error ' + $lastErr) }
            }
            $le = ''
            if (-not $rulesOk) { $le = 'R-RULESMISMATCH' } elseif ($noKey) { $le = 'R-NOKEY' } elseif ($lastErr -and ($now - $lastErrAt).TotalSeconds -le 3600) { $le = $lastErr }
            $nb = $buf.Count
            if ($null -ne $pending) { $nb++ }
            Save-LmHeartbeat ([ordered]@{ schema = 'lm27.hb/1'; install_id = $InstallId; pc_id = $pc; pid = $PID; agent_ver = $ver; impl = 'ps';
                started_at = (Format-LmUtc $started); last_tick = (Format-LmUtc $now); interval_s = $interval; samples_today = $samplesToday;
                harvest = $hInfo; last_error = $le; buffered = $nb; state = $(if ($rulesOk) { 'running' } else { 'rules_mismatch' }) })
            $nextTickM += $interval
            $m = $sw.Elapsed.TotalSeconds
            if ($nextTickM -le $m) { $nextTickM = $m + $interval }      # 절전·멈춤 뒤 — 지금부터 다시 센다
        }
        # 종료: 살아 있는 자식(수확·teams.uia·폴링)을 끈다 — 정지·제거 뒤 고아 수집 0(수확은 흐름별 커서로 다음 기동이 이어 한다)
        foreach ($ch in @($harvestChild, $teamsChild, $pollChild)) {
            if ($null -ne $ch) { try { if (-not $ch.HasExited) { Stop-LmTree $ch.Id } } catch { } }
        }
        $harvestChild = $null; $teamsChild = $null; $pollChild = $null
        # 종료: 마지막 틱 확정 → 플러시(진행 중 연산 구간은 확정판) → heartbeat
        $now = [datetime]::UtcNow
        $interval = [int](Get-LmCfgNum $cfg 'agent.sampleIntervalSec' 60 5 600)
        if ($rulesOk) {
            if ($null -ne $pending) {
                $dt = ($now - $pending.ts).TotalSeconds
                if ($dt -lt 1) { $dt = 1 }
                if ($dt -gt $interval) { $dt = $interval }
                $buf.Add(@{ tick = $pending; interval = [int][math]::Round($dt) })
                $off = $pending.off_min
                $pending = $null
            } else { $off = 0 }
            [void](Invoke-LmFlush $buf $comp $runs (Get-LmCfgNum $cfg 'pc.compute.consecutiveTicks' 3 1 100) $pc $cfg $off $now $true)
        }
        Save-LmHeartbeat ([ordered]@{ schema = 'lm27.hb/1'; install_id = $InstallId; pc_id = $pc; pid = $PID; agent_ver = $ver; impl = 'ps';
            started_at = (Format-LmUtc $started); last_tick = (Format-LmUtc $now); interval_s = $interval; samples_today = $samplesToday;
            harvest = $hInfo; last_error = ''; buffered = 0; state = 'stopped' })
        Write-LmLog 'stop'
        return 0
    } finally {
        try { $mutex.Dispose() } catch { }
    }
}

# 연산 구간 → pc_compute(pc.compute) 원시 레코드(파이썬 compute_record 와 같은 필드)
function New-LmComputeRecord($run, [int]$off, [datetime]$observed, [bool]$final) {
    $flags = [ordered]@{ solver = $true }
    if (-not $final) { $flags['end_uncertain'] = $true }
    $cores = 0.0
    if ($run.wall -gt 0) { $cores = $run.core / $run.wall }
    if ($cores -gt 256) { $cores = 256.0 }
    $end = $run.last
    if ($end -lt $run.start) { $end = $run.start }
    $fx = $null
    if ($script:Cat.ContainsKey($run.exe)) { $fx = $script:Cat[$run.exe].fg_exe }
    return [ordered]@{ ts_utc = (Format-LmUtc $run.start); ts_end = (Format-LmUtc $end); ts_local_offset = (Format-LmOffset $off);
                       ts_precision = 'exact'; observed_at = (Format-LmUtc $observed); confidence = 1.0; fg_exe = $fx; app_id = $run.app_id;
                       cpu_core = [math]::Round($cores, 3); flags = $flags }
}

# 버퍼 → 정제 파이프(카탈로그 판정을 채워 레코드로). 반환 = pc.sampler 파이프 종료 코드(또는 $null)
function Invoke-LmFlush($buf, $comp, $runs, [int]$need, [string]$pc, $cfg, [int]$off, [datetime]$now, [bool]$final) {
    Update-LmCatalog @($buf | ForEach-Object { $_.tick.fg_exe })
    $recs = New-Object 'Collections.Generic.List[object]'
    foreach ($b in $buf) {
        $c = $null
        if ($b.tick.fg_exe -and $script:Cat.ContainsKey($b.tick.fg_exe)) { $c = $script:Cat[$b.tick.fg_exe] }
        $ac = 'other'
        if ($null -ne $c) { $ac = [string]$c.app_class }
        $doc = $null
        if ($b.tick.fg_title) { try { $doc = Get-LmDocPath $b.tick.fg_title $ac } catch { $doc = $null } }
        $recs.Add((New-LmTickRecord $b.tick ([int]$b.interval) $c $doc))
    }
    $wait = [int](Get-LmCfgNum $cfg 'privacy.pipe.waitSec' 120 30 1800)
    $code = Send-LmPipe 'pc_session' 'pc.sampler' $pc $recs $wait
    $cr = New-Object 'Collections.Generic.List[object]'
    foreach ($x in $comp) { $cr.Add($x) }
    foreach ($aid in @($runs.Keys)) {
        if ($runs[$aid].ticks -ge $need) { $cr.Add((New-LmComputeRecord $runs[$aid] $off $now $final)) }
    }
    if ($final) { $runs.Clear() }
    [void](Send-LmPipe 'pc_compute' 'pc.compute' $pc $cr $wait)
    $recs = $null
    return $code
}

# ───────────────────────── 시작 ─────────────────────────
if ($InstallId -cnotmatch '^[0-9a-f]{32}$') { exit 5 }
if ($TestSamples -gt 0) {
    $st = $null
    try { $st = Invoke-LmSelfTest $TestSamples } catch { $st = [ordered]@{ impl = 'ps'; ok = $false; reason = 'R-CLM' } }
    $b = $script:Utf8.GetBytes((ConvertTo-LmJson ([ordered]@{ _selftest = $st })) + "`n")
    $o = [Console]::OpenStandardOutput()
    $o.Write($b, 0, $b.Length)
    $o.Flush()
    if ($st.ok) { exit 0 }
    exit 3
}
$code = 3
try { $code = Invoke-LmAgent } catch { Write-LmLog ('agent_error ' + $_.Exception.GetType().Name); $code = 3 }
exit $code
