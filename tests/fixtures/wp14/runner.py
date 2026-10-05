# -*- coding: utf-8 -*-
r"""PC 수집기 실행 도우미(시험 전용, WP-14) — %TEMP% 복제 트리의 collect\*.ps1 을 Windows PowerShell 5.1 로 돌리고
stdout NDJSON(레코드 · 제어 줄)과 stderr 상태 줄 {"_status": …} 을 나눠 돌려준다.

    r = run_ps(clone, "Get-EventActivity.ps1", ["-EventsCsv", csv, "-Now", "2026-09-03 17:00"], cfg={...}, cursor=None)
    r.rc · r.records · r.cursor · r.status · r.controls

stdin: cfg·cursor·self_names 중 하나라도 주면 {"_in": …} 한 줄(WP-05 inject.in_line), 아니면 빈 입력(리디렉션만 — 기본값으로 돈다).
stdout 은 UTF-8 로 엄격히 디코드한다(수집기 출력 인코딩 결함을 바로 드러낸다).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from tests.fixtures.synth.inject import in_line

CREATE_NO_WINDOW = 0x08000000
FORBIDDEN_RAW = frozenset({"message", "user", "computer", "username", "computername", "machine_guid", "host", "server"})


def powershell() -> str:
    for c in (shutil.which("powershell.exe"), shutil.which("powershell"),
              os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                           "powershell.exe")):
        if c and os.path.isfile(c):
            return c
    raise RuntimeError("Windows PowerShell 을 찾지 못했습니다")


@dataclass
class PsResult:
    rc: int
    records: list = field(default_factory=list)
    controls: list = field(default_factory=list)
    cursor: dict | None = None
    status: dict | None = None
    stdout: bytes = b""
    stderr: bytes = b""

    def err(self) -> str:
        return self.stderr.decode("utf-8", "replace")


def parse_output(stdout: bytes, stderr: bytes, rc: int) -> PsResult:
    text = stdout.decode("utf-8")                       # 엄격 — UTF-8 이 아니면 시험이 실패해야 한다
    r = PsResult(rc=rc, stdout=stdout, stderr=stderr)
    lines = [ln for ln in text.split("\n") if ln.strip()]
    for ln in lines:
        obj = json.loads(ln)
        if any(k.startswith("_") for k in obj):
            r.controls.append(obj)
            if "_cursor" in obj:
                r.cursor = obj["_cursor"]
        else:
            r.records.append(obj)
    for ln in reversed(stderr.decode("utf-8", "replace").splitlines()):
        s = ln.strip()
        if s.startswith('{"_status"'):
            r.status = json.loads(s)["_status"]
            break
    return r


def run_ps(clone, script: str, args=(), *, cfg: dict | None = None, cursor=None, self_names=None, env: dict | None = None,
           timeout: float = 240, script_path: str | os.PathLike | None = None) -> PsResult:
    path = Path(script_path) if script_path else clone.path("collect", script)
    argv = [powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path),
            *(str(a) for a in args)]
    data = b""
    if cfg is not None or cursor is not None or self_names is not None:
        data = in_line(cursor=cursor, cfg=cfg or {}, self_names=self_names)
    clone.temp.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(argv, input=data, capture_output=True, env=clone.env(env or {}), cwd=str(clone.temp),
                        timeout=timeout, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)
    return parse_output(cp.stdout, cp.stderr, cp.returncode)


def snapshot(root: str | os.PathLike) -> dict:
    """폴더 아래 파일 → (크기, 수정 시각 ns). 수집기가 디스크에 아무것도 쓰지 않았는지 대조용."""
    out = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns)
    return out
