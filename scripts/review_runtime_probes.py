"""Read-only runtime design diagnostics using selected AST definitions and TEMP.

No application imports, real process starts, collection, user settings or network.
These observations report whether historical defects still reproduce; a repaired
behavior produces issue_reproduced=false, not a desired regression assertion.
"""

import ast
import contextlib
import copy
import hashlib
import io
import json
import os
import runpy
import sys
import importlib.util
import tempfile
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

_helpers = runpy.run_path(str(Path(__file__).with_name("review_probes.py")))
SOURCE = _helpers["SOURCE"]
load_definitions = _helpers["load_definitions"]


def load_method(namespace, relative_path, class_name, method_name, sources):
    path = SOURCE / relative_path
    raw = path.read_bytes()
    tree = ast.parse(raw.decode("utf-8-sig"), filename=str(path))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = copy.deepcopy(next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name))
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    sources.append({"path": f"LoadMonitor25/{relative_path}", "sha256": hashlib.sha256(raw).hexdigest(),
                    "definitions": [f"{class_name}.{method_name}"]})


def run_probes():
    sources = []
    probes = []
    stages = []
    records = []

    def fake_step(name, command, timeout):
        stages.append({"name": name, "command": command, "result": False})
        namespace["RUN"]["stages"].append({"name": name, "ok": False})
        return False

    namespace = {
        "cfg": lambda: {"graph": {"clientId": "synthetic-id"}},
        "arg": lambda flag: {"--from": "2026-09-01", "--to": "2026-09-02"}.get(flag),
        "date": date, "os": os, "ROOT": "SYNTHETIC_ROOT", "RUN": {}, "time": time,
        "_ACTIVE_CACHE": None, "_CAPTURE_RESULTS": {},
        "sys": SimpleNamespace(argv=["run.py", "--collect-only", "--no-teams"], executable="SYNTHETIC_PYTHON"),
        "record": lambda *args: records.append(args), "step": fake_step,
        "archive_other_pc": lambda *args: True, "ensure_sampler": lambda *args: None,
        "collect_outlook": lambda *args: None, "mail_fallbacks": lambda *args: None,
    }
    load_definitions(namespace, "run.py", {"main", "finish_run"}, sources)
    with contextlib.redirect_stdout(io.StringIO()):
        exit_code = namespace["main"]()
    graph = [stage for stage in stages if "Graph" in stage["name"]]
    probes.append({"id": "no_teams_does_not_disable_graph", "observed": {"graph_calls": graph},
                   "issue_reproduced": len(graph) == 1})
    probes.append({"id": "failed_collection_reports_completion", "observed": {
        "failed_step_count": len(stages), "exit_code": exit_code, "completion_record": records[-1],
        "scope": "All direct injected step calls fail; Outlook/fallbacks are no-op stubs."},
        "issue_reproduced": bool(stages) and exit_code == 0 and records[-1][1] is True})

    job = {"running": False}
    namespace = {"json": json, "LOCK": threading.Lock(), "REQUEST_LOCK": threading.Lock(), "JOB": job, "time": time,
                 "threading": SimpleNamespace(), "run_job": lambda *args: None}
    # Thread is resolved before its argument expressions, but must never start here.
    def forbidden_thread(*args, **kwargs):
        raise AssertionError("A real or stub worker must not be created by this probe")

    namespace["threading"].Thread = forbidden_thread
    load_definitions(namespace, "ui/app.py", {"validate_run_request"}, sources)
    load_method(namespace, "ui/app.py", "H", "do_POST", sources)
    load_method(namespace, "ui/app.py", "H", "_do_POST", sources)
    replies = []
    handler = SimpleNamespace(path="/api/run", headers={"Content-Length": "2"}, rfile=io.BytesIO(b"[]"),
                              _freezing=lambda: False, _send=lambda *args: replies.append(args))
    handler._do_POST = lambda: namespace["_do_POST"](handler)
    exception = None
    try:
        namespace["do_POST"](handler)
    except AttributeError as error:
        exception = str(error)
    probes.append({"id": "json_array_latches_busy", "observed": {
        "payload": [], "exception": exception, "job_running": job["running"], "http_replies": replies},
        "issue_reproduced": exception is not None and job["running"] is True and not replies})

    commands = []
    def capture(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=b"[]")
    if str(SOURCE / "core") not in sys.path:
        sys.path.insert(0, str(SOURCE / "core"))
    namespace = {"subprocess": SimpleNamespace(run=capture), "NO_WIN": 0, "ROOT": "SYNTHETIC_ROOT", "json": json}
    load_definitions(namespace, "ui/app.py", {"kill_copilot_edge"}, sources)
    namespace["kill_copilot_edge"]()
    probes.append({"id": "browser_cleanup_has_no_installation_scope", "observed": {
        "captured_command_only_not_executed": commands[0], "real_processes_touched": False},
        "issue_reproduced": "-like '*copilot_profile*'" in commands[0][-1]})

    # Only newly created synthetic files are written; retained TEMP directory is reported.
    temp_root = Path(tempfile.mkdtemp(prefix="lm25-design-runtime-"))
    owner_root = temp_root / "synthetic-person"
    owner_root.mkdir()
    tag = "20260901-20260902"
    names = [f"mm_rows_{tag}.csv", f"mm_meta_{tag}.json", "member.json"]
    old_member = {"owner": "synthetic-person", "tag": tag, "generation": "old"}
    for name in names:
        (owner_root / name).write_text(json.dumps(old_member) if name == "member.json" else "old", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("runtime_probe_bundles", SOURCE / "core/bundles.py")
    bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundle)
    observations = []
    original_write = bundle._write

    def observe_write(path, body):
        original_write(path, body)
        active = Path(bundle.resolve_member_dir(owner_root))
        observations.append({n: (active / n).read_text(encoding="utf-8") for n in names})

    bundle._write = observe_write
    namespace = {"os": os, "TEAMDATA": str(temp_root), "write_bundle": bundle.write_bundle}
    load_method(namespace, "teamserver.py", "H", "_save", sources)
    bad, staged = namespace["_save"]("synthetic-person", dict(old_member, generation="new"),
                                     {names[0]: "new", names[1]: "new"})
    probes.append({"id": "team_bundle_publication_is_per_file", "observed": {
        "snapshots_during_staging": observations, "save_errors": bad, "staged_count": len(staged),
        "scope": "A callback observes the staging boundary; no actual server was run.",
        "synthetic_directory": str(temp_root)},
        "issue_reproduced": any(o[names[0]] != o[names[1]] for o in observations)})

    return {"schema_version": 1, "project": "LoadMonitor25", "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "execution": {"mode": "selected AST definitions with synthetic inputs and injected I/O",
                          "application_imported": False, "user_data_or_config_read": False,
                          "network_or_process_started": False, "temp_data_only": True},
            "sources": sources, "probes": probes}


if __name__ == "__main__":
    print(json.dumps(run_probes(), ensure_ascii=True, indent=2))
