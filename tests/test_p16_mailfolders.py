# -*- coding: utf-8 -*-
r"""tests\test_p16_mailfolders.py — LM28-OWA-5: 받은·보낸 편지함 밖의 다른 메일 폴더 · Copilot 메일 질문의 폴더 범위 · Outlook 웹 일정
본문 발췌.

사용자 제보: '메일함 보낸/받은만 보는데 메일 폴더를 바꿀 수 있음(이름 등) — 제외되는 게 있을 수 있다'. 실제 Edge·Outlook·네트워크를
쓰지 않는다 — tests\fakes\fake_browser.py(FakeBrowser: 폴더 창 owa_tree · CDP 신뢰 입력 · 일정 상세 owa_cal_bar·owa_cal_detail)와
LM_OWA_FAKE 로 돈다. 운영 data\ 에 쓰지 않는다(파일은 tempfile 폴더만).
"""
import contextlib
import csv
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

import _boot  # noqa: F401  — 경로 등록
import coverage  # noqa: E402
import diag_bundle  # noqa: E402
import owa_parse as op  # noqa: E402

sys.path.insert(0, os.path.join(_boot.TESTS, "fakes"))
import fake_browser as fb  # noqa: E402

COL = os.path.join(_boot.ROOT, "collect")


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, os.path.join(COL, fn))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


owa = _load("owa_web_p16", "Get-OutlookWeb.py")
owa._sleep = lambda s: None                    # 수집 루프 대기 없음
owa.log = lambda msg: None
mvc = _load("mail_copilot_p16", "Get-MailViaCopilot.py")

TODAY = date(2026, 10, 7)                      # 수요일
D = date.fromisoformat
D0, D1 = D("2026-09-01"), D("2026-09-30")


def _st_days(day_st, a, b, want):
    bad, d = [], a
    while d <= b:
        if day_st.get(d) != want:
            bad.append((d.isoformat(), day_st.get(d)))
        d += timedelta(days=1)
    return bad


def _status_of(text):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    assert lines and lines[-1].startswith("LMSTATUS "), lines[-3:]
    return json.loads(lines[-1][len("LMSTATUS "):])


def xmsg(tag, days, sender="고객사 담당", subject="견적 회신"):
    """다른 폴더 메일 — 날마다 한 통(제목에 순번 — 같은 날 같은 보낸이도 서로 다른 메일)."""
    return [fb.msg(f"{tag}{i}", datetime(d.year, d.month, d.day, 10, 30), sender, f"{subject} {i}") for i, d in enumerate(days)]


def folders():
    return {"받은 편지함/프로젝트A": xmsg("pa", [D("2026-09-10"), D("2026-09-03"), D("2026-08-25")]),
            "보낸 편지함/보고": xmsg("bg", [D("2026-09-05"), D("2026-08-20")], sender="나", subject="주간 보고서"),
            "지운 편지함/옛 폴더": xmsg("old", [D("2026-09-09")], subject="지운 메일"),
            "보관": xmsg("ar", [D("2026-09-08"), D("2026-07-01")], subject="보관 메일"),
            "프로젝트B": xmsg("pb", [D("2026-09-20"), D("2026-09-15"), D("2026-08-01")], subject="과제 회의")}


def _tree_of(br):
    t = br.eval_json(owa._tree_js("read"))
    return op.tree_nodes(t["items"]), t["trees"]


def _mail(br, run=None, **kw):
    run = run or owa.Run(D0, D1, today=TODAY, recover_max=0)
    for k, v in kw.items():
        setattr(run, k, v)
    rows, st, diag, day_st = owa.collect_mail(br, D0, D1, run=run)
    return run, rows, diag, day_st


# ════════════════════════════════ 순수 판정 ════════════════════════════════
class FolderPure(unittest.TestCase):
    def test_folder_kind_multilingual_and_name_tail(self):
        k = op.folder_kind
        for name, want in (("받은 편지함", "inbox"), ("Inbox", "inbox"), ("Posteingang", "inbox"), ("受信トレイ", "inbox"),
                           ("보낸 편지함", "sent"), ("Sent Items", "sent"), ("Gesendete Elemente", "sent"),
                           ("지운 편지함", "deleted"), ("Deleted Items", "deleted"), ("정크 메일", "junk"), ("Junk Email", "junk"),
                           ("임시 보관함", "drafts"), ("보낼 편지함", "outbox"), ("대화 기록", "conv"), ("RSS 구독", "rss"),
                           ("동기화 문제", "sync"), ("메모", "notes"), ("검색 폴더", "search"), ("예약됨", "scheduled"),
                           ("보관", "archive"), ("Archive", "archive"), ("프로젝트A", ""), ("2025", ""), ("Sent", "")):
            self.assertEqual(k(name), want, name)
        self.assertNotIn("archive", op.SKIP_KINDS)                                  # 보관은 읽는다(받은 메일)
        self.assertEqual(k("Papierkorb", "deleteditems"), "deleted")                 # data-folder-name 이 이름보다 앞선다
        self.assertEqual(k("메모", "", top=False), "")                               # 맨 위 칸 밖의 '메모'는 사람이 만든 폴더
        self.assertEqual(k("아무 이름", "junkemail", top=False), "junk")
        n = op.folder_name
        self.assertEqual(n("받은 편지함, 읽지 않음 3"), "받은 편지함")
        self.assertEqual(n("Inbox, 3 unread"), "Inbox")
        self.assertEqual(n("받은 편지함 읽지 않은 항목 3개"), "받은 편지함")
        self.assertEqual(n("프로젝트A, 선택됨"), "프로젝트A")
        self.assertEqual((n("과제 3"), n("2025"), n("  공백   많은  이름 ")), ("과제 3", "2025", "공백 많은 이름"))

    def test_pick_mailbox_skips_favorites_groups_shared_archive(self):
        for flags in ({"tree": "aria"}, {"tree": "dom"}, {"tree": "split"}, {"tree": "aria", "fav_label": ""},
                      {"tree": "split", "fav_label": ""}, {"tree": "aria", "wk": False}):
            br = fb.FakeBrowser(TODAY, folders=folders(), **flags)
            nodes, trees = _tree_of(br)
            scope, why = op.pick_mailbox(nodes, trees)
            self.assertEqual(why, "", flags)
            if flags["tree"] == "split":
                self.assertEqual((scope["kind"], trees[scope["tree"]]["al"]), ("tree", fb.MAILBOX), flags)
            else:
                self.assertEqual((scope["kind"], nodes[scope["root"]]["name"]), ("root", fb.MAILBOX), flags)
            self.assertGreaterEqual(scope["score"], owa.XF_GOOD, flags)
            sh = op.tree_shape(nodes, trees, scope)
            self.assertIn("m", sh["rk"], flags)
            self.assertNotIn("프로젝트", json.dumps(sh, ensure_ascii=False), flags)       # 구조 진단에 폴더 이름 없음
        self.assertEqual(op.pick_mailbox([], []), (None, "none"))
        br = fb.FakeBrowser(TODAY, folders=folders(), tree="aria", xf_collapsed={"@mb"})   # 기본 사서함 머리가 접힘
        nodes, trees = _tree_of(br)
        scope, _why = op.pick_mailbox(nodes, trees)
        self.assertTrue(scope is None or scope["score"] < owa.XF_GOOD)             # 공유 사서함(받은 편지함 하나)만 보인다
        self.assertEqual([nodes[i]["name"] for i in op.open_roots(nodes, trees)], [fb.MAILBOX])

    def test_plan_folders_boxes_system_and_user_skip(self):
        br = fb.FakeBrowser(TODAY, folders=dict(folders(), **{"프로젝트B/하위": []}), tree="aria")
        nodes, trees = _tree_of(br)
        scope, _w = op.pick_mailbox(nodes, trees)
        plan = op.plan_folders(nodes, scope)
        got = [(nodes[f["i"]]["name"], f["box"], f["kind"]) for f in plan["extra"]]
        self.assertEqual(got, [("프로젝트A", "inbox", "user"), ("보고", "sent", "user"), ("보관", "inbox", "archive"),
                               ("프로젝트B", "inbox", "user"), ("하위", "inbox", "user")])
        self.assertEqual(plan["sys"], 8)          # 임시·지운(+옛 폴더)·정크·메모·대화 기록·RSS·검색 폴더
        self.assertEqual((plan["expand"], plan["user"]), ([], 0))
        plan2 = op.plan_folders(nodes, scope, ["프로젝트b"])
        self.assertEqual(plan2["user"], 2)                                         # 하위까지 함께 뺀다
        self.assertNotIn("하위", [nodes[f["i"]]["name"] for f in plan2["extra"]])
        br = fb.FakeBrowser(TODAY, folders=folders(), tree="aria", xf_collapsed={"받은 편지함"})
        nodes, trees = _tree_of(br)
        scope, _w = op.pick_mailbox(nodes, trees)
        plan = op.plan_folders(nodes, scope)
        self.assertNotIn("프로젝트A", [nodes[f["i"]]["name"] for f in plan["extra"]])     # 접혀 있어 안 보인다
        self.assertEqual([nodes[i]["name"] for i in plan["expand"]], ["받은 편지함"])
        k = op.node_key(nodes, plan["expand"][0], trees)
        self.assertEqual(k, ("", fb.MAILBOX, "받은 편지함"))
        self.assertEqual(op.find_node(nodes, k, trees), plan["expand"][0])

    def test_cap_extra_never_upgrades(self):
        d = [D(f"2026-09-0{i}") for i in range(1, 6)]
        ds = {d[0]: "ok", d[1]: "ok", d[2]: "partial", d[3]: "unverified", d[4]: "zero_ok"}
        self.assertEqual(op.cap_extra(ds, op.verdict_ranges("list_verified", d[1], d[0], d[4])), 2)
        self.assertEqual(ds, {d[0]: "partial", d[1]: "partial", d[2]: "partial", d[3]: "unverified", d[4]: "zero_ok"})
        self.assertEqual(op.cap_extra(ds, [(d[0], d[4], "ok")]), 0)                 # 끝까지 읽은 폴더는 올리지도 않는다
        self.assertEqual(ds[d[3]], "unverified")
        self.assertEqual(op.cap_extra(ds, [(d[0], d[4], "unverified")]), 1)         # zero_ok 도 낮춘다
        self.assertEqual(ds[d[4]], "partial")

    def test_url_kind_same_folder_body_key(self):
        u = op.url_kind
        self.assertEqual(u("https://outlook.office.com/mail/deleteditems"), "deleted")
        self.assertEqual(u("https://outlook.office.com/mail/0/junkemail/"), "junk")
        self.assertEqual(u("https://outlook.office.com/mail/archive"), "archive")
        self.assertEqual(u("https://outlook.office.com/mail/inbox"), "inbox")
        self.assertEqual(u("https://outlook.office.com/mail/inbox/id/AAQkAGI"), "")    # 메일을 연 주소 — 받은 편지함 자신이 아니다
        self.assertEqual(u("https://outlook.office.com/mail/id/AAMkADI"), "")
        s = op.same_folder
        self.assertTrue(s("프로젝트A3", "프로젝트A"))                                   # 글에 읽지 않은 수가 붙어 온다
        self.assertFalse(s("보낸 편지함", "프로젝트A"))
        self.assertIsNone(s("", "프로젝트A"))
        self.assertIsNone(s("2025", "2025"))                                          # 숫자뿐인 이름은 비교할 수 없다(모름)
        k = op.body_key("2026-10-05 14:00", "2026-10-05 15:00", "주간 회의")
        self.assertTrue(k.startswith("2026-10-05 14:00|2026-10-05 15:00|"))
        self.assertEqual(len(k.rsplit("|", 1)[1]), 12)
        self.assertNotIn("주간", k)
        self.assertEqual(k, op.body_key("2026-10-05 14:00", "2026-10-05 15:00", " 주간  회의 "))


# ════════════════════════════════ 다른 메일 폴더 — 화면 흐름 ════════════════════════════════
class OwaExtraFolders(unittest.TestCase):
    def setUp(self):
        self.box = fb.make_mailbox(D("2026-09-01"), TODAY)

    def test_reads_user_folders_with_boxes_and_keeps_verdicts(self):
        br = fb.FakeBrowser(TODAY, mail=self.box, folders=folders(), tree="aria")
        run, rows, diag, day_st = _mail(br)
        self.assertEqual(br.navs, ["받은 편지함/프로젝트A", "보낸 편지함/보고", "보관", "프로젝트B"])   # 지운·공유·그룹·보관 사서함 없음
        xr = [r for r in rows if r[3].startswith(("견적 회신", "주간 보고서", "보관 메일", "과제 회의", "지운 메일"))]
        self.assertEqual(sorted((r[0], r[3]) for r in xr),
                         [("inbox", "견적 회신 0"), ("inbox", "견적 회신 1"), ("inbox", "과제 회의 0"), ("inbox", "과제 회의 1"),
                          ("inbox", "보관 메일 0"), ("sent", "주간 보고서 0")])           # 보낸 편지함 하위 = sent · 기간 밖 제외
        self.assertEqual(len(rows), 60 + 6)
        for ax in ("mail_in", "mail_out"):
            self.assertEqual(_st_days(day_st[ax], D0, D1, "ok"), [], ax)              # 끝 근거(기간 시작 앞 도달) — 낮추지 않음
        xf = run.xf
        self.assertEqual((xf["enum"], xf["found"], xf["read"], xf["ok"], xf["sys"], xf["rows"], xf["fail"], xf["down"]),
                         ("ok", 4, 4, 4, 8, 6, 0, 0))
        self.assertEqual(br.calls["cdp:Input.dispatchMouseEvent"] >= 3 * 4, True)   # 이름 글에 신뢰 마우스(옮김·누름·뗌)
        self.assertEqual(br.calls["open"], 0)                                        # 메일은 열지 않는다
        line, cen = owa._census(run, ["mail"], {"mail": (rows, "ok", diag, day_st)})
        self.assertIn("다른 폴더 4/4(끝 근거 4·제외 8·행 6)", line)
        self.assertIn("→ 확인", line)
        dumped = json.dumps(cen, ensure_ascii=False)
        self.assertLessEqual(len(dumped.encode("utf-8")), owa.CENSUS_MAX)
        for word in ("프로젝트", "보고서", "견적", "고객사", fb.MAILBOX):                # 폴더·메일 글자는 진단에 없다
            self.assertNotIn(word, dumped)
        self.assertEqual(cen["mail"]["xf"]["found"], 4)

    def test_tree_styles_and_expansion_methods(self):
        cases = (({"tree": "dom", "xf_collapsed": {"@mb"}, "expand": "chev"}, "chev"),       # 기본 사서함 머리가 접힘 → 펼침 단추
                 ({"tree": "aria", "xf_collapsed": {"받은 편지함"}, "expand": "key"}, "key"),   # 받은 편지함이 접힘 → 키 →
                 ({"tree": "split", "xf_collapsed": {"받은 편지함"}, "expand": "synth"}, "synth"),
                 ({"tree": "aria", "fav_label": ""}, ""))
        for flags, how in cases:
            br = fb.FakeBrowser(TODAY, mail=self.box, folders=folders(), **flags)
            run, rows, _diag, day_st = _mail(br)
            self.assertIn("받은 편지함/프로젝트A", br.navs, flags)
            self.assertEqual(run.xf["read"], 4, flags)
            self.assertEqual(run.xf_how, how, flags)
            self.assertFalse([p for p in br.navs if p.startswith("@")], flags)       # 즐겨찾기·그룹·공유·온라인 보관은 열지 않는다
            self.assertEqual(_st_days(day_st["mail_in"], D0, D1, "ok"), [], flags)

    def test_expand_dead_reads_visible_folders_only(self):
        br = fb.FakeBrowser(TODAY, mail=self.box, folders=folders(), tree="aria", xf_collapsed={"받은 편지함"}, expand="dead")
        run, _rows, _diag, day_st = _mail(br)
        self.assertNotIn("받은 편지함/프로젝트A", br.navs)
        self.assertEqual((run.xf["read"], run.xf["expf"]), (3, 1))
        self.assertEqual(_st_days(day_st["mail_in"], D0, D1, "ok"), [])             # 못 본 폴더는 알 수 없다 — 낮추지 않음

    def test_switch_failures_downgrade_and_stop(self):
        br = fb.FakeBrowser(TODAY, mail=self.box, folders=folders(), tree="aria", nav_dead=True)
        run, rows, _diag, day_st = _mail(br)
        self.assertEqual(len(rows), 60)                                               # 받은·보낸 편지함 행은 그대로
        self.assertEqual((run.xf["fail"], run.xf["left"], run.xf["read"]), (owa.XF_NAV_DEAD, 2, 0))
        for ax in ("mail_in", "mail_out"):                                            # 프로젝트A(받은)·보고(보낸)가 안 열렸다
            self.assertEqual(_st_days(day_st[ax], D0, D1, "partial"), [], ax)

    def test_folder_without_end_evidence_partial_older_days(self):
        fl = {"프로젝트B": xmsg("pb", [D("2026-09-25"), D("2026-09-20"), D("2026-09-15"), D("2026-09-10"), D("2026-09-05"),
                                    D("2026-08-30")])}
        br = fb.FakeBrowser(TODAY, mail=self.box, folders=fl, tree="aria", xf_reach={"프로젝트B": 3})
        run, rows, _diag, day_st = _mail(br)
        self.assertEqual(len([r for r in rows if r[3].startswith("견적 회신")]), 3)
        self.assertEqual(_st_days(day_st["mail_in"], D0, D("2026-09-15"), "partial"), [])
        self.assertEqual(_st_days(day_st["mail_in"], D("2026-09-16"), D1, "ok"), [])
        self.assertEqual(_st_days(day_st["mail_out"], D0, D1, "ok"), [])             # 받은 메일 폴더 — 보낸 축은 그대로
        self.assertEqual(run.xf["ends"], {"busy": 1, "empty": 1})                    # 빈 보관 폴더는 '비어 있음'으로 끝(0건 확인)
        self.assertEqual(run.xf["v"], {"list_verified": 1, "empty_verified": 1})

    def test_same_message_not_taken_twice_and_stale_list_guard(self):
        same = fb.msg("dup", datetime(2026, 9, 12, 11, 0), "협력사", "공용 안건")
        box = dict(self.box, inbox=self.box["inbox"] + [same])
        fl = {"프로젝트B": [same] + xmsg("pb", [D("2026-09-20"), D("2026-08-01")], subject="과제 회의")}
        br = fb.FakeBrowser(TODAY, mail=box, folders=fl, tree="aria", stale_screens=2)
        run, rows, _diag, day_st = _mail(br)
        self.assertEqual(len([r for r in rows if r[2] == "협력사"]), 1)              # 같은 항목 키 — 한 번만
        self.assertEqual(len([r for r in rows if r[3].startswith("과제 회의")]), 1)
        self.assertIsNone(run.sd.get("xf_stale"))                                     # 앞 폴더 목록 두 화면은 기다려 넘겼다
        self.assertEqual(_st_days(day_st["mail_in"], D0, D1, "ok"), [])
        br = fb.FakeBrowser(TODAY, mail=self.box, folders=fl, tree="aria", stale_screens=50)
        run, rows, _diag, day_st = _mail(br)
        self.assertEqual(run.sd.get("xf_stale"), 1)                                   # 끝내 앞 폴더 그대로 — 읽지 않는다
        self.assertEqual([r for r in rows if r[3].startswith("과제 회의")], [])
        self.assertEqual(_st_days(day_st["mail_in"], D0, D1, "partial"), [])

    def test_time_cut_downgrades_unread_folders(self):
        run = owa.Run(D0, D1, today=TODAY, recover_max=0)
        br = fb.FakeBrowser(TODAY, mail=self.box, folders=folders(), tree="aria",
                            on_nav=lambda p: setattr(run, "timed_out", True))
        run, rows, _diag, day_st = _mail(br, run)
        self.assertEqual((run.xf["read"], run.xf["left"]), (1, 3))
        self.assertEqual(br.navs, ["받은 편지함/프로젝트A"])
        for ax in ("mail_in", "mail_out"):
            self.assertEqual(_st_days(day_st[ax], D0, D1, "partial"), [], ax)

    def test_user_skip_cap_off_and_no_tree(self):
        br = fb.FakeBrowser(TODAY, mail=self.box, folders=folders(), tree="aria")
        run, _rows, _diag, day_st = _mail(br, xf_skip=["프로젝트b"], xf_max=1)
        self.assertEqual(br.navs, ["받은 편지함/프로젝트A"])
        self.assertEqual((run.xf["user"], run.xf["cap"], run.xf["found"]), (1, 2, 3))
        self.assertEqual(_st_days(day_st["mail_in"], D0, D1, "ok"), [])             # 상한으로 뺀 폴더는 낮추지 않는다(로그만)
        br = fb.FakeBrowser(TODAY, mail=self.box, folders=folders(), tree="aria")
        run, rows, _diag, _ds = _mail(br, xf_on=False)
        self.assertEqual((run.xf["enum"], br.calls["tree"], len(rows)), ("off", 0, 60))
        br = fb.FakeBrowser(TODAY, mail=self.box)                                     # 폴더 창 없음(접힌 탐색 창 등)
        run, rows, diag, day_st = _mail(br)
        self.assertEqual((run.xf["enum"], len(rows)), ("none", 60))
        self.assertEqual(_st_days(day_st["mail_in"], D0, D1, "ok"), [])
        line, _cen = owa._census(run, ["mail"], {"mail": (rows, "ok", diag, day_st)})
        self.assertIn("다른 폴더 못 찾음(폴더 창 없음)", line)

    def test_main_fake_folders_and_counts(self):
        fake = {"mail": {"2026-03": {
            "inbox": [{"key": "k1", "label": "동료, 안내, 2026-03-05 오전 9:10", "texts": ["동료", "안내"]}], "sent": [],
            "folders": {"프로젝트A": [{"key": "k2", "label": "협력사, 사양 검토, 2026-03-06 오후 2:10", "texts": ["협력사", "사양 검토"]}],
                        "보낸 편지함/보고": [{"key": "k3", "label": "나, 주간 보고, 2026-03-09 오전 8:30", "texts": ["나", "주간 보고"]}],
                        "지운 편지함": [{"key": "k4", "label": "광고, 할인 안내, 2026-03-10 오전 7:00", "texts": ["광고", "할인 안내"]}]}}}}
        with tempfile.TemporaryDirectory(prefix="lm28_p16_") as tmp:
            fk = os.path.join(tmp, "fake.json")
            with open(fk, "w", encoding="utf-8") as f:
                json.dump(fake, f, ensure_ascii=False)
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["Get-OutlookWeb.py", "--from", "2026-03-01", "--to", "2026-03-31", "--only",
                                                 "mail", "--out-dir", tmp, "--tag", "owa"]), \
                    mock.patch.dict(os.environ, {"LM_OWA_FAKE": fk, "LM_NO_BROWSER": ""}), contextlib.redirect_stdout(out):
                rc = owa.main()
            st = _status_of(out.getvalue())
            with open(os.path.join(tmp, "mail_owa.csv"), encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))[1:]
        self.assertEqual(rc, 0)
        self.assertEqual(sorted((r[0], r[3]) for r in rows), [("inbox", "사양 검토"), ("inbox", "안내"), ("sent", "주간 보고")])
        c = st["counts"]
        self.assertEqual((c["xf_enum"], c["xf_read"], c["xf_sys"], c["xf_rows"], c["collector_ver"]),
                         ("fake", 2, 1, 2, "LM28-OWA-5"))


# ════════════════════════════════ Copilot 메일 질문 ════════════════════════════════
class CopilotAllFolders(unittest.TestCase):
    def test_prompt_asks_all_folders_and_parser_box_words(self):
        for alt in (False, True):
            p = mvc.build_prompt("mail", "2026-03-01", "2026-03-07", alt)
            self.assertIn("모든 메일 폴더", p)
            self.assertIn("이름을 바꾼 폴더", p)
            self.assertIn("지운 편지함·정크 메일·임시 보관함은 제외", p)
            self.assertNotIn("받은 편지함과 보낸 편지함의 메일", p)
            self.assertIn("box : 받은 메일이면 inbox, 내가 보낸 메일이면 sent", p)
        self.assertNotIn("모든 메일 폴더", mvc.build_prompt("cal", "2026-03-01", "2026-03-07"))
        reply = ("box,time,sender,subject,conversation,rcv\n"
                 "받은 메일,2026-03-02 10:00,동료,설계 검토,설계 검토,to\n"
                 "received,2026-03-03 11:00,협력사,견적,견적,cc\n"
                 "보낸 항목,2026-03-04 12:00,나,회신,회신,\n"
                 "프로젝트A,2026-03-05 09:00,동료,폴더 이름 상자,폴더 이름 상자,to\n")
        rows = mvc.parse_mail_rows(reply)
        self.assertEqual([(r[0], r[3]) for r in rows], [("inbox", "설계 검토"), ("inbox", "견적"), ("sent", "회신")])


# ════════════════════════════════ 일정 본문 발췌 ════════════════════════════════
def _events():
    evs = fb.make_events(D("2026-09-28"), D("2026-10-02"))
    evs[0]["body"] = "안건: 설계 검토 진행 상황 공유\nhttps://teams.microsoft.com/l/meetup-join/xyz"
    evs[1]["body"] = "여기를 클릭하여 모임에 참가"                                      # 안내문뿐
    evs[2]["private"] = True
    evs[3]["join"] = True
    return evs                                                                        # evs[4] 는 본문 칸 없음


def _fake_clean(t, max_len=600):
    return "" if "여기를 클릭하여" in t else re.sub(r"https?://\S+", " ", t)


class CalBody(unittest.TestCase):
    d0, d1 = D("2026-09-28"), D("2026-10-04")

    def setUp(self):
        self._mn = dict(owa._MN)
        owa._MN.clear()
        owa._MN["f"] = _fake_clean

    def tearDown(self):
        owa._MN.clear()
        owa._MN.update(self._mn)

    def _cal(self, run=None, **flags):
        br = fb.FakeBrowser(TODAY, events=flags.pop("events", None) or _events(), **flags)
        run = run or owa.Run(self.d0, self.d1, today=TODAY)
        rows, _st, _diag, day_st = owa.collect_cal(br, self.d0, self.d1, run=run)
        return br, run, rows, day_st

    def test_open_read_close_and_cache(self):
        br, run, rows, day_st = self._cal(peek=True)
        cb = run.cb
        self.assertEqual((cb["open"], cb["found"], cb["body"], cb["closed"], cb["join"], cb["skip"], cb["dead"]),
                         (3, 3, 1, 3, 1, 1, ""))
        self.assertEqual(run.c["weeks_ok"], 1)
        self.assertEqual(_st_days(day_st, self.d0, self.d1, "ok"), [])                # 본문 읽기가 주 판정을 바꾸지 않는다
        by = {r[4]: r for r in rows}
        self.assertEqual(by["정기 회의 928"][9:], ["안건: 설계 검토 진행 상황 공유"])
        self.assertEqual(len(by["정기 회의 929"]), 7)                                 # 안내문뿐 — 본문 없음(빈 발췌는 캐시에만)
        self.assertEqual(sorted(run.cb_new.values()), ["", "안건: 설계 검토 진행 상황 공유"])
        self.assertEqual(br.calls["bar_click"], 3)                                    # 비공개·참가 단추 막대는 누르지 않았다
        run2 = owa.Run(self.d0, self.d1, today=TODAY)
        run2.cb_cache = dict(run.cb_new)
        br2, run2, rows2, _ds = self._cal(run2, peek=True)
        self.assertEqual((run2.cb["open"], run2.cb["cache"]), (1, 2))                 # 이미 읽은 회의는 다시 열지 않는다
        self.assertEqual({r[4]: r for r in rows2}["정기 회의 928"][9], "안건: 설계 검토 진행 상황 공유")
        plus = owa._census_plus(run, ["cal"], {"cal": (rows, "ok", {}, day_st)})
        self.assertIn("본문 1/3(상세 3·닫힘 3·저장됨 0)", plus)
        self.assertNotIn("설계", plus)

    def test_sticky_peek_view_change_title_mismatch_and_limits(self):
        _br, run, _rows, _ds = self._cal(peek=True, peek_sticky=True)
        self.assertEqual((run.cb["closed"], run.cb["xbtn"]), (3, 3))                   # Esc 로 안 닫히면 '닫기' 단추
        br, run, rows, day_st = self._cal(peek=True, view_breaks=True)
        self.assertEqual((run.cb["dead"], run.cb["none"], run.cb["open"]), ("view", 1, 1))
        self.assertEqual(run.cb_off, (TODAY + timedelta(days=owa.CB_OFF_DAYS)).isoformat())
        self.assertEqual(br.view, "cal")                                               # 그 주 주소로 되돌렸다
        self.assertEqual((len(rows), run.c["weeks_ok"]), (5, 1))
        _br, run, _rows, _ds = self._cal(peek=True, peek_title="다른 회의")
        self.assertEqual((run.cb["mis"], run.cb_new), (2, {}))                         # 다른 회의 상세 — 적지 않는다
        r0 = owa.Run(self.d0, self.d1, today=TODAY)
        r0.cb_max = 1
        _br, run, _rows, _ds = self._cal(r0, peek=True)
        self.assertEqual((run.cb["open"], run.cb["cap"]), (1, 3))
        r1 = owa.Run(self.d0, self.d1, today=TODAY)
        r1.store_subject = False                                                       # 저장물 최소화 — 열지 않는다
        br, run, _rows, _ds = self._cal(r1, peek=True)
        self.assertEqual((br.calls["bar"], run.cb["open"]), (0, 0))
        r2 = owa.Run(self.d0, self.d1, today=TODAY)
        r2.cb_off = (TODAY + timedelta(days=1)).isoformat()                            # 쉬는 날
        br, run, _rows, _ds = self._cal(r2, peek=True)
        self.assertEqual(br.calls["bar"], 0)

    def test_want_rules_and_fallback_clean(self):
        run = owa.Run(self.d0, TODAY, today=TODAY)
        ev = {"label": "x", "texts": []}
        self.assertIsNone(owa._cb_want(run, ev, ["2026-10-07 10:00", "2026-10-07 11:00", "False", "2", "오늘 회의", "", ""]))
        self.assertIsNone(owa._cb_want(run, ev, ["2026-10-06 00:00", "2026-10-06 23:59", "True", "2", "종일", "", ""]))
        self.assertIsNone(owa._cb_want(run, {"label": "x", "alt": ["비공개"]},
                                       ["2026-10-05 10:00", "2026-10-05 11:00", "False", "2", "면담", "", ""]))
        k = owa._cb_want(run, ev, ["2026-10-06 10:00", "2026-10-06 11:00", "False", "2", "어제 회의", "", ""])
        self.assertTrue(k)
        self.assertIsNone(owa._cb_want(run, ev, ["2026-10-06 10:00", "2026-10-06 11:00", "False", "2", "어제 회의", "", ""]))
        self.assertEqual(run.cb["skip"], 3)
        owa._MN["f"] = None                                                            # core\meetnote 를 못 불러온 PC
        self.assertEqual(owa._clean_body("안건: 검토\n\thttps://example.com/a?b=1 링크"), "안건: 검토 링크")
        self.assertEqual(len(owa._clean_body("가" * 900)), owa.CB_LEN)
        owa._MN["f"] = lambda t, max_len=600: 1 / 0                                     # 정제 함수가 깨져도 대체 정리로
        self.assertEqual(owa._clean_body("안건\nwww.example.com/x 끝"), "안건 끝")

    def test_save_body_column_old_files_and_store_subject(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p16_") as tmp:
            p = os.path.join(tmp, "cal_owa.csv")
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write("start,end,all_day,busy_status,subject,categories,location,response,meeting_status\n")
                f.write("2026-09-01 10:00,2026-09-01 11:00,False,2,옛 회의,,,,\n")
                f.write("2026-09-29 14:00,2026-09-29 15:00,False,2,정기 회의 929,,,,\n")
            new = [["2026-09-29 14:00", "2026-09-29 15:00", "False", "2", "정기 회의 929", "", ""]]
            bodies = {op.body_key("2026-09-29 14:00", "2026-09-29 15:00", "정기 회의 929"): "안건, \"A\"",
                      op.body_key("2026-09-01 10:00", "2026-09-01 11:00", "옛 회의"): "옛 안건"}
            ver = {"cal": [("2026-09-28", "2026-10-04")]}
            owa._save("cal", new, True, p, ver, bodies)
            with open(p, encoding="utf-8-sig") as f:
                got = list(csv.reader(f))
            self.assertEqual(",".join(got[0]), owa.CAL_HDR)
            self.assertTrue(owa.CAL_HDR.endswith(",body"))
            self.assertEqual([(r[4], r[9]) for r in got[1:]], [("옛 회의", "옛 안건"), ("정기 회의 929", "안건, \"A\"")])
            owa._save("cal", new, False, p, ver, bodies)
            with open(p, encoding="utf-8-sig") as f:
                self.assertEqual([r[9] for r in list(csv.reader(f))[1:]], ["", ""])     # storeMailSubject=false — 본문 비움

    def test_cache_file_masked_in_diag_bundle_and_main_fake(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p16_") as tmp:
            run = owa.Run(self.d0, self.d1, today=TODAY)
            run.cb_path = os.path.join(tmp, "cal_body_owa.json")
            k = op.body_key("2026-09-29 14:00", "2026-09-29 15:00", "정기 회의")
            run.cb_new = {k: "안건: 비밀 과제 일정 조율"}
            self.assertTrue(owa._cb_save(run))
            self.assertEqual(owa._cb_load(run.cb_path), ({k: "안건: 비밀 과제 일정 조율"}, ""))
            with open(run.cb_path, encoding="utf-8") as f:
                masked = json.dumps(diag_bundle.mask_obj(json.load(f)), ensure_ascii=False)
            self.assertNotIn("비밀", masked)                                            # 진단 묶음에는 수만('<가림: 1개>')
            self.assertIn("가림", masked)
            owa._MN["f"] = None
            ev = {"label": "주간 회의, 2026년 9월 29일 화요일 오후 2:00 ~ 오후 3:00, 바쁨", "texts": ["주간 회의"],
                  "body": "안건: 시험 계획 검토\nhttps://example.com/x"}
            fk = os.path.join(tmp, "fake.json")
            with open(fk, "w", encoding="utf-8") as f:
                json.dump({"cal": {"2026-09-28": [ev]}}, f, ensure_ascii=False)
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["Get-OutlookWeb.py", "--from", "2026-09-28", "--to", "2026-10-04", "--only", "cal",
                                                 "--out-dir", tmp, "--tag", "owa"]), \
                    mock.patch.dict(os.environ, {"LM_OWA_FAKE": fk, "LM_NO_BROWSER": ""}), contextlib.redirect_stdout(out):
                rc = owa.main()
            st = _status_of(out.getvalue())
            with open(os.path.join(tmp, "cal_owa.csv"), encoding="utf-8-sig") as f:
                got = list(csv.reader(f))
            cache, _off = owa._cb_load(os.path.join(tmp, "cal_body_owa.json"))
        self.assertEqual(rc, 0)
        self.assertEqual(got[0][-1], "body")
        self.assertEqual(got[1][9], "안건: 시험 계획 검토")
        self.assertEqual(sorted(cache.values()), ["안건: 비밀 과제 일정 조율", "안건: 시험 계획 검토"])   # 캐시는 쌓인다
        self.assertEqual((st["counts"]["cb_open"], st["counts"]["cb_body"]), (1, 1))
        self.assertNotIn("시험 계획", out.getvalue())                                     # 본문은 로그·LMSTATUS 에 없다


# ════════════════════════════════ 원장·설정 ════════════════════════════════
class LedgerAndConfig(unittest.TestCase):
    def test_owa_rule_bump_drops_only_owa_cells(self):
        self.assertEqual(coverage.SRC_RULES["owa"], "3")
        with tempfile.TemporaryDirectory(prefix="lm28_p16_") as td:
            p = os.path.join(td, coverage.FILE_NAME)
            days = {"2026-03-02": {"mail_in": {"owa": "ok", "com": "ok"}, "cal": {"owa": "ok"}},
                    "2026-03-03": {"teams": {"teams_web": "ok"}, "mail_out": {"copilot": "partial"}}}
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"v": 1, "ver": "v|1", "host": "h", "src_rules": {"owa": "2", "teams_web": "2", "com": "2"},
                           "days": days, "suspect": {}, "na": {}, "last": {}}, f)
            L = coverage.Ledger.load(p, "v|1", "h")
            self.assertEqual(L.dropped_src, ["owa"])                                   # 지난 판(받은·보낸만)의 OWA 칸만
            self.assertIsNone(L.src_status("2026-03-02", "mail_in", "owa"))
            self.assertIsNone(L.src_status("2026-03-02", "cal", "owa"))
            self.assertEqual(L.src_status("2026-03-02", "mail_in", "com"), "ok")
            self.assertEqual(L.src_status("2026-03-03", "teams", "teams_web"), "ok")
            self.assertEqual(L.src_status("2026-03-03", "mail_out", "copilot"), "partial")   # 증인은 그대로(다시 묻지 않음)
            L.save()
            self.assertEqual(coverage.Ledger.load(p, "v|1", "h").dropped_src, [])

    def test_config_keys_both_files(self):
        want = {"owaExtraFolders": True, "owaExtraFolderMax": 40, "owaExtraFolderSkip": [], "owaCalBodyMax": 60}
        for name in ("config.default.json", "config.json"):
            with open(os.path.join(_boot.ROOT, "config", name), encoding="utf-8-sig") as f:
                c = json.load(f)
            for k, v in want.items():
                self.assertEqual(c.get(k), v, (name, k))
                self.assertIn(f"_{k}_설명", c, (name, k))
        run = owa.Run(D0, D1, today=TODAY)
        owa._cfg_xf(run, {"owaExtraFolders": "false", "owaExtraFolderMax": "x", "owaExtraFolderSkip": "개인", "owaCalBodyMax": -5})
        self.assertEqual((run.xf_on, run.xf_max, run.xf_skip, run.cb_max), (False, owa.XF_MAX, ["개인"], 0))
        owa._cfg_xf(run, {})
        self.assertEqual((run.xf_on, run.xf_max, run.xf_skip, run.cb_max), (True, 40, [], 60))

    def test_js_placeholders_and_markers(self):
        js = owa._tree_js("aim", 3, 'a"b')
        self.assertTrue(js.startswith("/*LM28:owa_tree*/"))
        self.assertIn('NAME = "a\\"b"', js)
        self.assertIn("K = 3", js)
        self.assertIn("window.__lm_ev = kept.map", owa.JS_CAL)
        for j in (owa.JS_CAL_BAR, owa.JS_CAL_DETAIL):
            self.assertIn("__", j)                                                     # 자리표(__K__·__ACT__)는 부를 때 채운다
        self.assertIn("아무것도 없", owa.JS_MAIL)                                       # 빈 폴더 표식 보강


if __name__ == "__main__":
    unittest.main()
