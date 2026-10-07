# LmName.ps1 - LM28 이름 단일원(PowerShell 쪽). core\lmname.py 와 같은 규칙이다 - 하나를 바꾸면 둘 다 바꾼다.
# 같은 PC 의 LM24(LoadMonitor<숫자>-*Sampler 작업 · 같은 이름의 뮤텍스)와 예약 작업·뮤텍스가 겹치지 않게
# 이름에 'LM28' 과 설치 폴더 해시 6자리(h6)를 넣는다. LM24 의 정리 정규식 ^LoadMonitor\d+-(Teams)?Sampler$ 밖이다.
# h6 = sha1(UTF-8(소문자(끝 구분자 제거(GetLongPathName(GetFullPath(경로))))))[:6]
# 사용(dot-source):  . (Join-Path $PSScriptRoot 'LmName.ps1');  $nm = Get-LmNames $root;  $nm.TaskSampler
# 시험: tests\ps\Test-LmName.ps1 (같은 고정 경로의 h6 를 Python 과 비교)

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
    # 키는 core\lmname.py names() 와 같다
    $h = Get-LmH6 $Root
    return @{
        H6            = $h
        Short         = 'LM28'
        Product       = 'LoadMonitor28'
        TaskSampler   = "LM28-Sampler-$h"
        TaskTeams     = "LM28-TeamsSampler-$h"
        MutexActivity = "Local\LM28-ActivitySampler-$h"
        MutexTeams    = "Local\LM28-TeamsSampler-$h"
        TaskRegex     = '^LM28-(Teams)?Sampler-[0-9a-f]{6}$'
        TmpPrefix     = 'lm28_'
    }
}
