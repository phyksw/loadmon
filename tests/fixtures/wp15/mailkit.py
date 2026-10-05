# -*- coding: utf-8 -*-
r"""WP-15 시험 도구 — 메일·일정 수집기(PS)를 %TEMP% 복제 트리에서 주입점으로만 돌리고 출력 모양을 푼다.

    from tests.fixtures.wp15.mailkit import run_ps, ps_exe
    r = run_ps(clone, "Get-OutlookCom.ps1", ["-Only", "mail"], env={"LM_OUTLOOK_SELFTEST": "12"}, cfg={...})
    r.rc · r.meta · r.records · r.cursor · r.results · r.err_text

실제 Outlook·색인·PC 신원은 건드리지 않는다: COM 은 LM_OUTLOOK_SELFTEST, 색인은 LM_INDEX_FAKE(계약 §11.3)만 쓴다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
HERE = Path(__file__).resolve().parent
FORBIDDEN_RAW = frozenset({"username", "computername", "machine_guid"})       # P §10.3 · P-T31
MAIL_RAW = frozenset({
    "internet_message_id", "conversation_id", "conversation_topic", "box", "folder_role", "sender_addr",
    "sender_name", "to", "cc", "subject", "attach_names", "sensitivity", "categories", "importance", "has_attach",
    "in_reply_to", "headers_text", "body_text", "focused_other", "copilot_text",
    "ts_utc", "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})
CAL_RAW = frozenset({
    "global_appointment_id", "start_utc", "end_utc", "subject", "organizer", "attendees", "busy_status",
    "response_status", "meeting_status", "location", "is_recurring", "all_day", "online", "recurrence_incomplete",
    "sensitivity", "categories", "body_text", "copilot_text", "ts_local_offset", "ts_precision", "observed_at",
    "confidence", "flags",
})
MAIL_FLAGS = frozenset({"has_file", "list_unsub", "precedence", "esp", "body_unsub", "bulk", "cc", "sensitivity",
                        "cat_private", "ad", "private", "meeting_response", "cap_hit", "utc_suspect", "deferred",
                        "teams_notice"})
CAL_FLAGS = frozenset({"sensitivity", "cat_private", "private", "recurring", "all_day", "online_meeting",
                       "organizer_me", "recurrence_incomplete", "response", "meeting_status", "cap_hit", "utc_suspect"})
UTC_RX = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
OFF_RX = r"^[+-](?:0\d|1[0-4]):[0-5]\d$"


def ps_exe() -> str | None:
    return shutil.which("powershell") or shutil.which("powershell.exe")


@dataclass
class PsRun:
    rc: int
    out: list = field(default_factory=list)
    err: list = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def lines(self) -> list:
        return [json.loads(x) for x in self.out if x.strip()]

    @property
    def meta(self):
        ls = self.lines
        return ls[0]["_meta"] if ls and "_meta" in ls[0] else None

    @property
    def records(self) -> list:
        return [x for x in self.lines if not any(k.startswith("_") and k != "_kind" for k in x)]

    @property
    def cursor(self):
        ls = self.lines
        return ls[-1]["_cursor"] if ls and "_cursor" in ls[-1] else None

    @property
    def results(self) -> list:
        out = []
        for x in self.err:
            if x.startswith('{"_result"'):
                out.append(json.loads(x)["_result"])
        for x in self.out:                    # 제한 언어 모드 대체 경로(stderr 를 못 쓸 때 stdout 제어 줄)
            if x.startswith('{"_result"'):
                out.append(json.loads(x)["_result"])
        return out

    def result(self, src: str) -> dict:
        for r in self.results:
            if r.get("src") == src:
                return r
        raise AssertionError(f"결과 줄 없음: {src}")

    @property
    def err_text(self) -> str:
        return "\n".join(self.err)


def in_line(cursor=None, cfg=None) -> bytes:
    return (json.dumps({"_in": {"cursor": cursor, "cfg": dict(cfg or {})}}, ensure_ascii=False) + "\n").encode("utf-8")


def run_ps(clone, script: str, args, *, env: dict | None = None, cursor=None, cfg=None, stdin: bool = True,
           timeout: float = 300, command: str | None = None) -> PsRun:
    """복제 트리의 collect\\<script> 를 Windows PowerShell 5.1 로 실행(창 없음). stdin 에 _in 한 줄."""
    exe = ps_exe()
    if not exe:
        raise RuntimeError("powershell 없음")
    path = str(clone.path("collect", script))
    if command is None:
        argv = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path, *[str(a) for a in args]]
    else:
        argv = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command.replace("@SCRIPT@", path)]
    e = clone.env(env or {})
    kw = {"input": in_line(cursor, cfg)} if stdin else {"stdin": subprocess.DEVNULL}
    clone.temp.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    cp = subprocess.run(argv, capture_output=True, env=e, cwd=str(clone.temp), timeout=timeout,
                        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, **kw)
    return PsRun(cp.returncode, cp.stdout.decode("utf-8", "replace").splitlines(),
                 cp.stderr.decode("utf-8", "replace").splitlines(), time.monotonic() - t0)


def selftest_mail_expect(n: int) -> dict:
    """Get-OutlookCom.ps1 시험 모델의 한 달 메일 구성(스크립트 New-SelfModel 과 같은 규칙) → 폴더 키별 건수와 낼 건수."""
    cyc = ("inbox", "inbox", "inbox", "rules", "sent", "sent", "project", "X")
    junk = ("deleted", "junk", "drafts", "outbox")
    by = {}
    emit = 0
    for i in range(n):
        key = cyc[i % 8]
        if key == "X":
            key = junk[(i // 8) % 4]
        by[key] = by.get(key, 0) + 1
        if key in junk:
            continue
        ndr = key != "sent" and i % 11 == 10
        if not ndr:
            emit += 1
    return {"by_folder": by, "emit": emit}


def tree_snapshot(root: Path, skip=("_sandbox",)) -> dict:
    """root 아래 파일 → (크기, mtime_ns). 쓰기 0 검사용."""
    out = {}
    for dp, dns, fns in os.walk(root):
        rel = os.path.relpath(dp, root)
        if rel.split(os.sep)[0] in skip:
            dns[:] = []
            continue
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            p = os.path.join(dp, fn)
            st = os.stat(p)
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns)
    return out
