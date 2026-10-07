# Test-PcCollect.ps1 - WP4 PC 수집기 보강(시험 p4). 단언은 tests\test_p4_pc.py 가 한다 - 여기서는 값만 모은다.
# 실제 이벤트 로그·Office 레지스트리는 건드리지 않는다(함수는 -LibOnly 로 dot-source).
# 외부 프로세스: 내장 파이썬 2회(Get-PcOnHistory 의 원장 반영 - 잠금 선점 실패 1회 + 정상 1회)뿐이다.
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$col = Join-Path $root 'collect'
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('lm28_t4_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$utf8 = [System.Text.Encoding]::UTF8
$r = @{}
$lockFs = $null
try {
    # (1) 확인 경로에 BEL(0x07)이 없다 · 고친 PS 파일 구문 오류 0
    $mine = @('Get-PcOnHistory.ps1', 'Get-RecentFiles.ps1', 'Get-FileActivity.ps1', 'Add-WorkLog.ps1')
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

    # (2) Office MRU 가짜 해시 → 5건 (14/15/16 × File MRU·User MRU, Place MRU·12.0·시각 없는 값·Max Display 는 제외)
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

    # (3) Add-WorkLog -Start/-End (옛 6열 머리말 파일 → 새 머리말)
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

    # (4) Get-PcOnHistory - 원장 잠금 선점 → 원장 반영 실패 rc 3 + LMSTATUS R-INGEST · 관측 보존 → 풀면 함께 반영
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
