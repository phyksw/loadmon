# -*- coding: utf-8 -*-
r"""가짜 수집기(합성 — 시험 전용). 실제 수집기(PS·PY)와 같은 입출력만 흉내 낸다(계약 §7.3 · v1.2 C1).

    "<PY>" -X utf8 -B fake_collector.py --spec <json 파일> [--src <경로 ID>]

spec(JSON): ``{"src", "rc", "records": [원시 레코드], "cursor": {...}|null, "status": {...}|null, "meta": {...}|null,
"sleep_s": 초(레코드 사이), "hang_s": 초(끝에 멈춤 — 감시 시험), "echo_in": 파일(받은 _in 줄을 그대로 저장),
"events": [이벤트 dict](stdout 에 §8.6 이벤트 줄), "stdout_status": bool(CLM 흉내 — 상태 줄을 stdout 제어 줄로),
"orphan_s": 초 + "orphan_pid_file": 파일(끝나기 전에 stdout·stderr 를 물려받은 손주를 띄워 남긴다 — 연결자가 감시 뒤 스트림
닫기에서 막히지 않는지(L13) 보는 시험 전용, 시험이 pid 파일로 끝낸다)}``.
stdin 첫 줄(``_in``)을 읽고, stdout 에 ``_meta``·레코드·``_cursor`` 를, stderr 마지막 줄에 ``{"_status": …}`` 를 낸다.
"""
import argparse
import json
import subprocess
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--src", default="")
    a, _rest = ap.parse_known_args()
    with open(a.spec, "rb") as fh:
        spec = json.loads(fh.read().decode("utf-8"))
    line = b""
    if not sys.stdin.isatty():
        try:
            line = sys.stdin.buffer.readline()
        except (OSError, ValueError):
            line = b""
    if spec.get("echo_in"):
        with open(spec["echo_in"], "wb") as fh:          # 시험 전용(%TEMP% 샌드박스) — 받은 _in 을 단언하려고
            fh.write(line)
    out = sys.stdout.buffer
    if spec.get("meta") is not None:
        out.write(json.dumps({"_meta": spec["meta"]}, ensure_ascii=False).encode("utf-8") + b"\n")
    for ev in spec.get("events") or ():
        out.write(json.dumps(ev, ensure_ascii=False).encode("utf-8") + b"\n")
    for rec in spec.get("records") or ():
        out.write(json.dumps(rec, ensure_ascii=False).encode("utf-8") + b"\n")
        out.flush()
        if spec.get("sleep_s"):
            time.sleep(float(spec["sleep_s"]))
    if spec.get("cursor") is not None:
        out.write(json.dumps({"_cursor": spec["cursor"]}, ensure_ascii=False).encode("utf-8") + b"\n")
    st = spec.get("status")
    if st is not None:
        st = dict(st)
        st.setdefault("src", a.src or spec.get("src"))
        blob = json.dumps({"_status": st}, ensure_ascii=False).encode("utf-8") + b"\n"
        if spec.get("stdout_status"):
            out.write(blob)
        else:
            sys.stderr.buffer.write(b"[fake] human line\n" + blob)
            sys.stderr.buffer.flush()
    out.flush()
    if spec.get("orphan_s"):
        # 표준 핸들(연결자 파이프)을 물려받은 손주 — 이 수집기가 끝나도 파이프 EOF 가 오지 않는다(L13 재현)
        g = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({float(spec['orphan_s'])})"],
                             close_fds=False, creationflags=0x08000000)
        with open(spec["orphan_pid_file"], "w", encoding="utf-8") as fh:     # 시험 전용(%TEMP% 샌드박스)
            fh.write(str(g.pid))
    if spec.get("hang_s"):
        time.sleep(float(spec["hang_s"]))
    return int(spec.get("rc", 0))


if __name__ == "__main__":
    sys.exit(main())
