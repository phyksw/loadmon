# -*- coding: utf-8 -*-
"""WP-21 레지스트리 검증기 시험 — H §2.4 · §3.3 · HG39 · G-H5 · G-H6 · 계약 §3.19 · §3.20 · §4.5 · X-050 · X-232 · X-241.

G-H5: §2.4 스키마의 제약마다 위반 사례 1개 → 기대 오류 코드(서버 = 거부, 클라이언트 = 항목 무시·파일 거부).
G-H6: 팀·개인 파일의 `P-99xx` 거부.
자료는 합성 레지스트리(과제A·고객사A 자리표시자)만 쓴다.
"""
import copy
import json
import unittest
from pathlib import Path

from lm27.hier import registry_schema as RS

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "wp21"
CAL = ROOT / "config" / "calendar.json"

BASE = {
    "schema": "lm27.registry/1", "version": 3,
    "projects": [{"id": "P-0001", "name": "과제A", "domain": "DEV", "codenames": ["PROJ-A"], "customers": ["C01"],
                  "partners": ["V01"], "keywords": ["브라켓"]},
                 {"id": "P-0002", "name": "과제B", "domain": "MP"}],
    "customers": [{"id": "C01", "names": ["고객사A"], "domains": ["custa.example"]}],
    "partners": [{"id": "V01"}],
    "agents_meta": {"catalog_version": "ag-1", "axes": {"X1": "문서 자동화"}},
    "agents": [{"id": "AG001", "name": "문서 초안 작성", "axis": "X1", "step_types": ["DOC_DOC"]}],
    "rules": [{"id": "TR001", "if": {"token": "광정렬"}, "then": {"project": "P-0001"}}],
    "vocab": {"fields": [{"code": "MECH", "name": "기구"}]},
}
FILE_LEVEL = {("schema", "missing"), ("schema", "bad_value"), ("version", "missing"), ("version", "bad_type"),
              ("version", "out_of_range"), ("domains", "bad_domains"), ("projects", "bad_type"),
              ("rules", "bad_type"), ("agents", "bad_type"), ("", "too_large"), ("", "too_deep"), ("", "bad_type")}


def _set(path, value):
    """BASE 사본의 path(키·첨자 튜플)에 value 를 넣는 변형기. value 가 _DEL 이면 지운다."""
    def f(o):
        cur = o
        for k in path[:-1]:
            cur = cur[k]
        if value is _DEL:
            del cur[path[-1]]
        else:
            cur[path[-1]] = copy.deepcopy(value)
        return o
    return f


_DEL = object()
P0 = ("projects", 0)
LONG = "가" * 61

# (이름, 변형기, (기대 경로, 기대 코드)) — §2.4 제약마다 하나
CASES = [
    # 최상위
    ("schema 없음", _set(("schema",), _DEL), ("schema", "missing")),
    ("schema 값", _set(("schema",), "lm27.registry/2"), ("schema", "bad_value")),
    ("version 없음", _set(("version",), _DEL), ("version", "missing")),
    ("version 형", _set(("version",), "3"), ("version", "bad_type")),
    ("version bool", _set(("version",), True), ("version", "bad_type")),
    ("version 음수", _set(("version",), -1), ("version", "out_of_range")),
    ("updated_at 형", _set(("updated_at",), 5), ("updated_at", "bad_type")),
    ("updated_label 길이", _set(("updated_label",), "가" * 21), ("updated_label", "too_long")),
    ("team.label 길이", _set(("team",), {"label": "가" * 21}), ("team.label", "too_long")),
    ("pepper 형식", _set(("pepper",), "xyz"), ("pepper", "bad_pattern")),
    ("pepper_id 형식", _set(("pepper_id",), "123"), ("pepper_id", "bad_pattern")),
    ("domains 고정", _set(("domains",), ["DEV"]), ("domains", "bad_domains")),
    ("domain_meta 키", _set(("domain_meta",), {"UNC": {}}), ("domain_meta.UNC", "bad_domain")),
    ("domain_meta desc", _set(("domain_meta",), {"COM": {"desc": LONG}}), ("domain_meta.COM.desc", "too_long")),
    ("domain_meta 필드", _set(("domain_meta",), {"COM": {"color": "x"}}), ("domain_meta.COM.color", "unknown_field")),
    ("domain_meta 키워드 수", _set(("domain_meta",), {"COM": {"keywords_add": [f"낱말{i}" for i in range(51)]}}),
     ("domain_meta.COM.keywords_add", "too_many")),
    ("domain_meta 키워드 길이", _set(("domain_meta",), {"COM": {"keywords_remove": ["x"]}}),
     ("domain_meta.COM.keywords_remove[0]", "too_short")),
    ("projects 형", _set(("projects",), "x"), ("projects", "bad_type")),
    ("projects 수", _set(("projects",), [{"id": f"P-{i:04d}", "name": f"과제{i}", "domain": "DEV"}
                                         for i in range(1, 502)]), ("projects", "too_many")),
    ("members 형", _set(("members",), {}), ("members", "bad_type")),
    ("rules 형", _set(("rules",), {}), ("rules", "bad_type")),
    ("rules 수", _set(("rules",), [{"id": f"TR{i}", "if": {"token": "광정렬"}, "then": {"project": "P-0001"}}
                                    for i in range(501)]), ("rules", "too_many")),
    ("agents 수", _set(("agents",), [{"id": f"AG{i}", "name": "문서 초안"} for i in range(201)]),
     ("agents", "too_many")),
    ("never_pairs 모양", _set(("never_pairs",), [["가나"]]), ("never_pairs[0]", "bad_shape")),
    ("never_pairs 길이", _set(("never_pairs",), [["가나", "가" * 41]]), ("never_pairs[0][1]", "too_long")),
    ("never_pairs 수", _set(("never_pairs",), [["가나", f"다라{i}"] for i in range(501)]), ("never_pairs", "too_many")),
    ("catalog_version", _set(("agents_meta", "catalog_version"), "판 3"), ("agents_meta.catalog_version",
                                                                            "bad_pattern")),
    ("axes 설명", _set(("agents_meta", "axes"), {"X1": LONG}), ("agents_meta.axes.X1", "too_long")),
    ("calendar 형", _set(("calendar",), "x"), ("calendar", "bad_type")),
    ("calendar 근무창 필드", _set(("calendar",), {"lunch": "12:00-13:00"}), ("calendar.lunch", "unknown_field")),
    ("calendar 형식", _set(("calendar",), {"version": "x"}), ("calendar", "bad_calendar")),
    ("internal_domains", _set(("internal_domains",), ["Bad_Domain"]), ("internal_domains[0]", "bad_pattern")),
    ("customers id 없음", _set(("customers",), [{"names": []}]), ("customers[0].id", "missing")),
    ("customers id 길이(X-050)", _set(("customers",), [{"id": "C" + "1" * 16}]), ("customers[0].id", "bad_id")),
    ("customers 이름 길이", _set(("customers",), [{"id": "C01", "names": ["가" * 41]}]), ("customers[0].names[0]",
                                                                                         "too_long")),
    ("customers 도메인", _set(("customers",), [{"id": "C01", "domains": ["X"]}]), ("customers[0].domains[0]",
                                                                                 "bad_pattern")),
    ("customers 중복", _set(("customers",), [{"id": "C01"}, {"id": "C01"}]), ("customers[1].id", "dup_id")),
    ("공공 도메인 값", _set(("public_domain_classes",), {".ac.kr": "대학"}), ("public_domain_classes..ac.kr",
                                                                           "bad_value")),
    ("공공 도메인 키", _set(("public_domain_classes",), {"ac.kr": "기관"}), ("public_domain_classes.ac.kr",
                                                                          "bad_pattern")),
    ("공공 도메인 수", _set(("public_domain_classes",), {f".s{i}.kr": "기관" for i in range(51)}),
     ("public_domain_classes", "too_many")),
    # 과제
    ("과제 id 없음", _set(P0 + ("id",), _DEL), ("projects[0].id", "missing")),
    ("과제 id 형식", _set(P0 + ("id",), "P-12"), ("projects[0].id", "bad_id")),
    ("과제 id 예약(G-H6)", _set(P0 + ("id",), "P-9901"), ("projects[0].id", "reserved_id")),
    ("과제 id 예약 범위", _set(P0 + ("id",), "P-9950"), ("projects[0].id", "reserved_id")),
    ("과제 이름 빈", _set(P0 + ("name",), ""), ("projects[0].name", "too_short")),
    ("과제 이름 길이", _set(P0 + ("name",), "가" * 41), ("projects[0].name", "too_long")),
    ("과제 영역 없음", _set(P0 + ("domain",), _DEL), ("projects[0].domain", "missing")),
    ("과제 영역 UNC(X-232)", _set(P0 + ("domain",), "UNC"), ("projects[0].domain", "bad_domain")),
    ("과제 상태", _set(P0 + ("status",), "done"), ("projects[0].status", "bad_value")),
    ("merged_into 형식", _set(P0 + ("merged_into",), "X"), ("projects[0].merged_into", "bad_id")),
    ("aliases 수", _set(P0 + ("aliases",), [f"별칭{i}" for i in range(21)]), ("projects[0].aliases", "too_many")),
    ("aliases 짧음(ASCII)", _set(P0 + ("aliases",), ["AB"]), ("projects[0].aliases[0]", "short_alias")),
    ("aliases 짧음(한글)", _set(P0 + ("aliases",), ["가"]), ("projects[0].aliases[0]", "short_alias")),
    ("codenames 짧음", _set(P0 + ("codenames",), ["AB"]), ("projects[0].codenames[0]", "short_alias")),
    ("codenames 길이", _set(P0 + ("codenames",), ["가" * 41]), ("projects[0].codenames[0]", "too_long")),
    ("mask_name 형", _set(P0 + ("mask_name",), "yes"), ("projects[0].mask_name", "bad_type")),
    ("keywords 수", _set(P0 + ("keywords",), [f"키워드{i}" for i in range(31)]), ("projects[0].keywords", "too_many")),
    ("keywords 길이", _set(P0 + ("keywords",), ["x"]), ("projects[0].keywords[0]", "too_short")),
    ("never 수", _set(P0 + ("never",), [f"후속{i}" for i in range(21)]), ("projects[0].never", "too_many")),
    ("mail_domains", _set(P0 + ("mail_domains",), ["X.COM"]), ("projects[0].mail_domains[0]", "bad_pattern")),
    ("customers 수", _set(P0 + ("customers",), [f"C{i:02d}" for i in range(11)]), ("projects[0].customers",
                                                                                   "too_many")),
    ("customers 참조", _set(P0 + ("customers",), ["C99"]), ("projects[0].customers[0]", "bad_ref")),
    ("partners 참조", _set(P0 + ("partners",), ["V99"]), ("projects[0].partners[0]", "bad_ref")),
    ("folders 형식", _set(P0 + ("folders",), ["a/b"]), ("projects[0].folders[0]", "bad_pattern")),
    ("folders 길이", _set(P0 + ("folders",), ["a"]), ("projects[0].folders[0]", "too_short")),
    ("apps 형식", _set(P0 + ("apps",), ["Bad App"]), ("projects[0].apps[0]", "bad_pattern")),
    ("apps 수", _set(P0 + ("apps",), [f"app{i}" for i in range(11)]), ("projects[0].apps", "too_many")),
    ("default_field 형식", _set(P0 + ("default_field",), "mech"), ("projects[0].default_field", "bad_pattern")),
    ("default_field 참조", _set(P0 + ("default_field",), "ZZZ"), ("projects[0].default_field", "bad_ref")),
    ("default_func 참조", _set(P0 + ("default_func",), "NOPE"), ("projects[0].default_func", "bad_ref")),
    ("ax_link 형", _set(P0 + ("ax_link",), 1), ("projects[0].ax_link", "bad_type")),
    ("shared_docs 길이", _set(P0 + ("shared_docs",), ["a"]), ("projects[0].shared_docs[0]", "too_short")),
    ("copilot_desc 길이", _set(P0 + ("copilot_desc",), "가" * 41), ("projects[0].copilot_desc", "too_long")),
    ("copilot_desc 코드네임", _set(P0 + ("copilot_desc",), "PROJ-A 일정 관리"),
     ("projects[0].copilot_desc", "desc_has_codename")),
    ("period.from", _set(P0 + ("period",), {"from": "2026-1"}), ("projects[0].period.from", "bad_pattern")),
    ("period.to", _set(P0 + ("period",), {"from": "2026-01", "to": "2026"}), ("projects[0].period.to",
                                                                             "bad_pattern")),
    ("adopted person_key", _set(P0 + ("adopted",), [{"person_key": "x", "proposal_id": "pr_1"}]),
     ("projects[0].adopted[0].person_key", "bad_pattern")),
    ("adopted 필수", _set(P0 + ("adopted",), [{"proposal_id": "pr_1"}]), ("projects[0].adopted[0].person_key",
                                                                         "missing")),
    ("note 길이", _set(P0 + ("note",), "가" * 201), ("projects[0].note", "too_long")),
    ("과제 중복", _set(("projects", 1, "id"), "P-0001"), ("projects[1].id", "dup_id")),
    ("별칭 충돌", _set(("projects", 1, "aliases"), ["과제 A"]), ("projects[1]", "alias_collision")),
    ("병합 대상 없음", _set(P0 + ("merged_into",), "P-0050"), ("projects[P-0001].merged_into",
                                                           "merge_target_missing")),
    # 어휘
    ("vocab 목록 형", _set(("vocab", "fields"), "x"), ("vocab.fields", "bad_type")),
    ("vocab 목록 수", _set(("vocab", "fields"), [f"분야{i}" for i in range(101)]), ("vocab.fields", "too_many")),
    ("vocab 코드 형식", _set(("vocab", "fields"), [{"code": "mech", "name": "기구"}]), ("vocab.fields[0].code",
                                                                                   "bad_pattern")),
    ("vocab 이름 없음", _set(("vocab", "fields"), [{"code": "MECH"}]), ("vocab.fields[0].name", "missing")),
    ("vocab 이름 길이", _set(("vocab", "fields"), [{"code": "MECH", "name": "가" * 21}]), ("vocab.fields[0].name",
                                                                                     "too_long")),
    ("vocab 상태", _set(("vocab", "fields"), [{"code": "MECH", "name": "기구", "status": "x"}]),
     ("vocab.fields[0].status", "bad_value")),
    ("vocab replaced_by 참조", _set(("vocab", "fields"), [{"code": "MECH", "name": "기구", "replaced_by": "NOPE"}]),
     ("vocab.fields[0].replaced_by", "bad_ref")),
    ("vocab exts", _set(("vocab", "fields"), [{"code": "MECH", "name": "기구", "exts": ["zmx"]}]),
     ("vocab.fields[0].exts[0]", "bad_pattern")),
    ("vocab apps", _set(("vocab", "fields"), [{"code": "MECH", "name": "기구", "apps": ["A B"]}]),
     ("vocab.fields[0].apps[0]", "bad_pattern")),
    ("vocab 문자열 길이", _set(("vocab", "fields"), ["가" * 21]), ("vocab.fields[0]", "too_long")),
    ("vocab 코드 중복", _set(("vocab", "fields"), [{"code": "MECH", "name": "기구"}, {"code": "MECH", "name": "기"}]),
     ("vocab.fields[1].code", "dup_id")),
    ("step tool_access(X-241)", _set(("vocab", "step_types"), [{"code": "APP_CAE", "name": "해석", "tool_access": 3}]),
     ("vocab.step_types[0].tool_access", "out_of_range")),
    ("step verifiable 형", _set(("vocab", "step_types"), [{"code": "APP_CAE", "name": "해석", "verifiable": "2"}]),
     ("vocab.step_types[0].verifiable", "bad_type")),
    ("step kind", _set(("vocab", "step_types"), [{"code": "APP_CAE", "name": "해석", "kind": "X"}]),
     ("vocab.step_types[0].kind", "bad_value")),
    ("step cls", _set(("vocab", "step_types"), [{"code": "APP_CAE", "name": "해석", "cls": "기타"}]),
     ("vocab.step_types[0].cls", "bad_value")),
    # 규칙
    ("규칙 id TR", _set(("rules", 0, "id"), "R1"), ("rules[0].id", "bad_id")),
    ("규칙 if 없음", _set(("rules", 0, "if"), _DEL), ("rules[0].if", "missing")),
    ("규칙 if 빈", _set(("rules", 0, "if"), {}), ("rules[0].if", "bad_shape")),
    ("규칙 if 둘", _set(("rules", 0, "if"), {"token": "광정렬", "app": "zemax"}), ("rules[0].if", "bad_shape")),
    ("규칙 if 키", _set(("rules", 0, "if"), {"color": "x"}), ("rules[0].if.color", "unknown_field")),
    ("규칙 if.ext", _set(("rules", 0, "if"), {"ext": "zmx"}), ("rules[0].if.ext", "bad_pattern")),
    ("규칙 if.domain", _set(("rules", 0, "if"), {"domain": "X"}), ("rules[0].if.domain", "bad_pattern")),
    ("규칙 if.sender_label", _set(("rules", 0, "if"), {"sender_label": "가" * 81}),
     ("rules[0].if.sender_label", "too_long")),
    ("규칙 then 없음", _set(("rules", 0, "then"), _DEL), ("rules[0].then", "missing")),
    ("규칙 then 과제 참조", _set(("rules", 0, "then"), {"project": "P-0099"}), ("rules[0].then.project", "bad_ref")),
    ("규칙 then 분야 참조", _set(("rules", 0, "then"), {"field": "NOPE"}), ("rules[0].then.field", "bad_ref")),
    ("규칙 then 영역", _set(("rules", 0, "then"), {"domain": "UNC"}), ("rules[0].then.domain", "bad_domain")),
    ("규칙 w 범위", _set(("rules", 0, "w"), 7), ("rules[0].w", "out_of_range")),
    ("규칙 w 형", _set(("rules", 0, "w"), "2"), ("rules[0].w", "bad_type")),
    ("규칙 상태", _set(("rules", 0, "status"), "x"), ("rules[0].status", "bad_value")),
    ("규칙 note", _set(("rules", 0, "note"), "가" * 61), ("rules[0].note", "too_long")),
    ("규칙 중복", _set(("rules",), [{"id": "TR1", "if": {"token": "광정렬"}, "then": {"func": "DESIGN"}}] * 2),
     ("rules[1].id", "dup_id")),
    # 에이전트
    ("에이전트 id", _set(("agents", 0, "id"), "X1"), ("agents[0].id", "bad_id")),
    ("에이전트 이름", _set(("agents", 0, "name"), "가"), ("agents[0].name", "too_short")),
    ("에이전트 상태", _set(("agents", 0, "status"), "x"), ("agents[0].status", "bad_value")),
    ("에이전트 desc", _set(("agents", 0, "desc"), "가" * 201), ("agents[0].desc", "too_long")),
    ("에이전트 copilot_desc", _set(("agents", 0, "copilot_desc"), "가" * 81), ("agents[0].copilot_desc", "too_long")),
    ("에이전트 단계 참조", _set(("agents", 0, "step_types"), ["NOPE"]), ("agents[0].step_types[0]", "bad_ref")),
    ("에이전트 단계 수", _set(("agents", 0, "step_types"), ["DOC_DOC"] * 11), ("agents[0].step_types", "too_many")),
    ("에이전트 입력 수", _set(("agents", 0, "inputs"), ["a"] * 6), ("agents[0].inputs", "too_many")),
    ("에이전트 출력 길이", _set(("agents", 0, "outputs"), ["가" * 21]), ("agents[0].outputs[0]", "too_long")),
    ("에이전트 축 참조", _set(("agents", 0, "axis"), "Z9"), ("agents[0].axis", "bad_ref")),
    ("에이전트 키워드", _set(("agents", 0, "keywords"), ["x"]), ("agents[0].keywords[0]", "too_short")),
    ("에이전트 owner_label", _set(("agents", 0, "owner_label"), "가" * 21), ("agents[0].owner_label", "too_long")),
    ("에이전트 설명 코드네임", _set(("agents", 0, "copilot_desc"), "PROJ-A 초안"),
     ("agents[0].copilot_desc", "desc_has_codename")),
    ("에이전트 중복", _set(("agents",), [{"id": "AG1", "name": "문서 초안"}] * 2), ("agents[1].id", "dup_id")),
]
# 경고(거부 아님) — 서버도 받아들이고 클라이언트는 그 낱말을 무시하거나 그대로 둔다
WARN_CASES = [
    ("범용어 키워드", _set(P0 + ("keywords",), ["검토"]), ("projects[0].keywords[0]", "generic_keyword")),
    ("범용어 별칭", _set(P0 + ("aliases",), ["보고서"]), ("projects[0].aliases[0]", "generic_keyword")),
    ("never 코드네임", _set(P0 + ("never",), ["PROJ-A 후속"]), ("projects[0].never[0]", "never_has_codename")),
    ("옛 문자열 어휘", _set(("vocab", "fields"), ["회로", "광학검사"]), ("vocab.fields[0]", "vocab_legacy_string")),
    ("퇴역 병합 대상", lambda o: (o["projects"][1].update({"status": "retired"}),
                             o["projects"][0].update({"merged_into": "P-0002"}), o)[-1],
     ("projects[P-0001].merged_into", "retired_merge_target")),
]


def _pairs(errs):
    return {(e.path, e.code) for e in errs}


class BaseValidTest(unittest.TestCase):
    def test_base_valid(self):
        for side in RS.SIDES:
            self.assertEqual(RS.validate_registry(BASE, side), [], side)

    def test_golden_and_example_valid(self):
        g = json.loads((FIX / "registry_golden.json").read_text(encoding="utf-8"))
        self.assertEqual(RS.validate_registry(g, "server"), [])
        ex = json.loads((FIX / "registry_example.json").read_text(encoding="utf-8"))
        ex["calendar"] = json.loads(CAL.read_text(encoding="utf-8"))
        self.assertEqual(RS.validate_registry(ex, "server"), [])

    def test_bad_side(self):
        with self.assertRaises(ValueError):
            RS.validate_registry(BASE, "both")


class HG39Test(unittest.TestCase):
    def test_golden(self):
        g = json.loads((FIX / "golden_hg.json").read_text(encoding="utf-8"))
        want = {tuple(x) for x in g["HG39_validate"]}
        server = RS.validate_registry(g["HG39_input"], "server")
        self.assertEqual(_pairs(server), want)
        self.assertTrue(all(e.level == RS.REJECT for e in server))
        client = RS.validate_registry(g["HG39_input"], "client")
        self.assertEqual(_pairs(client), want)
        self.assertFalse(RS.blocking(client))                    # 항목 단위 — 파일은 쓴다(그 항목만 무시)


class GH5ConstraintTest(unittest.TestCase):
    """G-H5 — 제약마다 위반 1개 → 기대 오류 코드."""

    def test_each_constraint(self):
        for name, mut, (path, code) in CASES:
            with self.subTest(name=name):
                obj = mut(copy.deepcopy(BASE))
                before = copy.deepcopy(obj)
                server = RS.validate_registry(obj, "server")
                self.assertIn((path, code), _pairs(server), [str(e) for e in server])
                hit = [e for e in server if (e.path, e.code) == (path, code)]
                self.assertTrue(all(e.level == RS.REJECT for e in hit))
                client = RS.validate_registry(obj, "client")
                ce = [e for e in client if (e.path, e.code) == (path, code)]
                self.assertTrue(ce)
                want_level = RS.REJECT if (path, code) in FILE_LEVEL else RS.DROP
                self.assertEqual({e.level for e in ce}, {want_level}, name)
                self.assertEqual(obj, before)                     # 입력은 바꾸지 않는다

    def test_warnings_not_reject(self):
        for name, mut, (path, code) in WARN_CASES:
            with self.subTest(name=name):
                obj = mut(copy.deepcopy(BASE))
                for side in RS.SIDES:
                    errs = RS.validate_registry(obj, side)
                    hit = [e for e in errs if (e.path, e.code) == (path, code)]
                    self.assertTrue(hit, [str(e) for e in errs])
                    self.assertEqual({e.level for e in hit}, {RS.WARN})
                    self.assertFalse(RS.blocking(errs))

    def test_merge_cycle(self):
        obj = copy.deepcopy(BASE)
        obj["projects"][0]["merged_into"] = "P-0002"
        obj["projects"][1]["merged_into"] = "P-0001"
        self.assertEqual({p for p in _pairs(RS.validate_registry(obj, "server")) if p[1] == "merge_cycle"},
                         {("projects[P-0001]", "merge_cycle"), ("projects[P-0002]", "merge_cycle")})

    def test_too_large_and_deep(self):
        big = copy.deepcopy(BASE)
        big["members"] = [{"id": f"M{i}", "label": "가" * 200} for i in range(4000)]
        for side in RS.SIDES:
            errs = RS.validate_registry(big, side)
            self.assertIn(("", "too_large"), _pairs(errs))
            self.assertTrue(RS.blocking(errs))
        deep = copy.deepcopy(BASE)
        x: list = []
        deep["members"] = x
        for _ in range(40):
            y: list = []
            x.append(y)
            x = y
        self.assertIn(("", "too_deep"), _pairs(RS.validate_registry(deep, "client")))

    def test_not_object(self):
        for v in (None, [], "x", 3):
            errs = RS.validate_registry(v, "client")
            self.assertEqual(_pairs(errs), {("", "bad_type")})
            self.assertTrue(RS.blocking(errs))

    def test_valid_calendar_ok(self):
        obj = copy.deepcopy(BASE)
        obj["calendar"] = json.loads(CAL.read_text(encoding="utf-8"))
        self.assertEqual(RS.validate_registry(obj, "server"), [])

    def test_deterministic_sorted(self):
        g = json.loads((FIX / "golden_hg.json").read_text(encoding="utf-8"))
        a = RS.validate_registry(g["HG39_input"], "server")
        b = RS.validate_registry(copy.deepcopy(g["HG39_input"]), "server")
        self.assertEqual(a, b)
        self.assertEqual(a, sorted(a))


class CleanRegistryTest(unittest.TestCase):
    """클라이언트 의미: 그 항목·값만 무시하고 나머지로 분류한다(H §2.4 · §14)."""

    def test_item_drops(self):
        obj = copy.deepcopy(BASE)
        obj["projects"].append({"id": "P-9902", "name": "예약", "domain": "MP"})
        obj["projects"].append({"id": "P-0003", "name": "과제C", "domain": "XX"})
        obj["projects"][1]["aliases"] = ["과제 A", "과제B 모듈"]
        obj["projects"][0]["copilot_desc"] = "PROJ-A 일정"
        obj["projects"][0]["customers"] = ["C01", "C99"]
        obj["projects"][0]["keywords"] = ["브라켓", "검토"]
        obj["vocab"]["fields"] = ["회로", {"code": "PHOTONICS", "name": "포토닉스"}]
        clean, errs = RS.clean_registry(obj)
        self.assertIsNotNone(clean)
        ids = [p["id"] for p in clean["projects"]]
        self.assertEqual(ids, ["P-0001", "P-0002"])
        p1, p2 = clean["projects"]
        self.assertEqual(p2["aliases"], ["과제B 모듈"])                  # 충돌 별칭만 버림
        self.assertEqual(p1["copilot_desc"], "")
        self.assertEqual(p1["customers"], ["C01"])
        self.assertEqual(p1["keywords"], ["브라켓"])
        self.assertEqual([it["code"] for it in clean["vocab"]["fields"]], ["ELEC", "PHOTONICS"])
        self.assertTrue(clean["vocab"]["fields"][0].get("legacy"))
        self.assertFalse(RS.blocking(errs))

    def test_cycle_and_missing_target_cleared(self):
        obj = copy.deepcopy(BASE)
        obj["projects"][0]["merged_into"] = "P-0002"
        obj["projects"][1]["merged_into"] = "P-0001"
        obj["projects"].append({"id": "P-0003", "name": "과제C", "domain": "DEV", "merged_into": "P-0077"})
        clean, _ = RS.clean_registry(obj)
        self.assertEqual([p.get("merged_into") for p in clean["projects"]], [None, None, None])

    def test_file_level_rejects(self):
        for mut in (_set(("domains",), ["DEV", "MP"]), _set(("projects",), {}), _set(("schema",), "x")):
            clean, errs = RS.clean_registry(mut(copy.deepcopy(BASE)))
            self.assertIsNone(clean)
            self.assertTrue(RS.blocking(errs))

    def test_bad_calendar_dropped(self):
        obj = copy.deepcopy(BASE)
        obj["calendar"] = {"version": "x"}
        clean, errs = RS.clean_registry(obj)
        self.assertNotIn("calendar", clean)
        self.assertFalse(RS.blocking(errs))


LOCAL = {"schema": "lm27.registry_local/1",
         "projects": [{"id": "L-0001", "name": "광센서 선행", "domain": "DEV", "codenames": ["PROJ-X"],
                       "proposal_id": "pr_2", "maps_to": None, "created_from": "user"}]}


class LocalTest(unittest.TestCase):
    def test_example_valid(self):
        loc = json.loads((FIX / "local_example.json").read_text(encoding="utf-8"))
        self.assertEqual(RS.validate_local(loc), [])
        self.assertEqual(RS.validate_local(LOCAL), [])

    def test_local_cases(self):
        cases = [
            (_set(("schema",), "lm27.registry/1"), ("schema", "bad_value"), RS.REJECT),
            (_set(("schema",), _DEL), ("schema", "missing"), RS.REJECT),
            (_set(("projects",), {}), ("projects", "bad_type"), RS.REJECT),
            (_set(("projects", 0, "id"), "P-0001"), ("projects[0].id", "bad_id"), RS.DROP),
            (_set(("projects", 0, "id"), "P-9903"), ("projects[0].id", "reserved_id"), RS.DROP),       # G-H6
            (_set(("projects", 0, "maps_to"), "P-9904"), ("projects[0].maps_to", "reserved_id"), RS.DROP),
            (_set(("projects", 0, "maps_to"), "L-0002"), ("projects[0].maps_to", "bad_id"), RS.DROP),
            (_set(("projects", 0, "proposal_id"), "pr-2"), ("projects[0].proposal_id", "bad_pattern"), RS.DROP),
            (_set(("projects", 0, "created_from"), "ai"), ("projects[0].created_from", "bad_value"), RS.DROP),
            (_set(("projects", 0, "copilot_desc"), "PROJ-X 검토"), ("projects[0].copilot_desc", "desc_has_codename"),
             RS.DROP),
            (_set(("overlays",), {"P-9903": {}}), ("overlays.P-9903", "reserved_id"), RS.DROP),            # G-H6
            (_set(("overlays",), {"L-0001": {}}), ("overlays.L-0001", "bad_id"), RS.DROP),
            (_set(("overlays",), {"P-0007": {"name": "x"}}), ("overlays.P-0007.name", "unknown_field"), RS.DROP),
            (_set(("overlays",), {"P-0007": {"domain": "MP"}}), ("overlays.P-0007.domain", "unknown_field"),
             RS.DROP),
            (_set(("roots",), {"R03": "X-1"}), ("roots.R03", "bad_id"), RS.DROP),
            (_set(("vocab_add",), {"fields": [{"code": "PHOTO", "name": "포토"}]}), ("vocab_add.fields[0].code",
                                                                                    "bad_pattern"), RS.DROP),
            (_set(("vocab_add",), {"steps": []}), ("vocab_add.steps", "unknown_field"), RS.DROP),
            (_set(("person",), {"default_field": "opt"}), ("person.default_field", "bad_pattern"), RS.DROP),
            (_set(("codename_review",), {"ignored": ["xyz"]}), ("codename_review.ignored[0]", "bad_pattern"),
             RS.DROP),
        ]
        for mut, pair, level in cases:
            with self.subTest(pair=pair):
                obj = mut(copy.deepcopy(LOCAL))
                errs = RS.validate_local(obj)
                hit = [e for e in errs if (e.path, e.code) == pair]
                self.assertTrue(hit, [str(e) for e in errs])
                self.assertEqual({e.level for e in hit}, {level})

    def test_dup_ids(self):
        obj = copy.deepcopy(LOCAL)
        obj["projects"].append(dict(obj["projects"][0]))
        obj["projects"].append(dict(obj["projects"][0], id="L-0002"))
        clean, errs = RS.clean_local(obj)
        self.assertIn(("projects[1].id", "dup_id"), _pairs(errs))
        self.assertIn(("projects[2].proposal_id", "dup_id"), _pairs(errs))
        self.assertEqual([p["id"] for p in clean["projects"]], ["L-0001", "L-0002"])
        self.assertIsNone(clean["projects"][1]["proposal_id"])

    def test_not_object(self):
        clean, errs = RS.clean_local([])
        self.assertIsNone(clean)
        self.assertTrue(RS.blocking(errs))


if __name__ == "__main__":
    unittest.main()
