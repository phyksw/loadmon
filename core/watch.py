# -*- coding: utf-8 -*-
r"""자식 스테이지 감시 — **한 벌** (v3 구조 감사 4계층).

v2 는 같은 감시기 3함수(watch_child·_stage_limits·kill_tree)가 run.py 와 ui/app.py 에 통째로
복제돼(유사도 0.981·1.000·1.000) 따로 진화했고, 판정 근거가 'stdout 침묵'뿐이라 긴 Copilot
왕복(출력 없음·정상)과 죽음을 구분하지 못했다 — 정상 판정을 끊고 뒤 단계를 전멸시킨 사고의 뿌리.

v3 규약:
 · **생존**은 stdout 또는 상태 파일 하트비트(updated) 어느 쪽이든 뛰면 산 것이다 —
   두 신호가 모두 stall 한도를 넘겨야 죽인다(백신이 상태 파일 쓰기를 막아도 stdout 폴백).
 · **무진전**은 상태 파일 done(없으면 stdout [progress])에만 적용한다 — updated 와 분리
   (구조 감사 검증 에이전트: 이 둘을 섞으면 '느림 vs 죽음' 오진이 재발한다).
 · 중단 판단의 1차 권한은 스테이지 자신(예산 자가 중단·rc 2 부분)이고, 감시는 마지막 안전망이다.
run.py 와 ui/app.py 는 이 모듈을 임포트한다 — 사본 재출현은 lint 관문 8(tools/check_l1.py 계약 검사)이 막는다.
"""
import json
import os
import subprocess
import time

NO_WIN = 0x08000000


def kill_tree(pid):
    r"""프로세스와 자손 전부 종료(윈도) — 자식만 죽이면 그 아래 드라이버·Edge 가 남아 다음 실행을 막는다."""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=30, creationflags=NO_WIN)
    except (OSError, subprocess.SubprocessError):
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def stage_limits(cfg_dict=None):
    r"""(정체 한도 초, 절대 상한 초, 무진전 한도 초) — aiStageStallMin·aiStageMaxMin·
    aiStageNoProgressMin. 0 이면 끔. 절대 상한 기본 0(진행 중인 단계를 죽인 사고 전례)."""
    stall, cap, nop = 15.0, 0.0, 45.0
    try:
        c = cfg_dict or {}
        stall = float(c.get("aiStageStallMin", stall))
        cap = float(c.get("aiStageMaxMin", cap))
        nop = float(c.get("aiStageNoProgressMin", nop))
    except (ValueError, TypeError):
        pass
    return max(0.0, stall) * 60.0, max(0.0, cap) * 60.0, max(0.0, nop) * 60.0


def _state_probe(state_path):
    """상태 파일에서 (updated, done, state) — 없거나 깨졌으면 None(구판 자식 폴백)."""
    if not state_path:
        return None
    try:
        with open(state_path, encoding="utf-8-sig") as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("schema") == 1:
            return float(d.get("updated") or 0), int(d.get("done") or 0), str(d.get("state") or "")
    except (OSError, ValueError, TypeError):
        pass
    return None


def watch_child(p, on_line, label, beat_sec=120, cfg_dict=None, state_path=None):
    r"""자식 출력을 릴레이하며 정체를 감시한다. 반환: 중단 사유(없으면 None).
    state_path 를 주면(신판 자식) 하트비트·done 을 함께 본다 — 왕복이 길어 출력이 없어도
    하트비트가 뛰면 살아 있는 것으로 친다."""
    import queue
    import threading
    stall_sec, cap_sec, nop_sec = stage_limits(cfg_dict)
    q = queue.Queue()
    seen = {"phase": None, "done": -1}

    def _pg_of(s):
        if not s.startswith("[progress]"):
            return None
        try:
            ph, done, _tot = s[len("[progress]"):].strip().split("|")
            return ph.strip(), int(done)
        except (ValueError, AttributeError):
            return None

    def _rd():
        try:
            for ln in p.stdout:
                q.put(ln if isinstance(ln, str) else ln.decode("utf-8", "replace"))
        except (OSError, ValueError):
            pass
        finally:
            q.put(None)

    threading.Thread(target=_rd, daemon=True).start()
    t0 = last = beat = prog = time.time()
    why = None
    while True:
        try:
            ln = q.get(timeout=5)
        except queue.Empty:
            now = time.time()
            st = _state_probe(state_path)
            if st is not None:
                upd, done, _stv = st
                if upd > last:
                    last = upd                     # 하트비트 = 생존 — stdout 침묵이어도 산 것
                if done > seen["done"]:
                    seen["done"] = done
                    prog = now                     # 상태 파일 done = 진전
            if stall_sec and now - last > stall_sec:
                why = f"{label}: {int((now - last) // 60)}분 {int((now - last) % 60)}초 동안 아무 신호가 없어 중단했습니다"
            elif nop_sec and now - prog > nop_sec:
                why = (f"{label}: {int((now - prog) / 60)}분 동안 진행이 늘지 않아 중단했습니다"
                       " (진행률이 그대로입니다 — Copilot 창 상태를 확인하세요)")
            elif cap_sec and now - t0 > cap_sec:
                why = f"{label}: 시간 상한 {int(cap_sec / 60)}분을 넘겨 중단했습니다"
            if why:
                break
            if now - beat >= beat_sec:
                beat = now
                print(f"   … {label} 진행 중 (경과 {int((now - t0) / 60)}분 · 마지막 신호 {int(now - last)}초 전)",
                      flush=True)
            continue
        if ln is None:
            break
        last = time.time()
        _pg = _pg_of(ln.rstrip())
        if _pg and (_pg[0] != seen["phase"] or _pg[1] > seen["done"]):
            seen["phase"], seen["done"] = _pg[0], _pg[1]
            prog = last
        on_line(ln.rstrip("\n"))
        if cap_sec and time.time() - t0 > cap_sec:
            why = f"{label}: 시간 상한 {int(cap_sec / 60)}분을 넘겨 중단했습니다"
            break
        if nop_sec and time.time() - prog > nop_sec:
            why = f"{label}: {int((time.time() - prog) / 60)}분 동안 진행이 늘지 않아 중단했습니다"
            break
    if why:
        print(f"[!] {why}", flush=True)
        print("    멈춘 자리에서 끊었습니다 — 화면의 마지막 줄이 그 자리입니다. 가장 흔한 원인은 Copilot 창이 로그인·"
              "오류 화면에서 멈춘 것입니다 — [AI 연결 진단]으로 확인한 뒤 다시 실행하세요.",
              flush=True)
        kill_tree(p.pid)
        try:
            p.wait(timeout=30)
        except Exception:  # noqa: BLE001
            pass
    return why
