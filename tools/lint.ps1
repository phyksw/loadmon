<#
.SYNOPSIS
  LM27 관문 실행기 — 계약 §11.4 순서(편집 훅 → lint → selftest privacy → 단위 → 골든 → 페르소나·E2E → 패키지).

.DESCRIPTION
  -Stage 로 고른 단계까지 앞 단계부터 차례로 돌고, 앞 단계가 실패하면 다음 단계를 돌지 않는다(-Only = 그 단계만).
    static   tools\hook_check.py --repo : L-01~L-30 정적 관문(ruff --no-cache, node --check 는 개발 PC 전용)
    selftest tools\lm27_selftest.py privacy : 정제 회귀 말뭉치(T-08)
    unit     %TEMP% 복제 트리에서 tests\<영역> 마다 "<PY>" -X utf8 -B -m unittest discover -s <clone>\tests\<영역> -t <clone>
             (CR-08) + tests\web\run_node_tests.js(node 가 있을 때)
    golden   복제 트리에서 test_golden*.py
    e2e      복제 트리에서 tests\e2e
    package  tools\make_package.py --check(T-20 패키지 = 커밋)
  대상 도구·폴더가 아직 없으면 그 단계는 '건너뜀'으로 표시하고 통과로 센다(W0 중 다른 작업 패키지를 막지 않음).
  복제 트리는 WP-05 하네스 tests\fixtures\tree.py 로 만든다(계획 §3.2 — make --extra docs → 영역마다 discover →
  remove). 복제 안 %LOCALAPPDATA%·%TEMP% 는 샌드박스라 실제 에이전트 폴더를 건드리지 않는다. 끝나면 지운다
  (-KeepClone 이면 남김). tree.py 가 없으면 단위·골든·E2E 단계는 실패한다(복제 없이 돌리지 않는다).
  종료 코드: 0 = 돈 단계 전부 통과, 1 = 실패, 2 = 인자 오류.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\lint.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\lint.ps1 -Stage unit -Area core
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\lint.ps1 -Stage static -Only -Rules L-02,L-13
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\lint.ps1 -L12Staged   # 옛 단계 규칙(L-12 는 W2 통합 창부터 늘 전면 실패 — CR-05)
#>
[CmdletBinding()]
param(
    [ValidateSet('static', 'selftest', 'unit', 'golden', 'e2e', 'package')]
    [string]$Stage = 'static',
    [switch]$Only,
    [string[]]$Area = @(),
    [string[]]$Rules = @(),
    [switch]$L12Full,      # 호환(W2 통합 창부터 기본이 전면 실패라 효과 없음)
    [switch]$L12Staged,
    [string]$Python = '',
    [switch]$KeepClone
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'

$Root = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $emb = Join-Path $Root 'python\python.exe'
    if (Test-Path -LiteralPath $emb) { $Python = $emb } else { $Python = 'python' }
}
# -File 로 부르면 'core,privacy' 가 문자열 하나로 온다 — 직접 나눈다
$Area = @($Area | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$Rules = @($Rules | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })

$Order = @('static', 'selftest', 'unit', 'golden', 'e2e', 'package')
$script:Clone = $null

function Write-Line([string]$Text) { Write-Host $Text }

function Invoke-Py {
    param([string[]]$PyArgs)
    Push-Location -LiteralPath ([IO.Path]::GetTempPath())
    try {
        & $Python @PyArgs | Out-Host
        return [int]$LASTEXITCODE
    } finally { Pop-Location }
}

function Get-TreePy {
    $tp = Join-Path $Root 'tests\fixtures\tree.py'
    if (-not (Test-Path -LiteralPath $tp)) { throw '복제 트리 하네스 tests\fixtures\tree.py 없음(WP-05, 계획 §3.2)' }
    return $tp
}

function Get-Clone {
    # WP-05 tree.py make: %TEMP%\lm27t_<rand>\ + 복제 표지 + 샌드박스 %LOCALAPPDATA%·%TEMP%(계획 §3.2 · 계약 §11.3)
    if ($script:Clone) { return $script:Clone }
    $tp = Get-TreePy
    Push-Location -LiteralPath ([IO.Path]::GetTempPath())
    try {
        $out = @(& $Python -X utf8 -B $tp make --extra docs)
        $rc = [int]$LASTEXITCODE
    } finally { Pop-Location }
    if ($rc -ne 0 -or $out.Count -eq 0) { throw ("복제 트리 만들기 실패(tree.py make rc {0})" -f $rc) }
    $dst = ([string]$out[-1]).Trim()
    if (-not (Test-Path -LiteralPath (Join-Path $dst '.lm27t_clone'))) { throw ("복제 표지 없음: {0}" -f $dst) }
    if ((Resolve-Path -LiteralPath $dst).Path -eq (Resolve-Path -LiteralPath $Root).Path) { throw '복제 트리가 원본과 같음' }
    $script:Clone = $dst
    Write-Line ("  clone: {0}  (복제 트리 — tree.py 샌드박스)" -f $dst)
    return $dst
}

function Remove-Clone {
    if (-not $script:Clone) { return }
    $tp = Join-Path $Root 'tests\fixtures\tree.py'
    if (Test-Path -LiteralPath $tp) {
        Push-Location -LiteralPath ([IO.Path]::GetTempPath())
        try { & $Python -X utf8 -B $tp remove $script:Clone | Out-Null } finally { Pop-Location }
    }
    if (Test-Path -LiteralPath $script:Clone) { Write-Line ("  !! 복제 트리를 지우지 못함: {0}" -f $script:Clone) }
}

function Invoke-Discover {
    param([string]$Pattern, [string[]]$Areas, [string[]]$Exclude)
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'tests\__init__.py'))) {
        Write-Line '  건너뜀 — tests\__init__.py 없음'
        return 0
    }
    $tp = Get-TreePy
    $clone = Get-Clone
    $tests = Join-Path $clone 'tests'
    $dirs = @(Get-ChildItem -LiteralPath $tests -Directory | Where-Object {
            if ($Areas.Count -gt 0) { $Areas -contains $_.Name } else { $Exclude -notcontains $_.Name }
        } | Sort-Object Name)
    $fail = 0
    $ran = 0
    foreach ($d in $dirs) {
        if (-not (Test-Path -LiteralPath (Join-Path $d.FullName '__init__.py'))) { continue }
        Write-Line ("  -- tests\{0} ({1})" -f $d.Name, $Pattern)
        # 복제 안 실행 = "<PY>" -X utf8 -B -m unittest discover -s <clone>\tests\<영역> -t <clone>(CR-08), 환경은 tree.py 가 만든다
        $rc = Invoke-Py @('-X', 'utf8', '-B', $tp, 'discover', $clone, $d.Name, '--pattern', $Pattern)
        $ran++
        if ($rc -ne 0) { $fail = 1; Write-Line ("  !! tests\{0} 실패(rc {1})" -f $d.Name, $rc) }
    }
    foreach ($a in $Areas) {
        if (-not (Test-Path -LiteralPath (Join-Path $tests $a))) { Write-Line ("  !! 영역 없음: tests\{0}" -f $a); $fail = 1 }
    }
    if ($ran -eq 0) { Write-Line '  건너뜀 — 돌릴 시험 영역 없음' }
    return $fail
}

function Invoke-Stage([string]$Name) {
    switch ($Name) {
        'static' {
            $hc = Join-Path $Root 'tools\hook_check.py'
            $pa = @('-X', 'utf8', '-B', $hc, '--repo', '--root', $Root)
            if ($L12Staged) { $pa += '--l12-staged' } else { $pa += '--l12-full' }   # CR-05 — W2 통합 창부터 전면 실패
            if ($Rules.Count -gt 0) { $pa += $Rules }
            return (Invoke-Py $pa)
        }
        'selftest' {
            $st = Join-Path $Root 'tools\lm27_selftest.py'
            if (-not (Test-Path -LiteralPath $st)) { Write-Line '  건너뜀 — tools\lm27_selftest.py 없음'; return 0 }
            return (Invoke-Py @('-X', 'utf8', '-B', $st, 'privacy'))
        }
        'unit' {
            $rc = Invoke-Discover -Pattern 'test*.py' -Areas $Area -Exclude @('fixtures', 'e2e', '__pycache__')
            $nodeTests = Join-Path (Get-Clone) 'tests\web\run_node_tests.js'
            if (($Area.Count -eq 0 -or $Area -contains 'web') -and (Test-Path -LiteralPath $nodeTests)) {
                $node = Get-Command node -ErrorAction SilentlyContinue
                if ($node) {
                    Write-Line '  -- node tests\web\run_node_tests.js'
                    Push-Location -LiteralPath ([IO.Path]::GetTempPath())
                    try { & $node.Source $nodeTests | Out-Host; if ($LASTEXITCODE -ne 0) { $rc = 1 } } finally { Pop-Location }
                } else { Write-Line '  node 없음 — 웹 시험 건너뜀(개발 PC 전용)' }
            }
            return $rc
        }
        'golden' {
            return (Invoke-Discover -Pattern 'test_golden*.py' -Areas $Area -Exclude @('fixtures', '__pycache__'))
        }
        'e2e' {
            if (-not (Test-Path -LiteralPath (Join-Path $Root 'tests\e2e'))) { Write-Line '  건너뜀 — tests\e2e 없음'; return 0 }
            return (Invoke-Discover -Pattern 'test*.py' -Areas @('e2e') -Exclude @())
        }
        'package' {
            $mp = Join-Path $Root 'tools\make_package.py'
            if (-not (Test-Path -LiteralPath $mp)) { Write-Line '  건너뜀 — tools\make_package.py 없음(WP-41)'; return 0 }
            return (Invoke-Py @('-X', 'utf8', '-B', $mp, '--check'))
        }
    }
    return 2
}

$upto = [Array]::IndexOf($Order, $Stage)
if ($Only) { $run = @($Stage) } else { $run = @($Order[0..$upto]) }
$rcAll = 0
$summary = @()
try {
    foreach ($st in $run) {
        Write-Line ("== [{0}] ==" -f $st)
        $t0 = Get-Date
        try { $rc = [int](Invoke-Stage $st) } catch { Write-Line ("  !! {0}" -f $_.Exception.Message); $rc = 1 }
        $sec = [int]((Get-Date) - $t0).TotalSeconds
        if ($rc -eq 0) { $summary += ("[{0}] PASS 통과 {1}s" -f $st, $sec) }
        else {
            $summary += ("[{0}] FAIL 실패 rc={1} {2}s" -f $st, $rc, $sec)
            $rcAll = 1
            $rest = @($run | Select-Object -Skip ([Array]::IndexOf($run, $st) + 1))
            if ($rest.Count -gt 0) { $summary += ("[{0}] NOT-RUN 돌지 않음 — 앞 단계 실패" -f ($rest -join ',')) }
            break
        }
    }
} finally {
    if ($script:Clone -and -not $KeepClone) { Remove-Clone }
}
Write-Line '== lint 요약 =='
$summary | ForEach-Object { Write-Line ("  " + $_) }
exit $rcAll
