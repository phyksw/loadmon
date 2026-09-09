"""Validate exactly the staged snapshot, including partially staged files."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRS = {"data", "report", "teamdata", "copilot_profile", "__pycache__", ".state", "verification", ".venv"}


def forbidden(path):
    parts = tuple(part.lower() for part in Path(path).parts)
    return bool(PRIVATE_DIRS.intersection(parts)) or (
        len(parts) >= 3 and parts[0].startswith("loadmonitor") and parts[1] == "config"
        and parts[2] not in {"config.default.json", "agentic_tasks.json"}
    )


def main(root=ROOT):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    staged = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], cwd=root, capture_output=True, check=True).stdout
    names = [x.decode("utf-8") for x in staged.split(b"\0") if x]
    bad = [x for x in names if forbidden(x)]
    if bad:
        print("Commit rejected: personal/generated files are staged:\n" + "\n".join(bad), file=sys.stderr)
        return 1
    changed = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"], cwd=root, capture_output=True, check=True).stdout
    if not changed:
        print("No staged changes.")
        return 0
    snapshot = Path(tempfile.mkdtemp(prefix="lm25-index-check-"))
    subprocess.run(["git", "checkout-index", "--all", f"--prefix={snapshot.as_posix()}/"], cwd=root, check=True)
    runner = snapshot / "scripts" / "quality.py"
    if not runner.is_file():
        print("Staged snapshot has no scripts/quality.py; stage the project infrastructure first.", file=sys.stderr)
        return 1
    print(f"Checking staged snapshot: {snapshot}")
    return subprocess.run([sys.executable, "-B", str(runner), "--full", "--root", str(snapshot)], cwd=snapshot, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
