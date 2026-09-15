# -*- coding: utf-8 -*-
"""
progress.py — 단계별 진행률을 UI로 흘려보내는 한 줄 프로토콜.

각 실행기(mine·judge·refine·retag)가 아래 형식을 stdout 에 찍으면
ui/app.py 의 run_job 이 파싱해 진행 바·남은 시간으로 보여준다.

    [progress] <단계이름>|<완료>|<전체>

Copilot 왕복은 한 번에 수십 초~수 분이 걸린다. 그동안 화면이 멈춘 것처럼 보이면
사용자는 오류인지 대기인지 구분할 수 없다 — 그래서 왕복 '직전'에도 한 번 찍는다.
"""
import sys


def progress(phase, done, total):
    try:
        print(f"[progress] {phase}|{int(done)}|{int(total)}", flush=True)
    except (ValueError, TypeError):
        pass
    # v3: 상태 파일 피기백 — stdout 줄은 그대로(하위 호환), 열린 스테이지 상태가 있으면 함께 갱신.
    # 무진전 감시는 이제 이 done 값을 본다(updated 는 하트비트 스레드가 갱신 — 생존 전용).
    try:
        from stage_state import current
        st = current()
        if st is not None:
            st.beat(phase=phase, done=done, total=total)
    except Exception:  # noqa: BLE001 — 진행 표시가 스테이지를 죽이면 안 된다
        pass


def parse(line):
    """'[progress] 판정|3|12' → ('판정', 3, 12) / 아니면 None"""
    if not line.startswith("[progress]"):
        return None
    try:
        phase, done, total = line[len("[progress]"):].strip().split("|")
        return phase.strip(), int(done), int(total)
    except (ValueError, AttributeError):
        return None


if __name__ == "__main__":
    sys.exit(0)
