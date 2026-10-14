# -*- coding: utf-8 -*-
r"""
core\meetnote.py — 일정 본문(회의 안건)을 걸러서 AI 판정의 참고로 쓴다(LM28).

사용자 요청: '일정 회의 내용도 참고하면 좋겠다(물론 필터링 되어서)'. 일정 본문은 대부분 온라인 회의 안내문(Teams·Zoom·
Webex·Meet 의 참가 링크·회의 ID·암호·전화 접속 번호)이고 사람이 쓴 안건은 그 앞 몇 줄이다. 그 몇 줄만 남겨 회의 신호의
판정(judge)에 '안건' 으로 덧붙인다 — 제목이 '주간 회의' 뿐이어도 안건이 과제를 가리키면 Copilot 이 맞는 과제·세부업무를 고른다.

관문(원문이 밖으로 나가지 않게 — core\privacy 의 네 관문 위에 얹는다):
  · 수집 직후(G1 — run.g1_mail → prep_body_csv → g1_body): 출처 파일(data\outlook\src\cal_<tag>.csv)의 body 열을
    clean_body → privacy.sanitize → 600자(자르기는 정제 뒤 — 다음 G1 이 다시 자르지 않게)로 바꾸고, 자격증명이 남은 본문은
    비운다(행은 남긴다 — scrub_csv 는 자격증명 행을 통째로 버리므로 회의 자체가 사라지지 않게). 이어지는 scrub_csv 의 body 정제는
    이미 정제된 글이라 바꾸지 않는다. 열이 없는 옛 파일은 건드리지 않는다.
  · 분석(judge → load_notes): 종일·취소·거절·한가함·미정(설정)·근태·부재중·비업무·개인 제외어·비공개 일정은 붙이지 않는다.
    본문은 다시 clean_body → privacy.sanitize(자격증명이면 버림) → 사적·친목(private_score)이 아닌 것만 → noteMaxChars 자.
    회의 신호와는 (날짜, 시작 HH:MM, 정제 제목) 으로만 맞댄다 — 다른 출처의 행에는 붙지 않는다.
  · Copilot 직전(G3): judge 가 안건을 행의 'note' 필드로 같은 관문(gate_items)에 넣는다.
  · 팀 반출: 나가지 않는다 — signals·mm_rows 의 열은 그대로이고 안건은 판정 프롬프트에만 실린다.
불변식: clean_body 는 순수 함수(표준 라이브러리 re·unicodedata 만, 부작용·기록 없음)이고 멱등이다 —
clean_body(clean_body(x)) == clean_body(x). G1 이 다음 실행에 정제된 본문을 다시 걸러도 바뀌지 않는다(가림 토큰 [사람]·[전화] 류를
깨지 않는다 — 이메일 로컬파트는 ASCII 만 보고, 자를 때 토큰 중간을 자르지 않는다). 원문·안건을 출력하지 않는다(건수만).
collect\Get-OutlookWeb.py(웹 경로)는 clean_body(text, max_len=600) 만 늦게 임포트해 쓴다 — 이 모듈의 최상위는 무거운 모듈을
임포트하지 않는다(extract·privacy 는 쓰는 함수 안에서).
"""
import csv
import io
import os
import re
import unicodedata

BODY_MAX = 600          # 출처 파일 body 열 상한(수집기·G1 공통) — 사람이 쓴 안건은 대개 본문 앞 몇 줄이다
NOTE_MAX = 160          # 판정 프롬프트에 붙이는 안건 상한(config.calendar.noteMaxChars 기본값)
NOTE_MIN = 20           # noteMaxChars 하한(이보다 짧으면 안건이 단어 한두 개로 잘린다)
_IN_MAX = 4000          # 한 본문에서 보는 최대 글자 수(병적 입력 방어 — privacy.MAX_SCAN 과 같다)

# ── 0) 정규화 ────────────────────────────────────────────────────────────────────
_ZW_RX = re.compile("[\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff]")
_CTRL_RX = re.compile("[\x00-\x08\x0e-\x1f\x7f-\x84\x86-\x9f]")
_NL_RX = re.compile("\r\n?|[\x0b\x0c\x85\u2028\u2029]")
_PUA_RX = re.compile("[\ue000-\uf8ff]")          # 보호 자리표시자 찌꺼기(정규식이 반쪽만 지운 경우)

# ── 1) 전달·회신 꼬리 — 가장 앞선 곳에서 뒤를 자른다(남이 쓴 글·주소·서명) ─────────────────────
_FWD_RX = re.compile(
    r"-{2,}\s*(?:original\s+(?:message|appointment)|원본\s*(?:메시지|약속)|원래\s*약속|forwarded\s+message|전달된\s*메시지)\s*-{2,}"
    r"|begin\s+forwarded\s+message\s*:"
    r"|님이\s*작성(?:함|했습니다)?\s*:"
    r"|(?<![A-Za-z])on\s[^\n]{4,120}?\swrote\s*:", re.I)
# 전달 머리 묶음: '보낸 사람:/From:' 뒤 300자 안에 '보낸 날짜:/날짜:/Sent:/Date:' 가 있어야 한다 — 'From: 10:00 To: 11:00' 같은
# 사람이 쓴 시간표는 머리 묶음이 아니다(Outlook·Gmail 전달 머리는 늘 보낸 사람 다음에 날짜 줄이 온다)
_HDR_FROM_RX = re.compile(r"(?<![A-Za-z가-힣])(?:보낸\s*사람|from)\s*:", re.I)
_HDR_DATE_RX = re.compile(r"(?<![A-Za-z가-힣])(?:보낸\s*날짜|날짜|sent|date)\s*:", re.I)
_QUOTE_RX = re.compile(r"(?m)^[ \t]*>[^\n]*\n[ \t]*>")     # '>' 로 시작하는 줄이 둘 이상 이어지면 인용 꼬리

# ── 2) 온라인 회의 안내 블록 — 구분선(___ --- ===)으로 나눈 조각마다, 안내 표지가 나오면 그 조각의 뒤를 버린다 ─────
_SEP_RX = re.compile(r"_{5,}|-{5,}|={5,}|\*{5,}|~{5,}|#{5,}|[─━═]{3,}")
_BLOCK_RX = re.compile("|".join((
    # Teams(영문·한글 — 옛 판·새 판). 'Microsoft Teams 회의' 머리 자체는 표지가 아니다(사람이 쓴 '장소: Microsoft Teams 회의'
    # 는 남긴다) — 표지 앞에 남은 머리는 _TEAMS_TAIL_RX 가 걷는다
    r"join\s+(?:the\s+)?(?:microsoft\s+teams\s+|teams\s+)?meeting\s+now",
    r"join\s+microsoft\s+teams\s+meeting",
    r"join\s+on\s+your\s+computer",
    r"click\s+here\s+to\s+join",
    r"join\s+with\s+a\s+video\s+conferencing\s+device",
    r"(?<![A-Za-z])join\s*:\s*<?https?://",
    r"join\s+conversation|대화에\s*참가",
    r"need\s+help\s*\?",
    r"지금\s*(?:모임|회의)에\s*참가",
    r"(?:모임|회의)에\s*참가하려면",
    r"여기를\s*클릭하여\s*(?:모임|회의)에\s*참가",
    r"컴퓨터[,\s]*(?:모바일\s*앱|휴대폰)[^\n]{0,40}?참가",
    r"도움이\s*필요하세요\s*\?",
    r"microsoft\s+teams\s*(?:모임|회의|미팅)(?:에)?\s*참가",
    r"화상\s*회의\s*(?:장치|디바이스)(?:로|를\s*사용하여)\s*참가",
    # 회의 번호·암호 머리
    r"(?:meeting|conference|video\s+conference|phone\s+conference|webinar)\s+(?:id|number)\s*(?:\(access\s+code\)\s*)?:",
    r"(?:모임|회의|전화\s*회의|화상\s*회의)\s*(?:id|번호)\s*:",
    r"passcode\s*:",
    # 전화 접속
    r"dial[\s-]*in\s+by\s+phone|or\s+call\s+in\s*\(audio\s+only\)|join\s+by\s+phone|dial\s+by\s+your\s+location"
    r"|one\s+tap\s+mobile|find\s+(?:a|your)\s+local\s+number",
    r"전화로\s*참가|전화\s*접속\s*\(?\s*오디오|오디오\s*전용|로컬\s*번호\s*찾기",
    # 이끌이(주최자) 옵션
    r"for\s+organizers\s*:",
    r"(?:이끌이|개최자|주최자|구성자)\s*용\s*:",
    # Zoom — 초대 문장 앞의 사람 이름까지 함께 자른다
    r"(?:(?-i:[A-Z][\w.'-]*)(?:\s+(?-i:[A-Z][\w.'-]*)){0,3}\s+)?is\s+inviting\s+you\s+to\s+a\s+scheduled\s+zoom\s+meeting",
    r"(?:\S{1,30}\s*님이\s*(?:귀하를\s*)?)?예약된\s*zoom\s*(?:회의|미팅)",
    r"join\s+zoom\s+meeting|zoom\s*(?:회의|미팅)\s*(?:에\s*)?참가|zoom\.us/",
    # Webex · Skype · Google Meet
    r"join\s+(?:the\s+)?webex\s+meeting|webex\s+meeting\s+(?:number|password)|meeting\s+number\s*\(access\s+code\)|\.webex\.com",
    r"join\s+skype\s+meeting|skype\s+web\s+app",
    r"join\s+with\s+google\s+meet|meet\.google\.com|more\s+phone\s+numbers",
)), re.I)
_TEAMS_TAIL_RX = re.compile(r"(?:microsoft\s+teams|teams)(?:\s*(?:모임|회의|meeting|미팅))?[\s|:·\-]*$", re.I)

# ── 3) 링크·주소·번호 ─────────────────────────────────────────────────────────────────
_DATE_RX = re.compile(
    r"(?<![0-9])(?:19|20)\d{2}\s?[-./년]\s?\d{1,2}\s?[-./월]\s?\d{1,2}(?:\s?일)?(?![0-9])"
    r"|(?<![0-9])(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?![0-9])"
    r"|(?<![0-9])(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?![0-9])")
# 앞 경계는 ASCII 만 본다 — 한글에 붙은 '자료https://…' 도 걷는다(\b 는 한글을 낱말 글자로 봐 놓친다)
_URL_RX = re.compile(
    r"<?(?<![A-Za-z0-9])(?:https?|ftp|file)://[^\s<>\"']+>?|<?(?<![A-Za-z0-9])(?:mailto|tel):[^\s<>\"']+>?"
    r"|(?<![A-Za-z0-9.\-])www\.[^\s<>\"']+|(?<![A-Za-z0-9.\-])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,10}/[^\s<>\"']*", re.I)
_EMAIL_RX = re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}"
                       r"(?![A-Za-z0-9\-])")
_ID_RX = re.compile(r"(?:(?:phone|video)\s+)?(?:meeting|conference|webinar|모임|회의|전화\s*회의|화상\s*회의)\s*(?:id|번호|number)"
                    r"(?:\s*\(access\s+code\))?\s*:\s*[\d\s#*\-]*", re.I)
# 회의 암호·PIN(값까지) — 'pin' 은 숫자 값만(회로의 'pin: GPIO12' 같은 공학 표기는 남긴다 — privacy.CRED_PIN 과 같은 선)
_PASS_RX = re.compile(r"(?<![A-Za-z가-힣])(?:(?:meeting\s+)?(?:passcode|password)|pwd|암호|비밀번호|패스코드|(?:회의|모임)\s*암호)"
                      r"\s*[:=]\s*\S+|(?<![A-Za-z])pin\s*[:=]\s*[\d#*\s]{4,}", re.I)
_PHONE_RX = re.compile(r"(?<![0-9A-Za-z.])\+?\(?\d{1,4}\)?(?:[ .\-]{1,2}\(?\d{1,5}\)?){1,6}(?:,{1,3}[\d#*]+)*#?(?![0-9A-Za-z])")
_REP_RX = re.compile(r"(?<![0-9A-Za-z])1[568]\d{2}-\d{4}(?![0-9A-Za-z])")          # 대표번호(1588-…)
_DIGITS_RX = re.compile(r"(?<![0-9A-Za-z])\d{7,}(?![0-9A-Za-z])")                   # 긴 숫자열(계좌·사번·회의 번호)
_OPAQUE_RX = re.compile(r"(?<![0-9A-Za-z])(?=[0-9A-Za-z_\-]*\d)(?=[0-9A-Za-z_\-]*[A-Za-z])[0-9A-Za-z_\-]{24,}(?![0-9A-Za-z])")

# ── 4) 참석자 목록·맺음말 이름·남은 안내 문구 ─────────────────────────────────────────────
_ATTEND_LABEL = r"(?:참석자|참석\s*대상|참석\s*인원|참석|참여자|필수\s*참석자|선택\s*참석자|attendees|participants|invitees" \
                r"|required(?:\s+attendees)?|optional(?:\s+attendees)?)"
_TITLE = r"(?:님|씨|책임|선임|수석|매니저|프로|팀장|파트장|그룹장|실장|센터장|본부장|부장|차장|과장|대리|사원|주임|연구원|위원|박사|교수)"
# 참석자 목록 — 항목은 짧은 이름(두 낱말까지)과 쉼표만 먹는다. 줄 단위('그 줄 끝까지')로 지우지 않는다: COM 은 줄바꿈을 공백으로
# 바꿔 본문이 한 줄이라, 줄 단위면 '참석자: … 안건: …' 의 안건까지 통째로 지워진다
_ATTEND_ITEM = r"[^\s,;:\n]{1,12}(?:\s[^\s,;:\n]{1,8})?"
_ATTEND_FLAT_RX = re.compile(r"(?i)(?<![가-힣A-Za-z])" + _ATTEND_LABEL + r"\s*:\s*(?:" + _ATTEND_ITEM + r"\s*[,;]\s*)*"
                             r"[^\s,;:\n]{1,12}(?:\s" + _TITLE + r"(?![가-힣]))?")
# 맺음말 이름 — '홍길동 드림' 은 본문 끝에서만('자료 드림'·'단가 올림' 같은 본문 동사는 남긴다) · 'Thanks, John'
_SIGN_RX = re.compile(r"(?<![가-힣])[가-힣]{2,4}\s*드림\s*[.!]?\s*$"
                      r"|(?i:\b(?:best\s+regards|kind\s+regards|regards|cheers|thanks|thank\s+you)\s*,\s*)"
                      r"(?-i:[A-Z][a-z]+)(?:\s(?-i:[A-Z][a-z]+))?")
_PHRASE_RX = re.compile("|".join((
    r"this\s+meeting\s+(?:is\s+being|will\s+be|may\s+be)\s+recorded[^.\n]{0,80}\.?",
    r"(?:이\s*)?(?:모임|회의)(?:은|는|이|가)?\s*녹화(?:됩니다|될\s*수\s*있습니다|되고\s*있습니다|중입니다)\.?",
    r"meeting\s+options|reset\s+(?:dial[\s-]*in\s+)?pin|learn\s+more\s+about\s+teams|system\s+reference|download\s+teams"
    r"|join\s+on\s+the\s+web",
    r"(?:모임|회의)\s*옵션|(?:전화\s*접속\s*)?pin\s*재설정|teams\s*에\s*대한\s*자세한\s*정보",
    r"get\s+outlook\s+for\s+(?:ios|android)|sent\s+from\s+my\s+\w+|outlook\s*(?:모바일)?\s*에서\s*보냄",
)), re.I)
# '자세한 정보 | 도움말 | Help' 처럼 세로줄로 이은 꼬리 — 세로줄 바로 앞·뒤에 붙은 것만(본문의 '자세한 정보는 첨부 참조' 는 남긴다)
_FOOT = r"(?:자세한\s*정보|도움말|help|learn\s+more|privacy\s+and\s+security)"
_FOOTER_RX = re.compile(r"(?<=\|)[ \t]*" + _FOOT + r"[ \t]*(?=\||$)|(?:^|(?<=\s))" + _FOOT + r"[ \t]*(?=\|)", re.I | re.M)
_EMPTY_BR_RX = re.compile(r"[(\[<{（【][\s,;:·|/\-]*[)\]>}）】]")
_PIPES_RX = re.compile(r"(?:[ \t]*\|[ \t]*){2,}")
_EDGE_PIPE_RX = re.compile(r"(?m)^[ \t]*\|[ \t]*|[ \t]*\|[ \t]*$")
_PUNCT_RUN_RX = re.compile(r"(?:\s*[,;]\s*){2,}")
_EDGE_RX = re.compile(r"^[\s,;:·|/\-–—_.~]+|[\s,;:·|/\-–—_~]+$")
_LETTER_RX = re.compile(r"[가-힣A-Za-z]")


def _prep(s):
    """NFKC(전각 콜론·NBSP → 반각) · 폭 0 문자 삭제 · 줄 구분자 → \\n · 제어 문자·탭 → 공백."""
    s = unicodedata.normalize("NFKC", s)
    s = _ZW_RX.sub("", s)
    s = _NL_RX.sub("\n", s)
    return _CTRL_RX.sub(" ", s).replace("\t", " ")


def _cut_tail(s):
    """전달 머리·회신 표지·인용 줄이 처음 나오는 곳에서 자른다(그 뒤는 남이 쓴 글이다)."""
    pos = [m.start() for m in (_FWD_RX.search(s), _QUOTE_RX.search(s)) if m]
    for m in _HDR_FROM_RX.finditer(s):
        if _HDR_DATE_RX.search(s, m.end(), m.end() + 300):
            pos.append(m.start())
            break
    return s[:min(pos)] if pos else s


def _strip_blocks(s):
    """구분선으로 나눈 조각마다 온라인 회의 안내 표지 뒤를 버리고, 표지 앞에 남은 'Microsoft Teams 모임' 머리를 걷는다."""
    kept = []
    for seg in _SEP_RX.split(s):
        m = _BLOCK_RX.search(seg)
        if m:
            seg = _TEAMS_TAIL_RX.sub("", seg[:m.start()])
        seg = seg.strip()
        if seg:
            kept.append(seg)
    return "\n".join(kept)


def _protect(s):
    """날짜·시각을 자리표시자(사설 영역 문자 — 숫자가 없다)로 가려 둔다 — 전화번호 정규식이 '2026-10-14 14' 를 먹지 않게."""
    held = []

    def put(m):
        held.append(m.group(0))
        return "\ue000" + chr(0xE100 + len(held) - 1) + "\ue001"
    return _DATE_RX.sub(put, s), held


def _restore(s, held):
    for i, v in enumerate(held):
        s = s.replace("\ue000" + chr(0xE100 + i) + "\ue001", v)
    return _PUA_RX.sub("", s)


def _phone_rep(m):
    g = m.group(0)
    return " " if len(re.sub(r"\D", "", g)) >= 9 else g


_MORE = "..."           # 잘림 표시 — '…'(U+2026)는 privacy.sanitize 의 NFKC 가 '...' 로 바꿔 다음 G1 에서 길이가 늘어
                        # 다시 잘린다(실행마다 낱말이 하나씩 깎인다). NFKC 에 안정인 ASCII 로 둔다


def _cut(s, n):
    """n 자 안으로 — 문장 끝(번호 매김 '1.' 은 제외) → 단어 경계 → 글자 순. 가림 토큰([사람] 류) 중간은 자르지 않는다.
    문장 끝에서 자르면 표시를 붙이지 않고, 그 밖은 '...' 를 붙인다(전체가 n 자를 넘지 않는다)."""
    if not n or n <= 0 or len(s) <= n:
        return s
    room = s[:max(1, n - len(_MORE))]
    m = re.search(r"\[[^\[\]]{0,24}$", room)
    if m:
        room = room[:m.start()]
    lo = n // 2
    ends = [e.end() for e in re.finditer(r"(?<![0-9.])[.!?。](?=\s|$)", room)]
    if ends and ends[-1] >= lo:
        return room[:ends[-1]].rstrip()
    k = room.rfind(" ")
    if k >= lo:
        room = room[:k]
    return room.rstrip(" ,;:·|/-") + _MORE


def _clean_once(s, max_len):
    s = _strip_blocks(_cut_tail(s))
    s, held = _protect(s)
    s = _URL_RX.sub(" ", s)
    s = _EMAIL_RX.sub(" ", s)
    s = _ID_RX.sub(" ", s)
    s = _PASS_RX.sub(" ", s)
    s = _ATTEND_FLAT_RX.sub(" ", s)
    s = _PHONE_RX.sub(_phone_rep, s)
    s = _REP_RX.sub(" ", s)
    s = _DIGITS_RX.sub(" ", s)
    s = _OPAQUE_RX.sub(" ", s)
    s = _SIGN_RX.sub(" ", s)
    s = _PHRASE_RX.sub(" ", s)
    s = _FOOTER_RX.sub(" ", s)
    s = _restore(s, held)
    for _ in range(2):                                   # '( <> )' 처럼 겹친 빈 괄호
        s = _EMPTY_BR_RX.sub(" ", s)
    s = _PIPES_RX.sub(" | ", s)
    s = _EDGE_PIPE_RX.sub(" ", s)
    s = " ".join(s.split())
    s = _PUNCT_RUN_RX.sub(", ", s)
    s = _EDGE_RX.sub("", s)
    if len(_LETTER_RX.findall(s)) < 2:                   # 글자가 없다(번호·기호만 남음) — 안건이 아니다
        return ""
    return _cut(s, max_len)


def clean_body(text, max_len=BODY_MAX):
    """일정 본문 → 사람이 쓴 안건 한 줄(max_len 자 이하 · 없으면 ""). 순수 함수 — 원문을 기록하지 않는다.
    걷는 것: 전달·회신 꼬리(보낸 사람:/From: … 보낸 날짜:/Sent: 머리 묶음, -----Original Message-----, '>' 인용 줄) ·
    온라인 회의 안내(Teams 모임/meeting·지금 모임에 참가/Join the meeting now·모임 ID/Meeting ID·암호/Passcode·
    전화로 참가/Dial in by phone·이끌이용/For organizers·모임 옵션/Meeting options·Zoom·Webex·Skype·Google Meet 블록, 구분선) ·
    URL·이메일·전화/회의 번호·긴 숫자열·긴 무작위 토큰 · 참석자 목록 · 맺음말 이름('홍길동 드림') · '녹화됩니다' 안내.
    공백을 접고 문장·단어 경계에서 자른다. 멱등(고정점까지 최대 3회)."""
    if text is None:
        return ""
    s = str(text)
    if not s.strip():
        return ""
    out = _clean_once(_prep(s[:_IN_MAX]), max_len)
    for _ in range(2):
        nxt = _clean_once(out, max_len)
        if nxt == out:
            break
        out = nxt
    return out


# ── 설정 ─────────────────────────────────────────────────────────────────────────
def _cal_cfg(cfg):
    c = (cfg or {}).get("calendar") if isinstance(cfg, dict) else None
    return c if isinstance(c, dict) else {}


def enabled(cfg):
    """config.calendar.bodyToAI — 기본 true. 문자열 "false"/"0"/"off" 도 거짓."""
    v = _cal_cfg(cfg).get("bodyToAI", True)
    return not (v is False or v is None or str(v).strip().lower() in ("0", "false", "no", "n", "off", ""))


def note_max(cfg):
    """config.calendar.noteMaxChars — 기본 160, NOTE_MIN~BODY_MAX 로 묶는다(숫자가 아니면 기본값)."""
    v = _cal_cfg(cfg).get("noteMaxChars", NOTE_MAX)
    try:
        n = int(v) if not isinstance(v, bool) else NOTE_MAX
    except (TypeError, ValueError):
        n = NOTE_MAX
    return max(NOTE_MIN, min(BODY_MAX, n))


# ── 회의 신호 ↔ 일정 행 맞댐 ──────────────────────────────────────────────────────────
def norm_subject(s):
    """맞댐용 제목 — 공백 접기·소문자·앞 60자(signals 의 text 는 100자 계약이라 그 앞부분으로 맞댄다)."""
    return " ".join(str(s or "").split()).lower()[:60]


def note_key(time_s, subject):
    """회의 신호의 (time 'YYYY-MM-DD HH:MM', text) 또는 일정 행의 (start, 정제 제목) → (날짜, 'HH:MM', 정규화 제목)."""
    t = " ".join(str(time_s or "").split())
    return (t[:10], t[11:16], norm_subject(subject))


def _mods():
    """(extract, privacy) — 평평한 import(core 가 sys.path 에 있을 때)와 core 패키지 import 를 둘 다 받는다."""
    try:
        import extract
        import privacy
    except ImportError:
        from core import extract, privacy
    return extract, privacy


def _as_date(v):
    from datetime import date, datetime
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


_PRIVATE_RX = re.compile(r"(?<![A-Za-z])(?:private|personal|confidential)(?![A-Za-z])|비공개|사적|개인\s*(?:일정|약속|용무|사유)", re.I)
# Outlook 분류(범주) 이름 — '개인'·'가족' 처럼 한 낱말로 붙인다(제목과 달리 낱말 하나로 판정)
_PRIVATE_CAT_RX = re.compile(r"(?<![A-Za-z])(?:private|personal|confidential|family)(?![A-Za-z])|비공개|사적|개인|가족", re.I)


def skip_reason(r, tentative="count", nonwork=(), hit=None):
    """일정 행에 안건을 붙이지 않을 사유(문자열) 또는 None — 종일 · 참석 아님(취소·거절·한가함·설정상 미정 — extract._meeting_skip
    과 같은 판정) · 부재중(busy 3)·근태 · 비업무 · 개인 제외어 · 비공개(분류·제목의 비공개/개인 표기)."""
    ex, _pv = _mods()
    if ex._truthy(r.get("all_day")):
        return "종일"
    if ex._meeting_skip(r, tentative):
        return "참석 아님"
    subj = str(r.get("subject") or "")
    low = subj.lower()
    if str(r.get("busy_status") or "").strip() == "3" or ex._absence_hit(subj):
        return "근태"
    if ex._nonwork_hit(low, nonwork):
        return "비업무"
    if hit is not None and hit(low):
        return "제외어"
    if _PRIVATE_RX.search(subj) or _PRIVATE_CAT_RX.search(str(r.get("categories") or "")):
        return "비공개"
    return None


def load_notes(data_dir, d0, d1, cfg=None, *, ctx=None, stats=None):
    r"""data\outlook\calendar.csv(본 PC + data\추가PC\*) → {(날짜, 'HH:MM', 정규화 제목): 안건}. bodyToAI=false 면 {}.
    · 기간 [d0, d1] 의 시작만 · skip_reason 이 있는 행은 뺀다.
    · 안건 = clean_body(본문) → 개인 제외어가 남으면 뺌 → privacy.sanitize(자격증명이면 뺌) → private_score 가 work 일 때만 →
      noteMaxChars 자. 키의 제목은 회의 신호와 같은 정제(sanitize · 한 줄)를 거친 것이다(신호 text 와 맞대려고).
    · 같은 회의가 여러 뿌리(본 PC·추가 PC)에 있으면 긴 안건을 남긴다.
    stats(dict)를 주면 사유별 건수만 센다(원문 없음)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    if not enabled(cfg):
        return {}
    ex, pv = _mods()
    rows = [r for r in ex._read_multi(data_dir, "outlook", "calendar.csv") if str(r.get("body") or "").strip()]
    if not rows:
        return {}
    a, b = _as_date(d0), _as_date(d1)
    tentative = ex.norm_cfg(cfg)[0]["tentativeMeetings"]
    nonwork = ex._nonwork_list(cfg)
    hit = ex._text_filter(pv.excluded_keywords(cfg))
    ctx = ctx if ctx is not None else pv.make_ctx(cfg, data_dir)
    nmax = note_max(cfg)
    st = stats if isinstance(stats, dict) else {}

    def bump(k):
        st[k] = st.get(k, 0) + 1
    out = {}
    for r in rows:
        t = ex._dt(r.get("start"))
        if t is None or (a and t.date() < a) or (b and t.date() > b):
            continue
        why = skip_reason(r, tentative, nonwork, hit)
        if why:
            bump(why)
            continue
        subj, _c, sdrop = pv.sanitize(ex._one_line(r.get("subject"), None), "signal", ctx)
        note = clean_body(r.get("body"), BODY_MAX)
        if sdrop or not subj or not note:
            bump("본문 없음")
            continue
        if hit(note.lower()):
            bump("제외어")
            continue
        note, _c, drop = pv.sanitize(note, "body", ctx)
        if drop or not note:
            bump("자격증명")
            continue
        if pv.private_score(note) != "work":
            bump("사적")
            continue
        note = _cut(note, nmax)
        k = note_key(t.strftime("%Y-%m-%d %H:%M"), subj)
        if len(note) > len(out.get(k, "")):
            out[k] = note
        bump("붙임")
    return out


# ── G1 앞단 — 출처 일정 파일의 body 열 ───────────────────────────────────────────────────
def g1_body(text, ctx=None, max_len=BODY_MAX):
    """G1 의 본문 한 칸 → (본문, 자격증명이라 비웠나). clean_body(자르지 않고) → privacy.sanitize → max_len 자(토큰을 자르지 않는 경계).
    자르기를 정제 **뒤**에 한다 — 정제가 글을 늘리면('홍길동' → '[사람]') 앞에서 600자로 자른 본문이 다음 수집의 G1 에서 또 잘려
    실행마다 끝 낱말이 깎였다. 정제된 본문에 다시 걸어도 그대로다."""
    c = clean_body(text, _IN_MAX)
    if not c:
        return "", False
    _ex, pv = _mods()
    s, _cats, drop = pv.sanitize(c, "body", ctx)
    if drop:
        return "", True
    return _cut(s, max_len), False


def prep_body_csv(path, ctx=None, *, key_cols=None, max_len=BODY_MAX):
    """출처 일정 파일(cal_<tag>.csv)의 body 열을 g1_body(정리·정제·600자)로 제자리 바꾼다(머리글·열 수·열 순서 불변 — body 열이 없으면
    손대지 않음). 이어지는 scrub_csv 의 body 정제는 이미 정제된 글이라 바꾸지 않는다(멱등).
    · 자격증명이 남은 본문은 비운다(행은 남긴다) — 다음 단계 scrub_csv 가 자격증명 행을 통째로 버려 회의가 사라지지 않게.
    · key_cols(웹·Copilot 출처 — scrub_csv 가 정제 키로 같은 일정을 접는다)를 주면 접혀 사라질 뒤 행의 본문을 남는 첫 행으로
      옮긴다(수집기가 다음 실행에 다시 붙인 원문 행에만 본문이 있을 때 본문이 함께 접혀 사라지지 않게).
    → {"ok", "rows", "cleaned", "blanked", "moved", "changed"} · 실패 {"ok": False, "error"}. 원문·본문을 기록하지 않는다."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {"ok": False, "error": type(e).__name__}
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
        enc = "utf-8-sig" if bom else "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("cp949", "replace")          # Excel 이 다시 저장한 파일 — 다시 쓸 때는 UTF-8(BOM)
        enc = "utf-8-sig"
    nl = "\r\n" if "\r\n" in text[:4096] or not text else "\n"
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as e:
        return {"ok": False, "error": f"csv: {e}"}
    info = {"ok": True, "rows": max(0, len(rows) - 1), "cleaned": 0, "blanked": 0, "moved": 0, "changed": False}
    if not rows or "body" not in rows[0]:
        return info
    _ex, pv = _mods()
    head = rows[0]
    bi = head.index("body")
    kidx = [head.index(c) for c in (key_cols or ()) if c in head]

    def fold_key(r):
        """scrub_csv 와 같은 접기 키 — key_cols 값(제목만 정제 뒤 값). 제목이 자격증명으로 버려질 행은 접히지 않는다(None)."""
        vals = []
        for i in kidx:
            v = r[i] if i < len(r) else ""
            if head[i] == "subject":
                v, _c, dr = pv.sanitize(v, "subject", ctx)
                if dr:
                    return None
            vals.append(v)
        return tuple(vals)
    first = {}
    for n, r in enumerate(rows[1:], 1):
        if not r:
            continue
        if bi < len(r):
            old = r[bi]
            new, blank = g1_body(old, ctx, max_len) if old else ("", False)
            if blank:
                info["blanked"] += 1
            if new != old:
                r[bi] = new
                info["cleaned"] += 1
        if not kidx:
            continue
        k = fold_key(r)
        if k is None:
            continue
        j = first.setdefault(k, n)
        if j != n and bi < len(r) and r[bi]:
            rj = rows[j]
            if len(rj) <= bi:                           # 본문 열이 생기기 전의 짧은 행 — 빈칸으로 늘려 옮긴다
                rj.extend([""] * (bi + 1 - len(rj)))
            if not rj[bi]:
                rj[bi] = r[bi]
                info["moved"] += 1
    info["changed"] = bool(info["cleaned"] or info["moved"])
    if not info["changed"]:
        return info
    buf = io.StringIO()
    csv.writer(buf, lineterminator=nl).writerows(rows)
    tmp = f"{path}.{os.getpid()}.lm28tmp"
    try:
        with open(tmp, "w", encoding=enc, newline="") as f:
            f.write(buf.getvalue())
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "error": f"쓰기 실패({type(e).__name__})"}
    return info
