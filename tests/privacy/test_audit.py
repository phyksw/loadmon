# -*- coding: utf-8 -*-
"""WP-11 감사 시험 — 본문 18키·``path_id``(C10)·값 형식(P-T20), 버린 행 이중 계수 방지(큰 쪽), 기록 실패 보존, 잘못된
필드 계수, 위치(LAD ``store\\privacy_audit``), 보존·제거(O-16), 전 경로 실행 뒤 감사 원문 0(T-07 · P-T20)."""
import json
import unittest
from datetime import date

from lm27.privacy import audit as A
from lm27.privacy import gate as G
from lm27.privacy import records as R
from lm27.privacy import selftest
from lm27.privacy.context import make_gate_context
from tests.fixtures import synth
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.wp11 import helpers as H

T0 = "2026-10-05T01:02:03Z"


def _lines(paths) -> list:
    root = paths.privacy_audit_file("2026-10-05").parent.parent
    out = []
    for p in sorted(root.rglob("*.jsonl")) if root.is_dir() else ():
        out += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return out


class SinkTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.got = []

    def sink(self, stage="collect", src="mail.com", **kw):
        return A.AuditSink(self.got.append, H.PC1, stage, src, clock=lambda: T0, **kw)

    def test_body_keys_C10(self):
        s = self.sink(kid="k0123abcd", config_hash="0123456789abcdef")
        s.add("masked", "phone", 3)
        s.add("remask", "person")
        s.add("priv", "work", 2)
        s.add("ad", "suspect")
        s.add("err", "KeyError")
        s.add("key", "created")
        s.add("cfg", "bad_regex")
        s.add("masked", "x@y.example")                  # 값처럼 보이는 코드 → invalid
        s.add("masked", "123456789")
        self.assertTrue(s.flush(rows_in=5, rows_out=4, dur_ms=12, out_sha256="ab" * 32))
        ev = self.got[0]
        self.assertLessEqual(set(ev), set(A.AUDIT_KEYS))
        self.assertEqual(len(A.AUDIT_KEYS), 18)
        self.assertEqual((ev["path_id"], ev["stage"], ev["ev"], ev["pc_id"]), ("mail.com", "collect", "collect_batch", H.PC1))
        self.assertNotIn("src", ev)
        self.assertEqual(ev["masked"], {"invalid": 2, "person": 1, "phone": 3})
        self.assertEqual(ev["err"], {"KeyError": 1, "cfg.bad_regex": 1, "key.created": 1})
        self.assertEqual((ev["rows_in"], ev["rows_out"], ev["dur_ms"], ev["kid"]), (5, 4, 12, "k0123abcd"))
        self.assertEqual(ev["config_hash"], "0123456789abcdef")
        self.assertEqual(selftest.audit_violations(ev), [])
        self.assertEqual(s.counts()["masked"], {})                       # flush 뒤 초기화

    def test_bad_numbers_counted_not_written(self):
        s = self.sink()
        s.flush(rows_in=-1, out_sha256="원문", foo="bar", kid="kXYZ")
        ev = self.got[0]
        self.assertEqual(ev["err"], {"audit.bad_field": 4})
        self.assertNotIn("out_sha256", ev)
        self.assertEqual(ev["rows_in"], 0)
        with self.assertRaises(ValueError):
            s.add("masked", "phone", -1)

    def test_dropped_reconcile_max_WP15(self):
        s = self.sink()
        for _ in range(3):
            s._note_outcome("dropped", "ad", {})
        s.add("dropped", "ad", 2)                     # 수집기가 같은 사유를 또 넘김 → 큰 쪽
        s.add("dropped", "cred", 1)
        self.assertEqual(s.counts()["dropped"], {"ad": 3, "cred": 1})
        s.add("dropped", "ad", 3)                     # 수집기 누계 5(2 + 3) → 5
        self.assertEqual(s.counts()["dropped"]["ad"], 5)
        s._note_outcome("stored", None, {"phone": 2}, priv="work", ad="keep", ad_partial=True)
        c = s.counts()
        self.assertEqual((c["rows_in"], c["rows_out"], c["masked"], c["priv"], c["ad"]),
                         (4, 1, {"phone": 2}, {"work": 1}, {"keep": 1, "partial": 1}))

    def test_write_failure_keeps_counts(self):
        calls = []

        def flaky(ev):
            calls.append(ev)
            if len(calls) == 1:
                raise PermissionError(13, "locked")
        s = A.AuditSink(flaky, H.PC1, "agent", "pc.sampler", clock=lambda: T0)
        hook = []
        s.after_flush = lambda: hook.append(1)
        s.add("masked", "phone")
        self.assertFalse(s.flush())
        self.assertEqual((s.failed, hook), (1, []))
        s.add("masked", "phone")
        self.assertTrue(s.flush())
        self.assertEqual(calls[-1]["masked"], {"phone": 2})
        self.assertEqual(hook, [1])

    def test_validation(self):
        for args in ((H.PC1, "Collect", "mail.com"), (H.PC1, "collect", "mail.c0m!"), ("PC1", "collect", "mail.com")):
            with self.assertRaises(ValueError):
                A.AuditSink(self.got.append, *args)
        self.assertEqual(A.AuditSink(self.got.append, None, "team_server", "team").pc_id, None)

    def test_default_events(self):
        for stage, ev in (("agent", "collect_batch"), ("load", "load_resanitize"), ("copilot:classify", "gate_copilot"),
                          ("team", "gate_team"), ("key", "key"), ("redact", "rewrite_redact")):
            s = A.AuditSink(self.got.append, H.PC1, stage, "copilot" if stage.startswith("copilot") else "mail.com",
                            clock=lambda: T0)
            s.flush()
            self.assertEqual(self.got[-1]["ev"], ev, stage)
        s.flush("not_an_event")
        self.assertEqual(self.got[-1]["ev"], "rewrite_redact")


class LocationTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_program_and_agent_same_file(self):
        a = A.AuditSink.open(self.sb.paths.data(), H.PC1, "collect", "mail.com", paths=self.sb.paths, clock=lambda: T0)
        b = A.AuditSink.open(None, H.PC1, "agent", "pc.sampler", agent_dir=self.sb.paths.agent_dir(), clock=lambda: T0)
        a.flush()
        b.flush()
        f = self.sb.paths.privacy_audit_file("2026-10-05")
        self.assertTrue(f.is_file())
        evs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["path_id"] for e in evs], ["mail.com", "pc.sampler"])
        self.assertTrue(str(f).startswith(str(self.sb.lad)))
        self.assertFalse((self.sb.root / "data" / "pcs").exists())       # 번들 세그먼트에는 직접 쓰지 않는다

    def test_prune_and_purge(self):
        for day in ("2024-08-31", "2024-09-01", "2024-10-01", "2026-10-05"):
            A.AuditSink.open(None, H.PC1, "agent", "pc.sampler", agent_dir=self.sb.paths.agent_dir(),
                             clock=lambda d=day: d + "T00:00:00Z").flush()
        n = A.prune_audit(self.sb.paths, 24, today=date(2026, 10, 5))
        self.assertEqual(n, 2)                                            # 2024-10-01 이전(24개월)만
        left = sorted(p.name for p in self.sb.paths.privacy_audit_file("2026-10-05").parent.parent.rglob("*.jsonl"))
        self.assertEqual(left, ["20241001.jsonl", "20261005.jsonl"])
        with self.assertRaises(ValueError):
            A.prune_audit(self.sb.paths, 0)
        self.assertEqual(A.purge_audit(self.sb.paths), 2)
        self.assertFalse(self.sb.paths.privacy_audit_file("2026-10-05").parent.parent.exists())
        self.assertEqual(A.purge_audit(self.sb.paths), 0)


class T20Test(unittest.TestCase):
    """P-T20 · T-07: 카나리아를 심은 합성 한 달치 전 경로 정제 + 게이트 3종 실행 뒤 감사 기록 전부 — 허용 키·값 형식만,
    9자리 이상 숫자·@·한글 문장 없음, 카나리아 원값 0."""

    def test_audit_after_full_run(self):
        sb = H.Sandbox()
        self.addCleanup(sb.cleanup)
        cs = canaries()
        plan = synth.plan_month(2026, 9)
        for kind, srcs in synth.SRCS_BY_KIND.items():
            for src in srcs:
                rc = sb.rc(src)
                for r in synth.raw_records(kind, plan, src=src, canaries=cs)[:60]:
                    R.sanitize_record(kind, r, rc)
                rc.audit.add("dropped", "bad_raw", 1)
                rc.audit.flush(rows_in=61)
        au = A.AuditSink.open(None, H.PC2, "copilot:classify", "copilot", agent_dir=sb.paths.agent_dir())
        gctx = make_gate_context(sb.rc("mail.com").sctx, sb.cfg(), H.keyring(), stage="copilot:classify", audit=au,
                                 environ={"COMPUTERNAME": "DESKTOP-TEST01", "USERNAME": "hongtest"}, machine_guid="")
        stage = G.StageSpec("classify", frozenset({"subject"}), frozenset({"subject"}))
        items = [G.GateItem(f"m{i:024x}", {"subject": c.sentence}, {}) for i, c in enumerate(cs) if c.sentence]
        G.gate_copilot(items, stage, gctx)
        G.gate_prompt_text("주민번호 900101-1234567 확인", gctx)
        G.check_team_payload({"x": "a@b.example"}, gctx, {"y": "NUM"})
        evs = _lines(sb.paths)
        self.assertGreater(len(evs), 20)
        for ev in evs:
            self.assertEqual(selftest.audit_violations(ev), [], ev.get("path_id"))
            self.assertLessEqual(set(ev), set(A.AUDIT_KEYS))
        blob = b"".join(p.read_bytes() for p in sb.paths.privacy_audit_file("2026-10-05").parent.parent.rglob("*.jsonl"))
        self.assertEqual(find_canaries(blob, cs, groups=["pii", "ctx", "env"]), [])
        self.assertNotIn(b"@", blob)
        gate_evs = [e for e in evs if e.get("pc_id") == H.PC2]
        self.assertEqual(sorted(e["ev"] for e in gate_evs), ["gate_copilot", "gate_prompt", "gate_team"])
        team = next(e for e in gate_evs if e["ev"] == "gate_team")
        self.assertEqual(team["err"]["gate_team.violations"], 2)


if __name__ == "__main__":
    unittest.main()
