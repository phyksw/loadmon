# -*- coding: utf-8 -*-
r"""구간 산술·정수 배분 — 시간 코어(W 부록 A `intervals.py`, 계약 §2.9 · §5.3).

- 구간은 로컬 초(lsec, 기준점 2020-01-01 00:00 로컬 — 계약 §3.14 · X-174) 반열린 `[a, b)` 튜플의 목록이다.
  `U` 가 정렬·병합하고, `I`·`SUB` 는 병합된 결과를 돌려준다(입력 순서와 무관 — 관문 G2).
- `IvIx` 는 병합된 구간 목록의 이분 탐색 색인(멤버십·겹침·잘라내기 O(log n), 관문 G9 성능).
- `split_int` 는 정수 최대잉여 배분으로 Σ = total 을 정확히 보장한다(보존 법칙 W §5.1 · 팀 R-3).
  동률 정렬 키는 계약 §5.3 · X-208: `(0 if 키가 "u_" 로 시작 else 1, 키)` — 단위업무가 버킷보다 먼저 잉여를 받는다.

표준 라이브러리만 쓴다. 파일을 쓰지 않는다. 참조 구현 `worktime_sim.py`(U·I·SUB·L·IvIx·pre_iv·split_int·
lr_minutes)를 옮겨 계약 이름·동률 규칙으로 바꿨다.
"""
from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping

__all__ = [
    "SLOT",
    "I",
    "IvIx",
    "L",
    "SUB",
    "U",
    "lr_minutes",
    "pre_iv",
    "pts_in",
    "slot_cover",
    "split_int",
    "tie_key",
]

SLOT = 300                     # 5분 슬롯(설정 아님 — 계약 §5.3)

Iv = tuple[int, int]


def U(iv: Iterable[Iv]) -> list[Iv]:
    """구간 합집합: 정렬하고 겹치거나 맞닿은 구간을 합친다. 길이 0 이하 구간은 버린다."""
    src = sorted((a, b) for a, b in iv if b > a)
    out: list[Iv] = []
    for a, b in src:
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def I(A: Iterable[Iv], B: Iterable[Iv]) -> list[Iv]:  # noqa: E743 — 계약 §2.9 이름
    """교집합 A ∩ B(병합된 결과)."""
    A, B = U(A), U(B)
    i = j = 0
    out: list[Iv] = []
    while i < len(A) and j < len(B):
        a, b = max(A[i][0], B[j][0]), min(A[i][1], B[j][1])
        if b > a:
            out.append((a, b))
        if A[i][1] < B[j][1]:
            i += 1
        else:
            j += 1
    return out


def SUB(A: Iterable[Iv], B: Iterable[Iv]) -> list[Iv]:
    """차집합 A − B(병합된 결과)."""
    A, B = U(A), U(B)
    out: list[Iv] = []
    j = 0
    for a, b in A:
        cur = a
        while j < len(B) and B[j][1] <= cur:
            j += 1
        k = j
        while k < len(B) and B[k][0] < b:
            c, d = B[k]
            if c > cur:
                out.append((cur, c))
            cur = max(cur, d)
            if cur >= b:
                break
            k += 1
        if cur < b:
            out.append((cur, b))
    return out


def L(A: Iterable[Iv]) -> int:
    """합집합 길이(초)."""
    return sum(b - a for a, b in U(A))


class IvIx:
    """병합된 구간 목록의 이분 탐색 색인."""

    __slots__ = ("iv", "st")

    def __init__(self, ivs: Iterable[Iv]):
        self.iv = U(ivs)
        self.st = [a for a, _ in self.iv]

    def has(self, t: int) -> bool:
        """t 가 어떤 구간 안에 있는가(`a ≤ t < b`)."""
        i = bisect.bisect_right(self.st, t) - 1
        return i >= 0 and t < self.iv[i][1]

    def hit(self, a: int, b: int) -> bool:
        """[a, b) 와 겹치는 구간이 있는가."""
        i = bisect.bisect_left(self.st, b) - 1
        return i >= 0 and self.iv[i][1] > a

    def clip(self, a: int, b: int) -> list[Iv]:
        """[a, b) 로 잘라낸 구간 목록."""
        i = max(0, bisect.bisect_right(self.st, a) - 1)
        out: list[Iv] = []
        while i < len(self.iv) and self.iv[i][0] < b:
            x, y = max(a, self.iv[i][0]), min(b, self.iv[i][1])
            if y > x:
                out.append((x, y))
            i += 1
        return out

    def length(self, a: int, b: int) -> int:
        """[a, b) 안에서 덮인 길이(초)."""
        return sum(y - x for x, y in self.clip(a, b))


def pts_in(sorted_pts: list[int], a: int, b: int) -> list[int]:
    """정렬된 점 목록에서 닫힌 구간 [a, b] 안의 점."""
    return sorted_pts[bisect.bisect_left(sorted_pts, a):bisect.bisect_right(sorted_pts, b)]


def pre_iv(t: int, pre_s: int) -> Iv:
    """앵커 직전 창(W §3.1): t 가 든 슬롯을 끝으로 round(pre/5분) 슬롯(최소 1)."""
    n = max(1, round(pre_s / SLOT))
    b = (t // SLOT + 1) * SLOT
    return (b - n * SLOT, b)


def slot_cover(ivs: Iterable[Iv], only: set[int] | None = None) -> dict[int, int]:
    """병합된 구간 목록이 슬롯마다 덮는 초. `only` 를 주면 그 슬롯만 센다."""
    cover: dict[int, int] = {}
    for a, b in ivs:
        s = a // SLOT
        while s * SLOT < b:
            if only is None or s in only:
                cover[s] = cover.get(s, 0) + min(b, (s + 1) * SLOT) - max(a, s * SLOT)
            s += 1
    return cover


def tie_key(k) -> tuple[int, str]:
    """최대잉여 동률 정렬 키(계약 §5.3 · X-208): 단위업무(`u_`) 먼저, 그다음 키 사전순."""
    s = str(k)
    return (0 if s.startswith("u_") else 1, s)


def split_int(total: int, weights: Mapping) -> dict:
    """정수 최대잉여 배분 — Σ = total 이 정확히 성립한다. 가중 0 이하 키는 빠진다.

    실수 가중은 1/1000 단위 정수로 바꿔 계산한다(결정적). 잉여 동률은 `tie_key` 순.
    """
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError(f"split_int: total 은 0 이상 정수여야 한다({total!r})")
    w = {k: v for k, v in weights.items() if v > 0}
    if not w or total == 0:
        return {}
    if any(isinstance(v, float) for v in w.values()):
        w = {k: int(round(v * 1000)) for k, v in w.items()}
        w = {k: v for k, v in w.items() if v > 0}
        if not w:
            return {}
    s = sum(w.values())
    base = {k: (total * v) // s for k, v in w.items()}
    rem = total - sum(base.values())
    order = sorted(w, key=lambda k: (-((total * w[k]) % s), tie_key(k)))
    for k in order[:rem]:
        base[k] += 1
    return {k: v for k, v in base.items() if v > 0}


def lr_minutes(sec_by_key: Mapping, total_min: int) -> dict:
    """초 → 정수 분, 최대잉여법으로 Σ = total_min(개인 = 팀 정수 분 표, W §5.6 · TAB R-3)."""
    if total_min <= 0 or not sec_by_key:
        return {}
    return split_int(total_min, {k: v for k, v in sec_by_key.items() if v > 0})
