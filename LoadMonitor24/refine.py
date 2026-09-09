# -*- coding: utf-8 -*-
"""
refine.py — AI 정제: 추출된 업무 항목을 Copilot이 '원문 근거를 읽고' 다듬는다.

규칙으로 못 하는 것만 AI에게 맡긴다:
  ① 같은 업무가 토큰별로 쪼개진 행 병합   ② 프로젝트명 정규화(실제 과제명으로)
  ③ Level 1 부여                        ④ 상세설명 한 줄 작성 (고유명사 포함)
비중(share)은 규칙이 계산한 값을 유지·재정규화한다 — AI가 총량을 바꾸지 못하게.

  python refine.py --from 2026-05-19 --to 2026-08-17 [--chunk 20]

청크·한도(LM22 S1):
  · 청크 20항목이지만 프롬프트는 **글자 예산(PROMPT_BUDGET 8,400)** 안에서 만든다 — 근거 슬라이스 상한을
    고정 9,000자로 두던 예전에는 20항목이 9,700~10,800자가 되어 드라이버가 매번 2조각으로 나눠 보냈다(실측).
  · 오버레이: 다음 청크 앞에 앞 청크 끝 3항목(600자 이내)을 '겹침' 표시로 다시 보인다 — 청크 경계에서 갈린
    같은 업무를 합칠 수 있게. 겹침 항목이 이번 청크의 새 항목과 함께 merge 되면 앞 청크의 그룹과 **이어
    붙인다**(union). 겹침 항목만으로 된 출력은 무시(앞 청크 결과 유지).
  · 응답 줄이기: 키 축약(m/l1/l2/l3/a/d/w — 옛 긴 키도 받는다) + 상세설명 90자 이내.
  · 적응 분할: 잘린 JSON 은 마지막 완전한 항목까지 복구하고 빠진 항목만 다시 묻는다. JSON 이 없으면
    청크를 반으로(최소 5항목·깊이 2) 나눠 재시도. 부분 성공은 그대로 쓰고 나머지는 원본 유지.
  · 마지막 줄에 {"ok":…,"chunks","failed_chunks","roundtrips","repaired","retries","bad_rows"} JSON 을 남긴다.
  · 병합 행의 제품·유형·Level 2/3 다수결은 결정적이다(_majority — 동률이면 비중 큰 원본 행의 값). 정제 행 → 원본
    (Level 2, Level 3) 매핑을 report\\refine_map_<tag>.json 에 남겨 UI 오할당 제외가 병합 행의 신호를 전부 찾는다.
  · mm_rows 의 share·mm·활동일수 가 빈칸·비숫자(엑셀 재저장·손편집)여도 죽지 않는다 — 0 으로 두고 행 수를 로그·JSON 에 남긴다.
"""
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
if ROOT not in sys.path:
    # 내장 파이썬(python\python.exe)은 ._pth 때문에 isolated 모드로 뜨고, 스크립트 폴더가
    # sys.path 에 들어가지 않는다. 그러면 아래 `from judge import` 가 임포트 단계에서
    # 죽어 **AI 정제만 단독으로** 실패한다(파이썬이 설치된 PC 에서는 안 보이는 결함).
    # agentic.py·retag.py·team_refine.py·ui/app.py 는 모두 ROOT 를 넣는다 — 여기만 빠져 있었다.
    sys.path.insert(0, ROOT)
from details import ukey2  # noqa: E402  - judge·flow 와 같은 과제 신원 축
from details import snap1  # noqa: E402  - 상위(Level 1)를 4개 고정 범주로 스냅
from progress import progress  # noqa: E402
if __name__ == "__main__":      # import 시엔 건드리지 않는다 — 임포트한 쪽의 stdout 이
    # 교체·GC 되면서 버퍼가 닫혀 이후 출력이 전부 죽는다(다른 모듈과 같은 관례)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
NO_WIN = 0x08000000
_DEC = json.JSONDecoder()


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


# Copilot 왕복은 judge.copilot_send 하나로 통일한다(LM22) — 드라이버의 긴 프롬프트 분할·
# [[전송끝]] 서약·왕복 예산(조각 수 반영)이 정제에도 그대로 적용되고, 보완 도구·회귀
# 테스트가 judge.copilot_send 만 바꿔치기하면 정제까지 모의 sender 로 돈다.
try:
    import judge as _judge  # noqa: E402
    chunk_default = _judge.chunk_default
    PROMPT_BUDGET = _judge.PROMPT_BUDGET
except ImportError:                      # judge 를 못 읽어도 정제 자체는 돌아야 한다
    _judge = None
    PROMPT_BUDGET = 8400

    def chunk_default(key, default):
        try:
            return int(arg("--chunk", "") or 0) or int(default)
        except ValueError:
            return int(default)

OV_N = 3                 # 오버레이 항목 수(앞 청크 끝)
OV_CHARS = 600           # 오버레이 항목 줄 합 상한
OV_EV_LINES = 2          # 오버레이 항목에 붙이는 근거 줄 수(참고용이라 짧게)
MIN_SPLIT = 5            # 적응 분할 최소 항목
MAX_SPLIT_DEPTH = 2      # 20 → 10 → 5
MIN_RETRY_ITEMS = 3      # 부분 성공 뒤 빠진 항목이 이 수 이상이면 그 항목만 재왕복
DETAIL_MAX = 90          # 상세설명 상한(프롬프트 지시 + 코드 절단)
FAIL_STOP_RETRY = 3      # 연속 실패 청크가 이만큼이면 적응 재시도를 끈다(공회전 방지)


def copilot_send(prompt_text, tag, name, fresh=None):
    """왕복 1회 — 호출 시점의 judge.copilot_send 를 쓴다(보완 도구·회귀 테스트가 그 이름을
    모의 sender 로 바꿔치기해도 정제까지 닿는다). 옛 3인자 sender(prompt, tag, name) 도
    받아들인다 — fresh 를 못 받으면 빼고 부른다."""
    if _judge is not None:
        fn = getattr(_judge, "copilot_send", None)
        if callable(fn):
            try:
                import inspect
                ps = inspect.signature(fn).parameters
                takes_fresh = "fresh" in ps or any(p.kind == p.VAR_KEYWORD for p in ps.values())
            except (TypeError, ValueError):
                takes_fresh = True
            return fn(prompt_text, tag, name, fresh=fresh) if takes_fresh else fn(prompt_text, tag, name)
    return _send_via_driver(prompt_text, tag, name, fresh=fresh)


def _send_via_driver(prompt_text, tag, name, fresh=None):
    """예비 경로 — 드라이버 직접 호출(judge 부재 시에만). 분할·서약은 드라이버가 처리."""
    pf = os.path.join(ROOT, "report", f"judge_{name}_{tag}.md")
    try:
        os.makedirs(os.path.dirname(pf), exist_ok=True)
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prompt_text)
        cmd = [sys.executable, os.path.join(ROOT, "tools", "copilot_auto.py"), "--send", pf]
        if fresh:
            cmd.append("--fresh")
        budget = max(900.0, 300.0 * 3 + 180) * (len(prompt_text or "") // 8000 + 1)
        out = subprocess.run(cmd, capture_output=True, timeout=budget, cwd=ROOT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
        res = json.loads((out.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1])
        return res if isinstance(res, dict) else {"ok": False, "error": "드라이버 출력 형식 오류"}
    except Exception as e:  # noqa: BLE001 - 한 청크 실패가 정제 전체를 멈추지 않게
        return {"ok": False, "error": f"드라이버 실패({type(e).__name__})", "hint": str(e)[:120]}


ACT_CATS = {"설계", "해석·시뮬레이션", "SW개발", "검증·평가", "입고검사·현장",
            "자재·발주", "불량·대응", "회의·협업", "문서·보고", "기타"}

# 출력 형식 예시 — 답에 프롬프트 에코가 섞이면(앵커 실패) 이 예시가 '답'으로 해석돼 항목 0·3 이
# Level 3 '...' 로 병합됐다(실측). 파서는 이 문자열과 같은 JSON 을 건너뛴다.
REFINE_EXAMPLE = ('{"items":[{"m":[0,3],"l1":"신제품개발","l2":"과제명","l3":"담당 업무명",'
                  '"a":"설계","d":"상세설명 한 줄","w":true}]}')
REFINE_EXAMPLE_OLD = ('{"items":[{"merge":[0,3],"level1":"...","level2":"...","level3":"...",'
                      '"activity":"...","detail":"...","work":true}]}')
REFINE_EXAMPLES = (REFINE_EXAMPLE, REFINE_EXAMPLE_OLD)
_KEYS = {"merge": ("m", "merge"), "level1": ("l1", "level1"), "level2": ("l2", "level2"),
         "level3": ("l3", "level3"), "activity": ("a", "activity"), "detail": ("d", "detail"),
         "work": ("w", "work")}


def _g(it, key):
    """항목 필드 — 축약 키(m/l1/…)와 옛 긴 키(merge/level1/…) 모두 받는다."""
    for k in _KEYS.get(key, (key,)):
        if k in it:
            return it.get(k)
    return None


def _f(x):
    """숫자 셀 → float. 빈칸·비숫자(엑셀 재저장·손편집)는 0 — 셀 하나로 정제 전체가 죽지 않게(V-05)."""
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(x):
    try:
        return int(float(x or 0))
    except (TypeError, ValueError):
        return 0


def _num_ok(x):
    """셀이 숫자로 읽히는가 — 빈칸·None·'abc' 는 False (변환 실패 행 수 집계용)."""
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def _majority(pairs):
    """다수결(결정적, V-03) — pairs: [(값, 비중)]. 최빈값을 고르고, 동률이면 비중이 가장 큰 원본 행의 값, 그래도
    같으면 원본 순서의 첫 값. 예전 max(set(x), key=x.count) 는 set 순회 순서가 해시 시드에 따라 달라 동률일 때
    병합 행의 제품·유형·Level 2/3 가 실행마다 뒤바뀌었고, agentic 이 '행이 바뀌었다' 고 보고 옛 매칭을 승계했다."""
    vals = [(str(v).strip(), _f(s)) for v, s in pairs if str(v or "").strip()]
    if not vals:
        return ""
    cnt = Counter(v for v, _s in vals)
    top = max(cnt.values())
    best = {}
    for v, s in vals:
        if cnt[v] == top:
            best[v] = max(best.get(v, -1.0), s)
    order = [v for v in dict.fromkeys(v for v, _s in vals) if v in best]       # 원본 순서
    return max(order, key=lambda v: (best[v], -order.index(v)))


def item_line(i, r, overlap=False):
    tagx = " (겹침·참고)" if overlap else ""
    return (f"  #{i}{tagx} {r.get('Level 2', '')} / {r.get('Level 3', '')} · 비중 {_f(r.get('share'))*100:.1f}% "
            f"· {_i(r.get('활동일수'))}일 · 근거 {r.get('근거', '')}")


def build_prompt(rows, evidence_md, model_names=(), ev_mode="aligned", overlap=()):
    """rows: [(원본 번호, 행)]. overlap: 앞 청크와 겹치는(참고용) 번호 집합."""
    # 근거가 실제로 얼마나 붙었는지에 따라 선언과 5번 규칙을 바꾼다.
    # 근거를 0바이트로 보내면서 "각 항목의 실제 원문 근거입니다"라고 말하면
    # AI 는 없는 파일명·건수를 지어낸다 — 창작을 부르는 것은 결핍이 아니라 거짓 선언이다.
    if evidence_md and ev_mode == "aligned":
        head = "**각 항목의 실제 원문 근거**(메일 제목·파일명·커밋 메시지·회의명·작업창)입니다."
        rule5 = [f"5. d = 상세설명 **한 줄, {DETAIL_MAX}자 이내** — 근거의 고유명사를 살려 '무엇을 어떻게 했는지'",
                 "   (좋은 예: 'CV 샘플 열·구동부 성능 검증용 자재 발주 및 입고 관리')",
                 "   (나쁜 예: '관련 업무 수행', '자료 작성' — 이런 건 쓰지 말 것)"]
    elif evidence_md:
        head = ("일부 항목의 원문 근거입니다. **근거는 항목별로 완전히 정렬되어 있지 않습니다** — "
                "근거 블록의 `## #번호` 와 항목 번호를 대조해 쓰세요.")
        rule5 = [f"5. d = 상세설명 **한 줄, {DETAIL_MAX}자 이내** — 대응 근거가 있으면 그 고유명사를 살릴 것",
                 "   5-b. 대응 근거가 없는 항목은 Level 2·Level 3 를 자연어로 풀어 쓰고,",
                 "        **확인되지 않은 파일명·메일 제목·수량을 만들어내지 말 것**"]
    else:
        head = "업무 항목 목록입니다. **원문 근거는 이번 요청에 포함되지 않았습니다.**"
        rule5 = [f"5. d = 상세설명 **한 줄, {DETAIL_MAX}자 이내** — 항목 줄의 Level 2·Level 3 만으로 쓸 것",
                 "   **파일명·메일 제목·건수 등 주어지지 않은 고유명사를 지어내지 말 것**",
                 "   (금지 예: 'xxx_1부터 xxx_11까지' 처럼 확인 안 된 목록·수량)"]
    lines = [
        "당신은 업무 로드율 분석의 판정자입니다. 아래는 한 사람의 PC에서 추출한 업무 항목과",
        head,
        "",
        "할 일:",
        "1. 같은 업무가 여러 항목으로 쪼개져 있으면 **하나로 합칠 것** (m 에 합칠 원본 항목번호들)",
        "2. l2 = 실제 과제·프로젝트명으로 정규화 (원문에서 읽어낸 이름. 토큰 조각 금지)"
        + (" — 이미 확정된 과제 체계가 있으니 그 표기를 그대로 유지할 것(변형·재작명 금지): "
           + ", ".join(model_names) if model_names else ""),
        "3. l1 = 업무 성격 (신제품개발 / 기술 내재화 / 양산준비 / 일반업무 중 택1)",
        "4. l3 = **담당 업무 항목명**(중위개체) — 항목 줄의 세부업무명을 유지·다듬는다.",
        "   ('Capability 구조 설계', '수광부 렌즈 해석'처럼 그 과제 안의 실제 업무 이름.",
        "    설계/문서·보고 같은 **범주로 축약 금지** — 범주는 a 에 따로 쓴다)",
        "4-b. a = 활동 범주 택1 (설계 / 해석·시뮬레이션 / SW개발 / 검증·평가 /",
        "   입고검사·현장 / 자재·발주 / 불량·대응 / 회의·협업 / 문서·보고)",
        *rule5,
        "6. 업무가 아닌 항목(개인·잡음)은 w:false",
    ]
    if overlap:
        lines += ["7. '(겹침·참고)' 표시 항목은 앞 청크에서 이미 정리한 것이다 — 이번 청크의 항목과 같은",
                  "   업무이면 m 에 그 번호를 함께 넣고, 아니면 그 항목만으로 된 출력은 내지 말 것."]
    lines += [
        "",
        "출력은 아래 JSON 하나만 (설명 문장·표·코드블록 금지). 키: m=합칠 항목번호, l1=업무 성격,",
        "l2=과제, l3=담당 업무명, a=활동 범주, d=상세설명, w=업무 여부:",
        REFINE_EXAMPLE,
        "",
        "[추출된 업무 항목]",
    ]
    for i, r in rows:                      # (원본 인덱스, 행)
        lines.append(item_line(i, r, overlap=(i in overlap)))
    if evidence_md:
        lines += ["", "[항목별 원문 근거]", evidence_md]
    return "\n".join(lines)


def _rfind(reply, key, skip=()):
    if _judge is not None and hasattr(_judge, "rfind_json"):
        try:
            return _judge.rfind_json(reply, key, skip=skip)
        except TypeError:                      # 구판 judge(skip 없음)
            return _judge.rfind_json(reply, key)
    skip_n = {re.sub(r"\s+", "", s) for s in (skip or ()) if s}      # judge 부재 폴백에도 예시 방어
    i = reply.rfind("{")
    n = 0
    while i != -1 and n < 400:
        try:
            o, end = _DEC.raw_decode(reply, i)
            if isinstance(o, dict) and key in o and re.sub(r"\s+", "", reply[i:end]) not in skip_n:
                return o
        except ValueError:
            pass
        n += 1
        i = reply.rfind("{", 0, i)
    return {}


def extract_items_ex(reply):
    """답 → (items, info{json, repaired}). 완전한 JSON → 잘린 JSON 복구(judge.repair_json) 순.
    repaired 가 참이면 답이 온전하지 않았다 — 호출자가 빠진 항목을 다시 묻는다."""
    reply = str(reply or "")
    info = {"json": False, "repaired": False}
    o = _rfind(reply, "items", skip=REFINE_EXAMPLES)
    if isinstance(o, dict) and isinstance(o.get("items"), list) and o["items"]:
        info["json"] = True
        return [it for it in o["items"] if isinstance(it, dict)], info
    if _judge is not None and hasattr(_judge, "repair_json"):
        try:
            o = _judge.repair_json(reply, "items", skip=REFINE_EXAMPLES)
        except TypeError:                          # 구판 judge(skip 없음)
            o = _judge.repair_json(reply, "items")
        items = [it for it in (o.get("items") or []) if isinstance(it, dict)] if isinstance(o, dict) else []
        if items:
            info["json"] = info["repaired"] = True
            return items, info
    return [], info


def extract_items(reply):
    """호환 — 항목 목록만."""
    return extract_items_ex(reply)[0]


def load_signal_evidence(rep, tag):
    """근거는 judge 가 판정 축으로 재작성하는 signals_{tag}.csv 에서 (Level 2, Level 3) 로 뽑는다.
    evidence_*.md 는 mine 축(규칙 이름)이라 판정 뒤에는 키가 절대 맞지 않는다 —
    judge 가 mm_rows 의 Level 2 만 덮어쓰고 evidence 는 재생성하지 않기 때문이다(실측 0건 매칭)."""
    sp = os.path.join(rep, f"signals_{tag}.csv")
    if not os.path.exists(sp):
        return None, False
    try:
        with open(sp, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error, UnicodeDecodeError):
        return None, False
    if not rows:
        return None, False
    judged = "model" in rows[0]          # judge 미실행이면 mine 판(model 컬럼 없음)
    k2, k3 = ("model", "detail") if judged else ("project", "activity")
    by = {}
    for r in rows:
        key = (str(r.get(k2) or "").strip(), str(r.get(k3) or "").strip())
        line = (f"- {(r.get('time') or '')[:10]} [{r.get('source') or ''}] "
                f"{(r.get('text') or '')[:100]}")
        by.setdefault(key, []).append(line)
    return by, judged


def slice_for_chunk(by, ch, cap=9000, overlap=()):
    """청크의 각 항목에 **자기 근거만** 붙인다. 헤더에 원본 항목번호(#i)를 심어
    프롬프트의 '[추출된 업무 항목]' 줄과 1:1 로 묶는다 — 이름이 바뀌어도 안 깨진다.
    cap 은 호출자가 예산(PROMPT_BUDGET − 머리말·항목 줄)으로 준다. 겹침 항목은 OV_EV_LINES 줄만."""
    if not by or not ch or cap <= 0:
        return "", 0
    n_main = max(1, len([1 for i, _ in ch if i not in overlap]))
    per = max(3, cap // max(1, n_main * 95))      # 항목이 많으면 항목당 줄 수를 줄인다
    out, hit = [], 0
    for i, r in ch:
        lv2 = str(r.get("Level 2") or "").strip()
        lv3 = str(r.get("Level 3") or "").strip()
        lines = by.get((lv2, lv3)) or []
        if not lines:                              # 2차: Level 2 만으로 (세부업무명이 정제된 경우)
            lines = [ln for (m, _d), v in by.items() if m == lv2 for ln in v]
        if not lines:
            continue
        hit += 1
        out.append(f"## #{i} {lv2} / {lv3}")
        out.extend(list(dict.fromkeys(lines))[:(OV_EV_LINES if i in overlap else per)])
    text = "\n".join(out)
    if len(text) > cap:                            # 줄 경계에서 자른다(항목 중간 절단 방지)
        text = text[:cap]
        text = text[:text.rfind("\n")] if "\n" in text else text
    return text, hit


def _evidence_slice(ev_text, names):
    """이 청크에 등장하는 과제(Level 2)의 근거 단락만 골라낸다 — 전체 근거를 매번 보내면
    프롬프트가 비대해져 응답이 잘린다.
    헤더의 Level 2 부분만 대조한다: Level 3(활동 범주)는 여러 과제가 공유하므로 그걸로
    매칭하면 다른 과제의 근거가 섞인다. 못 맞추면 **빈 문자열** — 예전처럼 앞부분 4000자를
    넣으면 다른 항목의 근거가 이 청크의 근거인 양 전달돼 오히려 판단을 망친다."""
    if not ev_text:
        return ""
    want = {str(n).strip().lower() for n in names if str(n).strip()}
    keep, take = [], False
    for ln in ev_text.splitlines():
        if ln.startswith("#"):
            # 헤더 형식 '## {Level 2} / {Level 3} — …' 의 Level 2 부분만 본다
            head = ln.lstrip("# ").split(" / ")[0].strip().lower()
            take = any(w and (w == head or w in head) for w in want)
        if take:
            keep.append(ln)
    return "\n".join(keep)


def load_exclude():
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            return [k for k in json.load(f).get("excludePathKeywords", []) if k and len(k) >= 2]
    except Exception:
        return []


def sanitize_evidence(ev_text, kws):
    """개인정보가 있는 '근거 줄'만 빼고 나머지는 보낸다.
    (전체 중단은 도구를 멈추게 하고, 통째 전송은 유출을 낳는다 — 줄 단위가 안전선)"""
    # 경로 전용 토큰·ASCII 부분일치 오탐 방지 — extract.load_signals 와 같은 규칙
    # ('temp'⊂'temperature' 로 정상 근거 줄이 삭제되던 결함의 자매 지점)
    from extract import PATH_ONLY_KW
    kr = [str(k).lower() for k in kws if k and not str(k).isascii()
          and str(k).lower() not in PATH_ONLY_KW]
    asc = [str(k).lower() for k in kws if k and str(k).isascii()
           and str(k).lower() not in PATH_ONLY_KW]
    pat = (re.compile("|".join(f"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])" for k in asc))
           if asc else None)
    keep, dropped, hits = [], 0, set()
    for ln in ev_text.splitlines():
        low = ln.lower()
        h = [k for k in kr if k in low]
        if not h and pat:
            m = pat.search(low)
            if m:
                h = [m.group(0)]
        if h and ln.strip().startswith("-"):        # 근거 항목 줄만 제거 (제목 줄은 유지)
            dropped += 1
            hits.update(h)
            continue
        keep.append(ln)
    return "\n".join(keep), dropped, sorted(hits)


def plan_chunks(idxed, chunk_n):
    """[(원본 인덱스, 행)] → [(항목 목록, 겹침 번호 집합)]. 두 번째 청크부터 앞 청크 끝 OV_N 항목
    (OV_CHARS 이내)을 앞에 붙인다 — 청크 경계에서 갈린 같은 업무를 이을 수 있게(agentic.split_rows 와 같은 꼴)."""
    base = [idxed[i:i + chunk_n] for i in range(0, len(idxed), chunk_n)]
    out = []
    for k, ch in enumerate(base):
        ov, size = [], 0
        if k:
            for i, r in reversed(base[k - 1]):
                ln = len(item_line(i, r, True)) + 1
                if len(ov) >= OV_N or size + ln > OV_CHARS:
                    break
                ov.insert(0, (i, r))
                size += ln
        out.append((ov + ch, {i for i, _ in ov}))
    return out


class Refiner:
    """청크 왕복 + 적응 분할. items 에 (보낸 번호 집합, 겹침 번호 집합, 항목 dict) 를 쌓는다."""

    def __init__(self, tag, rep, sig_by, ev, model_names, say=print):
        self.tag, self.rep, self.sig_by, self.ev, self.model_names, self.say = tag, rep, sig_by, ev, model_names, say
        self.items = []
        self.st = {"roundtrips": 0, "repaired": 0, "retries": 0, "failed_items": 0, "notes": []}
        self.excl = load_exclude()
        self.first_filter_note = True
        self.soft = False

    def make_prompt(self, ch, ov, label):
        head = build_prompt(ch, "", self.model_names, "aligned", ov)     # 가장 긴 머리말로 예산을 잰다
        cap = PROMPT_BUDGET - len(head) - 40
        if self.sig_by:
            sub_ev, hit = slice_for_chunk(self.sig_by, ch, cap, ov)
            ev_mode = "aligned" if hit == len(ch) else ("partial" if hit else "none")
        else:
            # signals 가 없다 — 예전 근거 파일을 항목별 정렬 없이 보낸다.
            # 정렬을 보장할 수 없다는 사실을 프롬프트가 명시하므로 창작으로 이어지지 않는다.
            sub_ev = _evidence_slice(self.ev, [r["Level 2"] for _i, r in ch]) or self.ev[:min(4000, cap)]
            sub_ev = sub_ev[:cap]
            ev_mode = "unaligned" if sub_ev else "none"
            hit = 0
        if sub_ev:
            sub_ev, dropped, hits = sanitize_evidence(sub_ev, self.excl)
            if dropped and self.first_filter_note:
                self.first_filter_note = False
                self.say(f"        개인정보 필터: 근거 {dropped}줄 제외 {hits}")
        if ev_mode != "aligned":
            self.say(f"        근거 정렬: {ev_mode} ({hit}/{len(ch)}항목) — "
                     f"프롬프트가 '지어내지 말 것'을 명시합니다")
        prompt = build_prompt(ch, sub_ev, self.model_names, ev_mode, ov)
        # 사람이 Copilot 에 직접 붙여넣을 수 있게 프롬프트 파일은 예전 이름 그대로 남긴다
        # (judge.copilot_send 의 report\judge_refine{n}_{tag}.md 는 성공 왕복 뒤 지워진다 — V-06)
        pf = os.path.join(self.rep, f"refine_prompt_{self.tag}_{label}.md")
        try:
            with open(pf, "w", encoding="utf-8") as f:
                f.write(prompt)
        except OSError:
            pass
        return prompt

    def run(self, ch, ov, label, depth=0):
        """청크 하나(겹침 포함) → 이 청크가 덮은 원본 번호 수. 실패·잘림은 적응 분할."""
        lo, hi = ch[0][0], ch[-1][0]
        prompt = self.make_prompt(ch, ov, label)
        self.say(f"[refine] {label} 왕복 중… (#{lo}~#{hi}{', 겹침 ' + str(len(ov)) if ov else ''}, "
                 f"프롬프트 {len(prompt):,}자)")
        try:
            # fresh=None — 청크를 같은 채팅에서 이어 보낸다(첫 왕복·실패 뒤·chatTurns 마다만 새 채팅): 앞 청크의 과제·담당 업무
            # 표기를 Copilot 이 기억한다(제보: 청크마다 새 채팅이라 기억이 안 이어짐). 프롬프트는 여전히 혼자서 완결
            res = copilot_send(prompt, self.tag, f"refine{label}")
        except Exception as e:  # noqa: BLE001 - 한 청크의 왕복 예외가 정제 전체를 멈추지 않게
            res = {"ok": False, "error": f"드라이버 실패({type(e).__name__})"}
        self.st["roundtrips"] += 1
        res = res if isinstance(res, dict) else {}
        got, info = [], {}
        if res.get("ok"):
            got, info = extract_items_ex(res.get("reply", ""))
            if info.get("repaired"):
                self.st["repaired"] += 1
                self.say(f"        잘린 응답 복구 — {len(got)}개 항목")
            elif not got:
                self.say("        응답에서 JSON을 찾지 못함")
                if _judge is not None and hasattr(_judge, "note_bad_reply"):
                    _judge.note_bad_reply()
            elif res.get("cut"):
                self.say(f"        생성 중단 응답 — {len(got)}개 항목 회수")
        else:
            self.say(f"        {res.get('error', '')} — {str(res.get('hint', ''))[:80]}")
        ch_ok = {i for i, _ in ch}
        covered = set()
        for it in got:
            mg = _g(it, "merge")
            mg = mg if isinstance(mg, list) else ([mg] if mg not in (None, "") else [])
            covered |= {int(x) for x in mg if str(x).isdigit() and int(x) in ch_ok}
        if got:
            self.items.extend((ch_ok, set(ov), it) for it in got)
            self.say(f"        {len(got)}개 항목 정리")
        missing = [(i, r) for i, r in ch if i not in covered and i not in ov]
        incomplete = (not res.get("ok")) or (not got) or bool(info.get("repaired")) or bool(res.get("cut"))
        if not missing or not incomplete or self.soft or depth >= MAX_SPLIT_DEPTH:
            if missing and incomplete:
                self.st["failed_items"] += len(missing)
            return len(ch_ok - set(ov)) - (len(missing) if incomplete else 0)
        if got:                                   # 부분 성공 — 빠진 항목만 (겹침 없이)
            if len(missing) >= MIN_RETRY_ITEMS:
                self.st["retries"] += 1
                self.say(f"        빠진 {len(missing)}항목 재왕복")
                self.run(missing, set(), f"{label}r", depth + 1)
            else:
                self.st["failed_items"] += len(missing)
            return len(ch_ok - set(ov))
        base = [(i, r) for i, r in ch if i not in ov]
        if len(base) >= 2 * MIN_SPLIT:            # 통째 실패 — 반으로
            self.st["retries"] += 1
            h = len(base) // 2
            self.say(f"        실패 — {len(base)}항목을 {h}+{len(base) - h} 로 나눠 재시도")
            self.run(base[:h], set(), f"{label}a", depth + 1)
            self.run(base[h:], set(), f"{label}b", depth + 1)
            return len(base)
        self.st["failed_items"] += len(base)
        return 0


def merge_groups(items, rows):
    """청크 응답들 → 그룹[{idxs, it}] (union). 앞 청크가 이미 가져간 번호는 **겹침 항목**일 때만
    이번 항목과 이어 붙이고(같은 업무가 청크 경계에서 갈린 것), 그 밖의 중복 번호는 무시한다 —
    같은 행이 청크마다 다시 계상돼 배분이 왜곡되던 결함(검증 확정)의 방어는 그대로.
    그룹의 이름·설명은 그 항목이 덮은 비중이 큰 쪽 것을 쓴다."""
    groups, owner = [], {}

    def share_of(ids):
        return sum(_f(rows[i].get("share")) for i in ids)

    for ch_ok, ov, it in items:
        mg = _g(it, "merge")
        mg = mg if isinstance(mg, list) else ([mg] if mg not in (None, "") else [])
        idxs = [int(x) for x in mg if str(x).isdigit() and int(x) < len(rows) and int(x) in ch_ok]
        new = [i for i in dict.fromkeys(idxs) if i not in owner]
        bridge = sorted({owner[i] for i in idxs if i in owner and i in ov})
        if not new:
            continue                              # 겹침 항목만 다시 낸 것(또는 중복 번호) — 앞 결과 유지
        if bridge:
            g = groups[bridge[0]]
            for other in bridge[1:]:              # 여러 앞 그룹을 한 번에 잇는 경우 — 전부 하나로
                g["idxs"] |= groups[other]["idxs"]
                groups[other]["idxs"] = set()
            g["idxs"] |= set(new)
            if share_of(new) > g["pick_share"]:   # 더 큰 비중을 덮은 항목의 이름·설명을 대표로
                g["it"], g["pick_share"] = it, share_of(new)
            gid = bridge[0]
        else:
            groups.append({"idxs": set(new), "it": it, "pick_share": share_of(new)})
            gid = len(groups) - 1
        for i in groups[gid]["idxs"]:
            owner[i] = gid
    return [g for g in groups if g["idxs"]], owner


def main():
    d0, d1 = arg("--from"), arg("--to")
    tag = f"{d0.replace('-','')}-{d1.replace('-','')}"
    rep = os.path.join(ROOT, "report")
    src = os.path.join(rep, f"mm_rows_{tag}.csv")
    evp = os.path.join(rep, f"evidence_{tag}.md")
    if not os.path.exists(src):
        print(f"[refine] 입력 없음 — 먼저 mine.py 를 실행하세요 ({src})")
        return 1
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    # 숫자 셀을 먼저 확정한다(V-05) — 빈칸·비숫자 셀 하나에 item_line/병합의 float()/int() 가 ValueError 로 죽어
    # run.py 가 'AI 정제 실패' 로만 남기던 결함. 0 으로 두고 행 수를 로그·마지막 JSON(bad_rows)에 남긴다.
    bad_rows = 0
    for r in rows:
        if not all(_num_ok(r.get(k)) for k in ("share", "mm", "활동일수")):
            bad_rows += 1
        r["share"], r["mm"], r["활동일수"] = _f(r.get("share")), _f(r.get("mm")), _i(r.get("활동일수"))
    if bad_rows:
        print(f"[refine] 숫자 변환 실패 {bad_rows}행 — share/mm/활동일수 가 빈칸·비숫자(엑셀 재저장·손편집?) → 0 으로 두고 계속합니다")
    # 근거는 판정 축과 키가 같은 signals 를 우선한다. 없을 때만 예전 evidence 파일.
    sig_by, sig_judged = load_signal_evidence(rep, tag)
    ev = open(evp, encoding="utf-8").read() if os.path.exists(evp) else ""
    if sig_by:
        print(f"[refine] 근거 원천: signals_{tag}.csv "
              f"({'판정 축' if sig_judged else '규칙 축'}, {len(sig_by)}묶음)")
    elif ev:
        print(f"[refine] 근거 원천: evidence_{tag}.md (signals 없음 — 정렬 보장 안 됨)")
    # judge가 확정한 과제 체계가 있으면 Level 2 재작명을 막는 제약으로 전달
    ent_p = os.path.join(rep, f"entities_{tag}.json")
    model_names = []
    if os.path.exists(ent_p):
        try:
            model_names = [m["name"] for m in json.load(open(ent_p, encoding="utf-8")).get("models", [])
                           if isinstance(m, dict) and m.get("name")]
        except (OSError, ValueError):
            pass
    # 항목이 많으면 한 번의 왕복으로는 응답이 잘리거나 실패한다 — 청크로 나눠 여러 번 돈다.
    # 실패한 청크는 '병합 없음'으로 두고 계속 진행한다(전부 버리지 않는다).
    # 40항목 ≈ 12,200자(근거 포함)로 입력 한도(9,000자)를 넘겼다 — 20항목이 안전값(실측).
    # --chunk 명시 > config.copilotAuto.refineChunk > 20. 근거 슬라이스는 예산에 맞춰 잘린다.
    chunk_n = chunk_default("refineChunk", 20)
    idxed = list(enumerate(rows))
    plan = plan_chunks(idxed, chunk_n)
    print(f"[refine] {len(rows)}항목 → {len(plan)}회 왕복 (청크 {chunk_n}항목 · 겹침 {OV_N}항목 · "
          f"예산 {PROMPT_BUDGET:,}자)")
    rf = Refiner(tag, rep, sig_by, ev, model_names)
    failed, consec = 0, 0
    for ci, (ch, ov) in enumerate(plan):
        progress("AI 정제", ci, len(plan))
        before = len(rf.items)
        rf.run(ch, ov, str(ci + 1))
        if len(rf.items) == before:
            failed += 1
            consec += 1
            if consec >= FAIL_STOP_RETRY and not rf.soft:
                rf.soft = True
                print(f"        연속 {consec}청크 실패 — 적응 재시도(반분·빠진 항목)를 끄고 1회씩만 시도합니다")
        else:
            consec = 0
    progress("AI 정제", len(plan), len(plan))
    st = rf.st
    tail = {"chunks": len(plan), "failed_chunks": failed, "roundtrips": st["roundtrips"],
            "repaired": st["repaired"], "retries": st["retries"], "failed_items": st["failed_items"],
            "bad_rows": bad_rows}
    if not rf.items:
        print("[refine] 정제된 항목이 없습니다 — 규칙 결과를 그대로 둡니다")
        print("        report\\refine_prompt_*.md 를 Copilot에 직접 붙여넣어도 됩니다")
        print(json.dumps(dict(tail, ok=False, error="정제 0건"), ensure_ascii=False))
        return 1
    if failed or st["repaired"] or st["retries"]:
        print(f"[refine] 청크 {failed}/{len(plan)} 실패 · 왕복 {st['roundtrips']}회(재시도 {st['retries']}) · "
              f"잘린 응답 복구 {st['repaired']}회 · 원본 유지 항목 {st['failed_items']} — 해당 항목은 원본 그대로 보존됩니다")

    # 병합 + 비중 재정규화 (AI가 총량을 바꾸지 못하게 규칙이 통제)
    # 과제명(Level 2)은 기존 이름으로 스냅한다 — AI가 새 이름을 지어내면 대시보드(refined)와
    # 상세리뷰 피벗(judge)의 과제 축이 갈라져 MM 이 다르게 보인다(실측 지적: 미스매칭).
    # 신원 축은 ukey2 — .lower() 로 보면 AI 가 띄어쓰기만 바꿔도 '모르는 이름' 이 되어
    # 원본 다수결로 되돌려지거나 새 과제로 남는다(judge·flow 와 같은 축을 쓴다).
    known_lv2 = {ukey2(r.get("Level 2")) for r in rows} | {ukey2(n) for n in model_names}
    groups, owner = merge_groups(rf.items, rows)
    final = []
    for g in groups:
        it, idxs = g["it"], sorted(g["idxs"])
        if _g(it, "work") is False:
            continue
        share = sum(_f(rows[i].get("share")) for i in idxs)
        days = max(_i(rows[i].get("활동일수")) for i in idxs)
        srcs = " · ".join(sorted({str(rows[i].get("근거") or "") for i in idxs}))

        def _vote(col, ids=idxs):
            """구성원 행의 col 다수결 — 동률이면 비중 큰 행의 값(결정적, V-03)"""
            return _majority((rows[i].get(col), rows[i].get("share")) for i in ids)
        lv2 = str(_g(it, "level2") or "").strip()
        # 스냅은 judge 체계(entities)가 있을 때만 — 축을 맞출 피벗이 있는 경우다.
        # judge 미실행/실패로 체계가 없으면 AI 정규화(토큰 조각→실제 과제명)를 허용해야
        # 한다: 무조건 되돌리면 refine 단독 사용의 핵심 기능이 죽는다(검증 확정).
        if model_names and ukey2(lv2) not in known_lv2:     # AI 개명 → 원본 다수결로
            lv2 = _vote("Level 2") or "공통"
        elif not lv2:
            lv2 = "미지정"
        # level3 는 실제 업무 항목명(중위개체) — AI 가 비웠거나 9종 범주로 축약해 오면
        # 원본 세부업무명(다수결)을 지킨다. 범주는 activity('활동') 열이 따로 담는다.
        lv3 = str(_g(it, "level3") or "").strip()
        if not lv3 or lv3 in ACT_CATS:
            lv3 = _vote("Level 3") or lv3 or "기타"
        act = str(_g(it, "activity") or "").strip()
        detail = re.sub(r"\s+", " ", str(_g(it, "detail") or "")).strip()[:DETAIL_MAX * 2]
        final.append({"유형": _vote("유형"), "제품": _vote("제품"),
                      "활동": act if act in ACT_CATS else "",
                      "Level 1": snap1(_g(it, "level1")), "Level 2": lv2,
                      "Level 3": lv3, "상세설명": detail,
                      "share": share, "활동일수": days, "근거": srcs,
                      "확신도": "상" if days >= 3 and len(idxs) > 1 else "중",
                      # 정제 행이 덮은 원본 (Level 2, Level 3) — refine_map 용(CSV 열에는 안 나간다)
                      "_orig": [(str(rows[i].get("Level 2") or ""), str(rows[i].get("Level 3") or "")) for i in idxs]})
    for i, r in enumerate(rows):                      # AI가 언급 안 한 항목은 그대로 보존
        if i not in owner:
            final.append({"유형": r.get("유형", ""), "제품": r.get("제품", ""),
                          "활동": r.get("활동", ""),
                          "Level 1": "", "Level 2": r.get("Level 2", ""), "Level 3": r.get("Level 3", ""),
                          "상세설명": "", "share": _f(r.get("share")), "활동일수": _i(r.get("활동일수")),
                          "근거": r.get("근거", ""), "확신도": r.get("확신도", ""),
                          "_orig": [(str(r.get("Level 2") or ""), str(r.get("Level 3") or ""))]})
    if len(final) > len(rows):
        # 정제는 행을 합칠 수만 있고 늘릴 수 없다 — 늘었다면 응답 번호가 중복된 것이다.
        # 왜곡된 배분으로 좋은 결과를 덮지 않고 규칙 결과를 그대로 둔다.
        print(f"[refine] 이상: {len(rows)}항목이 {len(final)}항목으로 늘었습니다 "
              "(응답의 항목번호 중복) — 정제본을 쓰지 않고 규칙 결과를 유지합니다")
        print(json.dumps(dict(tail, ok=False, error="항목 수 증가"), ensure_ascii=False))
        return 1
    tot = sum(f["share"] for f in final) or 1.0
    # share 0(실측 총량 0)이면 0으로 둔다 — 1.0 폴백은 빈 기간을 1MM 규모로 지어내는 결함
    # (judge.py 의 `or 1` 폴백 제거와 같은 취지)
    # 총 MM 은 Σmm/Σshare 로 잰다 — 예전 rows[0] 한 행의 mm/share 는 반올림(mm 3자리·share 4자리)이
    # 작은 첫 행에서 크게 증폭됐다(합성 실측: 7.80 MM 이 8.33 으로).
    tot_mm = sum(_f(r.get("mm")) for r in rows)
    tot_sh = sum(_f(r.get("share")) for r in rows)
    months = tot_mm / tot_sh if tot_sh else 0.0
    for f in final:
        f["share"] = round(f["share"] / tot, 4)
        f["mm"] = round(f["share"] * months, 3)
        f["이름"] = rows[0].get("이름", "")
        f["Function"] = rows[0].get("Function", "")
    final.sort(key=lambda x: -x["mm"])

    dst = os.path.join(rep, f"mm_rows_{tag}_refined.csv")
    cols = ["Function", "Level 1", "제품", "유형", "활동", "Level 2", "Level 3", "이름", "상세설명",
            "share", "mm", "근거", "확신도", "활동일수"]
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in final:
            w.writerow({c: r.get(c, "") for c in cols})
    # 정제 행 → 원본 (Level 2, Level 3) 매핑(V-02) — UI 오할당 제외(app.exclude_work)가 정제·병합으로 이름이 바뀐
    # 행도 signals 의 원본 쌍으로 풀어 구성원 신호를 전부 제외한다. 정제본과 운명을 같이한다(run.py 가 .stale 로
    # 개명, exclude 가 함께 삭제). 같은 이름의 정제 행이 둘이면 원본 쌍을 합친다.
    rmap = {}
    for r in final:
        key = f"{r.get('Level 2', '')}/{r.get('Level 3', '')}"
        lst = rmap.setdefault(key, [])
        for a, b in r.get("_orig", []):
            if [a, b] not in lst:
                lst.append([a, b])
    mp = os.path.join(rep, f"refine_map_{tag}.json")
    try:
        with open(mp, "w", encoding="utf-8") as f:
            json.dump({"tag": tag, "generated": time.strftime("%Y-%m-%d %H:%M"), "rows_file": os.path.basename(src),
                       "refined_file": os.path.basename(dst), "map": rmap}, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[refine] 정제 매핑(refine_map) 저장 실패({type(e).__name__}) — 오할당 제외는 이름 일치로만 찾습니다")
    print(f"[refine] {len(rows)}항목 → {len(final)}항목 (병합 {len(rows)-len(final)}) · "
          f"총 {sum(f['mm'] for f in final):.2f} MM")
    for f in final[:8]:
        print(f"   {str(f.get('Level 2') or '')[:22]:23s} {str(f.get('Level 3') or '')[:12]:13s} "
              f"{f['mm']:5.2f} MM  {str(f.get('상세설명') or '')[:44]}")
    print(f"[refine] → {dst}")
    print(json.dumps(dict(tail, ok=True, rows=len(rows), refined=len(final)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
