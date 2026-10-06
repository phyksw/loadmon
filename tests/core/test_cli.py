# -*- coding: utf-8 -*-
"""WP-00 lm27.cli — 계약 §7.1 명령 표 · 인자 · rc(§8.3) · 지연 import · 이벤트(§8.6) 시험(같은 프로세스).

다른 WP 의 계약 함수는 가짜로 바꿔 끼워(resolve 대체) '어느 모듈의 어느 함수를 어떤 인자로 부르는가'만 본다.
실제 수집·설치·전송은 하지 않는다.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lm27 import cli
from lm27.paths import Paths
from lm27.util import events

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "wp00" / "cli_commands.json"
TREE = Path(__file__).resolve().parents[2]
JOB = "j20261005180000a1b2"
RUN = "20261005-180000-a1b2"
ITEM = "lm27_team_bundle_2026-07-01_2026-09-30_0123456789ab"
# 가짜 설정(Ctx.cfg 대체) — 분배 시험이 읽는 키만
FAKE_CFG = {"bundle.lockTimeoutSec": 30, "team.serverHost": "team.example.com", "team.serverPort": 9310,
            "team.connectTimeoutSec": 4}


def _load_fixture():
    with open(FIX, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


class _FakeLock:
    instances = []

    def __init__(self, paths, purpose, timeout_s):
        self.purpose, self.timeout_s = purpose, timeout_s
        self.entered = False
        _FakeLock.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        return False


class _FakeItem:
    """대기열 항목(TAB §2.7 QueueItem — path·meta)."""

    def __init__(self, path):
        self.path = path
        self.meta = {"sha256": "0" * 64, "state": "pending"}


class _Recorder:
    """resolve(mod, attr) 대체 — 부른 (mod, attr) 와 인자를 기록하고 가짜 함수(반환 0)를 준다.
    list_items 는 항목 하나, hello 는 result=ok 를 돌려준다(rets 로 바꿀 수 있다)."""

    def __init__(self, ret=0, rets=None, items=None):
        self.resolved = []
        self.calls = {}
        self.ret = ret
        self.items = [_FakeItem(os.path.join("x", ITEM + ".json"))] if items is None else items
        self.rets = {("lm27.team.queue", "list_items"): self.items, ("lm27.team.client", "hello"): {"result": "ok"}}
        self.rets.update(rets or {})

    def __call__(self, modname, attr):
        self.resolved.append((modname, attr))
        if (modname, attr) == ("lm27.bundle.lock", "BundleLock"):
            return _FakeLock

        def fake(*args, **kwargs):
            self.calls[(modname, attr)] = (args, kwargs)
            return self.rets.get((modname, attr), self.ret)
        return fake


class _FakeIdent:
    pc_id = "pc_0123456789abcdef"
    install_id = "0" * 32


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp00_cli_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = Paths(self.tmp, lad=os.path.join(self.tmp, "lad"))
        self.addCleanup(events.configure, "text")

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def subst(self, argv):
        missing = os.path.join(self.tmp, "없는폴더")
        return [self.tmp if a == "@TMPDIR@" else missing if a == "@MISSING@" else a for a in argv]

    def put_current(self, run_id=RUN):
        from lm27.util import fsx
        fsx.atomic_write(self.paths.analysis_current(), fsx.canon_bytes({"run_id": run_id, "from": "2026-07-01",
                                                                         "to": "2026-09-30"}))


class ParserTest(CliCase):
    def test_all_commands_in_parser_and_help(self):
        fx = _load_fixture()
        self.assertEqual([c for c, _ in cli.COMMANDS], fx["commands"])
        rc, out, _err = self.run_main(["--help"])
        self.assertEqual(rc, 0)
        for name in fx["commands"]:
            self.assertIn(name, out)

    def test_help_does_not_import_command_modules(self):
        import sys
        before = set(sys.modules)
        rc, _out, _err = self.run_main(["--help"])
        self.assertEqual(rc, 0)
        new = {m for m in set(sys.modules) - before if m.startswith("lm27.")}
        self.assertFalse(new & {"lm27.collect.run", "lm27.agent.install", "lm27.team.server", "lm27.ui.server",
                                "lm27.pipeline.analyze", "lm27.config"}, new)

    def test_every_case_parses_with_screen_args(self):
        p = cli.build_parser()
        for case in _load_fixture()["cases"]:
            argv = self.subst(case["argv"])
            with self.subTest(argv=argv):
                a = p.parse_args(argv)
                self.assertTrue(callable(a.func))
                a2 = p.parse_args(argv + ["--job", JOB, "--events", "jsonl"])
                self.assertEqual(a2.job, JOB)
                self.assertEqual(a2.events, "jsonl")

    def test_version(self):
        rc, out, _err = self.run_main(["--version"])
        self.assertEqual(rc, 0)
        self.assertIn("LoadMonitor27", out)

    def test_bad_arguments_rc1(self):
        for argv in _load_fixture()["bad"]:
            argv = self.subst(argv)
            with self.subTest(argv=argv), mock.patch.object(cli, "resolve", _Recorder()), \
                    mock.patch.object(cli.Ctx, "cfg", lambda self, overrides=None: dict(FAKE_CFG)):
                rc, _out, err = self.run_main(argv)
                self.assertEqual(rc, 1)
                self.assertIn("[!]", err)

    def test_subcommand_help_rc0(self):
        for argv in (["collect", "--help"], ["team", "--help"], ["agent", "install", "--help"]):
            with self.subTest(argv=argv):
                rc, out, _err = self.run_main(argv)
                self.assertEqual(rc, 0)
                self.assertIn("usage", out)


class DispatchTest(CliCase):
    def setUp(self):
        super().setUp()
        self.put_current()

    def _run_case(self, case, rec):
        cfg_calls = []

        def fake_cfg(ctx_self, overrides=None):
            cfg_calls.append({k: v for k, v in (overrides or {}).items() if v is not None})
            return dict(FAKE_CFG)

        with mock.patch.object(cli, "resolve", rec), \
                mock.patch.object(cli.Ctx, "cfg", fake_cfg), \
                mock.patch.object(cli.Ctx, "ident", lambda ctx_self: _FakeIdent()), \
                mock.patch.object(cli.Ctx, "paths", self.paths):
            rc, out, err = self.run_main(self.subst(case["argv"]))
        return rc, out, err, cfg_calls

    def test_cases_call_contract_functions(self):
        for case in _load_fixture()["cases"]:
            with self.subTest(argv=case["argv"]):
                rec = _Recorder()
                _FakeLock.instances.clear()
                rc, _out, err, cfg_calls = self._run_case(case, rec)
                self.assertEqual(rc, 0, err)
                want = {tuple(c) for c in case["calls"]}
                self.assertEqual(set(rec.resolved), want)
                first = tuple(case["calls"][0])
                self.assertIn(first, rec.calls)                     # 계약 함수가 실제로 불렸다
                args, kwargs = rec.calls[first]
                for k, v in (case.get("kwargs") or {}).items():
                    self.assertIn(k, kwargs, first)
                    self.assertEqual(kwargs[k], v, (first, k))
                ph = self._placeholders(rec)
                if "args" in case:                                  # 계약 시그니처 그대로의 위치 인자
                    self.assertEqual(list(args), [ph(x) for x in case["args"]], first)
                    self.assertEqual(kwargs, {}, first)
                if "args_head" in case:
                    self.assertEqual(list(args[:len(case["args_head"])]), [ph(x) for x in case["args_head"]], first)
                if "args_tail" in case:
                    n = len(case["args_tail"])
                    self.assertEqual(list(args[-n:]), [ph(x) for x in case["args_tail"]], first)
                    self.assertEqual(kwargs, {}, first)
                if ("lm27.bundle.lock", "BundleLock") in want:
                    self.assertTrue(_FakeLock.instances and all(x.entered for x in _FakeLock.instances))
                    self.assertTrue(all(x.timeout_s == 30 for x in _FakeLock.instances))
                if "overrides" in case:
                    got = [c for c in cfg_calls if c]
                    exp = {k: (self.tmp if v == "@TMPDIR@" else v) for k, v in case["overrides"].items()}
                    self.assertIn(exp, got)

    def _placeholders(self, rec):
        def ph(x):
            return {"@ITEM@": rec.items[0] if rec.items else None, "@CFG@": FAKE_CFG, "@TMPDIR@": self.tmp,
                    "@PYEXE@": str(self.paths.python_exe()), "@PATHS@": self.paths}.get(x, x) if isinstance(x, str) else x
        return ph

    def test_collect_passes_paths_and_cfg_positionally(self):
        rec = _Recorder()
        rc, _o, _e, _c = self._run_case({"argv": ["collect", "--auto"]}, rec)
        self.assertEqual(rc, 0)
        args, _kw = rec.calls[("lm27.collect.run", "collect_here")]
        self.assertIs(args[0], self.paths)
        self.assertEqual(args[1], FAKE_CFG)

    def test_queue_item_is_queueitem_not_argv_string(self):
        rec = _Recorder()
        rc, _o, _e, _c = self._run_case({"argv": ["team", "approve", ITEM]}, rec)
        self.assertEqual(rc, 0)
        args, _kw = rec.calls[("lm27.team.queue", "approve")]
        self.assertIs(args[0], rec.items[0])
        self.assertNotIsInstance(args[0], str)

    def test_queue_item_missing_rc4(self):
        for argv in (["team", "preview", "lm27_team_bundle_nope"], ["team", "drop", ITEM],
                     ["team", "export", ITEM, "--dir", "@TMPDIR@"]):
            with self.subTest(argv=argv):
                rec = _Recorder(items=[] if argv[1] != "preview" else None)
                rc, _o, err, _c = self._run_case({"argv": argv}, rec)
                self.assertEqual(rc, 4, err)
                self.assertIn("대기열", err)
                self.assertFalse({k for k in rec.calls if k[1] in ("preview", "mark", "export_to_dir")})

    def test_ping_result_to_rc(self):
        for result, want in (("ok", 0), ("lm24", 2), ("timeout", 2), ("other_lm", 2)):
            with self.subTest(result=result):
                rec = _Recorder(rets={("lm27.team.client", "hello"): {"result": result}})
                rc, out, _e, _c = self._run_case({"argv": ["team", "ping"]}, rec)
                self.assertEqual(rc, want)
                self.assertEqual(json.loads(out)["result"], result)

    def test_ping_ipv6_host_bracketed(self):
        rec = _Recorder()
        rc, _o, _e, _c = self._run_case({"argv": ["team", "ping", "--host", "::1"]}, rec)
        self.assertEqual(rc, 0)
        self.assertEqual(rec.calls[("lm27.team.client", "hello")][0][0], "http://[::1]:9310")

    def test_registry_fetch_refresh_rc(self):
        # 계약 O-14 ② (W2 통합): refresh_registry(paths, cfg, force=True) 의 rc — 0 저장 · 4 이미 최신 · 2 받지 못함
        for ret, want in (({"rc": 0, "status": 200}, 0), ({"rc": 4, "status": 304}, 4), ({"rc": 2, "status": None}, 2),
                          ({"status": 200}, 0), ({"status": 503}, 2)):
            with self.subTest(ret=ret):
                rec = _Recorder(rets={("lm27.team.client", "refresh_registry"): ret})
                rc, _o, _e, _c = self._run_case({"argv": ["team", "registry-fetch"]}, rec)
                self.assertEqual(rc, want)
                args, kw = rec.calls[("lm27.team.client", "refresh_registry")]
                self.assertIs(args[0], self.paths)
                self.assertEqual(kw, {"force": True})
                self.assertNotIn(("lm27.team.client", "fetch_registry"), rec.resolved)

    def test_team_send_item_rc_is_item_rc(self):
        for item_rc in (0, 1, 2, 4):
            with self.subTest(item_rc=item_rc):
                rec = _Recorder(rets={("lm27.team.queue", "send_item"): {"rc": item_rc}})
                rc, _o, err, _c = self._run_case({"argv": ["team", "send", ITEM]}, rec)
                self.assertEqual(rc, item_rc, err)
                self.assertNotIn(("lm27.team.queue", "send_due"), rec.calls)

    def test_report_build_force_passes_force(self):
        rec = _Recorder()
        rc, _o, err, _c = self._run_case({"argv": ["report", "build", "--run", RUN, "--force"]}, rec)
        self.assertEqual(rc, 0, err)
        self.assertEqual(rec.calls[("lm27.report", "build_report")], ((RUN,), {"force": True}))
        rc, _o, err, _c = self._run_case({"argv": ["report", "build", "--run", RUN]}, rec)
        self.assertEqual(rec.calls[("lm27.report", "build_report")], ((RUN,), {}))

    def test_team_build_loads_current_analysis(self):
        rec = _Recorder(rets={("lm27.report", "load_model"): {"model": "합성"}})
        rc, _o, _e, _c = self._run_case({"argv": ["team", "build", "--from", "2026-07-01", "--to", "2026-09-30"]}, rec)
        self.assertEqual(rc, 0)
        self.assertEqual(rec.calls[("lm27.report", "load_model")][0], (RUN,))
        args, kw = rec.calls[("lm27.team.build", "build_and_queue")]
        self.assertEqual((args, kw), (({"model": "합성"}, {"from": "2026-07-01", "to": "2026-09-30"}, FAKE_CFG), {}))

    def test_team_build_without_analysis_rc2(self):
        os.remove(self.paths.analysis_current())
        rec = _Recorder()
        rc, _o, err, _c = self._run_case({"argv": ["team", "build", "--from", "2026-07-01", "--to", "2026-09-30"]}, rec)
        self.assertEqual(rc, 2)
        self.assertIn("분석", err)
        self.assertNotIn(("lm27.team.build", "build_and_queue"), rec.calls)

    def test_unsupported_args_rc1_without_calling(self):
        for argv in (["team-firewall-diag", "--store", "@TMPDIR@"],):
            with self.subTest(argv=argv):
                rec = _Recorder()
                rc, _o, err, _c = self._run_case({"argv": argv}, rec)
                self.assertEqual(rc, 1)
                self.assertIn("아직 지원하지 않는 인자", err)
                self.assertEqual(rec.calls, {})

    def test_agent_install_writes_pc_json_only_on_success(self):
        rec = _Recorder(ret={"rc": 3})
        rc, _o, _e, _c = self._run_case({"argv": ["agent", "install", "--only"]}, rec)
        self.assertEqual(rc, 3)
        self.assertNotIn(("lm27.bundle.pcreg", "ensure_pc_dir"), rec.resolved)

    def test_agent_install_bundle_failure_is_partial(self):
        rec = _Recorder()

        class Boom(_FakeLock):
            def __enter__(self):
                raise PermissionError("읽기 전용")

        def res(mod, attr):
            return Boom if (mod, attr) == ("lm27.bundle.lock", "BundleLock") else _Recorder.__call__(rec, mod, attr)

        with mock.patch.object(cli, "resolve", res), \
                mock.patch.object(cli.Ctx, "cfg", lambda s, overrides=None: {"bundle.lockTimeoutSec": 30}), \
                mock.patch.object(cli.Ctx, "ident", lambda s: _FakeIdent()), \
                mock.patch.object(cli.Ctx, "paths", self.paths):
            rc, _out, err = self.run_main(["agent", "install", "--only"])
        self.assertEqual(rc, 2)
        self.assertIn("PermissionError", err)
        self.assertNotIn("읽기 전용", err)          # 예외 메시지(원문일 수 있음)는 내보내지 않는다

    def test_action_result_not_dumped_in_text_mode(self):
        rc, out, _e, _c = self._run_case({"argv": ["agent", "install", "--only"]}, _Recorder(ret={"healthy": True}))
        self.assertEqual((rc, out), (0, ""))
        rc, out, _e, _c = self._run_case({"argv": ["agent", "status"]}, _Recorder(ret={"healthy": True}))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {"healthy": True})

    def test_rc_passthrough(self):
        for ret, want in ((0, 0), (2, 2), (3, 3), (4, 4), (9, 1), (True, 0), (False, 1), ({"rc": 4}, 4),
                          ({"healthy": False}, 2), ({"healthy": True}, 0)):
            with self.subTest(ret=ret):
                rc, _o, _e, _c = self._run_case({"argv": ["collect", "--auto"]}, _Recorder(ret=ret))
                self.assertEqual(rc, want)

    def test_bridge_passthrough(self):
        got = {}

        def res(mod, attr):
            self.assertEqual((mod, attr), ("lm27.bridge.cli", "main"))

            def main(argv):
                got["argv"] = argv
                got["mode"] = events.mode()
                got["job"] = events.job_id()
                return 2
            return main

        with mock.patch.object(cli, "resolve", res):
            rc, out, _err = self.run_main(["bridge", "run", "--run-id", "20261005-180000-a1b2", "--stages", "task_label",
                                           "--job", JOB, "--events", "jsonl"])
        self.assertEqual(rc, 2)
        self.assertEqual(got["argv"], ["run", "--run-id", "20261005-180000-a1b2", "--stages", "task_label"])
        self.assertEqual(got["mode"], "jsonl")
        self.assertEqual(got["job"], JOB)
        last = json.loads(out.strip().splitlines()[-1])
        self.assertEqual((last["ev"], last["rc"]), ("run_end", 2))

    def test_bridge_bad_job_rc1(self):
        rc, _out, err = self.run_main(["bridge", "probe", "--job", "x"])
        self.assertEqual(rc, 1)
        self.assertIn("--job", err)


class LazyImportTest(CliCase):
    def test_missing_module_rc1_korean(self):
        with mock.patch.object(cli, "module_present", lambda name: False):
            rc, _out, err = self.run_main(["selftest", "privacy"])
        self.assertEqual(rc, 1)
        self.assertIn("아직", err)

    def test_missing_function_rc1(self):
        with mock.patch.object(cli, "module_present", lambda name: True), \
                mock.patch.object(cli.importlib, "import_module", lambda name: object()):
            rc, _out, err = self.run_main(["selftest", "privacy"])
        self.assertEqual(rc, 1)
        self.assertIn("run_selftest", err)

    def test_module_present_walks_parents(self):
        self.assertTrue(cli.module_present("lm27.util.fsx"))
        self.assertFalse(cli.module_present("lm27.없는패키지.x"))
        self.assertFalse(cli.module_present("lm27_nosuch_pkg.sub"))

    def test_internal_error_reports_type_and_location_only(self):
        def res(mod, attr):
            def boom(*a, **k):
                raise ValueError("메일 본문 원문 홍길동")
            return boom

        with mock.patch.object(cli, "resolve", res), \
                mock.patch.object(cli.Ctx, "cfg", lambda s, overrides=None: {}), \
                mock.patch.object(cli.Ctx, "paths", self.paths):
            rc, _out, err = self.run_main(["collect", "--auto"])
        self.assertEqual(rc, 1)
        self.assertIn("ValueError", err)
        self.assertIn("test_cli.py", err)
        self.assertNotIn("원문", err)

    def test_keyboard_interrupt_rc2(self):
        def res(mod, attr):
            def stop(*a, **k):
                raise KeyboardInterrupt
            return stop

        with mock.patch.object(cli, "resolve", res), \
                mock.patch.object(cli.Ctx, "cfg", lambda s, overrides=None: {}), \
                mock.patch.object(cli.Ctx, "paths", self.paths):
            rc, _out, _err = self.run_main(["collect", "--auto"])
        self.assertEqual(rc, 2)


class JobCancelTest(CliCase):
    """--job 명령의 협조형 취소(계약 §8.7 · W2 통합 WP-35 CR): 정지 플래그가 생기면 KeyboardInterrupt → rc 2,
    analyze 에는 cancel() 이 넘어간다. 감시 스레드는 명령이 끝나면 남지 않는다."""

    def _patched(self, res):
        return (mock.patch.object(cli, "resolve", res),
                mock.patch.object(cli.Ctx, "cfg", lambda s, overrides=None: dict(FAKE_CFG)),
                mock.patch.object(cli.Ctx, "paths", self.paths))

    def test_stop_flag_interrupts_command_rc2(self):
        import threading
        import time
        flag = self.paths.ui_job_stop_flag(JOB)
        seen = {}

        def res(mod, attr):
            def slow(*a, **k):
                os.makedirs(flag.parent, exist_ok=True)
                flag.write_bytes(b"stop\n")
                t0 = time.monotonic()
                while time.monotonic() - t0 < 10:      # 감시 스레드가 0.5초 안에 끊는다
                    time.sleep(0.05)
                seen["timeout"] = True
                return 0
            return slow

        before = {t.name for t in threading.enumerate()}
        p1, p2, p3 = self._patched(res)
        with p1, p2, p3:
            rc, _out, err = self.run_main(["collect", "--auto", "--job", JOB, "--events", "jsonl"])
        self.assertEqual(rc, 2, err)
        self.assertNotIn("timeout", seen)
        self.assertNotIn("lm27-cli-stopwatch", {t.name for t in threading.enumerate()} - before)

    def test_no_flag_no_interrupt_and_thread_gone(self):
        import threading

        def res(mod, attr):
            return lambda *a, **k: 0

        p1, p2, p3 = self._patched(res)
        with p1, p2, p3:
            rc, _out, err = self.run_main(["collect", "--auto", "--job", JOB])
        self.assertEqual(rc, 0, err)
        self.assertNotIn("lm27-cli-stopwatch", {t.name for t in threading.enumerate()})

    def test_analyze_gets_cancel_only_with_job(self):
        got = []

        def res(mod, attr):
            def analyze(*a, **k):
                got.append(k)
                return 0
            return analyze

        p1, p2, p3 = self._patched(res)
        with p1, p2, p3:
            self.run_main(["analyze", "--from", "2026-09-01", "--to", "2026-09-30"])
            self.run_main(["analyze", "--from", "2026-09-01", "--to", "2026-09-30", "--job", JOB])
        self.assertNotIn("cancel", got[0])
        self.assertTrue(callable(got[1]["cancel"]))
        self.assertFalse(got[1]["cancel"]())
        flag = self.paths.ui_job_stop_flag(JOB)
        os.makedirs(flag.parent, exist_ok=True)
        flag.write_bytes(b"stop\n")
        self.assertTrue(got[1]["cancel"]())


class EventsModeTest(CliCase):
    def test_jsonl_stdout_only_json_lines(self):
        rc, out, err = self.run_main(["analyze", "--from", "2026-10-01", "--job", JOB, "--events", "jsonl"])
        self.assertEqual(rc, 1)
        lines = [json.loads(x) for x in out.strip().splitlines()]
        self.assertEqual([x["ev"] for x in lines], ["warn", "run_end"])
        self.assertEqual(lines[-1]["rc"], 1)
        seqs = [x["seq"] for x in lines]
        self.assertEqual(seqs, sorted(set(seqs)))
        self.assertIn("--to", err)

    def test_text_mode_stdout_empty_on_error(self):
        rc, out, _err = self.run_main(["analyze", "--from", "2026-10-01"])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_result_event_in_jsonl(self):
        rec = _Recorder(ret={"healthy": True, "registered": True})
        with mock.patch.object(cli, "resolve", rec), \
                mock.patch.object(cli.Ctx, "ident", lambda s: _FakeIdent()), \
                mock.patch.object(cli.Ctx, "paths", self.paths):
            rc, out, _err = self.run_main(["agent", "status", "--events", "jsonl"])
        self.assertEqual(rc, 0)
        evs = [json.loads(x) for x in out.strip().splitlines()]
        self.assertEqual(evs[0]["ev"], "result")
        self.assertEqual(evs[0]["data"], {"healthy": True, "registered": True})
        self.assertEqual(evs[-1]["ev"], "run_end")


class StrictOverrideTest(CliCase):
    """명령줄 --host·--port·--store 는 레지스트리 범위·형식에 어긋나면 기본값으로 바뀌지 않고 rc 1(실제 Ctx.cfg·레지스트리)."""

    def setUp(self):
        super().setUp()
        self.real = Paths(str(TREE), lad=os.path.join(self.tmp, "lad"))   # 레지스트리는 트리 것(읽기만)
        self.got = {}
        real_resolve = cli.resolve

        def res(mod, attr):
            if mod == "lm27.config":
                return real_resolve(mod, attr)
            self.assertEqual((mod, attr), ("lm27.team.server", "serve"))

            def serve(cfg):
                self.got["bind"] = (cfg["teamServer.bindHost"], cfg["teamServer.bindPort"])
                return 0
            return serve
        self.patches = [mock.patch.object(cli, "resolve", res), mock.patch.object(cli.Ctx, "paths", self.real)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_bad_host_is_rejected_not_defaulted(self):
        for host in ("bad host", "127.0.0.1!", "x" * 300):
            with self.subTest(host=host):
                self.got.clear()
                rc, _out, err = self.run_main(["team-server", "--host", host])
                self.assertEqual(rc, 1, err)
                self.assertIn("--host", err)
                self.assertNotIn("bind", self.got)              # 0.0.0.0 으로 조용히 바인드하지 않는다

    def test_low_port_rejected_by_parser(self):
        for port in ("80", "1000", "1023", "70000"):
            with self.subTest(port=port):
                rc, _out, err = self.run_main(["team-server", "--port", port])
                self.assertEqual(rc, 1, err)
                self.assertNotIn("bind", self.got)

    def test_valid_values_apply(self):
        rc, _out, err = self.run_main(["team-server", "--host", "127.0.0.1", "--port", "9400"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.got["bind"], ("127.0.0.1", 9400))

    def test_ctx_cfg_rejects_out_of_range_override(self):
        ctx = cli.Ctx(None, paths=self.real)
        with self.assertRaises(cli.CliError) as cm:
            ctx.cfg({"teamServer.bindPort": 1000})
        self.assertEqual(cm.exception.rc, 1)
        self.assertIn("--port", cm.exception.msg)
        ok = ctx.cfg({"teamServer.bindPort": 9400, "teamServer.bindHost": None})
        self.assertEqual(ok["teamServer.bindPort"], 9400)
        self.assertEqual([w for w in ok.config_warnings if w["key"].startswith("teamServer.")], [])

    def test_ping_bad_host_rc1(self):
        rc, _out, err = self.run_main(["team", "ping", "--host", "bad host"])
        self.assertEqual(rc, 1, err)
        self.assertIn("--host", err)


class RcOfTest(unittest.TestCase):
    def test_rc_of(self):
        class R:
            rc = 2
        self.assertEqual(cli.rc_of(None), 0)
        self.assertEqual(cli.rc_of(None, 3), 3)
        self.assertEqual(cli.rc_of(R()), 2)
        self.assertEqual(cli.rc_of(-1), 1)
        self.assertEqual(cli.rc_of(Path("x")), 0)
        self.assertEqual(cli.rc_of({"rc": True}), 0)        # bool rc 는 rc 로 보지 않는다 → 기본값


if __name__ == "__main__":
    unittest.main()
