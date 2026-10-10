# -*- coding: utf-8 -*-
r"""core\coverage.py — 일자×축 수집 원장(LM28 C-31·C-09·REQ-18·REQ-51) — data\coverage_ledger.json.

축: mail_in(받은 메일)·mail_out(보낸 메일)·cal(일정)·teams·pc. 출처(src)마다 그날 그 축을 어떻게 읽었는지 적고,
합성 상태는 출처 중 최선값이다. 미관측 날을 0시간(일 안 한 날)으로 세지 않게 하는 근거이고(C-31), 수집 사슬은
gaps() 가 빈 날이 남는 동안 다음 경로를 돈다(P3 — 첫 성공에서 멈추지 않는다).
  순위: ok > zero_ok > partial > unverified = out_of_horizon = blocked(= asked) > not_attempted · na 는 축 단위로 따로.
  규칙(LM27 ledger 의 순위·_comgap 1.3 만 가져왔다 — 계획기·rcmap·셀 키는 들이지 않는다):
   · 색인은 zero_ok 를 줄 수 없다(0행이 '없음'의 증거가 아니다). 반복 마스터가 있으면(counts.recurring_masters>0) cal ok 도 없다.
   · Copilot(copilot·teams_copilot)은 증인이다 — ok·zero_ok 를 만들지 않고, 합성에서 다른 출처의 미관측을 덮지 않는다.
     Copilot 이 답했는데 표가 없던 날은 'asked'(다시 묻지 않는다 — gaps(witness=…)).
   · COM 이 zero_ok 인데 색인 행이 있거나, 색인/COM > 1.3(차이 2통 이상)이면 그날 그 축은 suspect — COM·색인의 '읽음'을
     믿지 않고 다른 경로(웹·반입)가 확인할 때까지 공백으로 둔다(C-09 'COM 누락 의심 → 폴백 계속').
   · teams: 모든 출처의 행이 0이고 teams_present=false 면 na(팀즈를 쓰지 않는 PC) — gaps 에서 뺀다.
   · 같은 출처의 새 관측이 그 날의 지난 관측을 바꾼다. 다만 오늘 이전 날의 ok·zero_ok 는 더 나쁜 관측으로 내리지 않는다
     (지난 실행이 확인한 날을 이번 실행의 막힘이 지우지 않게). 오늘 이후 날은 받지 않는다.
   · 판(LM28-COV-1|collect.cursorEpoch)·PC(host)가 다르면 원장을 버린다 — cursorEpoch 를 올리거나 폴더째 다른 PC 로
     옮기면 처음부터. --reset-cursors 는 reset() 으로 모든 축을 not_attempted 로 되돌린다.
   · 출처별 판정 규칙의 판(SRC_RULES)이 원장과 다르면 그 출처의 칸만 지운다 — 웹 경로의 확인 규칙을 고친 판이 나가면
     지난 판이 잘못 '읽음'으로 적은 날을 다음 실행이 다시 읽는다(다른 출처의 표시는 그대로).
읽기 쪽(WP8·WP9): Ledger.load(path).composite(day, axis) · day_status(d0, d1) · summary(d0, d1).
"""
import csv
import json
import os
import time
from datetime import date, timedelta

AXES = ("mail_in", "mail_out", "cal", "teams", "pc")
MAIL_AXES = ("mail_in", "mail_out", "cal")
RANK = {"ok": 0, "zero_ok": 1, "partial": 2, "unverified": 3, "out_of_horizon": 3, "blocked": 3, "asked": 3,
        "not_attempted": 4}
VERIFIED = ("ok", "zero_ok")
WITNESS = frozenset({"copilot", "teams_copilot"})
COMGAP_RATIO = 1.3
COMGAP_MIN_DIFF = 2             # 비율 규칙의 최소 차이(통) — 하루 1~2통 날의 흔들림을 의심으로 만들지 않는다
LEDGER_VER = "LM28-COV-1"
# 출처별 '읽음' 판정 규칙의 판 — 웹 경로의 확인 규칙을 고치면 여기를 올린다. 불러올 때 판이 다른(또는 판이 없는) 출처의
# 칸만 지우고 그 날들을 다시 읽게 한다(다른 출처의 표시는 둔다). 2: 회사 PC 실측 — 첫 listbox 'fits' 로 메일 17건에
# 281일을 확인 처리했고(OWA), 팀즈 웹 전환 확인이 전부 빗나갔다(LM28 OWA-2·TW-2).
SRC_RULES = {"owa": "2", "teams_web": "2"}
FILE_NAME = "coverage_ledger.json"
DAY = timedelta(days=1)


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _days(a, b):
    a, b = _d(a), _d(b)
    if a is None or b is None:
        return
    while a <= b:
        yield a.isoformat()
        a += DAY


def to_ranges(days):
    """날짜 문자열 모음 → 이어진 [(from, to)]"""
    out = []
    for s in sorted(set(days)):
        d = _d(s)
        if d is None:
            continue
        if out and _d(out[-1][1]) + DAY == d:
            out[-1] = (out[-1][0], s)
        else:
            out.append((s, s))
    return out


def union(gaps, axes=None):
    """gaps {축: [(from, to)]} → 여러 축의 합집합 [(from, to)]"""
    days = set()
    for ax, rs in (gaps or {}).items():
        if axes and ax not in axes:
            continue
        for a, b in rs:
            days.update(_days(a, b))
    return to_ranges(days)


def span(gaps, axes=None):
    """gaps → (가장 이른 날, 가장 늦은 날) | None"""
    rs = union(gaps, axes)
    return (rs[0][0], rs[-1][1]) if rs else None


def fmt_ranges(rs):
    """[(from, to)] → 'A:B,C:D' (Get-MailViaCopilot·Get-TeamsViaCopilot --ranges 형식)"""
    return ",".join(f"{a}:{b}" for a, b in rs)


def n_days(rs):
    return sum(((_d(b) - _d(a)).days + 1) for a, b in rs if _d(a) and _d(b))


def day_counts(path, kind):
    """출처 파일 하나의 (날, 축) → 행 수. kind 'mail'(box=sent → mail_out, 그 밖 mail_in) · 'cal'(start)."""
    out = {}
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                if kind == "mail":
                    d = str(r.get("time") or "")[:10]
                    ax = "mail_out" if str(r.get("box") or "").strip().lower() == "sent" else "mail_in"
                else:
                    d = str(r.get("start") or "")[:10]
                    ax = "cal"
                if _d(d):
                    out[(d, ax)] = out.get((d, ax), 0) + 1
    except (OSError, csv.Error):
        pass
    return out


def src_counts(src_dir, tag):
    """data\\outlook\\src 의 mail_<tag>.csv + cal_<tag>.csv → {(날, 축): 행 수}"""
    out = day_counts(os.path.join(src_dir, f"mail_{tag}.csv"), "mail")
    out.update(day_counts(os.path.join(src_dir, f"cal_{tag}.csv"), "cal"))
    return out


class Ledger:
    """일자×축 원장 — 위 머리말 참고. 메모리 dict 하나와 save()."""

    def __init__(self, path=None, ver="", host="", today=None):
        self.path, self.ver, self.host = path, ver, host
        self.today = today or date.today()
        self.days = {}          # {날: {축: {출처: 상태}}}
        self.suspect = {}       # {날: [축]}
        self.na = {}            # {축: bool}
        self.last = {}          # {출처: {rc, reason, at}}
        self.dropped = ""       # 불러올 때 버린 이유(판·PC 가 다름 — 화면 안내용)
        self.dropped_src = []   # 불러올 때 판정 규칙의 판이 달라 칸을 지운 출처(SRC_RULES)

    @classmethod
    def load(cls, path, ver="", host="", today=None):
        led = cls(path, ver, host, today)
        try:
            with open(path, encoding="utf-8-sig") as f:
                o = json.load(f)
        except (OSError, ValueError):
            return led
        if not isinstance(o, dict):
            return led
        if (ver and o.get("ver") != ver) or (host and o.get("host") and o.get("host") != host):
            led.dropped = "ver" if (ver and o.get("ver") != ver) else "host"
            return led
        for k in ("days", "suspect", "na", "last"):
            if isinstance(o.get(k), dict):
                setattr(led, k, o[k])
        old = o.get("src_rules") if isinstance(o.get("src_rules"), dict) else {}
        stale = sorted(s for s, v in SRC_RULES.items() if str(old.get(s) or "") != v)
        if stale:
            led.dropped_src = sorted(s for s, n in led.drop_sources(stale).items() if n)
        return led

    def drop_sources(self, srcs):
        """그 출처들의 칸을 모두 지운다 → {출처: 지운 칸 수}. 판정 규칙이 바뀐 출처의 지난 '읽음'을 믿지 않게(SRC_RULES)."""
        n = dict.fromkeys(srcs, 0)
        for day in list(self.days):
            row = self.days[day] if isinstance(self.days[day], dict) else {}
            for ax in list(row):
                cell = row[ax] if isinstance(row[ax], dict) else {}
                for s in srcs:
                    if s in cell:
                        del cell[s]
                        n[s] += 1
                if not cell:
                    del row[ax]
            if not row:
                del self.days[day]
        return n

    def save(self):
        if not self.path:
            return False
        o = {"v": 1, "ver": self.ver, "host": self.host, "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
             "src_rules": dict(SRC_RULES), "days": self.days, "suspect": self.suspect, "na": self.na, "last": self.last}
        tmp = f"{self.path}.{os.getpid()}.tmp"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(o, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            os.replace(tmp, self.path)
            return True
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    # ── 쓰기 ──
    def _clamp(self, src, axis, st, rc, counts):
        if st not in RANK:
            st = "unverified"
        if src in WITNESS:
            if st in VERIFIED:
                st = "partial"
            if st == "unverified" and rc == 0:
                st = "asked"               # 답은 받았는데 표가 없었다 — 다음 실행이 같은 날을 다시 묻지 않게
        elif src == "index":
            if st == "zero_ok":
                st = "unverified"          # 색인 0행은 '없음'의 증거가 아니다
            if axis == "cal" and st == "ok" and int((counts or {}).get("recurring_masters") or 0) > 0:
                st = "partial"             # 반복 회의 미전개(C-11) — 웹이 다시 읽게
        return st

    def put(self, src, axis, day, st):
        """한 칸 — 같은 출처의 새 관측이 바꾸되, 지난 날의 ok·zero_ok 는 더 나쁜 관측으로 내리지 않는다."""
        d = _d(day)
        if d is None or d > self.today or axis not in AXES:
            return False
        cell = self.days.setdefault(day, {}).setdefault(axis, {})
        old = cell.get(src)
        if old in VERIFIED and d < self.today and RANK.get(st, 9) > RANK.get(old, 9):
            return False
        if old == st:
            return False
        cell[src] = st
        return True

    def apply(self, st, src=None):
        """수집기 상태(collect_status.parse 결과 또는 LMSTATUS dict) 하나 반영 → 바뀐 칸 수."""
        src = src or str(st.get("src") or "")
        if not src:
            return 0
        rc = st.get("rc")
        counts = st.get("counts") if isinstance(st.get("counts"), dict) else {}
        n = 0
        for x in st.get("ranges") or []:
            ax = x.get("axis")
            if ax not in AXES:
                continue
            s = self._clamp(src, ax, str(x.get("st") or ""), rc, counts)
            for day in _days(x.get("from"), x.get("to")):
                n += self.put(src, ax, day, s)
        self.last[src] = {"rc": rc, "reason": str(st.get("reason") or "")[:120],
                          "at": time.strftime("%Y-%m-%d %H:%M")}
        return n

    def comgap(self, com_counts, idx_counts, d0, d1, ratio=COMGAP_RATIO):
        """COM ↔ 색인 일자 대조(C-09) → suspect [(날, 축)]. 기간 안의 지난 의심 표시는 지우고 다시 단다."""
        hits = []
        for day in list(self.suspect):
            if str(d0) <= day <= str(d1):
                del self.suspect[day]
        for day in _days(d0, d1):
            for ax in MAIL_AXES:
                st = ((self.days.get(day) or {}).get(ax) or {}).get("com")
                if st not in VERIFIED:
                    continue
                nc, ni = int(com_counts.get((day, ax)) or 0), int(idx_counts.get((day, ax)) or 0)
                if not ni:
                    continue
                if (nc == 0 and st == "zero_ok") or (nc and ni / nc > ratio and ni - nc >= COMGAP_MIN_DIFF):
                    self.suspect.setdefault(day, [])
                    if ax not in self.suspect[day]:
                        self.suspect[day].append(ax)
                    hits.append((day, ax))
        return hits

    def set_na(self, axis, flag):
        self.na[axis] = bool(flag)

    def reset(self, axes=None):
        """모든(또는 주어진) 축을 not_attempted 로 — --reset-cursors"""
        axes = tuple(axes or AXES)
        for day in list(self.days):
            for ax in axes:
                self.days[day].pop(ax, None)
            if not self.days[day]:
                del self.days[day]
        for day in list(self.suspect):
            self.suspect[day] = [a for a in self.suspect[day] if a not in axes]
            if not self.suspect[day]:
                del self.suspect[day]
        for ax in axes:
            self.na.pop(ax, None)

    # ── 읽기 ──
    def is_suspect(self, day, axis):
        return axis in (self.suspect.get(day) or ())

    def composite(self, day, axis):
        """그날 그 축의 합성 상태 — 증인(Copilot)은 빼고 최선값. na 축은 'na'."""
        if self.na.get(axis):
            return "na"
        best = "not_attempted"
        sus = self.is_suspect(day, axis)
        for src, s in ((self.days.get(day) or {}).get(axis) or {}).items():
            if src in WITNESS:
                continue
            if sus and src in ("com", "index") and s in VERIFIED:
                s = "partial"              # COM 누락 의심 — COM·색인의 '읽음'을 믿지 않는다
            if RANK.get(s, 9) < RANK[best]:
                best = s
        return best

    def is_verified(self, day, axis):
        return self.composite(day, axis) in VERIFIED

    def src_status(self, day, axis, src):
        return ((self.days.get(day) or {}).get(axis) or {}).get(src)

    def gaps(self, axes, d0, d1, witness=None):
        """미검증 날 {축: [(from, to)]} — [d0, min(d1, 오늘)] 에서 합성이 ok·zero_ok 가 아닌 날(na 축 제외).
        witness(출처 이름)를 주면 그 출처가 이미 증언(partial)했거나 답한(asked) 날은 뺀다 — Copilot 에 같은 날을 다시 묻지 않게."""
        hi = min(_d(d1) or self.today, self.today)
        out = {}
        for ax in axes:
            if self.na.get(ax):
                out[ax] = []
                continue
            miss = []
            for day in _days(d0, hi.isoformat()):
                if self.composite(day, ax) in VERIFIED:
                    continue
                if witness and self.src_status(day, ax, witness) in ("partial", "asked"):
                    continue
                miss.append(day)
            out[ax] = to_ranges(miss)
        return out

    def day_status(self, d0, d1, axes=AXES):
        """{날: {축: 합성 상태}} — 보고서·분석(WP8·WP9)용"""
        hi = min(_d(d1) or self.today, self.today)
        return {day: {ax: self.composite(day, ax) for ax in axes} for day in _days(d0, hi.isoformat())}

    def summary(self, d0, d1, axes=AXES):
        """{축: {상태: 날 수}} + suspect 날 수 + na 축 — 화면·last_run 요약"""
        out = {ax: {} for ax in axes}
        for _day, row in self.day_status(d0, d1, axes).items():
            for ax, s in row.items():
                out[ax][s] = out[ax].get(s, 0) + 1
        out["_suspect"] = sum(1 for day in self.suspect if str(d0) <= day <= str(d1))
        out["_na"] = sorted(a for a, v in self.na.items() if v)
        return out
