# -*- coding: utf-8 -*-
"""색인 수집기(Get-OutlookIndex.ps1) — 계정 있는 회사 PC 가정 시험(Microsoft 문서 대조 위험 H11·H12·M18·M19·L7·L8·L9).

%TEMP% 복제 트리에서 LM_INDEX_FAKE 주입점만 쓴다(실 색인·실 Outlook·실 레지스트리 0). 가짜 색인 행은 문서 모양을 따른다:
``System.ItemFolderPathDisplay`` = '/<메일함 계정>/<폴더>'(props-system-itemfolderpathdisplay 예 '/Mailbox Account/Inbox'),
``System.ItemUrl`` = 'mapi16://{<사용자 SID>}/<저장소>/…'(-search-sql-folderdepth SCOPE 예 · Windows Search 블로그 형식).

* H11 메일 지평선은 메일만으로(주 저장소·제외 폴더 밖) — 오래된 일정·공유 메일함이 지평선이 되지 않는다. 정책 동기화 창
  (HKCU\\Software\\Policies\\Microsoft\\Office\\16.0\\Outlook\\Cached Mode SyncWindowSetting·SyncWindowSettingDays)이 있으면 그보다
  오래된 날은 out_of_horizon(only-subset-items-synchronized).
* H12 공유·추가 메일함과 공유 일정은 '내 것'이 아니다(shared-mail-folders-in-cached-exchange-mode) — 주 저장소만.
* M18 일정은 일정 폴더에서만 — 지운 편지함·받은 편지함(모임 요청)·같은 회의 중복을 뺀다.
* M19 OleDbCommand.CommandTimeout 기본 30초 — 시간 초과는 '확장 속성 거부' 사다리로 내려가지 않는다.
* L7 탐침 Decide-Index 와 같은 판정(정책은 건수와 무관 · 최근 365일 종류별 건수 · 카탈로그 재구축 중).
* L8 다른 사용자 SID 의 mapi 항목은 뺀다(내 SID 행이 하나도 없으면 거르지 않는다).
* L9 날짜 리터럴 해석 차이 — 하루 여유로 묻고 정확한 창으로 다시 거른다, 어긋남이 보이면 R-TZ.
"""
import json
import re
import subprocess
import unittest
from datetime import date, timedelta

from lm27.collect import rcmap
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp15.mailkit import CREATE_NO_WINDOW, ps_exe, run_ps

SCRIPT = "Get-OutlookIndex.ps1"
ME = "worker.a@corp.example"
TEAM = "team.box@corp.example"
PEER = "peer.b@corp.example"
SID_ME = "S-1-12-1-1111111111-2222222222-3333333333-4444444444"
SID_OTHER = "S-1-12-1-5555555555-6666666666-7777777777-8888888888"
NOW = "2026-10-07 18:00"
YEAR = ["-Since", "2026-01-01", "-Until", "2026-10-07", "-TestNow", NOW]
SEP = ["-Since", "2026-09-01", "-Until", "2026-09-30", "-TestNow", NOW]


def weekdays(a: date, b: date):
    d = a
    while d <= b:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def mail(store, folder, subject, when, *, sent=False, sid=SID_ME, frm=None):
    path = "/" + "/".join(x for x in (store, folder) if x)
    r = {"System.ItemUrl": f"mapi16://{{{sid}}}/{store}($1a2b)/0/{folder}/{subject}",
         "System.ItemFolderPathDisplay": path, "System.Subject": subject, "System.ItemDate": when,
         "System.Message.FromName": ["보낸이"], "System.Message.FromAddress": [frm or (ME if sent else PEER)],
         "System.Message.ToAddress": [PEER if sent else ME], "System.Message.ToName": ["받는이"],
         "System.Message.CcAddress": [], "System.Message.CcName": [], "System.Message.ConversationID": "c" + subject[-4:],
         "System.Kind": ["email"]}
    r["System.Message.DateSent" if sent else "System.Message.DateReceived"] = when
    return r


def cal(store, folder, subject, start, end, *, sid=SID_ME, recurring=False):
    return {"System.ItemUrl": f"mapi16://{{{sid}}}/{store}($1a2b)/0/{folder}/{subject}",
            "System.ItemFolderPathDisplay": "/" + "/".join(x for x in (store, folder) if x),
            "System.Subject": subject, "System.StartDate": start, "System.EndDate": end,
            "System.Calendar.ShowTimeAs": 2, "System.Calendar.IsRecurring": recurring, "System.Kind": ["calendar"]}


def mail_days(store, a, b, *, tag, per_day=1, sent_per_day=0, sid=SID_ME, folder="받은 편지함", frm=None):
    out = []
    for d in weekdays(a, b):
        for i in range(per_day):
            out.append(mail(store, folder, f"{tag} 받은 {d:%m%d}-{i}", f"{d:%Y-%m-%d} {9 + i:02d}:10", sid=sid, frm=frm))
        for i in range(sent_per_day):
            out.append(mail(store, "보낸 편지함", f"{tag} 보낸 {d:%m%d}-{i}", f"{d:%Y-%m-%d} {14 + i:02d}:20", sent=True, sid=sid,
                            frm=frm or (ME if store != TEAM else TEAM)))
    return out


def cal_days(store, a, b, *, tag, sid=SID_ME, folder="일정"):
    return [cal(store, folder, f"{tag} 회의 {d:%m%d}", f"{d:%Y-%m-%d} 10:00", f"{d:%Y-%m-%d} 11:00", sid=sid)
            for d in weekdays(a, b)]


def zero_cell(res, day):
    return rcmap.translate_cell(res["rc"], res["reasons"], {"n": 0, "date": day, "horizon_oldest": res.get("horizon_oldest"),
                                                             "horizon_newest": res.get("horizon_newest")})["status"]


@unittest.skipUnless(ps_exe(), "Windows PowerShell 없음")
class IndexM365Test(CloneTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = cls.clone.sandbox / "m365idx"
        cls.dir.mkdir(parents=True, exist_ok=True)
        cls.n = 0

    def run_idx(self, fake, rng, only="mail", cfg=None, cursor=None):
        type(self).n += 1
        p = self.dir / f"fake_{self.n}.json"
        p.write_text(json.dumps(fake, ensure_ascii=False), encoding="utf-8")
        a = list(rng) if only is None else ["-Only", only] + list(rng)
        return run_ps(self.clone, SCRIPT, a, env={"LM_INDEX_FAKE": str(p)}, cfg=cfg, cursor=cursor)

    # ── H11 지평선 ───────────────────────────────────────────────────────────────────────────────
    def h11_fake(self, **extra):
        m = mail_days(ME, date(2026, 7, 8), date(2026, 10, 7), tag="H11", sent_per_day=1)
        c = [cal(ME, "일정", "H11 주간 회의(반복 마스터)", "2019-03-04 10:00", "2019-03-04 11:00", recurring=True)]
        c += cal_days(ME, date(2026, 9, 1), date(2026, 10, 7), tag="H11")
        return dict({"mail": m, "calendar": c, "_my_addrs": [ME], "_classic": True}, **extra)

    def test_h11_mail_horizon_is_mail_only(self):
        """동기화 창 3개월 회사 PC: 메일은 7/8 부터, 일정 반복 마스터는 2019 — 메일 지평선은 7/8(1~6월 0건은 미관측)."""
        r = self.run_idx(self.h11_fake(), YEAR)
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.index")
        self.assertEqual(res["horizon_oldest"], "2026-07-08")
        self.assertIn("R-HORIZON", res["reasons"])
        self.assertEqual(res["counts"]["horizon_src"], "index")
        self.assertEqual(zero_cell(res, "2026-02-03"), "out_of_horizon")      # 예전: zero_ok(관측 못 한 날을 0건으로 확정)
        self.assertEqual(zero_cell(res, "2026-08-15"), "zero_ok")            # 지평선 안 주말은 정상 0건
        rc = self.run_idx(self.h11_fake(), YEAR, only="cal")
        cres = rc.result("cal.index")
        self.assertEqual(cres["horizon_oldest"], "2019-03-04")               # 일정은 동기화 창 영향 없음(문서)
        self.assertNotIn("R-HORIZON", cres["reasons"])

    def test_h11_sync_window_policy(self):
        """정책 SyncWindowSetting(개월)·SyncWindowSettingDays(일): 색인에 남은 오래된 메일이 있어도 창 밖 날짜는 out_of_horizon."""
        fake = self.h11_fake(_sync_window_months=3)
        fake["mail"].append(mail(ME, "받은 편지함", "H11 남은 옛 메일", "2026-02-02 09:00"))
        r = self.run_idx(fake, YEAR)
        res = r.result("mail.index")
        self.assertEqual(res["horizon_oldest"], "2026-07-07")
        self.assertEqual(res["counts"]["horizon_src"], "policy")
        self.assertIn("H11 남은 옛 메일", {x["subject"] for x in r.records})  # 읽은 것은 낸다(그날 셀은 n>0 → ok)
        r2 = self.run_idx(self.h11_fake(_sync_window_months=0, _sync_window_days=14), YEAR)
        self.assertEqual(r2.result("mail.index")["horizon_oldest"], "2026-09-23")
        r3 = self.run_idx(self.h11_fake(_sync_window_months=0, _sync_window_days=0), YEAR)   # 0·0 = 전체(All)
        self.assertEqual(r3.result("mail.index")["counts"]["horizon_src"], "index")

    def test_h11_horizon_ignores_other_stores_and_excluded_folders(self):
        fake = self.h11_fake()
        fake["mail"] += [mail(TEAM, "받은 편지함", "H11 공유 옛 메일", "2025-01-06 09:00"),
                         mail(ME, "지운 편지함", "H11 지운 옛 메일", "2025-06-02 09:00")]
        res = self.run_idx(fake, YEAR).result("mail.index")
        self.assertEqual(res["horizon_oldest"], "2026-07-08")

    def test_h11_aux_failure_falls_back_to_window(self):
        """지평선 질의가 실패하면 지평선을 모른다고 0건을 믿지 않는다 — 창 안 가장 이른 메일 날짜를 지평선으로(보수적)."""
        res = self.run_idx(self.h11_fake(_query_error="timeout@aux"), YEAR).result("mail.index")
        self.assertEqual(res["counts"]["horizon_src"], "window")
        self.assertEqual(res["horizon_oldest"], "2026-07-08")
        self.assertEqual(res["counts"]["aux_error"], "timeout")

    # ── H12 저장소 범위 · M18 일정 폴더 · L8 SID ─────────────────────────────────────────────────
    def shared_fake(self, **extra):
        a, b = date(2026, 9, 1), date(2026, 9, 30)
        m = mail_days(ME, a, b, tag="ME", per_day=2, sent_per_day=1) + mail_days(TEAM, a, b, tag="TEAM", per_day=3,
                                                                                    sent_per_day=1)
        c = cal_days(ME, a, b, tag="ME") + cal_days(TEAM, a, b, tag="TEAM")
        return dict({"mail": m, "calendar": c, "_my_addrs": [ME], "_classic": True}, **extra)

    def test_h12_shared_mailbox_not_mine(self):
        n_team = sum(1 for _ in weekdays(date(2026, 9, 1), date(2026, 9, 30))) * 4
        r = self.run_idx(self.shared_fake(), SEP)
        self.assertEqual(r.rc, 0, r.err_text)
        subj = [x["subject"] for x in r.records]
        self.assertTrue(subj and all(s.startswith("ME ") for s in subj), subj[:5])
        res = r.result("mail.index")
        self.assertEqual((res["counts"]["store_scope"], res["counts"]["stores"]), ("addr", 2))
        self.assertEqual(res["counts"]["other_store"], n_team)
        rc = self.run_idx(self.shared_fake(), SEP, only="cal")                    # 공유 일정도 내 회의가 아니다
        self.assertTrue(rc.records and all(x["subject"].startswith("ME ") for x in rc.records))
        self.assertGreater(rc.result("cal.index")["counts"]["other_store"], 0)

    def test_h12_display_name_stores_use_my_sent_items(self):
        """저장소 이름이 주소가 아니면(표시 이름) 내 주소로 보낸 편지함이 있는 저장소가 주 저장소."""
        fake = self.shared_fake()
        for row in fake["mail"]:
            for k in ("System.ItemFolderPathDisplay", "System.ItemUrl"):
                row[k] = row[k].replace(ME, "Mailbox - Worker A").replace(TEAM, "Mailbox - Team Box")
        r = self.run_idx(fake, SEP)
        self.assertEqual(r.result("mail.index")["counts"]["store_scope"], "sent")
        self.assertTrue(all(x["subject"].startswith("ME ") for x in r.records))

    def test_h12_undecidable_scope_keeps_everything(self):
        """주 저장소를 못 정하면(내 주소 모름) 버리지 않는다 — 내 메일을 잃는 쪽(0건 확정)이 부풀림보다 나쁘다."""
        fake = {k: v for k, v in self.shared_fake().items() if k != "_my_addrs"}
        r = self.run_idx(fake, SEP)
        res = r.result("mail.index")
        self.assertEqual(res["counts"]["store_scope"], "unknown")
        self.assertEqual(res["counts"]["other_store"], 0)
        self.assertTrue(any(x["subject"].startswith("TEAM ") for x in r.records))

    def test_h12_paths_without_store_segment_are_never_filtered(self):
        """경로에 저장소 조각이 없는 모양('\\Presentations', '\\일정')이면 저장소로 거르지 않는다 — 표본에 받은 편지함 행이 없어도
        첫 폴더 이름을 저장소로 오인해 일정을 통째로 버리지 않게."""
        m = [dict(mail(ME, "x", f"NS 메일 {d:%m%d}", f"{d:%Y-%m-%d} 09:00"), **{"System.ItemFolderPathDisplay": "\\Presentations"})
             for d in weekdays(date(2026, 9, 1), date(2026, 9, 30))]
        c = [dict(x, **{"System.ItemFolderPathDisplay": "\\일정"})
             for x in cal_days(ME, date(2026, 9, 1), date(2026, 9, 30), tag="NS")]
        r = self.run_idx({"mail": m, "calendar": c, "_my_addrs": [ME], "_classic": True}, SEP, only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertEqual(len(r.records), len(c))
        self.assertEqual(r.result("cal.index")["counts"]["other_store"], 0)

    def test_m18_calendar_only_from_calendar_folders(self):
        d = "2026-09-15"
        c = [cal(ME, "일정", "M18 회의", f"{d} 10:00", f"{d} 11:00"),
             cal(ME, "받은 편지함", "M18 회의", f"{d} 10:00", f"{d} 11:00"),           # 모임 요청
             cal(ME, "지운 편지함", "M18 취소된 회의", f"{d} 13:00", f"{d} 14:00"),
             cal(ME, "일정/과제 일정", "M18 회의", f"{d} 10:00", f"{d} 11:00")]        # 같은 회의 중복
        fake = {"mail": mail_days(ME, date(2026, 9, 1), date(2026, 9, 30), tag="ME", sent_per_day=1), "calendar": c,
                "_my_addrs": [ME], "_classic": True}
        r = self.run_idx(fake, SEP, only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertEqual([x["subject"] for x in r.records], ["M18 회의"])
        cnt = r.result("cal.index")["counts"]
        self.assertEqual((cnt["excluded_folder"], cnt["cal_mail_folder"], cnt["cal_dup"]), (1, 1, 1))

    def test_l8_other_user_sid_excluded(self):
        a, b = date(2026, 9, 1), date(2026, 9, 30)
        fake = {"mail": mail_days(ME, a, b, tag="ME", sent_per_day=1) + mail_days(ME, a, b, tag="OTHERSID", sid=SID_OTHER),
                "calendar": [], "_my_addrs": [ME], "_classic": True, "_sid": SID_ME}
        r = self.run_idx(fake, SEP)
        self.assertTrue(r.records and all(x["subject"].startswith("ME ") for x in r.records))
        cnt = r.result("mail.index")["counts"]
        self.assertEqual(cnt["sid_check"], "match")
        self.assertEqual(cnt["other_sid"], sum(1 for _ in weekdays(a, b)))
        # 내 SID 행이 하나도 없으면(SID 형식이 다름 등) 거르지 않는다 — 전부 잃지 않게
        r2 = self.run_idx(dict(fake, _sid="S-1-12-1-9"), SEP)
        self.assertEqual(r2.result("mail.index")["counts"]["sid_check"], "nomatch")
        self.assertTrue(any(x["subject"].startswith("OTHERSID") for x in r2.records))

    # ── L7 탐침과 같은 판정 ──────────────────────────────────────────────────────────────────────
    def recent_fake(self, **extra):
        a, b = date(2026, 9, 1), date(2026, 9, 30)
        return dict({"mail": mail_days(ME, a, b, tag="ME", sent_per_day=1), "calendar": cal_days(ME, a, b, tag="ME"),
                     "_my_addrs": [ME], "_classic": True}, **extra)

    def test_l7_policy_blocks_even_with_items(self):
        r = self.run_idx(self.recent_fake(_policy=True), SEP, only=None)
        self.assertEqual(r.rc, 3)
        for src in ("mail.index", "cal.index"):
            self.assertIn("R-IDXPOLICY", r.result(src)["reasons"])
        self.assertEqual(r.records, [])

    def test_l7_policy_hkcu_is_information_only(self):
        r = self.run_idx(self.recent_fake(_policy_hkcu=True), SEP)
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.index")
        self.assertTrue(res["counts"]["policy_hkcu"])
        self.assertNotIn("R-IDXPOLICY", res["reasons"])

    def test_l7_catalog_rebuilding_zero_days_unobserved(self):
        r = self.run_idx(self.recent_fake(_catalog_status=3), SEP)
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.index")
        self.assertIn("R-IDXPAUSED", res["reasons"])
        self.assertEqual(res["counts"]["catalog_status"], 3)
        self.assertEqual(zero_cell(res, "2026-09-05"), "transport_fail")       # 재구축 중 0건은 믿지 않는다
        self.assertEqual(rcmap.translate_cell(res["rc"], res["reasons"], {"n": 3})["status"], "ok")

    def test_l7_catalog_backoff_pause_is_information(self):
        """CATALOG_STATUS_PAUSED 는 사용자 활동 등 back-off 로도 난다(문서) — 항목이 있으면 사유 없이 counts 만."""
        res = self.run_idx(self.recent_fake(_catalog_status=1), SEP).result("mail.index")
        self.assertEqual(res["rc"], 0)
        self.assertNotIn("R-IDXPAUSED", res["reasons"])
        self.assertEqual(res["counts"]["catalog_status"], 1)

    def test_l7_empty_while_rebuilding_is_idxpaused(self):
        r = self.run_idx({"mail": [], "calendar": [], "_my_addrs": [ME], "_classic": True, "_catalog_status": 2}, SEP)
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.result("mail.index")["reasons"], ["R-IDXPAUSED"])

    def test_l7_zero_rule_is_recent_365_days_per_kind(self):
        """탐침 n365: 최근 365일에 그 종류 항목이 0이면 막힘 사유. 2024년 메일만 남은 색인(낡음)은 '그해 0건'이 아니다."""
        old = mail_days(ME, date(2024, 3, 4), date(2024, 3, 29), tag="OLD", sent_per_day=1)
        r = self.run_idx({"mail": old, "calendar": [], "_my_addrs": [ME], "_classic": True},
                         ["-Since", "2024-03-01", "-Until", "2024-03-31", "-TestNow", NOW])
        self.assertEqual(r.rc, 3)
        self.assertIn("R-ONLINE", r.result("mail.index")["reasons"])
        a, b = date(2026, 9, 1), date(2026, 9, 30)
        r2 = self.run_idx({"mail": mail_days(ME, a, b, tag="ME"), "calendar": [], "_my_addrs": [ME], "_classic": True},
                          SEP, only=None)
        self.assertEqual(r2.result("mail.index")["rc"], 0)
        self.assertEqual(r2.result("cal.index")["rc"], 3)                       # 일정 0 — 메일이 있어도 일정 경로는 막힘
        self.assertIn("R-ONLINE", r2.result("cal.index")["reasons"])

    # ── M19 질의 시간 제한·예외 종류 ─────────────────────────────────────────────────────────────
    def test_m19_timeout_does_not_descend(self):
        r = self.run_idx(self.recent_fake(_query_error="timeout@0"), SEP)
        self.assertEqual(r.rc, 3)
        res = r.result("mail.index")
        self.assertEqual(res["reasons"], ["R-BUDGET"])
        self.assertEqual((res["counts"]["query_error"], res["counts"]["query_level"]), ("timeout", 0))
        self.assertEqual(r.records, [])
        self.assertIsNone(r.cursor)                                              # 커서를 옮기지 않는다(다음 실행이 다시)
        rc = self.run_idx(self.recent_fake(_query_error="timeout@0"), SEP, only="cal")
        self.assertNotIn("R-RECURINC", rc.result("cal.index")["reasons"])        # 시간 초과를 '반복 속성 거부'로 오인하지 않음

    def test_m19_column_rejection_descends_one_level(self):
        r = self.run_idx(self.recent_fake(_query_error="column@0"), SEP)
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.index")
        self.assertEqual((res["counts"]["query_level"], res["counts"]["fallback"], res["counts"]["query_error"]),
                         (1, False, "column"))
        self.assertTrue(all("conversation_id" not in x and x["to"][0]["name"] for x in r.records))

    def test_m19_unknown_errors_on_every_level(self):
        r = self.run_idx(self.recent_fake(_query_error="other@0,other@1,other@2"), SEP)
        self.assertEqual(r.rc, 3)
        res = r.result("mail.index")
        self.assertEqual(res["reasons"], ["R-TRANSPORT"])
        self.assertEqual(res["counts"]["query_error"], "other")

    def _ps_funcs(self, *names):
        text = self.clone.path("collect", SCRIPT).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        parts = []
        for ln in text.split("\n"):
            if re.match(r"^\$(COLUMN_HR|TIMEOUT_HR|QUERY_TIMEOUT_SEC) = ", ln):
                parts.append(ln)
        for n in names:
            m = re.search(r"\nfunction " + n + r"\b.*?\n\}\n", text, re.S)
            self.assertIsNotNone(m, n)
            parts.append(m.group(0))
        return "\n".join(parts)

    def _ps(self, code):
        # 스크립트 파일(UTF-8 BOM)로 돌린다 — `-Command -` 의 stdin 은 콘솔 코드 페이지로 읽혀 한글 주석이 다음 줄을 삼킨다
        type(self).n += 1
        p = self.dir / f"unit_{self.n}.ps1"
        p.write_bytes(b"\xef\xbb\xbf" + code.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
        cp = subprocess.run([ps_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)], capture_output=True,
                            timeout=120, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)
        return cp.stdout.decode("utf-8", "replace").strip().splitlines()

    def test_m19_invoke_query_sets_timeout_and_keeps_list(self):
        """실물 Invoke-Query(OLE DB) 계약: CommandTimeout 을 넣고, 1행이어도 목록을 돌려준다(PowerShell 이 풀어 해시표가 되면
        지평선 `$top[0]` 이 늘 $null 이었다 — 예전 실물 경로에서 R-HORIZON 이 한 번도 나지 않던 원인)."""
        fake_conn = r"""
$rd = [pscustomobject]@{ i = -1; FieldCount = 1 }
$rd | Add-Member ScriptMethod Read { $this.i++; return ($this.i -lt 1) }
$rd | Add-Member ScriptMethod GetValue { param($k) return [datetime]'2026-07-08 00:00:00' }
$rd | Add-Member ScriptMethod GetName { param($k) return 'System.ItemDate' }
$rd | Add-Member ScriptMethod Close { }
$cmd = [pscustomobject]@{ CommandText = ''; CommandTimeout = 30; rd = $rd }
$cmd | Add-Member ScriptMethod ExecuteReader { return $this.rd }
$conn = [pscustomobject]@{ cmd = $cmd }
$conn | Add-Member ScriptMethod CreateCommand { return $this.cmd }
"""
        out = self._ps(self._ps_funcs("Invoke-Query") + fake_conn +
                       "$r = Invoke-Query $conn 'SELECT x' 5 $QUERY_TIMEOUT_SEC\n"
                       "'{0}|{1}|{2}|{3}' -f $r.GetType().Name, $r.Count, ($r[0]['System.ItemDate'] -is [datetime]), $cmd.CommandTimeout\n")
        self.assertEqual(out[-1].split("|")[:3], ["List`1", "1", "True"], out)
        t = int(out[-1].split("|")[3])
        self.assertTrue(30 < t < 600, t)                                         # 기본 30초가 아니고 감시 상한(600초) 안

    def test_m19_error_classes_from_hresult(self):
        """개발 PC 실측(Search.CollatorDSO): 없는 속성 → OleDbException 0x80040E55(DB_E_NOCOLUMN), MethodInvocationException 에 싸여 옴."""
        code = self._ps_funcs("Get-QueryError") + r"""
function New-OleEx([int]$hr) {
    $ex = [Runtime.Serialization.FormatterServices]::GetUninitializedObject([Data.OleDb.OleDbException])
    [Exception].GetField('_HResult', [Reflection.BindingFlags]'NonPublic,Instance').SetValue($ex, $hr)
    return (New-Object System.Management.Automation.MethodInvocationException('x', $ex))
}
(Get-QueryError (New-OleEx (-2147217835)) 0.1 180).cls
(Get-QueryError (New-OleEx (-2147217900)) 0.1 180).cls
(Get-QueryError (New-OleEx (-2147217900)) 175.0 180).cls
(Get-QueryError (New-OleEx (-2147217871)) 1.0 180).cls
(Get-QueryError (New-OleEx (-2147217835)) 0.1 180).hr
"""
        self.assertEqual(self._ps(code)[-5:], ["column", "other", "timeout", "timeout", "0x80040E55"])

    # ── L9 리터럴 해석 ───────────────────────────────────────────────────────────────────────────
    def test_l9_literal_shift_detected_and_window_exact(self):
        """색인이 리터럴을 로컬 시각(+9시간)으로 해석한다고 가정한 가짜 SQL: 창 끝 메일을 잃지 않고, 창 밖 행은 내지 않으며 R-TZ."""
        rows = [mail(ME, "받은 편지함", "L9 창 끝", "2026-09-30 22:00"),
                mail(ME, "받은 편지함", "L9 창 시작", "2026-09-01 08:00"),
                mail(ME, "받은 편지함", "L9 하루 전", "2026-08-31 10:00"),
                mail(ME, "받은 편지함", "L9 여유 밖", "2026-08-30 20:00"),
                mail(ME, "보낸 편지함", "L9 보낸", "2026-09-10 10:00", sent=True)]
        r = self.run_idx({"mail": rows, "calendar": [], "_my_addrs": [ME], "_classic": True, "_literal_shift_min": 540}, SEP)
        self.assertEqual(r.rc, 0, r.err_text)
        subj = {x["subject"] for x in r.records}
        self.assertEqual(subj, {"L9 창 끝", "L9 창 시작", "L9 보낸"})
        cnt = r.result("mail.index")["counts"]
        self.assertIn("R-TZ", r.result("mail.index")["reasons"])
        self.assertGreaterEqual(cnt["out_of_range"], 1)
        self.assertGreaterEqual(cnt["literal_mismatch"], 1)
        r2 = self.run_idx({"mail": rows, "calendar": [], "_my_addrs": [ME], "_classic": True}, SEP)   # 해석이 맞으면 경고 없음
        self.assertNotIn("R-TZ", r2.result("mail.index")["reasons"])
        self.assertEqual({x["subject"] for x in r2.records}, {"L9 창 끝", "L9 창 시작", "L9 보낸"})


if __name__ == "__main__":
    unittest.main()
