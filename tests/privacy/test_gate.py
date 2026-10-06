# -*- coding: utf-8 -*-
"""WP-11 게이트 시험 — 단계 등록 검사(P §13.4), G3 ``gate_copilot``(P-T15 — 옛 규칙 행의 HIGH 잔여 제외·MEDIUM 재가림 통과·
감사엔 건수만), 사람·이메일 토큰 축약, 웹 근거(X-112), 카나리아, 최종 프롬프트(P-T16), 팀 라벨(P §14.4), 금지 값(P §14.3),
팀 페이로드(P-T17 — spec 필수·경로·코드만), 서버 모드 게이트 문맥(WP-27·WP-34 요청), 게이트 감사 1줄(P-T35 일부)."""
import json
import re
import unittest

from lm27.privacy import gate as G
from lm27.privacy import selftest
from lm27.privacy.context import make_gate_context
from lm27.privacy.detect import SanitizeContext
from lm27.privacy.rules import HIGH
from tests.fixtures.wp11 import helpers as H

ENV = {"COMPUTERNAME": "DESKTOP-ZQ7K2PX", "USERNAME": "hongtest", "USERDOMAIN": "CORPDOM",
       "USERPROFILE": r"C:\Users\hongtest"}
IP10 = ".".join(("10", "1", "2", "3"))                # 사설 IP 는 런타임 조립(L-21)
STAGE = G.StageSpec("classify", frozenset({"subject", "body", "kind"}), frozenset({"subject", "body"}), 60)


class _Audit:
    def __init__(self):
        self.c, self.flushes = {}, []

    def add(self, counter, key, n=1):
        self.c[f"{counter}.{key}"] = self.c.get(f"{counter}.{key}", 0) + n

    def flush(self, ev=None, **numbers):
        self.flushes.append((ev, numbers))
        return True


def _gctx(**kw):
    sb = kw.pop("sctx", None) or SanitizeContext(key=H.MASTER)
    return G.GateContext(sctx=sb, **kw)


class StageSpecTest(unittest.TestCase):
    def test_forbidden_fields_at_registration(self):
        for f in ("ts_utc", "date", "hours", "effort_min", "start", "pc_id", "who_key", "kid", "counterpart_keys", "mm"):
            with self.subTest(f):
                with self.assertRaises(G.GateSpecError):
                    G.StageSpec("s", frozenset({"subject", f}), frozenset({"subject"}))
        with self.assertRaises(G.GateSpecError):
            G.StageSpec("s", frozenset({"subject"}), frozenset({"body"}))
        with self.assertRaises(G.GateSpecError):
            G.StageSpec("s", frozenset({"subject"}), frozenset({"subject"}), 5)
        self.assertEqual(G.StageSpec("s", {"title", "app"}, {"title"}).allowed_fields, frozenset({"title", "app"}))

    def test_unknown_field_stops_stage(self):
        au = _Audit()
        items = [G.GateItem("m1", {"subject": "정상"}), G.GateItem("m2", {"subject": "x", "ts_utc": "2026-10-05"})]
        with self.assertRaises(G.GateSpecError):
            G.gate_copilot(items, STAGE, _gctx(audit=au))
        self.assertEqual(au.flushes, [])                                  # 아무것도 보내지 않았다


class CopilotGateTest(unittest.TestCase):
    def test_T15_corpus_positives_old_rules(self):
        """옛 규칙 행(원문 PII 가 남은 텍스트)을 게이트에 — HIGH 범주 행은 제외, MEDIUM 만 있는 행은 재가림 통과."""
        rows = [r for r in selftest.load_corpus() if r["type"] == "pos" and not r.get("ctx")]
        items = [G.GateItem(r["id"], {"subject": r["text"]}, {"rules_ver": "2025.1.0"}) for r in rows]
        au = _Audit()
        res = G.gate_copilot(items, G.StageSpec("t15", {"subject"}, {"subject"}, 400), _gctx(audit=au))
        dropped = dict(res.dropped)
        for r in rows:
            high = sorted(set(r["hits"]) & set(HIGH))
            with self.subTest(r["id"]):
                if high:
                    self.assertIn(r["id"], dropped)
                    self.assertTrue(dropped[r["id"]].startswith("pii:"))
                else:
                    self.assertNotIn(r["id"], dropped)
        kept = {it.item_id: it.fields["subject"] for it in res.kept}
        self.assertTrue(kept)
        for iid, text in kept.items():
            exp = next(r["expect"] for r in rows if r["id"] == iid)
            self.assertEqual(text, re.sub(r"\[사람#[^\]]*\]", "[사람]", exp))       # 말뭉치 '[사람#*]' = 아무 태그
        self.assertEqual(sum(v for k, v in res.counts.items() if k.startswith("drop:")), len(dropped))
        self.assertEqual(au.flushes[0][0], "gate_copilot")
        self.assertEqual(au.flushes[0][1], {"rows_in": len(items), "rows_out": len(kept)})
        self.assertTrue(all(isinstance(v, int) for v in au.c.values()))
        self.assertFalse(any(any(ch.isdigit() for ch in k.split(".", 1)[1]) for k in au.c))   # 코드만

    def test_class_drops_and_tokens(self):
        items = [G.GateItem("a", {"subject": "가족 모임"}, {"priv_class": "social"}),
                 G.GateItem("b", {"subject": "웨비나"}, {"ad_band": "suspect"}),
                 G.GateItem("c", {"subject": "[사람#a1b2c3] 님 [이메일@vendor.example] 회신"}, {}),
                 G.GateItem("d", {"subject": "[이메일@사내] [이메일@고객사:C01] 확인", "kind": "mail"}, {}),
                 G.GateItem("e", {"subject": "견적 1,200만원 " + "가" * 80}, {})]
        res = G.gate_copilot(items, STAGE, _gctx())
        self.assertEqual(res.dropped, [("a", "class_private"), ("b", "class_ad")])
        out = {it.item_id: it.fields for it in res.kept}
        self.assertEqual(out["c"]["subject"], "[사람] 님 [이메일@외부] 회신")
        self.assertEqual(out["d"], {"subject": "[이메일@사내] [이메일@고객사:C01] 확인", "kind": "mail"})
        self.assertLessEqual(len(out["e"]["subject"]), 60)
        self.assertIn("[금액]", out["e"]["subject"])
        self.assertEqual(res.counts["remask:money"], 1)
        keyed = G.gate_copilot([items[2]], STAGE, _gctx(person_tokens="keyed")).kept[0].fields["subject"]
        self.assertIn("[사람#a1b2c3]", keyed)

    def test_web_grounding_X112(self):
        it = [G.GateItem("u", {"subject": "자료 https://intra.example/a 참고"}),
              G.GateItem("p", {"subject": "[사람#a1b2c3] 검토"})]
        res = G.gate_copilot(it, STAGE, _gctx(person_tokens="keyed", web_grounding=True))
        self.assertEqual(res.dropped, [("u", "pii:url")])
        self.assertEqual(res.kept[0].fields["subject"], "[사람] 검토")
        res2 = G.gate_copilot(it[:1], STAGE, _gctx())
        self.assertEqual(res2.kept[0].fields["subject"], "자료 [URL] 참고")

    def test_canaries(self):
        g = _gctx(canaries=("DESKTOP-ZQ7K2PX", "hongtest", "abc", "  "))
        self.assertEqual(g.canaries, ("DESKTOP-ZQ7K2PX", "hongtest"))     # 4자 미만·공백 무시
        self.assertTrue(G.canary_hit("desktop-zq7k2px 에서 저장", g))
        self.assertFalse(G.canary_hit("hongtester 폴더", g))               # ASCII 는 영숫자 경계
        res = G.gate_copilot([G.GateItem("x", {"subject": "HONGTEST 폴더 정리"})], STAGE, g)
        self.assertEqual(res.dropped, [("x", "pii:canary")])

    def test_T16_prompt_gate(self):
        au = _Audit()
        g = _gctx(audit=au)
        ok, hits = G.gate_prompt_text("다음 항목을 분류하라: 연락처 010-0000-0000", g)
        self.assertEqual((ok, hits), (False, {"phone": 1}))
        self.assertEqual(au.c["dropped.gate_blocked"], 1)
        ev, nums = au.flushes[0]
        self.assertEqual((ev, nums["rows_out"]), ("gate_prompt", 0))
        self.assertRegex(nums["out_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(G.gate_prompt_text("다음 항목을 분류하라: [사람] 회의 2026-10-05", g), (True, {}))


class TeamLabelTest(unittest.TestCase):
    def test_labels(self):
        g = _gctx(canaries=("hongtest",))
        self.assertEqual(G.check_team_label("설계 검토", g), [])
        self.assertEqual(G.check_team_label("[과제:P-0001] 시험", g), [])
        self.assertEqual(G.check_team_label("[사람#a1b2c3] 회의", g), ["forbidden_pattern"])
        self.assertIn("not_clean", G.check_team_label("010-1234-5678 회신", g))
        self.assertEqual(G.check_team_label("hongtest 메모", g), ["canary"])
        self.assertEqual(G.check_team_label("가" * 41, g), ["too_long"])
        self.assertEqual(G.check_team_label(5, g), ["type"])

    def test_forbidden_codes(self):
        g = _gctx(canaries=("DESKTOP-ZQ7K2PX",))
        cases = {"w0a1b2c3d4e5f6a7b": ["forbidden:who_key"], "d0a1b2c3d4e5f6a7b": ["forbidden:local_key"],
                 "k0123abcd": ["forbidden:kid"], "pc_0a1b2c3d4e5f6a7b": ["forbidden:pc_id"],
                 "3f2a8c1e-9b4d-4e7f-a1c2-5d6e7f8a9b0c": ["forbidden:guid"], "a@b.example": ["forbidden:email"],
                 "C:\\x": ["forbidden:path"], "https://h.example/a": ["forbidden:url"],
                 IP10: ["forbidden:ip"], "123456789": ["forbidden:digits"],
                 "desktop-zq7k2px": ["forbidden:canary"], "정상 라벨": []}
        for s, want in cases.items():
            self.assertEqual(G.forbidden_codes(s, g), want, s)
        self.assertEqual(G.forbidden_codes("p_0123456789ab", g, cls="PERSON_KEY"), [])
        self.assertEqual(G.forbidden_codes("2026", g, cls="NUM"), [])
        self.assertEqual(G.forbidden_codes("1234567890", g, cls="VER"), [])
        self.assertEqual(set(G.FORBIDDEN_CODES), {c for v in cases.values() for c in v})


SPEC = {"schema": "CONST:lm27.team_bundle", "person": {"person_key": "PERSON_KEY", "self_label": "LABEL20",
                                                       "pepper_id": "HEX8?", "field": "ENUM:fields|EMPTY"},
        "units": [{"unit_id": "UNIT_ID", "title": "LABEL40", "grade": "ENUM{A,B}", "apps": ["APP_ID"],
                   "spans": [{"$row": ["DATE", "DATE", "ENUM{lead,active}"]}],
                   "evidence_n": {"$map": "NUM", "$key": "RE:[a-z_]{1,16}"}}],
        "privacy_counts": "COUNTS", "n": "NUM", "t": "SNUM", "ok": "BOOL"}


class TeamPayloadTest(unittest.TestCase):
    def good(self):
        return {"schema": "lm27.team_bundle",
                "person": {"person_key": "p_0123456789ab", "self_label": "팀원", "pepper_id": None, "field": ""},
                "units": [{"unit_id": "u_0123456789", "title": "설계 검토", "grade": "A", "apps": ["excel"],
                           "spans": [["2026-10-01", "2026-10-05", "lead"]], "evidence_n": {"mail": 3}}],
                "privacy_counts": {"phone": 2}, "n": 1, "t": -3, "ok": True}

    def test_spec_required(self):
        for bad in (None, [], "TEAM_SPEC_V1"):
            with self.assertRaises(TypeError):
                G.check_team_payload({}, _gctx(), bad)
        with self.assertRaises(TypeError):
            G.check_team_payload({}, _gctx())                             # pylint: disable=no-value-for-parameter

    def test_clean(self):
        self.assertEqual(G.check_team_payload(self.good(), _gctx(), SPEC), [])

    def test_T17_violations(self):
        mg = "3f2a8c1e-9b4d-4e7f-a1c2-5d6e7f8a9b0c"
        p = self.good()
        p["units"][0]["title"] = "w0123456789abcdef 검토"
        p["person"]["self_label"] = "kim@corp.example"
        p["units"][0]["apps"] = ["C:\\x.exe"]
        p["n"] = "123456789"
        p["privacy_counts"] = {"phone": 1, mg: 2}
        p["units"][0]["evidence_n"] = {"BAD KEY": 1}
        p["zz_" + "unknown"] = {"inner": IP10}
        p[mg] = 1
        au = _Audit()
        out = G.check_team_payload(p, _gctx(audit=au, canaries=("hongtest",)), SPEC)
        codes = {(v.path, v.code) for v in out}
        self.assertIn(("units[0].title", "forbidden:who_key"), codes)
        self.assertIn(("person.self_label", "forbidden:email"), codes)
        self.assertIn(("units[0].apps[0]", "bad_app_id"), codes)
        self.assertIn(("units[0].apps[0]", "forbidden:path"), codes)
        self.assertIn(("n", "bad_num"), codes)
        self.assertIn(("privacy_counts{0}", "forbidden:guid"), codes)
        self.assertIn(("units[0].evidence_n{0}", "bad_re"), codes)
        self.assertIn(("zz_unknown", "unknown_key"), codes)
        self.assertIn(("zz_unknown.inner", "forbidden:ip"), codes)
        self.assertTrue(any(c == "unknown_key" and p_.startswith("{") for p_, c in codes))   # 금지 값 키 → 자리표
        blob = json.dumps([list(v) for v in out], ensure_ascii=False)
        for raw in ("w0123456789abcdef", "kim@corp.example", "123456789", mg, IP10, "BAD KEY"):
            self.assertNotIn(raw, blob)                                      # 경로·코드만(값 없음)
        self.assertEqual(out, sorted(set(out)))
        path, code = out[0]                                                  # 튜플로도 풀린다
        self.assertEqual((path, code), (out[0].path, out[0].code))
        self.assertEqual(au.c["gate_team.violations"], len(out))
        self.assertEqual(au.flushes, [("gate_team", {"rows_in": 1, "rows_out": 0})])
        au2 = _Audit()
        self.assertEqual(G.check_team_payload(self.good(), _gctx(audit=au2), SPEC), [])
        self.assertEqual(au2.flushes, [])                                    # 통과면 호출자가 sha 와 함께 기록

    def test_nullable_empty_row_shapes(self):
        p = self.good()
        p["person"]["pepper_id"] = "zz"
        p["person"]["field"] = None
        p["units"][0]["spans"] = [["2026-10-01", "lead"]]
        p["units"] = {"not": "a list"}
        out = {(v.path, v.code) for v in G.check_team_payload(p, _gctx(), SPEC)}
        self.assertIn(("person.pepper_id", "bad_hex8"), out)
        self.assertIn(("person.field", "bad_enum"), out)
        self.assertIn(("units", "bad_list"), out)

    def test_real_team_spec_if_present(self):
        try:
            from lm27.team.schema import TEAM_SPEC_V1
        except ModuleNotFoundError:
            self.skipTest("lm27.team.schema 없음")
        p = {"schema": "lm27.team_bundle", "schema_version": "1.0", "person": {"person_key": "p_0123456789ab",
             "self_label": "a@b.example", "peer_scope": "team"}, "units": [{"title": "w0123456789abcdef"}],
             "mystery": "C:\\x"}
        codes = {(v.path, v.code) for v in G.check_team_payload(p, _gctx(), TEAM_SPEC_V1)}
        self.assertIn(("person.self_label", "forbidden:email"), codes)
        self.assertIn(("units[0].title", "forbidden:who_key"), codes)
        self.assertIn(("mystery", "unknown_key"), codes)
        self.assertNotIn(("schema", "bad_const"), codes)


class GateContextTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_program_mode_canaries(self):
        rc = self.sb.rc("mail.com")
        local = {"person_dir": {"people": {"w" + "1" * 16: {"self": True, "smtp": ["hong.gd@corp.example"],
                                                            "names": ["홍길동"]}}}}
        cfg = self.sb.cfg(**{"collect.ownerAddress": "owner01@corp.example", "privacy.copilot.personTokens": "keyed"})
        from lm27.privacy.context import LocalOnly
        g = make_gate_context(rc.sctx, cfg, H.keyring(), stage="copilot:classify", audit=None, environ=ENV,
                              machine_guid="3f2a8c1e-9b4d-4e7f-a1c2-5d6e7f8a9b0c",
                              local=LocalOnly(person_dir=local["person_dir"]))
        can = set(g.canaries)
        for want in ("DESKTOP-ZQ7K2PX", "hongtest", "CORPDOM", "owner01@corp.example", "owner01", "hong.gd@corp.example",
                     "hong.gd", "3f2a8c1e-9b4d-4e7f-a1c2-5d6e7f8a9b0c", "3f2a8c1e9b4d4e7fa1c25d6e7f8a9b0c"):
            self.assertIn(want, can)
        self.assertNotIn("홍길동", can)                                    # 4자 미만 카나리아는 무시(P §13.2 오탐 방지)
        import base64
        self.assertIn(base64.b64encode(H.MASTER).decode()[:16], can)
        self.assertEqual((g.person_tokens, g.stage, g.web_grounding), ("keyed", "copilot:classify", False))
        g2 = make_gate_context(rc.sctx, cfg, H.keyring(), stage="copilot:x", audit=None, environ=ENV, machine_guid="",
                               web_grounding=True)
        self.assertEqual((g2.person_tokens, g2.web_grounding), ("plain", True))

    def test_server_mode_WP27(self):
        g = make_gate_context(None, self.sb.cfg(), None, stage="team_server", audit=None, environ=ENV, machine_guid="")
        self.assertIsInstance(g.sctx, SanitizeContext)
        self.assertEqual(set(g.canaries), {"DESKTOP-ZQ7K2PX", "hongtest", "CORPDOM"})
        out = G.check_team_payload({"x": "DESKTOP-ZQ7K2PX"}, g, {"x": "LABEL20"})
        self.assertIn(("x", "forbidden:canary"), {(v.path, v.code) for v in out})

    def test_T35_cloud_pc_gate_audit_one_line(self):
        from lm27.privacy.audit import AuditSink
        cloud = "pcx_0a0b0c0d0e0f0a0b"
        au = AuditSink.open(None, cloud, "copilot:classify", "copilot", agent_dir=self.sb.paths.agent_dir(),
                            clock=lambda: "2026-10-05T03:00:00Z")
        g = make_gate_context(self.sb.rc("mail.com").sctx, self.sb.cfg(), H.keyring(), stage="copilot:classify",
                              audit=au, environ=ENV, machine_guid="")
        G.gate_copilot([G.GateItem("m1", {"subject": "회의 일정"})], STAGE, g)
        f = self.sb.paths.privacy_audit_file("2026-10-05")
        evs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(e["pc_id"], e["ev"], e["path_id"]) for e in evs], [(cloud, "gate_copilot", "copilot")])
        self.assertFalse(self.sb.paths.store_dir(H.PC1).exists())          # 다른 pc_id 폴더 불변(만들지도 않음)


if __name__ == "__main__":
    unittest.main()
