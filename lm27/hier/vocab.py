# -*- coding: utf-8 -*-
"""업무 영역·어휘 단일원(H §1.2 · §1.4 · §1.6 · §2.3.4 · §4.4, 계약 §2.10 · §6.6 · X-230 · X-231 · X-242).

영역의 이름·색·순서·설명·프롬프트 문구·규칙 키워드는 **이 파일의 `DOMAIN_META` 한 표**에서만 나온다.
화면·보고서·프롬프트·규칙은 접근 함수(`domain_name` `domain_color` `domain_order` `domain_prompt_line`
`domain_keywords`)만 쓴다 — 이 표 밖에서 영역 이름 문자열·색을 하드코딩하면 L-25(G-H11)가 막는다.

- 영역 색은 R 의 대비 검증값(계약 §6.6 · X-242)이다(H 표의 MP·COM·UNC 색은 폐기).
- 어휘의 정본은 **코드**(ELEC·DESIGN·DEV·REQ_IN — X-230)이고 이름은 표시 라벨이다. 업무 유형은 7종(X-231).
- 단계 유형(step_types)은 `lm27.vocab.steps` 가 원천이다(X-243).
- 옛 문자열 어휘는 `legacy_code(name, kind)` 로 코드로 바꾼다(내장 이름 `ukey` 일치 → 그 코드, 없으면
  `X_` + sha1(ukey(이름))[:6] 대문자 — 계약 §4.5).
- 예약 과제 `P-9901`~`P-9905`(영역 일반)는 코드가 주입한다(`RESERVED`). 레지스트리 파일에는 둘 수 없다.

저장소 기본값은 중립 어휘뿐이다(과제·별칭·코드네임·고객·규칙·카탈로그 0 — G-H13).
"""
import hashlib
from dataclasses import dataclass

from lm27.hier.names import ukey
from lm27.vocab import steps as _steps

# ── 업무 영역(5종 + 미분류) ─────────────────────────────────────────────────────
DOMAIN_META: dict[str, dict] = {
    "DEV": {"name": "개발 프로젝트", "order": 0, "color": "#2a78d6",
            "desc": "포트폴리오 확장을 위한 제품 개발(선행·신제품·요소기술)",
            "keywords": ("선행", "신제품", "시제품", "프로토", "요소기술", "개발샘플", "목업"),
            "synonyms": ("개발", "선행", "신제품", "요소기술")},
    "MP": {"name": "양산 프로젝트", "order": 1, "color": "#c47400",
           "desc": "사업을 위한 양산 이관·양산 대응·생산 지원",
           "keywords": ("양산", "양산이관", "생산", "라인", "수율", "공정불량", "8d", "출하", "ppap", "초도품",
                        "양산대응"),
           "synonyms": ("양산", "양산이관", "생산", "제조")},
    "EXT": {"name": "외부 업무지원", "order": 2, "color": "#0e8c7a",
            "desc": "팀 직접 업무가 아닌 외부 지원(국책·산학·포럼·파견·교육)",
            "keywords": ("국책", "정부과제", "산학", "산학협력", "공동연구", "위탁연구", "포럼", "학회", "세미나",
                         "컨퍼런스", "파견", "교육", "강의", "강연", "워크숍", "외부심사", "자문", "위원회", "전시회",
                         "기술지도"),
            "synonyms": ("외부지원", "국책", "산학", "대외")},
    "COM": {"name": "공통 업무", "order": 3, "color": "#a61b4a",
            "desc": "회계·재무·예산·실험실 관리·특허·정보보안·총무 등 팀 운영",
            "keywords": ("회계", "재무", "예산", "결산", "정산", "품의", "법인카드", "자산실사", "총무", "비품",
                         "사무용품", "인사", "근태", "노무", "연말정산", "실험실", "랩관리", "장비관리", "검교정",
                         "교정", "안전점검", "보건", "소방", "정보보안", "보안점검", "보안교육", "법정교육",
                         "안전교육", "사내교육", "의무교육", "특허", "지재권", "출원", "내부감사", "내부통제",
                         "팀운영"),
            "synonyms": ("공통", "사무", "일반", "운영")},
    "AX": {"name": "AX 프로젝트", "order": 4, "color": "#6c4fb8",
           "desc": "AI 를 활용한 업무 효율화·자동화(개발·양산과 연계하거나 별도)",
           "keywords": ("ai", "llm", "gpt", "copilot", "코파일럿", "rpa", "에이전트", "agentic", "에이전틱",
                        "프롬프트", "자동화", "머신러닝", "딥러닝", "챗봇", "rag", "생성형"),
           "synonyms": ("ax", "ai", "자동화", "agentic")},
    "UNC": {"name": "미분류", "order": 9, "color": "#8b929b",
            "desc": "영역·과제를 정하지 못함(숨기지 않고 보인다)",
            "keywords": (), "synonyms": ()},
}
DOMAINS: tuple[str, ...] = ("DEV", "MP", "EXT", "COM", "AX")            # 과제·제안이 가질 수 있는 영역(X-232)
ALL_DOMAINS: tuple[str, ...] = DOMAINS + ("UNC",)                        # UNC 는 파생 전용
DOMAIN_ORDER: tuple[str, ...] = tuple(sorted(DOMAIN_META, key=lambda c: DOMAIN_META[c]["order"]))
# AX 연계 판정의 강한 낱말(H §10.3) — 하나만 맞아도 연계
AX_STRONG: frozenset[str] = frozenset({"llm", "rag", "copilot", "코파일럿", "에이전트", "agentic", "에이전틱", "생성형"})

# ── 예약 '영역 일반' 과제(H §1.3 — 코드에 내장, 모든 유효 레지스트리에 주입) ─────────────
RESERVED: dict[str, str] = {"P-9901": "DEV", "P-9902": "MP", "P-9903": "EXT", "P-9904": "COM", "P-9905": "AX"}
RESERVED_BY_DOMAIN: dict[str, str] = {d: p for p, d in RESERVED.items()}


def is_reserved_id(pid) -> bool:
    """`P-99\\d{2}` 범위(예약 5개 + 레지스트리가 쓸 수 없는 나머지)."""
    return isinstance(pid, str) and len(pid) == 6 and pid.startswith("P-99") and pid[4:].isdigit()


def reserved_name(pid: str) -> str:
    """예약 과제 표시 이름 '<영역 이름> 일반'."""
    return f"{domain_name(RESERVED[pid])} 일반"


def reserved_desc(pid: str) -> str:
    """예약 과제 프롬프트 설명 '(<영역 이름> — 과제 미지정)'."""
    return f"({domain_name(RESERVED[pid])} — 과제 미지정)"


# ── 영역 접근 함수 ─────────────────────────────────────────────────────────────
def _meta(c) -> dict:
    return DOMAIN_META.get(c) or DOMAIN_META["UNC"]


def domain_name(c) -> str:
    """영역 코드 → 표시 이름(모르는 코드는 미분류)."""
    return _meta(c)["name"]


def domain_color(c) -> str:
    """영역 코드 → 16진 색(R 대비 검증값)."""
    return _meta(c)["color"]


def domain_order(c) -> int:
    """영역 코드 → 표시 순서(모르는 코드는 미분류 순서)."""
    return _meta(c)["order"]


def domain_desc(c, reg=None) -> str:
    """영역 설명(화면·프롬프트). 유효 레지스트리의 `domain_meta.desc` 덮어쓰기가 있으면 그것."""
    if reg is not None:
        d = getattr(reg, "domain_desc", None) or {}
        if d.get(c):
            return d[c]
    return _meta(c)["desc"]


def domain_keywords(c, reg=None) -> tuple[str, ...]:
    """영역 규칙 키워드(`head` 모드). 유효 레지스트리가 있으면 내장 ∪ 팀 add − remove(개인 로컬 마지막)."""
    if reg is not None:
        kw = getattr(reg, "domain_kw", None) or {}
        if c in kw:
            return tuple(kw[c])
    return tuple(_meta(c)["keywords"]) if c in DOMAIN_META else ()


def domain_prompt_line() -> str:
    """프롬프트의 영역 줄: '[업무영역] DEV <이름> · MP <이름> · …'(UNC 는 싣지 않는다)."""
    return "[업무영역] " + " · ".join(f"{c} {domain_name(c)}" for c in DOMAINS)


def snap_domain(s) -> str:
    """바깥 영역 문자열(코파일럿 답·옛 파일·수동 입력) → 영역 코드. ① 코드 완전 일치 → ② 이름 완전 일치(ukey)
    → ③ 동의어 표(ukey 완전 일치) → ④ 그 밖·모호하면 ''(억지로 찍지 않는다 — LM24 snap1).
    LM24 의 '지원·교육 → 공통' 동의어는 폐기했다(외부 업무지원과 충돌)."""
    if not isinstance(s, str) or not s.strip():
        return ""
    t = s.strip()
    if t.upper() in DOMAIN_META and t == t.upper():
        return t.upper()
    k = ukey(t)
    if not k:
        return ""
    for c, m in DOMAIN_META.items():
        if k == ukey(c) or k == ukey(m["name"]):
            return c
    hits = {c for c, m in DOMAIN_META.items() if any(k == ukey(x) for x in m["synonyms"])}
    return hits.pop() if len(hits) == 1 else ""


# ── 어휘(분야·기능·업무 유형·단계 유형) ─────────────────────────────────────────
VOCAB_KINDS: tuple[str, ...] = ("fields", "functions", "activity_types", "step_types")


@dataclass(frozen=True)
class VocabItem:
    """어휘 항목 하나(H §2.3.4 · 계약 §3.19). step_types 만 tool_access·verifiable·kind·cls 를 가진다."""
    code: str
    name: str
    status: str = "active"              # active | retired
    replaced_by: str = ""
    keywords: tuple[str, ...] = ()      # 어휘 키워드(head 모드). 팀이 덧붙인 값은 내장과 합집합
    apps: tuple[str, ...] = ()          # 분야 힌트 앱(APP_ID)
    exts: tuple[str, ...] = ()          # 분야 힌트 확장자(점 포함 소문자)
    origin: str = "builtin"             # builtin | team | local | legacy
    maps_to: str = ""                   # 개인 L_ 코드 → 팀 묶음에 실을 코드(없으면 ETC)
    tool_access: int | None = None      # step_types: 0~2
    verifiable: int | None = None       # step_types: 0~2
    kind: str = ""                      # step_types: M | A
    cls: str = ""                       # step_types: 묶음

    def to_obj(self) -> dict:
        """정규 JSON 형(해시·저장용). 빈 선택 필드는 뺀다."""
        o = {"code": self.code, "name": self.name, "status": self.status, "replaced_by": self.replaced_by,
             "keywords": list(self.keywords), "apps": list(self.apps), "exts": list(self.exts)}
        if self.maps_to:
            o["maps_to"] = self.maps_to
        if self.tool_access is not None:
            o["tool_access"] = self.tool_access
        if self.verifiable is not None:
            o["verifiable"] = self.verifiable
        if self.kind:
            o["kind"] = self.kind
        if self.cls:
            o["cls"] = self.cls
        return o


_FIELDS = (  # 코드, 이름, 키워드(head), 앱 힌트(APP_ID), 확장자 힌트 — H §1.4
    ("MECH", "기구", ("기구", "기구설계", "하우징", "브라켓", "금형", "사출", "도면", "공차", "체결", "판금"),
     ("solidworks", "creo", "catia", "nx", "inventor", "autocad"),
     (".prt", ".asm", ".sldprt", ".sldasm", ".step", ".stp", ".igs", ".dwg", ".catpart", ".x_t")),
    ("ELEC", "회로", ("회로", "전원", "pcb", "아트웍", "하네스", "emc", "부품선정", "회로도"),
     ("altium", "orcad", "kicad", "ltspice", "pads", "allegro"),
     (".sch", ".schdoc", ".pcbdoc", ".brd", ".dsn", ".kicad_pcb", ".asc")),
    ("SW", "소프트웨어", ("소프트웨어", "sw", "펌웨어", "코드", "빌드", "릴리즈", "버그", "알고리즘"),
     ("vscode", "visual_studio", "eclipse", "keil", "iar", "pycharm"),
     (".c", ".cpp", ".h", ".py", ".cs", ".java", ".js", ".ts")),
    ("OPT", "광학", ("광학", "렌즈", "광정렬", "광원", "수광", "광경로"), ("zemax", "codev", "lighttools", "speos"),
     (".zmx", ".zos", ".seq")),
    ("THERM", "열", ("열해석", "방열", "온도", "발열", "냉각"), ("icepak", "flotherm"), ()),
    ("REL", "신뢰성", ("신뢰성", "수명", "환경시험", "진동", "충격", "내구"), (), ()),
    ("PROC", "공정", ("공정", "생산기술", "조립", "지그", "수율", "라인"), (), ()),
    ("QA", "품질", ("품질", "불량", "8d", "고객불만", "입고검사", "ppap"), (), ()),
    ("SYS", "시스템", ("시스템", "요구사항", "사양", "아키텍처", "사양서"), (), ()),
    ("ETC", "기타", (), (), ()),
)
_FUNCS = (  # 코드, 이름, 키워드(head) — H §1.4
    ("DESIGN", "설계", ("설계", "도면", "모델링", "레이아웃", "아트웍")),
    ("IMPL", "구현", ("구현", "코딩", "빌드", "디버깅", "포팅")),
    ("ANALYSIS", "해석·분석", ("해석", "시뮬레이션", "분석", "계산")),
    ("TEST", "시험·검증", ("시험", "평가", "측정", "검증", "테스트", "실험", "성적서", "입고검사")),
    ("OUTSRC", "외주 관리", ("외주", "용역", "업체관리")),
    ("PURCHASE", "구매·발주", ("구매", "발주", "견적", "납기", "입고")),
    ("DOC", "문서·보고", ("보고서", "문서", "작성", "보고자료", "발표자료")),
    ("MEET", "회의·조율", ("회의", "미팅", "조율", "협의")),
    ("PM", "과제 관리", ("일정", "마일스톤", "wbs", "과제관리", "착수", "종료보고")),
    ("TRANSFER", "양산 이관", ("양산이관", "이관", "초도품")),
    ("SUPPORT", "기술 지원·대응", ("대응", "지원", "이슈대응", "고객대응")),
    ("STUDY", "조사·학습", ("조사", "동향", "벤치마킹", "학습", "수강")),
    ("ADMIN", "행정·사무", ("정산", "품의", "결재", "신청", "등록")),
    ("ETC", "기타", ()),
)
_WTYPES = (  # 코드, 이름, 판정 낱말(head — H §10.1 의 현장·교육·PM 낱말) — H §1.6
    ("DEV", "개발", ()),
    ("OFFICE", "사무", ()),
    ("FIELD", "현장", ("현장", "출장", "라인", "입고검사", "방문", "설치", "시운전", "필드")),
    ("PM", "PM", ("일정", "예산", "마일스톤", "wbs", "견적", "계약", "고객")),
    ("PL", "PL", ()),
    ("SUPPORT", "지원", ()),
    ("EDU", "교육·학습", ("교육", "강의", "세미나", "학회", "수강", "워크숍")),
)

BUILTIN_VOCAB: dict[str, tuple[VocabItem, ...]] = {
    "fields": tuple(VocabItem(c, n, keywords=kw, apps=ap, exts=ex) for c, n, kw, ap, ex in _FIELDS),
    "functions": tuple(VocabItem(c, n, keywords=kw) for c, n, kw in _FUNCS),
    "activity_types": tuple(VocabItem(c, n, keywords=kw) for c, n, kw in _WTYPES),
    "step_types": tuple(VocabItem(c, s.name, tool_access=s.tool_default, verifiable=s.verify_default, kind=s.kind,
                                  cls=s.cls) for c, s in _steps.STEP_TYPES.items()),
}
FALLBACK_CODE = "ETC"                       # 퇴역 코드의 replaced_by 가 없을 때·개인 L_ 코드의 maps_to 가 없을 때


def builtin_codes(kind: str) -> tuple[str, ...]:
    """내장 어휘 코드(표 순서)."""
    return tuple(it.code for it in BUILTIN_VOCAB[kind])


def builtin_item(kind: str, code: str) -> VocabItem | None:
    for it in BUILTIN_VOCAB.get(kind, ()):
        if it.code == code:
            return it
    return None


def legacy_code(name, kind: str = "fields") -> str:
    """옛 문자열 어휘(이름) → 코드(H §2.3.4). 내장 이름과 `ukey` 가 같으면 그 코드(예 '회로' → ELEC),
    없으면 결정적 코드 `X_` + sha1(ukey(이름))[:6] 대문자(예 '광학검사' → X_E42E7B)."""
    if kind not in BUILTIN_VOCAB:
        raise ValueError(f"vocab: 어휘 종류는 {VOCAB_KINDS} 중 하나")
    k = ukey(name)
    for it in BUILTIN_VOCAB[kind]:
        if ukey(it.name) == k or ukey(it.code) == k:
            return it.code
    return "X_" + hashlib.sha1(k.encode("utf-8")).hexdigest()[:6].upper()


def all_vocab_keywords() -> frozenset[str]:
    """내장 어휘·영역 키워드 전부(ukey) — 범용어 판정(`generic_keyword`)·코드네임 후보 제외용."""
    out = set()
    for items in BUILTIN_VOCAB.values():
        for it in items:
            out.update(ukey(k) for k in it.keywords)
    for m in DOMAIN_META.values():
        out.update(ukey(k) for k in m["keywords"])
    out.discard("")
    return frozenset(out)
