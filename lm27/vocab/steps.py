# -*- coding: utf-8 -*-
"""단계 유형 어휘 단일원(R §3.3 · 부록 A, 계약 §2.11 · §3.19 · §6.6 · X-241).

과정 마이닝의 닫힌 어휘 22종. 시간 코어(`attrib.obs`)·보고서·브리지 프롬프트·팀 레지스트리 기본값이 모두
이 모듈 하나를 읽는다. 팀 레지스트리 `vocab.step_types` 는 이 코드 목록을 쓰고, 항목 객체의
`tool_access`(0~2)·`verifiable`(0~2)·`kind`(M|A)·`cls` 로 기본값을 덮는다(X-241 — 옛 `step_tool_access` ·
`step_verifiable` · `step_type_names` 사전 형식은 폐지).

- `STEP_TYPES`: 코드 → `StepType(name, kind, cls, tool_default, verify_default, order)`(표 순서 = 정렬 순서).
- `CLASSES`: 단계 묶음 7종(소통·회의·문서·공학·코드·조사·오프라인).
- `ext_class(ext)`: 확장자 → 확장자군 'doc'|'ppt'|'xls'|'pdf'|'txt'|'cad'|'code'|''.
- `obs_of(level, cls, ext_cls, anchor_kind, meeting_role)`: 귀속 조각 → 구간 단계 코드('' = 단계 아님).
- `tool_access(code, registry)` · `verifiable(code, registry)`: 레지스트리 덮어쓰기를 반영한 0~2 점수.

표준 라이브러리만 쓴다.
"""
import re
from collections.abc import Mapping
from typing import NamedTuple


class StepType(NamedTuple):
    name: str               # 한글명(프롬프트·화면 — '코드 한글명' 쌍)
    kind: str               # 'M' 점(milestone, 소요 0) | 'A' 구간(activity, 귀속 분)
    cls: str                # 묶음(CLASSES 중 하나)
    tool_default: int       # 도구 접근 기본(§4.8 TOOL) 0~2
    verify_default: int     # 검증 가능성 기본(§4.8 VER) 0~2
    order: int              # 표 순서(정렬·동시각 점 단계의 순번)


CLASSES: tuple[str, ...] = ("소통", "회의", "문서", "공학", "코드", "조사", "오프라인")

_TABLE = (  # 코드, 한글명, 종류, 묶음, 도구 접근, 검증 가능성 — R §3.3 표 순서
    ("REQ_IN", "의뢰 수신", "M", "소통", 2, 0),
    ("REQ_OUT", "지시 발신", "M", "소통", 2, 0),
    ("ACK_OUT", "수락 회신", "M", "소통", 2, 1),
    ("REPORT_OUT", "보고 발신", "M", "소통", 2, 1),
    ("REPORT_IN", "보고 수신", "M", "소통", 2, 1),
    ("COMM", "메일·채팅 작성", "A", "소통", 2, 1),
    ("MEET", "회의", "A", "회의", 0, 0),
    ("REVIEW", "검토 회의", "A", "회의", 0, 0),
    ("DOC_DOC", "문서 작성", "A", "문서", 2, 1),
    ("DOC_PPT", "발표 자료", "A", "문서", 2, 1),
    ("DOC_XLS", "표 계산", "A", "문서", 2, 2),
    ("DOC_PDF", "PDF 검토", "A", "문서", 2, 1),
    ("DOC_ETC", "기타 문서", "A", "문서", 1, 1),
    ("APP_CAD", "설계 프로그램", "A", "공학", 1, 1),
    ("APP_CAE", "해석 프로그램", "A", "공학", 1, 2),
    ("APP_SIM", "시뮬레이터", "A", "공학", 1, 2),
    ("APP_EDA", "회로 설계 도구", "A", "공학", 1, 2),
    ("APP_IDE", "개발 도구", "A", "코드", 2, 2),
    ("APP_ENG", "기타 공학 도구", "A", "공학", 1, 1),
    ("COMMIT", "코드 커밋", "A", "코드", 2, 2),
    ("WEB", "웹 자료 조사", "A", "조사", 2, 1),
    ("OFFLINE", "오프라인 업무", "A", "오프라인", 0, 0),
)

STEP_TYPES: dict[str, StepType] = {c: StepType(n, k, g, t, v, i) for i, (c, n, k, g, t, v) in enumerate(_TABLE)}
STEP_ORDER: tuple[str, ...] = tuple(c for c, *_ in _TABLE)
POINT_STEPS: frozenset[str] = frozenset(c for c, s in STEP_TYPES.items() if s.kind == "M")
ACTIVITY_STEPS: frozenset[str] = frozenset(c for c, s in STEP_TYPES.items() if s.kind == "A")
SCORE_RANGE = (0, 1, 2)

# ── 확장자 → 확장자군(R §3.3 '근거' 열의 목록이 기본값) ─────────────────────────
EXT_CLASSES: tuple[str, ...] = ("doc", "ppt", "xls", "pdf", "txt", "cad", "code")
_EXT_TABLE = {
    "doc": ("doc", "docx", "hwp", "hwpx", "odt", "rtf"),
    "ppt": ("ppt", "pptx", "odp"),
    "xls": ("xls", "xlsx", "xlsm", "xlsb", "csv", "ods"),
    "pdf": ("pdf",),
    "txt": ("txt", "md", "xml", "json", "yaml", "ini", "log"),
    "cad": ("prt", "asm", "sldprt", "sldasm", "dwg", "dxf", "step", "stp", "igs", "iges", "catpart", "catproduct",
            "ipt", "iam", "x_t"),
    "code": ("py", "c", "h", "cpp", "hpp", "cs", "java", "js", "ts", "m", "v", "sv", "vhd", "vhdl", "ipynb", "sql",
             "ps1", "bat"),
}
EXT_CLASS: dict[str, str] = {e: g for g, exts in _EXT_TABLE.items() for e in exts}
_EXT_RX = re.compile(r"^[0-9a-z_]{1,10}$")
_CREO_VER = re.compile(r"^([0-9a-z_]+)\.\d+$")          # Creo 판번호 꼬리(part.prt.12 → prt)

# 확장자군 → 문서 단계
_DOC_STEP = {"doc": "DOC_DOC", "ppt": "DOC_PPT", "xls": "DOC_XLS", "pdf": "DOC_PDF", "txt": "DOC_ETC",
             "cad": "APP_CAD", "code": "APP_IDE"}
# 앱 분류(W Samp.cls · CP title_class) → 구간 단계. office·pdf·viewer 는 확장자군으로 정한다.
_APP_STEP = {"cad": "APP_CAD", "cae": "APP_CAE", "sim": "APP_SIM", "eda": "APP_EDA", "ide": "APP_IDE",
             "eng": "APP_ENG", "mail": "COMM", "mail_work": "COMM", "chat": "COMM", "chat_work": "COMM",
             "meet": "MEET", "meeting": "MEET", "browser": "WEB", "work_site": "WEB"}
_DOC_APPS = frozenset({"office", "pdf", "viewer"})
# L4 앵커 종류 → 단계(R §3.3: 발신 → COMM, 저장·내보내기 → 확장자군, 솔버 제출 → APP_CAE, 커밋 → COMMIT)
_ANCHOR_STEP = {"send": "COMM", "commit": "COMMIT", "submit": "APP_CAE", "solver": "APP_CAE"}
_SAVE_ANCHORS = frozenset({"save", "export"})


def _norm_ext(ext) -> str:
    e = str(ext or "").strip().lower().lstrip(".")
    m = _CREO_VER.match(e)
    if m:
        e = m.group(1)
    return e if _EXT_RX.match(e) else ""


def ext_class(ext, extra: Mapping | None = None) -> str:
    """확장자(점 있어도 됨, 대소문자 무시) → 확장자군. 모르면 ''.

    extra = `report.mining.extClassExtra`{ext: class} — **추가만** 된다(기본 표의 확장자는 바꾸지 않음 — 결정성).
    """
    e = _norm_ext(ext)
    if not e:
        return ""
    g = EXT_CLASS.get(e)
    if g:
        return g
    if extra:
        g = extra.get(e, extra.get("." + e))
        if isinstance(g, str) and g in EXT_CLASSES:
            return g
    return ""


def _level(level) -> str:
    s = str(level or "").strip().upper()
    if s[:1] == "L" and s[1:2].isdigit():
        return s[:2]
    if s.isdigit():
        return "L" + s[:1]
    return ""


def obs_of(level, cls, ext_cls, anchor_kind, meeting_role) -> str:
    """시간 코어 귀속 조각 하나 → 구간 단계 코드(R §3.3 · §4.1, 요청 W-1). 단계가 아니면 ''.

    level: 'L1'~'L7'(꼬리표가 붙어 있어도 앞 두 글자만 본다) · cls: 앱 분류(W `Samp.cls` 또는 CP `title_class`)
    ext_cls: `ext_class()` 결과 · anchor_kind: L4 앵커 종류(send·save·export·submit·solver·commit)
    meeting_role: L2 회의가 그 업무의 검토 회의(S2m·E3c 회의·검토 낱말)이면 'review'.
    L5(흡수·공백·하한근접)·L6(비례)·L7(버킷)은 관측 단계가 없다(R §4.1.3).
    """
    lv = _level(level)
    c = str(cls or "").strip().lower()
    g = str(ext_cls or "").strip().lower()
    if lv == "L1":
        return "OFFLINE"
    if lv == "L2":
        return "REVIEW" if str(meeting_role or "").strip().lower() == "review" else "MEET"
    if lv == "L3":
        step = _APP_STEP.get(c)
        if step:
            return step
        if g in _DOC_STEP:
            return _DOC_STEP[g]
        if c in _DOC_APPS:
            return "DOC_ETC"                 # 문서 앱인데 확장자군 미상 — '미상 확장자의 문서 키'
        return ""
    if lv == "L4":
        a = str(anchor_kind or "").strip().lower()
        if a in _ANCHOR_STEP:
            return _ANCHOR_STEP[a]
        if a in _SAVE_ANCHORS:
            return _DOC_STEP.get(g, "DOC_ETC")
        return ""
    return ""


def _override(code: str, registry, field: str) -> int | None:
    """레지스트리(원본 dict 의 vocab.step_types 객체 목록, 또는 유효 레지스트리의 vocab 사전)의 0~2 덮어쓰기."""
    if registry is None:
        return None
    if isinstance(registry, Mapping):
        vocab = registry.get("vocab")
        items = vocab.get("step_types") if isinstance(vocab, Mapping) else None
        if isinstance(items, list):
            for it in items:
                if isinstance(it, Mapping) and it.get("code") == code:
                    v = it.get(field)
                    return v if type(v) is int and v in SCORE_RANGE else None
        return None
    vocab = getattr(registry, "vocab", None)
    table = vocab.get("step_types") if isinstance(vocab, Mapping) else None
    item = table.get(code) if isinstance(table, Mapping) else None
    v = getattr(item, field, None)
    return v if type(v) is int and v in SCORE_RANGE else None


def tool_access(code: str, registry=None) -> int:
    """도구 접근 점수 0~2(§4.8 TOOL). 팀 레지스트리 항목의 `tool_access` 가 있으면 그것, 없으면 기본값.
    모르는 코드는 0(사람의 자리 — 보수적)."""
    v = _override(code, registry, "tool_access")
    if v is not None:
        return v
    st = STEP_TYPES.get(code)
    return st.tool_default if st else 0


def verifiable(code: str, registry=None) -> int:
    """검증 가능성 점수 0~2(§4.8 VER). 팀 레지스트리 항목의 `verifiable` 이 있으면 그것, 없으면 기본값.
    모르는 코드는 0."""
    v = _override(code, registry, "verifiable")
    if v is not None:
        return v
    st = STEP_TYPES.get(code)
    return st.verify_default if st else 0
