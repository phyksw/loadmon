# Run-PsTests.ps1 - tests\ps\Test-*.ps1 을 이 PowerShell 하나 안에서 모두 돌리고 결과를 JSON 한 파일로 남긴다.
# tests\run_tests.py --ps 가 1회만 띄운다(개발 PC 는 끝난 프로세스가 커널에 남으므로 시험마다 powershell 을 띄우지 않는다).
# 약속:
#   · 각 Test-<이름>.ps1 은 마지막에 결과 해시테이블 하나를 돌려준다(return @{ ... }). 실 Outlook·Teams·Edge 는 띄우지 않는다.
#   · 결과 파일: $env:LM_PS_RESULTS  =  { "<이름>": { ...그 시험이 돌려준 값... }, ... }
#     예외로 끝난 시험은 { "error": "<메시지>" } 로 남는다 - 파이썬 쪽 test_pN 이 그것을 실패로 단언한다.
#   · $env:LM_PS_ONLY = '이름1,이름2' 면 그 시험만 돈다.
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = [string]$env:LM_PS_RESULTS
if (-not $out) { Write-Host '[ps] LM_PS_RESULTS 가 비어 있습니다 - tests\run_tests.py --ps 로 실행하세요'; exit 2 }
$only = @()
if ($env:LM_PS_ONLY) { $only = @(([string]$env:LM_PS_ONLY).Split(',') | Where-Object { $_ }) }

$results = [ordered]@{}
$nOk = 0; $nErr = 0
foreach ($f in @(Get-ChildItem -LiteralPath $here -Filter 'Test-*.ps1' | Sort-Object Name)) {
    $name = $f.BaseName.Substring(5)
    if ($only.Count -and $only -notcontains $name) { continue }
    $t0 = [datetime]::Now
    try {
        $o = @(& $f.FullName)
        $r = $null
        for ($i = $o.Count - 1; $i -ge 0; $i--) {
            if ($o[$i] -is [System.Collections.IDictionary] -or $o[$i] -is [System.Management.Automation.PSCustomObject]) { $r = $o[$i]; break }
        }
        if ($null -eq $r) { $r = @{ error = '결과 해시테이블을 돌려주지 않음' }; $nErr++ } else { $nOk++ }
    } catch {
        $r = @{ error = ($_.Exception.Message + ' @ ' + [string]$_.InvocationInfo.ScriptLineNumber) }
        $nErr++
    }
    $results[$name] = $r
    Write-Host ("[ps] {0}: {1} ({2:N1}s)" -f $name, $(if ($r -is [System.Collections.IDictionary] -and $r.Contains('error')) { '오류 - ' + $r['error'] } else { 'OK' }), ([datetime]::Now - $t0).TotalSeconds)
}
$json = $results | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($out, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ("[ps] 시험 {0}개 - 결과 {1}개 · 오류 {2}개 → {3}" -f ($nOk + $nErr), $nOk, $nErr, $out)
exit 0
