# -*- coding: utf-8 -*-
"""WP-18 load — load_evidence(번들 로더 → G2 재정제 → 병합 → 파생 열) 를 %TEMP% 임시 번들에서 끝까지.

파생 열(subject_tokens = tokens_of · act·act_conf·act_source · presence_of · provenance·alias_keys) · G2(낮은 rules_ver 행만
다시 가림, id 그대로, 디스크 불변, 카나리아 0, 키 없음 모드 [사람]) · 소급 가림 오버레이의 단서 비우기(C11) · 방 성향
재계산(P §12.4)·사용자 지정 사적 방 · 수동 태깅 최우선(CT-18) · 코파일럿 답 덮어쓰기(X-090) · 팀즈 알림 메일(X-133) ·
T-11(멀티 PC·멀티 경로·UTC 클라우드PC) · 결정성(세그먼트 쓰기 순서 무관 — T-02) · 감사 1줄(건수·코드만) · 시간 코어 연결."""
import importlib.util
import json
import unittest
from datetime import date

from lm27.normalize import act as A
from lm27.normalize.load import DERIVED_COLUMNS, TOKEN_KINDS, load_evidence, load_report
from lm27.privacy import RULES_VERSION, tokens_of
from lm27.util import fsx
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.wp18 import rows as R

T = "2026-09-01T01:00:00Z"            # 09-01 10:00 KST
D0, D1 = "2026-09-01", "2026-09-30"


def canon(rows):
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


def mixed_rows():
    return [
        R.mail(T, msg="M1", subject="[과제:P-0001] 도면 검토 부탁드립니다. 금요일까지 회신 바랍니다"),
        R.mail(R.plus(T, minutes=50), msg="M2", box="sent", subject="RE: 검토 결과 공유드립니다", cues=("rep",)),
        R.teams(R.plus(T, minutes=5), body="넵 확인했습니다", author="self"),
        R.cal(R.plus(T, hours=4), R.plus(T, hours=5)),
        R.session(T), R.session(R.plus(T, minutes=1)),
        R.git(R.plus(T, hours=2)),
        R.manual("2026-09-01T15:00:00Z"),
    ]


class DerivedColumnsTest(R.SandboxCase):
    def test_columns_by_kind(self):
        self.sb.put(mixed_rows())
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        self.assertEqual(len(out), 8)
        for r in out:
            kind = r["kind"]
            if kind in TOKEN_KINDS:
                txt = next((r[c] for c in ("subject_masked", "body_masked", "msg_masked", "text_masked")
                            if isinstance(r.get(c), str) and r[c]), "")
                self.assertEqual(r["subject_tokens"], tokens_of(txt), kind)
            else:
                self.assertNotIn("subject_tokens", r, kind)
            if kind in ("mail", "teams"):
                self.assertIn(r["act"], A.ACTS)
                self.assertEqual(r["act_source"], "rule")
                self.assertTrue(0 <= r["act_conf"] <= 1)
            else:
                self.assertEqual(r["act"], "", "화행은 메시지에만 — 저장값 그대로")
                self.assertNotIn("act_source", r)
            if kind in ("mail", "cal", "teams"):
                self.assertTrue(r["provenance"] and r["alias_keys"])
        acts = {r["msg_key"]: r["act"] for r in out if r["kind"] in ("mail", "teams")}
        self.assertEqual(sorted(acts.values()), ["ack", "report", "request"])
        self.assertTrue(set(DERIVED_COLUMNS) >= {"subject_tokens", "act", "act_conf", "act_source"})
        ts = [(r["ts_utc"], r["kind"], r["id"]) for r in out]
        self.assertEqual(ts, sorted(ts))

    def test_period_and_kinds(self):
        rows = mixed_rows() + [R.mail("2026-10-02T01:00:00Z", msg="OCT")]
        self.sb.put(rows)
        cfg = self.sb.cfg()
        self.assertEqual(len(load_evidence(self.paths, cfg, D0, D1)), 8)
        self.assertEqual(len(load_evidence(self.paths, cfg, None, None)), 9)
        only = load_evidence(self.paths, cfg, date(2026, 9, 1), date(2026, 9, 1), kinds=("mail",))
        self.assertEqual({r["kind"] for r in only}, {"mail"})
        with self.assertRaises(ValueError):
            load_evidence(self.paths, cfg, D0, D1, kinds=("privacy_audit",))
        empty = R.Sandbox()
        self.addCleanup(empty.remove)
        self.assertEqual(load_evidence(empty.paths, cfg, D0, D1, audit=False), [], "번들 없음 = 빈 목록")

    def test_report(self):
        self.sb.put(mixed_rows())
        load_evidence(self.paths, self.sb.cfg(), D0, D1)
        rep = load_report()
        self.assertEqual(rep["rows_in"], 8)
        self.assertEqual(rep["rows_out"], 8)
        self.assertEqual(rep["kinds"]["pc_session"]["records"], 2)
        self.assertEqual(rep["act_rule"], 3)
        self.assertEqual((rep["d0"], rep["d1"]), (D0, D1))


class G2Test(R.SandboxCase):
    """P §10.5 — 적재 시 재정제: rules_ver 가 낮은 행만, 가림은 늘기만, id 그대로, 디스크 불변."""

    def setUp(self):
        super().setUp()
        cs = {c.cid: c for c in canaries()}
        self.ph, self.rrn, self.person = cs["c01.phone"], cs["c10.rrn"], cs["c52.person"]

    def test_old_rows_resanitized(self):
        old = R.mail(T, msg="old", subject="연락처 " + self.ph.sentence, rules_ver=R.OLD_RULES)
        tm = R.teams(R.plus(T, minutes=9), body="참고 " + self.rrn.sentence, rules_ver=R.OLD_RULES)
        cur = R.mail(R.plus(T, minutes=30), msg="cur", subject="이미 [전화] 가림")
        infos = self.sb.put([old, tm, cur])
        before = {i["file"]: (self.paths.pc_dir(R.PC1) / i["file"]).read_bytes() for i in infos}
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        blob = canon(out).encode("utf-8")
        self.assertEqual(find_canaries(blob), [])
        by_id = {r["id"]: r for r in out}
        self.assertIn(old["id"], by_id, "id 는 다시 계산하지 않는다")
        self.assertIn("[전화]", by_id[old["id"]]["subject_masked"])
        self.assertIn("[주민번호]", by_id[tm["id"]]["body_masked"])
        self.assertEqual({r["rules_ver"] for r in out}, {RULES_VERSION})
        self.assertEqual(by_id[cur["id"]]["subject_masked"], "이미 [전화] 가림")
        rep = load_report()
        self.assertEqual(rep["resanitized"], 2)
        self.assertEqual(rep["masked"], {"phone": 1, "rrn": 1})
        after = {i["file"]: (self.paths.pc_dir(R.PC1) / i["file"]).read_bytes() for i in infos}
        self.assertEqual(before, after, "세그먼트는 바꾸지 않는다(메모리 사본만)")

    def test_no_keyring_new_person_tags_plain(self):
        old = R.teams(T, body="[사람#0a1b2c]님 " + self.person.sentence, rules_ver=R.OLD_RULES)
        self.sb.put([old])
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        body = out[0]["body_masked"]
        self.assertTrue(body.startswith("[사람#0a1b2c]님 "), "있던 태그는 그대로")
        self.assertIn("[사람] ", body)
        self.assertEqual(body.count("[사람#"), 1)
        self.assertEqual(find_canaries(canon(out).encode("utf-8")), [])

    def test_injected_context_used(self):
        from lm27.privacy import SanitizeContext
        old = R.mail(T, msg="old", subject="연락처 " + self.ph.sentence + " " + self.person.sentence,
                     rules_ver=R.OLD_RULES)
        self.sb.put([old])
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1, sctx=SanitizeContext())
        self.assertIn("[전화]", out[0]["subject_masked"])
        self.assertNotIn("[사람#", out[0]["subject_masked"], "키 없는 문맥이면 새 사람 태그는 평문 토큰")
        self.assertFalse(self.paths.keyring().exists(), "적재는 키링을 만들지 않는다")
        keyed = SanitizeContext(key=bytes(range(32)))
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1, sctx=keyed)
        self.assertIn("[사람#", out[0]["subject_masked"])


class OverlayAndRoomTest(R.SandboxCase):
    def test_overlay_clears_cues(self):
        row = R.teams(T, room="RX", body="[과제:P-0001] 검토 부탁드립니다", cues=("req",))
        self.sb.put([row])
        fsx.atomic_write(self.paths.local_only_file("redact_overlay.json"),
                         fsx.canon_bytes({"chat": {R.chat("RX"): "2026-08-01T00:00:00Z"}, "msg": []}))
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        self.assertEqual((out[0]["body_masked"], out[0]["act_cues"]), ("", []))
        self.assertEqual(out[0]["act"], "info")
        self.assertEqual(load_report()["overlay_rows"], 1)

    def test_room_prior_private(self):
        rows = [R.teams(R.plus(T, minutes=i), room="PRIV", body=f"택배 왔어요 {i}", base_score=3, msg=f"p{i}")
                for i in range(9)]
        rows.append(R.teams(R.plus(T, minutes=20), room="PRIV", body="[과제:P-0001] 도면 결과 공유드립니다",
                            base_score=-6, msg="work"))
        rows.append(R.teams(R.plus(T, minutes=30), room="PRIV", body="내일 점심", base_score=0, msg="neutral"))
        rows += [R.teams(R.plus(T, minutes=40 + i), room="WORK", body=f"[과제:P-0001] 검토 {i}", base_score=-3,
                         msg=f"w{i}") for i in range(12)]
        self.sb.put(rows)
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        priv = [r for r in out if r["chat_key"] == R.chat("PRIV")]
        self.assertEqual(len(priv), 11)
        hidden = [r for r in priv if r["priv_class"] == "private"]
        self.assertEqual(len(hidden), 10, "강한 업무(≤ −4) 한 행만 남는다")
        for r in hidden:
            self.assertEqual(r["body_masked"], "")
            self.assertIn("room_private", r["priv_why"])
            self.assertTrue(r["flags"]["private"])
        self.assertTrue(all(r["priv_class"] == "work" for r in out if r["chat_key"] == R.chat("WORK")))
        self.assertEqual(load_report()["room_private"], 10)

    def test_user_private_chats(self):
        rows = [R.teams(R.plus(T, minutes=i), room="MINE", body=f"[과제:P-0001] 검토 {i}", base_score=-8,
                        msg=f"m{i}") for i in range(3)]
        self.sb.put(rows)
        fsx.atomic_write(self.paths.local_only_file("private_chats.json"), fsx.canon_bytes({"chats": [R.chat("MINE")]}))
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        self.assertEqual({r["priv_class"] for r in out}, {"private"})
        self.assertEqual({r["body_masked"] for r in out}, {""})


class ActSourceTest(R.SandboxCase):
    """X-090 · CT-18 — 규칙 < 코파일럿(by=ai·manual, conf h·m) < 수동 태깅."""

    def setUp(self):
        super().setUp()
        self.req = R.teams(T, body="[과제:P-0001] 도면 검토 부탁드립니다", msg="R1", room="A")
        self.q = R.teams(R.plus(T, minutes=3), body="시간 되시나요?", msg="Q1", room="B")
        self.sb.put([self.req, self.q])

    def ai_out(self, items):
        fsx.atomic_write(self.paths.ai_out("speech_act"), fsx.canon_bytes({"schema": 1, "stage": "speech_act",
                                                                           "items": items}))

    def acts(self):
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        return {r["msg_key"]: (r["act"], r["act_source"]) for r in out}

    def test_precedence(self):
        k1, k2 = self.req["msg_key"], self.q["msg_key"]
        self.assertEqual(self.acts()[k1], ("request", "rule"))
        self.ai_out({"msg:" + k1: {"ans": {"act": "info", "conf": "h"}, "by": "ai"},
                     "msg:" + k2: {"ans": {"act": "request", "conf": "l"}, "by": "ai"}})
        got = self.acts()
        self.assertEqual(got[k1], ("info", "ai"))
        self.assertEqual(got[k2][1], "rule", "conf l 은 덮지 않는다")
        A.save_tag(self.paths, k1, "report")
        got = self.acts()
        self.assertEqual(got[k1], ("report", "manual"), "수동 태깅이 최우선(CT-18)")
        rep = load_report()
        self.assertEqual((rep["act_manual"], rep["act_rule"]), (1, 1))
        raw = self.paths.local_only_file(A.TAG_FILE).read_bytes()
        self.assertNotIn("도면".encode(), raw, "태그 파일에 원문·정제문 없음")

    def test_apply_acts_without_reload(self):
        from lm27.normalize.load import apply_acts
        cfg = self.sb.cfg()
        rows = load_evidence(self.paths, cfg, D0, D1)
        k1 = self.req["msg_key"]
        self.ai_out({"msg:" + k1: {"ans": {"act": "ack", "conf": "m"}, "by": "manual"}})
        n = apply_acts(rows, self.paths, cfg)
        got = {r["msg_key"]: (r["act"], r["act_source"], r["act_conf"]) for r in rows}
        self.assertEqual(got[k1], ("ack", "ai", 0.75))
        self.assertEqual((n["act_ai"], n["act_rule"], n["act_manual"]), (1, 1, 0))

    def test_tag_found_through_alias_key(self):
        com = R.mail(R.plus(T, hours=1), msg="mid:<x@corp.example>", subject="[과제:P-0001] 시험 결과 송부드립니다")
        idx = R.mail(R.plus(T, hours=1, seconds=30), msg="index-fuzzy", src="mail.index",
                     subject="[과제:P-0001] 시험 결과 송부드립니다")
        self.sb.put([com, idx])
        A.save_tag(self.paths, idx["msg_key"], "request")           # 색인 키로 붙인 태그
        out = [r for r in load_evidence(self.paths, self.sb.cfg(), D0, D1) if r["kind"] == "mail"]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["msg_key"], com["msg_key"])
        self.assertEqual((out[0]["act"], out[0]["act_source"]), ("request", "manual"))


class TeamsNoticeTest(R.SandboxCase):
    def test_presence_marker(self):
        notice = R.mail(T, msg="N1", subject="Microsoft Teams 놓친 활동", sender=R.who("noreply"),
                        flags={"teams_notice": True})
        self.sb.put([notice, R.mail(R.plus(T, minutes=2), msg="N2")])
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        n = next(r for r in out if r["msg_key"] == notice["msg_key"])
        self.assertEqual((n["act"], n["presence_of"]), ("notice", "teams"))
        self.assertTrue(n["flags"]["teams_notice"])
        self.assertEqual(sum(1 for r in out if r.get("presence_of")), 1)
        self.assertEqual(load_report()["presence"], 1)


class T11BundleTest(R.SandboxCase):
    """T-11 — 번들(멀티 PC 세그먼트) 경유: 건수 보존·중복 0·UTC 클라우드PC 2배 없음."""

    def rows(self):
        out = []
        for i in range(6):
            ts = R.plus(T, hours=i)
            subj = f"[과제:P-0001] 진행 {i}"
            out += [R.mail(ts, msg=f"mid{i}", subject=subj, thr=f"T{i}", pc=R.PC1),
                    R.mail(ts, msg=f"mid{i}", subject=subj, thr=f"T{i}", pc=R.PC2),
                    R.mail(R.plus(ts, seconds=50), msg=f"idx{i}", subject=subj, thr=f"T{i}", src="mail.index"),
                    R.mail(ts, msg=f"mid{i}", subject=subj, thr=f"T{i}", src="mail.owa", pc=R.CLOUD, off="+00:00")]
        out.append(R.mail("2026-08-31T15:00:00Z", msg="owa-date", subject="[과제:P-0001] 진행 0", thr="T0",
                          src="mail.owa", pc=R.CLOUD, prec="date"))
        return out

    def test_count_preserved(self):
        self.sb.put(self.rows())
        out = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        self.assertEqual(len(out), 6)
        self.assertEqual(sum(len(r["provenance"]) for r in out), 24)
        rep = load_report()["merge"]
        self.assertEqual((rep["exact_merged"], rep["fuzzy_merged"], rep["date_absorbed"]), (12, 6, 1))

    def test_deterministic_regardless_of_write_order(self):
        rows = self.rows()
        self.sb.put(rows)
        a = load_evidence(self.paths, self.sb.cfg(), D0, D1)
        other = R.Sandbox()
        self.addCleanup(other.remove)
        for i, r in enumerate(reversed(rows)):         # 한 줄씩 거꾸로 — 세그먼트 수·쓰기 순서가 다르다
            other.put([r], created=R.plus("2026-10-05T09:00:00Z", seconds=i))
        b = load_evidence(other.paths, other.cfg(), D0, D1)
        self.assertEqual(canon(a), canon(b))


class AuditTest(R.SandboxCase):
    def test_one_line_codes_only(self):
        ph = {c.cid: c for c in canaries()}["c01.phone"]
        self.sb.put([R.mail(T, msg="old", subject="연락처 " + ph.sentence, rules_ver=R.OLD_RULES)] + mixed_rows())
        load_evidence(self.paths, self.sb.cfg(), D0, D1)
        lines = self.sb.audit_lines()
        self.assertEqual(len(lines), 1)
        ev = json.loads(lines[0])
        from lm27.privacy.audit import AUDIT_KEYS
        self.assertTrue(set(ev) <= set(AUDIT_KEYS))
        self.assertEqual((ev["ev"], ev["stage"], ev["path_id"]), ("load_resanitize", "load", "load"))
        self.assertEqual(ev["masked"], {"phone": 1})
        self.assertEqual(ev["err"].get("load.resanitized"), 1)
        self.assertEqual(find_canaries(b"\n".join(lines)), [])
        self.assertNotIn("도면".encode(), b"\n".join(lines))

    def test_audit_off_or_given(self):
        self.sb.put(mixed_rows())
        load_evidence(self.paths, self.sb.cfg(), D0, D1, audit=False)
        self.assertEqual(self.sb.audit_lines(), [])
        from lm27.privacy import AuditSink
        sink = AuditSink(lambda e: None, None, "load", "load")
        load_evidence(self.paths, self.sb.cfg(), D0, D1, audit=sink)
        self.assertEqual(self.sb.audit_lines(), [], "주어진 기록기는 호출자가 flush 한다")


class TimeCoreLinkTest(R.SandboxCase):
    """출력 행이 시간 코어 증거 정규화(lm27.time.evidence.normalize)·달력 build_days 입력으로 그대로 쓰인다."""

    def test_feeds_time_evidence(self):
        if importlib.util.find_spec("lm27.time.evidence") is None:
            self.skipTest("시간 코어(WP-19) 모듈 없음")
        from lm27.normalize.absence import leaves
        from lm27.time.evidence import normalize
        start = R.plus("2026-09-03T00:00:00Z", hours=-9)
        rows = mixed_rows() + [R.cal(start, R.plus(start, days=1), abs_hint="leave", busy="oof", subject="",
                                     flags={"all_day": True, "meeting_status": 0})]
        self.sb.put(rows)
        cfg = self.sb.cfg()
        out = load_evidence(self.paths, cfg, D0, D1)
        lv = leaves(out, None, off_min=int(cfg["time.tzOffsetMin"]))
        self.assertEqual(lv, {date(2026, 9, 3): "full"})
        ev, audit = normalize(out, {"d0": D0, "d1": "2026-09-03", "leaves": lv}, cfg, "2026-09-04T00:00:00+09:00")
        self.assertEqual({m.act for m in ev.msgs}, {"request", "report", "ack"})
        self.assertEqual(len(ev.meets), 2)
        self.assertTrue(any(m.category == "leave" for m in ev.meets))
        self.assertEqual(ev.leaves, {date(2026, 9, 3): "full"})


if __name__ == "__main__":
    unittest.main()
