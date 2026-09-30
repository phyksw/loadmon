"""Offline export import contracts; synthetic TEMP data and copied code only."""
import copy
import csv
from datetime import date, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1] / 'LoadMonitor25'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CommunicationExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lm25-export-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(APP / 'core', self.root / 'core')
        self.inputs = self.root / 'selected'
        self.inputs.mkdir()
        self.path_patch = mock.patch.object(sys, 'path', [str(self.root / 'core'), *sys.path])
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.importer = module('synthetic_exports_import', self.root / 'core/communication_import.py')
        self.evidence = module('synthetic_exports_evidence', self.root / 'core/communication_evidence.py')

    def save(self, payload, name='selected.json'):
        path = self.inputs / name
        path.write_text(json.dumps(payload), encoding='utf-8')
        return path

    @staticmethod
    def graph(**changes):
        message = {'id': 'message-1', 'chatId': 'chat-1', 'messageType': 'message',
                   'createdDateTime': '2026-09-15T10:00:00+09:00',
                   'from': {'user': {'id': 'sender-1', 'displayName': 'Synthetic colleague'}},
                   'body': {'contentType': 'html', 'content': '<p>Review complete; proceed with the revised draft.</p>'}}
        return dict(message, **changes)

    @staticmethod
    def normalized(**changes):
        return dict({'schema': 'lm25.communication.v1', 'family': 'teams', 'time': '2026-09-15T10:00:00+09:00',
                     'body': 'Review complete; proceed with revised specification.', 'conversation_id': 'chat-1',
                     'source_id': 'message-1', 'sender': 'Synthetic colleague'}, **changes)

    def run_import(self, paths, **collection):
        return self.importer.import_paths(self.root, paths, '2026-09-01', '2026-09-30', {'collection': collection})

    def rows(self, family='teams'):
        return self.importer.read_csv(self.root / ('data/m365/teams_import.csv' if family == 'teams' else 'data/outlook/mail.csv'))

    def test_graph_pages_duplicates_conversation_scope_full_body_and_safe_summary(self):
        body = '<p>FIRST ' + 'context ' * 1100 + ' FINAL DECISION</p><script>SECRET_SCRIPT</script>'
        one = self.graph(body={'contentType': 'html', 'content': body})
        page = {'@odata.context': 'https://graph.microsoft.com/v1.0/$metadata#Collection(microsoft.graph.chatMessage)',
                '@odata.nextLink': 'https://graph.microsoft.com/private?token=SECRET_TOKEN',
                'value': [one, copy.deepcopy(one), self.graph(chatId='chat-2')]}
        path = self.save(page)
        result = self.run_import([path], communicationImportExpectedCount=3)
        self.assertEqual((result['teams_rows'], result['counts']['added'], result['counts']['duplicates']), (3, 2, 1))
        self.assertEqual(result['reconciliation']['matched'], True)
        self.assertFalse(result['reconciliation']['server_coverage_verified'])
        self.assertEqual(result['status'], 'partial')
        self.assertIn('graph_page_has_unverified_next_page', result['reasons'])
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        long = next(r for r in rows if r['conversation_id'] == 'chat-1')
        self.assertEqual(len(long['context_excerpt']), 4000)
        self.assertEqual(long['context_truncated'], 'true')
        originals = [json.loads(p.read_text('utf-8')) for p in (self.root / 'data/communication_originals').rglob('*.json')]
        self.assertEqual(len(originals), 2)
        self.assertTrue(any('FINAL DECISION' in row['body'] for row in originals))
        self.assertNotIn('SECRET_SCRIPT', json.dumps(originals))
        self.assertNotIn('SECRET_TOKEN', str(result))
        self.assertNotIn('Synthetic colleague', str(result))
        self.assertNotIn(str(path), str(result))
        repeated = self.run_import([path])
        self.assertEqual((repeated['imported_rows'], repeated['counts']['duplicates']), (0, 3))
        self.assertEqual(len(self.rows()), 2)

    def test_date_rejection_period_exclusion_and_expected_count_are_reconciled(self):
        messages = [self.normalized(), self.normalized(source_id='old', time='2025-09-15T10:00:00+09:00'),
                    self.normalized(source_id='naive', time='2026-09-15T10:00:00'),
                    self.normalized(source_id='empty', body=''), self.normalized(source_id='missing', sender='')]
        path = self.save({'schema': 'lm25.communication.v1', 'messages': messages})
        result = self.run_import([path], communicationImportExpectedCount=6)
        c = result['counts']
        self.assertEqual((c['messages'], c['observed'], c['outside_range'], c['undated'], c['discarded'], c['body_missing']), (5, 1, 1, 1, 3, 1))
        self.assertTrue(result['reconciliation']['count_reconciled'])
        self.assertFalse(result['reconciliation']['matched'])
        self.assertEqual(len(self.rows()), 1)
        narrow = self.importer.import_paths(self.root, [path], '2026-09-20', '2026-09-30')
        self.assertEqual(narrow['counts']['observed'], 0)
        self.assertEqual(len(self.rows()), 1)

    def test_template_import_to_evidence_and_extractor_keeps_both_families(self):
        template = self.inputs / 'admin.csv'
        shutil.copyfile(APP / 'docs/LM25_communication_template.csv', template)
        result = self.run_import([template], communicationImportExpectedCount=2)
        self.assertEqual((result['status'], result['mail_rows'], result['teams_rows']), ('complete', 1, 1))
        report = self.evidence.build_report(self.root, '2026-09-01', '2026-09-30')
        for family in ('mail', 'teams'):
            self.assertEqual(report['families'][family]['context_rows'], 1)
            self.assertEqual(report['families'][family]['scope_status'], 'partial')
            self.assertIsNone(report['families'][family]['source_coverage_ratio'])
        extract = module('synthetic_export_extract', self.root / 'core/extract.py')
        cfg = json.loads((APP / 'config/config.default.json').read_text('utf-8-sig'))
        signals, meta = extract.load_signals(str(self.root / 'data'), date(2026, 9, 1), date(2026, 9, 30),
                                             exclude=cfg['excludePathKeywords'], cfg=cfg)
        self.assertEqual(len(signals), 2)
        self.assertTrue(all(row.get('context_excerpt') for row in meta['signal_contexts']))
        self.assertTrue(any(s[1] == '메일(방향미확인)' for s in signals))

    def test_graph_context_scopes_chat_without_guessing_and_channel_reply_ids(self):
        missing = self.graph()
        del missing['chatId']
        page = {'@odata.context': "https://graph.microsoft.com/v1.0/$metadata#chats('chat%2Dcontext')/messages", 'value': [missing]}
        channel = self.graph(chatId='', channelIdentity={'teamId': 'team-1', 'channelId': 'channel-1'}, replyToId='root-1')
        reply = dict(channel, replyToId='root-2')
        paths = [self.save(page), self.save([channel, reply], 'channel.json')]
        result = self.run_import(paths)
        self.assertEqual(result['teams_rows'], 3)
        self.assertEqual(len(self.rows()), 3)
        self.assertIn('chat-context', {row['conversation_id'] for row in self.rows()})
        alone = self.save(missing, 'missing.json')
        self.assertEqual(self.run_import([alone])['counts']['discarded'], 1)

    def test_live_channel_root_and_reply_exports_match_only_explicit_same_account(self):
        conversation = 'channel:team-1/channel-1'
        messages = [self.graph(id='root-1', chatId='', channelIdentity={'teamId': 'team-1', 'channelId': 'channel-1'}),
                    self.graph(id='reply-1', chatId='', channelIdentity={'teamId': 'team-1', 'channelId': 'channel-1'}, replyToId='root-1')]
        live = [{'time': '2026-09-15 10:00', 'source_id': identity, 'source_kind': 'teams_graph',
                 'conversation_id': conversation, 'account': 'tenant:synthetic-user', 'from': 'Synthetic colleague',
                 'chat': 'Team / Channel', 'summary': 'Review complete', 'context_excerpt': 'Review complete; proceed with the revised draft.'}
                for identity in ('graph-channel:team-1/channel-1/root-1', 'graph-channel:team-1/channel-1/root-1/reply-1')]
        target = self.root / 'data/m365/teams_chats.csv'
        self.importer.merge_csv(target, live, tuple(live[0]), kind='teams')
        before = target.read_bytes()
        path = self.save(messages)
        result = self.run_import([path], communicationImportAccount='tenant:synthetic-user')
        self.assertEqual(result['counts']['added'], 2)  # New route observations, no new unique originals.
        self.assertEqual({r['source_id'] for r in self.rows()}, {r['source_id'] for r in live})
        report = self.evidence.build_report(self.root, '2026-09-01', '2026-09-30')
        self.assertEqual((report['families']['teams']['raw_rows'], report['families']['teams']['unique_rows']), (4, 2))
        extract = module('synthetic_channel_export_extract', self.root / 'core/extract.py')
        cfg = json.loads((APP / 'config/config.default.json').read_text('utf-8-sig'))
        signals, _ = extract.load_signals(str(self.root / 'data'), date(2026, 9, 1), date(2026, 9, 30),
                                          exclude=cfg['excludePathKeywords'], cfg=cfg)
        self.assertEqual(len(signals), 2)
        unknown = self.run_import([path])
        other = self.run_import([path], communicationImportAccount='tenant:another-user')
        self.assertEqual((unknown['counts']['added'], other['counts']['added']), (2, 2))
        report = self.evidence.build_report(self.root, '2026-09-01', '2026-09-30')
        self.assertEqual(report['families']['teams']['unique_rows'], 6)
        self.assertEqual(target.read_bytes(), before)

    def test_jsonl_malformed_lines_and_mail_direction_are_explicit(self):
        path = self.inputs / 'rows.jsonl'
        rows = [self.normalized(family='mail', box='sent', subject='Synthetic draft', source_id='mail-1'), self.graph()]
        path.write_text('\n'.join(json.dumps(x) for x in rows) + '\n{malformed\n', encoding='utf-8')
        result = self.run_import([path])
        self.assertEqual((result['mail_rows'], result['teams_rows'], result['counts']['discarded']), (1, 1, 1))
        self.assertEqual(self.rows('mail')[0]['box'], 'sent')
        self.assertTrue(result['reconciliation']['count_reconciled'])

    def test_unrecognized_tokens_personal_purview_and_missing_csv_contract_are_rejected(self):
        paths = [self.save({'access_token': 'SECRET_TOKEN'}, 'token.json'),
                 self.save({'userId': 'SECRET_PERSON', 'conversations': []}, 'messages.json')]
        csvpath = self.inputs / 'not-contract.csv'
        csvpath.write_text('time,body\n2026-09-15,SECRET_BODY\n', encoding='utf-8')
        xmlpath = self.inputs / 'transcript.xml'
        xmlpath.write_text('<messages>SECRET_BODY</messages>', encoding='utf-8')
        result = self.run_import([*paths, csvpath, xmlpath])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['counts']['unsupported'], 4)
        self.assertEqual(self.rows(), [])
        self.assertNotIn('SECRET_', str(result))
        self.assertFalse((self.root / 'data/communication_originals').exists())

    def test_archive_failure_cannot_publish_new_csv_or_reuse_complete_status(self):
        path = self.save(self.graph())
        self.run_import([path])
        replacement = self.save(self.graph(id='new-message'), 'new.json')
        with mock.patch.object(self.importer, 'archive_records', side_effect=OSError('synthetic storage failure')):
            with self.assertRaises(self.importer.ImportPersistenceError):
                self.run_import([replacement])
        self.assertEqual(len(self.rows()), 1)
        status = json.loads((self.root / 'data/collection_status/communication_import.json').read_text('utf-8'))
        self.assertEqual(status['status'], 'partial')
        self.assertEqual(status['reasons'], ['import_in_progress'])

    def test_same_id_conflicting_body_is_retained_and_raw_archive_not_overwritten(self):
        first = self.save(self.graph())
        second = self.save(self.graph(body={'contentType': 'text', 'content': 'Different documented decision'}), 'edited.json')
        result = self.run_import([first, second])
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(len(list((self.root / 'data/communication_originals').rglob('*.json'))), 2)
        self.assertIn('conflicting_message_id_retained_separately', result['reasons'])

    def test_utf16_admin_csv_and_invalid_count_do_not_lose_prior_rows(self):
        path = self.inputs / 'unicode.csv'
        row = self.normalized(body='설계 검토 완료; 도면을 수정했습니다.')
        with path.open('w', encoding='utf-16', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        result = self.run_import([path])
        self.assertEqual(result['teams_rows'], 1)
        self.assertIn('도면', self.rows()[0]['context_excerpt'])
        with self.assertRaises(ValueError):
            self.run_import([path], communicationImportExpectedCount=-1)
        self.assertEqual(len(self.rows()), 1)

    def test_selected_count_is_not_mailbox_coverage_even_when_exact(self):
        path = self.save({'schema': 'lm25.communication.v1', 'expected_count': 1, 'messages': [self.normalized()]})
        result = self.run_import([path], communicationImportExpectedCount=1)
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['reconciliation']['matched'])
        self.assertFalse(result['reconciliation']['server_coverage_verified'])
        evidence = self.evidence.build_report(self.root, '2026-09-01', '2026-09-30')
        self.assertEqual(evidence['families']['mail']['source_statuses'], [])
        self.assertEqual(evidence['families']['teams']['scope_status'], 'partial')
        self.assertIsNone(evidence['families']['teams']['source_coverage_ratio'])

    def test_jsonl_stream_passes_old_ten_thousand_limit_and_reads_tail(self):
        path = self.inputs / 'large.jsonl'
        start = datetime.fromisoformat('2026-09-15T10:00:00+09:00')
        with path.open('w', encoding='utf-8') as stream:
            for number in range(10003):
                row = self.normalized(source_id=str(number), time=(start + timedelta(seconds=number)).isoformat())
                stream.write(json.dumps(row) + '\n')
        original_read = Path.read_text
        def no_whole_export_read(candidate, *args, **kwargs):
            if candidate == path:
                raise AssertionError('JSONL must not materialize the whole export')
            return original_read(candidate, *args, **kwargs)
        with mock.patch.object(Path, 'read_text', no_whole_export_read), \
                mock.patch.object(self.importer, 'archive_records', side_effect=lambda root, family, rows: len(rows)):
            result = self.run_import([path], communicationImportExpectedCount=10003)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['teams_rows'], 10003)
        self.assertIsNone(result['limits']['record_count_limit'])
        self.assertEqual(len(self.rows()), 10003)
        self.assertIn('normalized:10002', {row['source_id'] for row in self.rows()})

    def test_stream_oversize_line_and_invalid_bytes_do_not_hide_later_records(self):
        import communication_exports
        path = self.inputs / 'bad-lines.jsonl'
        valid = json.dumps(self.normalized()).encode()
        path.write_bytes(b'x' * 501 + b'\n\xff\xfe\n' + valid + b'\n')
        with mock.patch.object(communication_exports, 'MAX_RECORD_BYTES', 500):
            result = self.run_import([path])
        self.assertEqual((result['counts']['messages'], result['counts']['discarded'], result['teams_rows']), (3, 2, 1))
        self.assertIn('message_size_limit', result['reasons'])
        self.assertTrue(result['reconciliation']['count_reconciled'])

    def test_batch_persistence_failure_keeps_prefix_and_retry_reaches_tail(self):
        path = self.save([self.graph(id=str(number)) for number in range(5)])
        merge = self.importer.merge_csv
        calls = []
        def failing_merge(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise OSError('synthetic failed disk write')
            return merge(*args, **kwargs)
        with mock.patch.object(self.importer, 'PERSIST_BATCH_ROWS', 2), \
                mock.patch.object(self.importer, 'merge_csv', side_effect=failing_merge):
            with self.assertRaises(self.importer.ImportPersistenceError):
                self.run_import([path])
        self.assertEqual(len(self.rows()), 2)
        result = self.run_import([path])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['imported_rows'], 3)
        self.assertEqual(len(self.rows()), 5)

if __name__ == '__main__':
    unittest.main()
