# -*- coding: utf-8 -*-
r"""
report_out.py — 개인 리포트(spec §5.11). Agentic AI 전환 과제 발굴 결과를 정적 HTML 한 장으로 만든다.

  python report_out.py [--from YYYY-MM-DD --to YYYY-MM-DD] [--variant local]
      → report\개인리포트_<tag>.html (이 PC 에서만 본다). 마지막 줄은 JSON {"ok","html","tag"} (실패면 + "code","msg").
      기간을 주지 않으면 run_meta 에 "product":"AgentFinder32" 가 있는 가장 최근 결과를 쓴다.
      시작 때 install.startup_check(종료 4) → consent.require(내 자료가 아니면 종료 4 · 모두 지우는 중이면 종료 3).
      종료 코드 0 · 1 실패(결과 없음·잘못된 인자) · 3 · 4.
      공유본(share)은 이 명령으로 만들지 않는다 — 화면 [공유] 탭(teamup --preview/--share)만 build(variant="share")를 부른다.

build(tag, *, variant="local"|"share", scrubber=None, include=None, owner=None, function=None, root=None, cfg=None) -> str|None
  읽는 결과는 report\run_meta_<tag>.json 에 "product":"AgentFinder32" 가 있는 tag 뿐이다(아니면 None).
  agentic_·workflow_·pivots_<tag>.json · data\outlook\collect_summary.json 도 같은 표식이 있어야 읽는다.
  local  머리 띠 "이 파일은 PC 밖으로 보내지 않습니다 — 공유는 [공유] 탭에서만 합니다".
         1 분석 개요(목적 문장·기간·수집 경로·남긴/뺀 건수·자동 삭제일) · 2 Agentic AI 전환 후보(이름·동작 로직·
         발굴 사유·업무 유형·근거건수) · 3 워크플로우와 Agent 가능성(단계·입력→출력·Agent 상/중/하·방법) · 4 업무 분류
         (Level 1~3·근거건수) · 5 공통 업무. 시각·사람·원문 근거는 싣지 않는다(워크플로 단계의 MM-DD 근거도 싣지 않는다).
  share  조직장에게 보내는 공유본. 구조화된 칸(agentic_<tag>.json · workflow_<tag>.json)에서 새로 만든다(local HTML 을 고쳐 쓰지
         않는다). 이름·파트(owner·function — 공유 탭에 적은 그대로) · 기간 YYYY-MM~YYYY-MM · 고정 문장(SHARE_PURPOSE) ·
         후보 {이름·동작 로직·발굴 사유·업무 유형} · 워크플로 단계 {이름·Agent 상/중/하·방법}. 글은 모두 scrubber.text()
         (core\privacy.ShareScrubber — 없으면 이 tag 로 만든다. 제한 고객 목록이 없으면 privacy.RestrictedListError)를 거친다.
         업무 유형(개발·사무·현장·협업)과 Agent 등급(상·중·하)은 정해진 낱말이라 그대로 쓴다.
         메일·일정에서 나온 숫자(근거건수·건수·날짜)·Level 2/3 이름·흐름 번호·script·JSON 섬이 없다.
         include = 미리보기에서 남긴 항목 id 모음(None 이면 전부). id 는 share_items() 가 준다.
share_items(tag, *, scrubber=None, root=None, cfg=None) -> list|None   미리보기 체크 상자용 — 공유본에 실릴 글 그대로(가린 뒤)
  [{"id":"c-…","kind":"candidate","name","logic","reason","task_type"},
   {"id":"s-…","kind":"step","flow":"f-…","name","agent","agent_how"}]  (id = 설치 소금 HMAC — 내용이 바뀌면 id 도 바뀐다.
  id 는 이 PC 의 미리보기 파일에만 둔다 — 서버로 보내지 않는다.)
share_period(tag, *, root=None) -> "YYYY-MM~YYYY-MM" | ""        공유본·공유 요청의 기간 표기
csp(*, sandbox=True) -> str                                       이 리포트에 맞는 Content-Security-Policy(스타일 해시 포함)
두 갈래 모두 정적 HTML 이다 — script·이벤트 속성·style 속성·외부 자원·양식이 없고, 스타일은 <style> 하나뿐(문서 안 CSP 메타가
그 해시만 허용한다).
"""
import base64
import csv
import hashlib
import hmac
import html
import io
import json
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
REP = os.path.join(ROOT, "report")
DATA = os.path.join(ROOT, "data")
_CORE = os.path.join(ROOT, "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import afcfg  # noqa: E402
import consent  # noqa: E402
import install  # noqa: E402
import lmname  # noqa: E402
import period  # noqa: E402
import retention  # noqa: E402

PRODUCT = lmname.PRODUCT
VARIANTS = ("local", "share")
OUT_PREFIX = "개인리포트_"
LOCAL_BANNER = "이 파일은 PC 밖으로 보내지 않습니다 — 공유는 [공유] 탭에서만 합니다"
SHARE_PURPOSE = "이 리포트는 Agentic AI 전환 과제 발굴에만 씁니다. 인사평가·근태·업무량 비교에 쓰지 않습니다"
# 공유본이 가리는 것 — 안내문의 공유 항목과 같은 문장을 그대로 쓴다(core\consent.py · 지키는 만큼만 말한다)
SHARE_MASK_NOTE = f"{consent.SHARE_MASK_LINE} {consent.SHARE_CHECK_LINE}"
LOCAL_TITLE = "Agentic AI 전환 과제 발굴 — 개인 리포트"
SHARE_TITLE = "Agentic AI 전환 과제 — 공유 리포트"
TAG_RX = re.compile(r"^\d{8}-\d{8}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEY_SEP = "␟"                                  # agentic keys '과제␟세부업무'
WORKTYPES = {"개발": "wt-dev", "사무": "wt-off", "현장": "wt-site", "협업": "wt-col"}
AGENT_CLASS = {"상": "ag-hi", "중": "ag-mid", "하": "ag-lo"}
CHANNEL_LABEL = {"com": "Outlook 앱", "owa": "Outlook 웹", "copilot": "M365 Copilot"}
KEPT_LABEL = (("mail_in", "받은 메일"), ("mail_out", "보낸 메일"), ("meetings", "회의"))
EXCL_COLLECT = (("private", "비공개·개인 항목"), ("admin", "휴가·출장·부재 같은 항목"), ("sensitive", "민감한 내용"),
                ("identifier", "번호류(주민번호·카드·계좌 등)"), ("external", "사외 사람이 있는 항목"),
                ("external_unknown", "사내인지 확인할 수 없는 항목"), ("restricted", "제한 고객 관련 항목"))
EXCL_ANALYSE = (("nonwork", "업무가 아닌 항목(자동 회신 등)"), ("bulk", "단체·알림 메일"), ("private_text", "사적인 내용"),
                ("credential", "비밀번호류가 든 항목"), ("duplicate", "중복"))
TYPED_MAX = 40                                      # 공유 탭에 적은 이름·파트의 최대 글자 수
DASH = "<span class=\"dim\">–</span>"

CSS = (
    ":root{color-scheme:light}*{box-sizing:border-box}"
    "body{font:13px/1.6 'Malgun Gothic','Segoe UI',sans-serif;color:#2c333b;background:#f4f6f8;margin:0}"
    ".top{background:#1c2b3a;color:#fff;padding:9px 16px;font-size:12px}"
    ".wrap{max-width:1080px;margin:0 auto;padding:16px 16px 60px}"
    "h1{font-size:19px;margin:10px 0 2px;color:#1c232b}"
    "h1 .sub{font-size:13px;font-weight:400;color:#5a626b;margin-left:8px}"
    ".meta{color:#8b929b;font-size:11.5px;margin-bottom:6px}"
    ".purpose{background:#eef4fb;border:1px solid #d5e3f3;border-radius:8px;padding:10px 14px;margin:10px 0 12px;"
    "font-size:12.5px;color:#1f3b5a}"
    ".card{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:12px}"
    ".card h2{font-size:14px;margin:0 0 10px;color:#2c333b}"
    ".state{font-size:12px;color:#5a626b;font-weight:400;margin-left:8px}"
    ".note{font-size:11px;color:#8b929b;margin-top:8px;line-height:1.6}"
    ".warn{font-size:12px;color:#b54708;margin:6px 0}"
    ".dim{color:#8b929b;font-size:11.5px}"
    ".sub{color:#8b929b;font-size:11px}"
    "table{width:100%;border-collapse:collapse;font-size:12px}"
    "th{background:#f6f8fa;color:#3d4a5c;text-align:left;padding:6px 8px;font-weight:700;"
    "border-bottom:2px solid #e4e7eb;font-size:11px}"
    "td{padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}"
    "td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}"
    "td.ord{width:28px;text-align:center;color:#8b929b}td.agc{width:240px}"
    "table.kv th{width:160px;background:#fafbfc;border-bottom:1px solid #eef0f3;font-size:12px}"
    "tr.l1 td{background:#fafbfc;font-weight:700;color:#4a5159}"
    ".cand{border-left:3px solid #6c4fb8;padding:4px 0 4px 12px;margin:12px 0}"
    ".cand .nm{font-weight:700;font-size:13px}"
    ".cand .ln{font-size:12px;margin-top:3px}.cand .ln b{color:#4a5159;margin-right:6px}"
    ".area{margin:16px 0 6px;font-size:12px;color:#4a5159;font-weight:700}"
    ".flow{border:1px solid #e4e7eb;border-radius:8px;padding:12px 14px;margin:10px 0}"
    ".flow .ft{font-weight:700;font-size:13px;margin-bottom:4px}"
    "ol.steps{margin:6px 0 0;padding-left:22px}ol.steps li{margin:6px 0}"
    ".pill{display:inline-block;padding:1px 8px;border-radius:9px;color:#fff;font-size:11px;white-space:nowrap;margin-left:6px}"
    ".ag-hi{background:#1d8a4a}.ag-mid{background:#c98a00}.ag-lo{background:#8b929b}"
    ".tag{display:inline-block;background:#f0f3f7;border-radius:3px;padding:1px 7px;margin:1px 3px 1px 0;"
    "font-size:11px;color:#3d444c}"
    ".wt-dev{color:#2a78d6}.wt-off{color:#e08a00}.wt-site{color:#0e8c7a}.wt-col{color:#6c4fb8}"
    "@media(max-width:640px){.wrap{padding:12px}table.kv th{width:96px}td.agc{width:auto}}"
    "@media print{body{background:#fff}.card,.flow,.cand{break-inside:avoid}"
    ".top{background:#fff;color:#1c2b3a;border-bottom:2px solid #1c2b3a}}"
)
STYLE_HASH = "sha256-" + base64.b64encode(hashlib.sha256(CSS.encode("utf-8")).digest()).decode("ascii")
CSP_META = (f"default-src 'none'; style-src '{STYLE_HASH}'; img-src 'none'; font-src 'none'; "
            "base-uri 'none'; form-action 'none'")


def csp(*, sandbox=True):
    """이 리포트를 HTTP 로 보일 때 쓸 Content-Security-Policy — 스크립트·외부 자원 없음, <style> 은 해시로만."""
    return CSP_META + ("; frame-ancestors 'none'; sandbox" if sandbox else "")


# ── 읽기 ────────────────────────────────────────────────────────────────────────────────────
def _dirs(root=None):
    """(설치 폴더, report\\, data\\) — root 가 없으면 모듈 값(시험이 REP·DATA 를 바꿔 끼울 수 있다)."""
    if root:
        r = os.path.abspath(str(root))
        return r, os.path.join(r, "report"), os.path.join(r, "data")
    return ROOT, REP, DATA


def _json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _af32(d):
    return isinstance(d, dict) and d.get("product") == PRODUCT


def _rows(p):
    """CSV → dict 행 목록. 다른 도구가 CP949 로 저장한 파일도 읽는다(utf-8 실패 시 cp949)."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(p, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
        except (OSError, csv.Error):
            return []
    return []


def _fresh_refined(plain, refined):
    """정제본을 써도 되는가 — 원본보다 오래된 정제본은 쓰지 않는다(정제 없이 다시 분석한 경우 옛 숫자를 말하지 않게)."""
    if not os.path.exists(refined):
        return False
    try:
        return not os.path.exists(plain) or os.path.getmtime(refined) >= os.path.getmtime(plain)
    except OSError:
        return True


def _int(v, d=0):
    if isinstance(v, bool) or v is None:
        return d
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return d


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return None


def latest_tag(rep=None):
    """run_meta 에 "product":"AgentFinder32" 가 있는 가장 최근 tag — 없으면 ""."""
    rep = rep or _dirs()[1]
    best, bt = "", -1.0
    try:
        names = os.listdir(rep)
    except OSError:
        return ""
    for n in names:
        if not (n.startswith("run_meta_") and n.endswith(".json")):
            continue
        tag = n[len("run_meta_"):-len(".json")]
        p = os.path.join(rep, n)
        if not TAG_RX.match(tag) or not _af32(_json(p)):
            continue
        mt = _mtime(p) or 0.0
        if mt > bt:
            best, bt = tag, mt
    return best


def _period(meta, tag):
    """(시작, 끝) 'YYYY-MM-DD' — run_meta.period({from,to} 또는 [from,to]), 없으면 tag."""
    p = meta.get("period") if isinstance(meta, dict) else None
    a = b = None
    if isinstance(p, dict):
        a, b = p.get("from"), p.get("to")
    elif isinstance(p, (list, tuple)) and len(p) == 2:
        a, b = p
    a, b = str(a or "")[:10], str(b or "")[:10]
    if not (_DATE_RX.match(a) and _DATE_RX.match(b)):
        a, b = f"{tag[:4]}-{tag[4:6]}-{tag[6:8]}", f"{tag[9:13]}-{tag[13:15]}-{tag[15:17]}"
    return a, b


def _load(tag, root=None):
    """tag 의 결과 묶음 dict | None(AF32 결과가 아님). 표식 없는 JSON 은 없는 것으로 본다."""
    if not isinstance(tag, str) or not TAG_RX.match(tag):
        return None
    r, rep, data = _dirs(root)
    meta = _json(os.path.join(rep, f"run_meta_{tag}.json"))
    if not _af32(meta):
        return None

    def af(name):
        d = _json(os.path.join(rep, name))
        return d if _af32(d) else {}
    plain = os.path.join(rep, f"work_rows_{tag}.csv")
    refined = os.path.join(rep, f"work_rows_{tag}_refined.csv")
    rows = (_rows(refined) if _fresh_refined(plain, refined) else []) or _rows(plain)
    d0, d1 = _period(meta, tag)
    summ = _json(os.path.join(data, "outlook", "collect_summary.json"))
    sp = summ.get("period") if _af32(summ) else None
    if not (isinstance(sp, dict) and str(sp.get("from") or "")[:10] == d0 and str(sp.get("to") or "")[:10] == d1):
        summ = {}                         # 다른 기간을 모은 기록이면 이 결과의 건수가 아니다
    ag_path = os.path.join(rep, f"agentic_{tag}.json")
    return {"tag": tag, "root": r, "rep": rep, "meta": meta, "period": (d0, d1), "rows": [x for x in rows if isinstance(x, dict)],
            "pivots": af(f"pivots_{tag}.json"), "agentic": af(f"agentic_{tag}.json"), "workflow": af(f"workflow_{tag}.json"),
            "summary": summ, "agentic_mtime": _mtime(ag_path) if os.path.exists(ag_path) else None}


# ── 결과 다듬기(두 갈래 공용) ──────────────────────────────────────────────────────────────────
def _row_index(rows):
    idx = {}
    for r in rows:
        k = f"{str(r.get('Level 2') or '').strip()}\x1f{str(r.get('Level 3') or '').strip()}"
        idx.setdefault(k, []).append(r)
    return idx


def _cand_rows(n, idx):
    """후보의 근거 업무 행(keys '과제␟세부업무' 로 찾는다 — 같은 행은 한 번만)."""
    hit, seen = [], set()
    for k in n.get("keys") if isinstance(n.get("keys"), list) else []:
        a, _s, b = str(k).partition(KEY_SEP)
        for r in idx.get(f"{a.strip()}\x1f{b.strip()}", []):
            if id(r) not in seen:
                seen.add(id(r))
                hit.append(r)
    return hit


def _cand_count(n, hit):
    """근거건수 — 후보의 '근거건수' 칸 → 근거 업무 행의 근거건수 합 → evidence_rows. 모르면 None."""
    v = _int(n.get("근거건수"), None)
    if v is not None:
        return v
    if hit:
        return sum(_int(r.get("근거건수")) for r in hit)
    return _int(n.get("evidence_rows"), None)


def _cand_type(n, hit):
    """업무 유형 — 후보의 task_type, 없으면 근거 업무 행에서 가장 많은 유형."""
    t = str(n.get("task_type") or "").strip()
    if t or not hit:
        return t
    cnt = {}
    for r in hit:
        u = str(r.get("유형") or "").strip()
        if u:
            cnt[u] = cnt.get(u, 0) + 1
    return max(sorted(cnt), key=lambda k: cnt[k]) if cnt else ""


def _candidates(d):
    """[(후보 dict, 근거건수|None, 업무 유형)] — 근거건수 많은 순(같으면 파일 순)."""
    ag = d["agentic"]
    idx = _row_index(d["rows"])
    out = []
    for n in ag.get("new") if isinstance(ag.get("new"), list) else []:
        if not isinstance(n, dict) or not str(n.get("name") or "").strip():
            continue
        hit = _cand_rows(n, idx)
        out.append((n, _cand_count(n, hit), _cand_type(n, hit)))
    out.sort(key=lambda x: -(x[1] or 0))
    return out


def _flows(d):
    """[(흐름 dict, [단계 dict — 순서대로])] — 이름 있는 단계가 하나도 없는 흐름은 뺀다."""
    wf = d["workflow"]
    out = []
    for fl in wf.get("flows") if isinstance(wf.get("flows"), list) else []:
        if not isinstance(fl, dict):
            continue
        steps = [(i, s) for i, s in enumerate(fl.get("steps") or []) if isinstance(s, dict) and str(s.get("name") or "").strip()]
        if not steps:
            continue
        steps.sort(key=lambda x: (_int(x[1].get("order"), x[0] + 1), x[0]))
        out.append((fl, [s for _i, s in steps]))
    return out


def _agent(v):
    v = str(v or "").strip()
    return v if v in AGENT_CLASS else ""


# ── HTML 조각 ─────────────────────────────────────────────────────────────────────────────────
def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def _head(title, variant, tag=""):
    meta_tag = f"<meta name=\"af32-tag\" content=\"{esc(tag)}\">" if tag else ""
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{esc(CSP_META)}\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"referrer\" content=\"no-referrer\">"
            f"<meta name=\"product\" content=\"{esc(PRODUCT)}\"><meta name=\"af32-variant\" content=\"{esc(variant)}\">"
            f"{meta_tag}<title>{esc(title)}</title><style>{CSS}</style></head><body>")


def _worktype(t):
    t = str(t or "").strip()
    return f"<span class=\"tag {WORKTYPES[t]}\">{esc(t)}</span>" if t in WORKTYPES else (
        f"<span class=\"tag\">{esc(t)}</span>" if t else "")


def _pill(a):
    a = _agent(a)
    return f"<span class=\"pill {AGENT_CLASS[a]}\">Agent {esc(a)}</span>" if a else ""


def _counts(obj, labels, unit="건"):
    obj = obj if isinstance(obj, dict) else {}
    parts = [f"{lab} {_int(obj.get(k)):,}{unit}" for k, lab in labels if k in obj]
    return " · ".join(parts)


# ── local ─────────────────────────────────────────────────────────────────────────────────────
def _restricted_line(meta, cfg, root):
    r"""분석 개요의 '제한 고객 목록' 칸(HTML) — 지금 목록을 확인한 날·지문(sha256 앞 8자)과, 이 결과를 다른 목록으로 만들었으면
    알림. 이름은 싣지 않는다. 목록이 없거나 형식이 틀리면 그렇다고만."""
    import privacy
    try:
        rl = privacy.load_restricted(cfg, root)
    except (privacy.RestrictedListError, OSError, ValueError):
        return esc("목록이 없거나 형식이 틀립니다 — 분석과 공유를 하지 않습니다")
    out = esc(f"{rl.confirmed} 에 확인한 목록 · 지문 {str(rl.sha256)[:8]}")
    used = str((meta or {}).get("restricted_sha256") or "") if isinstance(meta, dict) else ""
    if used and used != rl.sha256:
        out += (f"<div class=\"warn\">{esc(f'이 결과는 다른 목록(지문 {used[:8]})으로 분석했습니다 — 다시 분석해야 공유할 수 있습니다')}"
                "</div>")
    elif not used:
        out += f"<div class=\"warn\">{esc('이 결과를 만든 목록을 알 수 없습니다 — 다시 분석해야 공유할 수 있습니다')}</div>"
    return out


def _overview(d, cfg, root):
    meta, summ = d["meta"], d["summary"]
    d0, d1 = d["period"]
    kv = [("목적", esc(consent.PURPOSE_LINE))]
    pv = f"{esc(d0)} ~ {esc(d1)}"
    cl = meta.get("clamped")
    if isinstance(cl, dict) and cl.get("clamped"):
        note = period.notice_text(cl, d0, d1, cfg)
        if note:
            pv += f"<div class=\"sub\">{esc(note)}</div>"
    kv.append(("분석 기간", pv + "<div class=\"sub\">오늘은 넣지 않고 어제까지 분석합니다</div>"))
    ch = summ.get("channels") if isinstance(summ.get("channels"), dict) else {}
    used = []
    for k, lab in CHANNEL_LABEL.items():
        c = ch.get(k) if isinstance(ch.get(k), dict) else None
        if c is None or (c.get("rc") is None and not _int(c.get("rows"))):
            continue
        s = f"{lab} {_int(c.get('rows')):,}건"
        if c.get("rc") not in (0, None):
            s += "(끝까지 읽지 못함)"
        used.append(s)
    if used:
        kv.append(("수집 경로", esc(" · ".join(used))
                   + "<div class=\"sub\">내 사서함의 메일·일정 목록만 읽습니다. 메일 본문·첨부·Teams 채팅은 읽지 않습니다</div>"))
    elif ch:
        kv.append(("수집 경로", "이 기간에 읽은 경로가 없습니다"))
    dom = [str(x) for x in (summ.get("internal_domains") or []) if str(x).strip()] if summ else []
    if dom:
        kv.append(("사내로 본 메일 도메인", esc(" · ".join(dom[:12]) + (" …" if len(dom) > 12 else ""))))
    if isinstance(summ.get("kept"), dict):
        kv.append(("모은 항목", esc(_counts(summ["kept"], KEPT_LABEL))))
    if isinstance(meta.get("counted"), dict):
        kv.append(("분석에 쓴 항목", esc(_counts(meta["counted"], KEPT_LABEL))))
    ex = meta.get("excluded") if isinstance(meta.get("excluded"), dict) else {}
    exc = summ.get("excluded") if isinstance(summ.get("excluded"), dict) else ex
    if exc:
        kv.append(("모을 때 뺀 항목", esc(_counts(exc, EXCL_COLLECT))
                   + "<div class=\"sub\">뺀 항목은 저장하지 않고 건수만 남깁니다</div>"))
    if any(k in ex for k, _l in EXCL_ANALYSE):
        kv.append(("분석할 때 뺀 항목", esc(_counts(ex, EXCL_ANALYSE))))
    kv.append(("제한 고객 목록", _restricted_line(meta, cfg, root)))
    try:
        dl = [f"이 리포트 파일 {retention.expiry_date(cfg, 'html')}"]
        if d["agentic_mtime"]:
            dl.append(f"분석 결과(후보·워크플로우) {retention.expiry_date(cfg, 'result', when=d['agentic_mtime'])}")
        days = {k: _int(afcfg.get(cfg, 'retention.' + k)) for k in ("rawDays", "intermediateDays")}
        kv.append(("자동 삭제", esc(" · ".join(dl))
                   + f"<div class=\"sub\">수집 자료는 마지막 수집 뒤 {days['rawDays']}일, 중간 자료는 {days['intermediateDays']}일이 "
                   "지나면 지웁니다. 화면 [내 데이터] 탭에서 지금 지울 수 있고, [모두 지우기(서버 사본 포함)]는 조직장 서버에 보낸 "
                   "사본까지 지웁니다</div>"))
    except (ValueError, TypeError, OSError):
        pass
    warns = [str(x) for x in (meta.get("config_warnings") or []) if str(x).strip()]
    if warns:
        kv.append(("설정 경고", esc(" · ".join(warns[:8]) + (" …" if len(warns) > 8 else ""))))
    return ("<div class=\"card\"><h2>1. 분석 개요</h2><table class=\"kv\">"
            + "".join(f"<tr><th>{esc(k)}</th><td>{v}</td></tr>" for k, v in kv) + "</table></div>")


def _local_candidates(d):
    ag = d["agentic"]
    h = ["<div class=\"card\"><h2>2. Agentic AI 전환 후보 <span class=\"state\">내 반복 업무에서 Agentic AI 로 바꿀 만한 "
         "과제 · 근거건수 = 근거가 된 내 업무의 메일·회의 수</span></h2>"]
    cands = _candidates(d)
    for n, cnt, tt in cands:
        h.append("<div class=\"cand\"><div class=\"nm\">" + esc(str(n.get("name")).strip()) + " " + _worktype(tt)
                 + (f"<span class=\"state\">근거 {cnt:,}건</span>" if cnt is not None else "") + "</div>"
                 + (f"<div class=\"ln\"><b>동작 로직</b>{esc(n.get('logic'))}</div>" if n.get("logic") else "")
                 + (f"<div class=\"ln\"><b>발굴 사유</b>{esc(n.get('reason'))}</div>" if n.get("reason") else "")
                 + "</div>")
    if not ag:
        h.append("<div class=\"note\">후보 발굴 결과가 없습니다 — 화면의 [Agentic AI 후보] 탭에서 만들 수 있습니다.</div>")
    elif not cands:
        h.append("<div class=\"note\">근거가 충분한 후보가 없습니다.</div>")
    if _int(ag.get("failed_chunks")):
        h.append(f"<div class=\"warn\">판정 묶음 {_int(ag.get('chunks')) or '?'}개 중 {_int(ag.get('failed_chunks'))}개를 "
                 "판정하지 못했습니다 — 후보가 실제보다 적을 수 있습니다</div>")
    if _int(ag.get("rule_rows")):
        h.append(f"<div class=\"note\">AI 판정을 기다리는 업무 {_int(ag.get('rule_rows'))}행은 아직 후보 찾기에 보내지 않았습니다.</div>")
    h.append("</div>")
    return "".join(h)


def _local_flows(d):
    flows = _flows(d)
    h = ["<div class=\"card\"><h2>3. 워크플로우와 Agent 가능성 <span class=\"state\">업무의 단계 → 단계별 Agent 가능성"
         "(상·중·하)</span></h2>"]
    prev = None
    for fl, steps in flows:
        l1 = str(fl.get("level1") or "").strip() or "업무 영역 미분류"
        if l1 != prev:
            h.append(f"<div class=\"area\">{esc(l1)}</div>")
            prev = l1
        pj = str(fl.get("project") or "").strip()
        det = str(fl.get("detail") or "").strip()
        title = det or str(fl.get("model") or "").strip() or pj or "업무"
        h.append("<div class=\"flow\"><div class=\"ft\">" + esc(title)
                 + (f" <span class=\"state\">{esc(pj)}</span>" if pj and det else "") + "</div>"
                 + (f"<div class=\"sub\">{esc(fl.get('summary'))}</div>" if fl.get("summary") else "")
                 + "<table><tr><th></th><th>단계</th><th>입력 → 출력</th><th>Agent 가능성</th></tr>")
        for i, s in enumerate(steps, 1):
            io_txt = " → ".join(x for x in (str(s.get("input") or "").strip(), str(s.get("output") or "").strip()) if x)
            h.append(f"<tr><td class=\"ord\">{i}</td><td><b>{esc(s.get('name'))}</b></td><td>{esc(io_txt)}</td>"
                     f"<td class=\"agc\">{_pill(s.get('agent')) or DASH}"
                     + (f"<div class=\"sub\">{esc(s.get('agent_how'))}</div>" if s.get("agent_how") else "")
                     + "</td></tr>")
        h.append("</table></div>")
    if not flows:
        h.append("<div class=\"note\">워크플로우 분석 결과가 없습니다 — 화면의 [워크플로우] 탭에서 만들 수 있습니다.</div>")
    if _int(d["workflow"].get("failed_chunks")):
        h.append("<div class=\"warn\">일부 업무의 워크플로우를 만들지 못했습니다 — 다시 실행하면 채웁니다</div>")
    h.append("</div>")
    return "".join(h)


def _local_taxonomy(d):
    rows = d["rows"]
    bw = d["pivots"].get("by_worktype") if isinstance(d["pivots"].get("by_worktype"), dict) else {}
    h = ["<div class=\"card\"><h2>4. 업무 분류 <span class=\"state\">업무 영역(Level 1) / 과제(Level 2) / 세부업무(Level 3) · "
         "근거건수 많은 순</span></h2>"]
    if bw:
        h.append("<div>" + " ".join(_worktype(k) + f"<span class=\"dim\">{_int(v):,}건</span>"
                                    for k, v in sorted(bw.items(), key=lambda kv: -_int(kv[1]))) + "</div>")
    if rows:
        groups = {}
        for r in rows:
            groups.setdefault(str(r.get("Level 1") or "").strip() or "업무 영역 미분류", []).append(r)
        order = sorted(groups, key=lambda g: (-sum(_int(r.get("근거건수")) for r in groups[g]), g))
        h.append("<table><tr><th>업무분류</th><th>과제</th><th>세부업무</th><th class=\"num\">근거건수</th></tr>")
        for g in order:
            rs = sorted(groups[g], key=lambda r: -_int(r.get("근거건수")))
            h.append(f"<tr class=\"l1\"><td colspan=\"3\">{esc(g)}</td>"
                     f"<td class=\"num\">{sum(_int(r.get('근거건수')) for r in rs):,}</td></tr>")
            for r in rs:
                h.append(f"<tr><td>{_worktype(r.get('유형'))}</td><td>{esc(r.get('Level 2'))}</td>"
                         f"<td><b>{esc(r.get('Level 3'))}</b>"
                         + (f"<div class=\"sub\">{esc(r.get('상세설명'))}</div>" if r.get("상세설명") else "")
                         + f"</td><td class=\"num\">{_int(r.get('근거건수')):,}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class=\"note\">업무 분류 결과가 없습니다.</div>")
    h.append("</div>")
    return "".join(h)


def _local_common(d):
    common = [c for c in (d["pivots"].get("common") or []) if isinstance(c, dict) and str(c.get("name") or "").strip()]
    h = ["<div class=\"card\"><h2>5. 공통 업무 <span class=\"state\">여러 과제에서 되풀이되는 업무 — 표준화·자동화를 먼저 볼 "
         "후보</span></h2>"]
    if common:
        h.append("<table><tr><th>업무</th><th>업무분류</th><th class=\"num\">근거건수</th></tr>")
        for c in sorted(common, key=lambda c: -_int(c.get("근거건수"))):
            h.append(f"<tr><td><b>{esc(c.get('name'))}</b></td><td>{_worktype(c.get('worktype'))}</td>"
                     f"<td class=\"num\">{_int(c.get('근거건수')):,}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class=\"note\">여러 과제에서 되풀이되는 업무가 없습니다.</div>")
    h.append("</div>")
    return "".join(h)


def _build_local(d, cfg):
    d0, d1 = d["period"]
    return "".join([
        _head(f"{LOCAL_TITLE} {d0}~{d1}", "local", d["tag"]),
        f"<div class=\"top\">{esc(LOCAL_BANNER)}</div><div class=\"wrap\">",
        f"<h1>{esc(LOCAL_TITLE)}</h1>",
        f"<div class=\"meta\">{esc(lmname.DISPLAY_TITLE)} · 기간 {esc(d0)} ~ {esc(d1)} · 만든 날 {time.strftime('%Y-%m-%d')}</div>",
        f"<div class=\"purpose\">{esc(consent.PURPOSE_LINE)}</div>",
        _overview(d, cfg, d["root"]),
        _local_candidates(d),
        _local_flows(d),
        _local_taxonomy(d),
        _local_common(d),
        "<div class=\"note\">이 리포트는 내 메일·일정 목록에서 업무 유형과 반복 업무를 찾은 결과입니다. 근거건수는 업무별 메일·회의 "
        "수이고, 시각과 사람 이름은 담지 않습니다. 사람을 평가하거나 업무량을 견주는 데 쓰지 않습니다.</div>",
        "</div></body></html>",
    ])


# ── share ─────────────────────────────────────────────────────────────────────────────────────
def _typed(v):
    """공유 탭에 적은 이름·파트 — 제어 문자를 빼고 공백을 줄여 TYPED_MAX 자까지(내용은 바꾸지 않는다)."""
    s = re.sub(r"[\x00-\x1f\x7f  ]", " ", str(v or ""))
    return re.sub(r"\s+", " ", s).strip()[:TYPED_MAX]


def _id_key(root):
    try:
        return bytes.fromhex(install.salt(root))
    except (OSError, ValueError, KeyError, TypeError):
        return b"af32-share-item-id"


def _mkid(key, prefix, parts, n):
    msg = "\x1f".join(str(p or "") for p in parts).encode("utf-8")
    return prefix + hmac.new(key, msg + b"\x1e" + str(n).encode("ascii"), hashlib.sha256).hexdigest()[:10]


def _scrubber(cfg, root, tag):
    import privacy
    return privacy.ShareScrubber(cfg, root=root, tag=tag)


def _fixed_or_scrub(v, fixed, sc):
    v = str(v or "").strip()
    if v in fixed:
        return v
    return sc.text(v).strip() if v else ""


def _share_items(d, sc):
    """공유본에 실릴 항목(가린 글) — share_items 와 build(variant="share")가 같은 것을 쓴다."""
    key = _id_key(d["root"])
    items, seen = [], set()

    def uid(prefix, parts):
        n = 0
        while True:
            i = _mkid(key, prefix, parts, n)
            if i not in seen:
                seen.add(i)
                return i
            n += 1
    for n, _cnt, tt in _candidates(d):
        raw = (str(n.get("name") or "").strip(), str(n.get("logic") or "").strip(), str(n.get("reason") or "").strip())
        items.append({"id": uid("c-", ("c",) + raw), "kind": "candidate",
                      "name": sc.text(raw[0]).strip(), "logic": sc.text(raw[1]).strip() if raw[1] else "",
                      "reason": sc.text(raw[2]).strip() if raw[2] else "",
                      "task_type": _fixed_or_scrub(tt, WORKTYPES, sc)})
    for fl, steps in _flows(d):
        fkey = (str(fl.get("model") or ""), str(fl.get("project") or ""), str(fl.get("detail") or ""))
        fid = uid("f-", ("f",) + fkey)
        for j, s in enumerate(steps):
            nm = str(s.get("name") or "").strip()
            how = str(s.get("agent_how") or "").strip()
            items.append({"id": uid("s-", ("s",) + fkey + (str(j), nm)), "kind": "step", "flow": fid,
                          "name": sc.text(nm).strip(), "agent": _agent(s.get("agent")),
                          "agent_how": sc.text(how).strip() if how else ""})
    return items


def share_items(tag, *, scrubber=None, root=None, cfg=None):
    """미리보기 항목(가린 글 그대로) → list | None(AF32 결과가 아님). scrubber 가 없으면 이 tag 로 만든다."""
    d = _load(tag, root)
    if d is None:
        return None
    if scrubber is None:
        if cfg is None:
            cfg, _w = afcfg.load_effective(d["root"])
        scrubber = _scrubber(cfg, d["root"], tag)
    return _share_items(d, scrubber)


def _ym(s):
    return str(s or "")[:7]


def share_period(tag, *, root=None):
    """공유본의 기간 'YYYY-MM~YYYY-MM' — AF32 결과가 아니면 ""."""
    d = _load(tag, root)
    if d is None:
        return ""
    d0, d1 = d["period"]
    return f"{_ym(d0)}~{_ym(d1)}"


def _build_share(d, sc, include, owner, function):
    items = _share_items(d, sc)
    if include is not None:
        keep = {include} if isinstance(include, str) else {str(x) for x in include}
        items = [it for it in items if it["id"] in keep]
    cands = [it for it in items if it["kind"] == "candidate"]
    flows = {}
    for it in items:
        if it["kind"] == "step":
            flows.setdefault(it["flow"], []).append(it)
    d0, d1 = d["period"]
    who, part = _typed(owner), _typed(function)
    h = [_head(f"{who} — {SHARE_TITLE}" if who else SHARE_TITLE, "share"),
         f"<div class=\"top\">{esc(lmname.DISPLAY_TITLE)} · 조직장 공유본</div><div class=\"wrap\">",
         "<h1>" + (esc(who) if who else esc(SHARE_TITLE)) + (f"<span class=\"sub\">{esc(part)}</span>" if part else "") + "</h1>",
         f"<div class=\"meta\">기간 {esc(_ym(d0))}~{esc(_ym(d1))}</div>",
         f"<div class=\"purpose\">{esc(SHARE_PURPOSE)}.</div>",
         "<div class=\"card\"><h2>Agentic AI 전환 후보</h2>"]
    for c in cands:
        h.append("<div class=\"cand\"><div class=\"nm\">" + esc(c["name"]) + " " + _worktype(c["task_type"]) + "</div>"
                 + (f"<div class=\"ln\"><b>동작 로직</b>{esc(c['logic'])}</div>" if c["logic"] else "")
                 + (f"<div class=\"ln\"><b>발굴 사유</b>{esc(c['reason'])}</div>" if c["reason"] else "")
                 + "</div>")
    if not cands:
        h.append("<div class=\"note\">싣는 후보가 없습니다.</div>")
    h.append("</div><div class=\"card\"><h2>워크플로우와 Agent 가능성</h2>")
    for steps in flows.values():
        h.append("<div class=\"flow\"><div class=\"ft\">업무 흐름</div><ol class=\"steps\">")
        for s in steps:
            h.append(f"<li><b>{esc(s['name'])}</b>{_pill(s['agent'])}"
                     + (f"<div class=\"sub\">{esc(s['agent_how'])}</div>" if s["agent_how"] else "") + "</li>")
        h.append("</ol></div>")
    if not flows:
        h.append("<div class=\"note\">싣는 워크플로우가 없습니다.</div>")
    h.append(f"</div><div class=\"note\">{esc(SHARE_MASK_NOTE)}</div></div></body></html>")
    return "".join(h)


# ── 진입점 ────────────────────────────────────────────────────────────────────────────────────
def build(tag, *, variant="local", scrubber=None, include=None, owner=None, function=None, root=None, cfg=None):
    """개인 리포트 HTML → str | None(tag 가 AF32 결과가 아님). variant 는 "local" 또는 "share"(머리말 참고).
    share 에서 scrubber 가 없으면 core\\privacy.ShareScrubber(cfg, root, tag) 를 만든다 — 제한 고객 목록이 없으면
    privacy.RestrictedListError(종료 코드 4 로 다룬다)."""
    if variant not in VARIANTS:
        raise ValueError(f"variant 는 {' · '.join(VARIANTS)} 중 하나입니다: {variant!r}")
    d = _load(tag, root)
    if d is None:
        return None
    if cfg is None:
        cfg, _w = afcfg.load_effective(d["root"])
    if variant == "local":
        return _build_local(d, cfg)
    if scrubber is None:
        scrubber = _scrubber(cfg, d["root"], tag)
    return _build_share(d, scrubber, include, owner, function)


def out_path(tag, root=None):
    r"""local 리포트 경로 report\개인리포트_<tag>.html."""
    return os.path.join(_dirs(root)[1], f"{OUT_PREFIX}{tag}.html")


def _write_atomic(path, text):
    """같은 폴더의 임시 파일에 쓴 뒤 바꿔 끼운다(쓰다 만 파일을 남기지 않는다)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def _arg(argv, flag):
    if flag not in argv:
        return None
    i = argv.index(flag)
    return argv[i + 1] if i + 1 < len(argv) else ""


def _fail(rc, code, msg, tag="", reason=""):
    print(f"[report] {msg}")
    res = {"ok": False, "code": code, "msg": msg, "html": None, "tag": tag}
    if reason:
        res["reason"] = reason                    # 시작 확인이 막은 까닭(other_user | withdrawn) — 단계 CLI 와 같은 키
    print(json.dumps(res, ensure_ascii=False))
    return rc


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = ROOT
    msg = install.startup_check(root)
    if msg:
        return _fail(4, "setup_refused", msg)
    cfg, _w = afcfg.load_effective(root)
    try:
        consent.require(root, cfg)
    except consent.ConsentRequired as e:
        return _fail(4 if getattr(e, "code", 3) == 4 else 3, "no_consent", e.message, reason=e.reason)
    variant = _arg(argv, "--variant")
    if variant not in (None, "local"):
        return _fail(1, "bad_variant", "공유본은 화면의 [공유] 탭에서만 만듭니다 — 이 명령은 이 PC 에서 보는 개인 리포트만 만듭니다")
    d0, d1 = _arg(argv, "--from"), _arg(argv, "--to")
    if d0 or d1:
        if not (d0 and d1):
            return _fail(1, "bad_period", "--from 과 --to 를 함께 주세요 (YYYY-MM-DD)")
        try:
            tag = period.tag_of(d0, d1)
        except ValueError as e:
            return _fail(1, "bad_period", str(e))
    else:
        tag = latest_tag()
        if not tag:
            return _fail(1, "no_result", "분석 결과가 없습니다 — 먼저 [분석 실행]을 하세요")
    doc = build(tag, variant="local", cfg=cfg)
    if not doc:
        return _fail(1, "no_result", f"run_meta_{tag}.json 이 없거나 {PRODUCT} 분석 결과가 아닙니다", tag)
    path = out_path(tag)
    try:
        _write_atomic(path, doc)
    except OSError as e:
        return _fail(1, "write_failed", f"리포트를 저장하지 못했습니다({type(e).__name__})", tag)
    print(f"[report] → {path}")
    print(json.dumps({"ok": True, "html": path, "tag": tag}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))   # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
