"""Opt-in, fail-closed reuse of a completed analysis in its original directory.

No application imports occur while inspecting a cache. The optional stage observer
runs only in a child process, preserves results/stdio, and stores no prompt bodies.
"""
import ast
import csv
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid
from datetime import date

SCHEMA = 3
MAX_AGE = 24 * 60 * 60
MAX_FILES = 20000
MAX_BYTES = 512 * 1024 * 1024
MAX_EXTERNAL_FILES = 1000
MAX_EXTERNAL_BYTES = 64 * 1024 * 1024
STAGES = ("judge.py", "refine.py", "agentic.py", "flow.py")
CACHE_DIR = ".run_cache"


class Uncertain(ValueError):
    """Missing or changing evidence must produce a cache miss, never success."""


def _json(path):
    with open(path, encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise Uncertain("JSON 객체가 아닌 자료")
    return value


def _atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=1, allow_nan=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _linked(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _digest(path, budget):
    if _linked(path):
        raise Uncertain("링크/클라우드 파일은 재사용 검증 제외")
    before = path.stat()
    if getattr(before, "st_file_attributes", 0) & (0x400000 | 0x40000 | 0x1000):
        raise Uncertain("오프라인/자리표시자 파일은 열지 않음")
    budget[0] -= 1
    budget[1] -= before.st_size
    if min(budget) < 0:
        raise Uncertain("내용 검증 파일 수/용량 예산 초과")
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    after = path.stat()
    fields = ("st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise Uncertain("내용 검증 중 파일 변경")
    return digest.hexdigest()


def _tree(root, directory, budget, report=False):
    base = root / directory
    if not base.exists():
        return {}
    result = {}
    for current, directories, names in os.walk(base):
        current = Path(current)
        if _linked(current):
            raise Uncertain("자료 폴더 링크는 재사용 검증 제외")
        directories[:] = sorted(d for d in directories
                                if not (d == "__pycache__" and directory in ("core", "ui", "tools", "collect", "python"))
                                and not (report and d == CACHE_DIR)
                                and not (current == root / "data" and d == "copilot_profile"))
        if any(_linked(current / name) for name in directories):
            raise Uncertain("자료 하위 폴더 링크는 재사용 검증 제외")
        for name in sorted(names):
            if report and current == base and name == "last_run.json":
                continue
            path = current / name
            digest = _digest(path, budget)
            # UI chooses latest/raw/refined files using mtime. Verify both content
            # and that display-selection metadata, never mtime on its own.
            result[path.relative_to(root).as_posix()] = (
                {"sha256": digest, "mtime_ns": path.stat().st_mtime_ns} if report else digest)
    return result


def _external_hints(root):
    """Only paths already named by collected file CSVs; no folder discovery."""
    tree = ast.parse((root / "core" / "extract.py").read_text(encoding="utf-8-sig"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("HINT_TEXT_EXTS", "HINT_OOXML"):
                    constants[target.id] = ast.literal_eval(node.value)
    if len(constants) != 2:
        raise Uncertain("원본 파일 힌트 범위를 확인하지 못함")
    extensions = set(constants["HINT_TEXT_EXTS"]) | set(constants["HINT_OOXML"])
    paths = set()
    for current, directories, names in os.walk(root / "data"):
        if Path(current) == root / "data":
            directories[:] = [d for d in directories if d != "copilot_profile"]
        for name in names:
            if name not in ("files.csv", "recent.csv", "files_history.csv", "recent_history.csv"):
                continue
            with open(Path(current) / name, encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    filename = row.get("name") or ""
                    if Path(filename).suffix.lower() not in extensions:
                        continue
                    folder = row.get("folder") or ""
                    path = Path(folder) / filename
                    if not path.is_absolute():
                        path = root / path
                    paths.add(str(path))
                    if len(paths) > MAX_EXTERNAL_FILES:
                        raise Uncertain("원본 파일 힌트 개수 예산 초과")
    result, budget = {}, [MAX_EXTERNAL_FILES, MAX_EXTERNAL_BYTES]
    for name in sorted(paths):
        path = Path(name)
        if name.startswith(("\\\\", "//")):
            raise Uncertain("네트워크 원본 파일 힌트는 재사용 검증 제외")
        if os.name == "nt":
            import ctypes
            if ctypes.windll.kernel32.GetDriveTypeW(path.anchor) == 4:
                raise Uncertain("원격 드라이브 원본 파일은 열지 않음")
        try:
            # file_hint never reads files above 50 MiB. Decline instead of opening
            # a large original merely to decide whether a cached hint is stale.
            if path.stat().st_size > 50 * 1024 * 1024:
                raise Uncertain("원본 파일 힌트 크기 한도 초과 — 내용은 열지 않음")
            if any(_linked(parent) for parent in path.parents if parent.exists()):
                raise Uncertain("원본 파일 힌트 경로의 링크는 열지 않음")
            result[name] = _digest(path, budget)
        except FileNotFoundError:
            result[name] = None
    return result


def inputs(root, period):
    root = Path(root).resolve()
    budget = [MAX_FILES, MAX_BYTES]
    files = {}
    for directory in ("data", "config", "core", "ui", "tools", "collect", "python"):
        files.update(_tree(root, directory, budget))
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in (".py", ".bat", ".ps1", ".json", ".txt"):
            files[path.name] = _digest(path, budget)
    # Historical entity files are actual inputs, chosen by modification order.
    entities = sorted((root / "report").glob("entities_*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name))
    context = {p.name: _digest(p, budget) for p in entities}
    legacy = root / "report" / "보완툴" / "detail_aliases.json"
    if legacy.exists():
        context["legacy_detail_aliases"] = _digest(legacy, budget)
    return {"files": files, "external_hints": _external_hints(root), "entities": context,
            "entity_order": [p.name for p in entities], "period": list(period),
            "mode": "skip-collect-ai", "python": sys.version, "timezone": list(time.tzname),
            "host": os.environ.get("COMPUTERNAME", ""), "user": os.environ.get("USERNAME", "")}


def outputs(root):
    return _tree(Path(root), "report", [MAX_FILES, MAX_BYTES], report=True)


def eligible(argv, config, period, today=None):
    if "--reuse-complete" not in argv:
        return "재사용 옵션 없음"
    if "--skip-collect" not in argv or "--ai" not in argv or "--collect-only" in argv:
        return "재사용은 --skip-collect --ai 전용"
    allowed = {"--skip-collect", "--ai", "--reuse-complete", "--force", "--from", "--to"}
    if any(arg.startswith("--") and arg not in allowed for arg in argv):
        return "별도 실행 옵션이 있어 재사용하지 않음"
    if not isinstance(config, dict) or not config:
        return "설정 확인 불가"
    upload = config.get("teamUpload") or {}
    if not isinstance(upload, dict):
        return "업로드 설정 확인 불가"
    if config.get("teamShareDir") or upload.get("auto"):
        return "공유/자동 업로드 요청은 전체 실행으로 처리"
    if os.environ.get("LM_COPILOT_STUB"):
        return "스텁 모드는 재사용하지 않음"
    if date.fromisoformat(period[1]) >= (today or date.today()):
        return "오늘/미래 포함 기간은 현재 시각에 따라 재계산 필요"
    return ""


def _zero(obj, keys):
    return all(type(obj.get(key)) is int and obj[key] == 0 for key in keys)


def complete(root, period, receipts, frozen):
    """Check observed, exact run completion rather than accepting old output flags."""
    tag = "-".join(value.replace("-", "") for value in period)
    report = Path(root) / "report"
    for stage in STAGES:
        receipt = receipts.get(stage)
        if (not isinstance(receipt, dict) or type(receipt.get("rc")) is not int
                or receipt["rc"] != 0 or receipt.get("safe") is not True):
            raise Uncertain(f"{stage} 완전한 응답 관찰 증거 없음")
    if not isinstance(frozen, dict) or frozen.get("ok") is not True or frozen.get("partial") is not False:
        raise Uncertain("보고서 전체 생성 증거 없음")
    if frozen.get("tag") != tag or frozen.get("errors") or not frozen.get("files"):
        raise Uncertain("보고서 기간/저장 상태 불일치")
    made = frozen.get("made")
    if (not isinstance(made, dict) or set(made) != {"word", "island", "freeze"}
            or any(not isinstance(paths, list) or len(paths) != 2 for paths in made.values())
            or sorted(p for paths in made.values() for p in paths) != sorted(frozen["files"])):
        raise Uncertain("보고서 3종 전체 저장 증거 없음")
    for filename in frozen["files"]:
        path = Path(filename).resolve()
        if not path.is_relative_to(report.resolve()) or not path.is_file():
            raise Uncertain("필수 보고서가 현재 report 경로에 없음")
    judged = _json(report / f"ai_judgments_{tag}.json")
    if not (type(judged.get("total")) is int and judged["total"] > 0
            and judged.get("judged") == judged["total"] and len(judged.get("items", {})) == judged["total"]
            and judged.get("aborted") is False and _zero(judged, ("failed_chunks", "partial_chunks", "failed_rows",
                                                          "omitted_rows", "repaired", "retries"))):
        raise Uncertain("신호 판정 누락/복구/실패 또는 완료 필드 미확인")
    refined = receipts["refine.py"].get("summary") or {}
    if refined.get("ok") is not True or not _zero(refined, ("failed_chunks", "failed_items", "repaired", "retries", "bad_rows")):
        raise Uncertain("정제의 전체 정상 완료 미확인")
    agentic = _json(report / f"agentic_{tag}.json")
    if not (agentic.get("tag") == tag and agentic.get("partial") is False
            and type(agentic.get("rows_total")) is int and agentic["rows_total"] > 0
            and agentic.get("rows_analyzed") == agentic["rows_total"]
            and _zero(agentic, ("rows_pending", "failed_chunks", "salvaged_chunks"))
            and not agentic.get("last_error")):
        raise Uncertain("Agentic 전체 정상 완료 미확인")
    flow = _json(report / f"workflow_{tag}.json")
    empty_flow = flow.get("rows_units") == 0 and flow.get("flows") == [] and bool(flow.get("empty_reason"))
    if not (flow.get("ok") is True and flow.get("tag") == tag
            and (empty_flow or (flow.get("partial") is False
                               and _zero(flow, ("missing_count", "failed_chunks", "salvaged_chunks"))))
            and not flow.get("dropped") and not flow.get("last_error")):
        raise Uncertain("워크플로우 전체 정상 완료 미확인")
    if any(type(receipts[s].get("calls")) is not int or receipts[s]["calls"] <= 0
           for s in STAGES if not (s == "flow.py" and empty_flow)):
        raise Uncertain("필수 단계의 실제 왕복 관찰 없음")
    for obj, field in ((judged, "model"), (agentic, "model_name"), (flow, "model_name")):
        if "stub" in str(obj.get(field)).lower() or (not obj.get(field) and not (obj is flow and empty_flow)):
            raise Uncertain("실제 모델 완료 정보 없음/스텁 산출물")
    # Narratives can fail independently while judge exits 0. Require every kept month.
    with open(report / f"signals_{tag}.csv", encoding="utf-8-sig", newline="") as stream:
        months = {row.get("time", "")[:7] for row in csv.DictReader(stream)}
    narratives = _json(report / f"ai_narratives_{tag}.json")
    if not months or any(not isinstance(narratives.get(month), dict)
                         or not narratives[month].get("summary") for month in months):
        raise Uncertain("월별 리뷰 완료 미확인")
    narrative_status = narratives.get("_status")
    if narrative_status is not None:
        if (not isinstance(narrative_status, dict) or narrative_status.get("schema") != 1
                or narrative_status.get("tag") != tag or narrative_status.get("partial") is not False
                or narrative_status.get("retained_months") != [] or narrative_status.get("missing_months") != []
                or not isinstance(narrative_status.get("expected_months"), list)
                or not isinstance(narrative_status.get("updated_months"), list)
                or set(narrative_status["expected_months"]) != months
                or set(narrative_status["updated_months"]) != months):
            raise Uncertain("월별 리뷰에 이전 결과 보존/누락/미완료가 있음")
    for prefix, suffix in (("mm_meta", ".json"), ("mm_rows", ".csv"), ("mm_rows", "_refined.csv"),
                           ("refine_map", ".json"), ("pivots", ".json"), ("entities", ".json"),
                           ("evidence", ".md")):
        if not (report / f"{prefix}_{tag}{suffix}").is_file():
            raise Uncertain("필수 분석 산출물 누락")


class Session:
    def __init__(self, root, period):
        self.root = Path(root).resolve()
        self.period = list(period)
        self.token = uuid.uuid4().hex
        self.path = self.root / "report" / CACHE_DIR / "complete.json"
        self.before = inputs(self.root, period)
        self.receipts = {}

    def lookup(self, now=None):
        try:
            record = _json(self.path)
            age = (now if now is not None else time.time()) - record["created"]
            if record.get("schema") != SCHEMA or record.get("root") != str(self.root):
                raise Uncertain("기존 원본 경로/캐시 버전 불일치")
            if not math.isfinite(age) or age < 0 or age > MAX_AGE or record.get("inputs") != self.before:
                raise Uncertain("입력 변경/캐시 만료")
            complete(self.root, self.period, record.get("receipts", {}), record.get("frozen"))
            if not record.get("outputs") or record["outputs"] != outputs(self.root):
                raise Uncertain("분석/보고 산출물 변경·추가·삭제")
            if inputs(self.root, self.period) != self.before:
                raise Uncertain("재사용 검증 중 입력 변경")
            return True, "동일 입력·정상 완료·산출물 내용 검증 통과"
        except (OSError, ValueError, TypeError, KeyError, AttributeError, SyntaxError) as exc:
            return False, str(exc)[:160]

    def command(self, script, args):
        path = self.path.parent / "receipts" / self.token / (script + ".json")
        self.receipts[script] = path
        return [sys.executable, str(self.root / "core" / "run_cache.py"), "--observe", script,
                str(path), *args, *(["--redo"] if script in ("agentic.py", "flow.py") else [])]

    def save(self, stages, frozen):
        try:
            required = {"업무 로드 추출", "AI 판정", "AI 정제", "Agentic 매칭", "워크플로우 분석",
                        "Agentic 실측 재계산", "보고서 생성", "팀 업로드 묶음 준비", "완료"}
            if (not stages or any(stage.get("ok") is not True for stage in stages)
                    or not required <= {stage.get("name") for stage in stages}):
                raise Uncertain("실패한 실행 단계가 있음")
            if inputs(self.root, self.period) != self.before:
                raise Uncertain("분석 중 입력/설정/별칭/과제 체계 변경 — 다음 정상 실행부터 재사용 가능")
            receipts = {stage: _json(path) for stage, path in self.receipts.items()}
            complete(self.root, self.period, receipts, frozen)
            snapshot = outputs(self.root)
            if inputs(self.root, self.period) != self.before:
                raise Uncertain("산출물 검증 중 입력 변경")
            _atomic(self.path, {"schema": SCHEMA, "root": str(self.root), "created": time.time(),
                                "inputs": self.before, "outputs": snapshot,
                                "receipts": receipts, "frozen": frozen})
            return True, "정상 완료 결과를 다음 실행 재사용용으로 기록했습니다"
        except (OSError, ValueError, TypeError, KeyError, AttributeError, SyntaxError) as exc:
            return False, str(exc)[:160]


def _agentic_reply_complete(obj, prompt):
    """Require usable entries before merge_* can silently drop/coerce them.

    Names are checked only against the supplied prompt, not for semantic truth.
    Ambiguous/truncated spellings fail closed; the original stage still receives
    its unchanged reply and remains free to apply its existing fallback behavior.
    """
    def text(value):
        return (isinstance(value, str) and bool(value.strip())
                and not (value.strip().startswith("<") and value.strip().endswith(">")))

    def key(value):
        return re.sub(r"\s*/\s*", "/", " ".join(value.split())).casefold()

    if not all(isinstance(obj.get(name), list) for name in ("match", "new", "misassigned")):
        return False
    tasks, works, rows, exact_tasks = set(), set(), set(), set()
    section = ""
    for line in prompt.splitlines():
        if line == "[계획 과제]":
            section = "tasks"
        elif line.startswith("[현재 업무 — "):
            section = "rows"
        elif section == "tasks":
            task = re.match(r"^· (\S+) \(", line)
            if task:
                tasks.add(task[1].upper())
                exact_tasks.add(task[1])
        elif section == "rows" and line.startswith("· "):
            parts = line[2:].split(" / ")
            kind = parts[2].split(" — ", 1)[0].split(" (수동 ", 1)[0] if len(parts) >= 3 else ""
            if (len(parts) >= 3 and all(parts[:2]) and kind in ("개발", "사무", "현장", "협업")
                    and (len(parts) == 3 or parts[3].startswith("신호 "))):
                # Preserve the stage's explicit source spelling; do not invent
                # links by searching the narrative or prompt examples.
                works.add(key(parts[1]))
                rows.add(key(parts[0] + "/" + parts[1]))

    def work_list(value):
        return (isinstance(value, list) and bool(value)
                and all(text(item) and (key(item) in works or key(item) in rows) for item in value))

    work_ids = set(re.findall(r"^· \[(work_[0-9a-f]{24})\] ", prompt, re.M))
    if work_ids:
        processed = obj.get("processed_ids")
        if (not isinstance(processed, list) or not all(isinstance(v, str) for v in processed)
                or len(processed) != len(set(processed)) or set(processed) != work_ids):
            return False
        for kind in ("match", "new", "misassigned"):
            for item in obj[kind]:
                if not isinstance(item, dict) or not text(item.get("reason")):
                    return False
                if kind == "misassigned":
                    if not isinstance(item.get("row_id"), str) or item["row_id"] not in work_ids:
                        return False
                    continue
                ids = item.get("work_ids")
                if (not isinstance(ids, list) or not ids or not all(isinstance(v, str) and v in work_ids for v in ids)
                        or len(ids) != len(set(ids))):
                    return False
                if kind == "match":
                    fit = item.get("fit")
                    if (not isinstance(item.get("task"), str) or item["task"] not in exact_tasks
                            or type(fit) not in (int, float) or not 1 <= fit <= 100):
                        return False
                elif not all(text(item.get(field)) for field in ("name", "logic")):
                    return False
        return True

    for item in obj["match"]:
        if not isinstance(item, dict) or not text(item.get("task")) or not text(item.get("reason")):
            return False
        fit = item.get("fit")
        if (item["task"].strip().upper() not in tasks or type(fit) not in (int, float)
                or not 1 <= fit <= 100 or not work_list(item.get("work"))):
            return False
    for item in obj["new"]:
        if (not isinstance(item, dict) or not all(text(item.get(field)) for field in ("name", "logic", "reason"))
                or not work_list(item.get("work"))):
            return False
    for item in obj["misassigned"]:
        if (not isinstance(item, dict) or not text(item.get("row")) or not text(item.get("reason"))
                or key(item["row"]) not in rows):
            return False
    return True


def inspect_reply(stage, prompt, name, result):
    """Conservative transport/schema completeness; does not assert AI truth."""
    if (not isinstance(result, dict) or result.get("ok") is not True
            or result.get("phase") != "replied" or result.get("sentinel") is not True
            or result.get("cut") or result.get("retry") or not result.get("model")
            or "stub" in str(result.get("model")).lower()):
        return False
    text = str(result.get("reply") or "").strip()
    text = re.sub(r"\s*\[\[전송끝\]\]\s*$", "", text).strip()
    try:
        obj = json.loads(text)
    except ValueError:
        return False
    if not isinstance(obj, dict):
        return False
    if stage == "judge.py":
        if name in ("taxonomy", "consolidate"):
            return (isinstance(obj.get("models"), list) and bool(obj["models"])
                    and all(isinstance(row, dict) and row.get("name") for row in obj["models"]))
        if name.startswith("narr_"):
            return bool(obj.get("summary")) and isinstance(obj.get("projects"), list)
        expected = {int(i) for i in re.findall(r"^#(\d+)\s*\|", prompt, re.M)}
        rows = obj.get("j")
        return bool(expected) and isinstance(rows, list) and all(
            isinstance(row, list) and len(row) >= 2 and type(row[0]) is int and row[1] in ("y", "n")
            and (row[1] == "n" or (len(row) >= 5 and all(isinstance(v, str) and v.strip() for v in row[2:5])
                                  and row[3] in ("개발", "사무", "현장", "협업")))
            for row in rows) and {row[0] for row in rows} == expected and len(rows) == len(expected)
    if stage == "refine.py":
        expected = {int(i) for i in re.findall(r"^\s+#(\d+)(?!\d)", prompt, re.M)}
        overlap = {int(i) for i in re.findall(r"^\s+#(\d+) \(겹침·참고\)", prompt, re.M)}
        required = expected - overlap
        items = obj.get("items")
        covered = set()
        if not expected or not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or type(item.get("w", item.get("work"))) is not bool:
                return False
            merged = item.get("m", item.get("merge"))
            if (not isinstance(merged, list) or not merged
                    or not all(type(i) is int and i in expected and i not in covered for i in merged)
                    or len(set(merged)) != len(merged)):
                return False
            if item.get("w", item.get("work")):
                for short, long in (("l1", "level1"), ("l2", "level2"), ("l3", "level3"), ("d", "detail")):
                    value = item.get(short, item.get(long))
                    if not isinstance(value, str) or not value.strip():
                        return False
                if item.get("l1", item.get("level1")) not in ("신제품개발", "기술 내재화", "양산준비", "일반업무"):
                    return False
            covered.update(merged)
        return bool(required) and required <= covered
    if stage == "agentic.py":
        return _agentic_reply_complete(obj, prompt)
    if name == "detail3":
        return isinstance(obj.get("groups"), list)
    flows = obj.get("flows")
    units, current = {}, None
    for line in prompt.splitlines():
        unit = re.search(r"^## .*\[unit_id=(unit_[0-9a-f]{24})\]", line)
        if unit:
            current = unit[1]
            units[current] = set()
        elif current:
            signal = re.match(r"^- \[(sig_[0-9a-f]{24})\]", line)
            if signal:
                units[current].add(signal[1])
    if units:
        processed = obj.get("processed_ids")
        if (not isinstance(processed, list) or not all(isinstance(v, str) for v in processed)
                or set(processed) != set(units) or len(processed) != len(set(processed))
                or not isinstance(flows, list)):
            return False
        covered = set()
        for flow in flows:
            if (not isinstance(flow, dict) or not isinstance(flow.get("unit_id"), str)
                    or flow["unit_id"] not in units or not isinstance(flow.get("steps"), list) or not flow["steps"]):
                return False
            covered.add(flow["unit_id"])
            for step in flow["steps"]:
                if not isinstance(step, dict) or step.get("agent") not in ("상", "중", "하"):
                    return False
                ids = step.get("evidence_ids")
                if (not isinstance(ids, list) or not ids or not all(isinstance(v, str) and v in units[flow["unit_id"]] for v in ids)):
                    return False
        return covered == set(units)
    return isinstance(flows, list) and all(
        isinstance(flow, dict) and isinstance(flow.get("steps"), list)
        and all(isinstance(step, dict) and step.get("agent") in ("상", "중", "하")
                for step in flow["steps"]) for flow in flows)


class _Tee:
    def __init__(self, stream):
        self.stream, self.pending, self.summary = stream, "", {}
        self.warning = False

    def write(self, text):
        result = self.stream.write(text)
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if re.search(r"\[!\]|실패|예외|오류|건너뜀|미반영", line.replace("실패 아님", "")):
                self.warning = True
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    self.summary = value
            except ValueError:
                pass
        return result

    def __getattr__(self, name):
        return getattr(self.stream, name)


def observe_stage(root, script, receipt, args):
    """Child-only observer: call/return values and exception behavior are unchanged."""
    root = Path(root).resolve()
    receipt = Path(receipt).resolve()
    if script not in STAGES or not receipt.is_relative_to(root / "report" / CACHE_DIR / "receipts"):
        raise ValueError("허용되지 않은 단계 관찰 경로")
    sys.path[:0] = [str(root), str(root / "core")]
    sys.argv = [str(root / script), *args]
    judge = importlib.import_module("judge")
    original = judge.copilot_send
    audit = {"safe": True, "calls": 0, "rc": 1, "summary": {}}

    def observed(prompt, tag, name, fresh=None):
        result = original(prompt, tag, name, fresh=fresh)
        audit["calls"] += 1
        try:
            audit["safe"] = audit["safe"] and inspect_reply(script, prompt, name, result)
        except (TypeError, ValueError, KeyError):
            audit["safe"] = False
        return result

    judge.copilot_send = observed
    previous_stdout = sys.stdout
    tee = _Tee(previous_stdout)
    sys.stdout = tee
    try:
        module = judge if script == "judge.py" else importlib.import_module(script[:-3])
        rc = module.main()
        audit["rc"] = rc if isinstance(rc, int) else 0
        return rc
    finally:
        sys.stdout = previous_stdout
        judge.copilot_send = original
        audit["summary"] = tee.summary
        if tee.warning:
            audit["safe"] = False
        if script != "flow.py" and audit["calls"] == 0:
            audit["safe"] = False
        try:
            _atomic(receipt, audit)
        except OSError:
            pass  # Missing receipt prevents reuse; never alter the stage's result.


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "--observe":
        raise SystemExit("단계 관찰기는 run.py의 완료 결과 재사용 옵션에서만 실행합니다")
    raise SystemExit(observe_stage(Path(__file__).resolve().parents[1], sys.argv[2], sys.argv[3], sys.argv[4:]))
