"""Rendered Teams body/context coverage; only synthetic markup and TEMP code."""
from datetime import date
import json
import os
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_teams_web_compatibility as markup_fixture


class TeamsContextCaptureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = markup_fixture.TeamsWebCompatibilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.mod = self.fixture.root, self.fixture.mod

    def read(self, pages, **kwargs):
        return self.mod.read_chat(None, 0, 'Room', date(2026, 6, 1), date(2026, 6, 30),
                                  date(2026, 9, 30), fake={'0': pages}, conversation_id='room', **kwargs)[0]

    def page(self, *messages):
        return {'chat': 'Room', 'conversation_id': 'room', 'items': list(messages), 'n': len(messages)}

    def original(self, identity='anchor'):
        return {'id': identity, 'conversation_id': 'room', 'name': 'Room',
                'url': 'https://teams.microsoft.com/l/message/room/'+identity}

    @staticmethod
    def message(identity, body, timestamp='2026-06-03 09:00'):
        return {'t': 'msg', 'id': identity, 'author': 'Synthetic person', 'ts': timestamp, 'body': body}

    def test_dom_keeps_long_rendered_message_tail_for_original_archive(self):
        body = 'BEGIN ' + 'Middle content ' * 2000 + ' IMPORTANT_FINAL_DECISION'
        markup = ('<html><main role="main"><h1>Room</h1><div role="log" data-chat-id="room">'
                  '<div role="listitem" data-message-id="long"><time datetime="2026-06-03T09:00:00+09:00"/>'
                  '<div data-tid="message-body">' + body + '</div></div></div></main></html>')
        page = self.fixture.dom(markup, self.mod.JS_MSGS)['results'][0]
        self.assertEqual(page['items'][0]['body'], body)

    def test_search_keeps_all_verified_visible_originals_not_only_six_neighbors(self):
        items = [self.message(str(i), f'Synthetic message {i}') for i in range(23)]
        item = {'id': '11', 'conversation_id': 'room', 'name': 'Room',
                'url': 'https://teams.microsoft.com/l/message/room/11'}
        rows, reason = self.mod.search_context(None, item, date(2026, 6, 3), date(2026, 6, 1),
            date(2026, 6, 30), date(2026, 9, 30), 4000,
            {'pane': {'conversation_id': 'room', 'chat': 'Room'},
             'page': {'conversation_id': 'room', 'chat': 'Room', 'items': items, 'n': len(items)}})
        self.assertEqual(reason, '')
        self.assertEqual(len(rows), len(items))

    def test_later_expanded_body_for_same_message_replaces_short_observation(self):
        short = 'Project discussion'
        full = short + ' and complete middle decision and follow-up responsibilities'
        pages = [{'chat': 'Room', 'items': [self.message('one', value)], 'n': 1} for value in (short, full)]
        persisted = []
        rows, _ = self.mod.read_chat(None, 0, 'Room', date(2026, 6, 1), date(2026, 6, 30),
            date(2026, 9, 30), fake={'0': pages}, conversation_id='room', on_page=persisted.extend)
        self.assertEqual(rows[0]['context_excerpt'], full)
        self.assertEqual(persisted[-1]['context_excerpt'], full)

    def test_interrupted_day_continues_after_saved_anchor_instead_of_first_anchor_forever(self):
        entries = [{'id': str(i), 'key': str(i), 'conversation_id': 'room', 'name': 'Room',
                    'url': f'https://teams.microsoft.com/l/message/room/{i}'} for i in range(3)]
        details = {str(i): {'pane': {'conversation_id': 'room', 'chat': 'Room'},
                           'page': {'chat': 'Room', 'items': [self.message(str(i), f'Body {i}')], 'n': 1}}
                   for i in range(3)}
        fake = {'search': {'2026-06-03': {'pages': [{'state': 'results', 'items': entries}], 'details': details}}}
        saved = []
        for _ in range(2):
            clock = [0]

            def persist(rows):
                saved.extend(rows)
                clock[0] = 100

            with patch.object(self.mod.time, 'monotonic', side_effect=lambda: clock[0]):
                self.mod.collect_search(None, fake, str(self.root), date(2026, 6, 3), date(2026, 6, 3),
                                        date(2026, 9, 30), 50, 4000, persist)
        self.assertEqual(len({row['source_id'] for row in saved}), 2)

    def test_expansion_reads_long_body_and_reply_without_clicking_message_content_actions(self):
        markup = '''<html><main role="main"><h1>Room</h1><div role="log" data-chat-id="room">
          <div role="listitem" data-message-id="a"><time datetime="2026-06-03T09:00:00+09:00"/>
          <div data-tid="message-body">Preview<button id="payload">Read more</button></div>
          <button id="expand">Read more</button><button id="replies">View 2 replies</button>
          <button id="send">Send</button><button id="reply">Reply</button>
          <button id="external-form" form="external">Read more</button>
          <a id="link" role="button" href="https://example.invalid/action">Show more</a>
          <form><button id="submit" type="submit">Read more</button></form>
          <blockquote><button id="quoted">Read more</button></blockquote></div>
          </div></main></html>'''
        full = 'Opening '+('middle ' * 2000)+' Final decision'
        setup = '''Element.prototype.click = function() {
          this.dispatchEvent({type:'click'});
          if(this.attrs.id==='expand') {
            const body=document.querySelector('[data-tid="message-body"]');body.raw=BODY;body.children=[];
            this.attrs['aria-expanded']='true';
          }
          if(this.attrs.id==='replies') {
            const log=document.querySelector('[role="log"]');
            log.children.push(new Element({tag:'div',attrs:{'role':'listitem','data-message-id':'reply-id'},children:[
              {tag:'time',attrs:{datetime:'2026-06-04T09:15:00+09:00'}},
              {tag:'div',attrs:{'data-tid':'message-body'},text:'Reply with its own original date'}]},log));
            this.attrs['aria-expanded']='true';
          }
        };'''.replace('BODY', json.dumps(full))
        result = self.fixture.dom(markup, setup, self.mod.JS_EXPAND_MESSAGES, self.mod.JS_MSGS)
        self.assertEqual({event['id'] for event in result['events']}, {'expand', 'replies'})
        rows = self.read([result['results'][-1]])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['_full_body'], full)
        self.assertTrue(rows[1]['time'].startswith('2026-06-04'))
        self.assertEqual(rows[1]['source_id'], 'teams-dom:room/reply-id')

    def test_original_archive_keeps_full_body_while_csv_has_bounded_middle_excerpt(self):
        body = 'BEGIN '+('first '*2000)+' MIDDLE_DECISION '+('after '*2000)+' END'
        rows = self.read([self.page(self.message('long', body))], context_chars=300)
        self.mod.save(rows, False)
        csv_rows = self.mod.read_csv(self.root/'data/m365/teams_web.csv')
        self.assertLessEqual(len(csv_rows[0]['context_excerpt']), 300)
        self.assertIn('MIDDLE_DECISION', csv_rows[0]['context_excerpt'])
        self.assertNotIn('_full_body', csv_rows[0])
        self.assertEqual(csv_rows[0]['context_truncated'], 'true')
        originals = list((self.root/'data/communication_originals/teams').rglob('*.json'))
        self.assertEqual(len(originals), 1)
        stored = json.loads(originals[0].read_text(encoding='utf-8'))
        self.assertEqual(stored['body'], body)
        self.assertFalse(stored['body_truncated'])
        self.assertEqual(stored['capture_method'], 'web_dom')

    def test_full_body_filter_runs_before_excerpt_and_archive_and_wins_dedup(self):
        body = 'A '*1000+' private '+'B '*7000
        self.assertNotIn('private', self.mod.make_excerpt(body, 200))
        pages = [self.page(self.message('one', 'PUBLIC LONG CONTENT '*2000)),
                 self.page(self.message('one', body)), self.page(self.message('one', 'Public again'))]
        saved = []
        rows = self.read(pages, context_chars=200, privacy_keywords=['private'], on_page=saved.extend)
        self.assertEqual(len(saved), 2)
        self.assertEqual(rows[0]['context_filtered'], 'true')
        self.assertEqual(rows[0]['summary'], '')
        self.assertEqual(rows[0]['context_excerpt'], '')
        self.mod.save([rows[0]], False)
        self.assertFalse(list((self.root/'data/communication_originals').rglob('*.json')))

    def test_same_size_rendered_capture_upgrades_collapsed_in_search_context(self):
        collapsed = dict(self.message('anchor', 'Same original body'), body_capture_status='collapsed')
        expanded = dict(collapsed, body_capture_status='rendered')
        fixture = {'pane': {'chat': 'Room', 'conversation_id': 'room'}, 'page': self.page(collapsed),
                   'pages_up': [self.page(expanded)]}
        saved = []
        rows, _ = self.mod.search_context(None, self.original(), date(2026, 6, 3), date(2026, 6, 1),
            date(2026, 6, 30), date(2026, 9, 30), 4000, fixture, persist=saved.extend)
        self.assertEqual(rows[0]['body_capture_status'], 'rendered')
        self.assertEqual([row['body_capture_status'] for row in saved], ['collapsed', 'rendered'])

    def test_search_persists_both_virtual_directions_and_filters_each_message_date(self):
        current = [self.message(str(i), 'Visible '+str(i)) for i in range(23)]
        fixture = {'pane': {'chat': 'Room', 'conversation_id': 'room'}, 'page': self.page(*current),
                   'pages_up': [self.page(self.message('older', 'Earlier context', '2026-06-02 10:00')),
                                self.page(self.message('outside-before', 'Too old', '2026-05-31 10:00'))],
                   'pages_down': [self.page(self.message('reply', 'Later context', '2026-06-04 10:00')),
                                  self.page(self.message('outside-after', 'Too late', '2026-07-01 10:00'))]}
        events = []
        rows, reason = self.mod.search_context(None, self.original('11'), date(2026, 6, 3), date(2026, 6, 1),
            date(2026, 6, 30), date(2026, 9, 30), 4000, fixture,
            persist=lambda batch: events.append(('save', {row['source_id'] for row in batch})),
            progress=lambda cursor: events.append(('cursor', dict(cursor))))
        self.assertEqual(reason, '')
        self.assertEqual(len(rows), 25)
        self.assertEqual({row['source_id'] for row in rows} - {'teams-dom:room/'+str(i) for i in range(23)},
                         {'teams-dom:room/older', 'teams-dom:room/reply'})
        for i, event in enumerate(events):
            if event[0] == 'cursor':
                self.assertTrue(any(value[0] == 'save' for value in events[:i]))
        self.assertEqual(events[-1][1]['down']['id'], 'outside-after')

    def test_archive_failure_never_advances_csv_or_page_cursor(self):
        cursors = []
        with patch.object(self.mod, 'archive_records', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.read([self.page(self.message('a', 'Original'))],
                          on_page=lambda rows: self.mod.save(rows, False), on_cursor=lambda *args: cursors.append(args))
        self.assertEqual(cursors, [])
        self.assertFalse((self.root/'data/m365/teams_web.csv').exists())

    def test_deleted_resume_id_falls_back_to_verified_anchor_and_wrong_room_is_rejected(self):
        anchor = self.original()
        bad = self.original('deleted')
        page = self.page(self.message('anchor', 'Original'))
        pane = {'chat': 'Room', 'conversation_id': 'room'}
        with patch.object(self.mod, '_open_original', side_effect=[(pane, self.page()), (pane, page)]) as opening:
            actual = self.mod.verified_resume(None, bad, anchor, time.monotonic()+20)
        self.assertEqual(actual, page)
        self.assertEqual([call.args[1]['id'] for call in opening.call_args_list], ['deleted', 'anchor'])
        with patch.object(self.mod, '_open_original', return_value=({'conversation_id': 'other'}, page)):
            self.assertIsNone(self.mod.verified_resume(None, bad, anchor, time.monotonic()+20))

    def test_chat_history_cursor_continues_old_pages_after_refreshing_recent_page(self):
        recent = self.page(self.message('recent', 'New visible', '2026-06-28 10:00'))
        previous = self.page(self.message('previous', 'Saved cursor', '2026-06-15 10:00'))
        older = self.page(self.message('older', 'Next unseen context', '2026-06-10 10:00'))
        browser = SimpleNamespace(eval_json=lambda _: recent, cdp=SimpleNamespace(eval=lambda _: 'scrolled'))
        persisted, cursors = [], []
        with patch.object(self.mod, 'verified_resume', return_value=previous) as restore, \
             patch.object(self.mod, 'wait_pane', return_value=('', 0)):
            browser.capture_messages = lambda *args: recent if not persisted else older
            self.mod.read_chat_resumable(browser, 0, 'Room', date(2026, 6, 1), date(2026, 6, 30),
                date(2026, 9, 30), max_scroll=1, on_page=persisted.extend, conversation_id='room',
                cursor=self.original('previous'), on_cursor=cursors.append)
        self.assertEqual([row['source_id'] for row in persisted],
                         ['teams-dom:room/recent', 'teams-dom:room/previous', 'teams-dom:room/older'])
        self.assertEqual(restore.call_args.args[1]['id'], 'previous')
        self.assertEqual(cursors[-1]['id'], 'older')

    def test_expansion_timeout_preserves_last_verified_body_and_marks_partial(self):
        browser = self.mod.Browser.__new__(self.mod.Browser)
        browser.deadline = time.monotonic()+10
        observed = self.page(dict(self.message('a', 'Visible preview'), body_capture_status='collapsed'))

        def evaluate(script, **kwargs):
            if script == self.mod.JS_PANE:
                return {'chat': 'Room', 'conversation_id': 'room'}
            if script == self.mod.JS_MSGS:
                return observed
            raise TimeoutError('synthetic slow expansion')

        browser.eval_json = evaluate
        page = browser.capture_messages('room', 'Room')
        saved, diagnostic = [], {}
        rows = self.read([page], on_page=saved.extend, diag=diagnostic)
        self.assertEqual(rows[0]['context_excerpt'], 'Visible preview')
        self.assertEqual(len(saved), 1)
        self.assertEqual(diagnostic['chat_reasons'], ['time_budget'])

    def test_search_short_private_later_observation_blocks_prior_safe_body(self):
        fixture = {'pane': {'chat': 'Room', 'conversation_id': 'room'},
                   'page': self.page(self.message('anchor', 'A long public original')),
                   'pages_up': [self.page(self.message('anchor', 'Private'))]}
        saved = []
        rows, _ = self.mod.search_context(None, self.original(), date(2026, 6, 3), date(2026, 6, 1),
            date(2026, 6, 30), date(2026, 9, 30), 4000, fixture, persist=saved.extend, privacy_keywords=['private'])
        self.assertEqual(rows[0]['context_filtered'], 'true')
        self.assertEqual(saved[-1]['context_excerpt'], '')

    def test_search_rejects_same_anchor_id_from_different_message_page_room(self):
        fixture = {'pane': {'chat': 'Room', 'conversation_id': 'room'},
                   'page': dict(self.page(self.message('anchor', 'Other room original')), conversation_id='another')}
        saved = []
        rows, reason = self.mod.search_context(None, self.original(), date(2026, 6, 3), date(2026, 6, 1),
            date(2026, 6, 30), date(2026, 9, 30), 4000, fixture, persist=saved.extend)
        self.assertEqual((rows, saved), ([], []))
        self.assertEqual(reason, 'search_room_unconfirmed')

    def test_out_of_period_pages_advance_only_id_cursor_before_older_requested_period(self):
        pages = [self.page(self.message('newest', 'Unrequested August', '2026-08-01 10:00')),
                 self.page(self.message('recent', 'Unrequested July', '2026-07-01 10:00'))]
        saved, cursors = [], []
        self.mod.read_chat_resumable(None, 0, 'Room', date(2026, 6, 1), date(2026, 6, 30), date(2026, 9, 30),
            fake={'0': pages}, on_page=saved.extend, on_cursor=cursors.append, conversation_id='room', max_scroll=1)
        self.assertEqual(saved, [])
        self.assertEqual(cursors[-1]['id'], 'recent')
        self.assertNotIn('body', json.dumps(cursors))
        in_period = self.page(self.message('june', 'Requested original', '2026-06-20 10:00'))
        browser = SimpleNamespace(cdp=SimpleNamespace(eval=lambda _: 'scrolled'))
        page_reads = iter([pages[0], in_period])
        browser.capture_messages = lambda *args: next(page_reads)
        with patch.object(self.mod, 'verified_resume', return_value=pages[-1]), \
                patch.object(self.mod, 'wait_pane', return_value=('', 0)):
            self.mod.read_chat_resumable(browser, 0, 'Room', date(2026, 6, 1), date(2026, 6, 30), date(2026, 9, 30),
                cursor=cursors[-1], on_page=saved.extend, on_cursor=cursors.append, conversation_id='room', max_scroll=1)
        self.assertEqual([row['source_id'] for row in saved], ['teams-dom:room/june'])

    def test_old_or_changed_capture_policy_does_not_skip_chat_from_previous_version(self):
        fixture = self.root/'fixture.json'
        fixture.write_text(json.dumps({'chats': {'items': [{'key': 'room', 'conversation_id': 'room', 'name': 'Room'}]},
                                       'msgs': {'room': [self.page(self.message('m1', 'Original'))]}}), encoding='utf-8')
        status_path = self.root/'data/collection_status/teams_web.json'
        status_path.parent.mkdir(parents=True)
        for signature in ('', self.mod.capture_signature(4000, ['previous-policy'])):
            status_path.write_text(json.dumps({'requested_from': '2026-06-01', 'requested_to': '2026-06-30',
                'processed_chat_keys': ['room'], 'reasons': ['time_budget'], 'capture_signature': signature}), encoding='utf-8')
            with patch.dict(os.environ, {'LM_TEAMSWEB_FAKE': str(fixture), 'LM_NO_BROWSER': '1'}), \
                    patch.object(sys, 'argv', ['collector', '--from', '2026-06-01', '--to', '2026-06-30']), \
                    patch.object(self.mod, 'log'):
                self.assertEqual(self.mod.main(), 0)
            status = json.loads(status_path.read_text(encoding='utf-8'))
            self.assertEqual(status['rows'], 1)
            self.assertEqual(status['capture_signature'], self.mod.capture_signature(4000, []))

    def test_search_old_capture_policy_retries_original_instead_of_old_done_key(self):
        path = self.root/'data/collection_status/teams_search_jobs.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'requested_from': '2026-06-03', 'requested_to': '2026-06-03',
            'jobs': {'2026-06-03': {'state': 'attempted', 'processed_anchors': ['["room","anchor"]']}}}), encoding='utf-8')
        fake = {'search': {'2026-06-03': {'pages': [{'state': 'results', 'items': [self.original()]}],
                'details': {'anchor': {'pane': {'chat': 'Room', 'conversation_id': 'room'},
                                       'page': self.page(self.message('anchor', 'Original'))}}}}}
        saved = []
        with patch.object(self.mod, 'log'):
            result = self.mod.collect_search(None, fake, str(self.root), date(2026, 6, 3), date(2026, 6, 3),
                                            date(2026, 9, 30), time.monotonic()+10, 4000, saved.extend)
        self.assertEqual(len(saved), 1)
        self.assertEqual(result['capture_signature'], self.mod.capture_signature(4000, []))


if __name__ == '__main__':
    unittest.main()
