# -*- coding: utf-8 -*-
r"""WP-22 코파일럿 입출력 시험 — H §6.1~§6.6 · §8.2 · §8.3 · T-H07(재질의) · B14(과제 이름·별칭·코드네임 미전송).

- 보낼 군집 고르기(a 과제 미확정·b 이름 약함·c 분야·기능 둘 다 l) · 사용자 라벨 제외 · 한 실행 상한.
- 항목 필드(kinds·subjects·files·apps·domains·cands·hint·regv) — 원 도메인·exe 이름·레지스트리 이름이 나가지 않는다.
- regv 상태(제목 캐시 ask) — 과제 목록이 바뀌면 NONE·예약 답만 다시 묻고, 한 번 정한 regv 는 붙박인다.
- 프롬프트 문맥 줄 · 답 검증 · ai_in/ai_out 파일 · 부트스트랩 표본 · 통합 확인 항목.
"""
import json
import unittest

from lm27.hier import copilot_io as CI
from lm27.hier.groups import Group, TitleCache
from lm27.hier.unitlabel import FieldFunc, RuleLabel
from tests.fixtures.wp22 import hierkit as K


def rl(project, source, conf="h", cands=(), domain=None, reg=None):
    dom = domain or (reg.domain_of(project) if reg is not None and project else "UNC")
    return RuleLabel(project, 1.0 if project else 0.0, source, conf, tuple(cands), dom)


def ff(fc="h", cc="h", field="OPT", func="ANALYSIS"):
    return FieldFunc(field, fc, func, cc)


def unit(uid, effort, **kw):
    f = K.F(uid + "_m", "mail", kw.pop("text", "공차 검토"), dom_labels=kw.pop("labels", ["사내"]))
    w = K.F(uid + "_w", "win", "", app=kw.pop("app", "excel"), app_cat=kw.pop("app_cat", "사무"))
    extra = [(K.F(uid + "_w" + a, "win", "", app=a, app_cat=c), 1.0, "app") for a, c in kw.pop("wins", {}).items()]
    base = {"fam_names": {"dA": "공차해석_v3.xlsx", "dG@s1": "보고서.pptx"}, "fam_min": {"dA": 10, "dG@s1": 90},
            "subjects": ("공차 해석 요청",), "kinds": {"메일수신": 2, "문서": 1}, "app_min": {"사무": effort},
            "app_ids": {"excel": effort}, "effort_min": effort}
    base.update(kw)
    return K.U(uid, "S1", [(f, 2.0, "boundary"), (w, 1.0, "app")] + extra, **base)


def scenario(reg):
    units = {f"u{i}": unit(f"u{i}", e) for i, e in enumerate([500, 400, 300, 200, 120, 30, 600])}
    groups = [Group(f"grp:{i:012d}", f"a{i}", f"u{i}", (f"u{i}",), units[f"u{i}"].effort_min) for i in range(7)]
    labels = {"u0": rl(None, "none", "l", [("P-0007", 0.4)]),
              "u1": rl("P-0007", "token", reg=reg),
              "u2": rl("P-9904", "domain_rule", "m", domain="COM"),
              "u3": rl("P-0007", "token", reg=reg),
              "u4": rl("P-0007", "token", reg=reg),
              "u5": rl("P-0007", "token", reg=reg),
              "u6": rl(None, "none", "l")}
    ffs = dict.fromkeys(labels, ff())
    ffs["u4"] = ff("l", "l")
    ffs["u5"] = ff("l", "l")
    wts = dict.fromkeys(labels, ("DEV", "h", ""))
    titles = {g.key: ("공차해석", "doc") for g in groups}
    titles["grp:000000000003"] = ("해석 프로그램 작업", "app")
    return units, groups, labels, ffs, wts, titles


class SelectTest(unittest.TestCase):
    def test_reasons_and_cap(self):
        reg = K.golden_reg()
        units, groups, labels, ffs, wts, titles = scenario(reg)
        items, st = CI.build_task_label_items(groups, labels, ffs, wts, {}, reg, K.cfg(), units=units, titles=titles,
                                              cache=TitleCache(), user_units={"u6"})
        keys = [it["key"] for it in items]
        self.assertEqual(keys, ["grp:000000000000", "grp:000000000003", "grp:000000000004"])   # 투입 큰 순
        self.assertEqual(st["user_label"], 1)
        self.assertEqual((st["why_a"], st["why_b"], st["why_c"]), (1, 1, 1))
        reg2 = K.golden_reg(team=dict(K.GOLDEN_TEAM, projects=K.GOLDEN_TEAM["projects"] + [
            {"id": "P-0030", "name": "예산 관리", "domain": "COM", "copilot_desc": "팀 예산"}]))
        items, _ = CI.build_task_label_items(groups, labels, ffs, wts, {}, reg2, K.cfg(), units=units, titles=titles)
        self.assertIn("grp:000000000002", [it["key"] for it in items])        # 그 영역에 active 과제가 있으면 예약도 묻는다
        cache = TitleCache()
        cache.put("grp:000000000003", title="해석 모델링", src="ai", conf="h")
        items, _ = CI.build_task_label_items(groups, labels, ffs, wts, {}, reg, K.cfg(), units=units, titles=titles,
                                             cache=cache)
        self.assertNotIn("grp:000000000003", [it["key"] for it in items])     # 캐시에 AI h 이름 → 약한 이름 아님
        items, st = CI.build_task_label_items(groups, labels, ffs, wts, {}, reg,
                                              K.cfg({"hier.copilot.maxGroupsPerRun": 1}), units=units, titles=titles,
                                              user_units={"u6"})
        self.assertEqual(len(items), 1)
        self.assertEqual(st["skipped_cap"], 2)
        items, _ = CI.build_task_label_items(groups, labels, ffs, wts, {}, reg,
                                             K.cfg({"hier.copilot.askTitleWeak": False,
                                                    "hier.copilot.vocabAskMinEffortH": 5.0}), units=units,
                                             titles=titles, user_units={"u6"})
        self.assertEqual([it["key"] for it in items], ["grp:000000000000"])


class ItemFieldsTest(unittest.TestCase):
    def test_fields(self):
        reg = K.golden_reg()
        u = unit("ux", 300, subjects=("PROJ-A 일정 공유", "과제A 모듈 검토", "PROJ-A 일정 공유"),
                 labels=["고객사:C01", "other.example", "사내", "개인메일"], app="unknown:mytool.exe", app_cat="",
                 app_ids={"unknown:mytool.exe": 100, "explorer": 50, "excel": 200}, app_min={"사무": 200},
                 wins={"excel": "사무", "explorer": ""},
                 kinds={"메일수신": 3, "메일발신": 1, "회의": 1, "앱": 2})
        g = Group("grp:00000000000x", "a", "ux", ("ux",), 300)
        r = rl("P-9904", "domain_rule", "m", [("P-0007", 0.21)], domain="COM")
        items, _ = CI.build_task_label_items([g], {"ux": r}, {"ux": ff("l", "l")}, {"ux": ("OFFICE", "m", "")}, {},
                                             reg, K.cfg(), units={"ux": u}, titles={g.key: ("공차해석", "doc")},
                                             rules_ver="2026.10.0")
        it = items[0]
        f = it["fields"]
        self.assertEqual(set(f), set(CI.SEND_FIELDS))
        self.assertEqual(f["kinds"], "메일수신 3·메일발신 1·회의 1·앱 2")
        self.assertEqual(f["subjects"], ["[과제:P-0007] 일정 공유", "[과제:P-0007] 검토"])  # 이름·별칭·코드네임 → 토큰
        self.assertEqual(f["files"], ["공차해석_v3.xlsx", "보고서.pptx"])          # 범용 이름은 뒤로
        self.assertEqual(f["apps"], ["엑셀", "미상 프로그램"])                    # exe 이름 없음, 범주 없는 탐색기 제외
        self.assertEqual(sorted(f["domains"]), sorted(["[고객사:C01]", "외부", "사내"]))
        self.assertNotIn("other.example", json.dumps(it, ensure_ascii=False))     # 원 도메인은 보내지 않는다
        self.assertEqual(f["cands"][0], ["P-9904", 1.0])                         # 예약 과제·영역 점수를 맨 앞에
        self.assertEqual(f["hint"], "OPT/ANALYSIS/OFFICE")
        self.assertEqual((it["group"], it["src_ver"], it["meta"]["rules_ver"]), ("P-9904", "hier/1", "2026.10.0"))
        self.assertEqual(it["rule"]["title_src"], "rule_doc")
        self.assertEqual(len(it["rule"]["reg_set"]), 8)


class RegvTest(unittest.TestCase):
    """T-H07 — 과제 추가 후 재분석: 이전 NONE·P-99xx 답 군집만 regv 로 재질의, 나머지 0회(내용 키 그대로)."""

    def _items(self, reg, store, cache, n_ev_units=None):
        units = {"u0": unit("u0", 300), "u1": unit("u1", 300), "u2": unit("u2", 300)}
        if n_ev_units:
            units.update(n_ev_units)
        groups = [Group(f"grp:{i:012d}", f"a{i}", f"u{i}", (f"u{i}",), 300) for i in range(3)]
        labels = {f"u{i}": rl(None, "none", "l") for i in range(3)}
        items, _ = CI.build_task_label_items(groups, labels, dict.fromkeys(labels, ff()), dict.fromkeys(labels, ("DEV", "h", "")),
                                             store, reg, K.cfg(), units=units, titles={g.key: ("x", "doc") for g in groups},
                                             cache=cache)
        return {it["key"]: it["fields"]["regv"] for it in items}

    def test_sticky(self):
        reg1 = K.golden_reg()
        cache = TitleCache()
        store = {"grp:000000000000": {"ans": {"project": "NONE", "conf": "m"}, "by": "ai"},
                 "grp:000000000001": {"ans": {"project": "P-0007", "conf": "h"}, "by": "ai"},
                 "grp:000000000002": {"ans": {"project": "P-9904", "conf": "h"}, "by": "ai"}}
        self.assertEqual(set(self._items(reg1, store, cache).values()), {""})       # 첫 실행 — 답을 지금 목록에서 받은 것으로
        team = dict(K.GOLDEN_TEAM, projects=K.GOLDEN_TEAM["projects"] + [{"id": "P-0020", "name": "과제F", "domain": "COM"}])
        reg2 = K.golden_reg(team=team)
        h2 = CI.set_hash(reg2.active_ids())
        got = self._items(reg2, store, cache)
        self.assertEqual(got, {"grp:000000000000": h2, "grp:000000000001": "", "grp:000000000002": h2})
        store2 = dict(store)
        store2["grp:000000000000"] = {"ans": {"project": "P-0020", "conf": "h"}, "by": "ai"}
        self.assertEqual(self._items(reg2, store2, cache), got)                    # 새 답이 와도 regv 는 그대로(붙박임)
        store3 = dict(store2)
        store3["grp:000000000000"] = {"ans": {"project": "NONE", "conf": "m"}, "by": "rule_pending"}
        self.assertEqual(self._items(reg2, store3, cache), got)

    def test_growth(self):
        reg = K.golden_reg()
        cache = TitleCache()
        store = {"grp:000000000000": {"ans": {"project": "P-0007", "conf": "l"}, "by": "ai"}}
        self.assertEqual(self._items(reg, store, cache)["grp:000000000000"], "")
        many = K.U("u0", "S1", [(K.F(f"m{i}", "mail", "x"), 1.0, "msg") for i in range(4)], effort_min=300)
        got = self._items(reg, store, cache, {"u0": many})
        self.assertEqual(got["grp:000000000000"], "g4")                         # 증거 2 → 4(2배)
        self.assertEqual(self._items(reg, store, cache, {"u0": many})["grp:000000000000"], "g4")


class ContextTest(unittest.TestCase):
    def test_prompt_context(self):
        reg = K.golden_reg()
        lines = CI.prompt_context(reg)
        text = "\n".join(lines)
        for name in ("과제A", "PROJ-A", "과제A 모듈", "브라켓"):
            self.assertNotIn(name, text)                                         # B14 — 이름·별칭·코드네임·키워드 0
        self.assertIn("P-0007 · DEV · 광학 모듈 신규 개발", lines)
        self.assertIn("P-9904 · COM · (공통 업무 — 과제 미지정)", lines)
        self.assertNotIn("P-0013", text)                                         # 퇴역(병합) 과제는 후보 밖
        comp = CI.prompt_context(reg, compact=True, cand_codes=["P-0008"])
        self.assertIn("P-0008 · MP · 센서 모듈 양산 대응", comp)
        self.assertNotIn("P-0007 · DEV · 광학 모듈 신규 개발", comp)
        self.assertEqual(comp[-4], CI.COMPACT_NOTE)
        local = {"schema": "lm27.registry_local/1", "vocab_add": {"fields": [{"code": "L_PHOTO", "name": "포토닉스",
                                                                             "maps_to": "OPT"}]},
                 "projects": [{"id": "L-0001", "name": "광센서 선행", "domain": "DEV", "copilot_desc": "",
                               "proposal_id": "pr_2"}]}
        reg2 = K.golden_reg(local=local)
        lines = CI.prompt_context(reg2)
        self.assertIn("L-0001 · DEV · (설명 없음)", lines)
        self.assertNotIn("L_PHOTO", "\n".join(lines))                             # 개인 어휘 코드는 싣지 않는다
        self.assertEqual(CI.prompt_context(K.empty_reg(), "taxonomy_bootstrap")[-1], "(없음)")
        codes = CI.codes_for(reg2)
        self.assertIn("L-0001", codes["projects"])
        self.assertIn("P-9901", codes["projects"])
        self.assertNotIn("P-9901", codes["projects_nonreserved"])

    def test_mask(self):
        reg = K.golden_reg()
        self.assertEqual(CI.mask_registry_names("PROJ-E 도면, proj-a 일정, 과제A의 건", reg),
                         "[과제:P-0007] 도면, [과제:P-0007] 일정, [과제:P-0007]의 건")
        self.assertEqual(CI.mask_registry_names("xPROJ-A1 그대로", reg), "xPROJ-A1 그대로")

    def test_desc_masked(self):
        """G-H2 둘째 방어선 — 레지스트리 검증을 지나 설명에 코드네임·별칭이 남아 있어도 문맥 줄에는 토큰으로."""
        import dataclasses
        reg = K.golden_reg()
        pv = dataclasses.replace(reg.projects["P-0007"], copilot_desc="PROJ-A 후속 · 과제A 모듈 정리")
        reg2 = dataclasses.replace(reg, projects=dict(reg.projects, **{"P-0007": pv}))
        for stage in (CI.STAGE, CI.BOOT_STAGE):
            text = "\n".join(CI.prompt_context(reg2, stage))
            self.assertNotIn("PROJ-A", text)
            self.assertNotIn("과제A 모듈", text)
            self.assertIn("P-0007 · DEV · [과제:P-0007] 후속 · [과제:P-0007] 정리", text)

    def test_web_drop(self):
        """T-H17 — 웹 노출 환경: 단계 명세의 web_drop_fields = ('domains',) — 열은 두고 값만 '-'(상대 계급이 나가지 않는다)."""
        self.assertEqual(CI.WEB_DROP_FIELDS, ("domains",))
        self.assertEqual(CI.SEND_FIELDS, ("kinds", "subjects", "files", "apps", "domains", "cands", "hint", "regv"))
        self.assertEqual(CI.TEXT_FIELDS, ("subjects", "files", "apps", "domains"))
        self.assertTrue(set(CI.WEB_DROP_FIELDS) <= set(CI.TEXT_FIELDS) and set(CI.CONTENT_KEY_FIELDS) < set(CI.SEND_FIELDS))
        from tests.hier.test_golden import item_line
        reg = K.golden_reg()
        u = unit("uw", 300, labels=["고객사:C01", "사내"])
        g = Group("grp:0000000000w1", "a", "uw", ("uw",), 300)
        items, _ = CI.build_task_label_items([g], {"uw": rl(None, "none", "l")}, {"uw": ff()},
                                             {"uw": ("DEV", "h", "")}, {}, reg, K.cfg(), units={"uw": u},
                                             titles={g.key: ("공차해석", "doc")})
        f = dict(items[0]["fields"])
        full = item_line(1, f)
        self.assertIn("[고객사:C01]", full)
        dropped = item_line(1, dict(f, **{k: [] for k in CI.WEB_DROP_FIELDS}))
        self.assertEqual(full.count(" | "), dropped.count(" | "))
        self.assertEqual(dropped.split(" | ")[5], "-")
        self.assertNotIn("고객사", dropped)
        self.assertNotIn("사내", dropped)

    def test_validate_more(self):
        codes = CI.codes_for(K.golden_reg())
        base = {"project": "P-0007", "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "title": "공차 해석", "conf": "h"}
        self.assertEqual(CI.validate_answer(base, codes), "")
        self.assertEqual(CI.validate_answer(dict(base, title="x" * 81), codes), "too_long:title")
        self.assertEqual(CI.validate_answer(dict(base, dom="ZZ"), codes), "bad_enum:dom")
        self.assertEqual(CI.validate_answer(dict(base, project="NEW", new="방열 모듈"), codes), "missing:dom")
        self.assertEqual(CI.validate_answer(dict(base, field="L_PHOTO"), codes), "unknown_code:field")
        self.assertEqual(CI.validate_answer(dict(base, id="x"), codes, [1]), "extra")
        for k, v in (("project", ["P-0007"]), ("field", {"x": 1}), ("conf", ["h"]), ("dom", ["DEV"]), ("title", 3)):
            self.assertNotEqual(CI.validate_answer(dict(base, **{k: v}), codes), "", k)     # 형이 틀린 값 — 예외 없이 무효


class FileTest(unittest.TestCase):
    def test_ai_in_out(self):
        with K.TmpTree() as t:
            n = CI.write_ai_in(t.paths, CI.STAGE, [{"key": "grp:1", "fields": {"kinds": "문서 1"}}])
            self.assertEqual(n, 1)
            raw = t.paths.ai_in(CI.STAGE).read_bytes()
            self.assertTrue(raw.endswith(b"\n") and b"\r" not in raw)
            self.assertEqual(CI.read_ai_out(t.paths.ai_out(CI.STAGE)), {})
            out = {"schema": 1, "stage": "task_label", "items": {
                "grp:1": {"ans": {"project": "P-0007", "conf": "h"}, "by": "ai", "rid": "R7F3QK", "asks": 1,
                          "at": "2026-10-05T10:00:00+09:00", "reg_set": "abcd1234"},
                "grp:2": {"by": "rule_pending"}}}
            t.write_json(t.paths.ai_out(CI.STAGE), out)
            got = CI.read_ai_out(t.paths.ai_out(CI.STAGE))
            self.assertEqual(set(got), {"grp:1"})
            self.assertEqual(got["grp:1"]["reg_set"], "abcd1234")


class BootstrapIoTest(unittest.TestCase):
    def test_samples(self):
        reg = K.golden_reg()
        units = {f"u{i}": unit(f"u{i}", 100 - i, subjects=("PROJ-A 결과 공유 요청 드립니다 " * 3,)) for i in range(6)}
        groups = [Group(f"grp:{i:012d}", "a", f"u{i}", (f"u{i}",), 100 - i) for i in range(6)]
        labels = {f"u{i}": rl("P-9904", "domain_rule", "m", domain="COM") for i in range(6)}
        titles = {g.key: ("같은 이름", "doc") for g in groups}
        titles["grp:000000000005"] = ("다른 이름", "subject")
        s = CI.build_bootstrap_samples(groups, labels, reg, K.cfg(), units=units, titles=titles)
        self.assertEqual([x["key"] for x in s], ["grp:000000000000", "grp:000000000001", "grp:000000000002",
                                                 "grp:000000000005"])           # 같은 규칙 이름은 3개까지
        f = s[0]["fields"]
        self.assertEqual(set(f), set(CI.BOOT_SEND_FIELDS))
        self.assertEqual(f["dom"], "COM")
        self.assertTrue(f["subject"].startswith("[과제:P-0007]") and len(f["subject"]) <= 50)
        self.assertEqual(f["peer"], "사내")
        s2 = CI.build_bootstrap_samples(groups, labels, reg, K.cfg({"hier.bootstrap.maxLines": 2}), units=units,
                                        titles=titles)
        self.assertEqual(len(s2), 2)
        self.assertEqual(CI.fit_lines([10, 10, 10], 100, 122), 2)
        self.assertEqual(CI.fit_lines([10], 200, 100), 0)

    def test_consolidate(self):
        rows = [{"name": "방열 모듈", "code": "", "dom": "DEV", "kind": "project", "match": ["방열", "열해석", "a", "b"]},
                {"name": "x", "code": "P-0007", "dom": "DEV", "kind": "project"},
                {"name": "운영", "code": "", "dom": "COM", "kind": "nonwork"}]
        props = [{"proposal_id": "pr_1", "label": "방열모듈", "domain_guess": "DEV", "status": "pending"},
                 {"proposal_id": "pr_2", "label": "센서 모듈", "domain_guess": "MP", "status": "pending"},
                 {"proposal_id": "pr_3", "label": "거절", "domain_guess": "MP", "status": "rejected"}]
        items = CI.build_consolidate_items(rows, props, K.golden_reg())
        self.assertEqual([it["fields"]["name"] for it in items], ["방열 모듈", "센서 모듈"])   # ukey 중복·비 pending 제외
        self.assertEqual(items[0]["fields"]["match"], ["방열", "열해석", "a"])
        rows2 = [{"name": "방열 개선", "code": "", "dom": "DEV", "kind": "project", "match": ["PROJ-A 시험", "과제A 모듈"]}]
        it = CI.build_consolidate_items(rows2, [], K.golden_reg())[0]
        self.assertEqual(it["fields"]["match"], ["[과제:P-0007] 시험", "[과제:P-0007]"])  # 낱말도 가린다(G-H2)


if __name__ == "__main__":
    unittest.main()
