# -*- coding: utf-8 -*-
r"""WP-22 명명 군집·규칙 이름·제목 캐시 시험 — H §5(G1~G3·제약·대표·키 안정) · §5.3 · §5.4 · 계약 §3.15 · §4.4.
군집은 인스턴스를 합치지 않는다(H-I5) — 구성원 목록만 만든다."""
import unittest
from datetime import date

from lm27.hier import groups as G
from tests.fixtures.wp22 import hierkit as K


def u(uid, kind="SELF", fams=None, start=0, peer="", follow_of=None, first_key=None, effort=10):
    return {"id": uid, "kind": kind, "fams": fams or {}, "start": start, "peer": peer, "follow_of": follow_of,
            "first_key": first_key or ("fk|" + uid), "effort_min": effort}


class NameGroupsTest(unittest.TestCase):
    def test_rules_and_constraints(self):
        units = [u("u_a", fams={"dA": 2}, start=5), u("u_b", fams={"dA": 2}, start=3),            # G2
                 u("u_c", "S1", {"dS": 3}, 7, peer="w1"), u("u_d", "S1", {"dS": 3}, 8, peer="w1"),  # G3
                 u("u_e", "S1", {"dS": 3}, 9, peer="w2"),                                          # 상대 다름
                 u("u_f", "APP", {}, 1), u("u_g", "APP", {}, 2),                                   # APP 는 앱만으로 묶지 않음
                 u("u_h", "SELF", {"dB@s1+s2": 2}, 4), u("u_i", "SELF", {"dB@s1+s2": 2}, 6)]        # 범용 문서군
        gs = G.name_groups(units, {}, K.cfg())
        mem = sorted(g.members for g in gs)
        self.assertIn(("u_a", "u_b"), mem)
        self.assertIn(("u_c", "u_d"), mem)
        self.assertIn(("u_e",), mem)
        self.assertIn(("u_f",), mem)
        self.assertIn(("u_h",), mem)
        ab = next(g for g in gs if g.members == ("u_a", "u_b"))
        self.assertEqual(ab.rep, "u_b")                                       # 첫 차수 시작이 가장 이른 구성원
        self.assertEqual(ab.key, G.group_key("fk|u_b"))
        self.assertEqual(ab.effort_min, 20)
        conf = {"u_a": {"source": "token", "project": "P-0007"}, "u_b": {"source": "rule", "project": "P-0008"}}
        mem = sorted(g.members for g in G.name_groups(units, conf, K.cfg()))
        self.assertIn(("u_a",), mem)                                          # 확정 과제 둘 → 따로
        self.assertIn(("u_b",), mem)

    def test_max_group_and_key_stability(self):
        chain = [u(f"u_w{i}", fams={"dW": 2}, start=100 + i, follow_of=(f"u_w{i - 1}" if i else None)) for i in range(5)]
        gs = G.name_groups(chain[:3], {}, K.cfg())
        self.assertEqual(len(gs), 1)
        k3 = gs[0].key
        gs = G.name_groups(chain, {}, K.cfg())
        self.assertEqual([g.key for g in gs], [k3])                          # 군집이 자라도 대표·키 그대로
        gs = G.name_groups(chain, {}, K.cfg({"hier.name.maxGroup": 2}))
        self.assertTrue(all(len(g.members) <= 2 for g in gs))

    def test_order_independent(self):
        units = [u(f"u_{i:02d}", fams={f"d{i % 3}": 2}, start=i) for i in range(12)]
        a = [(g.key, g.members) for g in G.name_groups(units, {}, K.cfg())]
        b = [(g.key, g.members) for g in G.name_groups(list(reversed(units)), {}, K.cfg())]
        self.assertEqual(a, b)


class TitleTest(unittest.TestCase):
    def test_stems(self):
        self.assertEqual(G.display_stem("[과제:P-0007]_공차해석_v3_최종.xlsx"), "공차해석")
        self.assertEqual(G.display_stem("회의록(2).docx"), "회의록")
        self.assertEqual(G.subject_title("FW: [사람#1a2b3c] 사양 송부요 [금액]"), "사양")
        self.assertEqual(G.subject_title("사양 송부드립니다"), "사양 송부드립니다")     # 접두 뒤 3자 이상은 남긴다
        self.assertEqual(G.clip_title("광학 모듈 공차 해석 결과 정리 및 보고서 작성", 12), "광학 모듈 공차 해석")
        self.assertEqual(G.clip_title("가나다라마바사아자차카타파하", 5), "가나다라마")

    def test_fallback_order(self):
        ctx = {"reg": K.golden_reg(), "cfg": K.cfg()}
        self.assertEqual(G.rule_title({"docs": [["보고서.pptx", 400], ["20261001.xlsx", 300]],
                                       "subjects": ["회의 자료 송부", "공차 해석 결과 공유"]}, ctx),
                         ("공차 해석", "subject"))
        self.assertEqual(G.rule_title({"docs": [], "subjects": ["RE: 검토 부탁드립니다"], "app_cat": "해석"}, ctx),
                         ("해석 프로그램 작업", "app"))
        self.assertEqual(G.rule_title({"app_cat": "사무", "app_id": "excel"}, ctx), ("엑셀 작업", "app"))
        self.assertEqual(G.rule_title({}, ctx), ("기타·기타 단위업무", "generic"))
        self.assertEqual(G.app_cat_name("", "unknown:tool.exe"), "미상 프로그램")
        self.assertTrue(G.is_generic_stem("새 문서 3", ()))

    def test_material(self):
        f = K.F("f", "file", "x")
        units = {"u_a": K.U("u_a", "SELF", [(f, 1.5, "doc")], fams={"dA": 3, "dG@s1": 2}, fam_min={"dA": 30, "dG@s1": 99},
                            fam_names={"dA": "공차해석_v3.xlsx", "dG@s1": "보고서.pptx"}, subjects=("요청",),
                            app_min={"해석": 20, "사무": 50}, app_ids={"ansys_fluent": 20, "excel": 50})}
        g = G.Group("grp:x", "a", "u_a", ("u_a",), 10)
        m = G.title_material(g, units)
        self.assertEqual(m["docs"], [("공차해석_v3.xlsx", 30)])                 # 범용 문서군은 빼고
        self.assertEqual(m["app_cat"], "해석")                                  # 공학 범주 우선
        self.assertEqual(m["subjects"], ["요청"])


class TitleCacheTest(unittest.TestCase):
    def test_roundtrip_bak_prune(self):
        with K.TmpTree() as t:
            c = G.TitleCache.for_paths(t.paths)
            self.assertEqual(c.groups, {})
            c.put("grp:aaaaaaaaaaaa", title="광학 모듈 공차 해석", src="ai", conf="h", at="2026-10-05T10:00:00+09:00")
            c.touch("grp:aaaaaaaaaaaa", "2026-10-05", "mk1")
            self.assertTrue(c.save())
            self.assertFalse(c.save())                                         # 바뀐 것 없으면 쓰지 않는다
            c2 = G.TitleCache.for_paths(t.paths)
            self.assertEqual(c2.get("grp:aaaaaaaaaaaa")["title"], "광학 모듈 공차 해석")
            c2.put("aaaaaaaaaaaa", conf="m")
            c2.save()
            self.assertTrue(t.paths.hier_local_file("title_cache.json.bak").exists())
            t.paths.hier_local_file("title_cache.json").write_bytes(b"{broken")
            c3 = G.TitleCache.for_paths(t.paths)
            self.assertEqual(c3.get("grp:aaaaaaaaaaaa")["conf"], "h")           # 깨지면 .bak(직전 판)
            c3.touch("grp:bbbbbbbbbbbb", "2026-10-05", "mk2")
            n = c3.prune(date(2027, 12, 1), 400)
            self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
