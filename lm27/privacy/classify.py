# -*- coding: utf-8 -*-
r"""광고·공사(公私)·방 성향·창 분류·부재 힌트(P §11·§12) — 판정 규칙. 가중치·임계·정규식은 규칙 고정(RULES_HASH 포함).

PRIVACY.md §11.1·§11.2·§12.3·§12.4·§12.6·§12.7 코드 블록을 옮겼다(정규식·가중치·임계 바이트 그대로). 바꾼 점:
  · ``s += 4; why.append(…)`` 한 줄 두 문장을 두 줄로(ruff E702) — 동작 같음.
  · ``window_class`` — 비업무 프로그램은 문맥의 **유효 목록**(``WindowContext.private_exes`` = 내장 ∪ add − disable)
    하나로 본다(코드 블록은 내장 목록을 따로 OR 해 disable 이 먹지 않았다). 카탈로그 범주 ``messenger_private``·``game``
    → private, ``media`` → media 를 합집합으로(P §12.6 본문). ``WindowContext`` 를 이 모듈에 둔다. 판정 전에 폭 0 문자를
    지운다(실제 Edge 창 제목은 ``Microsoft<U+200B> Edge`` 라 ``BROWSER_SUFFIX_RX`` 가 맞지 않아 사적 프로필을 놓쳤다).
  · 호출 쪽 보정 도우미(규칙 해시 불변 — 설정 해시 몫): ``ad_score_adjusted``(``privacy.ad.extraWords`` P §11.2 끝),
    ``private_score_adjusted``(``privacy.private.extraWords``·``extraWorkWords`` P §12.3 끝), ``priv_why_codes``
    (P §12.3 세부 → ``priv_why`` 코드), 헤더·본문 플래그 ``header_flags``·``body_unsub``·``adlike_localpart``
    (P §11.1 — 헤더 원문은 bool 만 뽑고 버린다), ``abs_hint``(P §12.7).

판정 입력은 **정제문**이다(정제 후 판정 → ``[과제:…]`` 토큰이 업무 근거, P §12.1). 광고 점수만 정제 전 제목(메모리)을
쓴다(광고 표기·광고어 판정용, 저장 안 함 — P §11.2). 이 모듈은 아무것도 쓰거나 출력하지 않는다. 표준 라이브러리만.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .detect import SanitizeContext, sanitize

# ── 광고성 메일(P §11.1 헤더 플래그 · §11.2 점수) ────────────────────────────────────────
HDR_LIST_UNSUB = re.compile(r"(?im)^List-Unsubscribe\s*:")
HDR_PRECEDENCE = re.compile(r"(?im)^Precedence\s*:\s*(?:bulk|list|junk)\b")
HDR_ESP = re.compile(r"(?im)^(?:Feedback-ID|X-Campaign(?:ID|-Id)?|X-Mailgun-[A-Za-z-]+|X-SES-[A-Za-z-]+|X-SG-EID|X-SG-ID"
                     r"|X-MC-User|X-Mailchimp-[A-Za-z-]+|X-CSA-Complaints|X-Mailer-RecptId|X-Stibee-[A-Za-z-]+"
                     r"|X-Sendinblue-[A-Za-z-]+|X-Marketo-[A-Za-z-]+|X-HubSpot-[A-Za-z-]+|X-SFMC-Stack)\s*:"
                     r"|^X-Mailer\s*:.*(?:Mailchimp|SendGrid|Amazon SES|Mailgun|Sendinblue|Brevo|Stibee|HubSpot|Marketo"
                     r"|Salesforce|Constant Contact|MailerLite|Campaign Monitor)")

AD_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd|회신|전달|답장)\s*[:：]\s*)*[\(\[<【〈{]\s*(?:광고|ad|광고성\s?정보|홍보|advertisement)"
                       r"\s*[\)\]>】〉}]", re.I)
AD_WORDS = re.compile(
    r"(?i)(수신\s?거부|구독\s?(?:취소|해지)|unsubscribe|opt[- ]?out|뉴스레터|newsletter|웨비나|webinar|프로모션|promotion|"
    r"할인|특가|쿠폰|coupon|이벤트|event|무료\s?체험|free\s?trial|신제품\s?출시|런칭|초대합니다|세미나\s?안내|전시회\s?초대|"
    r"limited\s?offer|sale|경품|사은품|당첨|혜택|얼리버드|early\s?bird)")
AD_LOCALPART = re.compile(r"(?i)^(?:newsletter|news|marketing|promo|promotion|event|events|webinar|campaign|mailer|edm|ad|ads"
                          r"|offers?)[._\-]?|(?:^|[._\-])(?:newsletter|marketing|promo|campaign|edm)(?:$|[._\-])")
BODY_UNSUB = re.compile(r"(?i)(수신\s?거부|수신을\s?원하지\s?않으시면|구독\s?(?:취소|해지)|unsubscribe|opt[- ]?out|이메일\s?수신\s?동의)")
AD_DROP, AD_SUSPECT = 5, 3


def ad_score(m: dict) -> tuple[int, str, list]:
    """m: 메모리 특징 dict — subject, internal, corresp_domain, partner, hdr{list_unsubscribe, precedence_bulk, esp},
    body_unsub, focused_other, folder, rcv, n_recipients, adlike_localpart, i_sent_in_conv, blocked, allowed."""
    why = []
    if m.get("blocked"):
        return 9, "drop", ["user_block"]
    if m.get("folder") == "junk":
        return 9, "drop", ["folder_junk"]
    if AD_PREFIX.search(m.get("subject", "")):
        return 9, "drop", ["ad_prefix"]            # 정보통신망법 제50조 광고 표기 — 단독 확정, 회신·허용 면제 무효
    s = 0
    h = m.get("hdr") or {}
    if h.get("list_unsubscribe"):
        s += 4
        why.append("list_unsub")
    if h.get("precedence_bulk"):
        s += 3
        why.append("precedence")
    if h.get("esp"):
        s += 2
        why.append("esp")
    if m.get("body_unsub"):
        s += 2
        why.append("body_unsub")
    if m.get("focused_other"):
        s += 3
        why.append("focused_other")
    rel = m.get("internal") or m.get("corresp_domain") or m.get("partner")
    if not m.get("internal"):
        s += 1
        why.append("external")
        if not m.get("corresp_domain"):
            s += 2
            why.append("no_corresp")
    if m.get("rcv") == "bulk":
        s += 1
        why.append("bulk")
    if (m.get("n_recipients") or 0) >= 20:
        s += 1
        why.append("many_rcpt")
    words = {w.lower() for w in AD_WORDS.findall(m.get("subject", ""))}
    if words:
        s += 2 + (1 if len(words) >= 2 else 0)
        why.append("ad_words")
    if m.get("adlike_localpart"):
        s += 1
        why.append("ad_localpart")
    if rel:
        s -= 3
        why.append("work_relation")        # 사내·왕래·협력사: 감점만(면제 아님 — LM24 영구 면제 결함 수정)
    if m.get("i_sent_in_conv"):
        s -= 4
        why.append("my_thread")
    if m.get("allowed"):
        s = min(s, 0)
        why.append("user_allow")
    band = "drop" if s >= AD_DROP else ("suspect" if s >= AD_SUSPECT else "keep")
    return s, band, why


AD_WHY = ("user_block", "folder_junk", "ad_prefix", "list_unsub", "precedence", "esp", "body_unsub", "focused_other",
          "external", "no_corresp", "bulk", "many_rcpt", "ad_words", "ad_localpart", "work_relation", "my_thread",
          "user_allow", "extra_words")            # ad_why 열거(계약 §3.2·P §10.2) — extra_words 는 설정 광고어 가점


def header_flags(headers_text: str | None) -> dict:
    """메일 헤더 원문(메모리) → ``{list_unsubscribe, precedence_bulk, esp}`` bool 만(P §11.1). 원문은 돌려주지 않는다."""
    h = headers_text or ""
    return {"list_unsubscribe": bool(HDR_LIST_UNSUB.search(h)), "precedence_bulk": bool(HDR_PRECEDENCE.search(h)),
            "esp": bool(HDR_ESP.search(h))}


def body_unsub(body_text: str | None) -> bool:
    """본문(앞 1,000자 + 끝 4,000자 — 메일 수집기가 자른 메모리 값)에 수신거부 문구가 있는가(P §11.1)."""
    return bool(BODY_UNSUB.search(body_text or ""))


def adlike_localpart(local: str | None) -> bool:
    """발신 주소 로컬파트가 광고형(newsletter@·marketing. …)인가 — 로컬파트 자체는 저장하지 않는다(P §11.2)."""
    return bool(AD_LOCALPART.search(local or ""))


def ad_score_adjusted(m: dict, extra_words=()) -> tuple[int, str, list]:
    """``ad_score`` + 설정 광고어(``privacy.ad.extraWords`` — 문자 그대로, 대소문자 무시) 가점(P §11.2 끝):
    제목에 설정 광고어가 있으면 +2(정규식 광고어가 이미 있었으면 +1 — 광고어 가점 합계 +3 상한), 같은 임계로 band 재계산.
    확정 9 규칙(차단·정크·광고 표기)과 사용자 허용 상한 0 은 그대로 우선한다."""
    s, band, why = ad_score(m)
    words = [w for w in (extra_words or ()) if w]
    if not words or (why and why[0] in ("user_block", "folder_junk", "ad_prefix")):
        return s, band, why
    subj = m.get("subject") or ""
    if not any(w.lower() in subj.lower() for w in words):
        return s, band, why
    found = {w.lower() for w in AD_WORDS.findall(subj)}
    rx_bonus = (2 + (1 if len(found) >= 2 else 0)) if found else 0
    add = min(2, 3 - rx_bonus)
    if add <= 0:
        return s, band, why
    s += add
    why = [*why, "extra_words"]
    if m.get("allowed"):
        s = min(s, 0)
    band = "drop" if s >= AD_DROP else ("suspect" if s >= AD_SUSPECT else "keep")
    return s, band, why


# ── 공사 구분(P §12.3) ──────────────────────────────────────────────────────────────
P_STRONG = re.compile(
    r"(가족|와이프|아내|남편|신랑|애기|아기|아이들|딸아이|아들|부모님|엄마|아빠|장모|시댁|처가|병원|치과|한의원|약국|진료|택배|배송|쇼핑|주문했|직구|"
    r"여행|휴가\s?계획|비행기\s?표|숙소|캠핑|게임|축구|야구|농구|영화|드라마|넷플|유튜브|주식|코인|대출|이사\s?(?:가|날|준비)|집들이|부동산|청약|전세|월세|"
    r"결혼식|소개팅|데이트|생일\s?선물|헬스장|골프)")
P_WEAK = re.compile(r"(점심|저녁|야식|커피|한잔|술|맥주|치킨|맛집|퇴근하고|퇴근\s?후에|주말에|휴일에|날씨|ㅋㅋ+|ㅎㅎ+|ㅠㅠ+|ㅜㅜ+|ㄱㄱ|헐|대박"
                    r"|😂|🤣|😆|🍺|🍻)")
P_SOCIAL = re.compile(r"(회식|경조사|축의|부의|조의|조문|돌잔치|동호회|송년회|신년회|뒤풀이|생일\s?축하|체육대회)")
W_WORK = re.compile(
    r"(?i)(검토|회신|보고|자료|첨부|일정|회의|미팅|도면|설계|시험|평가|해석|시뮬|샘플|발주|구매|견적|고객|과제|프로젝트|양산|개발|이슈|불량|대책|품질|"
    r"(?<![A-Za-z])(?:BOM|ECO|DR|PR|PO|spec)(?![A-Za-z])|사양|요청|부탁드립니다|공유드립니다|확인\s?부탁|승인|결재|기안|출장|교육|특허|예산|정산)")
W_ACK = re.compile(r"(넵|네\s?알겠습니다|알겠습니다|확인했습니다|감사합니다|수고하셨습니다)")
REG_TOKEN = re.compile(r"\[(?:과제|고객사|협력사):[^\]]+\]")
PRIV_THRESHOLD = 2


def private_score(text: str, *, chat_type: str = "", offhours: bool = False, room_prior: str = "",
                  personal_mail: bool = False, sensitivity: int = 0, private_category: bool = False,
                  user_private_chat: bool = False):
    """정제문 하나의 공사 점수(P §12.3) → ``(점수, "work"|"private"|"social", 세부 건수)``. ≥2 면 private(친목어만 있고
    강한 사적어가 없으면 social), 아니면 work. 민감도 1·2·개인 범주·사용자 지정 사적 방은 즉시 9·private."""
    if sensitivity in (1, 2) or private_category or user_private_chat:
        return 9, "private", {"explicit": 1}
    ps, pw, so = P_STRONG.findall(text), P_WEAK.findall(text), P_SOCIAL.findall(text)
    ww, ack = W_WORK.findall(text), W_ACK.findall(text)
    s = 2 * len(ps) + len(pw) + len(so) - 2 * min(len(ww), 4) - len(ack)
    if REG_TOKEN.search(text):
        s -= 3                                      # 레지스트리 토큰(과제·고객·협력사) = 강한 업무 근거
    if chat_type == "1:1":
        s += 1
    elif chat_type in ("meeting", "channel"):
        s -= 1
    if offhours:
        s += 1                                      # 평일 19~07시, 주말·공휴일 (시간 명세의 표준창 밖)
    if room_prior == "private":
        s += 2
    elif room_prior == "work":
        s -= 1
    if personal_mail:
        s += 3                                      # 상대가 공용 개인 메일 도메인
    if s >= PRIV_THRESHOLD:
        cls = "social" if so and not ps else "private"
    else:
        cls = "work"
    return s, cls, {"strong": len(ps), "weak": len(pw), "social": len(so), "work": len(ww), "ack": len(ack)}


PRIV_WHY = ("explicit", "strong", "weak", "social", "work", "ack", "reg_token", "one_to_one", "group_meeting", "offhours",
            "room_private", "room_work", "personal_mail")    # priv_why 열거 중 private_score 쪽(창 분류 코드는 별도)


def private_score_adjusted(text: str, *, extra_words=(), extra_work_words=(), **kw) -> tuple[int, str, dict]:
    """``private_score`` + 설정 어휘 보정(P §12.3 끝 — 정규식은 그대로, 규칙 해시 불변):
    설정 사적어(``privacy.private.extraWords``) 1개마다 +2, 설정 업무어(``extraWorkWords``) 1개마다 −2(정규식 업무어와
    합쳐 4개 상한). 같은 임계(PRIV_THRESHOLD)·같은 social 규칙으로 클래스를 다시 정한다. 명시적 사적(점수 9)은 그대로."""
    s, cls, det = private_score(text, **kw)
    if det.get("explicit"):
        return s, cls, det
    t = text or ""
    n_priv = sum(t.count(w) for w in (extra_words or ()) if w)
    n_work = sum(t.count(w) for w in (extra_work_words or ()) if w)
    if not n_priv and not n_work:
        return s, cls, det
    base_work = min(det.get("work", 0), 4)
    work_total = min(det.get("work", 0) + n_work, 4)
    s += 2 * n_priv - 2 * (work_total - base_work)
    det = dict(det, strong=det.get("strong", 0) + n_priv, work=det.get("work", 0) + n_work)
    if s >= PRIV_THRESHOLD:
        cls = "social" if det.get("social") and not det.get("strong") else "private"
    else:
        cls = "work"
    return s, cls, det


def priv_why_codes(det: dict, *, text: str = "", chat_type: str = "", offhours: bool = False, room_prior: str = "",
                   personal_mail: bool = False) -> list:
    """``private_score`` 세부 dict + 입력 조건 → ``priv_why`` 코드 목록(값이 0 인 코드는 뺌, 최대 8 — P §12.3·§10.1)."""
    if det.get("explicit"):
        return ["explicit"]
    out = [k for k in ("strong", "weak", "social", "work", "ack") if det.get(k)]
    if REG_TOKEN.search(text or ""):
        out.append("reg_token")
    if chat_type == "1:1":
        out.append("one_to_one")
    elif chat_type in ("meeting", "channel"):
        out.append("group_meeting")
    if offhours:
        out.append("offhours")
    if room_prior == "private":
        out.append("room_private")
    elif room_prior == "work":
        out.append("room_work")
    if personal_mail:
        out.append("personal_mail")
    return out[:8]


# ── 1:1 대화방 성향(P §12.4) ────────────────────────────────────────────────────────
@dataclass
class RoomStat:            # 적재기가 정제된 teams 행에서 계산(별도 파일 없음)
    n: int                 # 최근 30일 메시지 수(msg_key 중복 제거 후)
    n_private: int         # priv_score_base >= 2
    n_work: int            # priv_score_base <= -2


def room_prior(st: RoomStat) -> str:
    """최근 30일 10건 이상이고 사적 70% 이상 → "private", 업무 70% 이상 → "work", 그 밖 ""(P §12.4)."""
    if st.n >= 10 and st.n_private / st.n >= 0.7:
        return "private"
    if st.n >= 10 and st.n_work / st.n >= 0.7:
        return "work"
    return ""


# ── 창 샘플 — 비업무 앱·사이트(P §12.6) ───────────────────────────────────────────────
BROWSER_EXES = frozenset({"msedge.exe", "chrome.exe", "firefox.exe", "whale.exe", "opera.exe", "brave.exe", "iexplore.exe"})
PRIVATE_EXES = frozenset({"kakaotalk.exe", "telegram.exe", "discord.exe", "whatsapp.exe", "line.exe", "steam.exe",
                          "steamwebhelper.exe", "epicgameslauncher.exe", "battle.net.exe", "leagueclient.exe",
                          "riotclientservices.exe"})
MEDIA_EXES = frozenset({"spotify.exe"})
INPRIVATE_RX = re.compile(r"(?i)InPrivate|Incognito|시크릿|비공개\s?창|Private\s?Browsing")
BROWSER_SUFFIX_RX = re.compile(r"\s[-–—]\s(?:(?P<profile>[^-–—]{1,40}?)\s[-–—]\s)?"
                               r"(?:Microsoft\s*Edge|Google\s*Chrome|Mozilla\s*Firefox|Whale|Opera|Brave)\s*$", re.I)
PRIVATE_SITE_RX = re.compile(
    r"(?i)(쿠팡|11번가|G마켓|옥션|SSG\.COM|무신사|오늘의집|배달의민족|요기요|당근|번개장터|중고나라|넷플릭스|Netflix|티빙|TVING|웨이브|wavve"
    r"|왓챠|디즈니\+|Disney\+|쿠팡플레이|인터넷뱅킹|스마트뱅킹|증권|주식|코인|업비트|빗썸|웹툰|나무위키|디시인사이드|DC인사이드|인스타그램"
    r"|Instagram|Facebook|페이스북|트위터|Twitch|치지직|아프리카TV|SOOP|네이버\s?카페|다음\s?카페|부동산)")
MEDIA_SITE_RX = re.compile(r"(?i)(YouTube|유튜브|멜론|Melon|Spotify|SoundCloud)")
WORK_SITE_RX = re.compile(
    r"(?i)(SharePoint|OneDrive|Outlook|Teams|Microsoft 365|Office 365|Copilot|Power BI|Confluence|Jira|GitHub|GitLab|Bitbucket"
    r"|Jenkins|Redmine|Azure DevOps|Stack Overflow|Microsoft Learn|Datasheet|데이터시트|IEEE Xplore|ScienceDirect"
    r"|Google Scholar|DBpia|RISS|KIPRIS|Espacenet|Digi-?Key|Mouser|Octopart|PLM|ERP|MES|SAP|Windchill|Teamcenter|Polarion|DOORS)")
TITLE_KEEP_CLASSES = frozenset({"office", "cad", "sim", "eda", "ide", "pdf", "viewer"})
PRIVATE_APP_CLASSES = frozenset({"messenger_private", "game"})   # 카탈로그 범주 → private(P §12.6 본문)
MEDIA_APP_CLASSES = frozenset({"media"})                         # 카탈로그 범주 → media
ZERO_WIDTH_RX = re.compile("[​-‏⁠﻿]")      # Edge 창 제목의 'Microsoft​ Edge' 등 — 판정 전 제거


@dataclass
class WindowContext:
    """창 분류 문맥(P §12.6) — ``make_record_context()`` 가 설정에서 만든다.
    ``private_exes`` = ``privacy.window.privateExes`` 의 **유효 목록**(내장 PRIVATE_EXES ∪ add − disable — 계약 §5.1
    list(+-))이라 내장 목록을 여기서 따로 더하지 않는다(disable 이 먹게). 기본값 = 내장 목록.
    ``work_title_patterns`` 는 컴파일된 패턴(문자열이면 여기서 컴파일 — 검증은 build_context 몫, P §17.3)."""
    private_exes: frozenset = PRIVATE_EXES
    private_profiles: frozenset = frozenset({"개인", "Personal"})
    work_title_patterns: tuple = ()
    sctx: SanitizeContext | None = None

    def __post_init__(self):
        self.private_exes = frozenset(str(x).lower() for x in self.private_exes)
        self.private_profiles = frozenset(self.private_profiles)
        self.work_title_patterns = tuple(re.compile(p) if isinstance(p, str) else p for p in self.work_title_patterns)


@dataclass(frozen=True)
class WindowVerdict:
    """창 분류 결과 — ``title_masked`` 는 정제 제목(저장하지 않는 갈래는 "")."""
    priv_class: str        # work | unknown | media | private
    title_masked: str
    inprivate: bool
    site_class: str        # app | inprivate | profile | site | work_site | other


def window_class(fg_exe: str, title: str, app_class: str, wctx: WindowContext | None = None) -> WindowVerdict:
    """창 샘플 한 건의 공사 판정(P §12.6). 비업무 앱·InPrivate·사적 프로필·사적 사이트 → private(제목 버림),
    미디어 → media, 업무 사이트·문서형 앱 → work(제목은 정제해 120자), 미분류 웹 → unknown(제목 버림),
    팀즈·아웃룩 창(사람·대화방 이름) → work(제목 버림), 미지 프로그램 → work(제목 버림)."""
    wctx = wctx if wctx is not None else WindowContext()
    exe = (fg_exe or "").lower()
    t = ZERO_WIDTH_RX.sub("", unicodedata.normalize("NFKC", title or ""))
    if exe in wctx.private_exes or app_class in PRIVATE_APP_CLASSES:
        return WindowVerdict("private", "", False, "app")
    if exe in MEDIA_EXES or app_class in MEDIA_APP_CLASSES:
        return WindowVerdict("media", "", False, "app")
    if exe in BROWSER_EXES or app_class == "browser":
        if INPRIVATE_RX.search(t):
            return WindowVerdict("private", "", True, "inprivate")
        m = BROWSER_SUFFIX_RX.search(t)
        page = t[:m.start()] if m else t
        profile = (m.group("profile") or "").strip() if m else ""
        if profile and profile in wctx.private_profiles:
            return WindowVerdict("private", "", False, "profile")
        if PRIVATE_SITE_RX.search(page):
            return WindowVerdict("private", "", False, "site")
        if MEDIA_SITE_RX.search(page):
            return WindowVerdict("media", "", False, "site")
        if WORK_SITE_RX.search(page) or any(p.search(page) for p in wctx.work_title_patterns):
            r = sanitize(page, "title", wctx.sctx, 120)
            return WindowVerdict("work", "" if r.drop else r.text, False, "work_site")
        return WindowVerdict("unknown", "", False, "other")     # 미분류 웹: 제목 버림
    if app_class in ("chat_work", "mail_work"):                 # 팀즈·아웃룩 창 제목 = 사람·대화방 이름 → 저장 안 함
        return WindowVerdict("work", "", False, "app")
    if app_class in TITLE_KEEP_CLASSES:                         # Office·CAD·시뮬레이터·IDE: 문서명만 정제 저장
        r = sanitize(t, "title", wctx.sctx, 120)
        return WindowVerdict("work", "" if r.drop else r.text, False, "app")
    if app_class in ("system", "idle"):
        return WindowVerdict("unknown", "", False, "app")
    return WindowVerdict("work", "", False, "app")              # 미지 프로그램 = 업무 신호(요구사항), 제목은 저장 안 함


# ── 부재 힌트(P §12.7) ─────────────────────────────────────────────────────────────
ABS_HINT = [
    ("half_am", re.compile(r"오전\s?반차")), ("half_pm", re.compile(r"오후\s?반차")), ("half", re.compile(r"반차")),
    ("leave", re.compile(r"연차|월차|휴가(?!\s?계획)|휴무")), ("sick", re.compile(r"병가")),
    ("early", re.compile(r"조퇴")), ("out", re.compile(r"외출")), ("trip", re.compile(r"출장")),
]   # 위에서부터 첫 일치 하나. 없으면 "none"


def abs_hint(text: str | None) -> str:
    """부재 힌트(P §12.7) — 위에서부터 첫 일치 하나의 코드, 없으면 ``"none"``. 사적 판정과 무관하게 내용을 비우기 **전에**
    메모리에서 뽑는다(R-P8)."""
    t = text or ""
    for code, rx in ABS_HINT:
        if rx.search(t):
            return code
    return "none"
