# -*- coding: utf-8 -*-
"""W2 검토 C07 — 시간 코어 단위업무 형성(`episodes._Builder`)의 성능 경로가 예전 고리와 같은 결과를 내는가.

9개월(행 140,283) 프로필에서 `analyze_time` 54~68초의 대부분이 업무 형성의 세 고리였다(cProfile 196초 중 build_tasks 175초):
자체 업무 병합 후보 훑기(모든 자체 업무 × 문서군 구간 — 토큰 유사도 1천만 회), 비보고 발신의 업무 찾기(발신 × 모든 업무,
업무 토큰 집합을 매번 다시 만듦), 회의 연결(회의 × 모든 업무, 차수·끝 시각을 매번 다시 계산). 고친 뒤:

- 자체 업무 병합: 업무의 가장 이른 진행 시각(= 만든 구간 t0)이 만든 순서로 단조 증가 → 시각 창 꼬리만 이분 탐색, 범용
  문서군 업무 표지·토큰 집합을 만들 때 한 번.
- 비보고 발신: 업무 토큰 집합을 한 번만(빈 집합 제외 — 유사도 0).
- 회의 연결: 업무별 창을 한 번 계산해 시작순 이분 탐색.

세 고리 모두 '최댓값 · 동점은 작은 id' 또는 '첫 일치' 규칙이고 고리 안에서 바뀌는 값(flags·meet_refs·rels·p_times 뒤쪽)은
판정 재료가 아니라 결과가 같다. 이 시험은 예전 고리를 그대로 옮긴 `_OldBuilder` 로 같은 세계를 돌려 결과 파일 9종이 바이트까지
같은지 본다(무작위 성능 세계 여러 벌 + 시나리오). 전체 동치는 WP-20 G7(무작위 1,000 세계 고정 서명)·골든이 함께 지킨다.

측정(이 PC · cProfile 없이): 3개월 7.0~7.7초 → 6.6초, 9개월 54.2초(검토 67.6초) → tests\\pipeline\\test_perf_c07 머리 표.
"""
from __future__ import annotations

import unittest
from unittest import mock

from lm27.time import episodes as EP
from lm27.time.calendar import DAY, d_of
from lm27.time.episodes import APP_TASK_CLS, B_GENERIC, Cycle, _mmdd, raw_tokens, tok_sim
from lm27.time.intervals import U
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X


class _OldBuilder(EP._Builder):
    """W2 검토 C07 이전의 `self_tasks`·`meetings`(대조 기준 — 글자 그대로 옮김)."""

    def self_tasks(self) -> None:
        selfs = []
        last_of = {}
        order = sorted((sg.t0, f, sg.i) for f in self.segs for sg in self.segs[f])
        for _t0, f, i in order:
            sg = self.segs[f][i]
            if sg.links or f == B_GENERIC:
                continue
            merged = None
            if not self.is_generic(f):
                for tk in selfs:
                    if any(self.is_generic(g) for g in tk.docs):
                        continue
                    if tok_sim(self.ftoks(f), self.toks(tk.tokens), self.ml) >= self.merge_sim and \
                            abs(sg.t0 - min(tk.p_times)) <= self.merge_days * DAY:
                        merged = tk
                        break
            if merged is None:
                key = f"{f}|{d_of(sg.t0).isoformat()}"
                merged = self.new("SELF", f"SELF:{f}@{_mmdd(sg.t0)}", key, tokens=set(self.ftoks(f)),
                                  follow_of=last_of.get(f))
                merged.cycles.append(Cycle(None, "S2p"))
                selfs.append(merged)
            merged.docs[f] = 3
            merged.p_times += sg.times
            sg.links[merged.id] = 3
            merged.segs.append((f, sg.i))
            last_of[f] = merged.id
        app_ev = {}
        for s in self.ev.samples:
            if s.state == "active" and not s.fam and s.cls in APP_TASK_CLS and s.priv not in ("private", "social"):
                app_ev.setdefault(s.app, []).append((s.a, s.b))
        for app, ivs in sorted(app_ev.items()):
            ivs = U(ivs)
            groups, cur = [], [ivs[0]]
            for iv in ivs[1:]:
                if self.wd(cur[-1][1], iv[0]) > self.split_wd:
                    groups.append(cur)
                    cur = []
                cur.append(iv)
            groups.append(cur)
            for g in groups:
                tk = self.new("APP", f"APP:{app}@{_mmdd(g[0][0])}", f"app:{app}|{d_of(g[0][0]).isoformat()}",
                              tokens=raw_tokens([app], self.boiler), app=app)
                tk.p_times = [a for a, _ in g] + [b - 1 for _, b in g]
                tk.cycles.append(Cycle(None, "S2p"))
                self.app_task.setdefault(app, []).append((g[0][0], g[-1][1], tk.id))
        for m in self.orphan_reports:
            fa = set(m.atts)
            exact = m.prec in EP.EXACT
            cands = [t for t in self.tasks if t.kind == "SELF" and fa & set(t.docs) and t.p_times and
                     min(t.p_times) <= m.t and t.cycles[-1].e is None]
            if cands:
                tk = max(cands, key=lambda t: (max(x for x in t.p_times if x <= m.t), t.id))
                c = tk.cycles[-1]
                c.e, c.eb, c.e_ref = (m.t if exact else self.day_end(m.t)), ("E1" if exact else "E1d"), m.id
                tk.peer = m.peer
                tk.peers.add(m.peer)
                tk.convs.add(m.conv)
                tk.tokens |= set(m.tokens)
                tk.rel(m.peer, "reporter")
                self.msg_task[m.id] = tk.id
            else:
                pre = self.pre_mail if m.ch == "mail" else self.pre_teams
                tk = self.new("REPORT_ONLY", f"REPORT:{m.conv}", m.key, conv=m.conv, peer=m.peer, peers={m.peer},
                              tokens=set(m.tokens), convs={m.conv})
                tk.rel(m.peer, "reporter")
                for f in fa:
                    tk.docs[f] = 3
                c = Cycle(m.t - pre, "S2p")
                c.e, c.eb, c.e_ref = (m.t if exact else self.day_end(m.t)), ("E1" if exact else "E1d"), m.id
                tk.cycles.append(c)
                tk.p_times = [m.t]
                tk.flags.append("단발보고(진행 증거 없음)")
                self.msg_task[m.id] = tk.id
                self.by_conv[m.conv].append(tk)
        for m in self.unlinked_sends:
            best, bs = None, 0.0
            mt = self.toks(m.tokens)
            for tk in self.tasks:
                if tk.kind in ("APP", "REPORT_ONLY"):
                    continue
                sc = tok_sim(mt, self.toks(tk.tokens) | self.doc_toks(tk), self.ml)
                if sc > bs or (sc == bs and best is not None and tk.id < best.id):
                    best, bs = tk, sc
            if best is not None and bs >= self.send_sim:
                best.p_times.append(m.t)
                best.rel(m.peer, "thread")
                self.msg_task[m.id] = best.id

    def meetings(self) -> None:
        for mt in self.env.counted_meetings:
            best, bs = None, 0.0
            mtoks = self.toks(mt.tokens)
            for tk in self.tasks:
                if tk.kind not in ("S1", "ACK", "COORD", "SELF", "REPORT_ONLY"):
                    continue
                s0 = tk.cycles[0].s if tk.cycles[0].s is not None else (tk.p_times[0] if tk.p_times else None)
                if s0 is None:
                    continue
                e = tk.last_end() if not tk.is_open() else self.as_of
                if not (s0 - self.meet_back <= mt.a <= (e or self.as_of) + self.e3c_ahead):
                    continue
                tt = self.toks(tk.tokens) | self.doc_toks(tk)
                sc = 2.0 * bool(self.requester_in(mt, tk)) + 2.5 * tok_sim(mtoks, tt, self.ml)
                if sc > bs or (sc == bs and best is not None and tk.id < best.id):
                    best, bs = tk, sc
            if best is not None and bs >= self.meet_min:
                self.meet_task[mt.id] = best.id
                best.flags.append(f"회의연결 {mt.id}")
                rv = bool(mtoks & self.review_words) or \
                    tok_sim(mtoks, self.toks(best.tokens) | self.doc_toks(best), self.ml) > 0
                best.meet_refs.append((mt, rv))
                for a in mt.attendees:
                    best.rel(a, "meeting")


def _files(w, cfg, *, old: bool) -> dict:
    if old:
        with mock.patch.object(EP, "_Builder", _OldBuilder):
            res, _names = H.run(w, cfg, ref_ids=False)
    else:
        res, _names = H.run(w, cfg, ref_ids=False)
    return res.files()


class BuilderEquivTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()

    def check(self, w, cfg=None):
        new, old = _files(w, cfg or self.cfg, old=False), _files(w, cfg or self.cfg, old=True)
        self.assertEqual(sorted(new), sorted(old))
        for name in sorted(new):
            self.assertEqual(new[name], old[name], name)

    def test_perf_worlds(self):
        for months, seed in ((1, 26), (0.5, 7), (1, 3)):
            with self.subTest(months=months, seed=seed):
                w, _n = H.gen_months(months, seed)
                self.check(w)

    def test_short_merge_window_and_more_meetings(self):
        """병합 창을 줄이고(이분 탐색 경계가 자주 걸림) 회의를 늘린 세계."""
        w, _n = H.gen_months(1, 11, per_day=(300, 250, 150, 9, 6))
        self.check(w, self.cfg.derive({"episode.selfMergeDays": 2}))

    def test_scenarios(self):
        """WP-20 시나리오 전부(시작·종료 조합 · 회의 연결 · 자체 업무 · 고아 보고 등)."""
        for name, fn in sorted(X.SC.items()):
            with self.subTest(scenario=name):
                self.check(fn())

if __name__ == "__main__":
    unittest.main()
