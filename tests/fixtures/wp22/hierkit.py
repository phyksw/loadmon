# -*- coding: utf-8 -*-
r"""WP-22 시험 도우미 — 합성 레지스트리(H §15.1 골든 — 자리표시자만) · 특징 작성기 · 가짜 키 함수 · 임시 트리 · 가짜 모듈.

- `golden_reg(cfg)` = H §15.1 합성 레지스트리: P-0007 과제A(DEV, 별칭 '과제A 모듈', 코드네임 'PROJ-A', 키워드 브라켓·광학모듈,
  고객 C01, 메일 도메인 custa.example, 폴더 '과제A_설계', 기본 분야 OPT) · P-0008 과제B(MP, PROJ-B, 양산라인·수율개선, C01,
  never '과제B 후속') · P-0011 과제C(AX) · P-0012 과제D(EXT) · P-0013 과제E(퇴역, merged_into P-0007, PROJ-E).
- 폴더·문서군 키는 키링 대신 무키 해시(`fake_folder`·`fake_doc`) — 시험 전용, 실제 키가 아니다.
- `install_fakes()` — 아직 없는 다른 작업 패키지 모듈(정규화 `lm27.normalize.absence` 등)을 계약 시그니처대로 가짜로 채운다.
  실물 파일이 있고 import 되면 실물을 쓴다. 가짜는 이 시험 안에만 있다(계획 §4).
- `TmpTree` — `%TEMP%` 아래 임시 루트(lm27t_wp22_ 접두)와 `Paths`(LAD 도 그 아래). 실제 사용자 폴더를 건드리지 않는다.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SETTINGS = ROOT / "config" / "settings_registry.json"
CALENDAR = ROOT / "config" / "calendar.json"
GOLDEN = Path(__file__).with_name("golden.json")

GOLDEN_TEAM = {
    "schema": "lm27.registry/1", "version": 7,
    "projects": [
        {"id": "P-0007", "name": "과제A", "domain": "DEV", "aliases": ["과제A 모듈"], "codenames": ["PROJ-A"],
         "keywords": ["브라켓", "광학모듈"], "customers": ["C01"], "mail_domains": ["custa.example"],
         "folders": ["과제A_설계"], "default_field": "OPT", "copilot_desc": "광학 모듈 신규 개발"},
        {"id": "P-0008", "name": "과제B", "domain": "MP", "codenames": ["PROJ-B"], "keywords": ["양산라인", "수율개선"],
         "customers": ["C01"], "never": ["과제B 후속"], "copilot_desc": "센서 모듈 양산 대응"},
        {"id": "P-0011", "name": "과제C", "domain": "AX", "keywords": ["자동분류"], "copilot_desc": "메일 자동 분류 도구"},
        {"id": "P-0012", "name": "과제D", "domain": "EXT", "keywords": ["산학과제"], "copilot_desc": "대학 공동연구 지원"},
        {"id": "P-0013", "name": "과제E", "domain": "DEV", "status": "retired", "merged_into": "P-0007",
         "codenames": ["PROJ-E"]},
    ],
    "customers": [{"id": "C01", "names": ["고객사A"], "domains": ["custa.example"]}],
}


def fake_folder(seg) -> str:
    from lm27.hier.registry import seg_norm
    return "s" + hashlib.sha256(("dir|seg:" + seg_norm(seg)).encode("utf-8")).hexdigest()[:16]


def fake_doc(name) -> str:
    return "d" + hashlib.sha256(("doc|" + str(name)).encode("utf-8")).hexdigest()[:16]


def fake_who(s) -> str:
    return "w" + hashlib.sha256(("who|" + str(s)).encode("utf-8")).hexdigest()[:16]


def fake_key(prefix: str, s, n: int = 16) -> str:
    return prefix + hashlib.sha256((prefix + "|" + str(s)).encode("utf-8")).hexdigest()[:n]


def fake_unit_id(k, kind="") -> str:
    return "u_" + hashlib.sha256(("unit|" + str(k)).encode("utf-8")).hexdigest()[:10]


# ───────────────────────── 가짜 모듈 ─────────────────────────
def _fake_meet_category(row) -> str:
    hint = row.get("abs_hint")
    if hint == "trip":
        return "trip"
    if hint in ("leave", "half", "half_am", "half_pm", "sick"):
        return "leave"
    if row.get("location_class") == "external":
        return "offsite"
    return ""


FAKES = (("lm27.normalize.absence", ("lm27", "normalize", "absence.py"), "meet_category", _fake_meet_category),)
INSTALLED: dict[str, str] = {}


def _real_ok(modname: str, rel: tuple, attr: str) -> bool:
    if not ROOT.joinpath(*rel).is_file():
        return False
    try:
        mod = importlib.import_module(modname)
    except Exception:              # 다른 작업 패키지 실물이 아직 불완전 — 시험 전용 가짜로 대체
        return False
    return callable(getattr(mod, attr, None))


def install_fakes() -> dict[str, str]:
    """없는 계약 함수를 가짜로 채운다(멱등). {모듈: real|fake}."""
    for modname, rel, attr, fn in FAKES:
        if modname in INSTALLED:
            continue
        if _real_ok(modname, rel, attr):
            INSTALLED[modname] = "real"
            continue
        parent, _, leaf = modname.rpartition(".")
        pm = importlib.import_module(parent)
        m = types.ModuleType(modname)
        setattr(m, attr, fn)
        m.LM27_FAKE = True
        sys.modules[modname] = m
        setattr(pm, leaf, m)
        INSTALLED[modname] = "fake"
    return dict(INSTALLED)


# ───────────────────────── 설정·레지스트리·특징 ─────────────────────────
_CFG = []


def cfg(over: dict | None = None):
    """선언 기본값 설정(개인 config.json 없음). over = 덮어쓰기(엄격)."""
    from lm27.config import Cfg, load_registry
    if not over:
        if not _CFG:
            _CFG.append(Cfg(load_registry(SETTINGS)))
        return _CFG[0]
    return Cfg(load_registry(SETTINGS)).derive(over)


def fresh_cfg(over: dict | None = None):
    """읽힘 기록이 빈 새 설정(cfg_used·read-check 시험용)."""
    from lm27.config import Cfg, load_registry
    c = Cfg(load_registry(SETTINGS))
    return c.derive(over) if over else c


def golden_reg(c=None, *, learned=(), team=None, local=None, person_key=None):
    from lm27.hier.registry import merge
    return merge(GOLDEN_TEAM if team is None else team, local, c if c is not None else cfg(), learned=learned,
                 folder_key=fake_folder, doc_key=fake_doc, person_key=person_key, source="cache")


def empty_reg(c=None):
    from lm27.hier.registry import builtin_registry
    return builtin_registry(c if c is not None else cfg())


def mk_team(n: int) -> dict:
    """과제 n 개 레지스트리(H §15 HG29 — 설명 20자, 영역 순환)."""
    doms = ["DEV", "MP", "EXT", "COM", "AX"]
    ps = [{"id": f"P-{i:04d}", "name": f"과제{i}", "domain": doms[i % 5],
           "copilot_desc": ("광학 모듈 신규 개발 과제 설명 " + str(i))[:20]} for i in range(1, n + 1)]
    return {"schema": "lm27.registry/1", "version": 1, "projects": ps}


def F(id: str, kind: str, text: str = "", **kw):
    """정제문 한 줄 → 특징(상용구 = 선언 기본값)."""
    from lm27.hier.features import feat
    from lm27.hier.match import boilerplate
    return feat(id, kind, text, boiler=boilerplate(cfg()), **kw)


def U(uid: str, kind: str, ev, **kw):
    from lm27.hier.unitlabel import make_unit
    return make_unit(uid, kind, ev, **kw)


def golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def canon(obj) -> bytes:
    from lm27.util.fsx import canon_bytes
    return canon_bytes(obj)


# ───────────────────────── 임시 트리 ─────────────────────────
class TmpTree:
    """%TEMP%\\lm27t_wp22_<rand>\\ — 프로그램 폴더 모양(data\\) + LAD. with 로 쓰면 끝에 지운다."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm27t_wp22_"))
        (self.root / "data").mkdir()
        from lm27.paths import Paths
        self.paths = Paths(self.root, lad=self.root / "lad")

    def __enter__(self) -> TmpTree:
        return self

    def __exit__(self, *exc) -> None:
        self.remove()

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write_json(self, path, obj) -> None:
        from lm27.util.fsx import atomic_write, canon_bytes
        atomic_write(path, canon_bytes(obj))


# ───────────────────────── 합성 저장 행(분류 입력) ─────────────────────────
_SEQ = [0]


def _rid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def row(kind: str, src: str, ts: str, **kw) -> dict:
    """정제 후 저장 행 하나(계약 §3.1 공통 봉투 + kind 열). 키·텍스트는 호출자가 준다(자리표시자만)."""
    r = {"id": kw.pop("id", None) or _rid(kind, src, ts, kw.get("msg_key"), kw.get("doc_key"), kw.get("subject_masked"),
                                          kw.get("name_masked"), kw.get("title_masked")),
         "kind": kind, "src": src, "pc_id": "pc_" + "a" * 16, "ts_utc": ts, "ts_local_offset": "+09:00",
         "ts_precision": kw.pop("ts_precision", "minute"), "act": kw.pop("act", ""), "priv_class": kw.pop("priv_class", "work"),
         "observed_at": ts, "rules_ver": "2026.10.0", "kid": "k" + "0" * 8}
    r.update(kw)
    return r
