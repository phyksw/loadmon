# Test-CalBody.ps1 - 일정 본문(회의 안건) 수집(LM28): collect\OutlookCommon.ps1 의 Get-CalBody(가짜 일정 객체 - 보호 멤버 판정·
# 비공개·예외·자르기) + Get-OutlookData 자가검증 끝단(body 끝 열 · 완료 표 cal_body · 옛 9열 파일·표에서 일정 달만 다시 읽기).
# 값만 돌려준다 - 단언은 tests\test_p18_meeting_notes.py 가 한다. 실 Outlook 은 건드리지 않는다(-SelfTest).
# 임시 폴더는 %TEMP%\lm28_t18_* 하나 - 끝에 지운다.
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
. (Join-Path $root 'collect\OutlookCommon.ps1')
$r = [ordered]@{}

# ── 1) Get-CalBody ────────────────────────────────────────────────────────────────
# 읽는 순간 예외를 내는 값(경고창 거부 흉내) - ScriptProperty 안의 throw 는 PowerShell 이 삼켜 $null 이 되므로(5.1 실측),
# 문자열로 바꿀 때 예외를 내는 객체를 돌려준다(Get-CalBody 의 [string]$Item.Body 가 try 안에서 예외를 받는다)
class LmBadText { [string] ToString() { throw 'denied'; return '' } }
function New-Appt($Ctr, [int]$Sens, $Text, [switch]$Throw) {
    # Body 를 읽으면 $Ctr.n 이 는다(보호 멤버를 건드렸는지 세려고) - -Throw 면 읽을 때 예외
    $o = [pscustomobject]@{ Sensitivity = $Sens }
    if ($Throw) { $get = { $Ctr.n++; [LmBadText]::new() }.GetNewClosure() }
    else { $get = { $Ctr.n++; $Text }.GetNewClosure() }
    $o | Add-Member -MemberType ScriptProperty -Name Body -Value $get
    return $o
}
function Probe($Appt, [bool]$ProtOk, $Ctr, [int]$Max = 600) {
    $Ctr.n = 0
    $x = Get-CalBody -Item $Appt -ProtOk $ProtOk -Max $Max
    return [ordered]@{ why = [string]$x.why; body = [string]$x.body; len = ([string]$x.body).Length; touched = [int]$Ctr.n }
}
$ctr = @{ n = 0 }
$long = ('가' * 700)
$sur = ('a' * 599) + [char]::ConvertFromUtf32(0x1F600) + 'b'
$r.body = [ordered]@{
    ok      = Probe (New-Appt $ctr 0 ("안건: 시험 결과`r`n공유`t검토  끝")) $true $ctr
    private = Probe (New-Appt $ctr 2 '비공개 내용') $true $ctr
    conf    = Probe (New-Appt $ctr 3 '기밀 내용') $true $ctr
    prot    = Probe (New-Appt $ctr 0 '보호 멤버 위험') $false $ctr
    err     = Probe (New-Appt $ctr 0 '' -Throw) $true $ctr
    empty   = Probe (New-Appt $ctr 0 "  `r`n ") $true $ctr
    long    = Probe (New-Appt $ctr 1 $long) $true $ctr
    sur     = Probe (New-Appt $ctr 0 $sur) $true $ctr
}

# ── 2) 수집기 끝단(자가검증 - 실 Outlook 없음) ─────────────────────────────────────────
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('lm28_t18_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$gd = Join-Path $root 'collect\Get-OutlookData.ps1'
function Run-Col([string]$script, [hashtable]$argv) {
    # 같은 PowerShell 안에서 수집기를 돌린다(프로세스를 띄우지 않는다) - Write-Host(6)·오류(2)를 줄로 모은다
    $lines = @(& $script @argv 6>&1 2>&1 | ForEach-Object { [string]$_ })
    return @{ rc = $LASTEXITCODE; last = $(if ($lines.Count) { $lines[-1] } else { '' }); lines = $lines }
}
$oldSt = $env:LM_OUTLOOK_SELFTEST
try {
    $env:LM_OUTLOOK_SELFTEST = $null
    $today = (Get-Date).Date
    $from = (New-Object DateTime ($today.Year, $today.Month, 1)).AddMonths(-2).ToString('yyyy-MM-dd')
    $to = $today.ToString('yyyy-MM-dd')
    $dir = Join-Path $tmp 'src'
    $cal = Join-Path $dir 'cal_com.csv'; $cov = Join-Path $dir 'coverage_com.json'
    $a = @{ SelfTest = 4; From = $from; To = $to; OutDir = $dir; Tag = 'com'; BudgetSec = 120 }
    $c1 = Run-Col $gd $a
    $l1 = @(Get-Content -LiteralPath $cal -Encoding UTF8 | Where-Object { $_ })
    $j1 = Get-Content -Raw -Encoding UTF8 $cov | ConvertFrom-Json
    $cov1 = [bool]$j1.cal_body
    # 옛 판 흉내: 9열 머리·본문 없는 행 + cal_body 없는 완료 표 → 이어서 읽기(-NoRefresh)여도 일정 달만 다시 읽는다(메일 달은 그대로)
    $old = [System.Collections.Generic.List[string]]::new()
    $old.Add('start,end,all_day,busy_status,subject,categories,location,response,meeting_status')
    foreach ($ln in $l1[1..($l1.Count - 1)]) { $old.Add(($ln -replace ',[^,]*$', '')) }
    [System.IO.File]::WriteAllLines($cal, $old, (New-Object System.Text.UTF8Encoding($true)))
    $j1.PSObject.Properties.Remove('cal_body')
    ($j1 | ConvertTo-Json -Depth 7) | Set-Content -LiteralPath $cov -Encoding UTF8
    $a.NoRefresh = $true
    $c2 = Run-Col $gd $a
    $l2 = @(Get-Content -LiteralPath $cal -Encoding UTF8 | Where-Object { $_ })
    $cov2 = [bool]((Get-Content -Raw -Encoding UTF8 $cov | ConvertFrom-Json).cal_body)
    $c3 = Run-Col $gd $a                       # 다시 - 표가 맞으므로 일정 달도 건너뛴다
    # Get-Content 의 줄은 PSPath·PSDrive 꼬리표를 단 문자열이다 - 그대로 담으면 ConvertTo-Json 이 드라이브·공급자 객체를 끝없이
    # 펼친다(실측: 결과 JSON 이 600초 안에 안 끝남). [string] 으로 벗겨 담는다
    $r.col = [ordered]@{
        rc1 = $c1.rc; last1 = $c1.last; head1 = [string]$l1[0]; rows1 = $l1.Count - 1
        body1 =@($l1 | Where-Object { $_ -match ',selftest agenda \d+$' }).Count; cov1 = $cov1
        rc2 = $c2.rc; last2 = $c2.last; head2 = [string]$l2[0]; rows2 = $l2.Count - 1
        body2 = @($l2 | Where-Object { $_ -match ',selftest agenda \d+$' }).Count; cov2 = $cov2
        reread_note = @($c2.lines | Where-Object { $_ -match '일정 본문 읽기 설정이 지난 수집과 달라' }).Count
        rc3 = $c3.rc; last3 = $c3.last
    }
} finally {
    $env:LM_OUTLOOK_SELFTEST = $oldSt
    try { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction Stop } catch {}
    $r.tmp_removed = -not (Test-Path -LiteralPath $tmp)
}
return $r
