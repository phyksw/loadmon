# Get-EmbeddedPython.ps1 — 내장 파이썬 설치기 (Python 미설치 PC 대응)
# python.org 공식 임베더블 배포판(약 11MB)을 받아 LoadMonitor22\python\ 에 풀어둔다.
# 이후 모든 bat 이 이 내장 파이썬을 최우선으로 사용한다 — PC에 Python을 설치할 필요가 없다.
# 표준 라이브러리 전체가 포함되며 LoadMonitor 는 표준 라이브러리만 쓰므로 추가 패키지가 필요 없다.
# (선택 도구 check.py 의 엑셀 검증만 openpyxl 이 필요 — 내장판에서는 지원하지 않음)
#
# 사용:  powershell -ExecutionPolicy Bypass -File tools\Get-EmbeddedPython.ps1
# 회사망에서 python.org 가 막혀 있으면: 집/개인망 PC에서 이 스크립트를 실행한 뒤
# LoadMonitor22 폴더를 통째로(python\ 포함) 복사하면 된다.
param([string]$Version = '3.11.9')

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dst  = Join-Path $root 'python'

if (Test-Path (Join-Path $dst 'python.exe')) {
    Write-Host "[embed-py] 이미 설치되어 있습니다: $dst"
    & (Join-Path $dst 'python.exe') --version
    exit 0
}

$url = "https://www.python.org/ftp/python/$Version/python-$Version-embed-amd64.zip"
$zip = Join-Path $env:TEMP "python-$Version-embed-amd64.zip"
Write-Host "[embed-py] 다운로드: $url (약 11MB)"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
} catch {
    Write-Host "[embed-py] 다운로드 실패: $($_.Exception.Message)"
    Write-Host "           회사망이 python.org 를 막았을 수 있습니다 - 개인망에서 실행 후 폴더째 복사하세요."
    exit 1
}

Write-Host "[embed-py] 압축 해제 → $dst"
Expand-Archive -Path $zip -DestinationPath $dst -Force
Remove-Item $zip -Force -ErrorAction SilentlyContinue

# 검증: 버전 출력 + 자가점검 실행
$py = Join-Path $dst 'python.exe'
& $py --version
if ($LASTEXITCODE -ne 0) { Write-Host '[embed-py] 실행 검증 실패'; exit 1 }
& $py (Join-Path $root '자가점검.py')
Write-Host ''
Write-Host '[embed-py] 완료 - 이제 LoadMonitor22-UI.bat 더블클릭으로 바로 실행됩니다.'
Write-Host '           (bat 이 내장 파이썬을 자동으로 우선 사용합니다)'
