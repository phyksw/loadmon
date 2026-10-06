# -*- coding: utf-8 -*-
"""WP-24 L2 교환(B §6) — 프롬프트 골격(글자 그대로) · rid · 필드 명세 언어(B §6.5) · 상태 분류 표(B §6.6 순서) ·
채팅 정책(B §6.9) · 재시도 사다리(B §6.7)와 시나리오 B-T18~T22 · T29~T32."""
from __future__ import annotations

import json
import re
import unittest

from lm27.bridge import exchange as X
from lm27.bridge.runner import WorkItem
from lm27.bridge.stages import base as B
from lm27.bridge.transport import SendResult
from lm27.bridge.transport_stub import StubTransport
from lm27.util import events

from tests.bridge.stub_responder import StubResponder
from tests.fixtures.wp24.rig import REG, Rig, act_rows, label_rows
from tests.fixtures.wp24.stages import ActStage, LabelStage, LookupStage

RID = "R7F3QK"


def _items(n):
    return [WorkItem(key=f"k{i}", group="", fields={"ch": "mail", "dir": "in", "chat": "1:1", "prev": "-",
                                                     "text": f"검토 부탁 {i}"}, rule={}, ck=f"c{i}")
            for i in range(1, n + 1)]


def _env(items):
    return json.dumps({"rid": RID, "n": len(items), "items": items}, ensure_ascii=False)


def setUpModule():
    events.configure(mode="off")


class Skeleton(unittest.TestCase):
    def test_footer_and_pledge_once(self):
        spec = ActStage()
        asm = X.assemble(spec, _items(3), B.StageCtx(), RID)
        lines = asm.text.splitlines()
        self.assertEqual(lines[0], f"[LM27 요청 {RID} · 화행 분류 · 항목 3개]")
        self.assertEqual(lines[-1], f"- 코드 블록이 끝나면 맨 마지막 줄에 [[END {RID}]] 만 씁니다.")
        self.assertEqual(asm.text.count(f"END {RID}"), 1)
        self.assertIn('- rid 에는 "R7F3QK" 를, n 에는 items 의 개수를 씁니다. 항목 번호 1~3 을 빠짐없이 한 번씩, '
                      '번호 순서대로 씁니다.', lines)
        self.assertIn(B.NO_WEB_PROMPT, lines)
        self.assertIn("- 근거가 부족하면 지어내지 말고 act 는 info, conf 는 l 로 씁니다.", lines)
        self.assertEqual(asm.item_ids, [1, 2, 3])
        for n, (a, b) in asm.line_spans.items():
            self.assertTrue(asm.text[a:b].startswith(f"{n} | "))
        # 예시 형식은 자리표시자 — 그 자체로 유효한 JSON 이 아니다
        fl = spec.format_line()
        with self.assertRaises(ValueError):
            json.loads(fl)

    def test_lookup_has_no_no_web_line_and_strict_line(self):
        spec = LookupStage()
        it = WorkItem(key="lookup_mail:2026-09-01:2026-09-07", group="", fields={"d0": "2026-09-01",
                                                                                  "d1": "2026-09-07"}, rule={}, ck="c")
        asm = X.assemble(spec, [it], B.StageCtx(), RID, strict_format=True)
        self.assertNotIn(B.NO_WEB_PROMPT, asm.text)
        self.assertIn("구간 2026-09-01~2026-09-07", asm.text.splitlines()[0])
        self.assertIn(B.STRICT_FORMAT_PROMPT, asm.text)
        self.assertNotIn("[항목]", asm.text)

    def test_rid_format_unique(self):
        used = set()
        rids = {X.new_rid(used) for _ in range(500)}
        self.assertEqual(len(rids), 500)
        self.assertTrue(all(re.fullmatch(r"R[2-9A-HJ-NP-TV-Z]{5}", r) for r in rids))

    def test_templates_scan_clean(self):
        """공통 문구 상수(이름에 PROMPT·TEMPLATE)는 정제 scan 0건(selftest '템플릿' 절과 같은 판정)."""
        from lm27.privacy import scan
        n = 0
        for name in dir(B):
            if name.isupper() and re.search(r"(?:^|_)(?:TEMPLATE|PROMPT)S?(?:_|$)", name):
                val = getattr(B, name)
                vals = val.values() if isinstance(val, dict) else (val if isinstance(val, tuple) else (val,))
                for v in vals:
                    self.assertEqual(scan(v), [], name)
                    n += 1
        self.assertGreater(n, 10)


class FieldSpec(unittest.TestCase):
    def setUp(self):
        self.spec = LabelStage()
        self.ctx = B.StageCtx(codes_map={k: frozenset(v) for k, v in REG["codes"].items()})

    def ok(self, **kw):
        base = {"project": "P-0012", "field": "OPT", "func": "ANALYSIS", "title": "공차 해석", "conf": "h"}
        base.update(kw)
        return B.check_item(self.spec, base, self.ctx)

    def test_valid_and_extra_fields(self):
        ans, err, c = self.ok(color="blue")
        self.assertEqual(err, "")
        self.assertNotIn("color", ans)
        self.assertEqual(c["extra_fields"], 1)

    def test_codes(self):
        self.assertEqual(self.ok(project="P-0999")[1], "unknown_code:project")   # B-T31
        self.assertEqual(self.ok(project="NEW")[1], "")
        self.assertEqual(self.ok(field="XX")[1], "unknown_code:field")

    def test_enum_missing_lengths(self):
        self.assertEqual(self.ok(conf="x")[1], "bad_enum:conf")
        self.assertEqual(B.check_item(self.spec, {"project": "NONE"}, self.ctx)[1], "missing:field")
        self.assertEqual(self.ok(title="가")[1], "too_short:title")
        self.assertEqual(self.ok(title="가" * 81)[1], "too_long:title")
        ans, err, c = self.ok(title="가" * 40)
        self.assertEqual((err, len(ans["title"]), c["trunc"]), ("", 30, 1))

    def test_forbidden_time_field(self):
        """B-T32: 분류 답에 시간형 키 → 그 항목 무효(forbidden_field)."""
        ans, err, c = self.ok(start="09:00")
        self.assertEqual((ans, err, c["forbidden_field"]), (None, "forbidden_field", 1))

    def test_lookup_allows_own_time_fields_only(self):
        spec = LookupStage()
        ans, err, _ = B.check_item(spec, {"t": "2026-09-02", "d": "in"}, None)
        self.assertEqual(err, "")
        self.assertEqual(B.check_item(spec, {"t": "2026-09-02", "d": "in", "date": "x"}, None)[1], "forbidden_field")

    def test_nested_list_and_nullable(self):
        from tests.fixtures.wp24.stages import AgentStage
        spec = AgentStage()
        ctx = B.StageCtx(codes_map={"catalog": frozenset({"AG01"})})
        a, e, c = B.check_item(spec, {"m": [{"a": "AG01", "fit": "상", "why": "근거"}] * 5, "need": None}, ctx)
        self.assertEqual((e, len(a["m"]), a["need"], c["list_items"]), ("", 3, None, 2))
        self.assertEqual(B.check_item(spec, {"m": [{"a": "AG09", "fit": "상", "why": "x"}], "need": None}, ctx)[1],
                         "unknown_code:m.a")
        self.assertEqual(B.check_item(spec, {"m": []}, ctx)[1], "missing:need")
        self.assertEqual(B.check_item(spec, {"m": [], "need": {"name": "새 에이전트", "logic": "자동"}}, ctx)[1], "")

    def test_content_key(self):
        s = ActStage()
        a = B.content_key(s, {"ch": "mail", "dir": "in", "chat": "1:1", "text": "도면  검토", "prev": "request"})
        b = B.content_key(s, {"ch": "mail", "dir": "in", "chat": "1:1", "text": "도면 검토", "prev": "-"})
        self.assertEqual(a, b)                                       # NFKC·공백 정리, prev 는 내용 키 밖
        self.assertEqual(len(a), 24)
        self.assertNotEqual(a, B.content_key(s, {"ch": "teams", "dir": "in", "chat": "1:1", "text": "도면 검토"}))


def _res(body, phase="replied"):
    return SendResult(phase=phase, body=body)


class Classify(unittest.TestCase):
    def setUp(self):
        self.spec = ActStage()
        self.meta = X.AsmMeta(rid=RID, item_ids=[1, 2, 3], id_to_key={1: "a", 2: "b", 3: "c"},
                              items=dict(enumerate(_items(3), 1)))
        self.good = [{"id": 1, "act": "request", "conf": "h"}, {"id": 2, "act": "report", "conf": "m"},
                     {"id": 3, "act": "info", "conf": "l"}]

    def st(self, body, phase="replied", spec=None, meta=None):
        return X.classify(spec or self.spec, _res(body, phase), meta or self.meta)

    def test_table(self):
        g = _env(self.good) + f"\n[[END {RID}]]"
        self.assertEqual(self.st(g)[0], "ok")
        s, info = self.st(_env(self.good[:2]))
        self.assertEqual((s, info["missing"]), ("partial", [3]))
        self.assertEqual(self.st(_env(self.good)[:-30])[0], "truncated")
        self.assertEqual(self.st("", "empty_reply")[0], "empty")
        self.assertEqual(self.st("", "no_reply")[0], "timeout")
        self.assertEqual(self.st(_env(self.good)[:-30], "no_reply")[0], "truncated")
        self.assertEqual(self.st("", "login_required")[0], "transport_fatal")
        s, info = self.st("", "input_overflow")
        self.assertEqual((s, info["side"]), ("truncated", "input"))
        self.assertEqual(self.st("", "inject_mismatch")[0], "format")
        self.assertEqual(self.st("", "send_failed")[0], "service_error")
        self.assertEqual(self.st("죄송합니다. 지금은 응답할 수 없습니다.")[0], "service_error")
        self.assertEqual(self.st("죄송하지만 이 요청은 도와드릴 수 없습니다.")[1]["reason"], "policy")
        self.assertEqual(self.st("요청하신 항목을 검토했습니다.")[1]["reason"], "no_envelope")
        bad = [dict(x, act="지시") for x in self.good]
        s, info = self.st(_env(bad))
        self.assertEqual((s, info["reason"]), ("format", "no_valid_items"))
        s, info = self.st(_env([]))
        self.assertEqual(s, "format")
        self.assertEqual(self.st(_env(self.good).replace(RID, "R2K9MP"))[1]["reason"], "stale")
        ex = '{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "act": <request|ack>} ]}'
        self.assertEqual(self.st(ex)[1]["reason"], "example")

    def test_partial_n40_items38(self):
        """B-T29: n=40, items 38 → partial."""
        meta = X.AsmMeta(rid=RID, item_ids=list(range(1, 41)), id_to_key={i: f"k{i}" for i in range(1, 41)},
                         items=dict(enumerate(_items(40), 1)))
        body = json.dumps({"rid": RID, "n": 40, "items": [{"id": i, "act": "info", "conf": "m"}
                                                           for i in range(1, 39)]})
        s, info = X.classify(self.spec, _res(body), meta)
        self.assertEqual((s, info["missing"]), ("partial", [39, 40]))

    def test_dup_and_extra(self):
        """B-T30: 같은 id 두 번 + 낯선 id → 첫 것 채택, dup=1, extra=1."""
        items = [self.good[0], dict(self.good[0], act="ack"), {"id": 9, "act": "info", "conf": "m"}] + self.good[1:]
        s, info = self.st(_env(items))
        self.assertEqual((s, info["dup"], info["extra"], info["answers"][1]["act"]), ("ok", 1, 1, "request"))

    def test_time_field_partial(self):
        items = [dict(self.good[0], start="09:00")] + self.good[1:]
        s, info = self.st(_env(items))
        self.assertEqual((s, info["invalid"]), ("partial", {1: "forbidden_field"}))

    def test_lookup_variants(self):
        spec = LookupStage()
        it = WorkItem(key="w", group="", fields={"d0": "2026-09-01", "d1": "2026-09-07"}, rule={}, ck="c")
        meta = X.AsmMeta(rid=RID, item_ids=[1], id_to_key={1: "w"}, items={1: it})
        body = json.dumps({"rid": RID, "n": 0, "items": []})
        s, info = X.classify(spec, _res(body), meta)
        self.assertEqual((s, info["answers"][1]["rows"]), ("ok", []))
        rows = [{"id": 1, "t": "2026-09-02", "d": "in"}, {"id": 2, "t": "2026-09-02 14:30", "d": "out"},
                {"id": 3, "t": "2026-08-31", "d": "in"}, {"id": 4, "t": "9/2", "d": "in"}]
        s, info = X.classify(spec, _res(json.dumps({"rid": RID, "n": 4, "items": rows})), meta)
        self.assertEqual(s, "ok")
        self.assertEqual([r["t"] for r in info["answers"][1]["rows"]], ["2026-09-02", "2026-09-02"])
        self.assertEqual((info["dropped"]["time_dropped"], info["dropped"]["out_of_window"],
                          info["dropped"]["bad_time"]), (1, 1, 1))
        s, info = X.classify(spec, _res(json.dumps({"rid": RID, "n": 3, "items": rows[:1]})), meta)
        self.assertEqual(s, "partial")
        s, info = X.classify(spec, _res("조회 도구가 없어 요청하신 기간의 내용을 찾을 수 없습니다."), meta)
        self.assertEqual((s, info["reason"], info["lic"]), ("refusal", "unavailable", "noconn"))
        s, info = X.classify(spec, _res("업무 데이터에 액세스할 수 없습니다."), meta)
        self.assertEqual((s, info["lic"]), ("refusal", "nolic"))


class Chat(unittest.TestCase):
    def test_policy(self):
        class C:
            chat_turns = 3
        ch = X.ChatState(C())
        s = ActStage()
        self.assertTrue(ch.need_fresh(s))
        ch.after_send("ok", fresh=True)
        self.assertFalse(ch.need_fresh(s))
        ch.after_send("partial", fresh=False)
        ch.after_send("ok", fresh=False)
        self.assertTrue(ch.need_fresh(s))                   # 같은 채팅 3번 → 새 채팅
        ch.after_send("format", fresh=True)
        self.assertTrue(ch.need_fresh(s))                   # 직전이 ok·partial 아님
        from tests.fixtures.wp24.stages import ReviewStage
        ch2 = X.ChatState(C())
        ch2.after_send("ok", fresh=True)
        self.assertTrue(ch2.need_fresh(ReviewStage()))      # fresh_each


class _Refusing(ActStage):
    def rephrase(self):
        return "화법을 바꾼 머리말입니다. 메시지를 읽고 7가지 중 하나를 고르세요."


class _Clocked(StubTransport):
    """전송마다 가상 시계를 민다(질의 예산 시나리오)."""

    def __init__(self, responder, clock, step):
        super().__init__(responder)
        self.clock, self.step = clock, step

    def roundtrip(self, req):
        self.clock.advance(self.step)
        return super().roundtrip(req)


class Ladder(unittest.TestCase):
    def rig(self, stages, script, rows, **kw):
        r = Rig(stages=stages, script=script, **kw)
        self.addCleanup(r.cleanup)
        for s in stages:
            r.write_ai_in(s.id, rows)
        return r

    def test_T18_echo_resend_new_chat(self):
        r = self.rig([ActStage()], {"t_act": ["echo", "ok"]}, act_rows(5))
        res = r.run()["t_act"]
        reqs = r.transport.requests
        self.assertEqual((len(reqs), res["state"], res["items_ai"]), (2, "done", 5))
        self.assertNotEqual(reqs[0].rid, reqs[1].rid)
        self.assertTrue(reqs[1].fresh)
        self.assertEqual(res["statuses"], {"ok": 1})
        self.assertEqual([j["status"] for j in r.journal("t_act") if j["t"] == "resp"], ["echo", "ok"])

    def test_T19_stale_resend(self):
        r = self.rig([ActStage()], {"t_act": ["stale", "ok"]}, act_rows(4))
        res = r.run()["t_act"]
        self.assertEqual((r.transport.sends, res["items_ai"]), (2, 4))
        resp = [j for j in r.journal("t_act") if j["t"] == "resp"]
        self.assertEqual(resp[0]["reason"], "stale")

    def test_format_resend_adds_strict_line(self):
        r = self.rig([ActStage()], {"t_act": ["format", "ok"]}, act_rows(3))
        r.run()
        self.assertNotIn(B.STRICT_FORMAT_PROMPT, r.transport.sent_texts[0])
        self.assertIn(B.STRICT_FORMAT_PROMPT, r.transport.sent_texts[1])

    def test_T20_refusal_rephrase_then_rule(self):
        spec = _Refusing()
        r = self.rig([spec], {"t_act": ["refusal", "refusal"]}, act_rows(3))
        res = r.run()["t_act"]
        self.assertEqual(r.transport.sends, 2)
        self.assertIn("화법을 바꾼 머리말", r.transport.sent_texts[1])
        self.assertEqual((res["items_rule"], res["items_failed"], res["state"]), (3, 3, "partial"))
        self.assertEqual({c["why"] for c in r.store("t_act")}, {"ai_refused"})
        self.assertIn("BR-REFUSED", r.notified())

    def test_T21_service_error_rung1(self):
        r = self.rig([ActStage()], {"t_act": ["service_error", "ok"]}, act_rows(3))
        res = r.run()["t_act"]
        self.assertEqual(res["rungs"], {"0": 1, "1": 1, "2": 0})
        req = [j for j in r.journal("t_act") if j["t"] == "req"]
        self.assertEqual([q["rung"] for q in req], [0, 1])
        reply1, first1 = r.cfg.rung_timeouts(1)
        self.assertEqual((r.transport.requests[1].reply_timeout_s, r.transport.requests[1].first_token_s),
                         (reply1, first1))
        self.assertEqual(res["state"], "done")

    def test_rung2_uses_fallback_model(self):
        r = self.rig([ActStage()], {"t_act": ["empty", "empty", "ok"]}, act_rows(2))
        r.run()
        self.assertEqual([q.model for q in r.transport.requests], [r.cfg.model_fast, r.cfg.model_fast,
                                                                    r.cfg.model_fallback])

    def test_T22_budget_skip_rung2_defer_then_split(self):
        st = StubResponder([ActStage()], script={"t_act": ["service_error"] * 4 + ["ok"]})
        r = Rig(stages=[ActStage()], responder=st)
        self.addCleanup(r.cleanup)
        r.new_runtime(transport=_Clocked(st, r.clock, 400))
        r.write_ai_in("t_act", act_rows(12))
        res = r.run()["t_act"]
        self.assertEqual(res["counts"]["rung_skipped"], 2)              # 2단 건너뜀 기록(질의 예산 부족)
        self.assertEqual(res["statuses"].get("service_error"), 2)
        req = [j for j in r.journal("t_act") if j["t"] == "req"]
        self.assertEqual([q["depth"] for q in req], [0, 0, 0, 0, 1, 1])   # 연기 1회 → 다시 실패 → 반분
        self.assertEqual([q["n"] for q in req][-2:], [6, 6])
        self.assertEqual((res["items_ai"], res["state"]), (12, "done"))

    def test_T31_unknown_code_requeued_with_note(self):
        seen = {"n": 0}

        def ans(spec, key):
            if key == "grp:00002" and seen["n"] == 0:
                seen["n"] = 1
                return {"project": "P-0999", "field": "OPT", "func": "ANALYSIS", "title": "공차 해석", "conf": "h"}
            return None
        r = Rig(stages=[LabelStage()], answer_fn=ans)
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_label", label_rows(5))
        res = r.run()["t_label"]
        self.assertEqual((res["items_ai"], r.transport.sends), (5, 2))
        resp = [j for j in r.journal("t_label") if j["t"] == "resp"]
        self.assertEqual(resp[0]["invalid"], {"3": "unknown_code:project"})
        self.assertIn("- 주의: project 는 목록에 있는 코드만 씁니다", r.transport.sent_texts[1])
        self.assertEqual(r.transport.sent_texts[1].count("\n1 | "), 1)

    def test_T32_forbidden_time_requeued(self):
        r = self.rig([ActStage()], {"t_act": ["forbidden_time", "ok"]}, act_rows(3))
        res = r.run()["t_act"]
        self.assertEqual((res["items_ai"], res["dropped"].get("forbidden_field")), (3, 1))
        self.assertIn("시각·날짜·공수 필드는 쓰지 않습니다", r.transport.sent_texts[1])


if __name__ == "__main__":
    unittest.main()
