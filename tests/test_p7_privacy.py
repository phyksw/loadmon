# -*- coding: utf-8 -*-
r"""test_p7_privacy.py — WP7: 개인정보 핵심 모듈(core\privacy) + G2 적재 관문(extract.add) + G4 팀 반출 변환.

실 Outlook·Teams·Edge·팀 서버는 쓰지 않는다 — 임시 폴더의 합성 CSV·설정과 순수 함수만 본다.
말뭉치는 tests\data\privacy_corpus.json(합성 — 실명·실제 번호·사내 코드네임 없음).
"""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date

import _boot

ROOT = _boot.ROOT
import privacy  # noqa: E402
import extract  # noqa: E402

CORPUS = os.path.join(_boot.TESTS, "data", "privacy_corpus.json")
MAIL_HDR = ["box", "time", "sender", "subject", "conversation", "rcv", "time_precision"]
SIG_HDR = ["time", "source", "who", "project", "activity", "weight", "text", "flag"]
D0, D1 = date(2026, 10, 1), date(2026, 10, 7)
NO_ENV = {"COMPUTERNAME": "", "USERNAME": "", "USERDOMAIN": ""}


def _write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _read_rows(path_or_text, is_text=False):
    if is_text:
        rd = csv.DictReader(io.StringIO(path_or_text, newline=""))
        return rd.fieldnames, list(rd)
    with open(path_or_text, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return rd.fieldnames, list(rd)


def _signals(data_dir, cfg, exclude=None):
    """load_signals 를 조용히(출력 버림) — exclude 는 privacy.excluded_keywords(cfg)."""
    ex = privacy.excluded_keywords(cfg) if exclude is None else exclude
    with contextlib.redirect_stdout(io.StringIO()):
        return extract.load_signals(data_dir, D0, D1, ex, cfg)


class Corpus(unittest.TestCase):
    """탐지기별 양성·음성 말뭉치 + 멱등."""

    @classmethod
    def setUpClass(cls):
        with open(CORPUS, encoding="utf-8") as f:
            cls.cases = json.load(f)["cases"]

    def test_corpus(self):
        cats = set()
        for c in self.cases:
            with self.subTest(c["id"]):
                ctx = privacy.Ctx(**c["ctx"]) if c.get("ctx") else None
                out, hits, drop = privacy.sanitize(c["text"], "text", ctx)
                exp = c["expect"]
                cats.add(c["cat"])
                if exp == "drop":
                    self.assertTrue(drop)
                    self.assertEqual(out, "")
                    self.assertEqual(hits, {"cred": 1})
                    continue
                self.assertFalse(drop)
                if exp == "unchanged":
                    self.assertEqual(out, c["text"])
                    self.assertEqual(hits, {})
                elif exp == "contains":
                    self.assertIn(c["token"], out)
                    for a in c.get("absent") or ():
                        self.assertNotIn(a, out)
                # 멱등: 두 번 정제 == 한 번 정제, 두 번째는 새로 잡는 것이 없다
                out2, hits2, drop2 = privacy.sanitize(out, "text", ctx)
                self.assertEqual(out2, out)
                self.assertEqual(hits2, {})
                self.assertFalse(drop2)
        # 지시서의 탐지기 묶음이 말뭉치에 다 있다
        for need in ("phone", "account", "rrn", "passport", "card", "money", "cred"):
            self.assertIn(need, cats)

    def test_token_digits_not_recaught(self):
        """토큰 안 숫자(도메인의 10자리)를 계좌 등으로 다시 잡지 않는다."""
        x = "[이메일@1234567890.com] 계좌 이체 [전화] [금액]"
        out, hits, drop = privacy.sanitize(x)
        self.assertEqual(out, x)
        self.assertEqual(hits, {})
        # 보호가 없다면 잡혔을 문맥 — 같은 숫자를 토큰 밖에 두면 계좌로 가린다
        self.assertIn("[계좌]", privacy.sanitize("1234567890 계좌 이체")[0])

    def test_truncate_keeps_tokens(self):
        out, _h, _d = privacy.sanitize("가" * 20 + " 010-1234-5678 끝", max_len=24)
        self.assertEqual(out, "가" * 20 + "…")                # '[전' 처럼 반쯤 잘린 토큰을 남기지 않는다
        self.assertEqual(privacy.safe_truncate("짧다", 400), "짧다")

    def test_nfkc_and_control(self):
        out, _h, _d = privacy.sanitize("ＡＢＣ​ 010–1234–5678")
        self.assertEqual(out, "ABC [전화]")


class AdPrivateWindow(unittest.TestCase):
    def test_ad_score(self):
        self.assertTrue(privacy.AD_PARTIAL)
        self.assertEqual(privacy.ad_score("(광고) 신제품 할인 안내", "promo@shop.example")[1], "drop")
        self.assertEqual(privacy.ad_score("RE: [광고] 10월 특가", "")[1], "drop")
        # 사내 공지는 광고가 아니다
        s, band = privacy.ad_score("[공지] 사내 보안 교육 안내", "notice@corp.example", "inbox", "", (),
                                   internal_domains=("corp.example",))
        self.assertEqual(band, "keep")
        # 왕래 있는 협력사의 웨비나 초대 — 감점만(면제 아님) → suspect 이하
        s, band = privacy.ad_score("웨비나 초대합니다", "event@partner.example", "inbox", "", {"partner.example"})
        self.assertIn(band, ("keep", "suspect"))
        self.assertLess(s, privacy.AD_DROP)
        # 처음 연락 온 외부 업무 메일은 광고 단서가 없으면 keep
        self.assertEqual(privacy.ad_score("견적 요청", "lee@vendor.example")[1], "keep")
        # 광고어 2종(표시 이름뿐) → suspect
        self.assertEqual(privacy.ad_score("이벤트 당첨 안내", "쇼핑몰")[1], "suspect")
        # 보낸 메일은 판정하지 않는다
        self.assertEqual(privacy.ad_score("(광고) 전달", "", "sent")[1], "keep")

    def test_private_score(self):
        self.assertEqual(privacy.private_score("주말에 가족 여행 숙소 예약 ㅋㅋ"), "private")
        self.assertEqual(privacy.private_score("송년회 뒤풀이 장소 공지"), "social")
        self.assertEqual(privacy.private_score("설계 검토 회의 자료 송부"), "work")
        self.assertEqual(privacy.private_score("신기술 동향", offhours=True), "work")       # '기술' 의 '술' 은 사적어가 아니다
        # NFKC 를 거친 정제문(ㅋㅋ → 첫가끝 자모)도 같은 판정
        clean = privacy.sanitize("점심 ㅋㅋ")[0]
        self.assertEqual(privacy.private_score(clean), "private")
        self.assertEqual(privacy.private_score("커피", partner_personal=True), "private")
        self.assertEqual(privacy.private_score("[과제] 커피 ㅋㅋ"), "work")

    def test_window_class(self):
        wc = privacy.window_class
        self.assertEqual(wc("KakaoTalk.exe", "채팅"), "private")
        self.assertEqual(wc("spotify.exe", "곡"), "media")
        self.assertEqual(wc("msedge.exe", "쿠팡 - Microsoft​ Edge"), "private")
        self.assertEqual(wc("msedge", "업무 - 개인 - Microsoft Edge"), "private")
        self.assertEqual(wc("chrome.exe", "새 탭 (InPrivate)"), "private")
        self.assertEqual(wc("msedge.exe", "YouTube - Microsoft Edge"), "media")
        self.assertEqual(wc("msedge.exe", "PRJ-1 - Jira - Microsoft Edge"), "work")
        self.assertEqual(wc("chrome.exe", "어떤 블로그 - Google Chrome"), "unknown")
        self.assertEqual(wc("LockApp.exe", ""), "unknown")
        self.assertEqual(wc("xtop.exe", "assy.prt"), "work")


class GateG3(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lm28_p7_")
        self.data = os.path.join(self.tmp.name, "data")
        os.makedirs(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_gate_items(self):
        cans = privacy.canaries({}, self.data, env={"COMPUTERNAME": "PC", "USERNAME": "tester01", "USERDOMAIN": "user"})
        self.assertEqual(cans, ("tester01",))               # 4자 미만·일반 계정명은 무시
        items = [
            {"id": 1, "text": "설계 검토 회의 자료"},
            {"id": 2, "text": "견적 요청 010-1234-5678"},          # 고위험 잔여 → 제외
            {"id": 3, "text": "tester01 개인 메모 정리"},           # 카나리아(USERNAME) → 제외
            {"id": 4, "text": "가" * 500},                        # 400자로 자름
            {"id": 5, "text": "할인 안내", "flag": "ad"},             # 광고 의심 → 제외
            {"id": 6, "text": "점심 메뉴", "priv": "private"},       # 사적 → 제외
            {"id": 7, "text": "pw: Abc12345"},                    # 자격증명 → 제외
            {"id": 8, "text": "[사람#abcdef] 회신 [사람]"},           # 사람 태그 통일
        ]
        kept, dropped = privacy.gate_items(items, ["text"], {}, canaries=cans, ctx=privacy.Ctx())
        ids = [k["id"] for k in kept]
        self.assertEqual(ids, [1, 4, 8])
        self.assertEqual(dropped, {"개인정보:phone": 1, "카나리아": 1, "광고의심": 1, "사적": 1, "자격증명": 1})
        self.assertLessEqual(len(kept[1]["text"]), 400)
        self.assertTrue(kept[1]["text"].endswith("…"))
        self.assertEqual(kept[2]["text"], "[사람] 회신 [사람]")
        self.assertEqual(items[3]["text"], "가" * 500)          # 원본은 바꾸지 않는다

    def test_gate_prompt(self):
        kw = {"canaries": ("tester01",), "ctx": privacy.Ctx()}
        self.assertTrue(privacy.gate_prompt("판정 요청\n1. 설계 검토 [전화] [이메일@사내] 2026-10-05", **kw))
        self.assertFalse(privacy.gate_prompt("판정 요청\n2. 견적 010-1234-5678", **kw))
        self.assertFalse(privacy.gate_prompt("판정 요청\n3. TESTER01 메모", **kw))
        long_ok = "\n".join(f"{i}. 설계 검토 회의" for i in range(600))
        self.assertTrue(privacy.gate_prompt(long_ok, **kw))
        self.assertFalse(privacy.gate_prompt(long_ok + "\n끝 010-9999-8888", **kw))   # 4,000자 뒤의 값도 본다

    def test_excluded_keywords(self):
        ex = privacy.excluded_keywords({"excludePathKeywords": ["내폴더", " ", "temp"]})
        self.assertEqual(ex, sorted(set(privacy.EXCLUDE) | {"내폴더"}))
        self.assertEqual(privacy.excluded_keywords({"excludePathKeywords": "하나"}),
                         sorted(set(privacy.EXCLUDE) | {"하나"}))
        # mine.py 는 단일원을 쓴다(소스 확인 — mine 은 import 시 stdout 을 바꿔 끼우므로 임포트하지 않는다)
        src = _boot.read_text(os.path.join(ROOT, "mine.py"))
        self.assertIn("privacy.excluded_keywords(cfg)", src)
        self.assertIn("EXCLUDE = list(privacy.EXCLUDE)", src)
        self.assertIn('"flag"]', src)


class ScrubCsvG1(unittest.TestCase):
    def test_scrub_fold_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p7_") as tmp:
            p = os.path.join(tmp, "data", "m365", "teams_2026-10.csv")
            hdr = ["time", "from", "chat", "kind", "summary"]
            _write_csv(p, hdr, [
                ["2026-10-05 10:00", "lee", "lee, 나", "msg", "연락처 010-1234-5678 로 주세요"],
                ["2026-10-05 10:00", "lee", "lee, 나", "msg", "연락처 010 1234 5678 로 주세요"],
                ["2026-10-05 10:05", "lee", "lee, 나", "msg", "비번은 Abc!2345 입니다"],
                ["2026-10-05 10:06", "lee", "lee, 나", "msg", "설계 검토 부탁"],
            ])
            r1 = privacy.scrub_csv(p, ["summary", "chat"], key_cols=["time", "from", "chat", "summary"],
                                   ctx=privacy.Ctx())
            r2 = privacy.scrub_csv(p, ["summary", "chat"], key_cols=["time", "from", "chat", "summary"],
                                   ctx=privacy.Ctx())
            self.assertTrue(r1["ok"] and r2["ok"])
            self.assertEqual((r1["rows_in"], r1["rows_out"], r1["folded"], r1["dropped"]), (4, 2, 1, 1))
            self.assertEqual((r2["rows_in"], r2["rows_out"], r2["changed"]), (2, 2, False))
            fields, rows = _read_rows(p)
            self.assertEqual(fields, hdr)                       # 머리글·열 수 불변(열을 더하지 않는다)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["summary"], "연락처 [전화] 로 주세요")
            raw = open(p, encoding="utf-8-sig").read()
            self.assertNotIn("1234", raw)
            self.assertNotIn("Abc!2345", raw)
            with open(os.path.join(tmp, "data", "privacy_audit.json"), encoding="utf-8") as f:
                au = json.load(f)
            ent = au["files"]["m365/teams_2026-10.csv"]
            self.assertEqual(ent["rules_ver"], privacy.RULES_VER)
            self.assertNotIn("010", json.dumps(au, ensure_ascii=False))   # 감사에는 건수만


class LoadSignalsG2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lm28_p7_")
        self.data = os.path.join(self.tmp.name, "data")
        os.makedirs(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self, **kw):
        c = {"owner": "tester", "mm": {}, "noticeSenders": ["no-reply"]}
        c.update(kw)
        return c

    def test_exclude_before_mask(self):
        """제외어로 지정한 고객사명이 든 제목 → 신호 0(정제로 [고객사] 가 되기 전에 원문으로 판정)."""
        cfg = self.cfg(privacy={"customers": ["가상고객"]}, excludePathKeywords=["가상고객"])
        _write_csv(os.path.join(self.data, "outlook", "mail.csv"), MAIL_HDR, [
            ["inbox", "2026-10-05 10:00:00", "lee@vendor.example", "가상고객 납품 일정 협의", "가상고객 납품 일정 협의", "to", "minute"],
            ["inbox", "2026-10-05 11:00:00", "lee@vendor.example", "설계 검토 요청", "설계 검토 요청", "to", "minute"],
        ])
        sig, meta = _signals(self.data, cfg)
        self.assertEqual(len(sig), 1)
        self.assertNotIn("가상고객", " ".join(s[2] for s in sig))
        self.assertNotIn("[고객사]", " ".join(s[2] for s in sig))
        self.assertEqual(meta["excluded"].get("개인정보필터"), 1)

    def test_dedup_raw_and_clean(self):
        """같은 메일의 원문 행(추가PC)과 G1 정제 행(본 PC) → 신호 1."""
        cfg = self.cfg()
        _write_csv(os.path.join(self.data, "outlook", "mail.csv"), MAIL_HDR, [
            ["inbox", "2026-10-05 10:00:00", "lee@vendor.example", "견적 요청 [전화]", "견적 요청 [전화]", "to", "minute"],
        ])
        _write_csv(os.path.join(self.data, "추가PC", "pc2", "outlook", "mail.csv"), MAIL_HDR, [
            ["inbox", "2026-10-05 10:00:00", "lee@vendor.example", "견적 요청 010-1234-5678",
             "견적 요청 010-1234-5678", "to", "minute"],
        ])
        sig, meta = _signals(self.data, cfg)
        mails = [s for s in sig if s[1].startswith("메일")]
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0][2], "견적 요청 [전화]")
        self.assertEqual(meta["excluded"].get("중복(추가 PC 취합·이력)"), 1)

    def test_ad_private_work(self):
        """합성 메일(광고 1·사적 1·업무 2) → 신호 2, 광고필터 1, 사적은 날짜별 건수만."""
        cfg = self.cfg()
        _write_csv(os.path.join(self.data, "outlook", "mail.csv"), MAIL_HDR, [
            ["inbox", "2026-10-05 09:00:00", "promo@shop.example", "(광고) 신제품 할인 안내", "", "to", "minute"],
            ["inbox", "2026-10-05 09:30:00", "friend@gmail.com", "주말에 캠핑 숙소 예약 ㅋㅋ", "", "to", "minute"],
            ["inbox", "2026-10-05 10:00:00", "kim@corp.example", "설계 검토 회의 자료 송부", "", "to", "minute"],
            ["sent", "2026-10-05 11:00:00", "tester", "BOM 확인 요청", "", "to", "minute"],
        ])
        sig, meta = _signals(self.data, cfg)
        self.assertEqual(len(sig), 2)
        self.assertEqual(meta["excluded"].get("광고필터"), 1)
        self.assertEqual(meta["excluded"].get("사적 대화(제외)"), 1)
        self.assertEqual(meta.get("private_days"), {"2026-10-05": 1})
        self.assertFalse(any("캠핑" in s[2] or "광고" in s[2] for s in sig))

    def test_suspect_flag_and_pii_masked(self):
        cfg = self.cfg()
        _write_csv(os.path.join(self.data, "outlook", "mail.csv"), MAIL_HDR, [
            ["inbox", "2026-10-05 09:00:00", "쇼핑몰", "이벤트 당첨 안내", "", "to", "minute"],
            ["inbox", "2026-10-05 10:00:00", "lee@vendor.example", "단가 12,000원 견적 회신 010-1234-5678", "", "to", "minute"],
            ["inbox", "2026-10-05 10:30:00", "lee@vendor.example", "pw: Abc12345 입니다", "", "to", "minute"],
        ])
        sig, meta = _signals(self.data, cfg)
        texts = {s[2]: s for s in sig}
        self.assertIn("이벤트 당첨 안내", texts)
        s = texts["이벤트 당첨 안내"]
        self.assertEqual(meta["flags"], {(s[0], s[1], s[2]): "ad"})
        self.assertIn("단가 [금액] 견적 회신 [전화]", texts)
        self.assertEqual(meta["excluded"].get("개인정보(자격증명)"), 1)
        self.assertEqual(len(sig), 2)

    def test_notice_default_generic_and_tokens(self):
        generic = {"no-reply", "noreply", "do-not-reply", "알림", "notification", "notice", "뉴스레터", "newsletter",
                   "웹진", "webzine", "공지", "설문", "survey", "시스템", "sharepoint", "yammer", "viva", "helpdesk",
                   "보안", "보안공지", "(광고)", "광고", "promotion", "프로모션", "마케팅", "수신거부", "unsubscribe"}
        self.assertEqual([x for x in extract.NOTICE_DEFAULT if x not in generic], [])
        toks = extract._tokens("[금액] 견적 [사람] 회신 [이메일@사내] 광학모듈 [과제]")
        self.assertFalse({"금액", "사람", "이메일@사내", "과제"} & toks)
        self.assertIn("광학모듈", toks)


class TeamExportG4(unittest.TestCase):
    TAG = "20261001-20261007"

    def _sig_rows(self):
        return [
            ["2026-10-05 10:00", "메일(수신)", "lee@partner.example", "공통", "기타", "1.0", "견적 요청 [전화]", "ad"],
            ["2026-10-05 10:30", "메일(수신)", "홍길동", "공통", "기타", "1.0", "설계 검토", ""],
            ["2026-10-05 11:00", "메일(발신)", "나", "공통", "기타", "1.5", "BOM 확인", ""],
            ["2026-10-05 11:30", "파일", "", "공통", "문서·보고", "3.0", "보고서.pptx", ""],
            ["2026-10-05 12:00", "팀즈(수신)", "kim@gmail.com", "공통", "기타", "0.4", "연락 010-9999-8888", ""],
        ]

    def test_export_equals_teamup_build(self):
        import export
        import teamup
        cfg = {"owner": "tester", "function": "", "privacy": {
            "partners": [{"names": ["가상협력"], "domains": ["partner.example"]}]}}
        saved = (export.ROOT, teamup.ROOT, teamup.REPORT, teamup.PENDING, list(sys.argv))
        with tempfile.TemporaryDirectory(prefix="lm28_p7_") as tmp:
            share = os.path.join(tmp, "share")
            os.makedirs(share)
            os.makedirs(os.path.join(tmp, "config"))
            cfg["teamShareDir"] = share
            with open(os.path.join(tmp, "config", "config.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)
            rep = os.path.join(tmp, "report")
            _write_csv(os.path.join(rep, f"signals_{self.TAG}.csv"), SIG_HDR, self._sig_rows())
            try:
                export.ROOT = tmp
                teamup.ROOT, teamup.REPORT, teamup.PENDING = tmp, rep, os.path.join(rep, "upload_pending")
                sys.argv = ["export.py", "--from", "2026-10-01", "--to", "2026-10-07"]
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = export.main()
                    bundle = teamup.build(cfg, "2026-10-01", "2026-10-07")
            finally:
                export.ROOT, teamup.ROOT, teamup.REPORT, teamup.PENDING = saved[:4]
                sys.argv[:] = saved[4]
            self.assertEqual(rc, 0)
            f_exp, r_exp = _read_rows(os.path.join(share, "tester", f"signals_{self.TAG}.csv"))
            with open(bundle, encoding="utf-8") as f:
                b = json.load(f)
            f_bun, r_bun = _read_rows(b["files"][f"signals_{self.TAG}.csv"], is_text=True)
            self.assertEqual(f_exp, f_bun)
            self.assertEqual(r_exp, r_bun)                     # 공유폴더 = 서버 묶음(같은 변환)
            self.assertNotIn("flag", f_exp)
            self.assertEqual(f_exp, SIG_HDR[:-1])
            self.assertEqual(len(r_exp), 4)                    # 고위험 잔여 1행만 빠진다
            whos = {r["who"] for r in r_exp}
            self.assertTrue(whos <= {"", "사내", "고객사", "협력사", "외부"})
            for orig in ("lee@partner.example", "홍길동", "나", "kim@gmail.com"):
                self.assertNotIn(orig, whos)
            self.assertEqual([r["who"] for r in r_exp], ["협력사", "사내", "사내", ""])
            # --to-folder 도 같은 변환(이미 변환한 본문에 다시 걸어도 같다)
            again, _note = teamup.team_signals(f"signals_{self.TAG}.csv", b["files"][f"signals_{self.TAG}.csv"], cfg)
            self.assertEqual(_read_rows(again, is_text=True), (f_bun, r_bun))

    def test_high_row_only_and_canary(self):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(SIG_HDR)
        w.writerows(self._sig_rows())
        text = buf.getvalue()
        out, info = privacy.team_export_csv(text, privacy.Ctx(), canaries=())
        self.assertIsNotNone(out)                              # 파일은 남는다
        self.assertEqual((info["rows_in"], info["rows_out"], info["high_dropped"]), (5, 4, 1))
        self.assertNotIn("010-9999", out)
        # 카나리아(이 PC·본인 식별자)가 남으면 파일째 빼고 사유를 준다
        out2, info2 = privacy.team_export_csv(text.replace("BOM 확인", "tester01 BOM 확인"), privacy.Ctx(),
                                              canaries=("tester01",))
        self.assertIsNone(out2)
        self.assertTrue(info2["canary"])
        self.assertTrue(info2["why"])
        rows = privacy.team_export_rows([{"who": "x@shop.example", "text": "a", "flag": "ad"}])
        self.assertEqual(rows, [{"who": "외부", "text": "a"}])
        self.assertTrue(privacy.canary_hit([{"text": "DESK-01 메모"}], ("desk-01",)))
        self.assertFalse(privacy.canary_hit([{"text": "메모"}], ("desk-01",)))

    def test_who_class(self):
        ctx = privacy.Ctx(customers=[{"names": ["가상고객"], "domains": ["cust.example"]}], partners=["가상협력"],
                          internal_domains=["corp.example"])
        wc = privacy.who_class
        self.assertEqual(wc("", ctx), "")
        self.assertEqual(wc("나", ctx), "사내")
        self.assertEqual(wc("kim@corp.example", ctx), "사내")
        self.assertEqual(wc("buyer@cust.example", ctx), "고객사")
        self.assertEqual(wc("가상고객 구매팀", ctx), "고객사")
        self.assertEqual(wc("가상협력 영업", ctx), "협력사")
        self.assertEqual(wc("someone@gmail.com", ctx), "외부")
        self.assertEqual(wc("Guest User (외부)", ctx), "외부")
        self.assertEqual(wc("홍길동", ctx), "사내")
        self.assertEqual(wc("협력사", ctx), "협력사")


if __name__ == "__main__":
    unittest.main()
