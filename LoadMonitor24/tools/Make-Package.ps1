# 배포본 만들기 — FILES.txt 에 적힌 파일만 담는다.
#
# 왜 이 스크립트가 필요한가: 폴더를 통째로 압축하면 data\ 와 report\ 가 딸려 간다.
# 실측 사고 — 배포 zip 두 개에 report\ 17개(시험용 과제명 'coding'/'모듈 개발')와
# Edge 프로필 자격증명 30개(Cookies·Login Data)가 들어갔다. 받은 사람 화면에는
# 남의 분석 결과가 자기 결과처럼 떴고, 로그인 정보까지 함께 나갔다.
#
#   powershell -ExecutionPolicy Bypass -File tools\Make-Package.ps1
#   powershell -ExecutionPolicy Bypass -File tools\Make-Package.ps1 -OutDir D:\작업\배포본
#   (파일을 고쳤으면 먼저  python tools\update_files.py  — FILES.txt 의 크기·crc 가 다르면 여기서 멈춘다)

param(
    [string]$OutDir = "$env:USERPROFILE\Desktop",
    [switch]$Full,         # 내장 파이썬(python\) 동봉 - 파이썬 없는 PC에서도 압축 해제 후 바로 실행
    [switch]$SkipLint      # (비상용) tools\lint.ps1 관문을 건너뛴다 - 결함이 있는 채로 배포되므로 평소엔 쓰지 말 것
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# 패키징 훅: lint 7관문(ruff·PS 파서·화면 JS 문법·bat/ps1 인코딩·개발 PC 실경로)을 통과해야 담는다.
# 실사고 — JS 문법 오류 하나로 버튼 11개가 전부 죽은 배포본이 나간 적이 있다. 배포 직전이 마지막 관문이다.
if (-not $SkipLint) {
    $lint = Join-Path $PSScriptRoot 'lint.ps1'
    if (Test-Path $lint) {
        Write-Host '[배포본] lint 관문 실행 (tools\lint.ps1)...'
        & powershell -NoProfile -ExecutionPolicy Bypass -File $lint
        if ($LASTEXITCODE -ne 0) { throw 'lint 관문 실패 - 위 항목을 고친 뒤 다시 실행하세요 (-SkipLint 는 비상용)' }
    }
}
$filesTxt = Join-Path $root 'FILES.txt'
if (-not (Test-Path $filesTxt)) { throw "FILES.txt 가 없습니다: $filesTxt" }

# FILES.txt 본문에서 경로·크기·crc32 를 뽑는다 (머리말·괄호 설명·'총 N개' 줄 제외)
$need = @()
$expect = @{}
foreach ($ln in Get-Content $filesTxt -Encoding UTF8) {
    if ($ln -match '^\s*$') { continue }
    if ($ln -match '^(LoadMonitor24 필수|총 |\()') { continue }
    if ($ln -match '^\s') { continue }              # 괄호 설명의 이어지는 줄
    $p = ($ln -split '\s{2,}')[0].Trim()
    if ($p) { $need += $p }
    if ($p -and $ln -match '\s{2,}([\d,]+) B\s+([0-9a-fA-F]{8})\s*$') {
        $expect[$p] = @{ size = [int64]($matches[1] -replace ',', ''); crc = $matches[2].ToLower() }
    }
}
if ($need.Count -lt 10) { throw "FILES.txt 파싱 실패 (경로 $($need.Count)개)" }

# FILES.txt 가 지금 트리와 맞는지 — 크기·crc32 를 실제 파일과 대조한다.
# 실측: README·ui\app.py 를 고친 뒤 FILES.txt 를 다시 만들지 않아 낡은 목록이 zip 에 실렸다.
# 다르면 담지 않고 멈춘다 — python tools\update_files.py 로 다시 만든 뒤 재시도.
$crcSrc = @'
public static class LmCrc32 {
    static readonly uint[] T = MakeTable();
    static uint[] MakeTable() {
        var t = new uint[256];
        for (uint n = 0; n < 256; n++) {
            uint c = n;
            for (int k = 0; k < 8; k++) { c = ((c & 1) != 0) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1); }
            t[n] = c;
        }
        return t;
    }
    public static string Hex(byte[] b) {
        uint c = 0xFFFFFFFFu;
        foreach (byte x in b) { c = T[(c ^ x) & 0xFF] ^ (c >> 8); }
        return (c ^ 0xFFFFFFFFu).ToString("x8");
    }
}
'@
if (-not ('LmCrc32' -as [type])) { try { Add-Type -TypeDefinition $crcSrc -ErrorAction Stop } catch { } }
$script:crcTab = $null
function Get-Crc32([byte[]]$bytes) {
    if ('LmCrc32' -as [type]) { return [LmCrc32]::Hex($bytes) }
    # Add-Type 이 막힌 PC — 순수 PowerShell (느리지만 같은 값).
    # PS5.1 은 0xFFFFFFFF·0xEDB88320 같은 16진 리터럴을 음수 Int32 로 읽어 [uint32] 변환이 죽는다 — 10진수로 쓴다.
    if (-not $script:crcTab) {
        $script:crcTab = New-Object uint32[] 256
        for ($n = 0; $n -lt 256; $n++) {
            [uint32]$c = $n
            for ($k = 0; $k -lt 8; $k++) {
                if ($c -band 1) { $c = [uint32]([uint32]3988292384 -bxor ($c -shr 1)) } else { $c = [uint32]($c -shr 1) }
            }
            $script:crcTab[$n] = $c
        }
    }
    [uint32]$c = [uint32]::MaxValue
    foreach ($x in $bytes) { $c = [uint32]($script:crcTab[($c -bxor $x) -band 0xFF] -bxor ($c -shr 8)) }
    return ('{0:x8}' -f [uint32]($c -bxor [uint32]::MaxValue))
}
$stale = @()
foreach ($rel in $need) {
    if (-not $expect.ContainsKey($rel)) { continue }      # 'FILES.txt (이 파일)' 줄
    $src = Join-Path $root ($rel -replace '/', '\')
    if (-not (Test-Path $src)) { continue }               # 누락은 아래 복사 단계가 따로 알린다
    $b = [System.IO.File]::ReadAllBytes($src)
    if ($b.Length -ne $expect[$rel].size -or (Get-Crc32 $b) -ne $expect[$rel].crc) { $stale += $rel }
}
if ($stale.Count) {
    throw "FILES.txt 가 현재 파일과 다릅니다 ($($stale.Count)개: $($stale -join ', ')) — python tools\update_files.py 를 먼저 실행해 FILES.txt 를 다시 만든 뒤 다시 시도하세요"
}

$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("LM22pkg_" + [Guid]::NewGuid().ToString('N').Substring(0,8))
$dest = Join-Path $stage 'LoadMonitor24'
New-Item -ItemType Directory -Force $dest | Out-Null

$missing = @()
foreach ($rel in $need) {
    $src = Join-Path $root ($rel -replace '/', '\')
    if (-not (Test-Path $src)) { $missing += $rel; continue }
    $dst = Join-Path $dest ($rel -replace '/', '\')
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    Copy-Item $src $dst
}
if ($missing.Count) {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    throw "필수 파일 누락 $($missing.Count)개: $($missing -join ', ')"
}

# 설정은 '만든 사람의 것'이 아니라 배포 템플릿을 담는다 —
# 그러지 않으면 owner·개인 폴더 키워드·공유폴더 경로가 팀 전체로 나가고,
# 받은 사람이 그대로 쓰면 팀 서버의 그 사람 기록을 덮어쓴다(검증 확정).
$tpl = Join-Path $root 'config\config.default.json'
if (-not (Test-Path $tpl)) { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue; throw 'config\config.default.json 이 없습니다 — 배포 템플릿이 있어야 합니다' }
Copy-Item $tpl (Join-Path $dest 'config\config.json') -Force

# 빈 폴더만 만들어 둔다 — 받는 사람이 처음 실행할 때 자기 데이터가 여기 쌓인다
foreach ($d in 'data', 'report') { New-Item -ItemType Directory -Force (Join-Path $dest $d) | Out-Null }

# 풀패키지: 내장 파이썬 동봉 - '어떤 PC 든 압축 풀고 더블클릭'이 목표.
# 없으면 Get-EmbeddedPython.ps1 로 먼저 받는다(인터넷 필요 - 이 PC 에서 1회).
if ($Full) {
    $pySrc = Join-Path $root 'python'
    if (-not (Test-Path (Join-Path $pySrc 'python.exe'))) {
        Write-Host '[배포본] 내장 파이썬이 없어 먼저 받습니다 (python.org, 약 11MB)...'
        powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Get-EmbeddedPython.ps1')
        if (-not (Test-Path (Join-Path $pySrc 'python.exe'))) {
            Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
            throw '내장 파이썬 준비 실패 - 인터넷/프록시 확인 후 재시도'
        }
    }
    Copy-Item $pySrc (Join-Path $dest 'python') -Recurse
    Write-Host '[배포본] 내장 파이썬 동봉 (python\ - 파이썬 미설치 PC 대응)'
}

# 안전 확인 — 스테이징에 개인 데이터가 한 톨도 없어야 한다
$leak = @(Get-ChildItem (Join-Path $dest 'data'), (Join-Path $dest 'report') -Recurse -File -ErrorAction SilentlyContinue)
if ($leak.Count) {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    throw "배포 위생 실패: data/report 에 파일 $($leak.Count)개가 들어갔습니다"
}
$stagedCfg = Join-Path $dest 'config\config.json'
$h1 = (Get-FileHash $stagedCfg -Algorithm SHA256).Hash
$h2 = (Get-FileHash $tpl -Algorithm SHA256).Hash
if ($h1 -ne $h2) {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    throw "배포 위생 실패: 담긴 config.json 이 배포 템플릿과 다릅니다"
}

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force $OutDir | Out-Null }
$kind = if ($Full) { 'LoadMonitor24_풀패키지_' } else { 'LoadMonitor24_' }
# 이름은 초 단위(HHmmss)까지, 이미 있으면 _2 _3 … 으로 비켜 간다 — 남의 zip 은 절대 지우지 않는다.
# 압축은 임시 이름(.partial.zip)으로 한 뒤 같은 폴더 안에서 제 이름으로 옮긴다(같은 볼륨 → 원자적 rename).
# 실측: 같은 분에 두 번 돌리면 뒤 실행이 ArchiveFileExists 로 죽거나, 앞 실행이 막 완성한 zip 을 지웠다.
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$zip = Join-Path $OutDir ($kind + $stamp + '.zip')
$n = 1
while (Test-Path -LiteralPath $zip) { $n++; $zip = Join-Path $OutDir ($kind + $stamp + '_' + $n + '.zip') }
$part = Join-Path $OutDir ($kind + $stamp + '.' + [Guid]::NewGuid().ToString('N').Substring(0, 8) + '.partial.zip')
try {
    Compress-Archive -Path $dest -DestinationPath $part -CompressionLevel Optimal
    Move-Item -LiteralPath $part -Destination $zip -ErrorAction Stop      # -Force 없음: 같은 초의 다른 실행과 겹치면 덮어쓰지 않고 멈춘다
} catch {
    Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    throw
}
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "[배포본] $zip  ($mb MB · 파일 $($need.Count)개)"
Write-Host "         data\ report\ 는 빈 폴더로만 들어갔습니다 (개인정보·남의 분석결과 제외)."
if ($Full) { Write-Host '         내장 파이썬 동봉 - 받는 PC 에 아무것도 설치할 필요 없이 bat 더블클릭으로 실행됩니다.' }
Write-Host ""
Write-Host "받는 사람 안내:"
Write-Host "  1) 압축을 풀고 LoadMonitor24-UI.bat 실행"
Write-Host "  2) 파이썬이 없으면 tools\Get-EmbeddedPython.ps1 을 먼저 실행"
Write-Host "  3) Copilot 판정을 쓰려면 화면의 [AI 연결 진단] 으로 로그인 상태 확인"
