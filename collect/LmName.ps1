# LmName.ps1 - AF32 이름 단일원(PowerShell 쪽). core\lmname.py 와 같은 규칙이다 - 하나를 바꾸면 둘 다 바꾼다.
# 같은 PC 의 AF32 두 벌(개발 사본·배포본)을 가르는 설치 폴더 해시 6자리(h6)를 낸다. AF32 에는 예약 작업·뮤텍스가 없다.
# 같은 PC 의 LM28·LM29·LM30 과는 Short·Product·TmpPrefix 로 갈린다(시험이 core\lmname.py 의 SHORT·PRODUCT·TMP_PREFIX 와 비교한다).
# h6 = sha1(UTF-8(소문자(끝 구분자 제거(GetLongPathName(GetFullPath(경로))))))[:6]
# 사용(dot-source):  . (Join-Path $PSScriptRoot 'LmName.ps1');  $nm = Get-LmNames $root;  $nm.H6
# 시험: tests\ps\Test-LmName.ps1 (같은 고정 경로의 h6·이름을 Python 과 비교)
# 시작 확인: Test-Af32Consent $root - 화면·run.py 와 같은 판정(core\consent.py --status --json 이 종료 코드 0)일 때만 $true.
#   이 설치 폴더의 자료가 지금 Windows 사용자의 것이고 '모두 지우기'가 진행 중이 아닐 때만 통과한다. 파이썬이 없거나 실패하면
#   $false(닫힌 쪽). 수집기는 이 함수가 $false 면 아무것도 읽지 않고 종료 코드 3 으로 끝낸다. 까닭은 $script:Af32ConsentWhy 에 남는다.

function Get-LmLongPath([string]$p) {
    # 8.3 짧은 이름(PROGRA~1)만 GetLongPathName 이 바꾼다 - '~' 가 없으면 결과가 같으므로 P/Invoke(Add-Type 은
    # 컴파일러 프로세스를 띄운다)를 건너뛴다. 없는 경로는 API 가 실패하므로 받은 값을 그대로 쓴다.
    if ($p -notlike '*~*') { return $p }
    try {
        if (-not ('LmNamePath' -as [type])) {
            Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class LmNamePath {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern uint GetLongPathName(string shortPath, StringBuilder longPath, uint bufLen);
}
"@
        }
        $sb = New-Object System.Text.StringBuilder 32768
        $n = [LmNamePath]::GetLongPathName($p, $sb, [uint32]32768)
        if ($n -gt 0 -and $n -lt 32768) { return $sb.ToString() }
    } catch {}
    return $p
}

function Get-LmNormRoot([string]$Path) {
    $p = [string]$Path
    try { $p = [System.IO.Path]::GetFullPath($p) } catch {}
    $p = Get-LmLongPath $p
    $p = $p.TrimEnd([char[]]@('\', '/'))
    return $p.ToLowerInvariant()
}

function Get-LmH6([string]$Path) {
    $norm = Get-LmNormRoot $Path
    $sha = [System.Security.Cryptography.SHA1]::Create()
    try { $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($norm)) } finally { $sha.Dispose() }
    return ((($bytes | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 6))
}

function Get-LmNames([string]$Root) {
    # 키는 core\lmname.py names() 와 같다(H6) + 이름 상수(core\lmname.py 의 같은 이름 상수와 같은 값)
    $h = Get-LmH6 $Root
    return @{
        H6              = $h
        Short           = 'AF32'
        Product         = 'AgentFinder32'
        TmpPrefix       = 'af32_'
        DisplayTitle    = 'AgentFinder32 · Agentic AI 전환 과제 발굴'
        TeamDefaultPort = 9390
        ShareSchema     = 'af32-share-1'
        SharePrefix     = '/af32'
    }
}

function Get-Af32Python([string]$Root) {
    # 시작 확인을 돌릴 파이썬 - bat 들과 같은 순서다. 설치 폴더의 내장 파이썬(python\python.exe)이 있으면 그것 하나만 쓴다
    # (깨졌으면 다른 파이썬으로 넘어가지 않는다). 없으면(내장 파이썬 없이 받은 배포본) PATH 의 python.exe, 그다음 py.exe -3.
    # 반환 = @( @{ exe = 실행 파일; pre = @(앞 인자) } … ) - 비면 파이썬이 없다(내 자료인지 확인할 수 없다).
    $out = New-Object System.Collections.Generic.List[object]
    $emb = Join-Path $Root 'python\python.exe'
    if (Test-Path -LiteralPath $emb -PathType Leaf) { $out.Add(@{ exe = $emb; pre = @() }); return $out.ToArray() }
    foreach ($c in @(@{ n = 'python.exe'; pre = @() }, @{ n = 'py.exe'; pre = @('-3') })) {
        $cmd = $null
        try { $cmd = Get-Command -Name $c.n -CommandType Application -ErrorAction Stop | Select-Object -First 1 } catch { $cmd = $null }
        if ($cmd -and $cmd.Source) { $out.Add(@{ exe = [string]$cmd.Source; pre = $c.pre }) }
    }
    return $out.ToArray()
}

function ConvertTo-Af32Arg([string]$s) {
    # 명령줄 인자 하나 - Windows(CommandLineToArgvW) 규칙으로 따옴표를 친다. 공백·한글·괄호가 든 설치 경로와 끝의 역슬래시('C:\')를
    # 그대로 넘긴다(따옴표 앞 역슬래시는 두 배, 닫는 따옴표 앞 끝 역슬래시도 두 배).
    if ($s.Length -gt 0 -and $s -notmatch '[\s"]') { return $s }
    $q = [regex]::Replace($s, '(\\*)"', { param($m) ($m.Groups[1].Value * 2) + '\"' })
    $q = [regex]::Replace($q, '(\\+)$', { param($m) $m.Groups[1].Value * 2 })
    return '"' + $q + '"'
}

function Invoke-Af32Py([string]$Exe, [string[]]$Arguments, [string]$Dir, [int]$TimeoutSec = 60) {
    # 파이썬 한 번 - 창 없이, 출력은 받아서 버린다(수집기 출력에 섞지 않는다). $TimeoutSec 넘으면 끝낸다.
    # 반환 @{ how = 'exit'(끝남) | 'start'(띄우지 못함) | 'timeout'; rc = 종료 코드 }
    $p = $null
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Exe
        $psi.Arguments = (@($Arguments | ForEach-Object { ConvertTo-Af32Arg ([string]$_) }) -join ' ')
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        if ($Dir) { $psi.WorkingDirectory = $Dir }
        try { $p = [System.Diagnostics.Process]::Start($psi) } catch { return @{ how = 'start'; rc = -1 } }
        if ($null -eq $p) { return @{ how = 'start'; rc = -1 } }
        try { $p.StandardInput.Close() } catch {}
        $o = $p.StandardOutput.ReadToEndAsync()
        $e = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit([math]::Max(1, $TimeoutSec) * 1000)) {
            try { $p.Kill() } catch {}
            return @{ how = 'timeout'; rc = -1 }
        }
        $p.WaitForExit()
        try { [void]$o.Wait(2000); [void]$e.Wait(2000) } catch {}
        return @{ how = 'exit'; rc = [int]$p.ExitCode }
    } catch {
        return @{ how = 'start'; rc = -1 }
    } finally {
        if ($p) { try { $p.Dispose() } catch {} }
    }
}

function Test-Af32Consent([string]$Root, [int]$TimeoutSec = 60) {
    # 수집기의 시작 확인(spec §6.2) - 화면·run.py 와 같은 판정이다. 이 설치 폴더의 자료가 지금 Windows 사용자의 것이고 '모두 지우기'가
    #   진행 중이 아닐 때만 $true. 이 함수는 판정을 스스로 하지 않는다 - 파이썬의 종료 코드만 읽는다:
    #   <설치 폴더>\python\python.exe(없으면 PATH 의 python·py -3 - Get-Af32Python)로
    #      python -X utf8 -B <설치 폴더>\core\consent.py --status --json --root <설치 폴더> 를 돌려 종료 코드 0 일 때만 $true.
    #      3(자료를 지우는 중)·4(다른 Windows 사용자의 자료·주인을 모르는 자료)는 $false.
    #   파이썬이 없거나 띄우지 못하거나 시간 초과·오류면 $false(닫힌 쪽 - 확인하지 못한 자료는 읽지 않는다).
    #   경로는 따옴표로 넘긴다(공백·한글이 든 설치 폴더). 까닭은 $script:Af32ConsentWhy:
    #   ok · wiping(3 - 자료를 지우는 중) · other(4 - 다른 Windows 사용자의 자료·주인을 모르는 자료) ·
    #   nopython(파이썬 없음) · error(띄우지 못함·consent.py 오류·시간 초과).
    $script:Af32ConsentWhy = 'error'
    $rt = ''
    try { $rt = [System.IO.Path]::GetFullPath($Root) } catch { return $false }
    $cpy = Join-Path $rt 'core\consent.py'
    $pys = @(Get-Af32Python $rt)
    if (-not $pys.Count) { $script:Af32ConsentWhy = 'nopython'; return $false }
    $embedded = Test-Path -LiteralPath (Join-Path $rt 'python\python.exe') -PathType Leaf
    $ran = $false
    foreach ($py in $pys) {
        $a = @($py.pre) + @('-X', 'utf8', '-B', $cpy, '--status', '--json', '--root', $rt)
        $x = Invoke-Af32Py -Exe $py.exe -Arguments $a -Dir $rt -TimeoutSec $TimeoutSec
        if ($x.how -eq 'exit' -and $x.rc -eq 0) { $script:Af32ConsentWhy = 'ok'; return $true }
        if ($x.how -eq 'exit' -and $x.rc -eq 3) { $script:Af32ConsentWhy = 'wiping'; return $false }
        if ($x.how -eq 'exit' -and $x.rc -eq 4) { $script:Af32ConsentWhy = 'other'; return $false }
        if ($x.how -eq 'timeout') { return $false }          # 다른 파이썬으로 다시 기다리지 않는다
        # 띄우지 못함·consent.py 오류(옛 파이썬 등) - PATH 의 다음 파이썬(내장 파이썬이면 후보가 하나뿐 - 그대로 $false).
        # 종료 코드 9009 는 파이썬이 아니다(Windows 의 'python' 앱 실행 별칭 - 설치돼 있지 않다는 안내만 찍고 끝난다)
        if ($x.how -eq 'exit' -and $x.rc -ne 9009) { $ran = $true }
    }
    if (-not $embedded -and -not $ran) { $script:Af32ConsentWhy = 'nopython' }   # PATH 의 후보 가운데 실제로 돈 파이썬이 없다
    return $false
}
