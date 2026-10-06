<#
.SYNOPSIS
  LM27 능력 탐침 — P-ENV · P-OL-INST · P-OL-COM · P-IDX · P-EDGE · P-TEAMS · P-PC(계약 §6.7 · C §4 · CM §14 · CT §12 · CP §1.3 · §12.1).

.DESCRIPTION
  수집 앞에 매번(전경) 돈다. 내용은 0바이트 — stdout 한 줄 JSON 에 숫자·열거·사유 코드만 낸다(계약 §6.7).
  디스크에 아무것도 쓰지 않는다(L-09). 진단·안내는 stderr 한국어 한 줄(건수·사유만, 원문 없음).

  호출(연결자 = lm27.collect.probe — 계약 §7.3):
    powershell -NoProfile -ExecutionPolicy Bypass -File collect\Invoke-CapabilityProbe.ps1 [-Pc <pc_id>]
               [-Only P-ENV,P-OL-INST,P-OL-COM,P-IDX,P-EDGE,P-TEAMS,P-PC] [-TestNow <ISO 8601>]
    stdin(선택, 한 줄): {"_in": {"cursor": null, "cfg": {"probe.budgetSec": 60, "probe.subfolderRatio": 0.3,
        "probe.ostStaleH": 72, "mail.com.watchdogSec": 20, "mail.com.protectedReadSec": 2,
        "teams.uia.windowWatchdogSec": 15, "teams.uia.maxElements": 4000, "teams.timeRegex": "", "pc.git.exe": ""}}}
    stdin 이 리디렉션되지 않았거나 _in 이 없으면 위 기본값(설정 레지스트리 기본값과 같음)으로 돈다.
    설정 값은 명령줄에 싣지 않는다(프로세스 목록 노출 방지). -Pc 는 공통 인자 자리(출력하지 않음).

  출력(stdout 한 줄, schema lm27.probe/1):
    {schema, now_utc, elapsed_ms, budget_sec, budget_hit, synthetic, groups{P-*: done|skipped|budget|error},
     warnings[stub_env_set · fake_unreadable], stub_env[주입 변수 이름], cfg_used{수치 키: 값},
     caps{<pc.json capabilities 키>: {ok: true|false|null, status: ok|fail|transport_fail|unknown,
                                      reasons: [R-*], value: {숫자·열거·불리언·날짜}, sig: 12자 16진}}}
    caps 키: env · mail.com · cal.com · mail.index · cal.index · edge_cdp_policy · teams.uia ·
             pc.sampler · pc.events · pc.recent · pc.mru · pc.git
    status 는 lm27.bundle.pcreg.record_probe 의 history.status 로 그대로 쓴다. 경고 사유(R-SUBFOLDER·R-STALE·
    R-OMG(A단은 됨)·R-OFFICE·R-TZ·R-MRUEMPTY 등)는 status ok 와 함께 올 수 있다. sig = 그 키의 구조 사실(설치·정책·
    권한)만으로 만든 해시 — 건수·시각이 바뀌어도 같고 환경이 바뀌면 달라진다(verdict 판정 창의 probe_sig, 계약 §6.4).
  종료 코드: 0 = 결과 출력(예산 소진도 0 + budget_hit) · 3 = 탐침 자체 실패(fatal 에 예외 유형만).

  워치독: COM(P-OL-COM)과 UIA(P-TEAMS)는 자식 PowerShell 에서 돈다. 자식은 PID 를 먼저 내보내고 진행 줄을 낸다.
  부모는 무진전 mail.com.watchdogSec(UIA 는 teams.uia.windowWatchdogSec) · 보호 속성 시험 읽기 mail.com.protectedReadSec ·
  전체 예산 probe.budgetSec 중 먼저 닿는 것에서 자식을 PID 로 바로 끝낸다(남으면 taskkill /T /F, Stop-Job 금지 — CM §5.2).
  워치독은 자식을 띄운 순간부터 센다(자식 기동 시간 포함, PID 줄은 진전으로 치지 않는다).
  New-Object Outlook.Application 은 부르지 않는다 — 떠 있는 Outlook 에 GetActiveObject 로 붙기만 한다(C §4.3).
  보호 속성 시험 읽기는 경고가 없다고 판단될 때만(정책·백신 상태) 1회, 결과는 ok/blocked/timeout 뿐이다.

  시험 주입(계약 §11.3): LM_PROBE_FAKE=<json>(이 탐침의 사실 묶음 — 계약 §11.3 등재 CR), LM_OUTLOOK_SELFTEST=N[,선택…]
  (Outlook·COM 가짜 — 앞 정수만 쓰고, 값이 있으면 실물 COM 을 건드리지 않는다), LM_INDEX_FAKE=<json>(색인 행 — WP-05
  synth 형식), -TestNow. LM_PROBE_FAKE 가 있으면 실제 환경을
  읽지 않는다(언어 모드만 fake 에 없을 때 이 세션 값). 주입 변수가 프로세스·사용자·컴퓨터 환경에 있으면 warnings 에
  stub_env_set(배포 설정에 시험 주입이 남은 것 — 계약 §11.3).
#>
[CmdletBinding()]
param(
    [string]$Pc = '',
    [string]$Only = '',
    [string]$TestNow = '',
    [ValidateSet('', 'com', 'uia')]
    [string]$Child = ''
)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }

# ───────────────────────────── 상수 ─────────────────────────────
$SCHEMA = 'lm27.probe/1'
$GROUPS = @('P-ENV', 'P-OL-INST', 'P-OL-COM', 'P-IDX', 'P-EDGE', 'P-TEAMS', 'P-PC')
$INJECT_NAMES = @('LM_OUTLOOK_SELFTEST', 'LM_INDEX_FAKE', 'LM_OWA_FAKE', 'LM_TEAMSWEB_FAKE', 'LM_COPILOT_STUB',
    'LM_NO_BROWSER', 'LM_PROBE_FAKE')
$LANG_MODES = @('FullLanguage', 'ConstrainedLanguage', 'RestrictedLanguage', 'NoLanguage')
$EP_SCOPES = @('MachinePolicy', 'UserPolicy', 'Process', 'CurrentUser', 'LocalMachine')
$EP_VALUES = @('Restricted', 'AllSigned', 'RemoteSigned', 'Unrestricted', 'Bypass', 'Undefined', 'Default')
$CHANNELS = [ordered]@{
    system    = 'System'
    security  = 'Security'
    diag_perf = 'Microsoft-Windows-Diagnostics-Performance/Operational'
    ts_lsm    = 'Microsoft-Windows-TerminalServices-LocalSessionManager/Operational'
}
$CH_STATES = @('ok', 'none', 'unauthorized', 'error')
$IDX_SERVICE = @('running', 'stopped', 'disabled', 'missing', 'unknown')
$OMG_POLICIES = @('auto', 'always', 'never')
$AV_STATES = @('valid', 'invalid', 'unknown')
$CTYPES_STATES = @('ok', 'fail', 'blocked', 'missing')
$GIT_SRC = @('cfg', 'path', 'candidate')
$RX_VER = '^\d{1,6}(\.\d{1,6}){0,3}$'
$RX_TZ = '^[A-Za-z][A-Za-z0-9 .()+\-]{0,63}$'
$RX_HR = '^0x[0-9A-F]{8}$'
$RX_TYPE = '^[A-Za-z][A-Za-z0-9_.]{0,79}$'
$RX_GENERIC_TIME = '(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)'
$MK_E_UNAVAILABLE = '0x800401E3'
$RPC_E_CALL_REJECTED = '0x8001010A'
$CFG_DEFAULT = [ordered]@{
    'probe.budgetSec'             = 60
    'probe.subfolderRatio'        = 0.3
    'probe.ostStaleH'             = 72
    'mail.com.watchdogSec'        = 20
    'mail.com.protectedReadSec'   = 2
    'teams.uia.windowWatchdogSec' = 15
    'teams.uia.maxElements'       = 4000
    'teams.timeRegex'             = ''
    'pc.git.exe'                  = ''
}
$CFG_NUMERIC = @('probe.budgetSec', 'probe.subfolderRatio', 'probe.ostStaleH', 'mail.com.watchdogSec',
    'mail.com.protectedReadSec', 'teams.uia.windowWatchdogSec', 'teams.uia.maxElements')
$OL_KEYS = @('classic', 'version', 'c2r', 'msi', 'new_installed', 'use_new', 'new_running', 'migration_policy', 'profiles',
    'profile_name', 'com_registered', 'com_server_match', 'running', 'ol_elevated', 'cached_policy', 'sync_months', 'omg_policy',
    'av_state')
$STORE_TYPES = @('primary', 'delegate', 'public', 'non_exchange', 'additional')   # Outlook OlExchangeStoreType 0~4
$ENV_KEYS = @('language_mode', 'exec_policy', 'elevated', 'tz_offset_min', 'tz_id', 'domain_joined', 'aad_joined', 'ctypes',
    'addtype', 'ps_version', 'os_build')
$EDGE_KEYS_F = @('installed', 'version', 'remote_debugging', 'devtools', 'profile')
$TEAMS_KEYS = @('new_installed', 'new_version', 'classic_installed', 'classic_version', 'processes')
$PC_KEYS = @('events', 'event_errors', 'recent_policy', 'lnk', 'mru', 'office_versions', 'git', 'git_src')
$IDX_KEYS = @('service', 'connect', 'policy_outlook', 'catalog_status', 'paused_reason', 'ext_props', 'mail', 'cal')
$OFFICE_APPS = @('Word', 'Excel', 'PowerPoint', 'OneNote', 'Visio', 'Access', 'Publisher', 'Project')
$PKG_ROOT = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'

$script:T0 = [DateTime]::UtcNow
$script:Deadline = $script:T0.AddSeconds(60)
$script:BudgetHit = $false
$script:ChildRc = 0
$script:NativeState = $null

# ───────────────────────────── 공용 ─────────────────────────────
function P($o, [string]$Name) {
    # PSCustomObject·hashtable 모두 같은 방식으로(이름에 점이 있어도 됨). 없으면 $null.
    if ($null -eq $o) { return $null }
    return $o.$Name
}

function B($v) { return ($v -eq $true) }

function S-Int($v) {
    if ($null -eq $v -or $v -is [bool] -or $v -is [string]) { return $null }
    try { return [long]$v } catch { return $null }
}

function S-Num($v) {
    if ($null -eq $v -or $v -is [bool] -or $v -is [string]) { return $null }
    try { return ([double]([long]([double]$v * 1000))) / 1000 } catch { return $null }
}

function S-Bool($v) { if ($v -is [bool]) { return $v }; return $null }

function S-Rx($v, [string]$Rx) { if ($v -is [string] -and $v -cmatch $Rx) { return $v }; return $null }

function S-Enum($v, $Allowed) { if ($v -is [string] -and $Allowed -ccontains $v) { return $v }; return $null }

function Get-Inner($ex) {
    $x = $ex
    while ($null -ne $x -and $null -ne $x.InnerException) { $x = $x.InnerException }
    return $x
}

function Get-TypeName($ex) {
    try { return [string](Get-Inner $ex).GetType().Name } catch { return 'Exception' }
}

function Get-HResult($ex) {
    try { return ('0x{0:X8}' -f [int](Get-Inner $ex).HResult) } catch { return $null }
}

function Format-Utc($d) {
    if ($null -eq $d) { return $null }
    try {
        $u = $d
        if ($d.Kind -ne [DateTimeKind]::Utc) { $u = $d.ToUniversalTime() }
        return $u.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
    } catch { return $null }
}

function Parse-Utc($v, [bool]$AssumeLocal = $false) {
    # ISO·'yyyy-MM-dd HH:mm' 문자열 또는 DateTime → UTC DateTime. 실패하면 $null.
    if ($null -eq $v) { return $null }
    if ($v -is [datetime]) {
        if ($v.Kind -eq [DateTimeKind]::Utc) { return $v }
        if ($v.Kind -eq [DateTimeKind]::Unspecified -and -not $AssumeLocal) { return [DateTime]::SpecifyKind($v, [DateTimeKind]::Utc) }
        return $v.ToUniversalTime()
    }
    $s = [string]$v
    if (-not $s) { return $null }
    $style = [Globalization.DateTimeStyles]::AssumeUniversal
    if ($AssumeLocal) { $style = [Globalization.DateTimeStyles]::AssumeLocal }
    try { return ([DateTimeOffset]::Parse($s, [Globalization.CultureInfo]::InvariantCulture, $style)).UtcDateTime } catch { }
    try { return ([datetime]::Parse($s)).ToUniversalTime() } catch { return $null }
}

function Get-NowUtc {
    if ($null -ne $script:TestNowUtc) { return $script:TestNowUtc }
    return [DateTime]::UtcNow
}

function Get-Left { return ($script:Deadline - [DateTime]::UtcNow).TotalSeconds }

function Get-Fnv([string]$s) {
    # FNV-1a 32비트 두 벌(기저가 다름) → 16진 12자. 순수 PowerShell 산술(제한 언어 모드에서도 같은 값).
    [long]$h1 = 2166136261
    [long]$h2 = 3166136261
    foreach ($ch in $s.ToCharArray()) {
        $c = [long][int]$ch
        $h1 = (($h1 -bxor $c) * 16777619) % 4294967296
        $h2 = (($h2 -bxor ($c + 131)) * 16777619) % 4294967296
    }
    return ('{0:x8}{1:x8}' -f $h1, $h2).Substring(0, 12)
}

function Get-Sig($Parts) {
    $t = @()
    foreach ($p in @($Parts)) {
        if ($null -eq $p) { $t += '~' }
        elseif ($p -is [bool]) { if ($p) { $t += '1' } else { $t += '0' } }
        else { $t += [string]$p }
    }
    return (Get-Fnv ($t -join '|'))
}

function To-Json($obj) {
    $j = ConvertTo-Json -InputObject $obj -Depth 12 -Compress
    try { $j = [regex]::Replace($j, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value }) } catch { }
    return $j
}

function Write-Line([string]$s) {
    try { [Console]::Out.WriteLine($s); [Console]::Out.Flush() } catch { Write-Output $s }
}

function Write-Diag([string]$s) {
    try { [Console]::Error.WriteLine($s); [Console]::Error.Flush() } catch { }
}

function Read-JsonFile([string]$Path) {
    if (-not $Path) { return $null }
    try {
        $t = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop
        return (ConvertFrom-Json -InputObject $t)
    } catch { return $null }
}

function Read-StdinKey([string]$Key) {
    # 연결자가 stdin 에 쓴 제어 줄({"_in": …} 또는 자식의 {"_child": …})을 찾는다. 리디렉션이 없으면 $null(기본값으로).
    $txt = $null
    try {
        if (-not [Console]::IsInputRedirected) { return $null }
        $st = [Console]::OpenStandardInput()
        $ms = New-Object System.IO.MemoryStream
        $st.CopyTo($ms)
        $txt = [System.Text.Encoding]::UTF8.GetString($ms.ToArray())
    } catch { return $null }
    if (-not $txt) { return $null }
    foreach ($ln in ($txt -split "`n")) {
        $t = $ln.Trim().TrimStart([char]0xFEFF)
        if (-not $t.StartsWith('{')) { continue }
        $o = $null
        try { $o = ConvertFrom-Json -InputObject $t } catch { continue }
        $v = P $o $Key
        if ($null -ne $v) { return $v }
    }
    return $null
}

function Get-EnvVar([string]$Name) {
    try { return [string](Get-Item -LiteralPath ('Env:' + $Name) -ErrorAction Stop).Value } catch { return '' }
}

function Get-RegValue([string]$Path, [string]$Name) {
    try { return (Get-ItemProperty -LiteralPath $Path -Name $Name -ErrorAction Stop).$Name } catch { return $null }
}

function Get-RegDefault([string]$Path) {
    try { return (Get-ItemProperty -LiteralPath $Path -ErrorAction Stop).'(default)' } catch { return $null }
}

function Get-RegSubkeys([string]$Path) {
    try { return @(Get-ChildItem -LiteralPath $Path -ErrorAction Stop | ForEach-Object { [string]$_.PSChildName }) } catch { return @() }
}

function Get-RegValueNames([string]$Path) {
    try { return @((Get-Item -LiteralPath $Path -ErrorAction Stop).Property) } catch { return @() }
}

function Get-ExePath($Raw) {
    # 레지스트리의 실행 파일 문자열("…\X.EXE" /automation 등) → 경로만. 메모리에서만 쓰고 출력하지 않는다.
    if ($null -eq $Raw) { return $null }
    $s = [string]$Raw
    if (-not $s) { return $null }
    $s = $s.Trim()
    try { $s = [Environment]::ExpandEnvironmentVariables($s) } catch { }
    if ($s.StartsWith('"')) {
        $e = $s.IndexOf('"', 1)
        if ($e -gt 1) { return $s.Substring(1, $e - 1) }
        return $s.Trim('"')
    }
    $i = $s.ToLowerInvariant().IndexOf('.exe')
    if ($i -ge 0) { return $s.Substring(0, $i + 4) }
    return $s
}

function Get-FileVersion([string]$Path) {
    try { return [string](Get-Item -LiteralPath $Path -ErrorAction Stop).VersionInfo.ProductVersion } catch { return $null }
}

function Copy-Facts($Src, $Keys) {
    $h = [ordered]@{}
    foreach ($k in $Keys) { $h[$k] = P $Src $k }
    return $h
}

# ───────────────────────────── 자식 프로세스(워치독) ─────────────────────────────
function Start-ProbeChild([string]$Mode, $Payload) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = Join-Path $PSHOME 'powershell.exe'
    $psi.Arguments = ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Child {1}' -f $PSCommandPath, $Mode)
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $p = [System.Diagnostics.Process]::Start($psi)
    try {
        $p.StandardInput.WriteLine((To-Json ([ordered]@{ _child = $Payload })))
        $p.StandardInput.Close()
    } catch { }
    return $p
}

function Stop-ProbeChild($Proc, [bool]$Gentle) {
    # 자식(손자 없음)은 PID 로 바로 끝낸다(CM §5.2 '그 프로세스를 직접 종료'). 남으면 taskkill /T /F 로 트리째.
    if ($null -eq $Proc) { return }
    try { if ($Gentle -and $Proc.WaitForExit(2000)) { return } } catch { }
    try { if (-not $Proc.HasExited) { $Proc.Kill() } } catch { }
    try { if ($Proc.WaitForExit(3000)) { return } } catch { }
    try {
        $tk = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        $null = & $tk /T /F /PID $Proc.Id 2>$null
        $null = $Proc.WaitForExit(3000)
    } catch { }
}

function Wait-ProbeChild($Proc, [double]$IdleSec, [datetime]$HardUntil, $PhaseSec) {
    # 자식 stdout 줄(JSON 사건)을 모은다. 무진전 IdleSec · 단계 시간(PhaseSec[사건]) · 전체 HardUntil 중 먼저 닿으면 끝낸다.
    $evs = @()
    $state = 'crash'
    $last = [DateTime]::UtcNow
    $phaseUntil = [DateTime]::MaxValue
    $task = $null
    try { $task = $Proc.StandardOutput.ReadLineAsync() } catch { $task = $null }
    while ($null -ne $task) {
        $got = $false
        try { $got = $task.Wait(100) } catch { $task = $null; break }
        if ($got) {
            $line = $task.Result
            if ($null -eq $line) { $task = $null; break }
            $ev = $null
            try { $ev = ConvertFrom-Json -InputObject $line } catch { $ev = $null }
            if ($null -ne $ev) {
                $evs += , $ev
                $name = [string](P $ev 'ev')
                # 워치독은 자식을 띄운 순간부터 센다 — PID 줄은 기동 알림이지 진전이 아니다(자식 기동 시간이 워치독에 얹히지 않게)
                if ($name -ne 'pid') { $last = [DateTime]::UtcNow }
                $phaseUntil = [DateTime]::MaxValue
                if ($null -ne $PhaseSec -and $PhaseSec.Contains($name)) { $phaseUntil = $last.AddSeconds([double]$PhaseSec[$name]) }
                if ($name -eq 'done') { $state = 'done'; break }
            }
            try { $task = $Proc.StandardOutput.ReadLineAsync() } catch { $task = $null }
            continue
        }
        $now = [DateTime]::UtcNow
        if ($now -ge $HardUntil) { $state = 'budget'; break }
        if ($now -ge $phaseUntil) { $state = 'phase_timeout'; break }
        if (($now - $last).TotalSeconds -ge $IdleSec) { $state = 'timeout'; break }
    }
    Stop-ProbeChild $Proc ($state -eq 'done')
    return @{ state = $state; events = $evs }
}

function Merge-Events($Events, $Into) {
    foreach ($ev in @($Events)) {
        foreach ($pp in $ev.PSObject.Properties) {
            if ($pp.Name -eq 'ev' -or $pp.Name -eq 'pid') { continue }
            $Into[$pp.Name] = $pp.Value
        }
    }
}

# ───────────────────────────── 자식: COM 붙기(P-OL-COM) ─────────────────────────────
function Emit-Ev($o) { Write-Line (To-Json $o) }

function Invoke-ComChildFake($f, $c) {
    $mode = [string](P $f 'mode')
    if ($mode -eq 'hang') { Start-Sleep -Seconds 3600; return }
    if ($mode -eq 'crash') { $script:ChildRc = 3; return }
    if ($mode -eq 'unavailable') { Emit-Ev ([ordered]@{ ev = 'done'; attach = 'unavailable'; hresult = $MK_E_UNAVAILABLE }); return }
    if ($mode -eq 'rejected') { Emit-Ev ([ordered]@{ ev = 'done'; attach = 'rejected'; hresult = $RPC_E_CALL_REJECTED }); return }
    if ($mode -eq 'error') { Emit-Ev ([ordered]@{ ev = 'done'; attach = 'error'; hresult = (P $f 'hresult') }); return }
    Emit-Ev ([ordered]@{ ev = 'attached'; attach = 'ok'; version_major = (P $f 'version_major'); exchange_mode = (P $f 'exchange_mode')
            cached = (P $f 'cached'); stores = (P $f 'stores'); store_types = (P $f 'store_types') })
    if ($mode -eq 'hang_after_attach') { Start-Sleep -Seconds 3600; return }
    Emit-Ev ([ordered]@{ ev = 'a'; inbox_oldest = (P $f 'inbox_oldest'); inbox_newest = (P $f 'inbox_newest'); sent_oldest = (P $f 'sent_oldest')
            sent_newest = (P $f 'sent_newest'); cal_items = (P $f 'cal_items') })
    Emit-Ev ([ordered]@{ ev = 'sub'; mail_total = (P $f 'mail_total'); mail_default = (P $f 'mail_default'); folders = (P $f 'folders')
            folders_capped = $false })
    if (B (P $c 'read_protected')) {
        Emit-Ev ([ordered]@{ ev = 'pr_start' })
        $pm = [string](P $f 'protected_mode')
        if ($pm -eq 'hang') { Start-Sleep -Seconds 3600; return }
        $pr = 'ok'
        if ($pm -eq 'blocked') { $pr = 'blocked' }
        Emit-Ev ([ordered]@{ ev = 'pr'; protected_read = $pr })
    }
    Emit-Ev ([ordered]@{ ev = 'done'; attach = 'ok' })
}

function Measure-Subfolders($ns) {
    # 기본 저장소의 메일 폴더를 재귀로 훑어 폴더별 Items.Count 만 더한다(항목을 열지 않는다, 이름·경로를 남기지 않는다).
    $r = [ordered]@{ ev = 'sub'; mail_total = 0; mail_default = 0; folders = 0; folders_capped = $false }
    try {
        $def = @{}
        foreach ($n in 6, 5) { try { $def[[string]$ns.GetDefaultFolder($n).EntryID] = 1 } catch { } }
        $skip = @{}
        foreach ($n in 3, 4, 16, 19, 20, 21, 22, 23, 25) { try { $skip[[string]$ns.GetDefaultFolder($n).EntryID] = 1 } catch { } }
        $stack = New-Object System.Collections.Stack
        foreach ($f in $ns.DefaultStore.GetRootFolder().Folders) { $stack.Push($f) }
        while ($stack.Count -gt 0) {
            $f = $stack.Pop()
            if ($r['folders'] -ge 3000) { $r['folders_capped'] = $true; break }
            $id = $null
            try { $id = [string]$f.EntryID } catch { }
            if ($id -and $skip.ContainsKey($id)) { continue }
            $type = -1
            try { $type = [int]$f.DefaultItemType } catch { }
            if ($type -ne 0) { continue }
            $r['folders'] = $r['folders'] + 1
            $n = 0
            try { $n = [int]$f.Items.Count } catch { }
            $r['mail_total'] = $r['mail_total'] + $n
            if ($id -and $def.ContainsKey($id)) { $r['mail_default'] = $r['mail_default'] + $n }
            try { foreach ($sf in $f.Folders) { $stack.Push($sf) } } catch { }
            if (($r['folders'] % 25) -eq 0) { Emit-Ev ([ordered]@{ ev = 'f'; n = $r['folders'] }) }
        }
    } catch { }
    return $r
}

function Invoke-ComChildReal($c) {
    $ol = $null
    $hr = $null
    for ($i = 1; $i -le 3; $i++) {
        try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application'); break }
        catch {
            $hr = Get-HResult $_.Exception
            if ($hr -eq $RPC_E_CALL_REJECTED -and $i -lt 3) { Start-Sleep -Seconds 2; continue }
            break
        }
    }
    if ($null -eq $ol) {
        $at = 'error'
        if ($hr -eq $MK_E_UNAVAILABLE) { $at = 'unavailable' } elseif ($hr -eq $RPC_E_CALL_REJECTED) { $at = 'rejected' }
        Emit-Ev ([ordered]@{ ev = 'done'; attach = $at; hresult = $hr })
        return
    }
    $ns = $null
    try { $ns = $ol.GetNamespace('MAPI') } catch {
        $hr = Get-HResult $_.Exception
        $at = 'error'
        if ($hr -eq $RPC_E_CALL_REJECTED) { $at = 'rejected' }
        Emit-Ev ([ordered]@{ ev = 'done'; attach = $at; hresult = $hr })
        return
    }
    $att = [ordered]@{ ev = 'attached'; attach = 'ok'; version_major = $null; exchange_mode = $null; cached = $null; stores = $null }
    try { $att['version_major'] = [int](([string]$ol.Version).Split('.')[0]) } catch { }
    try { $att['exchange_mode'] = [int]$ns.ExchangeConnectionMode } catch { }
    try { $att['cached'] = [bool]$ns.DefaultStore.IsCachedExchange } catch { }
    try { $att['stores'] = [int]$ns.Stores.Count } catch { }
    try {
        $ty = [ordered]@{}
        foreach ($n in $STORE_TYPES) { $ty[$n] = 0 }
        foreach ($st in $ns.Stores) {
            $i = -1
            try { $i = [int]$st.ExchangeStoreType } catch { }
            if ($i -ge 0 -and $i -lt $STORE_TYPES.Count) { $ty[$STORE_TYPES[$i]] = $ty[$STORE_TYPES[$i]] + 1 }
        }
        $att['store_types'] = $ty
    } catch { }
    Emit-Ev $att
    # A단(비보호): 받은 편지함 지평선 = 가장 오래된·최신 수신 시각만(제목·주소 0)
    $a = [ordered]@{ ev = 'a'; inbox_oldest = $null; inbox_newest = $null; sent_oldest = $null; sent_newest = $null; cal_items = $null }
    try {
        $items = $ns.GetDefaultFolder(6).Items
        $items.Sort('[ReceivedTime]', $false)
        $first = $items.GetFirst()
        if ($null -ne $first) { $a['inbox_oldest'] = Format-Utc ($first.ReceivedTime) }
        $lastItem = $items.GetLast()
        if ($null -ne $lastItem) { $a['inbox_newest'] = Format-Utc ($lastItem.ReceivedTime) }
        $first = $null
        $lastItem = $null
    } catch { }
    try {
        $items = $ns.GetDefaultFolder(5).Items
        $items.Sort('[SentOn]', $false)
        $first = $items.GetFirst()
        if ($null -ne $first) { $a['sent_oldest'] = Format-Utc ($first.SentOn) }
        $lastItem = $items.GetLast()
        if ($null -ne $lastItem) { $a['sent_newest'] = Format-Utc ($lastItem.SentOn) }
        $first = $null
        $lastItem = $null
    } catch { }
    try { $a['cal_items'] = [int]$ns.GetDefaultFolder(9).Items.Count } catch { }
    Emit-Ev $a
    Emit-Ev (Measure-Subfolders $ns)
    if (B (P $c 'read_protected')) {
        # B단 시험 읽기 1회 — 값은 길이만 보고 버린다. 부모가 mail.com.protectedReadSec 안에 끝나지 않으면 끊는다(R-OMG).
        Emit-Ev ([ordered]@{ ev = 'pr_start' })
        $pr = 'blocked'
        try {
            $nm = [string]$ns.CurrentUser.Name
            if ($nm.Length -gt 0) { $pr = 'ok' }
            $nm = $null
        } catch { }
        Emit-Ev ([ordered]@{ ev = 'pr'; protected_read = $pr })
    }
    Emit-Ev ([ordered]@{ ev = 'done'; attach = 'ok' })
}

# ───────────────────────────── 자식: UIA(P-TEAMS) ─────────────────────────────
$WIN_CS = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
namespace Lm27ProbeUi {
    public static class Win {
        delegate bool EnumProc(IntPtr h, IntPtr l);
        [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
        [DllImport("user32.dll")] static extern int GetWindowTextLength(IntPtr h);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
        [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
        [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
        public static IntPtr[] TopWindows(int[] pids) {
            HashSet<uint> set = new HashSet<uint>();
            foreach (int p in pids) { set.Add((uint)p); }
            List<IntPtr> res = new List<IntPtr>();
            EnumProc cb = delegate(IntPtr h, IntPtr l) {
                uint pid;
                GetWindowThreadProcessId(h, out pid);
                if (set.Contains(pid) && GetWindowTextLength(h) > 0) { res.Add(h); }
                return true;
            };
            EnumWindows(cb, IntPtr.Zero);
            GC.KeepAlive(cb);
            return res.ToArray();
        }
        public static bool Shown(IntPtr h) {
            RECT r;
            if (!IsWindowVisible(h) || IsIconic(h)) { return false; }
            if (!GetWindowRect(h, out r)) { return false; }
            return (r.R - r.L) > 0 && (r.B - r.T) > 0;
        }
    }
}
'@

function Get-TimeRegex([string]$Custom) {
    # 이 PC 지역 설정에서 시각 정규식을 만든다(LM24 Get-TeamsWindow 이식). 설정 teams.timeRegex 가 있으면 그것.
    if ($Custom) { return $Custom }
    $ci = Get-Culture
    $am = [string]$ci.DateTimeFormat.AMDesignator
    $pm = [string]$ci.DateTimeFormat.PMDesignator
    $names = @('오전', '오후', 'AM', 'PM', 'am', 'pm', 'a.m.', 'p.m.', 'A.M.', 'P.M.', '午前', '午後', '上午', '下午', $am, $pm)
    $desig = (@($names | Where-Object { $_ } | Select-Object -Unique | ForEach-Object { [regex]::Escape($_) }) -join '|')
    $sep = ':'
    if ($ci.DateTimeFormat.ShortTimePattern -match '\.') { $sep = '[:.]' }
    return '(?:(' + $desig + ')\s*)?(?<!\d)(\d{1,2})' + $sep + '(\d{2})(?!\d)(?:\s*(' + $desig + '))?'
}

function Invoke-UiaChildFake($f) {
    $mode = [string](P $f 'mode')
    if ($mode -eq 'hang') { Start-Sleep -Seconds 3600; return }
    if ($mode -eq 'crash') { $script:ChildRc = 3; return }
    $vis = [int](S-Int (P $f 'visible'))
    Emit-Ev ([ordered]@{ ev = 'wins'; windows = (P $f 'windows'); visible = $vis })
    if ($mode -eq 'hang_in_window') { Start-Sleep -Seconds 3600; return }
    if ($vis -gt 0) {
        if ($mode -eq 'denied') {
            Emit-Ev ([ordered]@{ ev = 'win'; lines = 0; time_matches = 0; generic_matches = 0; denied = $vis; errors = 0; capped = $false })
        } else {
            Emit-Ev ([ordered]@{ ev = 'win'; lines = (P $f 'lines'); time_matches = (P $f 'time_matches')
                    generic_matches = (P $f 'generic_matches'); denied = (P $f 'denied'); errors = 0; capped = $false })
        }
    }
    Emit-Ev ([ordered]@{ ev = 'done' })
}

function Invoke-UiaChildReal($c) {
    $max = [int](S-Int (P $c 'max_elements'))
    if ($max -le 0) { $max = 4000 }
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction Stop
    Add-Type -TypeDefinition $WIN_CS -Language CSharp -ErrorAction Stop
    $ids = @(Get-Process -Name 'ms-teams', 'Teams', 'msteams' -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.Id })
    $hs = @([Lm27ProbeUi.Win]::TopWindows([int[]]$ids))
    $vis = @($hs | Where-Object { [Lm27ProbeUi.Win]::Shown($_) })
    Emit-Ev ([ordered]@{ ev = 'wins'; windows = $hs.Count; visible = $vis.Count })
    $re = Get-TimeRegex ([string](P $c 'time_regex'))
    $cond = [System.Windows.Automation.Automation]::ContentViewCondition
    foreach ($h in $vis) {
        $w = [ordered]@{ ev = 'win'; lines = 0; time_matches = 0; generic_matches = 0; denied = 0; errors = 0; capped = $false }
        try {
            $el = [System.Windows.Automation.AutomationElement]::FromHandle($h)
            $all = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
            $n = 0
            foreach ($e in $all) {
                $n++
                if ($n -gt $max) { $w['capped'] = $true; break }
                $nm = $null
                try { $nm = [string]$e.Current.Name } catch { $nm = $null }
                if ($nm -and $nm.Length -ge 4) {
                    $w['lines'] = $w['lines'] + 1
                    if ($nm -match $re) { $w['time_matches'] = $w['time_matches'] + 1 }
                    elseif ($nm -match $RX_GENERIC_TIME) { $w['generic_matches'] = $w['generic_matches'] + 1 }
                }
                $nm = $null
            }
        } catch {
            $x = Get-Inner $_.Exception
            $tn = ''
            try { $tn = [string]$x.GetType().Name } catch { }
            if ($tn -match 'Unauthorized|ElementNotAvailable|AccessDenied') { $w['denied'] = 1 } else { $w['errors'] = 1 }
        }
        Emit-Ev $w
    }
    Emit-Ev ([ordered]@{ ev = 'done' })
}

function Invoke-ProbeChild([string]$Mode) {
    $c = Read-StdinKey '_child'
    Emit-Ev ([ordered]@{ ev = 'pid'; pid = $PID })
    $f = P $c 'fake'
    try {
        if ($Mode -eq 'com') {
            if ($null -ne $f) { Invoke-ComChildFake $f $c } else { Invoke-ComChildReal $c }
        } else {
            if ($null -ne $f) { Invoke-UiaChildFake $f } else { Invoke-UiaChildReal $c }
        }
    } catch { $script:ChildRc = 3 }
}

# ───────────────────────────── 부모: 입력·설정 ─────────────────────────────
function Merge-Cfg($c) {
    $m = [ordered]@{}
    foreach ($k in $CFG_DEFAULT.Keys) { $m[$k] = $CFG_DEFAULT[$k] }
    if ($null -ne $c) {
        foreach ($k in @($CFG_DEFAULT.Keys)) {
            $v = P $c $k
            if ($null -eq $v) { continue }
            if ($CFG_NUMERIC -contains $k) {
                if ($v -is [string] -or $v -is [bool]) { continue }
                try { $m[$k] = [double]$v } catch { }
            } elseif ($v -is [string]) { $m[$k] = $v }
        }
    }
    # 하한 — 범위 밖 값이 와도 멈추지 않게(범위 검증은 설정 레지스트리가 한다)
    foreach ($k in @('probe.budgetSec', 'mail.com.watchdogSec', 'mail.com.protectedReadSec', 'teams.uia.windowWatchdogSec',
            'teams.uia.maxElements')) {
        if ([double]$m[$k] -lt 1) { $m[$k] = 1 }
    }
    return $m
}

function Get-OnlySet([string]$Text) {
    $set = @()
    foreach ($t in @($Text -split ',')) {
        $u = $t.Trim().ToUpperInvariant()
        if ($u -and $GROUPS -contains $u) { $set += $u }
    }
    return , $set
}

function Test-Want([string]$Group) {
    if (-not $script:OnlyGiven) { return $true }
    return ($script:OnlySet -contains $Group)
}

function Get-StubEnv {
    $found = @()
    foreach ($n in $INJECT_NAMES) {
        $hit = [bool](Get-EnvVar $n)
        if (-not $hit -and $null -ne (Get-RegValue 'HKCU:\Environment' $n)) { $hit = $true }
        if (-not $hit -and $null -ne (Get-RegValue 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' $n)) { $hit = $true }
        if ($hit) { $found += $n }
    }
    return , $found
}

# ───────────────────────────── 부모: 사실 모으기 ─────────────────────────────
$NATIVE_CS = @'
using System;
using System.Runtime.InteropServices;
namespace Lm27Probe {
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
    public static class Native {
        [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
        [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
        public static int[] CatalogStatus() {
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

function Initialize-Native {
    # Add-Type(P/Invoke) 가능 여부 = PS 샘플러 구현 가능 여부의 재료(CP §3.5). 한 번만 컴파일한다.
    if ($null -ne $script:NativeState) { return ($script:NativeState -eq 'ok') }
    try { Add-Type -TypeDefinition $NATIVE_CS -Language CSharp -ErrorAction Stop; $script:NativeState = 'ok' } catch { $script:NativeState = 'fail' }
    return ($script:NativeState -eq 'ok')
}

function Test-Elevated {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $pr = New-Object Security.Principal.WindowsPrincipal($id)
        return [bool]$pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { }
    try {
        $g = @(& whoami.exe /groups 2>$null)
        return [bool](@($g | Where-Object { $_ -match 'S-1-16-12288' }).Count)
    } catch { return $null }
}

function Test-PyCtypes {
    # 동봉 파이썬 ctypes 실행 가능 여부(py 샘플러 구현 재료). 정책이 실행을 막으면 Win32 1260 → blocked(R-APPLOCKER).
    $py = Join-Path (Split-Path -Parent $PSScriptRoot) 'python\python.exe'
    if (-not (Test-Path -LiteralPath $py)) { return 'missing' }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $py
        $psi.Arguments = '-X utf8 -I -B -c "import ctypes;ctypes.windll.kernel32.GetTickCount64()"'
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $p = [System.Diagnostics.Process]::Start($psi)
        $p.StandardInput.Close()
        $null = $p.StandardOutput.ReadToEndAsync()
        $null = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(10000)) { Stop-ProbeChild $p $false; return 'fail' }
        if ($p.ExitCode -eq 0) { return 'ok' }
        return 'fail'
    } catch {
        $x = Get-Inner $_.Exception
        try { if ([int]$x.NativeErrorCode -eq 1260) { return 'blocked' } } catch { }
        return 'fail'
    }
}

function Get-EnvFacts([bool]$Full) {
    $real = [string]$ExecutionContext.SessionState.LanguageMode
    if ($script:FakeMode) {
        $h = Copy-Facts (P $script:Fake 'env') $ENV_KEYS
        if ($null -eq $h['language_mode']) { $h['language_mode'] = $real }
        return $h
    }
    $h = Copy-Facts $null $ENV_KEYS
    $h['language_mode'] = $real
    $h['elevated'] = Test-Elevated
    if (-not $Full) { return $h }
    $ep = [ordered]@{}
    try { foreach ($r in @(Get-ExecutionPolicy -List)) { $ep[[string]$r.Scope] = [string]$r.ExecutionPolicy } } catch { }
    $h['exec_policy'] = $ep
    try {
        $tz = [TimeZoneInfo]::Local
        $h['tz_offset_min'] = [int]$tz.GetUtcOffset([DateTime]::UtcNow).TotalMinutes
        $h['tz_id'] = [string]$tz.Id
    } catch {
        try { $z = Get-TimeZone; $h['tz_offset_min'] = [int]$z.BaseUtcOffset.TotalMinutes; $h['tz_id'] = [string]$z.Id } catch { }
    }
    try { $h['domain_joined'] = [bool](Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop).PartOfDomain } catch { }
    $h['aad_joined'] = (@(Get-RegSubkeys 'HKLM:\SYSTEM\CurrentControlSet\Control\CloudDomainJoin\JoinInfo').Count -gt 0)
    $h['ctypes'] = Test-PyCtypes
    if ($h['language_mode'] -eq 'FullLanguage' -and (Initialize-Native)) { $h['addtype'] = 'ok' } else { $h['addtype'] = 'fail' }
    try { $h['ps_version'] = '{0}.{1}' -f $PSVersionTable.PSVersion.Major, $PSVersionTable.PSVersion.Minor } catch { }
    try { $h['os_build'] = [int][Environment]::OSVersion.Version.Build } catch { }
    return $h
}

function Get-SelfTestOl {
    $h = Copy-Facts $null $OL_KEYS
    $h['classic'] = $true; $h['version'] = '16.0.4000'; $h['c2r'] = $true; $h['msi'] = $false
    $h['new_installed'] = $false; $h['use_new'] = $false; $h['new_running'] = $false; $h['profiles'] = 1
    $h['profile_name'] = 'selftest'; $h['com_registered'] = $true; $h['com_server_match'] = $true; $h['running'] = $true
    $h['ol_elevated'] = $false; $h['sync_months'] = 0; $h['omg_policy'] = 'never'; $h['av_state'] = 'valid'
    return $h
}

function Get-SelfTestCom {
    $n = [int]$script:SelfTestN
    $now = Get-NowUtc
    return [ordered]@{ mode = 'ok'; version_major = 16; exchange_mode = 0; cached = $true; stores = 1
        inbox_oldest = (Format-Utc $now.AddDays(-30)); inbox_newest = (Format-Utc $now); cal_items = [int][Math]::Max(1, [int]($n / 2))
        mail_total = $n; mail_default = $n; folders = 2; protected_mode = 'ok' }
}

function Get-OmgPolicy([string]$Ov) {
    $pol = "HKCU:\Software\Policies\Microsoft\Office\$Ov\Outlook\Security"
    if ((Get-RegValue $pol 'AdminSecurityMode') -eq 3) {
        $vals = @()
        foreach ($n in @('PromptOOMAddressInformationAccess', 'PromptOOMAddressBookAccess')) {
            $v = Get-RegValue $pol $n
            if ($null -ne $v) { $vals += [int]$v }
        }
        if (@($vals | Where-Object { $_ -eq 0 -or $_ -eq 1 }).Count) { return 'always' }
        if ($vals.Count -and -not @($vals | Where-Object { $_ -ne 2 }).Count) { return 'never' }
    }
    foreach ($k in @("HKLM:\SOFTWARE\Policies\Microsoft\Office\$Ov\Outlook\Security", "HKLM:\SOFTWARE\Microsoft\Office\$Ov\Outlook\Security",
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Office\$Ov\Outlook\Security")) {
        $g = Get-RegValue $k 'ObjectModelGuard'
        if ($null -ne $g) {
            if ([int]$g -eq 1) { return 'always' }
            if ([int]$g -eq 2) { return 'never' }
            return 'auto'
        }
    }
    return 'auto'
}

function Get-AvState {
    try {
        $av = @(Get-CimInstance -Namespace 'root/SecurityCenter2' -ClassName AntiVirusProduct -ErrorAction Stop)
        if ($av.Count -eq 0) { return 'invalid' }
        foreach ($a in $av) {
            $s = [int]$a.productState
            if (((($s -shr 12) -band 15) -eq 1) -and ((($s -shr 4) -band 15) -eq 0)) { return 'valid' }
        }
        return 'invalid'
    } catch { return 'unknown' }
}

function Get-OlFacts {
    if ($script:FakeMode) {
        $f = P $script:Fake 'ol'
        if ($null -ne $f) { return (Copy-Facts $f $OL_KEYS) }
        if ($script:SelfTestOn) { return (Get-SelfTestOl) }
        return $null
    }
    if ($script:SelfTestOn) { return (Get-SelfTestOl) }
    $h = Copy-Facts $null $OL_KEYS
    $exe = Get-ExePath (Get-RegDefault 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE')
    if (-not $exe) { $exe = Get-ExePath (Get-RegDefault 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE') }
    $h['classic'] = [bool]($exe -and (Test-Path -LiteralPath $exe))
    if ($h['classic']) { $h['version'] = Get-FileVersion $exe }
    $h['c2r'] = [bool](Test-Path -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration')
    $msi = $false
    foreach ($v in @('14.0', '15.0', '16.0')) {
        foreach ($b in @('HKLM:\SOFTWARE\Microsoft\Office', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Office')) {
            if (Get-RegValue "$b\$v\Outlook\InstallRoot" 'Path') { $msi = $true }
        }
    }
    $h['msi'] = $msi
    $pk = @(Get-RegSubkeys $PKG_ROOT)
    $h['new_installed'] = [bool](@($pk | Where-Object { $_ -like 'Microsoft.OutlookForWindows_*' }).Count)
    $useNew = $false
    foreach ($rp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
        if ((Get-RegValue $rp 'UseNewOutlook') -eq 1) { $useNew = $true }
    }
    $h['use_new'] = $useNew
    $h['new_running'] = [bool](@(Get-Process -Name olk -ErrorAction SilentlyContinue).Count)
    $mig = Get-RegValue 'HKCU:\Software\Policies\Microsoft\Office\16.0\Outlook\Preferences' 'NewOutlookMigrationUserSetting'
    if ($null -ne $mig) { try { $h['migration_policy'] = [int]$mig } catch { } }
    $nProf = 0
    foreach ($pp in @('HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles',
            'HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles', 'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles')) {
        $nProf += @(Get-RegSubkeys $pp).Count
    }
    $h['profiles'] = $nProf
    $ov = '16.0'
    if ($h['version'] -match '^(\d+)\.') { $ov = $Matches[1] + '.0' }
    $h['profile_name'] = Get-RegValue "HKCU:\Software\Microsoft\Office\$ov\Outlook" 'DefaultProfile'
    $clsid = Get-RegDefault 'HKLM:\SOFTWARE\Classes\Outlook.Application\CLSID'
    $h['com_registered'] = [bool]$clsid
    $h['com_server_match'] = $true
    if ($clsid -and $exe) {
        $srv = Get-ExePath (Get-RegDefault "HKLM:\SOFTWARE\Classes\CLSID\$clsid\LocalServer32")
        if (-not $srv) { $srv = Get-ExePath (Get-RegDefault "HKLM:\SOFTWARE\WOW6432Node\Classes\CLSID\$clsid\LocalServer32") }
        if ($srv) { $h['com_server_match'] = ([string]$srv).Trim().ToLowerInvariant() -eq ([string]$exe).Trim().ToLowerInvariant() }
    }
    $procs = @(Get-Process -Name outlook -ErrorAction SilentlyContinue)
    $h['running'] = ($procs.Count -gt 0)
    if ($h['running']) { $h['ol_elevated'] = [bool](@($procs | Where-Object { -not $_.Path }).Count) }
    $cm = "HKCU:\Software\Policies\Microsoft\Office\$ov\Outlook\Cached Mode"
    $en = Get-RegValue $cm 'Enable'
    if ($null -ne $en) { if ([int]$en -eq 0) { $h['cached_policy'] = 'off' } else { $h['cached_policy'] = 'on' } }
    $sw = Get-RegValue $cm 'SyncWindowSetting'
    if ($null -eq $sw) { $sw = Get-RegValue "HKCU:\Software\Microsoft\Office\$ov\Outlook\Cached Mode" 'SyncWindowSetting' }
    if ($null -ne $sw) { $h['sync_months'] = [int]$sw }
    $h['omg_policy'] = Get-OmgPolicy $ov
    $h['av_state'] = Get-AvState
    return $h
}

function New-IdxAcc {
    # 색인 건수 누적기 — 행마다 날짜만 보고 센다(배열에 모으지 않는다: 2만 행에서도 선형).
    return [ordered]@{ n30 = 0; n90 = 0; n365 = 0; newest = $null; oldest = $null; rows = 0; recurring = $null; now = (Get-NowUtc) }
}

function Add-IdxDate($Acc, $D) {
    $Acc['rows'] = $Acc['rows'] + 1
    if ($null -eq $D) { return }
    $age = ($Acc['now'] - $D).TotalDays
    if ($age -le 365) { $Acc['n365'] = $Acc['n365'] + 1 }
    if ($age -le 90) { $Acc['n90'] = $Acc['n90'] + 1 }
    if ($age -le 30) { $Acc['n30'] = $Acc['n30'] + 1 }
    if ($null -eq $Acc['newest'] -or $D -gt $Acc['newest']) { $Acc['newest'] = $D }
    if ($null -eq $Acc['oldest'] -or $D -lt $Acc['oldest']) { $Acc['oldest'] = $D }
}

function Close-IdxAcc($Acc, [int]$Cap) {
    return [ordered]@{ n30 = $Acc['n30']; n90 = $Acc['n90']; n365 = $Acc['n365']; newest = (Format-Utc $Acc['newest'])
        oldest = (Format-Utc $Acc['oldest']); capped = ($Cap -gt 0 -and $Acc['rows'] -ge $Cap); recurring = $Acc['recurring'] }
}

function Read-IdxQuery($Conn, [string]$Kind, [string]$Col, [int]$Cap, [bool]$WithRec) {
    # 최근 365일 Outlook 항목의 날짜 열만 읽는다(제목·주소·폴더 열은 고르지 않는다). 최신순 상한 $Cap — 넘으면 capped.
    $since = (Get-NowUtc).AddDays(-365).ToString('yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
    $cols = $Col
    if ($WithRec) { $cols = $Col + ', System.Calendar.IsRecurring' }
    $cmd = $Conn.CreateCommand()
    $cmd.CommandText = "SELECT TOP $Cap $cols FROM SYSTEMINDEX WHERE System.Kind = '$Kind' AND System.ItemUrl LIKE 'mapi%' AND $Col >= '$since' ORDER BY $Col DESC"
    $acc = New-IdxAcc
    $rec = 0
    $rd = $cmd.ExecuteReader()
    try {
        while ($rd.Read()) {
            $d = $null
            try { $d = Parse-Utc ($rd.GetValue(0)) } catch { }
            Add-IdxDate $acc $d
            if ($WithRec) { try { if ([bool]$rd.GetValue(1)) { $rec++ } } catch { } }
        }
    } finally { $rd.Close() }
    if ($WithRec) { $acc['recurring'] = $rec }
    # 색인에 남은 가장 오래된 항목 날짜(지평선) — 날짜 열 1행만
    try {
        $c2 = $Conn.CreateCommand()
        $c2.CommandText = "SELECT TOP 1 $Col FROM SYSTEMINDEX WHERE System.Kind = '$Kind' AND System.ItemUrl LIKE 'mapi%' ORDER BY $Col ASC"
        $r2 = $c2.ExecuteReader()
        try {
            if ($r2.Read()) {
                $o = Parse-Utc ($r2.GetValue(0))
                if ($null -ne $o -and ($null -eq $acc['oldest'] -or $o -lt $acc['oldest'])) { $acc['oldest'] = $o }
            }
        } finally { $r2.Close() }
    } catch { }
    return (Close-IdxAcc $acc $Cap)
}

function Get-IdxFromIndexFake([string]$Path) {
    # WP-05 synth.inject.index_fake 형식: {"mail":[{System.ItemDate:'yyyy-MM-dd HH:mm'(로컬), …}], "calendar":[{System.StartDate, System.Calendar.IsRecurring, …}]}
    # 날짜·반복 표시만 읽는다(제목·주소·장소 칸은 보지 않는다).
    $o = Read-JsonFile $Path
    $h = Copy-Facts $null $IDX_KEYS
    $h['service'] = 'running'; $h['connect'] = $true; $h['policy_outlook'] = $false; $h['catalog_status'] = 0; $h['paused_reason'] = 0
    $h['ext_props'] = $true
    $ma = New-IdxAcc
    foreach ($row in @(P $o 'mail')) {
        if ($null -eq $row) { continue }
        $v = P $row 'System.ItemDate'
        if ($null -eq $v) { $v = P $row 'System.Message.DateReceived' }
        if ($null -eq $v) { $v = P $row 'System.Message.DateSent' }
        Add-IdxDate $ma (Parse-Utc $v $true)
    }
    $ca = New-IdxAcc
    $rec = 0
    foreach ($row in @(P $o 'calendar')) {
        if ($null -eq $row) { continue }
        Add-IdxDate $ca (Parse-Utc (P $row 'System.StartDate') $true)
        if (B (P $row 'System.Calendar.IsRecurring')) { $rec++ }
    }
    $ca['recurring'] = $rec
    $h['mail'] = Close-IdxAcc $ma 0
    $h['cal'] = Close-IdxAcc $ca 0
    return $h
}

function Get-IdxFacts {
    if ($script:FakeMode) {
        $f = P $script:Fake 'idx'
        if ($null -ne $f) { return (Copy-Facts $f $IDX_KEYS) }
        if ($script:IndexFake) { return (Get-IdxFromIndexFake $script:IndexFake) }
        return $null
    }
    if ($script:IndexFake) { return (Get-IdxFromIndexFake $script:IndexFake) }
    $h = Copy-Facts $null $IDX_KEYS
    $h['connect'] = $false
    $h['policy_outlook'] = $false
    try {
        $svc = Get-Service -Name WSearch -ErrorAction Stop
        if ([string]$svc.StartType -eq 'Disabled') { $h['service'] = 'disabled' }
        elseif ([string]$svc.Status -eq 'Running') { $h['service'] = 'running' }
        else { $h['service'] = 'stopped' }
    } catch { $h['service'] = 'missing' }
    foreach ($b in @('HKLM:\SOFTWARE\Policies\Microsoft\Windows\Windows Search', 'HKCU:\SOFTWARE\Policies\Microsoft\Windows\Windows Search')) {
        if ((Get-RegValue $b 'PreventIndexingOutlook') -eq 1) { $h['policy_outlook'] = $true }
    }
    if ($h['service'] -ne 'running') { return $h }
    if (Initialize-Native) {
        try { $cs = [Lm27Probe.Native]::CatalogStatus(); $h['catalog_status'] = [int]$cs[0]; $h['paused_reason'] = [int]$cs[1] } catch { }
    }
    $conn = $null
    try {
        $conn = New-Object System.Data.OleDb.OleDbConnection("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
        $conn.Open()
        $h['connect'] = $true
        $h['mail'] = Read-IdxQuery $conn 'email' 'System.ItemDate' 20000 $false
        try { $h['cal'] = Read-IdxQuery $conn 'calendar' 'System.StartDate' 8000 $true; $h['ext_props'] = $true }
        catch { $h['cal'] = Read-IdxQuery $conn 'calendar' 'System.StartDate' 8000 $false; $h['ext_props'] = $false }
    } catch { } finally { if ($null -ne $conn) { try { $conn.Close() } catch { } } }
    return $h
}

function Get-EdgeFacts {
    if ($script:FakeMode) { $f = P $script:Fake 'edge'; if ($null -eq $f) { return $null }; return (Copy-Facts $f $EDGE_KEYS_F) }
    $h = Copy-Facts $null $EDGE_KEYS_F
    $exe = $null
    foreach ($k in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe',
            'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe')) {
        $c = Get-ExePath (Get-RegDefault $k)
        if ($c -and (Test-Path -LiteralPath $c)) { $exe = $c; break }
    }
    if (-not $exe) {
        foreach ($b in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA)) {
            if (-not $b) { continue }
            $c = Join-Path $b 'Microsoft\Edge\Application\msedge.exe'
            if (Test-Path -LiteralPath $c) { $exe = $c; break }
        }
    }
    $h['installed'] = [bool]$exe
    if ($exe) { $h['version'] = Get-FileVersion $exe }
    foreach ($b in @('HKLM:\SOFTWARE\Policies\Microsoft\Edge', 'HKCU:\SOFTWARE\Policies\Microsoft\Edge')) {
        if ($null -eq $h['remote_debugging']) { $v = Get-RegValue $b 'RemoteDebuggingAllowed'; if ($null -ne $v) { $h['remote_debugging'] = [int]$v } }
        if ($null -eq $h['devtools']) { $v = Get-RegValue $b 'DeveloperToolsAvailability'; if ($null -ne $v) { $h['devtools'] = [int]$v } }
    }
    $h['profile'] = [bool]($env:LOCALAPPDATA -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'LoadMonitor27\edge_copilot')))
    return $h
}

function Get-TeamsFacts {
    if ($script:FakeMode) { $f = P $script:Fake 'teams'; if ($null -eq $f) { return $null }; return (Copy-Facts $f $TEAMS_KEYS) }
    $h = Copy-Facts $null $TEAMS_KEYS
    $pk = @(Get-RegSubkeys $PKG_ROOT | Where-Object { $_ -like 'MSTeams_*' } | Select-Object -First 1)
    $h['new_installed'] = ($pk.Count -gt 0)
    if ($pk.Count) { $parts = ([string]$pk[0]).Split('_'); if ($parts.Count -ge 2) { $h['new_version'] = $parts[1] } }
    $ce = $null
    if ($env:LOCALAPPDATA) { $ce = Join-Path $env:LOCALAPPDATA 'Microsoft\Teams\current\Teams.exe' }
    $h['classic_installed'] = [bool]($ce -and (Test-Path -LiteralPath $ce))
    if ($h['classic_installed']) { $h['classic_version'] = Get-FileVersion $ce }
    $h['processes'] = @(Get-Process -Name 'ms-teams', 'Teams', 'msteams' -ErrorAction SilentlyContinue).Count
    return $h
}

function Get-ChannelState([string]$Log) {
    try {
        $null = Get-WinEvent -LogName $Log -MaxEvents 1 -ErrorAction Stop
        return @('ok', $null)
    } catch {
        $fq = [string]$_.FullyQualifiedErrorId
        $tn = Get-TypeName $_.Exception
        if ($fq -like 'NoMatchingEventsFound*' -or $fq -like 'NoMatchingLogsFound*') { return @('none', $null) }
        if ($fq -match 'Unauthorized' -or $tn -match 'Unauthorized') { return @('unauthorized', $null) }
        return @('error', $tn)
    }
}

function Get-MruCount {
    $vers = @(Get-RegSubkeys 'HKCU:\Software\Microsoft\Office' | Where-Object { $_ -match '^\d+\.\d$' })
    $total = 0
    $seen = @()
    foreach ($v in $vers) {
        $n = 0
        foreach ($app in $OFFICE_APPS) {
            $base = "HKCU:\Software\Microsoft\Office\$v\$app"
            $n += @(Get-RegValueNames "$base\File MRU" | Where-Object { $_ -match '^Item \d+$' }).Count
            foreach ($u in @(Get-RegSubkeys "$base\User MRU")) {
                $n += @(Get-RegValueNames "$base\User MRU\$u\File MRU" | Where-Object { $_ -match '^Item \d+$' }).Count
            }
        }
        if ($n -gt 0) { $seen += $v }
        $total += $n
    }
    return @($total, $seen)
}

function Find-Git {
    $cfgExe = [string]$script:Cfg['pc.git.exe']
    if ($cfgExe -and (Test-Path -LiteralPath $cfgExe)) { return 'cfg' }
    if (Get-Command git.exe -ErrorAction SilentlyContinue) { return 'path' }
    $cands = @()
    if ($env:ProgramFiles) { $cands += Join-Path $env:ProgramFiles 'Git\cmd\git.exe' }
    if (${env:ProgramFiles(x86)}) { $cands += Join-Path ${env:ProgramFiles(x86)} 'Git\cmd\git.exe' }
    if ($env:LOCALAPPDATA) {
        $cands += Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe'
        $cands += Join-Path $env:LOCALAPPDATA 'GitHubDesktop\app-*\resources\app\git\cmd\git.exe'
        $cands += Join-Path $env:LOCALAPPDATA 'Atlassian\SourceTree\git_local\cmd\git.exe'
    }
    foreach ($c in $cands) {
        try { if (@(Get-Item -Path $c -ErrorAction Stop).Count) { return 'candidate' } } catch { }
    }
    return $null
}

function Get-PcFacts {
    if ($script:FakeMode) { $f = P $script:Fake 'pc'; if ($null -eq $f) { return $null }; return (Copy-Facts $f $PC_KEYS) }
    $h = Copy-Facts $null $PC_KEYS
    $ev = [ordered]@{}
    $er = [ordered]@{}
    foreach ($k in $CHANNELS.Keys) {
        $st = Get-ChannelState $CHANNELS[$k]
        $ev[$k] = $st[0]
        if ($st[1]) { $er[$k] = $st[1] }
    }
    $h['events'] = $ev
    $h['event_errors'] = $er
    $rp = $false
    foreach ($b in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer')) {
        if ((Get-RegValue $b 'NoRecentDocsHistory') -eq 1 -or (Get-RegValue $b 'ClearRecentDocsOnExit') -eq 1) { $rp = $true }
    }
    if ((Get-RegValue 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' 'Start_TrackDocs') -eq 0) { $rp = $true }
    $h['recent_policy'] = $rp
    $h['lnk'] = 0
    if ($env:APPDATA) {
        try { $h['lnk'] = @(Get-ChildItem -LiteralPath (Join-Path $env:APPDATA 'Microsoft\Windows\Recent') -Filter '*.lnk' -File -ErrorAction Stop).Count } catch { $h['lnk'] = 0 }
    }
    $m = Get-MruCount
    $h['mru'] = [int]$m[0]
    $h['office_versions'] = @($m[1])
    $src = Find-Git
    $h['git'] = [bool]$src
    $h['git_src'] = $src
    return $h
}

function Test-NewOnly($O) {
    if ($null -eq $O) { return $false }
    if (B $O['use_new']) { return $true }
    return ((B $O['new_installed']) -or (B $O['new_running'])) -and -not (B $O['classic'])
}

function Test-OmgExpected($O) {
    $pol = [string]$O['omg_policy']
    if ($pol -eq 'always') { return $true }
    if ($pol -eq 'never') { return $false }
    return ([string]$O['av_state'] -ne 'valid')
}

function Test-ComEligible($E, $O) {
    if ([string]$E['language_mode'] -ne 'FullLanguage') { return $false }
    if ($null -eq $O -or -not (B $O['classic']) -or (Test-NewOnly $O)) { return $false }
    if ((S-Int $O['profiles']) -eq 0) { return $false }
    return (B $O['running'])
}

function Invoke-ComProbe($E, $O) {
    $r = [ordered]@{}
    if (-not (Test-ComEligible $E $O)) { return @{ state = 'not_attempted'; r = $r } }
    $fake = $null
    if ($script:FakeMode) { $fake = P $script:Fake 'com' }
    if ($null -eq $fake -and $script:SelfTestOn) { $fake = Get-SelfTestCom }
    if ($script:FakeMode -and $null -eq $fake) { return @{ state = 'not_attempted'; r = $r } }
    if ((Get-Left) -lt 2) { $script:BudgetHit = $true; return @{ state = 'budget'; r = $r } }
    $readProt = -not (Test-OmgExpected $O)
    $payload = [ordered]@{ read_protected = $readProt; fake = $fake }
    $t0 = [DateTime]::UtcNow
    $p = Start-ProbeChild 'com' $payload
    $w = Wait-ProbeChild $p ([double]$script:Cfg['mail.com.watchdogSec']) ($script:Deadline.AddSeconds(-1.0)) @{ pr_start = [double]$script:Cfg['mail.com.protectedReadSec'] }
    Merge-Events $w.events $r
    $r['attach_ms'] = [long](([DateTime]::UtcNow - $t0).TotalMilliseconds)
    if (-not $readProt) { $r['protected_read'] = 'skipped' }
    if ($w.state -eq 'phase_timeout') { $r['protected_read'] = 'timeout' }
    if ($w.state -eq 'budget') { $script:BudgetHit = $true }
    return @{ state = $w.state; r = $r }
}

function Invoke-UiaProbe($E, $T) {
    $r = [ordered]@{}
    if ([string]$E['language_mode'] -ne 'FullLanguage') { return @{ state = 'not_attempted'; r = $r } }
    if ($null -eq $T -or (S-Int $T['processes']) -le 0) { return @{ state = 'not_running'; r = $r } }
    $fake = $null
    if ($script:FakeMode) {
        $fake = P $script:Fake 'uia'
        if ($null -eq $fake) { return @{ state = 'not_attempted'; r = $r } }
    }
    if ((Get-Left) -lt 2) { $script:BudgetHit = $true; return @{ state = 'budget'; r = $r } }
    $payload = [ordered]@{ max_elements = [int]$script:Cfg['teams.uia.maxElements']; time_regex = [string]$script:Cfg['teams.timeRegex']; fake = $fake }
    $t0 = [DateTime]::UtcNow
    $p = Start-ProbeChild 'uia' $payload
    $w = Wait-ProbeChild $p ([double]$script:Cfg['teams.uia.windowWatchdogSec']) ($script:Deadline.AddSeconds(-1.0)) $null
    $sum = [ordered]@{ windows = $null; visible = $null; lines = 0; time_matches = 0; generic_matches = 0; denied = 0; errors = 0; capped = $false; win_events = 0
        uia_ms = [long](([DateTime]::UtcNow - $t0).TotalMilliseconds) }
    foreach ($ev in @($w.events)) {
        $name = [string](P $ev 'ev')
        if ($name -eq 'wins') { $sum['windows'] = S-Int (P $ev 'windows'); $sum['visible'] = S-Int (P $ev 'visible') }
        elseif ($name -eq 'win') {
            $sum['win_events'] = $sum['win_events'] + 1
            foreach ($k in @('lines', 'time_matches', 'generic_matches', 'denied', 'errors')) {
                $v = S-Int (P $ev $k)
                if ($null -ne $v) { $sum[$k] = $sum[$k] + $v }
            }
            if (B (P $ev 'capped')) { $sum['capped'] = $true }
        }
    }
    if ($w.state -eq 'budget') { $script:BudgetHit = $true }
    return @{ state = $w.state; r = $sum }
}

# ───────────────────────────── 부모: 판정 ─────────────────────────────
function New-Cap([string]$Status, $Rs, $Value, $SigParts) {
    $ok = $null
    if ($Status -eq 'ok') { $ok = $true } elseif ($Status -eq 'fail' -or $Status -eq 'transport_fail') { $ok = $false }
    $codes = @($Rs.Keys | Sort-Object)
    return [ordered]@{ ok = $ok; status = $Status; reasons = $codes; value = $Value; sig = (Get-Sig $SigParts) }
}

function New-MissingCap([string]$GroupState) {
    $rs = @{}
    if ($GroupState -eq 'budget') { $rs['R-BUDGET'] = 1 }
    return (New-Cap 'unknown' $rs ([ordered]@{}) @('missing'))
}

function Get-Ctypes($E) { return (S-Enum $E['ctypes'] $CTYPES_STATES) }

function Decide-Env($E) {
    $rs = @{}
    $st = 'ok'
    $lang = [string]$E['language_mode']
    if (-not $lang) { $st = 'unknown' }
    elseif ($lang -ne 'FullLanguage') { $rs['R-CLM'] = 1; $st = 'fail' }
    if ((Get-Ctypes $E) -eq 'blocked') { $rs['R-APPLOCKER'] = 1; $st = 'fail' }
    $off = S-Int $E['tz_offset_min']
    if ($null -ne $off -and $off -eq 0) { $rs['R-TZ'] = 1 }
    $ep = [ordered]@{}
    $epSrc = $E['exec_policy']
    foreach ($s in $EP_SCOPES) { $v = S-Enum (P $epSrc $s) $EP_VALUES; if ($null -ne $v) { $ep[$s] = $v } }
    $ct = Get-Ctypes $E
    $ctOk = $null
    if ($ct -eq 'ok') { $ctOk = $true } elseif ($ct -eq 'fail' -or $ct -eq 'blocked') { $ctOk = $false }
    $atOk = $null
    if ($E['addtype'] -eq 'ok') { $atOk = $true } elseif ($E['addtype'] -eq 'fail') { $atOk = $false }
    $v = [ordered]@{
        language_mode = (S-Enum $lang $LANG_MODES); exec_policy = $ep; elevated = (S-Bool $E['elevated'])
        tz_offset_min = $off; tz_id = (S-Rx $E['tz_id'] $RX_TZ); domain_joined = (S-Bool $E['domain_joined'])
        aad_joined = (S-Bool $E['aad_joined']); ctypes = $ct; ctypes_ok = $ctOk; addtype_ok = $atOk
        ps_version = (S-Rx $E['ps_version'] $RX_VER); os_build = (S-Int $E['os_build'])
    }
    return (New-Cap $st $rs $v @('env', $lang, (S-Bool $E['elevated']), $ct, $E['addtype'], $off, (S-Bool $E['domain_joined']), (S-Bool $E['aad_joined'])))
}

function Get-VersionParts([string]$V) {
    $maj = $null
    $build = $null
    if ($V -match '^(\d+)\.\d+(?:\.(\d+))?') {
        $maj = [int]$Matches[1]
        if ($Matches[2]) { $build = [int]$Matches[2] }
    }
    return @($maj, $build)
}

function Test-OfficeEol($O) {
    # 지원 종료 Office: 2013(15.0) 이하, MSI 2016(16.0 빌드 1만 미만) — C2R(365·2021+)은 아님.
    $vp = Get-VersionParts ([string]$O['version'])
    if ($null -eq $vp[0]) { return $false }
    if ($vp[0] -lt 16) { return $true }
    if ($vp[0] -eq 16 -and $null -ne $vp[1] -and $vp[1] -lt 10000 -and -not (B $O['c2r'])) { return $true }
    return $false
}

function Test-ElevMismatch($E, $O) {
    $me = S-Bool $E['elevated']
    $ol = S-Bool $O['ol_elevated']
    if ($null -eq $me -or $null -eq $ol) { return ($me -eq $true) }
    return ($me -ne $ol)
}

function Decide-Outlook($E, $O, $Com, [string]$ComState, [string]$InstState) {
    # mail.com · cal.com 두 키를 함께 판정한다. 반환 @(mail, cal)
    if ($null -eq $O) { return @((New-MissingCap $InstState), (New-MissingCap $InstState)) }
    $rs = @{}
    $st = $null
    $lang = [string]$E['language_mode']
    $classic = B $O['classic']
    $newOnly = Test-NewOnly $O
    $profiles = S-Int $O['profiles']
    $mismatch = ($O['com_registered'] -eq $false) -or ($O['com_server_match'] -eq $false) -or ((B $O['c2r']) -and (B $O['msi']))
    if ($lang -and $lang -ne 'FullLanguage') { $rs['R-CLM'] = 1; $st = 'fail' }
    elseif ($newOnly) { $rs['R-NEWOL'] = 1; $st = 'fail' }
    elseif (-not $classic) { $st = 'fail' }
    elseif ($profiles -eq 0) { $rs['R-NOPROF'] = 1; $st = 'fail' }
    if ($classic -and (Test-OfficeEol $O)) { $rs['R-OFFICE'] = 1 }
    if ($classic -and -not $newOnly -and $mismatch -and $profiles -ne 0) { $rs['R-WIZARD'] = 1 }
    $attach = [string](P $Com 'attach')
    if (-not $st) {
        if ($ComState -eq 'not_attempted' -or $ComState -eq 'skipped') {
            if ($mismatch) { $st = 'fail' } else { $st = 'unknown' }
            if (-not $attach) { $attach = $ComState }
            if ($ComState -eq 'not_attempted' -and -not (B $O['running'])) { $attach = 'not_running' }
        } elseif ($ComState -eq 'budget') {
            if ($attach -eq 'ok') { $st = 'ok' } else { $st = 'unknown'; $attach = 'budget' }
            $rs['R-BUDGET'] = 1
        } elseif ($ComState -eq 'timeout' -or $ComState -eq 'crash') {
            $rs['R-TRANSPORT'] = 1; $st = 'transport_fail'
            if ($attach -ne 'ok') { $attach = $ComState }
        } else {
            if ($attach -eq 'ok') { $st = 'ok' }
            elseif ($attach -eq 'unavailable') {
                if (Test-ElevMismatch $E $O) { $rs['R-ELEV'] = 1 } else { $rs['R-DIALOG'] = 1 }
                $st = 'fail'
            } elseif ($attach -eq 'rejected') { $rs['R-COM-BUSY'] = 1; $st = 'transport_fail' }
            else { $rs['R-TRANSPORT'] = 1; $st = 'transport_fail'; if (-not $attach) { $attach = 'error' } }
        }
    } elseif (-not $attach) { $attach = 'not_attempted' }
    $omgExp = Test-OmgExpected $O
    $pr = [string](P $Com 'protected_read')
    $omg = $null
    if ($attach -eq 'ok') { $omg = ($omgExp -or $pr -eq 'blocked' -or $pr -eq 'timeout') }
    elseif ($attach -eq 'not_running') { $omg = $omgExp }
    # 메일 고유 경고(붙었을 때만): 기본 폴더 밖 비중·OST 신선도·OMG
    $mrs = @{}
    foreach ($k in $rs.Keys) { $mrs[$k] = 1 }
    $crs = @{}
    foreach ($k in $rs.Keys) { $crs[$k] = 1 }
    if ($omg -eq $true) { $mrs['R-OMG'] = 1; $crs['R-OMG'] = 1 }
    $total = S-Int (P $Com 'mail_total')
    $def = S-Int (P $Com 'mail_default')
    $ratio = $null
    if ($null -ne $total -and $null -ne $def -and $total -gt 0) { $ratio = S-Num (($total - $def) / [double]$total) }
    if ($attach -eq 'ok' -and $null -ne $ratio -and $ratio -ge [double]$script:Cfg['probe.subfolderRatio']) { $mrs['R-SUBFOLDER'] = 1 }
    $newest = Parse-Utc (P $Com 'inbox_newest')
    $oldest = Parse-Utc (P $Com 'inbox_oldest')
    $ageH = $null
    if ($null -ne $newest) {
        $hrs = ((Get-NowUtc) - $newest).TotalHours
        try { $ageH = [long][Math]::Floor($hrs) } catch { $ageH = [long]$hrs }
    }
    $cached = S-Bool (P $Com 'cached')
    if ($attach -eq 'ok' -and $null -ne $ageH -and $ageH -gt [double]$script:Cfg['probe.ostStaleH'] -and $cached -ne $false) { $mrs['R-STALE'] = 1 }
    $hr = S-Rx (P $Com 'hresult') $RX_HR
    $vp = Get-VersionParts ([string]$O['version'])
    $common = [ordered]@{
        classic = $classic; version = (S-Rx $O['version'] $RX_VER); c2r = (S-Bool $O['c2r']); msi = (S-Bool $O['msi'])
        new_outlook = $newOnly; use_new = (S-Bool $O['use_new']); profiles = $profiles
        com_registered = (S-Bool $O['com_registered']); com_server_match = (S-Bool $O['com_server_match'])
        running = (S-Bool $O['running']); attach = $attach; hresult = $hr; omg = $omg
        omg_policy = (S-Enum $O['omg_policy'] $OMG_POLICIES); av_state = (S-Enum $O['av_state'] $AV_STATES)
        office_eol = ($classic -and (Test-OfficeEol $O))
    }
    $mv = [ordered]@{}
    foreach ($k in $common.Keys) { $mv[$k] = $common[$k] }
    $mv['exchange_mode'] = S-Int (P $Com 'exchange_mode')
    $mv['cached'] = $cached
    $mv['cached_policy'] = S-Enum $O['cached_policy'] @('on', 'off')
    $mv['sync_months'] = S-Int $O['sync_months']
    $mv['stores'] = S-Int (P $Com 'stores')
    $sty = [ordered]@{}
    $styIn = P $Com 'store_types'
    foreach ($n in $STORE_TYPES) { $x = S-Int (P $styIn $n); if ($null -ne $x) { $sty[$n] = $x } }
    $mv['store_types'] = $sty
    $mv['migration_policy'] = S-Int $O['migration_policy']
    $mv['folders'] = S-Int (P $Com 'folders')
    $mv['folders_capped'] = S-Bool (P $Com 'folders_capped')
    $mv['mail_total'] = $total
    $mv['subfolder_ratio'] = $ratio
    $mv['horizon_oldest'] = $null
    $mv['horizon_newest'] = $null
    if ($null -ne $oldest) { $mv['horizon_oldest'] = $oldest.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) }
    if ($null -ne $newest) { $mv['horizon_newest'] = $newest.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) }
    $mv['newest_age_h'] = $ageH
    foreach ($k in @('sent_oldest', 'sent_newest')) {
        $d = Parse-Utc (P $Com $k)
        $mv['sent_horizon_' + $k.Substring(5)] = $null
        if ($null -ne $d) { $mv['sent_horizon_' + $k.Substring(5)] = $d.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) }
    }
    $mv['protected_read'] = S-Enum $pr @('ok', 'blocked', 'timeout', 'skipped')
    $mv['attach_ms'] = S-Int (P $Com 'attach_ms')
    $cv = [ordered]@{}
    foreach ($k in $common.Keys) { $cv[$k] = $common[$k] }
    $cv['cal_items'] = S-Int (P $Com 'cal_items')
    $sig = @('ol', $lang, $classic, $newOnly, $vp[0], (B $O['c2r']), (B $O['msi']), ($profiles -gt 0), (Get-Fnv ([string]$O['profile_name'])),
        $mismatch, (S-Bool $E['elevated']), (S-Bool $O['ol_elevated']), [string]$O['omg_policy'], [string]$O['av_state'])
    return @((New-Cap $st $mrs $mv $sig), (New-Cap $st $crs $cv $sig))
}

function Test-Online($O, $Com) {
    if ([string](P $Com 'attach') -eq 'ok' -and (P $Com 'cached') -eq $false) { return $true }
    return ([string]$O['cached_policy'] -eq 'off')
}

function Decide-Index($E, $O, $I, $Com, [string]$Kind, [string]$GroupState) {
    if ($null -eq $I) { return (New-MissingCap $GroupState) }
    $rs = @{}
    $st = $null
    $lang = [string]$E['language_mode']
    $svc = S-Enum $I['service'] $IDX_SERVICE
    $cnt = $I[$Kind]
    $n = S-Int (P $cnt 'n365')
    $cs = S-Int $I['catalog_status']
    $paused = ($null -ne $cs -and $cs -ge 1 -and $cs -le 3)
    if ($lang -and $lang -ne 'FullLanguage') { $rs['R-CLM'] = 1; $st = 'fail' }
    elseif ($svc -eq 'stopped' -or $svc -eq 'disabled' -or $svc -eq 'missing' -or -not (B $I['connect'])) { $rs['R-NOIDX'] = 1; $st = 'fail' }
    elseif (B $I['policy_outlook']) { $rs['R-IDXPOLICY'] = 1; $st = 'fail' }
    elseif ($null -ne $n -and $n -gt 0) { $st = 'ok'; if ($paused) { $rs['R-IDXPAUSED'] = 1 } }
    elseif ($paused) { $rs['R-IDXPAUSED'] = 1; $st = 'fail' }
    elseif (Test-NewOnly $O) { $rs['R-NEWOL'] = 1; $st = 'fail' }
    elseif ($null -ne $O -and (B $O['classic']) -and (S-Int $O['profiles']) -eq 0) { $rs['R-NOPROF'] = 1; $st = 'fail' }
    elseif ($null -ne $O -and (Test-Online $O $Com)) { $rs['R-ONLINE'] = 1; $st = 'fail' }
    elseif ($null -eq $n) { $st = 'unknown' }
    else { $st = 'ok' }
    $v = [ordered]@{
        service = $svc; connect = (S-Bool $I['connect']); policy = (S-Bool $I['policy_outlook']); catalog_status = $cs
        paused_reason = (S-Int $I['paused_reason']); ext_props = (S-Bool $I['ext_props'])
        n_30d = (S-Int (P $cnt 'n30')); n_90d = (S-Int (P $cnt 'n90')); n_365d = $n
        newest = $null; oldest = $null; capped = (S-Bool (P $cnt 'capped'))
    }
    $nw = Parse-Utc (P $cnt 'newest')
    $od = Parse-Utc (P $cnt 'oldest')
    if ($null -ne $nw) { $v['newest'] = $nw.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) }
    if ($null -ne $od) { $v['oldest'] = $od.ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) }
    if ($Kind -eq 'cal') { $v['recurring'] = S-Int (P $cnt 'recurring') }
    $online = $false
    if ($null -ne $O) { $online = Test-Online $O $Com }
    return (New-Cap $st $rs $v @('idx', $Kind, $lang, $svc, (B $I['connect']), (B $I['policy_outlook']), (Test-NewOnly $O),
            ($null -ne $O -and (S-Int $O['profiles']) -gt 0), $online))
}

function Decide-Edge($F, [string]$GroupState) {
    if ($null -eq $F) { return (New-MissingCap $GroupState) }
    $rs = @{}
    $rd = S-Int $F['remote_debugging']
    $dt = S-Int $F['devtools']
    if (-not (B $F['installed'])) { $st = 'fail' }
    elseif (($null -ne $rd -and $rd -eq 0) -or ($null -ne $dt -and $dt -eq 2)) { $rs['R-EDGEPOL'] = 1; $st = 'fail' }
    else { $st = 'ok' }
    $v = [ordered]@{ installed = (B $F['installed']); version = (S-Rx $F['version'] $RX_VER); remote_debugging = $rd; devtools = $dt
        profile = (S-Bool $F['profile']) }
    return (New-Cap $st $rs $v @('edge', (B $F['installed']), $rd, $dt))
}

function Decide-Teams($E, $T, $U, [string]$UState, [string]$GroupState) {
    if ($null -eq $T) { return (New-MissingCap $GroupState) }
    $rs = @{}
    $st = $null
    $lang = [string]$E['language_mode']
    $inst = (B $T['new_installed']) -or (B $T['classic_installed'])
    $procs = S-Int $T['processes']
    $u = $U
    $lines = [long](S-Int (P $u 'lines'))
    $denied = [long](S-Int (P $u 'denied'))
    $vis = S-Int (P $u 'visible')
    $uia = $UState
    if ($lang -and $lang -ne 'FullLanguage') { $rs['R-CLM'] = 1; $st = 'fail' }
    elseif (-not $inst) { $st = 'fail' }
    elseif ($UState -eq 'not_running') { $st = 'unknown' }
    elseif ($UState -eq 'not_attempted') { $st = 'unknown' }
    elseif ($UState -eq 'budget') {
        if ($lines -gt 0) { $st = 'ok' } else { $st = 'unknown' }
        $rs['R-BUDGET'] = 1
    } elseif ($UState -eq 'timeout' -or $UState -eq 'crash') {
        if ($lines -gt 0) { $st = 'ok' } else { $rs['R-TRANSPORT'] = 1; $st = 'transport_fail' }
    } else {
        $uia = 'ok'
        if ($null -eq $vis -or $vis -eq 0) { $rs['R-UIAEMPTY'] = 1; $st = 'fail'; $uia = 'none' }
        elseif ($lines -gt 0) { $st = 'ok' }
        elseif ($denied -gt 0) { $rs['R-UIAELEV'] = 1; $st = 'fail'; $uia = 'denied' }
        else { $rs['R-UIAEMPTY'] = 1; $st = 'fail'; $uia = 'empty' }
    }
    $v = [ordered]@{
        new_installed = (S-Bool $T['new_installed']); new_version = (S-Rx $T['new_version'] $RX_VER)
        classic_installed = (S-Bool $T['classic_installed']); classic_version = (S-Rx $T['classic_version'] $RX_VER)
        processes = $procs; uia = $uia; windows = (S-Int (P $u 'windows')); visible = $vis; uia_lines = (S-Int (P $u 'lines'))
        time_matches = (S-Int (P $u 'time_matches')); generic_matches = (S-Int (P $u 'generic_matches')); denied = (S-Int (P $u 'denied'))
        capped = (S-Bool (P $u 'capped')); uia_ms = (S-Int (P $u 'uia_ms'))
    }
    return (New-Cap $st $rs $v @('teams', $lang, (B $T['new_installed']), (B $T['classic_installed'])))
}

function Decide-Sampler($E) {
    $rs = @{}
    $lang = [string]$E['language_mode']
    $ps = $null
    if ($lang -and $lang -ne 'FullLanguage') { $ps = $false }
    elseif ($E['addtype'] -eq 'ok') { $ps = $true }
    elseif ($E['addtype'] -eq 'fail') { $ps = $false }
    $ct = Get-Ctypes $E
    $py = $null
    if ($ct -eq 'ok') { $py = $true } elseif ($ct -eq 'fail' -or $ct -eq 'blocked') { $py = $false }
    if ($ps -eq $true -or $py -eq $true) { $st = 'ok' }
    elseif ($ps -eq $false) {
        # 두 구현 모두 불가 — 정책 차단(동봉 python.exe 실행 거부, 또는 전체 언어 모드인데 Add-Type 거부)이면 R-APPLOCKER
        if ($ct -eq 'blocked' -or ($lang -eq 'FullLanguage' -and $E['addtype'] -eq 'fail')) { $rs['R-APPLOCKER'] = 1 } else { $rs['R-CLM'] = 1 }
        $st = 'fail'
    } else { $st = 'unknown' }
    $v = [ordered]@{ ps = $ps; py = $py }
    return (New-Cap $st $rs $v @('sampler', $lang, $E['addtype'], $ct))
}

# PS 수집기(Get-EventActivity·Get-RecentFiles·Get-OfficeMru)는 제한 언어 모드에서 돌지 못한다(첫 실행문에서 rc 3 + R-CLM —
# 계약 v1.2 §0.7 C1·C4). 그래서 그 경로의 능력도 언어 모드를 본다(W1 통합 창 결함 수정: 전에는 CLM 에서도 '가능').
function Test-PsClm($E) {
    if ($null -eq $E) { return $false }
    $lang = [string]$E['language_mode']
    return [bool]($lang -and $lang -ne 'FullLanguage')
}

function Decide-Events($F, [string]$GroupState, $E = $null) {
    if ($null -eq $F) { return (New-MissingCap $GroupState) }
    $rs = @{}
    $evs = $F['events']
    $errs = $F['event_errors']
    $v = [ordered]@{}
    $sigp = @('events')
    foreach ($k in $CHANNELS.Keys) {
        $s = S-Enum (P $evs $k) $CH_STATES
        $v[$k] = $s
        $sigp += [string]$s
        if ($s -eq 'unauthorized') { $rs['R-NOEVT'] = 1 }
    }
    $et = [ordered]@{}
    foreach ($k in $CHANNELS.Keys) { $t = S-Rx (P $errs $k) $RX_TYPE; if ($null -ne $t) { $et[$k] = $t } }
    $v['error_types'] = $et
    $sys = $v['system']
    if ($sys -eq 'ok' -or $sys -eq 'none') { $st = 'ok' }
    elseif ($sys -eq 'unauthorized') { $st = 'fail' }
    else { $st = 'unknown' }
    if (Test-PsClm $E) { $rs['R-CLM'] = 1; $st = 'fail'; $sigp += 'clm' }
    return (New-Cap $st $rs $v $sigp)
}

function Decide-Recent($F, [string]$GroupState, $E = $null) {
    if ($null -eq $F) { return (New-MissingCap $GroupState) }
    $rs = @{}
    $pol = B $F['recent_policy']
    $n = S-Int $F['lnk']
    if ($pol) { $rs['R-RECENTPOLICY'] = 1; $st = 'fail' }
    else { $st = 'ok'; if ($null -ne $n -and $n -eq 0) { $rs['R-MRUEMPTY'] = 1 } }
    $sigp = @('recent', $pol)
    if (Test-PsClm $E) { $rs['R-CLM'] = 1; $st = 'fail'; $sigp += 'clm' }
    return (New-Cap $st $rs ([ordered]@{ policy = $pol; lnk = $n }) $sigp)
}

function Decide-Mru($F, [string]$GroupState, $E = $null) {
    if ($null -eq $F) { return (New-MissingCap $GroupState) }
    $rs = @{}
    $n = S-Int $F['mru']
    $vers = @()
    foreach ($x in @($F['office_versions'])) { $s = S-Rx $x '^\d{1,2}\.\d$'; if ($null -ne $s) { $vers += $s } }
    $st = 'ok'
    if ($null -eq $n) { $st = 'unknown' } elseif ($n -eq 0) { $rs['R-MRUEMPTY'] = 1 }
    $sigp = @('mru', ($vers -join ','))
    if (Test-PsClm $E) { $rs['R-CLM'] = 1; $st = 'fail'; $sigp += 'clm' }
    return (New-Cap $st $rs ([ordered]@{ items = $n; versions = $vers }) $sigp)
}

function Decide-Git($F, [string]$GroupState) {
    if ($null -eq $F) { return (New-MissingCap $GroupState) }
    $rs = @{}
    $found = B $F['git']
    if ($found) { $st = 'ok' } else { $rs['R-NOGIT'] = 1; $st = 'fail' }
    return (New-Cap $st $rs ([ordered]@{ found = $found; src = (S-Enum $F['git_src'] $GIT_SRC) }) @('git', $found))
}

# ───────────────────────────── 부모: 본체 ─────────────────────────────
function Invoke-Step([string]$Group, [bool]$Wanted, [scriptblock]$Body) {
    # 예산이 1초 넘게 남았으면 사실 모으기를 하고 $true(끝의 판정·출력 몫을 남긴다). 아니면 그룹을 budget 으로 표시하고 $false.
    if ((Get-Left) -le 1.0) {
        $script:BudgetHit = $true
        if ($Wanted) { $script:G[$Group] = 'budget' }
        return $false
    }
    try {
        & $Body
        if ($Wanted) { $script:G[$Group] = 'done' }
    } catch {
        if ($Wanted) { $script:G[$Group] = 'error' }
    }
    return $true
}

function Invoke-Main {
    $script:TestNowUtc = $null
    if ($TestNow) { $script:TestNowUtc = Parse-Utc $TestNow }
    $in = Read-StdinKey '_in'
    $script:Cfg = Merge-Cfg (P $in 'cfg')
    $script:Deadline = $script:T0.AddSeconds([double]$script:Cfg['probe.budgetSec'])
    $script:OnlyGiven = [bool]$Only.Trim()
    $script:OnlySet = Get-OnlySet $Only
    $stub = Get-StubEnv
    $warn = @()
    if ($stub.Count) { $warn += 'stub_env_set' }
    $fakePath = Get-EnvVar 'LM_PROBE_FAKE'
    $script:FakeMode = [bool]$fakePath
    $script:Fake = $null
    if ($script:FakeMode) {
        $script:Fake = Read-JsonFile $fakePath
        if ($null -eq $script:Fake) { $warn += 'fake_unreadable' }
    }
    # LM_OUTLOOK_SELFTEST=N[,선택…] — Get-OutlookCom.ps1 과 같은 문법(앞 정수만 쓴다). 값이 있으면 무조건 시험 모드:
    # 해석이 안 되는 값이어도 실물 Outlook·COM 을 건드리지 않는다(W1a 통합 관문 — WP-15·WP-17 주입점 일치).
    $script:SelfTestN = 0
    $stn = Get-EnvVar 'LM_OUTLOOK_SELFTEST'
    $script:SelfTestOn = [bool]$stn.Trim()
    if ($script:SelfTestOn) {
        $n0 = 0
        [void][int]::TryParse(([string]$stn.Split(',')[0]).Trim(), [ref]$n0)
        $script:SelfTestN = [math]::Max(0, $n0)
    }
    $script:IndexFake = Get-EnvVar 'LM_INDEX_FAKE'
    $synthetic = $script:FakeMode -or $script:SelfTestOn -or [bool]$script:IndexFake

    $script:G = [ordered]@{}
    foreach ($g in $GROUPS) { $script:G[$g] = 'skipped' }
    $wEnv = Test-Want 'P-ENV'; $wInst = Test-Want 'P-OL-INST'; $wCom = Test-Want 'P-OL-COM'; $wIdx = Test-Want 'P-IDX'
    $wEdge = Test-Want 'P-EDGE'; $wTeams = Test-Want 'P-TEAMS'; $wPc = Test-Want 'P-PC'
    $F = @{ env = $null; ol = $null; com = $null; idx = $null; edge = $null; teams = $null; uia = $null; pc = $null }
    $comState = 'skipped'
    $uiaState = 'not_attempted'

    # 순서: 싼 사실(레지스트리·서비스) 먼저, 자식이 필요한 COM·UIA 는 끝에 — 예산이 모자라도 싼 사실은 남는다.
    $F.env = Get-EnvFacts ($wEnv -or $wPc)
    if ($wEnv) { $script:G['P-ENV'] = 'done' }
    $olRan = $false
    if ($wInst -or $wCom -or $wIdx) { $olRan = Invoke-Step 'P-OL-INST' $wInst { $F.ol = Get-OlFacts } }
    if ($wEdge) { $null = Invoke-Step 'P-EDGE' $true { $F.edge = Get-EdgeFacts } }
    if ($wPc) { $null = Invoke-Step 'P-PC' $true { $F.pc = Get-PcFacts } }
    if ($wIdx) { $null = Invoke-Step 'P-IDX' $true { $F.idx = Get-IdxFacts } }
    if ($wCom) {
        if (-not $olRan) { $comState = 'budget'; $script:G['P-OL-COM'] = 'budget' }
        elseif ($null -eq $F.ol) { $comState = 'not_attempted'; $script:G['P-OL-COM'] = 'done' }
        elseif (Invoke-Step 'P-OL-COM' $true { $x = Invoke-ComProbe $F.env $F.ol; $F.com = $x.r; $F.comState = $x.state }) {
            $comState = [string]$F.comState
            if ($comState -eq 'budget') { $script:G['P-OL-COM'] = 'budget' }
        } else { $comState = 'budget' }
    }
    if ($wTeams) {
        $null = Invoke-Step 'P-TEAMS' $true {
            $F.teams = Get-TeamsFacts
            $x = Invoke-UiaProbe $F.env $F.teams
            $F.uia = $x.r
            $F.uiaState = $x.state
        }
        if ($F.uiaState) { $uiaState = [string]$F.uiaState }
        if ($uiaState -eq 'budget') { $script:G['P-TEAMS'] = 'budget' }
    }

    $caps = [ordered]@{}
    if ($wEnv) { $caps['env'] = Decide-Env $F.env }
    if ($wInst -or $wCom) {
        $instState = [string]$script:G['P-OL-INST']
        if (-not $wInst) { $instState = [string]$script:G['P-OL-COM'] }
        $pair = Decide-Outlook $F.env $F.ol $F.com $comState $instState
        $caps['mail.com'] = $pair[0]
        $caps['cal.com'] = $pair[1]
    }
    if ($wIdx) {
        $caps['mail.index'] = Decide-Index $F.env $F.ol $F.idx $F.com 'mail' ([string]$script:G['P-IDX'])
        $caps['cal.index'] = Decide-Index $F.env $F.ol $F.idx $F.com 'cal' ([string]$script:G['P-IDX'])
    }
    if ($wEdge) { $caps['edge_cdp_policy'] = Decide-Edge $F.edge ([string]$script:G['P-EDGE']) }
    if ($wTeams) { $caps['teams.uia'] = Decide-Teams $F.env $F.teams $F.uia $uiaState ([string]$script:G['P-TEAMS']) }
    if ($wPc) {
        $gs = [string]$script:G['P-PC']
        $caps['pc.sampler'] = Decide-Sampler $F.env
        $caps['pc.events'] = Decide-Events $F.pc $gs $F.env
        $caps['pc.recent'] = Decide-Recent $F.pc $gs $F.env
        $caps['pc.mru'] = Decide-Mru $F.pc $gs $F.env
        $caps['pc.git'] = Decide-Git $F.pc $gs
    }

    $used = [ordered]@{}
    foreach ($k in $CFG_NUMERIC) { $used[$k] = $script:Cfg[$k] }
    $out = [ordered]@{
        schema     = $SCHEMA
        now_utc    = (Format-Utc (Get-NowUtc))
        elapsed_ms = [long](([DateTime]::UtcNow - $script:T0).TotalMilliseconds)
        budget_sec = $script:Cfg['probe.budgetSec']
        budget_hit = [bool]$script:BudgetHit
        synthetic  = [bool]$synthetic
        groups     = $script:G
        warnings   = $warn
        stub_env   = $stub
        cfg_used   = $used
        caps       = $caps
    }
    Write-Line (To-Json $out)
    $codes = @()
    foreach ($k in $caps.Keys) { foreach ($c in @($caps[$k]['reasons'])) { if ($c -and $codes -notcontains $c) { $codes += $c } } }
    $sec = '{0:0.0}' -f ($out['elapsed_ms'] / 1000.0)
    $bh = ''
    if ($script:BudgetHit) { $bh = ' · 예산 소진' }
    $rsTxt = '없음'
    if ($codes.Count) { $rsTxt = (@($codes | Sort-Object) -join ' ') }
    Write-Diag ("[탐침] 항목 {0}개 · {1}초 · 예산 {2}초{3} · 사유: {4}" -f $caps.Count, $sec, $script:Cfg['probe.budgetSec'], $bh, $rsTxt)
}

# ───────────────────────────── 진입 ─────────────────────────────
if ($Child) {
    Invoke-ProbeChild $Child
    exit $script:ChildRc
}
$rc = 0
try {
    Invoke-Main
} catch {
    $rc = 3
    Write-Line (To-Json ([ordered]@{ schema = $SCHEMA; fatal = (S-Rx (Get-TypeName $_.Exception) $RX_TYPE) }))
    Write-Diag '[탐침] 내부 오류 — 결과를 내지 못했습니다(rc 3)'
}
exit $rc
