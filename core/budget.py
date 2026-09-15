# -*- coding: utf-8 -*-
"""AI 스테이지 시간 예산 — **한 벌**.

v3 구조 감사 실측: 같은 _stage_budget 이 judge/refine/agentic 세 파일에 복붙돼 있었고
(refine↔agentic 유사도 1.000 · judge↔refine 0.925), 사본을 안 만든 flow 는 조용히 정책 밖이었다.
'앞 단계가 전체 마감을 소진하면 뒤 단계가 입구에서 전멸' 사고의 땜질(floor)도 3중 복붙이었다.
예산 정책이 바뀔 때마다 3~4곳을 같은 모양으로 고쳐야 했고 한 곳은 매번 빠졌다 — 그래서 한 벌로 모은다.

규칙(기존 의미 그대로):
 · config.aiStageBudgetMin(기본 120, 0=끔)이 이 단계의 자기 예산.
 · run.py 가 물려준 전체 마감(LM_AI_DEADLINE, epoch 초)과 비교해 이른 쪽.
 · 전체 마감이 이미 지났어도 최소 몫(floor_min)은 준다 — "진행되다가 안 된다" 방지.
 · extra_cap_min 을 주면 그 값과도 min (flow 의 flowBudgetMin 편입 — 0 이면 무시=무제한).
"""
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def stage_budget(floor_min=15.0, extra_cap_min=None, root=None, now=None, mono=None,
                 stage_min_override=None):
    r"""(마감 시각(monotonic) 또는 None, 예산 분). 모든 AI 스테이지(judge·refine·agentic·flow)가
    이 함수 하나만 쓴다 — tools/check_l1.py 와 같은 취지의 관문이 사본 재출현을 막는다.
    now/mono: 호출 스테이지의 time.time/monotonic — 가상 시계 하네스(J.time 몽키패치)가
    이 함수까지 닿게 하는 주입구. 안 주면 실제 시계."""
    now = now or time.time
    mono = mono or time.monotonic
    mins = 120.0
    if stage_min_override is not None:
        # 자기 예산 키를 따로 가진 단계(flow=flowBudgetMin) — aiStageBudgetMin 을 읽지 않는다.
        # 0 = 무제한(그 단계의 기존 의미 그대로).
        mins = max(0.0, float(stage_min_override))
    else:
        try:
            with open(os.path.join(root or ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
                v = json.load(f).get("aiStageBudgetMin")
            if v is not None:
                mins = max(0.0, float(v))
        except (OSError, ValueError, TypeError, AttributeError):
            mins = 120.0
    if extra_cap_min:
        mins = min(mins, float(extra_cap_min)) if mins > 0 else float(extra_cap_min)
    dl = (mono() + mins * 60.0) if mins > 0 else None
    try:
        total_at = float(os.environ.get("LM_AI_DEADLINE") or 0)
    except ValueError:
        total_at = 0.0
    if total_at > 0:
        left = mono() + max(0.0, total_at - now())
        # 전체 마감이 지났어도 이 단계 최소 몫은 보장 — 앞 단계의 소진이 뒤 단계를 전멸시키지 않게
        left = max(left, mono() + max(0.0, float(floor_min)) * 60.0)
        dl = min(dl, left) if dl else left
    return dl, mins
