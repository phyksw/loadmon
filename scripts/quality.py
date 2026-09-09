"""Read-only LM25 quality gates; full checks execute only an isolated code copy.

Usage: python -B scripts/quality.py --quick | --full
The --root option selects another *project* root for isolated verification.
No application entrypoint is imported or run by the quick checks.
"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib


EXCLUDED_DIRS = {
    "data", "report", "teamdata", "python", ".git", ".venv", "venv",
    "__pycache__", ".ruff_cache", ".pytest_cache", ".state", "node_modules",
    "copilot_profile", "loadmonitor24",
}
DEFAULT_CONFIGS = {"config.default.json", "agentic_tasks.json"}


def iter_source_files(source: Path):
    """Yield code/default configuration without traversing private/runtime trees."""
    for directory, children, filenames in os.walk(source, followlinks=False):
        parent = Path(directory)
        children[:] = sorted(
            name for name in children
            if name.casefold() not in EXCLUDED_DIRS and not (parent / name).is_symlink()
            and (parent / name).resolve().is_relative_to(source.resolve())
        )
        for name in sorted(filenames):
            path = parent / name
            if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
                continue
            relative = path.relative_to(source)
            if relative.parts[0].casefold() == "config" and relative.as_posix().casefold() not in {
                f"config/{name}" for name in DEFAULT_CONFIGS
            }:
                continue
            yield path


def project_files(root: Path) -> list[Path]:
    files = []
    for name in ("LoadMonitor25", "scripts", "tests", ".codex", ".githooks"):
        folder = root / name
        if folder.is_dir() and not folder.is_symlink():
            files.extend(iter_source_files(folder))
    files.extend(path for path in root.iterdir() if path.is_file() and not path.is_symlink()
                 and not path.name.casefold().startswith('.env'))
    return sorted(set(files))


def label(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def check_syntax(paths: list[Path], root: Path) -> list[str]:
    findings = []
    for path in paths:
        kind = path.suffix.lower()
        if kind not in {".py", ".json", ".toml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
            if kind == ".py":
                ast.parse(text, filename=label(path, root))
            elif kind == ".json":
                json.loads(text)
            else:
                tomllib.loads(text)
        except (OSError, UnicodeError, SyntaxError, ValueError) as error:
            findings.append(f"{label(path, root)}: {error}")
    return findings


def check_encodings(paths: list[Path], root: Path) -> list[str]:
    findings = []
    for path in paths:
        kind = path.suffix.lower()
        if kind not in {".bat", ".ps1"}:
            continue
        data = path.read_bytes()
        has_bom = data.startswith(b"\xef\xbb\xbf")
        if kind == ".bat" and has_bom:
            findings.append(f"{label(path, root)}: BAT must be CP949 without BOM")
        elif kind == ".ps1" and not has_bom:
            findings.append(f"{label(path, root)}: PowerShell requires UTF-8 BOM")
        if re.search(rb"(?<!\r)\n|\r(?!\n)", data):
            findings.append(f"{label(path, root)}: {kind} requires CRLF line endings")
        try:
            data.decode("cp949" if kind == ".bat" else "utf-8-sig", errors="strict")
        except UnicodeError:
            findings.append(f"{label(path, root)}: invalid {kind} encoding")
    return findings


def child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    # The legacy lint entrypoint invokes `python`; use this same Ruff-enabled runtime.
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    return environment


def run_command(command: list[str], cwd: Path, *, input_text: str | None = None,
                timeout: int = 120) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, cwd=cwd, env=child_environment(),
            input=input_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return 1, f"Cannot finish check: {error}"


def powershell_executable() -> str | None:
    windows = os.environ.get("SystemRoot")
    if windows:
        native = Path(windows) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if native.is_file():
            return str(native)
    return shutil.which("powershell") or shutil.which("pwsh")


def check_powershell(paths: list[Path], root: Path, executable: str) -> tuple[int, str]:
    files = [path for path in paths if path.suffix.lower() == ".ps1"]
    literals = ",".join("'" + str(path).replace("'", "''") + "'" for path in files)
    script = """
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$ErrorActionPreference = 'Stop'
$failed = 0
foreach ($file in @(__LM25_FILES__)) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$errors)
    foreach ($problem in $errors) {
        $failed = 1
        Write-Output ('{0}:{1}: {2}' -f $file, $problem.Extent.StartLineNumber, $problem.Message)
    }
}
exit $failed
""".replace("__LM25_FILES__", literals)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return run_command([executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], root)


def check_page_javascript(source: Path, node_exe: str, root: Path) -> list[str]:
    """Parse browser-visible literals with Node; never import ui.app/teamserver."""
    findings = []
    for relative in ("ui/app.py", "teamserver.py"):
        path = source / relative
        if not path.is_file():
            findings.append(f"{label(path, root)}: required source file missing")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, SyntaxError) as error:
            findings.append(f"{label(path, root)}: {error}")
            continue
        pages = {}
        for statement in tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in {"PAGE", "TEAM_PAGE"}:
                    value = statement.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        pages[target.id] = value.value
                    else:
                        findings.append(f"{label(path, root)}:{target.id}: expected static HTML literal")
        if relative == "ui/app.py":
            for missing in sorted({"PAGE", "TEAM_PAGE"} - pages.keys()):
                findings.append(f"{label(path, root)}: missing {missing} literal")
        for name, html in pages.items():
            scripts = re.findall(r"<script\b[^>]*>(.*?)</script\s*>", html, re.S | re.I)
            if not scripts:
                findings.append(f"{label(path, root)}:{name}: no script found")
            for index, javascript in enumerate(scripts, 1):
                code, output = run_command([node_exe, "--check", "-"], root,
                                           input_text=javascript, timeout=30)
                if code:
                    findings.append(f"{label(path, root)}:{name}/script{index}: {output}")
    return findings


class QualityGates:
    def __init__(self, root: Path):
        self.root = root
        self.failed = 0

    def findings(self, name: str, findings: list[str]) -> None:
        print(f"[{'FAIL' if findings else 'PASS'}] {name}", flush=True)
        if findings:
            self.failed += 1
            for finding in findings:
                print(f"  {finding}", flush=True)

    def command(self, name: str, command: list[str], *, cwd: Path | None = None,
                timeout: int = 120) -> None:
        code, output = run_command(command, cwd or self.root, timeout=timeout)
        self.findings(name, [output or f"exit {code}"] if code else [])
        if not code and output:
            print(output, flush=True)


def quick_checks(gates: QualityGates, source: Path) -> str | None:
    files = project_files(gates.root)
    gates.findings("Python / JSON / TOML syntax", check_syntax(files, gates.root))
    gates.findings("BAT CP949 / PowerShell UTF-8 BOM / CRLF", check_encodings(files, gates.root))
    python_files = [str(path) for path in files if path.suffix.lower() == ".py"]
    gates.command("Ruff: all LM25 + project Python (including UI)", [
        sys.executable, "-B", "-m", "ruff", "check", "--no-cache", "--config",
        str(source / "ruff.toml"), "--output-format=concise", *python_files,
    ])
    powershell = powershell_executable()
    if powershell:
        code, output = check_powershell(files, gates.root, powershell)
        gates.findings("PowerShell parser", [output or f"exit {code}"] if code else [])
    else:
        gates.findings("PowerShell parser", ["PowerShell is required but unavailable"])
    node = shutil.which("node")
    if node:
        gates.findings("PAGE / TEAM_PAGE JavaScript: Node parser",
                       check_page_javascript(source, node, gates.root))
    else:
        gates.findings("PAGE / TEAM_PAGE JavaScript", ["Node.js is required; fallback cannot certify syntax"])
    return powershell


def full_checks(gates: QualityGates, source: Path, powershell: str | None) -> None:
    packaged = source / "python/python.exe"
    if not packaged.is_file():
        gates.findings("Packaged Python", ["LoadMonitor25/python/python.exe is missing"])
        return
    gates.command("Packaged Python", [str(packaged), "-B", "--version"])
    gates.findings("Git dependency", [] if shutil.which("git") else ["Git is required but unavailable"])
    with tempfile.TemporaryDirectory(prefix="LoadMonitor25-quality-") as temporary:
        clone = Path(temporary).resolve()
        assert clone.parent == Path(tempfile.gettempdir()).resolve()
        assert clone.name.startswith("LoadMonitor25-quality-")
        for path in iter_source_files(source):
            destination = clone / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        # Personalized config never enters the checks; the package ships defaults.
        shutil.copyfile(clone / "config/config.default.json", clone / "config/config.json")
        gates.command("Required files (isolated defaults)", [
            str(packaged), "-B", str(clone / "자가점검.py")], cwd=clone)
        gates.command("FILES size / CRC32 (isolated defaults)", [
            str(packaged), "-B", str(clone / "tools/update_files.py"), "--check"], cwd=clone)
        if powershell:
            gates.command("Legacy seven lint gates (isolated copy)", [
                powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(clone / "tools/lint.ps1"),
            ], cwd=clone)
    tests = gates.root / "tests"
    if tests.is_dir():
        if not any(path.is_file() for path in tests.rglob("test_*.py")):
            gates.findings("Project regression tests", ["tests/ contains no test_*.py files"])
            return
        gates.command("Project regression tests", [
            sys.executable, "-B", "-m", "unittest", "discover", "-s", str(tests), "-p", "test_*.py",
        ], timeout=120)
    else:
        print("[SKIP] Project regression tests: tests/ is not present", flush=True)


def main(argv: list[str] | None = None) -> int:
    # Windows developer Python may otherwise emit CP949 to UTF-8 hook/log pipes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--quick", action="store_true", help="read-only static checks")
    mode.add_argument("--full", action="store_true", help="static checks + isolated package checks + regression")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    source = root / "LoadMonitor25"
    if not source.is_dir() or source.is_symlink():
        print(f"[FAIL] LM25 source directory missing or linked: {source}")
        return 1
    gates = QualityGates(root)
    print(f"LM25 {'full' if args.full else 'quick'} quality checks; application services are not started.", flush=True)
    try:
        powershell = quick_checks(gates, source)
        if args.full:
            full_checks(gates, source, powershell)
    except (OSError, ValueError) as error:
        gates.findings("Quality runner", [str(error)])
    result = "FAIL" if gates.failed else "PASS"
    print(f"RESULT: {result} ({gates.failed} failed gates; static/isolated checks only)", flush=True)
    return 1 if gates.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
