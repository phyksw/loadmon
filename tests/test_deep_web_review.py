"""Cross-call browser/date regressions. All profiles, markup and UIA input are synthetic."""
import importlib.util
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_teams_collection_reliability as collection_fixture
import test_teams_web_compatibility as markup_fixture


PRODUCT = Path(__file__).resolve().parents[1] / 'LoadMonitor25'


class DeepWebReviewTests(unittest.TestCase):
    def app_fixture(self):
        fixture = collection_fixture.TeamsCollectionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def web_fixture(self):
        fixture = markup_fixture.TeamsWebCompatibilityTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def driver(self):
        temp = tempfile.TemporaryDirectory(prefix='lm25-browser-ownership-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'tools').mkdir()
        target = root / 'tools/copilot_auto.py'
        shutil.copyfile(PRODUCT / 'tools/copilot_auto.py', target)
        spec = importlib.util.spec_from_file_location('synthetic_deep_driver', target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, root

    def test_app_explicit_old_year_survives_numeric_and_month_name_headers(self):
        fixture = self.app_fixture()
        rows = fixture.app_replay(
            'Synthetic chat\nPerson 15/08/2025 09:00 Archived slash message\n'
            'Person Aug 15 2025 10:00 Archived English message\n'
            'Person 15 August 2025 11:00 Archived day first message\n'
            'Person 15.08.2025 12:00 Archived dotted message\n',
            '-From', '2025-08-01', '-To', '2025-08-31')
        self.assertEqual([row['time'] for row in rows],
                         ['2025-08-15 09:00', '2025-08-15 10:00',
                          '2025-08-15 11:00', '2025-08-15 12:00'])
        self.assertTrue(all(row['time_precision'] == 'minute' for row in rows))

    def test_yearless_app_header_keeps_observation_but_not_exact_time_claim(self):
        fixture = self.app_fixture()
        rows = fixture.app_replay('Synthetic chat\n8/15\nPerson 09:00 Prior work\n'
                                  'Person Aug 16 10:00 Next work\n'
                                  'Person 11:00 Next work later\n',
                                  '-From', '2026-08-01', '-To', '2026-08-31')
        self.assertEqual([row['time'] for row in rows],
                         ['2026-08-15 09:00', '2026-08-16 10:00', '2026-08-16 11:00'])
        self.assertTrue(all(row['time_precision'] == 'estimated' for row in rows))

    def test_explicit_numeric_year_in_day_first_culture_honors_unambiguous_month(self):
        fixture = self.app_fixture()
        script = fixture.root / 'collect/Get-TeamsWindow.ps1'
        content = script.read_text('utf-8-sig').replace('$ci = Get-Culture',
                    "$ci = [Globalization.CultureInfo]::GetCultureInfo('de-DE')")
        script.write_bytes(b'\xef\xbb\xbf' + content.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'))
        rows = fixture.app_replay('Synthetic chat\nPerson 08/15/2025 09:00 Month first export\n'
                                  'Person 15/08/2025 10:00 Day first display\n',
                                  '-From', '2025-08-01', '-To', '2025-08-31')
        self.assertEqual([row['time'] for row in rows], ['2025-08-15 09:00', '2025-08-15 10:00'])

    def test_yearless_different_observed_days_do_not_trigger_today_redraw_dedupe(self):
        fixture = self.app_fixture()
        rows = fixture.app_replay('Synthetic chat\n8/15\nPerson 09:00 Daily review\n'
                                  '8/16\nPerson 09:00 Daily review\n',
                                  '-From', '2026-08-01', '-To', '2026-08-31')
        self.assertEqual([row['time'] for row in rows], ['2026-08-15 09:00', '2026-08-16 09:00'])

    def test_quoted_body_time_cannot_override_message_header_or_end_history(self):
        fixture = self.web_fixture()
        markup = '''<html><main role="main"><h1>Room</h1><div role="log" data-chat-id="room-id">
          <div role="listitem" data-message-id="m1"><span data-tid="timestamp" title="2026-06-03 09:00">09:00</span>
          <div data-tid="message-body">Current message quotes <time datetime="2025-01-01T03:00:00+09:00">past event</time>
          <span data-tid="timestamp" title="2024-01-01 04:00">04:00</span></div></div></div></main></html>'''
        page = fixture.dom(markup, fixture.mod.JS_MSGS)['results'][0]
        self.assertEqual(page['items'][0]['iso'], [])
        self.assertEqual(page['items'][0]['titles'], ['2026-06-03 09:00'])
        self.assertEqual(fixture.read([page])[0]['time'], '2026-06-03 09:00')

    def test_body_time_without_header_remains_undated(self):
        fixture = self.web_fixture()
        markup = '''<html><main role="main"><h1>Room</h1><div role="log"><div role="listitem" data-message-id="m1">
          <div data-tid="message-body">Quoted deadline <time datetime="2026-06-03T09:00:00+09:00">event</time></div>
          </div></div></main></html>'''
        page = fixture.dom(markup, fixture.mod.JS_MSGS)['results'][0]
        pending = []
        self.assertEqual(fixture.read([page], pending.extend), [])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['time_precision'], 'unknown')

    def test_quote_outside_body_and_nested_reply_keep_their_own_timestamps(self):
        fixture = self.web_fixture()
        markup = '''<html><main role="main"><h1>Room</h1><div role="log">
          <div role="listitem" data-message-id="root">
          <blockquote><time datetime="2024-01-01T03:00:00+09:00">Quoted old clock</time></blockquote>
          <div data-tid="quoted-reply" data-message-id="old"><time datetime="2024-02-01T03:00:00+09:00"/>
          <div data-tid="message-body">Quoted old body</div></div>
          <span data-tid="timestamp" title="2026-06-03 09:00">09:00</span>
          <div data-tid="message-body">Root work</div>
          <div role="listitem" data-message-id="reply"><time datetime="2026-06-04T10:00:00+09:00"/>
          <div data-tid="message-body">Reply work</div></div>
          </div></div></main></html>'''
        page = fixture.dom(markup, fixture.mod.JS_MSGS)['results'][0]
        self.assertEqual([(row['id'], row['body']) for row in page['items']],
                         [('root', 'Root work'), ('reply', 'Reply work')])
        rows = fixture.read([page])
        self.assertEqual([(row['time'], row['context_excerpt']) for row in rows],
                         [('2026-06-03 09:00', 'Root work'), ('2026-06-04 10:00', 'Reply work')])

    def test_existing_matching_profile_reuses_and_legacy_listener_is_supported(self):
        module, root = self.driver()
        cfg = {'port': 9333, 'profileDir': str(root / 'profile'), 'url': 'https://example.invalid'}
        args = ['msedge.exe', '--user-data-dir=' + cfg['profileDir'], '--remote-debugging-port=9333']
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(module, 'debugger_alive', return_value=True), \
                patch.object(module, 'http_json', return_value={'webSocketDebuggerUrl': 'ws://127.0.0.1:9333/devtools/browser/test'}), \
                patch.object(module, 'CDP', side_effect=RuntimeError('old browser')), \
                patch.object(module, '_windows_listener_arguments', return_value=args) as listener, \
                patch.object(module.subprocess, 'Popen') as launch:
            self.assertEqual(module.ensure_edge(cfg), 'reused')
            listener.assert_called_once()
            launch.assert_not_called()

    def test_unverified_ports_do_not_connect_or_kill_other_profiles(self):
        module, root = self.driver()
        cfg = {'port': 9333, 'profileDir': str(root / 'profile'), 'url': 'https://example.invalid'}
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(module, 'debugger_alive', return_value=True), \
                patch.object(module, '_debugger_owns_profile', return_value=False), \
                patch.object(module.subprocess, 'Popen') as launch:
            self.assertIsNone(module.ensure_edge(cfg))
            self.assertEqual(cfg['_edge_reason'], 'browser_profile_unverified')
            launch.assert_not_called()

    def test_actual_browser_start_uses_owned_alternate_port_for_both_collectors(self):
        module, root = self.driver()
        fixture = self.app_fixture()
        for filename in ('Get-OutlookWeb.py', 'Get-TeamsWeb.py'):
            with self.subTest(collector=filename):
                collector = fixture.module(filename)
                own, other = str(root / 'own profile'), str(root / 'other profile')
                owners, requested, launched = {9333: other}, [], []

                class Connection:
                    def __init__(self, url, timeout=30):
                        self.port = int(url.split(':')[2].split('/')[0])

                    def call(self, method, params=None, timeout=25):
                        if method == 'Browser.getBrowserCommandLine':
                            return {'arguments': ['msedge.exe', '--user-data-dir=' + owners[self.port],
                                                  '--remote-debugging-port=' + str(self.port)]}
                        return {}

                    def close(self):
                        pass

                def response(port, path, **kwargs):
                    requested.append((port, path))
                    if path == '/json/version':
                        return {'webSocketDebuggerUrl': f'ws://127.0.0.1:{port}/devtools/browser/test'}
                    return [{'type': 'page', 'url': collector.MAIL_URL if filename == 'Get-OutlookWeb.py' else collector.TEAMS_URL,
                             'webSocketDebuggerUrl': f'ws://127.0.0.1:{port}/devtools/page/test'}]

                def launch(args, **kwargs):
                    port = int(module._argument_value(args, '--remote-debugging-port'))
                    owners[port] = module._argument_value(args, '--user-data-dir')
                    launched.append(port)

                browser = collector.Browser.__new__(collector.Browser)
                browser.ca, browser.cfg = module, {'port': 9333, 'profileDir': own, 'url': 'https://example.invalid'}
                browser.port, browser.deadline = 9333, None
                with patch.dict(os.environ, {}, clear=True), \
                        patch.object(module, 'debugger_alive', side_effect=lambda port, **kw: port in owners), \
                        patch.object(module, 'http_json', side_effect=response), \
                        patch.object(module, 'CDP', Connection), \
                        patch.object(module, '_port_available', return_value=True), \
                        patch.object(module, 'find_edge', return_value='FAKE_EDGE'), \
                        patch.object(module.subprocess, 'Popen', side_effect=launch), \
                        patch.object(module.time, 'sleep'):
                    self.assertTrue(browser.start())
                    selected = browser.port
                    self.assertNotEqual(selected, 9333)
                    self.assertEqual(owners[selected], own)
                    self.assertNotIn((9333, '/json'), requested)
                    self.assertEqual(module.ensure_edge(browser.cfg), 'reused')
                self.assertEqual(launched, [selected])

    def socket_server(self, handler):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(2)
        stop = threading.Event()

        def serve():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(2)
                    handler(connection, stop)
            except (OSError, TimeoutError):
                pass  # Test closes a deliberately stalled transport.

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

        def finish():
            stop.set()
            listener.close()
            thread.join(2.5)
            self.assertFalse(thread.is_alive())

        self.addCleanup(finish)
        return f'ws://127.0.0.1:{listener.getsockname()[1]}/devtools/page/test'

    @staticmethod
    def handshake(connection):
        request = b''
        while b'\r\n\r\n' not in request:
            request += connection.recv(4096)
        connection.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')

    def test_real_socket_partial_frame_cannot_extend_cdp_deadline(self):
        module, _ = self.driver()

        def stalled_reply(connection, stop):
            self.handshake(connection)
            connection.recv(4096)
            payload = b'{"id":1,"result":{"ok":true}}'
            connection.sendall(bytes([0x81, len(payload)]))
            for chunk in (payload[:10], payload[10:20], payload[20:]):
                if stop.wait(0.08):
                    return
                connection.sendall(chunk)

        url = self.socket_server(stalled_reply)
        cdp = module.CDP(url, timeout=1)
        self.addCleanup(cdp.close)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            cdp.call('Synthetic', timeout=0.14)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(cdp.ws.sock.fileno(), -1)

    def test_handshake_slow_chunks_share_one_absolute_deadline(self):
        module, _ = self.driver()

        def slow_handshake(connection, stop):
            connection.recv(4096)
            for chunk in (b'HTTP/1.1 101 Switching Protocols\r\n', b'Upgrade: websocket\r\n', b'\r\n'):
                if stop.wait(0.08):
                    return
                connection.sendall(chunk)

        url = self.socket_server(slow_handshake)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            module.CDP(url, timeout=0.14)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_real_socket_normal_reply_still_succeeds(self):
        module, _ = self.driver()

        def reply(connection, stop):
            self.handshake(connection)
            connection.recv(4096)
            payload = b'{"id":1,"result":{"ok":true}}'
            connection.sendall(bytes([0x81, len(payload)]) + payload)

        cdp = module.CDP(self.socket_server(reply), timeout=1)
        self.addCleanup(cdp.close)
        self.assertEqual(cdp.call('Synthetic', timeout=1), {'ok': True})

    @staticmethod
    def owa_browser(pages):
        class Browser:
            def __init__(self):
                self.nav = self.index = 0
                self.cdp = SimpleNamespace(eval=lambda _script: 'end')

            def goto(self, _url):
                self.nav += 1
                return 'ok' if self.nav == 1 else 'login'

            def search(self, _query):
                return 'query_entered_unverified'

            def eval_json(self, _script):
                page = pages[min(self.index, len(pages)-1)]
                self.index += 1
                return {'state': 'results', 'items': page}

            def wait_list_change(self, *_args, **_kwargs):
                pass

        return Browser()

    def test_normal_owa_search_quarantines_yearless_metadata_without_period_invention(self):
        fixture = self.app_fixture()
        module = fixture.module('Get-OutlookWeb.py')
        item = {'key': 'message-1', 'item_id': 'message-1', 'date_texts': ['Jun 3 09:00'],
                'sender': 'Synthetic sender', 'subject': 'PRIVATE_MARKER', 'label': 'PRIVATE_MARKER Jun 3 09:00'}
        rows, state, diag = module.collect_mail(self.owa_browser([[item]]), date(2025, 6, 1), date(2025, 6, 30),
                                                store_subject=False)
        self.assertEqual((rows, state, diag['undated']), ([], 'login', 1))
        path = fixture.root / 'data/collection_pending/outlook_web_undated.csv'
        saved = module.read_csv(path)
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0]['time'], saved[0]['time_precision']), ('', 'unknown'))
        self.assertEqual((saved[0]['requested_from'], saved[0]['requested_to']), ('2025-06-01', '2025-06-30'))
        self.assertNotIn('PRIVATE_MARKER', path.read_text('utf-8'))
        self.assertIn('mail_date_unconfirmed', diag['reasons'])

    def test_later_exact_owa_observation_resolves_pending_in_same_collection(self):
        fixture = self.app_fixture()
        module = fixture.module('Get-OutlookWeb.py')
        item = {'key': 'message-1', 'item_id': 'message-1', 'date_texts': ['Jun 3 09:00'],
                'sender': 'Synthetic sender', 'subject': 'Synthetic work'}
        exact = dict(item, date_texts=['2026-06-03T09:00:00'])
        rows, state, _ = module.collect_mail(self.owa_browser([[item], [exact]]), date(2026, 6, 1), date(2026, 6, 30),
                                             checkpoint=lambda current: module._save('mail', current, True))
        self.assertEqual((len(rows), state, rows[0][1]), (1, 'login', '2026-06-03 09:00'))
        self.assertEqual(module.read_csv(fixture.root / 'data/collection_pending/outlook_web_undated.csv'), [])

    def test_calendar_navigation_timeout_never_reads_previous_week_dom(self):
        fixture = self.app_fixture()
        module = fixture.module('Get-OutlookWeb.py')
        browser = SimpleNamespace(goto=lambda *_args, **_kwargs: 'timeout',
                                  eval_json=lambda _script: self.fail('Stale calendar DOM must not be read'))
        rows, state, diag = module.collect_cal(browser, date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual((rows, state, diag['reasons']), ([], 'failed', ['calendar_page_not_ready']))


if __name__ == '__main__':
    unittest.main()
