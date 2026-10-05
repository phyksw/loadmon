# -*- coding: utf-8 -*-
"""WP-01 레지스트리 ↔ 계약 §5.2 표 생성 대조(L-12 정적 부분) + 선언 위생(L-21·L-24·L-26 일부).

- §5.2 표의 모든 키(· 로 묶인 하위 키·.x 줄임 포함)가 레지스트리에 하나씩, 같은 순서로 있다.
- ★ = uncalibrated, 기본값(서술형 '내장'·'W 목록' 등 제외)·형 계열·선택지가 표와 같다.
- snake_case 키 0, §5.4 옛 이름 0(키·문구 모두), 배포 기본값에 고객·과제·별칭·코드네임·규칙·카탈로그 0.
- 팀 서버 기본 주소는 계약 §0.1 의 기본 URL 과 바이트 일치(시험 텍스트에는 주소 리터럴을 두지 않는다).
"""
import ipaddress
import json
import re
import unittest
from pathlib import Path

from lm27 import config as C

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "config" / "settings_registry.json"
CONTRACT = ROOT / "docs" / "CONTRACT.md"

# 계약 §2 모듈 지도의 파이썬 모듈(소유 모듈 표기 검사용)
KNOWN_MODULES = set()
for _pkg, _mods in {
    "lm27": "cli paths config catalog",
    "lm27.util": "fsx tz proc events",
    "lm27.privacy": "sanitize rules detect scan classify records keys gate audit context sanitize_stream selftest",
    "lm27.store": "writer reader cursor",
    "lm27.agent": "install main sampler harvest exemeta",
    "lm27.collect": "run plan probe rcmap watch stage_result ledger todo diagnose",
    "lm27.bundle": "ids lock segment manifest pcreg aliases export loader merge move",
    "lm27.normalize": "load merge cues act absence",
    "lm27.time": "calendar intervals tokens evidence envelope episodes attribute mm ledger queue",
    "lm27.hier": "names vocab registry_schema registry match features rules unitlabel groups copilot_io apply "
                 "proposals merge learn queue bootstrap team_out",
    "lm27.vocab": "steps",
    "lm27.bridge": "clock settings cdp js session env transport transport_stub jsonx exchange gate runner budget "
                   "journal calibrate capability manual messages trace fsio cli",
    "lm27.bridge.stages": "base lookup speech_act task_label taxonomy_bootstrap taxonomy_consolidate workflow_label "
                          "review_text agentic_match subagent_review",
    "lm27.pipeline": "analyze stages retention",
    "lm27.report": "inputs vocab fmt resolve model export drill",
    "lm27.report.analysis": "activity mining review peers ontology agentic subagent quality ai_items",
    "lm27.ui": "server jobs nextactions api_home api_collect api_analysis api_report api_team api_settings "
               "api_privacy",
    "lm27.team": "schema build queue client server store aggregate report portdiag firewall offline",
}.items():
    KNOWN_MODULES |= {f"{_pkg}.{m}" for m in _mods.split()}

REF_RX = re.compile(r"(?:[A-Z]{1,3} §\d+(?:\.\d+)*|[OXD]-\d+)")
TYPE_FAMILY = {"int": {"int"}, "float": {"float"}, "bool": {"bool"}, "path": {"path"}, "obj": {"obj"},
               "list(+-)": {"list(+-)"}, "시각 구간": {"timerange"}, "list·obj": {"list", "obj"}}


def family(type_text: str):
    """계약 형 칸 조각 → 허용 레지스트리 형 집합(판정 불가면 None), 또는 ('choices', [...])."""
    t = type_text.strip()
    if t in TYPE_FAMILY:
        return TYPE_FAMILY[t]
    if t.startswith("list(+-)"):
        return {"list(+-)"}
    if t.startswith("list"):
        return {"list"}
    if t.startswith("int"):
        return {"int"}
    if t.startswith("float"):
        return {"float"}
    if t.startswith("str"):
        return {"str", "enum", "path", "regex", "timerange"}
    parts = [p.strip() for p in t.split("·")]
    if len(parts) > 1 and all(re.fullmatch(r"[A-Za-z0-9_]+", p) for p in parts):
        return ("choices", parts)
    return None


class RegistryTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.md = CONTRACT.read_text(encoding="utf-8")
        cls.rows = C.contract_table_rows(cls.md)
        cls.raw = REG.read_bytes()
        cls.doc = json.loads(cls.raw.decode("utf-8"))
        cls.reg = C.load_registry(REG)
        cls.ct = {r["key"]: r for r in cls.rows}

    # ── 키 집합 ───────────────────────────────────────────────────────────
    def test_parser_expands_groups_and_shorthand(self):
        keys = [r["key"] for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))
        for k in ("privacy.extraCtx.passport", "time.window.halfPmOff", "time.envelope.preWindowMin.submit",
                  "bridge.dom.assistantSelectors", "teamServer.aggregateTimeoutSec", "mail.com.capCal",
                  "hier.ax.minHits", "teamReport.maxDetailMb"):
            self.assertIn(k, keys)
        self.assertTrue(self.ct["hier.rule.w.keyword"]["star"])          # 키 칸의 ★
        self.assertFalse(self.ct["hier.rule.w.keywordCap"]["star"])
        self.assertTrue(self.ct["time.envelope.preWindowMin.code"]["star"])  # 기본값 조각의 ★
        self.assertTrue(self.ct["collect.lookbackDays"]["star"])          # '120 ★'

    def test_registry_keys_equal_contract_table(self):
        self.assertEqual(list(self.doc["keys"]), [r["key"] for r in self.rows])
        self.assertGreaterEqual(len(self.rows), 400)

    def test_key_notation(self):
        for k in self.doc["keys"]:
            self.assertRegex(k, C.KEY_RX)
            self.assertNotIn("_", k)

    def test_no_retired_names(self):
        s = self.md.index("### 5.4 ")
        e = self.md.index("\n---\n", s)
        olds = set()
        for line in self.md[s:e].splitlines():
            if line.startswith("|"):
                first = line.strip().strip("|").split("|")[0]
                olds |= {t for t in re.findall(r"`([^`]+)`", first) if "*" not in t}
        self.assertGreater(len(olds), 40)
        text = self.raw.decode("utf-8")
        for o in sorted(olds):
            self.assertNotIn(o, self.doc["keys"], o)
            rx = r"(?<![A-Za-z0-9_.])" + re.escape(o) + r"(?![A-Za-z0-9_])"
            self.assertIsNone(re.search(rx, text), f"레지스트리 문구에 옛 이름: {o}")

    # ── 표 ↔ 선언 대조 ─────────────────────────────────────────────────────
    def test_uncalibrated_equals_star(self):
        for r in self.rows:
            self.assertEqual(self.reg[r["key"]].uncalibrated, r["star"], r["key"])
        self.assertGreaterEqual(sum(r["star"] for r in self.rows), 60)

    def test_defaults_equal_table(self):
        n = 0
        for r in self.rows:
            if r["default_ok"]:
                n += 1
                self.assertEqual(self.reg[r["key"]].default, r["default"], r["key"])
        self.assertGreaterEqual(n, 350)

    def test_type_family_equals_table(self):
        n = 0
        for r in self.rows:
            if not r["type_text"]:
                continue
            fam = family(r["type_text"])
            meta = self.reg[r["key"]]
            if fam is None:
                continue
            n += 1
            if isinstance(fam, tuple):
                self.assertEqual(meta.type, "enum", r["key"])
                self.assertEqual(sorted(meta.choices), sorted(fam[1]), r["key"])
            else:
                self.assertIn(meta.type, fam, r["key"])
        self.assertGreaterEqual(n, 150)

    def test_explicit_contract_ranges(self):
        self.assertEqual(self.reg["teams.uia.intervalSec"].range, {"min": 120, "max": 300})
        self.assertEqual(self.reg["agent.sampleIntervalSec"].range["min"], 5)
        self.assertEqual(self.reg["privacy.pipe.waitSec"].range, {"min": 30, "max": 1800})
        for k in ("privacy.time.regularPrivateRunMin", "privacy.time.offhoursPrivateBreakMin"):
            self.assertEqual(self.reg[k].range, {"min": 5, "max": 240, "step": 5})

    def test_spec_references_kept(self):
        for r in self.rows:
            spec = self.reg[r["key"]].spec
            for ref in REF_RX.findall(r["spec"]):
                self.assertIn(ref, spec, r["key"])

    def test_list_merge_keys_have_builtin(self):
        merge = {k for k, m in self.reg.items() if m.type == "list(+-)"}
        declared = {r["key"] for r in self.rows if (r["type_text"] or "").startswith("list(+-)")}
        self.assertLessEqual(declared, merge)
        for k in merge - declared:                                   # 표에 형 칸이 없는 행만(서술형 기본값)
            self.assertIsNone(self.ct[k]["type_text"], k)
            self.assertTrue(self.ct[k]["default_text"].startswith(("내장", "W 목록")), k)
        for k in merge:
            if k != "pc.excludeFolderNames":                       # 이전 판 내장 목록이 비어 있던 키
                self.assertTrue(self.reg[k].default, k)
        self.assertEqual(len(self.reg["pc.watchExtensions"].default), 248)
        self.assertEqual(len(self.reg["privacy.personalMailDomains"].default), 13)

    def test_bridge_stages_default(self):
        st = self.reg["bridge.stages"].default
        self.assertEqual(len(st), 11)
        self.assertEqual([k for k, v in st.items() if not v], ["lookup_calendar"])

    # ── 선언 위생 ──────────────────────────────────────────────────────────
    def test_every_key_complete(self):
        for k, d in self.doc["keys"].items():
            for f in C.REQUIRED_FIELDS:
                self.assertIn(f, d, k)
            self.assertTrue("range" in d or "choices" in d, k)
            self.assertRegex(d["label_ko"], r"[가-힣]", k)
            self.assertRegex(d["help_ko"], r"[가-힣]", k)
            self.assertIn(d["scope"], C.SCOPES)
            self.assertIn(d["restart"], C.RESTARTS)

    def test_owner_modules_exist_in_contract_map(self):
        for k, m in self.reg.items():
            for o in (m.owner, *m.readers):
                if "/" in o:
                    self.assertIn(o.rsplit("/", 1)[1], self.md, f"{k}: {o}")
                else:
                    self.assertIn(o, KNOWN_MODULES, f"{k}: {o}")
            self.assertTrue(m.owner_file().endswith((".py", ".ps1")))
        self.assertEqual(C.owner_file("lm27.collect.run"), "lm27/collect/run.py")
        self.assertEqual(C.owner_file("collect/Get-TeamsWeb.py"), "collect/Get-TeamsWeb.py")

    def test_scope_restart_rules(self):
        for k, m in self.reg.items():
            if C.is_agent_key(k):
                self.assertEqual((m.scope, m.restart), ("agent", "agent"), k)
            elif k.startswith(("teamServer.", "teamReport.")):
                self.assertEqual(m.scope, "team_server", k)
            else:
                self.assertEqual(m.scope, "personal", k)

    def test_no_secrets_in_registry(self):
        for k, m in self.reg.items():
            if m.secret:
                self.assertTrue(k.endswith("Sha256"), k)
                self.assertEqual(m.default, "", k)
            if "token" in k.lower() and m.type == "str":             # 토큰 값을 담는 키는 sha256 만
                self.assertTrue(m.secret and k.endswith("Sha256"), k)

    def test_team_server_default_matches_contract_url(self):
        m = re.search(r"팀 서버 기본 주소 `(http://([\d.]+):(\d+))`", self.md)
        self.assertIsNotNone(m)
        host, port = self.reg["team.serverHost"].default, self.reg["team.serverPort"].default
        self.assertEqual(f"http://{host}:{port}", m.group(1))
        self.assertEqual(host, self.ct["team.serverHost"]["default"])
        self.assertEqual(port, self.ct["team.serverPort"]["default"])
        self.assertEqual(self.reg["teamServer.bindPort"].default, port)

    def test_deploy_defaults_neutral(self):
        for k in ("privacy.customers", "privacy.partners", "privacy.internalDomains", "privacy.allowPatterns",
                  "privacy.window.workTitlePatterns", "privacy.ad.blockDomains", "privacy.ad.allowDomains",
                  "privacy.ad.blockSubjectRegex", "privacy.ad.extraWords", "privacy.private.extraWords",
                  "privacy.private.extraWorkWords", "privacy.names.extraStopwords", "teams.pmWhoKeys",
                  "pc.programsExtra", "pc.watchFolders", "pc.git.repos", "pc.git.scanRoots",
                  "hier.tokens.boilerplateAdd", "team.serverAlternates", "teamServer.allowCidrs"):
            self.assertEqual(self.reg[k].default, [], k)
        for k in ("collect.ownerAddress", "team.selfLabel", "team.memberId", "teamServer.displayName",
                  "teams.timeRegex"):
            self.assertEqual(self.reg[k].default, "", k)
        for k in self.reg:
            if k.startswith("privacy.extraCtx."):
                self.assertEqual(self.reg[k].default, [], k)

    def test_no_addresses_or_private_ips_in_text(self):
        text = self.raw.decode("utf-8")
        self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text))
        hits = []
        for mm in re.finditer(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])", text):
            try:
                ip = ipaddress.ip_address(mm.group())
            except ValueError:
                continue
            hits.append(ip)
        allowed = {ipaddress.ip_address(self.reg["team.serverHost"].default),
                   ipaddress.ip_address(self.reg["teamServer.bindHost"].default)}
        self.assertEqual(set(hits) - allowed, set())
        self.assertEqual(len(hits), 2)
        for port in ("8765", "8766", "8767", "9333"):
            self.assertIsNone(re.search(rf"(?<!\d){port}(?!\d)", text), port)

    def test_file_bytes(self):
        raw = self.raw
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        bad = set(range(0, 9)) | {11, 12} | set(range(14, 32))
        self.assertFalse(any(b in bad for b in raw))
        self.assertEqual(self.doc["schema"], C.SCHEMA)
        for meta in self.reg.values():
            self.assertIs(C.registry_meta(meta.key), C.load_registry()[meta.key])


if __name__ == "__main__":
    unittest.main()
