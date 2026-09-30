"""Observed communication evidence, distinct from collection completion and hours.

This module reads saved CSVs only. Public reports contain counts and fixed labels,
never subjects, bodies, participants, account identifiers or local file paths.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

from collection_state import latest_original_rows, read_csv, record_key

SCHEMA = 1
POLICY = ("수집된 자료에서 관측한 단서만 분석합니다. 건수는 업무 전체 확보율·업무시간이 아닙니다. "
          "근거 ID 연결은 서술의 사실 검증이 아닙니다. 본문·첨부·대화 앞뒤·역할·성과가 없으면 판단을 유보하고, "
          "AI 해석·자동화 제안을 확인된 원문 사실과 구분하세요. 자료 부족을 무업무·0시간으로 해석하지 마세요.")
ROUTES = {"outlook_com", "outlook_index", "outlook_web", "outlook_copilot", "outlook_graph", "outlook_files", "outlook_msg", "teams_app", "teams_graph",
          "teams_web", "teams_copilot", "import_eml", "import_mbox", "import_csv", "import_json", "communication_import", "mail-import",
          "teams-graph-import", "teams-normalized-import", "mail-normalized-import"}
UNCERTAIN_TIME = {"estimated", "ai_reported", "unknown"}


def _true(value):
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _text(value):
    return " ".join(str(value or "").split())


def usable_context(row, config=None):
    """Respect the downstream privacy flag even if a stale body is still present."""
    if _true(row.get("context_filtered")):
        return ""
    body = _text(row.get("context_excerpt"))
    excluded = (config or {}).get("excludePathKeywords") or []
    if any(str(word).strip().lower() in body.lower() for word in excluded if str(word).strip()):
        return ""
    return body


def unit_readiness(signals):
    """Assess available context, never semantic truth or total work coverage.

    Communication titles alone cannot establish a process. Concrete file/commit/
    manual evidence remains usable even when mail is unavailable.
    """
    rows = list(signals or [])
    communication = [r for r in rows if str(r.get("source") or "").startswith(("메일", "팀즈"))]
    contexts = sum(bool(usable_context(r)) for r in communication)
    direct_contexts = sum(bool(usable_context(r)) and "copilot" not in str(r.get("source_kind") or "").lower()
                          and str(r.get("time_precision") or "").lower() != "ai_reported"
                          and str(r.get("source") or "") != "메일(방향미확인)" for r in communication)
    artifacts = [r for r in rows if str(r.get("source") or "").startswith(("파일", "커밋", "수동기록"))
                 and str(r.get("source")) not in {"파일(일괄)", "파일(타인)", "파일(열람)", "파일(해석출력)"}
                 and _text(r.get("text"))]
    supported = bool(direct_contexts or artifacts)
    return {"schema": SCHEMA, "status": "context_available" if supported else ("limited" if rows else "unavailable"),
            "signals": len(rows), "communication_rows": len(communication), "context_rows": contexts,
            "direct_context_rows": direct_contexts,
            "artifact_rows": len(artifacts), "allows_interpretation": supported,
            "sufficiency": "unknown", "fact_verified": False,
            "limits": ([] if supported else ["업무 흐름을 설명할 본문·산출물 근거 부족"])
                      + ["관측된 일부 근거이며 업무 전체·서술 사실의 검증을 뜻하지 않음"]}


def readiness_notice(readiness):
    item = readiness or {}
    return (f"근거 상태: {item.get('status', 'unknown')} · 관측 신호 {item.get('signals', 0)}건 · "
            f"대화 본문 {item.get('context_rows', 0)}건 · 산출물/수동 근거 {item.get('artifact_rows', 0)}건. "
            "업무 전체의 충분성은 미확인; 서술은 AI 해석입니다."
            + (" 근거 부족: 과정·역할·완료를 확정하지 마세요." if not item.get("allows_interpretation") else ""))


def evidence_line(row, limit=400):
    """A bounded local signal excerpt; never used in the public counts report."""
    base = _text(row.get("text") or row.get("subject") or row.get("summary"))[:100]
    body = usable_context(row)
    note = "본문 일부 발췌" if body else ("문맥 제외(보호 필터)" if _true(row.get("context_filtered")) else "본문 미수집")
    source = str(row.get("source") or "")
    if not source.startswith(("메일", "팀즈")) and not body:
        return base[:limit]
    # Budget includes labels and crop markers, rather than only body characters.
    prefix = base + " | " + note + ": "
    available = max(0, limit - len(prefix) - 8)
    excerpt = body[:available]
    if len(body) > available >= 18:
        size = (available - 6) // 3
        middle = max(size, len(body) // 2 - size // 2)
        excerpt = body[:size] + " … " + body[middle:middle + size] + " … " + body[-(available - 6 - 2 * size):]
    return (prefix + excerpt + (" [발췌]" if len(body) > available or _true(row.get("context_truncated")) else ""))[:limit]


def _day(value, offset=0):
    try:
        raw = str(value or "").strip()
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (dt + timedelta(hours=offset)).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _identity(row, family):
    account = _text(row.get("account"))
    conversation = _text(row.get("conversation_id") or row.get("conversation") or row.get("chat"))
    if row.get("source_id"):
        values = [family, account, conversation, _text(row["source_id"])]
    else:
        values = [family, account, conversation, _text(row.get("time")), _text(row.get("box") or row.get("kind")),
                  _text(row.get("sender") or row.get("from")), _text(row.get("source_kind")),
                  _text(row.get("subject") or row.get("summary")),
                  _text(row.get("context_excerpt"))]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def _roots(root):
    data = Path(root) / "data"
    extra = data / "추가PC"
    return [data, *sorted(p for p in extra.iterdir() if p.is_dir())] if extra.is_dir() else [data]


def _pending_counts(root, family, d0, d1, collected=()):
    """Count undated originals separately; they establish no in-period evidence."""
    filename = "outlook_web_undated.csv" if family == "mail" else "teams_web_undated.csv"
    # A precise original on another PC can resolve a stale pending copy. Do not
    # infer identity from a title/body or resolve it with another uncertain row.
    resolved = {(record_key(row, family), _text(row.get("source_kind"))) for row in collected
                if row.get("source_id") and _text(row.get("source_kind"))
                and _text(row.get("time_precision")).lower() in {"second", "minute"}
                and re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", str(row.get("time") or ""))
                and _day(row.get("time")) is not None}
    seen, unreadable = set(), 0
    for data in _roots(root):
        path = data / "collection_pending" / filename
        if not path.is_file():
            continue
        try:
            rows = read_csv(path)
            required = {"time", "time_precision", "requested_from", "requested_to"}
            if any(not required.issubset(row) for row in rows):
                raise ValueError("Invalid pending observation schema")
            for row in rows:
                if ([row.get("requested_from"), row.get("requested_to")] == [str(d0), str(d1)]
                        and not _text(row.get("time"))
                        and _text(row.get("time_precision")).lower() == "unknown"):
                    if row.get("source_id") and (record_key(row, family), _text(row.get("source_kind"))) in resolved:
                        continue
                    seen.add(record_key(row, family))
        except (OSError, UnicodeError, csv.Error, ValueError):
            # A damaged file's period is unknowable; only the file count is exposed.
            unreadable += 1
    return len(seen), unreadable


def _current_states(root, d0, d1, current_run=None):
    """Use same-period receipts from the current run, including unsaved failures."""
    if current_run is None:
        try:
            current_run = json.loads((Path(root) / "report/last_run.json").read_text("utf-8-sig"))
        except (OSError, ValueError, UnicodeError):
            return []
    if not isinstance(current_run, dict) or current_run.get("period") != [str(d0), str(d1)]:
        return []
    started = current_run.get("started_at")
    if type(started) not in {int, float} or not math.isfinite(started) or started <= 0:
        return []
    collection = current_run.get("collection")
    if not isinstance(collection, dict):
        return []
    states = []
    for family in collection.values():
        rows = family.get("sources") if isinstance(family, dict) else None
        if not isinstance(rows, list):
            continue
        for item in rows:
            if (not isinstance(item, dict) or not isinstance(item.get("source"), str)
                    or item["source"] not in ROUTES):
                continue
            finished = item.get("finished_at")
            if ([item.get("requested_from"), item.get("requested_to")] == [str(d0), str(d1)]
                    and type(finished) in {int, float} and math.isfinite(finished) and finished >= started):
                states.append(item)
    return states


def _scope(root, family, d0, d1, current_states=()):
    observed = {}
    directory = Path(root) / "data" / "collection_status"
    for path in sorted(directory.glob("*.json")):
        try:
            item = json.loads(path.read_text("utf-8-sig"))
            if (isinstance(item, dict) and isinstance(item.get("source"), str)
                    and [item.get("requested_from"), item.get("requested_to")] == [str(d0), str(d1)]):
                observed[item["source"]] = item
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    for item in current_states:
        previous = observed.get(item["source"], {})
        stamp = previous.get("finished_at")
        if type(stamp) in {int, float} and math.isfinite(stamp) and stamp > item["finished_at"]:
            continue  # A later standalone collection takes precedence over last_run.
        observed[item["source"]] = item
    states = []
    for item in observed.values():
        try:
            source = item.get("source", "")
            if source not in ROUTES or not (source.startswith("outlook_" if family == "mail" else "teams_")
                                            or (source == "communication_import" and item.get(family + "_status") != "skipped"
                                                and (family == "mail" or family + "_status" in item))):
                continue
            if [item.get("requested_from"), item.get("requested_to")] != [str(d0), str(d1)]:
                continue
            status = item.get("mail_status", item.get("status")) if family == "mail" else item.get("teams_status", item.get("status"))
            if item.get("status") in {"failed", "blocked", "skipped"}:
                status = item["status"]
            if source in {"communication_import", "outlook_files"}:
                status = "partial"  # Import completion proves only the selected files, not the mailbox/chat scope.
            if item.get("server_scope_verified") is False or item.get("server_coverage_verified") is False:
                status = "partial"
            if item.get("process_ok") is False or not item.get("scope"):
                status = "partial"
            states.append({"source": source, "status": status if status in {"complete", "partial", "failed", "blocked", "skipped"} else "unknown"})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    coverage = "scoped_complete" if any(s["status"] == "complete" for s in states) else ("partial" if states else "unknown")
    return coverage, states


def build_report(root, d0, d1, config=None, current_run=None):
    """Read saved communication CSVs for one exact period; never starts a collector."""
    d0, d1 = date.fromisoformat(str(d0)), date.fromisoformat(str(d1))
    if d1 < d0:
        raise ValueError("시작일이 종료일보다 늦습니다")
    config = config or {}
    current_states = _current_states(root, d0, d1, current_run)
    try:
        offset = float((config.get("mm") or {}).get("mailTimeOffsetH") or 0)
        if not -24 <= offset <= 24:
            offset = 0
    except (TypeError, ValueError):
        offset = 0
    families = {}
    for family in ("mail", "teams"):
        item = dict.fromkeys(("raw_rows", "in_period_rows", "unique_rows", "context_rows", "context_truncated_rows",
                              "context_filtered_rows", "dated_rows", "unknown_date_rows", "conversation_count", "files", "unreadable_files", "ai_reported_rows"), 0)
        seen, conversations, kinds, days = {}, set(), set(), set()
        collected = []
        for data in _roots(root):
            paths = [data / "outlook" / "mail.csv"] if family == "mail" else sorted((data / "m365").glob("teams_*.csv"))
            for path in paths:
                if not path.is_file():
                    continue
                item["files"] += 1
                try:
                    collected.extend(read_csv(path))
                except (OSError, UnicodeError, csv.Error, ValueError):
                    item["unreadable_files"] += 1
        item["raw_rows"] = len(collected)
        originals = latest_original_rows(collected, family)
        item["pending_rows"], item["pending_unreadable_files"] = _pending_counts(root, family, d0, d1, originals)
        for row in originals:
            # The legacy mailTimeOffsetH setting also adjusts Teams
            # in extract.load_signals. Saved-evidence counts must use
            # the same date boundary as the analysis they describe.
            day = _day(row.get("time"), offset)
            uncertain = str(row.get("time_precision") or "").lower() in UNCERTAIN_TIME
            if day is None:
                item["unknown_date_rows"] += 1
                continue
            if not d0 <= day <= d1:
                continue
            item["in_period_rows"] += 1
            if uncertain:
                item["unknown_date_rows"] += 1
            key = _identity(row, family)
            # A duplicate metadata-only row cannot erase a richer observation.
            if key not in seen or len(usable_context(row, config)) > len(usable_context(seen[key], config)):
                seen[key] = row
            days.add(str(day))
        for row in seen.values():
            body = usable_context(row, config)
            item["context_rows"] += bool(body)
            item["context_truncated_rows"] += _true(row.get("context_truncated"))
            item["context_filtered_rows"] += _true(row.get("context_filtered")) or bool(row.get("context_excerpt") and not body)
            item["dated_rows"] += str(row.get("time_precision") or "").lower() not in UNCERTAIN_TIME
            conversation = _text(row.get("conversation_id") or row.get("conversation") or row.get("chat"))
            if conversation:
                conversations.add((_text(row.get("account")), conversation))
            source = str(row.get("source_kind") or "legacy")
            item["ai_reported_rows"] += "copilot" in source.lower() or str(row.get("time_precision") or "").lower() == "ai_reported"
            kinds.add(source if source in ROUTES else ("import" if source.startswith("import") else "legacy_or_other"))
        item.update(unique_rows=len(seen), conversation_count=len(conversations), source_kinds=sorted(kinds),
                    observed_days=len(days), source_coverage_ratio=None,
                    context_ratio=round(item["context_rows"] / len(seen), 4) if seen else None)
        item["scope_status"], item["source_statuses"] = _scope(root, family, d0, d1, current_states)
        item["status"] = "unavailable" if not seen else ("observed" if item["context_rows"] else "limited")
        item["limits"] = ["전체 원본 건수 미확인: 확보율 산출 불가", "본문 비율은 저장된 기간 내 고유행 기준; 전체 대화·첨부 확보율 아님"]
        if not seen:
            item["limits"].append("이 기간에 활용할 저장 신호 없음; 실제 업무가 없었다는 뜻 아님")
        elif not item["context_rows"]:
            item["limits"].append("제목·요약 단서만 있어 과정·역할·성과 이해 제한")
        if item["scope_status"] != "scoped_complete":
            item["limits"].append("요청 범위 완주 미확인")
        if item["unknown_date_rows"]:
            item["limits"].append("날짜 미확인·추정 자료 존재")
        if item["pending_rows"]:
            item["limits"].append("날짜 확인 대기 원문 존재: 기간 내 건수·본문·AI 분석에서 제외")
        if item["pending_unreadable_files"]:
            item["limits"].append("읽지 못한 날짜 확인 대기 파일 존재: 해당 파일의 기간도 미확인")
        if item["unreadable_files"]:
            item["limits"].append("읽지 못한 저장 파일 존재")
        if item["ai_reported_rows"]:
            item["limits"].append("AI 조회·요약 자료 존재: 원문 확인 전 확정 근거 아님")
        item["actions"] = (["수집 경로·계정·요청 기간 확인", "사용자가 선택한 원본 내보내기 자료 가져오기"]
                           if not seen or not item["context_rows"] else ["중요 업무의 앞뒤 대화·원문을 추가 확인"])
        families[family] = item
    status = "unavailable" if not any(f["unique_rows"] for f in families.values()) else "limited"
    if all(f["context_rows"] and f["scope_status"] == "scoped_complete" for f in families.values()):
        status = "observed"
    return {"schema": SCHEMA, "period": [str(d0), str(d1)], "status": status, "families": families,
            "limits": ["수집 실행 완료·관측 건수·본문 확보·업무 이해의 충분성은 서로 다름", "업무 전체 충분성 미확인"],
            "actions": list(dict.fromkeys(a for f in families.values() for a in f["actions"])),
            "note": POLICY, "mm_effect": "none"}


def write_report(root, d0, d1, config=None, report=None, current_run=None):
    result = report if report is not None else build_report(root, d0, d1, config, current_run=current_run)
    tag = str(d0).replace("-", "") + "-" + str(d1).replace("-", "")
    if not re.fullmatch(r"\d{8}-\d{8}", tag) or result.get("period") != [str(d0), str(d1)]:
        raise ValueError("근거 보고서 기간 불일치")
    target = Path(root) / "report" / f"communication_evidence_{tag}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return result


def prompt_notice(report=None):
    if not report:
        return POLICY
    counts = " · ".join(f"{name}: 기간 내 {item.get('unique_rows', 0)}건/본문 {item.get('context_rows', 0)}건"
                        for name, item in (report.get("families") or {}).items())
    return POLICY + (" 관측 범위: " + counts if counts else "")
