"""Date-search coverage contracts: synthetic TEMP files, never a company UI."""
import importlib.util
import json
import shutil
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[1] / 'LoadMonitor25'


class TeamsSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lm25-teams-search-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ('collect', 'core', 'config'):
            (self.root / folder).mkdir()
        for name in ('Get-TeamsWeb.py', 'Get-OutlookWeb.py'):
            shutil.copyfile(PRODUCT / 'collect' / name, self.root / 'collect' / name)
        for name in ('collection_state.py', 'communication_archive.py', 'communication_context.py', 'collection_diagnostics.py'):
            shutil.copyfile(PRODUCT / 'core' / name, self.root / 'core' / name)
        spec = importlib.util.spec_from_file_location('search_fixture', self.root / 'collect/Get-TeamsWeb.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    @staticmethod
    def item(mid='m1', conv='room-a'):
        return {'id': mid, 'conversation_id': conv, 'name': 'Synthetic room', 'key': mid,
                'url': f'https://teams.microsoft.com/l/message/{conv}/{mid}'}

    @staticmethod
    def detail(mid='m1', day='2026-06-03', conv='room-a'):
        return {'pane': {'conversation_id': conv, 'chat': 'Synthetic room'},
                'page': {'chat': 'Synthetic room', 'n': 1, 'items': [
                    {'t': 'msg', 'id': mid, 'author': 'Synthetic person', 'ts': day+' 09:00',
                     'body': 'Original content, never a result preview.'}]}}

    def collect(self, fake, first=date(2026, 6, 3), last=date(2026, 6, 3), max_days=30):
        self.rows = []
        return self.mod.collect_search(None, fake, str(self.root), first, last, date(2026, 9, 30),
                                       time.monotonic()+10, 4000, self.rows.extend, max_days=max_days)

    def test_virtual_results_beyond_first_seven_are_collected(self):
        items = [self.item('m'+str(i)) for i in range(10)]
        result = self.collect({'search': {'2026-06-03': {
            'pages': [{'state': 'results', 'items': items[:7]}, {'state': 'results', 'items': items[6:]}],
            'details': {it['id']: self.detail(it['id']) for it in items}}}})
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(result['jobs']['2026-06-03']['results'], 10)
        self.assertEqual(result['counts']['completed_partial'], 1)
        self.assertIn('search_scope_unverified', result['reasons'])

    def test_original_room_and_anchor_both_required(self):
        for wrong in ('room', 'anchor'):
            detail = self.detail()
            if wrong == 'room':
                detail['pane']['conversation_id'] = 'room-b'
            else:
                detail['page']['items'][0]['id'] = 'different-message'
            self.collect({'search': {'2026-06-03': {
                'pages': [{'state': 'results', 'items': [self.item()]}], 'details': {'m1': detail}}}})
            self.assertEqual(self.rows, [])

    def test_query_date_is_not_used_as_message_timestamp(self):
        for timestamp in ('09:00', '2026-09-30 09:00'):
            detail = self.detail()
            detail['page']['items'][0]['ts'] = timestamp
            detail['page']['items'][0]['body'] = 'Meeting mentioned 2026-06-03, not sent then.'
            self.collect({'search': {'2026-06-03': {
                'pages': [{'state': 'results', 'items': [self.item()]}], 'details': {'m1': detail}}}})
            self.assertEqual(self.rows, [])

    def test_neighbors_keep_own_identity_and_exclude_outside_requested_period(self):
        detail = self.detail()
        detail['page']['items'] = [self.detail('before', '2026-06-02')['page']['items'][0],
                                  *detail['page']['items'],
                                  self.detail('after')['page']['items'][0]]
        self.collect({'search': {'2026-06-03': {
            'pages': [{'state': 'results', 'items': [self.item()]}], 'details': {'m1': detail}}}})
        self.assertEqual({row['source_id'] for row in self.rows}, {'teams-dom:room-a/m1', 'teams-dom:room-a/after'})

    def test_empty_ui_and_unsupported_ui_are_different(self):
        empty = self.collect({'search': {'2026-06-03': {'pages': [{'state': 'empty'}]}}})
        self.assertEqual(empty['counts']['completed_partial'], 1)
        missing = self.collect({'search': {'2026-06-03': {'pages': [{'state': 'unsupported'}]}}})
        self.assertEqual(missing['counts']['blocked'], 1)
        self.assertEqual(missing['counts']['completed_partial'], 0)

    def test_checkpoint_advances_unattempted_days_and_refreshes_latest(self):
        fake = {'search': {f'2026-06-0{i}': {'pages': [{'state': 'empty'}]} for i in range(1, 5)}}
        first = self.collect(fake, date(2026, 6, 1), date(2026, 6, 4), max_days=2)
        old_latest = first['jobs']['2026-06-04']['finished_at']
        second = self.collect(fake, date(2026, 6, 1), date(2026, 6, 4), max_days=2)
        self.assertIn('2026-06-02', second['jobs'])
        self.assertGreaterEqual(second['jobs']['2026-06-04']['finished_at'], old_latest)
        self.assertEqual(second['counts']['pending'], 1)

    def test_failed_day_retries_without_blocking_fresh_days(self):
        fake = {'search': {'2026-06-01': {'pages': [{'state': 'unsupported'}]},
                           '2026-06-02': {'pages': [{'state': 'empty'}]},
                           '2026-06-03': {'pages': [{'state': 'empty'}]}}}
        self.collect(fake, date(2026, 6, 1), date(2026, 6, 3), max_days=2)
        second = self.collect(fake, date(2026, 6, 1), date(2026, 6, 3), max_days=2)
        self.assertEqual(second['jobs']['2026-06-02']['state'], 'completed_partial')
        fake['search']['2026-06-01'] = {'pages': [{'state': 'empty'}]}
        third = self.collect(fake, date(2026, 6, 1), date(2026, 6, 3), max_days=2)
        self.assertEqual(third['jobs']['2026-06-01']['state'], 'completed_partial')

    def test_external_links_and_conflicting_original_ids_are_rejected(self):
        self.assertIsNone(self.mod.search_identity({'url': 'https://evil.example/l/message/room/m1'}))
        self.assertIsNone(self.mod.search_identity(dict(self.item(), conversation_id='another-room')))
        self.assertIsNone(self.mod.search_identity(dict(self.item(), id='another-message')))

    def test_time_budget_during_result_page_does_not_mark_day_completed(self):
        fake = {'search': {'2026-06-03': {'pages': [{'state': 'results', 'items': [self.item(), self.item('m2')]}],
                'details': {'m1': self.detail(), 'm2': self.detail('m2')}}}}
        now = [0]
        saved = []
        def persist(rows):
            saved.extend(rows)
            now[0] = 100
        with patch.object(self.mod.time, 'monotonic', side_effect=lambda: now[0]):
            state = self.mod.collect_search(None, fake, str(self.root), date(2026, 6, 3), date(2026, 6, 3),
                                            date(2026, 9, 30), 50, 4000, persist)
        self.assertEqual(len(saved), 1)
        self.assertEqual(state['counts']['completed_partial'], 0)
        self.assertEqual(state['counts']['attempted'], 1)
        self.assertIn('search_time_budget', state['jobs']['2026-06-03']['reasons'])

    def test_overlapping_context_is_saved_as_two_unique_originals(self):
        detail = self.detail()
        detail['page']['items'].append(self.detail('m2')['page']['items'][0])
        state = self.collect({'search': {'2026-06-03': {
            'pages': [{'state': 'results', 'items': [self.item(), self.item('m2')]}],
            'details': {'m1': detail, 'm2': detail}}}})
        self.mod.save(self.rows, False)
        rows = self.mod.read_csv(str(self.root / 'data/m365/teams_web.csv'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(state['jobs']['2026-06-03']['rows'], 2)

    def test_search_failure_does_not_block_legacy_chat_walk(self):
        fixture = self.root / 'fixture.json'
        fake = {'search': {'2026-06-03': {'pages': [{'state': 'unsupported'}]}},
                'chats': {'items': [{'idx': 0, 'key': 'room-a', 'conversation_id': 'room-a', 'name': 'Synthetic room'}]},
                'msgs': {'room-a': [self.detail()['page']]}}
        fixture.write_text(json.dumps(fake), encoding='utf-8')
        with patch.dict('os.environ', {'LM_TEAMSWEB_FAKE': str(fixture), 'LM_NO_BROWSER': '1'}), \
                patch.object(sys, 'argv', ['collector', '--from', '2026-06-03', '--to', '2026-06-03']), \
                patch.object(self.mod, 'log'):
            self.assertEqual(self.mod.main(), 0)
        rows = self.mod.read_csv(str(self.root / 'data/m365/teams_web.csv'))
        self.assertEqual(len(rows), 1)
        state = json.loads((self.root / 'data/collection_status/teams_web.json').read_text('utf-8'))
        self.assertEqual(state['search']['counts']['blocked'], 1)
        self.assertEqual(state['status'], 'partial')


if __name__ == '__main__':
    unittest.main()
