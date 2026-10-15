# -*- coding: utf-8 -*-
r"""
agentic.py — Agentic AI 니즈 후보 발굴 (LoadMonitor29 — LM28 의 Agentic 과제 매칭에서 '발굴'만 남긴 판)

Copilot 에게 [본인 업무(#번호·과제·세부업무·유형·설명)]만 주고, 그 사람이 반복해서 하는 업무에서 Agentic AI 로 자동화할
만한 **니즈 후보**(new — 이름·동작 로직·발굴 사유·근거 업무)만 찾게 한다.
  · 팀 과제 목록과 맞춰 보지 않는다 — LM29 에는 과제 목록 파일(config\agentic_tasks.json)·적합률·과제별 로드가 없다.
  · 오할당(내 업무가 아닌데 내 업무로 분류된 행) 검증도 하지 않는다.
  · 팀 차원의 니즈 후보는 팀 취합(aggregate.merge_needs — 팀 화면·팀 통합 보고서)이 인원별 후보를 이름으로 모아 보여 준다.

LM28 agentic.py 에서 그대로 가져온 규칙:
  · 업무 행마다 실행 전체에서 고정된 '#번호'(MM 큰 순)를 붙여 보내고, 답의 근거 업무(work)는 번호로 받는다(이름 표기도 받는다:
    번호 → 이 묶음 행 이름 → 전체 행 이름 순). 근거는 그 행의 원본 mm_rows (과제, 세부업무) 쌍(keys — 정제 행이면 refine_map
    으로 되짚는다)으로 상한 없이 쌓는다. agenticMaxWork 는 화면에 보일 근거 업무 이름(work) 수의 상한일 뿐이다.
  · MM 은 프롬프트에 넣지 않는다(사람·MM 미전송 원칙). 후보에도 MM('대체 가능 MM≈')을 붙이지 않고 근거 행 수(evidence_rows)만 센다.
  · 업무 행을 8,300자 묶음으로 나눠 보낸다 — 묶음 경계는 앞 묶음 끝 3행(600자) 겹침, 겹친 행은 rows_analyzed 에 세지 않는다.
  · 묶음은 같은 채팅에서 이어 보낸다(fresh=None — 첫 왕복·실패 뒤·config.copilotAuto.chatTurns 마다만 새 채팅). 되풀이돼 섞여
    오는 앞 답은 strip_prompt_echo·find_json 이 걷어내고, 답을 해석하지 못하면 judge.note_bad_reply 로 다음 왕복을 새 채팅에서 연다.
  · 잘린 JSON·코드펜스·굽은 따옴표는 core/details.find_json 이 복구한다(부분 결과는 salvaged_chunks 로 센다). 프롬프트의 출력
    예시는 <...> 자리표시자라 되돌아온 프롬프트가 답으로 파싱되지 않는다.
  · 로그인 만료·Edge 미기동처럼 사람이 손대야 하는 실패와 Copilot 사용량 제한(hard)은 그 자리에서 접고, 그 밖의 실패는 연속
    3회면 접는다. 마지막 줄 JSON 의 error/hint 에 실제 사유를, stop_kind 에 중단 갈래를 싣는다(rc 0 완료 · 2 부분 · 1 실패).
  · 답이 왔는데 해석 못 했거나 잘려 건질 게 없거나 응답이 없는 묶음(parse·no_reply)만 반으로 나눠 1회 더 묻는다(적응 분할).
    일시 오류(copilot_error·시간 초과 등)는 나누지 않고 coolDownSec(기본 90초) 쉰 뒤 같은 묶음을 한 번만 다시 보낸다 — 드라이버가
    이미 쉬고 다시 보냈으면(결과의 cooldowns) 또 쉬지 않는다. 쉬는 초는 이번 실행의 쉬는 시간 합계(copilotAuto.runWaitMaxSec —
    judge.wait_room) 안이고, 다 썼으면 쉬지 않고 바로 한 번 더 보낸다.
  · 신호의 80%(config.agentic.ruleRowShare) 이상이 규칙 판정(AI 판정이 중단돼 규칙으로 남은 행)인 업무는 보내지 않는다
    (rows_rule · 'AI 판정 대기') — 판정이 회복되면([재분석만]) 다음 실행이 보낸다.
  · G3 — 업무 행의 상세설명은 관문(judge.g3_rows)을 거친 재정제 사본으로 보내고, 자기 줄이 최종 검사(judge.g3_prompt)에
    걸리는 행은 **그 행만** 빼고 보낸다(판정 끝으로 두고 gate_skipped_rows 로 센다).
  · 묶음이 끝날 때마다 저장하고(중단돼도 그때까지의 결과가 남는다), rows_done 으로 **다음 실행은 남은 행만 이어서** 보낸다
    (--redo 면 처음부터). 행 식별자는 '과제|세부업무|유형'(MM 제외). --carry(run.py 가 늘 붙인다)면 기간 끝날짜가 바뀌어 오늘
    파일이 없을 때 같은 시작일의 최근 결과(matched_since 7일 이내)를 이어받고, 다 끝난 결과는 왕복 없이 근거 행 수만 다시 센다.
    화면의 [니즈 후보 발굴 실행](--carry 없음)은 다 끝난 결과면 처음부터 다시 묻는다.
  · 모든 묶음이 정상인데 후보가 0건이면 실패가 아니라 '후보 없음' 결과다.
  · 프롬프트 첫 줄의 팀 업무 영역은 config.agentic.domainHint(비면 일반 문구) — 조직 고유 문구를 코드에 두지 않는다.

  python agentic.py                          # 최신 결과 대상
  python agentic.py --from ... --to ... [--redo] [--carry] [--budget 8300] [--max-chunks 30]
  python agentic.py --recalc [--from --to]   # 왕복 없이 후보의 근거 행 수(evidence_rows)만 다시 센다

출력: report\agentic_<기간>.json → 대시보드 'Agentic AI' 탭 · 리포트 · 분석리포트 · 팀 취합(팀 Agentic AI 니즈 후보)
  {tag, kind:"needs", new[{name,logic,reason,work,evidence_rows,evidence_missing,keys[원본 '과제␟세부업무'],missing[못 찾은 원문]}],
   rows_analyzed, rows_total, rows_pending, rows_done[], rows_rule[], rule_rows, rule_share_cut, rows_gate[], row_keys{sent,rule,gate},
   partial, chunks, failed_chunks, salvaged_chunks, gate_skipped_rows, note, last_error, generated, carried_from, matched_since,
   stop_kind, cooldowns}
  LM28 이 만든 파일(match·misassigned·mm_recalc 가 든 것)을 읽으면 그 키는 버리고 후보(new)만 쓴다(needs_only).
"""
import glob
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from progress import progress  # noqa: E402
import details  # noqa: E402
from details import fold, _fresh_refined  # noqa: E402,F401  (호환: 옛 이름 유지)

PROMPT_BUDGET = 8300           # 한 왕복 프롬프트 글자 상한 — flow 와 같은 값(드라이버 분할 문턱 SAFE_PROMPT 9,000 − 서약 아래).
OVERLAY_ROWS = 3               # 묶음 경계 겹침 행 수
OVERLAY_CHARS = 600            # 겹침 행 글자 상한 (예산 안에 포함해 계산한다)
MAX_WORK = 60                  # 후보별 근거 업무 **표시** 상한(config.copilotAuto.agenticMaxWork) — 근거 키(keys)는 상한 없음
MAX_CHUNKS = 30                # 한 실행의 묶음 상한 — 초과분은 rows_done 을 남겨 다음 실행이 이어서
MAX_CONSEC_FAIL = 3            # 연속 실패 상한 — Copilot 이 안 되는 날 남은 묶음을 헛되이 기다리지 않게
SPLIT_MIN_ROWS = 4             # 이 이상인 묶음이 답 없이/잘려 실패하면 반으로 나눠 1회 재시도
RULE_ROW_SHARE = 0.8           # 행의 신호 중 규칙 판정 비중이 이 이상이면 보내지 않는다(config.agentic.ruleRowShare)
CARRY_DAYS = 7                 # --carry 로 다른 기간 결과를 이어받는 상한(일) — matched_since 기준
COOL_DOWN_SEC = 90             # 일시 오류 뒤 같은 묶음을 다시 보내기 전 쉬는 시간(초) — config.copilotAuto.coolDownSec
MISSING_CAP = 12               # 후보별 '못 찾은 업무 이름' 보관 상한
NEW_CAP = 12                   # 저장하는 후보 수 상한 — 근거 행이 많은 후보부터(LM28 은 발견 순 8건)
KIND = "needs"                 # 결과 파일의 종류 표식 — LM28 의 과제 매칭 결과와 구분한다
# 저장 파일·화면·보고서에 남기는 키 — 이 밖의 키(LM28 의 match·misassigned·mm_recalc·axes …)는 needs_only 가 버린다
NEEDS_KEYS = ("tag", "kind", "new", "rows_analyzed", "rows_total", "rows_pending", "rows_done", "rows_rule", "rule_rows",
              "rule_share_cut", "rows_gate", "row_keys", "partial", "chunks", "failed_chunks", "salvaged_chunks",
              "gate_skipped_rows", "note", "last_error", "generated", "carried_from", "matched_since", "stop_kind",
              "cooldowns")


def _chat_note():
    """로그용 — 묶음을 같은 채팅에서 이어 보내는 정책(config.copilotAuto.chatTurns)"""
    try:
        import judge
        n = judge.chat_turns()
    except Exception:  # noqa: BLE001 - 로그 문구가 실행을 막지 않게
        return ""
    return " — 설정 chatTurns=0: 묶음마다 새 채팅" if n <= 0 else f" · 첫 왕복·실패 뒤·{n}회마다 새 채팅"


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def _cfg_int(key, default):
    """config.copilotAuto.<key> 정수 — 없거나 이상하면 default."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            v = (json.load(f).get("copilotAuto") or {}).get(key)
        n = int(v)
        return n if n > 0 else int(default)
    except (OSError, ValueError, TypeError, AttributeError):
        return int(default)


def _cool_sec():
    """config.copilotAuto.coolDownSec — 일시 오류 뒤 쉬는 초(0 = 쉬지 않고 바로 한 번 더). 없거나 이상하면 COOL_DOWN_SEC."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            v = (json.load(f).get("copilotAuto") or {}).get("coolDownSec")
        return COOL_DOWN_SEC if v is None else max(0, int(v))
    except (OSError, ValueError, TypeError, AttributeError):
        return COOL_DOWN_SEC


def rule_cut():
    """규칙 판정 비중 문턱 — config.agentic.ruleRowShare(기본 RULE_ROW_SHARE). 0 초과 1 이하만 받는다."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            x = float((json.load(f).get("agentic") or {}).get("ruleRowShare"))
        return x if 0 < x <= 1 else RULE_ROW_SHARE
    except (OSError, ValueError, TypeError, AttributeError):
        return RULE_ROW_SHARE


def latest_tag():
    fs = sorted(glob.glob(os.path.join(ROOT, "report", "mm_meta_*.json")), key=os.path.getmtime)
    return os.path.basename(fs[-1])[len("mm_meta_"):-len(".json")] if fs else ""


DOMAIN_HINT_DEFAULT = "엔지니어링 팀"


def domain_hint():
    """config.agentic.domainHint — 프롬프트 첫 줄에 넣을 팀 업무 영역 한 줄(특정 팀 문구를 코드에 두지 않는다).
    비었거나 못 읽으면 일반 문구. 60자·한 줄로 자른다."""
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            v = (json.load(f).get("agentic") or {}).get("domainHint")
    except (OSError, ValueError, TypeError, AttributeError):
        v = ""
    return " ".join(str(v or "").split())[:60]


def g3_part(rows):
    """G3 관문 — 업무 행의 상세설명·근거를 재정제한 사본(자격증명·고위험 잔여·카나리아 행은 뺀다). 과제·세부업무 이름은
    답의 표기와 대조하는 열쇠라 바꾸지 않는다(그 이름의 잔여는 행 줄 단위 최종 검사가 본다 — _run 의 ask)."""
    if not rows:
        return []
    import judge
    return judge.g3_rows(rows, ("상세설명", "근거"))[0]


def rfind_json(reply, want_key):
    """호환 — 정상 파싱 + 정규화 + 잘린 JSON 복구까지(core/details.find_json)."""
    return details.find_json(reply, want_key)[0]


# ── 프롬프트 ───────────────────────────────────────────────────────────────
def _one_line(s, n):
    """이름·설명 속 개행·탭을 공백으로 — 한 행이 여러 줄로 갈라지면 묶음 형식이 깨진다."""
    return " ".join(str(s or "").split())[:n]


def row_line(r):
    """행 한 줄 — MM 은 넣지 않는다. '· #번호 과제 / 세부업무 / 유형 — 설명[:50]'
    번호(_rid)는 실행 전체에서 고정된 행 번호 — 답은 근거 업무를 이 번호로 돌려준다(이름 대조 대신 번호 대조). 번호가 없는
    행(옛 호출)은 '#' 없이."""
    rid = r.get("_rid")
    s = ("· " + (f"#{rid} " if rid else "")
         + f"{_one_line(r.get('Level 2'), 40)} / {_one_line(r.get('Level 3'), 60)} / {_one_line(r.get('유형'), 10)}")
    d = _one_line(r.get("상세설명"), 50)
    if d:
        s += f" — {d}"
    return s


def row_key(r):
    return (fold(r.get("Level 2")), fold(r.get("Level 3")))


def row_sig(r):
    """행 식별자(이어서 판정용) — '과제|세부업무|유형'. MM 은 넣지 않는다 — 재판정·다음 날 MM 이 바뀌어도 이어진다."""
    return (f"{_one_line(r.get('Level 2'), 80)}|{_one_line(r.get('Level 3'), 120)}|"
            f"{_one_line(r.get('유형'), 10)}")


_SIG_MM = re.compile(r"\|-?\d+\.\d{3}$")


def _sig_norm(s):
    """옛 결과의 행 식별자('…|유형|0.123')에서 MM 꼬리를 뗀다 — 지금 식별자와 같은 꼴로."""
    return _SIG_MM.sub("", str(s or ""))


def ag_prompt(rows):
    """rows: 한 팀원의 업무 행 목록(MM 미전송) → 니즈 후보 발굴 프롬프트. 팀 과제 목록은 넣지 않는다(LM29).
    출력 예시는 <...> 자리표시자 — **예시 자체가 유효한 JSON 이 아니게** 한다: 회수가 어긋나 우리 프롬프트가 되돌아와도
    예시가 답으로 파싱되지 않는다. 근거 업무는 줄 앞의 '#번호' 로 답하게 한다."""
    hint = domain_hint()
    lines = [
        (f"당신은 '{hint}' 업무를 하는 팀의 Agentic AI 니즈 발굴 분석가입니다." if hint
         else f"당신은 {DOMAIN_HINT_DEFAULT}의 Agentic AI 니즈 발굴 분석가입니다."),
        "[현재 업무]는 한 팀원의 실제 업무(PC 흔적 기반 자동 분석) 목록입니다. 각 줄 앞의 '#번호' 가 그 업무의 번호입니다.",
        "",
        "이 사람이 반복해서 하는 업무에서 Agentic AI 로 자동화하거나 도울 만한 니즈 후보(new)를 찾으세요:",
        "   name(후보 이름) · logic(무엇을 입력받아 무엇을 자동화하는지) · reason(왜 니즈인지 — 반복·분량 등 근거 1~2문장) ·",
        "   work(근거가 된 업무의 **번호** 목록 — 줄 앞의 '#번호' 를 그대로, 예: \"#12\". 번호가 없는 줄만 세부업무 표기 그대로).",
        "   근거가 약하면 빈 배열로 두세요. 억지로 만들지 마세요.",
        "",
        "출력은 JSON 하나만 (설명 문장·코드펜스 금지, 짧게). <...> 자리에 실제 값을 넣으세요:",
        '{"new":[{"name":<후보 이름>,"logic":<자동화 로직>,"reason":<발굴 사유>,"work":[<"#번호">]}]}',
        "",
        "[현재 업무 — #번호 과제 / 세부업무 / 유형 — 설명]  (MM 순)",
    ]
    for r in rows:
        lines.append(row_line(r))
    return "\n".join(lines)


def split_rows(rows, budget=PROMPT_BUDGET, ov_n=OVERLAY_ROWS, ov_chars=OVERLAY_CHARS):
    """업무 행을 프롬프트 예산 단위로 나눈다 → [(rows_part, n_new)].

    MM 내림차순으로 정렬해 큰 업무가 앞 묶음에 오게 하고, 머리말+겹침 여유(ov_chars)+행 합이 budget 을 넘으면 자른다.
    다음 묶음 앞에는 앞 묶음 끝 ov_n 행(ov_chars 이내)을 겹쳐 붙인다(오버레이) — 겹친 행은 두 번 보여도 병합이 흡수하고,
    n_new(실판정 행 수)에는 세지 않는다."""
    rows = sorted(rows, key=lambda r: -(r["_mm"] if "_mm" in r else details._f(r.get("mm"))))
    base = len(ag_prompt([])) + ov_chars
    sizes = {id(r): len(row_line(r)) + 1 for r in rows}
    chunks, cur, size = [], [], 0
    for r in rows:
        one = sizes[id(r)]
        if cur and base + size + one > budget:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += one
    if cur:
        chunks.append(cur)
    parts = []
    for i, ch in enumerate(chunks):
        if i == 0:
            parts.append((ch, len(ch)))
            continue
        ov, ov_sz = [], 0
        for r in reversed(chunks[i - 1]):
            s1 = sizes[id(r)]
            if len(ov) >= ov_n or ov_sz + s1 > ov_chars:
                break
            ov.insert(0, r)
            ov_sz += s1
        parts.append((ov + ch, len(ch)))
    return parts


# ── 원본 축(키) ────────────────────────────────────────────────────────────
def key_of(a, b):
    """원본 mm_rows (과제, 세부업무) → 키 문자열 '과제␟세부업무'(details.KEY_SEP — 세부업무 병합 맵과 같은 구분자)."""
    return f"{a}{details.KEY_SEP}{b}"


def split_key(k):
    a, _sep, b = str(k or "").partition(details.KEY_SEP)
    return a.strip(), b.strip()


def _loose(a, b):
    """느슨한 비교 축 — 과제는 ukey2, 세부업무는 ukey3(띄어쓰기·구분자 변형을 같게)."""
    return (details.ukey2(a or "공통"), details.ukey3(b))


def _pairs_of(r):
    """행 → 신호 축(원본 mm_rows) (과제, 세부업무) 쌍들. 정제 행이면 refine_map 의 원본 쌍(_pairs), 아니면 자기 이름
    (세부업무 병합 맵을 적용하기 전 이름 _raw3)."""
    ps = r.get("_pairs")
    if ps:
        return [(str(a or "").strip(), str(b or "").strip()) for a, b in ps]
    return [((r.get("Level 2") or "").strip(), str(r.get("_raw3") or r.get("Level 3") or "").strip())]


def attach_pairs(rows, tag, rep=None, rows_fn=""):
    """행마다 원본 쌍(_pairs)을 붙인다 — 정제본이면 refine_map 으로 되짚고(없는 행은 자기 이름), 원본이면 자기 이름."""
    rmap = details.refine_orig(tag, rep) if str(rows_fn or "").endswith("_refined.csv") else {}
    for r in rows:
        l2, l3 = (r.get("Level 2") or "").strip(), (r.get("Level 3") or "").strip()
        r["_pairs"] = (rmap.get(f"{r.get('Level 2') or ''}/{r.get('Level 3') or ''}".strip())
                       or rmap.get(f"{l2}/{l3}") or [(l2, l3)])
    return rows


def row_rule_share(r, rshare, pmm=None):
    """행의 규칙 판정 비중 — 원본 쌍마다 (규칙 신호 / 전체 신호)를 원본 MM 으로 가중 평균(MM 이 없으면 신호 수로).
    rshare = details.rule_share(signals) · pmm = {(과제, 세부업무): 원본 MM}."""
    num = den = 0.0
    n_rule = n_all = 0
    for a, b in _pairs_of(r):
        k = (a or "공통", b or "기타")
        nr, na = rshare.get(k, (0, 0))
        if not na:
            continue
        n_rule += nr
        n_all += na
        w = (pmm or {}).get(k, 0.0)
        num += w * nr / na
        den += w
    if den > 0:
        return num / den
    return (n_rule / n_all) if n_all else 0.0


# ── 응답 병합 ──────────────────────────────────────────────────────────────
def _placeholder(s):
    """프롬프트의 <...> 자리표시자를 그대로 베낀 값 — 근거·이름으로 쓰면 안 된다."""
    s = str(s or "").strip()
    return len(s) >= 2 and s[0] == "<" and s[-1] == ">"


def max_work():
    """후보별 근거 업무 **표시** 상한 — config.copilotAuto.agenticMaxWork(기본 MAX_WORK). 근거 키(keys)는 상한 없음."""
    return max(1, _cfg_int("agenticMaxWork", MAX_WORK))


_ID_LIST = re.compile(r"\s*#?\s*\d{1,5}\s*(?:[,;]\s*#?\s*\d{1,5}\s*)+")


def _clean_list(v, cap=None):
    """답의 업무 목록 정리 — 공백 정규화·자리표시자·중복 제거. cap: None = max_work(), 0 이하 = 상한 없음.
    형식이 조금 다른 답도 받는다: 쉼표·세미콜론·줄바꿈으로 이은 한 문자열, {name|work|id|row} 객체 항목, '#1, #2' 처럼
    번호를 한 항목에 이은 것."""
    # cap 기본값에 상수를 박아 두면 import 시점에 고정돼 설정이 무력해진다 — None 으로 받고 여기서 읽는다
    cap = max_work() if cap is None else cap
    if isinstance(v, str):
        v = re.split(r"[,;\n]", v)
    elif isinstance(v, dict):
        v = [v]
    if not isinstance(v, list):
        return []
    items = []
    for w in v:
        if isinstance(w, dict):
            w = next((w.get(k) for k in ("name", "work", "id", "row") if w.get(k) not in (None, "")), "")
        s = " ".join(str(w or "").split())
        if _ID_LIST.fullmatch(s):
            items += [x.strip() for x in re.split(r"[,;]", s)]
        else:
            items.append(s)
    out = []
    for s in items:
        if s and not _placeholder(s) and s not in out:
            out.append(s)
    return out[:cap] if cap and cap > 0 else out


_RID_RE = re.compile(r"^#?\s*(\d{1,5})\s*(?:번|행)?$")
_RID_HEAD = re.compile(r"^#\s*(\d{1,5})(?!\d)")


def resolve_work(items, by_rid=None, idx_chunk=None, idx_all=None):
    """답의 업무 목록 → (맞은 행들, 못 찾은 원문). '#n'·'n' 은 행 번호(by_rid)로, '#n 이름' 처럼 번호가 앞에 붙어도 번호로,
    그 밖은 이 묶음의 행 이름에서 먼저(idx_chunk), 없으면 전체 행 이름에서(idx_all — find_rows 의 표기 변형·부분 일치
    폴백) 찾는다. 행은 중복 없이 답의 순서대로."""
    by_rid = by_rid or {}
    hit, miss, seen = [], [], set()
    for w in items or []:
        s = str(w or "").strip()
        if not s:
            continue
        rs = []
        m = _RID_RE.match(s) or _RID_HEAD.match(s)
        if m and by_rid.get(int(m.group(1))) is not None:
            rs = [by_rid[int(m.group(1))]]
        else:
            if idx_chunk:
                rs = find_rows(s, *idx_chunk)
            if not rs and idx_all:
                rs = find_rows(s, *idx_all)
        if not rs:
            miss.append(s)
            continue
        for r in rs:
            if id(r) not in seen:
                seen.add(id(r))
                hit.append(r)
    return hit, miss


def _resolver(by_rid, part_rows, idx_all):
    """묶음 하나의 업무 해석기 — resolve_work 에 이 묶음 행 색인을 붙인 것."""
    idx_chunk = _row_index(part_rows) if part_rows else None
    return lambda items: resolve_work(items, by_rid, idx_chunk, idx_all)


def _add_hits(item, hit, miss=()):
    """근거 행을 후보에 싣는다 — keys(원본 쌍 · 상한 없음) · work(표시용 세부업무 이름 · max_work() 상한) ·
    missing(못 찾은 원문 이름 · MISSING_CAP 상한)."""
    keys = item.get("keys")
    if not isinstance(keys, set):
        keys = item["keys"] = set(keys or [])
    work = item.setdefault("work", [])
    cap = max_work()
    for r in hit:
        for a, b in _pairs_of(r):
            keys.add(key_of(a, b))
        nm = _one_line(r.get("Level 3"), 60)
        if nm and nm not in work and len(work) < cap:
            work.append(nm)
    ms = item.setdefault("missing", [])
    for w in miss:
        if w not in ms and len(ms) < MISSING_CAP:
            ms.append(w)


def _merge_hits(dst, src):
    """같은 후보의 근거를 합친다(keys 합집합 · work·missing 은 상한 안에서 이어 붙임)."""
    keys = dst.get("keys")
    if not isinstance(keys, set):
        keys = dst["keys"] = set(keys or [])
    keys.update(src.get("keys") or ())
    cap = max_work()
    for w in src.get("work") or []:
        if w not in dst.setdefault("work", []) and len(dst["work"]) < cap:
            dst["work"].append(w)
    for w in src.get("missing") or []:
        if w not in dst.setdefault("missing", []) and len(dst["missing"]) < MISSING_CAP:
            dst["missing"].append(w)


def _export(m):
    """누적판 후보 → 저장용 사본(keys 집합은 정렬 목록으로 — JSON 은 집합을 못 쓴다)."""
    e = dict(m)
    if isinstance(e.get("keys"), (set, list, tuple)):
        e["keys"] = sorted(str(k) for k in e["keys"])
    if "missing" in e:
        e["missing"] = list(e.get("missing") or [])[:MISSING_CAP]
    e["work"] = list(e.get("work") or [])
    return e


def merge_new(news, o, res=None):
    """한 묶음 응답(o)의 니즈 후보를 news(누적)에 합친다 → 이 묶음에서 새로 생긴 후보 수.
    같은 이름(fold — 띄어쓰기·구분자·대소문자 무시)이면 근거를 합치고, 비어 있던 로직·사유만 채운다. res(업무 해석기 —
    resolve_work)를 주면 근거를 행으로 풀어 keys(상한 없음)·work(표시 상한)·missing 에 쌓고, 없으면(옛 호출) work 이름을 합집합."""
    n = 0
    items = o.get("new")
    if isinstance(items, dict):                    # {"후보 이름": {...}}
        items = [(dict(v, name=v.get("name") or k) if isinstance(v, dict) else v) for k, v in items.items()]
    for x in (items if isinstance(items, list) else []):
        if not isinstance(x, dict) or not str(x.get("name") or "").strip() or _placeholder(x.get("name")):
            continue
        # 후보에는 MM 을 붙이지 않는다('대체 가능 MM≈' 은 만들지 않는다 — RP4). 근거는 recalc_evidence 의 evidence_rows.
        item = {"name": str(x["name"]).strip()[:60],
                "logic": "" if _placeholder(x.get("logic")) else str(x.get("logic") or "")[:300],
                "reason": "" if _placeholder(x.get("reason")) else str(x.get("reason") or "")[:300],
                "work": [] if res is not None else _clean_list(x.get("work"))}
        if res is not None:
            hit, miss = res(_clean_list(x.get("work"), cap=0))
            item["keys"], item["missing"] = set(), []
            _add_hits(item, hit, miss)
        dup = next((u for u in news if fold(u["name"]) == fold(item["name"])), None)
        if dup is None:
            news.append(item)
            n += 1
        else:
            if res is not None:
                _merge_hits(dup, item)
            else:
                for w in item["work"]:
                    if w not in dup["work"] and len(dup["work"]) < MAX_WORK:
                        dup["work"].append(w)
            for k in ("logic", "reason"):
                if not dup.get(k) and item[k]:
                    dup[k] = item[k]
    return n


def _has_items(o):
    """응답에 후보가 하나라도 있는가 — 복구본(salvaged)이 빈 껍데기면 성공으로 세지 않는다."""
    v = o.get("new")
    return bool(v) and isinstance(v, (list, dict))


# ── 근거 행 다시 세기 (왕복 없음) ─────────────────────────────────────────────
def _row_index(rows):
    """fold 축 인덱스 — Level 3 · 'Level 2 Level 3' 두 키, 공백 제거판도 함께(붙여 쓴 이름도 찾게).
    병합 맵을 적용하기 전 판정 이름(_raw3)도 같이 색인한다 — Copilot 은 프롬프트에 보낸 원 표기로 답한다."""
    idx, idx_ns = {}, {}
    for r in rows:
        keys = {fold(r.get("Level 3")), fold(f"{r.get('Level 2')} {r.get('Level 3')}")}
        raw3 = r.get("_raw3")
        if raw3 and raw3 != r.get("Level 3"):
            keys |= {fold(raw3), fold(f"{r.get('Level 2')} {raw3}")}
        for key in keys:
            if key:
                idx.setdefault(key, []).append(r)
                idx_ns.setdefault(key.replace(" ", ""), []).append(r)
    return idx, idx_ns


def find_rows(name, idx, idx_ns):
    f = fold(name)
    if not f:
        return []
    if f in idx:
        return idx[f]
    ns = f.replace(" ", "")
    if ns in idx_ns:
        return idx_ns[ns]
    # 부분 일치 폴백 — 양쪽 다 4자 이상일 때만('세부'·'교육' 같은 짧은 이름이 전부를 물지 않게)
    if len(ns) < 4:
        return []
    hit = [r for k, rs in idx_ns.items() if len(k) >= 4 and (ns in k or k in ns) for r in rs]
    return list({id(r): r for r in hit}.values())


def _axis_index(arows, amap=None, use_pairs=False):
    """축 행 색인 → (정확 {(과제, 세부업무): [행]}, 느슨 {(ukey2, ukey3): [행]}). amap(세부업무 병합 맵)이 있으면 대표
    이름으로도 느슨 색인. use_pairs=True(표시 행 축)면 행의 원본 쌍(_pairs)으로 색인한다."""
    exact, loose = {}, {}
    for r in arows:
        prs = (_pairs_of(r) if use_pairs
               else [((r.get("Level 2") or "").strip(), (r.get("Level 3") or "").strip())])
        for a, b in prs:
            exact.setdefault((a, b), []).append(r)
            loose.setdefault(_loose(a, b), []).append(r)
            rep_ = (amap or {}).get((a or "공통", b))
            if rep_ and rep_ != b:
                loose.setdefault(_loose(a, rep_), []).append(r)
    return exact, loose


def _rows_for_key(k, exact, loose, amap=None):
    """키 하나 → 축 행들. 정확 → 느슨(띄어쓰기·구분자 변형) → 세부업무 병합 맵의 대표 이름 순."""
    a, b = split_key(k)
    rs = exact.get((a, b)) or loose.get(_loose(a, b))
    if not rs and amap:
        rep_ = amap.get((a or "공통", b))
        if rep_:
            rs = loose.get(_loose(a, rep_))
    return rs or []


def needs_only(o):
    """저장·화면·보고서용 꼴 — NEEDS_KEYS 만 남기고 kind='needs'. LM28 이 만든 파일의 match·misassigned·mm_recalc 같은
    과제 매칭·오할당 키는 버린다(LM29 는 니즈 후보만). new 는 dict 항목만."""
    o = o if isinstance(o, dict) else {}
    out = {k: o[k] for k in NEEDS_KEYS if k in o}
    out["kind"] = KIND
    v = o.get("new")
    out["new"] = [n for n in v if isinstance(n, dict)] if isinstance(v, list) else []
    return out


def recalc_evidence(out, rows, amap=None, plain_rows=None):
    """후보(new)의 근거 행 수(evidence_rows)·못 찾은 이름(evidence_missing)을 내 자료로 다시 센다(out 제자리 갱신 · 왕복 없음).
    · 근거 키(keys — 원본 mm_rows (과제, 세부업무) 쌍)가 있으면 원본 행(plain_rows)에서 키로 찾는다 — 정제본이 지워져 행 파일이
      원본으로 바뀌어도 그대로다. 원본 행이 없으면 표시 행의 원본 쌍(_pairs)으로 찾는다.
    · 키가 없는 옛 후보는 근거 업무 이름 → 행 이름 대조(find_rows)로 찾는다.
    · MM 은 붙이지 않는다(옛 결과의 new[].load_mm·load_mm_ai 는 지운다)."""
    rows = [dict(r) for r in rows]
    for r in rows:
        if "_mm" not in r:
            r["_mm"] = details._f(r.get("mm"))
        r.setdefault("_raw3", r.get("Level 3"))       # 맵 적용 전 이름 — 근거 대조는 원 표기·대표 이름 둘 다로
    if amap:
        details.apply_detail_map(rows, None, amap)
    idx, idx_ns = _row_index(rows)
    news = [n for n in (out.get("new") or []) if isinstance(n, dict)]
    keyed = any(isinstance(n.get("keys"), list) for n in news)
    # 원본 축은 키 근거 결과(keys·row_keys)에만 쓴다. 옛 결과(이름 근거)는 표시 행 축에서 센다.
    new_fmt = keyed or isinstance(out.get("row_keys"), dict)
    plain = [dict(r) for r in (plain_rows or [])] if new_fmt else []
    plain_axis = bool(plain)
    arows = plain if plain_axis else rows
    ex, lo = _axis_index(arows, amap, use_pairs=not plain_axis)

    def _to_axis(rs):
        """이름 대조로 찾은 표시 행 → 근거 축 행(원본 축이면 원본 쌍으로 되짚기)."""
        if not plain_axis:
            return rs
        got = []
        for r in rs:
            for a, b in _pairs_of(r):
                got += _rows_for_key(key_of(a, b), ex, lo, amap)
        return got

    for n in news:
        n.pop("load_mm_ai", None)
        n.pop("load_mm", None)                         # '대체 가능 MM≈' 산출 없음 — 빈도(근거 행 수)만
        hit, miss = [], []
        if isinstance(n.get("keys"), list):
            for k in n["keys"]:
                hit += _rows_for_key(k, ex, lo, amap)
            miss = _clean_list(n.get("missing"), cap=MISSING_CAP)
        else:
            for w in _clean_list(n.get("work")):
                rs = find_rows(w, idx, idx_ns)
                if rs:
                    hit += _to_axis(rs)
                else:
                    miss.append(w)
        n["evidence_rows"] = len({id(r) for r in hit})
        n["evidence_missing"] = miss[:6]
    out["new"] = news
    return out


def _save_json(path, obj):
    details.save_json_atomic(path, obj)


def _load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else None
    except (OSError, ValueError):
        return None


def recalc_file(tag, rep=None, log=print):
    """agentic_<tag>.json 을 읽어 후보의 근거 행 수만 다시 세어 저장(왕복 없음 — run.py 가 워크플로우 뒤·AI 없는 실행에서 부른다).
    LM28 이 만든 파일이면 과제 매칭·오할당 키를 버리고 니즈 후보만 남긴다(needs_only). 반환: 저장 경로 / 실패 None."""
    rep = rep or os.path.join(ROOT, "report")
    ap = os.path.join(rep, f"agentic_{tag}.json")
    ag = _load_json(ap)
    if ag is None:
        return None
    rows, fn = details.read_rows(tag, rep)
    if not rows:
        return None
    attach_pairs(rows, tag, rep, fn)
    try:
        amap = details.load_detail_aliases()
    except Exception:  # noqa: BLE001
        amap = {}
    plain = details.read_rows(tag, rep, plain=True)[0] or None
    ag = needs_only(ag)
    recalc_evidence(ag, rows, amap, plain_rows=plain)
    _save_json(ap, ag)
    try:
        log(f"[agentic] 근거 행 다시 셈: 니즈 후보 {len(ag['new'])}건 · 근거 업무 "
            f"{sum(int(n.get('evidence_rows') or 0) for n in ag['new'])}행 ({fn})")
    except (UnicodeEncodeError, OSError, ValueError):
        pass
    return ap


# ── 실행 ───────────────────────────────────────────────────────────────────
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


def _seed_keys(e, m, to_keys=None):
    """지난 결과 후보의 근거를 누적판 후보(e)에 옮긴다 — keys 가 있으면 그대로, 없는 옛 판(이름 근거)이면 to_keys(지금 행
    이름으로 풀기)로 한 번 키로 바꾼다."""
    if isinstance(m.get("keys"), list):
        e["keys"] = {str(k) for k in m["keys"] if isinstance(k, str) and details.KEY_SEP in k}
        e["missing"] = _clean_list(m.get("missing"), cap=MISSING_CAP)
    elif to_keys is not None:
        hit, miss = to_keys(e.get("work") or [])
        e["work"], e["keys"], e["missing"] = [], set(), []
        _add_hits(e, hit, miss)


def _seed_prev(prev, to_keys=None):
    """이어서 판정할 때 지난 결과의 후보(new)를 누적판으로 되살린다(근거 keys 는 그대로 이어받는다).
    LM28 결과의 과제 매칭(match)·오할당(misassigned)은 읽지 않는다."""
    news = []
    for x in (prev.get("new") or []):
        if not isinstance(x, dict) or not str(x.get("name") or "").strip() or _placeholder(x.get("name")):
            continue
        item = {"name": str(x["name"]).strip()[:60], "logic": str(x.get("logic") or "")[:300],
                "reason": str(x.get("reason") or "")[:300], "work": _clean_list(x.get("work"))}
        _seed_keys(item, x, to_keys)
        if not any(fold(u["name"]) == fold(item["name"]) for u in news):
            news.append(item)
    return news


def _stage_budget(floor_min=15.0):
    r"""core.budget.stage_budget 위임 — 단계 예산 정책은 한 벌(core\budget.py)."""
    from budget import stage_budget
    return stage_budget(floor_min=floor_min, root=ROOT, now=time.time, mono=time.monotonic)


def _age_days(at, today):
    """'YYYY-MM-DD' 두 날짜의 차(일) — 날짜를 모르면 None."""
    try:
        return (date.fromisoformat(str(today)[:10]) - date.fromisoformat(str(at or "")[:10])).days
    except ValueError:
        return None


def _carry_prev(rep, tag, today, days=CARRY_DAYS):
    """--carry: 오늘 기간 파일이 없을 때 — 같은 시작일의 다른 기간 결과 중 가장 최근 것으로, 발굴 시작일(matched_since ·
    옛 판은 generated)이 days 일 이내인 것 → (결과, 그 기간 tag). 없으면 (None, '')."""
    head = tag.split("-")[0]
    cands = []
    for p in glob.glob(os.path.join(rep, f"agentic_{head}-*.json")):
        t = os.path.basename(p)[len("agentic_"):-len(".json")]
        if t == tag:
            continue
        try:
            cands.append((os.path.getmtime(p), p, t))
        except OSError:
            continue
    for _mt, p, t in sorted(cands, reverse=True):
        o = _load_json(p)
        if not o or not isinstance(o.get("rows_done"), list):
            continue
        age = _age_days(o.get("matched_since") or str(o.get("generated") or "")[:10], today)
        if age is not None and 0 <= age <= days:
            return o, t
    return None, ""


def _stop_kind_of(info):
    """치명 실패 info → 중단 갈래 — throttle(Copilot 사용량 제한) · login(로그인) · fatal(그 밖의 사람이 손댈 일)."""
    info = info or {}
    ph, err = str(info.get("phase") or ""), str(info.get("error") or "")
    if info.get("hard") or ph == "throttled" or "사용량 제한" in err:
        return "throttle"
    if ph == "login_required" or "로그인" in err:
        return "login"
    return "fatal"


def _splittable(info):
    """반으로 나눠 다시 물을 실패인가 — 답이 왔는데 해석 못 했거나(parse·잘려 건질 게 없음) 응답이 없을 때(no_reply)만."""
    return str(info.get("phase") or "") in ("parse", "no_reply") or info.get("kind") == "parse"


def _transient(info):
    """쉬었다가 같은 묶음을 한 번 더 보낼 일시 오류인가 — Copilot 오류 응답·시간 초과·빈 phase 등(치명·관문·해석 실패 제외)."""
    return (not info.get("ok") and info.get("phase") != "blocked" and not info.get("fatal")
            and not info.get("hard") and not _splittable(info))


def _cool_wait(deadline, cool):
    """일시 오류 뒤 쉴 초 — coolDownSec 와 '마감 − 60초' 중 작은 쪽(음수면 0)."""
    if deadline is None:
        return float(cool)
    return max(0.0, min(float(cool), deadline - time.monotonic() - 60.0))


def _run_room(judge, wait):
    """쉴 초를 이번 실행의 쉬는 시간 합계(copilotAuto.runWaitMaxSec)·프로세스 합계·전체 마감 안으로(judge.wait_room).
    judge 에 없으면(시험 가짜) 바라는 그대로. 1초도 못 쉬면 0(쉬지 않고 바로 한 번 더)."""
    fn = getattr(judge, "wait_room", None)
    if wait > 0 and callable(fn):
        try:
            wait = min(float(wait), float(fn(wait)))
        except Exception:  # noqa: BLE001 - 합계를 못 읽으면 바라는 그대로
            pass
    return float(wait) if wait >= 1 else 0.0


def _note_wait(judge, wait):
    """방금 wait 초 쉬었다 — 판정 모듈의 프로세스·실행 합계에 더한다(judge.note_waited). 기록 실패는 무시한다."""
    fn = getattr(judge, "note_waited", None)
    if wait > 0 and callable(fn):
        try:
            fn(wait)
        except Exception:  # noqa: BLE001
            pass


def _bad_reply(judge):
    """답을 받았지만 쓰지 못했다 — 다음 왕복은 새 채팅에서(judge.note_bad_reply). 알림 실패가 판정을 막지 않게."""
    try:
        judge.note_bad_reply()
    except Exception:  # noqa: BLE001
        pass


def main():
    import judge
    d0, d1 = arg("--from"), arg("--to")
    tag = (f"{d0.replace('-', '')}-{d1.replace('-', '')}" if d0 and d1 else latest_tag())
    rep = os.path.join(ROOT, "report")
    if not tag:
        print("[agentic] 분석 결과가 없습니다 — 먼저 [분석 실행]")
        print(json.dumps({"ok": False, "error": "no result", "stop_kind": "fatal",
                          "hint": "report\\ 에 분석 결과(mm_meta)가 없습니다 — 먼저 [분석 실행]"}, ensure_ascii=False))
        return 1
    if "--recalc" in sys.argv:
        # 왕복 없는 재계산은 단계 상태 파일을 열지 않는다 — 열고 닫지 않으면 화면이 90초 뒤 '정체로 중단' 이라고 보인다
        ap = recalc_file(tag, rep)
        print(json.dumps({"ok": bool(ap), "tag": tag, "recalc": True,
                          **({} if ap else {"error": "no file",
                                            "hint": f"agentic_{tag}.json 또는 mm_rows_{tag}.csv 가 없습니다"})},
                         ensure_ascii=False))
        return 0 if ap else 1
    from stage_state import open_stage
    _ss = open_stage(rep, tag, "agentic")
    try:
        return _run(judge, tag, rep, _ss)
    except Exception as e:  # noqa: BLE001 - 상태 파일에 사유를 남기고 다시 던진다('정체로 중단' 오진 방지)
        if _ss is not None:
            _ss.finish("failed", stop_kind="fatal", reason=f"예외로 중단: {type(e).__name__}",
                       error=f"{type(e).__name__}: {str(e)[:200]}", hint="진행 로그의 마지막 오류 줄을 확인하세요")
        raise


def _run(judge, tag, rep, _ss):
    carry = "--carry" in sys.argv and "--redo" not in sys.argv
    today = time.strftime("%Y-%m-%d")

    def _end(rc, js, state, kind=None, reason="", error="", hint=""):
        """마지막 줄 JSON(stop_kind 포함) + 상태 파일 마감 — 모든 반환 경로가 여기를 지난다. 그 앞에 Copilot 채팅 정리 한 줄."""
        judge.chat_note()
        print(json.dumps(dict(js, stop_kind=kind or ""), ensure_ascii=False))
        if _ss is not None:
            _ss.finish(state, stop_kind=kind or None, reason=reason, error=error or None, hint=hint or None)
        return rc

    rows, rows_fn = details.read_rows(tag, rep)
    if not rows:
        exists = os.path.exists(os.path.join(rep, f"mm_rows_{tag}.csv")) or \
            os.path.exists(os.path.join(rep, f"mm_rows_{tag}_refined.csv"))
        hint = (f"mm_rows_{tag}(_refined).csv 에 업무 행이 없습니다(0행) — 그 기간의 신호가 없거나 전부 제외됐습니다"
                if exists else
                f"report\\mm_rows_{tag}.csv(또는 _refined) 가 없습니다 — 화면 기간({tag})과 결과 파일 기간이 다르면 "
                "그 기간을 [분석 실행]으로 다시 만드세요")
        print(f"[agentic] 업무 행이 없습니다 — {hint}")
        return _end(1, {"ok": False, "error": "no rows", "hint": hint}, "failed", "fatal", hint, "no rows", hint)
    try:
        amap = details.load_detail_aliases()
    except Exception as e:  # noqa: BLE001 - 캐시가 깨져도 발굴은 돈다
        print(f"[agentic] 세부업무 병합 맵을 읽지 못해 무시합니다({type(e).__name__})")
        amap = {}

    sigs = details.read_signals(tag, rep)
    plain_rows = details.read_rows(tag, rep, plain=True)[0] or None
    attach_pairs(rows, tag, rep, rows_fn)
    # 행 번호 — MM 큰 순으로 실행 전체에 고정(묶음 경계·겹침과 무관). 답은 근거 업무를 이 번호로 돌려준다.
    rows.sort(key=lambda r: -r["_mm"])
    for i, r in enumerate(rows, 1):
        r["_rid"] = i
    by_rid = {r["_rid"]: r for r in rows}
    idx_all = _row_index(rows)
    try:
        budget = max(1500, int(arg("--budget", PROMPT_BUDGET)))    # 튜닝·테스트용 묶음 예산
    except ValueError:
        budget = PROMPT_BUDGET
    try:
        max_chunks = max(1, int(arg("--max-chunks", _cfg_int("agenticMaxChunks", MAX_CHUNKS))))
    except ValueError:
        max_chunks = MAX_CHUNKS
    ap = os.path.join(rep, f"agentic_{tag}.json")

    # AI 판정 대기 — 신호 대부분이 규칙 판정인 행은 보내지 않는다(판정 끝으로도 세지 않는다 — 판정이 회복되면 보낸다)
    cut = rule_cut()
    rshare = details.rule_share(sigs)
    pmm = {}
    for r in (plain_rows or []):
        k = ((r.get("Level 2") or "").strip() or "공통", (r.get("Level 3") or "").strip() or "기타")
        pmm[k] = pmm.get(k, 0.0) + r["_mm"]
    rule_now = {row_sig(r) for r in rows if row_rule_share(r, rshare, pmm) >= cut}

    # 이어서 판정 — 지난 실행이 판정한 행(식별자 '과제|세부업무|유형')은 두고 남은 행만 보낸다
    sig_all = [row_sig(r) for r in rows]
    sig_set = set(sig_all)
    prev = None if "--redo" in sys.argv else _load_json(ap)
    if prev is not None and prev.get("tag") not in (None, "", tag):
        prev = None
    carried_from = ""
    if prev is None and carry:
        # 기간 끝날짜가 바뀌어(기본 기간 '올해' 는 매일 바뀐다) 오늘 파일이 없다 — 같은 시작일의 최근 결과를 잇는다
        prev, carried_from = _carry_prev(rep, tag, today)
    done_prev = set()
    if prev and isinstance(prev.get("rows_done"), list):
        done_prev = (({_sig_norm(s) for s in prev["rows_done"]}
                      - {_sig_norm(s) for s in (prev.get("rows_rule") or [])}) & sig_set) - rule_now
        if not carry and done_prev >= (sig_set - rule_now):
            done_prev = set()                    # 다 끝난 결과 — 처음부터 다시(화면 [니즈 후보 발굴 실행]). --carry 는 이어받는다
    todo = [r for r in rows if row_sig(r) not in done_prev and row_sig(r) not in rule_now]
    if done_prev:
        news = _seed_prev(prev, to_keys=lambda names: resolve_work(names, {}, None, idx_all))
        matched_since = str(prev.get("matched_since") or str(prev.get("generated") or "")[:10] or today)
        src = f"지난 기간 결과({carried_from})" if carried_from else "지난 실행"
        print(f"[agentic] {src}가 {len(done_prev)}/{len(rows)}행까지 판정했습니다 — "
              f"남은 {len(todo)}행만 이어서 보냅니다(처음부터 하려면 --redo)")
    else:
        news = []
        matched_since, carried_from = today, ""

    parts = split_rows(todo, budget=budget)
    deferred = 0
    if len(parts) > max_chunks:
        deferred = sum(n for _p, n in parts[max_chunks:])
        print(f"[agentic] 묶음이 {len(parts)}개라 이번 실행은 앞 {max_chunks}묶음만 보냅니다 — "
              f"남은 {deferred}행은 다음 실행이 이어서 봅니다")
        parts = parts[:max_chunks]
    if rule_now:
        _rmm = sum(r["_mm"] for r in rows if row_sig(r) in rule_now)
        print(f"[agentic] AI 판정 대기 — 신호의 {int(round(cut * 100))}% 이상이 규칙 판정인 업무 {len(rule_now)}행"
              f"({_rmm:.2f} MM)은 보내지 않습니다(규칙 토큰이라 니즈를 가늠할 수 없음 — [재분석만]으로 판정을 마친 뒤 "
              "[니즈 후보 발굴 실행])")
    if todo:
        print(f"[agentic] 니즈 후보 발굴 왕복 — 업무 {len(todo)}행을 {len(parts)}묶음으로 나눠 보냅니다 "
              f"(팀 과제와 매칭하지 않음 · 업무는 #번호로 · 묶음 경계는 앞 행 겹침 · MM 미전송 · 같은 채팅에서 이어서{_chat_note()})")
    elif done_prev:
        print("[agentic] 지난 결과가 보낼 행을 모두 판정했습니다 — 이번 실행은 Copilot 왕복 없이 근거 행 수만 다시 셉니다")

    done_sigs = set(done_prev)
    gate_sigs = ({_sig_norm(s) for s in ((prev or {}).get("rows_gate") or [])} & done_prev) if done_prev else set()
    failed, salvaged, fails = 0, 0, []
    consec, stopped, n_sent = 0, "", 0
    st = {"kind": "", "cool": 0}                 # kind=중단 갈래 · cool=쉬고 다시 보낸 횟수
    cool_sec = _cool_sec()
    last_res = {}

    def _send(prompt, tg, name, fresh=None):
        """judge.copilot_send 를 부르고 드라이버 결과의 hard(Copilot 사용량 제한)·cooldowns(이미 쉬고 다시 보낸 횟수)를
        기억한다 — details.ask_json 의 info 에는 이 둘이 실리지 않는다."""
        res = details._call_sender(judge.copilot_send, prompt, tg, name, fresh)
        last_res.clear()
        if isinstance(res, dict):
            try:
                _cd = int(res.get("cooldowns") or 0)
            except (TypeError, ValueError):
                _cd = 0
            last_res.update(hard=bool(res.get("hard")), cooldowns=_cd)
        return res

    def ask(part, name, n_new):
        """→ (o, info). G3 — 상세설명·근거는 재정제 사본으로, 자기 줄이 최종 검사에 걸리는 행은 **그 행만** 빼고 보낸다
        (빠진 새 행은 gate 로 판정 끝). 보낼 새 행이 없거나 줄인 프롬프트도 막히면 묶음 전체가 blocked(실패 아님)."""
        nonlocal n_sent
        new_rows = part[-n_new:] if n_new else []
        new_ids = {r.get("_rid") for r in new_rows}
        sendable = [r for r in g3_part(part) if judge.g3_prompt(row_line(r))]
        ok_ids = {r.get("_rid") for r in sendable}
        for r in new_rows:
            if r.get("_rid") not in ok_ids:
                gate_sigs.add(row_sig(r))
                done_sigs.add(row_sig(r))
        if part and not any(r.get("_rid") in new_ids for r in sendable):
            return {}, {"ok": False, "kind": "roundtrip", "phase": "blocked", "fatal": False,
                        "error": "개인정보 관문 — 보낼 업무 행이 없음", "hint": ""}
        n_sent += 1
        last_res.clear()
        # fresh=None — 묶음을 같은 채팅에서 이어 보낸다(첫 왕복·실패 뒤·chatTurns 마다만 새 채팅). 앞 묶음의 후보 이름·표기를
        # Copilot 이 기억해 묶음 간 이름이 일관된다(같은 니즈가 묶음마다 다른 이름으로 갈리지 않게)
        o, info = details.ask_json(_send, ag_prompt(sendable), f"{tag}-{name}", "agentic", "new", fresh=None)
        info = dict(info, hard=bool(info.get("hard") or last_res.get("hard")),
                    cooldowns=int(last_res.get("cooldowns") or 0))
        if info.get("phase") == "blocked":
            for r in new_rows:                   # 줄인 프롬프트도 최종 검사에 걸렸다 — 이 묶음의 새 행은 관문
                gate_sigs.add(row_sig(r))
                done_sigs.add(row_sig(r))
            return {}, info
        if not info.get("ok"):
            if info.get("kind") == "parse":
                _bad_reply(judge)                # 답은 왔는데 해석 못 했다 — 다음 왕복은 새 채팅에서
            return o, info
        if info.get("how") == "salvaged" and not _has_items(o):
            _bad_reply(judge)
            return {}, {"ok": False, "kind": "parse", "phase": "parse", "error": "응답이 잘려 건질 내용이 없음",
                        "hint": "답이 길어 중간에 끊겼습니다 — 묶음을 나눠 다시 묻습니다", "fatal": False}
        return o, info

    def absorb(o, part_rows, n_new, ci, note=""):
        res = _resolver(by_rid, part_rows, idx_all)
        got = merge_new(news, o, res=res)
        for r in part_rows[-n_new:]:
            done_sigs.add(row_sig(r))
        print(f"[agentic] {ci}/{len(parts)}{note} — 업무 {n_new}행(겹침 {len(part_rows) - n_new}) → 새 니즈 후보 {got}건")

    def write_out(final=False):
        pending = [s for s in sig_all if s not in done_sigs and s not in rule_now]
        analyzed = len([s for s in sig_all if s in done_sigs])      # 판정 끝(관문 포함) — AI 판정 대기 행은 세지 않는다
        # 분할 재시도로 결국 성공한 묶음의 실패는 사유에 남기지 않는다 — 남은 행·실패 묶음이 있을 때만
        why, how = _fail_summary(fails) if (pending or failed) else ("", "")
        # 원본 축 갈래 — 근거 행을 다시 셀 때 표시 행 파일이 바뀌어도(정제본 삭제) 같은 축을 쓰게
        rk = {"sent": set(), "rule": set(), "gate": set()}
        for r in rows:
            s = row_sig(r)
            b = ("rule" if s in rule_now else "gate" if s in gate_sigs else ("sent" if s in done_sigs else ""))
            if b:
                rk[b].update(key_of(a, c) for a, c in _pairs_of(r))
        out = {"tag": tag, "kind": KIND, "new": [_export(n) for n in news],
               # 실제로 판정에 쓰인 행 수만 적는다(겹침 제외) — 반쪽 결과가 완전한 결과처럼 보이면 안 된다
               "rows_analyzed": analyzed, "rows_total": len(rows), "rows_pending": len(pending),
               "rows_done": sorted(done_sigs & sig_set),
               # AI 판정 대기(신호 대부분이 규칙 판정) — 보내지 않은 행. 판정 끝이 아니라 다음 실행이 다시 본다
               "rows_rule": sorted(rule_now), "rule_rows": len(rule_now), "rule_share_cut": cut,
               "rows_gate": sorted(gate_sigs & sig_set),
               "row_keys": {k: sorted(v) for k, v in rk.items()},
               "partial": bool(pending), "chunks": len(parts), "failed_chunks": failed,
               "salvaged_chunks": salvaged, "gate_skipped_rows": len(gate_sigs & sig_set),
               "note": ("" if not pending else
                        (f"{len(pending)}행 미판정 — " + (stopped or "다시 실행하면 남은 행만 이어서 봅니다"))),
               "last_error": ({"error": why, "hint": how} if why else {}),
               "generated": time.strftime("%Y-%m-%d %H:%M"),
               # 이어받기 — 다른 기간 결과에서 이어받았으면 그 기간. matched_since = 처음부터 발굴을 시작한 날(이어받기 상한 기준)
               "carried_from": carried_from, "matched_since": matched_since,
               "stop_kind": st["kind"], "cooldowns": st["cool"]}
        recalc_evidence(out, rows, amap, plain_rows=plain_rows)
        # 근거 행이 많은 후보부터 NEW_CAP 건 — 같으면 발견 순(정렬은 안정)
        out["new"] = sorted(out["new"], key=lambda n: -int(n.get("evidence_rows") or 0))[:NEW_CAP]
        out = needs_only(out)
        _save_json(ap, out)
        return out

    _dl, _bud = _stage_budget()

    def over_budget():
        return _dl is not None and time.monotonic() > _dl

    def ask_cool(part, name, n_new):
        """일시 오류(Copilot 오류 응답·시간 초과 등)는 반으로 나누지 않고 쉬었다가 같은 묶음을 새 채팅에서 한 번만 다시.
        드라이버가 이미 쉬고 다시 보냈으면(cooldowns) 또 쉬지 않는다."""
        o, info = ask(part, name, n_new)
        if not _transient(info) or info.get("cooldowns"):
            return o, info
        want = _cool_wait(_dl, cool_sec)
        wait = _run_room(judge, want)            # 이번 실행의 쉬는 시간 합계(runWaitMaxSec) 안
        err = str(info.get("error") or "")[:60]
        if wait > 0:
            print(f"[agentic] {name} {err} — {wait:.0f}초 쉬고 새 채팅에서 같은 묶음을 한 번 더 보냅니다")
        else:
            print(f"[agentic] {name} {err} — 쉬지 않고 새 채팅에서 같은 묶음을 한 번 더 보냅니다"
                  + ("(이번 실행에서 쉴 수 있는 시간을 다 썼습니다)" if want >= 1 else ""))
        _bad_reply(judge)
        if wait > 0:
            time.sleep(wait)
            _note_wait(judge, wait)
        if over_budget():
            return o, info
        st["cool"] += 1
        return ask(part, f"{name}-c", n_new)

    for ci, (part, n_new) in enumerate(parts, 1):
        if over_budget():
            # 예산 초과 — 남은 묶음은 rows_done 에 남아 다음 실행이 이어서 묻는다(MAX_CHUNKS 와 같은 처리)
            st["kind"] = "budget"
            if _ss is not None:
                _ss.note_resume(pending=len(parts) - ci + 1)
            stopped = (f"시간 예산 {_bud:.0f}분을 넘겨 남은 {len(parts) - ci + 1}묶음을 보내지 않았습니다 — "
                       "다시 실행하면 남은 것만 이어서 묻습니다(config.aiStageBudgetMin·agenticReserveMin 으로 조절)")
            print(f"[agentic] {stopped}")
            break
        progress("Agentic 니즈 발굴", ci - 1, len(parts))
        o, info = ask_cool(part, f"ag{ci}", n_new)
        if info.get("phase") == "blocked":
            # 개인정보 관문(G3)에 막혀 보내지 않았다 — 실패가 아니므로 연속 실패·적응 분할에 넣지 않는다. 다시 물어도 같으므로
            # 그 행은 판정 끝으로 둔다(후보 없음 · gate_skipped_rows 로 정직히 센다).
            print(f"[agentic] {ci}/{len(parts)} 개인정보 관문에 걸려 보내지 않았습니다 — 업무 {n_new}행은 후보 없이 둡니다")
            write_out()
            continue
        if info.get("ok"):
            if info.get("how") == "salvaged":
                salvaged += 1
                print(f"[agentic] {ci}/{len(parts)} 응답이 잘려 앞부분만 복구했습니다(부분 결과)")
            absorb(o, part, n_new, ci)
            consec = 0
            write_out()
            continue
        fails.append(info)
        print(f"[agentic] {ci}/{len(parts)} 실패: {info.get('error', '')[:80]}"
              + (f" — {info.get('hint', '')[:100]}" if info.get("hint") else "")
              + f" (report\\judge_agentic_{tag}-ag{ci}.md)")
        if info.get("fatal") or info.get("hard"):
            st["kind"] = _stop_kind_of(info)
            stopped = f"{info.get('error', '')} — {info.get('hint', '')}".strip(" —")
            failed += len(parts) - ci + 1
            print(f"[agentic] {'Copilot 사용량 제한' if st['kind'] == 'throttle' else '사람이 손대야 풀리는 상태'}라 "
                  f"남은 {len(parts) - ci}묶음은 보내지 않습니다")
            break
        # 적응 분할 — 답이 왔는데 해석 못 했거나(parse·잘려 빈 답) 응답이 없을 때(no_reply)만 반으로 나눠 한 번 더(겹침 없이,
        # 새 행만). 일시 오류는 위에서 쉬고 한 번 더 보냈다 — 나누면 지친 Copilot 에 왕복만 늘어난다.
        fresh_rows = part[-n_new:]
        if n_new >= SPLIT_MIN_ROWS and _splittable(info):
            half = (n_new + 1) // 2
            halves = [h for h in (fresh_rows[:half], fresh_rows[half:]) if h]
            ok_half = 0
            print(f"[agentic] {ci}/{len(parts)} 묶음을 {len(halves)}개로 나눠 다시 묻습니다(적응 분할)")
            for hi, sub in enumerate(halves, 1):
                if over_budget():
                    # 반분 루프도 예산을 본다 — 남은 절반은 다음 실행이 이어서 판정한다
                    print("[agentic] 시간 예산을 넘겨 분할 재시도를 멈춥니다 — 남은 것은 다시 실행하면 이어서")
                    break
                o2, info2 = ask(sub, f"ag{ci}-{hi}", len(sub))
                if info2.get("ok"):
                    ok_half += 1
                    if info2.get("how") == "salvaged":
                        salvaged += 1
                    absorb(o2, sub, len(sub), ci, note=f" (분할 {hi}/{len(halves)})")
                elif info2.get("phase") == "blocked":
                    print(f"[agentic] {ci}/{len(parts)} 분할 {hi}/{len(halves)} 개인정보 관문 — 보내지 않음(실패로 세지 않음)")
                else:
                    fails.append(info2)
                    print(f"[agentic] {ci}/{len(parts)} 분할 {hi}/{len(halves)} 실패: {info2.get('error', '')[:80]}")
                    if info2.get("fatal") or info2.get("hard"):
                        st["kind"] = _stop_kind_of(info2)
                        stopped = f"{info2.get('error', '')} — {info2.get('hint', '')}".strip(" —")
                        break
            if ok_half:
                consec = 0
                if ok_half < len(halves):
                    failed += 1                  # 반쪽만 됐다 — 이 묶음은 실패로 센다(남은 행은 pending)
                write_out()
                if stopped:
                    failed += len(parts) - ci
                    break
                continue
            if stopped:
                failed += len(parts) - ci + 1
                break
        failed += 1
        consec += 1
        if consec >= MAX_CONSEC_FAIL and ci < len(parts):
            st["kind"] = "fail"
            stopped = (f"{consec}묶음 연속 실패({info.get('error', '')[:40]}) — "
                       "Copilot 상태를 확인한 뒤 [니즈 후보 발굴 실행]으로 이어서")
            failed += len(parts) - ci
            print(f"[agentic] {consec}묶음 연속 실패 — 남은 {len(parts) - ci}묶음은 보내지 않습니다 "
                  "(잠시 뒤 재실행하면 남은 행만 이어서 판정합니다)")
            break
    progress("Agentic 니즈 발굴", len(parts), len(parts))

    analyzed_now = len([s for s in sig_all if s in done_sigs])
    if not analyzed_now and not news and not rule_now:
        # 기존 agentic_<tag>.json 은 손대지 않는다 — 반쪽 실패가 멀쩡한 옛 결과를 지우지 않게
        why, how = _fail_summary(fails)
        if not why and st["kind"] == "budget":
            why, how = "시간 예산 초과 — 보내지 못함", stopped
        why = why or "roundtrip"
        print(f"[agentic] 만들지 못했습니다 — {failed}/{len(parts)} 묶음이 실패했습니다: {why} — {how}")
        kind = st["kind"] or "fail"
        return _end(1, {"ok": False, "error": why,
                        "hint": (how + " · " if how else "") + f"{failed}/{len(parts)} 묶음 실패 — 기존 결과 파일은 그대로 둡니다",
                        "chunks": len(parts), "failed_chunks": failed, "cooldowns": st["cool"]},
                    "failed", kind, stopped or why, why, how)

    out = write_out(final=True)
    if not out["new"] and not out["rows_pending"] and not rule_now:
        print(f"[agentic] 업무 {len(rows)}행을 모두 봤지만 근거가 충분한 니즈 후보가 없습니다 — 후보 0건(실패 아님)")
    print(f"[agentic] Agentic AI 니즈 후보 {len(out['new'])}건 → agentic_{tag}.json")
    for n in out["new"][:6]:
        print(f"   · {str(n.get('name') or '')[:40]:41s} 근거 업무 {int(n.get('evidence_rows') or 0)}행"
              + (" [근거 없음]" if not n.get("evidence_rows") else ""))
    if out["rows_pending"]:
        print(f"[agentic] [!] 업무 {out['rows_analyzed']}/{len(rows)}행만 판정했습니다 — {out['note']}")
    js = {"ok": True, "tag": tag, "new": len(out["new"]), "chunks": len(parts),
          "failed_chunks": failed, "salvaged_chunks": salvaged,
          "rows_analyzed": out["rows_analyzed"], "rows_total": len(rows),
          "rows_pending": out["rows_pending"], "partial": out["partial"],
          "note": out["note"], **({"hint": out["note"]} if out["rows_pending"] else {}),
          **({"last_error": out["last_error"]} if out["last_error"] else {}),
          "rule_rows": len(rule_now), "gate_skipped_rows": out["gate_skipped_rows"],
          "carried_from": carried_from, "cooldowns": st["cool"]}
    if out["rows_pending"]:
        # 부분 — 남은 행이 있다(다시 실행하면 이어서). 갈래가 없으면 묶음 상한 이월은 budget, 그 밖은 실패 묶음
        kind = st["kind"] or ("budget" if deferred else "fail")
        return _end(2, js, "partial", kind, stopped or out["note"])
    return _end(0, js, "done", ("gate" if (not n_sent and gate_sigs and not news) else None))


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
