# -*- coding: utf-8 -*-
"""WP-18 merge — 메시지 병합(C §7 · CM §7 · CT §5 · X-148 · T-11 · T-02).

신뢰 순위 COM > 색인 > OWA(minute) > OWA(date) > Copilot · 필드 단위 최선 값 + provenance · date-only 흡수 · *.copilot
병합 제외 · 교차 경로 보조 병합(같은 PC·경로 안의 다른 키는 합치지 않음) · 공사 판정은 엄격한 쪽 · T-11 건수 보존·중복 0
(멀티 PC·멀티 경로·UTC 클라우드PC) · 입력 순서와 무관(T-02) · 입력 행 불변."""
import copy
import json
import random
import unittest

from lm27.normalize.merge import merge_messages
from tests.fixtures.wp18 import rows as R

T = "2026-09-01T01:00:00Z"            # 10:00 KST


def by_kind(out, kind):
    return [r for r in out if r["kind"] == kind]


def canon(rows):
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


class ExactMergeTest(unittest.TestCase):
    def test_same_key_across_pcs_and_paths(self):
        a = R.mail(T, msg="M1", pc=R.PC1, observed=R.plus(T, minutes=5))
        b = R.mail(T, msg="M1", pc=R.PC2, observed=R.plus(T, hours=3))
        c = R.mail(T, msg="M1", src="mail.index", pc=R.PC1)
        st = {}
        out = merge_messages([c, b, a], stats=st)
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertEqual(m["src"], "mail.com")
        self.assertEqual(m["id"], min(a["id"], b["id"]), "기준 행 = 신뢰 순위 첫 행(동률 id 순)")
        self.assertEqual(m["observed_at"], R.plus(T, hours=3))
        self.assertEqual({(p["src"], p["pc_id"]) for p in m["provenance"]},
                         {("mail.com", R.PC1), ("mail.com", R.PC2), ("mail.index", R.PC1)})
        self.assertEqual(m["provenance"][-1]["src"], "mail.index", "provenance 는 신뢰 순위")
        self.assertEqual(m["alias_keys"], [a["msg_key"]])
        self.assertEqual(st["exact_merged"], 2)
        self.assertEqual(st["rows_out"], 1)

    def test_trust_order_and_time_from_best_precision(self):
        owa_d = R.mail("2026-08-31T15:00:00Z", msg="M2", src="mail.owa", pc=R.CLOUD, prec="date", off="+00:00")
        owa_m = R.mail(R.plus(T, seconds=30), msg="M2", src="mail.owa", pc=R.CLOUD, off="+00:00")
        idx = R.mail(T, msg="M2", src="mail.index")
        out = merge_messages([owa_d, owa_m, idx])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["src"], "mail.index", "COM 이 없으면 색인이 기준")
        self.assertEqual(out[0]["ts_precision"], "minute")
        out = merge_messages([owa_d, owa_m])
        self.assertEqual(out[0]["ts_utc"], owa_m["ts_utc"], "OWA(minute) > OWA(date)")
        self.assertEqual(out[0]["ts_local_offset"], "+00:00")

    def test_teams_web_exact_time_preferred(self):
        uia = R.teams(T, msg="TM", src="teams.uia", room="U")
        web = R.teams(R.plus(T, seconds=37), msg="TM", src="teams.web", room="W", prec="exact", pc=R.CLOUD)
        m = merge_messages([uia, web])[0]
        self.assertEqual(m["ts_precision"], "exact")
        self.assertEqual(m["ts_utc"], web["ts_utc"])
        self.assertEqual(m["chat_key"], web["chat_key"], "웹 chat_key 우선(X-148)")


class FieldLevelTest(unittest.TestCase):
    def test_best_values(self):
        com = R.mail(T, msg="F", cps=(R.KIM,), rcv="unknown", n_to=None, n_cc=None, sender="w" + "1" * 16,
                     flags={"list_unsub": True})
        com.pop("n_to"), com.pop("n_cc")
        idx = R.mail(T, msg="F", src="mail.index", cps=(R.KIM, R.LEE), rcv="to", n_to=2, n_cc=1, sender=None,
                     flags={"has_file": True, "utc_suspect": True}, attach_keys=[R.doc("a")], attach_names_masked=["a.xlsx"],
                     attach_exts=[".xlsx"])
        m = merge_messages([idx, com])[0]
        self.assertEqual(m["counterpart_keys"], sorted({R.KIM, R.LEE}), "상대 키 합집합")
        self.assertEqual(m["rcv"], "to", "unknown 이 아닌 첫 값")
        self.assertEqual((m["n_to"], m["n_cc"]), (2, 1))
        self.assertEqual(m["sender_key"], "w" + "1" * 16)
        self.assertEqual(m["flags"].get("list_unsub"), True)
        self.assertEqual(m["flags"].get("has_file"), True)
        self.assertNotIn("utc_suspect", m["flags"], "UTC 의심은 시각을 준 행의 것만")
        self.assertEqual((m["attach_keys"], m["attach_names_masked"], m["attach_exts"]),
                         ([R.doc("a")], ["a.xlsx"], [".xlsx"]), "첨부 키·이름 짝은 같은 행에서")

    def test_counterparts_capped(self):
        a = R.mail(T, msg="C", cps=[R.who(i) for i in range(15)])
        b = R.mail(T, msg="C", src="mail.index", cps=[R.who(i) for i in range(10, 30)])
        m = merge_messages([a, b])[0]
        self.assertEqual(len(m["counterpart_keys"]), 20)
        self.assertTrue(m["flags"].get("cap_hit"))

    def test_privacy_strictest_wins(self):
        a = R.teams(T, msg="P", src="teams.web", prec="exact", body="[과제:P-0001] 오늘 회식 장소 공유드립니다",
                    cues=("rep",), room="W")
        b = R.teams(T, msg="P", src="teams.uia", body="", priv_class="social", room="U")
        m = merge_messages([a, b])[0]
        self.assertEqual(m["priv_class"], "social")
        self.assertEqual(m["body_masked"], "")
        self.assertEqual(m["act_cues"], [])

    def test_ad_band_suspect_wins_and_inputs_unchanged(self):
        a = R.mail(T, msg="AD")
        b = R.mail(T, msg="AD", src="mail.index", ad_band="suspect", ad_score=4, ad_why=["ad_word"])
        snap = copy.deepcopy([a, b])
        m = merge_messages([a, b])[0]
        self.assertEqual((m["ad_band"], m["ad_score"], m["ad_why"]), ("suspect", 4, ["ad_word"]))
        self.assertEqual([a, b], snap, "입력 행을 바꾸지 않는다")


class CopilotTest(unittest.TestCase):
    def test_witness_never_merged_with_messages(self):
        msg = R.mail(T, msg="W1")
        wit = R.mail("2026-08-31T15:00:00Z", msg=msg["msg_key"], src="mail.copilot", pc=R.CLOUD, prec="summary",
                     subject="", text_masked="요약: 설계 검토 메일 1건", confidence=0.3)
        out = merge_messages([msg, wit])
        self.assertEqual(len(out), 2)
        self.assertEqual({r["src"] for r in out}, {"mail.com", "mail.copilot"})

    def test_witness_duplicates_deduped(self):
        w1 = R.teams("2026-08-31T15:00:00Z", msg="CP", src="teams.copilot", pc=R.CLOUD, prec="summary",
                     observed="2026-09-02T00:00:00Z", room="C")
        w2 = dict(w1, pc_id=R.PC2, id=R.rid("w2"), observed_at="2026-09-03T00:00:00Z")
        st = {}
        out = merge_messages([w1, w2], stats=st)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["observed_at"], "2026-09-03T00:00:00Z")
        self.assertEqual(len(out[0]["provenance"]), 2)
        self.assertEqual(st["copilot_dups"], 1)


class DateOnlyTest(unittest.TestCase):
    """C §7.3 — 같은 (날짜, box, thread_key) 에 분 단위 사본이 있으면 date-only 행은 버린다."""

    def test_absorbed_and_kept(self):
        minute = R.mail("2026-09-01T23:30:00Z", msg="D1", thr="TH")            # KST 09-02 08:30
        dated = R.mail("2026-09-01T15:00:00Z", msg="D2", src="mail.owa", pc=R.CLOUD, prec="date", thr="TH")
        other = R.mail("2026-09-01T15:00:00Z", msg="D3", src="mail.owa", pc=R.CLOUD, prec="date", thr="OTHER")
        sent = R.mail("2026-09-01T15:00:00Z", msg="D4", src="mail.owa", pc=R.CLOUD, prec="date", thr="TH", box="sent")
        st = {}
        out = merge_messages([minute, dated, other, sent], off_min=540, stats=st)
        self.assertEqual({r["msg_key"] for r in out}, {minute["msg_key"], other["msg_key"], sent["msg_key"]})
        self.assertEqual(st["date_absorbed"], 1)

    def test_teams_date_rows(self):
        exact = R.teams("2026-09-01T02:00:00Z", msg="E", room="R", prec="minute")
        dated = R.teams("2026-08-31T15:00:00Z", msg="E2", room="R", prec="date")
        other_room = R.teams("2026-08-31T15:00:00Z", msg="E3", room="Q", prec="date")
        out = merge_messages([exact, dated, other_room], off_min=540)
        self.assertEqual({r["msg_key"] for r in out}, {exact["msg_key"], other_room["msg_key"]})


class FuzzyTest(unittest.TestCase):
    """C §7.2 퍼지 키 — 경로마다 키가 다른 같은 메시지(COM Message-ID 대 색인 퍼지 키, UIA 합성 방 대 웹 방)."""

    def test_mail_com_vs_index(self):
        com = R.mail(T, msg="mid:<a@corp.example>")
        idx = R.mail(R.plus(T, seconds=60), msg="idx-fuzzy", src="mail.index", cps=(R.KIM, R.LEE))
        st = {}
        out = merge_messages([com, idx], stats=st)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["msg_key"], com["msg_key"], "기준 = COM")
        self.assertEqual(out[0]["alias_keys"], sorted({com["msg_key"], idx["msg_key"]}))
        self.assertEqual(st["fuzzy_merged"], 1)

    def test_mail_not_merged_when_different(self):
        com = R.mail(T, msg="X1")
        for other in (R.mail(T, msg="X2", src="mail.index", subject="다른 제목"),
                      R.mail(R.plus(T, seconds=180), msg="X3", src="mail.index"),
                      R.mail(T, msg="X4", src="mail.index", box="sent"),
                      R.mail(T, msg="X5", src="mail.index", sender=R.LEE),
                      R.mail(T, msg="X6", src="mail.index", thr="OTHER"),
                      R.mail(T, msg="X7", src="mail.com")):                       # 같은 PC·같은 경로의 다른 키 = 다른 메일
            self.assertEqual(len(merge_messages([com, other])), 2, other["msg_key"])

    def test_no_chain_across_same_path(self):
        a = R.mail(T, msg="A")                                  # COM PC1
        b = R.mail(R.plus(T, seconds=90), msg="B", src="mail.index")
        c = R.mail(R.plus(T, seconds=180), msg="C")             # COM PC1 의 다른 메일(같은 제목·대화)
        out = merge_messages([a, b, c])
        self.assertEqual(len(out), 2, "색인 사본은 가까운 한 통에만 붙고 COM 두 통은 합쳐지지 않는다")

    def test_index_copies_from_two_pcs(self):
        com = R.mail(T, msg="Q")
        i1 = R.mail(T, msg="Q-i1", src="mail.index", pc=R.PC1)
        i2 = R.mail(R.plus(T, seconds=30), msg="Q-i2", src="mail.index", pc=R.PC2)
        self.assertEqual(len(merge_messages([com, i1, i2])), 1)

    def test_teams_uia_vs_web(self):
        body = "[과제:P-0001] 시험 결과 정리해서 공유드립니다"
        uia = R.teams(T, msg="u1", src="teams.uia", room="uia:방", body=body)
        web = R.teams(R.plus(T, seconds=42), msg="w1", src="teams.web", room="web-room", body=body, prec="exact",
                      pc=R.CLOUD)
        m = merge_messages([uia, web])
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["msg_key"], web["msg_key"])
        self.assertEqual(m[0]["chat_key"], web["chat_key"])
        self.assertEqual(len(m[0]["provenance"]), 2)
        short = [R.teams(T, msg="s1", src="teams.uia", body="넵"),
                 R.teams(T, msg="s2", src="teams.web", body="넵", prec="exact", pc=R.CLOUD)]
        self.assertEqual(len(merge_messages(short)), 2, "짧은 본문끼리는 합치지 않는다")
        other_author = R.teams(T, msg="w2", src="teams.web", body=body, author=R.LEE, prec="exact", pc=R.CLOUD)
        self.assertEqual(len(merge_messages([uia, other_author])), 2)

    def test_cal_com_vs_index(self):
        com = R.cal(T, R.plus(T, hours=1), msg="GID|start")
        idx = R.cal(T, R.plus(T, hours=1), msg="fallback", src="cal.index", flags={"recurrence_incomplete": True})
        later = R.cal(R.plus(T, days=7), R.plus(T, days=7, hours=1), msg="fallback2", src="cal.index")
        out = merge_messages([com, idx, later])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["src"], "cal.com")
        self.assertTrue(out[0]["flags"].get("recurrence_incomplete"))


class T11Test(unittest.TestCase):
    """T-11 — 병합 후 건수 보존·중복 0(멀티 PC·멀티 경로·UTC 클라우드PC 2배 없음)."""

    def scenario(self):
        rows, truth = [], set()
        for i in range(12):
            ts = R.plus(T, hours=i)
            subj = f"[과제:P-0001] 진행 상황 {i}"
            key = f"mid-{i}"
            truth.add(("mail", i))
            rows.append(R.mail(ts, msg=key, subject=subj, thr=f"T{i}", pc=R.PC1))
            rows.append(R.mail(ts, msg=key, subject=subj, thr=f"T{i}", pc=R.PC2, observed=R.plus(ts, days=1)))
            rows.append(R.mail(R.plus(ts, seconds=40), msg=f"idx-{i}", src="mail.index", subject=subj, thr=f"T{i}"))
            rows.append(R.mail(ts, msg=key, subject=subj, thr=f"T{i}", src="mail.owa", pc=R.CLOUD, off="+00:00"))
            body = f"[과제:P-0001] 도면 {i}번 검토 부탁드립니다"
            truth.add(("teams", i))
            rows.append(R.teams(ts, msg=f"u{i}", src="teams.uia", room="uia:설계", body=body, pc=R.PC1))
            rows.append(R.teams(ts, msg=f"u{i}", src="teams.uia", room="uia:설계", body=body, pc=R.PC2))
            rows.append(R.teams(R.plus(ts, seconds=25), msg=f"w{i}", src="teams.web", room="web:설계", body=body,
                                prec="exact", pc=R.CLOUD, off="+00:00"))
        wit = R.mail("2026-08-31T15:00:00Z", msg="cp-day", src="mail.copilot", pc=R.CLOUD, prec="summary",
                     subject="", text_masked="요약", confidence=0.3)
        rows.append(wit)
        return rows, truth

    def test_count_preserved_no_duplicates(self):
        rows, truth = self.scenario()
        out = merge_messages(rows, off_min=540)
        msgs = [r for r in out if not r["src"].endswith(".copilot")]
        self.assertEqual(len(msgs), len(truth))
        self.assertEqual(len(by_kind(msgs, "mail")), 12)
        self.assertEqual(len(by_kind(msgs, "teams")), 12)
        self.assertEqual(len([r for r in out if r["src"] == "mail.copilot"]), 1)
        keys = [k for r in out for k in r["alias_keys"]]
        self.assertEqual(len(keys), len(set(keys)), "한 키는 한 행에만")
        ids = [p["id"] for r in out for p in r["provenance"]]
        self.assertEqual(sorted(ids), sorted(r["id"] for r in rows), "모든 입력 행이 정확히 한 번 provenance 에")
        for r in by_kind(msgs, "mail"):
            self.assertEqual(r["src"], "mail.com")
            self.assertEqual(len(r["provenance"]), 4)

    def test_order_independent(self):
        rows, _ = self.scenario()
        base = canon(merge_messages(rows, off_min=540))
        for seed in range(5):
            sh = list(rows)
            random.Random(seed).shuffle(sh)
            self.assertEqual(canon(merge_messages(sh, off_min=540)), base, seed)

    def test_duplicate_ids_keep_latest(self):
        a = R.session(T)
        b = dict(a, observed_at=R.plus(T, hours=2), ts_end=R.plus(T, hours=2))
        out = merge_messages([a, b, a])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["observed_at"], R.plus(T, hours=2))
        self.assertNotIn("provenance", out[0], "메시지가 아닌 kind 는 그대로")

    def test_synth_multi_path_month(self):
        """WP-05 합성 한 달 — 메일 COM·색인·OWA·증인, 팀즈 UIA·웹·증인, 일정 COM·색인·OWA 를 섞어도 메시지 수 = 한 경로 수."""
        from tests.fixtures import synth
        kinds = ("mail", "teams", "cal")
        one = synth.stored_rows(kinds=kinds)
        many = synth.stored_rows(kinds=kinds, srcs={"mail": ("mail.com", "mail.index", "mail.owa", "mail.copilot"),
                                                    "teams": ("teams.uia", "teams.web", "teams.copilot"),
                                                    "cal": ("cal.com", "cal.index", "cal.owa")})
        out = merge_messages(many, off_min=540)
        for kind in kinds:
            msgs = [r for r in out if r["kind"] == kind and not r["src"].endswith(".copilot")]
            self.assertEqual(len(msgs), len([r for r in one if r["kind"] == kind]), kind)
        wit = [r for r in many if r["src"].endswith(".copilot")]
        self.assertEqual(len([r for r in out if r["src"].endswith(".copilot")]), len({(r["src"], r["msg_key"]) for r in wit}))
        self.assertEqual(sorted(p["id"] for r in out for p in r["provenance"]), sorted(r["id"] for r in many))
        sh = list(many)
        random.Random(7).shuffle(sh)
        self.assertEqual(canon(merge_messages(sh, off_min=540)), canon(out))

    def test_other_kinds_pass_through(self):
        rows = [R.session(T), R.git(T), R.manual(T), R.mail(T, msg="Z")]
        out = merge_messages(rows)
        self.assertEqual(len(out), 4)
        for r in rows[:3]:
            self.assertIn(r, out)


if __name__ == "__main__":
    unittest.main()
