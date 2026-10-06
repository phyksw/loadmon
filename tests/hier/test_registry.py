# -*- coding: utf-8 -*-
"""WP-21 유효 레지스트리 시험 — H §3 · §2.5 · T-H01~T-H04 · T-H20 · 계약 §3.19 · §3.20 · X-237 · X-238 · X-247.

- merge: 내장 ⊕ 팀 ⊕ 개인 로컬(예약 주입·overlays·개인 과제 대응·어휘·규칙·never_pairs·domain_meta).
- load_effective: 서버(가짜 fetch) → 304 캐시 → 오프라인 사본 → 캐시 → 내장, 개인 로컬·.bak, 자동 대응 기록.
시험 트리는 %TEMP% 아래 임시 폴더(lm27t_ 접두)에만 만든다. 키링 대신 가짜 폴더 키·문서군 키 함수를 주입한다.
"""
import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lm27.config import load_config
from lm27.hier import registry as R
from lm27.hier import vocab as V
from lm27.hier.names import ukey
from lm27.paths import Paths
from lm27.util import fsx

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "wp21"
SETTINGS = ROOT / "config" / "settings_registry.json"
CAL = ROOT / "config" / "calendar.json"
PK = "p_7fa3c2d19e01"
NOW = datetime(2026, 10, 5, 3, 0, 0, tzinfo=UTC)


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def fake_folder(seg):
    return "s" + hashlib.sha256(("dir|seg:" + R.seg_norm(seg)).encode("utf-8")).hexdigest()[:16]


def fake_doc(name):
    return "d" + hashlib.sha256(("doc|" + str(name)).encode("utf-8")).hexdigest()[:16]


def make_cfg(tmp, over=None):
    return load_config(registry_path=SETTINGS, config_path=Path(tmp) / "none.json", overrides=over or {})


def team_with(projects, version=7, **extra):
    t = {"schema": "lm27.registry/1", "version": version, "projects": projects}
    t.update(extra)
    return t


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lm27t_wp21_"))
        self.cfg = make_cfg(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class GoldenMergeTest(_Tmp):
    def setUp(self):
        super().setUp()
        self.reg = R.merge(load("registry_golden.json"), None, self.cfg)

    def test_reserved_injected(self):
        for pid, dom in V.RESERVED.items():
            p = self.reg.projects[pid]
            self.assertEqual((p.origin, p.domain, p.name, p.copilot_desc),
                             ("reserved", dom, V.reserved_name(pid), V.reserved_desc(pid)))
        self.assertTrue(self.reg.is_reserved("P-9904"))

    def test_alias_index(self):
        ix = self.reg.alias_ix
        self.assertEqual(ix[ukey("PROJ-A")], "P-0007")
        self.assertEqual(ix[ukey("과제A 모듈")], "P-0007")
        self.assertEqual(ix[ukey("PROJ-E")], "P-0007")          # 퇴역·병합 과제의 코드네임 → 대표
        self.assertEqual(ix[ukey("과제E")], "P-0007")
        self.assertEqual(ix[ukey("PROJ-B")], "P-0008")
        for pid in V.RESERVED:
            self.assertNotIn(ukey(V.reserved_name(pid)), ix)

    def test_resolve_domain_active(self):
        r = self.reg
        self.assertEqual(r.resolve("P-0013"), "P-0007")
        self.assertEqual(r.resolve("P-0500"), "P-0500")
        self.assertIsNone(r.resolve(None))
        self.assertEqual(r.domain_of("P-0013"), "DEV")
        self.assertEqual(r.domain_of("P-9904"), "COM")
        self.assertEqual(r.domain_of(None), "UNC")
        self.assertEqual(r.domain_of("P-0500"), "UNC")
        self.assertEqual(r.domain_of("pr_3"), "UNC")
        self.assertEqual(r.active_ids(), ["P-0007", "P-0008", "P-0011", "P-0012"])
        self.assertEqual(r.name_of("P-0013"), "과제A")
        self.assertEqual(r.name_of("P-9901"), V.reserved_name("P-9901"))
        self.assertEqual(r.version, 7)
        self.assertEqual(r.source, "team")

    def test_resolve_cycle_picks_min(self):
        pv = R.ProjectView
        views = {"P-0003": pv("P-0003", "c", "DEV", "active", "P-0004", "team"),
                 "P-0004": pv("P-0004", "d", "DEV", "active", "P-0005", "team"),
                 "P-0005": pv("P-0005", "e", "DEV", "active", "P-0003", "team"),
                 "P-0001": pv("P-0001", "a", "DEV", "active", "P-0004", "team")}
        self.assertEqual(R._resolve_in(views, "P-0001"), "P-0003")
        self.assertEqual(R._resolve_in(views, "P-0005"), "P-0003")

    def test_privacy_dict(self):
        cfg = make_cfg(self.tmp, {"privacy.customers": [{"id": "C02", "names": ["고객사B"], "domains": []}],
                                  "privacy.internalDomains": ["mail.example.com"]})
        team = load("registry_golden.json")
        team["projects"][2]["mask_name"] = True
        team["projects"][2]["aliases"] = ["메일분류기"]
        reg = R.merge(team, None, cfg)
        d = reg.privacy_dict()
        got = {p["id"]: p["codenames"] for p in d["projects"]}
        self.assertEqual(got, {"P-0007": ["PROJ-A"], "P-0008": ["PROJ-B"], "P-0011": ["과제C", "메일분류기"],
                               "P-0013": ["PROJ-E"]})
        self.assertEqual([c["id"] for c in d["customers"]], ["C01", "C02"])
        self.assertIn("mail.example.com", d["internal_domains"])
        self.assertNotIn("pepper", json.dumps(d))


class OverlayLocalTest(_Tmp):
    def merged(self, team=None, local=None, **kw):
        kw.setdefault("folder_key", fake_folder)
        kw.setdefault("doc_key", fake_doc)
        return R.merge(load("registry_example.json") if team is None else team,
                       load("local_example.json") if local is None else local, self.cfg, **kw)

    def test_example_merge(self):
        reg = self.merged()
        p7 = reg.projects["P-0007"]
        self.assertIn("A모듈", p7.aliases)
        self.assertIn("광축", p7.keywords)
        self.assertEqual(p7.folder_keys, {fake_folder("과제A_설계"), fake_folder("A_시험")})
        self.assertEqual(p7.shared_fams, {fake_doc("팀공용_마스터")})
        self.assertEqual(p7.default_field, "OPT")
        self.assertEqual(p7.period, ("2026-01", ""))
        self.assertEqual(p7.adopted, ((PK, "pr_3"),))
        self.assertEqual(reg.folder_ix[fake_folder("A_시험")], "P-0007")
        self.assertEqual(reg.root_ix, {"R03": "P-0007"})
        l1 = reg.projects["L-0001"]
        self.assertEqual((l1.origin, l1.proposal_id, l1.maps_to), ("local", "pr_2", None))
        self.assertIn("L-0001", reg.active_ids())
        self.assertEqual(reg.alias_ix[ukey("PROJ-X")], "L-0001")
        self.assertEqual(reg.team_code("fields", "L_PHOTO"), "OPT")
        self.assertEqual(reg.vocab["fields"]["PHOTONICS"].origin, "team")
        self.assertEqual(reg.vocab["fields"]["L_PHOTO"].origin, "local")
        self.assertEqual(reg.vocab_codes("fields")[-2:], ["PHOTONICS", "L_PHOTO"])
        com = reg.domain_kw["COM"]
        self.assertEqual(sum(1 for k in com if ukey(k) == ukey("팀 워크숍")), 1)
        self.assertNotIn("교정", com)
        self.assertIn("검교정", com)
        self.assertIn("기술자문", reg.domain_kw["EXT"])
        self.assertEqual(V.domain_keywords("EXT", reg), reg.domain_kw["EXT"])
        self.assertIn(frozenset((ukey("과제A 후속"), ukey("과제A"))), reg.never_pairs)
        self.assertIn(frozenset((ukey("광센서 선행"), ukey("광센서 양산"))), reg.never_pairs)
        self.assertEqual([r.id for r in reg.rules], ["TR001", "TR002", "TR003"])
        self.assertEqual(reg.rules[0].cond, ("token", "광정렬"))
        self.assertEqual(reg.rules[0].then, ("project", "P-0007"))
        self.assertEqual(reg.rules[1].w, 1.0)
        self.assertEqual([a.id for a in reg.agents], ["AG003"])
        self.assertEqual(reg.agents[0].step_types, ("DOC_DOC",))
        self.assertEqual(reg.catalog_version, "ag-3")
        self.assertEqual(set(reg.agent_axes), {"X1", "X2"})
        self.assertEqual(reg.person, {"default_field": "OPT", "default_func": ""})
        self.assertEqual(reg.codename_review["ignored"], ["3f9a1c2e"])
        self.assertEqual(reg.pepper_id, "9f2c01ab")
        self.assertFalse(hasattr(reg, "pepper"))                      # X-238: 분류기는 pepper 를 들고 다니지 않는다
        self.assertNotIn("ab" * 32, json.dumps(R._hash_payload(reg), ensure_ascii=False))

    def test_overlay_alias_conflict_and_default_field(self):
        local = load("local_example.json")
        local["overlays"] = {"P-0007": {"aliases": ["과제B"], "default_field": "MECH"},
                             "P-0008": {"default_field": "MECH"}, "P-0099": {"keywords": ["광축"]}}
        reg = self.merged(local=local)
        self.assertNotIn("과제B", reg.projects["P-0007"].aliases)
        self.assertEqual(reg.alias_ix[ukey("과제B")], "P-0008")
        self.assertIn("local_alias_conflict:overlays.P-0007", reg.warnings)
        self.assertEqual(reg.projects["P-0007"].default_field, "OPT")      # 팀 값이 있으면 팀
        self.assertEqual(reg.projects["P-0008"].default_field, "MECH")     # 팀 값이 비면 개인
        self.assertIn("overlay_unknown:overlays.P-0099", reg.warnings)

    def test_overlay_alias_blanks_desc(self):
        local = load("local_example.json")
        local["overlays"] = {"P-0007": {"aliases": ["광학 모듈"]}}
        reg = self.merged(local=local)
        self.assertEqual(reg.projects["P-0007"].copilot_desc, "")
        self.assertIn("desc_has_codename:projects.P-0007", reg.warnings)

    def test_t_h03_auto_map_by_alias(self):
        team = team_with([{"id": "P-0021", "name": "광센서 모듈", "domain": "MP", "aliases": ["광센서 선행"]}])
        reg = self.merged(team=team)
        self.assertEqual(reg.projects["L-0001"].maps_to, "P-0021")
        self.assertEqual(reg.local_maps, {"L-0001": "P-0021"})
        self.assertEqual(reg.resolve("L-0001"), "P-0021")
        self.assertEqual(reg.domain_of("L-0001"), "MP")
        self.assertNotIn("L-0001", reg.active_ids())
        self.assertEqual(reg.alias_ix[ukey("광센서 선행")], "P-0021")
        self.assertEqual(reg.alias_ix[ukey("PROJ-X")], "P-0021")
        self.assertIn("local_auto_mapped:projects.L-0001", reg.warnings)
        local = load("local_example.json")
        local["projects"][0]["maps_to"] = "P-0021"
        again = self.merged(team=team, local=local)
        self.assertEqual(again.local_maps, {})                              # 이미 기록된 대응은 새 대응이 아니다
        self.assertEqual(again.resolve("L-0001"), "P-0021")

    def test_t_h04_adopted(self):
        team = team_with([{"id": "P-0021", "name": "열관리 모듈", "domain": "DEV",
                           "adopted": [{"person_key": PK, "proposal_id": "pr_3"}]},
                          {"id": "P-0022", "name": "다른 과제", "domain": "DEV"}])
        local = {"schema": "lm27.registry_local/1",
                 "projects": [{"id": "L-0002", "name": "방열 모듈 선행", "domain": "DEV", "proposal_id": "pr_3",
                               "maps_to": "P-0022"}]}
        reg = self.merged(team=team, local=local, person_key=PK)
        self.assertEqual(reg.resolve("L-0002"), "P-0021")                  # 팀 adopted 가 파일 maps_to 를 이긴다
        self.assertEqual(reg.local_maps, {"L-0002": "P-0021"})
        other = self.merged(team=team, local=local, person_key="p_000000000000")
        self.assertEqual(other.resolve("L-0002"), "P-0022")
        self.assertEqual(other.local_maps, {})

    def test_maps_to_missing_and_alias_conflict_after_map(self):
        team = team_with([{"id": "P-0021", "name": "광센서 선행", "domain": "DEV"},
                          {"id": "P-0007", "name": "과제A", "domain": "DEV"}])
        local = {"schema": "lm27.registry_local/1",
                 "projects": [{"id": "L-0001", "name": "광센서 선행", "domain": "DEV", "aliases": ["과제A"]},
                              {"id": "L-0003", "name": "별도 선행", "domain": "AX", "maps_to": "P-0099"}]}
        reg = self.merged(team=team, local=local)
        self.assertEqual(reg.resolve("L-0001"), "P-0021")
        self.assertEqual(reg.projects["L-0001"].aliases, ())
        self.assertIn("local_alias_conflict:projects.L-0001", reg.warnings)
        self.assertIn("maps_to_missing:projects.L-0003", reg.warnings)
        self.assertIsNone(reg.projects["L-0003"].maps_to)
        self.assertIn("L-0003", reg.active_ids())
        self.assertEqual(reg.domain_of("L-0003"), "AX")

    def test_local_vocab_conflict(self):
        team = load("registry_example.json")
        team["vocab"]["fields"].append({"code": "L_PHOTO", "name": "팀 포토"})
        reg = self.merged(team=team)
        self.assertEqual(reg.vocab["fields"]["L_PHOTO"].origin, "team")
        self.assertIn("local_vocab_conflict:vocab_add.fields.L_PHOTO", reg.warnings)

    def test_local_reserved_and_rejected(self):
        local = {"schema": "lm27.registry_local/1",
                 "projects": [{"id": "P-9901", "name": "x예약", "domain": "DEV"}]}
        reg = self.merged(local=local)
        self.assertEqual(reg.projects["P-9901"].origin, "reserved")       # G-H6: 개인 파일의 예약 ID 는 무시
        self.assertTrue(any(w.startswith("local.reserved_id") for w in reg.warnings))
        bad = self.merged(local={"schema": "x"})
        self.assertIn("local_rejected", bad.warnings)
        self.assertNotIn("L-0001", bad.projects)


class VocabDomainRulesTest(_Tmp):
    def test_vocab_merge_and_read_code(self):
        team = team_with([], vocab={"fields": [
            {"code": "MECH", "name": "기구부", "keywords": ["하우징2"]},
            {"code": "ELEC", "name": "회로", "status": "retired", "replaced_by": "SW"},
            {"code": "REL", "name": "신뢰성", "status": "retired"},
            "광학검사"]})
        reg = R.merge(team, None, self.cfg)
        mech = reg.vocab["fields"]["MECH"]
        self.assertEqual(mech.name, "기구부")
        self.assertIn("하우징", mech.keywords)
        self.assertIn("하우징2", mech.keywords)
        self.assertIn(".sldprt", mech.exts)
        self.assertEqual(reg.read_code("fields", "ELEC"), "SW")
        self.assertEqual(reg.read_code("fields", "REL"), "ETC")
        self.assertEqual(reg.read_code("fields", "NOPE"), "ETC")
        self.assertEqual(reg.read_code("activity_types", "NOPE"), "OFFICE")
        self.assertEqual(reg.read_code("fields", "OPT"), "OPT")
        self.assertNotIn("ELEC", reg.vocab_codes("fields"))
        self.assertIn("ELEC", reg.vocab_codes("fields", include_retired=True))
        self.assertEqual(reg.vocab["fields"]["X_E42E7B"].origin, "legacy")
        self.assertEqual(reg.vocab["fields"]["X_E42E7B"].name, "광학검사")
        self.assertTrue(any(w.startswith("vocab_legacy_string") for w in reg.warnings))
        self.assertEqual(reg.team_code("fields", "ELEC"), "SW")
        self.assertEqual(len(reg.vocab["step_types"]), 22)
        self.assertEqual(len(reg.vocab["activity_types"]), 7)

    def test_local_code_without_maps_to(self):
        local = {"schema": "lm27.registry_local/1",
                 "vocab_add": {"functions": [{"code": "L_SCRIPT", "name": "스크립트"}]}}
        reg = R.merge(None, local, self.cfg)
        self.assertEqual(reg.team_code("functions", "L_SCRIPT"), "ETC")

    def test_domain_desc_overrides(self):
        team = team_with([], domain_meta={"EXT": {"desc": "대외 지원 업무 전반"}})
        local = {"schema": "lm27.registry_local/1", "domain_meta": {"COM": {"desc": "팀 살림"}}}
        reg = R.merge(team, local, self.cfg)
        self.assertEqual(V.domain_desc("EXT", reg), "대외 지원 업무 전반")
        self.assertEqual(V.domain_desc("COM", reg), "팀 살림")
        self.assertEqual(V.domain_desc("DEV", reg), V.DOMAIN_META["DEV"]["desc"])

    def test_rules_team_and_learned(self):
        team = team_with([{"id": "P-0007", "name": "과제A", "domain": "DEV"}], rules=[
            {"id": "TR001", "if": {"token": "광정렬"}, "then": {"project": "P-0007"}},
            {"id": "TR002", "if": {"app": "zemax"}, "then": {"field": "OPT"}, "status": "off"}])
        learned = [{"id": "LK-conv-t0123", "if": {"conv": "t0123456789abcdef"}, "then": {"project": "P-0007"},
                    "status": "active", "support": 1},
                   {"id": "LT-1a2b3c4d", "if": {"token": "광정렬"}, "then": {"project": "P-0007"},
                    "status": "candidate"},
                   {"id": "LT-bad", "if": {}, "then": {}, "status": "active"}]
        reg = R.merge(team, None, self.cfg, learned=learned)
        self.assertEqual([(r.id, r.origin) for r in reg.rules], [("TR001", "team"), ("LK-conv-t0123", "learned")])
        self.assertIsNone(reg.rules[0].w)
        self.assertEqual(reg.rules[1].cond, ("conv", "t0123456789abcdef"))
        self.assertIn("learned_rule_bad", reg.warnings)

    def test_public_suffix_sources(self):
        reg = R.merge(load("registry_golden.json"), None, self.cfg)
        self.assertEqual(reg.public_suffix, dict(self.cfg["hier.publicDomainClasses"]))
        team = load("registry_golden.json")
        team["public_domain_classes"] = {".example": "공공"}
        self.assertEqual(R.merge(team, None, self.cfg).public_suffix, {".example": "공공"})
        self.assertEqual(R.merge(load("registry_golden.json"), None, None).public_suffix, {})


class KeysAndHashTest(_Tmp):
    def test_seg_norm(self):
        self.assertEqual(R.seg_norm("  과제A_설계 "), "과제a_설계")
        self.assertEqual(R.seg_norm("A-시험.v2"), "a_시험_v2")
        self.assertEqual(R.seg_norm("__X  Y__"), "x_y")

    def test_folders_need_keyring(self):
        reg = R.merge(load("registry_golden.json"), None, self.cfg)
        self.assertEqual(reg.folder_ix, {})
        self.assertIn("no_keyring:folders", reg.warnings)
        reg2 = R.merge(load("registry_golden.json"), None, self.cfg, folder_key=fake_folder)
        self.assertEqual(reg2.folder_ix, {fake_folder("과제A_설계"): "P-0007"})
        self.assertNotIn("no_keyring:folders", reg2.warnings)

    def test_folder_conflict_first_wins(self):
        team = team_with([{"id": "P-0001", "name": "과제A", "domain": "DEV", "folders": ["공용_설계"]},
                          {"id": "P-0002", "name": "과제B", "domain": "MP", "folders": ["공용-설계"]}])
        reg = R.merge(team, None, self.cfg, folder_key=fake_folder)
        self.assertEqual(reg.folder_ix, {fake_folder("공용_설계"): "P-0001"})
        self.assertIn("folder_conflict:projects.P-0002", reg.warnings)

    def test_hash_deterministic_and_scoped(self):
        team = load("registry_example.json")
        a = R.merge(team, None, self.cfg, folder_key=fake_folder, doc_key=fake_doc)
        b = R.merge(copy.deepcopy(team), None, self.cfg, folder_key=fake_folder, doc_key=fake_doc)
        self.assertEqual(a.hier_hash, b.hier_hash)
        self.assertEqual(R.hier_hash(a), a.hier_hash)
        self.assertRegex(a.hier_hash, r"^[0-9a-f]{16}$")
        t2 = copy.deepcopy(team)
        t2["projects"][0]["note"] = "메모 바꿈"
        t2["projects"][0]["created_at"] = "2026-04-01"
        t2["updated_at"] = "2026-10-06T09:00:00+09:00"
        t2["never_pairs"] = [["과제A", "과제A 후속"]]
        self.assertEqual(R.merge(t2, None, self.cfg, folder_key=fake_folder, doc_key=fake_doc).hier_hash,
                         a.hier_hash)
        t3 = copy.deepcopy(team)
        t3["projects"][0]["keywords"].append("광축")
        self.assertNotEqual(R.merge(t3, None, self.cfg, folder_key=fake_folder, doc_key=fake_doc).hier_hash,
                            a.hier_hash)

    def test_t_h20_domain_change(self):
        v7 = load("registry_golden.json")
        v8 = copy.deepcopy(v7)
        v8["version"] = 8
        v8["projects"][0]["domain"] = "MP"
        a, b = R.merge(v7, None, self.cfg), R.merge(v8, None, self.cfg)
        self.assertEqual((a.domain_of("P-0007"), b.domain_of("P-0007")), ("DEV", "MP"))
        self.assertEqual(b.domain_of("P-0013"), "MP")                      # 병합 사슬도 따라간다
        self.assertEqual(a.active_ids(), b.active_ids())                   # 코파일럿 재질의 키(과제 집합) 불변
        self.assertNotEqual(a.hier_hash, b.hier_hash)


class LoadEffectiveTest(_Tmp):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "root"
        (self.root / "data").mkdir(parents=True)
        self.paths = Paths(self.root, lad=self.tmp / "lad")
        self.off = self.tmp / "offline"
        self.off.mkdir()

    def put(self, path, obj):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        return path

    def cfg_with(self, **over):
        o = {"team.offlineDir": str(self.off)}
        o.update({k.replace("__", "."): v for k, v in over.items()})
        return make_cfg(self.tmp, o)

    def golden_v(self, v):
        g = load("registry_golden.json")
        g["version"] = v
        return g

    def test_builtin_when_nothing(self):
        reg, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertEqual((st.source, st.version, st.stale), ("builtin", 0, False))
        self.assertEqual(st.label_ko(), "팀 레지스트리 없음 — 초기 상태")
        self.assertEqual(reg.active_ids(), [])
        self.assertEqual(st.hier_hash, reg.hier_hash)
        self.assertEqual(reg.agents, ())                                  # 로컬 카탈로그도 없으면 비어 있다

    def test_local_catalog_lm24_format(self):
        """계약 v1.3 §0.8 V13: 팀 카탈로그가 없으면 config\\agentic_tasks.json(LM24 형식)을 카탈로그로 쓴다."""
        self.put(self.paths.config_dir() / R.LOCAL_CATALOG, {
            "axes": {"축1": "시험 축"},
            "tasks": [{"id": "T-2", "axis": "축1", "name": "시험 보고서 작성 보조"},
                      {"id": "T-1", "axis": "축1", "name": "도면 검토 자동화", "desc": "도면 검토를 자동으로"},
                      {"id": "", "name": "이름만"}, {"id": "T-1", "name": "같은 id 는 처음 것만"}]})
        reg, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertEqual([a.id for a in reg.agents], ["T-1", "T-2"])
        self.assertEqual((reg.agents[0].name, reg.agents[0].copilot_desc), ("도면 검토 자동화", "도면 검토를 자동으로"))
        self.assertIn("도면", reg.agents[0].keywords)
        self.assertTrue(reg.catalog_version.startswith("local:"))
        self.assertEqual(reg.agent_axes, {"축1": "시험 축"})
        self.assertEqual(st.hier_hash, reg.hier_hash)

    def test_local_catalog_ignored_when_team_has_agents_or_broken(self):
        self.put(self.paths.config_dir() / R.LOCAL_CATALOG, {"tasks": "형식 아님"})
        reg, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertEqual(reg.agents, ())
        self.assertIn("local_catalog_rejected", st.warnings)
        team = self.golden_v(7)
        if team.get("agents"):                                            # 팀 카탈로그가 있으면 그것이 앞선다
            self.put(self.paths.registry_cache(), team)
            self.put(self.paths.config_dir() / R.LOCAL_CATALOG, {"tasks": [{"id": "L-1", "name": "로컬"}]})
            reg, _st = R.load_effective(self.paths, self.cfg_with(), NOW)
            self.assertNotIn("L-1", [a.id for a in reg.agents])

    def test_t_h01_offline_newer_than_cache(self):
        self.put(self.paths.registry_cache(), self.golden_v(7))
        self.put(self.off / R.OFFLINE_REGISTRY_NAME, self.golden_v(8))
        reg, st = R.load_effective(self.paths, self.cfg_with(), NOW)
        self.assertEqual((st.source, st.version, st.adopt_offline), ("offline", 8, True))
        self.assertEqual(reg.version, 8)
        self.assertEqual(st.label_ko(), "레지스트리 v8(오프라인 사본)")

    def test_t_h02_offline_rejected(self):
        self.put(self.paths.registry_cache(), self.golden_v(7))
        bad = self.golden_v(9)
        bad["domains"] = ["DEV", "MP"]
        self.put(self.off / R.OFFLINE_REGISTRY_NAME, bad)
        reg, st = R.load_effective(self.paths, self.cfg_with(), NOW)
        self.assertEqual((st.source, st.version), ("cache", 7))
        self.assertIn("offline_rejected", st.warnings)
        self.assertTrue(st.label_ko().startswith("레지스트리 v7("))

    def test_offline_older_uses_cache(self):
        self.put(self.paths.registry_cache(), self.golden_v(7))
        self.put(self.off / R.OFFLINE_REGISTRY_NAME, self.golden_v(6))
        _reg, st = R.load_effective(self.paths, self.cfg_with(), NOW)
        self.assertEqual((st.source, st.version, st.adopt_offline), ("cache", 7, False))

    def test_server_paths(self):
        self.put(self.paths.registry_cache(), self.golden_v(7))
        seen = []

        def ok(timeout_s):
            seen.append(timeout_s)
            return 200, self.golden_v(9)
        reg, st = R.load_effective(self.paths, self.cfg, NOW, fetch=ok)
        self.assertEqual((st.source, st.version), ("server", 9))
        self.assertEqual(seen, [15])
        self.assertEqual(st.fetched_at, "2026-10-05T03:00:00Z")
        bad = self.golden_v(10)
        bad["schema"] = "x"
        _r, st = R.load_effective(self.paths, self.cfg, NOW, fetch=lambda timeout_s: {"status": 200, "obj": bad})
        self.assertEqual((st.source, st.version), ("cache", 7))
        self.assertIn("server_rejected", st.warnings)
        _r, st = R.load_effective(self.paths, self.cfg, NOW, fetch=lambda timeout_s: (304, None))
        self.assertEqual((st.source, st.version, st.fetched_at), ("cache", 7, "2026-10-05T03:00:00Z"))

        def down(timeout_s):
            raise OSError("연결 거부")
        _r, st = R.load_effective(self.paths, self.cfg, NOW, fetch=down)
        self.assertEqual(st.source, "cache")
        self.assertIn("server_unreachable:OSError", st.warnings)
        cfg = make_cfg(self.tmp, {"team.registryTimeoutSec": 3})
        seen.clear()
        R.load_effective(self.paths, cfg, NOW, fetch=ok)
        self.assertEqual(seen, [3])                                       # 설정 섭동 → 호출 인자 변화(T-14)

    def test_cache_rejected(self):
        bad = self.golden_v(7)
        bad["projects"] = "x"
        self.put(self.paths.registry_cache(), bad)
        _r, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertEqual(st.source, "builtin")
        self.assertIn("cache_rejected", st.warnings)

    def test_stale_and_perturbation(self):
        p = self.put(self.paths.registry_cache(), self.golden_v(7))
        old = (NOW - timedelta(days=30)).timestamp()
        os.utime(p, (old, old))
        _r, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertTrue(st.stale)
        _r, st = R.load_effective(self.paths, make_cfg(self.tmp, {"hier.registry.staleWarnDays": 60}), NOW)
        self.assertFalse(st.stale)

    def test_cfg_read_check(self):
        cfg = self.cfg_with()
        R.load_effective(self.paths, cfg, NOW)
        used = cfg.used()
        for k in ("team.registryTimeoutSec", "hier.registry.staleWarnDays", "team.offlineDir",
                  "hier.publicDomainClasses", "privacy.customers", "privacy.partners", "privacy.internalDomains"):
            self.assertIn(k, used)

    def test_local_bak_recovery(self):
        main = self.paths.hier_local_file(R.LOCAL_FILE)
        main.parent.mkdir(parents=True)
        main.write_bytes(b"{broken")
        self.put(self.paths.hier_local_file(R.LOCAL_BAK), load("local_example.json"))
        reg, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertIn("local_broken", st.warnings)
        self.assertIn("local_from_bak", st.warnings)
        self.assertIn("L-0001", reg.projects)
        self.paths.hier_local_file(R.LOCAL_BAK).write_bytes(b"[]")
        reg, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertIn("local_broken", st.warnings)
        self.assertNotIn("L-0001", reg.projects)

    def test_t_h03_persist_maps_to(self):
        team = team_with([{"id": "P-0021", "name": "광센서 모듈", "domain": "MP", "aliases": ["광센서 선행"]}])
        self.put(self.paths.registry_cache(), team)
        main = self.put(self.paths.hier_local_file(R.LOCAL_FILE), load("local_example.json"))
        before = main.read_bytes()
        reg, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertEqual(st.local_maps, {"L-0001": "P-0021"})
        self.assertEqual(reg.resolve("L-0001"), "P-0021")
        saved = fsx.read_json(main)
        self.assertEqual(saved["projects"][0]["maps_to"], "P-0021")
        self.assertEqual(self.paths.hier_local_file(R.LOCAL_BAK).read_bytes(), before)
        after = main.read_bytes()
        _reg2, st2 = R.load_effective(self.paths, self.cfg, NOW)
        self.assertEqual(st2.local_maps, {})
        self.assertEqual(main.read_bytes(), after)                         # 바꿀 것이 없으면 쓰지 않는다

    def test_persist_off(self):
        team = team_with([{"id": "P-0021", "name": "광센서 모듈", "domain": "MP", "aliases": ["광센서 선행"]}])
        self.put(self.paths.registry_cache(), team)
        main = self.put(self.paths.hier_local_file(R.LOCAL_FILE), load("local_example.json"))
        before = main.read_bytes()
        R.load_effective(self.paths, self.cfg, NOW, persist=False)
        self.assertEqual(main.read_bytes(), before)
        self.assertFalse(self.paths.hier_local_file(R.LOCAL_BAK).exists())

    def test_t_h04_person_key_from_bundle(self):
        team = team_with([{"id": "P-0021", "name": "열관리 모듈", "domain": "DEV",
                           "adopted": [{"person_key": PK, "proposal_id": "pr_3"}]}])
        self.put(self.paths.registry_cache(), team)
        self.put(self.paths.hier_local_file(R.LOCAL_FILE),
                 {"schema": "lm27.registry_local/1",
                  "projects": [{"id": "L-0002", "name": "방열 선행", "domain": "DEV", "proposal_id": "pr_3"}]})
        self.put(self.paths.bundle_json(), {"schema": "lm27.bundle/1", "person_key": PK})
        reg, st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertEqual(reg.resolve("L-0002"), "P-0021")
        self.assertEqual(st.local_maps, {"L-0002": "P-0021"})

    def test_learned_file_and_keyers(self):
        self.put(self.paths.registry_cache(), self.golden_v(7))
        self.put(self.paths.hier_local_file(R.LEARNED_FILE),
                 {"schema": "lm27.rules_learned/1",
                  "rules": [{"id": "LK-conv-t1", "if": {"conv": "t0123456789abcdef"}, "then": {"project": "P-0007"},
                             "status": "active"}]})
        reg, _st = R.load_effective(self.paths, self.cfg, NOW, folder_key=fake_folder, doc_key=fake_doc)
        self.assertEqual([r.id for r in reg.rules], ["LK-conv-t1"])
        self.assertEqual(reg.folder_ix, {fake_folder("과제A_설계"): "P-0007"})

    def test_calendar_passthrough(self):
        cal = json.loads(CAL.read_text(encoding="utf-8"))
        cal["version"] = "team-test-1"
        g = self.golden_v(7)
        g["calendar"] = cal
        self.put(self.paths.registry_cache(), g)
        reg, _st = R.load_effective(self.paths, self.cfg, NOW)
        self.assertEqual(reg.calendar["version"], "team-test-1")
        from lm27.time.calendar import load_calendar
        c = load_calendar(Paths(ROOT), reg)
        self.assertEqual((c.version, c.source), ("team-test-1", "registry"))

    def test_privacy_dict_includes_local(self):
        # X-247: 사전 가명화 출처 = 유효 레지스트리(팀 ⊕ 개인 로컬)
        self.put(self.paths.registry_cache(), self.golden_v(7))
        self.put(self.paths.hier_local_file(R.LOCAL_FILE), load("local_example.json"))
        reg, _st = R.load_effective(self.paths, self.cfg, NOW)
        got = {p["id"]: p["codenames"] for p in reg.privacy_dict()["projects"]}
        self.assertEqual(got["L-0001"], ["PROJ-X"])
        self.assertEqual(got["P-0007"], ["PROJ-A"])


class ReaderBoundaryTest(unittest.TestCase):
    def test_only_registry_reads_team_cache(self):
        # L-22 · X-237: data\team\registry.json 은 hier 에서 registry.py 만 읽는다
        for p in sorted((ROOT / "lm27" / "hier").glob("*.py")):
            text = p.read_text(encoding="utf-8")
            if p.name != "registry.py":
                self.assertNotIn("registry_cache", text, p.name)


if __name__ == "__main__":
    unittest.main()
