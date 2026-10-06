# -*- coding: utf-8 -*-
"""WP-24 명령(B §12.1) — run(단계 rc 최악값) · manual-export·manual-import · unlock(죽은 잠금만) · 인자 오류 · 등록부 없음 ·
``tools\\bridge.py`` 진입(ROOT sys.path, -X utf8 -B) · ``tools\\bridge_trace_summary.py`` 요약."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from lm27.bridge import cli, fsio, runner
from lm27.bridge.env import manual_env
from lm27.bridge.transport_stub import StubTransport, envelope_text
from lm27.util import events

from tests.bridge.stub_responder import StubResponder
from tests.fixtures.wp24.rig import REG, RUN, Rig, act_rows, settings
from tests.fixtures.wp24.stages import ActStage

ROOT = Path(__file__).resolve().parents[2]
PC = "pc_0123456789abcdef"


def setUpModule():
    events.configure(mode="off")


class _Specs:
    """runner.resolve_specs 를 시험 단계로 바꿔 끼운다(실제 등록부는 WP-25)."""

    def __init__(self, specs):
        self.table = {s.id: s for s in specs}

    def __call__(self, ids=None):
        if not ids:
            return list(self.table.values())
        out = []
        for i in ids:
            if i not in self.table:
                raise LookupError(f"모르는 단계: {i}")
            out.append(self.table[i])
        return out


class Commands(unittest.TestCase):
    def setUp(self):
        self.r = Rig(stages=[ActStage()])
        self.addCleanup(self.r.cleanup)
        self.orig = runner.resolve_specs
        runner.resolve_specs = _Specs([ActStage()])
        self.addCleanup(setattr, runner, "resolve_specs", self.orig)
        _c, self.raw = settings(self.r.tmp)

    def env(self, transport=None, **kw):
        rt_kw = {"clock": self.r.clock, "registry": REG, "gate_base": self.r.gate_base(), "pc_id": PC,
                 "raw_cfg": self.raw, "heartbeat": False, "emit": None}
        if transport is not None:
            rt_kw["transport"] = transport
        rt_kw.update(kw)
        return {"paths": self.r.paths, "rt_kw": rt_kw}

    def main(self, argv, env):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(argv, **env)
        found = None
        for x in out.getvalue().splitlines():
            try:
                found = json.loads(x)
            except ValueError:
                continue
        return rc, found

    def test_run_stub(self):
        self.r.write_ai_in("t_act", act_rows(5))
        st = StubResponder([ActStage()])
        rc, out = self.main(["run", "--run-id", RUN, "--stages", "t_act"], self.env(StubTransport(st)))
        self.assertEqual((rc, out["rc"], out["stages"]["t_act"]["state"]), (0, 0, "done"))
        st2 = StubResponder([ActStage()], script={"t_act": ["refusal"]})
        self.r.write_ai_in("t_act", act_rows(3, start=10))
        rc, out = self.main(["run", "--run-id", "20261006-090000-0b2c", "--stages", "t_act"],
                            self.env(StubTransport(st2)))
        self.assertEqual((rc, out["stages"]["t_act"]["state"]), (2, "partial"))

    def test_bad_args_and_unknown_stage(self):
        self.assertEqual(self.main([], {})[0], 1)
        self.assertEqual(self.main(["run", "--stages", "t_act", "--run-id", "bad"], {})[0], 1)
        self.assertEqual(self.main(["run", "--stages", "Bad Stage"], {})[0], 1)
        self.assertEqual(self.main(["run", "--stages", "nope"], self.env())[0], 1)
        self.assertEqual(self.main(["--help"], {})[0], 0)
        runner.resolve_specs = self.orig
        if not hasattr(__import__("lm27.bridge.stages", fromlist=["x"]), "REGISTRY"):
            self.assertEqual(self.main(["run", "--stages", "t_act"], self.env())[0], 1)

    def test_manual_export_then_import(self):
        self.r.write_ai_in("t_act", act_rows(3))
        rc, out = self.main(["manual-export"], self.env(env=manual_env(self.r.clock)))
        self.assertEqual((rc, out["open"]), (2, 1))
        mf = json.loads(Path(self.r.paths.copilot_manual(), "manifest.json").read_text("utf-8"))
        b = mf["batches"][0]
        ans = envelope_text(b["rid"], [{"id": i["n"], "act": "ack", "conf": "h"} for i in b["items"]])
        f = Path(self.r.tmp, "answer.txt")
        f.write_bytes(ans.encode("utf-8"))
        rc, out = self.main(["manual-import", "--file", str(f)], self.env())
        self.assertEqual((rc, out["reports"][-1]["committed"]), (0, 3))
        self.assertEqual(self.main(["manual-import"], self.env())[0], 1)

    def test_replay_and_calibrate_without_cdp(self):
        self.r.write_ai_in("t_act", act_rows(4))
        st = StubResponder([ActStage()])
        self.main(["run", "--run-id", RUN, "--stages", "t_act"], self.env(StubTransport(st)))
        rc, out = self.main(["replay", "--run-id", RUN, "--stage", "t_act", "--seq", "1"],
                            self.env(StubTransport(StubResponder([ActStage()]))))
        self.assertEqual((rc, out["status"], out["same_prompt"], out["ok"]), (0, "ok", True, 4))
        self.assertEqual(self.main(["replay", "--run-id", RUN, "--stage", "t_act", "--seq", "9"],
                                   self.env(StubTransport(st)))[0], 1)
        rc, out = self.main(["calibrate"], self.env(StubTransport(st)))
        self.assertEqual((rc, out["error"]), (1, "no_cdp"))

    def test_diagnose_with_fake_session(self):
        from tests.bridge.fake_cdp import FakePage
        from tests.bridge.fake_http import World
        w = World(page_factory=lambda url: FakePage(w.clock, url=url))
        self.addCleanup(w.cleanup)
        rc, out = self.main(["diagnose", "--model"], {"session_factory": lambda: w.session("bridge", RUN)})
        self.assertEqual(rc, 0)
        self.assertTrue(Path(out["file"]).is_file())
        self.assertEqual(out["model_menu"], ["자동", "빠른 응답", "깊이 생각하기"])
        self.assertEqual(out["state"], "ready")

    def test_unlock(self):
        lock = Path(self.r.paths.edge_lock())
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_bytes(json.dumps({"schema": 1, "pid": 999999, "pid_ctime": 1, "role": "bridge",
                                     "acquired": "2026-10-05T10:00:00+09:00"}).encode("utf-8"))
        env = {"paths": self.r.paths, "clock": self.r.clock, "proc_probe": lambda pid, ct=None: True}
        rc, out = self.main(["unlock"], env)
        self.assertEqual((rc, out["lock"]), (1, "busy"))                   # 살아 있는 소유자는 건드리지 않는다
        self.assertTrue(lock.exists())
        env["proc_probe"] = lambda pid, ct=None: False
        rc, out = self.main(["unlock"], env)
        self.assertEqual((rc, out["lock"]), (0, "removed"))
        self.assertFalse(lock.exists())
        self.assertTrue(Path(str(lock) + ".stale").exists())
        self.assertEqual(self.main(["unlock"], env)[1]["lock"], "none")

    def test_events_jsonl_result_and_run_end(self):
        buf = io.StringIO()
        events.configure(mode="jsonl", stream=buf)
        self.addCleanup(events.configure, mode="off")
        rc = cli.main(["unlock"], paths=self.r.paths)
        evs = [json.loads(x)["ev"] for x in buf.getvalue().splitlines()]
        self.assertEqual((rc, evs), (0, ["result"]))
        buf2 = io.StringIO()
        events.configure(mode="off", stream=buf2)
        with contextlib.redirect_stdout(buf2):
            cli.main(["unlock", "--events", "jsonl"], paths=self.r.paths)
        self.assertEqual([json.loads(x)["ev"] for x in buf2.getvalue().splitlines()][-1], "run_end")


class Tools(unittest.TestCase):
    def run_tool(self, *args, env=None):
        e = dict(os.environ)
        e.update(env or {})
        return subprocess.run([sys.executable, "-X", "utf8", "-B", *args], cwd=str(ROOT), capture_output=True,
                              text=True, encoding="utf-8", timeout=120, env=e)

    def test_bridge_entry_help(self):
        r = self.run_tool(str(ROOT / "tools" / "bridge.py"), "--help")
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        self.assertIn("run", r.stdout)
        src = (ROOT / "tools" / "bridge.py").read_text(encoding="utf-8")
        code = [ln for ln in src.splitlines() if ln and not ln.startswith(("#", "r\"\"\"", " ", "\"\"\""))
                and not ln.startswith(("import", "ROOT", "from", "``", "그", "동봉"))]
        self.assertIn("sys.path.insert(0, ROOT)", src)
        self.assertGreater(len(code), 0)

    def test_trace_summary(self):
        sys.path.insert(0, str(ROOT / "tools"))
        self.addCleanup(sys.path.remove, str(ROOT / "tools"))
        import bridge_trace_summary as TS
        rows = [{"kind": "send", "stage": "t_act", "rung": 0, "status": "ok", "done_by": "pledge", "pick": "dom",
                 "busy_seen": True, "gen_sec": 30.0, "reply": 400},
                {"kind": "resend", "stage": "t_act", "rung": 1, "status": "ok", "done_by": "stable", "pick": "fulltext",
                 "busy_seen": False, "gen_sec": 60.0, "reply": 300},
                {"kind": "session", "stage": "", "phase": "ready"}]
        s = TS.summarize(rows)["t_act"]
        self.assertEqual((s["asks"], s["sends"], s["rungs"]), (1, 2, {"0": 1, "1": 1, "2": 0}))
        self.assertEqual((s["busy_seen_ratio"], s["gen_sec_max"], s["reply_avg"]), (0.5, 60.0, 350.0))
        self.assertEqual(s["warnings"], ["stable_over_30pct", "fulltext_pick"])
        r = Rig()
        self.addCleanup(r.cleanup)
        f = Path(r.tmp, "trace.jsonl")
        for row in rows:
            fsio.append_line(f, row)
        p = self.run_tool(str(ROOT / "tools" / "bridge_trace_summary.py"), "--file", str(f), "--json")
        self.assertEqual(p.returncode, 0, p.stderr[-300:])
        self.assertEqual(json.loads(p.stdout)["t_act"]["sends"], 2)
        self.assertEqual(self.run_tool(str(ROOT / "tools" / "bridge_trace_summary.py"), "--file",
                                       str(Path(r.tmp, "none.jsonl"))).returncode, 1)


if __name__ == "__main__":
    unittest.main()
