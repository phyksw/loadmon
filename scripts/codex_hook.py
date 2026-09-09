"""Read-only quality feedback for Codex; only local hash/log caches are written."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from quality import project_files

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(root):
    """Content, names and deletions count; private data and model replies never do."""
    digest = hashlib.sha256()
    for path in project_files(root):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def check(root, mode, current_hash):
    state_dir = root / ".codex" / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    stamp = state_dir / f"{mode}.json"
    try:
        cached = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    if cached.get("hash") == current_hash and cached.get("passed"):
        return True, "", True
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        result = subprocess.run(
            [sys.executable, "-B", str(root / "scripts" / "quality.py"), f"--{mode}", "--root", str(root)],
            cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150,
        )
        output = (result.stdout or "") + (result.stderr or "")
        passed = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        passed, output = False, f"Quality runner failed: {exc}"
    # Do not cache success if another agent changed code while the checker ran.
    if fingerprint(root) != current_hash:
        passed = False
        output += "\nFiles changed during validation; run quality again after edits finish."
    log = state_dir / f"{mode}-last.txt"
    log.write_text(output, encoding="utf-8")
    record = json.dumps({"hash": current_hash, "passed": passed}, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=state_dir, delete=False) as stream:
        stream.write(record)
        temp_name = stream.name
    os.replace(temp_name, stamp)
    return passed, output[-6000:], False


def handle(payload, root=ROOT):
    event = payload.get("hook_event_name", "")
    if event not in {"PostToolUse", "Stop"}:
        return {}
    if payload.get("permission_mode") == "plan":
        return {}
    mode = "full" if event == "Stop" else "quick"
    passed, output, cached = check(root, mode, fingerprint(root))
    if passed:
        if cached:
            return {}
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "LM25 quality checks passed."}} if event == "PostToolUse" else {}
    reason = f"LM25 {mode} 검증 실패. .codex/.state/{mode}-last.txt를 확인하고 수정 후 scripts/quality.py --{mode}를 실행하세요.\n{output}"
    if event == "Stop":
        if payload.get("stop_hook_active"):
            # Report a persistent failure without an unbounded continuation loop.
            return {"systemMessage": reason + "\n검증 미통과 상태를 최종 답변에 명시하세요."}
        return {"decision": "block", "reason": reason}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": reason}}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        response = handle(payload)
    except (OSError, ValueError) as exc:
        print(json.dumps({"systemMessage": f"LM25 hook input/check error: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
