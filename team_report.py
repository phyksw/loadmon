# -*- coding: utf-8 -*-
r"""
team_report.py — 팀 통합 보고서(HTML 한 장) + 유사 항목 정리 엔진 (LoadMonitor22, 팀장용).

옛 '팀보완툴.py' 를 본체 모듈로 옮긴 것이다. 하는 일:
  · refine_once(share, sender)   — 과제·세부업무 표기 통합(규칙 + Copilot ≤3회) → team_aliases.json
  · build(share, sender)          — 인별 리포트 복원(개인리포트\) + 팀 통합 보고서 2종
                                    team_full_report.html / team_full_report_v3.html (고정 이름·원자 교체)
  · aggregate.py 가 취합 끝에 build(share) 를 부르므로 팀 서버가 업로드를 받을 때마다 갱신된다
    (서버 경로는 Copilot 없이 캐시만 적용). Copilot 정리는 UI [유사 항목 정리] → team_refine.py 만.

sender 계약: sender(prompt_text, tag, name) -> {"ok": bool, "reply": str, "error"?: str}
  (= judge.copilot_send). None 이면 Copilot 을 쓰지 않는다. 프롬프트에는 과제·업무·후보 '이름 목록'만
  들어간다 — 사람 이름·MM 은 보내지 않는다.

캐시(취합 폴더 루트, 모두 tmp+replace 로 쓴다): CACHE_FILES 참고. 한 줄 지우면 그 통합만 원복.

  python team_report.py [취합폴더] [--snapshot] [--copilot]
"""
import csv
import glob
import io
import json
import os
import re
import shutil
import sys
import time
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FULL_HTML, FULL_V3_HTML = "team_full_report.html", "team_full_report_v3.html"
MEMBER_HTML_DIR = "개인리포트"
ADJUST_FILE = "team_agentic_adjust.json"
SERIES_FILE = "team_series.json"
PJCLASS_FILE = "team_pjclass.json"
DETGRP_FILE = "team_detail_groups.json"
CAND_FILE = "team_cand_groups.json"
ALIAS_FILE = "team_aliases.json"
CACHE_FILES = (ALIAS_FILE, SERIES_FILE, PJCLASS_FILE, DETGRP_FILE, CAND_FILE, ADJUST_FILE)


def say(msg=""):
    print(msg, flush=True)


def esc(s):
    import html as _h
    return _h.escape(str(s or ""))


def _agg():
    """설치본 aggregate 모듈 — 취합·별칭 로직은 그 버전 것을 그대로 쓴다(지연 임포트: 순환 방지)"""
    import aggregate
    return aggregate


def _fnum(v, default=None):
    """숫자 강제 변환(aggregate.fnum) — 업로드된 JSON·CSV 값은 'abc'·dict·None 일 수 있다"""
    return _agg().fnum(v, default)


def _fint(v, default=None):
    return _agg().fint(v, default)


_BAD_FN = re.compile(r'[\\/:*?"<>|.]')


def _owner_key(s):
    """사람 비교축 — HTML 섬의 owner(원문)와 폴더의 owner(safe_owner 정규화: 금지문자→'_')를 같은 사람으로"""
    return ukey(_BAD_FN.sub("_", str(s or "")))


def _atomic_write(dst, body):
    r"""tmp 에 쓰고 os.replace — 팀 서버(업로드마다)와 UI([다시 만들기])가 같은 파일을 동시에
    쓸 수 있다. pid 를 붙여 각자 자기 임시 파일만 쓰고, 브라우저가 열어 둔 파일이라 replace 가
    막히면(윈도우) 덮어쓰기로 폴백한다(aggregate.visual_report 와 같은 패턴)."""
    tmp = f"{dst}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    try:
        os.replace(tmp, dst)
    except OSError:
        try:
            with open(dst, "w", encoding="utf-8") as f:
                f.write(body)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return dst


def _atomic_json(dst, obj):
    return _atomic_write(dst, json.dumps(obj, ensure_ascii=False, indent=1))


# ══ ① 유사 항목 정리 ══════════════════════════════════════════════════════
_SEP = {"·": " ", "・": " ", "ㆍ": " ", "‧": " ",
        "（": "(", "）": ")", "－": "-", "–": "-", "—": "-",
        "／": "/", "_": " ", "-": " ", "/": " "}


def fold(s, drop_note=True):
    """표기 접기 — 대소문자·구분자·공백을 걷어낸 비교 축.
    괄호 꼬리 제거(drop_note)는 퍼지 비교에서만 — '(양산)'/'(선행)' 같은 꼬리가
    실제 구분일 수 있어, 확정 병합(규칙 정리)에서는 떼지 않는다."""
    t = "".join(_SEP.get(ch, ch) for ch in str(s or ""))
    t = unicodedata.normalize("NFKC", t)
    t = "".join(_SEP.get(ch, ch) for ch in t)
    if drop_note:
        t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    return " ".join(t.split()).casefold()


def ukey(s):
    r"""워크플로우 신원 비교축 — **한 곳에서만 정한다**.
      · 괄호 꼬리는 **남긴다** — '(양산)'/'(선행)'은 실제 구분일 수 있다
      · 띄어쓰기·구분자·대소문자는 **무시한다** — 'RAG개발'과 'RAG 개발'은 같은 과제다"""
    return fold(s, drop_note=False).replace(" ", "")


def _note(s):
    """이름 끝 괄호 주석 — '(양산)'/'(선행)' 처럼 실제 구분일 수 있다"""
    m = re.search(r"\(([^)]*)\)\s*$", str(s or ""))
    return (m.group(1).strip().casefold() if m else "")


def local_groups(names):
    """규칙만으로 확실한 것(접기 결과가 같은 표기 변형)을 묶는다 — 오병합 없는 안전 구간."""
    by = {}
    for n in names:
        by.setdefault(fold(n, drop_note=False).replace(" ", ""), []).append(n)
    out = []
    for _k, v in by.items():
        if len(v) > 1:
            canon = max(v, key=lambda x: (len(x), x))     # 정보가 많은 표기를 대표로
            out.append({"canon": canon, "alts": [x for x in v if x != canon]})
    return out


def bigram_dice(a, b):
    def bg(t):
        t = fold(t).replace(" ", "")
        return {t[i:i + 2] for i in range(len(t) - 1)} or {t}
    x, y = bg(a), bg(b)
    return 2 * len(x & y) / (len(x) + len(y) or 1)


def flatten_chain(mp):
    """A→B, B→C 를 A→C 로 — 설치본 resolve_chain 은 '띄어쓰기 교정'(정규화가 같은 매핑)을
    지나는 사슬을 순환으로 오판해 중간 이름에 멈춘다(검증 확정). 저장 전에 여기서 끝까지 푼다."""
    ag = _agg()
    exact = dict(mp or {})
    norm_idx = {}
    for k, v in exact.items():
        norm_idx.setdefault(ag.norm_name(k), v)
    out = {}
    for k in exact:
        cur, seen = exact[k], {k}
        for _ in range(20):                       # 순환 방어
            nxt = exact.get(cur)
            if nxt is None:
                nxt = norm_idx.get(ag.norm_name(cur))
                if nxt is not None and ag.norm_name(nxt) == ag.norm_name(cur):
                    nxt = None                    # 자기 정규화 항목으로의 제자리걸음 방지
            if nxt is None or nxt in seen or nxt == cur:
                break
            seen.add(cur)
            cur = nxt
        if cur != k:
            out[k] = cur
    return out


def load_alias_raw(share):
    p = os.path.join(share, ALIAS_FILE)
    try:
        o = json.load(open(p, encoding="utf-8-sig"))
        return {"projects": dict(o.get("projects") or {}), "details": dict(o.get("details") or {})}
    except (OSError, ValueError):
        return {"projects": {}, "details": {}}


def save_aliases(share, aliases):
    """내용이 바뀔 때만 백업(.팀보완백업_<ts>)을 남기고 tmp+replace 로 쓴다."""
    p = os.path.join(share, ALIAS_FILE)
    payload = json.dumps(aliases, ensure_ascii=False, indent=1)
    if os.path.exists(p):
        try:
            if open(p, encoding="utf-8-sig").read() == payload:
                return False                 # 무변경 — 같은 내용 백업이 실행마다 쌓이지 않게
        except OSError:
            pass
        try:
            shutil.copy2(p, p + time.strftime(".팀보완백업_%Y%m%d_%H%M%S"))
        except OSError:
            pass
    _atomic_write(p, payload)
    return True


_TAIL_DROP = "(괄호 꼬리 다름)"


def _apply_groups(target, groups, pool, kind="", detail=None, dropped=None):
    """canon/alts 를 검증해 매핑에 넣는다 — 목록에 없는 이름은 정규화로 한 번 더 찾고, 그래도
    없으면 버린다(지어낸 이름 방지). '공통' 은 예약어. detail/dropped 리스트가 오면 내역을 남긴다.

    · 이름 끝 괄호 꼬리('(양산)'/'(선행)')가 다른 것끼리는 **절대 묶지 않는다** — detgrp/cand/merge_similar
      와 같은 규칙(검증 확정: Copilot 이 둘을 묶어 team_aliases.json 에 저장돼 전 화면에 번졌다).
    · 앞 회차에서 이미 매핑된 이름(target 의 키)은 다음 회차 풀에 없어도 '목록에 없는 이름'으로 세지 않는다.
    · canon/alts 의 형식이 다르면(숫자·목록·None) 그 그룹만 무시한다 — 정리 전체가 죽지 않게."""
    ag = _agg()
    by_n = {}
    for x in pool:
        by_n.setdefault(ag.norm_name(x), []).append(x)
    mapped_n = {ag.norm_name(k) for k in target}
    n_new = 0
    for g in groups if isinstance(groups, list) else []:
        if not isinstance(g, dict):
            continue
        canon = g.get("canon")
        if canon is None or isinstance(canon, (bool, list, dict)):
            continue
        canon = str(canon).strip()
        if not canon or canon == "공통":
            continue
        alts = g.get("alts")
        if isinstance(alts, str):
            alts = [alts]
        elif not isinstance(alts, list):
            alts = []
        alts = [str(x).strip() for x in alts
                if isinstance(x, (str, int, float)) and not isinstance(x, bool)]
        if canon not in pool:
            canon = (by_n.get(ag.norm_name(canon)) or [""])[0]
        if not canon:
            # 목록에 없는 대표명은 채택하지 않는다(지어낸 이름 방지 — 검증 지적).
            # 대신 실재하는 변형 중 가장 정보가 많은 것을 대표로 세운다.
            reals = [x for x in alts if x in pool or by_n.get(ag.norm_name(x))]
            reals = [(x if x in pool else by_n[ag.norm_name(x)][0]) for x in reals]
            if len(reals) < 2:
                continue
            canon = max(reals, key=lambda x: (len(x), x))
        got = []
        for x in alts:
            if not x or x == "공통":
                continue
            reals = [x] if x in pool else by_n.get(ag.norm_name(x)) or []
            if not reals:
                if dropped is not None and ag.norm_name(x) not in mapped_n:
                    dropped.append(f"{kind}: {x}")          # 조용히 버리지 않는다
                continue
            for real in reals:
                if real == canon or target.get(real) == canon:
                    continue
                if _note(real) != _note(canon):
                    if dropped is not None:
                        dropped.append(f"{kind}: {real} → {canon} {_TAIL_DROP}")
                    continue
                target[real] = canon
                n_new += 1
                got.append(real)
        if got and detail is not None:
            detail.append(f"{kind}: {' / '.join(got)} → {canon}")
    return n_new


def collect_names(members):
    projects, details = set(), set()
    for m in members:
        for r in m["rows"]:
            if (r.get("Level 2") or "").strip():
                projects.add(r["Level 2"].strip())
            if (r.get("Level 3") or "").strip():
                details.add(r["Level 3"].strip())
    projects.discard("공통")
    return projects, details


def build_prompt(projects, details):
    """Copilot 정리 프롬프트 — 과제명·세부업무명 '목록만' (사람·MM 없음). team_refine 도 이것을 쓴다."""
    lines = [
        "당신은 팀 업무 데이터 정리 담당입니다. 아래는 팀원 여러 명의 업무 분석에서 나온",
        "과제명 목록과 세부업무명 목록입니다. 각자 PC에서 따로 분석돼 같은 실체가 다른",
        "표기로 갈라져 있습니다. '같은 실체'만 그룹으로 묶고 대표 이름을 정하세요.",
        "",
        "· 같은 실체 = 표기 변형(대소문자·축약·한/영·띄어쓰기·조사)이거나 명백한 동의어.",
        "· 서로 다른 과제·업무는 절대 묶지 않는다 — 애매하면 묶지 않는 쪽을 택한다.",
        "· 이름 끝 괄호 표기('(양산)'/'(선행)' 등)가 다르면 절대 묶지 마라 — 실제 구분이다.",
        "· 대표 이름은 팀이 실제로 쓰는 가장 표준적인 표기로.",
        "· '공통' 은 예약어 — 건드리지 않는다.",
        "",
        "출력은 JSON 하나만 (묶을 것이 없으면 빈 배열):",
        '{"project_groups":[{"canon":"대표 과제명","alts":["변형1","변형2"]}],',
        ' "detail_groups":[{"canon":"대표 세부업무","alts":["변형1"]}]}',
        "",
        "[과제명 목록] — 한 줄이 한 항목이다. 이름을 고치지 말고 이 줄 그대로 옮겨 적을 것",
        chr(10).join("· " + p for p in projects),
        "",
        "[세부업무명 목록] — 한 줄이 한 항목",
        chr(10).join("· " + p for p in details),
    ]
    return "\n".join(lines)


def refine_once(share, sender=None, log=say):
    """정리 한 번에 — ① 규칙(확실한 표기 변형) ② sender 가 있으면 Copilot 반복(같은 실체 동의어),
    남는 게 없다고 할 때까지(최대 3회). 결과는 team_aliases.json 에 누적(백업 후).

    반환 dict 는 team_refine.py 가 그대로 JSON 으로 낸다(화면 계약):
      {"ok","groups","aliases","members","rounds","detail":[...],"dropped","rule","ai","share"}"""
    ag = _agg()
    members = ag.load_members(share)
    if not members:
        log("    [!] 취합할 인원이 없습니다.")
        return {"ok": False, "error": "no members", "share": share, "groups": 0,
                "aliases": 0, "members": 0, "rounds": 0, "detail": [], "dropped": 0}
    for m in members:
        if not m.get("rows"):
            # 기간(tag)이 어긋난 인원의 이름도 정리 풀에 넣는다 — §2 재집계와 같은 축(검증 확정)
            m["rows"], _rf9 = _member_rows(m.get("dir") or "", m.get("tag") or "",
                                           m.get("total_mm"))
    aliases = load_alias_raw(share)
    detail, dropped = [], []

    def canon_sets():
        pj, dt = collect_names(members)
        pmap = flatten_chain(aliases["projects"])
        dmap = flatten_chain(aliases["details"])
        pj = {pmap.get(x, x) for x in pj} - {"공통"}
        dt = {dmap.get(x, x) for x in dt}
        return pj, dt

    pj, dt = canon_sets()
    log(f"  대상: 과제 {len(pj)}개 · 세부업무 {len(dt)}개 (인원 {len(members)}명)")

    n1 = _apply_groups(aliases["projects"], local_groups(pj), pj, "과제", detail)
    n2 = _apply_groups(aliases["details"], local_groups(dt), dt, "세부업무", detail)
    log(f"  ① 규칙 정리: 표기 변형 {n1 + n2}건 통합")

    n_ai, rounds, err = 0, 0, ""
    if sender is not None:
        import judge
        for rnd in (1, 2, 3):
            pj, dt = canon_sets()
            if len(pj) + len(dt) < 3:
                break
            log(f"  ② Copilot 정리 {rnd}회차 — 남은 과제 {len(pj)} · 세부업무 {len(dt)}")
            res = sender(build_prompt(sorted(pj), sorted(dt)), f"team{rnd}", "teamrefine")
            rounds = rnd
            if not isinstance(res, dict):
                res = {"ok": False, "error": "bad sender result"}
            if not res.get("ok"):
                err = str(res.get("error") or "roundtrip")
                log(f"    [!] 왕복 실패: {err} — 여기까지 반영합니다")
                break
            o = judge.rfind_json(res.get("reply", ""), "project_groups")
            if not o:
                err = "parse"
                log("    [!] 응답 형식이 달라 여기까지 반영합니다")
                break
            g1 = _apply_groups(aliases["projects"], o.get("project_groups"), pj, "과제", detail, dropped)
            g2 = _apply_groups(aliases["details"], o.get("detail_groups"), dt, "세부업무", detail, dropped)
            n_ai += g1 + g2
            log(f"    → {g1 + g2}건 통합")
            if g1 + g2 == 0:
                log("    더 묶을 것이 없습니다 — 정리 완료")
                break

    # 저장본은 항상 '완전히 평탄한' 매핑으로 — 그래야 설치본(resolve_chain 결함 포함)이
    # 읽어도 사슬을 풀 필요 없이 바로 대표 이름이 나온다
    for key in ("projects", "details"):
        flat = flatten_chain(aliases[key])
        aliases[key] = {k: flat.get(k, v) for k, v in aliases[key].items()}
    save_aliases(share, aliases)
    n_alias = len(aliases["projects"]) + len(aliases["details"])
    log(f"  저장: {ALIAS_FILE} (과제 {len(aliases['projects'])} · "
        f"세부업무 {len(aliases['details'])} 매핑) — 팀 화면·리포트 전부에 적용됩니다")
    fab = [d for d in dropped if not d.endswith(_TAIL_DROP)]
    if dropped:
        log(f"  건너뜀 {len(dropped)}개 — 목록에 없는 이름 {len(fab)} · 괄호 꼬리 다름 "
            f"{len(dropped) - len(fab)}: {', '.join(dropped[:5])}")
    out = {"ok": True, "groups": len(detail), "aliases": n_alias, "members": len(members),
           "rounds": rounds, "rule": n1 + n2, "ai": n_ai, "detail": detail[:10],
           "dropped": len(dropped), "share": share}
    if err and sender is not None:
        out["hint"] = ("Copilot 왕복이 도중에 실패해 규칙 정리와 그때까지의 결과만 반영했습니다"
                       f"({err}). 다시 누르면 이어서 정리합니다.")
    elif fab and not detail:
        out["hint"] = ("Copilot 이 목록에 없는 이름을 만들어 냈습니다("
                       + ", ".join(fab[:3]) + " 등) — 다시 눌러 보세요.")
    elif not detail:
        out["hint"] = "통합할 유사 항목이 없었습니다"
    return out


# ══ ② 팀 보고서 재료 ═══════════════════════════════════════════════════════
def load_adjust(share, log=say):
    """손으로 편집하는 파일이다 — 어떤 오형식이 와도 보고서 생성이 죽으면 안 된다(검증 확정)"""
    empty = {"excluded_people": [], "excluded_cells": []}
    p = os.path.join(share, ADJUST_FILE)
    if not os.path.exists(p):
        return empty
    try:
        o = json.load(open(p, encoding="utf-8-sig"))
        if not isinstance(o, dict):
            raise ValueError("객체가 아님")
        ppl = [str(x) for x in (o.get("excluded_people") or [])
               if isinstance(x, str) and x.strip()]
        cells = [[str(x[0]), str(x[1])] for x in (o.get("excluded_cells") or [])
                 if isinstance(x, (list, tuple)) and len(x) >= 2]
        return {"excluded_people": ppl, "excluded_cells": cells}
    except Exception as e:  # noqa: BLE001 - 조정 파일 하나로 전체가 죽지 않게
        log(f"    [!] {ADJUST_FILE} 형식이 이상해 무시합니다 ({type(e).__name__}) — "
            "보고서의 [조정 내용 내보내기]가 만든 JSON 그대로 저장하세요.")
        return empty


# 후보명 비교축 — 조사·'~화' 꼬리·수식어(봇/에이전트/자동…)를 걷어낸 내용어 집합.
_CAND_STOP = {"봇", "bot", "에이전트", "agent", "ai", "시스템", "툴", "tool", "도구",
              "프로그램", "매크로", "자동", "자동화", "반자동", "기반"}
_JOSA = ("으로", "에서", "부터", "까지", "을", "를", "이", "가", "은", "는",
         "와", "과", "의", "로", "에", "도", "만")


def cand_tokens(name):
    toks = set()
    for t in fold(name).split():
        for j in _JOSA:
            if t.endswith(j) and len(t) - len(j) >= 2:
                t = t[:-len(j)]
                break
        if t.endswith("화") and len(t) > 2:
            t = t[:-1]                       # 자동화→자동
        if t and t not in _CAND_STOP:
            toks.add(t)
    for t in re.findall(r"[0-9a-z가-힣]+", _note(name)):  # '(시험)' 어순 꼬리는 본문 취급
        if t not in _CAND_STOP:
            toks.add(t)
    return toks


_NUM_TOK = re.compile(r"^[a-z]?\d+[가-힣a-z]*$|^[a-z](?:라인|동|호기|공장)$")


def _cand_marks(name):
    """번호·차수·라인 표기 — '1공장/2공장'·'1차/2차'·'A라인/B라인'은 다른 대상이다"""
    return {t for t in fold(name).split() if _NUM_TOK.match(t)}


def cand_same(a, b):
    na, nb = _note(a), _note(b)
    if na and nb and na != nb:               # (양산) vs (선행) — 실제 구분, 안 묶는다
        return False
    if _cand_marks(a) != _cand_marks(b):     # 번호 하나만 달라도 딴 후보
        return False
    if ukey(a) == ukey(b):
        return True
    x, y = cand_tokens(a), cand_tokens(b)
    if not x or not y:
        return False
    j = len(x & y) / len(x | y)
    return j > 0.75 or (bigram_dice(a, b) >= 0.9 and j >= 0.5)


def merge_candidates(agentic):
    """인별 '신규 Agentic 후보'를 유사한 것끼리 통합 — 표기·어순·조사 변형까지"""
    items = []
    for a in agentic:
        if not isinstance(a, dict):
            continue
        new = a.get("new")
        for n in (new if isinstance(new, list) else []):
            if not isinstance(n, dict):          # 한 인원의 ['x'] 한 줄이 §5 전체를 죽이지 않게
                continue
            nm = str(n.get("name") or "").strip()
            if not nm:
                continue
            items.append({"name": nm, "logic": str(n.get("logic") or ""),
                          "reason": str(n.get("reason") or ""),
                          "mm": _fnum(n.get("load_mm"), 0.0), "who": str(a.get("owner") or "")})
    groups = []
    for it in items:
        hit = None
        itn = _note(it["name"])
        for g in groups:
            g_notes = {_note(n) for n in g["names"]} - {""}
            if itn and g_notes and itn not in g_notes:
                continue
            if any(cand_same(n, it["name"]) for n in g["names"]):
                hit = g
                break
        if hit is None:
            groups.append({"name": it["name"], "names": {it["name"]}, "logic": it["logic"],
                           "reason": it["reason"], "mm": it["mm"], "who": {it["who"]}})
        else:
            hit["names"].add(it["name"])
            hit["who"].add(it["who"])
            hit["mm"] += it["mm"]
            if len(it["name"]) > len(hit["name"]):
                hit["name"] = it["name"]
            if len(it["logic"]) > len(hit["logic"]):
                hit["logic"] = it["logic"]
            if len(it["reason"]) > len(hit["reason"]):
                hit["reason"] = it["reason"]
    for g in groups:
        g["who"] = sorted(g["who"])
        g["names"] = sorted(g["names"])
    groups.sort(key=lambda g: -(len(g["who"]) * 10 + g["mm"]))
    return groups


def heat(v, vmax):
    """순차(한 색 파랑) 배경 — 값이 클수록 진하게, 50% 넘으면 흰 글자"""
    if v <= 0 or vmax <= 0:
        return "", ""
    steps = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"]
    i = min(len(steps) - 1, int(v / vmax * len(steps)))
    return steps[i], ("#ffffff" if i >= 3 else "#0b0b0b")


def find_member_file(mdir, prefix, tag):
    r"""인별 폴더에서 산출물 하나 — **기간(tag)이 달라도 찾는다**(같은 이름이면 최신)."""
    p = os.path.join(mdir, f"{prefix}_{tag}.json")
    if tag and os.path.exists(p):
        return p
    fs = glob.glob(os.path.join(mdir, f"{prefix}_*.json"))
    if not fs:
        return ""
    try:
        return max(fs, key=os.path.getmtime)
    except OSError:
        return fs[-1]


def collect_agentic_all(members):
    """인별 Agentic 결과 — 기간이 달라도 모은다. 어떤 파일을 썼는지도 남긴다."""
    out = []
    for m in members:
        p = find_member_file(m["dir"], "agentic", m.get("tag", ""))
        if not p:
            continue
        try:
            with open(p, encoding="utf-8-sig") as f:
                a = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(a, dict):
            continue
        a = _agg().norm_agentic(a)            # dict 항목만 · fit/load_mm 숫자 강제(화면 JS 도 이것을 믿는다)
        atag = str(a.get("tag") or "")
        out.append({"owner": m["owner"], "match": a.get("match") or [],
                    "new": a.get("new") or [], "misassigned": a.get("misassigned") or [],
                    "tag": atag, "file": os.path.basename(p),
                    "other_period": bool(m.get("tag") and atag and atag != str(m["tag"]))})
    return out


def merge_similar(pairs):
    r"""(이름, {인원: MM}) 목록에서 **유사한 이름끼리 합친다**. 괄호 꼬리가 다르면 합치지 않는다."""
    groups = []
    for name, row in pairs:
        hit = None
        for g in groups:
            if ukey(name) == ukey(g["name"]) or (
                    _note(name) == _note(g["name"])
                    and bigram_dice(name, g["name"]) >= 0.8):
                hit = g
                break
        if hit is None:
            groups.append({"name": name, "names": {name}, "row": dict(row)})
        else:
            hit["names"].add(name)
            for w, v in row.items():
                hit["row"][w] = hit["row"].get(w, 0.0) + v
            if (len(str(name)), str(name)) > (len(str(hit["name"])), str(hit["name"])):
                hit["name"] = name
    for g in groups:
        g["names"] = sorted(g["names"])
        g["total"] = round(sum(g["row"].values()), 3)
    groups.sort(key=lambda g: -g["total"])
    return groups


PAL10 = ["#2a78d6", "#0e8c7a", "#a61b4a", "#e08a00", "#6c4fb8", "#3d8f3d",
         "#c05a78", "#4a7f9e", "#8a6d3b", "#556270"]


def stack_rows(groups, owners, width=300, label_w=150):
    r"""과제 × 인원 누적바 — 원본 팀 화면(TEAM_PAGE pjstack)과 같은 도식."""
    if not groups:
        return '<div class="note">데이터 없음</div>'
    gmax = max([g["total"] for g in groups] or [0.001]) or 0.001
    out = []
    for g in groups:
        segs = "".join(
            f'<i style="display:inline-block;height:14px;'
            f'width:{max(0.0, g["row"][o] / gmax * width):.1f}px;background:{PAL10[i % len(PAL10)]}"'
            f' title="{esc(o)} {g["row"][o]:.2f} MM"></i>'
            for i, o in enumerate(owners) if g["row"].get(o))
        alt = (f'<div class="sub">표기 {len(g["names"])}종 통합: '
               f'{esc(" / ".join(g["names"][:3]))}</div>' if len(g["names"]) > 1 else "")
        out.append(
            '<div style="display:flex;align-items:center;gap:8px;margin:4px 0">'
            f'<span style="width:{label_w}px;flex:0 0 {label_w}px;font-size:11.5px;'
            f'text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
            f'title="{esc(g["name"])}"><b>{esc(g["name"])}</b></span>'
            f'<span style="white-space:nowrap;flex:0 0 auto">{segs}</span>'
            f'<span style="font-size:11px;color:#5a626b;white-space:nowrap">'
            f'{g["total"]:.2f} MM</span></div>' + alt)
    return ("<div style='overflow-x:auto'>" + "".join(out) + "</div>")


def stack_legend(owners):
    return "".join(
        f'<span style="font-size:11px;margin-right:10px">'
        f'<span class="dot" style="background:{PAL10[i % len(PAL10)]}"></span>{esc(o)}</span>'
        for i, o in enumerate(owners))


def _flow_mm(fl, rows=None):
    r"""이 흐름의 MM — 워크플로우 JSON 값이 비면 **본인 mm_rows 실측**으로 되살린다.
    mm 칸이 'abc'·문자열·숫자 그대로여도 죽지 않는다(한 인원의 오형식이 보고서를 막지 않게)."""
    mm = fl.get("mm")
    if not isinstance(mm, dict):
        v0 = _fnum(mm)
        if v0:
            return v0
        mm = {}
    v = _fnum(mm.get("mm"))
    if v:
        return v
    d = mm.get("details")
    if isinstance(d, dict) and d:
        try:
            return float(sum(float(v) for v in d.values()))
        except (TypeError, ValueError):
            pass
    if not rows:
        return 0.0
    proj, det = flow_unit(fl)
    if proj == "(과제 미상)":
        proj = ""
    tot = 0.0
    for r in rows:
        p2, d2 = ukey(r.get("Level 2")), ukey(r.get("Level 3"))
        if det:
            if (not proj or p2 == ukey(proj)) and d2 == ukey(det):
                tot += r["_mm"]
        elif proj and p2 == ukey(proj):
            tot += r["_mm"]
    return round(tot, 3)


def _flow_ax(fl):
    """이 흐름 자체의 AX 비율 — 상 100% + 중 50%, 그 사람이 실제로 적은 단계 기준"""
    st = [s for s in (fl.get("steps") or []) if isinstance(s, dict)]
    if not st:
        return 0.0
    hi = sum(1 for s in st if (s.get("agent") or "") == "상")
    mid = sum(1 for s in st if (s.get("agent") or "") == "중")
    return (hi + mid * 0.5) / len(st)


def _island(html_text, el_id):
    m = re.search(r'<script type="application/json" id="' + el_id + r'">(.*?)</script>',
                  html_text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("<\\/", "</"))
    except ValueError:
        return None


def _flow_print(owner, fl):
    r"""흐름 지문 — (**사람**, 과제, 단계 구성, 역할). 사람을 빼면 같은 단계를 반복하는 두 사람의
    흐름이 '같은 자료'로 보여 한쪽이 통째로 버려진다(실측)."""
    return (fold(str(owner)),
            fold(fl.get("model")),
            frozenset(fold(s.get("name")) for s in (fl.get("steps") or []) if s.get("name")),
            fold(fl.get("role")))


_STEP_STR = ("name", "agent", "cycle", "desc", "agent_how", "evidence")
_FLOW_STR = ("model", "project", "detail", "role", "summary")


def norm_flow(fl):
    """흐름 하나를 믿을 수 있는 형태로 — dict 만, steps 는 list 의 dict 항목만, 표시 칸은 str.
    None 이면 버릴 흐름. (한 인원의 steps:'notalist'·[null,'x',5]·cycle:{…} 이 팀 보고서를 죽이던 결함)"""
    if not isinstance(fl, dict) or not isinstance(fl.get("steps"), list):
        return None
    steps = []
    for s in fl["steps"]:
        if not isinstance(s, dict):
            continue
        s2 = dict(s)
        for k in _STEP_STR:
            if s2.get(k) is not None and not isinstance(s2[k], str):
                s2[k] = str(s2[k])
        steps.append(s2)
    fl2 = dict(fl, steps=steps)
    for k in _FLOW_STR:
        if fl2.get(k) is not None and not isinstance(fl2[k], str):
            fl2[k] = str(fl2[k])
    return fl2


def gather_flows(share, html_dir):
    """워크플로우 재료 — ① 취합 폴더 인별 workflow_*.json ② 개인 리포트/얼린 보고서 HTML.
    같은 (사람, 과제) 는 단계가 많은 쪽 하나만 남기고, HTML 쪽은 지문이 같으면 버린다(이중 합산 방지).
    HTML 의 owner 가 인원(member.json)이 아니면 사람으로 세지 않고 src_n["external"] 에 이름만 남긴다
    (옛 자료·다른 팀 파일이 KPI '워크플로우 N명' 에 끼던 결함). 교체된 흐름은 옛 출처 계수를 되돌린다."""
    ag = _agg()
    flows, src_n = {}, {"server": 0, "html": 0, "external": {}}
    prints = set()
    rows_by = {}                      # owner -> mm_rows (MM 되살리기용)
    members = ag.load_members(share)
    known = {_owner_key(m["owner"]) for m in members}

    def add_rows(owner, rows):
        out = []
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            mmv = _fnum(r.get("mm"))
            if mmv is None:
                continue
            r = dict(r)
            r["_mm"] = mmv
            out.append(r)
        if out:
            rows_by.setdefault(fold(str(owner)), out)

    def put(owner, fl, srckind):
        fl = norm_flow(fl)
        if fl is None:
            return
        model = str(fl.get("model") or "").strip()
        if not model:                            # project/detail 만 있는 흐름도 살린다
            _p, _d = flow_unit(fl)
            model = f"{_p} / {_d}" if _d else _p
            if model and model != "(과제 미상)":
                fl = dict(fl, model=model)
        if not model:
            return
        fp = _flow_print(owner, fl)
        if srckind == "html" and fp in prints:
            return                       # 그 사람의 서버 취합분과 같은 자료 — 두 번 세지 않는다
        key = (ukey(owner), ukey(model))
        cur = flows.get(key)
        if cur is None or len(fl.get("steps") or []) > len(cur["fl"].get("steps") or []):
            if cur is not None:          # 교체 — 옛 출처의 계수를 되돌린다(각주 합이 맞게)
                src_n[cur["src"]] = max(0, src_n.get(cur["src"], 0) - 1)
            flows[key] = {"owner": str(owner), "fl": fl, "_html": srckind == "html", "src": srckind}
            src_n[srckind] += 1
        prints.add(fp)

    def put_html(who, fls):
        """HTML 출처 — 인원이 아니면 세지 않고 이름만 기록"""
        fls = fls if isinstance(fls, list) else []
        if _owner_key(who) not in known:
            src_n["external"][str(who)] = src_n["external"].get(str(who), 0) + len(fls)
            return False
        for fl in fls:
            put(who, fl, "html")
        return True

    def drop_coarse():
        r"""한 사람이 '과제' 단위 흐름과 '과제 / 담당업무' 단위 흐름을 함께 냈으면 굵은 쪽을 버린다."""
        fine = {}
        for (own, _mdl), v in flows.items():
            fl = v["fl"]
            base = fold(fl.get("project") or (str(fl.get("model") or "").split(" / ")[0]))
            if fl.get("detail") or " / " in str(fl.get("model") or ""):
                fine.setdefault((own, base), 0)
                fine[(own, base)] += 1
        for key in [k for k in list(flows)
                    if (k[0], fold(str(flows[k]["fl"].get("model") or ""))) in fine
                    and " / " not in str(flows[k]["fl"].get("model") or "")]:
            src = "html" if flows[key].get("_html") else "server"
            flows.pop(key, None)
            src_n[src] = max(0, src_n.get(src, 0) - 1)

    for m in members:
        add_rows(m["owner"], m.get("rows"))       # 취합 엔진이 이미 읽어 둔 mm_rows
        p = os.path.join(m["dir"], f"workflow_{m.get('tag')}.json")
        o = None
        try:
            o = json.load(open(p, encoding="utf-8-sig")) if os.path.exists(p) else None
        except (OSError, ValueError):
            pass
        if not isinstance(o, dict):              # '[1,2]' 한 파일이 팀 보고서를 죽이지 않게
            continue
        fls = o.get("flows")
        for fl in (fls if isinstance(fls, list) else []):
            put(m["owner"], fl, "server")

    if html_dir and os.path.isdir(html_dir):
        for p in glob.glob(os.path.join(html_dir, "*.html")):
            try:
                txt = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            o = _island(txt, "lm-report-data")
            if isinstance(o, dict) and isinstance(o.get("workflow"), dict):
                who0 = str(o.get("owner") or "") or os.path.basename(p)
                if put_html(who0, o["workflow"].get("flows")):
                    add_rows(who0, o.get("rows"))     # 개인 리포트 섬에는 mm_rows 가 통째로 있다
                continue
            o = _island(txt, "lm-frozen-data")
            if isinstance(o, dict) and isinstance(o.get("/api/workflow"), dict):
                dash = o.get("/api/dash")
                dash = dash if isinstance(dash, dict) else {}
                lm = o.get("_lm")
                lm = lm if isinstance(lm, dict) else {}
                who = str(lm.get("owner") or "").strip()
                if not who:
                    who = re.sub(r"^LoadMonitor_보고서_|\.html$", "",
                                 os.path.basename(p))
                    who = re.sub(r"[_ ]?\d{4}-\d{2}-\d{2}.*$", "", who).strip("_ ") or who
                if put_html(who, o["/api/workflow"].get("flows")):
                    add_rows(who, dash.get("rows"))
    drop_coarse()
    return list(flows.values()), src_n, rows_by


def _pivot_bw(o):
    """얼린 보고서 섬에서 by_worktype 피벗 — LM22 화면은 /api/extra 의 pivots 에 싣는다.
    /api/review 는 {gran, groups} 뿐이라 거기서만 찾던 분기는 항상 비어 있었다(검증 확정).
    옛 사본 호환으로 review 쪽도 한 번 더 본다."""
    ex = o.get("/api/extra")
    if isinstance(ex, dict) and isinstance(ex.get("pivots"), dict):
        bw = ex["pivots"].get("by_worktype")
        if isinstance(bw, dict) and bw:
            return bw
    for k in ("/api/review?g=all", "/api/review?g=month", "/api/review?g=week"):
        rv = o.get(k)
        if isinstance(rv, dict) and isinstance(rv.get("pivots"), dict):
            bw = rv["pivots"].get("by_worktype")
            if isinstance(bw, dict) and bw:
                return bw
    return {}


def _sum_wt_rows(rows, wt):
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        k2 = str(r.get("유형") or "").strip() or "사무"
        mmv = _fnum(r.get("mm"))
        if mmv is not None:
            wt[k2] = wt.get(k2, 0.0) + mmv


def collect_wt_html(html_dir):
    r"""개인 HTML 에서 **화면이 보여주는 업무유형 값 그대로** 걷는다.
    ① 얼린 보고서(lm-frozen-data): /api/extra 의 pivots.by_worktype(옛 사본은 /api/review), 없으면
       /api/dash rows 합산.
    ② 개인 PC 에서 만든 분석 리포트(lm-report-data): rows 합산. 복원 사본(rebuilt_from)은 제외."""
    out = {}
    if not (html_dir and os.path.isdir(html_dir)):
        return out
    for p2 in sorted(glob.glob(os.path.join(html_dir, "*.html"))):
        try:
            txt = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        who, wt, frozen = "", {}, False
        o = _island(txt, "lm-frozen-data")
        if isinstance(o, dict):
            frozen = True
            lm = o.get("_lm")
            lm = lm if isinstance(lm, dict) else {}
            who = str(lm.get("owner") or "").strip()
            for k2, v in _pivot_bw(o).items():
                mmv = _fnum(v.get("mm") if isinstance(v, dict) else v)
                if mmv is not None:
                    wt[str(k2)] = wt.get(str(k2), 0.0) + mmv
            if not wt:
                dash = o.get("/api/dash")
                _sum_wt_rows((dash if isinstance(dash, dict) else {}).get("rows"), wt)
        else:
            o = _island(txt, "lm-report-data")
            if not isinstance(o, dict) or str(o.get("rebuilt_from") or ""):
                continue
            who = str(o.get("owner") or "").strip()
            _sum_wt_rows(o.get("rows"), wt)
        if not (who and wt):
            continue
        k0 = ukey(who)
        if k0 not in out or (frozen and not out[k0]["frozen"]):
            out[k0] = {"owner": who, "frozen": frozen,
                       "wt": {k2: round(v, 3) for k2, v in wt.items() if v}}
    return out


def flow_unit(fl):
    r"""이 흐름의 단위 — (상위 개체, 중위/하위 개체). 워크플로우는 담당 업무 단위여야 뜻이 통한다."""
    p = str(fl.get("project") or "").strip()
    d = str(fl.get("detail") or "").strip()
    m = str(fl.get("model") or "").strip()
    mp = md = ""
    if " / " in m:
        mp, md = m.rsplit(" / ", 1)
        mp, md = mp.strip(), md.strip()
    p = p or mp
    d = d or md
    if p or d:
        return (p or "(과제 미상)"), d
    return (m or "(과제 미상)"), ""


def cluster_flows(items, share, rows_by=None):
    r"""담당 업무(중위/하위) 단위로 유사한 것끼리 묶는다 — 같은 과제 안에서만."""
    ag = _agg()
    al = ag.load_aliases(share)
    pmap, dmap = al["projects"], al["details"]

    def sig(fl):
        return {fold(s.get("name")) for s in (fl.get("steps") or []) if s.get("name")}

    clusters, coarse = [], []
    for it in items:
        fl = it["fl"]
        p0, d0 = flow_unit(fl)
        proj = pmap.get(p0, p0)
        det = dmap.get(d0, d0) if d0 else ""
        if not det:                                   # 상위 개체 단위 — 유형으로 삼지 않는다
            coarse.append({"owner": it["owner"], "project": proj, "fl": fl})
            continue
        s = sig(fl)
        hit = None
        for c in clusters:
            if ukey(proj) != ukey(c["project"]):
                continue
            same_note = _note(det) == _note(c["detail"])
            if ukey(det) == ukey(c["detail"]) or (
                    same_note and bigram_dice(det, c["detail"]) >= 0.75):
                hit = c
                break
            if (same_note and len(s) >= 3 and len(c["sig"]) >= 3
                    and bigram_dice(det, c["detail"]) >= 0.4):
                inter = len(s & c["sig"])
                uni = len(s | c["sig"]) or 1
                if inter / uni >= 0.6:
                    hit = c
                    break
        if hit is None:
            clusters.append({"project": proj, "detail": det, "sig": set(s), "items": [it]})
        else:
            hit["sig"] |= s
            hit["items"].append(it)
            if (len(str(det)), str(det)) > (len(str(hit["detail"])), str(hit["detail"])):
                hit["detail"] = det

    out = []
    for c in clusters:
        n = len(c["items"])
        who = sorted({it["owner"] for it in c["items"]})
        per = []
        for it in c["items"]:
            v = _flow_mm(it["fl"], (rows_by or {}).get(fold(it["owner"])))
            per.append((it, v))
        mm = sum(v for _it, v in per)
        mm_by = {}
        for it, v in per:
            mm_by[it["owner"]] = round(mm_by.get(it["owner"], 0.0) + v, 2)
        ax_mm = round(sum(v * _flow_ax(it["fl"]) for it, v in per), 3)
        ax_ratio = (ax_mm / mm) if mm else round(
            sum(_flow_ax(it["fl"]) for it, _v in per) / max(1, len(per)), 3)
        pos, cnt, name_rep, agents, cycles = {}, {}, {}, {}, {}
        descs, hows = {}, {}
        for it in c["items"]:
            for i, s in enumerate(it["fl"].get("steps") or []):
                k = fold(s.get("name"))
                if not k:
                    continue
                pos[k] = pos.get(k, 0) + i
                cnt[k] = cnt.get(k, 0) + 1
                name_rep.setdefault(k, s.get("name"))
                a = s.get("agent") or "중"
                agents.setdefault(k, {}).update({a: agents.get(k, {}).get(a, 0) + 1})
                if s.get("cycle"):
                    cycles[k] = s["cycle"]
                d = str(s.get("desc") or "")
                if len(d) > len(descs.get(k, "")):
                    descs[k] = d
                hw = str(s.get("agent_how") or "")
                if len(hw) > len(hows.get(k, "")):
                    hows[k] = hw
        keep = [k for k in cnt if cnt[k] * 2 >= n] or sorted(cnt, key=lambda k: -cnt[k])[:7]
        keep.sort(key=lambda k: pos[k] / cnt[k])
        all_steps = [{"name": name_rep[k],
                      "agent": max(agents.get(k, {"중": 1}), key=lambda a: agents[k].get(a, 0)),
                      "cycle": cycles.get(k, ""), "n": cnt[k],
                      "desc": descs.get(k, ""), "how": hows.get(k, "")} for k in keep]
        steps = all_steps[:10]
        roles = [it["fl"].get("role") or "" for it in c["items"] if it["fl"].get("role")]
        from collections import Counter as _C
        cyc = _C(st.get("cycle") for it in c["items"]
                 for st in (it["fl"].get("steps") or []) if st.get("cycle"))
        out.append({"project": c["project"], "detail": c["detail"],
                    "model": f'{c["project"]} / {c["detail"]}',
                    "who": who, "flows": n, "mm": round(mm, 2),
                    "ax_mm": ax_mm, "ax_ratio": round(ax_ratio, 3),
                    "mm_by": mm_by, "cycle_top": (cyc.most_common(1)[0][0] if cyc else ""),
                    "steps": steps, "steps_total": len(all_steps),
                    "role": (roles[0] if roles else ""),
                    "agent_hi": sum(1 for s in all_steps if s["agent"] == "상"),
                    "agent_hi_names": [s["name"] for s in all_steps if s["agent"] == "상"],
                    "solo": len(who) == 1})
    out.sort(key=lambda c: (-len(c["who"]), -c["mm"]))
    return out, coarse


def group_by_project(clusters, rows_by=None):
    """상위 개체(과제)로 묶는다 — 그 안에 어떤 담당 업무 워크플로우가 있는지 펼쳐 보게"""
    g = {}
    for c in clusters:
        k = ukey(c["project"])
        d = g.setdefault(k, {"project": c["project"], "types": [], "mm": 0.0, "ax_mm": 0.0,
                             "who": set(), "flows": 0})
        if len(str(c["project"])) > len(str(d["project"])):
            d["project"] = c["project"]
        d["types"].append(c)
        d["mm"] += c["mm"]
        d["ax_mm"] += c["ax_mm"]
        d["who"].update(c["who"])
        d["flows"] += c["flows"]
    out = []
    for d in g.values():
        d["who"] = sorted(d["who"])
        d["mm"] = round(d["mm"], 2)
        d["ax_mm"] = round(d["ax_mm"], 2)
        d["types"].sort(key=lambda c: (-len(c["who"]), -c["mm"]))
        d["shared"] = sum(1 for c in d["types"] if len(c["who"]) > 1)
        out.append(d)
    out.sort(key=lambda d: (-len(d["who"]), -d["mm"]))
    return out


# 원본 대시보드(ui/app.py AGENT_C)와 같은 색 — 범례와 배지가 어긋나면 표를 못 읽는다
_AGENT_C = {"상": "#1d8a4a", "중": "#c98a00", "하": "#8b929b"}


def find_member_any(mdir, prefix, tag, exts=(".json",)):
    """인별 폴더에서 prefix_*.확장자 하나 — tag 우선, 없으면 최신"""
    for ext in exts:
        p = os.path.join(mdir, f"{prefix}_{tag}{ext}")
        if tag and os.path.exists(p):
            return p
    fs = []
    for ext in exts:
        fs += glob.glob(os.path.join(mdir, f"{prefix}_*{ext}"))
    if not fs:
        return ""
    try:
        return max(fs, key=os.path.getmtime)
    except OSError:
        return fs[-1]


def _parse_mm_rows(p, total_mm=None):
    """CSV 한 파일을 읽어 mm 을 복원한다 — mm 칸이 비면 share × total_mm 으로."""
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.DictReader(f))
    except (OSError, ValueError):
        return None
    for r in rows:
        v = None
        if str(r.get("mm") or "").strip() != "":
            try:
                v = float(r["mm"])
            except (TypeError, ValueError):
                v = None
        if v is None and total_mm:
            try:
                v = float(r.get("share") or 0) * float(total_mm)
            except (TypeError, ValueError):
                v = None
        elif v is None:
            try:
                if float(r.get("share") or 0) > 0:
                    r["_share_only"] = True
            except (TypeError, ValueError):
                pass
        r["mm"] = round(v or 0.0, 3)
    return rows


def _member_rows(mdir, tag, total_mm=None):
    """정제본 우선 — 개인 대시보드와 같은 규칙. 이 기간(tag) 파일이 하나라도 있으면 다른 기간이
    mtime 으로 이기지 못한다. total_mm 은 숫자로 강제('abc' 면 없는 것으로)."""
    total_mm = _fnum(total_mm)
    ref = os.path.join(mdir, f"mm_rows_{tag}_refined.csv") if tag else ""
    plain = os.path.join(mdir, f"mm_rows_{tag}.csv") if tag else ""
    ref = ref if (ref and os.path.exists(ref)) else ""
    plain = plain if (plain and os.path.exists(plain)) else ""
    p = ref or plain
    if ref and plain:
        try:
            if os.path.getmtime(plain) > os.path.getmtime(ref):
                p = plain
        except OSError:
            pass
    if not p:
        refs = glob.glob(os.path.join(mdir, "mm_rows_*_refined.csv"))
        plains = [x for x in glob.glob(os.path.join(mdir, "mm_rows_*.csv"))
                  if not x.endswith("_refined.csv")]
        if total_mm:
            best, best_key = "", None
            for c in refs + plains:
                rows_c = _parse_mm_rows(c, total_mm)
                if rows_c is None:
                    continue
                sc = sum(r["mm"] for r in rows_c)
                try:
                    mt = os.path.getmtime(c)
                except OSError:
                    mt = 0.0
                key = (abs(sc - float(total_mm)), -mt)
                if best_key is None or key < best_key:
                    best, best_key = c, key
            p = best
        else:
            cands = refs or plains
            try:
                p = max(cands, key=os.path.getmtime) if cands else ""
            except OSError:
                p = cands[-1] if cands else ""
    if not p:
        return [], ""
    rows = _parse_mm_rows(p, total_mm)
    if rows is None:
        return [], ""
    rows.sort(key=lambda r: -r["mm"])
    return rows, os.path.basename(p)


def member_report(mdir, member, out_dir):
    r"""팀 서버에 올라온 **JSON·CSV 만으로** 그 사람의 분석 리포트를 복원한다.

    팀 서버는 파일 이름을 제한해 HTML 을 받지 않는다. 그런데 리포트를 만들 재료(mm_rows·mm_meta·
    workflow·agentic·member.json)는 전부 올라와 있으니 팀장 PC 에서 다시 만든다."""
    owner = str(member.get("owner") or "").strip() or os.path.basename(mdir)
    tag = str(member.get("tag") or "")
    rows, rows_file = _member_rows(mdir, tag, member.get("total_mm"))

    def _load_obj(prefix):
        """인별 JSON 하나 — 객체가 아니면(손편집 '[]') 없는 것으로. 한 파일의 오형식이 리포트를 막지 않게"""
        p9 = find_member_any(mdir, prefix, tag)
        if not p9:
            return {}
        try:
            with open(p9, encoding="utf-8-sig") as f:
                o9 = json.load(f)
        except (OSError, ValueError):
            return {}
        return o9 if isinstance(o9, dict) else {}

    meta = _load_obj("mm_meta")
    wf = _load_obj("workflow")
    ag = _load_obj("agentic")
    if ag:
        ag = _agg().norm_agentic(ag)          # dict 항목만 · fit/load_mm 숫자 강제
    if not rows and not wf and not ag:
        return None

    period = member.get("period") or meta.get("period") or ["", ""]
    if isinstance(period, str):
        period = period.split("~") if "~" in period else [period]
    if not isinstance(period, list) or not period:
        period = ["", ""]
    d0, d1 = (str(period[0] or "").strip() or "?"), (str(period[-1] or "").strip() or "?")
    d0e, d1e = esc(d0), esc(d1)                 # 기간도 업로드된 값 — 제목·머리글에 그대로 박지 않는다
    total = round(sum(r["mm"] for r in rows), 2) or _fnum(member.get("total_mm"), 0.0)
    avail = _fnum(member.get("avail_mm"))
    if avail is None:
        avail = _fnum(meta.get("avail_mm"))
    pct = _fnum(member.get("load_pct"))
    if pct is None:
        pct = _fnum(meta.get("load_pct"))
    if pct is None and avail:
        pct = round(total / avail * 100)
    an9, ld9 = _fint(member.get("anomaly_days"), 0), _fint(member.get("long_days"), 0)
    anom_txt = " · ".join(([f"PC 기록 이상 {an9}일"] if an9 > 0 else [])
                          + ([f"16h 초과 {ld9}일"] if ld9 > 0 else []))
    anom_txt = f" · {anom_txt}" if anom_txt else ""
    # D5 — 측정 방식·신뢰도(member.json 우선, 없으면 올라온 mm_meta 의 measure/coverage)
    ag9 = _agg()
    m9 = dict(member)
    for k9 in ("measure", "coverage", "cfg_used"):
        if not isinstance(m9.get(k9), dict):
            v9 = meta.get(k9) if isinstance(meta.get(k9), dict) else (meta.get("mm_basis") or {}).get(k9)
            if isinstance(v9, dict):
                m9[k9] = v9
    m9["measure"] = ag9.norm_measure(m9.get("measure"))
    m9["coverage"] = ag9.norm_coverage(m9.get("coverage"))
    meas_txt = ag9.measure_text(m9)
    meas_txt = f" · 측정 {meas_txt}" if meas_txt else ""
    cov_badge = ag9.coverage_badge(m9)
    cov_note = ""
    if (m9.get("coverage") or {}).get("grade") == "unreliable":
        cov_note = (" · <b style='color:#c0122f'>측정 불충분</b> — PC 가동 기록·창 샘플러·Outlook 일정이 모두 비어 "
                    "근거가 파일 흔적뿐입니다(팀 비교 제외)")

    mmax = max([r["mm"] for r in rows] or [1]) or 1
    row_html = "".join(
        f"<tr><td>{esc(r.get('Level 1'))}</td><td>{esc(r.get('유형'))}</td>"
        f"<td><b>{esc(r.get('Level 2'))}</b></td><td>{esc(r.get('Level 3'))}</td>"
        f"<td>{esc(r.get('상세설명'))}</td><td class='num'><b>{r['mm']:.2f}</b></td>"
        f"<td style='width:100px'><span class='mmbar' "
        f"style='width:{max(2, round(r['mm'] / mmax * 90))}px'></span></td></tr>"
        for r in rows[:60]) or "<tr><td colspan=7 class='dim'>업무 행이 없습니다</td></tr>"

    by_pj = {}
    for r in rows:
        k = r.get("Level 2") or "공통"
        by_pj[k] = by_pj.get(k, 0.0) + r["mm"]
    by_pj = sorted(by_pj.items(), key=lambda kv: -kv[1])
    ptot = sum(v for _k, v in by_pj) or 1
    pj_bar = ('<div class="bigbar">' + "".join(
        f'<i style="width:{v / ptot * 100:.1f}%;background:{PAL10[i % len(PAL10)]}"'
        f' title="{esc(k)} {v:.2f} MM"></i>' for i, (k, v) in enumerate(by_pj))
        + '</div><div class="leg">' + "".join(
            f'<div><span class="dot" style="background:{PAL10[i % len(PAL10)]}"></span>'
            f'{esc(k)}<span class="v">{v:.2f} MM</span></div>'
            for i, (k, v) in enumerate(by_pj)) + "</div>") if by_pj else ""

    fl_cards = []
    flows_l = [norm_flow(f) for f in (wf.get("flows") if isinstance(wf.get("flows"), list) else [])]
    for i, f in enumerate([f for f in flows_l if f is not None]):
        st_l = f.get("steps") or []
        # 값은 업로드된 JSON — 화면에 낼 때 반드시 esc(order 칸의 저장형 XSS, 검증 확정)
        steps = "".join(
            f'<tr><td class="ord"><b>{esc(s.get("order", j + 1))}</b></td>'
            f'<td class="stn"><b>{esc(s.get("name"))}</b>'
            + (f'<div class="sub">{esc(s.get("cycle"))}</div>' if s.get("cycle") else "")
            + "</td><td>" + (esc(s.get("desc")) or '<span class="dim">설명 없음</span>')
            + (f'<div class="sub">근거: {esc(s.get("evidence"))}</div>'
               if s.get("evidence") else "")
            + f'</td><td class="agc"><span class="pill" '
            f'style="background:{_AGENT_C.get(str(s.get("agent") or "중"), "#8b929b")}">'
            f'Agent {esc(s.get("agent") or "중")}</span>'
            + (f'<div class="sub">{esc(s.get("agent_how"))}</div>'
               if s.get("agent_how") else "") + "</td></tr>"
            for j, s in enumerate(st_l))
        mm = f.get("mm")
        mmv = _fnum(mm.get("mm") if isinstance(mm, dict) else mm)
        mm_txt = f"{mmv:g} MM · " if mmv else ""
        fl_cards.append(
            f'<details{" open" if i == 0 else ""}><summary>{esc(f.get("model"))}'
            f'<span class="state">{mm_txt}단계 {len(st_l)}개 · '
            f'{esc(str(f.get("role") or "판단 유보").split("—")[0].strip())}</span></summary>'
            f'<div class="body"><div style="margin:2px 0 6px"><b>역할:</b> '
            f'{esc(f.get("role")) or "판단 유보"}</div>'
            + (f'<div class="note" style="margin:0 0 6px">{esc(f.get("summary"))}</div>'
               if f.get("summary") else "")
            + '<table style="margin-top:6px"><tr><th></th><th>단계</th><th>무슨 일</th>'
            f'<th>Agent 가능성</th></tr>{steps}</table></div></details>')
    flows_html = "".join(fl_cards) or (
        '<div class="card"><div class="note">담당자 워크플로우가 없습니다 — '
        '그 PC 에서 [분석 실행](AI 판정)을 돌리면 만들어집니다.</div></div>')

    def _fitbar(v):
        v = max(0, min(100, _fint(v, 0)))     # 'high' 같은 값은 0 — ValueError 로 리포트를 잃지 않게
        c = ["#e1e0d9", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf",
             "#184f95"][0 if v <= 0 else min(6, v // 17 + 1)]
        w = max(3, round(v * 0.9)) if v > 0 else 0
        return (f'<svg width="90" height="12" style="vertical-align:middle">'
                f'<rect width="90" height="12" rx="2" fill="#eef0f3"/>'
                f'<rect width="{w}" height="12" rx="2" fill="{c}"/>'
                f'<text x="{4 if v >= 45 else w + 4}" y="9.3" style="font-size:9px;'
                f'font-weight:700;fill:{"#fff" if v >= 45 else "#52514e"}">{v}%</text></svg>')

    match = [m for m in (ag.get("match") or []) if isinstance(m, dict) and _fint(m.get("fit"), 0) > 0]
    m_html = "".join(
        f"<tr><td><b>{esc(m.get('task'))}</b> {esc(m.get('name'))}</td>"
        f"<td class='num'>{_fint(m.get('fit'), 0)}%</td><td style='width:100px'>{_fitbar(m.get('fit'))}</td>"
        f"<td class='num'><b>{_fnum(m.get('load_mm'), 0.0):.2f}</b>"
        + (f"<div class='sub'>안분 {m.get('load_mm_split'):.2f}</div>"
           if isinstance(m.get("load_mm_split"), (int, float))
           and m.get("load_mm_split") != m.get("load_mm") else "")
        + "</td><td>"
        + "".join(f'<span class="tag">{esc(w)}</span>' for w in (m.get("work") or []))
        + ("<div style='color:#c0392b;font-size:11px'>근거 없음 — 이 업무명을 자료에서 "
           "찾지 못했습니다</div>" if m.get("evidence_rows") == 0 else "")
        + (f"<div class='sub'>{esc(m.get('reason'))}</div>" if m.get("reason") else "")
        + "</td></tr>"
        for m in match[:12]) or "<tr><td colspan=5 class='dim'>Agentic 매칭 결과가 없습니다</td></tr>"

    island = json.dumps({
        "kind": "lm-personal-report", "owner": owner, "host": member.get("host", ""),
        "period": [d0, d1], "tag": tag, "total_mm": total, "avail_mm": avail,
        "load_pct": pct, "rows_file": rows_file, "rows": rows,
        "measure": m9.get("measure"), "coverage": m9.get("coverage"),
        "workflow": wf, "agentic": ag, "rebuilt_from": "팀서버 업로드 자료",
        "generated": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False).replace("<", "\\u003c")

    pct_txt = _agg().pct_text(pct)
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>업무 분석 리포트 — {esc(owner)} {d0e}~{d1e}</title><style>
body{{font:13px/1.55 'Malgun Gothic','Segoe UI',sans-serif;color:#2c333b;background:#f4f6f8;margin:0}}
.wrap{{max-width:1080px;margin:0 auto;padding:16px 20px 60px}}
h1{{font-size:18px;margin:10px 0 2px;color:#1c232b}}
.card{{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:12px}}
.card h2{{font-size:13px;margin:0 0 10px;color:#2c333b}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}}
.kpi{{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:12px 14px}}
.kpi .lb{{font-size:10.5px;color:#8b929b}}
.kpi .vl{{font-size:21px;font-weight:800;margin:2px 0;letter-spacing:-0.5px}}
.kpi .nt{{font-size:10.5px;color:#5a626b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
@media(max-width:860px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:520px){{.kpis{{grid-template-columns:1fr}}.wrap{{padding:12px}}}}
.state{{font-size:12px;color:#5a626b;font-weight:400;margin-left:8px}}
.note{{font-size:10.5px;color:#8b929b;margin-top:8px;line-height:1.6}}
.dim{{color:#8b929b;font-size:11.5px}} .sub{{color:#8b929b;font-size:11px}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
.leg{{font-size:11px;color:#4a5159;line-height:1.9}} .leg .v{{float:right;font-weight:700}}
.bigbar{{height:26px;border-radius:5px;overflow:hidden;display:flex;margin:6px 0 10px}}
.bigbar i{{display:block;height:100%}}
details{{margin-bottom:12px}}
details summary{{cursor:pointer;font-size:13px;font-weight:700;color:#2c333b;padding:12px 16px;
background:#fff;border:1px solid #e4e7eb;border-radius:8px;list-style:none}}
details summary::-webkit-details-marker{{display:none}}
details summary::before{{content:"▸ ";color:#8b929b}}
details[open] summary{{border-radius:8px 8px 0 0}}
details[open] summary::before{{content:"▾ "}}
details .body{{background:#fff;border:1px solid #e4e7eb;border-top:0;border-radius:0 0 8px 8px;
padding:14px 16px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#f6f8fa;color:#3d4a5c;text-align:left;padding:6px 8px;font-weight:700;
border-bottom:2px solid #e4e7eb;font-size:11px}}
td{{padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.ord{{width:26px;text-align:center;color:#8b929b}}
td.stn{{width:170px}} td.agc{{width:210px}}
.pill{{display:inline-block;padding:1px 8px;border-radius:9px;color:#fff;font-size:11px}}
.tag{{display:inline-block;background:#f0f3f7;border-radius:3px;padding:1px 7px;
margin:1px 3px 1px 0;font-size:10.5px;color:#3d444c}}
.mmbar{{display:inline-block;height:9px;border-radius:4px;background:#2a78d6;vertical-align:middle}}
.top{{background:#1c2b3a;color:#fff;padding:9px 14px;font-size:12px}}
</style></head><body>
<div class="top">개인 업무 분석 리포트 · {esc(owner)} · {d0e} ~ {d1e} ·
{time.strftime('%Y-%m-%d %H:%M')} 생성 · 사내 전용 —
<b>팀 서버에 올라온 자료로 팀장 PC 에서 다시 만든 사본</b>입니다</div>
<div class="wrap">
<h1>{esc(owner)} — 업무 로드 분석</h1>
<div class="dim">근거 {esc(rows_file)} · 신호 {esc(member.get('signals') or meta.get('signals'))}건
· 올린 시각 {esc(member.get('uploaded_at') or member.get('analyzed_at'))}{esc(anom_txt)}{esc(meas_txt)}{cov_badge}{cov_note}</div>

<div class="kpis" style="margin-top:10px">
<div class="kpi"><div class="lb">로드율 (투입 ÷ 가용)</div><div class="vl">{pct_txt}</div>
<div class="nt">야근은 상한 없이 반영(하루 24h 물리 한계만)</div></div>
<div class="kpi"><div class="lb">투입 MM</div><div class="vl">{total:.2f}</div>
<div class="nt">주력 {esc(by_pj[0][0] if by_pj else '—')}</div></div>
<div class="kpi"><div class="lb">가용 MM</div><div class="vl">
{'–' if avail is None else format(avail, '.2f')}</div>
<div class="nt">연차·휴가 차감</div></div>
<div class="kpi"><div class="lb">업무 항목</div><div class="vl">{len(rows)}</div>
<div class="nt">과제 {len(by_pj)}개</div></div>
</div>

<div class="card"><h2>1. 프로젝트 내 업무 로드 <span class="state">과제별 MM 배분</span></h2>
{pj_bar or '<div class="note">표시할 배분이 없습니다</div>'}</div>

<div class="card"><h2>2. 업무별 상세 <span class="state">MM 순</span></h2>
<div style="overflow-x:auto"><table><tr><th style="width:70px">Level 1</th>
<th style="width:52px">유형</th><th style="width:140px">과제</th>
<th style="width:120px">담당 업무</th><th>상세설명</th><th class="num" style="width:52px">MM</th>
<th></th></tr>{row_html}</table></div></div>

<h1 style="font-size:15px;margin:18px 0 8px">3. 담당자 워크플로우
<span class="state">역할 → 일의 순서 → 단계별 Agent 가능성</span></h1>
{flows_html}

<div class="card"><h2>4. Agentic AI 과제 매칭</h2>
<div style="overflow-x:auto"><table><tr><th>과제</th><th class="num" style="width:52px">적합률</th>
<th></th><th class="num" style="width:78px">대체 로드 MM</th>
<th>관련 업무 · 사유</th></tr>{m_html}</table></div></div>

<div class="note">이 리포트는 팀 서버에 올라온 분석 자료(mm_rows·mm_meta·workflow·agentic)로
다시 만든 것입니다 — 본인 PC 에서 만든 얼린 보고서와 화면 구성은 같고, 대시보드 조작
버튼만 없습니다.</div>
</div>
<script type="application/json" id="lm-report-data">{island}</script>
</body></html>"""

    os.makedirs(out_dir, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|]', "-", f"{owner}_분석리포트_{d0}_{d1}.html")
    dst = os.path.join(out_dir, name)
    try:
        _atomic_write(dst, doc)
    except OSError:
        return None
    return dst


def _is_rebuilt(path):
    """팀장 PC 에서 복원한 사본인가 — 섬에 rebuilt_from 표식이 있으면 복원본.
    본인 PC 가 --to-folder 로 넣은 진짜 분석리포트(<이름>_분석리포트_<tag>.html)는 표식이 없다."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return '"rebuilt_from"' in f.read()
    except OSError:
        return False


def rebuild_member_reports(share, html_dir, log=say):
    r"""팀 서버에 올라온 자료로 **인별 분석 리포트를 팀장 PC 에서 복원**한다.
    팀원이 직접 넣어 둔 HTML(분석리포트 아닌 이름)이 있으면 그것을 그대로 둔다."""
    ag = _agg()
    members = ag.load_members(share)
    if not members:
        return 0
    made, kept, stale, failed = 0, 0, 0, []

    def _drop_stale(owner, keep=""):
        """같은 사람의 옛 복원본(기간이 바뀌어 이름이 달라진 것·진짜 리포트가 생긴 뒤 남은 것)을 지운다 —
        옛 흐름이 계속 읽히지 않게. 복원본(rebuilt_from 표식)만 지우고 팀원이 직접 넣은 HTML 은 손대지 않는다."""
        n = 0
        pref = re.sub(r'[\\/:*?"<>|]', "-", f"{owner}_분석리포트_")
        for q in glob.glob(os.path.join(html_dir, "*.html")):
            if (os.path.basename(q).startswith(pref)
                    and (not keep or os.path.abspath(q) != os.path.abspath(keep)) and _is_rebuilt(q)):
                try:
                    os.remove(q)
                    n += 1
                except OSError:
                    pass
        return n

    for m in members:
        owner = m["owner"]
        try:                # 한 사람의 오형식이 **뒤 순서 인원**의 복원까지 막던 결함 — 그 사람만 건너뛴다
            own = [p for p in glob.glob(os.path.join(html_dir, "*.html"))
                   if ukey(owner) in ukey(os.path.basename(p))
                   and ("분석리포트" not in os.path.basename(p) or not _is_rebuilt(p))]
            if own:
                kept += 1
                stale += _drop_stale(owner)        # 진짜 리포트가 있으면 복원본은 군더더기
                continue
            p = member_report(m["dir"], m, html_dir)
            if not p:
                continue
            made += 1
            stale += _drop_stale(owner, keep=p)
        except Exception as e:  # noqa: BLE001 - 인원 하나 때문에 나머지 복원을 잃지 않는다
            failed.append(owner)
            log(f"  [!] {owner} 인별 리포트 복원 실패({type(e).__name__}: {e}) — 다음 인원 계속")
    if made or kept or stale:
        log(f"  인별 분석 리포트: 새로 만든 것 {made}명"
            + (f" · 팀원이 직접 올린 것 {kept}명은 그대로 둠" if kept else "")
            + (f" · 옛 복원본 {stale}개 정리" if stale else ""))
    return made


EMPTY_PJ = "(과제 미지정)"
# 비과제성(과제가 아닌 일) 판별 규칙 — 이름만 본다
NONPJ_SUB = ("공통", "동호회", "노조", "봉사")
NONPJ_TAIL = ("교육", "지원", "운영", "행사", "회의", "행정")


def _rule_nonpj(name):
    if str(name).startswith("회의·협업"):   # 배분 잔여 줄 — 과제가 아니다
        return True
    u = fold(name)
    if not u:                      # EMPTY_PJ 는 fold 가 괄호 꼬리로 전부 떼어 빈 값이 된다
        return True
    if u == "공통" or any(k in u for k in NONPJ_SUB):
        return True
    return any(u.endswith(k) for k in NONPJ_TAIL)


def is_nonproject(name, cls):
    """과제/비과제 판별 — 캐시(수동·Copilot 판정)가 규칙보다 우선한다."""
    if name in (cls.get("project") or ()):
        return False
    if name in (cls.get("nonproject") or ()):
        return True
    return _rule_nonpj(name)


def _load_groups_cache(share, fname):
    p = os.path.join(share, fname)
    try:
        o = json.load(open(p, encoding="utf-8-sig"))
        if isinstance(o, dict) and isinstance(o.get("groups"), dict):
            return {str(k): str(v) for k, v in o["groups"].items()}
    except (OSError, ValueError):
        pass
    return {}


def pjclass_refine(share, names, sender=None, log=say):
    r"""과제 이름을 '과제'와 '비과제(공통·교육·지원·운영)'로 나눈다. 규칙으로 확실한 것만 먼저
    정하고, 애매한 이름은 sender(Copilot)에 1회 물어 team_pjclass.json 에 누적한다(과제 이름만
    전송 — 사람·MM 금지). 파일의 "project" 목록은 수동 오버라이드."""
    p = os.path.join(share, PJCLASS_FILE)
    cls = {"nonproject": [], "project": []}
    try:
        o = json.load(open(p, encoding="utf-8-sig"))
        if isinstance(o, dict):
            for k in cls:
                if isinstance(o.get(k), list):
                    cls[k] = [str(x) for x in o[k]]
    except (OSError, ValueError):
        pass
    covered = set(cls["nonproject"]) | set(cls["project"])
    todo = [n for n in names if n not in covered and not _rule_nonpj(n)]
    if sender is not None and todo and len(names) >= 3:
        import judge
        prompt = (
            "다음 과제 이름 목록을 '과제'(제품/프로젝트 수행 업무)와 "
            "'비과제'(사내 공통·교육·지원·행사·운영·행정)로 분류하라.\n"
            "확실할 때만 비과제로 하라 — 애매하면 과제다.\n"
            'JSON 만 출력: {"nonproject": ["이름", ...]}\n\n'
            + "\n".join(f"- {n}" for n in sorted(todo)))
        res = sender(prompt, "pjclass", "teampjclass")
        o = judge.rfind_json(res.get("reply", ""), "nonproject") if res.get("ok") else None
        if res.get("ok") and o and isinstance(o.get("nonproject"), list):
            pool = set(todo)
            got = {str(x) for x in o["nonproject"] if str(x) in pool}
            cls["nonproject"] = sorted(set(cls["nonproject"]) | got)
            # 안 고른 이름은 '과제'로 기억 — 다음 실행부터 다시 묻지 않는다
            cls["project"] = sorted(set(cls["project"]) | (pool - got))
            try:
                _atomic_json(p, cls)
            except OSError:
                pass
        elif not res.get("ok"):
            log(f"    [!] 과제 분류 왕복 실패: {res.get('error', '')} — 규칙 분류만 적용")
    return cls


def series_label(g):
    """계열로 합친 줄의 표시 이름 — 공통 어간 + '계열'. 실재 표기(names)만 센다."""
    names = sorted(set(g["names"])) or [g["name"]]
    if len(names) < 2:
        return names[0]
    stem = []
    for parts in zip(*[str(n).split() for n in names]):  # noqa: B905
        if len({fold(x) for x in parts}) == 1:
            stem.append(parts[0])
        else:
            break
    return (" ".join(stem) + " 계열") if stem else max(names, key=len)


def detgrp_refine(share, det2, sender=None, log=say):
    r"""§2 세부업무 계열 통합 — 의미 병합은 sender(Copilot)에 물어 team_detail_groups.json 에
    누적한다(과제·세부 이름만 전송). 같은 과제 안에서만 묶는다. 반환: {(과제, 세부): 대표}."""
    p2 = os.path.join(share, DETGRP_FILE)
    cache = {}
    try:
        o = json.load(open(p2, encoding="utf-8-sig"))
        if isinstance(o, dict) and isinstance(o.get("groups"), dict):
            for k, v in o["groups"].items():
                if isinstance(k, str) and "␟" in k and isinstance(v, str):
                    cache[tuple(k.split("␟", 1))] = v
    except (OSError, ValueError):
        pass
    covered = set(cache) | {(k[0], v) for k, v in cache.items()}
    by_pj = {pj: sorted(d) for pj, d in det2.items() if len(d) >= 2}
    todo_n = sum(1 for pj, ds in by_pj.items() for d in ds if (pj, d) not in covered)
    if sender is not None and todo_n:
        import judge
        secs = []
        for pj, ds in sorted(by_pj.items()):
            mapped = sorted({cache.get((pj, d), d) for d in ds})
            if len(mapped) >= 2:
                secs.append((pj, f"[과제] {pj}\n" + "\n".join(f"- {d}" for d in mapped)))
        head_txt = (
            "다음은 여러 과제의 세부업무 이름 목록이다. **같은 과제 안에서만**, 같은 묶음의 "
            "일(한 덩어리 업무의 논의/회의/협의/검토/관리 같은 국면들)이면 묶어라.\n"
            "확실할 때만 묶고, 성격이 다른 업무·다른 과제끼리는 절대 묶지 마라.\n"
            "이름 끝 괄호 표기('(양산)'/'(선행)' 등)가 다르면 절대 묶지 마라 — 실제 구분이다.\n"
            'JSON 만 출력: {"groups": [{"project": "과제명", '
            '"items": [["대표이름", "이름2", ...], ...]}, ...]}\n'
            '묶을 것이 없으면 {"groups": []}\n\n')
        batches, cur, size = [], [], 0
        for pj, txt in secs:
            if cur and size + len(txt) > 7000:
                batches.append(cur)
                cur, size = [], 0
            cur.append((pj, txt))
            size += len(txt)
        if cur:
            batches.append(cur)
        if batches:
            log(f"    세부업무 통합 — 과제 {len(secs)}개를 Copilot {len(batches)}회 왕복으로 묶어 물어봅니다")
        for bi, batch in enumerate(batches, 1):
            res = sender(head_txt + "\n\n".join(t for _pj, t in batch),
                         f"detgrp-{bi}", "teamdetgrp")
            if not res.get("ok"):
                log(f"    [!] 세부 통합 왕복 {bi}/{len(batches)} 실패 — 저장된 통합만 적용하고 접습니다")
                break
            o = judge.rfind_json(res.get("reply", ""), "groups")
            for grp in ((o or {}).get("groups") or []):
                if not isinstance(grp, dict):
                    continue
                pj = str(grp.get("project") or "").strip()
                pool = set(by_pj.get(pj) or ())
                if not pool:
                    continue
                for items in (grp.get("items") or []):
                    if not isinstance(items, list):
                        continue
                    names = [str(x).strip() for x in items if str(x).strip() in pool]
                    if len(names) < 2 or len({_note(x) for x in names}) > 1:
                        continue                      # 실재 이름만 · 괄호 꼬리 다르면 거부
                    w = {d: sum((det2.get(pj) or {}).get(d, {}).values()) for d in names}
                    canon = max(names, key=lambda x: (w.get(x, 0.0), len(x), x))
                    for x in names:
                        if x != canon:
                            rep0, seen0 = canon, set()
                            while (pj, rep0) in cache and rep0 not in seen0:
                                seen0.add(rep0)
                                rep0 = cache[(pj, rep0)]
                            if x != rep0:
                                cache[(pj, x)] = rep0
            try:
                _atomic_json(p2, {"groups": {"␟".join(k): v for k, v in cache.items()}})
            except OSError:
                pass
    # 사슬 평탄화 — 손편집 실수는 조용히 삼키지 않는다: 꼬리 불일치·순환·유령 대표는 경고.
    flat, warned = {}, []
    for (pj, a), v in cache.items():
        seen = {a}
        while (pj, v) in cache and v not in seen:
            seen.add(v)
            v = cache[(pj, v)]
        if v == a:
            continue
        if (pj, v) in cache and v in seen:
            warned.append(f"순환: {pj} / {a}")
            continue
        if _note(a) != _note(v):
            warned.append(f"괄호 꼬리 다름: {pj} / {a} → {v}")
            continue
        d2c = det2.get(pj)
        if (d2c is not None and a in d2c
                and not any(ukey(v) == ukey(k2) for k2 in d2c)):
            warned.append(f"실재하지 않는 대표: {pj} / {v}")
            continue
        flat[(pj, a)] = v
    for w2 in warned[:4]:
        log(f"    [!] {DETGRP_FILE} 무시된 줄 — {w2}")
    if len(warned) > 4:
        log(f"    [!] … 외 {len(warned) - 4}건")
    return flat


def _dt_rule_groups(dts, protected=frozenset()):
    """세부 목록 표기-변형 병합(규칙) — ukey 동일 또는 (꼬리 일치 ∧ dice≥0.8).
    protected = 캐시가 지정한 대표 이름들 — 규칙의 '더 긴 표기'에 밀리지 않는다."""
    out = []
    for dt, row, tot in dts:
        hit = None
        for g in out:
            if ukey(dt) == ukey(g[0]) or (_note(dt) == _note(g[0])
                                          and bigram_dice(dt, g[0]) >= 0.8):
                hit = g
                break
        if hit is None:
            out.append([dt, dict(row), tot])
        else:
            for w2, v2 in row.items():
                hit[1][w2] = hit[1].get(w2, 0.0) + v2
            hit[2] = round(hit[2] + tot, 2)
            if hit[0] not in protected and (
                    dt in protected or (len(dt), dt) > (len(hit[0]), hit[0])):
                hit[0] = dt
    out.sort(key=lambda x: -x[2])
    return [(a, b, c) for a, b, c in out]


def group_details(g, det2, dgmap=None):
    """한 §2 줄(통합된 과제)의 세부업무 × 인원 구성 — Copilot 캐시(dgmap) + 표기 규칙으로
    같은 묶음의 세부('빌드 논의/회의/협의')를 한 줄로 합쳐 보여준다."""
    dgmap = dgmap or {}
    out = {}
    for nm in set(g["names"]) | {g["name"]}:
        for dt, row in (det2.get(nm) or {}).items():
            dt2 = dgmap.get((nm, dt), dt)
            r = out.setdefault(dt2, {})
            for w, v in row.items():
                r[w] = r.get(w, 0.0) + v
    dts = sorted(((dt, r, round(sum(r.values()), 2)) for dt, r in out.items()),
                 key=lambda x: -x[2])
    return _dt_rule_groups(dts, frozenset(dgmap.values()))


def _squarify(vals, x, y, w, h):
    """면적 비례 사각 채우기(squarified) — 반환 [(i, x, y, w, h)] (좌표는 입력 단위)"""
    vals = [max(0.0, v) for v in vals]
    out = []
    items = sorted(range(len(vals)), key=lambda i: -vals[i])
    total = sum(vals) or 1.0
    scale = w * h / total
    row, rs = [], 0.0

    def worst(row_v, side):
        if not row_v or not side:
            return 1e18
        sm = sum(row_v)
        mn, mx = min(row_v), max(row_v)
        return max((side * side * mx) / (sm * sm), (sm * sm) / (side * side * mn))

    def flush():
        nonlocal x, y, w, h, row, rs
        if not row:
            return
        horiz = w >= h
        side = h if horiz else w
        thick = rs / side if side else 0
        off = 0.0
        for i in row:
            a = vals[i] * scale
            ln = a / thick if thick else 0
            if horiz:
                out.append((i, x, y + off, thick, ln))
            else:
                out.append((i, x + off, y, ln, thick))
            off += ln
        if horiz:
            x += thick
            w -= thick
        else:
            y += thick
            h -= thick
        row, rs = [], 0.0

    for i in items:
        a = vals[i] * scale
        if a <= 0:
            continue
        side = h if w >= h else w
        cur = [vals[j] * scale for j in row]
        if row and worst(cur + [a], side) > worst(cur, side):
            flush()
        row.append(i)
        rs += a
    flush()
    return out


def treemap_html(pj_rows, np_rows, height=300, min_mm=1.0, max_tiles=9):
    r"""과제 MM 트리맵 — **본판에는 과제만**. 기타 과제 묶음·비과제성은 아래 분리 스트립으로."""
    TPAL = ["2563EB", "0D9488", "7C3AED", "DB2777", "EA580C",
            "16A34A", "0891B2", "CA8A04", "4F46E5", "65A30D"]
    pj = [g for g in pj_rows if max(0.0, g["total"]) > 0]
    if not pj and not np_rows:
        return ""
    pj.sort(key=lambda g: -g["total"])
    vis = [g for g in pj if g["total"] > min_mm][:max_tiles]
    if not vis:
        vis = pj[:max_tiles]
    vset = {id(g) for g in vis}
    rest = [g for g in pj if id(g) not in vset]
    etc_mm = round(sum(g["total"] for g in rest), 2)
    np_mm = round(sum(max(0.0, g["total"]) for g in np_rows), 2)
    grand = sum(g["total"] for g in pj) + np_mm or 1.0
    out = []
    if vis:
        rects = _squarify([g["total"] for g in vis], 0.0, 0.0, 1000.0, float(height))
        out.append(f'<div style="position:relative;width:100%;height:{height}px;'
                   'border:1px solid #e4e7eb;border-radius:8px;overflow:hidden;margin:6px 0 6px">')
        for i, rx, ry, rw, rh in rects:
            g = vis[i]
            label = series_label(g)
            pct = g["total"] / grand * 100
            area = rw * rh / (1000.0 * height)
            fs = 17 if area >= 0.09 else 14.5 if area >= 0.045 else 12.5 if area >= 0.02 else 10.5
            two = area >= 0.018 and rh >= 46
            inner = (f'<div style="font-size:{fs}px;font-weight:700;line-height:1.25;'
                     f'overflow:hidden;text-overflow:ellipsis;'
                     f'{"white-space:nowrap" if not two or rh < 66 else ""}">{esc(label)}</div>')
            if two:
                inner += (f'<div style="font-size:{max(10, fs - 4)}px;opacity:.92;margin-top:2px">'
                          f'{g["total"]:.2f} MM · {pct:.0f}%</div>')
            out.append(
                f'<div title="{esc(label)} — {g["total"]:.2f} MM (전체의 {pct:.1f}%)" '
                f'style="position:absolute;left:{rx / 10.0:.2f}%;top:{ry / height * 100:.2f}%;'
                f'width:{rw / 10.0:.2f}%;height:{rh / height * 100:.2f}%;'
                f'background:#{TPAL[i % len(TPAL)]};color:#fff;box-sizing:border-box;'
                f'border:2px solid #fff;padding:6px 8px;overflow:hidden">'
                + inner + "</div>")
        out.append("</div>")
    strip = []
    if rest:
        strip.append(("기타 과제 " + str(len(rest)) + "건", etc_mm, "64748B"))
    if np_mm:
        strip.append(("비과제성(공통·근무시간·교육 등)", np_mm, "94A3B8"))
    if strip:
        st = sum(v for _t, v, _c in strip) or 1.0
        ws = [max(14.0, v9 / st * 100) if len(strip) > 1 else 100.0 for _t, v9, _c in strip]
        wsum = sum(ws) or 1.0
        ws = [w9 / wsum * 100 for w9 in ws]
        out.append('<div style="display:flex;height:30px;border-radius:6px;overflow:hidden;'
                   'border:1px solid #e4e7eb;margin:0 0 4px">')
        for (t9, v9, c9), wpct in zip(strip, ws):  # noqa: B905
            out.append(
                f'<div title="{esc(t9)} — {v9:.2f} MM (전체의 {v9 / grand * 100:.1f}%)" '
                f'style="flex:0 0 {wpct:.1f}%;max-width:{wpct:.1f}%;background:#{c9};'
                'color:#fff;display:flex;align-items:center;gap:8px;padding:0 10px;'
                'overflow:hidden;white-space:nowrap;box-sizing:border-box;'
                'border-right:2px solid #fff">'
                f'<span style="font-size:11px;font-weight:700;overflow:hidden;'
                f'text-overflow:ellipsis">{esc(t9)}</span>'
                f'<span style="font-size:10.5px;opacity:.92">{v9:.2f} MM · '
                f'{v9 / grand * 100:.0f}%</span></div>')
        out.append("</div>")
        out.append('<div class="note" style="margin:0 0 8px">트리맵은 과제만 — 위 스트립의 '
                   "몫까지 합치면 전체 로드입니다. 아래 누적바에는 전부 있습니다.</div>")
    return "".join(out)


def stack_rows_x(groups, owners, det2, dgmap=None, width=300, label_w=150):
    r"""§2 전용 누적바 — 줄을 펼치면 그 과제의 세부업무×인원 구성이 보인다."""
    if not groups:
        return '<div class="note">데이터 없음</div>'
    gmax = max([g["total"] for g in groups] or [0.001]) or 0.001
    oi = {o: i for i, o in enumerate(owners)}

    def _segs(row, w):
        return "".join(
            f'<i style="display:inline-block;height:14px;'
            f'width:{max(0.0, row[o] / gmax * w):.1f}px;background:{PAL10[oi.get(o, 0) % len(PAL10)]}"'
            f' title="{esc(o)} {row[o]:.2f} MM"></i>'
            for o in owners if row.get(o))

    out = []
    for g in groups:
        label = series_label(g)
        alt = (f'<div class="sub" style="margin-left:{label_w + 8}px">통합 {len(g["names"])}종: '
               f'{esc(" / ".join(g["names"][:4]))}</div>') if len(g["names"]) > 1 else ""
        dts = group_details(g, det2, dgmap)
        head_row = (
            '<div style="display:inline-flex;align-items:center;gap:8px">'
            f'<span style="width:{label_w}px;flex:0 0 {label_w}px;font-size:11.5px;'
            f'text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '
            f'title="{esc(g["name"])}"><b>{esc(label)}</b></span>'
            f'<span style="white-space:nowrap;flex:0 0 auto">{_segs(g["row"], width)}</span>'
            f'<span style="font-size:11px;color:#5a626b;white-space:nowrap">{g["total"]:.2f} MM'
            + (f' · 세부 {len(dts)}종' if dts else "") + "</span></div>")
        if not dts:
            out.append('<div style="margin:4px 0">' + head_row + "</div>" + alt)
            continue
        body = []
        for dt, row, tot in dts[:12]:
            body.append(
                '<div style="display:flex;align-items:center;gap:8px;margin:2px 0;'
                'break-inside:avoid">'
                f'<span style="width:{label_w}px;flex:0 0 {label_w}px;font-size:10.5px;'
                f'color:#5a626b;text-align:right;overflow:hidden;text-overflow:ellipsis;'
                f'white-space:nowrap" title="{esc(dt)}">{esc(dt)}</span>'
                f'<span style="white-space:nowrap;flex:0 0 auto">{_segs(row, width * 0.85)}</span>'
                f'<span style="font-size:10.5px;color:#8b929b;white-space:nowrap">{tot:.2f}</span>'
                "</div>")
        rest = dts[12:]
        if rest:
            rest_sum = round(g["total"] - sum(t for _d, _r, t in dts[:12]), 2)
            body.append(f'<div class="sub" style="margin-left:{label_w + 8}px">'
                        f'… 나머지 {len(rest)}종 · {rest_sum:.2f} MM</div>')
        out.append(
            '<details style="margin:4px 0"><summary style="padding:2px 4px;border:0;'
            'background:transparent;font-weight:400">' + head_row + "</summary>"
            '<div style="padding:2px 0 4px 8px;border-left:2px solid #eef0f3;margin-left:8px;'
            'columns:24rem auto;column-gap:26px">'
            + "".join(body) + "</div></details>" + alt)
    return "<div style='overflow-x:auto'>" + "".join(out) + "</div>"


def cand_refine(share, cands, sender=None, log=say):
    r"""규칙으로 안 묶인 신규 후보(동사 동의어·오타)를 sender(Copilot) 1회로 통합.
    보내는 것은 후보 **이름 목록뿐**. 결과는 team_cand_groups.json 에 누적."""
    p = os.path.join(share, CAND_FILE)
    cache = _load_groups_cache(share, CAND_FILE)
    names = [g["name"] for g in cands]
    covered = set(cache) | set(cache.values())
    todo = [n for n in names if n not in covered]
    if sender is not None and todo and len(names) >= 3:
        import judge
        prompt = (
            "다음은 한 팀에서 제안된 업무 자동화 에이전트 후보의 이름 목록이다.\n"
            "같은 일을 자동화하는 에이전트면 묶어라 — 어순·조사 차이, 동의어(검증/체크,\n"
            "생성/작성 등), 봇/에이전트 같은 수식어 차이는 같은 것이다.\n"
            "대상 업무가 다르면 절대 묶지 마라 (주간/월간, 양산/선행처럼 주기·단계가\n"
            "다르면 다른 것이다).\n"
            'JSON 만 출력: {"groups": [["대표이름", "이름2", ...], ...]}\n'
            '묶을 것이 없으면 {"groups": []}\n\n'
            + "\n".join(f"- {n}" for n in sorted(names)))
        res = sender(prompt, "cands", "teamcands")
        o = judge.rfind_json(res.get("reply", ""), "groups") if res.get("ok") else None
        if res.get("ok") and o and isinstance(o.get("groups"), list):
            pool = set(names)
            for grp in o["groups"]:
                if not isinstance(grp, list):
                    continue
                grp = [str(x) for x in grp if str(x) in pool]   # 지어낸 이름 방지
                if len(grp) < 2:
                    continue
                rep0, seen0 = grp[0], set()
                while rep0 in cache and rep0 not in seen0:
                    seen0.add(rep0)
                    rep0 = cache[rep0]
                for n in grp:
                    if n != rep0:
                        cache[n] = rep0
            try:
                _atomic_json(p, {"groups": cache})
            except OSError:
                pass
        elif not res.get("ok"):
            log(f"    [!] 후보 통합 왕복 실패: {res.get('error', '')} — 저장된 통합만 적용")
    if not cache:
        return cands, 0
    flat = flatten_chain(dict(cache))
    flat = {k: v for k, v in flat.items() if k != v and flat.get(v, v) == v}  # 순환 방어
    merged, by_rep, n = [], {}, 0
    for g in cands:
        rep_n = ""
        for nm in [g["name"]] + [x for x in g["names"] if x != g["name"]]:
            if nm in flat:
                rep_n = flat[nm]
                break
        rep_n = rep_n or g["name"]
        hit = by_rep.get(ukey(rep_n))
        if hit is None:
            g = dict(g)
            g["name"] = rep_n
            by_rep[ukey(rep_n)] = g
            merged.append(g)
        else:
            n += 1
            hit["names"] = sorted(set(hit["names"]) | set(g["names"]) | {g["name"]})
            hit["who"] = sorted(set(hit["who"]) | set(g["who"]))
            hit["mm"] += g["mm"]
            if len(g["logic"]) > len(hit["logic"]):
                hit["logic"] = g["logic"]
            if len(g["reason"]) > len(hit["reason"]):
                hit["reason"] = g["reason"]
    for g in merged:
        if g["names"] and g["name"] not in set(g["names"]):
            g["name"] = max(g["names"], key=lambda x: (len(x), x))
    merged.sort(key=lambda g: -(len(g["who"]) * 10 + g["mm"]))
    return merged, n


def team_rows_matrix(members, share):
    r"""과제×인원 · 업무유형을 **기간(tag)이 달라도** 다시 센다.

    행 MM 은 그 사람의 공식 투입(member.total_mm)에 맞춰 재스케일한다(배율 규칙은 aggregate.mm_scale
    한 곳) — 과제×인원·트리맵·세부·회의 배분·업무유형이 §1 투입과 같은 총량이 되게. 예전에는 업무유형만
    맞추고 과제×인원은 행 합 그대로여서 한 문서 안에서 §1·§2·§3 수치가 서로 달랐다(검증 확정).
    src[who] 에는 원래 행 합(sum)·공식값(total)·배율(scale)을 남긴다."""
    ag = _agg()
    al = ag.load_aliases(share)
    pj_map, dt_map = al["projects"], al["details"]
    matrix, det, wt, fixed, empty, src = {}, {}, {}, [], [], {}
    meet = {}                      # 과제 미지정 회의·협업 MM — 과제 비중대로 배분(추정)용
    for m in members:
        who = m["owner"]
        tmm = _fnum(m.get("total_mm"))
        rows, rf = (_member_rows(m["dir"], m.get("tag") or "", tmm)
                    if m.get("dir") else ([], ""))
        if not rows:
            empty.append(who)
            src[who] = {"sum": 0.0, "total": tmm or 0.0, "file": rf, "scale": 1.0}
            continue
        tag = str(m.get("tag") or "")
        if rf and tag and tag not in rf:
            fixed.append(who)
        raw_sum = round(sum(_fnum(r.get("mm"), 0.0) for r in rows), 3)
        scale = ag.mm_scale(tmm, raw_sum)
        src[who] = {"sum": raw_sum, "total": tmm or 0.0, "file": rf, "scale": scale,
                    "share_only": (not any(r.get("mm") for r in rows)
                                   and any(r.get("_share_only") for r in rows))}
        for r in rows:
            mm = _fnum(r.get("mm"), 0.0) * scale
            if not mm:
                continue
            pj0 = str(r.get("Level 2") or "").strip() or EMPTY_PJ
            pj = pj_map.get(pj0, pj0)
            dt0 = str(r.get("Level 3") or "").strip() or "(세부 미상)"
            dt = dt_map.get(dt0, dt0)
            k9 = str(r.get("유형") or "").strip()
            if _rule_nonpj(pj) and (k9 == "협업" or "회의" in fold(dt) or "회의" in fold(pj)):
                meet[who] = meet.get(who, 0.0) + mm
                wt.setdefault(who, {})
                wt[who][k9 or "협업"] = wt[who].get(k9 or "협업", 0.0) + mm
                continue
            matrix.setdefault(pj, {})
            matrix[pj][who] = matrix[pj].get(who, 0.0) + mm
            d = det.setdefault(pj, {}).setdefault(dt, {})
            d[who] = d.get(who, 0.0) + mm
            k = str(r.get("유형") or "").strip() or "사무"
            wt.setdefault(who, {})
            wt[who][k] = wt[who].get(k, 0.0) + mm
    return matrix, det, wt, fixed, empty, src, meet


def series_refine(share, groups, sender=None, log=say):
    r"""과제 '계열' 통합 — 표기 유사로도 안 묶이는 같은 계열의 과제를 sender(Copilot)에 물어
    한 줄로 합친다. 보내는 것은 과제 이름 목록뿐. 결과는 team_series.json 에 누적."""
    p = os.path.join(share, SERIES_FILE)
    cache = _load_groups_cache(share, SERIES_FILE)
    names = [g["name"] for g in groups]
    covered = set(cache) | set(cache.values())
    todo = [n for n in names if n not in covered]
    if sender is not None and todo and len(names) >= 3:
        import judge
        prompt = (
            "다음은 한 팀의 과제(프로젝트) 이름 목록이다. 같은 계열이면 묶어라.\n"
            "같은 계열 = 같은 제품/과제의 표기 차이, 단계(선행/개발/검증/양산 등), 차수.\n"
            "확실할 때만 묶고, 성격이 다른 과제는 절대 묶지 마라.\n"
            'JSON 만 출력: {"groups": [["대표이름", "이름2", ...], ...]}\n'
            '묶을 것이 없으면 {"groups": []}\n\n'
            + "\n".join(f"- {n}" for n in sorted(names)))
        res = sender(prompt, "series", "teamseries")
        o = judge.rfind_json(res.get("reply", ""), "groups") if res.get("ok") else None
        if res.get("ok") and o and isinstance(o.get("groups"), list):
            pool = set(names)
            for grp in o["groups"]:
                if not isinstance(grp, list):
                    continue
                grp = [str(x) for x in grp if str(x) in pool]
                if len(grp) < 2:
                    continue
                rep0, seen0 = grp[0], set()
                while rep0 in cache and rep0 not in seen0:
                    seen0.add(rep0)
                    rep0 = cache[rep0]
                for n in grp:
                    if n != rep0:
                        cache[n] = rep0
            try:
                _atomic_json(p, {"groups": cache})
            except OSError:
                pass
        elif not res.get("ok"):
            log(f"    [!] 계열 통합 왕복 실패: {res.get('error', '')} — 저장된 통합만 적용")

    if not cache:
        return groups, 0
    flat = flatten_chain(dict(cache))
    flat = {k: v for k, v in flat.items() if k != v and flat.get(v, v) == v}
    merged, by_rep, n_merged = [], {}, 0
    for g in groups:
        rep = flat.get(g["name"], g["name"])
        hit = by_rep.get(ukey(rep))
        if hit is None:
            g = dict(g)
            g["row"] = dict(g["row"])
            g["name"] = rep
            by_rep[ukey(rep)] = g
            merged.append(g)
        else:
            n_merged += 1
            hit["names"] = sorted(set(hit["names"]) | set(g["names"]) | {g["name"]})
            for w, v in g["row"].items():
                hit["row"][w] = hit["row"].get(w, 0.0) + v
    for g in merged:
        g["total"] = round(sum(g["row"].values()), 3)
    merged.sort(key=lambda g: -g["total"])
    return merged, n_merged


_MON_RE = re.compile(r"(19|20)\d{2}-(0[1-9]|1[0-2])")   # 'YYYY-MM' 만 — 월 13·'abcdefg' 는 월이 아니다
GANTT_MAX_MONTHS = 24


def _month_window(active, max_months=GANTT_MAX_MONTHS):
    r"""활동이 있는 달 목록(정렬, 'YYYY-MM')에서 표에 놓을 연속 월 창을 정한다 — 반환 (months, old).
    창은 마지막 활동 달에서 거꾸로 최대 max_months 개월이며, 앞쪽 빈 달은 잘라 내 **활동이 있는
    달부터 시작**한다(예전에는 빈 2024-09~12 네 칸이 남고 진짜 활동 2024-01~03 은 '생략' 됐다).
    old = 창 앞에서 잘려 나간 활동 달들. while 루프가 아니라 정수 산술이라 잘못된 값으로 멈추지 않는 일이 없다."""
    if not active:
        return [], []
    i1 = int(active[-1][:4]) * 12 + int(active[-1][5:7]) - 1
    i0 = max(int(active[0][:4]) * 12 + int(active[0][5:7]) - 1, i1 - (max_months - 1))
    months = [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(i0, i1 + 1)]
    aset = set(active)
    while months and months[0] not in aset:
        months.pop(0)
    old = [m9 for m9 in active if months and m9 < months[0]]
    return months, old


def build_gantt(share, members, clusters, groups, owners=()):
    r"""담당 업무 활동 간트 — 과제 접기 → 담당 업무 일정 → 사람별 타임라인 + 단계 체인.
    신호 raw 이름은 team_aliases 축으로 접어 매칭.

    셀은 인라인 style 이 아니라 **CSS 클래스 + data 속성**으로 그리고, 활동이 없는 달은 요소를 만들지
    않는다(활동 구간의 빈 달은 선 하나로) — 30명 취합에서 이 절 하나가 8.7MB 이던 규모 결함.
    말풍선(title)은 마우스가 올라갈 때 JS 가 data-n 과 월 목록으로 만든다."""
    al2 = _agg().load_aliases(share)
    pmap2, dmap2 = al2["projects"], al2["details"]
    key2ci = {}
    for ci, c in enumerate(clusters):
        key2ci[(ukey(c["project"]), ukey(c["detail"]))] = ci
    counts = {}                    # (ci, mon) -> n
    pcounts = {}                   # (ci, owner, mon) -> n
    for m in members:
        if not m.get("dir"):
            continue
        who9 = m["owner"]
        sp = find_member_any(m["dir"], "signals", str(m.get("tag") or ""), exts=(".csv",))
        if not sp:
            continue
        try:
            with open(sp, encoding="utf-8-sig", errors="replace") as f:
                srows = list(csv.DictReader(f))
        except (OSError, ValueError, csv.Error):
            continue
        for r in srows:
            if not isinstance(r, dict):
                continue
            mon = str(r.get("time") or "")[:7]
            if not _MON_RE.fullmatch(mon):
                continue           # 날짜가 아닌 값('abcdefg')이 문자열 비교로 월 범위를 무한히 늘리던 결함
            pj = str(r.get("model") or r.get("project") or "").strip()
            dt = str(r.get("detail") or r.get("activity") or "").strip()
            if " / " in pj and not dt:
                pj, dt = pj.rsplit(" / ", 1)
            pj = pmap2.get(pj, pj)
            dt = dmap2.get(dt, dt)
            ci = key2ci.get((ukey(pj), ukey(dt)))
            if ci is None:
                continue
            counts[(ci, mon)] = counts.get((ci, mon), 0) + 1
            pcounts[(ci, who9, mon)] = pcounts.get((ci, who9, mon), 0) + 1
    if not counts:
        return ('<div class="card"><h2>9-1. 담당 업무 활동 간트</h2>'
                '<div class="note">판정 신호(signals) 파일이 취합 폴더에 없어 활동 간트를 '
                "만들 수 없습니다 — 팀원이 [팀 서버 업로드]를 하면 함께 올라옵니다.</div></div>")
    active = sorted({m9 for (_c9, m9) in counts})
    months, old = _month_window(active)
    mset = set(months)
    cmax = max([v9 for (_c9, m9), v9 in counts.items() if m9 in mset] or [1]) or 1
    LW = 250
    CW = max(40, min(112, (1088 - LW) // max(1, len(months))))
    GW = len(months) * CW
    oi9 = {o: i for i, o in enumerate(owners)}

    def _rgb(col):
        c = col.lstrip("#")
        return f"{int(c[0:2], 16)},{int(c[2:4], 16)},{int(c[4:6], 16)}"

    # 색 클래스 — 과제/사람 색(PAL10) + 회색. 인라인 rgba 대신 CSS 변수 --gc 로 그린다
    cols = list(PAL10) + ["#8b929b"]
    ccls = {c9: (f"c{i}" if i < len(PAL10) else "cx") for i, c9 in enumerate(cols)}
    css = [f".gnt .gt{{position:relative;display:inline-block;flex:0 0 auto;--gc:{_rgb('#8b929b')};"
           f"background:repeating-linear-gradient(90deg,transparent 0 {CW - 1}px,#eef1f5 {CW - 1}px {CW}px)}}",
           f".gnt .gb{{position:absolute;top:2px;bottom:2px;width:{CW - 2}px;margin-left:1px;"
           "background:linear-gradient(180deg,rgba(var(--gc),var(--a2)),rgba(var(--gc),var(--a1)))}",
           ".gnt .gs{position:absolute;top:50%;height:2px;margin-top:-1px;border-radius:1px;"
           "background:rgb(var(--gc));opacity:.28}",
           ".gnt .rl{border-top-left-radius:9px;border-bottom-left-radius:9px}",
           ".gnt .rr{border-top-right-radius:9px;border-bottom-right-radius:9px}",
           f".gnt .gl{{flex:0 0 {LW}px;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}",
           f".gnt .gl2{{flex:0 0 {LW}px;box-sizing:border-box;font-size:10px;color:#5a626b;padding-left:24px;"
           "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
           ".gnt .gp{display:flex;align-items:center;margin:1px 0}",
           ".gnt .gd{width:7px;height:7px}",
           ".gnt .gch{display:inline-flex;align-items:center;gap:4px;margin:2px 8px 2px 0;font-size:10px;"
           "color:#2c333b;background:#f7f9fb;border:1px solid #e8ecf1;border-radius:10px;padding:1px 8px 1px 3px}",
           ".gnt .gch .pill{font-size:9px;padding:0 5px}",
           ".gnt .gar{color:#c3c9d1;font-size:10px;margin-right:8px}",
           ".gnt .gchain{margin:7px 0 0 24px;line-height:2}",
           ".gnt .gsub{padding:2px 0 8px;border-left:2px solid #eef0f3;margin-left:8px}"]
    for c9, cl in ccls.items():
        css.append(f".gnt .{cl}{{--gc:{_rgb(c9)}}} .gnt .d{cl[1:]}{{background:{c9}}}")
    for b in range(1, 7):                                 # 진하기 6단계(그 달 신호 수 ÷ 최대)
        a1 = 0.30 + 0.62 * b / 6
        css.append(f".gnt .o{b}{{--a1:{a1:.2f};--a2:{min(0.95, a1 + 0.1):.2f}}}")
    css.append(" ".join(f".gnt .m{k}{{left:{k * CW}px}}" for k in range(len(months))))

    def _bars(get, col, h):
        """한 줄의 막대들 — 활동 달만 <i>, 활동 구간의 빈 달은 선(.gs) 하나. 반환 (html, 기간 문자열)"""
        act = [k for k, mth in enumerate(months) if get(mth)]
        if not act:
            return f'<span class="gt" style="flex:0 0 {GW}px;height:{h}px"></span>', ""
        k0, k1 = act[0], act[-1]
        outc = [f'<span class="gt {ccls.get(col, "cx")}" style="flex:0 0 {GW}px;height:{h}px">']
        if k1 - k0 + 1 > len(act):
            outc.append(f'<i class="gs" style="left:{k0 * CW}px;width:{(k1 - k0 + 1) * CW}px"></i>')
        prev_on = False
        for k in range(k0, k1 + 1):
            n2 = get(months[k])
            if not n2:
                prev_on = False
                continue
            nxt_on = k < k1 and bool(get(months[k + 1]))
            b = max(1, min(6, -(-n2 * 6 // cmax)))
            cls = f"gb o{b} m{k}" + ("" if prev_on else " rl") + ("" if nxt_on else " rr")
            outc.append(f'<i class="{cls}" data-n="{n2}"></i>')
            prev_on = True
        outc.append("</span>")
        return "".join(outc), (f"{months[k0][2:4]}.{months[k0][5:7]}–"
                               f"{months[k1][2:4]}.{months[k1][5:7]}")

    def _overlay(months9, lw, cw):
        parts = ['<div style="position:absolute;inset:0;z-index:0;pointer-events:none">']
        i9 = 0
        while i9 < len(months9):
            y9, m9 = months9[i9][:4], int(months9[i9][5:7])
            q9 = (m9 - 1) // 3
            j9 = i9
            while (j9 < len(months9) and months9[j9][:4] == y9
                   and (int(months9[j9][5:7]) - 1) // 3 == q9):
                j9 += 1
            if q9 % 2 == 1:
                parts.append(f'<i style="position:absolute;top:0;bottom:0;'
                             f'left:{lw + i9 * cw}px;width:{(j9 - i9) * cw}px;'
                             'background:#f4f7fb"></i>')
            i9 = j9
        for k9 in range(1, len(months9)):
            if months9[k9][:4] != months9[k9 - 1][:4]:
                parts.append(f'<i style="position:absolute;top:0;bottom:0;'
                             f'left:{lw + k9 * cw - 1}px;width:2px;background:#d7dde4"></i>')
        parts.append(f'<i style="position:absolute;top:0;bottom:0;left:{lw - 8}px;'
                     'width:1px;background:#e8ecf1"></i>')
        parts.append("</div>")
        return "".join(parts)

    def _chip(txt, col="#f0f3f7", fg="#3d444c"):
        return (f'<span style="display:inline-block;background:{col};color:{fg};'
                f'border-radius:8px;padding:0 7px;font-size:9.5px;font-weight:600;'
                f'margin-left:6px;vertical-align:1px">{txt}</span>')

    yr_spans, cur_y, cnt_y = [], months[0][:4], 0
    for mth in months:
        if mth[:4] != cur_y:
            yr_spans.append((cur_y, cnt_y))
            cur_y, cnt_y = mth[:4], 0
        cnt_y += 1
    yr_spans.append((cur_y, cnt_y))
    hdr = ('<div style="display:flex;margin:0 0 1px">'
           f'<span style="flex:0 0 {LW}px"></span>'
           + "".join(f'<span style="flex:0 0 {n9 * CW}px;font-size:9.5px;font-weight:700;'
                     f'color:#5a626b;border-left:2px solid #dfe3e8;padding-left:5px">'
                     f"{y9}년</span>" for y9, n9 in yr_spans)
           + "</div>"
           '<div style="display:flex;margin:0 0 8px">'
           f'<span style="flex:0 0 {LW}px"></span>'
           + "".join(f'<span style="flex:0 0 {CW}px;font-size:9.5px;text-align:center;'
                     f'color:{"#3d4a5c" if mth[5:7] in ("01", "04", "07", "10") else "#9aa1a9"};'
                     f'{"font-weight:700;" if mth[5:7] in ("01", "04", "07", "10") else ""}'
                     f'box-shadow:inset -1px 0 0 #eef1f5">{mth[5:7]}월</span>'
                     for mth in months)
           + "</div>")

    body = []
    for gi2, g2 in enumerate(groups):
        col = PAL10[gi2 % len(PAL10)]
        rows_h = []
        for c in g2["types"]:
            ci = clusters.index(c)
            cells, span_txt = _bars(lambda mth: counts.get((ci, mth), 0), col, 20)
            sig_who = sorted({o9 for (ci9, o9, _m9) in pcounts if ci9 == ci})
            all_who = list(c["who"]) + [o9 for o9 in sig_who if o9 not in c["who"]]
            sub = []
            for w9 in all_who:
                pcol = PAL10[oi9[w9] % len(PAL10)] if w9 in oi9 else "#8b929b"
                pc, _sp9 = _bars(lambda mth, w=w9: pcounts.get((ci, w, mth), 0), pcol, 12)
                tag9 = "" if w9 in c["who"] else ' <span class="sub">(신호만)</span>'
                sub.append('<div class="g-row gp">'
                           f'<span class="gl2"><span class="dot gd d{ccls.get(pcol, "cx")[1:]}"></span>'
                           f'{esc(w9)}{tag9}</span>' + pc + "</div>")
            chain = "".join(
                f'<span class="gch"><span class="pill" style="background:'
                f'{_AGENT_C.get(st9["agent"], "#8b929b")}">{esc(st9["agent"])}</span>'
                f'{esc(st9["name"])}</span>'
                + ('<span class="gar">→</span>' if k9 < len(c["steps"]) - 1 else "")
                for k9, st9 in enumerate(c["steps"]))
            more9 = c.get("steps_total", len(c["steps"])) - len(c["steps"])
            if more9 > 0:
                chain += f'<span class="sub">… +{more9}단계</span>'
            rows_h.append(
                '<details class="gxr"><summary style="padding:0;background:transparent;'
                'border:0;border-radius:0;font-weight:400;font-size:inherit">'
                '<div class="g-row" style="display:flex;align-items:center;margin:2px 0">'
                f'<span class="gl" title="{esc(c["detail"])} · {span_txt}">'
                f'<span class="garr">▸</span> <b>{esc(c["detail"])}</b>'
                + _chip(f"{len(c['who'])}명") + _chip(f"{c['mm']:.2f} MM")
                + "</span>" + cells + "</div></summary>"
                '<div class="gsub">' + "".join(sub)
                + f'<div class="gchain">{chain}</div>'
                "</div></details>")
        if not rows_h:
            continue
        cis = tuple(clusters.index(c) for c in g2["types"])
        agg, agg_span = _bars(
            lambda mth, cis=cis: sum(counts.get((ci9, mth), 0) for ci9 in cis), col, 20)
        body.append(
            f'<details class="gx"{" open" if gi2 == 0 else ""}>'
            '<summary style="padding:0;background:transparent;border:0;border-radius:0;'
            'font-size:inherit">'
            '<div class="g-row" style="display:flex;align-items:center;margin:8px 0 2px;'
            'padding:3px 0;border-top:1px solid #f0f2f5">'
            f'<span class="gl" style="font-size:11.5px;font-weight:700;color:#2c333b" '
            f'title="{esc(g2["project"])} · {agg_span}"><span class="garr">▸</span> '
            f'<span class="dot" style="background:{col}"></span>{esc(g2["project"])}'
            + _chip(f"업무 {len(g2['types'])}종", "#eef4fd", "#27476e")
            + _chip(f"{g2['mm']:.2f} MM", "#eef4fd", "#27476e")
            + "</span>" + agg + "</div></summary>"
            '<div style="margin-left:6px">' + "".join(rows_h) + "</div></details>")
    old_note = ""
    if old:
        old_note = (f" · 오래된 활동 {len(old)}개월({old[0]}~{old[-1]})은 생략"
                    f"(최근 {GANTT_MAX_MONTHS}개월 창)")
    # 말풍선은 마우스가 올라갈 때만 — 셀마다 title 을 박으면 30명 취합에서 파일이 몇 MB 늘어난다
    js = ('<script>(function(){var M=' + json.dumps(months)
          + ';document.addEventListener("mouseover",function(e){var t=e.target;'
          'if(!t||!t.classList||!t.classList.contains("gb")||t.title)return;'
          'var k=/\\bm(\\d+)\\b/.exec(t.className);'
          't.title=(k?M[+k[1]]:"")+" \\u00b7 \\uc2e0\\ud638 "+(t.getAttribute("data-n")||"?")+"\\uac74";});})();</script>')
    return ('<div class="card gnt"><style>' + "\n".join(css) + "</style>"
            '<h2>9-1. 담당 업무 활동 간트 '
            '<span class="state">과제를 접고 펼 수 있습니다 · 담당 업무를 누르면 사람별 '
            '타임라인(§2와 같은 사람 색)과 워크플로우 단계가 열립니다 · 진할수록 그 달 '
            '활동 많음' + old_note + '</span></h2>'
            '<div style="overflow-x:auto"><div style="position:relative;min-width:'
            f'{LW + GW}px">'
            + _overlay(months, LW, CW)
            + '<div style="position:relative;z-index:1">' + hdr + "".join(body) + "</div>"
            "</div></div>"
            '<div class="note">판정에 실제로 쓰인 신호(signals)의 시각을 담당 업무 단위로 '
            "센 것입니다 — 파일 신호는 저장 시각 기준이라 재동기화가 있으면 그 달로 몰려 "
            "보일 수 있습니다.</div>" + js + "</div>")


def render_full(share, html_dir, sender=None, log=say):
    r"""팀 통합 보고서 본문 렌더 — (doc_v2, doc_v3, info). **파일을 쓰지 않는다**.

    로드율·과제 배분·Agentic·워크플로우를 한 장으로. 표는 원본 팀 화면(TEAM_PAGE)의 도식을
    따른다: 과제·업무는 누적바, Agentic 12과제는 히트맵 색. sender 가 있으면 계열/세부/후보/
    과제분류 캐시를 Copilot 으로 채우고(캐시 누적), 없으면 저장된 캐시만 적용한다."""
    ag = _agg()
    data = ag.collect_team_data(share)
    members = data["members"]
    lm = ag.load_members(share)
    if len(lm) == len(members):
        # 두 목록은 같은 폴더 순서다 — 항목끼리 붙여야 owner 이름이 같은 폴더 두 개도 제 폴더를 가리킨다
        for m, src in zip(members, lm):  # noqa: B905
            m["dir"] = src["dir"]
    else:
        mdirs = {m["owner"]: m["dir"] for m in lm}
        for m in members:
            m["dir"] = mdirs.get(m["owner"], "")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    adjust = load_adjust(share, log)

    # 기간이 달라도 모은다 — 예전 버전으로 올린 사람의 Agentic 이 빠지던 결함
    agentic = collect_agentic_all([m for m in members if m["dir"]]) or (data.get("agentic") or [])
    cands = merge_candidates(agentic)
    cands, n_cand = cand_refine(share, cands, sender, log)
    if n_cand:
        log(f"    신규 후보 통합: {n_cand}줄 합침 ({CAND_FILE} 누적)")
    owners_all = list(dict.fromkeys(m["owner"] for m in members))
    # D5(b) — 측정 불충분(coverage.grade=unreliable) 인원은 §1 별도 표 · 팀 투입·순위·과제×인원·유형 분포에서 제외.
    # Agentic·워크플로우·간트(그 사람 자신의 자료)는 그대로 둔다. 구판 자료(coverage 없음)는 비교에 들어간다.
    members_cmp = [m for m in members if not m.get("unreliable")]
    members_x = [m for m in members if m.get("unreliable")]
    owners = list(dict.fromkeys(m["owner"] for m in members_cmp))
    if members_x:
        log(f"    측정 불충분(비교 제외) {len(members_x)}명: {', '.join(m['owner'] for m in members_x)}")

    # ── 워크플로우 재료 ──
    items, src_n, rows_by = gather_flows(share, html_dir)
    clusters, coarse = cluster_flows(items, share, rows_by) if items else ([], [])
    groups = group_by_project(clusters) if clusters else []
    wf_owners = sorted({it["owner"] for it in items})
    wf_mm = round(sum(c["mm"] for c in clusters), 2)
    ax_total = round(sum(c["ax_mm"] for c in clusters), 2)

    team_mm = round(sum(float(m.get("total_mm") or 0) for m in members_cmp), 2)
    n_ag = len(agentic)

    # ── 1. 인별 로드율 ──
    # 값은 업로드로 들어온 남의 입력 — 숫자는 숫자로만(fnum/pct_text), 문자열은 esc 를 거친다
    vmax = max([_fnum(m.get("total_mm"), 0.0) for m in members_cmp] or [1]) or 1

    def _row1(m, grey=False):
        return (
            f"<tr{' style=color:#8b929b' if grey else ''}><td><b>{esc(m['owner'])}</b></td>"
            f"<td class='dim'>{esc(m.get('function'))}</td>"
            f"<td class='dim'>{esc('~'.join(str(x) for x in (m.get('period') or [])))}</td>"
            f"<td class='num'><b>{_fnum(m.get('total_mm'), 0.0):.2f}</b></td>"
            f"<td class='num'>{'–' if not _fnum(m.get('avail_mm')) else format(_fnum(m.get('avail_mm')), '.2f')}</td>"
            f"<td class='num'><b>{ag.pct_text(m.get('load_pct'))}</b></td>"
            f"<td style='width:150px'>"
            + ("" if grey else f"<span class='mmbar' style='width:{max(2, round(_fnum(m.get('total_mm'), 0.0) / vmax * 140))}px'></span>")
            + f"</td><td class='dim' style='font-size:11px'>{esc(ag.measure_text(m)) or '–'}</td>"
            f"<td class='dim'>신호 {esc(m.get('signals'))}건"
            + (f" · 무흔적 {esc(m['no_evidence_days'])}일" if m.get("no_evidence_days") else "")
            + (f" · 비업무 제외 −{_fnum(m.get('dropped_h'), 0.0):.1f}h"
               if m.get("rehours") and _fnum(m.get("dropped_h")) else "")
            + ag.anomaly_badge(m)            # 'PC 기록 이상 N일 · 16h 초과 N일' — 개인 이상치 장부의 일수
            + ag.coverage_badge(m)           # 신뢰 / 주의 / 측정 불충분 (D5)
            + ag.cfg_badge(m)                # 산식 설정 상이 (팀 다수와 다른 분모)
            + "</td></tr>")

    rows1 = "".join(_row1(m) for m in members_cmp)
    rows1x = ""
    if members_x:
        rows1x = (
            "<div style='margin-top:10px;border-top:1px dashed #e4e7eb;padding-top:8px'>"
            "<div style='font-size:12px;font-weight:700;margin-bottom:2px'>측정 불충분 — 팀 투입·순위·과제×인원에서 제외 "
            "<span class='state'>PC 가동 기록·창 샘플러·Outlook 일정이 모두 비어 근거가 파일 흔적뿐 — 수집 실패이지 "
            "낮은 로드가 아닙니다</span></div><div style='overflow-x:auto'><table><tr><th>이름</th><th>파트</th>"
            "<th>기간</th><th class='num'>투입</th><th class='num'>가용</th><th class='num'>로드율</th><th></th>"
            "<th>측정 방식</th><th>근거</th></tr>"
            + "".join(_row1(m, grey=True) for m in members_x) + "</table></div></div>")

    # ── 2. 과제 × 인원 (누적바 · 기간 무관 재집계 · 규칙+계열 통합 · 작은 과제 접기) ──
    matrix2, det2, wt, tag_fixed, no_rows, wt_src, meet = team_rows_matrix(members_cmp, share)
    if not matrix2:                       # 인별 폴더가 전혀 없으면 배포본 취합값으로
        matrix2 = data.get("matrix") or {}
        det2 = {}
        wt = data.get("wt") or {}
        wt_src = {}
        meet = {}

    # 회의·협업(과제 미지정) MM 을 그 사람의 과제 비중대로 배분한다 — **추정**이며 화면에 명시
    meet_alloc = round(sum(meet.values()), 2)
    if meet_alloc:
        left = {}
        for who9, amt in meet.items():
            w9 = {pj: row.get(who9, 0.0) for pj, row in matrix2.items()
                  if not _rule_nonpj(pj) and row.get(who9)}
            tot9 = sum(w9.values())
            if tot9 <= 0:
                left[who9] = amt
                continue
            for pj, v9 in w9.items():
                add9 = amt * v9 / tot9
                matrix2[pj][who9] = matrix2[pj].get(who9, 0.0) + add9
                d9 = det2.setdefault(pj, {}).setdefault("회의·협업(배분)", {})
                d9[who9] = d9.get(who9, 0.0) + add9
        if left:
            for who9, amt in left.items():
                matrix2.setdefault("회의·협업(미배분)", {})[who9] = amt
        meet_alloc = round(meet_alloc - sum(left.values()), 2)
    pj_groups = merge_similar(list(matrix2.items()))
    pj_groups, n_series = series_refine(share, pj_groups, sender, log)
    if n_series:
        log(f"    계열 통합: 과제 {n_series}줄을 합쳤습니다 ({SERIES_FILE} 누적)")
    dgmap = detgrp_refine(share, det2, sender, log)
    if dgmap:
        log(f"    세부업무 통합 맵 {len(dgmap)}건 적용 ({DETGRP_FILE})")
    cls = pjclass_refine(share, [g["name"] for g in pj_groups], sender, log)
    np_rows = [g for g in pj_groups if is_nonproject(g["name"], cls)]
    pj_only = [g for g in pj_groups if not is_nonproject(g["name"], cls)]
    pj_big = [g for g in pj_only if g["total"] >= 0.3]
    pj_small = [g for g in pj_only if g["total"] < 0.3]
    if not pj_big:
        pj_big, pj_small = pj_only, []
    pj_stack = stack_rows_x(pj_big, owners, det2, dgmap, 300, 150)
    pj_fold = ""
    if pj_small:
        pj_fold = (
            f'<details style="margin:8px 0 0"><summary style="padding:8px 12px;font-size:12px">'
            f'작은 과제 {len(pj_small)}건 펼치기 <span class="state">각 0.3 MM 미만 · 합계 '
            f'{sum(g["total"] for g in pj_small):.2f} MM</span></summary>'
            f'<div class="body">{stack_rows(pj_small, owners, 300, 150)}</div></details>')
    np_html = ""
    if np_rows:
        np_html = (
            '<div style="margin-top:10px;border-top:1px dashed #e4e7eb;padding-top:8px">'
            '<div style="font-size:12px;font-weight:700;margin-bottom:2px">비과제성 업무 '
            '<span class="state">공통·교육·지원·운영 — 과제가 아니어서 따로 셉니다</span></div>'
            + stack_rows_x(np_rows, owners, det2, dgmap, 300, 150) + "</div>")
        if any(g["name"] == EMPTY_PJ or EMPTY_PJ in g["names"] for g in np_rows):
            np_html += ('<div class="note">' + esc(EMPTY_PJ)
                        + " = 과제(Level 2) 칸이 비어 있던 행 — 그 PC 에서 정제하면 채워집니다.</div>")
    data_note = ""
    rescaled = [f"{o9}({i9.get('sum', 0):.2f}→{i9.get('total', 0):.2f})"
                for o9, i9 in (wt_src or {}).items() if abs(i9.get("scale", 1.0) - 1.0) > 0.05]
    if rescaled:
        data_note += ('<div class="note" style="margin:6px 0 0">행 MM 합이 ①의 공식 투입과 달라 '
                      "투입에 맞춰 재스케일한 인원: " + esc(", ".join(rescaled))
                      + " — 과제 열 합·트리맵·세부 구성은 이 배율로 맞춘 값입니다(정제본이 옛것이거나 "
                      "다른 기간 자료를 가져온 경우).</div>")
    if tag_fixed:
        data_note += ('<div class="note" style="margin:6px 0 0">다른 기간 자료를 가져온 인원: '
                      + esc(", ".join(tag_fixed)) + " — 기간이 달라도 빠지지 않게 했습니다.</div>")
    if meet_alloc:
        data_note += ('<div class="note" style="margin:6px 0 0">과제 미지정 회의·협업 '
                      f"{meet_alloc:.2f} MM 은 각자의 과제 비중대로 배분했습니다(추정) — "
                      "세부 펼침의 \'회의·협업(배분)\' 줄로 구분됩니다.</div>")
    if no_rows:
        data_note += ('<div class="note" style="margin:6px 0 0">mm 자료를 찾지 못한 인원: '
                      + esc(", ".join(no_rows)) + " — 그 PC 에서 업로드하면 채워집니다.</div>")
    if members_x:
        data_note += ('<div class="note" style="margin:6px 0 0">측정 불충분으로 과제×인원·유형 분포에서 제외한 인원: '
                      + esc(", ".join(m["owner"] for m in members_x))
                      + " — 그 사람의 과제 배분은 개인 리포트(개인리포트 폴더)를 보세요.</div>")
    so_owners = sorted(o for o, i in (wt_src or {}).items() if i.get("share_only"))
    if so_owners:
        data_note += ('<div class="note" style="margin:6px 0 0">share 값만 있고 공식 총량이 '
                      "없어 MM 을 복원하지 못한 인원: " + esc(", ".join(so_owners))
                      + " — 그 PC 에서 다시 업로드하면 채워집니다.</div>")

    # ── 3. 업무유형 분포 — 개인 HTML 화면 값 그대로, 없는 사람만 폴백 ──
    html_wt = collect_wt_html(html_dir)
    n_html_wt = 0
    for o in owners:
        hw = html_wt.get(ukey(o))
        if hw:
            wt[o] = dict(hw["wt"])
            n_html_wt += 1
            wt_src.setdefault(o, {})["file"] = ("개인 HTML(얼린 보고서)" if hw["frozen"]
                                               else "개인 HTML(분석 리포트)")
    if n_html_wt:
        log(f"    업무유형: 개인 HTML 화면 값 그대로 {n_html_wt}명 (재계산 없음)")

    WTC = {"개발": "#4f8ef7", "사무": "#f7b94f", "현장": "#4fc47f", "협업": "#b06ef7"}
    seen_wt = {k for o in owners for k in (wt.get(o) or {})}
    extra_wt = sorted(seen_wt - set(WTC))
    for i, k in enumerate(extra_wt):
        WTC[k] = PAL10[(4 + i) % len(PAL10)]
    wt_keys = [k for k in ("개발", "사무", "현장", "협업") if k in seen_wt] + extra_wt
    wt_max = max([sum((wt.get(o) or {}).values()) for o in owners] or [0.001]) or 0.001

    def _wt_badge(o, sv):
        info = wt_src.get(o) or {}
        if sv == 0 and not info.get("file"):
            return ""
        t = info.get("total") or 0
        gap = sv - t
        if abs(gap) <= 0.05 or (t and abs(gap) / t <= 0.05):
            return ""
        pct = f"{gap / t * 100:+.0f}%" if t else f"{gap:+.2f} MM"
        tip = (f"업무유형 합 {sv:.2f} MM 은 {esc(info.get('file') or 'CSV')} 행의 합, "
               f"인별 로드율의 투입 {t:.2f} MM 은 업로드된 공식값(member.json)입니다.")
        return (f'<span title="{tip}" style="font-size:10px;color:#b3541e;'
                f'border:1px solid #e0b394;border-radius:3px;padding:0 4px;margin-left:6px">'
                f'로드율 근거와 다름({pct})</span>')

    def _wt_row(o):
        row = wt.get(o) or {}
        if not sum(row.values()):
            return '<span class="dim">자료 없음</span>' + _wt_badge(o, 0.0)
        return ("".join(f'<i style="display:inline-block;height:14px;'
                        f'width:{max(0.0, row.get(k, 0) / wt_max * 280):.1f}px;background:{WTC[k]}"'
                        f' title="{esc(k)} {row.get(k, 0):.2f} MM"></i>'
                        for k in wt_keys if row.get(k))
                + f'<span style="font-size:10.5px;color:#5a626b"> {sum(row.values()):.2f}</span>'
                + _wt_badge(o, sum(row.values())))

    wt_stack = ("<div style=\'overflow-x:auto\'>" + "".join(
        '<div style="display:flex;align-items:center;gap:8px;margin:4px 0">'
        f'<span style="width:90px;flex:0 0 90px;font-size:11.5px;text-align:right">{esc(o)}</span>'
        f'<span style="white-space:nowrap;flex:0 0 auto">{_wt_row(o)}</span></div>'
        for o in owners) + "</div>") if owners else '<div class="note">데이터 없음</div>'
    wt_leg = "".join(f'<span style="font-size:11px;margin-right:10px">'
                     f'<span class="dot" style="background:{WTC[k]}"></span>{esc(k)}</span>'
                     for k in wt_keys)

    # ── 4. Agentic 12과제 × 인원 (히트맵 색 — 원본 팀 화면 방식) ──
    other_period = [a["owner"] for a in agentic if a.get("other_period")]
    task_legend = "".join(
        f'<span class="tag" title="{esc(t.get("desc"))}"><b>{esc(t.get("id"))}</b> '
        f'{esc(t.get("name"))}</span>' for t in (data.get("tasks") or []))

    # ── 5. 신규 후보(유사 병합) ──
    rows_new = "".join(
        f"<tr><td><b>{esc(g['name'])}</b>"
        + (f"<div class='sub'>표기 {len(g['names'])}종 통합: "
           f"{esc(' / '.join(g['names'][:4]))}</div>" if len(g["names"]) > 1 else "")
        + f"</td><td>{''.join('<span class=tag>' + esc(w) + '</span>' for w in g['who'])}</td>"
        f"<td class='num'>{g['mm']:.2f}</td>"
        f"<td class='dim'>{esc(g['logic'][:130])}</td></tr>"
        for g in cands) or "<tr><td colspan=4 class='dim'>발굴된 후보가 없습니다</td></tr>"

    # ── 6. 공통업무 ──
    rows_common = "".join(
        f"<tr><td><b>{esc(c['detail'])}</b></td><td class='dim'>{esc(', '.join(c['models']))}</td>"
        f"<td>{''.join('<span class=tag>' + esc(w) + '</span>' for w in c['who'])}</td>"
        f"<td class='num'>{c['mm']:.2f}</td></tr>"
        for c in (data.get("common") or [])[:12]) or (
        "<tr><td colspan=4 class='dim'>없음</td></tr>")

    # ── 7. 워크플로우 유형별 비중 ──
    cmax = max([c["mm"] for c in clusters] or [0.001]) or 0.001
    wf_bars = "".join(
        f"<tr><td style='max-width:240px'><b>{esc(c['detail'])}</b>"
        f"<div class='sub'>{esc(c['project'])}</div></td>"
        f"<td style='width:270px'><span class='mmbar' "
        f"style='width:{max(3, round(c['mm'] / cmax * 250))}px'></span></td>"
        f"<td class='num'><b>{c['mm']:.2f}</b></td>"
        f"<td class='num'>{len(c['who'])}명 · {c['flows']}건</td>"
        f"<td class='num'>{c['ax_mm']:.2f}</td></tr>"
        for c in clusters[:14]) or (
        "<tr><td colspan=5 class='dim'>담당 업무 단위 워크플로우가 없습니다</td></tr>")
    if len(clusters) > 14:
        _r = clusters[14:]
        wf_bars += (f"<tr><td class='dim'>나머지 {len(_r)}종</td><td></td>"
                    f"<td class='num dim'>{sum(c['mm'] for c in _r):.2f}</td>"
                    f"<td class='num dim'>{sum(c['flows'] for c in _r)}건</td>"
                    f"<td class='num dim'>{sum(c['ax_mm'] for c in _r):.2f}</td></tr>")

    # ── 8. 자동화 우선순위 ──
    auto = sorted([c for c in clusters if c["agent_hi"]],
                  key=lambda c: (-len(c["who"]), -c["mm"]))
    auto_rows = "".join(
        f"<tr><td><b>{esc(c['detail'])}</b><div class='sub'>{esc(c['project'])}</div></td>"
        f"<td>{''.join('<span class=tag>' + esc(n) + '</span>' for n in c['agent_hi_names'])}</td>"
        f"<td class='num'>{len(c['who'])}명</td><td class='num'><b>{c['mm']:.2f}</b></td>"
        f"<td class='num'>{c['ax_mm']:.2f}</td>"
        f"<td class='dim'>{esc(c['cycle_top'] or '-')}</td></tr>"
        for c in auto[:12]) or (
        "<tr><td colspan=6 class='dim'>'상'(자동화 가능) 판정 단계가 없습니다</td></tr>")

    # ── 9. 담당 업무 × 인원 (누적바) ──
    wf_stack = stack_rows(
        [{"name": f"{c['detail']}", "names": {c["detail"]}, "row": c["mm_by"],
          "total": c["mm"]} for c in clusters[:14]], wf_owners, 280, 160)

    # ── 9-1. 담당 업무 활동 간트 (월별 · 신호 기준) ──
    gantt_html = build_gantt(share, members, clusters, groups, owners_all)   # 간트는 본인 자료 — 전원

    # ── 10. 과제별 워크플로우 (접이식) ──
    def _steps_tbl(steps, total=None):
        hidden = max(0, (total or len(steps)) - len(steps))
        tail = (f'<tr><td></td><td colspan="4" class="dim">… 나머지 {hidden}단계 — '
                "전체 단계는 그 사람의 개인 리포트에 있습니다</td></tr>") if hidden else ""
        body = "".join(
            f'<tr><td class="ord"><b>{i + 1}</b></td>'
            f'<td class="stn"><b>{esc(s["name"])}</b>'
            + (f'<div class="sub">{esc(s["cycle"])}</div>' if s.get("cycle") else "")
            + "</td><td>"
            + (esc(s.get("desc")) or '<span class="dim">설명 없음</span>')
            + f'</td><td class="num" style="width:44px">{s["n"]}명</td>'
            f'<td class="agc"><span class="pill" '
            f'style="background:{_AGENT_C.get(s["agent"], "#8b929b")}">Agent {esc(s["agent"])}</span>'
            + (f'<div class="sub">{esc(s["how"])}</div>' if s.get("how") else "")
            + "</td></tr>" for i, s in enumerate(steps))
        return (body + tail) or (
            '<tr><td colspan="5" class="dim">공통 단계가 없습니다 — 사람마다 흐름이 다릅니다</td></tr>')

    wf_cards = []
    for gi, g in enumerate(groups):
        inner = []
        for c in g["types"]:
            tagline = ("<span class='tag' style='background:#e8f3ea;color:#1d6b3a'>여러 명</span>"
                       if len(c["who"]) > 1 else "<span class='tag'>단독</span>")
            by = [(w, v) for w, v in sorted(c["mm_by"].items(), key=lambda kv: -kv[1]) if v > 0]
            btot = sum(v for _w, v in by) or 1

            def _pc(w):
                return PAL10[(wf_owners.index(w) if w in wf_owners else 0) % len(PAL10)]
            bar = ('<div class="bigbar">' + "".join(
                f'<i style="width:{v / btot * 100:.1f}%;background:{_pc(w)}"'
                f' title="{esc(w)} {v:.2f} MM"></i>' for w, v in by)
                + '</div><div class="leg">' + "".join(
                    f'<div><span class="dot" style="background:{_pc(w)}"></span>'
                    f'{esc(w)}<span class="v">{v:.2f} MM</span></div>'
                    for w, v in by) + "</div>") if by else ""
            inner.append(
                f'<div class="unit"><div class="uhead">{tagline}<b>{esc(c["detail"])}</b>'
                f'<span class="state">{c["mm"]:.2f} MM · 수행 인원 {len(c["who"])}명'
                f'<span class="sub"> (이 담당 업무를 하는 사람 수)</span> · 흐름 {c["flows"]}건 · '
                f'단계 {len(c["steps"])}{"/" + str(c["steps_total"]) if c.get("steps_total", 0) > len(c["steps"]) else ""}개'
                + (f' · 주기 {esc(c["cycle_top"])}' if c["cycle_top"] else "") + "</span></div>"
                f'<div class="dim" style="margin:2px 0 4px">{esc(c["role"] or "판단 유보")}</div>'
                + "".join(f'<span class="tag">{esc(w)}</span>' for w in c["who"])
                + bar
                + '<table style="margin-top:6px"><tr><th></th><th>단계</th><th>무슨 일</th>'
                f'<th class="num">수행</th><th>Agent 가능성</th></tr>'
                f'{_steps_tbl(c["steps"], c.get("steps_total"))}</table></div>')
        wf_cards.append(
            f'<details{" open" if gi == 0 else ""}><summary>{esc(g["project"])}'
            f'<span class="state">담당 업무 {len(g["types"])}종 · {g["mm"]:.2f} MM · '
            f'수행 인원 {len(g["who"])}명 · 여러 명이 하는 업무 {g["shared"]}종</span></summary>'
            f'<div class="body">{"".join(inner)}</div></details>')

    coarse_html = ""
    if coarse:
        by_who = {}
        for x in coarse:
            by_who.setdefault(x["owner"], set()).add(x["project"])
        coarse_html = (
            '<div class="card"><h2>과제(상위 개체) 단위로만 올라온 워크플로우 '
            f'<span class="state">{len(coarse)}건 · 유형 분석에서 제외</span></h2>'
            '<div class="note" style="margin:0 0 8px">프로젝트 하나에는 성격이 다른 업무가 여럿 '
            '섞여 있어 하나의 일의 순서로 정의할 수 없습니다. 아래 인원은 담당 업무 단위 '
            '워크플로우가 아직 없어 유형 분석에 넣지 않았습니다 — 그 PC 에서 LoadMonitor22 로 '
            '[분석 실행](AI 판정)을 다시 돌리면 담당 업무 단위로 만들어집니다.</div>'
            '<table><tr><th style="width:120px">이름</th><th>과제</th></tr>'
            + "".join(f"<tr><td><b>{esc(w)}</b></td><td>"
                      + "".join(f'<span class="tag">{esc(p)}</span>' for p in sorted(ps))
                      + "</td></tr>" for w, ps in sorted(by_who.items())) + "</table></div>")

    island = json.dumps({"kind": "lm-team-report", "generated": stamp, "share": share,
                         "tasks": data.get("tasks") or [], "agentic": agentic,
                         "members": members, "adjust": adjust},
                        ensure_ascii=False).replace("<", "\\u003c")
    ext = src_n.get("external") or {}
    ext_note = ""
    if ext:                # 인원(member.json)이 아닌 owner 의 개인 HTML — 사람으로 세지 않았다
        ext_note = (" 인원 목록에 없는 개인 HTML " + str(sum(ext.values())) + "건("
                    + esc(", ".join(sorted(ext)[:5])) + ")은 옛 자료·외부 자료로 보고 제외했습니다.")
        log(f"    개인 HTML 제외(인원 아님): {', '.join(sorted(ext)[:5])}")

    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>팀 통합 보고서 — 로드율 · Agentic · 워크플로우</title><style>
body{{font:13px/1.55 'Malgun Gothic','Segoe UI',sans-serif;color:#2c333b;background:#f4f6f8;margin:0}}
.wrap{{max-width:1120px;margin:0 auto;padding:16px 20px 60px}}
h1{{font-size:18px;margin:10px 0 2px;color:#1c232b}}
.card{{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:12px}}
.card h2{{font-size:13px;margin:0 0 10px;color:#2c333b}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}}
.kpi{{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:12px 14px}}
.kpi .lb{{font-size:10.5px;color:#8b929b}}
.kpi .vl{{font-size:21px;font-weight:800;margin:2px 0;letter-spacing:-0.5px}}
.kpi .nt{{font-size:10.5px;color:#5a626b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
@media(max-width:860px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:520px){{.kpis{{grid-template-columns:1fr}}.wrap{{padding:12px}}}}
.state{{font-size:12px;color:#5a626b;font-weight:400;margin-left:8px}}
.note{{font-size:10.5px;color:#8b929b;margin-top:8px;line-height:1.6}}
.dim{{color:#8b929b;font-size:11.5px}} .sub{{color:#8b929b;font-size:11px}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
.leg{{font-size:11px;color:#4a5159;line-height:1.9}} .leg .v{{float:right;font-weight:700}}
.bigbar{{height:22px;border-radius:5px;overflow:hidden;display:flex;margin:6px 0 8px}}
.bigbar i{{display:block;height:100%}}
details{{margin-bottom:12px}}
details summary{{cursor:pointer;font-size:13px;font-weight:700;color:#2c333b;padding:12px 16px;
background:#fff;border:1px solid #e4e7eb;border-radius:8px;list-style:none}}
details summary::-webkit-details-marker{{display:none}}
details summary::before{{content:"▸ ";color:#8b929b}}
details[open] summary{{border-radius:8px 8px 0 0}}
details[open] summary::before{{content:"▾ "}}
details .body{{background:#fff;border:1px solid #e4e7eb;border-top:0;border-radius:0 0 8px 8px;
padding:10px 16px 14px}}
.unit{{border-left:3px solid #d7dbe0;padding:8px 0 10px 12px;margin:10px 0}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#f6f8fa;color:#3d4a5c;text-align:left;padding:6px 8px;font-weight:700;
border-bottom:2px solid #e4e7eb;font-size:11px}}
td{{padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.ord{{width:26px;text-align:center;color:#8b929b}}
td.stn{{width:170px}} td.agc{{width:130px}}
.pill{{display:inline-block;padding:1px 8px;border-radius:9px;color:#fff;font-size:11px}}
.tag{{display:inline-block;background:#f0f3f7;border-radius:3px;padding:1px 7px;
margin:1px 3px 1px 0;font-size:10.5px;color:#3d444c}}
.mmbar{{display:inline-block;height:9px;border-radius:4px;background:#2a78d6;vertical-align:middle}}
.top{{background:#1c2b3a;color:#fff;padding:9px 14px;font-size:12px}}
#agx td.x{{text-decoration:line-through;color:#b6bcc3;background:#f2f4f6}}
#agx th,#agx td{{padding:3px 5px;font-size:10.5px}}
#agx .stick{{position:sticky;left:0;background:#fff;z-index:1}}
#agx tr.sumrow td{{background:#f6f8fa;border-bottom:2px solid #d7dbe0}}
#agx th.stick{{background:#f6f8fa}}
details.gx>summary::before,details.gxr>summary::before,
details.gx[open]>summary::before,details.gxr[open]>summary::before{{content:""}}
details.gx>summary,details.gxr>summary{{cursor:pointer;list-style:none}}
details.gx,details.gxr{{margin-bottom:0}}
.g-row{{border-radius:5px;transition:background .12s}}
.g-row:hover{{background:#f4f8fd}}
.garr{{display:inline-block;color:#9aa1a9;font-size:10px;transition:transform .15s}}
details[open]>summary .garr{{transform:rotate(90deg)}}
#agx td.cell{{cursor:pointer}} #agx td.cell:hover{{outline:2px solid #2a78d6;outline-offset:-2px}}
.pchk{{font-size:11.5px;color:#52514e;margin-right:10px;white-space:nowrap}}
button{{font:12px 'Malgun Gothic';padding:4px 10px;border:1px solid #c3c2b7;border-radius:6px;
background:#fff;cursor:pointer}} button:hover{{background:#f0f3f7}}
textarea{{width:100%;height:64px;font:11px Consolas,monospace;margin-top:6px}}
</style></head><body>
<div class="top">팀 통합 보고서 · 인원 {len(members)}명 · {stamp} 생성 · 사내 전용 —
로드율·과제 배분·Agentic·워크플로우를 한 장에 담았습니다
{'· 유사 항목 정리 적용' if data.get('aliases') else ''}</div>
<div class="wrap">
<h1>팀 업무 로드율 · Agentic AI · 워크플로우</h1>

<div class="kpis">
<div class="kpi"><div class="lb">인원</div><div class="vl">{len(members)}</div>
<div class="nt">Agentic {n_ag}명 · 워크플로우 {len(wf_owners)}명{f' · 측정 불충분 {len(members_x)}명' if members_x else ''}</div></div>
<div class="kpi"><div class="lb">팀 투입 MM</div><div class="vl">{team_mm:.2f}</div>
<div class="nt">과제 {len(pj_groups)}개{' · 측정 불충분 인원 제외' if members_x else ''}</div></div>
<div class="kpi"><div class="lb">담당 업무 유형</div><div class="vl">{len(clusters)}</div>
<div class="nt">여러 명이 하는 유형 {sum(1 for c in clusters if len(c['who']) > 1)}종</div></div>
<div class="kpi"><div class="lb">AX 가능 MM</div><div class="vl">{ax_total:.2f}</div>
<div class="nt">워크플로우 MM {wf_mm:.2f} 의
{round(ax_total / (wf_mm or 1) * 100)}%</div></div>
</div>

<!--SEC1--><div class="card"><h2>1. 인별 로드율 <span class="state">투입 MM ÷ 가용 MM · 야근은 상한 없이(하루 24h 물리 한계만) ·
측정 방식 = 샘플러 실측 / PC 가동 하한 / 흔적 폭 / 종일 행사 / 수동 기록 일수 · 배지: 신뢰·주의·측정 불충분(수집 결측 수) ·
'산식 설정 상이' = 표준시간·점심·주간 창·공휴일 수가 팀 다수와 달라 분모가 다른 사람</span></h2>
<div style='overflow-x:auto'><table><tr><th>이름</th><th>파트</th><th>기간</th><th class="num">투입</th><th class="num">가용</th>
<th class="num">로드율</th><th></th><th>측정 방식</th><th>근거</th></tr>{rows1}</table></div>{rows1x}</div><!--/SEC1-->

<div class="card"><h2>2. 과제 × 인원 <span class="state">누적바 = 사람별 MM · 줄을 펼치면
세부업무 구성 · 유사 표기·같은 계열은 합침 · 0.3 MM 미만 접힘 · 비과제성은 아래 따로</span></h2>
{treemap_html(pj_big + pj_small, np_rows)}{pj_stack}{pj_fold}{np_html}
<div class="row" style="margin-top:8px">{stack_legend(owners)}</div>{data_note}</div>

<div class="card"><h2>3. 업무유형 분포 <span class="state">인별 MM — 개인 HTML 화면 값
그대로(HTML 이 없는 사람만 개인 자료 구성비 × ①의 투입 MM)</span></h2>
{wt_stack}<div class="row" style="margin-top:6px">{wt_leg}</div></div>

<div class="card"><h2>4. Agentic AI 12과제 적합률 × 인원
<span class="state">세로 = 인원 · 가로 = 12과제(인원이 많아도 표 폭이 늘지 않습니다) ·
색이 진할수록 적합률 높음 · 셀 클릭 = 제외/복원 · 이름 체크 해제 = 그 사람 제외</span></h2>
{('<div class="note" style="margin:0 0 6px">다른 기간 결과를 쓴 인원: '
  + esc(', '.join(other_period)) + ' — 기간이 달라도 결과를 가져왔습니다.</div>')
 if other_period else ''}
<div id="pchks" style="margin:6px 0"></div>
<div style="overflow-x:auto"><table id="agx"></table></div>
<div style="margin-top:6px">{task_legend}</div>
<div style="margin-top:8px"><button id="copyadj">조정 내용 내보내기</button>
<span class="dim"> 내보낸 JSON 을 취합 폴더의 {ADJUST_FILE} 로 저장하면 다음 생성부터 반영됩니다.</span>
<textarea id="adjout" style="display:none" readonly></textarea></div></div>

<div class="card"><h2>5. 팀에서 발굴된 신규 Agentic AI 후보
<span class="state">담당자별로 나온 후보 중 비슷한 것은 합쳤습니다</span></h2>
<div style='overflow-x:auto'><table><tr><th>후보</th><th>제안 인원</th><th class="num">대체 가능 ≈MM</th><th>로직</th></tr>
{rows_new}</table></div></div>

<div class="card"><h2>6. 공통업무 — 자동화 우선 후보</h2>
<div style='overflow-x:auto'><table><tr><th>세부업무</th><th>관련 과제</th><th>수행 인원</th><th class="num">합산 MM</th></tr>
{rows_common}</table></div></div>

<h1 style="font-size:15px;margin:20px 0 8px">워크플로우 — 담당 업무 단위</h1>
<div class="note" style="margin:0 0 10px">워크플로우는 <b>담당 업무(중위/하위 개체)</b> 단위로만
셉니다 — 프로젝트 하나에는 성격이 다른 업무가 섞여 있어 하나의 일의 순서로 정의할 수 없습니다.
Agent 가능성 <span class="pill" style="background:#1d8a4a">상</span> 자동화 가능
<span class="pill" style="background:#c98a00">중</span> 보조
<span class="pill" style="background:#8b929b">하</span> 사람 몫 ·
단계의 '수행 N명' = 그 업무를 하는 사람 중 같은 단계를 밟는 사람 수</div>

<div class="card"><h2>7. 유형별 비중 <span class="state">막대 = 합산 MM</span></h2>
<div style='overflow-x:auto'><table><tr><th>담당 업무</th><th></th><th class="num">MM</th><th class="num">인원·흐름</th>
<th class="num">AX 가능 MM</th></tr>{wf_bars}</table></div></div>

<div class="card"><h2>8. 자동화 우선순위
<span class="state">'상'(자동화 가능) 단계가 있는 담당 업무 — 여러 명이 하고 MM 이 클수록
팀 차원 효과가 큽니다</span></h2>
<div style='overflow-x:auto'><table><tr><th>담당 업무</th><th>자동화 가능 단계</th><th class="num">인원</th>
<th class="num">MM</th><th class="num">AX 가능 MM</th><th>주기</th></tr>{auto_rows}</table></div></div>

<div class="card"><h2>9. 담당 업무 × 인원 <span class="state">누적바 = 사람별 MM</span></h2>
{wf_stack}<div class="row" style="margin-top:8px">{stack_legend(wf_owners)}</div></div>

{gantt_html}

<h1 style="font-size:15px;margin:18px 0 8px">10. 과제별 워크플로우
<span class="state">과제를 펼치면 그 안의 담당 업무 워크플로우가 나옵니다</span></h1>
{''.join(wf_cards) or '<div class="card"><div class="note">담당 업무 단위 워크플로우가 없습니다.</div></div>'}
{coarse_html}
<div class="note">원천: {esc(share)}{f' + {esc(html_dir)}' if src_n['html'] else ''} ·
개인 워크플로우 {len(items)}건(서버 {src_n['server']} · 개인 HTML {src_n['html']}) ·
같은 (사람·업무)는 하나만 계상했습니다.{ext_note}</div>
</div>
<script type="application/json" id="lm-team-data">{island}</script>
<script>
(function(){{
 "use strict";
 function E(s){{return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");}}
 var D=JSON.parse(document.getElementById("lm-team-data").textContent);
 var tasks=D.tasks||[], ags=D.agentic||[];
 var owners=ags.map(function(a){{return a.owner;}});
 var exP=new Set();
 ((D.adjust&&D.adjust.excluded_people)||[]).forEach(function(w){{
  var i=owners.indexOf(String(w)); if(i>=0)exP.add(i);}});
 var exC=new Set();
 ((D.adjust&&D.adjust.excluded_cells)||[]).forEach(function(x){{
  if(!x||x.length<2)return;
  var ti=tasks.findIndex(function(t){{return t.id===String(x[0]);}});
  var oi=owners.indexOf(String(x[1]));
  if(ti>=0&&oi>=0)exC.add(ti+","+oi);}});
 function mmOf(hit){{return hit.load_mm_split!=null?hit.load_mm_split:(hit.load_mm||0);}}
 function heatSt(fit){{
  var al=Math.min(0.85,fit/100*0.85+0.08);
  return "background:rgba(42,120,214,"+al.toFixed(2)+");color:"+(fit>=45?"#fff":"#12151a");}}
 function render(){{
  var t=document.getElementById("agx");
  if(!tasks.length||!ags.length){{
   t.innerHTML="<tr><td class='dim'>Agentic 분석 결과가 있는 인원이 없습니다</td></tr>";return;}}
  var h="<tr><th class=stick>이름</th>";
  tasks.forEach(function(tk){{
   h+="<th title=\\""+E(tk.name)+" — "+E(tk.desc)+"\\">"+E(tk.id)+"</th>";}});
  h+="<th class=num>합계 ≈MM</th></tr>";
  var sums=tasks.map(function(){{return 0;}}), fits=tasks.map(function(){{return [];}});
  ags.forEach(function(a,oi){{
   if(exP.has(oi))return;
   tasks.forEach(function(tk,ti){{
    if(exC.has(ti+","+oi))return;
    var hit=(a.match||[]).find(function(x){{return x.task===tk.id&&x.fit;}});
    if(!hit)return;
    sums[ti]+=mmOf(hit); fits[ti].push(hit.fit);
   }});
  }});
  var gtot=0, sr="<tr class=sumrow><td class=stick><b>팀 합계</b></td>";
  tasks.forEach(function(tk,ti){{
   gtot+=sums[ti];
   var nn=fits[ti].length;
   var av=nn?Math.round(fits[ti].reduce(function(x,y){{return x+y;}},0)/nn):0;
   sr+="<td class=num style=\\""+(nn?heatSt(av):"")+"\\"><b>"+sums[ti].toFixed(2)
     +"</b><br><span style='font-size:9.5px'>"+(nn?nn+"명 · "+av+"%":"·")+"</span></td>";
  }});
  sr+="<td class=num><b>"+gtot.toFixed(2)+"</b></td></tr>";
  h+=sr;
  ags.forEach(function(a,oi){{
   var ptot=0;
   var row="<tr><td class=\\"stick"+(exP.has(oi)?" x":"")+"\\"><b>"+E(a.owner)+"</b>"
     +(a.other_period?"<br><span style='font-size:9px;color:#8b929b'>다른 기간</span>":"")+"</td>";
   tasks.forEach(function(tk,ti){{
    var hit=(a.match||[]).find(function(x){{return x.task===tk.id&&x.fit;}});
    var off=exP.has(oi)||exC.has(ti+","+oi);
    if(hit){{
     var mmv=mmOf(hit);
     if(!off)ptot+=mmv;
     row+="<td class='cell num"+(off?" x":"")+"' style=\\""+(off?"":heatSt(hit.fit))
       +"\\" data-ti="+ti+" data-oi="+oi+" title=\\"\\u2248"+mmv.toFixed(2)
       +" MM\\"><b>"+E(hit.fit)+"%</b><br><span style='font-size:8.5px'>"
       +mmv.toFixed(2)+"</span></td>";
    }}else row+="<td class='dim num'>·</td>";
   }});
   row+="<td class=num><b>"+ptot.toFixed(2)+"</b></td></tr>";
   h+=row;
  }});
  t.innerHTML=h;
  Array.prototype.forEach.call(t.querySelectorAll("td.cell"),function(td){{
   td.onclick=function(){{
    var k=td.getAttribute("data-ti")+","+td.getAttribute("data-oi");
    if(exC.has(k))exC.delete(k);else exC.add(k);
    render();}};}});
 }}
 var pc=document.getElementById("pchks");
 pc.innerHTML=owners.map(function(w,oi){{
  return "<label class=pchk><input type=checkbox data-oi="+oi+" "
   +(exP.has(oi)?"":"checked")+"> "+E(w)+"</label>";}}).join("");
 Array.prototype.forEach.call(pc.querySelectorAll("input"),function(cb){{
  cb.onchange=function(){{
   var oi=parseInt(cb.getAttribute("data-oi"),10);
   if(cb.checked)exP.delete(oi);else exP.add(oi);
   render();}};}});
 document.getElementById("copyadj").onclick=function(){{
  var out=JSON.stringify({{
   excluded_people:Array.from(exP).map(function(oi){{return owners[oi];}}),
   excluded_cells:Array.from(exC).map(function(k){{
    var p=k.split(","); return [tasks[+p[0]].id, owners[+p[1]]];}})}},null,1);
  var ta=document.getElementById("adjout");
  ta.style.display="block"; ta.value=out; ta.select();
  try{{document.execCommand("copy");}}catch(e){{}}}};
 render();
}})();
</script></body></html>"""

    # v3 — 인별 로드율 절을 뺀 공유용. 데이터 섬에서도 개인 로드 수치·경로·PC 이름을 지운다.
    m3 = [{k9: v9 for k9, v9 in m9.items()
           if k9 not in ("total_mm", "avail_mm", "load_pct", "worked_h", "overtime_h",
                         "dir", "host", "uploaded_from")}
          for m9 in members]
    island3 = json.dumps({"kind": "lm-team-report", "generated": stamp, "share": share,
                          "tasks": data.get("tasks") or [], "agentic": agentic,
                          "members": m3, "adjust": adjust},
                         ensure_ascii=False).replace("<", "\\u003c")
    doc3 = re.sub(r"<!--SEC1-->.*?<!--/SEC1-->", "", doc, flags=re.S)
    doc3 = re.sub(r'<span title="업무유형 합[^"]*"[^>]*>로드율 근거와 다름\([^)]*\)</span>',
                  "", doc3)
    doc3 = doc3.replace("HTML 이 없는 사람만 개인 자료 구성비 × ①의 투입 MM",
                        "HTML 이 없는 사람만 개인 자료 구성비 기준", 1)
    doc3 = doc3.replace(island, island3, 1)
    doc3 = doc3.replace("<title>팀 통합 보고서",
                        "<title>팀 통합 보고서 v3(로드율 제외)", 1)
    doc3 = doc3.replace('<div class="top">팀 통합 보고서 ·',
                        '<div class="top">팀 통합 보고서 <b>v3 — 인별 로드율 제외</b> ·', 1)
    info = {"members": len(members), "agentic": n_ag, "clusters": len(clusters),
            "coarse": len(coarse), "other_period": other_period, "wf_owners": len(wf_owners),
            "flows": len(items), "flows_html": src_n["html"], "generated": stamp}
    log(f"       인원 {len(members)}명 · Agentic {n_ag}명 · 담당 업무 유형 {len(clusters)}종"
        + (f" · 과제 단위만 {len(coarse)}건" if coarse else ""))
    if other_period:
        log(f"       (다른 기간 결과를 가져온 인원: {', '.join(other_period)})")
    return doc, doc3, info


def build(share, sender=None, snapshot=False, log=say):
    """단일 진입점 — 인별 리포트 복원 + 통합 보고서 2종을 고정 이름으로 원자 교체.
    sender=None(팀 서버 자동 경로) 이면 파일 쓰기는 보고서 2개 + 개인리포트 복원뿐(캐시·alias 무수정).
    snapshot=True 면 팀통합보고서_<ts>.html / 팀통합보고서_v3_<ts>.html 사본도 남긴다."""
    html_dir = os.path.join(share, MEMBER_HTML_DIR)
    try:
        rebuild_member_reports(share, html_dir, log)
    except Exception as e:  # noqa: BLE001 - 복원 실패가 통합 보고서를 막지 않게
        log(f"  [!] 인별 리포트 복원 실패({type(e).__name__}) — 계속")
    doc, doc3, info = render_full(share, html_dir, sender, log)
    full = _atomic_write(os.path.join(share, FULL_HTML), doc)
    v3 = _atomic_write(os.path.join(share, FULL_V3_HTML), doc3)
    out = {"ok": True, "full": full, "v3": v3, **info}
    if snapshot:                                      # 수동 [스냅샷] 때만 타임스탬프 사본
        ts = time.strftime("%Y%m%d_%H%M%S")
        snaps = []
        for src, name in ((full, f"팀통합보고서_{ts}.html"), (v3, f"팀통합보고서_v3_{ts}.html")):
            dst = os.path.join(share, name)
            try:
                shutil.copy2(src, dst)
                snaps.append(dst)
            except OSError as e:
                log(f"  [!] 스냅샷 저장 실패({type(e).__name__}): {name}")
        out["snapshots"] = snaps
    log(f"    → 팀 통합 보고서: {full}")
    log(f"    → v3(인별 로드율 제외): {v3}")
    return out


def _share_from_argv():
    share = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else ""
    if not share:
        try:
            cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
            share = (cfg.get("teamShareDir") or "").strip()
        except (OSError, ValueError):
            share = ""
    if not share or not os.path.isdir(share):
        td = os.path.join(ROOT, "teamdata")
        share = td if os.path.isdir(td) else ""
    return share


def main():
    share = _share_from_argv()
    if not share:
        say("[team_report] 취합 폴더 없음 — 인자로 경로를 주거나 config.teamShareDir 설정")
        say(json.dumps({"ok": False, "error": "no share"}))
        return 1
    sender = None
    if "--copilot" in sys.argv and not os.environ.get("LM_NO_COPILOT"):
        import judge
        sender = judge.copilot_send
    r = build(share, sender=sender, snapshot=("--snapshot" in sys.argv))
    say(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
