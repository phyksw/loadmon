# -*- coding: utf-8 -*-
r"""개발 PC 모양의 합성 저장 행(회사 계정 없음 — 메일·팀즈·일정 0, PC 흔적만) — 규칙 제안 과제 이름 시험(W2 검토 C06 · N2).

실측(2026-10-06) 모양만 흉내 낸다 — 실제 자료·실명·사내 이름 없음(자리표시자):
- `pc.events` 켜짐 구간(평일 08:50~18:10), `pc.sampler` 창 표본(개발 도구 창 제목 '<파일> - <작업 폴더> - Visual Studio Code',
  작업 폴더가 없으면 '<파일> - Visual Studio Code'), `pc.files` 저장(프로그램·자료 파일), `pc.git` 커밋(범용 낱말 메시지).
- 파일 이름은 프로그래밍 동사·범용 낱말·연도·판 꼬리 조각뿐이다(get_signals.py · judge_load.py · refine_v2.py · signals_2026.json …)
  — 이 조각들이 과제 이름이 되면 안 된다. 작업 폴더 이름(`folder`)이 있으면 그것이 과제 이름 후보다.
- 키는 무키 해시(`hierkit.fake_*`) — 시험 전용.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

from tests.fixtures.wp22 import hierkit as K

KST = timezone(timedelta(hours=9))
START = date(2026, 8, 3)                       # 월요일
FILES = ("get_signals.py", "load_signals.py", "judge_load.py", "refine_judge.py", "get_refine.py", "signals_2026.json",
         "signals_2026_get.json", "refine_v2.py")
JUNK = frozenset({"get", "judge", "refine", "load", "signals", "signals_2026", "signals2026", "py", "json", "v2", "w2",
                  "2026", "code", "visual", "studio"})
COMMITS = ("W2 검토 반영", "v2 수정", "코드 정리", "테스트 추가")


def _utc(d: date, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=KST).astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _h(prefix: str, *parts, n: int = 16) -> str:
    return prefix + hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:n]


def workdays(weeks: int) -> list[date]:
    return [START + timedelta(days=7 * w + i) for w in range(weeks) for i in range(5)]


def title(file: str, folder: str | None) -> str:
    return f"{file} - {folder} - Visual Studio Code" if folder else f"{file} - Visual Studio Code"


def rows(folder: str | None = "loadmon27", *, weeks: int = 6, step_min: int = 10) -> list[dict]:
    """정제 후 저장 행(계약 §3.1·§3.2 모양). 하루에 파일 둘(오전·오후)을 번갈아 연다."""
    out: list[dict] = []
    repo = _h("r", "repo", folder or "repo")
    dirs = [K.fake_folder(folder or "work"), K.fake_folder("dev")]
    for n, d in enumerate(workdays(weeks)):
        out.append(K.row("pc_session", "pc.events", _iso(_utc(d, 8, 50)), ts_end=_iso(_utc(d, 18, 10)), app_id=None,
                         session_state="active", idle_sec=None, layer="L0", event_class="boot", ts_precision="minute"))
        out.append(K.row("pc_session", "pc.events", _iso(_utc(d, 8, 52)), ts_end=_iso(_utc(d, 18, 8)), app_id=None,
                         session_state="active", idle_sec=None, layer="L1", event_class="logon",
                         ts_precision="minute"))
        am, pm = FILES[n % len(FILES)], FILES[(n + 2) % len(FILES)]
        for half, (h0, h1, f) in enumerate(((9, 12, am), (13, 18, pm))):
            m = h0 * 60
            while m < h1 * 60:
                t0 = _utc(d, m // 60, m % 60)
                out.append(K.row("pc_session", "pc.sampler", _iso(t0), ts_end=_iso(t0 + timedelta(minutes=step_min)),
                                 app_id="vscode", fg_exe="code.exe", app_class="ide", title_masked=title(f, folder),
                                 doc_key=K.fake_doc(f), site_class=None, session_state="active", idle_sec=5,
                                 layer="L3", event_class=None, ts_precision="exact"))
                m += step_min
            ts = _utc(d, h0 + 1, 17 + half)
            out.append(K.row("pc_file", "pc.files", _iso(ts), doc_key=K.fake_doc(f), path_key=_h("f", folder, f),
                             name_masked=f, ext="." + f.rsplit(".", 1)[-1], folder_role="other", root_id=None,
                             op="save", dir_keys=dirs, flags={"edit": True}, ts_precision="exact"))
        tc = _utc(d, 17, 40)
        out.append(K.row("pc_git", "pc.git", _iso(tc), doc_key=repo, commit_key=_h("g", d.isoformat()),
                         msg_masked=COMMITS[n % len(COMMITS)], n_commits=1, n_files=2, exts=[".py"],
                         ts_precision="exact"))
    return sorted(out, key=lambda r: (r["ts_utc"], r["id"]))
