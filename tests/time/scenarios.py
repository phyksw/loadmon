# -*- coding: utf-8 -*-
r"""WP-19 시나리오 입력 — W §9 의 83개 시나리오(참조 `design\worktime\scenarios.py` 이식) + 저장 행 어댑터.

- 시나리오는 참조 구현과 같은 중립 작성기 `W`(시각 = 근무 시간대 'YYYY-MM-DD HH:MM')로 쓴다.
- `to_inputs(w)` 가 그것을 **정제 후 저장 행 모양**(계약 §3.1~§3.3 열 + `load_evidence` 파생 열 `act`·
  `subject_tokens`)으로 바꾼다: UTC `ts_utc` + `+09:00`, 가명 키(시험 전용 HMAC — 실제 키링 아님), 문서군 키 =
  `"d" + HMAC("n:" + fam(이름))`. 레코드 id 는 참조 구현의 동률 순서(메시지 id 사전순)를 지키는 16hex 다.
- 아직 없는 다른 WP 의 함수는 계약 시그니처대로 가짜를 넣는다(`install_fakes` — 실물 파일이 있고 import 되면 실물):
  `lm27.privacy.keys.doc_fam`(WP-11, W §4.1 규칙) · `lm27.catalog.cat_of`(WP-14, 최소 카탈로그) ·
  `lm27.normalize.absence.meet_category`(WP-18).
- 자리표시자만 쓴다(사람 P1~P40·김철수 계열 대화방, 과제A~J, 고객사A). 실데이터 없음.

이 파일은 시험 자료다(unittest 가 모으지 않는 이름). WP-20 도 읽기만 한다.
"""
from __future__ import annotations

import copy as _copy
import hashlib
import hmac
import importlib
import json
import re
import sys
import types
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "wp19" / "golden.json"
CAL_PATH = ROOT / "config" / "calendar.json"
REGISTRY_PATH = ROOT / "config" / "settings_registry.json"
TZ_MIN = 540
TAG_CODES = {"정규": "regular", "연장": "extended", "야간": "night", "휴일": "holiday"}
_TEST_KEY = b"lm27-wp19-synthetic-test-key"          # 시험 전용(키링 아님)

# ───────────────────────────── 가짜(아직 없는 WP 의 계약 함수) ─────────────────────────────
# 계약 v1.2 §0.7 C16(§4.3): 낱말·판 꼬리는 앞에 구분자가 있을 때만, '(n)' 은 구분자 없이도 · 날짜 숫자 꼬리는 남긴다
_FAM_TAIL = re.compile(r"(?:[\s_\-]+(?:복사본|사본|수정본?|copy|최종|final|v\d{1,3}(?:\.\d{1,3}){0,2}|rev\.?\s?\d{1,3}"
                       r"|r\d{1,3})|\s?\(\d{1,3}\))$", re.I)
_FAM_SEP = re.compile(r"[\s_\-.]+")
MINI_CATALOG = {"ansys": "해석", "creo": "CAD", "vivado": "FPGA", "zemax": "광학", "notepad": "사무"}


def fake_doc_fam(name: str) -> str:
    """계약 §4.3 · C16 문서군 정규화(가짜 — WP-11 `lm27.privacy.keys.doc_fam` 의 계약 규칙 그대로: 경로면 기본 이름,
    확장자 제거, 꼬리 반복 제거(최대 5회), 비면 원래 이름, 구분자 묶음 → '_')."""
    if not name:
        return ""
    x = re.split(r"[\\/]", unicodedata.normalize("NFKC", name))[-1].lower().strip()
    x = re.sub(r"\.(gz|zip|7z)$", "", x)
    y = re.sub(r"\.(prt|asm|drw)\.\d{1,4}$", "", x)
    x = (y if y != x else re.sub(r"\.[a-z0-9]{1,5}$", "", x)).strip()
    base = x
    for _ in range(5):
        x2 = _FAM_TAIL.sub("", x)
        if x2 == x:
            break
        x = x2
    if not _FAM_SEP.sub("", x):
        x = base
    return _FAM_SEP.sub("_", x).strip("_")


def fake_cat_of(app_id: str) -> str:
    """최소 카탈로그(가짜 — WP-14 `lm27.catalog.cat_of`)."""
    return MINI_CATALOG.get(app_id, "")


def fake_meet_category(row) -> str:
    """일정 근태 범주(가짜 — WP-18 `lm27.normalize.absence.meet_category`): abs_hint·장소로만."""
    hint = row.get("abs_hint")
    if hint == "trip":
        return "trip"
    if hint in ("leave", "half", "half_am", "half_pm", "sick"):
        return "leave"
    if hint == "edu":
        return "edu"
    if row.get("location_class") == "external":
        return "offsite"
    return ""


FAKES = (("lm27.privacy.keys", ("lm27", "privacy", "keys.py"), "doc_fam", fake_doc_fam),
         ("lm27.catalog", ("lm27", "catalog.py"), "cat_of", fake_cat_of),
         ("lm27.normalize.absence", ("lm27", "normalize", "absence.py"), "meet_category", fake_meet_category))
INSTALLED: dict[str, str] = {}
FAKE_NOTES: list[str] = []


def _real_usable(modname: str, rel: tuple, attr: str) -> bool:
    if not ROOT.joinpath(*rel).is_file():
        return False
    try:
        mod = importlib.import_module(modname)
    except Exception as e:     # 다른 WP 실물이 아직 불완전 — 가짜로 대체하고 기록한다(시험 전용)
        FAKE_NOTES.append(f"{modname}: 실물 import 실패({type(e).__name__}) — 가짜 사용")
        return False
    return callable(getattr(mod, attr, None))


def _install(modname: str, attr: str, fn) -> None:
    parent, _, leaf = modname.rpartition(".")
    if parent not in sys.modules:
        try:
            importlib.import_module(parent)
        except Exception:      # 부모 패키지가 아직 없다 — 빈 가짜 패키지
            pm = types.ModuleType(parent)
            pm.__path__ = []
            sys.modules[parent] = pm
            gp, _, pl = parent.rpartition(".")
            setattr(sys.modules[gp], pl, pm)
    m = types.ModuleType(modname)
    setattr(m, attr, fn)
    m.LM27_FAKE = True
    sys.modules[modname] = m
    setattr(sys.modules[parent], leaf, m)


def install_fakes() -> dict[str, str]:
    """없는 계약 함수를 가짜로 채운다(멱등). 반환 {모듈: 'real'|'fake'}."""
    for modname, rel, attr, fn in FAKES:
        if modname in INSTALLED:
            continue
        if _real_usable(modname, rel, attr):
            INSTALLED[modname] = "real"
            continue
        _install(modname, attr, fn)
        INSTALLED[modname] = "fake"
    return dict(INSTALLED)


install_fakes()

from lm27.config import load_config                    # noqa: E402
from lm27.time.calendar import Calendar, build_days     # noqa: E402
from lm27.time.envelope import build_envelope           # noqa: E402
from lm27.time.evidence import normalize                # noqa: E402
from lm27.time.tokens import fam, fam_key               # noqa: E402

_CAL = None


def calendar() -> Calendar:
    global _CAL
    if _CAL is None:
        _CAL = Calendar(CAL_PATH)
    return _CAL


def base_cfg():
    """선언 기본값만(개인 config.json 은 읽지 않는다 — 없는 경로를 준다)."""
    return load_config(registry_path=REGISTRY_PATH, config_path=ROOT / "tests" / "fixtures" / "wp19" / "_none.json")


# ───────────────────────────── 중립 작성기(참조 구현과 같은 API) ─────────────────────────────
class W:
    """중립 시나리오. 시각은 'YYYY-MM-DD HH:MM'(근무 시간대 로컬)."""

    def __init__(self, name, d0, d1, as_of, note=""):
        self.name, self.d0, self.d1, self.as_of, self.note = name, d0, d1, as_of, note
        self.samples, self.pcon, self.msgs, self.meets, self.docs = [], [], [], [], []
        self.comps, self.commits, self.manual, self.leaves = [], [], [], {}
        self.coverage = {}            # (date_iso, axis) → status
        self.cfg = {}
        self.shared_docs = set()

    def copy(self) -> W:
        """사본(목록·사전은 새로, 값은 불변 — 시험이 목록을 바꾸거나 덧붙여도 원본이 그대로)."""
        n = _copy.copy(self)
        for a in ("samples", "pcon", "msgs", "meets", "docs", "comps", "commits", "manual"):
            setattr(n, a, [dict(x) for x in getattr(self, a)])
        n.leaves, n.coverage, n.cfg, n.shared_docs = dict(self.leaves), dict(self.coverage), dict(self.cfg),             set(self.shared_docs)
        return n

    def samp(self, pc, a, b, cls="browser", doc="", state="active", priv="work", idle=None, app=None):
        self.samples.append({"pc": pc, "a": a, "b": b, "cls": cls, "doc": doc, "state": state, "priv": priv,
                             "idle": idle, "app": app or cls})
        return self

    def on(self, pc, a, b):
        self.pcon.append({"pc": pc, "a": a, "b": b})
        return self

    def msg(self, t, dir, act, conv, peer="P1", ch="mail", prec="exact", direct=True, atts=(), tokens=(),
            n_part=2, flags=(), key=None, proj=None):
        self.msgs.append({"t": t, "dir": dir, "act": act, "conv": conv, "peer": peer, "ch": ch, "prec": prec,
                          "direct": direct, "atts": tuple(atts), "tokens": tuple(tokens), "n_part": n_part,
                          "flags": tuple(flags), "key": key or f"k{len(self.msgs) + 1}",
                          "id": f"m{len(self.msgs) + 1}", "proj": proj})
        return self

    def meet(self, a, b, organizer="P1", attendees=("P1", "ME"), tokens=(), status="accepted", n_att=None,
             online=False, personal=False, all_day=False, category=""):
        self.meets.append({"a": a, "b": b, "organizer": organizer, "attendees": tuple(attendees),
                           "tokens": tuple(tokens), "status": status, "n_att": n_att or len(attendees),
                           "online": online, "personal": personal, "all_day": all_day, "category": category,
                           "id": f"mt{len(self.meets) + 1}"})
        return self

    def doc(self, t, kind, name, pc="PC1", autosave=False, folder="", other=False, proj=None):
        self.docs.append({"t": t, "kind": kind, "doc": name, "pc": pc, "autosave": autosave, "folder": folder,
                          "other": other, "proj": proj})
        return self

    def comp(self, pc, a, b, app, doc):
        self.comps.append({"pc": pc, "a": a, "b": b, "app": app, "doc": doc})
        return self

    def commit(self, t, repo, pc="PC1", tokens=()):
        self.commits.append({"t": t, "repo": repo, "pc": pc, "tokens": tuple(tokens)})
        return self

    def man(self, kind, a=None, b=None, hours=None, ref="", tokens=(), day=None, key=None):
        """kind: work|offsite|instr|report|absence|exclude|attended|must_link|cannot_link."""
        self.manual.append({"kind": kind, "a": a, "b": b, "hours": hours, "ref": ref, "tokens": tuple(tokens),
                            "day": day, "key": key})
        return self

    def leave(self, day, kind):
        self.leaves[day] = kind
        return self


def office_day(n, pc, day, segs=(), fill="browser", after=None, lunch="locked"):
    """표준 근무일 샘플러: 09~12·13~18 능동(segs 로 덮어씀), 12~13 잠금, PC 가동 08:50~18:05."""
    cover = []
    for a, b, cls, doc in segs:
        n.samp(pc, f"{day} {a}", f"{day} {b}", cls, doc)
        cover.append((a, b))
    for a, b in (("09:00", "12:00"), ("13:00", "18:00")):
        cur = a
        for x, y in sorted(cover):
            if y <= cur or x >= b:
                continue
            if x > cur:
                n.samp(pc, f"{day} {cur}", f"{day} {x}", fill, "")
            cur = max(cur, y)
        if cur < b:
            n.samp(pc, f"{day} {cur}", f"{day} {b}", fill, "")
    if lunch:
        n.samp(pc, f"{day} 12:00", f"{day} 13:00", "other", "", state=lunch)
    n.on(pc, f"{day} 08:50", f"{day} 18:05" if not after else after[0])
    if after:
        n.samp(pc, f"{day} 18:00", after[0], "other", "", state=after[1])
    return n


# ───────────────────────────── 어댑터: W → 저장 행 · 프로필 · 꼬리표 ─────────────────────────────
@cache
def _h(purpose: str, value: str, n: int) -> str:
    return hmac.new(_TEST_KEY, f"{purpose}|{value}".encode(), hashlib.sha256).hexdigest()[:n]


def who(p: str) -> str:
    return "w" + _h("person", p, 16)


def msg_key(k: str) -> str:
    return "m" + _h("msg", k, 24)


def cal_key(k: str) -> str:
    return "e" + _h("cal", k, 24)


def thread_key(conv: str) -> str:
    return "t" + _h("thread", conv, 16)


def chat_key(conv: str) -> str:
    return "h" + _h("chat", conv, 16)


@cache
def doc_key(name: str) -> str:
    return "d" + _h("doc", "n:" + fam(name), 16)


def repo_key(repo: str) -> str:
    return "r" + _h("repo", repo.lower(), 16)


def dir_key(folder: str) -> str:
    return "s" + _h("dir", folder, 16)


def pc_id(pc: str) -> str:
    return "pc_" + hashlib.sha256(("LM27.pc|" + pc.lower()).encode("utf-8")).hexdigest()[:16]


@cache
def utc(local: str) -> str:
    dt = datetime.strptime(local, "%Y-%m-%d %H:%M") - timedelta(minutes=TZ_MIN)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def as_of_utc(local: str) -> datetime:
    return (datetime.strptime(local, "%Y-%m-%d %H:%M") - timedelta(minutes=TZ_MIN)).replace(tzinfo=timezone.utc)


CLS_TO_APP = {   # 참조 Samp.cls → (저장 app_class, fg_exe)  (X-201 의 역)
    "office": ("office", "winword.exe"), "cad": ("cad", "acad.exe"), "cae": ("sim", "fluent.exe"),
    "sim": ("sim", "fluent.exe"), "eda": ("eda", "orcad.exe"), "ide": ("ide", "code.exe"),
    "eng": ("other", "ansys.exe"), "browser": ("browser", "msedge.exe"), "mail": ("mail_work", "outlook.exe"),
    "chat": ("chat_work", "ms-teams.exe"), "meet": ("meeting", "ms-teams.exe"), "remote": ("remote", "mstsc.exe"),
    "explorer": ("system", "explorer.exe"), "system": ("system", "svchost.exe"), "other": ("other", "other.exe"),
}
STATUS_RESP = {"accepted": 3, "organizer": 1, "tentative": 2, "declined": 4, "none": 0, "cancelled": 3}
DOC_OP = {"save": "modify", "create": "create", "open": "open", "export": "modify", "result": "modify"}
CFG_RENAME = {"privacy.time.regular_private_run_min": "privacy.time.regularPrivateRunMin",
              "privacy.time.offhours_private_break_min": "privacy.time.offhoursPrivateBreakMin",
              "time.envelope.fileBurstN": "pc.files.burstN", "time.queue.parallelMax": "time.queue.parallelSuspect"}


def map_cfg(over: dict) -> dict:
    """참조 설정 키 → 계약 레지스트리 키(§5.4 개명). preWindowMin 사전은 6개 키로 나눈다."""
    out = {}
    for k, v in (over or {}).items():
        if k == "time.envelope.preWindowMin":
            for sub, x in v.items():
                out[f"time.envelope.preWindowMin.{sub}"] = x
            continue
        if k in ("time.window.weekdays", "mm.stdDayMin", "mm.todayFraction"):
            continue                                   # 폐지 키(계약 §5.4) — 달력 값만
        out[CFG_RENAME.get(k, k)] = list(v) if isinstance(v, tuple) else v
    return out


def _base(kind: str, src: str, pc: str, local: str, prec: str) -> dict:
    return {"kind": kind, "src": src, "pc_id": pc_id(pc), "ts_utc": utc(local), "ts_local_offset": "+09:00",
            "ts_precision": prec, "act": "", "act_cues": [], "confidence": 1.0, "observed_at": utc(local),
            "rules_ver": "2026.10.0", "kid": "k00000000", "san": {}, "priv_score": None, "priv_class": "work",
            "priv_why": []}


def _ext(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def to_inputs(w: W, cfg=None) -> tuple[list[dict], dict, datetime, dict, dict]:
    """W → (저장 행 목록, profile, as_of, HierTags, 설정 덮어쓰기)."""
    cfg = cfg or base_cfg()
    rows: list[tuple[str, str, dict]] = []          # (그룹, 동률 정렬 키, 행)
    tags = {"msg": {}, "fam": {}, "shared_fams": set()}
    for i, s in enumerate(w.samples):
        if s["state"] == "sleep":
            r = _base("pc_session", "pc.events", s["pc"], s["a"], "minute")
            r.update(ts_end=utc(s["b"]), app_id=None, session_state="active", idle_sec=None, layer="L0",
                     event_class="sleep")
            rows.append(("4", f"{i:08d}", r))
            continue
        ac, exe = CLS_TO_APP.get(s["cls"], ("other", "other.exe"))
        r = _base("pc_session", "pc.sampler", s["pc"], s["a"], "exact")
        state, idle = s["state"], s["idle"]
        if state == "idle":
            state, idle = "active", 3600 if idle is None else max(int(idle), 3600)
        app = s["app"] if s["app"] else s["cls"]
        if s["cls"] == "eng" and app == "eng":
            app = "ansys"
        r.update(ts_end=utc(s["b"]), app_id=app, fg_exe=exe, app_class=ac,
                 title_masked=(f"{s['doc']} - 앱" if s["doc"] else None), doc_key=doc_key(s["doc"]) if s["doc"] else None,
                 site_class=None, session_state=state, idle_sec=idle, layer="L3", event_class=None,
                 priv_class=s["priv"])
        rows.append(("4", f"{i:08d}", r))
    for i, p in enumerate(w.pcon):
        r = _base("pc_session", "pc.events", p["pc"], p["a"], "minute")
        r.update(ts_end=utc(p["b"]), app_id=None, session_state="active", idle_sec=None, layer="L1",
                 event_class="logon")
        rows.append(("5", f"{i:08d}", r))
    for m in w.msgs:
        fl = set(m["flags"])
        kind = "mail" if m["ch"] == "mail" else "teams"
        src = {"exact": "mail.com", "minute": "mail.com", "date": "mail.owa", "summary": "mail.copilot",
               "unknown": "mail.com"}[m["prec"]]
        if kind == "teams":
            src = {"date": "teams.web", "summary": "teams.copilot"}.get(m["prec"], "teams.uia")
        r = _base(kind, src, "PC1", m["t"], m["prec"])
        mk = msg_key(m["key"])
        r.update(act=m["act"], msg_key=mk, subject_tokens=list(m["tokens"]), n_participants=m["n_part"],
                 counterpart_keys=[who(m["peer"])])
        if "private" in fl:
            r["priv_class"] = "private"
        elif "social" in fl:
            r["priv_class"] = "social"
        rf = {}
        if "utc" in fl:
            rf["utc_suspect"] = True
        if kind == "mail":
            for f in ("cc", "bulk", "deferred", "meeting_response", "ad"):
                if f in fl:
                    rf[f] = True
            if "notice" in fl:
                rf["teams_notice"] = True
            r.update(direction=m["dir"], thread_key=thread_key(m["conv"]), box="sent" if m["dir"] == "out" else "inbox",
                     sender_key=who(m["peer"]) if m["dir"] == "in" else "self",
                     rcv="na" if m["dir"] == "out" else ("to" if m["direct"] else "cc"),
                     attach_keys=[doc_key(x) for x in m["atts"]], attach_names_masked=list(m["atts"]),
                     subject_masked=" ".join(m["tokens"]))
        else:
            r.update(direction="sent" if m["dir"] == "out" else "received", chat_key=chat_key(m["conv"]),
                     chat_type="1:1" if m["direct"] else "group", thread_key=None,
                     author_key=who(m["peer"]) if m["dir"] == "in" else "self",
                     file_keys=[doc_key(x) for x in m["atts"]], file_names_masked=list(m["atts"]),
                     body_masked=" ".join(m["tokens"]))
        if rf:
            r["flags"] = rf
        if m["proj"]:
            tags["msg"][mk] = m["proj"]
        mid = m["id"]
        rows.append(("1", mid, r))
    for mt in w.meets:
        r = _base("cal", "cal.com", "PC1", mt["a"], "minute")
        st = mt["status"]
        rf = {"response": STATUS_RESP.get(st, 0), "meeting_status": 5 if st == "cancelled" else 1}
        if mt["organizer"] == "ME" or st == "organizer":
            rf["organizer_me"] = True
        if mt["online"]:
            rf["online_meeting"] = True
        if mt["all_day"]:
            rf["all_day"] = True
        if mt["personal"]:
            rf["sensitivity"] = 2
        hint = {"trip": "trip", "leave": "leave", "edu": "edu"}.get(mt["category"], "none")
        r.update(ts_end=utc(mt["b"]), msg_key=cal_key(mt["id"]), thread_key=None,
                 subject_masked=" ".join(mt["tokens"]), subject_tokens=list(mt["tokens"]),
                 counterpart_keys=sorted({who(x) for x in mt["attendees"] if x != "ME"}),
                 n_participants=mt["n_att"], busy="busy", abs_hint=hint,
                 location_class="external" if mt["category"] == "offsite" else ("online" if mt["online"] else "room"),
                 flags=rf)
        rows.append(("2", mt["id"], r))
    for i, d in enumerate(w.docs):
        r = _base("pc_file", "pc.files", d["pc"], d["t"], "exact")
        dk = doc_key(d["doc"])
        dks = [dir_key(d["folder"])] if d["folder"] else []
        rf = {"edit": True}
        if d["autosave"]:
            rf["autosave"] = True
        if d["other"]:
            rf["author_other"] = True
        if d["kind"] == "export":
            rf["pdf_export"] = True
        r.update(doc_key=dk, path_key="f" + _h("path", d["folder"] + "/" + d["doc"], 16), name_masked=d["doc"],
                 ext=_ext(d["doc"]), folder_role="documents", root_id=None, op=DOC_OP[d["kind"]],
                 size_bucket="<100KB", ooxml_totaltime=None, ooxml_revision=None, dir_keys=dks, flags=rf)
        if d["proj"]:
            tags["fam"][fam_key(dk, d["doc"], dks, cfg)] = d["proj"]
        rows.append(("3", f"{i:08d}", r))
    for i, c in enumerate(w.comps):
        r = _base("pc_compute", "pc.compute", c["pc"], c["a"], "minute")
        r.update(ts_end=utc(c["b"]), app_id=c["app"], cpu_core=4.0, doc_key=doc_key(c["doc"]) if c["doc"] else None,
                 flags={"solver": True})
        rows.append(("6", f"{i:08d}", r))
    for i, c in enumerate(w.commits):
        r = _base("pc_git", "pc.git", c["pc"], c["t"], "exact")
        r.update(doc_key=repo_key(c["repo"]), commit_key="g" + _h("commit", f"{c['t']}|{c['repo']}|{i}", 16),
                 msg_masked=" ".join(c["tokens"]), subject_tokens=[c["repo"], *c["tokens"]], n_commits=1, n_files=1,
                 exts=[".py"])
        rows.append(("7", f"{i:08d}", r))
    for i, m in enumerate(w.manual):
        local = m["a"] or ((m["day"] or w.d0) + " 00:00")      # 시각·날짜 없는 응답(must_link 등) = 기간 첫날(date)
        r = _base("manual", "manual", "PC1", local, "minute" if m["a"] else "date")
        refs = []
        if m["key"]:
            refs.append(msg_key(m["key"]))
        if m["ref"]:
            refs.append(cal_key(m["ref"]) if m["kind"] == "attended" else doc_key(m["ref"]))
        toks = list(m["tokens"]) + ([m["ref"]] if m["ref"] and m["kind"] != "attended" else [])
        r.update(ts_end=utc(m["b"]) if m["b"] else None, work_category=None, hours=m["hours"],
                 text_masked=" ".join(toks), subject_tokens=toks, project_id=None, role_field=None, role_func=None,
                 man_kind=m["kind"], ref_keys=refs, retract_of=None)
        rows.append(("8", f"{i:08d}", r))
    for name in sorted(w.shared_docs):
        tags["shared_fams"].add(fam_key(doc_key(name), name, [], cfg))
    out = []
    by_group: dict[str, list[tuple[str, dict]]] = {}
    for g, k, r in rows:
        by_group.setdefault(g, []).append((k, r))
    for g in sorted(by_group):
        for rank, (_k, r) in enumerate(sorted(by_group[g], key=lambda x: x[0])):
            r["id"] = g + f"{rank:015x}"
            out.append(r)
    profile = {"d0": w.d0, "d1": w.d1, "leaves": dict(w.leaves), "coverage": dict(w.coverage)}
    return out, profile, as_of_utc(w.as_of), tags, map_cfg(w.cfg)


def run_env(w: W, cfg=None, *, records=None, shuffle=None):
    """W(또는 미리 바꾼 행) → (Evidence, days, Envelope, cfg). shuffle = 행 순서를 섞을 난수 시드."""
    import random
    base = cfg or base_cfg()
    recs, profile, as_of, tags, over = to_inputs(w, base)
    if records is not None:
        recs = records
    if shuffle is not None:
        recs = list(recs)
        random.Random(shuffle).shuffle(recs)
    c = base.derive(over) if over else base
    ev, _audit = normalize(recs, profile, c, as_of, tags)
    days = build_days(ev, c, calendar())
    env = build_envelope(ev, c, days)
    return ev, days, env, c


def load_golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def golden_minutes(g: dict) -> tuple[int, dict[str, int]]:
    """골든 h(소수 2자리) → 정수 분(5분 슬롯 단위로 반올림)."""
    env = int(round(g["env"] * 12)) * 5
    tags = {TAG_CODES[k]: int(round(v * 12)) * 5 for k, v in g["tags"].items() if v}
    return env, tags


# ───────────────────────────── 시나리오(참조 scenarios.py 이식 — 본문 그대로) ─────────────────────────────
SC = {}
AS_OF = '2026-10-30 18:00'


def sc(fn):
    SC[fn.__name__.upper()] = fn
    return fn


# ───────────────────────── A. 시작·종료 조합([업무시간]6) ─────────────────────────
@sc
def w01():
    """S1×E1: 팀즈 의뢰 → 3일 문서 → 같은 방 보고(첨부)"""
    n = W('W01', '2026-10-12', '2026-10-14', AS_OF, 'S1×E1 팀즈 의뢰→문서 3일→같은 방 보고')
    v1, v2, oth = '검토보고서_과제A_열해석_v1.pptx', '검토보고서_과제A_열해석_v2.pptx', '주간회의록_과제B.docx'
    n.msg('2026-10-12 10:00', 'in', 'request', 'chat_kim', 'P1', 'teams', tokens=('과제A', '열해석', '검토보고서'))
    n.msg('2026-10-14 16:00', 'out', 'report', 'chat_kim', 'P1', 'teams', atts=(v2,))
    office_day(n, 'PC1', '2026-10-12', [('10:00', '12:00', 'mail', ''), ('13:00', '17:00', 'office', v1)])
    office_day(n, 'PC1', '2026-10-13', [('09:00', '12:00', 'office', v1), ('13:00', '18:00', 'office', oth)])
    office_day(n, 'PC1', '2026-10-14', [('09:00', '11:00', 'office', v2), ('13:00', '15:30', 'office', v2),
                                         ('15:30', '16:10', 'chat', '')])
    for t, d in (('10-12 16:50', v1), ('10-13 11:50', v1), ('10-14 10:50', v2), ('10-14 15:25', v2),
                 ('10-13 17:50', oth)):
        n.doc('2026-' + t, 'save', d)
    return n


@sc
def w02():
    """S1×E2: 의뢰 메일 → 목 15:00 마지막 저장·15:05 PDF 내보내기, 보고 없음(3업무일 조용)"""
    n = W('W02', '2026-10-12', '2026-10-16', AS_OF, 'S1×E2 마지막 저장+PDF, 보고 없음')
    d = '원가절감안_과제B.pptx'
    n.msg('2026-10-12 10:00', 'in', 'request', 'M2', 'P2', tokens=('원가절감안', '과제B'))
    for day in ('2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15'):
        office_day(n, 'PC1', day, [('13:00', '16:00', 'office', d)])
        n.doc(f'{day} 15:00', 'save', d)
    n.doc('2026-10-15 15:05', 'export', d.replace('.pptx', '.pdf'))
    office_day(n, 'PC1', '2026-10-16')
    return n


@sc
def w03():
    """S1×E2 → E1: W02 + 금 10:00 보고 메일(PDF 첨부) → 종료가 보고로 연장"""
    n = w02()
    n.name, n.note = 'W03', 'W02 + 금 10:00 보고(첨부) → 종료 연장'
    n.msg('2026-10-16 10:00', 'out', 'report', 'M2', 'P2', atts=('원가절감안_과제B.pdf',), tokens=('원가절감안',))
    return n


@sc
def w04():
    """S2×E1: 신호 없는 대면 지시 → 문서 3일 → 메일 보고(첨부)"""
    n = W('W04', '2026-10-13', '2026-10-15', AS_OF, 'S2×E1 오프라인 지시→메일 보고')
    d = '원가분석_과제B.xlsx'
    n.msg('2026-10-15 16:00', 'out', 'report', 'M4', 'P2', atts=(d,), tokens=('원가분석', '과제B'))
    office_day(n, 'PC1', '2026-10-13', [('09:40', '12:00', 'office', d)])
    office_day(n, 'PC1', '2026-10-14', [('13:00', '17:00', 'office', d)])
    office_day(n, 'PC1', '2026-10-15', [('09:00', '11:00', 'office', d), ('15:50', '16:00', 'mail', '')])
    for t in ('10-13 11:50', '10-14 16:50', '10-15 10:50'):
        n.doc('2026-' + t, 'save', d)
    return n


@sc
def w05():
    """S2m×E1: W04 + 첫 작업 전 의뢰자(보고 수신자) 주최 회의 09:00~09:30"""
    n = w04()
    n.name, n.note = 'W05', 'W04 + 의뢰자 주최 회의 → 시작 = 회의'
    n.meet('2026-10-13 09:00', '2026-10-13 09:30', 'P2', ('P2', 'ME'), ('원가분석', '착수'))
    return n


@sc
def w06():
    """S2×E2: 신호 없는 지시 → 월·화 문서 → 화 11:50 PDF 내보내기 → 이후 조용"""
    n = W('W06', '2026-10-12', '2026-10-13', AS_OF, 'S2×E2')
    d = '배선도_과제C.dwg'
    office_day(n, 'PC1', '2026-10-12', [('13:00', '18:00', 'cad', d)])
    office_day(n, 'PC1', '2026-10-13', [('09:00', '11:50', 'cad', d)])
    n.doc('2026-10-12 17:50', 'save', d)
    n.doc('2026-10-13 11:45', 'save', d)
    n.doc('2026-10-13 11:50', 'export', '배선도_과제C.pdf')
    return n


@sc
def w07():
    """S1×E3i: 의뢰 메일 → 3일 작업 → 대면 보고(무신호) → 5업무일 휴면"""
    n = W('W07', '2026-10-12', '2026-10-14', AS_OF, 'S1×E3 의뢰→작업→대면보고(무신호)')
    d = '센서보정_과제C.xlsx'
    n.msg('2026-10-12 09:30', 'in', 'request', 'M7', 'P3', tokens=('센서보정', '과제C'))
    office_day(n, 'PC1', '2026-10-12', [('10:00', '12:00', 'office', d)])
    office_day(n, 'PC1', '2026-10-13', [('13:00', '17:00', 'office', d)])
    office_day(n, 'PC1', '2026-10-14', [('09:00', '12:00', 'office', d), ('13:00', '16:00', 'office', d)])
    for t in ('10-12 11:50', '10-13 16:50', '10-14 15:50'):
        n.doc('2026-' + t, 'save', d)
    return n


@sc
def w08():
    """S1×E3c: 의뢰 → 2일 작업 → 다음 날 의뢰자 주최 리뷰 회의(대면 보고)"""
    n = W('W08', '2026-10-12', '2026-10-14', AS_OF, 'S1×E3c 의뢰자 주최 리뷰 회의')
    d = '구조해석_과제A.pptx'
    n.msg('2026-10-12 09:30', 'in', 'request', 'M8', 'P1', tokens=('구조해석', '과제A'))
    office_day(n, 'PC1', '2026-10-12', [('10:00', '12:00', 'office', d), ('13:00', '17:00', 'office', d)])
    office_day(n, 'PC1', '2026-10-13', [('09:00', '12:00', 'office', d)])
    office_day(n, 'PC1', '2026-10-14')
    n.doc('2026-10-12 16:50', 'save', d)
    n.doc('2026-10-13 11:50', 'save', d)
    n.meet('2026-10-14 10:00', '2026-10-14 11:00', 'P1', ('P1', 'ME', 'P2'), ('구조해석', '리뷰'))
    return n


@sc
def w09():
    """S2×E3 분리: CAD 9/1·9/2·9/4 → 10업무일 공백(추석 연휴는 근무일 아님) → 9/21 재개"""
    n = W('W09', '2026-09-01', '2026-09-22', '2026-09-30 18:00', 'S2×E3 + 휴면 분리')
    d = '하우징_과제D.prt'
    for day in ('2026-09-01', '2026-09-02', '2026-09-04', '2026-09-21'):
        office_day(n, 'PC1', day, [('09:00', '12:00', 'cad', d)])
        n.doc(f'{day} 11:55', 'save', d)
    return n


@sc
def w10():
    """시작만(미착수): 9/1 팀즈 의뢰, 진행 증거 없음, 그날 PC 는 일반 사용"""
    n = W('W10', '2026-09-01', '2026-09-01', '2026-09-30 18:00', '시작만 → 미착수 Z')
    n.msg('2026-09-01 10:00', 'in', 'request', 'chat_z', 'P4', 'teams', tokens=('치구', '발주'))
    office_day(n, 'PC1', '2026-09-01')
    return n


@sc
def w11():
    """종료만(진행 있음): 의뢰 없이 14:00~14:50 주간보고 작성 → 15:00 보고(첨부)"""
    n = W('W11', '2026-10-16', '2026-10-16', AS_OF, '고아 보고 → 자체 업무 S2p×E1')
    d = '주간업무_과제E.xlsx'
    office_day(n, 'PC1', '2026-10-16', [('14:00', '14:50', 'office', d), ('14:50', '15:00', 'mail', '')])
    n.doc('2026-10-16 14:48', 'save', d)
    n.msg('2026-10-16 15:00', 'out', 'report', 'M11', 'P1', atts=(d,), tokens=('주간업무',))
    return n


@sc
def w12():
    """종료만(진행 없음): 15:00 보고 메일, 첨부 파일의 작성 흔적 없음"""
    n = W('W12', '2026-10-16', '2026-10-16', AS_OF, '단발 보고 REPORT_ONLY')
    office_day(n, 'PC1', '2026-10-16')
    n.msg('2026-10-16 15:00', 'out', 'report', 'M12', 'P1', atts=('외주_검수결과.pdf',), tokens=('외주', '검수결과'))
    return n


@sc
def w13():
    """재의뢰 차수: 의뢰 → 보고(v1) → 같은 스레드 수정 요청 → 보고(v2)"""
    n = W('W13', '2026-10-19', '2026-10-21', AS_OF, '재의뢰 rev2')
    d1, d2 = '시험계획_과제F_v1.docx', '시험계획_과제F_v2.docx'
    n.msg('2026-10-19 10:00', 'in', 'request', 'M13', 'P1', tokens=('시험계획', '과제F'))
    office_day(n, 'PC1', '2026-10-19', [('10:10', '12:00', 'office', d1), ('13:00', '18:00', 'office', d1)])
    office_day(n, 'PC1', '2026-10-20', [('09:00', '12:00', 'office', d1), ('13:00', '14:50', 'office', d1)])
    n.doc('2026-10-19 17:50', 'save', d1)
    n.doc('2026-10-20 14:45', 'save', d1)
    n.msg('2026-10-20 15:00', 'out', 'report', 'M13', 'P1', atts=(d1,), tokens=('시험계획',))
    n.msg('2026-10-21 10:00', 'in', 'request', 'M13', 'P1', tokens=('시험계획', '수정'))
    office_day(n, 'PC1', '2026-10-21', [('10:10', '12:00', 'office', d2), ('13:00', '16:50', 'office', d2)])
    n.doc('2026-10-21 16:45', 'save', d2)
    n.msg('2026-10-21 17:00', 'out', 'report', 'M13', 'P1', atts=(d2,), tokens=('시험계획',))
    return n


@sc
def w14():
    """ACK 시작(S2a): 대면 지시 뒤 팀즈 '수락' 발신 → 작업 → 같은 방 보고"""
    n = W('W14', '2026-10-13', '2026-10-14', AS_OF, 'ACK 시작 S2a×E1')
    d = '하네스사양_과제G.xlsx'
    n.msg('2026-10-13 10:00', 'out', 'ack', 'chat_lee', 'P5', 'teams')
    office_day(n, 'PC1', '2026-10-13', [('10:05', '12:00', 'office', d), ('13:00', '17:00', 'office', d)])
    office_day(n, 'PC1', '2026-10-14', [('09:00', '11:00', 'office', d)])
    n.doc('2026-10-13 16:55', 'save', d)
    n.doc('2026-10-14 10:55', 'save', d)
    n.msg('2026-10-14 11:00', 'out', 'report', 'chat_lee', 'P5', 'teams', atts=(d,))
    return n


@sc
def w15():
    """선행 착수: 의뢰 전날 구두 예고 → 10~13 선행 작업 → 다음 날 09:00 공식 의뢰 → 15:00 보고"""
    n = W('W15', '2026-10-12', '2026-10-13', AS_OF, '선행 착수 pre_request')
    d = '열해석_과제H.xlsx'
    office_day(n, 'PC1', '2026-10-12', [('10:00', '12:00', 'office', d), ('13:00', '14:00', 'office', d)])
    n.doc('2026-10-12 13:55', 'save', d)
    n.msg('2026-10-13 09:00', 'in', 'request', 'M15', 'P1', tokens=('열해석', '과제H'))
    office_day(n, 'PC1', '2026-10-13', [('09:10', '12:00', 'office', d), ('13:00', '14:50', 'office', d)])
    n.doc('2026-10-13 14:45', 'save', d)
    n.msg('2026-10-13 15:00', 'out', 'report', 'M15', 'P1', atts=(d,), tokens=('열해석',))
    return n


@sc
def w16():
    """NEXT_REQ: 의뢰 → 2일 작업 → (대면 보고, 무신호) → 4업무일 조용 → 같은 스레드 같은 화제 추가 요청 → 1일 작업"""
    n = W('W16', '2026-10-12', '2026-10-20', AS_OF, '추가 요청이 조용한 기간 뒤 → 새 차수')
    d = '배터리팩_과제I.xlsx'
    n.msg('2026-10-12 09:30', 'in', 'request', 'M16', 'P6', tokens=('배터리팩', '과제I'))
    office_day(n, 'PC1', '2026-10-12', [('10:00', '12:00', 'office', d)])
    office_day(n, 'PC1', '2026-10-13', [('13:00', '16:00', 'office', d)])
    n.doc('2026-10-12 11:50', 'save', d)
    n.doc('2026-10-13 15:50', 'save', d)
    n.msg('2026-10-19 10:00', 'in', 'request', 'M16', 'P6', tokens=('배터리팩', '보완'))
    office_day(n, 'PC1', '2026-10-19', [('10:10', '12:00', 'office', d), ('13:00', '15:00', 'office', d)])
    n.doc('2026-10-19 14:50', 'save', d)
    return n


# ───────────────────────── B. 연결(키 사슬·대화방·반복·범용 이름) ─────────────────────────
@sc
def w17():
    """1:1 상시 대화방 의뢰 2건: 10:00 브라켓·10:02 수락·13:30 모터·14:00/16:30 보고(첨부)"""
    n = W('W17', '2026-10-13', '2026-10-13', AS_OF, '1:1 대화방 의뢰 2건(X19)')
    br, mo = '브라켓_도면.dwg', '모터_사양.xlsx'
    n.msg('2026-10-13 10:00', 'in', 'request', 'chat_p31', 'P31', 'teams', tokens=('브라켓', '도면'))
    n.msg('2026-10-13 10:02', 'out', 'ack', 'chat_p31', 'P31', 'teams')
    n.msg('2026-10-13 13:30', 'in', 'request', 'chat_p31', 'P31', 'teams', tokens=('모터', '사양'))
    n.msg('2026-10-13 14:00', 'out', 'report', 'chat_p31', 'P31', 'teams', atts=(br,), tokens=('브라켓', '도면'))
    n.msg('2026-10-13 16:30', 'out', 'report', 'chat_p31', 'P31', 'teams', atts=(mo,), tokens=('모터', '사양'))
    office_day(n, 'PC1', '2026-10-13', [('10:05', '12:00', 'cad', br), ('13:00', '13:55', 'cad', br),
                                         ('14:05', '16:25', 'office', mo)])
    n.doc('2026-10-13 13:50', 'save', br)
    n.doc('2026-10-13 16:20', 'save', mo)
    return n


@sc
def w18():
    """다대다: 같은 상대의 의뢰 2건(M1 원가·M2 일정)을 M1 스레드 보고 1통(두 파일 첨부)으로 닫음"""
    n = W('W18', '2026-10-12', '2026-10-13', AS_OF, '보고 1통이 의뢰 2건 종료(X20)')
    a, b = '원가분석_과제F.xlsx', '일정계획_과제G.xlsx'
    n.msg('2026-10-12 09:30', 'in', 'request', 'M1', 'P1', tokens=('원가분석', '과제F'))
    n.msg('2026-10-12 10:00', 'in', 'request', 'M2', 'P1', tokens=('일정계획', '과제G'))
    office_day(n, 'PC1', '2026-10-12', [('10:10', '12:00', 'office', a), ('13:00', '17:00', 'office', b)])
    office_day(n, 'PC1', '2026-10-13', [('09:00', '12:00', 'office', a), ('13:00', '16:00', 'office', b)])
    for t, d in (('10-12 11:50', a), ('10-12 16:50', b), ('10-13 11:50', a), ('10-13 15:50', b)):
        n.doc('2026-' + t, 'save', d)
    n.msg('2026-10-13 16:30', 'out', 'report', 'M1', 'P1', atts=(a, b), tokens=('원가분석', '일정계획'))
    return n


@sc
def w19():
    """조율형(S1o/E1i): P5 에게 지시 → P5 보고 수신(첨부) → 검토(열람) → P1 에게 전달 보고(E1o)"""
    n = W('W19', '2026-10-12', '2026-10-14', AS_OF, '조율형 지시·검토·전달(X21)')
    f = '시험성적서_과제H.pdf'
    n.msg('2026-10-12 10:00', 'out', 'request', 'M21', 'P5', tokens=('시험성적서', '과제H'))
    n.msg('2026-10-14 15:00', 'in', 'report', 'M21', 'P5', atts=(f,), tokens=('시험성적서', '과제H'))
    n.msg('2026-10-14 16:00', 'out', 'report', 'M22', 'P1', atts=(f,), tokens=('시험성적서', '과제H'))
    office_day(n, 'PC1', '2026-10-12', [('09:40', '10:00', 'mail', '')])
    office_day(n, 'PC1', '2026-10-13')
    office_day(n, 'PC1', '2026-10-14', [('15:05', '15:50', 'office', f), ('15:50', '16:00', 'mail', '')])
    n.doc('2026-10-14 15:06', 'open', f)
    return n


@sc
def w20():
    """반복 문서: 9/2~10/21 매주 수 16~17시 주간보고.xlsx 작성·저장(8주)"""
    n = W('W20', '2026-09-01', '2026-10-23', AS_OF, '주간보고 8주 반복(X22)')
    import datetime as dt
    d = dt.date(2026, 9, 2)
    while d <= dt.date(2026, 10, 21):
        s = d.isoformat()
        n.on('PC1', f'{s} 15:55', f'{s} 17:05')
        n.samp('PC1', f'{s} 16:00', f'{s} 17:00', 'office', '주간보고.xlsx')
        n.doc(f'{s} 16:55', 'save', '주간보고.xlsx')
        d += dt.timedelta(days=7)
    return n


@sc
def w21():
    """범용 파일명: P1 의뢰(M1)·P2 의뢰(M2)를 둘 다 '보고서.pptx' 로 작업·첨부 보고"""
    n = W('W21', '2026-10-12', '2026-10-13', AS_OF, '범용 파일명 2업무(X23)')
    n.msg('2026-10-12 09:30', 'in', 'request', 'M1', 'P1', tokens=('원가', '절감'))
    n.msg('2026-10-12 13:00', 'in', 'request', 'M2', 'P2', tokens=('품질', '이슈'))
    office_day(n, 'PC1', '2026-10-12', [('09:40', '12:00', 'office', '보고서.pptx'),
                                         ('13:10', '18:00', 'office', '보고서.pptx')])
    office_day(n, 'PC1', '2026-10-13', [('09:00', '12:00', 'office', '보고서.pptx'),
                                         ('13:00', '16:00', 'office', '보고서.pptx')])
    for t in ('10-12 11:50', '10-12 17:50', '10-13 11:50', '10-13 15:50'):
        n.doc('2026-' + t, 'save', '보고서.pptx')
    n.msg('2026-10-12 11:58', 'out', 'report', 'M1', 'P1', atts=('보고서.pptx',), tokens=('원가', '절감'))
    n.msg('2026-10-13 16:00', 'out', 'report', 'M2', 'P2', atts=('보고서.pptx',), tokens=('품질', '이슈'))
    return n


@sc
def w22():
    """같은 메일 스레드, 보고 후 2업무일 만에 무관한 새 의뢰(토큰·첨부 불일치) → 새 업무"""
    n = W('W22', '2026-10-12', '2026-10-16', AS_OF, '같은 스레드 무관 새 의뢰(X24)')
    a, b = '원가검토_과제F.xlsx', '출장일정_고객사A.xlsx'
    n.msg('2026-10-12 09:30', 'in', 'request', 'M1', 'P1', tokens=('원가검토', '과제F'))
    office_day(n, 'PC1', '2026-10-12', [('09:40', '12:00', 'office', a), ('13:00', '16:00', 'office', a)])
    n.doc('2026-10-12 15:50', 'save', a)
    n.msg('2026-10-12 16:10', 'out', 'report', 'M1', 'P1', atts=(a,), tokens=('원가검토',))
    n.msg('2026-10-14 10:00', 'in', 'request', 'M1', 'P1', tokens=('출장일정', '고객사A'))
    office_day(n, 'PC1', '2026-10-14', [('10:10', '12:00', 'office', b), ('13:00', '15:00', 'office', b)])
    n.doc('2026-10-14 14:50', 'save', b)
    n.msg('2026-10-14 15:10', 'out', 'report', 'M1', 'P1', atts=(b,), tokens=('출장일정',))
    return n


@sc
def w23():
    """[업무시간]3 + 한국어 합성어: '견적·검토' 의뢰 ↔ '견적검토.xlsx', 21:30 휴대폰 보고(PC 꺼짐)"""
    n = W('W23', '2026-10-15', '2026-10-15', AS_OF, '휴대폰 원격 발신 + 합성어 연결(X08)')
    n.msg('2026-10-15 10:00', 'in', 'request', 'M8', 'P1', tokens=('견적', '검토'))
    office_day(n, 'PC1', '2026-10-15', [('10:10', '12:00', 'office', '견적검토.xlsx')])
    n.doc('2026-10-15 11:50', 'save', '견적검토.xlsx')
    n.msg('2026-10-15 21:30', 'out', 'report', 'M8', 'P1', tokens=('견적', '검토'))
    return n


@sc
def w24():
    """과제 레지스트리 충돌(cannot-link): 같은 상대·같은 토큰 의뢰 2건이 과제A·과제B 로 갈림"""
    n = W('W24', '2026-10-21', '2026-10-21', AS_OF, '과제 충돌 → 분리(B S32)')
    n.msg('2026-10-21 09:10', 'in', 'request', 'M24a', 'P32', tokens=('하네스', '시험'), proj='P-0001')
    n.msg('2026-10-21 09:20', 'in', 'request', 'M24b', 'P32', tokens=('하네스', '시험'), proj='P-0002')
    office_day(n, 'PC1', '2026-10-21', [('09:30', '12:00', 'office', '하네스시험_A.xlsx'),
                                         ('13:00', '16:00', 'office', '하네스시험_B.xlsx')])
    n.doc('2026-10-21 11:55', 'save', '하네스시험_A.xlsx', proj='P-0001')
    n.doc('2026-10-21 15:55', 'save', '하네스시험_B.xlsx', proj='P-0002')
    return n


@sc
def w25():
    """상용구 오매칭 방지: 두 의뢰(P1·P2) → P2 에게 상용구만의 보고 1통 + 토큰이 맞는 보고 1통"""
    n = W('W25', '2026-10-22', '2026-10-22', AS_OF, '상용구만 겹치는 보고는 짝이 아님(A S14)')
    n.msg('2026-10-22 09:10', 'in', 'request', 'M25a', 'P1', tokens=('브레이크', '소음'))
    n.msg('2026-10-22 09:20', 'in', 'request', 'M25b', 'P2', tokens=('과제B', '원가표'))
    office_day(n, 'PC1', '2026-10-22', [('09:30', '12:00', 'office', '과제B_원가표.xlsx'),
                                         ('13:00', '15:50', 'office', '과제B_원가표.xlsx')])
    n.doc('2026-10-22 15:45', 'save', '과제B_원가표.xlsx')
    n.msg('2026-10-22 10:50', 'out', 'report', 'M25c', 'P2', tokens=('검토', '부탁드립니다', '결과'))
    n.msg('2026-10-22 16:00', 'out', 'report', 'M25d', 'P2', tokens=('과제B', '원가표', '검토결과'))
    return n


# ───────────────────────── C. 근무 봉투([업무시간]2~5, 신호 결손) ─────────────────────────
@sc
def w26():
    """[업무시간]5: 18~19 개인 브라우저 능동(업무 앱·산출물 없음) → 19~23 잠금"""
    n = W('W26', '2026-10-14', '2026-10-14', AS_OF, '퇴근 후 개인 브라우저 1h(X06)')
    office_day(n, 'PC1', '2026-10-14', [('09:00', '12:00', 'office', '사양서.docx'),
                                         ('13:00', '18:00', 'office', '사양서.docx')], after=('2026-10-14 23:00', 'locked'))
    n.samples = [s for s in n.samples if not (s['a'] == '2026-10-14 18:00')]
    n.samp('PC1', '2026-10-14 18:00', '2026-10-14 19:00', 'browser')
    n.samp('PC1', '2026-10-14 19:00', '2026-10-14 23:00', 'other', state='locked')
    n.doc('2026-10-14 11:50', 'save', '사양서.docx')
    return n


@sc
def w27():
    """창 밖 자격 = 골격 ±30분: 18:00~22:45 개인 브라우저 + 22:45~22:51 문서 + 22:50 저장 1건"""
    n = W('W27', '2026-10-14', '2026-10-14', AS_OF, '퇴근 후 5h 브라우저 + 저장 1건(X06b)')
    office_day(n, 'PC1', '2026-10-14', [('09:00', '12:00', 'office', '사양서.docx'),
                                         ('13:00', '18:00', 'office', '사양서.docx')], after=('2026-10-14 23:00', 'active'))
    n.samples = [s for s in n.samples if not (s['a'] == '2026-10-14 18:00')]
    n.samp('PC1', '2026-10-14 18:00', '2026-10-14 22:45', 'browser')
    n.samp('PC1', '2026-10-14 22:45', '2026-10-14 22:51', 'office', '사양서.docx')
    n.samp('PC1', '2026-10-14 22:51', '2026-10-14 23:00', 'browser')
    n.doc('2026-10-14 11:50', 'save', '사양서.docx')
    n.doc('2026-10-14 22:50', 'save', '사양서.docx')
    return n


@sc
def w28():
    """[업무시간]4: 정규 후 18:05 잠금 → 22:10 재개 → 같은 문서 → 01:40~02:30 잠금 → 02:40 보고 메일"""
    n = W('W28', '2026-10-26', '2026-10-27', AS_OF, '늦은 재개→새벽 보고, 샘플러 잠금 관측(X07)')
    d = '해석보고서_과제A.docx'
    office_day(n, 'PC1', '2026-10-26', [('09:00', '12:00', 'office', d), ('13:00', '18:00', 'office', d)])
    n.pcon = [p for p in n.pcon if not p['a'].startswith('2026-10-26')]
    n.on('PC1', '2026-10-26 08:30', '2026-10-27 03:00')
    n.samp('PC1', '2026-10-26 18:00', '2026-10-26 22:10', 'other', state='locked')
    n.samp('PC1', '2026-10-26 22:10', '2026-10-26 23:20', 'office', d)
    n.samp('PC1', '2026-10-26 23:20', '2026-10-26 23:50', 'other', state='idle')
    n.samp('PC1', '2026-10-26 23:50', '2026-10-27 01:40', 'office', d)
    n.samp('PC1', '2026-10-27 01:40', '2026-10-27 02:30', 'other', state='locked')
    n.samp('PC1', '2026-10-27 02:30', '2026-10-27 02:41', 'mail', '')
    n.samp('PC1', '2026-10-27 02:41', '2026-10-27 03:00', 'other', state='locked')
    for t in ('10-26 11:50', '10-26 17:50', '10-26 23:00', '10-27 01:30'):
        n.doc('2026-' + t, 'save', d)
    n.msg('2026-10-27 02:40', 'out', 'report', 'M28', 'P1', atts=(d,), tokens=('해석보고서',))
    return n


@sc
def w28b():
    """W28 의 샘플러 없는 판(LM24 V9): PC 08:30~익일 03:00 가동, 저장·발신만"""
    n = w28()
    n.name, n.note = 'W28b', '같은 하루, 샘플러 없음(PC 가동만) — V9'
    n.samples = []
    return n


@sc
def w29a():
    """단조성 기준: 평일 21:00 저장 1건(샘플러 없음)"""
    n = W('W29a', '2026-10-14', '2026-10-14', AS_OF, '창 밖 저장 1건(X25a)')
    n.doc('2026-10-14 21:00', 'save', '계산서_과제A.xlsx')
    return n


@sc
def w29b():
    """W29a + 같은 PC 샘플러 21:00~21:02 능동(같은 문서) — 양성 증거 추가 → 비감소"""
    n = w29a()
    n.name, n.note = 'W29b', 'W29a + 샘플러 2분(X25b)'
    n.samp('PC1', '2026-10-14 21:00', '2026-10-14 21:02', 'office', '계산서_과제A.xlsx')
    return n


@sc
def w30a():
    """샘플러 없는 PC1(09~18 가동), 저장 10:00·16:00"""
    n = W('W30a', '2026-10-14', '2026-10-14', AS_OF, '샘플러 없음 하한, 저장 2건(X25c)')
    n.on('PC1', '2026-10-14 09:00', '2026-10-14 18:00')
    n.doc('2026-10-14 10:00', 'save', '설계서_과제A.docx')
    n.doc('2026-10-14 16:00', 'save', '설계서_과제A.docx')
    return n


@sc
def w30b():
    """W30a + 다른 PC2 샘플러 11:00~11:05 브라우저 능동 — PC1 하한 유지"""
    n = w30a()
    n.name, n.note = 'W30b', 'W30a + PC2 샘플러 5분(X25d)'
    n.samp('PC2', '2026-10-14 11:00', '2026-10-14 11:05', 'browser')
    return n


@sc
def w31a():
    """에이전트 15시 중도 설치: PC1 이벤트 08:50~18:05, 샘플러 15:00~18:00, 저장 10:00·11:30·16:00"""
    n = W('W31a', '2026-10-13', '2026-10-13', AS_OF, '샘플러 중도 시작(X12)')
    d = '설계변경_과제A.pptx'
    n.on('PC1', '2026-10-13 08:50', '2026-10-13 18:05')
    n.samp('PC1', '2026-10-13 15:00', '2026-10-13 18:00', 'office', d)
    for t in ('10:00', '11:30', '16:00'):
        n.doc(f'2026-10-13 {t}', 'save', d)
    return n


@sc
def w31b():
    """W31a 에서 샘플러를 뺀 것(비교 기준)"""
    n = w31a()
    n.name, n.note = 'W31b', '같은 입력, 샘플러 없음(X12b)'
    n.samples = []
    return n


@sc
def w32():
    """샘플러 정상, 11~16시 무입력(잠그지 않음) — 근거 없는 낮 공백"""
    n = W('W32', '2026-10-13', '2026-10-13', AS_OF, '샘플러 유휴 5h(X13)')
    d = '검토_과제E.docx'
    n.on('PC1', '2026-10-13 08:50', '2026-10-13 18:05')
    n.samp('PC1', '2026-10-13 09:00', '2026-10-13 11:00', 'office', d)
    n.samp('PC1', '2026-10-13 11:00', '2026-10-13 16:00', 'other', state='idle')
    n.samp('PC1', '2026-10-13 16:00', '2026-10-13 18:00', 'office', d)
    n.doc('2026-10-13 10:50', 'save', d)
    n.doc('2026-10-13 17:50', 'save', d)
    return n


@sc
def w33():
    """수집 안 된 노트북: PC1 오전 능동·오후 잠금, 오후 발신 14:00·15:30·17:00(같은 화제)"""
    n = W('W33', '2026-10-14', '2026-10-14', AS_OF, '미수집 노트북 오후(X33)')
    d = '검토의견_과제B.docx'
    n.on('PC1', '2026-10-14 08:50', '2026-10-14 18:05')
    n.samp('PC1', '2026-10-14 09:00', '2026-10-14 12:00', 'office', d)
    n.samp('PC1', '2026-10-14 12:00', '2026-10-14 18:00', 'other', state='locked')
    n.doc('2026-10-14 11:50', 'save', d)
    for t, th in (('14:00', 'Ma'), ('15:30', 'Mb'), ('17:00', 'Mc')):
        n.msg(f'2026-10-14 {t}', 'out', 'info', th, 'P2', tokens=('검토의견',))
    return n


@sc
def w34():
    """점심 개인 사용: 12~13 브라우저 능동(업무 앱·산출물 없음, 잠금 없음)"""
    n = W('W34', '2026-10-14', '2026-10-14', AS_OF, '점심 브라우저 1h(X26)')
    office_day(n, 'PC1', '2026-10-14', [('09:00', '12:00', 'office', '보고서_과제A.docx'),
                                         ('13:00', '18:00', 'office', '보고서_과제A.docx')], lunch=None)
    n.samp('PC1', '2026-10-14 12:00', '2026-10-14 13:00', 'browser')
    n.doc('2026-10-14 17:50', 'save', '보고서_과제A.docx')
    return n


@sc
def w35():
    """date-only 발신 5통 + PC 09~18(샘플러 없음) — 기본 0h"""
    n = W('W35', '2026-10-14', '2026-10-14', AS_OF, 'date-only 발신만(X27)')
    n.on('PC1', '2026-10-14 09:00', '2026-10-14 18:00')
    for k in range(5):
        n.msg('2026-10-14 12:00', 'out', 'info', f'D{k}', 'P1', prec='date')
    return n


@sc
def w35b():
    """W35 + 게이트 옵션(time.envelope.dateOnlyGate=true) → 낮은 신뢰 하한 + Q06"""
    n = w35()
    n.name, n.note = 'W35b', 'W35 + dateOnlyGate 켬'
    n.cfg = {'time.envelope.dateOnlyGate': True}
    return n


@sc
def w36():
    """V1·R7: 샘플러 없음, PC 09~18, 직접 수신만 — 10/13 8통(1h 간격), 10/14 80통, 10/15 CC 1통"""
    n = W('W36', '2026-10-13', '2026-10-15', AS_OF, '수신만(8통·80통·CC1)(X14)')
    for d in ('2026-10-13', '2026-10-14', '2026-10-15'):
        n.on('PC1', f'{d} 09:00', f'{d} 18:00')
    for k in range(8):
        n.msg(f'2026-10-13 {9 + k:02d}:30', 'in', 'info', f'T{k}', 'P1')
    for k in range(80):
        mm = 9 * 60 + 5 + k * 6
        n.msg(f'2026-10-14 {mm // 60:02d}:{mm % 60:02d}', 'in', 'info', f'U{k}', f'P{k % 7}')
    n.msg('2026-10-15 10:00', 'in', 'info', 'V0', 'P1', direct=False)
    return n


@sc
def w37():
    """V4: 1h 회의 4건(수락, 사이 30·60분 공백) + 회의 중 저장 1건, PC 기록 없음"""
    n = W('W37', '2026-10-14', '2026-10-14', AS_OF, '회의 4건(X15)')
    for a in ('09:00', '10:30', '13:00', '15:00'):
        h = int(a[:2]) + 1
        n.meet(f'2026-10-14 {a}', f'2026-10-14 {h:02d}:{a[3:]}', 'P1', ('P1', 'ME', 'P2'), ('과제A', '설계', '리뷰'))
    n.doc('2026-10-14 13:30', 'save', '회의록_과제A.docx')
    return n


@sc
def w38():
    """V11: PC 기록 없는 평일(외근) 10:00 정보 발신·15:00 첨부 보고 발신 + 11:00 의뢰 수신"""
    n = W('W38', '2026-10-16', '2026-10-16', AS_OF, 'PC 기록 없는 평일 발신 2건(X09)')
    n.msg('2026-10-16 10:00', 'out', 'info', 'M9a', 'P4', tokens=('현장', '점검'))
    n.msg('2026-10-16 11:00', 'in', 'request', 'M9b', 'P5', tokens=('견적', '비교'))
    n.msg('2026-10-16 15:00', 'out', 'report', 'M9c', 'P6', atts=('점검결과_고객사A.pdf',), tokens=('점검결과',))
    return n


@sc
def w39():
    """V12·E8: 샘플러 없음, PC 08~19 켜짐, 파일 저장 1건(10:00)"""
    n = W('W39', '2026-10-13', '2026-10-13', AS_OF, '샘플러 없음·파일 1건(X10)')
    n.on('PC1', '2026-10-13 08:00', '2026-10-13 19:00')
    n.doc('2026-10-13 10:00', 'save', '메모_과제D.docx')
    return n


@sc
def w40():
    """V8: 데스크톱 09~10 문서A, 10~12 원격창(→클라우드PC 문서B), 노트북 13~18 문서A"""
    n = W('W40', '2026-10-14', '2026-10-14', AS_OF, '여러 PC + 원격(X16)')
    a, b = '문서A_과제A.docx', '문서B_과제B.xlsx'
    n.on('DESK', '2026-10-14 08:50', '2026-10-14 12:05')
    n.on('LAP', '2026-10-14 12:55', '2026-10-14 18:05')
    n.on('CPC', '2026-10-14 09:55', '2026-10-14 12:05')
    n.samp('DESK', '2026-10-14 09:00', '2026-10-14 10:00', 'office', a)
    n.samp('DESK', '2026-10-14 10:00', '2026-10-14 12:00', 'remote')
    n.samp('CPC', '2026-10-14 10:00', '2026-10-14 12:00', 'office', b)
    n.samp('LAP', '2026-10-14 13:00', '2026-10-14 18:00', 'office', a)
    n.doc('2026-10-14 09:50', 'save', a, pc='DESK')
    n.doc('2026-10-14 11:50', 'save', b, pc='CPC')
    n.doc('2026-10-14 17:50', 'save', a, pc='LAP')
    return n


@sc
def w41():
    """회의 중 PC: 30명 설명회 10~11 중 10:00~10:40 문서Y, 4명 주간회의 14~15 중 14:20~14:40 문서Y"""
    n = W('W41', '2026-10-14', '2026-10-14', AS_OF, '회의 혼합(대형 0.5/0.5, 소형 회의 100%)')
    x, y = '문서X_과제A.docx', '문서Y_과제B.xlsx'
    segs = [('09:00', '10:00', 'office', x), ('10:00', '10:40', 'office', y), ('10:40', '11:00', 'browser', ''),
            ('11:00', '12:00', 'office', x), ('13:00', '14:00', 'office', x), ('14:00', '14:20', 'browser', ''),
            ('14:20', '14:40', 'office', y), ('14:40', '15:00', 'browser', ''), ('15:00', '18:00', 'office', x)]
    office_day(n, 'PC1', '2026-10-14', segs)
    n.meet('2026-10-14 10:00', '2026-10-14 11:00', 'P9', tuple(f'P{i}' for i in range(30)), ('전사', '설명회'), n_att=30)
    n.meet('2026-10-14 14:00', '2026-10-14 15:00', 'P1', ('P1', 'P2', 'P3', 'ME'), ('과제A', '주간'))
    n.doc('2026-10-14 10:35', 'save', y)
    n.doc('2026-10-14 17:50', 'save', x)
    return n


@sc
def w42():
    """장시간 솔버: 15:30~16:30 설정·제출 → 연산 16:30~익일 04:00 → 익일 09:10~10:00 결과 확인"""
    n = W('W42', '2026-10-19', '2026-10-20', AS_OF, '밤샘 솔버(X18)')
    m, r = '열해석_모델.cas', '결과보고서_과제A.docx'
    office_day(n, 'PC1', '2026-10-19', [('09:00', '12:00', 'office', r), ('13:00', '15:30', 'office', r),
                                         ('15:30', '16:30', 'cae', m)], fill='other')
    n.samples = [s for s in n.samples if not (s['a'] >= '2026-10-19 16:30' and s['cls'] == 'other'
                                              and s['state'] == 'active')]
    n.samp('PC1', '2026-10-19 16:30', '2026-10-19 17:00', 'browser')
    n.samp('PC1', '2026-10-19 17:00', '2026-10-19 18:00', 'other', state='idle')
    n.pcon = [p for p in n.pcon if not p['a'].startswith('2026-10-19')]
    n.on('PC1', '2026-10-19 08:50', '2026-10-20 18:05')
    n.samp('PC1', '2026-10-19 18:00', '2026-10-20 09:00', 'other', state='locked')
    n.comp('PC1', '2026-10-19 16:30', '2026-10-20 04:00', 'cae', m)
    n.samp('PC1', '2026-10-20 09:00', '2026-10-20 09:10', 'mail')
    n.samp('PC1', '2026-10-20 09:10', '2026-10-20 10:00', 'cae', m)
    n.samp('PC1', '2026-10-20 10:00', '2026-10-20 12:00', 'office', r)
    n.samp('PC1', '2026-10-20 12:00', '2026-10-20 13:00', 'other', state='locked')
    n.samp('PC1', '2026-10-20 13:00', '2026-10-20 18:00', 'office', r)
    n.doc('2026-10-19 16:25', 'save', m)
    n.doc('2026-10-20 04:00', 'result', m)
    n.doc('2026-10-20 17:50', 'save', r)
    return n


# ───────────────────────── D. 심사 추가(extra) 시나리오 ─────────────────────────
@sc
def w43():
    """퇴근 후 AutoSave 문서 40분 편집(저장 이벤트 없음, 열린 문서 mtime 폴링만) → 업무 앱 전경 ≥15분 자격"""
    n = W('W43', '2026-10-15', '2026-10-15', AS_OF, '퇴근 후 AutoSave 40분')
    d = '제안서_과제J.docx'
    office_day(n, 'PC1', '2026-10-15', [('09:00', '12:00', 'office', d), ('13:00', '18:00', 'office', d)],
               after=('2026-10-15 22:00', 'locked'))
    n.samples = [s for s in n.samples if not (s['a'] == '2026-10-15 18:00')]
    n.samp('PC1', '2026-10-15 18:00', '2026-10-15 20:00', 'other', state='locked')
    n.samp('PC1', '2026-10-15 20:00', '2026-10-15 20:40', 'office', d)
    n.samp('PC1', '2026-10-15 20:40', '2026-10-15 22:00', 'other', state='locked')
    n.doc('2026-10-15 20:35', 'save', d, autosave=True)
    return n


@sc
def w43b():
    """AutoSave 문서의 완료 후보: W43 + 20:38 같은 stem PDF 내보내기 → 조용한 기간(autosaveQuietWd) + 내보내기 = E2h"""
    n = w43()
    n.name, n.note = 'W43b', 'W43 + PDF 내보내기(자동 저장 문서 E2)'
    n.doc('2026-10-15 20:38', 'export', '제안서_과제J.pdf')
    return n


@sc
def w44():
    """수락 회의 10~11 동안 노트북에서 다른 업무 능동 입력 60분 → 봉투 1h, 귀속 PC 업무, 불참 의심 큐"""
    n = W('W44', '2026-10-15', '2026-10-15', AS_OF, '회의 불참 의심')
    d = '도면검토_과제C.dwg'
    office_day(n, 'PC1', '2026-10-15', [('09:00', '10:00', 'cad', d), ('11:00', '12:00', 'cad', d)])
    n.samples = [s for s in n.samples if not (s['a'] == '2026-10-15 10:00' and s['cls'] == 'browser')]
    n.samp('LAP', '2026-10-15 10:00', '2026-10-15 11:00', 'cad', d)
    n.on('LAP', '2026-10-15 09:55', '2026-10-15 11:05')
    n.meet('2026-10-15 10:00', '2026-10-15 11:00', 'P7', ('P7', 'P8', 'ME'), ('품질', '회의'))
    n.doc('2026-10-15 11:55', 'save', d)
    return n


@sc
def w45():
    """공용 마스터 엑셀: 업무 3개(같은 주)가 '팀공용_마스터.xlsx' 를 함께 쓰고 각 보고에 첨부 → B_GENERIC"""
    n = W('W45', '2026-10-19', '2026-10-21', AS_OF, '공용 문서 → 최근 업무 쏠림 없음')
    mst = '팀공용_마스터.xlsx'
    tasks = [('M45a', 'P1', ('원가', '집계'), '원가집계_과제A.xlsx'),
             ('M45b', 'P2', ('일정', '조정'), '일정조정_과제B.xlsx'),
             ('M45c', 'P3', ('품질', '지표'), '품질지표_과제C.xlsx')]
    for i, (th, p, tk, _doc) in enumerate(tasks):
        n.msg(f'2026-10-19 {9 + i // 2:02d}:{(i % 2) * 30:02d}', 'in', 'request', th, p, tokens=tk)
    for day in ('2026-10-19', '2026-10-20', '2026-10-21'):
        office_day(n, 'PC1', day, [('09:00', '10:00', 'office', tasks[0][3]), ('10:00', '11:00', 'office', mst),
                                   ('11:00', '12:00', 'office', tasks[1][3]), ('13:00', '14:00', 'office', mst),
                                   ('14:00', '16:00', 'office', tasks[2][3]), ('16:00', '17:00', 'office', mst)])
        for t, dd in (('09:55', tasks[0][3]), ('10:55', mst), ('11:55', tasks[1][3]), ('15:55', tasks[2][3])):
            n.doc(f'{day} {t}', 'save', dd)
    for i, (th, p, tk, doc) in enumerate(tasks):
        n.msg(f'2026-10-21 17:{10 + i * 10}', 'out', 'report', th, p, atts=(doc, mst), tokens=tk)
    return n


@sc
def w46():
    """월 경계 자정 넘김: 9/30 23:00~10/1 01:30 같은 문서 + 01:20 보고 발신"""
    n = W('W46', '2026-09-30', '2026-10-01', AS_OF, '월 경계 자정 넘김')
    d = '월말정산_과제A.xlsx'
    n.msg('2026-09-30 10:00', 'in', 'request', 'M46', 'P1', tokens=('월말정산', '과제A'))
    office_day(n, 'PC1', '2026-09-30', [('10:10', '12:00', 'office', d)])
    n.pcon = [p for p in n.pcon if not p['a'].startswith('2026-09-30')]
    n.on('PC1', '2026-09-30 08:50', '2026-10-01 01:40')
    n.samp('PC1', '2026-09-30 18:00', '2026-09-30 23:00', 'other', state='locked')
    n.samp('PC1', '2026-09-30 23:00', '2026-10-01 01:30', 'office', d)
    n.doc('2026-09-30 23:50', 'save', d)
    n.doc('2026-10-01 01:10', 'save', d)
    n.msg('2026-10-01 01:20', 'out', 'report', 'M46', 'P1', atts=(d,), tokens=('월말정산',))
    return n


@sc
def w47a():
    """확인 응답 지속성(1회차): 자체 업무(의뢰·보고 신호 없음) + 사용자 확인 '지시 9/14 08:50, 대면 보고 9/16 17:00'"""
    n = W('W47a', '2026-09-14', '2026-09-16', '2026-09-30 18:00', '확인 응답 반영(1회차)')
    d = '점검표_과제H.xlsx'
    for day in ('2026-09-14', '2026-09-15', '2026-09-16'):
        office_day(n, 'PC1', day, [('09:00', '12:00', 'office', d)])
        n.doc(f'{day} 11:55', 'save', d)
    n.man('instr', a='2026-09-14 08:50', ref=d, key='Q-answer-1')
    n.man('report', a='2026-09-16 17:00', ref=d, key='Q-answer-2')
    return n


@sc
def w47b():
    """확인 응답 지속성(2회차): W47a + 클라우드PC 백필로 의뢰 메일(9/14 08:55) 발견 → S1 업무로 바뀌어도 응답(증거 키) 유지"""
    n = w47a()
    n.name, n.note = 'W47b', '재분석: 의뢰 메일 백필 → 업무 ID 바뀜, 응답은 문서군 키로 유지'
    n.msg('2026-09-14 08:55', 'in', 'request', 'M47', 'P1', tokens=('점검표', '과제H'))
    return n


@sc
def w48():
    """사적 앱 전경 30분(사적 사이트)이 근무창 안에 있음 → 마지막 단계 차감, 원장에 남김, 다른 업무로 옮겨 붙지 않음"""
    n = W('W48', '2026-10-20', '2026-10-20', AS_OF, '사적 사용 차감(R-P3)')
    d = '설계서_과제A.docx'
    office_day(n, 'PC1', '2026-10-20', [('09:00', '10:00', 'office', d), ('10:30', '12:00', 'office', d),
                                         ('13:00', '18:00', 'office', d)])
    n.samples = [s for s in n.samples if not (s['a'] == '2026-10-20 10:00')]
    n.samp('PC1', '2026-10-20 10:00', '2026-10-20 10:30', 'browser', priv='private')
    n.doc('2026-10-20 17:50', 'save', d)
    return n


@sc
def w49():
    """팀즈 '놓친 활동' 알림 메일만 있는 날(PC 기록 없음) → 존재 증거일 뿐 봉투 0"""
    n = W('W49', '2026-10-20', '2026-10-20', AS_OF, '놓친 활동 알림 메일만')
    for t in ('10:00', '14:00'):
        n.msg(f'2026-10-20 {t}', 'in', 'notice', f'N{t}', 'teams_notify', flags=('notice',), direct=False)
    return n


@sc
def w50():
    """같은 발신이 PC1 COM(정확 15:00)·클라우드PC 웹(date-only)에 둘 다, 다른 날 발신은 UTC 저장 의심"""
    n = W('W50', '2026-10-21', '2026-10-23', AS_OF, '정밀 사본 우선·UTC 의심')
    n.msg('2026-10-21 15:00', 'out', 'info', 'M50', 'P1', key='K50')
    n.msg('2026-10-21 12:00', 'out', 'info', 'M50', 'P1', prec='date', key='K50')
    for i, t in enumerate(('01:10', '02:05', '03:30', '05:40', '06:15', '07:20')):
        n.msg(f'2026-10-22 {t}', 'out', 'info', f'U{i}', 'P2')
    return n


@sc
def w50b():
    """W50 + 그 경로를 UTC 저장으로 확인(utc 표식) 후 time.envelope.mailTimeOffsetH=9 → 오전 근무 시간으로 옮겨짐"""
    n = w50()
    n.name, n.note = 'W50b', 'W50 + UTC 보정(+9h)'
    for m in n.msgs:
        if m['conv'].startswith('U'):
            m['flags'] = ('utc',)
    n.cfg = {'time.envelope.mailTimeOffsetH': 9}
    return n


@sc
def w51():
    """월 MM(2026-09, 평일 20일): 평일 8h, 연장 2일×2h, 토 4h, 연차 1, 오후반차 1, 9/22 야간 22~24"""
    import datetime as dt
    n = W('W51', '2026-09-01', '2026-09-30', '2026-09-30 23:59', '월 MM·초과(분모 160h)')
    d = dt.date(2026, 9, 1)
    doc = '양산지원_과제B.xlsx'
    while d <= dt.date(2026, 9, 30):
        s = d.isoformat()
        if d.weekday() < 5 and d not in (dt.date(2026, 9, 24), dt.date(2026, 9, 25)):
            if s == '2026-09-10':
                n.leave(s, 'full')
            elif s == '2026-09-17':
                n.leave(s, 'pm')
                office_day(n, 'PC1', s, [('09:00', '12:00', 'office', doc), ('13:00', '14:00', 'office', doc)])
                n.samples = [x for x in n.samples if not x['a'].startswith(s + ' 14')]
                n.samples = [x for x in n.samples if not (x['a'].startswith(s) and x['a'][11:13] in ('14', '15', '16', '17'))]
            else:
                office_day(n, 'PC1', s, [('09:00', '12:00', 'office', doc), ('13:00', '18:00', 'office', doc)])
            if s != '2026-09-10':
                n.doc(f'{s} 11:55', 'save', doc)
        d += dt.timedelta(1)
    for s in ('2026-09-08', '2026-09-15'):
        n.samp('PC1', f'{s} 18:00', f'{s} 20:00', 'office', doc)
        n.doc(f'{s} 19:55', 'save', doc)
    n.samp('PC1', '2026-09-19 13:00', '2026-09-19 17:00', 'cad', '치구도면_과제C.dwg')
    n.doc('2026-09-19 16:55', 'save', '치구도면_과제C.dwg')
    n.samp('PC1', '2026-09-22 22:00', '2026-09-23 00:00', 'cad', '치구도면_과제C.dwg')
    n.doc('2026-09-22 23:55', 'save', '치구도면_과제C.dwg')
    return n


@sc
def w52():
    """연차·반차: 연차 10/22 + 15:00 휴대폰 발신 1통, 오후반차 10/23 + 오전 근무 09~12·13~14"""
    n = W('W52', '2026-10-22', '2026-10-23', AS_OF, '연차 중 발신·반차')
    n.leave('2026-10-22', 'full')
    n.leave('2026-10-23', 'pm')
    n.msg('2026-10-22 15:00', 'out', 'info', 'M52', 'P1', tokens=('긴급', '회신'))
    d = '보고서_과제D.docx'
    n.samp('PC1', '2026-10-23 09:00', '2026-10-23 12:00', 'office', d)
    n.samp('PC1', '2026-10-23 13:00', '2026-10-23 14:00', 'office', d)
    n.on('PC1', '2026-10-23 08:50', '2026-10-23 14:05')
    n.doc('2026-10-23 13:55', 'save', d)
    return n


@sc
def w53():
    """주말·야간: 금 정상 + 금 23:00~토 01:00 수락 회의 + 토 13~17 문서 + 일 수신 3통만"""
    n = W('W53', '2026-10-16', '2026-10-18', AS_OF, '주말·야간 꼬리표')
    office_day(n, 'PC1', '2026-10-16', [('09:00', '12:00', 'office', '사양검토_과제A.docx'),
                                         ('13:00', '18:00', 'office', '사양검토_과제A.docx')])
    n.doc('2026-10-16 17:50', 'save', '사양검토_과제A.docx')
    n.meet('2026-10-16 23:00', '2026-10-17 01:00', 'P9', ('P9', 'ME'), ('고객사A', '화상회의'))
    n.samp('PC1', '2026-10-17 13:00', '2026-10-17 17:00', 'office', '주말작업_과제E.docx')
    n.doc('2026-10-17 16:55', 'save', '주말작업_과제E.docx')
    for t in ('10:00', '11:00', '12:00'):
        n.msg(f'2026-10-18 {t}', 'in', 'info', f'S{t}', 'P1')
    return n


@sc
def w54():
    """병행 3업무: 10/12 의뢰 X·Y·Z → 10/13 30분 단위 교차 편집(보존)"""
    n = W('W54', '2026-10-12', '2026-10-13', AS_OF, '병행 3업무 교차(X05)')
    docs = ['X_회로검토.docx', 'Y_원가표.xlsx', 'Z_시험계획.docx']
    for i, (th, tok) in enumerate((('MX', ('X', '회로검토')), ('MY', ('Y', '원가표')), ('MZ', ('Z', '시험계획')))):
        n.msg(f'2026-10-12 1{i}:00', 'in', 'request', th, f'P{i + 1}', tokens=tok)
    office_day(n, 'PC1', '2026-10-12')
    segs = []
    hh = [('09:00', '09:30'), ('09:30', '10:00'), ('10:00', '10:30'), ('10:30', '11:00'), ('11:00', '11:30'),
          ('11:30', '12:00'), ('13:00', '13:30'), ('13:30', '14:00'), ('14:00', '14:30'), ('14:30', '15:00'),
          ('15:00', '15:30'), ('15:30', '16:00'), ('16:00', '16:30'), ('16:30', '17:00'), ('17:00', '17:30'),
          ('17:30', '18:00')]
    for k, (a, b) in enumerate(hh):
        segs.append((a, b, 'office', docs[k % 3]))
        h, m = int(b[:2]), int(b[3:])
        tm = h * 60 + m - 2
        n.doc(f'2026-10-13 {tm // 60:02d}:{tm % 60:02d}', 'save', docs[k % 3])
    office_day(n, 'PC1', '2026-10-13', segs)
    return n


@sc
def w55():
    """커버리지 보류: W07 + 의뢰 후 메일 발신 수집이 10/16~10/23 막힘(blocked) → E3i 보류(OPEN)·Q03"""
    n = w07()
    n.name, n.note = 'W55', 'W07 + 메일 수집 결손 → 종료 판정 보류'
    import datetime as dt
    d = dt.date(2026, 10, 16)
    while d <= dt.date(2026, 10, 23):
        n.coverage[(d.isoformat(), 'mail_out')] = 'blocked'
        d += dt.timedelta(1)
    return n


@sc
def w56():
    """V25 무증거 배분(L6): 직접 증거 A 3h·B 1h, 14~18 브라우저 4h → A 6h·B 2h"""
    n = W('W56', '2026-10-20', '2026-10-20', '2026-10-20 18:00', '직접 증거 비례 배분(A S16)')
    a, b = '회로검토_과제A.docx', '견적비교_과제B.xlsx'
    n.msg('2026-10-20 08:30', 'in', 'request', 'M56a', 'P1', tokens=('회로검토', '과제A'))
    n.msg('2026-10-20 08:40', 'in', 'request', 'M56b', 'P2', tokens=('견적비교', '과제B'))
    office_day(n, 'PC1', '2026-10-20', [('09:00', '12:00', 'office', a), ('13:00', '14:00', 'office', b),
                                         ('14:00', '18:00', 'browser', '')])
    n.doc('2026-10-20 11:55', 'save', a)
    n.doc('2026-10-20 13:55', 'save', b)
    return n


@sc
def w42b():
    """W42 와 같은 입력, 솔버 cap 옵션(LM24 호환: 창 밖 연산 밤당 4h, 사람 흔적 있으면 상한 해제)"""
    n = w42()
    n.name, n.note = 'W42b', 'W42 + solverMode=cap(옵션)'
    n.cfg = {'time.envelope.solverMode': 'cap'}
    return n


@sc
def w24b():
    """과제 레지스트리 일치가 약한 토큰 연결을 보강: '과제A 일정' 의뢰 ↔ '과제A_마일스톤.xlsx'(같은 과제 ID)"""
    n = W('W24b', '2026-10-22', '2026-10-22', AS_OF, '과제 ID 일치 +0.7 로 연결')
    n.msg('2026-10-22 09:10', 'in', 'request', 'M24c', 'P7', tokens=('과제A', '일정', '갱신'), proj='P-0001')
    office_day(n, 'PC1', '2026-10-22', [('09:30', '12:00', 'office', '과제A_마일스톤.xlsx')])
    n.doc('2026-10-22 11:55', 'save', '과제A_마일스톤.xlsx', proj='P-0001')
    return n


@sc
def w26b():
    """퇴근 후 18:30~18:45 브라우저(업무 앱 아님) → 18:55 메일 발신(샘플러 없는 휴대폰): 산출물 ±15분 근접 자격"""
    n = W('W26b', '2026-10-27', '2026-10-27', AS_OF, '창 밖 일반 앱 + 15분 안 발신')
    office_day(n, 'PC1', '2026-10-27', [('09:00', '12:00', 'office', '사양서.docx'),
                                         ('13:00', '18:00', 'office', '사양서.docx')], after=('2026-10-27 20:00', 'locked'))
    n.samples = [x for x in n.samples if not (x['a'] == '2026-10-27 18:00')]
    n.samp('PC1', '2026-10-27 18:00', '2026-10-27 18:30', 'other', state='locked')
    n.samp('PC1', '2026-10-27 18:30', '2026-10-27 18:45', 'browser')
    n.samp('PC1', '2026-10-27 18:45', '2026-10-27 20:00', 'other', state='locked')
    n.msg('2026-10-27 18:55', 'out', 'info', 'M26b', 'P2', tokens=('사양서',))
    return n


@sc
def w48b():
    """창 밖 사적 단절(R-P4): 19:00 저장 → 19:10~19:25 사적 앱 → 19:45 발신, 그 사이 샘플러 없음 19:05~19:10"""
    n = W('W48b', '2026-10-27', '2026-10-27', AS_OF, '퇴근 후 사적 사용이 다리를 끊음')
    d = '설계서_과제A.docx'
    office_day(n, 'PC1', '2026-10-27', [('09:00', '12:00', 'office', d), ('13:00', '18:00', 'office', d)])
    n.samp('PC2', '2026-10-27 18:40', '2026-10-27 19:05', 'office', d)
    n.doc('2026-10-27 19:00', 'save', d, pc='PC2')
    n.samp('PC2', '2026-10-27 19:10', '2026-10-27 19:25', 'browser', priv='private')
    n.msg('2026-10-27 19:45', 'out', 'info', 'M48b', 'P2', tokens=('설계서',))
    return n


# ───────────────────────── E. 신호 품질·옵션 키 시나리오 ─────────────────────────
@sc
def w57():
    """고착 샘플러: PC1 샘플러가 24시간 '능동·유휴 0초'로만 기록(TickCount 고착) + 저장 10:00·15:00, PC 08:50~18:05"""
    n = W('W57', '2026-10-27', '2026-10-27', AS_OF, '고착 PC·날 폐기 → 하한 폴백')
    for h in range(24):
        n.samp('PC1', f'2026-10-27 {h:02d}:00', f'2026-10-27 {h:02d}:59', 'other', idle=0)
    n.on('PC1', '2026-10-27 08:50', '2026-10-27 18:05')
    n.doc('2026-10-27 10:00', 'save', '점검일지_과제E.xlsx')
    n.doc('2026-10-27 15:00', 'save', '점검일지_과제E.xlsx')
    return n


@sc
def w58a():
    """미정(tentative) 회의 19:00~20:00, 회의 창 근거 없음 → 미산입 + Q15"""
    n = W('W58a', '2026-10-28', '2026-10-28', AS_OF, '미정 회의, 참석 근거 없음')
    office_day(n, 'PC1', '2026-10-28', [('09:00', '12:00', 'office', '시험보고_과제F.docx'),
                                         ('13:00', '18:00', 'office', '시험보고_과제F.docx')])
    n.doc('2026-10-28 17:50', 'save', '시험보고_과제F.docx')
    n.meet('2026-10-28 19:00', '2026-10-28 20:00', 'P3', ('P3', 'ME'), ('해외', '고객사A'), status='tentative')
    return n


@sc
def w58b():
    """W58a + 회의 창(온라인 회의 전경) 19:00~19:45 → 참석 근거 50% 이상 → 회의 1h 산입(연장)"""
    n = w58a()
    n.name, n.note = 'W58b', '미정 회의 + 회의 창 45분'
    n.samp('PC1', '2026-10-28 19:00', '2026-10-28 19:45', 'meet')
    return n


@sc
def w59():
    """저녁 식사 시간: 18:00 퇴근(샘플러 끝) → 18:50 저장(샘플러 없는 PC9) → 19:30 메일 발신"""
    n = W('W59', '2026-10-21', '2026-10-21', AS_OF, '저녁 식사 시간 차감')
    d = '발표자료_과제G.pptx'
    office_day(n, 'PC1', '2026-10-21', [('09:00', '12:00', 'office', d), ('13:00', '18:00', 'office', d)])
    n.doc('2026-10-21 18:50', 'save', d, pc='PC9')
    n.msg('2026-10-21 19:30', 'out', 'info', 'M59', 'P2', tokens=('발표자료',))
    return n


@sc
def w52b():
    """오전 반차(10/26, 09~14 휴가) + 10:30~11:30 문서 작업(휴가 중 근무) + 14:00~18:00 정규 작업"""
    n = W('W52b', '2026-10-26', '2026-10-26', AS_OF, '오전 반차 + 휴가 중 근무')
    n.leave('2026-10-26', 'am')
    d = '견적서_과제H.xlsx'
    n.samp('PC1', '2026-10-26 10:30', '2026-10-26 11:30', 'office', d)
    n.samp('PC1', '2026-10-26 14:00', '2026-10-26 18:00', 'office', d)
    n.on('PC1', '2026-10-26 10:25', '2026-10-26 18:05')
    n.doc('2026-10-26 11:25', 'save', d)
    n.doc('2026-10-26 17:55', 'save', d)
    return n


@sc
def w60():
    """정규창 안 샘플러 공백 50분(잠그지 않음, 유휴) — PC 내부 다리(≤60분)로 잇는다"""
    n = W('W60', '2026-10-27', '2026-10-27', AS_OF, '샘플러 유휴 50분 다리')
    d = '회로검토_과제I.docx'
    office_day(n, 'PC1', '2026-10-27', [('09:00', '10:00', 'office', d), ('10:50', '12:00', 'office', d),
                                         ('13:00', '18:00', 'office', d)])
    n.samples = [x for x in n.samples if not (x['a'] == '2026-10-27 10:00')]
    n.samp('PC1', '2026-10-27 10:00', '2026-10-27 10:50', 'other', state='idle')
    n.doc('2026-10-27 17:55', 'save', d)
    return n


@sc
def w61():
    """원격 연결 다리: 클라우드PC 22:00~22:50 문서 → 연결 끊김 → 00:05 휴대폰 회신(같은 문서 첨부, 55분 공백)"""
    n = W('W61', '2026-10-28', '2026-10-29', AS_OF, '원격 연결 다리(≤60분, 같은 연결 키)')
    d = '대응방안_고객사A.docx'
    office_day(n, 'PC1', '2026-10-28', [('09:00', '12:00', 'office', d), ('13:00', '18:00', 'office', d)])
    n.samp('CPC', '2026-10-28 22:00', '2026-10-28 22:50', 'office', d)
    n.samp('CPC', '2026-10-28 22:50', '2026-10-29 01:00', 'other', state='disconnected')
    n.doc('2026-10-28 22:45', 'save', d, pc='CPC')
    n.msg('2026-10-29 00:05', 'out', 'report', 'M61', 'P1', atts=(d,), tokens=('대응방안',))
    office_day(n, 'PC1', '2026-10-29', [('09:00', '12:00', 'office', '주간보고_과제A.xlsx')])
    return n


@sc
def w62():
    """V2: PC 기록 없는 평일, 직접 수신 8통(40분 간격)만 → 수신 크레딧 5분×8 = 40분(하루 상한 60분)"""
    n = W('W62', '2026-10-27', '2026-10-27', AS_OF, '수신만·PC 없음')
    for k in range(8):
        mm = 9 * 60 + 10 + k * 40
        if 12 * 60 <= mm < 13 * 60:
            mm += 60
        n.msg(f'2026-10-27 {mm // 60:02d}:{mm % 60:02d}', 'in', 'info', f'R{k}', 'P1')
    return n


@sc
def w64():
    """부분월·오늘 경과 비율: 10/1~10/14 분석, 분석 시각 10/14 13:30, 평일 8h + 오늘 오전 3h"""
    import datetime as dt
    n = W('W64', '2026-10-01', '2026-10-14', '2026-10-14 13:30', '부분월 분모·가용(오늘 0.5일)')
    d = dt.date(2026, 10, 1)
    doc = '양산이관_과제B.xlsx'
    while d <= dt.date(2026, 10, 13):
        if not calendar().is_holiday(d):
            office_day(n, 'PC1', d.isoformat(), [('09:00', '12:00', 'office', doc), ('13:00', '18:00', 'office', doc)])
            n.doc(f'{d.isoformat()} 17:55', 'save', doc)
        d += dt.timedelta(1)
    n.samp('PC1', '2026-10-14 09:00', '2026-10-14 12:00', 'office', doc)
    n.on('PC1', '2026-10-14 08:50', '2026-10-14 13:30')
    n.doc('2026-10-14 11:55', 'save', doc)
    return n


@sc
def w63():
    """자체 업무 문서군 병합: '열해석_모델.cas'(월) → 다음 날 '열해석_결과정리.xlsx' → 토큰 유사(≥0.5)·3일 안 → 한 자체 업무"""
    n = W('W63', '2026-10-26', '2026-10-27', AS_OF, '자체 업무 병합(토큰·3일)')
    office_day(n, 'PC1', '2026-10-26', [('13:00', '17:00', 'cae', '열해석_모델.cas')])
    office_day(n, 'PC1', '2026-10-27', [('09:00', '12:00', 'office', '열해석_결과정리.xlsx')])
    n.doc('2026-10-26 16:55', 'save', '열해석_모델.cas')
    n.doc('2026-10-27 11:55', 'save', '열해석_결과정리.xlsx')
    return n


@sc
def w65a():
    """심사 퍼즈 반례(seed 7 #6) 기준: PC 13~19만 가동(샘플러 없음), 09:07 발신 + 14~15 수락 회의 + 21:30 발신"""
    n = W('W65a', '2026-10-28', '2026-10-28', AS_OF, '퍼즈 반례 기준(PC 13~19)')
    n.on('PC1', '2026-10-28 13:00', '2026-10-28 19:00')
    n.msg('2026-10-28 09:07', 'out', 'info', 'M65a', 'P1', tokens=('일정',))
    n.meet('2026-10-28 14:00', '2026-10-28 15:00', 'P1', ('P1', 'ME', 'P3'), ('과제A', '리뷰'))
    n.msg('2026-10-28 21:30', 'out', 'info', 'M65b', 'P1', tokens=('일정',))
    return n


@sc
def w65b():
    """W65a 에서 PC 가동 기록을 뺀 것 → 봉투가 늘면 안 된다(원본 A: 6.08h → 9.17h 증가 결함)"""
    n = w65a()
    n.name, n.note = 'W65b', 'W65a − PC 가동 기록'
    n.pcon = []
    return n


@sc
def w66():
    """V14 항상 켜진 PC: 48h 연속 가동(샘플러 없음), 저장 10:00·13:30·17:00 → 흔적 범위 ±25분 하한"""
    n = W('W66', '2026-10-28', '2026-10-28', AS_OF, '항상 켜진 PC(≥20h)')
    n.on('PC1', '2026-10-27 09:00', '2026-10-29 09:00')
    for t in ('10:00', '13:30', '17:00'):
        n.doc(f'2026-10-28 {t}', 'save', '도면_과제C.dwg')
    return n


@sc
def w67a():
    """이름이 다른 산출 문서: '검증 절차 작성' 의뢰 ↔ 작업 문서 '과제J_검증서.docx'(토큰 불일치) → 연결 안 됨(미착수 Z + 자체 업무)"""
    n = W('W67a', '2026-10-29', '2026-10-29', AS_OF, '연결 키 없음(확인 전)')
    n.msg('2026-10-29 09:10', 'in', 'request', 'M67', 'P8', tokens=('검증', '절차', '작성'), key='K67')
    office_day(n, 'PC1', '2026-10-29', [('09:30', '12:00', 'office', '과제J_검증서.docx'),
                                         ('13:00', '17:00', 'office', '과제J_검증서.docx')])
    n.doc('2026-10-29 11:55', 'save', '과제J_검증서.docx')
    n.doc('2026-10-29 16:55', 'save', '과제J_검증서.docx')
    return n


@sc
def w67b():
    """W67a + 확인 응답 '같은 업무'(must_link, 증거 키 = 의뢰 msg_key K67 · 문서군) → 의뢰 업무로 합쳐짐(재분석에도 유지)"""
    n = w67a()
    n.name, n.note = 'W67b', 'must_link 응답(증거 키) 반영'
    n.man('must_link', ref='과제J_검증서.docx', key='K67')
    return n
