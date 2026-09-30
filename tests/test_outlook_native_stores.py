"""Native-store and selected MSG contracts; synthetic COM objects in TEMP only."""
import json
import shutil
import unittest

import test_outlook_collection_reliability as reliability

ROOT = reliability.ROOT


PREAMBLE = r'''
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Outlook-Collection.ps1')
$root=Split-Path -Parent $PSScriptRoot; $mailP=Join-Path $root 'data\outlook\mail.csv'
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Get-OutlookData.ps1'),[ref]$tokens,[ref]$errors)
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('Read-MailMonth','Csv-Escape','Test-MeInList','Conv-Token','Save-Coverage')},$false)) {
    . ([scriptblock]::Create($node.Extent.Text))
}
$SelfTest=0; $SelfTestDelayMs=0; $BudgetSec=30; $sw=[Diagnostics.Stopwatch]::StartNew()
$TS='yyyy-MM-dd HH:mm:ss'; $fmt='g'; $contextChars=4000; $mailBody=$true; $storeSubject=$true
$script:collectionProblems=New-Object 'System.Collections.Generic.List[string]'; $script:observedRows=0
$MAIL_HEADER='box,time,sender,subject,conversation,rcv,time_precision,context_excerpt,context_truncated,source_id,source_kind,source_url,conversation_id,folder,account,raw_body_b64'
function Message($id,$sender='other@synthetic.invalid') {
 return [pscustomobject]@{Class=43;Sent=$true;SenderName='synthetic';SenderEmailAddress=$sender;
   ReceivedTime=[datetime]'2026-01-03 09:00';SentOn=[datetime]'2026-01-03 08:00';Subject='Synthetic';
   ConversationTopic='Synthetic';To='me@synthetic.invalid';CC='';EntryID=$id;ConversationID='thread';Body=('BEGIN'+('x'*6000)+"`r`nEND")}
}
function Items($rows) {
 $items=[pscustomobject]@{Rows=@($rows)}
 $items | Add-Member ScriptMethod Sort {param($field,$descending)}
 $items | Add-Member ScriptMethod Restrict {param($filter); return $this.Rows}
 return $items
}
function Folder($id,$store,$children=@(),$rows=@()) {
 return [pscustomobject]@{EntryID=$id;Name=$id;StoreID=$store;DefaultItemType=0;Folders=@($children);Items=(Items $rows);FolderPath=($store+'\'+$id)}
}
function Store($id) {
 $inbox=Folder 'inbox' $id; $sent=Folder 'sent' $id
 $junk=Folder 'junk' $id @((Folder 'junk-child' $id))
 $custom=Folder 'custom' $id @((Folder 'custom-child' $id))
 $rootFolder=Folder 'root' $id @($inbox,$sent,$junk,$custom)
 $s=[pscustomobject]@{StoreID=$id;Root=$rootFolder;Map=@{6=$inbox;5=$sent;23=$junk};ExchangeStoreType=3}
 $s | Add-Member ScriptMethod GetRootFolder {return $this.Root}
 $s | Add-Member ScriptMethod GetDefaultFolder {param($id);return $this.Map[$id]}
 return $s
}
$month=[pscustomobject]@{key='2026-01';start=[datetime]'2026-01-01';end=[datetime]'2026-02-01'}
'''


class OutlookNativeTests(unittest.TestCase):
    def setUp(self):
        self.case = reliability.OutlookReliabilityTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.root
        shutil.copyfile(ROOT / 'core/communication_archive.py', self.root / 'core/communication_archive.py')
        shutil.copyfile(ROOT / 'collect/Import-OutlookFiles.ps1', self.root / 'collect/Import-OutlookFiles.ps1')

    def probe(self, code):
        path = self.root / 'collect/probe.ps1'
        path.write_text((PREAMBLE + code).replace('\n', '\r\n'), encoding='utf-8-sig', newline='')
        result = self.case.ps('probe.ps1')
        self.assertEqual(result.returncode, 0, result.text)
        return json.loads(result.stdout.decode('utf-8-sig'))

    def test_all_connected_stores_archive_and_colliding_folder_ids(self):
        data = self.probe(r'''
$ns=[pscustomobject]@{Stores=@((Store 'primary'),(Store 'archive-pst'))}
$found=@(Get-OutlookMailFolders $ns $true $script:collectionProblems 3000 $true)
@{keys=@($found | ForEach-Object {$_.key}); mixed=@($found|Where-Object {$_.mixed}).Count; problems=@($script:collectionProblems)}|ConvertTo-Json -Compress
''')
        self.assertEqual(len(data['keys']), 10)
        self.assertIn('archive-pst:custom-child', data['keys'])
        self.assertIn('primary:inbox', data['keys'])
        self.assertFalse(any('junk' in key for key in data['keys']))
        self.assertEqual(data['problems'], [])

    def test_failed_store_root_keeps_other_store_and_accessible_defaults(self):
        data = self.probe(r'''
$broken=Store 'broken'; $broken | Add-Member ScriptMethod GetRootFolder {throw 'synthetic inaccessible root'} -Force
$ns=[pscustomobject]@{Stores=@($broken,(Store 'archive'))}
$found=@(Get-OutlookMailFolders $ns $true $script:collectionProblems 3000 $true)
@{keys=@($found|ForEach-Object {$_.key});problems=@($script:collectionProblems)}|ConvertTo-Json -Compress
''')
        self.assertIn('broken:inbox', data['keys'])
        self.assertIn('archive:custom-child', data['keys'])
        self.assertTrue(data['problems'])

    def test_moved_sent_uses_sent_period_and_preserves_full_body(self):
        data = self.probe(r'''
$sent=Message 'sent-moved' 'me@synthetic.invalid'; $sent.ReceivedTime=[datetime]'2026-02-05'; $sent.SentOn=[datetime]'2026-01-07 10:00'
$received=Message 'received'; $received.SentOn=[datetime]'2025-12-31';$received.ReceivedTime=[datetime]'2026-01-01 01:00'
$folder=Folder 'custom' 'archive' @() @($sent,$received)
$script:mailFolders=@(@{name='inbox';key='archive:custom';field='[ReceivedTime]';folder=$folder;mixed=$true})
$state=@{folders=@{}}; $rows=@(Read-MailMonth $null $month @('me@synthetic.invalid') $state)
@{rows=$rows.Count; done=@($state.folders.Values|Where-Object {$_.done}).Count;problems=@($script:collectionProblems)}|ConvertTo-Json -Compress
''')
        self.assertEqual(data['rows'], 2)
        self.assertEqual(data['done'], 2)
        saved = {row['source_id']: row for row in self.case.read()}
        self.assertEqual(saved['archive:sent-moved']['time'], '2026-01-07 10:00')
        self.assertEqual(saved['archive:received']['time'], '2026-01-01 01:00')
        self.assertEqual(len(saved['archive:sent-moved']['context_excerpt']), 4000)
        self.assertNotIn('raw_body_b64', saved['archive:sent-moved'])
        originals = [json.loads(p.read_text('utf-8')) for p in (self.root / 'data/communication_originals/mail').rglob('*.json')]
        self.assertEqual(len(originals), 2)
        self.assertTrue(all(len(r['body']) > 6000 and '\r\nEND' in r['body'] for r in originals))

    def test_seen_ids_resume_same_timestamp_without_dropping_new_rows(self):
        data = self.probe(r'''
$folder=Folder 'custom' 'store' @() @((Message 'already-saved'),(Message 'new-one'))
$script:mailFolders=@(@{name='inbox';key='custom';field='[ReceivedTime]';folder=$folder})
$state=@{folders=@{custom=@{done=$false;before='2026-01-03 09:00:00';seen_ids=@('already-saved')}}}
$rows=@(Read-MailMonth $null $month @('me@synthetic.invalid') $state)
@{rows=$rows.Count;done=$state.folders.custom.done;seen=@($state.folders.custom.seen_ids)}|ConvertTo-Json -Compress
''')
        self.assertEqual(data['rows'], 1)
        self.assertEqual(set(data['seen']), {'already-saved', 'new-one'})
        self.assertEqual(self.case.read()[0]['source_id'], 'store:new-one')

    def test_cached_local_complete_never_claims_server_complete(self):
        for extra in ([], ['-NoRefresh']):
            result = self.case.ps('Get-OutlookData.ps1', '-SelfTest', '2', '-From', '2026-01-01', '-To', '2026-01-31', *extra)
            self.assertEqual(result.returncode, 0, result.text)
            state = self.case.status('outlook_com')
            self.assertEqual(state['mail_status'], 'partial')
            self.assertFalse(state['server_complete'])
            self.assertEqual(state['local_mail_status'], 'complete')

    def test_page_checkpoint_invalidates_old_completion_and_retains_body_retry(self):
        data = self.probe(r'''
$all=@(0..101 | ForEach-Object {Message ('msg-'+$_)})
$all[100].PSObject.Properties.Remove('Body')
$all[100] | Add-Member ScriptProperty Body {throw 'synthetic body temporarily unavailable'}
$folder=Folder 'custom' 'store' @() $all
$script:mailFolders=@(@{name='inbox';key='custom';field='[ReceivedTime]';folder=$folder})
$covP=Join-Path $root 'data\outlook\coverage.json'; $writer='com'; $mailScope='already_connected_stores'; $mailAllFolders=$true
$script:cov=@{mail=@{'2026-01'=@{rows=1;start=$month.start;end=$month.end}};calendar=@{};partial=@{mail=@{};calendar=@{}}}
$state=@{folders=@{}}; $rows=@(Read-MailMonth $null $month @('me@synthetic.invalid') $state)
$saved=Get-Content -LiteralPath $covP -Raw -Encoding UTF8 | ConvertFrom-Json
@{rows=$rows.Count;done=$state.folders.custom.done;retry=(-not ($state.folders.custom.seen_ids -contains 'msg-100'));
 seen=@($saved.partial.mail.'2026-01'.folders.custom.seen_ids).Count; oldComplete=($null -ne $saved.mail.'2026-01')}|ConvertTo-Json -Compress
''')
        self.assertEqual(data['rows'], 102)
        self.assertFalse(data['done'])
        self.assertTrue(data['retry'])
        self.assertEqual(data['seen'], 101)
        self.assertFalse(data['oldComplete'])
        self.assertEqual(len(self.case.read()), 102)

    def test_selected_message_parser_respects_dates_and_privacy(self):
        data = self.probe(r'''
$tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Import-OutlookFiles.ps1'),[ref]$tokens,[ref]$errors)
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Convert-OutlookSelectedMessage'},$false)){. ([scriptblock]::Create($node.Extent.Text))}
$msg=Message 'selected'; $msg.SenderEmailAddress='me@synthetic.invalid'
$row=Convert-OutlookSelectedMessage $msg 'outlook-msg:synthetic' @('me@synthetic.invalid') $month.start $month.end 4000 $true $true $script:collectionProblems
$private=Convert-OutlookSelectedMessage $msg 'outlook-msg:private' @() $month.start $month.end 4000 $false $true $script:collectionProblems
$incoming=Message 'incoming'
$received=Convert-OutlookSelectedMessage $incoming 'received' @('me@synthetic.invalid') $month.start $month.end 4000 $true $true $script:collectionProblems
$uncertain=Convert-OutlookSelectedMessage $incoming 'uncertain' @('someone-else@synthetic.invalid') $month.start $month.end 4000 $true $true $script:collectionProblems
$disabled=Convert-OutlookSelectedMessage $incoming 'disabled' @() $month.start $month.end 0 $true $true $script:collectionProblems
$outside=Convert-OutlookSelectedMessage $msg 'outside' @() ([datetime]'2026-02-01') ([datetime]'2026-03-01') 4000 $true $true $script:collectionProblems
@{row=$row;private=$private;outside=$outside;received=$received;uncertain=$uncertain;disabled=$disabled}|ConvertTo-Json -Depth 5 -Compress
''')
        self.assertEqual(data['row']['box'], 'sent')
        self.assertTrue(data['row']['raw_body_b64'])
        self.assertEqual(data['private']['subject'], '')
        self.assertEqual(data['private']['raw_body_b64'], '')
        self.assertEqual((data['private']['box'], data['private']['time_precision']), ('unknown', 'unknown'))
        self.assertEqual((data['received']['box'], data['received']['time_precision']), ('inbox', 'minute'))
        self.assertEqual((data['uncertain']['box'], data['uncertain']['time_precision']), ('unknown', 'unknown'))
        self.assertEqual(data['disabled']['raw_body_b64'], '')
        self.assertIsNone(data['outside'])

    def test_manifest_rejects_pst_before_any_outlook_connection(self):
        pst = self.root / 'explicit.pst'
        pst.write_bytes(b'synthetic, not a real PST')
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'paths': [str(pst)], 'ownAddresses': [], 'expectedCount': 1}), encoding='utf-8')
        result = self.case.ps('Import-OutlookFiles.ps1', '-ManifestPath', manifest, '-From', '2026-01-01', '-To', '2026-01-31')
        self.assertEqual(result.returncode, 1, result.text)
        self.assertIn('Only existing explicitly selected .msg', self.case.status('outlook_files')['reasons'][0])
        self.assertEqual(pst.read_bytes(), b'synthetic, not a real PST')

    def test_selected_files_resume_unfinished_and_invalidate_changed_inputs(self):
        data = self.probe(r'''
$tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Import-OutlookFiles.ps1'),[ref]$tokens,[ref]$errors)
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('Get-SelectedMessagePlan','Test-SelectedMessageComplete')},$false)){. ([scriptblock]::Create($node.Extent.Text))}
$checkpoint=Join-Path $root 'data\collection_status\test-msg-progress.json'
$paths=@('C:\synthetic\first.msg','C:\synthetic\last.msg')
$initial=Get-SelectedMessagePlan $paths $checkpoint '2026-01-01' '2026-01-31' $true $true 4000 @('me@synthetic.invalid')
$key=Get-OutlookTextHash ($paths[0].ToLowerInvariant()); $initial.state.files[$key]=@{done=$true;hash='saved-bytes'}
Write-OutlookProgress $checkpoint $initial.state
$resumed=Get-SelectedMessagePlan $paths $checkpoint '2026-01-01' '2026-01-31' $true $true 4000 @('me@synthetic.invalid')
$period=Get-SelectedMessagePlan $paths $checkpoint '2026-02-01' '2026-02-28' $true $true 4000 @('me@synthetic.invalid')
$body=Get-SelectedMessagePlan $paths $checkpoint '2026-01-01' '2026-01-31' $true $false 4000 @('me@synthetic.invalid')
$initial.state.complete=$true; Write-OutlookProgress $checkpoint $initial.state
$refresh=Get-SelectedMessagePlan $paths $checkpoint '2026-01-01' '2026-01-31' $true $true 4000 @('me@synthetic.invalid')
@{first=$resumed.paths[0];same=(Test-SelectedMessageComplete $resumed.state $paths[0] 'saved-bytes');
changed=(Test-SelectedMessageComplete $resumed.state $paths[0] 'new-bytes');period=$period.state.files.Count;
body=$body.state.files.Count;refresh=$refresh.state.files.Count;json=(Get-Content -LiteralPath $checkpoint -Raw -Encoding UTF8)} | ConvertTo-Json -Compress
''')
        self.assertTrue(data['first'].endswith('last.msg'))
        self.assertTrue(data['same'])
        self.assertFalse(data['changed'])
        self.assertEqual((data['period'], data['body'], data['refresh']), (0, 0, 0))
        self.assertNotIn('synthetic', data['json'])


if __name__ == '__main__':
    unittest.main()
