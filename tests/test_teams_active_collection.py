"""Teams startup/current-room contracts, using TEMP source and synthetic DOM only."""
import contextlib
import copy
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_teams_web_compatibility as markup


class TeamsActiveCollectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = markup.TeamsWebCompatibilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.mod = self.fixture.root, self.fixture.mod

    def page(self, room='Synthetic Room', conv='room', timestamp='2026-06-03T09:00:00+09:00', body='Synthetic original'):
        html = f'''<html><main role="main"><h1>{room}</h1><section role="log" data-chat-id="{conv}">
          <div role="listitem" data-message-id="m1"><span data-tid="message-author-name">Synthetic Person</span>
          <time datetime="{timestamp}"/><div data-tid="message-body">{body}</div></div></section></main></html>'''
        return self.fixture.dom(html, self.mod.JS_MSGS)['results'][0]

    def browser(self, active=None, rooms=None, fail=()):
        module = self.mod
        rooms = rooms or []
        events = []

        class Browser:
            capture_messages = module.Browser.capture_messages

            def __init__(self):
                self.cfg, self.observation, self.deadline = {}, {}, None
                self.current = copy.deepcopy(active or {})
                self.selected = None
                self.cdp = SimpleNamespace(eval=self.evaluate)

            def start(self):
                events.append('start')
                return True

            def wait_ready(self):
                events.append('ready_without_navigation')
                return 'ok'

            def goto(self, *_args, **_kwargs):
                events.append('navigate_home')
                self.current = {}
                return 'ok'

            def eval_json(self, script, **_kwargs):
                if script == module.JS_CHATS:
                    return {'n': len(rooms), 'items': [copy.deepcopy(item) for item, _ in rooms]}
                if script == module.JS_PANE:
                    return {k: self.current.get(k) for k in ('chat', 'conversation_id', 'n')}
                if script == module.JS_MSGS:
                    events.append('read_page')
                    if self.selected in fail:
                        raise RuntimeError('synthetic pane replaced')
                    return copy.deepcopy(self.current)
                if script == module.JS_EXPAND_MESSAGES:
                    return {'clicked': 0}
                raise AssertionError('Unexpected DOM request')

            def evaluate(self, script, **_kwargs):
                if 'const key = ' in script:
                    key = json.JSONDecoder().raw_decode(script.split('const key = ', 1)[1])[0]
                    self.selected = key
                    events.append('open:'+key)
                    self.current = copy.deepcopy(next(page for item, page in rooms if item['key'] == key))
                    return 'ok'
                if script in (module.JS_SCROLL_CHATS, module.JS_SCROLL_UP, module.JS_SCROLL_DOWN):
                    return 'no-scroller'
                raise AssertionError('Unexpected browser action')

            def close(self):
                events.append('close')

        return Browser(), events

    def run_main(self, browser, search=None):
        module = self.mod
        with patch.object(module, 'Browser', return_value=browser), \
                patch.object(module, 'collect_search', side_effect=search or (lambda *_a, **_kw: {})), \
                patch.object(module, 'wait_pane', return_value=('', 0)), \
                patch.object(module.sys, 'argv', ['collector', '--from', '2026-06-01', '--to', '2026-06-30', '--budget', '5']), \
                patch.dict(module.os.environ, {'LM_NO_BROWSER': '', 'LM_TEAMSWEB_FAKE': ''}), \
                contextlib.redirect_stdout(io.StringIO()):
            code = module.main()
        return code, module.read_csv(self.root/'data/m365/teams_web.csv'), json.loads(
            (self.root/'data/collection_status/teams_web.json').read_text(encoding='utf-8-sig'))

    def test_open_conversation_survives_before_search_without_sidebar(self):
        browser, events = self.browser(self.page())

        def search(*_args, **_kwargs):
            events.append('search')
            rows = self.mod.read_csv(self.root/'data/m365/teams_web.csv')
            self.assertEqual(len(rows), 1, 'Current page must be durable before search changes the surface')
            return {}

        code, rows, state = self.run_main(browser, search)
        self.assertEqual(code, 0)
        self.assertEqual(rows[0]['context_excerpt'], 'Synthetic original')
        self.assertEqual(rows[0]['source_id'], 'teams-dom:room/m1')
        self.assertLess(events.index('read_page'), events.index('search'))
        self.assertLess(events.index('search'), events.index('navigate_home'))
        self.assertEqual(state['status'], 'partial')
        self.assertEqual(state['processed_chat_keys'], [])
        self.assertEqual(state['chat_context_cursors'], {})

    def test_active_page_unknown_date_is_quarantined_and_outside_period_is_excluded(self):
        page = self.page()
        missing = dict(page['items'][0], id='unknown', iso=[], ts='09:01', titles=[], label='', body='Unknown date')
        outside = dict(page['items'][0], id='outside', iso=['2026-07-03T09:00:00+09:00'], ts='')
        page['items'] = [missing, outside]
        page['n'] = 2
        browser, _ = self.browser(page)
        code, rows, state = self.run_main(browser)
        self.assertEqual(code, 1)
        self.assertEqual(rows, [])
        pending = self.mod.read_csv(self.root/'data/collection_pending/teams_web_undated.csv')
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['source_id'], 'teams-dom:room/unknown')
        self.assertEqual((pending[0]['time'], pending[0]['time_precision']), ('', 'unknown'))
        self.assertEqual(state['undated_rows'], 1)

    def test_group_full_title_verified_once_is_preserved_through_capture(self):
        item = {'idx': 0, 'key': 'group', 'name': '', 'conversation_id': '',
                'label': 'Synthetic One, Synthetic Two, Last message',
                'texts': ['Synthetic One, Synthetic Two', 'Preview']}
        page = self.page('Synthetic One, Synthetic Two', '')
        browser, _ = self.browser(rooms=[(item, page)])
        self.assertEqual(self.mod.chat_name(item), 'Synthetic One')
        code, rows, state = self.run_main(browser)
        self.assertEqual(code, 0)
        self.assertEqual(rows[0]['chat'], 'Synthetic One, Synthetic Two')
        self.assertEqual(rows[0]['context_excerpt'], 'Synthetic original')
        self.assertFalse(any(reason.startswith('chat_read_failed:') for reason in state['reasons']))

    def test_one_room_read_failure_does_not_remove_next_verified_room(self):
        first = {'idx': 0, 'key': 'first', 'name': 'First', 'conversation_id': 'first'}
        second = {'idx': 1, 'key': 'second', 'name': 'Second', 'conversation_id': 'second'}
        browser, events = self.browser(rooms=[(first, self.page('First', 'first')),
                                             (second, self.page('Second', 'second'))], fail={'first'})
        code, rows, state = self.run_main(browser)
        self.assertEqual(code, 0)
        self.assertEqual([r['source_id'] for r in rows], ['teams-dom:second/m1'])
        self.assertIn('open:second', events)
        self.assertIn('chat_read_failed:RuntimeError', state['reasons'])
        self.assertNotIn('first', state['processed_chat_keys'])
        self.assertNotIn('first', state['chat_context_cursors'])

    def test_changed_room_between_pane_and_message_read_is_not_saved(self):
        browser, _ = self.browser(self.page('Expected', 'expected'))
        original = browser.eval_json

        def changed(script, **kwargs):
            return self.page('Different', 'different') if script == self.mod.JS_MSGS else original(script, **kwargs)

        browser.eval_json = changed
        _, rows, state = self.run_main(browser)
        self.assertEqual(rows, [])
        self.assertIn('active_chat_read_failed:ValueError', state['reasons'])

    def test_unidentified_active_pane_does_not_block_identified_list_room(self):
        item = {'idx': 0, 'key': 'known', 'name': 'Known room', 'conversation_id': 'known'}
        browser, _ = self.browser(self.page('', '', body='Unidentified body'),
                                  rooms=[(item, self.page('Known room', 'known', body='Verified body'))])
        code, rows, state = self.run_main(browser)
        self.assertEqual(code, 0)
        self.assertEqual([row['context_excerpt'] for row in rows], ['Verified body'])
        self.assertIn('active_chat_read_failed:ValueError', state['reasons'])

    def test_storage_failure_stops_before_navigation_or_cursor_advance(self):
        browser, events = self.browser(self.page())
        with patch.object(self.mod, 'save', side_effect=OSError('synthetic archive unavailable')):
            code, rows, state = self.run_main(browser)
        self.assertEqual(code, 1)
        self.assertEqual(rows, [])
        self.assertEqual(state['rows'], 0)
        self.assertNotIn('navigate_home', events)
        self.assertEqual(state['chat_context_cursors'], {})
        self.assertIn('collection_error:OSError', state['reasons'])

    def test_active_page_applies_full_body_privacy_filter_before_archive(self):
        browser, _ = self.browser(self.page(body='Synthetic SECRET marker'))
        (self.root/'config/config.json').write_text(json.dumps({'excludePathKeywords': ['SECRET']}), encoding='utf-8')
        _, rows, _ = self.run_main(browser)
        self.assertEqual(rows[0]['context_filtered'], 'true')
        self.assertEqual(rows[0]['context_excerpt'], '')
        self.assertEqual(list((self.root/'data/communication_originals').rglob('*.json')), [])


if __name__ == '__main__':
    unittest.main()
