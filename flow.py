# -*- coding: utf-8 -*-
r"""
flow.py — 담당자 워크플로우 분석 (LoadMonitor24: 과제 / 담당업무 단위)

**(과제, 담당 업무)** 마다 Copilot 에게 [시간순 신호 표본 + 정제 설명]을 주고 세 가지를 판정시킨다:
  ① 역할     — 이 담당 업무에서 사용자가 어떤 롤인가 (주도/실무/검토/조율 등 + 근거)
  ② 워크플로우 — 일이 실제로 흘러간 순서: 단계별로 무슨 일을 했고 어떤 주기로 반복되는지
  ③ Agent 가능성 — 각 단계를 Agentic AI 가 대체/보조할 수 있는지 (상/중/하 + 방안)

LoadMonitor20 과 다른 점:
  · 과제(model) 단위로 묶으면 관계없는 업무가 한 흐름으로 엮였다(실측) → (과제, 담당업무) 단위.
    신호 3건 미만인 단위는 흐름이라 할 수 없어 제외한다.
  · 먼저 세부업무 표기 병합 맵(core/details — 규칙 + Copilot, config\detail_aliases.json 캐시)을
    만들어 적용한다: '레이아웃 검토/수정/리뷰 회의' 처럼 조각난 이름이 한 단위가 된다. --no-merge 면
    규칙 병합만.
  · MM 은 AI 가 만들지 않는다 — mm_rows(정제본 우선) 실측 합을 프로그램이 붙인다(프롬프트에는
    신호 건수만 보낸다).
  · 판정(model) 열이 없는 기간은 규칙 축(project/activity)으로 만들되 basis:"규칙" 을 남긴다.

  python flow.py                          # 최신 결과 대상
  python flow.py --from ... --to ... [--no-merge] [--budget 7000]

묶음이 많은 사람이 통째로 실패하던 것(S2)에 대한 보강 — agentic.py 와 같은 규칙:
  · 묶음은 같은 채팅에서 이어 보낸다(fresh=None — 첫 왕복·실패 뒤·chatTurns 마다만 새 채팅, 앞 묶음의 표기를 기억)
    · 묶음당 단위 6개 상한(답이 잘리지 않게) · 잘린 JSON 복구(core/details.find_json)
  · fatal(로그인 만료·Edge 미기동) 즉시 중단 + 사유 hint · 연속 실패 3회 중단 · 적응 분할
  · 묶음별 저장 + 이어서 판정(지난 결과의 flows 는 두고 missing 만 보낸다, --redo 면 처음부터)
  · 신호 3건 이상인 단위가 없으면 실패가 아니라 '결과 없음'(ok:true, flows:[], empty_reason) 으로 저장한다.

출력: report\workflow_<기간>.json  →  UI '담당자 워크플로우' 탭 (f.model/role/summary/steps/mm.mm/signals)
  {ok, tag, generated, model_name, unit:"과제"|"과제/담당업무", basis, flows[{model:"과제"(기본) 또는 "과제 / 담당업무",
   level1:"신제품개발|기술 내재화|양산준비|일반업무"(상위 · 정제 단계가 채운다. 없으면 빈 문자열),
   branch:"흐름 이름"(한 과제 안에서 서로 이어지지 않는 일은 흐름을 나눠 여러 건이 된다. 하나뿐이면 ""),
   upstream/downstream:"같은 과제의 앞·뒤 담당업무 키"(이어짐만 표시 · 흐름은 합치지 않는다. 없으면 ""),
   project, detail, role, summary, steps[≤8], mm:{mm}, signals}], chunks, failed_chunks, salvaged_chunks,
   missing, missing_count, partial, note, last_error, dropped, merge:{rule, ai}, rows_units, empty_reason?}
"""
import glob
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from progress import progress  # noqa: E402
import details  # noqa: E402
from details import fold, _fresh_refined  # noqa: E402,F401  (호환: 옛 이름 유지)

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8

PROMPT_BUDGET = 8300            # 한 번에 보낼 프롬프트 글자 수 상한 (입력 잘림 방지)
#                                 7,000 이던 것을 올렸다 — 묶음이 잘게 갈려 왕복이 1.6배가 됐고
#                                 그중 14~21%는 단위 1개짜리로 예산의 45%만 쓰고 있었다(감사 실측).
#                                 답 길이는 ANSWER_BUDGET 5,500 이 그대로 제동하므로 '답 잘림' 위험은 없고,
#                                 최대 프롬프트 8,102자 < 드라이버 분할 문턱(SAFE_PROMPT 9,000 − 서약 38)
#                                 이라 2조각 분할도 생기지 않는다. 실측 시뮬: 묶음 118 → 98(-17%).


def _chat_note():
    """로그용 — 묶음을 같은 채팅에서 이어 보내는 정책(config.copilotAuto.chatTurns)"""
    try:
        import judge
        n = judge.chat_turns()
    except Exception:  # noqa: BLE001 - 로그 문구가 실행을 막지 않게
        return ""
    return " — 설정 chatTurns=0: 묶음마다 새 채팅" if n <= 0 else f" · 첫 왕복·실패 뒤·{n}회마다 새 채팅"
L1_MARGIN = 0.60                # 상위(업무 성격) 확정에 필요한 1위 표 비중 — 못 넘으면 찍지 않고 '혼재' 로 남긴다.
#                                 51:49 로 갈린 과제와 100:0 인 과제를 같게 다루던 argmax 를 대신한다(감사 지적).
#                                 계층 분류 문헌의 통례 — 확신이 없으면 하위로 내려가지 않고 기권한다.
MIN_SIGNALS = 3                 # 이보다 적은 신호는 흐름이라 할 수 없다
MIN_STEPS = 3                   # 이보다 얕은 흐름은 잘린 답의 잔해로 보고 다시 묻는다(프롬프트도 3단계 이상 요구)
FINISH_ROUNDS = 12              # 미판정 자동 마무리 **상한** 회차 — 실제로는 '진전이 없으면' 먼저 멈춘다.
#                                 예전엔 2 로 고정이라, 두 번 돌고도 남으면 사람이 [이어서 분석]을 또 눌러야 했다(제보).
MAX_BRANCHES = 4                # 한 과제가 가질 수 있는 흐름 수 — 이어지지 않는 일을 억지로 엮지 않되
#                                 무한정 쪼개지도 않게. 초과분은 버리지 않고 마지막 흐름에 잇는다.
SAMPLE_N = 14                   # 단위당 시간순 표본 수
MAX_UNITS_PER_CHUNK = 10        # 묶음당 단위 상한(마지막 방어선) — 실제 제동은 ANSWER_BUDGET 이 건다
ANSWER_PER_UNIT = 1100          # 단위 하나가 요구하는 답 길이(실측 ≈1,100자)
ANSWER_BUDGET = 5500            # 한 왕복이 요구할 답 길이 상한 — 넘으면 잘려 salvage 로 단계가 깎인다
#                                 (실측: LM22 가 한 왕복에 9,520자를 요구해 보완2 4,760자의 2배였다)
MAX_CHUNKS = 400                # 묶음 수 상한(폭주 방지용 최후 방어선) — 이 실행을 실제로 끊는 것은
#                                 아래 시간 예산이다. 예전엔 40 이라 단위가 많은 사람은 한 번에 못 끝났다(제보).
BUDGET_MIN = 120                # 워크플로우 전체 시간 예산(분) — 이 안에 끝내고, 넘으면 그때까지 것을 저장한다.
#                                 run.py·대시보드는 flow.py 에 타임아웃을 걸지 않으므로(p.wait()) 스스로 끊어야 한다.
#                                 config.flowBudgetMin 으로 조절 · 0 이면 무제한(끝까지).
MAX_CONSEC_FAIL = 3             # 연속 실패 상한 — Copilot 이 안 되는 날 남은 묶음을 헛되이 기다리지 않게
UNIT = ""                      # 실행 시 workflow_unit() 로 채운다(아래) — 설정이 바뀌면 캐시가 무효화되어야 한다
KEY_JOIN = " / "                # flow.model = "과제 / 담당업무"


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def latest_tag():
    fs = sorted(glob.glob(os.path.join(ROOT, "report", "mm_meta_*.json")), key=os.path.getmtime)
    return os.path.basename(fs[-1])[len("mm_meta_"):-len(".json")] if fs else ""


def _spread(lst, n):
    """시간순 고른 표본 — 기간의 앞·중간·끝이 남아 흐름이 보인다."""
    if len(lst) <= n:
        return lst
    if n <= 1:
        return lst[:1]
    step = (len(lst) - 1) / (n - 1)
    return [lst[round(i * step)] for i in range(n)]


THIN = []                       # gather 가 문턱 미달로 뺀 (과제, 담당업무, 신호수) — main 이 알린다


def unit_key(md, dt):
    return f"{md}{KEY_JOIN}{dt}" if dt else str(md)


def _seed_from_refine(amap, tag, rep, rows_plain):
    """refine 이 한 행으로 합친 원본 (과제, 담당업무) 들을 별칭 맵에 보탠다 → 새로 넣은 수.
    같은 과제 안의 병합만 쓰고, 괄호 꼬리가 다르면 거부(_accept_group3), 대표는 MM 큰 이름,
    캐시에 이미 있는 방향은 지킨다(_set_alias). 원본 파일은 건드리지 않는다."""
    rmap = _refine_orig(tag, rep)
    if not rmap or not rows_plain:
        return 0
    by_pj, mm_w = details._detail_pools(rows_plain)
    n = 0
    for rk, pairs in rmap.items():
        pjs = {p for p, _d in pairs if p}
        if len(pjs) != 1:
            continue                         # 과제를 넘나드는 병합은 워크플로우 단위에 쓰지 않는다
        pj = next(iter(pjs))
        pool = by_pj.get(pj) or set()
        names = [d for _p, d in pairs if d]
        acc = details._accept_group3(names, pool, {d: mm_w.get((pj, d), 0.0) for d in pool})
        if not acc:
            continue                         # 실재하지 않는 이름·1개짜리·괄호 꼬리 상이 → 거부(가드는 그대로)
        # 대표 이름은 refine 이 지은 이름(refine_map 키 '과제/정제이름' 의 뒷부분)으로 — 그래야 워크플로우 카드가
        # 분석 리포트 '업무별 상세' 표와 같은 이름으로 보인다. 신호·행 모두 apply_detail_map 으로 그 이름이 되므로
        # 신호 축에 없는 이름이어도 단위 키는 어긋나지 않는다.
        refined = rk.split("/", 1)[1].strip() if "/" in rk else ""
        canon = refined or acc[0]
        for x in names:
            if x != canon and details._set_alias(amap, pj, x, canon):
                n += 1
    return n


def _refine_orig(tag, rep=None):
    r"""report\refine_map_<tag>.json → {"정제L2/정제L3": [(원본L2, 원본L3), …]}. 없으면 빈 dict."""
    import json
    p = os.path.join(rep or details.REPORT, f"refine_map_{tag}.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return {}
    mp = o.get("map") if isinstance(o, dict) else None
    out = {}
    for k, v in (mp.items() if isinstance(mp, dict) else []):
        pairs = [(str(it[0] or "").strip(), str(it[1] or "").strip())
                 for it in (v if isinstance(v, list) else []) if isinstance(it, (list, tuple)) and len(it) >= 2]
        if pairs:
            out[str(k).strip()] = pairs
    return out


# ── 재료 (보완2.wf_materials 이식) ────────────────────────────────────────
L1_PIN = {}        # ukey2(과제) → 상위. config\projects.json 의 level1 — 사람이 못 박은 값은 투표를 이긴다


def load_l1_pin(root):
    """지정 과제 목록에서 상위를 읽어 둔다 — 상위는 Level 2·3 과 달리 사람이 고칠 수단이 전혀 없었다."""
    out = {}
    try:
        import projmap
        for p in (projmap.load_user_projects(root) or []):
            nm, l1 = str(p.get("name") or "").strip(), details.snap1(p.get("level1"))
            if nm and l1:
                out[details.ukey2(nm)] = l1
    except Exception:  # noqa: BLE001 - 지정 과제가 없어도 워크플로우는 돈다
        return {}
    return out


def gather(rep, tag, amap=None, pmap=None):
    """(과제, 담당 업무) 단위 재료 → (mats, basis, err).
    signals 를 (model|project, detail|activity) 로 묶고 MIN_SIGNALS 미만 제외, 시간순 표본,
    mm 은 mm_rows(정제본 우선) (Level 2, Level 3) fold 합, desc 는 정제 상세설명."""
    sigs = details.read_signals(tag, rep)
    if not sigs:
        return [], "", f"signals_{tag}.csv 가 없거나 비었습니다 — 그 기간을 다시 분석하세요"
    head = sigs[0] or {}
    if "model" in head:
        basis = "판정"
    elif "project" in head or "activity" in head:
        basis = "규칙"
    else:
        return [], "", f"signals_{tag}.csv 에 판정(model)·규칙(project) 열이 모두 없습니다"
    # ★ MM 은 **판정 축**(원본 mm_rows)에서 읽는다. 예전에는 정제본을 우선해서 읽었는데, refine 이
    #   이름을 합치고 바꾸므로 신호(signals)의 (과제, 담당업무) 키와 하나도 맞지 않아 **모든 단위의 MM 이
    #   0.0** 으로 나왔다(실데이터 실측: 12/12 단위 0.0, 원본으로 바꾸면 합 0.339 로 정상 복구).
    #   MM 총량을 다시 계산하는 것이 아니라 '조회 축'만 바로잡는 것이라 로드율에는 영향이 없다.
    rows, _fn = details.read_rows(tag, rep, plain=True)
    # 과제(중위) 병합이 **먼저**다 — 세부업무 맵의 키가 (과제, 이름) 이고 _detail_pools 의 파티션 키도
    # raw Level 2 라, 과제가 갈린 채로 두면 세부 병합까지 반쪽이 된다(감사 실측).
    if pmap:
        details.apply_project_map(rows, sigs, pmap)
    if amap:
        details.apply_detail_map(rows, sigs, amap)
    mm_by, desc_by = {}, {}
    for r in rows:
        # 신호 쪽 기본값('공통'/'기타')과 같은 축으로 — 과제나 세부업무가 빈 행의 MM 이 단위에 붙지 않던 것
        k = (fold((r.get("Level 2") or "").strip() or "공통"), fold((r.get("Level 3") or "").strip() or "기타"))
        mm_by[k] = mm_by.get(k, 0.0) + r["_mm"]
        d = " ".join((r.get("상세설명") or "").split())
        if d:
            desc_by.setdefault(k, d[:120])
    # 정제 상세설명은 정제본에만 있다 — refine_map 으로 원본 이름에 되짚어 얹는다(설명이라 중복은 무해).
    # MM 은 여기서 손대지 않는다: 정제 행 하나가 원본 여럿에서 왔을 때 원본마다 같은 MM 을 붙이면 총량이 부푼다.
    # 상위(Level 1)는 판정 단계에서 빈칸이고 정제 단계만 채운다 — 정제본에서 원본 이름 축으로 되짚어 온다.
    parts_by, dsc_by = {}, {}   # 과제 축 — 세부업무 MM 배분 / 정제 설명(아래 두 루프가 함께 채운다)
    # ★ 키는 **과제 병합 대표** 이름이어야 한다. 예전에는 병합 전 원본 이름(fold(o2))으로 표를 만들고
    #   조회는 병합 후 대표 이름으로 해서, 흡수된 과제의 상위 표가 통째로 버려졌다 — 합성 실측에서
    #   전체 MM 의 절반을 차지한 '양산준비' 표가 사라지고 0.5MM 짜리가 과제 전체를 대표했다(감사 확인).
    #   축도 fold 가 아니라 병합과 같은 ukey2 를 쓴다. fold 는 괄호를 지워, 병합이 일부러 갈라 둔
    #   '(양산)'/'(선행)' 두 과제가 서로의 상위를 가져갔다(감사 실측).
    def _l1k(name):
        return details.ukey2((pmap or {}).get(str(name or "").strip(), str(name or "").strip()) or "공통")

    l1_w = {}          # ukey2(병합 대표 과제) → {상위: mm 합}
    try:
        rrows, _rfn = details.read_rows(tag, rep)
        if _rfn and _rfn.endswith("_refined.csv"):
            rmap = _refine_orig(tag, rep)
            for r in rrows:
                # 읽을 때도 스냅한다 — refine 은 저장 시 스냅하지만, **이미 만들어진 정제본**에는
                # 스냅 전 값이 남아 있다. 그걸 그대로 쓰면 '기술내재화'가 다섯 번째 상위로 화면에 뜬다.
                l1 = details.snap1(r.get("Level 1"))
                d = " ".join((r.get("상세설명") or "").split())
                l2 = (r.get("Level 2") or "").strip()
                l3 = (r.get("Level 3") or "").strip()
                pairs = rmap.get(f"{l2}/{l3}", []) or [(l2, l3)]
                if d:
                    # 별칭 병합이 refine 이 지은 이름을 대표로 쓰면 단위 키가 그 이름이 된다 — 그 축으로도 색인
                    desc_by.setdefault((fold(l2 or "공통"), fold(l3 or "기타")), d[:120])
                for (o2, o3) in pairs:
                    if d:
                        desc_by.setdefault((fold(o2 or "공통"), fold(o3 or "기타")), d[:120])
                        # 과제 단위 카드도 정제 설명을 받아야 한다 — 판정 축(원본 mm_rows)의 상세설명은
                        # 비어 있으므로, 여기서 과제 축으로도 모아 두지 않으면 0줄이 나간다(실측).
                        dsc_by.setdefault(fold(o2 or "공통"), []).append(f"{o3}: {d[:80]}")
                    if l1:
                        # 정제 행 하나가 원본 여럿에서 왔으면 MM 을 나눠 싣는다(총량이 부풀지 않게)
                        w = r["_mm"] / max(1, len(pairs))
                        g = l1_w.setdefault(_l1k(o2), {})
                        g[l1] = g.get(l1, 0.0) + w
    except Exception:  # noqa: BLE001 - 설명·상위가 없어도 워크플로우는 나와야 한다
        pass

    # 과제 안의 세부업무 MM 배분 — 과제 단위 카드가 LM20 처럼 '무엇에 얼마' 를 보여 주는 재료.
    for r in rows:
        l2 = (r.get("Level 2") or "").strip() or "공통"
        l3 = (r.get("Level 3") or "").strip() or "기타"
        f2 = fold(l2)
        parts_by.setdefault(f2, {})
        parts_by[f2][l3] = parts_by[f2].get(l3, 0.0) + r["_mm"]
        d = " ".join((r.get("상세설명") or "").split())
        if d:
            dsc_by.setdefault(f2, []).append(f"{l3}: {d[:80]}")

    # 요청→산출 페어(에피소드) — pivots 가 만든 '무엇이 요청돼 무엇으로 끝났고 리드타임이 얼마인가'.
    # 흐름을 잇는 핵심 재료인데 LM22 에서 통째로 빠져 있었다(모델이 시간순 나열만 보고 순서를 지어냈다).
    eps_by = {}
    try:
        with open(os.path.join(rep, f"pivots_{tag}.json"), encoding="utf-8-sig") as f:
            _pv = json.load(f)
        for od in ((_pv.get("episodes") or {}).get("orders") or []):
            if not isinstance(od, dict):
                continue
            eps_by.setdefault(fold(od.get("model") or ""), []).append(
                f"요청 '{str(od.get('req') or '')[:50]}' → 산출 '{str(od.get('done') or '')[:50]}'"
                + (f" (리드 {od.get('lead_h')}h)" if od.get("lead_h") is not None else ""))
    except (OSError, ValueError, AttributeError):
        pass

    unit = workflow_unit()
    groups = {}
    for s in sigs:
        # 이름 속 개행·탭은 공백으로 — '## 과제 / 담당업무' 머리말이 두 줄로 갈라지면 키를 못 맞춘다
        md = " ".join((s.get("model") or s.get("project") or "").split())
        dt = " ".join((s.get("detail") or s.get("activity") or "").split())
        if not md and not dt:
            continue
        # 기본(LM20 과 같음)은 과제 하나가 한 단위다 — 담당업무로 더 쪼개지 않는다.
        groups.setdefault((md or "공통", (dt or "기타") if unit == "과제/담당업무" else ""), []).append(s)

    # 담당업무 단위(기본)는 보완2 와 같이 신호 3건 미만을 뺀다. 예전에 그것들을 '<과제> / 기타 담당업무' 로
    # 모았는데, 그 자체가 서로 무관한 일을 한 타임라인에 엮는 뭉치였다(제보) — 없앤다.
    # 별칭 병합이 신호 축에 제대로 걸리면 조각이 합쳐져 문턱 미달이 크게 준다. 뺀 것은 세어 두고 알린다.
    floor = MIN_SIGNALS if unit == "과제/담당업무" else 1
    THIN.clear()
    for (md, dt), ss in list(groups.items()):
        if len(ss) < floor:
            THIN.append((md, dt, len(ss)))
            del groups[(md, dt)]
    # 표본 수도 LM20 과 같은 눈금 — 단위가 적으면 과제마다 더 많이 보여 준다
    per_cap = SAMPLE_N if unit == "과제/담당업무" else (30 if len(groups) <= 3 else 20)
    out = []
    for (md, dt), ss in groups.items():
        if len(ss) < floor:
            continue
        ss.sort(key=lambda r: str(r.get("time") or ""))
        ev = [f"- {(r.get('time') or '')[5:16]} [{r.get('source')}] "
              f"{' '.join((r.get('text') or '').split())[:80]}"
              for r in _spread(ss, per_cap)]
        f2 = fold(md)
        if dt:
            mm = round(mm_by.get((f2, fold(dt)), 0.0), 3)
            desc = desc_by.get((f2, fold(dt)), "")
            parts = []
        else:
            # 과제 단위: 그 과제의 세부업무 MM 을 모두 더하고, 배분은 parts 로 함께 넘긴다(LM20 과 같은 카드).
            pv = parts_by.get(f2) or {}
            mm = round(sum(pv.values()), 3)
            parts = [[n, round(v, 3)] for n, v in sorted(pv.items(), key=lambda kv: -kv[1])[:8] if v > 0]
            desc = " · ".join((dsc_by.get(f2) or [])[:6])
        # 상위는 표가 갈리면 **찍지 않는다**. 1위 비중이 L1_MARGIN 에 못 미치면 빈 값으로 두고
        # 진 표를 level1_mix 에 남겨 화면이 '상위 혼재' 로 알린다 — 혼재 자체가 '과제가 과병합됐거나
        # 상위 판정이 갈렸다' 는 신호라, 억지로 하나를 찍으면 그 사실이 숨는다(감사 지적).
        # 지정 과제(config\projects.json)에 상위를 적어 두었으면 그것이 투표를 이긴다.
        g1 = l1_w.get(details.ukey2(md)) or l1_w.get(f2) or {}
        pinned_l1 = (L1_PIN.get(details.ukey2(md)) or "")
        level1, level1_mix = pinned_l1, []
        if not level1 and g1:
            tot = sum(g1.values())
            top, w1 = max(g1.items(), key=lambda kv: (kv[1], kv[0]))
            if tot > 0 and w1 / tot >= L1_MARGIN:
                level1 = top
            else:
                level1_mix = [[k, round(v, 3)] for k, v in sorted(g1.items(), key=lambda kv: -kv[1])[:3]]
        out.append({"model": md, "detail": dt, "key": unit_key(md, dt), "signals": len(ss),
                    "level1": level1, "level1_mix": level1_mix, "mm": mm, "desc": desc, "parts": parts,
                    # 요청→산출 페어 — 파일 스스로 '흐름을 잇는 핵심 재료' 라 부르는 것인데 담당업무 카드에는
                    # 한 건도 안 실려 모델이 시간순 나열만 보고 순서를 지어냈다(실측: 페어 0). 되살린다.
                    # 과제 전체 페어라 다른 업무 것이 섞일 수 있으므로 '이 과제의 페어' 라고 밝혀 붙인다.
                    "episodes": (eps_by.get(f2) or [])[:(5 if not dt else 3)], "evidence": ev})
    if not out:
        return [], basis, (f"흐름을 만들 단위가 없습니다 (단위 {len(groups)}개 · 신호 {len(sigs)}건)")
    # 상위(업무 성격)로 먼저 묶고 그 안에서 무거운 순 — LM20 처럼 상위 단위로도 읽히게 한다.
    L1_ORDER = {"신제품개발": 0, "기술 내재화": 1, "양산준비": 2, "일반업무": 3}
    # 과제(중위) 안에서는 무거운 순 — 담당업무 카드가 자기 과제 밑에 모여 '상위 → 과제 → 담당업무' 로 읽힌다.
    # 과제 순서 자체는 그 과제의 MM 합(내림차순)으로 정한다.
    pj_mm = {}
    for x in out:
        pj_mm[fold(x["model"])] = pj_mm.get(fold(x["model"]), 0.0) + x["mm"]
    out.sort(key=lambda x: (L1_ORDER.get(x.get("level1") or "", 9), x.get("level1") or "힣",
                            -pj_mm.get(fold(x["model"]), 0.0), fold(x["model"]),
                            -(x["mm"] * 100 + x["signals"])))
    return out, basis, ""


def build_prompt(mats):
    # 단위가 '과제' 인지 '과제/담당업무' 인지에 따라 말을 바꾼다 — 프롬프트가 단위와 어긋나면
    # 모델이 한 흐름 안에서 여러 업무를 섞거나, 반대로 과제를 더 쪼개려 든다.
    by_task = not any(m.get("detail") for m in mats)
    unit_word = "과제" if by_task else "담당 업무"
    if not by_task:
        # 보완2 의 문안 그대로(간결 · 3~6단계 · 다른 업무 섞지 말 것). 업무 내용 예시는 두지 않는다 —
        # 사람마다 하는 일이 달라 예시가 틀이 된다(제보).
        lines = [
            "당신은 업무 프로세스 분석가입니다. 아래는 한 엔지니어의 **담당 업무별** 실제 활동 흔적입니다",
            "(과제 / 담당 업무 단위 · 시간순 raw 신호 표본 · 요청→산출 페어 · AI 가 정제한 설명).",
            "",
            "담당 업무마다 세 가지를 판정하세요 — 반드시 아래 근거에서 관찰되는 것만, 지어내지 말 것:",
            "1. role — 이 담당 업무에서 이 사람의 역할 한 줄.",
            "   근거에 드러난 것만 쓰세요 — 누구에게 받아 무엇을 만들어 누구에게 넘겼는지,",
            "   주도했는지 요청을 받아 처리했는지. 근거가 약하면 '판단 유보'.",
            "2. steps — 일이 실제로 흘러간 **순서**. 시간순 신호와 요청→산출 페어에서 반복되는",
            "   흐름을 읽어 3~7단계로. 각 단계: name(단계명) · desc(무슨 일을 했는지 1문장) ·",
            "   evidence(근거가 된 신호 원문 조각 하나) · cycle(반복 주기: 매일/주 1회/수시 등).",
            "   ★ **다른 담당 업무의 일을 이 흐름에 섞지 마세요.** 한 흐름은 그 업무 안에서만 이어집니다.",
            "   ★★ 다만 한 업무의 산출물이 **같은 과제의 다른 담당 업무**의 입력이 되면, 그 상대 업무명을",
            "      upstream(앞) · downstream(뒤) 에 적으세요. 아래 '### 과제:' 머리말 밑의 업무들끼리만입니다.",
            "      흐름을 합치지는 말고, 이어진다는 사실만 적습니다.",
            "3. 각 단계의 agent — Agentic AI 가 그 단계를 대체·보조할 가능성:",
            "   '상'(정형 반복 — 지금 기술로 자동화 가능) / '중'(보조 가능 — 사람 확인 필요) /",
            "   '하'(판단·협상·책임 — 사람 몫). agent_how 에 구체 방안 1문장",
            "   (무슨 데이터를 입력받아 무엇을 자동으로 하는지).",
            "",
            "summary — 이 담당 업무에서 실제로 한 일 2문장 요약.",
            "",
            "출력은 JSON 하나만 (설명 문장 금지). <...> 자리에 실제 값을 넣으세요:",
            '{"flows": [ {"key": <아래 목록의 "과제 / 담당업무" 를 그대로>, "role": <한 줄>,',
            '   "upstream": <앞 업무명 또는 "">, "downstream": <뒤 업무명 또는 "">,',
            '   "summary": <2문장>, "steps": [ {"order": 1, "name": <단계명>, "desc": <1문장>,',
            '     "evidence": <근거 조각>, "cycle": <주기>, "agent": <상|중|하>,',
            '     "agent_how": <방안 1문장>} ]} ]}',
            "",
        ]
        # 같은 과제의 담당업무를 한 덩어리로 보여 준다 — 묶음이 과제 단위로 짜이므로 여기서도 과제 머리말을
        # 두어야 모델이 '이 업무들은 서로 이어질 수 있다' 를 안다. 요청→산출 페어는 과제 블록에 한 번만.
        _pj_prev = None
        for m in mats:
            _pj = m["model"]
            if _pj != _pj_prev:
                _sib = [x["detail"] for x in mats if x["model"] == _pj]
                lines.append(f"### 과제: {_pj} — 담당 업무 {len(_sib)}개"
                             + (f"  [상위: {m['level1']}]" if m.get("level1") else ""))
                if len(_sib) > 1:
                    lines.append("    (아래 ## 들은 모두 이 과제의 업무입니다 — 서로 이어지면 upstream/downstream 에 적으세요)")
                for e in (m.get("episodes") or []):
                    lines.append(f"    [요청→산출] {e}")
                _pj_prev = _pj
            lines.append(f"## {m['key']}  (신호 {m['signals']}건 · 실측 {m['mm']} MM)")
            if m.get("desc"):
                lines.append(f"[정제 설명] {m['desc']}")
            lines.append("[시간순 신호 표본]")
            lines += m["evidence"]
            lines.append("")
        return "\n".join(lines)
    lines = [
        f"당신은 업무 프로세스 분석가입니다. 아래는 한 엔지니어의 {unit_word}별 실제 활동 흔적입니다",
        "(시간순 raw 신호 표본, 요청→산출 페어, AI 가 정제한 세부업무 설명).",
        "",
        f"{unit_word}마다 세 가지를 판정하세요 — 반드시 아래 근거에서 관찰되는 것만, 지어내지 말 것:",
        f"1. role — 이 {unit_word}에서 이 사람의 역할 한 줄.",
        "   근거에 드러난 것만 쓰세요 — 누구에게 받아 무엇을 만들어 누구에게 넘겼는지,",
        "   주도했는지 요청을 받아 처리했는지. 근거가 약하면 '판단 유보'.",
        "2. steps — 일이 실제로 흘러간 **순서**. 시간순 신호와 요청→산출 페어에서 반복되는",
        "   흐름을 읽어 3~7단계로. 각 단계: name(단계명) · desc(무슨 일을 했는지 1문장) ·",
        "   evidence(근거가 된 신호 원문 조각 하나) · cycle(반복 주기: 매일/주 1회/수시 등).",
        f"   ★ **다른 {unit_word}의 일을 이 흐름에 섞지 마세요.** 한 흐름은 그 안에서만 이어집니다.",
        f"   ★★ 한 {unit_word} 안의 [세부업무]가 **서로 이어지지 않으면 흐름을 나눠** 답하세요.",
        "      같은 key 로 여러 개를 답하고 branch 에 그 흐름 이름(어느 세부업무들인지)을 적습니다.",
        "      나눌지 합칠지는 아래 근거만 보고 정하세요 — 한 일의 산출물이 다음 일의 입력이 되는가,",
        "      요청→산출 페어가 서로 이어지는가, 같은 시기에 번갈아 진행되는가.",
        "      그렇지 않으면 다른 흐름입니다. **억지로 한 줄기로 엮지 마세요.**",
        "      반대로 실제로 이어지는 일을 굳이 쪼개지도 마세요.",
        f"      한 {unit_word}의 흐름은 최대 {MAX_BRANCHES}개까지.",
        "3. 각 단계의 agent — Agentic AI 가 그 단계를 대체·보조할 가능성:",
        "   '상'(정형 반복 — 지금 기술로 자동화 가능) / '중'(보조 가능 — 사람 확인 필요) /",
        "   '하'(판단·협상·책임 — 사람 몫). agent_how 에 구체 방안 1문장",
        "   (무슨 데이터를 입력받아 무엇을 자동으로 하는지).",
        "",
        f"summary — 이 {unit_word}에서 실제로 한 일 2문장 요약.",
        "",
        "출력은 JSON 하나만 (설명 문장 금지). <...> 자리에 실제 값을 넣으세요:",
        # 자리표시자를 <...> 로 둬 **이 예시 자체가 유효한 JSON 이 아니게** 한다 —
        # 회수가 어긋나 우리 프롬프트가 되돌아와도 이것이 답으로 파싱되지 않는다(실측 사고).
        '{"flows": [ {"key": <아래 목록의 머리말 이름을 그대로>, "branch": <흐름 이름 · 하나뿐이면 "">,',
        '   "role": <한 줄>,',
        # LM20 은 3~7단계였다. 상한을 6 으로 줄이면 긴 흐름이 잘려 '생략된' 것처럼 보인다.
        '   "summary": <2문장>, "steps": [ {"order": 1, "name": <단계명>, "desc": <1문장>,',
        '     "evidence": <근거 조각>, "cycle": <주기>, "agent": <상|중|하>,',
        '     "agent_how": <방안 1문장>} ]} ]}',
        "",
    ]
    for m in mats:
        lines.append(f"## {m['key']}  (신호 {m['signals']}건)"
                     + (f"  [상위: {m['level1']}]" if m.get("level1") else ""))
        for e in (m.get("episodes") or []):
            lines.append(f"[요청→산출] {e}")
        if m.get("parts"):
            # 과제 단위일 때 그 안의 세부업무 배분을 알려 준다 — 단계를 나눌 재료가 된다(LM20 과 같은 정보량)
            lines.append("[세부업무] " + " · ".join(f"{n} {v}MM" for n, v in m["parts"]))
        if m.get("desc"):
            lines.append(f"[정제 설명] {m['desc']}")
        if m.get("evidence"):
            lines.append("[시간순 신호 표본]")
        lines += m["evidence"]
        lines.append("")
    return "\n".join(lines)


ECHO_MARK = "출력은 JSON 하나만"


def strip_echo(reply, prompt):
    r"""회수 결과에서 '되돌아온 우리 프롬프트' 를 잘라 낸다.

    Copilot 화면에서 답을 집어 올 때 앵커를 못 찾으면 우리가 보낸 말풍선까지 함께 딸려온다.
    그대로 두면 프롬프트 안의 예시·지시문이 답으로 읽힌다(실측 사고). 프롬프트의 마지막
    긴 줄을 기준으로 그 뒤만 남긴다."""
    if not reply or not prompt:
        return reply
    tail = [ln.strip() for ln in prompt.splitlines() if len(ln.strip()) >= 25]
    for ln in reversed(tail[-6:]):
        i = reply.rfind(ln)
        if i >= 0:
            return reply[i + len(ln):]
    return reply


def looks_like_echo(reply):
    """답이 아니라 우리 프롬프트가 돌아온 것으로 보이는가"""
    return ECHO_MARK in (reply or "")


def rfind_json(reply, want_key):
    """호환 — 정상 파싱 + 코드펜스·따옴표 정규화 + 잘린 JSON 복구까지(core/details.find_json)."""
    return details.find_json(reply, want_key)[0]


AGENT_OK = {"상", "중", "하"}

# 같은 뜻으로 쓰이는 구분자들 — 표기만 다른 것을 한 축으로 모은다
_SEP = {"·": "·", "・": "·", "ㆍ": "·", "‧": "·",
        "（": "(", "）": ")", "－": "-", "–": "-", "—": "-",
        "／": "/", "’": "'", "“": '"', "”": '"'}


def _fold_sep(t):
    return "".join(_SEP.get(ch, ch) for ch in t)


def _norm_model(s, drop_note=False):
    r"""이름 비교 축 — 표기 차이를 걷어 내고 남는 알맹이.

    응답이 '## 광학 설계 / 렌즈 시뮬레이션  (신호 12건)' 처럼 머리말을 옮겨 적거나 공백이 하나
    늘어난 것만으로 통째로 버려져 '파싱 실패' 가 되던 것을 막는다. 구분자(·/・/ㆍ, 전각 괄호,
    각종 대시)도 한 축으로 모은다 — NFKC 만으로는 ㆍ(U+318D)가 엉뚱한 글자로 바뀌므로
    **NFKC 앞뒤로 한 번씩** 접어야 한다(실측).

    drop_note=True 면 꼬리 괄호 주석·꼬리 대시 설명까지 떼어 낸다."""
    t = _fold_sep(str(s or "").strip())
    t = unicodedata.normalize("NFKC", t)
    t = _fold_sep(t)
    t = re.sub(r"^#+\s*", "", t)
    t = re.sub(r"^과제\s*[:：]\s*", "", t)
    t = re.sub(r"\s*[(]\s*신호[^)]*[)]\s*$", "", t)
    if drop_note:
        t = _strip_tails(t)
    return " ".join(t.split()).casefold()


# 꼬리 대시 '설명'만 뗀다 — 대시 양쪽에 공백이 하나도 없는 'LiDAR-2 개발' 같은 이름 속 하이픈이나,
# ' / ' 를 품은 꼬리(담당업무 부분 전체)는 이름이다. 예전 정규식 `[-–—]\s*[^-–—]{1,20}$` 은
# 'LiDAR-2 개발 / 빌드 논의' 를 'lidar' 로 만들어 엉뚱한 단위에 스냅시켰다(F2).
_DASH_TAIL = re.compile(r"(?:\s+[-–—]\s*|\s*[-–—]\s+)[^-–—/]{1,20}$")
_PAREN_TAIL = re.compile(r"\s*[(][^)]*[)]\s*$")


def _strip_tails(t, paren=True):
    """꼬리 대시 설명과(paren=True 면) 꼬리 괄호를 순서와 무관하게 뗀다 — 'X(양산) — 설명' 도 'X'."""
    for _ in range(3):
        u = _DASH_TAIL.sub("", t)
        if paren:
            u = _PAREN_TAIL.sub("", u)
        if u == t:
            break
        t = u
    return t


def _tail_note(s):
    """이름 끝 괄호 꼬리('수광부 해석(양산)' → '양산') — 표기 차이·대시 설명을 걷어낸 뒤. 없으면 ''."""
    t = _fold_sep(unicodedata.normalize("NFKC", _fold_sep(str(s or "").strip())))
    t = re.sub(r"\s*[(]\s*신호[^)]*[)]\s*$", "", t)
    t = _strip_tails(t, paren=False)
    m = re.search(r"[(]([^()]*)[)]\s*$", t)
    return " ".join(m.group(1).split()).casefold() if m else ""


def _uniq_map(keys, fn):
    """{fn(k): k} — 같은 비교 축 값에 재료 키가 2개 이상 걸리면(모호) 그 값은 뺀다.
    '수광부 해석(양산)'/'(선행)' 의 괄호를 뗀 축에서 dict 마지막 항목이 조용히 이겨 응답이
    엉뚱한 단위에 스냅되던 결함(F2) — 모호하면 다음 축으로 넘기고, 끝까지 없으면 버린다."""
    out, dup = {}, set()
    for k in keys:
        v = fn(k)
        if not v:
            continue
        if v in out and out[v] != k:
            dup.add(v)
        else:
            out[v] = k
    for v in dup:
        out.pop(v, None)
    return out


def _resolve_key(raw, keys, low_map, fold_map, norm_map, note_map, ns_map=None, fns_map=None):
    """응답의 key 를 재료 키로 스냅 — 정확 → 소문자 → fold → _norm_model → 공백 제거 →
    괄호·꼬리 제거 → 앞부분 유일 일치 → 담당업무 이름 유일 일치 순. 못 찾으면 ''.
    각 축은 후보가 유일할 때만 인정한다(_uniq_map 으로 만든 맵)."""
    if raw in keys:
        return raw
    hit = low_map.get(raw.lower()) or fold_map.get(fold(raw)) or norm_map.get(_norm_model(raw))
    if hit:
        return hit
    nr = _norm_model(raw)
    # 대시 설명만 뗀 축('X(양산) — 해석 반복' → 'x(양산)', 괄호 꼬리는 남긴다)과 공백 제거 비교
    # ('광학설계/수광부해석(양산)' 처럼 붙여 쓴 응답)
    nd = " ".join(_strip_tails(nr, paren=False).split())
    hit = (norm_map.get(nd) or (ns_map or {}).get(nd.replace(" ", ""))
           or (fns_map or {}).get(fold(raw).replace(" ", "")))
    if hit:
        return hit
    # 꼬리(괄호·대시 설명)를 뗀 축 — 응답이 꼬리를 빠뜨렸을 때. 응답 자신의 괄호 꼬리가 후보의
    # 것과 다르면('(선행)' vs '(양산)') 다른 단위이므로 스냅하지 않는다.
    hit = note_map.get(_norm_model(raw, True))
    if hit and _tail_note(raw) in ("", _tail_note(hit)):
        return hit
    nk = nr.rstrip(". …")
    if len(nk) >= 8:
        # 앞부분 일치는 이름 경계에서만 — 'lidar-2 개발' 이 'lidar-2 개발자 …' 에 걸리지 않게
        cands = [v for k, v in norm_map.items()
                 if k.startswith(nk) and (len(k) == len(nk) or not k[len(nk)].isalnum())]
        if len(cands) == 1:
            return cands[0]
    # '/' 없이 담당업무 이름만 온 경우 — 세부업무 fold 가 딱 하나에만 걸리면 인정
    fr = fold(raw)
    if fr:
        frn = fr.replace(" ", "")
        cands = [k for k, m in keys.items()
                 if fold(m["detail"]) == fr or fold(m["detail"]).replace(" ", "") == frn]
        if len(cands) == 1:
            return cands[0]
    return ""


def _dedupe_flows(flows, unit, log=None):
    """저장 직전 마지막 그물 — 같은 단위가 두 번 들어온 것을 지운다 → (정리된 목록, 버린 것 요약).

    같은 단위가 두 번 생기는 통로는 넷이다: 묶음 사이 재판정 · 지난 결과(kept)와 새 판정 ·
    잘린 답 복구 · 자동 마무리 회차. sanitize_flows 의 seen 은 **한 호출 안에서만** 살아 있어
    이들 사이는 못 막는다(감사 재현).

    남기는 쪽은 단계가 많은 쪽 → 역할·요약이 긴 쪽 → 먼저 온 쪽. **steps 를 합치지는 않는다** —
    두 답의 단계 순서가 다르면 시간순이 깨지고, 근거가 서로 다른 신호를 가리키면 한 카드 안에
    서로 다른 업무가 섞인다. 버린 쪽은 요약만 남겨 사람이 확인할 수 있게 한다."""
    def _sig(f):
        return {details.ukey3(str(x.get("name") or "")) for x in (f.get("steps") or []) if x.get("name")}

    def _rank(f):
        return (len(f.get("steps") or []),
                len(str(f.get("role") or "")) + len(str(f.get("summary") or "")))

    best, order, dupes = {}, [], []
    for f in flows:
        model = str(f.get("model") or "")
        br = fold(str(f.get("branch") or "")) if unit == "과제" else ""
        k = (details.ukey2(model.split(KEY_JOIN)[0]),
             details.ukey3(model.split(KEY_JOIN)[1]) if KEY_JOIN in model else "", br)
        cur = best.get(k)
        if cur is None:
            best[k] = f
            order.append(k)
            continue
        # 과제 단위에서 branch 이름이 다른데 단계가 거의 같으면 같은 흐름을 달리 부른 것이다.
        # 반대로 단계가 많이 다르면 의도된 분기이므로 둘 다 남긴다(그 경우 위에서 키가 갈린다).
        keep, drop = (f, cur) if _rank(f) > _rank(cur) else (cur, f)
        best[k] = keep
        dupes.append({"kept": str(keep.get("model") or ""),
                      "dropped_branch": str(drop.get("branch") or ""),
                      "steps": [len(keep.get("steps") or []), len(drop.get("steps") or [])],
                      "role": str(drop.get("role") or "")[:40],
                      "why": "담당업무 모드 · 같은 단위 재답변" if unit != "과제" else "같은 흐름을 다른 이름으로"})
    if dupes and log:
        for d in dupes[:5]:
            log(f"[flow] 흐름 중복 제거: '{d['kept']}' (단계 {d['steps'][0]}개 유지 · {d['steps'][1]}개 버림)")
    return [best[k] for k in order], dupes


def sanitize_flows(raw_flows, keys, mats_by=None, dropped=None):
    """응답 형태 방어 — 스칼라·null·모르는 키·이상 agent 값을 정규화한다.
    keys: {"과제 / 담당업무": mat}. 정말 모르는 키의 flow 만 버린다(지어낸 단위 방지);
    버린 이름은 dropped 에 담아 사유로 쓸 수 있게 한다."""
    flows = raw_flows if isinstance(raw_flows, list) else []
    keys = keys or {}
    if mats_by is None:
        mats_by = keys
    # 모든 비교 축은 후보가 유일할 때만 쓴다(F2 — 모호한 축 값은 빠진다)
    low_map = _uniq_map(keys, str.lower)
    fold_map = _uniq_map(keys, fold)
    norm_map = _uniq_map(keys, _norm_model)
    note_map = _uniq_map(keys, lambda k: _norm_model(k, True))
    ns_map = _uniq_map(keys, lambda k: _norm_model(k).replace(" ", ""))
    fns_map = _uniq_map(keys, lambda k: fold(k).replace(" ", ""))
    out, seen, n_branch = [], set(), {}
    for f in flows:
        if not isinstance(f, dict):
            continue
        raw_name = str(f.get("key") or f.get("model") or "").strip()
        key = (_resolve_key(raw_name, keys, low_map, fold_map, norm_map, note_map, ns_map, fns_map)
               if raw_name else "")
        if not key:
            if dropped is not None and raw_name:
                dropped.append(raw_name)
            continue
        # 한 과제 안에서 서로 이어지지 않는 일은 흐름(branch)을 나눠 답하게 했다. 예전에는 과제당
        # 하나만 남겨(if key in seen) 무관한 담당업무가 한 타임라인으로 엮였다(제보).
        branch = " ".join(str(f.get("branch") or f.get("stream") or "").split())[:40]
        # 담당업무 단위(기본)에서는 프롬프트가 branch 를 요구하지 않는다 — 모델이 자유롭게 붙인 이름이
        # 공백 하나만 달라도 같은 단위의 재답변이 그대로 통과해 카드가 두 장이 됐다(감사 재현).
        # 그 모드에서는 branch 를 중복 판정에서 아예 뺀다.
        bk = (key, fold(branch) if workflow_unit() == "과제" else "")
        if bk in seen:
            continue
        if n_branch.get(key, 0) >= MAX_BRANCHES:
            continue
        steps_raw = f.get("steps")
        steps_raw = steps_raw if isinstance(steps_raw, list) else []
        steps = []
        for s in steps_raw[:8]:
            if not isinstance(s, dict):
                continue
            ag = str(s.get("agent") or "").strip()
            i = len(steps) + 1                 # 건너뛴 항목이 있어도 번호가 비지 않게
            steps.append({"order": i,
                          "name": str(s.get("name") or "")[:40] or f"단계 {i}",
                          "desc": str(s.get("desc") or "")[:200],
                          "evidence": str(s.get("evidence") or "")[:120],
                          "cycle": str(s.get("cycle") or "")[:20],
                          "agent": ag if ag in AGENT_OK else "중",
                          "agent_how": str(s.get("agent_how") or "")[:200]})
        if not steps:
            if dropped is not None:
                dropped.append(f"{raw_name}(단계 없음)")
            continue
        seen.add(bk)
        n_branch[key] = n_branch.get(key, 0) + 1
        hit = mats_by.get(key) or {}
        # 같은 과제 안의 앞/뒤 업무 — 흐름을 합치지 않고 '이어진다' 는 사실만 남긴다.
        # 상대 이름이 같은 과제의 실제 단위로 풀릴 때만 인정한다(지어낸 이름 방지).
        def _link(v):
            r = str(v or "").strip()
            if not r:
                return ""
            k2 = _resolve_key(r, keys, low_map, fold_map, norm_map, note_map, ns_map, fns_map)
            if not k2 or k2 == key:
                return ""
            a, b = (mats_by.get(k2) or {}), hit
            return k2 if fold(a.get("model", "")) == fold(b.get("model", "")) else ""

        out.append({"model": key, "branch": branch, "level1": hit.get("level1", ""),
                    # 상위 표가 갈린 카드는 화면이 "상위 미분류" 대신 그 사실을 말해야 한다
                    "level1_mix": hit.get("level1_mix") or [],
                    "upstream": _link(f.get("upstream")), "downstream": _link(f.get("downstream")),
                    "project": hit.get("model", ""), "detail": hit.get("detail", ""),
                    "role": str(f.get("role") or "")[:160],
                    "summary": str(f.get("summary") or "")[:400],
                    "steps": steps,
                    # MM 은 실측(mm_rows) — AI 숫자가 아니라 프로그램이 붙인다
                    "mm": {"mm": hit.get("mm", 0.0)},
                    "signals": hit.get("signals", 0)})
    return out


def _chunks(mats, budget=PROMPT_BUDGET, max_units=None):
    r"""단위를 **과제 덩어리**로 묶는다 — 같은 과제의 담당업무가 묶음 경계로 갈리면 연계를 볼 수 없다
    (실측: 광학 설계 8개가 묶음1·2 로 갈렸다). 과제 하나가 예산이나 예상 답 길이를 넘을 때만 그 안에서 쪼갠다.

    두 가지를 함께 막는다:
      · 입력 — 프롬프트 글자 수 ≤ budget. base 는 **그 모드의 머리말**로 잰다. 예전에는 build_prompt([]) 를
        썼는데 빈 목록은 과제 모드로 읽혀 다른 머리말(1,330자)을 재는 바람에 단위당 비용을 989자로 잡았다
        (참값 1,533자) — 예산 가드가 사실상 죽어 있었다(실측).
      · 출력 — 단위 하나당 답이 약 1,100자다. 묶음이 커지면 답이 잘려 salvage 로 떨어지고 단계가 깎인다.
        ANSWER_BUDGET 로 예상 답 길이를 눌러, 단위 수 상한(고정 6)보다 실제에 맞게 막는다."""
    out, cur = [], []
    if not mats:
        return []
    cap = max_units or MAX_UNITS_PER_CHUNK

    # 입력 크기는 **실제 프롬프트 길이**로 잰다. 예전에는 단위 블록 길이를 더했는데, build_prompt 는
    # '### 과제:' 머리말과 요청→산출 페어를 **과제당 한 번만** 넣는데, 예전 계산은 그것을 단위마다
    # 세어 같은 과제 3단위 묶음을 실제 6,596자인데 7,423자로 잡아 예산 7,000 을 넘긴 것처럼 만들었다.
    # 그 과대추정 때문에 들어갈 수 있는 묶음이 둘로 갈렸고 왕복이 두 배가 됐다(감사 실측: 100 → 50묶음).
    def _fits(add):
        n = len(cur) + len(add)
        return (n * ANSWER_PER_UNIT <= ANSWER_BUDGET and n <= cap
                and len(build_prompt(cur + add)) <= budget)

    # 과제별 덩어리 — mats 는 이미 상위 → 과제 → 무게 순으로 정렬돼 있다
    lumps = []
    for m in mats:
        if lumps and lumps[-1][0] == m["model"]:
            lumps[-1][1].append(m)
        else:
            lumps.append((m["model"], [m]))
    for _pj, group in lumps:
        if cur and not _fits(group):
            out.append(cur)
            cur = []
        if _fits(group):
            cur.extend(group)
            continue
        # 과제 하나가 통째로 안 들어간다 — 그 과제 안에서만 쪼갠다(다른 과제와는 섞지 않는다)
        for m in group:
            if cur and not _fits([m]):
                out.append(cur)
                cur = []
            cur.append(m)
        out.append(cur)
        cur = []
    if cur:
        out.append(cur)
    return [c for c in out if c] or [mats]


def _save_json(path, obj):
    details.save_json_atomic(path, obj)


def _load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else None
    except (OSError, ValueError):
        return None


def workflow_unit():
    """워크플로우 한 단위를 무엇으로 볼 것인가 — config.workflowUnit.

    "과제/담당업무"(기본 · LM20+보완2 와 같음): 담당 업무(중위개체)마다 따로 흐름을 만든다.
        보완2 문서: "과제 하나를 한 흐름으로 물어보면 서로 관계 없는 업무가 한 줄로 엮인다."
        잘게 갈라진 세부업무는 흐름을 만들기 **전에** 별칭 맵(규칙·Copilot·정제 결과)으로 먼저 합친다.
    "과제"                                    : 과제 하나를 한 흐름으로(옛 방식 — 무관한 일이 엮인다).

    '너무 세분화' 제보의 진짜 원인은 단위가 아니라 병합 맵이 신호 축에 적용되지 않던 것이었다(main 참고)."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            v = str(json.load(f).get("workflowUnit") or "").strip()
    except (OSError, ValueError, TypeError, AttributeError):
        v = ""
    return "과제" if v.replace(" ", "") in ("과제", "task", "project") else "과제/담당업무"


def _sync_unit():
    """모듈 상수 UNIT 을 지금 설정값으로 맞춘다. 출력 JSON 의 unit 과 캐시 유효성 판정(prev.unit == UNIT)이
    이 값을 보므로, 설정을 바꾸면 지난 흐름 캐시가 저절로 버려진다 — 단위가 달라졌는데 옛 결과를
    되쓰면 화면과 설정이 어긋난다."""
    global UNIT
    UNIT = workflow_unit()
    return UNIT


def _cfg_int(key, default):
    """config.copilotAuto.<key> 정수 — 없거나 이상하면 default."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            v = (json.load(f).get("copilotAuto") or {}).get(key)
        n = int(v)
        return n if n > 0 else int(default)
    except (OSError, ValueError, TypeError, AttributeError):
        return int(default)


def _fail_summary(fails):
    """실패 목록 → (대표 사유, 조치). fatal 이 있으면 그것, 아니면 가장 잦은 사유."""
    if not fails:
        return "", ""
    fatal = next((f for f in fails if f.get("fatal")), None)
    if fatal:
        return str(fatal.get("error") or "왕복 실패"), str(fatal.get("hint") or "")
    top = Counter(str(f.get("error") or "왕복 실패") for f in fails).most_common(1)[0][0]
    hint = next((str(f.get("hint") or "") for f in fails if str(f.get("error") or "왕복 실패") == top), "")
    return top, hint


def main():
    import judge
    _sync_unit()               # 출력 JSON 의 unit·캐시 유효성 판정을 지금 설정에 맞춘다
    d0, d1 = arg("--from"), arg("--to")
    tag = (f"{d0.replace('-', '')}-{d1.replace('-', '')}" if d0 and d1 else latest_tag())
    rep = os.path.join(ROOT, "report")
    if not tag:
        print("[flow] 분석 결과가 없습니다 — 먼저 [분석 실행]")
        print(json.dumps({"ok": False, "error": "no result",
                          "hint": "report\\ 에 분석 결과(mm_meta)가 없습니다 — 먼저 [분석 실행]"}, ensure_ascii=False))
        return 1
    dst = os.path.join(rep, f"workflow_{tag}.json")

    # ① 세부업무 표기 병합 맵 — 규칙 + (--no-merge 아니면) Copilot. 실패해도 워크플로우는 돈다.
    sender = None if "--no-merge" in sys.argv else judge.copilot_send
    amap, n_rule, n_ai, n_ref = {}, 0, 0, 0
    pmap, n_p_rule, n_p_ev, p_note = {}, 0, 0, {"pairs": [], "rejects": []}
    try:
        # ★ 병합 맵은 **신호 축(원본 mm_rows 이름)** 으로 만든다. 예전에는 read_rows 기본(정제본 우선)으로
        #   만들어 별칭 키가 정제본 이름이었고, 원본 이름을 가진 신호에는 하나도 적용되지 않았다
        #   (규칙 병합 0건 실측). LM20 refine 은 Level 3 를 유지했지만 LM22 refine 은 합치고 바꾼다.
        rows_plain, _pf = details.read_rows(tag, rep, plain=True)
        # ★ 과제(중위) 병합을 **세부업무 병합보다 먼저** 돌린다. details._detail_pools 가 raw Level 2 를
        #   파티션 키로 쓰므로, 과제가 '광학 설계'/'광학설계' 로 갈린 채 두면 같은 세부업무 집합이 여러
        #   풀로 쪼개져 세부 병합이 반쪽이 된다(감사 합성 실측: 변형 4개 → 풀 4개).
        try:
            import projmap as _pm
            _pinned = [p.get("name") for p in (_pm.load_user_projects(ROOT) or []) if p.get("name")]
        except Exception:  # noqa: BLE001 - 지정 과제 목록이 없어도 병합은 돈다
            _pinned = []
        pmap, n_p_rule, n_p_ev, p_note = details.project_merge_map(
            rows_plain or [], details.read_signals(tag, rep), refmap=_refine_orig(tag, rep),
            pinned=_pinned, log=lambda m: print(f"[flow]{m}"))
        if pmap:
            details.apply_project_map(rows_plain, None, pmap)     # 아래 세부 병합이 합쳐진 과제 축을 보게
        amap, n_rule, n_ai = details.detail_merge_map(tag, sender, rows=rows_plain or None,
                                                      log=lambda m: print(f"[flow]{m}"))
        # refine 이 '같은 일' 로 합친 원본 담당업무들도 별칭으로 흡수한다 — 정제가 이미 내린 동일성 판정을
        # 워크플로우 단위에도 적용해야 조각이 합쳐진다(보완2 시절엔 refine 이 이름을 안 바꿔 저절로 그랬다).
        n_ref = _seed_from_refine(amap, tag, rep, rows_plain or [])
        if n_ref:
            amap = details._flatten3_map(amap)
            try:
                details.save_detail_aliases(amap)
            except OSError:
                pass
        if n_rule or n_ai or n_ref:
            print(f"[flow] 세부업무 유사 병합: 규칙 {n_rule}건 · Copilot {n_ai}건 · 정제 결과 {n_ref}건 → "
                  "config\\detail_aliases.json (한 줄 지우면 그 병합만 원복)")
        elif amap:
            print(f"[flow] 세부업무 병합 맵 {len(amap)}건 적용(캐시)")
        # 캐시에 남은 (옛 과제, 이름) 키는 과제가 합쳐지면 고아가 된다 — 대표 축으로 접는다.
        if pmap and amap:
            amap = details.remap_detail_scope(amap, pmap)
        if n_p_rule or n_p_ev:
            print(f"[flow] 과제 표기 병합: 규칙 {n_p_rule}건 · 증거 {n_p_ev}건 · 거부 "
                  f"{len(p_note.get('rejects') or [])}건 → config\\project_aliases.json")
            for pr in (p_note.get("pairs") or [])[:6]:
                print(f"[flow]   '{pr['from']}' → '{pr['to']}'  ({pr['why']} · {pr['mm']:.2f} MM · 신호 {pr['signals']}건)")
            for rj in (p_note.get("rejects") or [])[:4]:
                print(f"[flow]   [거부] '{rj['a']}' ↔ '{rj['b']}' — {rj['why']}")
            print("[flow]   (한 줄 지우면 그 병합만 원복 · 규칙이 다시 합치면 never 에 쌍을 적으세요)")
        elif pmap:
            print(f"[flow] 과제 표기 병합 맵 {len(pmap)}건 적용(캐시)")
    except Exception as e:  # noqa: BLE001 - 병합 실패가 워크플로우를 막지 않게
        print(f"[flow] (세부업무 병합 건너뜀: {type(e).__name__}: {str(e)[:80]})")
    merge_fail = dict(getattr(details, "LAST_FAIL", {}) or {})

    # ② 재료
    L1_PIN.update(load_l1_pin(ROOT))
    mats, basis, err = gather(rep, tag, amap, pmap)
    if not mats:
        if not basis:
            # 신호 파일 자체가 없다/열이 없다 — 이것은 결과 없음이 아니라 전제가 깨진 것
            print(f"[flow] {err}")
            print(json.dumps({"ok": False, "error": err,
                              "hint": f"report\\signals_{tag}.csv 를 만드는 [분석 실행]을 그 기간으로 다시 돌리세요"},
                             ensure_ascii=False))
            return 1
        # 신호는 있는데 흐름이라 할 단위가 없다 — 실패가 아니라 '결과 없음'. 옛 판은 rc1 로 재시도까지 했다.
        out = {"ok": True, "tag": tag, "generated": time.strftime("%Y-%m-%d %H:%M"), "model_name": "",
               "unit": UNIT, "basis": basis, "flows": [], "chunks": 0, "failed_chunks": 0, "missing": [],
               "dropped": [], "merge": {"rule": n_rule, "ai": n_ai, "aliases": len(amap or {})},
               "rows_units": 0, "empty_reason": err}
        _save_json(dst, out)
        print(f"[flow] 워크플로우를 만들 단위가 없습니다 — {err} (실패 아님: 더 긴 기간을 분석하거나 신호가 쌓인 뒤 다시)")
        print(json.dumps({"ok": True, "flows": 0, "units": 0, "chunks": 0, "failed_chunks": 0,
                          "basis": basis, "empty_reason": err, "note": err}, ensure_ascii=False))
        return 0
    if basis == "규칙":
        print("[flow] 판정(model) 열이 없어 규칙 분류(project/activity) 축으로 만듭니다 — "
              "과제명이 AI 가 정리한 상위개체가 아니라 품질이 낮습니다(basis: 규칙)")
    keys = {m["key"]: m for m in mats}
    if THIN:
        # 어떤 담당업무가 왜 빠졌는지 화면에 남긴다 — 예전에는 조용히 사라져 '워크플로우가 너무 적다' 로 읽혔다
        print(f"[flow] 신호 {MIN_SIGNALS}건 미만이라 흐름을 만들지 않은 담당 업무 {len(THIN)}개: "
              + ", ".join(f"{md} / {dt}({n})" for md, dt, n in THIN[:6])
              + (" …" if len(THIN) > 6 else "")
              + " — 별칭 병합이 더 묶이면 다음 실행에 합쳐져 들어옵니다")

    # 세부 병합 왕복이 '사람이 손대야 하는' 이유로 죽었으면 흐름 왕복도 같은 이유로 죽는다 — 헛되이 보내지 않는다
    if merge_fail.get("fatal") and sender is not None:
        why, how = str(merge_fail.get("error") or "왕복 실패"), str(merge_fail.get("hint") or "")
        print(f"[flow] Copilot 왕복이 막혀 있습니다({why}) — {how}")
        print(json.dumps({"ok": False, "error": why, "hint": how or "조치 후 다시 실행"}, ensure_ascii=False))
        return 1

    # 이어서 판정 — 같은 기간·같은 단위 축의 지난 결과가 있으면 그 단위는 두고 빠진 단위만 보낸다
    prev = None if "--redo" in sys.argv else _load_json(dst)
    kept = []
    if prev and prev.get("tag") == tag and prev.get("unit") == UNIT and isinstance(prev.get("flows"), list):
        for f in prev["flows"]:
            # 단계가 MIN_STEPS 미만인 흐름은 잘린 답에서 온 것일 수 있다 — 이어받지 말고 다시 묻는다.
            if (not isinstance(f, dict) or f.get("model") not in keys
                    or len(f.get("steps") or []) < MIN_STEPS):
                continue
            hit = keys[f["model"]]
            # level1 도 함께 갱신한다 — 예전에는 이어받은 흐름이 **옛 상위**를 그대로 들고 와,
            # 같은 과제의 카드가 상위 머리말 여러 개로 찢어졌다(감사 재현). 새로 판정한 흐름은
            # 이번 mats 의 level1 을 쓰므로 두 축이 어긋난 것이다.
            f = dict(f, project=hit["model"], detail=hit["detail"], mm={"mm": hit["mm"]},
                     signals=hit["signals"], level1=hit.get("level1", ""))
            kept.append(f)
        # 한 과제가 여러 흐름(branch)을 가질 수 있으므로 '흐름 수' 가 아니라 '끝난 과제 수' 로 본다.
        # 그러지 않으면 분기가 하나만 생겨도 len(kept) > len(keys) 가 되어 다 끝난 줄 알고 전부 다시 돌린다.
        if len({f["model"] for f in kept}) >= len(keys):
            kept = []                            # 다 끝난 결과 — 처음부터 다시(재분석)
    done_keys = {f["model"] for f in kept}
    todo = [m for m in mats if m["key"] not in done_keys]
    if kept:
        print(f"[flow] 지난 실행이 {len(kept)}/{len(keys)}개 업무를 끝냈습니다 — 남은 {len(todo)}개만 이어서 보냅니다"
              "(처음부터 하려면 --redo)")

    # ③ 묶음 왕복 — 부분 실패는 계속
    try:
        budget = max(1500, int(arg("--budget", PROMPT_BUDGET)))    # 튜닝·테스트용 묶음 예산
    except ValueError:
        budget = PROMPT_BUDGET
    try:
        max_chunks = max(1, int(arg("--max-chunks", _cfg_int("flowMaxChunks", MAX_CHUNKS))))
    except ValueError:
        max_chunks = MAX_CHUNKS
    # 전체 시간 예산 — '한 번에 다 끝내되 영원히 돌지는 않게'. 0 이면 끝까지 간다.
    try:
        budget_min = max(0.0, float(arg("--budget-min", _cfg_int("flowBudgetMin", BUDGET_MIN))))
    except ValueError:
        budget_min = float(BUDGET_MIN)
    t_start = time.monotonic()
    deadline = (t_start + budget_min * 60) if budget_min else None

    def over_budget():
        return deadline is not None and time.monotonic() > deadline

    def elapsed_min():
        return (time.monotonic() - t_start) / 60
    chunks = _chunks(todo, budget, _cfg_int("flowUnitsPerChunk", MAX_UNITS_PER_CHUNK))
    if len(chunks) > max_chunks:
        print(f"[flow] 묶음이 {len(chunks)}개로 상한({max_chunks})을 넘었습니다 — 앞 {max_chunks}묶음만 보냅니다. "
              f"남은 {sum(len(c) for c in chunks[max_chunks:])}개 업무는 다음 실행이 이어서 판정합니다 "
              "(config.flowMaxChunks 로 상한을 올릴 수 있습니다)")
        chunks = chunks[:max_chunks]
    print(f"[flow] 담당 업무 {len(todo)}개 워크플로우 왕복 ({len(chunks)}회로 나눠 보냄 — "
          f"한 흐름이 다른 업무로 넘어가지 않게 업무 단위로 물어봅니다 · 같은 채팅에서 이어서{_chat_note()})")
    dropped, flows, fails = [], list(kept), []
    model_name = str((prev or {}).get("model_name") or "") if kept else ""
    failed, salvaged, consec, stopped, n_sent = 0, 0, 0, "", 0

    def ask(part, name):
        nonlocal model_name, n_sent
        n_sent += 1
        # fresh=None — 묶음을 같은 채팅에서 이어 보낸다(첫 왕복·실패 뒤·chatTurns 마다만 새 채팅)
        o, info = details.ask_json(judge.copilot_send, build_prompt(part), f"{tag}-{name}", "flow",
                                   "flows", fresh=None)
        if not info.get("ok"):
            return [], info
        model_name = model_name or str(info.get("model") or "")
        # 인정 범위 = 이 묶음의 단위 + **같은 과제의 다른 단위**. 예전에는 묶음 키만 인정해,
        # 같은 채팅으로 문맥이 이어져도 앞·뒤 묶음의 업무를 언급한 답을 통째로 버렸다
        # (실측: dropped 8·15건이 전부 유효한 단위 이름이었다). 보완2 는 전체 keys 로 살렸다.
        # 다른 과제 이름은 계속 버린다(지어낸 단위 방지). 이미 판정된 키는 아래에서 걸러 중복을 막는다.
        _pjs = {fold(m["model"]) for m in part}
        _allow = {k: v for k, v in keys.items() if fold(v["model"]) in _pjs}
        _allow.update({m["key"]: m for m in part})
        got = sanitize_flows(o.get("flows"), _allow, keys, dropped)
        _have = {f["model"] for f in flows}
        got = [g for g in got if g["model"] not in _have]      # 앞 묶음에서 이미 판정한 것은 덮지 않는다
        # 잘린 답(salvage)의 마지막 흐름은 2~3단계로 깎여 온다. 그것을 '완료' 로 저장하면 캐시가
        # 영구 보존해 다시 묻지 않는다(실측) — 얕은 흐름은 이번 답에서 빼고 미판정으로 남겨 재질문한다.
        if info.get("how") == "salvaged" and got:
            _thin = [g for g in got if len(g.get("steps") or []) < MIN_STEPS]
            if _thin and len(_thin) < len(got):
                got = [g for g in got if len(g.get("steps") or []) >= MIN_STEPS]
        if not got:
            why = ("응답이 잘려 건질 흐름이 없음" if info.get("how") == "salvaged" else
                   ("응답의 업무명이 분석된 단위와 달라 전부 버림: " + ", ".join(dropped[-3:]) if dropped
                    else "응답에 flows 가 없거나 형식이 다름"))
            # 형식을 틀린 그 채팅에 재질문을 그대로 이어 붙이면 같은 형식으로 또 답한다 —
            # judge 에 알려 다음 왕복을 새 채팅에서 시작하게 한다(judge·refine 은 이미 그렇게 한다).
            try:
                judge.note_bad_reply()
            except Exception:  # noqa: BLE001 - 알림 실패가 판정을 막지 않게
                pass
            return [], {"ok": False, "kind": "parse", "error": why[:120], "fatal": False, "phase": "parse",
                        "hint": "묶음을 나눠 다시 묻습니다 — 반복되면 report\\judge_flow_*.md 의 답을 확인"}
        return got, info

    _order = {m["key"]: i for i, m in enumerate(mats)}

    def write_out():
        # 잘린 답 복구·적응 분할·자동 마무리를 거치면 판정 순서가 뒤섞여, 같은 과제가 화면에서 두 덩어리로
        # 갈라져 보였다(제보의 '연계되는 업무가 분할'). 저장 직전에 재료 순서(상위 → 과제 → 무게)로 되돌린다.
        flows[:], _dupes = _dedupe_flows(flows, UNIT, log=print)
        flows.sort(key=lambda f: _order.get(f.get("model"), 10 ** 6))
        # 화면·분석리포트가 '같은 과제' 를 묶는 키. 예전에는 원시 문자열로 비교해, 정렬은 fold 축인데
        # 머리말은 표기가 조금만 달라도 따로 서고 같은 과제 머리말이 두 번 나왔다(감사 재현).
        # 정렬과 같은 축을 그대로 실어 보내 둘이 어긋날 수 없게 한다.
        for _f in flows:
            _f["pjkey"] = fold(str(_f.get("project") or _f.get("model") or "").split(KEY_JOIN)[0])
        done = {f["model"] for f in flows}
        missing = [k for k in keys if k not in done]
        why, how = _fail_summary(fails) if (missing or failed) else ("", "")
        out = {"ok": True, "tag": tag, "generated": time.strftime("%Y-%m-%d %H:%M"),
               "model_name": model_name, "unit": UNIT, "basis": basis, "flows": flows,
               "chunks": len(chunks), "failed_chunks": failed, "salvaged_chunks": salvaged, "roundtrips": n_sent,
               # 왜 어떤 단위가 비었는지 나중에도 알 수 있게 남긴다
               # 신호가 얕아 흐름을 만들지 않은 업무 — 예전에는 콘솔에만 찍혀 화면에서 통째로 사라졌다.
               # 사용자에게는 '내 일이 없어졌다' 로 보인다(감사 지적). 왕복은 늘지 않는다.
               # 상위(업무 성격) 표가 갈린 과제 — 억지로 하나를 찍지 않고 여기에 남긴다.
               # 이 목록이 곧 '재배치가 필요한 것' 이다(과병합 의심 또는 상위 판정 불일치).
               "level1_mixed": [{"model": m["model"], "detail": m["detail"], "votes": m["level1_mix"]}
                                for m in mats if m.get("level1_mix")][:100],
               "thin": [{"project": md, "detail": dt, "signals": n} for md, dt, n in THIN[:200]],
               "thin_count": len(THIN),
               "missing": missing[:200], "missing_count": len(missing), "dropped": dropped[:20],
               "partial": bool(missing),
               # 다시 돌리면 남은 것이 채워지는가 — 시간 예산·묶음 상한·치명 중단으로 끊긴 경우만 참이다.
               # 마무리 회차가 '더 못 늘려서' 멈춘 것이면 다시 눌러도 같으므로 화면이 헛수고를 권하지 않게 한다.
               "resumable": bool(missing) and bool(stopped),
               "note": ("" if not missing else
                        f"{len(missing)}개 업무 미판정 — "
                        + (stopped or "자동 마무리가 더 늘리지 못했습니다(신호가 얕거나 응답이 그 이름을 "
                                      "돌려주지 않는 단위) — 다시 실행해도 같을 수 있습니다")),
               "last_error": ({"error": why, "hint": how} if why else {}),
               "merge": {"rule": n_rule, "ai": n_ai, "aliases": len(amap or {})},
               # 과제(중위) 표기 병합과 흐름 중복 제거의 내역 — 무엇을 왜 합쳤는지 사람이 보고 되돌릴 수 있게.
               # 별도 report 파일을 만들지 않는다(만들면 배포·취합 목록 네 곳을 한 세트로 고쳐야 한다).
               "merge2": {"rule": n_p_rule, "evidence": n_p_ev, "aliases": len(pmap or {}),
                          "rejected": len(p_note.get("rejects") or []), "dupes": len(_dupes),
                          "pairs": (p_note.get("pairs") or [])[:50],
                          "rejects": (p_note.get("rejects") or [])[:30],
                          "flow_dupes": _dupes[:30]},
               "rows_units": len(mats)}
        _save_json(dst, out)
        return out

    for ci, part in enumerate(chunks, 1):
        if over_budget():
            stopped = (f"시간 예산 {budget_min}분을 넘겨 남은 {len(chunks) - ci + 1}묶음을 보내지 않았습니다 — "
                       "다시 실행하면 남은 업무만 이어서 판정합니다(config.flowBudgetMin 으로 조절)")
            print(f"[flow] {stopped}")
            break
        progress("워크플로우 분석", ci - 1, len(chunks))
        got, info = ask(part, f"wf{ci}")
        if info.get("ok"):
            flows.extend(got)
            consec = 0
            print(f"[flow] {ci}/{len(chunks)} — 업무 {len(part)}개 중 {len(got)}개 판정")
            if info.get("how") == "salvaged":
                salvaged += 1
                # 답이 길어 잘렸다 — 빠진 단위만 작은 묶음으로 한 번 더 묻는다(답이 짧아져 잘리지 않는다)
                left = [m for m in part if m["key"] not in {f["model"] for f in got}]
                print(f"[flow] {ci}/{len(chunks)} 응답이 잘려 앞부분만 복구했습니다 — 빠진 {len(left)}개를 다시 묻습니다")
                if left:
                    got2, info2 = ask(left, f"wf{ci}-r")
                    if info2.get("ok"):
                        flows.extend(got2)
                        print(f"[flow] {ci}/{len(chunks)} (재질문) — 업무 {len(left)}개 중 {len(got2)}개 판정")
                    else:
                        fails.append(info2)
                        if info2.get("fatal"):
                            stopped = f"{info2.get('error', '')} — {info2.get('hint', '')}".strip(" —")
                            failed += len(chunks) - ci
                            write_out()
                            break
            write_out()
            continue
        fails.append(info)
        print(f"[flow] {ci}/{len(chunks)} 실패: {info.get('error', '')[:80]}"
              + (f" — {info.get('hint', '')[:100]}" if info.get("hint") else "")
              + f" (report\\judge_flow_{tag}-wf{ci}.md)")
        if info.get("fatal"):
            stopped = f"{info.get('error', '')} — {info.get('hint', '')}".strip(" —")
            failed += len(chunks) - ci + 1
            print(f"[flow] 사람이 손대야 풀리는 상태라 남은 {len(chunks) - ci}묶음은 보내지 않습니다")
            break
        # 적응 분할 — 답이 없거나 잘린 묶음은 반으로 나눠 한 번 더
        if len(part) >= 2 and str(info.get("phase") or "") in ("parse", "no_reply", "copilot_error", "", "timeout"):
            half = (len(part) + 1) // 2
            halves = [h for h in (part[:half], part[half:]) if h]
            ok_half = 0
            print(f"[flow] {ci}/{len(chunks)} 묶음을 {len(halves)}개로 나눠 다시 묻습니다(적응 분할)")
            for hi, sub in enumerate(halves, 1):
                got2, info2 = ask(sub, f"wf{ci}-{hi}")
                if info2.get("ok"):
                    ok_half += 1
                    if info2.get("how") == "salvaged":
                        salvaged += 1
                    flows.extend(got2)
                    print(f"[flow] {ci}/{len(chunks)} (분할 {hi}/{len(halves)}) — 업무 {len(sub)}개 중 {len(got2)}개 판정")
                else:
                    fails.append(info2)
                    print(f"[flow] {ci}/{len(chunks)} 분할 {hi}/{len(halves)} 실패: {info2.get('error', '')[:80]}")
                    if info2.get("fatal"):
                        stopped = f"{info2.get('error', '')} — {info2.get('hint', '')}".strip(" —")
                        break
            if ok_half:
                consec = 0
                if ok_half < len(halves):
                    failed += 1
                write_out()
                if stopped:
                    failed += len(chunks) - ci
                    break
                continue
            if stopped:
                failed += len(chunks) - ci + 1
                break
        failed += 1
        consec += 1
        if consec >= MAX_CONSEC_FAIL and ci < len(chunks):
            stopped = (f"{consec}묶음 연속 실패({info.get('error', '')[:40]}) — "
                       "Copilot 상태를 확인한 뒤 [재분석]으로 이어서")
            failed += len(chunks) - ci
            print(f"[flow] {consec}묶음 연속 실패 — 남은 {len(chunks) - ci}묶음은 보내지 않습니다 "
                  "(잠시 뒤 재실행하면 남은 업무만 이어서 판정합니다)")
            break
    # ③-2 미판정 자동 마무리 — 사람이 [이어서 분석]을 누르지 않아도 남은 단위를 **끝까지** 마저 묻는다.
    # 묶음이 통째로 실패했거나 답에서 빠진 단위가 남는 일이 흔하다(응답 잘림·이름 불일치).
    # 예전에는 2회차 고정이라 그래도 남으면 사람이 다시 눌러야 했다(제보) — 이제 '진전이 있는 한' 계속하고,
    # 한 회차에 하나도 못 늘렸거나 시간 예산을 넘기면 멈춘다. FINISH_ROUNDS 는 폭주를 막는 상한일 뿐이다.
    # 사람이 손대야 풀리는 상태(stopped)면 헛되이 보내지 않는다.
    if not stopped:
        for rnd in range(1, FINISH_ROUNDS + 1):
            left = [m for m in mats if m["key"] not in {f["model"] for f in flows}]
            if not left:
                break
            if over_budget():
                stopped = (f"시간 예산 {budget_min}분을 넘겨 미판정 {len(left)}개를 남겼습니다 — "
                           "다시 실행하면 남은 업무만 이어서 판정합니다(config.flowBudgetMin 으로 조절)")
                print(f"[flow] {stopped}")
                break
            # 남은 것은 작게 나눠 묻는다 — 한 번에 몰아 물으면 답이 잘려 또 빠진다
            sub_chunks = _chunks(left, budget, max(1, min(3, _cfg_int("flowUnitsPerChunk", MAX_UNITS_PER_CHUNK))))
            print(f"[flow] 미판정 {len(left)}개를 자동으로 마저 판정합니다 "
                  f"({rnd}회차 · {len(sub_chunks)}묶음 · 경과 {elapsed_min():.0f}분)")
            before = len(flows)
            for si, sub in enumerate(sub_chunks, 1):
                if over_budget():
                    break
                got3, info3 = ask(sub, f"wf-fin{rnd}-{si}")
                if info3.get("ok"):
                    flows.extend(got3)
                    print(f"[flow] 마무리 {rnd}-{si} — 업무 {len(sub)}개 중 {len(got3)}개 판정")
                else:
                    fails.append(info3)
                    print(f"[flow] 마무리 {rnd}-{si} 실패: {info3.get('error', '')[:80]}")
                    if info3.get("fatal"):
                        stopped = f"{info3.get('error', '')} — {info3.get('hint', '')}".strip(" —")
                        break
                write_out()
            if stopped or len(flows) == before:
                # 한 회차를 다 돌았는데 하나도 못 늘렸으면 더 보내도 같은 결과다
                if not stopped and len(flows) == before:
                    print(f"[flow] 마무리 {rnd}회차에서 더 늘지 않아 멈춥니다 — "
                          f"남은 {len(left)}개는 신호가 얕거나 이름이 응답과 맞지 않는 단위입니다")
                break
        else:
            _lo = [m for m in mats if m["key"] not in {f["model"] for f in flows}]
            if _lo:
                print(f"[flow] 마무리 상한 {FINISH_ROUNDS}회차를 다 썼는데 {len(_lo)}개가 남았습니다")
    progress("워크플로우 분석", len(chunks), len(chunks))

    # ④ 결과 — 없으면 기존 workflow_<tag>.json 보존
    if not flows:
        why, how = _fail_summary(fails)
        if not why:
            why = "파싱 실패"
            how = ("응답의 업무명이 분석된 단위와 달라 전부 버렸습니다: " + ", ".join(dropped[:8])
                   if dropped else "응답에 flows 가 없거나 형식이 달랐습니다")
        print(f"[flow] 만들지 못했습니다 — {why} — {how}")
        print(json.dumps({"ok": False, "error": why,
                          "hint": (how + " · " if how else "") + f"{failed}/{len(chunks)}개 묶음 실패 — 기존 결과는 그대로",
                          "chunks": len(chunks), "failed_chunks": failed}, ensure_ascii=False))
        return 1
    if dropped:
        print(f"[flow] 목록에 없는 업무명 {len(dropped)}개는 건너뜀: {', '.join(dropped[:3])}")

    out = write_out()
    for fl in flows:
        print(f"   {fl['model']}: 역할={fl['role'][:40]} · 단계 {len(fl['steps'])}개 · "
              f"Agent 상 {sum(1 for s in fl['steps'] if s['agent'] == '상')}건 · {fl['mm']['mm']} MM")
    if out["missing_count"]:
        print(f"[flow] [!] 업무 {len(flows)}/{len(mats)}개만 판정했습니다 — {out['note']}")
    print(f"[flow] → {dst}")
    print(json.dumps({"ok": True, "flows": len(flows), "units": len(mats), "chunks": len(chunks),
                      "failed_chunks": failed, "salvaged_chunks": salvaged, "basis": basis,
                      "missing": out["missing_count"], "partial": out["partial"], "note": out["note"],
                      **({"hint": out["note"]} if out["missing_count"] else {}),
                      **({"last_error": out["last_error"]} if out["last_error"] else {}),
                      "merge": {"rule": n_rule, "ai": n_ai}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
