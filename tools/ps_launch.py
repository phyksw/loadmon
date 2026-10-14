# -*- coding: utf-8 -*-
r"""tools\ps_launch.py — bat 이 PowerShell 스크립트를 띄울 때 '켜지는 순간 실패(0xc0000142)' 를 견디는 실행기 (LM28 2026-10-15).

왜: 개발 PC(2026-10-15)에서 LoadMonitor28-강제종료.bat 이 바로 띄운 powershell 이 켜지는 순간 Windows 초기화에 실패해
    '응용 프로그램을 제대로 시작하지 못했습니다(0xc0000142)' 창을 띄우고 [확인]까지 멈췄다 — Stop-LM28.ps1 은 한 줄도 돌지
    않았다. 수집기는 core\proc 가 이미 막는다(quiet_errors + run_step 다시 띄우기). bat 이 powershell 을 바로 부르면 그 보호가
    없으므로 bat 은 이 실행기를 거쳐 띄운다.
  · proc.quiet_errors() — 오류 창을 막는다(자식이 오류 모드를 물려받는다 → 못 켜진 powershell 은 창 없이 곧바로 끝난다).
  · 콘솔을 물려받아 띄운다 — 스크립트의 출력이 그대로 bat 창에 보인다(모으지 않는다).
  · proc.START_FAIL_SEC 안에 proc.START_FAIL_RC 로 끝나면 proc.START_WAIT(3초·8초) 쉬고 proc.START_RETRY(2)번 다시 띄운다.
    띄우기 자체가 OSError 면(PowerShell 없음·정책 차단) 다시 띄워도 같으므로 바로 '켜지지 못함' 으로 돌려준다.

  launch(script, args) → (rc, start_failed)   start_failed = 끝내 켜지지 못했다(호출측이 대안을 고른다 — tools\stop_lm28.py)
  run_ps(script, args) → rc
  python tools\ps_launch.py <스크립트.ps1> [인자…]     (LoadMonitor28-수집진단.bat)
runner·sleep·clock·say 는 시험이 바꿔 끼운다(tests\test_p24_stop_startfail.py — 실제 powershell 은 띄우지 않는다).
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "core") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "core"))
import proc  # noqa: E402  — core\proc.py(START_FAIL_RC·START_FAIL_SEC·START_RETRY·START_WAIT·quiet_errors 단일원)

PS_BASE = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
OSERR_RC = -2                  # 띄우지 못함(proc.run_step 의 '실행 실패' 와 같은 값)
GIVEUP_LINE = ("  [!] PowerShell 을 끝내 띄우지 못했습니다(Windows 오류 0xc0000142) — 보안 프로그램·Windows 자원 문제가 "
               "의심됩니다. PC 를 다시 시작한 뒤 다시 실행하세요")


def ps_cmd(script, args=()):
    return PS_BASE + [str(script)] + [str(a) for a in args]


def retry_line(wait, n):
    return (f"  PowerShell 이 켜지지 못했습니다(Windows 오류 0xc0000142) — {wait:.0f}초 뒤 다시 띄웁니다"
            f"({n}/{proc.START_RETRY})")


def _call(cmd, cwd=None):
    """콘솔을 물려받아 띄우고 끝날 때까지 기다린다 → 종료 코드. 띄우지 못하면 OSError."""
    return subprocess.call(cmd, cwd=cwd)


def _say(s):
    print(s, flush=True)


def launch(script, args=(), *, cwd=None, runner=None, sleep=None, clock=None, say=None):
    """PowerShell 로 script 를 돌린다 → (rc, start_failed). 위 머리말 참고.
    start_failed=True 면 rc 는 마지막 시도의 종료 코드(START_FAIL_RC 중 하나) 또는 OSERR_RC 다."""
    proc.quiet_errors()
    runner = runner or _call
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    say = say or _say
    cmd = ps_cmd(script, args)
    tries = 0
    while True:
        t0 = clock()
        try:
            rc = runner(cmd, cwd)
        except OSError as e:
            say(f"  [!] PowerShell 을 띄우지 못했습니다({e})"[:300])
            return OSERR_RC, True
        if not (rc in proc.START_FAIL_RC and clock() - t0 < proc.START_FAIL_SEC):
            return rc, False             # 켜져서 일하고 끝났다(성공이든 스크립트의 실패든 그대로 돌려준다)
        if tries >= proc.START_RETRY:
            return rc, True
        wait = proc.START_WAIT[min(tries, len(proc.START_WAIT) - 1)]
        tries += 1
        say(retry_line(wait, tries))
        sleep(wait)


def run_ps(script, args=(), **kw):
    """launch 의 종료 코드만 → rc."""
    return launch(script, args, **kw)[0]


def exit_code(rc):
    """sys.exit 에 넘길 32비트 부호 있는 값 — 0xC0000142 같은 큰 값이 넘치지 않게(윈도에서는 같은 종료 코드가 된다)."""
    rc = int(rc) & 0xFFFFFFFF
    return rc - (1 << 32) if rc >= (1 << 31) else rc


def main(argv, **kw):
    if not argv or argv[0] in ("-h", "--help", "/?"):
        print(r"사용법: python tools\ps_launch.py <스크립트.ps1> [인자…]")
        return 2
    say = kw.get("say") or _say
    rc, failed = launch(argv[0], argv[1:], **kw)
    if failed:
        say(GIVEUP_LINE)
    return exit_code(rc)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(1)
