# -*- coding: utf-8 -*-
"""WP-14 pc.events 수집기 시험 — collect\\Get-EventActivity.ps1 을 %TEMP% 복제 트리에서 시험 주입(-EventsCsv -Now -BootTime -OutDir,
계약 §11.3)으로만 돌린다(실제 이벤트 로그를 읽지 않는다).

CP §4 · 계약 X-077(이벤트 ID → event_class·layer) · X-078(event-cap 폐지 — 20시간 절단 없음) · X-317(채널 상태 열거) ·
X-300(stdin _in·마지막 줄 _cursor) · §8.1 rc · P-T31(금지 원시 필드 없음) · CP-5(롤오버 뒤 재수확 — 커서 이후만, 이전 구간 불변).
"""
import json
import os
import unittest
from datetime import UTC, datetime

from tests.fixtures.synth.inject import events_args, write_events_csv
from tests.fixtures.synth.month import plan_period
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp14.runner import FORBIDDEN_RAW, run_ps, snapshot

SCRIPT = "Get-EventActivity.ps1"
RAW_KEYS = {"event_class", "session_state", "layer", "ts_utc", "ts_end", "ts_local_offset", "ts_precision", "observed_at",
            "confidence", "flags"}
EVENT_CLASSES = {"boot", "shutdown", "sleep", "wake", "logon", "logoff", "lock", "unlock", "rdp_connect",
                 "rdp_disconnect", "crash"}


def utc(local: str) -> str:
    """로컬 'YYYY-MM-DD HH:MM' → 'YYYY-MM-DDTHH:MM:SSZ'(이 PC 시간대 — 수집기와 같은 변환)."""
    return datetime.strptime(local, "%Y-%m-%d %H:%M").astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventsTest(CloneTestCase):
    def csv(self, name: str, rows) -> str:
        p = self.clone.temp / "wp14_events" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = ["t,kind,src"] + [f"{t},{k},{s}" for t, k, s in rows]
        p.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
        return str(p)

    def run_ev(self, csv, *, now, boot=None, since="2026-09-01", until="2026-09-30", cursor=None, cfg=None, extra=()):
        args = ["-EventsCsv", csv, "-Now", now, "-Since", since, "-Until", until, *extra]
        if boot:
            args += ["-BootTime", boot]
        r = run_ps(self.clone, SCRIPT, args, cfg=cfg if cfg is not None else {}, cursor=cursor)
        self.assertIsNotNone(r.status, r.err())
        self.assertEqual(r.controls[-1].keys(), {"_cursor"}, "마지막 줄은 _cursor")
        for rec in r.records:
            self.assertTrue(set(rec) <= RAW_KEYS, set(rec) - RAW_KEYS)
            self.assertFalse(set(rec) & FORBIDDEN_RAW)
            self.assertIn(rec["event_class"], EVENT_CLASSES)
            self.assertIn(rec["layer"], ("L0", "L1"))
            self.assertEqual(rec["ts_precision"], "minute")
            self.assertLess(rec["ts_utc"], rec["ts_end"])
        return r

    def spans(self, r):
        return [(x["event_class"], x["layer"], x["ts_utc"], x["ts_end"], x["flags"]["end_uncertain"]) for x in r.records]

    # ── 기본 구간화 ──────────────────────────────────────────────────────
    def test_basic_day_power_and_session(self):
        rows = [("2026-09-01 08:50", "on", "6005"), ("2026-09-01 08:52", "on", "7001"), ("2026-09-01 12:00", "off", "42"),
                ("2026-09-01 13:00", "on", "1"), ("2026-09-01 18:08", "off", "7002"), ("2026-09-01 18:10", "off", "6006")]
        r = self.run_ev(self.csv("basic.csv", rows), now="2026-09-02 09:00")
        self.assertEqual(r.rc, 0, r.status)
        self.assertEqual(self.spans(r), [
            ("boot", "L0", utc("2026-09-01 08:50"), utc("2026-09-01 12:00"), False),
            ("logon", "L1", utc("2026-09-01 08:52"), utc("2026-09-01 18:08"), False),
            ("wake", "L0", utc("2026-09-01 13:00"), utc("2026-09-01 18:10"), False),
        ])
        for x in r.records:
            self.assertEqual(x["confidence"], 1.0)
            self.assertEqual(x["session_state"], "active")
            self.assertRegex(x["ts_local_offset"], r"^[+-](?:0\d|1[0-4]):[0-5]\d$")
            self.assertEqual(x["observed_at"], utc("2026-09-02 09:00"))
        self.assertEqual(r.cursor, {"last_ts_utc": utc("2026-09-01 18:10")})
        self.assertEqual(r.status["rc"], 0)
        self.assertEqual(r.status["channels"], {"synthetic": "ok"})
        self.assertEqual(r.status["spans"], {"L0": 2, "L1": 1})

    def test_event_id_mapping_x077(self):
        days = [("6005", "6006", "boot"), ("12", "13", "boot"), ("100", "200", "boot"), ("1", "42", "wake"),
                ("107", "506", "wake"), ("507", "1074", "wake"), ("7001", "7002", "logon"), ("21", "23", "logon"),
                ("25", "24", "rdp_connect"), ("4801", "4800", "unlock")]
        rows = []
        for i, (on, off, _cls) in enumerate(days):
            d = f"2026-09-{i + 2:02d}"
            rows += [(f"{d} 09:00", "on", on), (f"{d} 10:00", "off", off)]
        rows += [("2026-09-20 09:00", "off", "6008"), ("2026-09-20 09:01", "off", "41")]    # crash 는 구간을 만들지 않는다
        r = self.run_ev(self.csv("map.csv", rows), now="2026-09-21 12:00")
        got = [(x["event_class"], x["layer"], x["flags"]["remote"], x["session_state"]) for x in r.records]
        exp = []
        for _on, _off, cls in days:
            layer = "L0" if cls in ("boot", "wake") else "L1"
            remote = cls == "rdp_connect"
            exp.append((cls, layer, remote, "remote" if remote else "active"))
        self.assertEqual(got, exp)
        self.assertEqual(r.status["events"], len(rows))

    def test_boot_gap_closes_with_end_uncertain_no_20h_cap(self):
        rows = [("2026-09-02 08:40", "on", "6005"), ("2026-09-02 08:41", "on", "7001"),
                ("2026-09-04 09:00", "on", "6005"), ("2026-09-04 09:10", "off", "6006")]
        r = self.run_ev(self.csv("gap.csv", rows), now="2026-09-05 12:00")
        first = r.records[0]
        self.assertEqual(first["ts_end"], utc("2026-09-04 09:00"))                     # 다음 부팅에서 닫힘(48시간 — 절단 없음)
        self.assertTrue(first["flags"]["end_uncertain"])
        self.assertEqual(first["confidence"], 0.4)
        l1 = [x for x in r.records if x["layer"] == "L1"]
        self.assertEqual(len(l1), 1)
        self.assertEqual(l1[0]["ts_end"], utc("2026-09-04 09:00"))                     # 세션은 재부팅을 넘지 않는다
        self.assertTrue(l1[0]["flags"]["end_uncertain"])
        self.assertEqual(r.records[-1]["ts_end"], utc("2026-09-04 09:10"))
        self.assertFalse(r.records[-1]["flags"]["end_uncertain"])

    def test_boot_cluster_within_30min_is_one_boot(self):
        rows = [("2026-09-03 08:00", "on", "12"), ("2026-09-03 08:02", "on", "6005"), ("2026-09-03 08:20", "on", "100"),
                ("2026-09-03 17:00", "off", "13")]
        r = self.run_ev(self.csv("cluster.csv", rows), now="2026-09-04 12:00")
        self.assertEqual(self.spans(r), [("boot", "L0", utc("2026-09-03 08:00"), utc("2026-09-03 17:00"), False)])

    def test_unpaired_without_boot_time_is_uncertain_until_now(self):
        rows = [("2026-09-05 09:00", "on", "6005")]
        r = self.run_ev(self.csv("unpaired.csv", rows), now="2026-09-05 15:00")
        self.assertEqual(self.spans(r), [("boot", "L0", utc("2026-09-05 09:00"), utc("2026-09-05 15:00"), True)])
        self.assertEqual(r.records[0]["confidence"], 0.4)
        self.assertEqual(r.cursor, {"last_ts_utc": utc("2026-09-05 09:00")})          # 열린 구간 시작에서 다시 읽는다
        self.assertFalse(r.status["live"])

    def test_live_session_with_boot_time(self):
        rows = [("2026-09-05 09:00", "on", "6005"), ("2026-09-05 09:03", "on", "7001")]
        r = self.run_ev(self.csv("live.csv", rows), now="2026-09-05 15:00", boot="2026-09-05 09:00")
        self.assertEqual(self.spans(r), [("boot", "L0", utc("2026-09-05 09:00"), utc("2026-09-05 15:00"), False),
                                         ("logon", "L1", utc("2026-09-05 09:03"), utc("2026-09-05 15:00"), False)])
        self.assertTrue(r.status["live"])
        self.assertEqual(r.cursor, {"last_ts_utc": utc("2026-09-05 09:00")})

    def test_always_on_flag(self):
        rows = [("2026-09-01 09:00", "on", "6005"), ("2026-09-03 09:00", "on", "6005"), ("2026-09-03 09:05", "on", "7001"),
                ("2026-09-03 18:00", "off", "7002")]
        r = self.run_ev(self.csv("always.csv", rows), now="2026-09-04 09:00", boot="2026-09-03 09:00")
        self.assertTrue(r.status["always_on"])
        for x in r.records:
            self.assertEqual(x["flags"]["always_on"], x["layer"] == "L0")

    def test_fallback_boot_when_no_events(self):
        r = self.run_ev(self.csv("empty.csv", []), now="2026-09-05 15:00", boot="2026-09-05 08:30")
        self.assertEqual(r.rc, 0)
        self.assertEqual(self.spans(r), [("boot", "L0", utc("2026-09-05 08:30"), utc("2026-09-05 15:00"), False)])
        self.assertEqual(r.records[0]["confidence"], 0.4)
        self.assertTrue(r.status["fallback_boot"])

    def test_no_events_rc1(self):
        r = self.run_ev(self.csv("empty2.csv", []), now="2026-09-05 15:00")
        self.assertEqual(r.rc, 1)
        self.assertEqual(r.records, [])
        self.assertEqual(r.cursor, {"last_ts_utc": None})
        self.assertEqual(r.status["reasons"], [])

    def test_range_filters_events(self):
        rows = [("2026-08-20 09:00", "on", "6005"), ("2026-08-20 18:00", "off", "6006"),
                ("2026-09-10 09:00", "on", "6005"), ("2026-09-10 18:00", "off", "6006")]
        r = self.run_ev(self.csv("range.csv", rows), now="2026-09-11 12:00", since="2026-09-01", until="2026-09-10")
        self.assertEqual([x["ts_utc"] for x in r.records], [utc("2026-09-10 09:00")])
        self.assertEqual(r.status["range"], ["2026-09-01", "2026-09-10"])

    # ── 채널 상태(X-317)·R-NOEVT ─────────────────────────────────────────
    def test_system_channel_unauthorized_rc3_noevt(self):
        rows = [("", "channel", "system:unauthorized"), ("", "channel", "security_lock:unauthorized"),
                ("", "channel", "diag_perf:ok"), ("2026-09-02 08:55", "on", "100"), ("2026-09-02 18:00", "off", "200")]
        r = self.run_ev(self.csv("noevt.csv", rows), now="2026-09-03 09:00")
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.status["reasons"], ["R-NOEVT"])
        self.assertEqual(len(r.records), 1)                                         # 다른 채널 구간은 그대로 낸다
        self.assertEqual(r.status["channels"], {"synthetic": "ok", "system": "unauthorized",
                                                "security_lock": "unauthorized", "diag_perf": "ok"})

    def test_bonus_channel_unauthorized_no_reason(self):
        rows = [("", "channel", "system:ok"), ("", "channel", "security_lock:unauthorized"),
                ("", "channel", "ts_session:error:EventLogException"), ("", "channel", "bogus:maybe"),
                ("2026-09-02 08:55", "on", "6005"), ("2026-09-02 18:00", "off", "6006")]
        r = self.run_ev(self.csv("bonus.csv", rows), now="2026-09-03 09:00")
        self.assertEqual((r.rc, r.status["reasons"]), (0, []))
        self.assertEqual(r.status["channels"]["security_lock"], "unauthorized")
        self.assertEqual(r.status["channels"]["ts_session"], "error")
        self.assertEqual(r.status["channel_errors"], {"ts_session": "EventLogException"})
        self.assertNotIn("bogus", r.status["channels"])
        for v in r.status["channels"].values():
            self.assertIn(v, ("ok", "none", "unauthorized", "error"))

    # ── 증분·롤오버(CP-5) ────────────────────────────────────────────────
    def test_rollover_reharvest_cursor_only(self):
        a = [("2026-09-01 09:00", "on", "6005"), ("2026-09-01 18:00", "off", "6006"),
             ("2026-09-02 09:00", "on", "6005"), ("2026-09-02 18:00", "off", "6006"),
             ("2026-09-03 09:00", "on", "6005")]
        r1 = self.run_ev(self.csv("roll_a.csv", a), now="2026-09-03 12:00", boot="2026-09-03 09:00")
        self.assertEqual(len(r1.records), 3)
        live_start = utc("2026-09-03 09:00")
        self.assertEqual(r1.cursor, {"last_ts_utc": live_start})
        # 6시간 뒤: 9/1 은 로그에서 롤오버로 사라졌고, 9/3 구간은 닫혔고, 9/4 가 새로 생김
        b = [("2026-09-02 09:00", "on", "6005"), ("2026-09-02 18:00", "off", "6006"),
             ("2026-09-03 09:00", "on", "6005"), ("2026-09-03 18:30", "off", "6006"),
             ("2026-09-04 09:00", "on", "6005"), ("2026-09-04 17:00", "off", "6006")]
        r2 = self.run_ev(self.csv("roll_b.csv", b), now="2026-09-04 20:00", cursor=r1.cursor)
        self.assertEqual([x["ts_utc"] for x in r2.records], [live_start, utc("2026-09-04 09:00")])
        self.assertEqual(r2.records[0]["ts_end"], utc("2026-09-03 18:30"))           # 같은 시작(같은 id) 의 새 판 — 끝이 닫힘
        self.assertEqual(r2.rc, 0)
        self.assertEqual(r2.cursor, {"last_ts_utc": utc("2026-09-04 17:00")})
        r3 = self.run_ev(self.csv("roll_b.csv", b), now="2026-09-04 21:00", cursor=r2.cursor)
        self.assertEqual(r3.records, [])
        self.assertEqual(r3.rc, 4)                                                   # 읽었지만 새 구간 0
        self.assertEqual(r3.cursor, r2.cursor)

    def test_cursor_never_moves_back(self):
        rows = [("2026-09-02 09:00", "on", "6005"), ("2026-09-02 18:00", "off", "6006")]
        cur = {"last_ts_utc": utc("2026-09-20 00:00")}
        r = self.run_ev(self.csv("back.csv", rows), now="2026-09-21 12:00", cursor=cur)
        self.assertEqual(r.cursor, cur)
        self.assertEqual(r.records, [])

    # ── 주입·디스크 ──────────────────────────────────────────────────────
    def test_outdir_writes_status_only_and_no_other_disk_writes(self):
        out = self.clone.temp / "wp14_outdir"
        out.mkdir(parents=True, exist_ok=True)
        rows = [("2026-09-01 08:50", "on", "6005"), ("2026-09-01 18:10", "off", "6006")]
        csv = self.csv("outdir.csv", rows)
        before_lad = snapshot(self.clone.lad)
        before_tree = snapshot(self.clone.root / "collect")
        r = self.run_ev(csv, now="2026-09-02 09:00", extra=["-OutDir", str(out)])
        self.assertEqual(os.listdir(out), ["event_status.json"])
        st = json.loads((out / "event_status.json").read_bytes().decode("utf-8"))
        self.assertEqual(st["rc"], r.rc)
        self.assertNotIn("path", json.dumps(st))
        self.assertEqual(snapshot(self.clone.lad), before_lad)
        self.assertEqual(snapshot(self.clone.root / "collect"), before_tree)

    def test_no_stdin_runs_with_defaults(self):
        rows = [("2026-09-01 08:50", "on", "6005"), ("2026-09-01 18:10", "off", "6006")]
        r = run_ps(self.clone, SCRIPT, ["-EventsCsv", self.csv("nostdin.csv", rows), "-Now", "2026-09-02 09:00"])
        self.assertEqual(r.rc, 0, r.err())
        self.assertEqual(r.status["in"], "none")
        self.assertEqual(len(r.records), 1)

    def test_bad_in_line_is_tolerated(self):
        rows = [("2026-09-01 08:50", "on", "6005"), ("2026-09-01 18:10", "off", "6006")]
        csv = self.csv("badin.csv", rows)
        from tests.fixtures.wp14 import runner
        import subprocess
        cp = subprocess.run([runner.powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(self.clone.path("collect", SCRIPT)), "-EventsCsv", csv, "-Now", "2026-09-02 09:00"],
                            input=b"not json\n", capture_output=True, env=self.clone.env(), cwd=str(self.clone.temp),
                            timeout=120, creationflags=runner.CREATE_NO_WINDOW, check=False)
        r = runner.parse_output(cp.stdout, cp.stderr, cp.returncode)
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.status["in"], "bad")

    def test_synth_plan_power_spans(self):
        """WP-05 합성 계획(근무일마다 부팅 L0 08:50~18:10 · 로그온 L1 08:52~18:08)을 그대로 구간으로 되살린다."""
        plan = plan_period(datetime(2026, 9, 7).date(), datetime(2026, 9, 11).date())
        p = write_events_csv(self.clone.temp / "wp14_events" / "synth.csv", plan)
        args = events_args(p, plan)
        r = run_ps(self.clone, SCRIPT, [*args, "-Since", "2026-09-07", "-Until", "2026-09-11"], cfg={})
        self.assertEqual(r.rc, 0, r.err())
        evs = sorted((ev for ev in plan.power if ev.pc == "PC1"), key=lambda e: (e.start, e.layer))
        got = sorted((x["ts_utc"], x["layer"], x["event_class"]) for x in r.records)
        exp = sorted((e.start.strftime("%Y-%m-%dT%H:%M:%SZ"), e.layer, e.event_class) for e in evs)
        self.assertEqual(got, exp)
        last_boot = max(e.start for e in evs if e.layer == "L0")
        for x in r.records:
            if x["ts_utc"] != last_boot.strftime("%Y-%m-%dT%H:%M:%SZ"):
                self.assertFalse(x["flags"]["end_uncertain"])


FAKE_WRAPPER = r"""
$ErrorActionPreference = 'Stop'
$inv = [Globalization.CultureInfo]::InvariantCulture
$global:FakeData = [IO.File]::ReadAllText($env:LM27T_FAKE_EVENTS, [Text.Encoding]::UTF8) | ConvertFrom-Json
$global:FakeSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$global:FakeQueries = 0
function Get-WinEvent {
    [CmdletBinding()] param([hashtable]$FilterHashtable)
    $global:FakeQueries++
    $log = [string]$FilterHashtable['LogName']
    $p = $global:FakeData.logs.PSObject.Properties[$log]
    if ($null -eq $p) { return @() }
    $st = [string]$p.Value.status
    if ($st -eq 'unauthorized') { throw (New-Object UnauthorizedAccessException) }
    if ($st -eq 'notfound') { throw (New-Object System.Diagnostics.Eventing.Reader.EventLogNotFoundException) }
    if ($st -eq 'error') { throw (New-Object System.InvalidOperationException) }
    $ids = @($FilterHashtable['Id'] | ForEach-Object { [int]$_ })
    $from = $FilterHashtable['StartTime']
    $to = $FilterHashtable['EndTime']
    foreach ($e in @($p.Value.events)) {
        $t = [datetime]::ParseExact([string]$e.t, 'yyyy-MM-dd HH:mm', $inv)
        if ($ids -notcontains [int]$e.id -or $t -lt $from -or $t -ge $to) { continue }
        $o = [pscustomobject]@{ Id = [int]$e.id; ProviderName = [string]$e.provider; TimeCreated = $t;
                                Xml = ([string]$e.xml).Replace('MYSID', $global:FakeSid) }
        $o | Add-Member -MemberType ScriptMethod -Name ToXml -Value { return $this.Xml }
        $o
    }
}
function Get-CimInstance {
    [CmdletBinding()] param([string]$ClassName)
    return [pscustomobject]@{ LastBootUpTime = [datetime]::ParseExact([string]$global:FakeData.boot, 'yyyy-MM-dd HH:mm', $inv) }
}
& $env:LM27T_COLLECTOR @args
exit $LASTEXITCODE
"""
NS = "http://schemas.microsoft.com/win/2004/08/events/event"


def _xml_data(field, value):
    return f'<Event xmlns="{NS}"><EventData><Data Name="{field}">{value}</Data></EventData></Event>'


def _xml_ts(user, addr):
    return (f'<Event xmlns="{NS}"><UserData><EventXML xmlns="Event_NS"><User>{user}</User><SessionID>2</SessionID>'
            f"<Address>{addr}</Address></EventXML></UserData></Event>")


class LiveMockTest(CloneTestCase):
    """실제 이벤트 로그 대신 Get-WinEvent·Get-CimInstance 를 시험 함수로 가린 감싸개로 '라이브' 갈래(공급자 대조·내 SID·내 계정·
    원격 주소 판정·채널 상태 열거)를 돈다. 감싸개는 복제 %TEMP% 에만 쓰고, 이벤트는 합성 JSON 이다(SID 는 실행 때 메모리에서 채운다)."""

    def run_live(self, logs, *, boot="2026-09-04 09:00", now="2026-09-04 18:00", cfg=None):
        d = self.clone.temp / "wp14_live"
        d.mkdir(parents=True, exist_ok=True)
        wrapper = d / "fake_events.ps1"
        wrapper.write_bytes(FAKE_WRAPPER.replace("\n", "\r\n").encode("ascii"))
        data = d / "events.json"
        data.write_bytes(json.dumps({"boot": boot, "logs": logs}, ensure_ascii=False).encode("utf-8"))
        env = {"LM27T_FAKE_EVENTS": str(data), "LM27T_COLLECTOR": str(self.clone.path("collect", SCRIPT)),
               "USERNAME": "tester01"}
        return run_ps(self.clone, SCRIPT, ["-Now", now, "-Since", "2026-09-01", "-Until", "2026-09-04"],
                      cfg=cfg if cfg is not None else {}, env=env, script_path=wrapper)

    def test_live_branch_filters_provider_sid_user_and_remote(self):
        system = {"status": "ok", "events": [
            {"t": "2026-09-03 08:50", "id": 6005, "provider": "EventLog", "xml": ""},
            {"t": "2026-09-03 08:51", "id": 12, "provider": "Some-Other-Provider", "xml": ""},     # 공급자 불일치 → 버림
            {"t": "2026-09-03 08:52", "id": 7001, "provider": "Microsoft-Windows-Winlogon", "xml": _xml_data("UserSid", "MYSID")},
            {"t": "2026-09-03 09:30", "id": 7002, "provider": "Microsoft-Windows-Winlogon",
             "xml": _xml_data("UserSid", "S-1-5-21-1-2-3-9999")},                                   # 다른 사용자 → 버림
            {"t": "2026-09-03 12:00", "id": 42, "provider": "Microsoft-Windows-Kernel-Power", "xml": ""},
            {"t": "2026-09-03 13:00", "id": 1, "provider": "Microsoft-Windows-Power-Troubleshooter", "xml": ""},
            {"t": "2026-09-03 18:00", "id": 7002, "provider": "Microsoft-Windows-Winlogon", "xml": _xml_data("UserSid", "MYSID")},
            {"t": "2026-09-03 18:05", "id": 6006, "provider": "EventLog", "xml": ""},
            {"t": "2026-09-04 09:00", "id": 6005, "provider": "EventLog", "xml": ""}]}
        ts = {"status": "ok", "events": [
            {"t": "2026-09-04 10:00", "id": 25, "provider": "Microsoft-Windows-TerminalServices-LocalSessionManager",
             "xml": _xml_ts("EXAMPLE\\tester01", "192.0.2.10")},
            {"t": "2026-09-04 11:00", "id": 24, "provider": "Microsoft-Windows-TerminalServices-LocalSessionManager",
             "xml": _xml_ts("EXAMPLE\\tester01", "192.0.2.10")},
            {"t": "2026-09-04 11:30", "id": 21, "provider": "Microsoft-Windows-TerminalServices-LocalSessionManager",
             "xml": _xml_ts("EXAMPLE\\tester02", "LOCAL")}]}                                         # 다른 계정 → 버림
        logs = {"System": system, "Microsoft-Windows-Diagnostics-Performance/Operational": {"status": "unauthorized"},
                "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational": ts,
                "Security": {"status": "notfound"}}
        r = self.run_live(logs)
        self.assertEqual(r.rc, 0, r.err())
        self.assertEqual(r.status["channels"], {"system": "ok", "diag_perf": "unauthorized", "ts_session": "ok",
                                                "security_lock": "none"})
        self.assertEqual(r.status["reasons"], [])
        got = [(x["event_class"], x["layer"], x["ts_utc"], x["ts_end"], x["flags"]["remote"]) for x in r.records]
        self.assertEqual(got, [
            ("boot", "L0", utc("2026-09-03 08:50"), utc("2026-09-03 12:00"), False),
            ("logon", "L1", utc("2026-09-03 08:52"), utc("2026-09-03 18:00"), False),
            ("wake", "L0", utc("2026-09-03 13:00"), utc("2026-09-03 18:05"), False),
            ("boot", "L0", utc("2026-09-04 09:00"), utc("2026-09-04 18:00"), False),
            ("rdp_connect", "L1", utc("2026-09-04 10:00"), utc("2026-09-04 11:00"), True),
        ])
        self.assertEqual(r.records[-1]["session_state"], "remote")
        self.assertTrue(r.status["live"])                                                # 부팅 시각(가짜 CIM) 이후 구간
        self.assertNotIn("192.0.2.10", r.stdout.decode("utf-8") + r.err())
        self.assertNotIn("tester0", r.stdout.decode("utf-8"))

    def test_live_system_unauthorized_rc3(self):
        logs = {"System": {"status": "unauthorized"},
                "Microsoft-Windows-Diagnostics-Performance/Operational": {"status": "ok", "events": [
                    {"t": "2026-09-03 08:55", "id": 100, "provider": "Microsoft-Windows-Diagnostics-Performance", "xml": ""},
                    {"t": "2026-09-03 18:00", "id": 200, "provider": "Microsoft-Windows-Diagnostics-Performance", "xml": ""}]},
                "Security": {"status": "error"}}
        r = self.run_live(logs)
        self.assertEqual((r.rc, r.status["reasons"]), (3, ["R-NOEVT"]))
        self.assertEqual(r.status["channels"]["system"], "unauthorized")
        self.assertEqual(r.status["channels"]["security_lock"], "error")
        self.assertEqual(r.status["channel_errors"], {"security_lock": "InvalidOperationException"})
        self.assertEqual([x["event_class"] for x in r.records], ["boot"])


if __name__ == "__main__":
    unittest.main()
