"""Read-only runtime design diagnostics using selected AST definitions and TEMP.

No application imports, real process starts, collection, user settings or network.
These observations reproduce defects; they are not desired regression assertions.
"""

import ast
import contextlib
import copy
import hashlib
import io
import json
import os
import runpy
import secrets
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
        return False

    namespace = {
        "cfg": lambda: {"graph": {"clientId": "synthetic-id"}},
        "arg": lambda flag: {"--from": "2026-09-01", "--to": "2026-09-02"}.get(flag),
        "date": date, "os": os, "ROOT": "SYNTHETIC_ROOT", "RUN": {}, "time": time,
        "sys": SimpleNamespace(argv=["run.py", "--collect-only", "--no-teams"], executable="SYNTHETIC_PYTHON"),
        "record": lambda *args: records.append(args), "step": fake_step,
        "archive_other_pc": lambda *args: None, "ensure_sampler": lambda *args: None,
        "collect_outlook": lambda *args: None, "mail_fallbacks": lambda *args: None,
    }
    load_definitions(namespace, "run.py", {"main"}, sources)
    with contextlib.redirect_stdout(io.StringIO()):
        exit_code = namespace["main"]()
    graph = [stage for stage in stages if "Graph" in stage["name"]]
    probes.append({"id": "no_teams_does_not_disable_graph", "observed": {"graph_calls": graph},
                   "issue_reproduced": len(graph) == 1})
    probes.append({"id": "failed_collection_reports_completion", "observed": {
        "failed_step_count": len(stages), "exit_code": exit_code, "completion_record": records[-1],
        "scope": "All six direct step calls fail; Outlook/fallbacks are no-op stubs."},
        "issue_reproduced": bool(stages) and exit_code == 0 and records[-1][1] is True})

    job = {"running": False}
    namespace = {"json": json, "LOCK": threading.Lock(), "JOB": job, "time": time,
                 "threading": SimpleNamespace(), "run_job": lambda *args: None}
    # Thread is resolved before its argument expressions, but must never start here.
    def forbidden_thread(*args, **kwargs):
        raise AssertionError("A real or stub worker must not be created by this probe")

    namespace["threading"].Thread = forbidden_thread
    load_method(namespace, "ui/app.py", "H", "do_POST", sources)
    replies = []
    handler = SimpleNamespace(path="/api/run", headers={"Content-Length": "2"}, rfile=io.BytesIO(b"[]"),
                              _freezing=lambda: False, _send=lambda *args: replies.append(args))
    exception = None
    try:
        namespace["do_POST"](handler)
    except AttributeError as error:
        exception = str(error)
    probes.append({"id": "json_array_latches_busy", "observed": {
        "payload": [], "exception": exception, "job_running": job["running"], "http_replies": replies},
        "issue_reproduced": exception is not None and job["running"] is True and not replies})

    commands = []
    namespace = {"subprocess": SimpleNamespace(run=lambda command, **kwargs: commands.append(command)), "NO_WIN": 0}
    load_definitions(namespace, "ui/app.py", {"kill_copilot_edge"}, sources)
    namespace["kill_copilot_edge"]()
    probes.append({"id": "browser_cleanup_has_no_installation_scope", "observed": {
        "captured_command_only_not_executed": commands[0], "real_processes_touched": False},
        "issue_reproduced": "-like '*copilot_profile*'" in commands[0][-1]})

    # Only newly created synthetic files are written; retained TEMP directory is reported.
    temp_root = Path(tempfile.mkdtemp(prefix="lm25-design-runtime-"))
    owner_root = temp_root / "synthetic-person"
    owner_root.mkdir()
    for name in ("first.csv", "second.csv", "member.json"):
        (owner_root / name).write_text('"old"', encoding="utf-8")
    observations = []

    def observe_replace(src, dst):
        os.replace(src, dst)
        if str(src).endswith(".part") and Path(dst).name == "first.csv":
            observations.append({p.name: p.read_text(encoding="utf-8") for p in (
                owner_root / "first.csv", owner_root / "second.csv", owner_root / "member.json")})

    os_proxy = SimpleNamespace(path=os.path, makedirs=os.makedirs, getpid=os.getpid, replace=observe_replace, remove=os.remove)
    namespace = {"os": os_proxy, "TEAMDATA": str(temp_root), "threading": threading, "secrets": secrets, "json": json}
    load_method(namespace, "teamserver.py", "H", "_save", sources)
    bad, staged = namespace["_save"]("synthetic-person", {"generation": "new"}, {"first.csv": "new", "second.csv": "new"})
    probes.append({"id": "team_bundle_publication_is_per_file", "observed": {
        "snapshot_after_first_replace": observations, "save_errors": bad, "staged_count": len(staged),
        "scope": "A callback observes the write boundary; no real concurrent server was run.",
        "synthetic_directory": str(temp_root)},
        "issue_reproduced": not bad and observations == [{"first.csv": "new", "second.csv": '"old"', "member.json": '"old"'}]})

    return {"schema_version": 1, "project": "LoadMonitor25", "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "execution": {"mode": "selected AST definitions with synthetic inputs and injected I/O",
                          "application_imported": False, "user_data_or_config_read": False,
                          "network_or_process_started": False, "temp_data_only": True},
            "sources": sources, "probes": probes}


if __name__ == "__main__":
    print(json.dumps(run_probes(), ensure_ascii=True, indent=2))
