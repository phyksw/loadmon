# sampler-stop — LoadMonitor 샘플러 끄기

LM20~LM25를 쓴 PC에서 로그온할 때마다 PowerShell 창이 뜨거나, 샘플러가 백그라운드에서 계속 돌 때 쓰는 단독 도구입니다.
샘플러를 확인하고 바로 끕니다. LM28에는 샘플러가 없습니다.

## 쓰는 법

1. 이 브랜치를 zip으로 받아 압축을 모두 풉니다: <https://github.com/phyksw/loadmon/archive/refs/heads/sampler-stop.zip>
2. `LoadMonitor-샘플러끄기.bat`을 더블클릭합니다. 묻지 않고 바로 끄고, 끄기 전과 끈 뒤의 상태를 보여 줍니다.

끄지 않고 확인만 하려면 명령 창에서 `LoadMonitor-샘플러끄기.bat -Status`를 실행합니다.

## 끄면 바뀌는 것

- **프로세스:** 명령줄에 `Start-ActivitySampler.ps1`(창 샘플러)이나 `Start-TeamsSampler.ps1`(팀즈 샘플러)이 있는
  PowerShell 프로세스를 종료합니다. 팀즈 샘플러가 띄운 자식 PowerShell도 함께 끕니다.
  다른 PowerShell 창이나 프로그램은 건드리지 않습니다.
- **자동 시작:** 작업 스케줄러의 `LoadMonitor<판>-Sampler`·`LoadMonitor<판>-TeamsSampler` 작업을 지웁니다.
  '사용 안 함'으로 되어 있는 것도 지웁니다.
- 관리자 권한은 필요 없습니다. 모아 둔 기록(`data\activity` 등)은 지우지 않습니다.

## 알아 둘 것

- 끈 뒤에 남은 PowerShell 창은 이미 끝난 창입니다. 닫으면 됩니다.
- LM24로 다시 분석하면 LM24가 자동 시작 작업을 다시 등록하고 샘플러를 다시 띄울 수 있습니다.
  그때는 이 도구를 다시 실행하세요. LM24가 샘플러를 다시 켜지 않게 하려면 그 LM 폴더의 `config\config.json`에
  `"autoRestartSampler": false, "autoRegisterSampler": false`를 넣으세요.
- 샘플러를 다시 켜려면 LM 폴더의 `LoadMonitor24-샘플러등록.bat`을 실행하세요.
