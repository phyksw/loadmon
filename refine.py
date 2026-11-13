# -*- coding: utf-8 -*-
r"""
refine.py — AI 정제(AgentFinder32): 판정된 업무 분류(work_rows)를 Copilot 이 근거(메일·회의 제목)를 읽고 다듬는다.

규칙으로 못 하는 것만 AI 에게 맡긴다:
  ① 같은 업무가 쪼개진 행 병합   ② 과제명 정규화(체계 표기 유지)   ③ Level 1 부여   ④ 상세설명 한 줄(업무 행위·산출물)
프롬프트에는 과제·세부업무 이름과 근거 제목만 싣는다 — 비중(%)·활동일수·건수·날짜는 싣지 않는다(D10).
근거는 judge 가 판정 축으로 쓴 report\evidence_<tag>.md(§5.5)에서 항목별로 뽑는다.

  python refine.py --from 2026-08-01 --to 2026-10-31 [--chunk 20]

산출: report\work_rows_<tag>_refined.csv(§5.5 열 + 유형 뒤 '활동') · report\refine_map_<tag>.json(정제 행 → 원본 쌍 · 날짜만).
근거건수는 구성원 행의 합, share 는 정렬용 상대값(재정규화)이다.

청크·한도:
  · 청크 20항목이지만 프롬프트는 글자 예산(PROMPT_BUDGET 8,400) 안에서 만든다.
  · 오버레이: 다음 청크 앞에 앞 청크 끝 3항목(600자 이내)을 '겹침' 표시로 다시 보인다 — 청크 경계에서 갈린 같은 업무를
    합칠 수 있게. 겹침 항목이 이번 청크의 새 항목과 함께 merge 되면 앞 청크의 그룹과 이어 붙인다(union).
  · 응답 줄이기: 키 축약(m/l1/l2/l3/a/d/w — 옛 긴 키도 받는다) + 상세설명 90자 이내.
  · 적응 분할: 잘린 JSON 은 마지막 완전한 항목까지 복구하고 빠진 항목만 다시 묻는다. JSON 이 없으면
    청크를 반으로(최소 5항목·깊이 2) 나눠 재시도. 부분 성공은 그대로 쓰고 나머지는 원본 유지.
  · 마지막 줄에 {"ok":…,"chunks","failed_chunks","roundtrips","repaired","retries","bad_rows"} JSON 을 남긴다.
  · G3: 근거 줄은 개인 주제어(privacy.keyword_hit) 줄을 빼고, 남은 줄은 관문(judge.g3_rows)을 거친 재정제 줄만 보낸다.
    과제 체계의 이름과 항목 줄의 과제 이름도 관문을 지난 사본으로 싣는다(judge.sendable·send_l2 — 지정 과제 이름에 든 사람
    이름·고객사는 가린 채 · 답의 가린 이름은 judge.unmask_name 이 원래 이름으로 되돌린다).
    관문에 막힌 청크는 보내지 않고 원본 그대로 둔다 — 실패가 아니다(skipped_chunks·gated_items, 연속 실패 계수 밖).
  · 과제 관문: 병합(m)은 같은 과제(Level 2) 안의 항목끼리만 받는다(task_guard_groups). 과제 이름은 구성원의 과제를 지킨다.
  · 시작할 때 내 자료인지(consent.require — 다른 사용자의 자료면 종료 코드 4 · 지우는 중이면 3)와 run_meta 의 AgentFinder32 표식을 확인한다.
"""
import csv
import io
import json
import os
import re
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
if ROOT not in sys.path:
    # 내장 파이썬(python\python.exe)은 ._pth 때문에 isolated 모드로 뜨고, 스크립트 폴더가
    # sys.path 에 들어가지 않는다 — 아래 `import judge` 가 임포트 단계에서 죽지 않게 넣는다.
    sys.path.insert(0, ROOT)
from details import l1_prompt_lines  # noqa: E402  - 상위 정의 줄 생성(L1_META 단일원)
from details import ukey2  # noqa: E402  - judge·flow 와 같은 과제 신원 축
from details import ukey3  # noqa: E402  - 담당업무(하위) 신원 축 — 같은 업무를 두 행으로 남기지 않게
import details as _details  # noqa: E402  - explain_failure(로그인 필요 등 치명 실패 판정)
from details import snap1  # noqa: E402  - 상위(Level 1)를 고정 범주로 스냅
from progress import progress  # noqa: E402
import judge as _judge  # noqa: E402  - Copilot 왕복 단일 접점(copilot_send — D19 머리말·G3 관문)
if __name__ == "__main__":      # import 시엔 건드리지 않는다 — 임포트한 쪽의 stdout 이
    # 교체·GC 되면서 버퍼가 닫혀 이후 출력이 전부 죽는다(다른 모듈과 같은 관례)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
chunk_default = _judge.chunk_default
PROMPT_BUDGET = _judge.PROMPT_BUDGET
REFINED_COLS = ["Function", "Level 1", "유형", "활동", "Level 2", "Level 3", "상세설명", "근거건수", "근거", "확신도", "ax",
                "field", "share"]        # §5.5 + 유형 뒤 '활동'


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def _chat_note():
    """마지막 줄 JSON 앞의 Copilot 채팅 정리 한 줄(judge.chat_note — 이 프로세스가 연·지운·남긴 채팅 수, 숫자만)."""
    _judge.chat_note()


OV_N = 3                 # 오버레이 항목 수(앞 청크 끝)
OV_CHARS = 600           # 오버레이 항목 줄 합 상한
OV_EV_LINES = 2          # 오버레이 항목에 붙이는 근거 줄 수(참고용이라 짧게)
MIN_SPLIT = 5            # 적응 분할 최소 항목
MAX_SPLIT_DEPTH = 2      # 20 → 10 → 5
MIN_RETRY_ITEMS = 3      # 부분 성공 뒤 빠진 항목이 이 수 이상이면 그 항목만 재왕복
DETAIL_MAX = 90          # 상세설명 상한(프롬프트 지시 + 코드 절단)
FAIL_STOP_RETRY = 3      # 연속 실패 청크가 이만큼이면 적응 재시도를 끈다(공회전 방지)


def copilot_send(prompt_text, tag, name, fresh=None):
    """왕복 1회 — 호출 시점의 judge.copilot_send 를 쓴다(회귀 테스트가 그 이름을 모의 sender 로 바꿔치기해도 정제까지
    닿는다). 옛 3인자 sender(prompt, tag, name) 도 받아들인다 — fresh 를 못 받으면 빼고 부른다."""
    fn = _judge.copilot_send
    try:
        import inspect
        ps = inspect.signature(fn).parameters
        takes_fresh = "fresh" in ps or any(p.kind == p.VAR_KEYWORD for p in ps.values())
    except (TypeError, ValueError):
        takes_fresh = True
    return fn(prompt_text, tag, name, fresh=fresh) if takes_fresh else fn(prompt_text, tag, name)


ACT_CATS = {"설계", "해석·시뮬레이션", "SW개발", "검증·평가", "입고검사·현장",
            "자재·발주", "불량·대응", "회의·협업", "문서·보고", "기타"}

# 출력 형식 예시 — 답에 프롬프트 에코가 섞이면(앵커 실패) 이 예시가 '답'으로 해석돼 항목 0·3 이
# Level 3 '...' 로 병합됐다(실측). 파서는 이 문자열과 같은 JSON 을 건너뛴다.
REFINE_EXAMPLE = ('{"items":[{"m":[0,3],"l1":"개발","l2":"과제명","l3":"담당 업무명",'
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
    """숫자 셀 → float. 빈칸·비숫자(엑셀 재저장·손편집)는 0 — 셀 하나로 정제 전체가 죽지 않게."""
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
    """다수결(결정적) — pairs: [(값, 비중)]. 최빈값을 고르고, 동률이면 비중이 가장 큰 원본 행의 값, 그래도
    같으면 원본 순서의 첫 값(set 순회 순서는 해시 시드에 따라 달라 동률일 때 실행마다 뒤바뀌었다)."""
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


def send_l2(name):
    """항목 줄에 싣는 과제 이름 — G3 행 관문을 지난 사본(judge.sendable: 지정 과제 이름에 든 사람 이름·고객사는 가린 채). 답의
    l2 가 그 가린 이름이면 judge.unmask_name 이 원래 이름으로 되돌린다(main). 관문이 싣지 못하게 한 이름(제한 고객 등 — None)은
    원문 그대로 둔다 — 그 청크는 보내기 직전 최종 검사가 막아 보내지 않는다(예전과 같다)."""
    s = str(name or "")
    return (_judge.sendable(s) or s) if s.strip() else s


def item_line(i, r, overlap=False):
    """항목 줄 — 번호·과제·세부업무만(비중·활동일수·건수는 싣지 않는다 — D10). 과제 이름은 관문을 지난 사본(send_l2)."""
    tagx = " (겹침·참고)" if overlap else ""
    return f"  #{i}{tagx} {send_l2(r.get('Level 2', ''))} / {r.get('Level 3', '')}"


def build_prompt(rows, evidence_md, model_names=(), ev_mode="aligned", overlap=()):
    """rows: [(원본 번호, 행)]. overlap: 앞 청크와 겹치는(참고용) 번호 집합."""
    # 근거가 실제로 얼마나 붙었는지에 따라 선언과 5번 규칙을 바꾼다.
    # 근거를 0바이트로 보내면서 "각 항목의 실제 원문 근거입니다"라고 말하면
    # AI 는 없는 파일명·건수를 지어낸다 — 창작을 부르는 것은 결핍이 아니라 거짓 선언이다.
    # LM30(2026-10-21) — 프롬프트 앞 64자(첫 줄 + 이 줄의 앞부분)에는 마크다운(**)을 두지 않는다: Copilot 대화 목록의 제목이 첫 질문의
    # 앞부분이라, 화면이 ** 를 지우고 보여 주면 LM 이 지울 채팅을 제목으로 확인하지 못했다(조사 보고 3d).
    if evidence_md and ev_mode == "aligned":
        head = "각 항목의 실제 근거(메일 제목·회의 제목)입니다."
        rule5 = [f"5. d = 상세설명 **한 줄, {DETAIL_MAX}자 이내** — 근거의 업무 행위와 산출물을 살려 '무엇을 어떻게 했는지'",
                 "   (좋은 예: '시제품 2차 성능 시험용 부품 발주 및 입고 일정 관리')",
                 "   (나쁜 예: '관련 업무 수행', '자료 작성' — 이런 건 쓰지 말 것). 사람 이름은 쓰지 말 것"]
    elif evidence_md:
        head = ("일부 항목의 근거입니다. **근거는 항목별로 완전히 정렬되어 있지 않습니다** — "
                "근거 블록의 `## #번호` 와 항목 번호를 대조해 쓰세요.")
        rule5 = [f"5. d = 상세설명 **한 줄, {DETAIL_MAX}자 이내** — 대응 근거가 있으면 그 업무 행위를 살릴 것(사람 이름 금지)",
                 "   5-b. 대응 근거가 없는 항목은 Level 2·Level 3 를 자연어로 풀어 쓰고,",
                 "        **확인되지 않은 파일명·메일 제목·수량을 만들어내지 말 것**"]
    else:
        head = "업무 항목 목록입니다. 근거는 이번 요청에 포함되지 않았습니다."
        rule5 = [f"5. d = 상세설명 **한 줄, {DETAIL_MAX}자 이내** — 항목 줄의 Level 2·Level 3 만으로 쓸 것",
                 "   **파일명·메일 제목·건수 등 주어지지 않은 고유명사를 지어내지 말 것**",
                 "   (금지 예: 'xxx_1부터 xxx_11까지' 처럼 확인 안 된 목록·수량)"]
    lines = [
        "당신은 Agentic AI 전환 과제 발굴을 위한 업무 분류의 정리자입니다. 아래는 한 사람의 메일·일정에서 뽑은 업무 항목과",
        head,
        "",
        "할 일:",
        "1. 같은 업무가 여러 항목으로 쪼개져 있으면 **하나로 합칠 것** (m 에 합칠 원본 항목번호들)",
        # LM30(2026-10-27) — 과제가 다른 '주간보고'·'일정 조율' 끼리 합쳐 과제가 하나로 묶였다(코드도 같은 과제끼리만 받는다)
        "   m 은 같은 과제 안의 항목끼리만 — 과제가 다르면 이름이 같은 업무라도 합치지 마세요.",
        "2. l2 = 실제 과제명으로 정규화 (근거에서 읽어낸 이름. 토큰 조각 금지)"
        + (" — 이미 확정된 과제 체계가 있으니 그 표기를 그대로 유지할 것(변형·재작명 금지): "
           + ", ".join(model_names) if model_names else ""),
        # 상위 정의 줄은 details.L1_META 에서 생성 — config.level1Set 추가 범주가 프롬프트에
        # 자동으로 실린다(v2 는 하드코딩이라 모델이 추가 범주를 낼 수 없었다 — 반쯤 죽은 설정).
        *l1_prompt_lines(),
        "4. l3 = **담당 업무 항목명**(중위개체) — 항목 줄의 세부업무명을 유지·다듬는다.",
        "   ('Capability 구조 설계', '구동부 강도 해석'처럼 그 과제 안의 실제 업무 이름.",
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
        lines += ["", "[항목별 근거]", evidence_md]
    return "\n".join(lines)


def _rfind(reply, key, skip=()):
    return _judge.rfind_json(reply, key, skip=skip)


def extract_items_ex(reply):
    """답 → (items, info{json, repaired}). 완전한 JSON → 잘린 JSON 복구(judge.repair_json) 순.
    repaired 가 참이면 답이 온전하지 않았다 — 호출자가 빠진 항목을 다시 묻는다."""
    reply = str(reply or "")
    info = {"json": False, "repaired": False}
    o = _rfind(reply, "items", skip=REFINE_EXAMPLES)
    if isinstance(o, dict) and isinstance(o.get("items"), list) and o["items"]:
        info["json"] = True
        return [it for it in o["items"] if isinstance(it, dict)], info
    o = _judge.repair_json(reply, "items", skip=REFINE_EXAMPLES)
    items = [it for it in (o.get("items") or []) if isinstance(it, dict)] if isinstance(o, dict) else []
    if items:
        info["json"] = info["repaired"] = True
        return items, info
    return [], info


def extract_items(reply):
    """호환 — 항목 목록만."""
    return extract_items_ex(reply)[0]


_EV_HEAD = re.compile(r"^##\s+(.*?)\s+—\s+근거\s+\d+건\s*$")
_EV_LINE = re.compile(r"^-\s+(?:\d{2}-\d{2}\s+)?(.*)$")


def load_evidence(rep, tag):
    r"""report\evidence_<tag>.md(§5.5 — judge 가 판정 축으로 쓴다) → {(Level 2, Level 3): ['- 제목', …]} · 없으면 None.
    머리 '## <L2> / <L3> — 근거 N건' 의 건수와 줄 앞 날짜(MM-DD)는 프롬프트에 싣지 않으려고 떼어 낸다."""
    p = os.path.join(rep, f"evidence_{tag}.md")
    try:
        with open(p, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    by, key = {}, None
    for ln in lines:
        m = _EV_HEAD.match(ln.strip())
        if m:
            l2, _sep, l3 = m.group(1).partition(" / ")
            key = (l2.strip(), l3.strip())
            by.setdefault(key, [])
            continue
        m = _EV_LINE.match(ln.strip())
        if key is not None and m and m.group(1).strip():
            by[key].append("- " + m.group(1).strip()[:100])
    return by or None


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


def load_exclude():
    """개인 주제어 — 단일원 privacy.excluded_keywords(내장 EXCLUDE ∪ privacy.excludeKeywords). mine·judge 와 같은 범위."""
    import afcfg
    import privacy
    return [k for k in privacy.excluded_keywords(afcfg.load(ROOT)) if k and len(k) >= 2]


def sanitize_evidence(ev_text, kws):
    """개인정보가 있는 '근거 줄'만 빼고 나머지는 보낸다(전체 중단은 도구를 멈추게 하고, 통째 전송은 유출을 낳는다).
    ① 개인 주제어(privacy.keyword_hit — 한글 부분 일치·영문 단어 경계)가 든 근거 줄 삭제 ② 남은 근거 줄은 G3 관문
    (judge.g3_rows → privacy.gate_items)을 거친다 — 제한 고객·민감정보·식별번호·카나리아 줄은 빼고, 나머지는 재정제한 줄로
    바꾼다. 반환: (글, 뺀 줄 수, 걸린 낱말·사유)."""
    import privacy
    words = tuple(kws or ())
    keep, dropped, hits = [], 0, set()
    ev_lines = []                                   # (keep 안 위치, 줄) — 관문에 함께 넘긴다
    for ln in ev_text.splitlines():
        if ln.strip().startswith("-"):
            h = privacy.keyword_hit(ln, words=words)
            if h:                                   # 근거 항목 줄만 제거 (제목 줄은 유지)
                dropped += 1
                hits.add(h)
                continue
            ev_lines.append((len(keep), ln))
        keep.append(ln)
    if ev_lines:
        kept, why = _judge.g3_rows([{"text": ln, "_k": k} for k, ln in ev_lines], ("text",))
        ok = {it["_k"]: it["text"] for it in kept}
        for k, _ln in ev_lines:
            keep[k] = ok.get(k)
        n_g = len(ev_lines) - len(kept)
        if n_g:
            dropped += n_g
            hits.update(f"관문:{w}" for w in why)
        keep = [ln for ln in keep if ln is not None]
    return "\n".join(keep), dropped, sorted(hits)


def plan_chunks(idxed, chunk_n):
    """[(원본 인덱스, 행)] → [(항목 목록, 겹침 번호 집합)]. 두 번째 청크부터 앞 청크 끝 OV_N 항목
    (OV_CHARS 이내)을 앞에 붙인다 — 청크 경계에서 갈린 같은 업무를 이을 수 있게(agentic.split_rows 와 같은 꼴)."""
    # 청크는 **정체성 축**으로 자른다 — 예전에는 CSV 순서(비중 내림차순)를 그대로 잘라 같은 과제의
    # 행이 여러 청크로 흩어졌고, 이어 주는 것은 겹침 3항목 창 하나뿐이었다. 경계에서 모델이 같은 업무에
    # 다른 이름을 붙이면 그대로 두 행으로 남았다(제보: '같은 일이 다른 일로 인식'). 원본 인덱스는
    # 그대로 들고 가므로 병합·되쓰기(merge_groups·refine_map)는 영향받지 않는다.
    idxed = sorted(idxed, key=lambda ir: (ukey2((ir[1].get("Level 2") or "").strip() or "공통"),
                                          -_f(ir[1].get("share")),
                                          ukey3((ir[1].get("Level 3") or "").strip())))
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

    def __init__(self, tag, rep, sig_by, model_names, say=print):
        self.tag, self.rep, self.sig_by, self.model_names, self.say = tag, rep, sig_by, model_names, say
        self.items = []
        self.st = {"roundtrips": 0, "repaired": 0, "retries": 0, "failed_items": 0, "notes": []}
        self.excl = load_exclude()
        self.first_filter_note = True
        self.soft = False

    def make_prompt(self, ch, ov, label):
        head = build_prompt(ch, "", self.model_names, "aligned", ov)     # 가장 긴 머리말로 예산을 잰다
        cap = PROMPT_BUDGET - len(head) - 40
        sub_ev, hit = slice_for_chunk(self.sig_by, ch, cap, ov) if self.sig_by else ("", 0)
        ev_mode = "aligned" if hit == len(ch) else ("partial" if hit else "none")
        if sub_ev:
            sub_ev, dropped, hits = sanitize_evidence(sub_ev, self.excl)
            if dropped and self.first_filter_note:
                self.first_filter_note = False
                self.say(f"        개인정보 필터: 근거 {dropped}줄 제외 {hits}")
        if ev_mode != "aligned":
            self.say(f"        근거 정렬: {ev_mode} ({hit}/{len(ch)}항목) — "
                     f"프롬프트가 '지어내지 말 것'을 명시합니다")
        # 실패한 왕복의 프롬프트는 judge.copilot_send 가 report\judge_refine{n}_{tag}.md 로 남긴다(회사 Copilot 에 붙여 넣기용 —
        # 성공 왕복의 파일은 지운다). 여기서 따로 쓰지 않는다.
        return build_prompt(ch, sub_ev, self.model_names, ev_mode, ov)

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
        res = res if isinstance(res, dict) else {}
        if res.get("phase") == "blocked":
            # 개인정보 관문(G3) — 보내지 않았다. 재시도·반분 없이 이 청크의 항목은 원본 그대로 둔다(실패 계수 밖)
            self.st["gated_items"] = self.st.get("gated_items", 0) + len({i for i, _ in ch} - set(ov))
            self.st["_skipped"] = True
            self.say("        개인정보 관문에 걸려 보내지 않았습니다 — 이 청크의 항목은 원본 그대로 둡니다")
            return 0
        self.st["roundtrips"] += 1
        got, info = [], {}
        if res.get("ok"):
            got, info = extract_items_ex(res.get("reply", ""))
            if info.get("repaired"):
                self.st["repaired"] += 1
                self.say(f"        잘린 응답 복구 — {len(got)}개 항목")
            elif not got:
                self.say("        응답에서 JSON을 찾지 못함")
                _judge.note_bad_reply()
            elif res.get("cut"):
                self.say(f"        생성 중단 응답 — {len(got)}개 항목 회수")
        else:
            self.say(f"        {res.get('error', '')} — {str(res.get('hint', ''))[:80]}")
            # 사람이 손대야 풀리는 실패(로그인 필요·Edge 없음)는 남은 청크를 다 물어도 똑같다 —
            # judge 와 같은 관문을 둔다. 정제 없이도 판정 결과는 그대로 남는다.
            _w, _h, _fatal = _details.explain_failure(res)
            if _fatal:
                self.st["fatal"] = f"{_w} — {_h}"
                # 예전엔 이 표식을 아무도 읽지 않아(감사 확정 — 죽은 관문) 로그인 필요 상태에서도 남은 청크를
                # 전부 보냈다. 여기서 접는다: 이 청크의 항목은 실패로 세고, 반분 재시도도 하지 않는다.
                self.st["failed_items"] += len({i for i, _ in ch} - set(ov))
                return 0
            # 일시 실패(사용량 제한·무응답·시간 초과 …)는 copilot_send 가 이미 쉬고 같은 청크를 다시 보냈다(cooldowns) —
            # 반으로 나눠 또 보내면 막힌 Copilot 에 왕복만 늘어난다(마감 직전이라 쉬지 못했으면 최대 7번). 원본 그대로 둔다.
            if res.get("cooldowns") or _judge._is_transient(res):
                self.st["failed_items"] += len({i for i, _ in ch} - set(ov))
                return 0
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


GENERIC_L2 = ("", "공통", "미지정")   # 정제가 다른 과제로 옮겨도 되는 원본 과제(실제 과제가 아닌 자리)


def task_guard_groups(groups, rows):
    """정제 병합의 과제 관문(LM30 2026-10-27) → (새 그룹 목록, 나눈 그룹 수).
    한 그룹의 구성원이 서로 다른 과제(Level 2 — ukey2, '공통'·'미지정' 제외)를 가지면 과제별로 나눈다 — 정제가 과제가 다른
    '주간보고'·'일정 조율' 끼리 합쳐 두 과제가 하나로 묶이던 것. '공통'·'미지정' 구성원은 AI 가 고른 과제(l2)가 그 그룹의 과제
    가운데 하나이면 그쪽에, 아니면 따로 남는다. 각 그룹에 own(구성원의 과제 — 없으면 None)을 붙인다: own 이 있으면 정제가
    고른 과제 이름 대신 own 을 쓴다(과제 이름은 '공통'·'미지정' 일 때만 바꿀 수 있다)."""
    out, n_split = [], 0

    def _own(ids):
        return _majority((rows[i].get("Level 2"), rows[i].get("share")) for i in ids)
    for g in groups:
        by, gen = {}, []
        for i in sorted(g["idxs"]):
            l2 = str(rows[i].get("Level 2") or "").strip()
            if l2 in GENERIC_L2:
                gen.append(i)
            else:
                by.setdefault(ukey2(l2), []).append(i)
        if len(by) <= 1:
            ids = next(iter(by.values()), [])
            out.append(dict(g, own=(_own(ids) if ids else None)))
            continue
        n_split += 1
        lk = ukey2(str(_g(g["it"], "level2") or "").strip())
        for k, ids in by.items():
            part = ids + (gen if k == lk else [])
            out.append({"idxs": set(part), "it": g["it"], "pick_share": sum(_f(rows[i].get("share")) for i in part),
                        "own": _own(ids)})
        if gen and lk not in by:
            out.append({"idxs": set(gen), "it": g["it"], "pick_share": sum(_f(rows[i].get("share")) for i in gen),
                        "own": None})
    return out, n_split


def _pinned_projects():
    r"""지정 과제(config\projects.json) → (이름 목록, {ukey2(이름): 상위}) — 과제명 관문 통과·상위 채움용(못 읽으면 빈 값)."""
    try:
        import projmap
        ps = projmap.load_user_projects(ROOT)
    except Exception:  # noqa: BLE001 - 지정을 못 읽어도 정제는 계속(관문·규칙 상위만)
        return [], {}
    return ([p["name"] for p in ps],
            {ukey2(p["name"]): snap1(p.get("level1")) for p in ps if snap1(p.get("level1"))})


def _guard_lv2(lv2, vote, people=(), pinned=()):
    """정제가 고른 과제명(Level 2) 관문 — 사람 이름·공지류(인사발령 …)·행정 표기는 과제가 아니다.
    걸리면 원본 다수결(vote()), 그것도 걸리면 '공통'. 빈칸·'미지정'·지정 과제는 그대로."""
    if not lv2 or lv2 == "미지정" or _details.task_name_ok(lv2, people, pinned):
        return lv2
    v = str(vote() or "").strip() or "공통"
    return v if _details.task_name_ok(v, people, pinned) else "공통"


def _stage_budget(floor_min=15.0):
    r"""core.budget.stage_budget 위임 — 단계 시간 예산(config.aiStageBudgetMin · 전체 마감 AF32_AI_DEADLINE)."""
    from budget import stage_budget
    return stage_budget(floor_min=floor_min, root=ROOT, now=time.time, mono=time.monotonic)


_FAM_RX = re.compile(r"([^\s·\d][^·\d]*?)\s*(\d+)")


def _fams(s):
    """근거 글('메일 12 · 회의 3') → Counter({계열: 건수})."""
    c = Counter()
    for name, n in _FAM_RX.findall(str(s or "")):
        name = name.strip()
        if name:
            c[name] += int(n)
    return c


def _confidence(fams, n):
    """확신도 — judge 와 같은 규칙(출처 계열 수·근거건수): 상 = 2계열·5건 이상 · 중 = 2계열 또는 3건 이상 · 하."""
    return _judge._confidence(fams, n)


def main():
    d0, d1 = arg("--from"), arg("--to")
    rc = _details.consent_gate("refine", ROOT) or _details.restricted_gate("refine", ROOT)   # 다른 사용자의 자료 4 · 지우는 중 3 · 제한 고객 목록 없음 4
    if rc:
        return rc
    tag = f"{d0.replace('-','')}-{d1.replace('-','')}"
    rep = os.path.join(ROOT, "report")
    from stage_state import open_stage
    _ss = open_stage(rep, tag, "refine")
    src = os.path.join(rep, f"work_rows_{tag}.csv")
    if not os.path.exists(src) or not _details.af32_tag_ok(tag, rep):
        why = ("입력 없음 — 먼저 mine.py·judge.py 를 실행하세요" if not os.path.exists(src)
               else f"report\\run_meta_{tag}.json 에 {_judge.PRODUCT} 표식이 없어 이 기간 자료를 쓰지 않습니다")
        print(f"[refine] {why} ({src})")
        if _ss is not None:
            _ss.finish("failed", stop_kind="fatal", reason=why)
        return 1
    with open(src, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    # 숫자 셀을 먼저 확정한다 — 빈칸·비숫자 셀 하나에 병합의 float()/int() 가 ValueError 로 죽지 않게. 0 으로 두고 행 수를
    # 로그·마지막 JSON(bad_rows)에 남긴다.
    bad_rows = 0
    for r in rows:
        if not all(_num_ok(r.get(k)) for k in ("share", "근거건수")):
            bad_rows += 1
        r["share"], r["근거건수"] = _f(r.get("share")), _i(r.get("근거건수"))
    if bad_rows:
        print(f"[refine] 숫자 변환 실패 {bad_rows}행 — share/근거건수 가 빈칸·비숫자(엑셀 재저장·손편집?) → 0 으로 두고 계속합니다")
    # 근거는 judge 가 판정 축으로 쓴 evidence_<tag>.md 에서 (Level 2, Level 3) 로 뽑는다.
    sig_by = load_evidence(rep, tag)
    print(f"[refine] 근거 원천: evidence_{tag}.md ({len(sig_by)}묶음)" if sig_by
          else f"[refine] 근거 없음(evidence_{tag}.md) — 항목 이름만으로 정제합니다")
    # 과제명 관문 — 사람 키는 signals 의 who 열과 G1 이 남긴 이름 해시(data\cache\name_hashes.json)에서 얻는다. 지정 과제는 늘 통과한다.
    people = _details.person_keys((r.get("who") for r in _details.read_signals(tag, rep)), ROOT)
    pinned, pin = _pinned_projects()
    # judge 가 확정한 과제 체계가 있으면 Level 2 재작명을 막는 제약으로 전달. 체계의 l1(상위)은 AI 가 상위를 비운
    # 행의 채움 재료다(details.level1_fill). 옛 체계에 남은 사람 이름·공지류는 제약 목록에서 뺀다. 프롬프트에는
    # G3 행 관문을 지난 사본만 싣는다(judge.sendable — 가린 이름은 가린 채 · 답의 가린 이름은 judge.unmask_name 이 되돌린다).
    ent_p = os.path.join(rep, f"entities_{tag}.json")
    model_names, l1_map = [], {}
    if os.path.exists(ent_p):
        try:
            with open(ent_p, encoding="utf-8-sig") as f:
                _ms = [m for m in json.load(f).get("models", []) if isinstance(m, dict) and m.get("name")]
            model_names = [m["name"] for m in _ms
                           if m.get("pinned") or _details.task_name_ok(m["name"], people, pinned)]
            l1_map = {ukey2(m["name"]): snap1(m.get("l1")) for m in _ms if snap1(m.get("l1"))}
        except (OSError, ValueError, AttributeError):
            pass
    send_names = list(dict.fromkeys(x for x in (_judge.sendable(n) for n in model_names) if x))
    # 항목이 많으면 한 번의 왕복으로는 응답이 잘리거나 실패한다 — 청크로 나눠 여러 번 돈다.
    # 실패한 청크는 '병합 없음'으로 두고 계속 진행한다(전부 버리지 않는다).
    # --chunk 명시 > config.copilotAuto.refineChunk > 20. 근거 슬라이스는 예산에 맞춰 잘린다.
    chunk_n = chunk_default("refineChunk", 20)
    idxed = list(enumerate(rows))
    plan = plan_chunks(idxed, chunk_n)
    print(f"[refine] {len(rows)}항목 → {len(plan)}회 왕복 (청크 {chunk_n}항목 · 겹침 {OV_N}항목 · "
          f"예산 {PROMPT_BUDGET:,}자)")
    rf = Refiner(tag, rep, sig_by, send_names)
    failed, consec, skipped = 0, 0, 0
    _dl, _bud = _stage_budget()
    _stopped = ""
    for ci, (ch, ov) in enumerate(plan):
        if _dl is not None and time.monotonic() > _dl and not rf.st.get("fatal"):
            # 예산 초과 — 루프만 정상 종료한다. 아래 병합·저장 경로를 그대로 타므로 여기까지 정제한 것은 남는다.
            if _ss is not None:
                _ss.note_resume(pending=len(plan) - ci)
            _stopped = (f"시간 예산 {_bud:.0f}분을 넘겨 남은 {len(plan) - ci}청크를 보내지 않았습니다 — "
                        "여기까지 정제한 것은 저장했습니다 — 정제는 이름 병합 특성상 전량 기준이라, "
                        "다시 실행하면 처음부터 다시 정제합니다(config.aiStageBudgetMin 으로 조절)")
            print(f"[refine] {_stopped}")
            for _ch2, _ov2 in plan[ci:]:
                rf.st["failed_items"] += len({i for i, _ in _ch2} - set(_ov2))
            break
        if rf.st.get("fatal"):
            # 사람이 손대야 풀리는 실패(로그인 필요 등) — 남은 청크는 보내지 않는다(judge 와 같은 관문).
            rf.st["failed_items"] += len({i for i, _ in ch} - set(ov))
            continue
        progress("AI 정제", ci, len(plan))
        before = len(rf.items)
        rf.st["_skipped"] = False
        rf.run(ch, ov, str(ci + 1))
        if len(rf.items) == before and rf.st.pop("_skipped", False):
            skipped += 1                 # 개인정보 관문 — 실패가 아니므로 연속 실패 계수에 넣지 않는다
        elif len(rf.items) == before:
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
            "bad_rows": bad_rows,
            # G3 — 개인정보 관문에 막혀 보내지 않은 청크·원본 그대로 둔 항목(실패 아님)
            "skipped_chunks": skipped, "gated_items": st.get("gated_items", 0)}
    if _stopped:                     # 화면이 '왜 일부만 정제됐는지' 를 말할 수 있게 마지막 JSON 에 싣는다
        tail["stopped"] = _stopped
        tail["hint"] = _stopped
    if not rf.items:
        print("[refine] 정제된 항목이 없습니다 — 판정 결과(work_rows)를 그대로 둡니다")
        print("        실패한 왕복의 프롬프트는 report\\judge_refine*_<기간>.md 에 남습니다 — 손으로 붙여 쓸 때는 "
              "회사 M365 Copilot(m365.cloud.microsoft, 회사 계정)에만 붙여 넣으세요")
        _chat_note()
        print(json.dumps(dict(tail, ok=False, error="정제 0건"), ensure_ascii=False))
        if _ss is not None:
            _ss.finish("failed", stop_kind="fatal", reason="정제 0건")
        return 1
    if failed or st["repaired"] or st["retries"]:
        print(f"[refine] 청크 {failed}/{len(plan)} 실패 · 왕복 {st['roundtrips']}회(재시도 {st['retries']}) · "
              f"잘린 응답 복구 {st['repaired']}회 · 원본 유지 항목 {st['failed_items']} — 해당 항목은 원본 그대로 보존됩니다")

    # 병합 + 비중 재정규화(AI 가 총량을 바꾸지 못하게 규칙이 통제). 과제명(Level 2)은 기존 이름으로 스냅한다 — AI 가 새 이름을
    # 지어내면 정제본과 판정 피벗의 과제 축이 갈라진다. 신원 축은 ukey2(judge·flow 와 같은 축).
    known_lv2 = {ukey2(r.get("Level 2")) for r in rows} | {ukey2(n) for n in model_names}
    groups, owner = merge_groups(rf.items, rows)
    # 과제 관문 — 과제가 다른 항목을 합친 병합은 과제별로 나누고, 과제 이름은 구성원의 과제를 지킨다
    groups, n_split = task_guard_groups(groups, rows)
    if n_split:
        print(f"[refine] 과제가 다른 항목을 합친 병합 {n_split}건은 과제별로 나눴습니다(같은 과제 안에서만 합칩니다)")
    final = []
    for g in groups:
        it, idxs = g["it"], sorted(g["idxs"])
        if _g(it, "work") is False:
            continue

        def _vote(col, ids=idxs):
            """구성원 행의 col 다수결 — 동률이면 비중 큰 행의 값(결정적)"""
            return _majority((rows[i].get(col), rows[i].get("share")) for i in ids)
        lv2 = _judge.unmask_name(str(_g(it, "level2") or "").strip())   # 가려 보낸 과제 이름이면 원래 이름으로
        # 스냅은 judge 체계(entities)가 있을 때만 — 축을 맞출 피벗이 있는 경우다.
        if model_names and ukey2(lv2) not in known_lv2:     # AI 개명 → 원본 다수결로
            lv2 = _vote("Level 2") or "공통"
        elif not lv2:
            lv2 = "미지정"
        lv2 = _guard_lv2(lv2, lambda: _vote("Level 2"), people, pinned)
        # 구성원의 과제가 '공통'·'미지정' 이 아니면 정제가 다른 과제로 옮기지 못한다
        if g.get("own") and ukey2(lv2) != ukey2(g["own"]):
            lv2 = g["own"]
        # level3 는 실제 업무 항목명 — AI 가 비웠거나 활동 범주로 축약해 오면 원본 세부업무명(다수결)을 지킨다.
        # 범주는 '활동' 열이 따로 담는다. 행정 표기·사람 이름이 든 이름도 받지 않는다(details.detail_name_ok·is_person_name).
        lv3 = str(_g(it, "level3") or "").strip()
        if (not lv3 or lv3 in ACT_CATS or not _details.detail_name_ok(lv3)
                or _details.is_person_name(lv3, people)):
            lv3 = _vote("Level 3") or ("" if _details.is_person_name(lv3, people) else lv3) or "기타"
        act = str(_g(it, "activity") or "").strip()
        # 상세설명은 AI 가 쓴 글 — 사람 이름(G1 이름 해시)은 [사람] 으로(D8)
        detail = _details.mask_people(re.sub(r"\s+", " ", str(_g(it, "detail") or "")).strip()[:DETAIL_MAX * 2], people)
        final.append({"유형": _vote("유형"), "활동": act if act in ACT_CATS else "",
                      # 상위는 AI 판정 우선, 비었을 때만 채움(지정 상위 > 체계 l1 > 규칙 > 과제명이 곧 범주)
                      "Level 1": (snap1(_g(it, "level1"))
                                  or _details.level1_fill(lv2, f"{lv3} {detail}", l1_map, pin, ROOT)),
                      "Level 2": lv2, "Level 3": lv3, "상세설명": detail,
                      "share": sum(_f(rows[i].get("share")) for i in idxs),
                      "근거건수": sum(_i(rows[i].get("근거건수")) for i in idxs),
                      "_fam": sum((_fams(rows[i].get("근거")) for i in idxs), Counter()),
                      # 정제 행이 덮은 원본 (Level 2, Level 3) — refine_map 용(CSV 열에는 안 나간다)
                      "_orig": [(str(rows[i].get("Level 2") or ""), str(rows[i].get("Level 3") or "")) for i in idxs]})
    for i, r in enumerate(rows):                      # AI가 언급 안 한 항목은 그대로 보존
        if i not in owner:
            final.append({"유형": r.get("유형", ""), "활동": r.get("활동", ""),
                          # AI 가 언급하지 않은 행 — 먼저 기존 Level 1 을 보존한다(옛 이름·수기 값을 snap1 로 접어)
                          "Level 1": (snap1(r.get("Level 1", ""))
                                      or _details.level1_fill(r.get("Level 2", ""), r.get("Level 3", ""),
                                                              l1_map, pin, ROOT)),
                          "Level 2": r.get("Level 2", ""), "Level 3": r.get("Level 3", ""),
                          "상세설명": "", "share": _f(r.get("share")), "근거건수": _i(r.get("근거건수")),
                          "_fam": _fams(r.get("근거")),
                          "_orig": [(str(r.get("Level 2") or ""), str(r.get("Level 3") or ""))]})
    # 같은 (과제, 담당업무)가 두 행으로 남는 것을 접는다 — 청크가 달라 각각 다른 이름으로 왔거나, 겹침 항목이 따로 판정된 경우다.
    # 접는 축은 judge·flow 와 같은 ukey2/ukey3. 비중·근거건수는 합하고 대표 표기·설명은 비중 큰 쪽을 쓴다.
    _fold, _order = {}, []
    for f in final:
        k = (ukey2(f.get("Level 2")), ukey3(f.get("Level 3")))
        g = _fold.get(k)
        if g is None:
            _fold[k] = f
            _order.append(k)
            continue
        if f["share"] > g["share"]:
            for col in ("Level 1", "Level 2", "Level 3", "상세설명", "활동", "유형"):
                if str(f.get(col) or "").strip():
                    g[col] = f[col]
        else:
            for col in ("Level 1", "상세설명", "활동", "유형"):
                if not str(g.get(col) or "").strip() and str(f.get(col) or "").strip():
                    g[col] = f[col]
        g["share"] = _f(g.get("share")) + _f(f.get("share"))
        g["근거건수"] = _i(g.get("근거건수")) + _i(f.get("근거건수"))
        g["_fam"] = g["_fam"] + f["_fam"]
        g["_orig"] = (g.get("_orig") or []) + (f.get("_orig") or [])
    if len(_fold) < len(final):
        print(f"[refine] 같은 업무로 판정된 {len(final) - len(_fold)}행을 접었습니다 "
              "(청크가 달라 따로 온 같은 과제·담당업무)")
    final = [_fold[k] for k in _order]
    if len(final) > len(rows):
        # 정제는 행을 합칠 수만 있고 늘릴 수 없다 — 늘었다면 응답 번호가 중복된 것이다.
        print(f"[refine] 이상: {len(rows)}항목이 {len(final)}항목으로 늘었습니다 "
              "(응답의 항목번호 중복) — 정제본을 쓰지 않고 판정 결과를 유지합니다")
        _chat_note()
        print(json.dumps(dict(tail, ok=False, error="항목 수 증가"), ensure_ascii=False))
        if _ss is not None:
            _ss.finish("failed", stop_kind="fatal", reason="항목 수 증가")
        return 1
    tot = sum(f["share"] for f in final) or 1.0
    fn = rows[0].get("Function", "") if rows else ""
    for f in final:
        f["share"] = round(f["share"] / tot, 4)
        f["Function"] = fn
        f["근거"] = " · ".join(f"{s} {n}" for s, n in f["_fam"].most_common())
        f["확신도"] = _confidence(len(f["_fam"]), f["근거건수"])
        f["ax"] = _details.ax_flag(f"{f['Level 2']} {f['Level 3']} {f.get('상세설명') or ''}")
        f["field"] = _details.field_of(f"{f['Level 2']} {f['Level 3']}")
    final.sort(key=lambda x: (-x["share"], -x["근거건수"]))

    dst = os.path.join(rep, f"work_rows_{tag}_refined.csv")
    _judge._write_csv_atomic(dst, REFINED_COLS, final)
    # 정제 행 → 원본 (Level 2, Level 3) 매핑 — UI 오할당 제외가 정제·병합으로 이름이 바뀐 행도 signals 의 원본 쌍으로 풀어
    # 구성원 신호를 전부 제외한다. 정제본과 운명을 같이한다. 같은 이름의 정제 행이 둘이면 원본 쌍을 합친다.
    rmap = {}
    for r in final:
        key = f"{r.get('Level 2', '')}/{r.get('Level 3', '')}"
        lst = rmap.setdefault(key, [])
        for a, b in r.get("_orig", []):
            if [a, b] not in lst:
                lst.append([a, b])
    try:
        _judge._write_json_atomic(os.path.join(rep, f"refine_map_{tag}.json"),
                                  {"product": _judge.PRODUCT, "tag": tag, "generated": time.strftime("%Y-%m-%d"),
                                   "rows_file": os.path.basename(src), "refined_file": os.path.basename(dst),
                                   "map": rmap})
    except OSError as e:
        print(f"[refine] 정제 매핑(refine_map) 저장 실패({type(e).__name__}) — 오할당 제외는 이름 일치로만 찾습니다")
    print(f"[refine] {len(rows)}항목 → {len(final)}항목 (병합 {len(rows)-len(final)})")
    for f in final[:8]:
        print(f"   {str(f.get('Level 2') or '')[:22]:23s} {str(f.get('Level 3') or '')[:12]:13s} "
              f"근거 {f['근거건수']:4d}건  {str(f.get('상세설명') or '')[:44]}")
    print(f"[refine] → {dst}")
    _chat_note()
    print(json.dumps(dict(tail, ok=True, rows=len(rows), refined=len(final)), ensure_ascii=False))
    if _ss is not None:
        if _stopped:
            _ss.finish("partial", stop_kind="budget", reason=_stopped)
        else:
            _ss.finish("done")
    return 2 if _stopped else 0


if __name__ == "__main__":
    sys.exit(main())
