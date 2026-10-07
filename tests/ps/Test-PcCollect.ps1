# Test-PcCollect.ps1 - WP4 PC 수집기·창 샘플러 보강(시험 p4). 단언은 tests\test_p4_pc.py 가 한다 - 여기서는 값만 모은다.
# 실제 작업 스케줄러·이벤트 로그·Office 레지스트리·샘플러 루프는 건드리지 않는다(함수는 -LibOnly 로 dot-source).
# 외부 프로세스: 내장 파이썬 2회(Get-PcOnHistory 의 원장 반영 - 잠금 선점 실패 1회 + 정상 1회)뿐이다.
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$col = Join-Path $root 'collect'
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('lm28_t4_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$utf8 = [System.Text.Encoding]::UTF8
$fmt = 'yyyy-MM-dd HH:mm:ss'
$r = @{}
$lockFs = $null
try {
    # (1) 확인 경로에 BEL(0x07)이 없다 · 고친 PS 파일 구문 오류 0
    $mine = @('Start-ActivitySampler.ps1', 'Register-Samplers.ps1', 'Get-PcOnHistory.ps1', 'Get-RecentFiles.ps1', 'Get-FileActivity.ps1', 'Add-WorkLog.ps1')
    $bel = @(); $perr = @()
    foreach ($f in $mine) {
        $p = Join-Path $col $f
        if ([System.IO.File]::ReadAllText($p).IndexOf([char]7) -ge 0) { $bel += $f }
        $tok = $null; $errs = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($p, [ref]$tok, [ref]$errs)
        foreach ($e in @($errs)) { $perr += ('{0}:{1}: {2}' -f $f, $e.Extent.StartLineNumber, $e.Message) }
    }
    $r.bel_files = @($bel)
    $r.parse_errors = @($perr)

    # (2) Register-Samplers -LibOnly - 확인 경로·등록 흔적·heartbeat 판정 (샘플러의 상태 함수도 함께 들어온다)
    . (Join-Path $col 'Register-Samplers.ps1') -LibOnly
    $r.act_dir_ok = ($actDir -eq [System.IO.Path]::Combine($root, 'data', 'activity'))
    $r.act_dir_bel = ($actDir.IndexOf([char]7) -ge 0)
    $regDir = Join-Path $tmp 'reg'
    $null = Write-SamplerStatus $regDir @{ ok = $true; heartbeat = '2026-01-01 09:00:00'; interval_s = 60 }
    $r.reg_write_ok = [bool](Set-SamplerRegistered $regDir 'LM28-Sampler-abcdef' $true)
    $st = Read-SamplerStatus $regDir
    $r.reg_registered = $st['registered']
    $r.reg_task = [string]$st['task']
    $r.reg_at_ok = ([string]$st['at'] -match '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
    $r.reg_keeps_heartbeat = [string]$st['heartbeat']
    $null = Write-SamplerStatus $regDir @{ ok = $true; heartbeat = '2026-01-01 09:01:00' }      # 샘플러 틱
    $r.hb_keeps_registered = (Read-SamplerStatus $regDir)['registered']
    $now = Get-Date
    $null = Write-SamplerStatus $regDir @{ heartbeat = $now.ToString($fmt); interval_s = 60 }
    $r.hb_fresh = Test-SamplerHeartbeat $regDir $now.AddSeconds(-1)
    $null = Write-SamplerStatus $regDir @{ heartbeat = $now.AddMinutes(-10).ToString($fmt) }
    $r.hb_stale = Test-SamplerHeartbeat $regDir $now
    $null = Write-SamplerStatus $regDir @{ ok = $false; reason = 'R-ADDTYPE'; failed_at = $now.ToString($fmt) }
    $r.hb_fail = Test-SamplerHeartbeat $regDir $now.AddSeconds(-1)
    $null = Set-SamplerRegistered $regDir 'LM28-Sampler-abcdef' $false
    $r.unreg = (Read-SamplerStatus $regDir)['registered']
    $r.status_tmp_left = @(Get-ChildItem -LiteralPath $regDir -Filter '*.tmp').Count

    # (3) 세션 상태(가짜 LogonUI)·솔버 CPU 차분 - 샘플러 순수 함수
    $r.sess_logonui_fg = Get-SessState 'LogonUI' @() 0
    $r.sess_lockapp_fg = Get-SessState 'lockapp' @() 0
    $r.sess_logonui_present = Get-SessState '' @('LogonUI') 0
    $r.sess_active = Get-SessState 'excel' @() 0
    $r.sess_disc = Get-SessState 'excel' @() 4
    $r.sess_unknown = Get-SessState 'excel' @() -1
    $t0 = [datetime]::ParseExact('2026-03-02 10:00:00', $fmt, $null)
    $c1 = Get-SolverCpuDelta $null @(@{ id = 100; cpu = 10.0; start = $t0.AddHours(-1) }) $null
    $r.cpu_first = $c1.delta
    $c2 = Get-SolverCpuDelta $c1.next @(
        @{ id = 100; cpu = 40.5; start = $t0.AddHours(-1) },      # 이어서 돈 솔버: +30.5
        @{ id = 300; cpu = 3.0; start = $t0.AddSeconds(30) },     # 직전 틱 뒤에 뜬 솔버: +3.0 전부
        @{ id = 400; cpu = 99.0; start = $t0.AddHours(-2) },      # 직전에 못 본(기준 없는) 오래된 프로세스: 0
        @{ id = 500; cpu = $null; start = $null }) $t0             # 권한 없어 못 읽음: 0
    $r.cpu_delta = $c2.delta
    $c3 = Get-SolverCpuDelta $c2.next @(@{ id = 100; cpu = 41.0; start = $t0.AddHours(-1) }) $t0.AddMinutes(1)
    $r.cpu_delta2 = $c3.delta
    $oldCul = [System.Threading.Thread]::CurrentThread.CurrentCulture
    try {
        [System.Threading.Thread]::CurrentThread.CurrentCulture = [System.Globalization.CultureInfo]::GetCultureInfo('de-DE')
        $r.fmt_num_de = Format-Num 33.5           # 소수점이 ',' 인 지역에서도 CSV 가 밀리지 않는다
    } finally { [System.Threading.Thread]::CurrentThread.CurrentCulture = $oldCul }

    # (4) 같은 날 옛 7열 파일 → 머리말만 새 것으로
    $af = Join-Path $tmp 'activity_20260302.csv'
    [System.IO.File]::WriteAllText($af, "time,process,title,idle_sec,solvers_running,user,host`r`n2026-03-02 09:00:00,excel,a,0,,u,h`r`n", $utf8)
    $r.hdr_upgraded = Update-ActivityHeader $af (Get-ActivityHeader)
    $al = [System.IO.File]::ReadAllLines($af, $utf8)
    $r.hdr_line = $al[0]
    $r.hdr_rows = $al.Count
    $r.hdr_row1 = $al[1]
    $bf = Join-Path $tmp 'other.csv'
    [System.IO.File]::WriteAllText($bf, "a,b,c`r`n1,2,3`r`n", $utf8)
    $r.hdr_unknown = Update-ActivityHeader $bf (Get-ActivityHeader)

    # (5) 제한 언어 모드 → R-CLM (실제 ConstrainedLanguage 런스페이스에서 샘플러를 돌린다 - Add-Type 까지 가지 않는다)
    $clmDir = Join-Path $tmp 'clm'
    $iss = [System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault()
    $iss.LanguageMode = [System.Management.Automation.PSLanguageMode]::ConstrainedLanguage
    try { $iss.ExecutionPolicy = [Microsoft.PowerShell.ExecutionPolicy]::Bypass } catch {}
    $rs = [runspacefactory]::CreateRunspace($iss)
    $rs.Open()
    $psi = [powershell]::Create()
    $psi.Runspace = $rs
    try {
        [void]$psi.AddCommand((Join-Path $col 'Start-ActivitySampler.ps1')).AddParameter('TestSamples', 1).AddParameter('OutDir', $clmDir)
        [void]$psi.Invoke()
        $r.clm_errors = @($psi.Streams.Error | ForEach-Object { [string]$_ } | Select-Object -First 3)
    } catch { $r.clm_errors = @([string]$_.Exception.Message) } finally { $psi.Dispose(); $rs.Dispose() }
    $cs = Read-SamplerStatus $clmDir
    $r.clm_reason = [string]$cs['reason']
    $r.clm_ok = $cs['ok']
    $r.clm_lang = [string]$cs['lang']
    $r.clm_csv = @(Get-ChildItem -LiteralPath $clmDir -Filter '*.csv' -ErrorAction SilentlyContinue).Count

    # (6) Office MRU 가짜 해시 → 5건 (14/15/16 × File MRU·User MRU, Place MRU·12.0·시각 없는 값·Max Display 는 제외)
    . (Join-Path $col 'Get-RecentFiles.ps1') -LibOnly
    $kb = 'HKEY_CURRENT_USER\Software\Microsoft\Office\'
    $fake = @{
        ($kb + '14.0\Word\File MRU') = @{ 'Item 1' = '[F00000000][T01D0A1B2C3D4E5F6]*C:\work\a.docx'; 'Item 2' = '[F00000000][T01D0A1B2C3D4E5F7][O00000000]*C:\work\b.doc'; 'Max Display' = '25' }
        ($kb + '15.0\Excel\File MRU') = @{ 'Item 1' = '[F00000000][T01D1A1B2C3D4E5F6][O00000000]*D:\proj\c.xlsx' }
        ($kb + '16.0\PowerPoint\User MRU\ADAL_TEST1\File MRU') = @{ 'Item 1' = '[F00000000][T01D9A1B2C3D4E5F6][O00000000]*\\server\share\d.pptx'; 'Item 2' = '[F00000000][T01D9A1B2C3D4E5F7][O00000000]*C:\work\e.pptx' }
        ($kb + '16.0\Word\User MRU\ADAL_TEST1\Place MRU') = @{ 'Item 1' = '[F00000000][T01D9A1B2C3D4E5F6][O00000000]*C:\work\' }
        ($kb + '12.0\Word\File MRU') = @{ 'Item 1' = '[F00000000][T01C0A1B2C3D4E5F6][O00000000]*C:\old\f.doc' }
        ($kb + '16.0\Excel\File MRU') = @{ 'Item 1' = 'no time stamp here' }
    }
    $mr = Get-MruItemsFromReg $fake $OfficeMruVersions
    $r.mru_items = @($mr.items).Count
    $r.mru_keys = [int]$mr.keys
    $r.mru_paths = @($mr.items | ForEach-Object { $_.path } | Sort-Object)
    $r.mru_versions = @($OfficeMruVersions)

    # (7) Add-WorkLog -Start/-End (옛 6열 머리말 파일 → 새 머리말)
    $wl = Join-Path $tmp 'manual'
    New-Item -ItemType Directory -Force -Path $wl | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $wl 'worklog.csv'), "date,category,hours,entity,note,user`r`n2026-03-01,trip,8,,,u`r`n", $utf8)
    $wlScript = Join-Path $col 'Add-WorkLog.ps1'
    $null = & $wlScript -Category 'site' -Start '09:30' -End '12:00' -Date '2026-03-02' -OutDir $wl *>&1
    $null = & $wlScript -Category 'night' -Start '22:00' -End '01:30' -Date '2026-03-02' -OutDir $wl *>&1
    $null = & $wlScript -Category 'fixed' -Hours 2 -Start '13:00' -End '17:00' -Date '2026-03-03' -OutDir $wl *>&1
    $wrows = @(Import-Csv -LiteralPath (Join-Path $wl 'worklog.csv') -Encoding UTF8)
    $r.wl_header = ([System.IO.File]::ReadAllLines((Join-Path $wl 'worklog.csv'), $utf8))[0]
    $r.wl_rows = @($wrows | ForEach-Object { '{0}|{1}|{2}|{3}|{4}' -f $_.date, $_.category, $_.hours, $_.start, $_.end })
    $bad = $false
    try { $null = & $wlScript -Category 'x' -Start '09:00' -OutDir $wl *>&1 } catch { $bad = $true }
    $r.wl_half_span_rejected = $bad

    # (8) Get-PcOnHistory - 원장 잠금 선점 → 원장 반영 실패 rc 3 + LMSTATUS R-INGEST · 관측 보존 → 풀면 함께 반영
    $py = Join-Path $root 'python\python.exe'
    if (Test-Path -LiteralPath $py) {
        $pcDir = Join-Path $tmp 'pc'
        New-Item -ItemType Directory -Force -Path $pcDir | Out-Null
        $ev = Join-Path $tmp 'ev.csv'
        [System.IO.File]::WriteAllText($ev, "t,kind`r`n2026-03-02 08:00,on`r`n2026-03-02 18:00,off`r`n2026-03-03 08:30,on`r`n2026-03-03 17:30,off`r`n", $utf8)
        $hist = Join-Path $col 'Get-PcOnHistory.ps1'
        $hargs = @{ EventsCsv = $ev; From = '2026-03-01'; To = '2026-03-03'; Now = '2026-03-03 20:00'; BootTime = '2026-03-03 08:30'; OutDir = $pcDir; Python = $py }
        $lockFs = [System.IO.File]::Open((Join-Path $pcDir '.ledger.lock'), [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::ReadWrite)
        $lockFs.Lock(0, 1)
        $o1 = @(& $hist @hargs *>&1 | ForEach-Object { [string]$_ })
        $r.pc_busy_rc = $LASTEXITCODE
        $lockFs.Unlock(0, 1); $lockFs.Dispose(); $lockFs = $null
        $r.pc_busy_status = [string](@($o1 | Where-Object { $_ -like 'LMSTATUS *' }) | Select-Object -Last 1)
        $r.pc_busy_last_is_status = ([string]($o1 | Select-Object -Last 1)) -like 'LMSTATUS *'
        $r.pc_busy_kept = Test-Path -LiteralPath (Join-Path $pcDir 'pc_events_new.csv')
        $r.pc_busy_spans = Test-Path -LiteralPath (Join-Path $pcDir 'pc_spans.csv')
        $o2 = @(& $hist @hargs *>&1 | ForEach-Object { [string]$_ })
        $r.pc_ok_rc = $LASTEXITCODE
        $r.pc_ok_status = [string](@($o2 | Where-Object { $_ -like 'LMSTATUS *' }) | Select-Object -Last 1)
        $r.pc_ok_merged_note = @($o2 | Where-Object { $_ -like '*반영하지 못한 관측*' }).Count
        $r.pc_ok_kept = Test-Path -LiteralPath (Join-Path $pcDir 'pc_events_new.csv')
        $r.pc_ok_span_rows = @(Import-Csv -LiteralPath (Join-Path $pcDir 'pc_spans.csv')).Count
        $srcj = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $pcDir 'pc_source.json') | ConvertFrom-Json
        $r.pc_channels = [string](($srcj.channels.PSObject.Properties | ForEach-Object { $_.Name + '=' + $_.Value }) -join ',')
    } else {
        $r.pc_skipped = 'python\python.exe 없음'
    }
} finally {
    if ($null -ne $lockFs) { try { $lockFs.Dispose() } catch {} }
    try { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}
$r.tmp_removed = -not (Test-Path -LiteralPath $tmp)
return $r
