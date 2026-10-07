# Test-LmName.ps1 - collect\LmName.ps1 이 core\lmname.py 와 같은 이름을 내는지(시험 p0 (9)).
# 고정 예시 경로(실재하지 않는 경로)의 h6 를 여러 표기로 계산해 돌려준다 - 단언은 tests\test_p0_names.py 가 한다.
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
. (Join-Path $root 'collect\LmName.ps1')
$p = 'C:\LM28test\Sample Folder'
$nm = Get-LmNames $p
$rn = Get-LmNames $root
return @{
    h6_plain    = (Get-LmH6 $p)
    h6_slash    = (Get-LmH6 ($p + '\'))
    h6_case     = (Get-LmH6 $p.ToLower())
    h6_fwd      = (Get-LmH6 'C:/LM28test/Sample Folder/')
    norm        = (Get-LmNormRoot $p)
    names_h6    = $nm.H6
    root_h6     = $rn.H6
}
