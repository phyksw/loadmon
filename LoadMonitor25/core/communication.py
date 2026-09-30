"""Supplement communication collection using explicit coverage, never row count.

Only invokes the caller's runner; tests inject that runner and use synthetic files.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import time

from collection_state import load_status, write_status


def _number(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


class CommunicationCollection:
    def __init__(self, root, config, d0, d1, step, record, argv=None, executable=None, ps=None):
        self.root = Path(root)
        self.config = config
        self.options = config.get("collection") or {}
        self.d0, self.d1 = str(d0), str(d1)
        self.step, self.record = step, record
        self.argv = sys.argv if argv is None else argv
        self.python = executable or sys.executable
        self.ps = ps or ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
        self.headless = ("--collect-only" in self.argv and config.get("collectOnlyHeadless", True)
                         and "--interactive-collect" not in self.argv)
        self.col = self.root / "collect"
        self.states = []

    def skip(self, source, reason):
        result = write_status(self.root, source, self.d0, self.d1, "skipped", reasons=[reason])
        self.states.append(result)
        self.record("수집 경로 · " + source, True, 0, "생략: " + reason)
        return result

    def run(self, source, label, command, timeout):
        started = time.time()
        ok = self.step(label, command, timeout)
        result = load_status(self.root, source, self.d0, self.d1, since=started)
        if result is None:
            result = write_status(
                self.root, source, self.d0, self.d1, "partial" if ok else "failed",
                reasons=["collector_did_not_report_scope" if ok else "collector_failed_or_timed_out"],
                process_ok=bool(ok))
        elif not ok:
            result = self.interrupted(result)
        self.states.append(result)
        return result

    def interrupted(self, result):
        """Reject completion after a bad exit while preserving the reported failure."""
        extras = {k: v for k, v in result.items() if k not in {
            "schema", "source", "requested_from", "requested_to", "status", "rows",
            "scope", "reasons", "finished_at"}}
        for field in ("mail_status", "calendar_status"):
            if extras.get(field) == "complete":
                extras[field] = "partial"
        extras["process_ok"] = False
        status = result["status"] if result["status"] in {"failed", "blocked", "skipped"} else "partial"
        return write_status(self.root, result["source"], self.d0, self.d1, status,
                            result.get("rows", 0), result.get("scope", ""),
                            [*result.get("reasons", []), "process_did_not_finish"], **extras)

    def report(self, family, complete, reasons=()):
        summary = "범위 확인 완료" if complete else "부분 수집 · 전체 범위 확인 안 됨"
        if reasons:
            summary += " · " + ", ".join(reasons)
        self.record(f"{family} 수집 범위", complete, 0, summary)
        return {"family": family, "status": "complete" if complete else "partial",
                "period": [self.d0, self.d1], "sources": self.states,
                "note": summary}

    def mail(self, since, process_ok=True):
        """COM has already run. Missing/zero/partial output still needs evidence."""
        pending = {"mail", "cal"}
        initial = load_status(self.root, "outlook_com", self.d0, self.d1, since=since)
        if initial and not process_ok:
            initial = self.interrupted(initial)
        if initial:
            self.states.append(initial)

        def consume(state):
            if not state:
                return
            for kind, field in (("mail", "mail_status"), ("cal", "calendar_status")):
                # A locally cached store can finish enumerating while older
                # server messages have never synchronized to this PC.
                if kind == "mail" and state.get("source") != "outlook_graph":
                    continue
                if state.get("status") not in {"failed", "blocked", "skipped"} and state.get("scope") and state.get(field) == "complete":
                    pending.discard(kind)

        consume(initial)
        budget = _number(self.options.get("supplementBudgetSec"), 2400, 60, 14400)
        deadline = time.monotonic() + budget
        months = max(1, (date.fromisoformat(self.d1) - date.fromisoformat(self.d0)).days // 30 + 1)
        routes = [
            ("outlook_graph", "Outlook 원문 · Graph 전체 사서함 페이지", "Get-OutlookGraph.py",
             _number(self.options.get("graphBudgetSec"), 900, 30, 6900) + 90,
             bool((self.config.get("graph") or {}).get("clientId"))),
            ("outlook_index", "Outlook 보충 · Windows Search 색인", "Get-OutlookIndex.ps1", 240, True),
            ("outlook_web", "Outlook 보충 · 웹", "Get-OutlookWeb.py", 180 + 150 * months,
             not self.headless and self.config.get("mailViaWeb", True) and "--no-mail-web" not in self.argv),
            ("outlook_copilot", "Outlook 보충 · Copilot 조회", "Get-MailViaCopilot.py", 300 + 600 * months * 2,
             not self.headless and self.config.get("mailViaCopilot", True) and "--no-mail-copilot" not in self.argv),
        ]
        for source, label, file, timeout, enabled in routes:
            if not pending:
                self.skip(source, "앞 경로가 명시한 요청 범위를 완료함")
                continue
            if not enabled:
                self.skip(source, "Graph 앱 연결 미설정" if source == "outlook_graph" else
                          "수집만 모드에서 창 생략" if self.headless else "설정 또는 실행 옵션에서 비활성")
                continue
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                self.skip(source, "보충 수집 시간 예산 도달 · 다음 실행 필요")
                continue
            if file.endswith(".ps1"):
                command = self.ps + [str(self.col / file), "-From", self.d0, "-To", self.d1, "-Force"]
                only_flag = "-Only"
            else:
                command = [self.python, str(self.col / file), "--from", self.d0, "--to", self.d1, "--force"]
                only_flag = "--only"
            if source == "outlook_graph":
                if "mail" not in pending:
                    self.skip(source, "메일 요청 범위 완료")
                    continue
                command += ["--non-interactive", "--time-budget", str(max(1, min(timeout, remaining) - 90))]
                # Force is a web refresh option; Graph must retain resumable cursors.
                command.remove("--force")
            elif len(pending) == 1:
                command += [only_flag, next(iter(pending))]
            if source == "outlook_web" and "--mail-web-body" in self.argv:
                command.append("--include-body")
            consume(self.run(source, label, command, min(timeout, remaining)))
        return self.report("Outlook", not pending,
                           [f"미확인: {', '.join(sorted(pending))}"] if pending else [])

    def teams(self):
        if "--no-teams" in self.argv:
            for source in ("teams_app", "teams_graph", "teams_web", "teams_copilot"):
                self.skip(source, "--no-teams")
            return {"family": "Teams", "status": "skipped", "period": [self.d0, self.d1], "sources": self.states}
        budget = _number(self.options.get("teamsBudgetSec"), 2400, 120, 14400)
        deadline = time.monotonic() + budget
        graph = bool((self.config.get("graph") or {}).get("clientId"))
        web = self.config.get("teamsWeb", True) and not self.headless
        copilot = (self.config.get("teamsViaCopilot", False) and not self.headless
                   and "--no-teams-copilot" not in self.argv)
        app = ("teams_app", "Teams 보충 · 열린 앱", self.ps + [str(self.col / "Get-TeamsWindow.ps1"),
               "-From", self.d0, "-To", self.d1], 120, True)
        routes = [
            ("teams_graph", "Teams 수집 · Graph", [self.python, str(self.col / "Get-TeamsChats.py"),
             "--from", self.d0, "--to", self.d1, "--non-interactive"],
             _number(self.options.get("graphBudgetSec"), 900, 30, 6900) + 90, graph),
            ("teams_web", "Teams 보충 · 웹", [self.python, str(self.col / "Get-TeamsWeb.py"),
             "--from", self.d0, "--to", self.d1, "--force"], 1200, web),
        ]
        if self.config.get("preferApp", True) and not graph:
            routes.insert(0, app)
        else:
            routes.append(app)
        routes.append(("teams_copilot", "Teams 보충 · Copilot 조회",
                       [self.python, str(self.col / "Get-TeamsViaCopilot.py"), "--from", self.d0,
                        "--to", self.d1, "--force"], 900, copilot))
        complete = False
        for source, label, command, timeout, enabled in routes:
            if complete:
                self.skip(source, "앞 경로가 명시한 요청 범위를 완료함")
                continue
            if not enabled:
                reason = "Graph 앱 연결 미설정" if source == "teams_graph" else (
                    "수집만 모드에서 창 생략" if self.headless else "설정에서 비활성")
                self.skip(source, reason)
                continue
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                self.skip(source, "수집 시간 예산 도달 · 다음 실행 필요")
                continue
            if source == "teams_web":
                web_budget = _number(self.config.get("teamsWebBudgetSec"), 900, 30, 6900)
                command += ["--budget", str(max(1, min(web_budget, remaining - 20)))]
            elif source == "teams_graph":
                command += ["--time-budget", str(max(1, min(timeout, remaining) - 90))]
            state = self.run(source, label, command, min(timeout, remaining))
            # App/UI/Copilot cannot certify the server's entire accessible chat list.
            complete = (source == "teams_graph" and state.get("status") == "complete"
                        and state.get("full_requested_scope_complete") is True)
        return self.report("Teams", complete, [] if complete else ["앱·웹 탐색 범위 및 중단 사유 확인"])


def collect_mail(root, config, d0, d1, step, record, since, process_ok=True, **kwargs):
    return CommunicationCollection(root, config, d0, d1, step, record, **kwargs).mail(since, process_ok)


def collect_teams(root, config, d0, d1, step, record, **kwargs):
    return CommunicationCollection(root, config, d0, d1, step, record, **kwargs).teams()
