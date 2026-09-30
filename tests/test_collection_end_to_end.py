"""Real packaged Python/PowerShell workers through production UI and evidence code.

Only generated workers and synthetic CSVs in TEMP execute. Production collectors,
the UI server, personal settings, browsers and accounts are never started/read.
"""
import ast
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

import test_collection_ui as page_harness


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
FIELDS = ["time", "source_id", "sender", "from", "subject", "summary", "chat", "context_excerpt"]
PYTHON_WORKER = """import csv, time
from pathlib import Path
print('[synthetic] ready', flush=True)
for _ in range(200):
    if Path('ack').exists(): break
    time.sleep(.01)
else: raise RuntimeError('stream callback did not arrive')
for folder, name in [('outlook', 'mail.csv'), ('m365', 'teams_window.csv')]:
    target = Path('data') / folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(dict(time='2026-09-03 10:00', source_id=folder, subject='Synthetic mail',
                             summary='Synthetic chat', chat='Synthetic room', context_excerpt='Synthetic body'))
print('[synthetic] CSV saved', flush=True)
"""
POWERSHELL_WORKER = """[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$ErrorActionPreference = 'Stop'
Write-Output '[synthetic] ready'
$until = [DateTime]::UtcNow.AddSeconds(2)
while (-not (Test-Path -LiteralPath 'ack')) {
    if ([DateTime]::UtcNow -ge $until) { throw 'stream callback did not arrive' }
    Start-Sleep -Milliseconds 10
}
New-Item -ItemType Directory -Path 'data/outlook','data/m365' -Force | Out-Null
@('time,source_id,sender,from,subject,summary,chat,context_excerpt',
  '2026-09-03 10:00,outlook,Sender,,Synthetic mail,,,Synthetic body') |
  Set-Content -LiteralPath 'data/outlook/mail.csv' -Encoding UTF8
@('time,source_id,sender,from,subject,summary,chat,context_excerpt',
  '2026-09-03 10:00,m365,,Sender,,Synthetic chat,Synthetic room,Synthetic body') |
  Set-Content -LiteralPath 'data/m365/teams_window.csv' -Encoding UTF8
[Console]::Error.WriteLine('[synthetic] stderr merged')
Write-Output '[synthetic] CSV saved'
exit 0
"""


def function_source(path, name):
    source = path.read_text("utf-8-sig")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(source, node)


class CollectionEndToEndTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-real-collection-chain-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "합성 작업공간"
        self.root.mkdir()
        self.python = APP / "python/python.exe"
        self.assertTrue(self.python.is_file(), "Packaged runtime is required by the product")

    def seed(self, directory):
        for folder, name in (("outlook", "mail.csv"), ("m365", "teams_window.csv")):
            path = directory / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow({"time": "2026-09-02 10:00", "source_id": "previous-" + folder,
                    "subject": "Synthetic previous mail", "summary": "Synthetic previous chat",
                    "chat": "Synthetic room", "context_excerpt": "Retained previous body"})
                writer.writerow({"time": "2026-08-02 10:00", "source_id": "outside-" + folder,
                    "subject": "Outside requested period", "summary": "Outside requested period"})

    def run_ui(self, worker_kind):
        if worker_kind == "powershell":
            shell = shutil.which("powershell")
            self.assertTrue(shell, "Windows PowerShell is required by the product")
            worker = self.root / "synthetic_worker.ps1"
            worker.write_text(POWERSHELL_WORKER, encoding="utf-8-sig", newline="\r\n")
            command = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(worker)]
        else:
            worker = self.root / "synthetic_worker.py"
            if worker_kind == "failed":
                program = "import sys\nprint('[synthetic] failed', flush=True)\nsys.exit(7)\n"
            elif worker_kind == "broken":
                program = ("from pathlib import Path\n"
                    "for folder,name in [('outlook','mail.csv'),('m365','teams_window.csv')]:\n"
                    " p=Path('data')/folder/name;p.parent.mkdir(parents=True,exist_ok=True)\n"
                    " p.write_text('time,subject\\n2026-09-03 10:00,Synthetic title,extra column\\n',encoding='utf-8')\n"
                    "print('[synthetic] malformed CSV stored',flush=True)\n")
            else:
                program = "FIELDS=" + repr(FIELDS) + "\n" + PYTHON_WORKER
            worker.write_text(program, encoding="utf-8")
            command = [str(self.python), "-B", str(worker)]
        # The real step()/run_stream execute in a separate packaged-Python process.
        runner = ("import sys, os, time\nfrom pathlib import Path\n"
                  "sys.path.insert(0," + repr(str(APP / "core")) + ")\n"
                  "ROOT=str(Path(__file__).parent)\nNO_WIN=0x08000000\n"
                  "def record(*args): pass\n")
        runner += function_source(APP / "run.py", "step") + "\n"
        runner += "ok=step('Synthetic raw collector'," + repr(command) + ",10)\n"
        runner += ("from communication_evidence import write_report\n"
                   "write_report(ROOT,'2026-09-01','2026-09-20')\n"
                   "sys.exit(0 if ok else 2)\n")
        (self.root / "run.py").write_text(runner, encoding="utf-8")
        lines, early = [], []

        def log(line):
            lines.append(line)
            if line.strip() == "[synthetic] ready":
                early.append(not (self.root / "data/outlook/mail.csv").exists())
                (self.root / "ack").write_text("continue", encoding="utf-8")

        processes = []
        def launch(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            processes.append(process)
            return process

        env = {"os": os, "json": json, "sys": SimpleNamespace(executable=str(self.python)), "time": time,
               "subprocess": SimpleNamespace(Popen=launch, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT),
               "ROOT": str(self.root), "NO_WIN": 0x08000000, "LOCK": threading.Lock(),
               "JOB": {"phase": "", "running": True}, "log": log, "parse_progress": lambda _: None}
        for name in ("validate_run_request", "run_job"):
            exec(compile(function_source(APP / "ui/app.py", name), "production-" + name, "exec"), env)
        request = {"from": "2026-09-01", "to": "2026-09-20", "collect_only": True, "mail_body": True}
        try:
            env["run_job"](*env["validate_run_request"](request), mail_body=request["mail_body"])
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()
        evidence = json.loads((self.root / "report/communication_evidence_20260901-20260920.json").read_text("utf-8"))
        self.assertFalse(env["JOB"]["running"])
        return env["JOB"]["run_result"], evidence, lines, early

    def test_real_python_and_powershell_saved_rows_reach_ui_with_previous_pc_and_period_filter(self):
        for kind in ("python", "powershell"):
            with self.subTest(worker=kind):
                self.root = self.root / kind
                self.root.mkdir()
                self.seed(self.root / "data/추가PC/synthetic-previous-pc")
                result, evidence, lines, early = self.run_ui(kind)
                self.assertEqual(result["code"], 0, lines)
                self.assertTrue(result["ok"])
                self.assertEqual(early, [True])
                for family, label in (("mail", "메일"), ("teams", "Teams")):
                    counts = evidence["families"][family]
                    self.assertEqual((counts["raw_rows"], counts["unique_rows"], counts["context_rows"]), (3, 2, 2))
                    self.assertIn(f"{label} 2건 / 본문 발췌 2건", result["message"])
                if kind == "powershell":
                    self.assertTrue(any("stderr merged" in line for line in lines))

    def test_failed_real_child_retains_saved_rows_and_displays_partial_counts(self):
        self.seed(self.root / "data")
        result, evidence, lines, early = self.run_ui("failed")
        self.assertEqual(result["code"], 2, lines)
        self.assertFalse(result["ok"])
        self.assertEqual(early, [])
        self.assertIn("부분 완료", result["message"])
        for family, label in (("mail", "메일"), ("teams", "Teams")):
            self.assertEqual(evidence["families"][family]["unique_rows"], 1)
            self.assertIn(f"{label} 1건 / 본문 발췌 1건", result["message"])

    def test_real_broken_csv_is_unknown_count_in_completion_and_actual_page_card(self):
        page_harness.CollectionUiTests.setUpClass()
        page = page_harness.CollectionUiTests()
        for previous_count in (0, 1):
            with self.subTest(previous_valid_records=previous_count):
                self.root = self.root / ("previous-" + str(previous_count))
                self.root.mkdir()
                if previous_count:
                    self.seed(self.root / "data/추가PC/synthetic-previous-pc")
                result, evidence, _, _ = self.run_ui("broken")
                for family, label in (("mail", "메일"), ("teams", "Teams")):
                    observed = evidence["families"][family]
                    self.assertEqual(observed["unreadable_files"], 1)
                    self.assertEqual(observed["unique_rows"], previous_count)
                    self.assertIn(f"{label} 건수 미확인 (읽기 실패 1파일 · 확인된 {previous_count}건", result["message"])
                    self.assertNotIn(f"{label} 0건", result["message"])
                page.run_js("context.renderCommunicationEvidence(" + json.dumps(evidence) + ");\n"
                    "const html=byId.communicationevidence.innerHTML;\n"
                    "assert.equal((html.match(/<td>건수 미확인<br>/g)||[]).length,2);\n"
                    "assert.equal((html.match(/읽기 실패 1파일 · 확인된 " + str(previous_count) + "건/g)||[]).length,2);\n"
                    "assert(!html.includes('<td>0건</td>'));\n")


if __name__ == "__main__":
    unittest.main()
