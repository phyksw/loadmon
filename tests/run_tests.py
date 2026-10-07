# -*- coding: utf-8 -*-
r"""tests\run_tests.py — LM28 시험 실행기(한 프로세스).

  python\python.exe -X utf8 -B tests\run_tests.py                 # tests\test_*.py 전부
  python\python.exe -X utf8 -B tests\run_tests.py p0 p3           # test_p0*.py · test_p3*.py 만
  python\python.exe -X utf8 -B tests\run_tests.py --ps p0         # PowerShell 시험도(아래)
  python\python.exe -X utf8 -B tests\run_tests.py -k names        # 시험 이름 부분일치

규칙(개발 PC 는 끝난 프로세스가 커널에 남는다 — 프로세스를 아낀다):
  · 파이썬 시험은 이 프로세스 안에서 unittest 로 돈다(시험마다 파이썬을 새로 띄우지 않는다).
  · --ps 일 때만 powershell 을 **1회** 띄워 tests\ps\Run-PsTests.ps1 이 tests\ps\Test-*.ps1 을 모두 돌리게 한다.
    결과는 LM_PS_RESULTS(임시 폴더의 JSON)로 받고, 각 test_pN 은 _boot.ps_result(이름) 으로 단언만 한다.
  · 임시 폴더는 tempfile.TemporaryDirectory — 끝나면 지워진다.
종료 코드: 0 전부 통과 · 1 실패/오류 · 2 PowerShell 시험 실행 자체가 실패.
"""
import os
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)
import _boot  # noqa: E402,F401  — 경로 등록

NO_WIN = 0x08000000
PS_TIMEOUT = 600


def run_ps(tmpdir, only=None):
    """Run-PsTests.ps1 을 1회 실행 → 결과 파일 경로(실패면 None). only = Test-<이름> 의 이름 목록(없으면 전부)."""
    out = os.path.join(tmpdir, "ps_results.json")
    env = dict(os.environ, LM_PS_RESULTS=out)
    if only:
        env["LM_PS_ONLY"] = ",".join(only)
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", os.path.join(TESTS, "ps", "Run-PsTests.ps1")]
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, timeout=PS_TIMEOUT, cwd=_boot.ROOT,
                           creationflags=NO_WIN if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        print(f"[run_tests] PowerShell 시험이 {PS_TIMEOUT}초 안에 끝나지 않았습니다")
        return None
    except OSError as e:
        print(f"[run_tests] powershell 을 띄우지 못했습니다: {e}")
        return None
    text = (r.stdout or b"").decode("utf-8", "replace").strip()
    for ln in text.splitlines()[-20:]:
        print(ln if ln.startswith("[ps]") else "[ps] " + ln)
    if r.returncode != 0 or not os.path.isfile(out):
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        print(f"[run_tests] Run-PsTests.ps1 rc={r.returncode} " + err[-600:])
        return out if os.path.isfile(out) else None
    return out


def build_suite(selected, keyword):
    loader = unittest.TestLoader()
    if keyword:
        loader.testNamePatterns = [f"*{keyword}*"]
    pats = [f"test_{s}*.py" for s in selected] if selected else ["test_*.py"]
    suite = unittest.TestSuite()
    for pat in pats:
        suite.addTests(loader.discover(TESTS, pattern=pat, top_level_dir=TESTS))
    return suite


def main(argv):
    use_ps, keyword, selected, ps_only = False, "", [], []
    it = iter(argv)
    for a in it:
        if a == "--ps":
            use_ps = True
        elif a == "-k":
            keyword = next(it, "")
        elif a.startswith("--ps-only="):
            use_ps = True
            ps_only = [x for x in a.split("=", 1)[1].split(",") if x]
        else:
            selected.append(a)
    rc_ps = 0
    with tempfile.TemporaryDirectory(prefix="lm28_tests_") as tmp:
        if use_ps:
            p = run_ps(tmp, ps_only)
            if p:
                os.environ["LM_PS_RESULTS"] = p
            else:
                rc_ps = 2
        else:
            os.environ.pop("LM_PS_RESULTS", None)       # 바깥에 남은 옛 결과 파일을 읽지 않게
        res = unittest.TextTestRunner(verbosity=1, stream=sys.stdout).run(build_suite(selected, keyword))
        os.environ.pop("LM_PS_RESULTS", None)
    if not res.wasSuccessful():
        return 1
    return rc_ps


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
