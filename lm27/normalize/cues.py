# -*- coding: utf-8 -*-
r"""화행 단서 추출 — 정제기 훅(계약 §2.7 · §3.1 ``act_cues`` · P §10.1 · X-305 · O-12 · CT §6).

    extract(text) -> list[str]      값 ⊂ ACT_CUES(req·rep·done·ack·ask·sched·cancel·fyi), ACT_CUES 순서·중복 없음

``lm27.privacy.records.sanitize_record`` 가 **메모리 원문**(메일 제목 + 본문, 팀즈 본문)에 부르고, 적재(``lm27.normalize.
load``)가 저장된 정제문(``*_masked``)에 다시 부른다. 그래서 원문·정제문 어느 쪽을 받아도 같은 규칙으로 동작한다 — 정제
토큰(``[전화]``·``[사람#…]``·``[과제:…]``)은 단서가 아니므로 지우고, 제목 꼬리표(``[요청]``·``[공지]``·``[완료]`` …)만
단서로 읽는다. 돌려주는 것은 닫힌 어휘의 단서 코드뿐이다(원문 조각·위치·건수 없음).

단서의 뜻(이 모듈이 정한다 — P Q16 · 계약 O-12 '정규화 소유'):

| 단서 | 뜻 | 예(문말 어미·관용구 단위 — 낱말 부분 일치 금지, CT §6) |
|---|---|---|
| ``req`` | 요청·지시 어미 | ~해 주세요 · 부탁드립니다 · 요청드립니다 · (참고·참조·양해 밖의) ~바랍니다 · 회신 요망 · 확인하세요 · 검토 가능할까요 |
| ``rep`` | 송부·공유·보고 | 송부드립니다 · 공유드립니다 · 보고드립니다 · 첨부와 같이 · 올려 두었습니다 · 결과 공유 |
| ``done`` | 완료 보고 | 완료했습니다 · 반영했습니다 · 처리되었습니다 · 마쳤습니다(완료 예정·미완료·완료되면 은 아님) |
| ``ack`` | 수락·확인 회신 | 넵 · 알겠습니다 · 확인했습니다 · 잘 받았습니다 · 진행하겠습니다 |
| ``ask`` | 질문 | 물음표 · ~인가요 · ~할까요 · ~하셨나요 · 문의드립니다 |
| ``sched`` | 기한·일정 지정 | ~까지(시각·날짜와 함께) · 언제까지 · 마감·기한·납기 · 일정 조율 |
| ``cancel`` | 취소·연기·보류 | 취소되었습니다 · 연기합니다 · 보류 · cancelled |
| ``fyi`` | 공지·참고 | 참고 바랍니다 · 공지드립니다 · 알려드립니다 · FYI |

LM24 의 낱말 부분 일치(``확인``·``공유``·``일정``·``가능``·``필요`` 가 들어 있으면 지시)는 쓰지 않는다(CT §6 · §14) —
'확인했습니다'는 ack, '공유드립니다'는 rep 이고, 낱말 '확인'·'공유' 만으로는 어떤 단서도 나오지 않는다.

메일 본문의 인용(``-----Original Message-----``·``보낸 사람:``·``From:``·``>`` 줄·밑줄 구분선) 뒤는 지난 대화라
읽지 않는다 — 회신 '확인했습니다' 가 인용된 원래 의뢰 '검토 부탁드립니다' 때문에 요청으로 읽히지 않게.

이 모듈은 에이전트 bin 사본(계약 §1.3 — ``normalize\{__init__, cues}``)에 들어가는 정제기 훅이다. 그래서 **표준
라이브러리만** import 한다(사본에 없는 모듈을 부르지 않는다 — X-305, 시험으로 확인). 파일을 쓰지 않고, 입력 문자열을
로그·예외 메시지·전역 상태에 남기지 않는다.
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["ACT_CUES", "MAX_SCAN", "extract"]

ACT_CUES = ("req", "rep", "done", "ack", "ask", "sched", "cancel", "fyi")
MAX_SCAN = 6000                      # 한 번에 보는 최대 글자(메일 본문은 앞 1,000 + 끝 4,000자가 들어온다 — P §10.2)
SHORT_ACK_MAX = 12                   # 이 길이 이하의 '넵'·'ok' 단독 메시지는 수락

# ── 인용(지난 대화) 시작 표지 — 이 뒤는 읽지 않는다 ─────────────────────────────────────────
_QUOTE_RX = re.compile(
    r"(?im)^[ \t]*(?:"
    r"-{2,}[ \t]*(?:original message|원본 메시지|원래 메시지|전달된 메시지|forwarded message)[ \t]*-{2,}"
    r"|_{8,}[ \t]*$"
    r"|(?:from|sent|보낸 사람|보낸사람|발신|발신자|보낸 날짜)[ \t]*:[ \t]"
    r"|on [^\n]{4,120} wrote:[ \t]*$"
    r"|\d{4}[-.년 ]+\d{1,2}[-.월 ]+\d{1,2}[^\n]{0,60}(?:작성|wrote)[^\n]{0,10}:?[ \t]*$"
    r"|>"
    r")")

# ── 제목 꼬리표 [요청]·[공지] … — 꼬리표 안 낱말(공백 제거·소문자) → 단서 ────────────────────────
_TAG_RX = re.compile(r"[\[【]([^\[\]【】]{1,14})[\]】]")
_ANY_BRACKET = re.compile(r"\[[^\[\]]{1,60}\]|【[^【】]{1,60}】")
_TAGS = {
    "req": ("요청", "의뢰", "검토요청", "검토의뢰", "확인요청", "작성요청", "제출요청", "승인요청", "결재요청", "협조",
            "협조요청", "회신요망", "회신요청", "요망", "action", "actionrequired", "request", "req", "todo"),
    "rep": ("보고", "결과", "결과보고", "결과공유", "송부", "공유", "회신", "제출", "report", "result"),
    "done": ("완료", "처리완료", "조치완료", "해결", "done", "completed", "closed", "resolved"),
    "fyi": ("공지", "공지사항", "안내", "참고", "알림", "공유사항", "info", "fyi", "notice", "newsletter", "뉴스레터"),
    "sched": ("긴급", "urgent", "asap", "마감", "기한", "일정"),
    "cancel": ("취소", "연기", "보류", "cancel", "canceled", "cancelled", "postponed"),
}
_TAG_CUE = {w: c for c, ws in _TAGS.items() for w in ws}

# ── 단서 규칙(정규화한 글: NFKC · 소문자 · 공백 하나) ─────────────────────────────────────────
_WORK_VERBS = (r"검토|확인|수정|작성|공유|송부|회신|전달|참석|진행|처리|지원|보완|제출|발송|정리|준비|변경|업데이트|"
               r"반영|조치|답변|협조|피드백|리뷰|승인|결재|보고|입력|등록|검증|분석|설명|요약|문의")

_REQ = [
    # ~해 주세요 · 주십시오 · 주시기 바랍니다 · 주시면 감사 · 주실 수 있을까요 · 주시겠어요
    re.compile(r"주\s*(?:세요|세여|십시오|십시요|시기\s*(?:를\s*)?바랍|시면\s*(?:감사|고맙|좋겠)|셨으면|"
               r"실\s*수\s*(?:있|있으)(?:을까요|나요|으신가요|으세요|습니까|으실까요)|시겠(?:어요|습니까|나요)|실래요|"
               r"시길\s*(?:바랍|부탁))"),
    re.compile(r"부탁\s*(?:드립니다|드립니당|드려요|드려용|드릴게요|드릴께요|드리겠습니다|드리며|드리고|드림|드려도|"
               r"합니다|해요|해용|드리오니|드려\s*봅니다|요|해(?![가-힣])|드려(?![가-힣]))|부탁(?=\s*(?:[.!~^]|$))"),
    re.compile(r"요청\s*(?:드립니다|드려요|드리며|드리고|합니다|하오니|드릴게요|드리겠습니다|드림|(?:의\s*)?건(?![가-힣]))|"
               r"요청(?=\s*(?:[.!~]|$))"),
    re.compile(r"의뢰\s*(?:드립니다|드려요|드리며|드리고|합니다|하오니|드림|(?:의\s*)?건(?![가-힣]))|의뢰(?=\s*(?:[.!~]|$))"),
    re.compile(r"요망(?![가-힣])|요망\s*(?:합니다|드립니다)"),
    re.compile(r"[가-힣]\s*줘(?:요|용)?(?=\s*(?:[.!~^?]|$))|줄래(?:요)?(?=\s*(?:[.!~^?]|$))"),
    re.compile(r"까지\s*(?:" + _WORK_VERBS + r")(?:\s*(?:요망|바람|요청|필요))?(?=\s*(?:[.!~]|$))"),
    re.compile(r"(?:" + _WORK_VERBS + r")\s*(?:하세요|하십시오|하시오|하시기\s*바람|할\s*것(?![가-힣])|바람(?![가-힣]))"),
    re.compile(r"(?:" + _WORK_VERBS + r")\s*(?:해\s*)?(?:주실\s*수\s*있|가능할까요|가능하실까요|가능하신가요|가능한가요|"
               r"가능하세요|가능할지요|가능하실지요|되실까요|가능하신지)"),
    re.compile(r"(?:해|하여|해서)\s*줄\s*수\s*(?:있어|있나|있을까|있니)"),
    re.compile(r"\b(?:please|pls|plz|kindly|could you|can you|would you|would it be possible|action required|"
               r"for your review|for review|need your)\b"),
]
_HOPE_RX = re.compile(r"([가-힣a-z]{1,8})?\s*(?:하시기\s*|해\s*주시기\s*|하여\s*주시기\s*)?바랍(?:니다|니당|니다만)")
_HOPE_FYI = ("참고", "참조", "양해", "이해")

_REP = [
    re.compile(r"(?:송부|공유|보고|전달|첨부|제출|업로드|발송|전송|회신|답변|피드백)\s*(?:해\s*)?(?:드립니다|드립니당|드려요|"
               r"드려용|드리오니|드리며|드리고|드렸습니다|드렸어요|드렸음|드림|합니다|하였습니다|했습니다|했어요|했음|"
               r"하오니|해\s*드립니다|해드립니다|해\s*드렸습니다|해드렸습니다|함(?![가-힣]))"),
    re.compile(r"(?:보내|전해)\s*(?:드립니다|드려요|드렸습니다|드렸어요|드림)"),
    re.compile(r"올려\s*(?:드립니다|드렸습니다|드려요|드렸어요|놓았습니다|놓았어요|놨습니다|놨어요|두었습니다|뒀습니다|"
               r"뒀어요)|올렸습니다|올렸어요|올렸음"),
    re.compile(r"첨부\s*(?:와\s*같이|한\s*바와|파일\s*(?:참고|참조|확인|드립)|자료|합니다|하였습니다|했습니다|드립니다)"),
    re.compile(r"결과\s*(?:를\s*)?(?:공유|보고|송부|전달|첨부|올립니다|입니다|드립니다|알려\s*드립니다)"),
    re.compile(r"(?:정리|작성)\s*(?:해\s*)?(?:드립니다|드렸습니다|드려요|했습니다|하였습니다|했어요)"),
    re.compile(r"\b(?:attached|enclosed|sharing|here is|here's|here are|sent you|please find attached)\b"),
]

_DONE = [
    re.compile(r"(?<!미)완료(?!\s*(?:예정|목표|일정|일자|시점|기한|여부|후|하면|되면|하는\s*대로|되는\s*대로|하셨|되셨|"
               r"하실|될|하시면|해\s*주|해주|부탁|요청|(?:했|됐|되었|되|하)?\s*(?:나요|는지|니(?![가-힣])|냐|인가요|입니까|됐어요\?)))"),
    re.compile(r"(?:끝냈|끝났|마쳤|마무리\s*(?:했|하였|되었|됐)|(?:처리|조치|해결|수정|반영|적용|배포|변경|등록|입력)\s*"
               r"(?:했|하였|되었|됐)(?:습니다|어요|음|습니당))"),
    re.compile(r"\b(?:done|completed|finished|fixed|resolved|deployed|merged)\b"),
]

_ACK = [
    re.compile(r"(?:알겠습니다|알겠어요|알겠습니당|알겠음|알겠네요|알겠슴다|확인\s*(?:했습니다|하였습니다|했어요|했음|했습니당)|"
               r"확인\s*완료|확인\s*(?:됐습니다|되었습니다)|잘\s*받았|받았습니다|수신\s*(?:했습니다|하였습니다)|"
               r"접수\s*(?:했습니다|하였습니다|되었습니다|됐습니다)|숙지\s*(?:했습니다|하였습니다|하겠습니다)|이해했습니다|"
               r"(?:진행|처리|반영|검토|확인|준비|수정|작성|공유|송부|회신|참석|조치)\s*(?:하겠습니다|할게요|할께요|하겠어요|"
               r"하도록\s*하겠습니다)|(?:보내|전달|송부|공유|회신|전해)\s*(?:해\s*)?(?:드리겠습니다|드릴게요|드릴께요)|"
               r"그렇게\s*(?:하겠습니다|할게요|하죠|하시죠|하겠어요)|동의합니다)"),
    re.compile(r"\b(?:noted|got it|will do|understood|roger|acknowledged|on it)\b"),
]
_ACK_SHORT = re.compile(r"^(?:넵|네|넹|예|옙|넵넵|네네|ㅇㅇ|ㅇㅋ|오케이|ok|okay|okey|sure|확인|알겠|좋습니다|좋아요)"
                        r"[\s.!~^ㅎㅋ]*$")

_ASK = [
    re.compile(r"[?？]"),
    re.compile(r"(?:인가요|일까요|을까요|할까요|될까요|있을까요|없을까요|습니까|입니까|한가요|하나요|되나요|있나요|없나요|맞나요|"
               r"건가요|는지요|은지요|던가요|(?:했|됐|되었|하셨|셨|았|었|였)나요|으신가요|하신가요|실까요|어떠세요|"
               r"어떠신가요|어떨까요)(?=\s*(?:[.!~…]|$))"),
    re.compile(r"(?:궁금합니다|궁금해요|문의\s*드립니다|문의드립니다|여쭤\s*봅니다|여쭤봅니다|여쭙니다|질문\s*드립니다|"
               r"질문드립니다)"),
]

_TIME_WORD = (r"(?:\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}\s*/\s*\d{1,2}|\d{1,2}\s*일|\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?|"
              r"\d{1,2}:\d{2}|[월화수목금토일]요일|오늘|내일|모레|금일|명일|익일|금주|차주|이번\s*주|다음\s*주|주말|주중|"
              r"월말|월초|연말|이번\s*달|다음\s*달|오전|오후|점심|퇴근|eod)")
_SCHED = [
    re.compile(r"(?:언제까지|몇\s*시까지|며칠까지)"),
    re.compile(_TIME_WORD + r"\s*(?:까지|전까지|이내(?:로|에)?|안으로|안에|중(?:으로|에)?(?:\s*까지)?)"),
    re.compile(r"(?:마감|기한|납기|데드라인)|\b(?:due|deadline|asap|eod)\b|\bby\s+(?:today|tomorrow|eod|monday|tuesday|"
               r"wednesday|thursday|friday|\d)"),
    re.compile(r"(?:일정|시간|미팅|회의)\s*(?:을\s*|를\s*)?(?:조율|잡아|잡겠|잡을|협의|맞춰|정해)|시간\s*(?:되실|되시는|"
               r"괜찮으신|가능하신)|가능하신\s*(?:시간|일정|날짜)"),
]

_CANCEL = [
    re.compile(r"(?<![미가-힣])(?:취소|연기|보류|철회|무산|중지)(?:\s*(?:합니다|되었습니다|됐습니다|하겠습니다|되었|됐|"
               r"드립니다|돼|됨|함|되어|하오니|되었어요|됐어요|할게요|하기로|되|처리|요청|안내|공지)|\s*[:：]|\s*$|[\s.,!])"),
    re.compile(r"\b(?:cancel(?:l?ed)?|postponed?|called off|on hold|rescheduled)\b"),
    re.compile(r"미뤄\s*(?:졌|지|주|야)|미루(?:겠|기로|게)"),
]

_FYI = [
    re.compile(r"(?:참고|참조)\s*(?:로|하세요|하시기|해\s*주세요|해주세요|바랍|하시라고|용(?![가-힣])|부탁|드립니다|자료|하십시오|"
               r"해\s*주시기|하시면|하여\s*주시기)"),
    re.compile(r"(?:공지|안내)(?:\s*(?:드립니다|합니다|사항|문|드려요|말씀|해\s*드립니다|드리오니|드립니당)|\s*[:：])"),
    re.compile(r"알려\s*드립니다|알려드립니다|알려\s*드려요|알립니다|공유\s*차(?:원)?(?![가-힣])|전파\s*(?:드립니다|합니다)"),
    re.compile(r"\b(?:fyi|f\.y\.i|for your information|please note|please be (?:advised|informed)|newsletter|"
               r"announcement)\b"),
]

# 요청으로 읽으면 안 되는 'please' 관용구 — 지우고 본다(송부·참고)
_PLEASE_REP = re.compile(r"\bplease (?:find|see) (?:the )?(?:attached|enclosed|below|attachment)\b")
_PLEASE_FYI = re.compile(r"\bplease (?:note|be (?:advised|informed))\b")
_COURTESY = re.compile(r"(?:너그러운\s*)?(?:양해|이해)\s*(?:를\s*)?(?:부탁|바랍|구합|청합)[가-힣]*")   # 맺음 인사 — 요청 아님
_WS = re.compile(r"\s+")


def _cut_quote(text: str) -> str:
    m = _QUOTE_RX.search(text)
    return text if m is None else text[:m.start()]


def _norm(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFKC", text).lower()).strip()


def _any(rxs, t: str) -> bool:
    return any(rx.search(t) for rx in rxs)


def _hope_req(t: str) -> bool:
    """'~바랍니다' 가 요청인가 — 앞 낱말이 참고·참조·양해·이해면 아니다(공지·참고 관용구)."""
    for m in _HOPE_RX.finditer(t):
        w = (m.group(1) or "").strip()
        if not w.startswith(_HOPE_FYI) and not w.endswith(_HOPE_FYI):
            return True
    return False


def extract(text: str) -> list[str]:
    """글(원문 또는 정제문) → 화행 단서 코드 목록(ACT_CUES 순서·중복 없음). 글이 아니거나 비면 빈 목록."""
    if not isinstance(text, str) or not text:
        return []
    raw = _cut_quote(text[:MAX_SCAN])
    found: set[str] = set()
    for m in _TAG_RX.finditer(raw):
        cue = _TAG_CUE.get(_WS.sub("", unicodedata.normalize("NFKC", m.group(1))).lower())
        if cue:
            found.add(cue)
    t = _norm(_ANY_BRACKET.sub(" ", raw))
    if not t:
        return [c for c in ACT_CUES if c in found]
    if _PLEASE_REP.search(t):
        found.add("rep")
        t = _PLEASE_REP.sub(" ", t)
    if _PLEASE_FYI.search(t):
        found.add("fyi")
        t = _PLEASE_FYI.sub(" ", t)
    t = _COURTESY.sub(" ", t)
    if _any(_REQ, t) or _hope_req(t):
        found.add("req")
    if _any(_REP, t):
        found.add("rep")
    if _any(_DONE, t):
        found.add("done")
    if _any(_ACK, t) or (len(t) <= SHORT_ACK_MAX and _ACK_SHORT.match(t)):
        found.add("ack")
    if _any(_ASK, t):
        found.add("ask")
    if _any(_SCHED, t):
        found.add("sched")
    if _any(_CANCEL, t):
        found.add("cancel")
    if _any(_FYI, t):
        found.add("fyi")
    return [c for c in ACT_CUES if c in found]
