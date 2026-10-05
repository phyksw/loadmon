# -*- coding: utf-8 -*-
"""WP-23 설정 한 벌(B §3, 계약 §5.2 bridge.*) — 기본값·일관성 되돌림·G-B3 키 대조·사다리 시간 공식."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from lm27.bridge import settings as S
from lm27.config import load_config
from lm27.paths import Paths

from tests.bridge.fake_http import REGISTRY, bridge_settings


class SettingsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_bset_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, overrides=None):
        return bridge_settings(self.tmp, overrides)


class TestDefaults(SettingsBase):
    def test_defaults_match_registry(self):
        s = self.load()
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))["keys"]
        self.assertEqual(s.mode, reg["bridge.mode"]["default"])
        self.assertEqual(s.edge.port, reg["bridge.edge.port"]["default"])
        self.assertEqual(s.edge.port_tries, reg["bridge.edge.portTries"]["default"])
        self.assertEqual(s.input_max_chars, reg["bridge.inputMaxChars"]["default"])
        self.assertEqual(s.answer_max_chars, reg["bridge.answerMaxChars"]["default"])
        self.assertEqual(s.reply_timeout_sec, reg["bridge.replyTimeoutSec"]["default"])
        self.assertEqual(s.first_token_sec, reg["bridge.firstTokenSec"]["default"])
        self.assertEqual(list(s.dom.work_labels), reg["bridge.dom.workModeLabels"]["default"]["work"])
        self.assertEqual(s.confirm_ttl_days, reg["collect.confirmTtlDays"]["default"])
        self.assertEqual(s.warnings, ())

    def test_stage_switches(self):
        s = self.load()
        self.assertFalse(s.stage_on("lookup_calendar"))
        self.assertTrue(s.stage_on("task_label"))
        self.assertTrue(s.stage_on("no_such_stage"))
        self.assertEqual(set(s.stages_map()), set(S.STAGE_IDS))
        s2 = self.load({"bridge.stages": {"speech_act": False}})
        self.assertFalse(s2.stage_on("speech_act"))
        self.assertTrue(s2.stage_on("task_label"))

    def test_ports_and_profile_dir(self):
        s = self.load()
        self.assertEqual(list(s.ports()), list(range(9343, 9343 + 10)))
        p = Paths(os.path.join(self.tmp, "root"), lad=os.path.join(self.tmp, "lad"))
        self.assertEqual(s.profile_dir(p), Path(p.edge_profile()))
        s2 = self.load({"bridge.edge.profileDir": os.path.join(self.tmp, "prof")})
        self.assertEqual(s2.profile_dir(p), Path(os.path.join(self.tmp, "prof")))

    def test_rung_timeouts_one_formula(self):
        s = self.load()
        self.assertEqual(s.rung_timeouts(0), (480.0, 180.0))
        self.assertEqual(s.rung_timeouts(1), (240.0, 90.0))
        self.assertEqual(s.rung_timeouts(2), (240.0, 90.0))
        s2 = self.load({"bridge.replyTimeoutSec": 200, "bridge.firstTokenSec": 40})
        self.assertEqual(s2.rung_timeouts(1), (float(S.RUNG_REPLY_FLOOR_S), float(S.RUNG_FIRST_FLOOR_S)))

    def test_model_for(self):
        s = self.load()
        self.assertEqual(s.model_for("fast"), s.model_fast)
        self.assertEqual(s.model_for("deep"), s.model_deep)
        self.assertEqual(s.model_for("fallback"), s.model_fallback)
        self.assertEqual(s.model_for("?"), "")


class TestConsistency(SettingsBase):
    """범위 밖·키끼리 어긋남은 기본값 + 경고 1건, 실행은 막지 않는다(B §3)."""

    def codes(self, s):
        return {(w["code"], w["key"]) for w in s.warnings}

    def test_out_of_range_reverts_with_warning(self):
        s = self.load({"bridge.pollSec": 99.0})
        self.assertEqual(s.poll_sec, 3.0)
        self.assertTrue(any(w["key"] == "bridge.pollSec" for w in s.warnings))

    def test_circuit_order(self):
        s = self.load({"bridge.circuitSoft": 10, "bridge.circuitAbort": 5})
        self.assertEqual((s.circuit_soft, s.circuit_abort), (3, 6))
        self.assertIn(("inconsistent", "bridge.circuitAbort"), self.codes(s))

    def test_https_only(self):
        s = self.load({"bridge.url": "http://m365.cloud.microsoft/chat"})
        self.assertTrue(s.url.startswith("https://"))
        s2 = self.load({"bridge.chatUrlPrefixes": ["http://insecure.example/"]})
        self.assertTrue(all(p.startswith("https://") for p in s2.chat_url_prefixes))
        self.assertTrue(any(k == "bridge.chatUrlPrefixes" for _c, k in self.codes(s2)))

    def test_window_size_and_lookup_window(self):
        s = self.load({"bridge.edge.windowSize": "big"})
        self.assertEqual(s.window_wh(), (1150, 900))
        s2 = self.load({"bridge.lookup.windowDays": 3, "bridge.lookup.minWindowDays": 5})
        self.assertLessEqual(s2.lookup.min_window_days, s2.lookup.window_days)

    def test_login_hosts_valid_or_default(self):
        s = self.load({"bridge.loginHosts": ["login.example.com"]})
        self.assertEqual(s.login_hosts, ("login.example.com",))
        for bad in (["bad host/x"], ["Login.Example.COM"]):
            s2 = self.load({"bridge.loginHosts": bad})
            self.assertIn("login.microsoftonline.com", s2.login_hosts)
            self.assertTrue(any(k == "bridge.loginHosts" for _c, k in self.codes(s2)))


class TestRegistryCoverage(SettingsBase):
    """G-B3: 레지스트리의 모든 bridge.* 키가 읽히고, 읽는 키는 모두 레지스트리에 있다(죽은 키·유령 키 0)."""

    def test_keys_table_equals_registry(self):
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))["keys"]
        bridge_reg = {k for k in reg if k.startswith("bridge.")}
        table = {k for k, _ in S.KEYS}
        self.assertEqual(bridge_reg, {k for k in table if k.startswith("bridge.")})
        self.assertTrue(table <= set(reg), sorted(table - set(reg)))

    def test_from_cfg_reads_every_key(self):
        cfg = load_config(registry_path=REGISTRY, config_path=Path(self.tmp) / "none.json")
        S.from_cfg(cfg)
        used = set(cfg.used())
        for k, _attr in S.KEYS:
            self.assertIn(k, used)

    def test_attr_paths_exist(self):
        s = self.load()
        for _k, attr in S.KEYS:
            obj = s
            for part in attr.split("."):
                if part == "work_mode_labels":
                    self.assertTrue(obj.work_labels and obj.web_labels)
                    break
                self.assertTrue(hasattr(obj, part), attr)
                obj = getattr(obj, part)

    def test_frozen(self):
        s = self.load()
        with self.assertRaises(AttributeError):
            s.mode = "off"      # type: ignore[misc]
        s2 = s.replace(mode="manual")
        self.assertEqual((s.mode, s2.mode), ("auto", "manual"))


if __name__ == "__main__":
    unittest.main()
