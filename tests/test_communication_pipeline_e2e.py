"""Seven clues -> explicit mail intake -> real mine -> workflow material, in TEMP."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"


class CommunicationPipelineE2E(unittest.TestCase):
    def test_imported_original_context_reaches_workflow_and_repeat_import_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="lm25-communication-e2e-") as temporary:
            root = Path(temporary)
            for folder in ("core", "config", "report"):
                (root / folder).mkdir()
            for source in (APP / "core").glob("*.py"):
                shutil.copyfile(source, root / "core" / source.name)
            for name in ("mine.py", "flow.py"):
                shutil.copyfile(APP / name, root / name)
            config = json.loads((APP / "config/config.default.json").read_text("utf-8-sig"))
            config.update(owner="Synthetic", teamsSelfNames=["Synthetic"], projects=[])
            config["collection"]["communicationImportOwnAddresses"] = ["synthetic@example.invalid"]
            (root / "config/config.json").write_text(json.dumps(config), encoding="utf-8")
            script = r'''
import csv, json, os, pathlib, subprocess, sys
from email.message import EmailMessage
root = pathlib.Path.cwd()
sys.path[:0] = [str(root/'core'), str(root)]
from collection_state import merge_csv
from communication_evidence import build_report
from communication_import import import_paths
config=json.loads((root/'config/config.json').read_text('utf-8'))
period=['2026-09-07','2026-09-07'];tag='20260907-20260907'
clues=[dict(time=f'2026-09-07 10:{i:02d}', **{'from':'Synthetic'}, chat='SYNTHETIC-ROOM',
            kind='msg',summary='Synthetic design review',source_id=f'synthetic-{i}',
            conversation_id='synthetic-room',source_kind='teams_app',time_precision='minute') for i in range(7)]
merge_csv(root/'data/m365/teams_app.csv',clues,list(clues[0]))
before=build_report(root,*period,config)
assert before['families']['mail']['unique_rows']==0
assert before['families']['teams']['unique_rows']==7
assert before['families']['teams']['context_rows']==0
assert before['status']=='limited'
files=[]
for i in range(3):
    m=EmailMessage();m['From']='synthetic@example.invalid';m['To']='recipient@example.invalid'
    m['Date']=f'Mon, 07 Sep 2026 10:{20+i:02d}:00 +0900'
    m['Message-ID']=f'<lm25-{i}@example.invalid>';m['Subject']='Synthetic design review'
    m['References']='<root@example.invalid>'
    m.set_content('SYNTHETIC_CONTEXT_MARKER: request tolerance review; reply with revision; decision is prototype test, not final approval.')
    p=root/f'input-{i}.eml';p.write_bytes(m.as_bytes());files.append(str(p))
first=import_paths(root,files,*period,config)
assert first['imported_rows']==3, first
again=import_paths(root,files,*period,config)
assert again['imported_rows']==0, again
report=build_report(root,*period,config)
assert report['families']['mail']['unique_rows']==3
assert report['families']['mail']['context_rows']==3
assert report['families']['mail']['conversation_count']==1
assert report['families']['mail']['source_coverage_ratio'] is None
assert 'SYNTHETIC_CONTEXT_MARKER' not in json.dumps(report)
assert '@example.invalid' not in json.dumps(report)
run=subprocess.run([sys.executable,'-B','mine.py',str(root/'data'),'--from',period[0],'--to',period[1],
                    '--name','Synthetic'],capture_output=True,text=True,encoding='utf-8',
                    env=dict(os.environ,PYTHONIOENCODING='utf-8'),timeout=40)
assert run.returncode==0, run.stdout+run.stderr
with (root/f'report/signals_{tag}.csv').open(encoding='utf-8-sig',newline='') as f: signals=list(csv.DictReader(f))
assert sum('SYNTHETIC_CONTEXT_MARKER' in s.get('context_excerpt','') for s in signals)==3, signals
meta=json.loads((root/f'report/mm_meta_{tag}.json').read_text('utf-8-sig'))
assert meta['communication_evidence']['families']['mail']['unique_rows']==3
import flow
flow.MIN_SIGNALS=1
materials,basis,error=flow.gather(str(root/'report'),tag)
assert not error, error
prompt=flow.build_prompt(materials)
assert 'SYNTHETIC_CONTEXT_MARKER' in prompt, prompt
assert '사실 검증' in prompt
assert all(m['evidence_readiness']['fact_verified'] is False for m in materials)
assert any(m['evidence_readiness']['context_rows'] for m in materials)
print('PASS: seven clues / mail zero -> explicit originals -> dedupe -> mine -> bounded workflow prompt')
'''
            result = subprocess.run([sys.executable, "-B", "-c", script], cwd=root, capture_output=True,
                                    text=True, encoding="utf-8", timeout=55)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
