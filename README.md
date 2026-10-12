# sampler-stop — LoadMonitor 샘플러 확인·끄기

LM20~LM25를 쓴 PC에서 로그온할 때마다 PowerShell 창이 뜨거나, 샘플러가 백그라운드에서 계속 돌 때 쓰는 단독 도구입니다.
샘플러가 돌고 있는지 확인하고 끕니다. LM28에는 샘플러가 없습니다.

## 쓰는 법

1. 이 브랜치를 zip으로 받아 압축을 모두 풉니다: <https://github.com/phyksw/loadmon/archive/refs/heads/sampler-stop.zip>
2. `LoadMonitor-샘플러끄기.bat`을 더블클릭합니다.
3. 상태가 나옵니다.
   - 돌고 있는 샘플러 프로세스: PID, 시작 시각, 마지막 기록 시각
   - 로그온 자동 시작 작업: 켜짐 또는 사용 안 함
4. `Y`를 누르면 끕니다. 다른 키를 누르면 아무것도 바꾸지 않습니다.

확인만 하려면 명령 창에서 `LoadMonitor-샘플러끄기.bat -Status`를 실행합니다.

## 끄면 바뀌는 것

- **프로세스:** 명령줄에 `Start-ActivitySampler.ps1`(창 샘플러)이나 `Start-TeamsSampler.ps1`(팀즈 샘플러)이 있는
  PowerShell 프로세스를 종료합니다. 팀즈 샘플러가 띄운 자식 PowerShell도 함께 끕니다.
  다른 PowerShell 창이나 프로그램은 건드리지 않습니다.
- **예약 작업:** 작업 스케줄러의 `LoadMonitor<판>-Sampler`·`LoadMonitor<판>-TeamsSampler` 작업을 '사용 안 함'으로 바꿉니다.
  작업은 지우지 않습니다. LM24는 작업이 없으면 다음 분석 때 다시 등록하기 때문입니다.
- 관리자 권한은 필요 없습니다. 모아 둔 기록(`data\activity` 등)은 지우지 않습니다.

## 알아 둘 것

- 끈 뒤에 남은 PowerShell 창은 이미 끝난 창입니다. 닫으면 됩니다.
- LM24를 다시 실행하면(분석 실행이나 대시보드) 샘플러가 다시 켜질 수 있습니다. 그때는 이 도구를 다시 실행하세요.
  다시 켜지지 않게 하려면 그 LM 폴더의 `config\config.json`에 `"autoRestartSampler": false`를 넣으세요.
- 샘플러를 다시 켜려면 작업 스케줄러에서 그 작업을 '사용'으로 바꾸거나, LM 폴더의 `LoadMonitor24-샘플러등록.bat`을
  실행하세요.
