"""Outlook collectors exercised with temporary roots and synthetic fixtures only."""
import contextlib
from datetime import date
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "LoadMonitor25"
STATE = {}
exec(compile((ROOT / "core/collection_state.py").read_text(encoding="utf-8-sig"),
             str(ROOT / "core/collection_state.py"), "exec"), STATE)


class OutlookReliabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-outlook-reliability-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / "data/outlook"
        self.out.mkdir(parents=True)
        (self.root / "collect").mkdir()
        (self.root / "core").mkdir()
        shutil.copy2(ROOT / "core/collection_state.py", self.root / "core/collection_state.py")
        for name in ("Get-OutlookData.ps1", "Get-OutlookIndex.ps1", "Outlook-Collection.ps1"):
            shutil.copy2(ROOT / "collect" / name, self.root / "collect" / name)

    def ps(self, filename, *args, env=None):
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(self.root / "collect" / filename), *map(str, args)],
                                cwd=self.root, env=dict(os.environ, **(env or {})),
                                capture_output=True, timeout=50)
        result.text = result.stdout.decode("utf-8-sig", "replace") + result.stderr.decode("utf-8-sig", "replace")
        return result

    def read(self, filename="mail.csv"):
        return STATE["read_csv"](self.out / filename)

    def status(self, name):
        return json.loads((self.root / "data/collection_status" / (name + ".json")).read_text(encoding="utf-8-sig"))

    def collector(self, name="Get-OutlookWeb.py"):
        spec = importlib.util.spec_from_file_location("_outlook_reliability", ROOT / "collect" / name)
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", list(sys.path)):
            spec.loader.exec_module(module)
        module.ROOT, module.OUT_DIR = str(self.root), str(self.out)
        if name == "Get-MailViaCopilot.py":
            module.UNAVAILABLE_FLAG = str(self.out / "mail_copilot_unavailable.json")
        return module

    def item(self, identity="synthetic-id", subject="Synthetic subject"):
        key = identity + "|synthetic"
        return {"key": key, "item_id": identity, "conversation_id": "synthetic-thread",
                "label": "2026-01-03 10:00", "texts": ["Synthetic sender", subject],
                "detail": {"item_id": identity, "selected_key": key, "container": "message-body",
                           "subject": subject, "body": "Synthetic complete message body " * 200,
                           "url": "https://outlook.office.com/mail/inbox/id/synthetic"}}

    def test_web_detail_requires_exact_identity_selection_container_and_subject(self):
        module, item = self.collector(), self.item()
        row = module.parse_mail_item(item, date(2026, 1, 1), date(2026, 1, 31), "inbox")
        body, truncated, reason, url = module.detail_context(item, row, item["detail"], 4000)
        self.assertEqual(len(body), 4000)
        self.assertEqual((truncated, reason), ("true", ""))
        self.assertTrue(url.startswith("https://outlook.office.com/"))
        for field, value in (("item_id", "other-message"), ("selected_key", "other-key"),
                             ("container", "list-preview"), ("subject", "Other subject")):
            with self.subTest(field=field):
                detail = dict(item["detail"], **{field: value})
                result = module.detail_context(item, row, detail, 4000)
                self.assertEqual(result[0], "")
                self.assertTrue(result[2])

    def test_web_fake_opt_in_retains_metadata_if_detail_is_not_verified(self):
        module, item = self.collector(), self.item()
        second = self.item("other-id", "Second subject")
        second["detail"]["subject"] = "Unrelated subject"
        fake = {"mail": {"2026-01": {"inbox": [item, second]}}}
        rows, state, diag = module.collect_mail(None, date(2026, 1, 1), date(2026, 1, 31), fake,
                                                body=True, checkpoint=lambda rows: module._save("mail", rows, True))
        self.assertEqual((len(rows), state, diag["body_rows"], diag["detail_failed"]), (2, "ok", 1, 1))
        saved = self.read()
        self.assertEqual(len(saved), 2)
        by_id = {row["source_id"]: row for row in saved}
        self.assertEqual(len(by_id[item["item_id"]]["context_excerpt"]), 4000)
        self.assertEqual(by_id[second["item_id"]]["context_excerpt"], "")
        self.assertEqual(by_id[second["item_id"]]["subject"], "Second subject")

    def test_web_default_never_opens_message_and_checkpoints_before_login_loss(self):
        module, item = self.collector(), self.item()
        navigations = []
        def goto(url):
            navigations.append(url)
            return "ok" if len(navigations) == 1 else "login"
        browser = SimpleNamespace(goto=goto, search=lambda query: True,
                                  eval_json=lambda query: {"items": [item]},
                                  cdp=SimpleNamespace(eval=lambda query: "end"))
        with patch.object(module, "read_mail_detail", side_effect=AssertionError("default must not open mail")), \
                patch.object(module.time, "sleep"):
            rows, state, _ = module.collect_mail(browser, date(2026, 1, 1), date(2026, 1, 31),
                                                 checkpoint=lambda rows: module._save("mail", rows, True))
        self.assertEqual((len(rows), state), (1, "login"))
        self.assertEqual(self.read()[0]["context_excerpt"], "")

    def test_python_fallbacks_union_legacy_and_preserve_existing_body(self):
        (self.out / "mail.csv").write_text("box,time,sender,subject,conversation,rcv\n"
                                           "sent,2020-01-01 10:00,synthetic,old,old,\n", encoding="utf-8-sig")
        module, item = self.collector(), self.item()
        rows, _, _ = module.collect_mail(None, date(2026, 1, 1), date(2026, 1, 31),
                                         {"mail": {"2026-01": [item]}}, body=True)
        module._save("mail", rows, True)
        rich = self.read()[1]["context_excerpt"]
        copilot = self.collector("Get-MailViaCopilot.py")
        copilot._save("mail", [rows[0][:7]], True)
        saved = self.read()
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["subject"], "old")
        self.assertEqual(saved[1]["context_excerpt"], rich)
        self.assertEqual(saved[1]["source_id"], item["item_id"])

    def test_web_main_manifest_is_partial_and_only_mail_leaves_calendar_skipped(self):
        module = self.collector()
        fixture = self.root / "fixture.json"
        fixture.write_text(json.dumps({"mail": {"2026-01": [self.item()]}}), encoding="utf-8")
        with patch.object(module.sys, "argv", ["collector", "--from", "2026-01-01", "--to", "2026-01-31", "--force", "--only", "mail"]), \
                patch.dict(os.environ, LM_OWA_FAKE=str(fixture), LM_NO_BROWSER="1"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(), 0)
        status = self.status("outlook_web")
        self.assertEqual((status["status"], status["mail_status"], status["calendar_status"]),
                         ("partial", "partial", "skipped"))
        self.assertFalse(status["body_requested"])
        self.assertTrue(any("metadata_only" in reason for reason in status["reasons"]))

    def test_copilot_manifest_never_claims_source_body_or_complete_calendar(self):
        module = self.collector("Get-MailViaCopilot.py")
        row = ["2026-01-03 09:00", "2026-01-03 10:00", "False", "2", "Synthetic event", "", "", "", ""]
        with patch.object(module.sys, "argv", ["collector", "--from", "2026-01-01", "--to", "2026-01-04", "--force", "--only", "cal"]), \
                patch.object(module, "_one_slice", return_value=([row], "table")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(), 0)
        status = self.status("outlook_copilot")
        self.assertEqual((status["mail_status"], status["calendar_status"]), ("skipped", "partial"))
        self.assertFalse(status["source_verified"])
        self.assertFalse(status["body_collected"])
        self.assertFalse(json.loads((self.out / "mail_source.json").read_text())["calendar_complete"])

    def test_index_preserves_archive_and_history_as_metadata_only(self):
        (self.out / "mail.csv").write_text("box,time,sender,subject,conversation,rcv\n"
                                           "sent,2020-01-01 10:00,synthetic,old,old,\n", encoding="utf-8-sig")
        fixture = self.root / "fixture.json"
        fixture.write_text(json.dumps({"mail": [{"System.ItemUrl": "mapi://synthetic/item",
                          "System.ItemFolderPathDisplay": "Mailbox/Archive/Project",
                          "System.Message.DateReceived": "2026-01-03 10:00",
                          "System.Subject": "Synthetic archived message", "System.Message.FromName": "Synthetic sender"}]}), encoding="utf-8")
        result = self.ps("Get-OutlookIndex.ps1", "-From", "2026-01-01", "-To", "2026-01-31", "-Only", "mail", "-Force",
                         env={"LM_INDEX_FAKE": str(fixture)})
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual(len(self.read()), 2)
        self.assertEqual(self.read()[1]["context_excerpt"], "")
        status = self.status("outlook_index")
        self.assertEqual((status["status"], status["mail_status"], status["calendar_status"]), ("partial", "partial", "skipped"))
        self.assertFalse(json.loads((self.out / "mail_source.json").read_text(encoding="utf-8-sig"))["calendar_complete"])

    def test_index_invalid_fixture_fails_closed(self):
        fixture = self.root / "fixture.json"
        fixture.write_text("{", encoding="utf-8")
        result = self.ps("Get-OutlookIndex.ps1", "-Only", "mail", "-Force", env={"LM_INDEX_FAKE": str(fixture)})
        self.assertEqual(result.returncode, 1, result.text)
        self.assertIn("live index was not queried", self.status("outlook_index")["reasons"][0])

    def runtime_env_without_path_python(self):
        windows = Path(os.environ["SystemRoot"])
        return {"PATH": os.pathsep.join(map(str, (windows / "System32", windows / "System32/WindowsPowerShell/v1.0"))),
                "LM_PYTHON_EXE": ""}

    def test_com_uses_parent_python_when_python_is_absent_from_path(self):
        env = dict(self.runtime_env_without_path_python(), LM_PYTHON_EXE=sys.executable)
        result = self.ps("Get-OutlookData.ps1", "-SelfTest", 2, "-From", "2026-01-01", "-To", "2026-01-31", env=env)
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual(len(self.read()), 4)
        self.assertEqual(len(self.read("calendar.csv")), 1)
        self.assertEqual(self.status("outlook_com")["status"], "complete")

    def test_launcher_only_runtime_saves_com_and_index_and_preserves_history(self):
        # Emulate the BAT's supported `py -3` route without relying on a registry
        # installation or any Outlook service. The shim executes the real Python.
        launcher = self.root / "launcher with spaces"
        launcher.mkdir()
        (launcher / "py.cmd").write_text(f'@"{sys.executable}" %2 %3 %4 %5 %6 %7 %8 %9\r\n', encoding="mbcs", newline="")
        env = self.runtime_env_without_path_python()
        env["PATH"] = str(launcher) + os.pathsep + env["PATH"]
        invalid = self.root / "invalid-runtime.txt"
        invalid.write_text("not an interpreter", encoding="ascii")
        env["LM_PYTHON_EXE"] = str(invalid)
        result = self.ps("Get-OutlookData.ps1", "-SelfTest", 2, "-From", "2026-01-01", "-To", "2026-01-31", env=env)
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual(len(self.read()), 4)
        fixture = self.root / "fixture.json"
        fixture.write_text(json.dumps({"mail": [{"System.ItemUrl": "mapi://synthetic/launcher",
                          "System.ItemFolderPathDisplay": "Mailbox/Inbox",
                          "System.Message.DateReceived": "2026-01-03 10:00",
                          "System.Subject": "Synthetic launcher mail", "System.Message.FromName": "Synthetic sender"}]}), encoding="utf-8")
        result = self.ps("Get-OutlookIndex.ps1", "-From", "2026-01-01", "-To", "2026-01-31", "-Only", "mail", "-Force",
                         env=dict(env, LM_INDEX_FAKE=str(fixture)))
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual(len(self.read()), 5)
        self.assertEqual(self.status("outlook_index")["mail_rows"], 1)
        self.assertEqual(self.status("outlook_index")["status"], "partial")

    def test_default_store_failure_still_saves_accessible_inbox_and_sent_as_partial(self):
        code = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Outlook-Collection.ps1')
$root=Split-Path -Parent $PSScriptRoot; $mailP=Join-Path $root 'data\outlook\mail.csv'
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Get-OutlookData.ps1'),[ref]$tokens,[ref]$errors)
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('Read-MailMonth','Csv-Escape','Test-MeInList','Conv-Token')},$false)) {
    . ([scriptblock]::Create($node.Extent.Text))
}
function Folder($id) {
    $message=[pscustomobject]@{Class=43;SenderName='synthetic';SenderEmailAddress='other@synthetic.invalid';
      ReceivedTime=[datetime]'2026-01-03 09:00';SentOn=[datetime]'2026-01-03 09:00';Subject=('Synthetic '+$id);
      ConversationTopic=$id;To='me@synthetic.invalid';CC='';EntryID=('message-'+$id);ConversationID=('thread-'+$id);Body='Synthetic body'}
    $items=[pscustomobject]@{Rows=@($message)}
    $items | Add-Member ScriptMethod Sort {param($field,$descending)}
    $items | Add-Member ScriptMethod Restrict {param($filter);return $this.Rows}
    return [pscustomobject]@{EntryID=$id;DefaultItemType=0;Folders=@();Items=$items;StoreID='default-store';FolderPath=$id}
}
$ns=[pscustomobject]@{DefaultStore=[pscustomobject]@{};Map=@{5=(Folder 'sent');6=(Folder 'inbox');3=(Folder 'deleted');23=(Folder 'junk');16=(Folder 'drafts');4=(Folder 'outbox')}}
$ns | Add-Member ScriptMethod GetDefaultFolder {param($id);return $this.Map[$id]}
$ns | Add-Member ScriptProperty Stores {throw 'other accounts must not be enumerated'}
$ns.DefaultStore | Add-Member ScriptMethod GetRootFolder {throw 'synthetic inaccessible store root'}
$SelfTest=0; $BudgetSec=360; $sw=[Diagnostics.Stopwatch]::StartNew()
$TS='yyyy-MM-dd HH:mm:ss'; $fmt='g'; $contextChars=4000; $mailBody=$true; $storeSubject=$true
$script:collectionProblems=New-Object 'System.Collections.Generic.List[string]'; $script:observedRows=0
$MAIL_HEADER='box,time,sender,subject,conversation,rcv,time_precision,context_excerpt,context_truncated,source_id,source_kind,source_url,conversation_id,folder,account'
$script:mailFolders=@(Get-OutlookMailFolders $ns $true $script:collectionProblems)
$state=@{folders=@{}}; $month=[pscustomobject]@{key='2026-01';start=[datetime]'2026-01-01';end=[datetime]'2026-02-01'}
$rows=@(Read-MailMonth $null $month @('me@synthetic.invalid') $state)
$ns.Map.Remove(5)
$oneProblems=New-Object 'System.Collections.Generic.List[string]'
$one=@(Get-OutlookMailFolders $ns $false $oneProblems)
@{keys=@($script:mailFolders | ForEach-Object {$_.key}); rows=$rows.Count;stop=$script:stopReason;problems=@($script:collectionProblems);
  oneKeys=@($one | ForEach-Object {$_.key});oneProblems=@($oneProblems)} | ConvertTo-Json -Compress
"""
        (self.root / "collect/probe.ps1").write_text(code.replace("\n", "\r\n"), encoding="utf-8-sig", newline="")
        result = self.ps("probe.ps1")
        self.assertEqual(result.returncode, 0, result.text)
        data = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(set(data["keys"]), {"inbox", "sent"})
        self.assertEqual(data["rows"], 2)
        self.assertTrue(data["stop"])
        self.assertTrue(any("root inaccessible" in reason for reason in data["problems"]))
        self.assertEqual(data["oneKeys"], ["inbox"])
        self.assertTrue(data["oneProblems"])
        rows = self.read()
        self.assertEqual({row["box"] for row in rows}, {"inbox", "sent"})
        self.assertEqual({row["source_id"] for row in rows}, {"default-store:message-inbox", "default-store:message-sent"})

    def test_default_store_folder_walk_excludes_deleted_subtrees_and_bounds_body(self):
        code = r"""
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Outlook-Collection.ps1')
function Folder($id, $children = @()) { return [pscustomobject]@{EntryID=$id; DefaultItemType=0; Folders=@($children)} }
$inbox=Folder 'inbox'; $sent=Folder 'sent' @((Folder 'sent-child'))
$deleted=Folder 'deleted' @((Folder 'deleted-child')); $junk=Folder 'junk' @((Folder 'junk-child'))
$drafts=Folder 'drafts'; $outbox=Folder 'outbox'; $custom=Folder 'custom' @((Folder 'custom-child'))
$rootFolder=Folder 'root' @($inbox,$sent,$deleted,$junk,$drafts,$outbox,$custom)
$store=[pscustomobject]@{Root=$rootFolder}
$store | Add-Member ScriptMethod GetRootFolder { return $this.Root }
$ns=[pscustomobject]@{DefaultStore=$store; Map=@{3=$deleted;23=$junk;16=$drafts;4=$outbox;5=$sent;6=$inbox}}
$ns | Add-Member ScriptMethod GetDefaultFolder { param($id); return $this.Map[$id] }
$ns | Add-Member ScriptProperty Stores { throw 'other accounts must not be enumerated' }
$problems=New-Object 'System.Collections.Generic.List[string]'
$folders=@(Get-OutlookMailFolders $ns $true $problems)
$context=@(Get-OutlookContext ([pscustomobject]@{Body=('x' * 5000)}) 4000 $true $problems)
$bad=[pscustomobject]@{}; $bad | Add-Member ScriptProperty Body { throw 'inaccessible synthetic body' }
$badContext=@(Get-OutlookContext $bad 4000 $true $problems)
$limitProblems=New-Object 'System.Collections.Generic.List[string]'
$null=Get-OutlookMailFolders $ns $true $limitProblems 2
@{keys=@($folders | ForEach-Object {$_.key}); sent=@($folders | Where-Object {$_.name -eq 'sent'} | ForEach-Object {$_.key});
  bodyLength=$context[0].Length; truncated=$context[1]; bodyFailure=$badContext[1]; problems=@($problems);
  limitProblems=@($limitProblems)} | ConvertTo-Json -Compress
"""
        (self.root / "collect/probe.ps1").write_text(code.replace("\n", "\r\n"), encoding="utf-8-sig", newline="")
        result = self.ps("probe.ps1")
        self.assertEqual(result.returncode, 0, result.text)
        data = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(set(data["keys"]), {"inbox", "sent", "sent-child", "custom", "custom-child"})
        self.assertEqual(set(data["sent"]), {"sent", "sent-child"})
        self.assertEqual((data["bodyLength"], data["truncated"], data["bodyFailure"]), (4000, "true", "unknown"))
        self.assertTrue(data["problems"])
        self.assertTrue(data["limitProblems"])

    def test_com_timeout_retains_partial_observations_and_reports_uncovered_scope(self):
        result = self.ps("Get-OutlookData.ps1", "-SelfTest", 100, "-SelfTestDelayMs", 25,
                         "-From", "2026-01-01", "-To", "2026-01-31", "-Force", "-BudgetSec", 2)
        self.assertEqual(result.returncode, 0, result.text)
        status = self.status("outlook_com")
        self.assertEqual(status["status"], "partial")
        self.assertGreater(status["rows"], 0)
        self.assertGreater(len(self.read("calendar.csv")), 0)
        self.assertTrue(status["reasons"])
        self.assertLessEqual(status["finished_at"], time.time())

    def test_com_body_access_failure_retains_metadata_and_prevents_folder_completion(self):
        code = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Outlook-Collection.ps1')
$root=Split-Path -Parent $PSScriptRoot; $mailP=Join-Path $root 'data\outlook\mail.csv'
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Get-OutlookData.ps1'),[ref]$tokens,[ref]$errors)
foreach($node in $tree.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('Read-MailMonth','Csv-Escape','Test-MeInList','Conv-Token')},$false)) {
    . ([scriptblock]::Create($node.Extent.Text))
}
$SelfTest=0; $SelfTestDelayMs=0; $BudgetSec=360; $sw=[Diagnostics.Stopwatch]::StartNew()
$TS='yyyy-MM-dd HH:mm:ss'; $fmt='g'; $contextChars=4000; $mailBody=$true; $storeSubject=$true
$script:collectionProblems=New-Object 'System.Collections.Generic.List[string]'; $script:observedRows=0
$MAIL_HEADER='box,time,sender,subject,conversation,rcv,time_precision,context_excerpt,context_truncated,source_id,source_kind,source_url,conversation_id,folder,account'
$message=[pscustomobject]@{Class=43; SenderName='synthetic'; SenderEmailAddress='other@synthetic.invalid';
  ReceivedTime=[datetime]'2026-01-03 09:00'; SentOn=[datetime]'2026-01-03 09:00'; Subject='Synthetic subject';
  ConversationTopic='Synthetic subject'; To='me@synthetic.invalid'; CC=''; EntryID='message-1'; ConversationID='thread-1'}
$message | Add-Member ScriptProperty Body { throw 'synthetic property failure' }
$items=[pscustomobject]@{Rows=@($message)}
$items | Add-Member ScriptMethod Sort {param($field,$descending)}
$items | Add-Member ScriptMethod Restrict {param($filter);return $this.Rows}
$folder=[pscustomobject]@{Items=$items;StoreID='default-store';FolderPath='Mailbox\Custom'}
$script:mailFolders=@(@{name='inbox';key='custom';field='[ReceivedTime]';folder=$folder})
$state=@{folders=@{}}; $month=[pscustomobject]@{key='2026-01';start=[datetime]'2026-01-01';end=[datetime]'2026-02-01'}
$rows=@(Read-MailMonth $null $month @('me@synthetic.invalid') $state)
@{rows=$rows.Count;done=$state.folders.custom.done;stop=$script:stopReason;problems=@($script:collectionProblems)} | ConvertTo-Json -Compress
"""
        (self.root / "collect/probe.ps1").write_text(code.replace("\n", "\r\n"), encoding="utf-8-sig", newline="")
        result = self.ps("probe.ps1")
        self.assertEqual(result.returncode, 0, result.text)
        data = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(data["rows"], 1, result.text)
        self.assertFalse(data["done"])
        self.assertTrue(data["stop"])
        self.assertTrue(data["problems"])
        self.assertEqual(self.read()[0]["subject"], "Synthetic subject")
        self.assertEqual(self.read()[0]["context_excerpt"], "")
        self.assertEqual(self.read()[0]["source_id"], "default-store:message-1")

    def test_com_selftest_retains_legacy_history_on_narrow_refresh(self):
        old = "box,time,sender,subject,conversation,rcv\ninbox,2020-01-01 10:00,synthetic,old,old,to\n"
        (self.out / "mail.csv").write_text(old, encoding="utf-8-sig")
        result = self.ps("Get-OutlookData.ps1", "-SelfTest", 3, "-From", "2026-01-01", "-To", "2026-01-31", "-Force")
        self.assertEqual(result.returncode, 0, result.text)
        rows = self.read()
        self.assertEqual(len(rows), 7, result.text)
        self.assertEqual(sum(r["subject"] == "old" for r in rows), 1)
        self.assertTrue(all(r.get("source_id") for r in rows if r["subject"] != "old"))
        result = self.ps("Get-OutlookData.ps1", "-SelfTest", 3, "-From", "2026-01-29", "-To", "2026-01-31", "-Force")
        self.assertEqual(result.returncode, 0, result.text)
        self.assertEqual(len(self.read()), 7, result.text)
        source = json.loads((self.out / "mail_source.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(source["mail"], 7)
        self.assertEqual(source["calendar"], len(self.read("calendar.csv")))
        status = self.status("outlook_com")
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["mail_scope"], "default_account_only")
        self.assertEqual(status["mail_status"], "complete")

    def test_com_incorrect_existing_csv_is_not_replaced(self):
        old = b"box,time,sender,subject,conversation,rcv\ninbox,2020-01-01,x,y,z,to,extra\n"
        (self.out / "mail.csv").write_bytes(old)
        result = self.ps("Get-OutlookData.ps1", "-SelfTest", 3, "-From", "2026-01-01", "-To", "2026-01-31", "-Force")
        self.assertNotEqual(result.returncode, 0, result.text)
        self.assertEqual((self.out / "mail.csv").read_bytes(), old)
        self.assertEqual(self.status("outlook_com")["status"], "failed")


if __name__ == "__main__":
    unittest.main()
