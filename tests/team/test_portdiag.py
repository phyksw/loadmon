# -*- coding: utf-8 -*-
"""WP-27 포트 진단 — netstat·netsh·프로세스 출력 해석, 판정 표, 대체 포트(회피·임시·예약·로컬 앱), 신원 판정
(TAB §3.4 · §2.9 · X-276, TAB-S02(판정) · S17). 외부 명령은 출력 모사만 — 시스템 설정을 바꾸지 않는다.
"""
import json
import unittest

from lm27.team import portdiag as D
from tests.fixtures.wp27 import bundles as B
from tests.fixtures.wp27.helpers import LM24_ROUTES, LM24_TEAM_ROUTES, fake_server, free_port, running_server

NETSTAT = (b"\r\n\xc8\xb0\xbc\xba \xbf\xac\xb0\xe1\r\n\r\n  Proto  Local  Foreign  State  PID\r\n"
           b"  TCP    0.0.0.0:9310           0.0.0.0:0              LISTENING       4120\r\n"
           b"  TCP    [::]:9310              [::]:0                 LISTENING       5000\r\n"
           b"  TCP    0.0.0.0:19310          0.0.0.0:0              LISTENING       77\r\n"
           b"  TCP    127.0.0.1:9310         127.0.0.1:50000        ESTABLISHED     88\r\n")
DYN_KO = "\r\n프로토콜 tcp 동적 포트 범위\r\n---------------------------------\r\n시작 포트      : 1024\r\n포트 수        : 13977\r\n"
RSV_KO = ("\r\n프로토콜 tcp 포트 제외 범위\r\n\r\n시작 포트    끝 포트\r\n----------    --------\r\n     5357        5357\r\n"
          "    19310       19312\r\n\r\n* - 관리 포트 제외\r\n")


def fake_run(netstat=NETSTAT, dyn=DYN_KO, rsv=RSV_KO, cim=None, ps_listen=None):
    calls = []

    def run(argv, timeout):
        cmd = " ".join(argv).lower()
        calls.append(cmd)
        if "netstat" in cmd:
            return None if netstat is None else (0, netstat)
        if "get-nettcpconnection" in cmd:
            return None if ps_listen is None else (0, ps_listen)
        if "get-ciminstance" in cmd:
            return None if cim is None else (0, json.dumps(cim).encode())
        if "dynamicport" in cmd:
            return 0, dyn.encode("cp949")
        if "excludedportrange" in cmd:
            return 0, rsv.encode("cp949")
        return None
    run.calls = calls
    return run


class TestParse(unittest.TestCase):
    def setUp(self):
        D.clear_cache()

    def test_listeners_ipv4_ipv6_and_none(self):
        self.assertEqual(D.listeners(9310, run=fake_run()), [4120, 5000])            # -p TCP 없이 IPv6 행까지
        self.assertEqual(D.listeners(9311, run=fake_run()), [])                      # 아무도 없음 = []
        self.assertEqual(D.listeners(9310, run=fake_run(netstat=None, ps_listen=b"4120\r\n4120\r\n")), [4120])
        self.assertIsNone(D.listeners(9310, run=fake_run(netstat=None)))             # 못 알아냄 = None
        r = fake_run()
        D.listeners(9310, run=r)
        self.assertFalse(any("-p" in c.split() for c in r.calls))

    def test_proc_info_readable_and_not(self):
        cim = [{"ProcessId": 4120, "Name": "python.exe", "ExecutablePath": "X\\python.exe"},
               {"ProcessId": 5000, "Name": "svc.exe", "ExecutablePath": None}]
        out = {p["pid"]: p for p in D.proc_info([4120, 5000, 9], run=fake_run(cim=cim))}
        self.assertEqual((out[4120]["name"], out[4120]["readable"]), ("python.exe", True))
        self.assertEqual((out[5000]["exe"], out[5000]["readable"]), ("확인 불가", False))
        self.assertEqual(out[9]["name"], "(확인 불가)")
        self.assertEqual(D.proc_info([], run=fake_run()), [])

    def test_netsh_ranges_korean(self):
        self.assertEqual(D.dynamic_range(run=fake_run()), (1024, 15000))
        self.assertEqual(D.reserved_ranges(run=fake_run()), [(5357, 5357), (19310, 19312)])
        self.assertEqual(D.reserved_range_of(19311, run=fake_run()), "19310~19312")
        self.assertEqual(D.reserved_range_of(19313, run=fake_run()), "")
        D.clear_cache()
        self.assertEqual(D.dynamic_range(run=lambda a, t: None), (0, 0))


class TestClassifySuggest(unittest.TestCase):
    def setUp(self):
        D.clear_cache()
        self._td = B.temp_dir()
        self.cfg = B.test_cfg(self._td.__enter__())

    def tearDown(self):
        self._td.__exit__(None, None, None)

    def test_classify_table(self):
        dyn = (1024, 15000)
        self.assertEqual(D.classify([1], [], {"result": "ok", "store_id": "s1"}, "", dyn, 9310, store_id="s1"),
                         "lm27_same")
        self.assertEqual(D.classify([1], [], {"result": "ok", "store_id": "s2"}, "", dyn, 9310, store_id="s1"),
                         "lm27_other")
        self.assertEqual(D.classify([1], [], {"result": "lm24"}, "", dyn, 9310), "lm24")
        self.assertEqual(D.classify([1], [], {"result": "other_lm"}, "", dyn, 9310), "other_lm")
        self.assertEqual(D.classify([1], [], {"result": "refused"}, "", dyn, 9310), "other_program")
        self.assertEqual(D.classify([], [], {"result": "refused"}, "9300~9320", dyn, 9310), "reserved")
        self.assertEqual(D.classify([], [], {"result": "refused"}, "", dyn, 9310), "ephemeral")
        self.assertEqual(D.classify(None, [], {"result": "refused"}, "", dyn, 9310), "unknown")
        self.assertEqual(D.classify([], [], {"result": "refused"}, "", (0, 0), 9310), "unknown")

    def test_s17_ephemeral(self):
        """S17: 동적 범위 1024~15000, 9310 리스너 없음 + bind 10048 → ephemeral, 제안 19310 이상(예약 19310~19312 건너뜀)."""
        run = fake_run(netstat=b"  TCP    0.0.0.0:445   0.0.0.0:0   LISTENING   4\r\n")
        d = D.diagnose_port(9310, 10048, self.cfg, run=run, ident={"result": "refused"}, bind=lambda p: True)
        self.assertEqual((d.kind, d.listeners), ("ephemeral", []))
        self.assertGreaterEqual(d.suggest, 19310)
        self.assertEqual(d.suggest, 19313)
        self.assertIn("임시 포트 범위 1024~15000", d.message)
        self.assertIn("관리자 권한", d.message)
        self.assertEqual(json.loads(json.dumps(d.as_dict()))["kind"], "ephemeral")

    def test_suggest_avoids(self):
        D.clear_cache()
        run = fake_run(rsv="")
        cfg = self.cfg.derive({"teamServer.suggestRanges": [[8760, 8770], [9330, 9346], [19280, 19295]]})
        got = []
        for _ in range(3):
            p = D.suggest_port(9310, cfg, run=run, bind=lambda q: q not in got, extra_avoid=())
            got.append(p)
        # 8765~8767(별개 프로젝트)·9333(이전 판)·9343~(CDP)·19280~19289(로컬 앱)·임시 범위(≤15000)를 건너뛴다
        self.assertEqual(got, [19290, 19291, 19292])
        self.assertEqual(D.suggest_port(9310, cfg, run=run, bind=lambda q: False), 0)
        self.assertTrue({8764 + k for k in (1, 2, 3)} | {9332 + 1} <= D.AVOID)

    def test_messages_name_process(self):
        d = D.PortDiag(kind="other_program", code=10048, port=9310, listeners=[4120],
                       procs=[{"pid": 4120, "name": "tool.exe", "exe": "확인 불가", "readable": False}], suggest=19310)
        msg = D.message_ko(d)
        self.assertIn("tool.exe", msg)
        self.assertIn("19310", msg)
        self.assertIn("끄지 않습니다", msg)


class TestIdentity(unittest.TestCase):
    def test_probe_identity_variants(self):
        with fake_server(LM24_ROUTES) as p:
            self.assertEqual(D.probe_identity(p)["result"], "lm24")
        with fake_server(LM24_TEAM_ROUTES) as p:
            self.assertEqual(D.probe_identity(p)["result"], "lm24")
        with fake_server({"/api/hello": (200, {"app": "LM28-team", "proto": "x"})}) as p:
            r = D.probe_identity(p)
            self.assertEqual((r["result"], r["app"]), ("other_lm", "LM28-team"))
        with fake_server({"/api/hello": (200, {"app": "other"})}) as p:
            self.assertEqual(D.probe_identity(p)["result"], "other_app")
        self.assertIn(D.probe_identity(free_port(), timeout=5.0)["result"], ("refused", "timeout"))   # 윈도우 루프백 거절은 ~2초

    def test_lm27_same_vs_other(self):
        with B.temp_dir() as d, running_server(d) as ts:
            ident = D.probe_identity(ts.port)
            self.assertEqual((ident["result"], ident["store_id"]), ("ok", ts.store.store_id))
            self.assertNotIn("pid", ident)
            dd = D.diagnose_port(ts.port, 10013, ts.store.cfg, store_id=ts.store.store_id,
                                 run=fake_run(netstat=f"  TCP 127.0.0.1:{ts.port} 0.0.0.0:0 LISTENING 1\r\n".encode()),
                                 bind=lambda p: True)
            self.assertEqual((dd.kind, dd.suggest), ("lm27_same", 0))
            self.assertIn("이미 실행 중", dd.message)
            dd = D.diagnose_port(ts.port, 10013, ts.store.cfg, store_id="other", run=fake_run(), bind=lambda p: True)
            self.assertEqual(dd.kind, "lm27_other")

    def test_bind_test_busy_port(self):
        with B.temp_dir() as d, running_server(d) as ts:
            self.assertFalse(D.bind_test(ts.port))
