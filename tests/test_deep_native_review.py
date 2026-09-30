"""Deep native/Graph review: synthetic COM and HTTP responses, TEMP data only."""
import json
import sys
import unittest
from unittest.mock import patch

import test_graph_server_collection as graph_fixtures
import test_outlook_native_stores as native_fixtures


class DeepNativeReviewTests(unittest.TestCase):
    def native(self):
        case = native_fixtures.OutlookNativeTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def graph(self):
        case = graph_fixtures.GraphFixture()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_index_supplement_keeps_com_partial_cursor_and_saved_rows(self):
        case = self.native()
        setup = r'''
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('Load-Coverage','New-Coverage')},$false)) {. ([scriptblock]::Create($node.Extent.Text))}
$covP=Join-Path $root 'data\outlook\coverage.json'; $srcP=Join-Path $root 'data\outlook\mail_source.json'
$writer='com'; $mailScope='already_connected_stores'; $mailAllFolders=$true; $KeepDays=400
'''
        before = case.probe(setup + r'''
$folder=Folder 'custom' 'store' @() @((Message 'saved'))
$script:mailFolders=@(@{name='inbox';key='custom';field='[ReceivedTime]';folder=$folder})
$state=@{folders=@{}}; $null=Read-MailMonth $null $month @('me@synthetic.invalid') $state
$state.folders.custom.done=$false
$cov=@{mail=@{};calendar=@{};partial=@{mail=@{'2026-01'=@{start=$month.start;end=$month.end;folders=$state.folders}};calendar=@{}}}
Save-Coverage $cov
'{"source":"com"}' | Set-Content -LiteralPath $srcP -Encoding UTF8
$loaded=Load-Coverage
@{cursor=$loaded.partial.mail.'2026-01'.folders.custom.seen_ids.Count} | ConvertTo-Json -Compress
''')
        self.assertEqual(before['cursor'], 1)
        fake = case.root / 'index-fixture.json'
        fake.write_text(json.dumps({'mail': [{
            'System.ItemUrl': 'mapi://synthetic/inbox/index-item',
            'System.ItemDate': '2026-01-04 10:00',
            'System.Message.DateReceived': '2026-01-04 10:00',
            'System.ItemFolderPathDisplay': 'Synthetic/Inbox',
            'System.Message.FromName': 'Synthetic index sender',
            'System.Subject': 'Synthetic index observation',
        }]}), encoding='utf-8')
        result = case.case.ps('Get-OutlookIndex.ps1', '-From', '2026-01-01', '-To', '2026-01-31',
                              '-Only', 'mail', '-Force',
                              env={'LM_INDEX_FAKE': str(fake), 'LM_PYTHON_EXE': sys.executable})
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual(len(case.case.read()), 2)
        after = case.probe(setup + r'''
$loaded=Load-Coverage 6>$null
@{cursor=$loaded.partial.mail.'2026-01'.folders.custom.seen_ids.Count} | ConvertTo-Json -Compress
''')
        self.assertEqual(after['cursor'], 1, 'Index atomically unions rows; it must not erase COM resume progress')

    def test_graph_missing_csv_restarts_inventory_instead_of_false_complete(self):
        case = self.graph()
        clock = [0.0]
        next_url = graph_fixtures.GRAPH + '/me/messages?$skiptoken=next'

        def response(url, token, **kwargs):
            clock[0] += 1
            if '$skiptoken' in url:
                return {'value': [case.mail_message('second')]}
            if '$filter=received' in url:
                return {'value': [case.mail_message('first')], '@odata.nextLink': next_url}
            return {'value': []}

        client = case.mail_client(response, clock=lambda: clock[0])
        first = case.collect_mail(client, budget=1)
        self.assertEqual(first['status'], 'partial')
        csv = case.root / 'data/outlook/mail.csv'
        previous = case.root / 'data/previous-pc/mail.csv'
        previous.parent.mkdir(parents=True)
        csv.rename(previous)
        second = case.collect_mail(client, budget=10)
        self.assertEqual(second['status'], 'complete')
        self.assertEqual({r['source_id'] for r in graph_fixtures.read_csv(csv)},
                         {'outlook-graph:first', 'outlook-graph:second'})

    def test_explicit_empty_teams_edit_removes_old_summary_as_well_as_context(self):
        case = self.graph()
        message = case.team_message('edit', body='An obsolete instruction')
        message['lastModifiedDateTime'] = '2026-06-03T11:00:00Z'

        def response(url, token, **kwargs):
            if url.endswith('/me'):
                return {'id': 'me'}
            if '/me/chats' in url:
                return {'value': [{'id': 'room'}]}
            return {'value': [message]}

        case.collect_teams(response)
        message['body']['content'] = ''
        message['lastModifiedDateTime'] = '2026-06-04T11:00:00Z'
        case.collect_teams(response)
        row = graph_fixtures.read_csv(case.root / 'data/m365/teams_chats.csv')[0]
        self.assertEqual((row['context_excerpt'], row['summary']), ('', ''))

    def test_calendar_scope_retains_same_account_and_resets_changed_calendar(self):
        case = self.native()
        result = case.probe(r'''
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Set-CalendarScope'},$false)) {. ([scriptblock]::Create($node.Extent.Text))}
$ns=[pscustomobject]@{Calendar=(Folder 'calendar' 'account-a')}
$ns | Add-Member ScriptMethod GetDefaultFolder {param($id); return $this.Calendar}
$script:cov=@{calendar=@{'2026-01'=@{rows=2}};partial=@{calendar=@{'2026-02'=@{from='2026-02-01 09:00:00'}}}}
$script:previousCalendarScope=Get-OutlookTextHash 'account-a:calendar'
Set-CalendarScope $ns
$same=$script:cov.calendar.Count; $samePartial=$script:cov.partial.calendar.Count
$ns.Calendar=Folder 'calendar' 'account-b'
Set-CalendarScope $ns
@{same=$same;samePartial=$samePartial;changed=$script:cov.calendar.Count;changedPartial=$script:cov.partial.calendar.Count}|ConvertTo-Json -Compress
''')
        self.assertEqual(result, {'same': 1, 'samePartial': 1, 'changed': 0, 'changedPartial': 0})

    def test_com_saved_rows_validate_resume_without_requiring_excluded_items(self):
        case = self.native()
        result = case.probe(r'''
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Confirm-CoverageObservations'},$false)) {. ([scriptblock]::Create($node.Extent.Text))}
$calP=Join-Path $root 'data\outlook\calendar.csv'
$excluded=Message 'draft';$excluded.Sent=$false
$folder=Folder 'custom' 'store' @() @((Message 'saved'),$excluded)
$script:mailFolders=@(@{name='inbox';key='custom';field='[ReceivedTime]';folder=$folder})
$state=@{folders=@{}}; $null=Read-MailMonth $null $month @('me@synthetic.invalid') $state
$cov=@{mail=@{};calendar=@{};partial=@{mail=@{'2026-01'=@{folders=$state.folders}};calendar=@{}}}
Confirm-CoverageObservations $cov @{} @{}
$retained=$state.folders.custom.done
$excludedSeen=($state.folders.custom.seen_ids -contains 'draft')
$excludedSaved=($state.folders.custom.saved_ids -contains 'draft')
Remove-Item -LiteralPath $mailP
Confirm-CoverageObservations $cov @{} @{}
@{retained=$retained;excludedSeen=$excludedSeen;excludedSaved=$excludedSaved;afterLoss=$state.folders.custom.done;seen=$state.folders.custom.seen_ids.Count}|ConvertTo-Json -Compress
''')
        self.assertEqual(result, {'retained': True, 'excludedSeen': True, 'excludedSaved': False,
                                  'afterLoss': False, 'seen': 0})

    def test_selected_msg_progress_requires_saved_row_but_keeps_period_exclusions(self):
        case = self.native()
        result = case.probe(r'''
$tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Import-OutlookFiles.ps1'),[ref]$tokens,[ref]$errors)
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('Get-SelectedMessagePlan','Test-SelectedMessageComplete')},$false)){. ([scriptblock]::Create($node.Extent.Text))}
$checkpoint=Join-Path $root 'data\collection_status\synthetic-progress.json'
$paths=@('C:\synthetic\one.msg','C:\synthetic\outside.msg');$id='derived:outlook-msg-sha256:synthetic'
$null=Merge-OutlookCsv $root $mailP @('source_id',$id) 'mail'
$plan=Get-SelectedMessagePlan $paths $checkpoint '2026-01-01' '2026-01-31' $true $true 4000 @() $mailP
$one=Get-OutlookTextHash $paths[0].ToLowerInvariant();$outside=Get-OutlookTextHash $paths[1].ToLowerInvariant()
$plan.state.files[$one]=@{done=$true;hash='bytes';source_id=$id;no_row=$false}
$plan.state.files[$outside]=@{done=$true;hash='outside-bytes';source_id='';no_row=$true}
Write-OutlookProgress $checkpoint $plan.state
$kept=Get-SelectedMessagePlan $paths $checkpoint '2026-01-01' '2026-01-31' $true $true 4000 @() $mailP
Remove-Item -LiteralPath $mailP
$missing=Get-SelectedMessagePlan $paths $checkpoint '2026-01-01' '2026-01-31' $true $true 4000 @() $mailP
@{kept=$kept.state.files[$one].done;lost=$missing.state.files[$one].done;outside=$missing.state.files[$outside].done}|ConvertTo-Json -Compress
''')
        self.assertEqual(result, {'kept': True, 'lost': False, 'outside': True})

    def test_explicit_graph_login_allows_account_switch_without_discarding_old_cache(self):
        case = self.graph()
        now = [1000.0]
        requests = []

        def poster(url, values):
            requests.append(url)
            if url.endswith('/devicecode'):
                return {'device_code': 'synthetic-device', 'user_code': 'SYNTHETIC',
                        'expires_in': 60, 'interval': 1}, None
            return {'access_token': 'synthetic-second-account', 'expires_in': 3600,
                    'scope': 'User.Read Mail.Read Chat.Read'}, None

        auth = graph_fixtures.GraphAuth(case.root, case.config, poster=poster,
                                       clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0] + n),
                                       emit=lambda *args, **kwargs: None)
        with patch('graph_client.subprocess.run'):
            auth.save({'access_token': 'synthetic-first-account', 'expires_in': 3600,
                       'scope': 'User.Read Mail.Read Chat.Read'})
            self.assertEqual(auth.acquire(False)[0], 'synthetic-first-account')
            self.assertEqual(requests, [])
            self.assertEqual(auth.acquire(True, force_login=True)[0], 'synthetic-second-account')
        self.assertTrue(requests[0].endswith('/devicecode'))


if __name__ == '__main__':
    unittest.main()
