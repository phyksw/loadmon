# -*- coding: utf-8 -*-
r"""WP-16 합성 UIA 판독 자료(-RawFile)와 Get-TeamsWindow.ps1 실행 도우미.

-RawFile 은 계약 §11.3 의 teams.uia 주입점이다. 형식 두 가지(수집기 머리말 주석과 같은 정의):
  · 일반 텍스트 — 한 줄 = UIA 요소 이름 하나인 가시 창 하나(WP-05 inject.write_teams_rawfile 형, UTF-8 BOM + CRLF)
  · JSON 스냅숏 — {"procs": n, "windows": [창…]}. 창 = {title, class, visible, iconic, on_screen, cloaked, elevated,
    hang, error, read_ms, rect: [l, t, w, h], elements: [{name, type, rect}]}. 창 열거(팝아웃·최소화·가림·권한 상승·
    워치독·예산)와 요소 기하(채팅 목록 열·오른쪽 정렬 말풍선)까지 흉내 낸다.
파일은 %TEMP% 복제 안(guard_write)에만 쓴다. 실제 창·UIA·Teams 는 건드리지 않는다. 이름은 자리표시자(홍길동·김철수·
동료B…)·과제A 만 쓴다.

    from tests.fixtures.wp16 import uia
    snap = uia.snapshot(uia.window("채팅 | 과제A 설계 | Microsoft Teams", [uia.button("참가자 5명"), uia.sep("오늘"),
                                                                           uia.msg("김철수, 오전 8:30, 검토 부탁드립니다")]))
    res = uia.run(clone, uia.write_json(clone.temp / "s.json", snap), self_names=["홍길동"])
    res.rc, res.records, res.cursor, res.status
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..synth.inject import in_line
from ..tree import CREATE_NO_WINDOW, guard_write

SCRIPT_REL = ("collect", "Get-TeamsWindow.ps1")
TEST_NOW = "2026-10-01T09:00:00+09:00"          # 2026-10-01(목) 09:00 KST — 상대 날짜(오늘·어제·요일)의 기준
W, H = 1600, 900                                 # 기본 창 크기(물리 픽셀)
RAW_FIELDS = frozenset({                         # P §10.2 teams 원시 이름(계약 §3.5) — WP-05 raw_teams.FIELDS 와 같은 집합의 부분
    "message_id", "chat_id", "chat_type", "n_participants", "reply_to_id", "author_addr", "author_name", "is_me",
    "participants", "mentions_me", "file_names", "body_text", "chat_title", "ts_utc", "ts_local_offset",
    "ts_precision", "observed_at", "confidence", "flags",
})


# ── 요소 ────────────────────────────────────────────────────────────────────
def el(name: str, type: str = "Text", rect: Sequence[float] | None = None) -> dict:
    d: dict = {"name": name, "type": type}
    if rect is not None:
        d["rect"] = list(rect)
    return d


def msg(name: str, *, x: float = 460, w: float = 1080, y: float = 200, h: float = 40) -> dict:
    """메시지 창 영역의 넓은 목록 항목(남의 메시지 — 왼쪽 정렬)."""
    return el(name, "ListItem", (x, y, w, h))


def mine(name: str, *, w: float = 420, y: float = 300, h: float = 40, win_w: float = W, win_x: float = 0) -> dict:
    """내 말풍선 — 작성자 생략, 창 오른쪽 끝에 붙은 좁은 항목(구조 단서: 오른쪽 정렬)."""
    return el(name, "ListItem", (win_x + win_w - 30 - w, y, w, h))


def preview(name: str, *, y: float = 100, x: float = 70, w: float = 330) -> dict:
    """왼쪽 채팅 목록 열의 미리보기 항목(창 왼쪽 25% 안에서 시작해 45% 안에서 끝남)."""
    return el(name, "ListItem", (x, y, w, 60))


def sep(text: str) -> dict:
    """날짜 구분선(오늘·어제·요일·날짜만 있는 줄)."""
    return el(text, "Text", (900, 150, 160, 20))


def button(name: str) -> dict:
    return el(name, "Button", (1300, 60, 120, 30))


def tab(name: str) -> dict:
    return el(name, "TabItem", (500, 60, 80, 30))


# ── 창·스냅숏 ───────────────────────────────────────────────────────────────
def window(title: str, elements: Iterable[Mapping], *, visible: bool = True, iconic: bool = False,
           on_screen: bool = True, cloaked: bool = False, elevated: bool = False, hang: bool = False,
           error: str | None = None, read_ms: int = 0, rect: Sequence[float] | None = (0, 0, W, H),
           cls: str = "TeamsWebView") -> dict:
    d: dict = {"title": title, "class": cls, "visible": visible, "iconic": iconic, "on_screen": on_screen,
               "cloaked": cloaked, "elevated": elevated, "hang": hang, "elements": [dict(e) for e in elements]}
    if error is not None:
        d["error"] = error
    if read_ms:
        d["read_ms"] = int(read_ms)
    if rect is not None:
        d["rect"] = list(rect)
    return d


def snapshot(*windows: Mapping, procs: int = 1) -> dict:
    return {"procs": procs, "windows": [dict(w) for w in windows]}


def write_json(path: str | os.PathLike, snap: Mapping) -> Path:
    p = guard_write(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(json.dumps(snap, ensure_ascii=False, indent=1).encode("utf-8") + b"\n")
    return p


def write_lines(path: str | os.PathLike, lines: Iterable[str]) -> Path:
    """일반 텍스트 원문 재생 파일(UTF-8 BOM + CRLF — WP-05 write_teams_rawfile 과 같은 인코딩)."""
    p = guard_write(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xef\xbb\xbf" + ("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return p


# ── 실행 ────────────────────────────────────────────────────────────────────
def powershell_exe() -> str | None:
    return shutil.which("powershell") or shutil.which("powershell.exe")


@dataclass
class Result:
    rc: int
    stdout: bytes
    stderr: bytes
    lines: list[dict] = field(default_factory=list)      # stdout 의 JSON 줄 전부(순서대로)
    records: list[dict] = field(default_factory=list)    # 제어 줄(_ 로 시작하는 키)을 뺀 레코드
    cursor: dict | None = None                            # 마지막 줄 {"_cursor": …} 의 값
    status: dict | None = None                            # stderr 마지막 줄 {"_status": …} 의 값

    @property
    def reasons(self) -> list[str]:
        return list((self.status or {}).get("reasons", []))

    @property
    def counts(self) -> dict:
        return dict((self.status or {}).get("counts", {}))


def _is_control(obj: Mapping) -> bool:
    return len(obj) == 1 and next(iter(obj)).startswith("_")


def parse_output(rc: int, stdout: bytes, stderr: bytes) -> Result:
    res = Result(rc, stdout, stderr)
    text = stdout.decode("utf-8")                         # UTF-8 이 아니면 여기서 실패(계약 §9.2 · NDJSON)
    for ln in text.split("\n"):
        if not ln.strip():
            continue
        obj = json.loads(ln)
        res.lines.append(obj)
        if not _is_control(obj):
            res.records.append(obj)
    if res.lines and "_cursor" in res.lines[-1]:
        res.cursor = res.lines[-1]["_cursor"]
    err_lines = [x for x in stderr.decode("utf-8", "replace").splitlines() if x.strip()]
    if err_lines:
        try:
            last = json.loads(err_lines[-1])
        except ValueError:
            last = None
        if isinstance(last, dict) and "_status" in last:
            res.status = last["_status"]
    return res


def command(clone, raw: str | os.PathLike | None, *, now: str | None = TEST_NOW,
            args: Sequence[str] = ()) -> list[str]:
    ps = powershell_exe()
    if not ps:
        raise RuntimeError("powershell 없음")
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(clone.path(*SCRIPT_REL))]
    if raw is not None:
        cmd += ["-RawFile", str(raw)]
    if now:
        cmd += ["-TestNow", now]
    return cmd + [str(a) for a in args]


def run(clone, raw: str | os.PathLike | None, *, self_names: Iterable[str] | None = ("홍길동",),
        cfg: Mapping | None = None, cursor: Mapping | None = None, inp: bytes | None = None,
        now: str | None = TEST_NOW, args: Sequence[str] = (), env: Mapping[str, str] | None = None,
        cwd: str | os.PathLike | None = None, timeout: float = 180) -> Result:
    """복제의 Get-TeamsWindow.ps1 을 -RawFile 로 실행한다. inp 를 주지 않으면 연결자처럼 _in 한 줄을 stdin 에 쓴다."""
    if inp is None:
        inp = in_line(cursor=cursor, cfg=cfg or {}, self_names=self_names)
    clone.temp.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(command(clone, raw, now=now, args=args), input=inp, capture_output=True, timeout=timeout,
                       cwd=str(cwd or clone.temp), env=dict(env) if env is not None else clone.env(),
                       creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)
    return parse_output(p.returncode, p.stdout, p.stderr)


def by_body(res: Result, needle: str) -> list[dict]:
    """본문에 needle 이 든 레코드(시험 단언용)."""
    return [r for r in res.records if needle in (r.get("body_text") or "")]
