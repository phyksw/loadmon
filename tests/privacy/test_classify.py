# -*- coding: utf-8 -*-
"""WP-10 판정 규칙 시험 — 광고 A01~A14 · 공사 Q01~Q14 · 창 분류(O-4 9건 + 카탈로그 범주), P-T13·T14(광고 점수 쪽),
방 성향·부재 힌트·헤더 플래그·설정 어휘 보정 도우미."""
import re
import unittest

from lm27.privacy import classify, selftest
from lm27.privacy.classify import (
    AD_DROP,
    AD_SUSPECT,
    AD_WHY,
    PRIV_WHY,
    RoomStat,
    WindowContext,
    abs_hint,
    ad_score,
    ad_score_adjusted,
    adlike_localpart,
    body_unsub,
    header_flags,
    priv_why_codes,
    private_score,
    private_score_adjusted,
    room_prior,
    window_class,
)
from lm27.privacy.detect import SanitizeContext
from tests.fixtures.canary import canaries

CORPUS = selftest.load_corpus()
BY_ID = {r["id"]: r for r in CORPUS}


def _canary(cat):
    return next(c for c in canaries() if c.cat == cat)


class AdCorpusTest(unittest.TestCase):
    def test_A01_to_A14(self):
        rows = [r for r in CORPUS if r["type"] == "ad"]
        self.assertEqual(len(rows), 14)
        for r in rows:
            with self.subTest(rid=r["id"]):
                s, band, why = ad_score(r["meta"])
                self.assertEqual(band, r["band"])
                self.assertTrue(set(why) <= set(AD_WHY))

    def test_documented_scores(self):
        """P §18.2 표의 점수 열."""
        want = {"A01": 9, "A02": 9, "A03": 10, "A04": -2, "A05": 5, "A06": -3, "A07": 0, "A08": 3, "A09": 9, "A10": -1,
                "A11": 11, "A12": 0, "A13": 9, "A14": 2}
        for rid, sc in want.items():
            with self.subTest(rid=rid):
                self.assertEqual(ad_score(BY_ID[rid]["meta"])[0], sc)


class AdScenarioTest(unittest.TestCase):
    BASE = {"subject": "신제품 출시 안내", "internal": False, "corresp_domain": True, "rcv": "bulk"}

    def test_path_difference_T13(self):
        """P-T13: 같은 광고 — COM(헤더 있음)은 drop, 색인(헤더 없음)은 같은 임계로 재계산(점수만 낮아짐)."""
        com = ad_score(dict(self.BASE, hdr={"list_unsubscribe": True}))
        idx = ad_score(dict(self.BASE, hdr={}))
        self.assertEqual(com[1], "drop")
        self.assertEqual(idx[0], com[0] - 4)
        self.assertEqual(idx[1], "drop" if idx[0] >= AD_DROP else ("suspect" if idx[0] >= AD_SUSPECT else "keep"))
        self.assertNotIn("list_unsub", idx[2])

    def test_user_block_T14(self):
        """P-T14: 광고 의심(A08) → 사용자 [차단] → 다음 수집부터 drop(user_block). 허용·내 대화도 못 이긴다."""
        meta = dict(BY_ID["A08"]["meta"])
        self.assertEqual(ad_score(meta)[1], "suspect")
        blocked = dict(meta, blocked=True, allowed=True, i_sent_in_conv=True, internal=True)
        self.assertEqual(ad_score(blocked), (9, "drop", ["user_block"]))

    def test_ad_prefix_beats_allow_and_reply(self):
        for subj in ("RE: FW: [광고] 행사", "회신: (AD) 소개", "【광고】 안내", "<홍보> 소식"):
            with self.subTest(subj=subj):
                self.assertEqual(ad_score({"subject": subj, "allowed": True, "i_sent_in_conv": True, "internal": True}),
                                 (9, "drop", ["ad_prefix"]))

    def test_junk_folder_and_allow_cap(self):
        self.assertEqual(ad_score({"subject": "x", "folder": "junk"})[1], "drop")
        s, band, why = ad_score({"subject": "웨비나 특가 이벤트", "hdr": {"list_unsubscribe": True}, "allowed": True})
        self.assertEqual((s, band), (0, "keep"))
        self.assertIn("user_allow", why)

    def test_work_relation_is_penalty_not_exemption(self):
        s, band, _ = ad_score({"subject": "뉴스레터 프로모션", "internal": False, "corresp_domain": True,
                               "hdr": {"list_unsubscribe": True, "precedence_bulk": True}})
        self.assertGreaterEqual(s, AD_DROP)
        self.assertEqual(band, "drop")

    def test_many_recipients_and_localpart(self):
        base = ad_score({"subject": "안내", "internal": False, "corresp_domain": False})[0]
        more = ad_score({"subject": "안내", "internal": False, "corresp_domain": False, "n_recipients": 25,
                         "adlike_localpart": True})[0]
        self.assertEqual(more, base + 2)


class AdHelperTest(unittest.TestCase):
    def test_header_flags_bool_only(self):
        hdr = "Received: x\r\nList-Unsubscribe: <mailto:u>\r\nPrecedence: bulk\r\nX-Mailer: Mailchimp Mailer\r\n"
        self.assertEqual(header_flags(hdr), {"list_unsubscribe": True, "precedence_bulk": True, "esp": True})
        self.assertEqual(header_flags("Subject: 회의\r\n"),
                         {"list_unsubscribe": False, "precedence_bulk": False, "esp": False})
        self.assertEqual(header_flags(None)["esp"], False)
        self.assertTrue(header_flags("Feedback-ID: 1:2:3\n")["esp"])
        self.assertFalse(header_flags("Precedence: first-class\n")["precedence_bulk"])

    def test_body_unsub_and_localpart(self):
        self.assertTrue(body_unsub("더 이상 수신을 원하지 않으시면 여기를 누르세요"))
        self.assertFalse(body_unsub("회의록 공유드립니다"))
        self.assertTrue(adlike_localpart("newsletter"))
        self.assertTrue(adlike_localpart("kr.marketing.team"))
        self.assertFalse(adlike_localpart("kim.chulsu"))
        self.assertFalse(adlike_localpart(None))

    def test_extra_words_bonus(self):
        """privacy.ad.extraWords — 정규식 광고어 없으면 +2, 1종 있으면 +1, 2종 이상이면 +0(가점 합계 +3 상한)."""
        m = {"subject": "가을 바자회 안내", "internal": False, "corresp_domain": True}
        s0 = ad_score(m)[0]
        self.assertEqual(ad_score_adjusted(m, ["바자회"])[0], s0 + 2)
        m1 = dict(m, subject="가을 바자회 할인")
        self.assertEqual(ad_score_adjusted(m1, ["바자회"])[0], ad_score(m1)[0] + 1)
        m2 = dict(m, subject="바자회 할인 쿠폰")
        self.assertEqual(ad_score_adjusted(m2, ["바자회"]), ad_score(m2))
        self.assertEqual(ad_score_adjusted(m, []), ad_score(m))
        self.assertEqual(ad_score_adjusted(m, ["없는말"]), ad_score(m))
        self.assertIn("extra_words", ad_score_adjusted(m, ["바자회"])[2])

    def test_extra_words_keep_fixed_rules(self):
        blocked = {"subject": "바자회", "blocked": True}
        self.assertEqual(ad_score_adjusted(blocked, ["바자회"]), (9, "drop", ["user_block"]))
        allowed = {"subject": "바자회 웨비나", "internal": False, "allowed": True}
        self.assertEqual(ad_score_adjusted(allowed, ["바자회"])[0], 0)


class PrivacyCorpusTest(unittest.TestCase):
    def test_Q01_to_Q14(self):
        want = {"Q01": 4, "Q02": 8, "Q03": -4, "Q04": -11, "Q05": 2, "Q06": -1, "Q07": 4, "Q08": 5, "Q09": 0, "Q10": 3,
                "Q11": 9, "Q12": -7, "Q13": 1, "Q14": 4}
        rows = [r for r in CORPUS if r["type"] == "priv"]
        self.assertEqual(len(rows), 14)
        for r in rows:
            with self.subTest(rid=r["id"]):
                s, cls, _det = private_score(r["text"], **r["kw"])
                self.assertEqual(cls, r["class"])
                self.assertEqual(s, want[r["id"]])

    def test_abs_hint_survives_private_Q10(self):
        self.assertEqual(abs_hint(BY_ID["Q10"]["text"]), "half_pm")

    def test_explicit_private(self):
        for kw in ({"sensitivity": 1}, {"sensitivity": 2}, {"private_category": True}, {"user_private_chat": True}):
            with self.subTest(kw=kw):
                self.assertEqual(private_score("주간 보고 자료", **kw), (9, "private", {"explicit": 1}))
        self.assertEqual(private_score("주간 보고 자료", sensitivity=3)[1], "work")          # 기밀 = 업무

    def test_work_cap_four(self):
        s4 = private_score("검토 회신 보고 자료")[0]
        s6 = private_score("검토 회신 보고 자료 첨부 일정")[0]
        self.assertEqual(s4, s6)


class PrivacyHelperTest(unittest.TestCase):
    def test_adjusted_private_and_work_words(self):
        text = "다음 주 바자회 일정"
        s, cls, det = private_score(text)
        s2, cls2, det2 = private_score_adjusted(text, extra_words=["바자회"])
        self.assertEqual(s2, s + 2)
        self.assertEqual(det2["strong"], det["strong"] + 1)
        s3, cls3, _ = private_score_adjusted("점심 맛집 커피", extra_work_words=["맛집"])
        self.assertEqual(s3, private_score("점심 맛집 커피")[0] - 2)
        self.assertEqual(private_score_adjusted(text), private_score(text))
        self.assertEqual(private_score_adjusted(text, extra_words=["바자회"], sensitivity=2)[0], 9)

    def test_adjusted_work_cap(self):
        text = "검토 회신 보고 자료 결재건"
        base = private_score(text)[0]                                   # 정규식 업무어 4개(상한)
        self.assertEqual(private_score_adjusted(text, extra_work_words=["결재건"])[0], base)

    def test_adjusted_reclassifies(self):
        s, cls, _ = private_score_adjusted("주말 바자회", extra_words=["바자회"])
        self.assertEqual(cls, "private")
        s, cls, _ = private_score_adjusted("점심 한잔", extra_work_words=["점심"], chat_type="1:1")
        self.assertEqual(cls, "work")

    def test_priv_why_codes(self):
        r = BY_ID["Q02"]
        _s, _c, det = private_score(r["text"], **r["kw"])
        why = priv_why_codes(det, text=r["text"], **r["kw"])
        self.assertIn("strong", why)
        self.assertIn("one_to_one", why)
        self.assertIn("offhours", why)
        self.assertTrue(set(why) <= set(PRIV_WHY))
        self.assertEqual(priv_why_codes({"explicit": 1}), ["explicit"])
        det4 = private_score(BY_ID["Q04"]["text"])[2]
        self.assertIn("reg_token", priv_why_codes(det4, text=BY_ID["Q04"]["text"], chat_type="channel"))
        self.assertLessEqual(len(priv_why_codes({"strong": 1, "weak": 1, "social": 1, "work": 1, "ack": 1},
                                                text="[과제:P-0001]", chat_type="1:1", offhours=True,
                                                room_prior="private", personal_mail=True)), 8)


class RoomPriorTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(room_prior(RoomStat(9, 9, 0)), "")
        self.assertEqual(room_prior(RoomStat(10, 7, 0)), "private")
        self.assertEqual(room_prior(RoomStat(10, 6, 0)), "")
        self.assertEqual(room_prior(RoomStat(12, 0, 9)), "work")
        self.assertEqual(room_prior(RoomStat(12, 9, 3)), "private")      # T9: 12건 중 9건 사적
        self.assertEqual(room_prior(RoomStat(0, 0, 0)), "")


class WindowTest(unittest.TestCase):
    def test_O4_nine_cases(self):
        rows = [r for r in CORPUS if r["type"] == "win"]
        self.assertEqual(len(rows), 9)
        for r in rows:
            with self.subTest(rid=r["id"]):
                v = window_class(r["exe"], r["title"], r["app_class"], WindowContext())
                self.assertEqual(v.priv_class, r["class"])

    def test_title_handling(self):
        w7 = BY_ID["W07"]
        v = window_class(w7["exe"], w7["title"], w7["app_class"], WindowContext())
        self.assertEqual((v.priv_class, v.site_class), ("work", "app"))
        self.assertIn("[전화]", v.title_masked)
        self.assertNotRegex(v.title_masked, r"\d{4}-\d{4}")
        teams = BY_ID["W08"]
        self.assertEqual(window_class(teams["exe"], teams["title"], "chat_work").title_masked, "")
        self.assertEqual(window_class("unknown_tool.exe", "고객 이름 창", "").title_masked, "")

    def test_browser_branches(self):
        self.assertEqual(window_class("chrome.exe", "a - 시크릿 - Google Chrome", "browser").site_class, "inprivate")
        v = window_class("msedge.exe", "주간 회의 - Personal - Microsoft Edge", "browser")
        self.assertEqual((v.priv_class, v.site_class), ("private", "profile"))
        v = window_class("msedge.exe", "SharePoint 문서함 - Microsoft Edge", "browser")
        self.assertEqual((v.priv_class, v.site_class), ("work", "work_site"))
        self.assertEqual(v.title_masked, "SharePoint 문서함")
        v = window_class("msedge.exe", "보고서 - SharePoint - Microsoft Edge", "browser")   # 끝에서 둘째 조각 = 프로필
        self.assertEqual((v.priv_class, v.title_masked), ("unknown", ""))
        v = window_class("firefox.exe", "넷플릭스 - Mozilla Firefox", "")
        self.assertEqual((v.priv_class, v.title_masked), ("private", ""))
        v = window_class("whale.exe", "멜론 차트 - Whale", "browser")
        self.assertEqual(v.priv_class, "media")

    def test_work_title_patterns_from_config(self):
        w = WindowContext(work_title_patterns=[r"사내포털"])
        v = window_class("chrome.exe", "사내포털 공지 - Google Chrome", "browser", w)
        self.assertEqual((v.priv_class, v.site_class), ("work", "work_site"))
        self.assertEqual(window_class("chrome.exe", "사내포털 공지 - Google Chrome", "browser").priv_class, "unknown")

    def test_edge_zero_width_title(self):
        """실제 Edge 창 제목('Microsoft<U+200B> Edge')에서도 프로필을 읽는다(폭 0 문자 제거)."""
        zw = chr(0x200B)
        v = window_class("msedge.exe", "주간 회의 - 개인 - Microsoft" + zw + " Edge", "browser")
        self.assertEqual((v.priv_class, v.site_class), ("private", "profile"))
        v = window_class("msedge.exe", "SharePoint 문서함 - Microsoft" + zw + " Edge", "browser")
        self.assertEqual((v.priv_class, v.title_masked), ("work", "SharePoint 문서함"))

    def test_catalog_classes_union(self):
        self.assertEqual(window_class("game.exe", "", "game").priv_class, "private")
        self.assertEqual(window_class("chat.exe", "", "messenger_private").priv_class, "private")
        self.assertEqual(window_class("player.exe", "", "media").priv_class, "media")
        self.assertEqual(window_class("spotify.exe", "x", "").priv_class, "media")
        self.assertEqual(window_class("x.exe", "", "system").priv_class, "unknown")
        self.assertEqual(window_class("x.exe", "", "idle").priv_class, "unknown")

    def test_private_exes_effective_list(self):
        """privacy.window.privateExes(list(+-)) 유효 목록 — 추가도 해제(disable)도 먹는다."""
        add = WindowContext(private_exes=classify.PRIVATE_EXES | {"Hobby.EXE"})
        self.assertEqual(window_class("hobby.exe", "", "", add).priv_class, "private")
        disabled = WindowContext(private_exes=classify.PRIVATE_EXES - {"kakaotalk.exe"})
        self.assertEqual(window_class("KakaoTalk.exe", "x", "", disabled).priv_class, "work")
        self.assertEqual(window_class("KakaoTalk.exe", "x", "").priv_class, "private")

    def test_title_uses_context_dictionary(self):
        w = WindowContext(sctx=SanitizeContext(customers=[{"id": "C01", "names": ["고객사A"], "domains": []}]))
        v = window_class("excel.exe", "견적_고객사A.xlsx - Excel", "office", w)
        self.assertEqual(v.title_masked, "견적_[고객사:C01].xlsx - Excel")

    def test_credential_title_dropped(self):
        v = window_class("notepad.exe", "pw=" + "Abc" + "12345 메모", "office")
        self.assertEqual((v.priv_class, v.title_masked), ("work", ""))

    def test_title_length(self):
        v = window_class("winword.exe", "가" * 300, "office")
        self.assertLessEqual(len(v.title_masked), 120)


class AbsHintTest(unittest.TestCase):
    def test_codes(self):
        cases = {"오전 반차 사용": "half_am", "오후반차": "half_pm", "반차 신청": "half", "연차 휴가": "leave",
                 "휴가 계획 세우기": "none", "병가": "sick", "조퇴합니다": "early", "외출 예정": "out", "출장 보고": "trip",
                 "": "none"}
        for text, code in cases.items():
            with self.subTest(text=text):
                self.assertEqual(abs_hint(text), code)
        self.assertEqual(abs_hint(None), "none")

    def test_first_match_wins(self):
        self.assertEqual(abs_hint("출장 후 오전 반차"), "half_am")


class WhyEnumsTest(unittest.TestCase):
    def test_enums_are_codes(self):
        for code in AD_WHY + PRIV_WHY:
            self.assertRegex(code, r"^[a-z_]+$")
        self.assertEqual(len(set(AD_WHY)), len(AD_WHY))
        self.assertTrue(re.fullmatch(r"[a-z_]+", classify.window_class.__name__))


if __name__ == "__main__":
    unittest.main()
