# -*- coding: utf-8 -*-
r"""WP-22 분류 특징 시험 — H §4.1·§4.2 · X-244(Feat.kind 대응) · X-245(앱 범주) · W1a CR(HierTags.fam = 시간 코어 fam_key).

- 행 → Feat: kind 대응, pc.events·사적·친목·광고·취소된 수동 기록은 특징 없음, 메일·팀즈·일정·파일·창·git·연산·수동·요약 증인.
- 상대 계급: 받은 메일 sender_label + 로컬 사람 사전(사내·개인메일·고객사·협력사·공공 계급·그 밖 도메인), 원 도메인은 mail_doms 로만.
- 문서군 키: 시간 코어 `lm27.time.evidence.normalize` 가 만드는 DocE.fam·Samp.fam·첨부 키와 같은가(B_GENERIC 제외).
- 결정성: 행 순서를 섞어도 같은 특징.
자료는 합성(자리표시자·시험 전용 무키 해시)뿐이다.
"""
import random
import unittest

from lm27.hier.features import (FamKeyer, Feat, PersonClasses, domain_class, feat, features_of, lsec_of, month_of,
                                person_classes, union_feat)
from lm27.time.tokens import B_GENERIC
from tests.fixtures.wp22 import hierkit as K
from tests.fixtures.wp22.hierkit import row

K.install_fakes()


def doc_rows():
    d_rep, d_spec, d_g = K.fake_doc("보고서"), K.fake_doc("센서사양"), K.fake_doc("공차해석")
    s1, s2, s3 = K.fake_key("s", "a"), K.fake_key("s", "b"), K.fake_key("s", "c")
    return [
        row("pc_file", "pc.files", "2026-09-01T01:00:00Z", doc_key=d_rep, name_masked="보고서", ext=".pptx",
            dir_keys=[s1, s2], op="save"),
        row("pc_file", "pc.files", "2026-09-02T01:00:00Z", doc_key=d_rep, name_masked="보고서", ext=".pptx",
            dir_keys=[s3, s2], op="save"),
        row("pc_file", "pc.files", "2026-09-02T02:00:00Z", doc_key=d_spec, name_masked="센서사양_v2", ext=".xlsx",
            dir_keys=[s1], op="save"),
        row("mail", "mail.com", "2026-09-02T03:00:00Z", msg_key=K.fake_key("m", 1, 24), direction="out",
            thread_key=K.fake_key("t", 1), subject_masked="[과제:P-0007] 센서사양 송부", attach_keys=[d_spec, d_rep],
            attach_names_masked=["센서사양_v2.xlsx", "보고서.pptx"], attach_exts=[".xlsx", ".pptx"]),
        row("pc_session", "pc.sampler", "2026-09-02T04:00:00Z", ts_end="2026-09-02T04:05:00Z", app_id="excel",
            app_class="office", title_masked="공차해석 - Excel", doc_key=d_g, session_state="active", idle_sec=3,
            layer="L3", ts_precision="exact"),
        row("pc_session", "pc.events", "2026-09-02T00:00:00Z", ts_end="2026-09-02T09:00:00Z", layer="L0",
            event_class="boot", session_state="active"),
    ]


class KindTest(unittest.TestCase):
    def test_kinds_and_skips(self):
        reg = K.golden_reg()
        rows = doc_rows() + [
            row("teams", "teams.uia", "2026-09-03T01:00:00Z", msg_key=K.fake_key("m", 2, 24), chat_key=K.fake_key("h", 1),
                chat_type="channel", thread_key=K.fake_key("t", 9), direction="received", body_masked="브라켓 도면 확인",
                chat_title_masked="과제 방"),
            row("cal", "cal.com", "2026-09-03T02:00:00Z", ts_end="2026-09-03T03:00:00Z", msg_key=K.fake_key("e", 1, 24),
                subject_masked="광학모듈 설계 검토 회의", flags={"organizer_me": True}),
            row("cal", "cal.com", "2026-09-03T04:00:00Z", ts_end="2026-09-03T05:00:00Z", msg_key=K.fake_key("e", 2, 24),
                subject_masked="개인 일정", flags={"sensitivity": 2}),
            row("pc_git", "pc.git", "2026-09-03T06:00:00Z", doc_key=K.fake_key("r", "repo"), msg_masked="빌드 수정",
                exts=["py"], commit_key=K.fake_key("g", 1)),
            row("pc_compute", "pc.compute", "2026-09-03T07:00:00Z", ts_end="2026-09-03T08:00:00Z", app_id="ansys_fluent"),
            row("manual", "manual", "2026-09-04T00:00:00Z", text_masked="현장 방문", project_id="P-0007", man_kind="work",
                id="aaaaaaaaaaaaaaa1"),
            row("manual", "manual", "2026-09-04T00:00:00Z", text_masked="잘못 입력", man_kind="work", id="aaaaaaaaaaaaaaa2"),
            row("manual", "manual", "2026-09-04T01:00:00Z", man_kind="retract", retract_of="aaaaaaaaaaaaaaa2",
                id="aaaaaaaaaaaaaaa3"),
            row("mail", "mail.copilot", "2026-09-05T00:00:00Z", ts_precision="date", text_masked="브라켓 협의 메일 2건",
                msg_key=K.fake_key("m", 3, 24)),
            row("mail", "mail.com", "2026-09-05T01:00:00Z", msg_key=K.fake_key("m", 4, 24), priv_class="private",
                subject_masked="사적"),
            row("mail", "mail.com", "2026-09-05T02:00:00Z", msg_key=K.fake_key("m", 5, 24), flags={"ad": True},
                subject_masked="광고"),
        ]
        fs = features_of(rows, reg, None, None, K.cfg())
        kinds = sorted(f.kind for f in fs)
        self.assertEqual(kinds.count("file"), 3)
        self.assertEqual(kinds.count("win"), 1)                       # pc.events 는 특징 없음
        self.assertIn("teams", kinds)
        self.assertEqual(kinds.count("cal"), 2)
        self.assertIn("git", kinds)
        self.assertIn("compute", kinds)
        self.assertEqual(kinds.count("manual"), 1)                    # 취소된 기록과 취소 줄은 없다
        self.assertEqual(kinds.count("summary"), 1)
        self.assertEqual(kinds.count("mail"), 1)                      # 사적·광고 메일 없음
        summ = next(f for f in fs if f.kind == "summary")
        self.assertEqual(summ.weight_mult, 0.5)
        man = next(f for f in fs if f.kind == "manual")
        self.assertEqual(man.manual["project_id"], "P-0007")
        tm = next(f for f in fs if f.kind == "teams")
        self.assertTrue(tm.conv.endswith(":" + K.fake_key("t", 9)))   # 채널 = 방 + 답글 루트(시간 코어 Msg.conv 와 같다)
        self.assertEqual(tm.direction, "in")
        priv = [f for f in fs if f.kind == "cal" and not f.text]
        self.assertEqual(len(priv), 1)                                # 개인 일정 제목 토큰은 싣지 않는다
        cal = next(f for f in fs if f.kind == "cal" and f.text)
        self.assertIn("organizer_me", cal.flags)
        git = next(f for f in fs if f.kind == "git")
        self.assertEqual(git.fams, frozenset({K.fake_key("r", "repo")}))
        self.assertIn(".py", git.exts)
        comp = next(f for f in fs if f.kind == "compute")
        self.assertEqual(comp.app_cat, "해석")

    def test_order_independent(self):
        reg = K.golden_reg()
        rows = doc_rows()
        a = features_of(rows, reg, None, None, K.cfg())
        r = list(rows)
        random.Random(3).shuffle(r)
        b = features_of(r, reg, None, None, K.cfg())
        self.assertEqual([(f.id, f.kind, sorted(f.fams), sorted(f.toks)) for f in a],
                         [(f.id, f.kind, sorted(f.fams), sorted(f.toks)) for f in b])

    def test_duplicate_ids_once(self):
        reg = K.golden_reg()
        r = doc_rows()[0]
        fs = features_of([r, dict(r)], reg, None, None, K.cfg())
        self.assertEqual(len(fs), 1)


class FamKeyTest(unittest.TestCase):
    """HierTags.fam 키 = 시간 코어 fam_key(W1a CR) — 같은 행으로 시간 코어 정규화와 대조한다."""

    def test_same_as_time_core(self):
        from lm27.time.evidence import normalize
        reg = K.golden_reg()
        rows = doc_rows()
        fs = features_of(rows, reg, None, None, K.cfg())
        ev, _a = normalize(rows, {}, K.cfg(), "2026-09-30T23:00:00+09:00", None)
        time_fams = {d.fam for d in ev.docs} | {s.fam for s in ev.samples} | {a for m in ev.msgs for a in m.atts}
        time_fams -= {"", B_GENERIC}
        hier_fams = {fk for f in fs for fk in f.fams}
        self.assertEqual(hier_fams, time_fams)
        files = [f for f in fs if f.kind == "file" and "보고서" in f.text]
        self.assertEqual(len({fk for f in files for fk in f.fams}), 2)   # 범용 이름 = 폴더 키로 갈린다(@)
        self.assertTrue(all("@" in fk for f in files for fk in f.fams))
        mail = next(f for f in fs if f.kind == "mail")
        self.assertEqual(len(mail.fams), 1)                              # 범용 첨부(폴더 모호) = B_GENERIC → 뺀다
        self.assertNotIn(B_GENERIC, mail.fams)

    def test_keyer_index_priority(self):
        dk = K.fake_doc("x")
        rows = [row("pc_session", "pc.sampler", "2026-09-01T00:00:00Z", doc_key=dk, title_masked="창이름 - 앱"),
                row("pc_file", "pc.files", "2026-09-01T00:00:00Z", doc_key=dk, name_masked="파일이름", ext=".docx")]
        k = FamKeyer(rows, K.cfg())
        self.assertEqual(k.best_name(dk), "파일이름.docx")             # 파일(0) > 첨부(1) > 창(2)
        self.assertEqual(k.key(dk), dk)
        self.assertEqual(k.key(""), "")


class PeerClassTest(unittest.TestCase):
    def test_classes(self):
        from lm27.privacy.rules import PERSONAL_MAIL_DOMAINS
        reg = K.golden_reg(team=dict(K.GOLDEN_TEAM, internal_domains=["corp.example"],
                                     partners=[{"id": "V01", "names": [], "domains": ["vendor.example"]}],
                                     public_domain_classes={".ac.kr": "학교"}))
        pd = {"format": "lm27-persondir/1", "people": {
            K.fake_who(1): {"smtp": ["a@corp.example"]}, K.fake_who(2): {"smtp": ["b@custa.example"]},
            K.fake_who(3): {"smtp": ["c@sub.vendor.example"]}, K.fake_who(4): {"smtp": ["@".join(("d", "lab.example.ac.kr"))]},
            K.fake_who(5): {"smtp": ["e@" + PERSONAL_MAIL_DOMAINS[0]]}, K.fake_who(6): {"smtp": ["f@other.example"]},
            K.fake_who(7): {"smtp": ["me@corp.example"], "self": True}, K.fake_who(8): {"names": ["김철수"], "internal": True}}}
        pc = person_classes(pd, reg)
        self.assertEqual(pc.labels[K.fake_who(1)], frozenset({"사내"}))
        self.assertEqual(pc.labels[K.fake_who(2)], frozenset({"고객사:C01"}))
        self.assertEqual(pc.labels[K.fake_who(3)], frozenset({"협력사:V01"}))
        self.assertEqual(pc.labels[K.fake_who(4)], frozenset({"학교"}))
        self.assertEqual(pc.labels[K.fake_who(5)], frozenset({"개인메일"}))
        self.assertEqual(pc.labels[K.fake_who(6)], frozenset({"other.example"}))
        self.assertNotIn(K.fake_who(7), pc.labels)                        # 본인 제외
        self.assertEqual(pc.labels[K.fake_who(8)], frozenset({"사내"}))
        r = row("mail", "mail.com", "2026-09-01T00:00:00Z", msg_key=K.fake_key("m", 9, 24), direction="in",
                sender_label="고객사:C01", sender_key=K.fake_who(2), counterpart_keys=[K.fake_who(6)],
                subject_masked="문의")
        f = features_of([r], reg, pd, None, K.cfg())[0]
        self.assertEqual(f.dom_labels, frozenset({"고객사:C01", "other.example"}))
        self.assertEqual(f.mail_doms, frozenset({"custa.example", "other.example"}))
        self.assertEqual(domain_class("x.custa.example", reg), "고객사:C01")
        self.assertEqual(person_classes(None, reg), PersonClasses())


class HelperTest(unittest.TestCase):
    def test_feat_and_union(self):
        a = feat("a", "file", "[과제:P-0007] 브라켓_v3.sldprt", exts=[".SLDPRT"], fams=["d1"], t=10)
        b = feat("b", "win", "[고객사:C01] 광학모듈", app="creo_parametric", app_cat="CAD", fams=["d1"], t=5)
        self.assertEqual(a.ent["과제"], frozenset({"P-0007"}))
        self.assertIn("브라켓", a.toks)
        self.assertEqual(a.exts, frozenset({".sldprt"}))
        u = union_feat([a, b], "fam:d1")
        self.assertEqual(u.t, 5)
        self.assertEqual(u.ent["과제"], frozenset({"P-0007"}))
        self.assertEqual(u.ent["고객사"], frozenset({"C01"}))
        self.assertEqual(u.app, "creo_parametric")
        self.assertTrue(isinstance(u, Feat))
        self.assertEqual(union_feat([], "z").id, "z")

    def test_time(self):
        self.assertEqual(lsec_of("2020-01-01T00:00:00Z", 540), 9 * 3600)
        self.assertEqual(month_of(lsec_of("2026-09-30T15:30:00Z", 540)), "2026-10")
        self.assertEqual(lsec_of("bad", 540), 0)
        self.assertEqual(month_of(0), "")


if __name__ == "__main__":
    unittest.main()
