"""Additional-PC UI -> API -> runner routing, without real processes or accounts."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import test_collection_ui as page_harness
import test_outlook_collection_reliability as outlook_harness
from test_transfer_ui import definitions


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LoadMonitor25" / "core"))
from communication import CommunicationCollection


class AdditionalPcCollectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-additional-pc-route-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = definitions({"validate_run_request", "run_job", "do_POST"})
        self.commands, self.workers = [], []
        self.env.update(ROOT=str(self.root), subprocess=SimpleNamespace(
            PIPE=-1, STDOUT=-2, Popen=self.process))

        def thread(**request):
            def start():
                self.workers.append(request)
                request["target"](*request.get("args", ()), **request.get("kwargs", {}))
            return SimpleNamespace(start=start)

        self.env["threading"].Thread = thread
        # An existing user's old config must not silently suppress explicit UI collection.
        self.config = {"collectOnlyHeadless": True, "graph": {"clientId": ""},
                       "preferApp": True, "mailViaWeb": False, "teamsWeb": False,
                       "mailViaCopilot": True, "teamsViaCopilot": True,
                       "collection": {"mailWebBody": True}}

    def process(self, command, **_):
        self.commands.append(command)
        return SimpleNamespace(pid=123, stdout=io.BytesIO(b""), returncode=2, wait=lambda: None)

    def post(self, values, path='/api/run'):
        raw = json.dumps({"from": "2026-09-01", "to": "2026-09-20", **values}).encode()
        replies = []
        handler = SimpleNamespace(path=path, rfile=io.BytesIO(raw),
                                  headers={"Content-Length": str(len(raw)), "Content-Type": "application/json"},
                                  _send=lambda *args: replies.append(args), _freezing=lambda: False)
        handler._do_POST = lambda: self.env["_do_POST"](handler)
        self.env["do_POST"](handler)
        return replies[0]

    def routes(self, argv):
        calls = {}

        def step(_, command, timeout):
            name = Path(next(arg for arg in command if arg.endswith((".py", ".ps1")))).name
            calls[name] = command
            return True

        runner = CommunicationCollection(self.root, self.config, "2026-09-01", "2026-09-20",
                                         step, lambda *args: None, argv=argv)
        runner.mail(time.time())
        runner.teams()
        return runner, calls

    def test_additional_pc_api_uses_raw_web_routes_and_keeps_full_pc_scope(self):
        for requested in (True, False, None):
            with self.subTest(mail_body=requested):
                body = {"collect_only": True}
                if requested is not None:
                    body["mail_body"] = requested
                self.assertEqual(self.post(body), (200, {"ok": True}))
                self.assertFalse(self.env["JOB"]["running"])
                self.assertEqual(self.env["JOB"]["run_result"]["code"], 2)
                command = self.commands[-1]
                for flag in ("--collect-only", "--interactive-collect", "--no-mail-copilot", "--no-teams-copilot", "--mail-web", "--teams-web"):
                    self.assertIn(flag, command)
                for flag in ("--communications-only", "--ai", "--skip-collect"):
                    self.assertNotIn(flag, command)
                wanted_body = requested is not False
                self.assertEqual("--mail-web-body" in command, wanted_body)
                self.assertEqual("--no-mail-web-body" in command, not wanted_body)
                runner, calls = self.routes(command)
                self.assertFalse(runner.headless)
                self.assertEqual(set(calls), {"Get-OutlookIndex.ps1", "Get-OutlookWeb.py",
                                             "Get-TeamsWindow.ps1", "Get-TeamsWeb.py"})
                self.assertEqual("--include-body" in calls["Get-OutlookWeb.py"], wanted_body)
                self.assertEqual("--exclude-body" in calls["Get-OutlookWeb.py"], not wanted_body)
                self.assertEqual(self.config["collectOnlyHeadless"], True)
                self.assertFalse(self.config['mailViaWeb'])
                self.assertFalse(self.config['teamsWeb'])

    def test_explicit_web_choice_matches_both_api_workers_and_route_execution(self):
        for path in ('/api/run', '/api/communication/collect'):
            for enabled in (True, False):
                with self.subTest(path=path, enabled=enabled):
                    self.assertEqual(self.post({'collect_only': True, 'mail_body': True, 'web_collect': enabled}, path)[0],
                                     200 if path == '/api/run' else 202)
                    command = self.commands[-1]
                    _, calls = self.routes(command)
                    self.assertEqual('--mail-web' in command, enabled)
                    self.assertEqual('--teams-web' in command, enabled)
                    self.assertEqual('--no-mail-web' in command, not enabled)
                    self.assertEqual('--no-teams-web' in command, not enabled)
                    self.assertEqual('Get-OutlookWeb.py' in calls, enabled)
                    self.assertEqual('Get-TeamsWeb.py' in calls, enabled)
                    self.assertIn('Get-OutlookIndex.ps1', calls)
                    self.assertIn('Get-TeamsWindow.ps1', calls)
                    self.assertEqual('--communications-only' in command, path != '/api/run')
                    self.assertNotIn('Get-MailViaCopilot.py', calls)
                    self.assertNotIn('Get-TeamsViaCopilot.py', calls)

    def test_cli_interactive_alone_keeps_disabled_configuration_and_no_flags_win_conflicts(self):
        base = ['--collect-only', '--interactive-collect']
        _, calls = self.routes(base)
        self.assertNotIn('Get-OutlookWeb.py', calls)
        self.assertNotIn('Get-TeamsWeb.py', calls)
        self.config.update(mailViaWeb=True, teamsWeb=True)
        _, calls = self.routes(base+['--mail-web', '--no-mail-web', '--teams-web', '--no-teams-web'])
        self.assertNotIn('Get-OutlookWeb.py', calls)
        self.assertNotIn('Get-TeamsWeb.py', calls)

    def test_invalid_web_choice_never_creates_a_worker_on_either_endpoint(self):
        for path in ('/api/run', '/api/communication/collect'):
            for invalid in ('false', 0, 1, None, [], {}):
                with self.subTest(path=path, invalid=invalid):
                    self.assertEqual(self.post({'collect_only': True, 'web_collect': invalid}, path)[0], 400)
                    self.assertFalse(self.env['JOB']['running'])
        self.assertEqual(self.commands, [])
        self.assertEqual(self.workers, [])

    def test_process_success_does_not_claim_zero_communication_collection_succeeded(self):
        def process(command, **_):
            report = self.root / 'report' / 'communication_evidence_20260901-20260920.json'
            report.parent.mkdir(exist_ok=True)
            pending = report.with_suffix('.tmp')
            pending.write_text(json.dumps({'period': ['2026-09-01', '2026-09-20'],
                'families': {kind: {'unique_rows': 0, 'context_rows': 0, 'unreadable_files': unreadable}
                             for kind in ('mail', 'teams')}}), encoding='utf-8')
            pending.replace(report)
            return SimpleNamespace(pid=123, stdout=io.BytesIO(b''), returncode=0, wait=lambda: None)
        self.env['subprocess'].Popen = process
        for unreadable in (0, 1):
            with self.subTest(unreadable=unreadable):
                self.assertEqual(self.post({'collect_only': True})[0], 200)
                result = self.env['JOB']['run_result']
                self.assertTrue(result['ok'])  # Other PC signals/process execution can succeed.
                self.assertIs(result['communication_available'], None if unreadable else False)
                self.assertIn('메일·Teams 건수 미확인' if unreadable else '0건, 수집 성공 미확인', result['message'])
                self.assertNotIn('PC 이동 준비', result['message'])

    def test_cli_collect_only_remains_headless_and_analysis_does_not_inherit_web_override(self):
        runner, calls = self.routes(["--collect-only"])
        self.assertTrue(runner.headless)
        self.assertEqual(set(calls), {"Get-OutlookIndex.ps1", "Get-TeamsWindow.ps1"})
        self.assertEqual(self.post({"ai": True, "skip": True, "mail_body": True})[0], 200)
        command = self.commands[-1]
        self.assertIn("--ai", command)
        self.assertIn("--skip-collect", command)
        self.assertNotIn("--interactive-collect", command)
        self.assertNotIn("--mail-web-body", command)

    def test_invalid_mail_body_is_rejected_before_worker_or_busy_state(self):
        for invalid in ("false", 0, 1, None, [], {}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.post({"collect_only": True, "mail_body": invalid})[0], 400)
                self.assertFalse(self.env["JOB"]["running"])
        self.assertEqual(self.commands, [])
        self.assertEqual(self.workers, [])

    def test_actual_additional_pc_button_has_checked_body_choice_and_sends_both_values(self):
        page_harness.CollectionUiTests.setUpClass()
        harness = page_harness.CollectionUiTests()
        harness.run_js(r'''
const checkbox=elements.find(e=>e.id==='collect2body');
assert(checkbox&&checkbox.type==='checkbox');assert('checked' in checkbox);
// Honor the actual HTML default even if an older shared fake DOM ignores it.
byId.collect2body.checked='checked' in checkbox;
fetchWith(async()=>reply(200,{ok:true}));
await byId.collect2.onclick();
assert.equal(requests[0].url,'/api/run');
assert.deepEqual(JSON.parse(requests[0].options.body),{
 from:'2026-09-01',to:'2026-09-13',collect_only:true,mail_body:true,web_collect:true});
byId.collect2body.checked=false;
await byId.collect2.onclick();
assert.equal(JSON.parse(requests[1].options.body).mail_body,false);
assert(!JSON.parse(requests[1].options.body).ai);
''')

    def test_actual_web_collector_exclusion_and_privacy_gates_precede_body_opt_in(self):
        cases = ((True, 4000, True, ["--include-body", "--exclude-body"], False),
                 (True, 4000, False, ["--include-body"], True),
                 (False, 4000, True, ["--include-body"], False),
                 (True, 0, True, ["--include-body"], False))
        for store_subject, context_chars, configured, flags, expected in cases:
            with self.subTest(store_subject=store_subject, context_chars=context_chars, flags=flags):
                harness = outlook_harness.OutlookReliabilityTests()
                harness.setUp()
                self.addCleanup(harness.doCleanups)
                module = harness.collector()
                fixture = harness.root / "fixture.json"
                fixture.write_text(json.dumps({"mail": {"2026-01": [harness.item()]}}), encoding="utf-8")
                config = harness.root / "config"
                config.mkdir()
                (config / "config.json").write_text(json.dumps({"storeMailSubject": store_subject,
                    "collection": {"mailWebBody": configured, "contextChars": context_chars}}), encoding="utf-8")
                argv = ["collector", "--from", "2026-01-01", "--to", "2026-01-31", "--force", "--only", "mail", *flags]
                with mock.patch.object(module.sys, "argv", argv), \
                        mock.patch.dict(os.environ, LM_OWA_FAKE=str(fixture), LM_NO_BROWSER="1"), \
                        mock.patch.object(module, "Browser", side_effect=AssertionError("No real browser in fixture tests")), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.main(), 0)
                self.assertEqual(harness.status("outlook_web")["body_requested"], expected)
                rows = harness.read()
                self.assertEqual(len(rows), 1)
                self.assertEqual(bool(rows[0]["context_excerpt"]), expected)


if __name__ == "__main__":
    unittest.main()
