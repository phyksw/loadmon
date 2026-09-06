# Get-OutlookIndex.ps1 - Outlook 메일·일정을 Windows Search 색인(SYSTEMINDEX)에서 읽는 폴백.
# 클래식 Outlook COM 이 막힌 PC(시작 마법사·프로필 선택·COM 미등록)에서도, 색인 서비스가
# Outlook 사서함을 색인하고 있으면 메일·일정 메타데이터를 읽을 수 있다(읽기 전용, Outlook 을
# 띄우지 않으므로 마법사 무한 대기가 없다).
# Usage:  .\Get-OutlookIndex.ps1 -From 2026-01-01 -To 2026-06-30 [-Force] [-Only mail|cal]
#   기존 mail.csv / calendar.csv 에 자료가 있으면 건드리지 않는다(-Force 로 덮어쓰기).
# 한계(감사 outlook-7): 색인은 MAPI 항목 단위라 반복 회의는 '마스터 1건' 뿐이고 회차가 전개되지 않는다
#   (COM 의 IncludeRecurrences 와 다름). 마스터 행은 calendar.csv 에 쓰지 않고(첫 회차 1건만 남기면 전개된
#   것처럼 보인다) 그 수를 mail_source.json 의 calendar_recurring_masters 에, calendar_complete=false 로 적고
#   exit 3 - run.py 가 Outlook 웹(주 보기 = 회차 전개)으로 일정만 다시 읽는다.
# rcv(to/cc/bulk): 내 주소·이름을 whoami /upn → UserPrincipal → AD(도메인 PC) → Outlook 프로필 레지스트리 →
#   config.owner 순으로 모아 To/CC 주소와 표시 이름 양쪽에 맞춘다. 내 주소를 끝내 모르면 'unknown' 으로 남긴다
#   (To 4명 이상을 bulk 로 버리거나 CC 를 to 로 올리지 않는다 - 분석기는 unknown 을 직접 수신처럼 계상).
# 종료 코드: 0 저장 / 1 아무것도 못 읽음 / 3 저장했지만 일정 불완전(반복 회의 미전개)
# 시험용: LM_INDEX_FAKE=<json> 이면 색인 대신 그 파일의 행을 쓴다 -
#   {"mail":[{"System.ItemUrl":"mapi://…","System.Message.DateReceived":"2026-06-03 10:00", …}], "calendar":[…]}
#   (키 = System.* 속성명, 시각은 로컬 'yyyy-MM-dd HH:mm')
param(
    [string]$From = '',
    [string]$To = '',
    [int]$Days = 90,
    [switch]$Force,
    [string]$Only = ''      # 'mail' | 'cal' - run.py 가 필요한 종류만 지정 (빈 값 = 둘 다)
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$cfg = $null
try { $cfg = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json } catch {}
$storeSubject = $true
if ($cfg -and $cfg.PSObject.Properties['storeMailSubject'] -and -not $cfg.storeMailSubject) { $storeSubject = $false }
$outDir = Join-Path $root 'data\outlook'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

function Csv-Escape([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "[`r`n]", ' '
    if ($s -match '[",]') { return '"' + ($s -replace '"', '""') + '"' }
    return $s
}
function Has-Data([string]$p) {
    if (-not (Test-Path -LiteralPath $p)) { return $false }
    try { return ((Get-Content -LiteralPath $p | Where-Object { $_.Trim() }).Count -gt 1) } catch { return $false }
}
function Conv-Token([string]$s) {
    # storeMailSubject=false 일 때 conversation 열의 대체값 - 원문 대신 짧은 해시(회신 이력 판정만 유지).
    # 정규화(공백 접기·trim·소문자)와 SHA1 앞 10자리는 웹·Copilot·COM 경로와 같은 규칙이다.
    $n = (([string]$s -replace '\s+', ' ').Trim()).ToLower()
    if (-not $n) { return '' }
    $sha = [System.Security.Cryptography.SHA1]::Create()
    try { $h = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($n)) } finally { $sha.Dispose() }
    return '#' + ((($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 10))
}

if ($From) { $since = [datetime]::ParseExact($From, 'yyyy-MM-dd', $null) } else { $since = (Get-Date).Date.AddDays(-$Days) }
if ($To)   { $until = ([datetime]::ParseExact($To, 'yyyy-MM-dd', $null)).AddDays(1) } else { $until = (Get-Date).Date.AddDays(1) }
$mailP = Join-Path $outDir 'mail.csv'
$calP  = Join-Path $outDir 'calendar.csv'
$doMail = $Force -or -not (Has-Data $mailP)
$doCal  = $Force -or -not (Has-Data $calP)
if ($Only -eq 'mail') { $doCal = $false } elseif ($Only -eq 'cal') { $doMail = $false }
if (-not $doMail -and $Only -ne 'cal') { Write-Host '[outlook-index] mail.csv 에 이미 자료가 있어 건너뜀 (덮어쓰려면 -Force)' }
if (-not $doCal -and $Only -ne 'mail') { Write-Host '[outlook-index] calendar.csv 에 이미 자료가 있어 건너뜀 (덮어쓰려면 -Force)' }
if (-not $doMail -and -not $doCal) { exit 0 }

# 내 주소·이름 - rcv(to/cc/bulk) 판정용. 도메인 미가입 PC 는 whoami /upn 이 실패한다(실측: 종료코드 1·빈값)
# 그래서 여러 출처를 겹쳐 본다. USERNAME 은 약한 단서라 매칭에는 쓰되 '내 주소를 안다' 로 치지 않는다.
$me = @(); $meSrc = @()
if ($doMail) {
    try {
        $u = (& whoami /upn 2>$null)
        if ($LASTEXITCODE -eq 0 -and $u) { $me += ([string]$u).Trim().ToLower(); $meSrc += 'upn' }
    } catch {}
    try {
        Add-Type -AssemblyName System.DirectoryServices.AccountManagement -ErrorAction Stop
        $up = [System.DirectoryServices.AccountManagement.UserPrincipal]::Current
        if ($up) {
            foreach ($v in @($up.EmailAddress, $up.UserPrincipalName, $up.DisplayName)) {
                if ($v) { $me += ([string]$v).Trim().ToLower(); $meSrc += 'principal' }
            }
        }
    } catch {}
    try {
        if ($env:USERDNSDOMAIN) {       # 도메인 PC 만 - 아니면 LDAP 조회가 길게 기다린다
            $srch = [adsisearcher]('(&(objectCategory=person)(sAMAccountName=' + $env:USERNAME + '))')
            $srch.ClientTimeout = [TimeSpan]::FromSeconds(5)
            $srch.ServerTimeLimit = [TimeSpan]::FromSeconds(5)
            [void]$srch.PropertiesToLoad.AddRange([string[]]@('mail', 'displayName', 'userPrincipalName'))
            $res = $srch.FindOne()
            if ($res) {
                foreach ($k in @('mail', 'displayname', 'userprincipalname')) {
                    foreach ($v in @($res.Properties[$k])) { if ($v) { $me += ([string]$v).Trim().ToLower(); $meSrc += 'adsi' } }
                }
            }
        }
    } catch {}
    try {
        # Outlook 프로필의 계정 주소(레지스트리, 읽기 전용) - Outlook 을 띄우지 않고 SMTP 주소를 안다
        foreach ($pp in @('HKCU:\Software\Microsoft\Office\16.0\Outlook\Profiles',
                          'HKCU:\Software\Microsoft\Office\15.0\Outlook\Profiles',
                          'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles')) {
            if (-not (Test-Path $pp)) { continue }
            foreach ($k in @(Get-ChildItem -Path $pp -Recurse -ErrorAction SilentlyContinue | Select-Object -First 400)) {
                foreach ($name in @('Account Name', 'Email')) {
                    $raw = $null
                    try { $raw = $k.GetValue($name) } catch {}
                    if ($raw -is [byte[]] -and $raw.Length -ge 4) { $raw = [System.Text.Encoding]::Unicode.GetString($raw).TrimEnd([char]0) }
                    if ($raw -is [string] -and $raw -match '^[^@\s]+@[^@\s]+\.[^@\s]+$') { $me += $raw.Trim().ToLower(); $meSrc += 'profile' }
                }
            }
        }
    } catch {}
    if ($cfg -and $cfg.owner) { $me += ([string]$cfg.owner).Trim().ToLower(); $meSrc += 'owner' }
    if ($env:USERNAME) { $me += $env:USERNAME.ToLower(); $meSrc += 'username' }
    $me = @($me | Where-Object { $_ -and $_.Length -ge 2 } | Select-Object -Unique)
}
$meKnown = [bool](@($meSrc | Where-Object { $_ -ne 'username' }).Count)
if ($doMail) {
    Write-Host ("[outlook-index] 내 주소/이름 후보 {0}개 (출처: {1}){2}" -f $me.Count, (($meSrc | Select-Object -Unique) -join ','),
        $(if ($meKnown) { '' } else { ' - 내 주소를 확정하지 못해 rcv 는 unknown(To 다수를 bulk 로 버리지 않음)' }))
}

$fake = $null
if ($env:LM_INDEX_FAKE) {
    try { $fake = Get-Content -Raw -Encoding UTF8 $env:LM_INDEX_FAKE | ConvertFrom-Json } catch { $fake = $null }
    Write-Host '[outlook-index] LM_INDEX_FAKE - 색인 대신 시험용 행을 씁니다'
}
$conn = $null
if (-not $fake) {
    $conn = New-Object System.Data.OleDb.OleDbConnection("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
    try { $conn.Open() } catch {
        Write-Host ('[outlook-index] Windows Search 색인에 연결할 수 없습니다: ' + $_.Exception.Message.Split([char]10)[0])
        Write-Host '                (Windows Search 서비스가 꺼져 있거나 색인이 비활성화된 PC)'
        exit 1
    }
}
function Query([string]$sql, [int]$cap) {
    $rows = New-Object System.Collections.Generic.List[object]
    $cmd = $conn.CreateCommand(); $cmd.CommandText = $sql
    $rd = $cmd.ExecuteReader()
    try {
        while ($rd.Read()) {
            $o = @{}
            for ($i = 0; $i -lt $rd.FieldCount; $i++) { $o[$rd.GetName($i)] = $rd.GetValue($i) }
            $rows.Add($o)
            if ($rows.Count -ge $cap) { break }
        }
    } finally { $rd.Close() }
    return $rows
}
function Fake-Rows([string]$kind) {
    # 시험용 JSON → 색인 행과 같은 모양(hashtable). 시각 문자열은 UTC Kind 의 datetime 으로 - D() 가 ToLocalTime 하므로
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($o in @($fake.$kind)) {
        if ($null -eq $o) { continue }
        $h = @{}
        foreach ($p in $o.PSObject.Properties) {
            $v = $p.Value
            if ($v -is [string] -and $v -match '^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}') {
                $v = [datetime]::SpecifyKind([datetime]::Parse($v), 'Local').ToUniversalTime()
            }
            $h[$p.Name] = $v
        }
        $rows.Add($h)
    }
    return $rows
}
function Run-Query([string]$kind, [string]$sqlNew, [string]$sqlOld, [int]$cap) {
    # 확장 속성(ToName/CcName·IsRecurring)이 이 PC 의 색인에서 거부되면 기본 속성으로 재시도한다 - 회귀 방지
    if ($fake) { return @{ rows = @(Fake-Rows $kind); fallback = $false } }
    try { return @{ rows = @(Query $sqlNew $cap); fallback = $false } }
    catch {
        Write-Host ('[outlook-index] ' + $kind + ' 조회(확장 속성) 실패: ' + $_.Exception.Message.Split([char]10)[0] + ' - 기본 속성으로 재시도')
        try { return @{ rows = @(Query $sqlOld $cap); fallback = $true } }
        catch {
            Write-Host ('[outlook-index] ' + $kind + ' 조회 실패: ' + $_.Exception.Message.Split([char]10)[0])
            return @{ rows = @(); fallback = $true }
        }
    }
}
function V($o, [string]$k) { $v = $o[$k]; if ($null -eq $v -or $v -is [System.DBNull]) { return '' } ; if ($v -is [array]) { return (($v | ForEach-Object { [string]$_ }) -join ';') } ; return [string]$v }
function D($o, [string]$k) { $v = $o[$k]; if ($v -is [datetime]) { return $v.ToLocalTime() } ; return $null }
# Windows Search SQL 의 날짜 리터럴은 UTC 로 해석된다 - 현지 자정을 UTC 로 바꿔 넣어야 경계가 밀리지 않는다
$fmt = 'yyyy-MM-dd HH:mm:ss'
$sinceU = $since.ToUniversalTime().ToString($fmt)
$untilU = $until.ToUniversalTime().ToString($fmt)
function Is-Me([string]$list) {
    # 내 주소·이름이 수신자 목록에 '한 항목으로' 들어 있는가 - 부분 문자열(kim ⊂ kimchulsoo@) 오판 방지
    if (-not $list) { return $false }
    foreach ($m in $me) {
        if (-not $m) { continue }
        if ($list -match ('(^|[;,\s<"' + "'" + '])' + [regex]::Escape($m) + '(@|$|[;,\s>"' + "'" + '])')) { return $true }
    }
    return $false
}
function Count-Rcpt([string]$list) {
    if (-not $list) { return 0 }
    return @($list.Split(';') | Where-Object { $_.Trim() }).Count
}

$nMail = 0; $nCal = 0; $nRec = 0; $nUnk = 0
$warnings = New-Object System.Collections.Generic.List[string]
# ---------- mail ----------
if ($doMail) {
    $selBase = ("SELECT System.ItemDate, System.Message.DateReceived, System.Message.DateSent, System.Message.FromName, " +
                "System.Message.FromAddress, System.Message.ToAddress, System.Message.CcAddress, System.Subject, " +
                "System.ItemFolderPathDisplay, System.ItemUrl{0} FROM SYSTEMINDEX WHERE System.Kind = 'email' " +
                "AND System.ItemUrl LIKE 'mapi%' " +     # Outlook 저장소 항목만(mapi:/mapi15:/mapi16:) - 디스크의 .msg/.eml 파일 제외(검증 실측 290건 오염)
                "AND System.ItemDate >= '{1}' AND System.ItemDate < '{2}' ORDER BY System.ItemDate DESC")
    $sqlNew = $selBase -f ', System.Message.ToName, System.Message.CcName', $sinceU, $untilU   # 표시 이름으로도 나를 찾는다(X500·별칭 주소 대응)
    $sqlOld = $selBase -f '', $sinceU, $untilU
    $res = Run-Query 'mail' $sqlNew $sqlOld 20000
    $mailRows = New-Object System.Collections.Generic.List[string]
    $mailRows.Add('box,time,sender,subject,conversation,rcv')
    $nIn = 0; $nSent = 0; $nSkip = 0; $nCc = 0; $nBulk = 0
    foreach ($r in $res.rows) {
        try {
            $folder = (V $r 'System.ItemFolderPathDisplay')
            $url = (V $r 'System.ItemUrl')
            if ($url -notmatch '^mapi\d*:') { $nSkip++; continue }     # SQL 필터의 이중 안전장치
            # 폴더는 경로 조각 단위로 정확히 본다 - '지운 편지함'(한국어 삭제함)을 놓치거나 'Presentations' 를 Sent 로 오인하지 않게
            $segs = @(($folder -split '[\\/]') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            if (@($segs | Where-Object { $_ -match '^(지운 편지함|삭제된 항목|삭제된 편지함|Deleted Items|Trash|정크 메일|Junk E-?mail|Junk|스팸|Spam|임시 보관함|Drafts?|보낼 편지함|Outbox|보관|보관함|Archive|동기화 문제|Sync Issues|대화 기록|Conversation History|RSS 피드|RSS Feeds)$' }).Count) { $nSkip++; continue }
            $box = 'inbox'
            if (@($segs | Where-Object { $_ -match '^(보낸\s*(편지함|메일함|항목)|Sent(\s+(Items|Mail|Messages))?)$' }).Count) { $box = 'sent' }
            $t = $null
            if ($box -eq 'sent') { $t = D $r 'System.Message.DateSent' }
            if (-not $t) { $t = D $r 'System.Message.DateReceived' }
            if (-not $t) { $t = D $r 'System.ItemDate' }
            if (-not $t) { continue }
            $subjRaw = (V $r 'System.Subject')
            $conv = $subjRaw
            while ($conv -match '^\s*(RE|FW|FWD|답장|전달|회신)\s*:\s*') { $conv = $conv -replace '^\s*(RE|FW|FWD|답장|전달|회신)\s*:\s*', '' }
            $subj = ''
            if ($storeSubject) { $subj = $subjRaw } else { $conv = Conv-Token $conv }   # 제목을 남기지 않을 때도 회신 이력은 해시로
            $sender = (V $r 'System.Message.FromName')
            if (-not $sender) { $sender = (V $r 'System.Message.FromAddress') }
            $rcv = ''
            if ($box -eq 'inbox') {
                $to = (V $r 'System.Message.ToAddress').ToLower()
                $cc = (V $r 'System.Message.CcAddress').ToLower()
                $toN = (V $r 'System.Message.ToName').ToLower()
                $ccN = (V $r 'System.Message.CcName').ToLower()
                if ((Is-Me $to) -or (Is-Me $toN)) { $rcv = 'to' }
                elseif ((Is-Me $cc) -or (Is-Me $ccN)) { $rcv = 'cc'; $nCc++ }
                elseif (-not $meKnown) { $rcv = 'unknown'; $nUnk++ }     # 내 주소를 모른다 - bulk 로 버리지도, CC 를 to 로 올리지도 않는다
                elseif (-not $to -and -not $toN) { $rcv = 'to' }          # 수신자 정보가 없는 항목 - 보수적으로 직접 수신
                elseif ([math]::Max((Count-Rcpt $to), (Count-Rcpt $toN)) -le 3) { $rcv = 'to' }   # 소규모 수신 - 별칭/X500 표기 차이일 가능성
                else { $rcv = 'bulk'; $nBulk++ }
                $nIn++
            } else { $nSent++ }
            $mailRows.Add(('{0},{1},{2},{3},{4},{5}' -f $box, $t.ToString('yyyy-MM-dd HH:mm'), (Csv-Escape $sender), (Csv-Escape $subj), (Csv-Escape $conv), $rcv))
        } catch {}
    }
    $nMail = $mailRows.Count - 1
    if ($nMail -gt 0) {
        [System.IO.File]::WriteAllLines($mailP, $mailRows, [System.Text.Encoding]::UTF8)
        Write-Host ("[outlook-index] mail rows: {0} (inbox {1} [cc {2} · bulk {3} · unknown {4}] / sent {5}, 제외 {6})" -f $nMail, $nIn, $nCc, $nBulk, $nUnk, $nSent, $nSkip)
        if ($nUnk -gt 0) { $warnings.Add(('내 주소 미확정 - 수신 {0}건 rcv=unknown(직접 수신처럼 계상, CC 구분 불가)' -f $nUnk)) }
    } else {
        Write-Host '[outlook-index] 색인에서 기간 내 메일을 찾지 못했습니다.'
    }
}
# ---------- calendar ----------
$calComplete = $true
if ($doCal) {
    $selCal = ("SELECT System.StartDate, System.EndDate, System.Subject, System.Calendar.Location, System.Calendar.ShowTimeAs{0}, " +
               "System.ItemUrl FROM SYSTEMINDEX WHERE System.Kind = 'calendar' AND System.ItemUrl LIKE 'mapi%' " +
               "AND System.EndDate >= '{1}' AND System.StartDate < '{2}'")
    $sqlNew = $selCal -f ', System.Calendar.IsRecurring', $sinceU, $untilU
    $sqlOld = $selCal -f '', $sinceU, $untilU
    $res = Run-Query 'calendar' $sqlNew $sqlOld 8000
    $recUnknown = [bool]$res.fallback          # 반복 여부를 읽지 못했다 - 마스터가 섞여 있어도 가려낼 수 없다
    $calRows = New-Object System.Collections.Generic.List[string]
    $calRows.Add('start,end,all_day,busy_status,subject,categories,location,response,meeting_status')   # response/meeting_status 는 색인에 없어 빈값
    foreach ($r in $res.rows) {
        try {
            if ((V $r 'System.ItemUrl') -notmatch '^mapi\d*:') { continue }     # 디스크의 .ics 파일 제외
            $isRec = $r['System.Calendar.IsRecurring']
            if (($isRec -is [bool] -and $isRec) -or ([string]$isRec -match '^(True|1|-1)$')) { $nRec++; continue }   # 반복 마스터 - 회차 전개 불가, 쓰지 않는다
            $st = D $r 'System.StartDate'; $en = D $r 'System.EndDate'
            if (-not $st -or -not $en) { continue }
            $allDay = 'False'
            if ($st.TimeOfDay.TotalMinutes -eq 0 -and ($en - $st).TotalHours -ge 23) { $allDay = 'True' }
            $busy = (V $r 'System.Calendar.ShowTimeAs'); if (-not $busy) { $busy = '2' }
            $subj = ''
            if ($storeSubject) { $subj = (V $r 'System.Subject') }
            $calRows.Add(('{0},{1},{2},{3},{4},{5},{6},,' -f $st.ToString('yyyy-MM-dd HH:mm'), $en.ToString('yyyy-MM-dd HH:mm'), $allDay, $busy, (Csv-Escape $subj), '', (Csv-Escape (V $r 'System.Calendar.Location'))))
        } catch {}
    }
    $nCal = $calRows.Count - 1
    $calComplete = (($nRec -eq 0) -and -not $recUnknown)
    if ($nCal -gt 0) {
        [System.IO.File]::WriteAllLines($calP, $calRows, [System.Text.Encoding]::UTF8)
        Write-Host ("[outlook-index] calendar rows: {0} (반복 마스터 {1}건 제외)" -f $nCal, $nRec)
    } else {
        Write-Host ("[outlook-index] 색인에서 기간 내 일정을 찾지 못했습니다.{0}" -f $(if ($nRec -gt 0) { " (반복 마스터 {0}건은 회차가 전개되지 않아 쓰지 않음)" -f $nRec } else { '' }))
    }
    if ($nRec -gt 0) { $warnings.Add(('반복 회의 마스터 {0}건 미전개(색인 한계) - Outlook 웹으로 일정 재수집 필요' -f $nRec)) }
    elseif ($recUnknown) { $warnings.Add('반복 여부(IsRecurring)를 읽지 못해 일정 완전성을 보증할 수 없음') }
}
try { if ($conn) { $conn.Close() } } catch {}

if ($nMail -gt 0 -or $nCal -gt 0 -or $nRec -gt 0) {
    try {
        $o = [ordered]@{ source = 'index'; when = (Get-Date).ToString('yyyy-MM-dd HH:mm'); mail = $nMail; calendar = $nCal;
                         calendar_complete = [bool]$calComplete; calendar_recurring_masters = $nRec;
                         me = @($me); me_known = [bool]$meKnown; rcv_unknown = $nUnk; warnings = @($warnings) }
        ($o | ConvertTo-Json -Compress) | Set-Content -Path (Join-Path $outDir 'mail_source.json') -Encoding UTF8
    } catch {}
    if ($nMail -gt 0) { try { Remove-Item (Join-Path $outDir 'outlook_skip.json') -ErrorAction SilentlyContinue } catch {} }
    if ($doCal -and -not $calComplete) {
        Write-Host ("[outlook-index] 일정 불완전: 반복 회의 마스터 {0}건은 회차가 전개되지 않아 쓰지 않음 - Outlook 웹(주 보기)으로 일정 재수집 (exit 3)" -f $nRec)
        exit 3
    }
    Write-Host '[outlook-index] done (Windows Search 색인 폴백).'
    exit 0
}
Write-Host '[outlook-index] 색인 폴백으로도 메일·일정을 얻지 못했습니다 - 이 PC 의 색인이 Outlook 을 포함하지 않거나'
Write-Host '                (새 Outlook 은 색인을 제공하지 않음) 기간에 항목이 없습니다. 다음 폴백: Outlook 웹 → Copilot 메일 수집.'
exit 1
