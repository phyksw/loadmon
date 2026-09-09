"""Read-only LM25 review probes; diagnostic examples, not a green regression gate.

Run from the project root: python -B scripts/review_probes.py
Only selected source definitions and constants are evaluated. Application imports,
entry points, configuration, collected data, reports, and network APIs are unused.
The caller may save the JSON stdout as docs/LM25_REVIEW_EVIDENCE.json.
"""

import ast
import hashlib
import json
import re
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25"


def load_definitions(namespace, relative_path, names, sources):
    """Compile explicitly selected functions/constants, excluding module imports."""
    path = SOURCE / relative_path
    raw = path.read_bytes()
    tree = ast.parse(raw.decode("utf-8-sig"), filename=str(path))
    nodes, found = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if assigned & names:
                nodes.append(node)
                found.update(assigned & names)
    if found != names:
        raise ValueError(f"Missing source definitions in {relative_path}: {sorted(names - found)}")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    sources.append({
        "path": f"LoadMonitor25/{relative_path}",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "definitions": sorted(found),
    })


def main():
    sources = []
    namespace = {"re": re, "unicodedata": unicodedata, "time": time}
    load_definitions(namespace, "core/details.py", {"fold", "_f"}, sources)
    # recalc_mm only needs details._f when the optional alias map is absent.
    namespace["details"] = SimpleNamespace(_f=namespace["_f"])
    load_definitions(namespace, "agentic.py", {
        "MAX_WORK", "_MARK_RE", "_placeholder", "_clean_list",
        "_row_index", "find_rows", "recalc_mm",
    }, sources)
    recalc = namespace["recalc_mm"]

    duplicate_rows = [
        {"Level 2": "project A", "Level 3": "design review", "mm": 0.2},
        {"Level 2": "project B", "Level 3": "design review", "mm": 0.8},
    ]
    duplicate_result = {
        "match": [{"task": "candidate A", "fit": 50, "work": ["design review"]}],
        "new": [],
    }
    recalc(duplicate_result, duplicate_rows)
    duplicate_match = duplicate_result["match"][0]
    duplicate_observed = {key: duplicate_match.get(key) for key in (
        "load_mm", "load_mm_split", "evidence_rows", "evidence_missing",
    )}

    overlap_rows = [{"Level 2": "project A", "Level 3": "design review", "mm": 1.0}]
    overlap_result = {
        "match": [
            {"task": "candidate A", "fit": 10, "work": ["design review"]},
            {"task": "candidate B", "fit": 90, "work": ["design review"]},
        ],
        "new": [],
    }
    recalc(overlap_result, overlap_rows)
    overlap_matches = [
        {key: match.get(key) for key in ("task", "fit", "load_mm", "load_mm_split")}
        for match in overlap_result["match"]
    ]
    raw_sum = sum(match["load_mm"] for match in overlap_matches)
    split_sum = sum(match["load_mm_split"] for match in overlap_matches)

    load_definitions(namespace, "flow.py", {
        "AGENT_OK", "MAX_BRANCHES", "KEY_JOIN", "_SEP", "_DASH_TAIL", "_PAREN_TAIL",
        "_fold_sep", "_norm_model", "_strip_tails", "_tail_note", "_uniq_map",
        "_resolve_key", "sanitize_flows",
    }, sources)
    # This explicit mode avoids workflow_unit() reading a user's config.json.
    namespace["workflow_unit"] = lambda: "담당업무"
    materials = {
        "project A / design review": {
            "model": "project A", "detail": "design review", "mm": 0.2,
            "signals": 5, "evidence": ["design checklist update"],
        },
    }
    raw_flows = [{
        "key": "project A / design review",
        "steps": [{
            "name": "approve purchase", "evidence": "a source that does not exist", "agent": "UNSURE",
        }],
    }]
    flows = namespace["sanitize_flows"](raw_flows, materials)
    accepted_steps = [step for flow in flows for step in flow.get("steps", [])]

    result = {
        "schema_version": 1,
        "project": "LoadMonitor25",
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "purpose": "Reproduce review findings; observed values are not desired regression expectations.",
        "execution": {
            "command": "python -B scripts/review_probes.py",
            "mode": "selected AST definitions with synthetic in-memory inputs",
            "application_module_imported": False,
            "application_entry_point_executed": False,
            "user_data_or_config_read": False,
            "network_used": False,
            "files_written_by_probe": False,
            "stubs": ["details exposes only the extracted _f", "workflow_unit returns 담당업무"],
        },
        "sources": sources,
        "probes": [
            {
                "id": "ambiguous_detail_across_projects",
                "certainty": "confirmed function behavior; field frequency unmeasured",
                "input": {"rows": duplicate_rows, "work": ["design review"]},
                "observed": duplicate_observed,
                "expected_improvement": {
                    "status": "ambiguous until a project-scoped row identifier is supplied",
                    "eligible_related_mm_while_ambiguous": 0.0,
                    "related_mm_if_project_A_is_explicitly_selected": 0.2,
                },
                "issue_reproduced": duplicate_observed["evidence_rows"] == 2
                and duplicate_observed["load_mm"] == 1.0,
            },
            {
                "id": "related_mm_overlap_and_savings_semantics",
                "certainty": "confirmed calculation; UI consumers were reviewed statically, not run here",
                "input": {"rows": overlap_rows, "candidate_fits": [10, 90]},
                "observed": {"matches": overlap_matches, "raw_sum_mm": raw_sum, "split_sum_mm": split_sum},
                "expected_improvement": {
                    "unique_related_work_mm": 1.0,
                    "estimated_saved_mm": None,
                    "display_contract": "Name related workload explicitly; use one aggregation policy across reports.",
                    "savings_contract": "Do not infer saved hours from fit or equal overlap allocation.",
                },
                "issue_reproduced": raw_sum == 2.0 and split_sum == 1.0,
            },
            {
                "id": "unverified_workflow_evidence_and_rating",
                "certainty": "confirmed sanitizer behavior; no live AI request made",
                "input": {"materials": materials, "raw_flows": raw_flows},
                "observed": {"accepted_flows": len(flows), "accepted_steps": accepted_steps},
                "expected_improvement": {
                    "status": "needs_review",
                    "automation_grade": None,
                    "unverified_steps_excluded_from_automation_ranking": True,
                    "evidence_contract": "Validate each evidence identifier against the same project and period.",
                },
                "issue_reproduced": any(
                    step.get("evidence") == "a source that does not exist" and step.get("agent") == "중"
                    for step in accepted_steps
                ),
            },
        ],
    }
    # ASCII escapes keep redirected JSON valid on Windows consoles with any code page.
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
