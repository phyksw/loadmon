# -*- coding: utf-8 -*-
r"""core\coverage.py — 일자×축 수집 원장(AgentFinder32) — data\coverage_ledger.json.

축: mail_in(받은 메일)·mail_out(보낸 메일)·cal(일정) 셋뿐이다. 출처(src — com·owa·copilot)마다 그날 그 축을 어떻게 읽었는지 적고,
합성 상태는 출처 중 최선값이다. 날마다 '확인됨(verified — ok·zero_ok)' 과 '확인 안 됨(unverified — 그 밖)' 으로 나뉜다 —
확인 안 된 날은 메일·회의가 없다는 뜻이 아니라 근거가 없다는 뜻이고, 수집 사슬은 gaps() 가 빈 날이 남는 동안 다음 경로를 돈다.
  순위: ok > zero_ok > partial > unverified = out_of_horizon = blocked(= asked) > not_attempted.
  규칙:
   · Outlook 웹(owa)은 받은 메일 축에 칸을 적지 않는다(SRC_BLIND) — 목록이 받는 사람을 보여 주지 않아 받은 메일 행을 모두 빼므로
     (D7), Outlook 웹이 읽은 날도 받은 메일은 확인된 날이 아니다. 그 날의 받은 메일은 다음 경로(Copilot)가 묻는다. 보낸 메일·일정
     칸은 그대로 적는다.
   · Copilot(copilot)은 증인이다 — ok·zero_ok 를 만들지 않고(partial 로 낮춘다), 합성에서 다른 출처의 미관측을 덮지 않는다.
     Copilot 이 답했는데 표가 없던 날은 'asked'(다시 묻지 않는다 — gaps(witness=…)).
   · 같은 출처의 새 관측이 그 날의 지난 관측을 바꾼다. 다만 오늘 이전 날의 ok·zero_ok 는 더 나쁜 관측으로 내리지 않는다
     (지난 실행이 확인한 날을 이번 실행의 막힘이 지우지 않게). 오늘 이후 날은 받지 않는다.
   · 판(AF32-COV-1|collect.cursorEpoch)·PC(host)가 다르면 원장을 버린다. --reset-cursors 는 reset() 으로 모든 축을 not_attempted 로.
   · 출처별 판정 규칙의 판(SRC_RULES)이 원장과 다르면 그 출처의 칸만 지운다.
   · 원자료가 지워지면(보관기한 — retention 의 raw 분류는 data\outlook\** 와 이 원장을 함께 지운다) 원장도 처음부터다: 불러올 때
     정제 파일(data\outlook\src\mail_*.csv·cal_*.csv)이 하나도 없으면 지난 칸을 믿지 않는다(dropped='raw_purged').
   · 분석 기간 창 밖의 날은 prune(d0, d1) 이 지운다(D13 — 그 날의 행도 mailmerge 가 지운다. 나중에 더 긴 기간으로 부르면 다시 읽는다).
읽기 쪽: Ledger.load(path).composite(day, axis) · is_verified · day_flags(d0, d1) · day_status(d0, d1) · summary(d0, d1).
"""
import glob
import json
import os
import time
from datetime import date, timedelta

AXES = ("mail_in", "mail_out", "cal")
MAIL_AXES = AXES
RANK = {"ok": 0, "zero_ok": 1, "partial": 2, "unverified": 3, "out_of_horizon": 3, "blocked": 3, "asked": 3,
        "not_attempted": 4}
VERIFIED = ("ok", "zero_ok")
WITNESS = frozenset({"copilot"})
# 그 출처가 확인하지 못하는 축 — 칸을 적지 않는다(put 이 거절하고, 옛 원장의 그런 칸은 불러올 때 지운다).
# Outlook 웹: 목록에 받는 사람이 없어 받은 메일 행을 모두 뺀다(D7). 남기는 행이 없으니 그날의 받은 메일을 읽었다고 적지 않는다.
SRC_BLIND = {"owa": ("mail_in",)}
LEDGER_VER = "AF32-COV-1"
# 출처별 '읽음' 판정 규칙의 판 — 수집기의 확인 규칙을 고치면 올린다(불러올 때 판이 다른 출처의 칸만 지운다)
SRC_RULES = {"com": "1", "owa": "1"}
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
    """[(from, to)] → 'A:B,C:D' (Get-MailViaCopilot --ranges 형식)"""
    return ",".join(f"{a}:{b}" for a, b in rs)


def n_days(rs):
    return sum(((_d(b) - _d(a)).days + 1) for a, b in rs if _d(a) and _d(b))


def _raw_present(src_dir):
    """정제 파일(mail_*.csv·cal_*.csv)이 하나라도 있나 — 없으면 원자료 보관기한이 지나 지워진 것(원장도 처음부터)."""
    if not src_dir:
        return True
    return bool(glob.glob(os.path.join(src_dir, "mail_*.csv")) or glob.glob(os.path.join(src_dir, "cal_*.csv")))


class Ledger:
    """일자×축 원장 — 위 머리말 참고. 메모리 dict 하나와 save()."""

    def __init__(self, path=None, ver="", host="", today=None):
        self.path, self.ver, self.host = path, ver, host
        self.today = today or date.today()
        self.days = {}          # {날: {축: {출처: 상태}}}
        self.na = {}            # 해당 없음 축 — AF32 의 세 축은 늘 해당한다(읽는 쪽 호환을 위해 빈 dict 로 둔다)
        self.last = {}          # {출처: {rc, reason, at}}
        self.dropped = ""       # 불러올 때 버린 이유(ver · host · raw_purged — 화면 안내용)
        self.dropped_src = []   # 불러올 때 판정 규칙의 판이 달라 칸을 지운 출처(SRC_RULES)

    @classmethod
    def load(cls, path, ver="", host="", today=None, src_dir=None):
        r"""원장 파일 → Ledger. src_dir(없으면 원장 옆 outlook\src)에 정제 파일이 하나도 없으면 지난 칸을 버린다(raw_purged)."""
        led = cls(path, ver, host, today)
        try:
            with open(path, encoding="utf-8-sig") as f:
                o = json.load(f)
        except (OSError, ValueError, TypeError):
            return led
        if not isinstance(o, dict):
            return led
        if (ver and o.get("ver") != ver) or (host and o.get("host") and o.get("host") != host):
            led.dropped = "ver" if (ver and o.get("ver") != ver) else "host"
            return led
        sd = src_dir if src_dir is not None else os.path.join(os.path.dirname(os.path.abspath(path)), "outlook", "src")
        if not _raw_present(sd):
            led.dropped = "raw_purged"
            return led
        for k in ("days", "last"):
            if isinstance(o.get(k), dict):
                setattr(led, k, o[k])
        for day in list(led.days):              # 옛 판의 다른 축(팀즈·PC)은 읽지 않는다
            row = led.days[day] if isinstance(led.days[day], dict) else {}
            for ax in list(row):
                if ax not in AXES:
                    del row[ax]
                elif isinstance(row[ax], dict):                 # 그 출처가 확인하지 못하는 축의 옛 칸(SRC_BLIND)은 믿지 않는다
                    blind = [s for s in row[ax] if ax in SRC_BLIND.get(s, ())]
                    for s in blind:
                        del row[ax][s]
                    if blind and not row[ax]:
                        del row[ax]
            if not row:
                del led.days[day]
        # 판정 규칙의 판이 바뀐 출처의 칸 지우기는 쓰는 쪽(수집 — 판 ver 를 주고 연다)만 한다
        old = o.get("src_rules") if isinstance(o.get("src_rules"), dict) else {}
        stale = sorted(s for s, v in SRC_RULES.items() if str(old.get(s) or "") != v)
        if ver and stale:
            led.dropped_src = sorted(s for s, n in led.drop_sources(stale).items() if n)
        return led

    def drop_sources(self, srcs):
        """그 출처들의 칸을 모두 지운다 → {출처: 지운 칸 수}."""
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
        o = {"v": 2, "ver": self.ver, "host": self.host, "updated": time.strftime("%Y-%m-%d"),
             "src_rules": dict(SRC_RULES), "days": self.days, "last": self.last}
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
    @staticmethod
    def _clamp(src, st, rc):
        if st not in RANK:
            st = "unverified"
        if src in WITNESS:
            if st in VERIFIED:
                st = "partial"
            if st == "unverified" and rc == 0:
                st = "asked"               # 답은 받았는데 표가 없었다 — 다음 실행이 같은 날을 다시 묻지 않게
        return st

    def put(self, src, axis, day, st):
        """한 칸 — 같은 출처의 새 관측이 바꾸되, 지난 날의 ok·zero_ok 는 더 나쁜 관측으로 내리지 않는다.
        그 출처가 확인하지 못하는 축(SRC_BLIND — Outlook 웹의 받은 메일)은 적지 않는다."""
        d = _d(day)
        if d is None or d > self.today or axis not in AXES or axis in SRC_BLIND.get(src, ()):
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
        """수집기 상태(collect_status.parse 결과 또는 AF32STATUS dict) 하나 반영 → 바뀐 칸 수."""
        src = src or str(st.get("src") or "")
        if not src:
            return 0
        rc = st.get("rc")
        n = 0
        for x in st.get("ranges") or []:
            ax = x.get("axis")
            if ax not in AXES:
                continue
            s = self._clamp(src, str(x.get("st") or ""), rc)
            for day in _days(x.get("from"), x.get("to")):
                n += self.put(src, ax, day, s)
        self.last[src] = {"rc": rc, "reason": str(st.get("reason") or "")[:120],
                          "at": time.strftime("%Y-%m-%d")}
        return n

    def reset(self, axes=None):
        """모든(또는 주어진) 축을 not_attempted 로 — --reset-cursors"""
        axes = tuple(axes or AXES)
        for day in list(self.days):
            for ax in axes:
                self.days[day].pop(ax, None)
            if not self.days[day]:
                del self.days[day]

    def prune(self, d0, d1):
        """분석 기간 창 [d0, d1] 밖의 날을 지운다(D13) → 지운 날 수."""
        a, b = _d(d0), _d(d1)
        n = 0
        for day in list(self.days):
            d = _d(day)
            if d is None or (a and d < a) or (b and d > b):
                del self.days[day]
                n += 1
        return n

    # ── 읽기 ──
    def composite(self, day, axis):
        """그날 그 축의 합성 상태 — 증인(Copilot)은 빼고 최선값."""
        best = "not_attempted"
        for src, s in ((self.days.get(day) or {}).get(axis) or {}).items():
            if src in WITNESS:
                continue
            if RANK.get(s, 9) < RANK[best]:
                best = s
        return best

    def is_verified(self, day, axis):
        return self.composite(day, axis) in VERIFIED

    def src_status(self, day, axis, src):
        return ((self.days.get(day) or {}).get(axis) or {}).get(src)

    def gaps(self, axes, d0, d1, witness=None):
        """미검증 날 {축: [(from, to)]} — [d0, min(d1, 오늘)] 에서 합성이 ok·zero_ok 가 아닌 날.
        witness(출처 이름)를 주면 그 출처가 이미 증언(partial)했거나 답한(asked) 날은 뺀다 — Copilot 에 같은 날을 다시 묻지 않게."""
        hi = min(_d(d1) or self.today, self.today)
        out = {}
        for ax in axes:
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
        """{날: {축: 합성 상태}}"""
        hi = min(_d(d1) or self.today, self.today)
        return {day: {ax: self.composite(day, ax) for ax in axes} for day in _days(d0, hi.isoformat())}

    def day_flags(self, d0, d1, axes=AXES):
        """{날: {축: 'verified' | 'unverified'}} — 확인 안 된 날은 '없음'이 아니라 '근거 없음'이다."""
        return {day: {ax: ("verified" if s in VERIFIED else "unverified") for ax, s in row.items()}
                for day, row in self.day_status(d0, d1, axes).items()}

    def summary(self, d0, d1, axes=AXES):
        """{축: {상태: 날 수}} — 화면·last_run 요약"""
        out = {ax: {} for ax in axes}
        for _day, row in self.day_status(d0, d1, axes).items():
            for ax, s in row.items():
                out[ax][s] = out[ax].get(s, 0) + 1
        return out

    def verified_counts(self, d0, d1, axes=AXES):
        """{축: {"verified": 날 수, "unverified": 날 수}} — 수집·제외 현황 카드용(날짜 목록 없이 수만)."""
        out = {ax: {"verified": 0, "unverified": 0} for ax in axes}
        for _day, row in self.day_flags(d0, d1, axes).items():
            for ax, f in row.items():
                out[ax][f] += 1
        return out
