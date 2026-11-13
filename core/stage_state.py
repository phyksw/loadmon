# -*- coding: utf-8 -*-
r"""AI 스테이지 상태 파일 — 프로세스 경계를 넘는 **표준 계약** (v3 구조 감사 4계층).

v2 의 문제: 자식→부모의 실시간 채널이 stdout 한국어 문자열뿐이었다. 진행률은 '[progress]' 접두
규약, 실패 사유는 '마지막 줄 JSON', 화면의 '왜 비었나'는 last_run.json note 의 부분 문자열 분류 —
사람에게 보여주려는 문장이 곧 프로토콜이라, 문구 하나 다듬는 정상 유지보수가 조용한 프로토콜
파괴였다. 긴 Copilot 왕복 동안 출력이 없으면 정체 감지가 '느림'과 '죽음'을 구분하지 못해 정상 판정을
끊는 사고(v24.11 의 원인)도 같은 뿌리다.

v3 계약: report\stage_state_<tag>_<stage>.json 하나.
 · 생존(하트비트) — 데몬 하트비트 스레드가 30초마다 파일을 다시 쓴다(beat 수가 는다). 왕복이 아무리 길어도 뛴다.
   AF32(D10 — report\ 아래는 날짜만): 파일 안에 시각(epoch)을 두지 않는다. 생존 시각은 파일의 수정 시각(mtime)이 담고,
   읽는 쪽은 probe()·heartbeat() 로 얻는다. 글에는 started(날짜 'YYYY-MM-DD')·beat(횟수)·elapsed_sec(경과 초)만 둔다.
   옛 판 파일·시험이 쓴 숫자 updated 가 있으면 그것을 먼저 본다(하위 호환).
 · done/total(진전) — progress() 가 함께 갱신. 무진전 판정은 **done 에만** 적용한다
   (하트비트는 생존 판정 전용 — 검증 에이전트 지적: 이 둘을 섞으면 오진이 재발한다).
 · state: running | done | partial | failed  ·  stop.kind: budget | stall | fatal | login | lock
 · resume.pending — 남은 묶음 수(이어가기 가능 여부를 화면·부모가 데이터로 안다).
 · 쓰기는 tmp→os.replace 원자 교체, 실패는 무시하고 센다(백신·DLP 잠금 실측 전례 — 쓰기 실패가
   스테이지를 죽이면 안 된다). 파일은 tag×stage 당 1개 — 소유자(그 프로세스) 단독 쓰기.
stdout 의 '[progress]' 줄은 **그대로 유지**한다(하위 호환 — 구판 부모가 신판 자식을 돌려도 동작).
"""
import json
import os
import sys
import threading
import time
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import lmname  # noqa: E402

SCHEMA = 1
PRODUCT = lmname.PRODUCT     # 모든 AF32 산출물의 "product" 표식
_CUR = None          # 이 프로세스의 열린 상태(스테이지당 1개)


def state_path(report_dir, tag, stage):
    return os.path.join(report_dir, f"stage_state_{tag}_{stage}.json")


class StageState:
    def __init__(self, report_dir, tag, stage, launcher="run", budget_min=None):
        self.path = state_path(report_dir, tag, stage)
        self._t0 = time.monotonic()
        # 시각(epoch)은 두지 않는다(D10) — started 는 날짜, 생존은 beat 수와 파일 수정 시각(probe)
        self.d = {
            "product": PRODUCT, "schema": SCHEMA, "stage": stage, "tag": tag, "pid": os.getpid(),
            "launcher": launcher, "started": date.today().isoformat(), "beat": 0, "elapsed_sec": 0,
            "phase": "", "done": 0, "total": 0, "state": "running",
            "stop": {}, "error": {}, "budget": {"stage_min": budget_min},
            "resume": {"pending": None, "done_n": 0}, "outputs": {},
        }
        self._lock = threading.Lock()
        self._fails = 0
        self._stop_beat = threading.Event()
        self._write()
        t = threading.Thread(target=self._beat_loop, daemon=True)
        t.start()

    # ── 쓰기(원자·관용) ──
    def _write(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            self._fails += 1        # 잠금·백신 — 세기만 하고 계속(스테이지를 죽이지 않는다)

    def _tick(self):
        """하트비트 한 번 — beat 수·경과 초를 올린다(쓰기는 부르는 쪽). 파일을 다시 쓰면 수정 시각이 생존 시각이 된다."""
        self.d["beat"] = int(self.d.get("beat") or 0) + 1
        self.d["elapsed_sec"] = int(time.monotonic() - self._t0)

    def _beat_loop(self):
        while not self._stop_beat.wait(30.0):
            with self._lock:
                self._tick()
                self._write()

    # ── 스테이지가 부르는 것 ──
    def beat(self, phase=None, done=None, total=None):
        with self._lock:
            if phase is not None:
                self.d["phase"] = str(phase)
            if done is not None:
                self.d["done"] = int(done)
            if total is not None:
                self.d["total"] = int(total)
            self._tick()
            self._write()

    def note_resume(self, pending=None, done_n=None):
        with self._lock:
            if pending is not None:
                self.d["resume"]["pending"] = int(pending)
            if done_n is not None:
                self.d["resume"]["done_n"] = int(done_n)
            self._write()

    def output(self, key, path):
        with self._lock:
            self.d["outputs"][key] = os.path.basename(str(path))
            self._write()

    def finish(self, state, stop_kind=None, reason=None, error=None, hint=None):
        """state: done|partial|failed · stop_kind: budget|stall|fatal|login|lock (partial/failed 때)."""
        self._stop_beat.set()
        with self._lock:
            self.d["state"] = str(state)
            self._tick()
            if stop_kind:
                self.d["stop"] = {"kind": str(stop_kind), "reason": str(reason or "")[:300]}
            if error:
                self.d["error"] = {"error": str(error)[:300], "hint": str(hint or "")[:200]}
            self._write()
        global _CUR
        if _CUR is self:
            _CUR = None


def open_stage(report_dir, tag, stage, launcher=None, budget_min=None):
    """스테이지 main 첫머리 1줄 — 상태 파일을 열고 하트비트를 시작한다. 실패해도 None(무해)."""
    global _CUR
    try:
        launcher = launcher or os.environ.get("AF32_LAUNCHER") or "run"
        _CUR = StageState(report_dir, tag, stage, launcher=launcher, budget_min=budget_min)
    except (OSError, ValueError):
        _CUR = None
    return _CUR


def current():
    return _CUR


DEAD_AFTER_SEC = 90.0     # 하트비트(30초) 3주기 — running 인데 이보다 오래 조용하면 죽은 것


def _beat_at(d, path=None):
    """마지막 하트비트 시각(epoch) — 옛 판·시험이 쓴 숫자 updated 가 있으면 그것, 아니면 파일 수정 시각(mtime). 모르면 0."""
    v = d.get("updated") if isinstance(d, dict) else None
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return float(v)
    if path:
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0
    return 0.0


def heartbeat(path):
    """상태 파일의 마지막 하트비트 시각(epoch · 파일 수정 시각) — 없으면 0."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return _beat_at(d if isinstance(d, dict) else {}, path)


def probe(path):
    """정체 확인(core\\watch)용 — 상태 파일 → (마지막 하트비트 epoch, done, state) | None(없거나 깨졌거나 다른 판).
    하트비트는 파일 수정 시각이다(report\\ 아래 글에는 시각을 두지 않는다 — D10)."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("schema") == SCHEMA:
            return _beat_at(d, path), int(d.get("done") or 0), str(d.get("state") or "")
    except (OSError, ValueError, TypeError):
        pass
    return None


def _normalize(d, path=None):
    """running 인데 하트비트가 멎은 지 오래면 사망으로 보정해 돌려준다 — finish 없이 죽은(kill·
    예외·조기 반환) 프로세스의 상태 파일이 화면을 영원히 '실행 중' 으로 속이지 않게(최종 검증 MAJOR).
    하트비트 시각은 _beat_at(옛 updated 또는 파일 수정 시각)."""
    try:
        if (d.get("state") == "running"
                and time.time() - _beat_at(d, path) > DEAD_AFTER_SEC):
            d = dict(d, state="failed",
                     stop={"kind": "stall", "reason": "프로세스가 하트비트 없이 사라졌습니다(중단·강제 종료)"})
    except (TypeError, ValueError):
        pass
    return d


def read_state(report_dir, tag, stage):
    """부모·화면이 읽는다 — 없거나 깨졌으면 None(구판 자식 → 기존 stdout 해석으로 폴백)."""
    p = state_path(report_dir, tag, stage)
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        return _normalize(d, p) if isinstance(d, dict) and d.get("schema") == SCHEMA else None
    except (OSError, ValueError):
        return None


def read_latest(report_dir, stage):
    """태그를 모를 때 — 그 스테이지의 가장 최근 상태 파일."""
    import glob
    best, best_t = None, -1.0
    for p in glob.glob(os.path.join(report_dir, f"stage_state_*_{stage}.json")):
        try:
            t = os.path.getmtime(p)
            if t > best_t:
                with open(p, encoding="utf-8-sig") as f:
                    d = json.load(f)
                if isinstance(d, dict) and d.get("schema") == SCHEMA and d.get("tag"):
                    best, best_t = _normalize(d, p), t       # 빈 tag 파일(인자 없는 실행 잔재)은 무시
        except (OSError, ValueError):
            continue
    return best


if __name__ == "__main__":
    sys.exit(0)
