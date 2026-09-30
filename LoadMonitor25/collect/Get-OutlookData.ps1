# Get-OutlookData.ps1 — bounded, read-only Outlook COM collection.
# Default account/store only: delivered mail folders and descendants, excluding
# Deleted/Junk/Drafts/Outbox, plus the default calendar with recurrence expansion.
# collection.mailAllFolders=false restricts mail to Inbox/Sent. No other account,
# shared/public mailbox or attachment contents are automatically expanded.
# Mail metadata + IDs/provenance + bounded Body text (collection.contextChars,
# default 4000). storeMailSubject=false also disables newly collected body text.
# Existing CSV history is atomically unioned, including rows outside this run's
# range. -Force recollects; it never replaces old history. -KeepDays is accepted
# for CLI compatibility and no longer deletes observations.
# coverage.json v3 tracks month/folder bounds and cursor overlap; changed folder
# scope or body settings invalidates old completion. Checkpoints retain partial
# results on limits/errors. Complete means only the declared local COM-visible
# scope was enumerated; it cannot verify server synchronization or all accounts.
# -SelfTest N is synthetic only, with explicit selftest writer/source markers.
# Usage: -From yyyy-MM-dd -To yyyy-MM-dd [-BudgetSec 360] [-Force] [-NoRefresh]
param(
    [string]$From = '',
    [string]$To = '',
    [int]$Days = 90,
    [int]$BudgetSec = 360,
    [switch]$Force,
    [switch]$NoRefresh,
    [int]$KeepDays = 400,
    [int]$SelfTest = 0,
    [int]$SelfTestDelayMs = 0
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # run.py 가 UTF-8 로 읽는다
$sw = [System.Diagnostics.Stopwatch]::StartNew()       # 시간 예산은 COM 연결까지 포함해 잰다(run.py 의 시계와 같다)
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $PSScriptRoot 'Outlook-Collection.ps1')
$cfg = $null
try { $cfg = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json } catch {}
$contextChars = 4000; $mailBody = $true; $mailAllFolders = $true
try { if ($null -ne $cfg.collection.contextChars) { $contextChars = [Math]::Min(20000, [Math]::Max(0, [int]$cfg.collection.contextChars)) } } catch {}
try { if ($null -ne $cfg.collection.mailBody) { $mailBody = [bool]$cfg.collection.mailBody } } catch {}
try { if ($null -ne $cfg.collection.mailAllFolders) { $mailAllFolders = [bool]$cfg.collection.mailAllFolders } } catch {}
$script:collectionProblems = New-Object 'System.Collections.Generic.List[string]'
$script:mailFolders = @()
$script:observedRows = 0
$script:observedCalendarRows = 0
$script:folderScope = ''
$script:previousFolderScope = ''
$storeSubject = $true
if ($cfg -and $cfg.PSObject.Properties['storeMailSubject'] -and -not $cfg.storeMailSubject) { $storeSubject = $false }
if ($BudgetSec -le 0) { $BudgetSec = 360 }
if ($KeepDays -le 0) { $KeepDays = 400 }
# 테스트 전용(run.py 를 거쳐도 자가검증을 돌릴 수 있게) - LM_COPILOT_STUB 과 같은 관례
if ($SelfTest -le 0 -and $env:LM_OUTLOOK_SELFTEST) { try { $SelfTest = [int]$env:LM_OUTLOOK_SELFTEST } catch {} }
if ($SelfTestDelayMs -le 0 -and $env:LM_OUTLOOK_SELFTEST_DELAY_MS) { try { $SelfTestDelayMs = [int]$env:LM_OUTLOOK_SELFTEST_DELAY_MS } catch {} }
$writer = $(if ($SelfTest) { 'selftest' } else { 'com' })
$outDir = Join-Path $root 'data\outlook'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$mailP = Join-Path $outDir 'mail.csv'
$calP  = Join-Path $outDir 'calendar.csv'
$covP  = Join-Path $outDir 'coverage.json'
$srcP  = Join-Path $outDir 'mail_source.json'
$MAIL_HEADER = 'box,time,sender,subject,conversation,rcv,time_precision,context_excerpt,context_truncated,source_id,source_kind,source_url,conversation_id,folder,account'
$CAL_HEADER  = 'start,end,all_day,busy_status,subject,categories,location,response,meeting_status'
$REFRESH_MONTHS = 2          # 최신 N개월은 이미 읽었어도 매번 다시 읽는다(-NoRefresh 면 안 한다)
$TS = 'yyyy-MM-dd HH:mm:ss'  # 표에 적는 시각 형식

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}
function Conv-Token([string]$s) {
    # storeMailSubject=false 일 때 conversation 열의 대체값 - 원문 대신 짧은 해시(회신 이력 판정만 유지).
    # 정규화(공백 접기·trim·소문자)와 SHA1 앞 10자리는 웹·Copilot·색인 경로와 같은 규칙이다.
    $n = (([string]$s -replace '\s+', ' ').Trim()).ToLower()
    if (-not $n) { return '' }
    $sha = [System.Security.Cryptography.SHA1]::Create()
    try { $h = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($n)) } finally { $sha.Dispose() }
    return '#' + ((($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 10))
}
function Test-MeInList([string]$list, [string[]]$ids) {
    # To/CC 표시 문자열("홍길동; 김철수 <kim@corp.com>") 에 내 이름·주소가 한 항목으로 있는가
    if (-not $list) { return $false }
    foreach ($tok in ($list -split ';')) {
        $t = $tok.Trim().ToLower()
        if (-not $t) { continue }
        foreach ($mid in $ids) {
            if (-not $mid) { continue }
            if ($t -eq $mid -or $t.EndsWith('<' + $mid + '>') -or $t.EndsWith('(' + $mid + ')') -or $t.StartsWith($mid + ' <')) { return $true }
        }
    }
    return $false
}

if ($From) { $since = [datetime]::ParseExact($From, 'yyyy-MM-dd', $null) } else { $since = (Get-Date).Date.AddDays(-$Days) }
if ($To)   { $until = ([datetime]::ParseExact($To, 'yyyy-MM-dd', $null)).AddDays(1) } else { $until = (Get-Date).Date.AddDays(1) }
$tomorrow = (Get-Date).Date.AddDays(1)
if ($until -gt $tomorrow) { $until = $tomorrow }     # 미래 종료일은 내일까지만 - 미래 달을 '완료'로 두면 이번 달이 영영 갱신되지 않는다
if ($until -le $since) { $until = $since.AddDays(1) }
$fmt = 'g'  # locale short date+time, what Outlook Restrict expects
$ol = $null
$requestedFrom = $since.ToString('yyyy-MM-dd'); $requestedTo = $until.AddDays(-1).ToString('yyyy-MM-dd')
$scope = 'default_account_only: delivered mail folders (excluding Deleted/Junk/Drafts/Outbox) and default calendar; local COM-visible items only'
if (-not $mailAllFolders) { $scope = 'default_account_only: Inbox and Sent only, and default calendar; local COM-visible items only' }
Write-OutlookStatus $root 'outlook_com' $requestedFrom $requestedTo 'partial' 0 $scope @('collection started; no completion verified') @{ mail_scope = 'default_account_only'; mail_status = 'partial'; calendar_status = 'partial'; mail_rows = $script:observedRows; calendar_rows = 0 }

# ── 달 목록: 기간과 겹치는 달을 최신 달부터. 각 달의 [start, end) 는 기간에 맞춰 자른다 ─────────────
$months = New-Object System.Collections.Generic.List[object]
$mCur = New-Object DateTime ($since.Year, $since.Month, 1)
while ($mCur -lt $until) {
    $mNext = $mCur.AddMonths(1)
    $ws = $mCur; if ($ws -lt $since) { $ws = $since }
    $we = $mNext; if ($we -gt $until) { $we = $until }
    $months.Add([pscustomobject]@{ key = $mCur.ToString('yyyy-MM'); start = $ws; end = $we })
    $mCur = $mNext
}
$months.Reverse()          # 최신 달 먼저
$monthKeys = @($months | ForEach-Object { $_.key })

# ── 파일 읽기: UTF-8 로 엄격히, 실패하면(Excel 이 CP949 로 다시 저장한 파일) 시스템 인코딩으로 ─────────
function Read-Lines([string]$path) {
    $strict = New-Object System.Text.UTF8Encoding($false, $true)
    try { return [System.IO.File]::ReadAllLines($path, $strict) }
    catch [System.Text.DecoderFallbackException] { return [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::Default) }
}

# ── 지난 실행의 달별 수집 완료 표(v2) ───────────────────────────────────────────
#   mail/calendar: { 'yyyy-MM': { rows, when, start, end } }  - start/end = 실제로 읽은 [start, end)
#   partial: { mail: { 'yyyy-MM': { inbox_done, inbox_before, sent_done, sent_before, start, end } },
#              calendar: { 'yyyy-MM': { from, start, end } } }  - 예산에 닿아 절반만 읽은 달의 '여기까지' 표식
function New-Coverage { return @{ mail = @{}; calendar = @{}; partial = @{ mail = @{}; calendar = @{} } } }
function Load-Coverage {
    $c = New-Coverage
    if (-not (Test-Path $covP)) { return $c }
    try {
        # 다른 경로(색인·웹·Copilot 폴백)가 CSV 를 다시 썼으면 표는 그 CSV 와 맞지 않는다 - 버린다
        if (Test-Path $srcP) {
            try {
                $sj = Get-Content -Raw -Encoding UTF8 $srcP | ConvertFrom-Json
                if ($sj -and $sj.PSObject.Properties['source'] -and ([string]$sj.source) -ne 'com') {
                    Write-Host ("[outlook] 지난 자료는 {0} 경로가 채운 것 - 완료 표를 버리고 처음부터 읽습니다" -f $sj.source)
                    return $c
                }
            } catch {}
        }
        $j = Get-Content -Raw -Encoding UTF8 $covP | ConvertFrom-Json
        $script:previousFolderScope = [string]$j.folder_scope
        $ver = 0; try { $ver = [int]$j.version } catch {}
        $w = ''; try { $w = [string]$j.writer } catch {}
        $ss = $true; try { $ss = [bool]$j.store_subject } catch {}
        if ($ver -ne 3 -or $w -ne $writer -or $ss -ne $storeSubject -or [bool]$j.mail_all_folders -ne $mailAllFolders -or [bool]$j.mail_body -ne $mailBody -or [int]$j.context_chars -ne $contextChars) {
            Write-Host ("[outlook] 완료 표가 이번 실행과 맞지 않아(버전 {0} · 작성 {1} · 제목 저장 {2}) 처음부터 읽습니다" -f $ver, $w, $ss)
            return $c
        }
        foreach ($kind in @('mail', 'calendar')) {
            $sec = $j.PSObject.Properties[$kind]
            if (-not $sec -or -not $sec.Value) { continue }
            foreach ($p in $sec.Value.PSObject.Properties) {
                if ($p.Name -notmatch '^\d{4}-\d{2}$') { continue }
                try {
                    $c[$kind][$p.Name] = @{ rows = [int]$p.Value.rows; when = [string]$p.Value.when;
                                            start = [datetime]::ParseExact([string]$p.Value.start, $TS, $null);
                                            end = [datetime]::ParseExact([string]$p.Value.end, $TS, $null) }
                } catch {}
            }
        }
        $ps = $j.PSObject.Properties['partial']
        if ($ps -and $ps.Value) {
            foreach ($kind in @('mail', 'calendar')) {
                $sec = $ps.Value.PSObject.Properties[$kind]
                if (-not $sec -or -not $sec.Value) { continue }
                foreach ($p in $sec.Value.PSObject.Properties) {
                    if ($p.Name -notmatch '^\d{4}-\d{2}$') { continue }
                    try {
                        $e = @{ start = [datetime]::ParseExact([string]$p.Value.start, $TS, $null);
                                end = [datetime]::ParseExact([string]$p.Value.end, $TS, $null) }
                        if ($kind -eq 'mail') {
                            $e.inbox_done = [bool]$p.Value.inbox_done; $e.inbox_before = [string]$p.Value.inbox_before
                            $e.sent_done = [bool]$p.Value.sent_done;   $e.sent_before = [string]$p.Value.sent_before
                            $e.folders = @{}
                            if ($p.Value.folders) { foreach ($fp in $p.Value.folders.PSObject.Properties) { $e.folders[$fp.Name] = @{ done = [bool]$fp.Value.done; before = [string]$fp.Value.before } } }
                        } else {
                            $e.from = [string]$p.Value.from
                        }
                        $c.partial[$kind][$p.Name] = $e
                    } catch {}
                }
            }
        }
    } catch { Write-Host ("[outlook] coverage.json 을 읽지 못해 처음부터 읽습니다: {0}" -f $_.Exception.Message); return (New-Coverage) }
    return $c
}
function Save-Coverage($c) {
    try {
        $o = [ordered]@{ version = 3; writer = $writer; store_subject = $storeSubject; keep_days = $KeepDays; mail_all_folders = $mailAllFolders; mail_body = $mailBody; context_chars = $contextChars; folder_scope = $script:folderScope;
                         when = (Get-Date).ToString('yyyy-MM-dd HH:mm'); mail = [ordered]@{}; calendar = [ordered]@{};
                         partial = [ordered]@{ mail = [ordered]@{}; calendar = [ordered]@{} } }
        foreach ($kind in @('mail', 'calendar')) {
            foreach ($k in ($c[$kind].Keys | Sort-Object -Descending)) {
                $e = $c[$kind][$k]
                $o[$kind][$k] = [ordered]@{ rows = [int]$e.rows; when = [string]$e.when;
                                            start = $e.start.ToString($TS); end = $e.end.ToString($TS) }
            }
            foreach ($k in ($c.partial[$kind].Keys | Sort-Object -Descending)) {
                $e = $c.partial[$kind][$k]
                $x = [ordered]@{ start = $e.start.ToString($TS); end = $e.end.ToString($TS) }
                if ($kind -eq 'mail') {
                    $x.inbox_done = [bool]$e.inbox_done; $x.inbox_before = [string]$e.inbox_before
                    $x.sent_done = [bool]$e.sent_done;   $x.sent_before = [string]$e.sent_before; $x.folders = $e.folders
                } else { $x.from = [string]$e.from }
                $o.partial[$kind][$k] = $x
            }
        }
        ($o | ConvertTo-Json -Depth 12) | Set-Content -Path $covP -Encoding UTF8
    } catch { Write-Host ("[outlook] coverage.json 저장 실패: {0}" -f $_.Exception.Message) }
}
function Test-Covered([string]$kind, $mo) {
    # 완료 표의 달이 이번에 부른 [start, end) 를 전부 덮을 때만 '읽었다'로 본다
    $e = $script:cov[$kind][$mo.key]
    if (-not $e) { return $false }
    return (($e.start -le $mo.start) -and ($e.end -ge $mo.end))
}
function Get-Partial([string]$kind, $mo) {
    # 같은 [start, end) 로 읽다 멈춘 표식만 유효 - 기간이 달라졌으면 처음부터
    $e = $script:cov.partial[$kind][$mo.key]
    if (-not $e) { return $null }
    if (($e.start -ne $mo.start) -or ($e.end -ne $mo.end)) { return $null }
    return $e
}

# ── 기존 CSV 를 달별로 나눠 든다(행은 원문 그대로) - 다시 읽는 달만 바꾸고 나머지는 보존 ────────────
function Month-Of([string]$line, [int]$timeCol) {
    # timeCol: 시각 열 위치(0부터). 앞 열들에는 쉼표가 없다(box 는 inbox/sent, start 는 시각) - 정규식으로 충분하다
    $re = '^' + ('[^,]*,' * $timeCol) + '(\d{4})-(\d{2})-(\d{2})'
    $m = [regex]::Match($line, $re)
    if (-not $m.Success) { return $null }
    try { $d = New-Object DateTime ([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value) } catch { return $null }
    return @{ key = ($m.Groups[1].Value + '-' + $m.Groups[2].Value); date = $d }
}
function Load-CsvByMonth([string]$path, [int]$timeCol) {
    $by = @{}
    if (-not (Test-Path $path)) { return $by }
    $hdr = $(if ($timeCol -eq 1) { $MAIL_HEADER } else { $CAL_HEADER })
    $n = 0
    foreach ($line in (Read-OutlookCsvLines $root $path $hdr)) {
        $n++
        if ($n -eq 1) { continue }                          # 머리말
        if (-not $line) { continue }
        $mo = Month-Of $line $timeCol
        if (-not $mo) { continue }                          # 형식이 어긋난 행은 버린다(구판 헤더 등)
        # Existing history is retained; KeepDays no longer deletes prior observations.
        if (-not $by.ContainsKey($mo.key)) { $by[$mo.key] = New-Object System.Collections.Generic.List[string] }
        $by[$mo.key].Add($line)
    }
    return $by
}
function Add-Rows($by, $rows, [int]$timeCol, [string]$defaultKey) {
    # 읽어 온 행을 '그 행의 달'로 넣는다 - 달 경계에 걸친 일정 회차(6/30 시작)는 6월 버킷으로. 형식이 어긋나면 읽던 달로
    foreach ($line in $rows) {
        $mo = Month-Of $line $timeCol
        $k = $(if ($mo) { $mo.key } else { $defaultKey })
        if (-not $by.ContainsKey($k)) { $by[$k] = New-Object System.Collections.Generic.List[string] }
        $by[$k].Add($line)
    }
}
function Write-CsvByMonth([string]$path, [string]$header, $by, [bool]$dedupe) {
    $lines = New-Object 'System.Collections.Generic.List[string]'
    $lines.Add($header)
    foreach ($key in ($by.Keys | Sort-Object)) { foreach ($line in $by[$key]) { $lines.Add($line) } }
    return Merge-OutlookCsv $root $path $lines.ToArray() $(if ($path -eq $mailP) { 'mail' } else { 'calendar' })
}

# ── 버전 강건성: 2016/2019/2021/365 '클래식' Outlook 은 전부 동일한 COM(Outlook.Application)
# 을 쓰므로 버전 구분이 필요 없다. 문제는 '새 Outlook'(olk.exe) - COM 인터페이스 자체가 없어
# 어떤 버전 표기든 수집이 통째로 빈다(실측: 'PC마다 메일 누락'의 주원인 후보).
$newOutlook = $false
if (-not $SelfTest) {
    try {
        # 공식 위치는 Office\16.0\Outlook\Preferences - 구형 경로도 함께 본다
        foreach ($rp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Preferences', 'HKCU:\Software\Microsoft\Office\Outlook\Preferences')) {
            $pref = Get-ItemProperty -Path $rp -ErrorAction SilentlyContinue
            if ($pref -and $pref.UseNewOutlook -eq 1) { $newOutlook = $true }
        }
    } catch {}
    if (Get-Process olk -ErrorAction SilentlyContinue) { $newOutlook = $true }
    if ($newOutlook) {
        Write-Host '[outlook] 주의: "새 Outlook" 사용이 감지되었습니다 - 새 Outlook 은 데이터 접근(COM)을 제공하지 않습니다.'
        Write-Host '          클래식 Outlook 을 함께 두면 됩니다: 새 Outlook 우상단 [새 Outlook] 토글을 끄거나,'
        Write-Host '          클래식 Outlook(2016~365)을 실행해 두고 다시 수집하세요. (계속 시도합니다)'
    }
}

# 건너뛴/실패한 사유를 남긴다 - 대시보드가 이것을 읽어 '메일 0건'의 이유를 말해 준다.
# 없으면 화면은 "Outlook 을 켜세요"라고만 하는데, 마법사에 막힌 PC 는 이미 켜져 있어
# 그 안내가 오히려 원인을 가린다(실측).
function Set-SkipReason([string]$reason) {
    try {
        $f = Join-Path $outDir 'outlook_skip.json'
        $o = [ordered]@{ reason = $reason; when = (Get-Date).ToString('yyyy-MM-dd HH:mm') }
        ($o | ConvertTo-Json -Compress) | Set-Content -Path $f -Encoding UTF8
        Write-OutlookStatus $root 'outlook_com' $requestedFrom $requestedTo 'blocked' $script:observedRows $scope @($reason) @{ mail_scope = 'default_account_only'; mail_status = 'failed'; calendar_status = 'failed'; mail_rows = $script:observedRows; calendar_rows = $script:observedCalendarRows }
    } catch {}
}
function Clear-SkipReason {
    try { Remove-Item (Join-Path $outDir 'outlook_skip.json') -ErrorAction SilentlyContinue } catch {}
}

# ── 프로필 사전 점검 (버전 불일치 대응) ─────────────────────────────────────
# COM 기동은 '등록된' Outlook 을 띄운다. 실제로 쓰는 것이 365 여도 구형 2016 설치본이
# 등록돼 있으면 그쪽이 뜨고, 그 설치본에 프로필이 없으면 '첫 실행 마법사'(모달)가 떠서
# 응답이 없다 - 그 PC 의 수집이 통째로 비고 스크립트는 무한정 대기한다(실측).
# 마법사를 띄우는 주체가 이 호출이므로, 프로필이 없으면 COM 을 건드리지 않는다.
$olRunning = $false
$hasProfile = $false
if (-not $SelfTest) {
    $olRunning = [bool](Get-Process outlook -ErrorAction SilentlyContinue)
    foreach ($pp in @('HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles',
                      'HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles',
                      'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles')) {
        try {
            if (Get-ChildItem -Path $pp -ErrorAction SilentlyContinue | Select-Object -First 1) {
                $hasProfile = $true
                break
            }
        } catch {}
    }
    if (-not $olRunning -and -not $hasProfile) {
        Write-Host '[outlook] 건너뜀: 메일 프로필이 구성되지 않았습니다.'
        Write-Host '          이 상태에서 COM 으로 Outlook 을 띄우면 "Outlook 시작" 설정 마법사가 떠서'
        Write-Host '          응답이 없고 수집이 멈춥니다. Outlook 을 직접 실행해 계정을 설정한 뒤,'
        Write-Host '          Outlook 을 켜 둔 채로 다시 수집하세요.'
        Write-Host '          (평소 쓰는 Outlook 이 따로 있다면, 그 Outlook 을 열어 두면 그쪽에 붙습니다.)'
        Set-SkipReason 'Outlook 메일 프로필이 구성되지 않았습니다 — Outlook 을 직접 실행해 계정 설정을 마친 뒤 다시 수집하세요'
        exit 0
    }
}

# ── 달 하나를 읽는 함수들 - COM 과 자가검증(SelfTest) 두 갈래. 둘 다 CSV 행 목록과 중단 사유를 돌려준다 ──
$script:stopReason = ''
$script:calLast = ''          # 일정: 이번에 읽은 마지막 시작 시각(TS) - 이어 읽기 표식
function Read-CalendarMonth($ns, $mo, [string]$resumeFrom) {
    # 반환: 이 달과 겹치는 일정의 CSV 행 목록(resumeFrom 이 있으면 그 시작 시각부터). 예산(절반)에 닿으면
    # $script:stopReason 을 채우고 그때까지의 행만.
    $rows = New-Object System.Collections.Generic.List[string]
    $script:stopReason = ''; $script:calLast = ''
    $halfBudget = $BudgetSec * 0.5
    $lo = $mo.start
    if ($resumeFrom) { try { $lo = [datetime]::ParseExact($resumeFrom, $TS, $null) } catch {} }
    if ($SelfTest) {
        $n = [math]::Max(1, [int]($SelfTest / 2))
        $span = [math]::Max(1, ($mo.end - $mo.start).Days)
        for ($i = 0; $i -lt $n; $i++) {
            $st = $mo.start.AddDays($i % $span).AddHours(9 + ($i % 8))
            if ($st -lt $lo) { continue }
            if ($SelfTestDelayMs -gt 0) { Start-Sleep -Milliseconds $SelfTestDelayMs }
            if ($sw.Elapsed.TotalSeconds -gt $halfBudget) { $script:stopReason = ('일정 시간 예산({0}초) 도달' -f [math]::Round($halfBudget, 1)); break }
            $rows.Add(('{0},{1},False,2,{2},,,3,1' -f $st.ToString('yyyy-MM-dd HH:mm'), $st.AddHours(1).ToString('yyyy-MM-dd HH:mm'), ('selftest meeting ' + $i)))
            $script:observedCalendarRows++
            $script:calLast = $st.ToString($TS)
        }
        return $rows
    }
    try {
    $cal = $ns.GetDefaultFolder(9)  # olFolderCalendar
    $items = $cal.Items
    # IncludeRecurrences 는 [Start] 오름차순 정렬을 요구한다(COM 규칙 - 내림차순이면 회차 전개가 깨진다). 예산에 닿으면
    # 마지막 시작 시각을 표식으로 남겨 다음 실행이 거기서부터 잇는다.
    $items.Sort('[Start]')
    $items.IncludeRecurrences = $true
    $flt = ("[Start] < '{0}' AND [End] >= '{1}' AND [Start] >= '{2}'" -f $mo.end.ToString($fmt), $mo.start.ToString($fmt), $lo.ToString($fmt))
    if ($lo -le $mo.start) { $flt = ("[Start] < '{0}' AND [End] >= '{1}'" -f $mo.end.ToString($fmt), $mo.start.ToString($fmt)) }
    $sel = $items.Restrict($flt)
    $count = 0
    foreach ($it in $sel) {
        $count++
        if ($count -gt 8000) { $script:stopReason = '일정 상한 8000건(깨진 반복 일정?)'; break }   # runaway guard for broken recurrences
        if ($sw.Elapsed.TotalSeconds -gt $halfBudget) {
            $script:stopReason = ('일정 시간 예산({0}초) 도달' -f [math]::Round($halfBudget, 1)); break
        }
        try {
            $subj = ''
            if ($storeSubject) { $subj = [string]$it.Subject }
            # LM22: 응답 상태(0 없음/1 주최/2 미정/3 수락/4 거절/5 미응답)와 회의 상태(5·7 = 취소).
            # '미정(busy 1)'은 대부분 미응답 초대라 extract 가 참석 판정(tentativeMeetings)에 쓴다. 못 읽으면 빈칸.
            $resp = ''; $mst = ''
            try { $resp = [string][int]$it.ResponseStatus } catch {}
            try { $mst = [string][int]$it.MeetingStatus } catch {}
            $rows.Add(('{0},{1},{2},{3},{4},{5},{6},{7},{8}' -f `
                $it.Start.ToString('yyyy-MM-dd HH:mm'), $it.End.ToString('yyyy-MM-dd HH:mm'), `
                $it.AllDayEvent, $it.BusyStatus, (Csv-Escape $subj), `
                (Csv-Escape ([string]$it.Categories)), (Csv-Escape ([string]$it.Location)), $resp, $mst))
            $script:observedCalendarRows++
            if (($rows.Count % 100) -eq 0) { $null = Merge-OutlookCsv $root $calP (@($CAL_HEADER) + @($rows)) 'calendar' }
            try { $script:calLast = $it.Start.ToString($TS) } catch {}
        } catch { $script:stopReason = 'calendar item could not be read'; $script:collectionProblems.Add($script:stopReason) }
    }
    } catch { $script:stopReason = 'calendar query or enumeration failed'; $script:collectionProblems.Add($script:stopReason) }
    if ($rows.Count) { $null = Merge-OutlookCsv $root $calP (@($CAL_HEADER) + @($rows)) 'calendar' }
    if (@($script:collectionProblems | Where-Object { $_ -like 'calendar *' }).Count) { $script:calLast = '' }
    return $rows
}
function Read-MailMonth($ns, $mo, [string[]]$me, $state) {
    $rows = New-Object 'System.Collections.Generic.List[string]'
    $script:stopReason = ''
    if (-not $state.folders) { $state.folders = @{} }
    $boxes = $script:mailFolders
    if ($SelfTest) { $boxes = @(@{ name = 'inbox'; key = 'self-inbox'; field = '[ReceivedTime]' }, @{ name = 'sent'; key = 'self-sent'; field = '[SentOn]' }) }
    foreach ($b in $boxes) {
        if (-not $state.folders.ContainsKey($b.key)) { $state.folders[$b.key] = @{ done = $false; before = '' } }
        $cursor = $state.folders[$b.key]
        if ($cursor.done) { continue }
        if ($sw.Elapsed.TotalSeconds -gt $BudgetSec) { $script:stopReason = 'mail time budget reached'; break }
        $upper = $mo.end
        if ($cursor.before) { try { $upper = [datetime]::ParseExact($cursor.before, $TS, $null).AddMinutes(1); if ($upper -gt $mo.end) { $upper = $mo.end } } catch {} }
        $lastT = $null; $stopped = $false; $failed = $false; $n = 0
        try {
            if ($SelfTest) {
                $selection = 0..($SelfTest - 1)
            } else {
                $items = $b.folder.Items
                $items.Sort($b.field, $true)
                $filter = ("{0} >= '{1}' AND {0} < '{2}'" -f $b.field, $mo.start.ToString($fmt), $upper.ToString($fmt))
                $selection = $items.Restrict($filter)
            }
            foreach ($m in $selection) {
                $n++
                if ($SelfTestDelayMs -gt 0) { Start-Sleep -Milliseconds $SelfTestDelayMs }
                if ($sw.Elapsed.TotalSeconds -gt $BudgetSec -or $n -gt 20000) { $stopped = $true; break }
                try {
                    if ($SelfTest) {
                        $t = $mo.end.AddMinutes(-1 - [int]$m * 97)
                        if ($t -lt $mo.start) { $t = $mo.start.AddMinutes([int]$m) }
                        if ($t -ge $upper) { continue }
                        $vals = @($b.name, $t.ToString('yyyy-MM-dd HH:mm'), 'selftest', ('selftest mail ' + $m), ('conv ' + ([int]$m % 3)), 'to', 'minute', 'synthetic body', 'false', ($mo.key + '-' + $b.key + '-' + $m), 'selftest', '', '', $b.key, 'selftest')
                    } else {
                        if ($m.Class -ne 43) { continue }
                        $box = $b.name; $sender = [string]$m.SenderName
                        # Custom folders can contain moved sent mail. Only exact known sender identity upgrades it.
                        try { if (Test-MeInList ([string]$m.SenderEmailAddress) $me) { $box = 'sent' } } catch {}
                        # Use the same timestamp as this folder's bounded Restrict/sort/cursor.
                        $t = $(if ($b.name -eq 'sent') { $m.SentOn } else { $m.ReceivedTime })
                        if ($t -lt $mo.start -or $t -ge $mo.end) { continue }
                        $subject = ''; $conversation = [string]$m.ConversationTopic
                        if ($storeSubject) { $subject = [string]$m.Subject } else { $conversation = Conv-Token $conversation }
                        $rcv = ''
                        if ($box -eq 'inbox') {
                            $toS = ''; $ccS = ''
                            try { $toS = [string]$m.To; $ccS = [string]$m.CC } catch {}
                            if (Test-MeInList $toS $me) { $rcv = 'to' }
                            elseif (Test-MeInList $ccS $me) { $rcv = 'cc' }
                            elseif (-not $me.Count -or (-not $toS -and -not $ccS)) { $rcv = 'unknown' }
                            else {
                                $rcv = 'bulk'
                                try {
                                    if ([int]$m.Recipients.Count -le 12) {
                                        foreach ($rc in $m.Recipients) {
                                            $addr = ''
                                            try { $addr = $rc.PropertyAccessor.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x39FE001E') } catch {}
                                            if (-not $addr) { $addr = [string]$rc.Address }
                                            if ((Test-MeInList $addr $me) -or (Test-MeInList ([string]$rc.Name) $me)) {
                                                if ($rc.Type -eq 1) { $rcv = 'to'; break }
                                                elseif ($rc.Type -eq 2) { $rcv = 'cc' }
                                            }
                                        }
                                    }
                                } catch { $rcv = 'unknown' }
                            }
                        }
                        $context = @(Get-OutlookContext $m $contextChars ($mailBody -and $storeSubject -and $contextChars -gt 0) $script:collectionProblems)
                        if ($context[1] -eq 'unknown') { $failed = $true }
                        $entry = ''; $conversationId = ''; $account = ''; $folderPath = ''
                        try { $entry = [string]$m.EntryID; $conversationId = [string]$m.ConversationID; $account = [string]$b.folder.StoreID; $folderPath = [string]$b.folder.FolderPath } catch { $failed = $true; $script:collectionProblems.Add('message identity or folder inaccessible') }
                        if (-not $entry -or -not $account) { $failed = $true; $script:collectionProblems.Add('message or account identity empty') }
                        $sourceId = $(if ($entry) { $account + ':' + $entry } else { '' })
                        $vals = @($box, $t.ToString('yyyy-MM-dd HH:mm'), $sender, $subject, $conversation, $rcv, 'minute', $context[0], $context[1], $sourceId, 'outlook_com', '', $conversationId, $folderPath, $account)
                    }
                    $rows.Add((($vals | ForEach-Object { Csv-Escape ([string]$_) }) -join ','))
                    $script:observedRows++; $lastT = $t
                    if (($n % 100) -eq 0) { $null = Merge-OutlookCsv $root $mailP (@($MAIL_HEADER) + @($rows)) 'mail' }
                } catch { $failed = $true; $script:collectionProblems.Add('mail item inaccessible: ' + $_.Exception.GetType().Name) }
            }
        } catch { $failed = $true; $script:collectionProblems.Add('mail folder query failed: ' + $_.Exception.GetType().Name) }
        if ($rows.Count) { $null = Merge-OutlookCsv $root $mailP (@($MAIL_HEADER) + @($rows)) 'mail' }
        if ($stopped) {
            if ($lastT -and -not $failed) { $cursor.before = $lastT.ToString($TS) }
            $script:stopReason = 'mail time or item limit reached'; break
        }
        if ($failed) { $cursor.before = ''; $script:stopReason = 'one or more mail items/folders could not be read' }
        else { $cursor.done = $true }
    }
    if (@($script:collectionProblems | Where-Object { $_ -notlike 'calendar *' }).Count -and -not $script:stopReason) { $script:stopReason = 'mail scope or item verification incomplete' }
    return $rows
}

function Months-ToRead([string]$kind) {
    # 읽는 순서: ① 최신 달(새 메일이 붙는 달) → ② 아직 못 읽은 달(최신→과거) → ③ 나머지 재수집 달.
    # 못 읽은 달을 재수집 달보다 앞에 둔다 - 재수집 달을 먼저 읽으면 예산이 거기서 다 닳아 실행을 거듭해도
    # 옛 달에 영영 못 간다(자가검증에서 실측). -NoRefresh(run.py 연속 회차)면 ②만.
    # 반환은 목록을 풀어서(호출측 @()) - ',$list' 로 돌리면 목록 하나가 원소가 돼 $mo 가 달이 아니라 목록이 된다(재검증 실측).
    $out = New-Object System.Collections.Generic.List[object]
    $added = @{}
    if ($Force) {
        foreach ($mo in $months) { $out.Add($mo); $added[$mo.key] = $true }
        return $out
    }
    if (-not $NoRefresh -and $months.Count -gt 0) { $out.Add($months[0]); $added[$months[0].key] = $true }
    foreach ($mo in $months) {
        if (-not $added.ContainsKey($mo.key) -and -not (Test-Covered $kind $mo)) { $out.Add($mo); $added[$mo.key] = $true }
    }
    if (-not $NoRefresh) {
        $i = 0
        foreach ($mo in $months) {
            if ($i -lt $REFRESH_MONTHS -and -not $added.ContainsKey($mo.key)) { $out.Add($mo); $added[$mo.key] = $true }
            $i++
        }
    }
    return $out
}

try {
    # ── 지난 표·CSV 읽기(여기서 실패해도 사유가 남게 try 안) ──
    $script:cov = Load-Coverage
    if ($Force) { $script:cov = New-Coverage }
    $mailBy = Load-CsvByMonth $mailP 1
    $calBy  = Load-CsvByMonth $calP  0
    # 지난 표에 '완료'로 남았는데 CSV 에 그 달 행이 하나도 없으면 표를 믿지 않는다(파일만 지운 경우). 원래 0건인 달은 그대로
    foreach ($kind in @('mail', 'calendar')) {
        $by = $(if ($kind -eq 'mail') { $mailBy } else { $calBy })
        foreach ($k in @($script:cov[$kind].Keys)) {
            if (-not $by.ContainsKey($k) -and [int]$script:cov[$kind][$k].rows -gt 0) { $script:cov[$kind].Remove($k) }
        }
    }
    $mailTodo = @(Months-ToRead 'mail')
    $calTodo  = @(Months-ToRead 'calendar')
    Write-Host ("[outlook] 기간 {0} ~ {1} · {2}개월 · 읽을 달: 메일 {3} / 일정 {4} (완료된 달은 건너뜀{5}{6}) · 예산 {7}초" -f `
        $since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'), $months.Count, $mailTodo.Count, $calTodo.Count, `
        $(if ($Force) { ' - Force 로 전부 다시' } else { '' }), $(if ($NoRefresh) { ' - 이어서 읽기 회차' } else { '' }), $BudgetSec)

    $ns = $null
    $me = @()
    if ($SelfTest) {
        Write-Host ("[outlook] 자가검증 모드 - Outlook 없이 달마다 가짜 메일 {0}건·일정 {1}건 (표·mail_source 에 selftest 표식)" -f $SelfTest, [math]::Max(1, [int]($SelfTest / 2)))
        $me = @('selftest@corp.local')
    } else {
        # 이미 떠 있는 Outlook 에 먼저 붙는다 - 사용자가 실제로 쓰는 버전이 그것이고,
        # 새 인스턴스 기동은 등록된(다를 수 있는) 설치본을 띄우기 때문이다.
        # 떠 있는 Outlook 에 붙기를 먼저 시도한다. 바쁜 순간에는 거부(RPC_E_CALL_REJECTED)될
        # 수 있는데 영구 실패가 아니므로 짧게 재시도한다.
        for ($try = 1; $try -le 3 -and -not $ol; $try++) {
            try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') } catch { $ol = $null }
            if (-not $ol -and $try -lt 3) { Start-Sleep -Seconds 2 }
        }
        if (-not $ol -and $olRunning) {
            # Outlook 이 실행 중인데 붙을 수 없다 = COM 을 아직 등록하지 않았다 = 시작 마법사·
            # 프로필 선택·암호 입력 같은 대화상자에 막혀 있다는 뜻이다. 이때 New-Object 를
            # 부르면 그 창이 닫힐 때까지 **반환되지 않는다**(실측: 300초 무응답). 부르지 않는다.
            $wins = @()
            try {
                $wins = @(Get-Process outlook -ErrorAction SilentlyContinue |
                          ForEach-Object { $_.MainWindowTitle } | Where-Object { $_ })
            } catch {}
            Write-Host '[outlook] 건너뜀: Outlook 이 실행 중이지만 아직 사용할 준비가 안 됐습니다.'
            if ($wins.Count) { Write-Host ("          열려 있는 창: {0}" -f ($wins -join ' / ')) }
            Write-Host '          보통 "Outlook 시작" 설정 마법사·프로필 선택·암호 입력 창이 떠 있을 때입니다.'
            Write-Host '          그 창을 닫거나 설정을 끝내고 메일 화면까지 연 다음 다시 수집하세요.'
            Write-Host '          (설치 문제가 아닙니다 - 재설치하지 마세요)'
            Set-SkipReason ("Outlook 이 대화상자에 막혀 있습니다" +
                $(if ($wins.Count) { " (열린 창: " + ($wins -join ' / ') + ")" } else { '' }) +
                " — 그 창을 닫고 메일 화면까지 연 다음 다시 수집하세요")
            exit 0
        }
        if (-not $ol) {
            if (-not $hasProfile) {
                Write-Host '[outlook] 건너뜀: 붙을 Outlook 도, 구성된 프로필도 없습니다.'
                Set-SkipReason '붙을 Outlook 도, 구성된 프로필도 없습니다'
                exit 0
            }
            $ol = New-Object -ComObject Outlook.Application
        }
        $ns = $ol.GetNamespace('MAPI')
        # ShowDialog=$false - 프로필 선택창·설정 마법사를 원천 차단한다. 이미 로그온된
        # 세션이면 무시되고, 아니면 기본 프로필로 조용히 붙는다.
        try { $ns.Logon($null, $null, $false, $false) } catch {}
        # 어느 설치본이 잡혔는지 남긴다 - 'PC 마다 누락'을 원격으로 판별하는 유일한 단서다.
        try {
            $exe = ''
            try { $exe = (Get-Process outlook -ErrorAction SilentlyContinue |
                          Select-Object -First 1).Path } catch {}
            Write-Host ("[outlook] 연결: 버전 {0}{1}" -f $ol.Version,
                        $(if ($exe) { " ($exe)" } else { '' }))
        } catch {}
        # 내 주소·이름(수신 구분용)
        try {
            $acc = $ns.Accounts
            foreach ($a in $acc) { if ($a.SmtpAddress) { $me += $a.SmtpAddress.ToLower() } }
        } catch {}
        try { $me += $ns.CurrentUser.Name.ToLower() } catch {}
        try { if ($ns.CurrentUser.Address) { $me += ([string]$ns.CurrentUser.Address).ToLower() } } catch {}
        try {
            $xu = $ns.CurrentUser.AddressEntry.GetExchangeUser()
            if ($xu -and $xu.PrimarySmtpAddress) { $me += ([string]$xu.PrimarySmtpAddress).ToLower() }
        } catch {}
        try { if ($cfg.owner) { $me += ([string]$cfg.owner).Trim().ToLower() } } catch {}
        $me = @($me | Where-Object { $_ -and $_.Length -ge 2 } | Select-Object -Unique)
    }
    try { Remove-Item -LiteralPath (Join-Path $outDir 'mail.csv.part') -ErrorAction SilentlyContinue } catch {}   # 구판의 중간 저장은 더 쓰지 않는다

    $warnings = New-Object System.Collections.Generic.List[string]
    $refreshIncomplete = New-Object System.Collections.Generic.List[string]   # 완료했던 달을 다시 읽다 끊긴 것(옛 행 유지)
    $now = (Get-Date).ToString('yyyy-MM-dd HH:mm')
    $readCal = 0; $readMail = 0

    if (-not $SelfTest) {
        try { $script:mailFolders = @(Get-OutlookMailFolders $ns $mailAllFolders $script:collectionProblems) }
        catch { $script:collectionProblems.Add('default mailbox folder discovery failed: ' + $_.Exception.GetType().Name); $script:mailFolders = @() }
        $scopeKeys = @($script:mailFolders | ForEach-Object { [string]$_.folder.StoreID + ':' + $_.key } | Sort-Object)
        $script:folderScope = Conv-Token ($scopeKeys -join '|')
    } else { $script:folderScope = 'selftest-inbox-sent' }
    if ($script:folderScope -ne $script:previousFolderScope -or $script:collectionProblems.Count) {
        # A newly added/moved folder changes the declared scope of every completed month.
        $script:cov.mail = @{}; $script:cov.partial.mail = @{}
        $mailTodo = @(Months-ToRead 'mail')
    }
    # ---------- calendar: 최신 달부터, 예산의 절반까지 ----------
    foreach ($mo in $calTodo) {
        if ($sw.Elapsed.TotalSeconds -gt ($BudgetSec * 0.5)) { break }
        $wasComplete = Test-Covered 'calendar' $mo
        $p = Get-Partial 'calendar' $mo
        $rows = @(Read-CalendarMonth $ns $mo $(if ($p) { $p.from } else { '' }))
        if ($script:stopReason) {
            if ($wasComplete) {
                # 완료했던 달의 재수집이 끊겼다 - 옛 행을 지키고 다음 실행이 처음부터 다시 읽는다
                Add-Rows $calBy $rows 0 $mo.key
                $refreshIncomplete.Add('일정 ' + $mo.key)
                $warnings.Add(('일정 {0}: {1} - 지난 수집분을 그대로 두고 다음 실행에서 다시 읽습니다' -f $mo.key, $script:stopReason))
            } else {
                # 부분: 이어 읽던 행(있으면) + 이번 행. 완료 표시는 안 하고 '여기까지' 표식만 남긴다
                # Retain the complete old month, including outside a narrower requested range.
                Add-Rows $calBy $rows 0 $mo.key
                $script:cov.partial.calendar[$mo.key] = @{ from = $script:calLast; start = $mo.start; end = $mo.end }
                $warnings.Add(('일정 {0}: {1} - 이 달은 다음 실행에서 이어서 읽습니다' -f $mo.key, $script:stopReason))
            }
            Write-Host ('[outlook] 경고: ' + $warnings[$warnings.Count - 1])
            $null = Write-CsvByMonth $calP $CAL_HEADER $calBy $true
            Save-Coverage $script:cov
            break
        }
        # Retain the complete old month, including outside a narrower requested range.
        Add-Rows $calBy $rows 0 $mo.key
        $cnt = $(if ($calBy.ContainsKey($mo.key)) { $calBy[$mo.key].Count } else { 0 })
        $script:cov.calendar[$mo.key] = @{ rows = $cnt; when = $now; start = $mo.start; end = $mo.end }
        $script:cov.partial.calendar.Remove($mo.key)
        $readCal++
        $null = Write-CsvByMonth $calP $CAL_HEADER $calBy $true
        Save-Coverage $script:cov
        Write-Host ("[outlook] 일정 {0}: {1}건 (경과 {2}초)" -f $mo.key, $cnt, [int]$sw.Elapsed.TotalSeconds)
    }
    if (-not (Test-Path $calP)) { $null = Write-CsvByMonth $calP $CAL_HEADER $calBy $true }

    # ---------- mail (inbox + sent): 최신 달부터, 예산까지 ----------
    foreach ($mo in $mailTodo) {
        if ($sw.Elapsed.TotalSeconds -gt $BudgetSec) { break }
        $wasComplete = Test-Covered 'mail' $mo
        $p = Get-Partial 'mail' $mo
        $state = @{ inbox_done = $false; inbox_before = ''; sent_done = $false; sent_before = ''; folders = @{} }
        if ($p) { $state.inbox_done = [bool]$p.inbox_done; $state.inbox_before = [string]$p.inbox_before; $state.sent_done = [bool]$p.sent_done; $state.sent_before = [string]$p.sent_before; $state.folders = $p.folders }
        $rows = @(Read-MailMonth $ns $mo $me $state)
        if ($script:stopReason) {
            if ($wasComplete) {
                Add-Rows $mailBy $rows 1 $mo.key
                $refreshIncomplete.Add('메일 ' + $mo.key)
                $warnings.Add(('메일 {0}: {1} 도달 - 지난 수집분을 그대로 두고 다음 실행에서 다시 읽습니다' -f $mo.key, $script:stopReason))
            } else {
                # Retain the complete old month, including outside a narrower requested range.
                Add-Rows $mailBy $rows 1 $mo.key
                $script:cov.partial.mail[$mo.key] = @{ inbox_done = $state.inbox_done; inbox_before = $state.inbox_before;
                                                       sent_done = $state.sent_done; sent_before = $state.sent_before; folders = $state.folders;
                                                       start = $mo.start; end = $mo.end }
                $warnings.Add(('메일 {0}: {1} 도달 - 이 달은 다음 실행에서 이어서 읽습니다(그다음 오래된 달도)' -f $mo.key, $script:stopReason))
            }
            Write-Host ('[outlook] 경고: ' + $warnings[$warnings.Count - 1])
            $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy $false
            Save-Coverage $script:cov
            break
        }
        # Retain the complete old month, including outside a narrower requested range.
        Add-Rows $mailBy $rows 1 $mo.key
        $cnt = $(if ($mailBy.ContainsKey($mo.key)) { $mailBy[$mo.key].Count } else { 0 })
        $script:cov.mail[$mo.key] = @{ rows = $cnt; when = $now; start = $mo.start; end = $mo.end }
        $script:cov.partial.mail.Remove($mo.key)
        $readMail++
        $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy $false
        Save-Coverage $script:cov
        Write-Host ("[outlook] 메일 {0}: {1}건 (경과 {2}초)" -f $mo.key, $cnt, [int]$sw.Elapsed.TotalSeconds)
    }
    if (-not (Test-Path $mailP)) { $null = Write-CsvByMonth $mailP $MAIL_HEADER $mailBy $false }
    # Report canonical persisted counts, not old rows plus repeated observations.
    $mailBy = Load-CsvByMonth $mailP 1
    $calBy = Load-CsvByMonth $calP 0
    foreach ($kind in @('mail', 'calendar')) {
        $by = $(if ($kind -eq 'mail') { $mailBy } else { $calBy })
        foreach ($key in @($script:cov[$kind].Keys)) {
            $script:cov[$kind][$key].rows = $(if ($by.ContainsKey($key)) { $by[$key].Count } else { 0 })
        }
    }
    Save-Coverage $script:cov

    # ---------- 요약: 기간 안에서 아직 못 읽은 달 ----------
    $uncMail = @($months | Where-Object { -not (Test-Covered 'mail' $_) } | ForEach-Object { $_.key })
    $uncCal  = @($months | Where-Object { -not (Test-Covered 'calendar' $_) } | ForEach-Object { $_.key })
    $unc = @($uncMail + $uncCal | Select-Object -Unique | Sort-Object)
    $partialMonths = @(@($script:cov.partial.mail.Keys) + @($script:cov.partial.calendar.Keys) | Select-Object -Unique | Sort-Object)
    $complete = ($unc.Count -eq 0 -and $refreshIncomplete.Count -eq 0 -and $script:collectionProblems.Count -eq 0)
    $nMail = 0; foreach ($k in $mailBy.Keys) { $nMail += $mailBy[$k].Count }
    $nCal = 0;  foreach ($k in $calBy.Keys)  { $nCal  += $calBy[$k].Count }
    $mailStatus = $(if ($uncMail.Count -eq 0 -and -not @($script:collectionProblems | Where-Object { $_ -notlike 'calendar *' }).Count -and -not @($refreshIncomplete | Where-Object { $_ -like '메일 *' }).Count) { 'complete' } else { 'partial' })
    $calendarStatus = $(if ($uncCal.Count -eq 0 -and -not @($refreshIncomplete | Where-Object { $_ -like '일정 *' }).Count -and -not @($script:collectionProblems | Where-Object { $_ -like 'calendar *' }).Count) { 'complete' } else { 'partial' })
    Write-OutlookStatus $root 'outlook_com' $requestedFrom $requestedTo $(if ($complete) { 'complete' } else { 'partial' }) ($script:observedRows + $script:observedCalendarRows) $scope @(@($warnings) + @($script:collectionProblems) + @($unc | ForEach-Object { 'uncovered month: ' + $_ })) @{ mail_scope = 'default_account_only'; mail_status = $mailStatus; calendar_status = $calendarStatus; mail_rows = $script:observedRows; calendar_rows = $script:observedCalendarRows; completed_units = (($months.Count * 2) - $uncMail.Count - $uncCal.Count); total_units = ($months.Count * 2); folders = $script:mailFolders.Count; body_requested = ($mailBody -and $storeSubject -and $contextChars -gt 0); context_chars = $contextChars }
    Clear-SkipReason            # 성공했으니 지난 사유는 지운다
    try {                       # 어느 경로가 채웠는지 기록 - 폴백(색인/Copilot)이 남긴 'index/copilot' 표식을 덮는다
        $src = [ordered]@{ source = 'com'; when = $now; mail = $nMail; calendar = $nCal;
                           calendar_complete = ($calendarStatus -eq 'complete'); calendar_recurring_masters = 0; me = @($me);
                           mail_truncated = ($uncMail.Count -gt 0); warnings = @($warnings);
                           coverage_complete = $complete; uncovered_months = @($unc);
                           uncovered_mail = @($uncMail); uncovered_calendar = @($uncCal);
                           partial_months = @($partialMonths); refresh_incomplete = @($refreshIncomplete);
                           months_read = [ordered]@{ mail = $readMail; calendar = $readCal };
                           period = @($since.ToString('yyyy-MM-dd'), $until.AddDays(-1).ToString('yyyy-MM-dd'));
                           budget_sec = $BudgetSec; elapsed_sec = [int]$sw.Elapsed.TotalSeconds;
                           selftest = [bool]$SelfTest; no_refresh = [bool]$NoRefresh }
        ($src | ConvertTo-Json -Compress -Depth 4) | Set-Content -Path $srcP -Encoding UTF8
    } catch {}
    Write-Host ("[outlook] mail rows: {0} · calendar rows: {1} (이번에 읽은 달: 메일 {2} / 일정 {3}, 경과 {4}초)" -f $nMail, $nCal, $readMail, $readCal, [int]$sw.Elapsed.TotalSeconds)
    if ($refreshIncomplete.Count) { Write-Host ("[outlook] 재수집 미완 {0} - 지난 수집분 유지(새 메일·일정 변경은 다음 실행에서)" -f ($refreshIncomplete -join ', ')) }
    if ($complete) {
        Write-Host '[outlook] coverage: complete - 기간의 모든 달을 읽었습니다'
        Write-Host '[outlook] done.'
    } else {
        Write-Host ("[outlook] coverage: partial - 미수집 달 {0}개: {1}{2}" -f $unc.Count, ($unc -join ','), $(if ($partialMonths.Count) { ' (이어 읽는 중: ' + ($partialMonths -join ',') + ')' } else { '' }))
        Write-Host '[outlook] done. (부분 수집 - 다음 실행이 남은 달을 이어서 읽습니다. 화면의 수집 데이터 현황에 표시됩니다)'
    }
}
catch {
    Write-Host ("[outlook] 수집 실패: {0}" -f $_.Exception.Message)
    Set-SkipReason ("수집 실패: " + $_.Exception.Message)
    if ($newOutlook) {
        Write-Host '          원인: "새 Outlook"(COM 미지원) - 클래식 Outlook 으로 전환/실행 후 재시도하세요.'
    } elseif ($_.Exception.Message -match '80010001|8001010A|RPC_E_CALL_REJECTED|RPC_E_SERVERCALL') {
        Write-Host '          원인: Outlook 이 응답하지 않습니다 - 보통 Outlook 이 대화상자를 띄우고 있을 때입니다.'
        Write-Host '          ("Outlook 시작" 설정 마법사, 프로필 선택, 암호 입력, 복구 창 등)'
        Write-Host '          Outlook 화면을 열어 떠 있는 창을 닫거나 설정을 끝낸 뒤 다시 수집하세요.'
        Write-Host '          (설치 문제가 아닙니다 - 재설치하지 마세요)'
    } elseif ($_.Exception.Message -match '80040154|REGDB_E_CLASSNOTREG') {
        Write-Host '          원인: 클래식 Outlook 이 설치돼 있지 않음(COM 미등록) - Microsoft 365 설치 옵션에서'
        Write-Host '          클래식 Outlook 을 추가하거나, 관리자에게 클래식 Outlook 배포를 요청하세요.'
    } else {
        Write-Host '          클래식 Outlook(2016~365)을 실행해 프로필 로그인까지 마친 상태에서 재시도하세요.'
        Write-Host '          (버전은 무관 - 2016/2019/2021/365 모두 동일하게 동작합니다)'
    }
    Write-OutlookStatus $root 'outlook_com' $requestedFrom $requestedTo $(if ($script:observedRows + $script:observedCalendarRows) { 'partial' } else { 'failed' }) ($script:observedRows + $script:observedCalendarRows) $scope @('COM collection exception; saved observations retained', $_.Exception.GetType().Name) @{ mail_scope = 'default_account_only'; mail_status = $(if ($script:observedRows) { 'partial' } else { 'failed' }); calendar_status = $(if ($script:observedCalendarRows) { 'partial' } else { 'failed' }); mail_rows = $script:observedRows; calendar_rows = $script:observedCalendarRows }
    exit 1
}
finally {
    if ($ol) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ol) }
}
