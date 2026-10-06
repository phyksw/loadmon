# -*- coding: utf-8 -*-
"""WP-01 lm27.config — 적재·형 검사·list(+-)·읽힌 키·해시·에이전트 부분집합·fail-closed(계약 §5.1).

입력은 tests\\fixtures\\wp01\\ 의 합성 설정 파일과 이 트리의 config\\settings_registry.json 뿐이다."""
import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from lm27 import config as C

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "wp01"
REG = ROOT / "config" / "settings_registry.json"
ABSENT = FIX / "없는_설정.json"


def load(name=None, **kw):
    return C.load_config(config_path=FIX / name if name else ABSENT, **kw)


def warn_map(cfg):
    out = {}
    for w in cfg.config_warnings:
        out.setdefault(w["key"], []).append(w["code"])
    return out


class DefaultsTest(unittest.TestCase):
    def test_no_config_file_means_all_defaults(self):
        cfg = load()
        reg = C.load_registry()
        self.assertEqual(cfg.config_warnings, [])
        self.assertEqual(cfg.overridden(), [])
        self.assertEqual(sorted(cfg.keys()), sorted(reg))
        for key, meta in reg.items():
            v = cfg.snapshot()[key]
            self.assertEqual(v, meta.default, key)

    def test_paths_like_inputs(self):
        # 경로 문자열·root 속성만 있는 객체·이 트리(None) 모두 같은 레지스트리를 쓴다
        a = C.load_config(str(ROOT), config_path=ABSENT)
        b = C.load_config(type("P", (), {"root": ROOT})(), config_path=ABSENT)
        c = C.load_config(None, config_path=ABSENT)
        self.assertEqual(a.hash(), b.hash())
        self.assertEqual(a.hash(), c.hash())

    def test_mini_root_resolution(self):
        with tempfile.TemporaryDirectory(prefix="lm27t_wp01_") as td:
            cfgdir = Path(td) / "config"
            cfgdir.mkdir()
            shutil.copyfile(FIX / "registry_mini.json", cfgdir / "settings_registry.json")
            shutil.copyfile(FIX / "config_mini.json", cfgdir / "config.json")
            for p in (td, type("P", (), {"root": td})(), type("P", (), {"root": lambda self: td})()):
                cfg = C.load_config(p)
                self.assertEqual(cfg["demo.limitSec"], 45)
                self.assertEqual(cfg["demo.words"], ("가", "나", "다"))
                self.assertEqual(cfg.config_warnings, [])
            if importlib.util.find_spec("lm27.paths") is not None:
                from lm27.paths import Paths
                cfg = C.load_config(Paths(td))
                self.assertEqual(cfg["demo.limitSec"], 45)
            with self.assertRaises(C.UnknownKeyError):
                C.load_config(td)["collect.lookbackDays"]


class StrictReadTest(unittest.TestCase):
    def test_unknown_key_is_error(self):
        cfg = load()
        with self.assertRaises(C.UnknownKeyError) as cm:
            cfg["collect.noSuchKey"]
        self.assertIsInstance(cm.exception, KeyError)
        self.assertIn("collect.noSuchKey", str(cm.exception))
        with self.assertRaises(C.UnknownKeyError):
            C.registry_meta("collect.noSuchKey")
        with self.assertRaises(C.UnknownKeyError):
            cfg.meta("collect.noSuchKey")
        self.assertNotIn("collect.noSuchKey", cfg)
        self.assertIn("collect.lookbackDays", cfg)

    def test_overrides_are_strict(self):
        with self.assertRaises(C.UnknownKeyError):
            load(overrides={"collect.noSuchKey": 1})
        cfg = load("config_mixed.json", overrides={"collect.lookbackDays": 30, "collect.budgetSec": "x"})
        self.assertEqual(cfg["collect.lookbackDays"], 30)
        self.assertEqual(cfg["collect.budgetSec"], 0)
        self.assertIn("bad_type", warn_map(cfg)["collect.budgetSec"])


class MixedConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load("config_mixed.json")
        self.w = warn_map(self.cfg)

    def test_valid_values_apply(self):
        c = self.cfg
        self.assertEqual(c["collect.lookbackDays"], 90)
        self.assertEqual(c["privacy.time.offhoursPrivateBreakMin"], 20)
        self.assertEqual(c["bridge.mode"], "manual")
        self.assertEqual(c["team.serverPort"], 19310)
        self.assertEqual(c["time.window.std"], "08:30-17:30")
        self.assertIsNone(c["time.envelope.mailTimeOffsetH"])
        self.assertIsNone(c["time.attrib.l6MaxRatio"])          # nullable — 무제한

    def test_int_to_float_coercion(self):
        v = self.cfg["bridge.pollSec"]
        self.assertIsInstance(v, float)
        self.assertEqual(v, 2.0)

    def test_type_mismatch_falls_back_with_warning(self):
        c, w = self.cfg, self.w
        expect = {
            "collect.parallelMax": ("bad_type", 2),
            "collect.budgetSec": ("out_of_range", 0),
            "privacy.time.regularPrivateRunMin": ("out_of_range", 30),   # 5의 배수 위반
            "mail.com.readProtected": ("bad_choice", "auto"),
            "ui.openBrowser": ("bad_type", True),                        # 1 은 bool 이 아니다
            "time.slotCoverSec": ("bad_type", 150),                     # null 불가 키
            "collect.ownerAddress": ("bad_pattern", ""),
            "teams.pmWhoKeys": ("bad_item", ()),
            "time.window.lunch": ("bad_pattern", "12:00-13:00"),
            "teams.timeRegex": ("bad_pattern", ""),
        }
        for key, (code, default) in expect.items():
            self.assertIn(code, w.get(key, []), key)
            self.assertEqual(c[key], default, key)

    def test_unknown_keys_ignored_with_warning(self):
        codes = [(x["code"], x["key"]) for x in self.cfg.config_warnings]
        self.assertIn(("unknown_key", "collect.notAKey"), codes)
        self.assertIn(("unknown_key", ""), codes)                      # 표기 위반 키는 키를 싣지 않는다
        self.assertNotIn("collect.notAKey", self.cfg)
        keys = {x["key"] for x in self.cfg.config_warnings}
        self.assertNotIn("_설명", keys)
        self.assertNotIn("schema", keys)

    def test_warnings_carry_no_values(self):
        blob = json.dumps(self.cfg.config_warnings, ensure_ascii=False)
        for secret in ("이것은 주소가 아님", "wXYZ", "12:00~13:00"):
            self.assertNotIn(secret, blob)
        for x in self.cfg.config_warnings:
            self.assertEqual(sorted(x), ["code", "key", "text_ko"])
            self.assertTrue(x["text_ko"])

    def test_overridden_lists_only_effective_changes(self):
        ov = self.cfg.overridden()
        self.assertIn("collect.lookbackDays", ov)
        self.assertNotIn("collect.parallelMax", ov)
        self.assertNotIn("collect.notAKey", ov)
        self.assertEqual(ov, sorted(ov))


class BrokenFileTest(unittest.TestCase):
    def test_bad_files_fall_back_to_defaults(self):
        base = load().hash()
        for name in ("config_broken.json", "config_dupkey.json", "config_nan.json", "config_array.json"):
            cfg = load(name)
            self.assertEqual(cfg.hash(), base, name)
            self.assertEqual([w["code"] for w in cfg.config_warnings], ["bad_file"], name)

    def test_bom_is_accepted_for_reading(self):
        raw = REG.read_bytes()
        self.assertEqual(len(C.parse_registry(b"\xef\xbb\xbf" + raw)), len(C.parse_registry(raw)))

    def test_deep_nesting_is_bad_file_not_crash(self):
        """'[' 10만 개 — RecursionError 로 CLI 전체가 rc 1 이 되지 않고 bad_file 경고 + 모든 기본값."""
        base = load().hash()
        deep = b"[" * 100000 + b"]" * 100000
        with tempfile.TemporaryDirectory(prefix="lm27t_wp01_") as td:
            for i, body in enumerate((deep, b'{"time.tzOffsetMin": ' + deep + b"}")):
                p = Path(td) / f"deep{i}.json"
                p.write_bytes(body)
                cfg = C.load_config(config_path=p)
                self.assertEqual(cfg.hash(), base)
                self.assertEqual([w["code"] for w in cfg.config_warnings], ["bad_file"])
            with self.assertRaises(C.RegistryError):
                C.parse_registry(deep)


class ListAndObjSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load("config_lists.json")
        self.w = warn_map(self.cfg)
        self.reg = C.load_registry()

    def test_add_disable(self):
        base = self.reg["pc.watchExtensions"].default
        got = self.cfg["pc.watchExtensions"]
        self.assertIsInstance(got, tuple)
        self.assertEqual(len(got), len(base) - 2 + 1)
        self.assertNotIn(".bin", got)
        self.assertNotIn(".map", got)
        self.assertEqual(got[-1], ".kicad_wks")
        self.assertEqual(got.count(".pptx"), 1)
        self.assertEqual(list(got[:5]), [x for x in base if x not in (".bin", ".map")][:5])   # 내장 순서 유지

    def test_disable_beats_add(self):
        self.assertEqual(self.cfg["privacy.path.excludeKeywords"], ("가족", "private", "personal"))

    def test_plain_list_replaces_builtin(self):
        self.assertEqual(self.cfg["privacy.window.privateExes"], ("game.exe",))
        self.assertNotIn("proton.me", self.cfg["privacy.personalMailDomains"])
        self.assertEqual(len(self.cfg["privacy.personalMailDomains"]),
                         len(self.reg["privacy.personalMailDomains"].default) - 1)

    def test_bad_list_op_falls_back(self):
        self.assertIn("bad_list_op", self.w["mail.index.excludeFolderNames"])
        self.assertEqual(list(self.cfg["mail.index.excludeFolderNames"]),
                         self.reg["mail.index.excludeFolderNames"].default)

    def test_obj_fixed_keys_shallow_merge(self):
        st = self.cfg["bridge.stages"]
        self.assertTrue(st["lookup_calendar"])
        self.assertFalse(st["review_text"])
        self.assertTrue(st["task_label"])
        self.assertEqual(sorted(st), sorted(self.reg["bridge.stages"].keys))
        dw = self.cfg["hier.domain.w"]
        self.assertEqual(dw["EXT"], 2.5)
        self.assertEqual(dw["COM"], self.reg["hier.domain.w"].default["COM"])

    def test_obj_unknown_subkey_falls_back(self):
        self.assertIn("bad_item", self.w["hier.unit.w"])
        self.assertEqual(self.cfg["hier.unit.w"], self.reg["hier.unit.w"].default)

    def test_obj_free_map_replaces(self):
        self.assertEqual(self.cfg["report.mining.extClassExtra"], {"kicad_pcb": "cad"})

    def test_item_checks(self):
        c, w = self.cfg, self.w
        self.assertEqual(c["team.retryScheduleSec"], (30, 60))
        self.assertEqual(c["team.serverAlternates"], ("teamhost.example:9310",))
        self.assertIn("bad_item", w["teamServer.suggestRanges"])
        self.assertIn("out_of_range", w["hier.domain.order"])
        self.assertIn("bad_choice", w["report.export.formats"])
        self.assertEqual(c["report.export.formats"], ("html", "csv", "json"))
        self.assertEqual(c["privacy.customers"][0]["id"], "C01")
        self.assertIn("bad_item", w["privacy.partners"])
        self.assertEqual(c["privacy.partners"], ())

    def test_values_are_not_shared_state(self):
        d = self.cfg["bridge.stages"]
        d["task_label"] = False
        self.assertTrue(self.cfg["bridge.stages"]["task_label"])
        lst = self.cfg["privacy.customers"]
        with self.assertRaises(TypeError):
            lst[0] = None                                              # 튜플 — 바꿀 수 없다
        m = C.registry_meta("pc.watchExtensions")
        before = copy.deepcopy(m.default)
        load("config_lists.json")["pc.watchExtensions"]
        self.assertEqual(m.default, before)


class UsedHashSubsetTest(unittest.TestCase):
    def test_used_records_reads_only(self):
        cfg = load("config_mixed.json")
        self.assertEqual(cfg.used(), {})
        cfg["collect.lookbackDays"]
        cfg["pc.watchExtensions"]
        cfg.snapshot()
        cfg.hash()
        cfg.agent_subset()
        used = cfg.used()
        self.assertEqual(list(used), ["collect.lookbackDays", "pc.watchExtensions"])
        self.assertEqual(used["collect.lookbackDays"], 90)
        self.assertIsInstance(used["pc.watchExtensions"], list)
        json.dumps(used, ensure_ascii=False, allow_nan=False)

    def test_hash_is_canonical_and_deterministic(self):
        a, b = load("config_mixed.json"), load("config_mixed.json")
        self.assertEqual(a.hash(), b.hash())
        self.assertRegex(a.hash(), r"^[0-9a-f]{16}$")
        body = json.dumps(a.snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.assertEqual(a.hash(), hashlib.sha256(body.encode("utf-8")).hexdigest()[:16])
        self.assertNotEqual(a.hash(), load().hash())
        sub = ["time.slotCoverSec", "collect.lookbackDays"]
        self.assertEqual(a.hash(sub), a.hash(list(reversed(sub))))
        self.assertEqual(a.hash(sub), a.hash(dict.fromkeys(sub, 0)))
        self.assertNotEqual(a.hash(sub), load().hash(sub))
        self.assertEqual(a.hash(["time.slotCoverSec"]), load().hash(["time.slotCoverSec"]))
        with self.assertRaises(C.UnknownKeyError):
            a.hash(["collect.noSuchKey"])

    def test_owner_rx_script_names(self):
        """owner·readers 표기(계약 §5.1-11) — 파이썬 탐침 스크립트 이름의 밑줄(probe_owa.py 등, §2.17)도 받는다(통합)."""
        for ok in ("lm27.collect.run", "collect/Get-OutlookIndex.ps1", "collect/probe_owa.py", "collect/agent/harvest.ps1"):
            self.assertRegex(ok, C.OWNER_RX)
        for bad in ("collect/../x.py", "collect/_x.py", "collect/a b.py", "tools/x.py", "lm27.Collect"):
            self.assertIsNone(C.OWNER_RX.match(bad), bad)
        reg = C.load_registry()
        self.assertIn("collect/probe_owa.py", reg["probe.budgetSec"].readers)
        self.assertIn("collect/Get-OutlookIndex.ps1", reg["collect.lookbackDays"].readers)
        self.assertEqual((reg["collect.sinceYearStart"].scope, reg["collect.sinceYearStart"].restart), ("agent", "agent"))
        self.assertIn("collect.sinceYearStart", load().agent_subset())          # 에이전트 수확 창(V6 — 통합)

    def test_agent_subset_matches_contract_rule(self):
        cfg = load("config_mixed.json")
        sub = cfg.agent_subset()
        self.assertEqual(cfg.used(), {})
        for k in C.AGENT_SUBSET_KEYS:
            self.assertIn(k, sub)
        for k in cfg.keys():
            agent = k.startswith(("agent.", "pc.", "teams.uia.")) or k in C.AGENT_SUBSET_KEYS
            self.assertEqual(k in sub, agent, k)
            self.assertEqual(cfg.meta(k).scope == "agent", agent, k)
        self.assertEqual(sub["collect.lookbackDays"], 90)
        self.assertNotIn("privacy.customers", sub)
        self.assertNotIn("teams.timeRegex.x", sub)
        self.assertEqual(list(sub), sorted(sub))
        json.dumps(sub, ensure_ascii=False, allow_nan=False)


class DeriveAndCheckTest(unittest.TestCase):
    def test_derive(self):
        base = load("config_mixed.json")
        base["collect.lookbackDays"]
        h0 = base.hash()
        d = base.derive({"time.slotCoverSec": 200, "collect.parallelMax": 4, "collect.lookbackDays": "x"})
        self.assertEqual(base.hash(), h0)
        self.assertEqual(d.used(), {})
        self.assertEqual(d["time.slotCoverSec"], 200)
        self.assertEqual(d["collect.parallelMax"], 4)
        self.assertNotIn("collect.parallelMax", warn_map(d))           # 덮어쓴 키의 옛 경고는 사라진다
        self.assertEqual(d["collect.lookbackDays"], 120)
        self.assertIn("bad_type", warn_map(d)["collect.lookbackDays"])
        self.assertEqual(d["bridge.mode"], "manual")                    # config.json 값은 유지
        with self.assertRaises(C.UnknownKeyError):
            base.derive({"collect.noSuchKey": 1})

    def test_derive_perturbation_changes_hash(self):
        cfg = load()
        for key in ("time.envelope.sessionGapMin", "hier.unit.confirm", "report.peers.topN"):
            m = cfg.meta(key)
            v = m.default + (1 if m.type == "int" else 0.05)
            self.assertNotEqual(cfg.derive({key: v}).hash(), cfg.hash(), key)

    def test_check_value(self):
        self.assertIsNone(C.check_value("team.serverPort", 9311))
        self.assertIsNotNone(C.check_value("team.serverPort", 70000))
        self.assertIsNotNone(C.check_value("team.serverPort", "9311"))
        self.assertIsNone(C.check_value("pc.watchExtensions", {"add": [".abc"]}))
        self.assertIsNotNone(C.check_value("pc.watchExtensions", {"add": ["abc"]}))
        self.assertIsNone(C.check_value("time.window.night", "22:00-06:00"))
        self.assertIsNotNone(C.check_value("time.window.night", "25:00-06:00"))
        self.assertIsNotNone(C.check_value("teamServer.uploadTokenSha256", "abc"))
        self.assertIsNone(C.check_value("teamServer.uploadTokenSha256", "0" * 64))
        self.assertIsNotNone(C.check_value("privacy.allowPatterns", [".*"]))      # 빈 문자열에 맞는 정규식
        self.assertIsNone(C.check_value("privacy.allowPatterns", [r"DWG-\d{4}"]))
        reason = C.check_value("collect.ownerAddress", "주소아님")
        self.assertIsInstance(reason, str)
        self.assertNotIn("주소아님", reason)
        with self.assertRaises(C.UnknownKeyError):
            C.check_value("collect.noSuchKey", 1)


class RegistryFailClosedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(REG.read_text(encoding="utf-8"))

    def mutate(self, fn):
        d = copy.deepcopy(self.doc)
        fn(d)
        return json.dumps(d, ensure_ascii=False).encode("utf-8")

    def assertRejects(self, fn):
        with self.assertRaises(C.RegistryError):
            C.parse_registry(self.mutate(fn))

    def test_real_registry_parses(self):
        self.assertEqual(len(C.parse_registry(REG.read_bytes())), len(self.doc["keys"]))

    def test_missing_or_broken_registry(self):
        with self.assertRaises(C.RegistryError):
            C.load_registry(FIX / "없는_레지스트리.json")
        with self.assertRaises(C.RegistryError):
            C.load_config(registry_path=FIX / "config_broken.json", config_path=ABSENT)
        with self.assertRaises(C.RegistryError):
            C.parse_registry(b'{"schema": "other/1", "keys": {}}')

    def test_declaration_rules(self):
        k = "collect.lookbackDays"
        self.assertRejects(lambda d: d["keys"].__setitem__("collect.lookback_days", d["keys"][k]))   # snake_case
        self.assertRejects(lambda d: d["keys"][k].pop("help_ko"))
        self.assertRejects(lambda d: (d["keys"][k].pop("range"), d["keys"][k].pop("choices")))
        self.assertRejects(lambda d: d["keys"][k].__setitem__("default", 0))                           # 범위 밖
        self.assertRejects(lambda d: d["keys"][k].__setitem__("scope", "personal"))                    # §5.1-8 불일치
        self.assertRejects(lambda d: d["keys"][k].__setitem__("type", "number"))
        self.assertRejects(lambda d: d["keys"][k].__setitem__("owner", "lm26.x"))
        self.assertRejects(lambda d: d["keys"][k].__setitem__("extra", 1))
        self.assertRejects(lambda d: d["keys"]["bridge.pollSec"].__setitem__("default", 3))           # float 정규형
        self.assertRejects(lambda d: d["keys"]["team.selfLabel"].__setitem__("secret", True))
        self.assertRejects(lambda d: d["keys"]["bridge.stages"]["default"].pop("task_label"))
        self.assertRejects(lambda d: d["keys"]["mm.denominator"].__setitem__("default", "days"))


class PerformanceTest(unittest.TestCase):
    def test_load_and_read_fast(self):
        from tests.fixtures.tree import best_of                 # 부하에 민감 — 여러 번 재서 최솟값(W1 통합 창 R8)

        def run():
            cfg = C.load_config(config_path=FIX / "config_lists.json")
            for _ in range(20000):
                cfg["time.slotCoverSec"]
                cfg["pc.watchExtensions"]
        self.assertLess(best_of(run, under=3.0), 3.0)


if __name__ == "__main__":
    unittest.main()
