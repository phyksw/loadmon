# -*- coding: utf-8 -*-
"""WP-11 정제 파이프 시험 — ``lm27_pipe.py`` / ``sanitize_stream.main``(P §3.5 · 계약 §8.2): 요약 줄(P §3.5 형 + cursor_saved),
종료 코드 0·2·3·5·6, 제어 줄(_meta·_cursor·_status)은 레코드가 아님, 커서는 0·2 일 때만(3·5·6 불변), route-by-kind
(P-T33 — ``--src-map`` 없으면 5), 키 없음(P-T29), 정상 대량(P-T4), 중단(P-T5 — 프로세스 강제 종료 포함, 복제 트리)."""
import gzip
import io
import json
import shutil
import subprocess
import time
import unittest
from unittest import mock

from lm27.paths import Paths
from lm27.privacy import keys as K
from lm27.privacy import records as R
from lm27.privacy import sanitize_stream as S
from lm27.privacy.rules import RULES_VERSION
from lm27.store import load_raw_cursor, read_store_since, store_files
from lm27.util import fsx
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp11 import helpers as H

CLOCK = "2026-10-05T03:00:00Z"
SUMMARY_KEYS = {"ok", "mode", "rows_in", "stored", "dropped", "errors", "rules_ver", "kid", "out_sha256", "cursor_saved"}


def jl(*objs) -> bytes:
    return b"".join((o if isinstance(o, bytes) else fsx.canon_bytes(o)) + b"\n" for o in objs)


class _Base(unittest.TestCase):
    agent = False

    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        if self.agent:                                         # 옆에 data\·lm27_cli.py 가 없는 사본 = 에이전트 모드
            shutil.rmtree(self.sb.root / "data")
            self.paths = Paths(self.sb.root, lad=self.sb.lad)
        else:
            (self.sb.root / "config").mkdir()
            shutil.copy(H.REGISTRY_JSON, self.sb.root / "config" / "settings_registry.json")
            self.paths = self.sb.paths
        p = mock.patch("lm27.privacy.context.os_display_names", return_value=["hongtest"])   # 실제 OS 이름 미조회
        p.start()
        self.addCleanup(p.stop)

    def run_pipe(self, argv, data: bytes = b"", stdin=None):
        out, err = io.StringIO(), io.StringIO()
        code = S.main(argv, stdin=stdin if stdin is not None else io.BytesIO(data), stdout=out, stderr=err,
                      paths=self.paths, clock=lambda: CLOCK)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1, "stdout 은 요약 1줄만")
        return code, json.loads(lines[0]), err.getvalue()

    def args(self, kind="pc_session", src="pc.sampler", *extra, mode="append"):
        return ["--kind", kind, "--src", src, "--pc", H.PC1, "--mode", mode, *extra]

    def store_rows(self, kind="pc_session", src="pc.sampler"):
        recs, _cur, _gap = read_store_since(self.paths, H.PC1, kind, src, None)
        return recs

    def audit(self):
        f = self.paths.privacy_audit_file("2026-10-05")
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.is_file() else []


class ProgramPipeTest(_Base):
    def test_ok_and_control_lines(self):
        data = jl({"_meta": {"my_addrs": [H.ME]}}, H.raw_sampler(), H.raw_sampler(ts_utc="2026-09-15T01:03:00Z"),
                  {"_status": {"state": "ok", "n": 2}}, {"_cursor": {"last_ts_utc": "2026-09-15T01:03:00Z"}}, {"_x": 1},
                  b"", b"\r")
        code, sm, err = self.run_pipe(self.args(), data)
        self.assertEqual(code, S.EXIT_OK)
        self.assertEqual(SUMMARY_KEYS | {"collector_status"}, set(sm))
        self.assertEqual((sm["ok"], sm["mode"], sm["rows_in"], sm["stored"], sm["dropped"], sm["errors"]),
                         (True, "program", 2, 2, {}, {}))
        self.assertEqual((sm["rules_ver"], sm["cursor_saved"], sm["collector_status"]), (RULES_VERSION, True,
                                                                                        {"state": "ok", "n": 2}))
        self.assertRegex(sm["kid"], r"^k[0-9a-f]{8}$")
        self.assertRegex(sm["out_sha256"], r"^[0-9a-f]{16}$")
        self.assertEqual(err, "")
        self.assertEqual(len(self.store_rows()), 2)
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {"pc.sampler": {"last_ts_utc": "2026-09-15T01:03:00Z"}})
        ev = self.audit()
        self.assertEqual([(e["path_id"], e["rows_in"], e["rows_out"]) for e in ev], [("pc.sampler", 2, 2)])
        self.assertEqual(ev[0]["out_sha256"][:16], sm["out_sha256"])
        f = store_files(self.paths, H.PC1, "pc_session", "pc.sampler")[0][1]
        self.assertTrue(f.name.endswith("20261005.jsonl.gz"))               # 쓰기(플러시) UTC 날짜

    def test_badlines_exit2_cursor_saved(self):
        data = jl(H.raw_sampler(), b"{not json", b"[1,2]", dict(H.raw_sampler(), _kind="mail"),
                  {"_cursor": 7}) + b"x" * (S.MAX_LINE + 10) + b"\n" + jl(H.raw_sampler(app_class="nope"))
        code, sm, err = self.run_pipe(self.args(), b"\xef\xbb\xbf" + data)
        self.assertEqual(code, S.EXIT_BADLINES)
        self.assertEqual((sm["ok"], sm["rows_in"], sm["stored"], sm["cursor_saved"]), (True, 6, 1, True))
        self.assertEqual(sm["dropped"], {"bad_raw": 4})
        self.assertEqual(sm["errors"], {"ColumnViolation": 1})
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {"pc.sampler": 7})
        self.assertNotIn("not json", err)

    def test_lone_surrogate_row_not_lost(self):
        """W1b 회귀: 원시 줄의 외톨이 서로게이트(JSON 이스케이프) — 행이 error 로 버려지고 커서만 진전하지 않는다."""
        line = json.dumps(H.raw_teams(body_text="최종 도면 공유 \ud83d", message_id="mS"), ensure_ascii=True).encode("ascii")
        code, sm, _err = self.run_pipe(self.args("teams", "teams.uia"), line + b"\n" + jl({"_cursor": {"last_ts_utc": H.TS}}))
        self.assertEqual((code, sm["stored"], sm["errors"], sm["cursor_saved"]), (S.EXIT_OK, 1, {}, True))
        (row,) = self.store_rows("teams", "teams.uia")
        self.assertIn("�", row["body_masked"])

    def test_T07_party_names_first_run_not_in_store(self):
        """W1b 회귀(T-07 · I1): 첫 수집(빈 사람 사전)에서 단톡방 참여자·작성자·보낸 사람 표시명이 store 바이트에 0건,
        주소 없는 팀즈 이름도 로컬 사람 사전(person_dir)에 이름 기반 키로 오른다."""
        names = ("이영희", "박민수", "최지훈")
        for i in range(2):
            raw = H.raw_teams(chat_title="이영희, 박민수, 최지훈", chat_type="group", chat_id="19:" + "d" * 32 + "@thread.v2",
                              participants=[{"name": n} for n in names], author_name="박민수",
                              body_text=f"최지훈 이영희 오늘 도면 공유했어요 {i}", message_id=f"mN{i}")
            code, sm, _err = self.run_pipe(self.args("teams", "teams.web"), jl(raw))
            self.assertEqual((code, sm["stored"]), (S.EXIT_OK, 1))
        mail = H.raw_mail(sender_addr="park.ms@corp.example", sender_name="박민수", subject="박민수 견적 검토 1차",
                          internet_message_id="<m9.p@corp.example>")
        self.assertEqual(self.run_pipe(self.args("mail", "mail.com"), jl(mail))[0], S.EXIT_OK)
        blob = self.sb.all_bytes()
        store = b"".join(gzip.decompress(p.read_bytes()) for p in self.paths.store_root().rglob("*.jsonl.gz"))
        self.assertGreater(len(store), 0)
        for n in names:
            self.assertNotIn(n.encode("utf-8"), store, n)
        pd = fsx.read_json(self.paths.local_only_file("person_dir.json"), default={}) or {}
        learned = {x for p in (pd.get("people") or {}).values() for x in p.get("names") or ()}
        self.assertLessEqual(set(names), learned)                           # 로컬 전용 사전(원장·번들 밖)에만
        self.assertTrue(blob)

    def test_args_exit5(self):
        save = {"pc.sampler": 1}
        from lm27.store import save_raw_cursor
        save_raw_cursor(self.paths, H.PC1, "pc.sampler", 1)
        cases = [["--route-by-kind", "--pc", H.PC1, "--mode", "append"],
                 ["--route-by-kind", "--kind", "mail", "--src-map", "mail=mail.com", "--pc", H.PC1],
                 ["--kind", "mail", "--src", "pc.sampler", "--pc", H.PC1, "--mode", "append"],
                 ["--kind", "mail", "--src", "mail.com", "--pc", "PC1", "--mode", "append"],
                 ["--kind", "mail", "--src", "mail.com", "--pc", H.PC1, "--mode", "new"],
                 ["--route-by-kind", "--src-map", "mail=mail.com", "--pc", H.PC1, "--out", str(self.sb.dir / "a.jsonl")],
                 ["--kind", "mail", "--src", "mail.com", "--pc", H.PC1, "--mode", "append", "--out",
                  str(self.sb.dir / "x" / "y" / "z.jsonl.gz")],
                 ["--kind", "mail", "--src", "mail.com", "--pc", H.PC1, "--bogus"],
                 ["--route-by-kind", "--src-map", "mail=cal.com", "--pc", H.PC1, "--mode", "append"]]
        for argv in cases:
            with self.subTest(argv=argv):
                code, sm, _err = self.run_pipe(argv, jl(H.raw_mail(), {"_cursor": 99}))
                self.assertEqual((code, sm["ok"], sm["stored"], sm["cursor_saved"]), (S.EXIT_ARGS, False, 0, False))
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), save)
        self.assertEqual(store_files(self.paths, H.PC1, "mail", "mail.com"), [])
        self.assertEqual(self.audit(), [])

    def test_internal_exit3(self):
        from lm27.store import save_raw_cursor
        save_raw_cursor(self.paths, H.PC1, "pc.sampler", "before")
        with mock.patch.object(S, "sanitize_record", side_effect=RuntimeError("boom 홍길동")):
            code, sm, err = self.run_pipe(self.args(), jl(H.raw_sampler(), {"_cursor": "after"}))
        self.assertEqual((code, sm["ok"], sm["cursor_saved"], sm["errors"]), (S.EXIT_INTERNAL, False, False,
                                                                              {"RuntimeError": 1}))
        self.assertNotIn("홍길동", err)
        self.assertIn("RuntimeError", err)
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {"pc.sampler": "before"})
        self.assertEqual(store_files(self.paths, H.PC1, "pc_session", "pc.sampler"), [])

    def test_T5_interrupted_input_exit3(self):
        """100번째 줄 뒤 입력이 끊기면(파이프 오류) 출력·멤버 미추가, 커서 불변."""
        class Broken(io.BytesIO):
            n = 0

            def readline(self, size=-1):
                Broken.n += 1
                if Broken.n > 100:
                    raise OSError("pipe broken")
                return super().readline(size)
        data = jl(*(H.raw_sampler(ts_utc=f"2026-09-15T{i // 60:02d}:{i % 60:02d}:00Z") for i in range(150)))
        code, sm, _err = self.run_pipe(self.args(), stdin=Broken(data))
        self.assertEqual((code, sm["stored"]), (S.EXIT_INTERNAL, 0))
        self.assertEqual(store_files(self.paths, H.PC1, "pc_session", "pc.sampler"), [])
        out = self.sb.dir / "new.jsonl.gz"
        Broken.n = 0
        code2, _sm, _ = self.run_pipe(self.args("pc_session", "pc.sampler", "--out", str(out), mode="new"),
                                      stdin=Broken(data))
        self.assertEqual(code2, S.EXIT_INTERNAL)
        self.assertFalse(out.exists())
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {})

    def test_cursor_last_msg_key_filled(self):
        m1 = H.raw_mail(internet_message_id="<a1@corp.example>", ts_utc="2026-09-15T01:00:00Z")
        m2 = H.raw_mail(internet_message_id="<a2@corp.example>", ts_utc="2026-09-15T02:00:00Z")
        cur = {"box": {"inbox": {"last_ts_utc": "2026-09-15T02:00:00Z", "last_msg_key": ""},
                       "sent": {"last_ts_utc": "2026-09-01T00:00:00Z", "last_msg_key": "m" + "0" * 24}}}
        code, sm, _ = self.run_pipe(self.args("mail", "mail.com"), jl({"_meta": {"my_addrs": [H.ME]}}, m1, m2,
                                                                      {"_cursor": cur}))
        self.assertEqual(code, 0)
        saved = load_raw_cursor(self.paths, H.PC1)["mail.com"]
        kr = K.load_keyring(self.paths.data(), None)                       # 파이프가 만든 폴더 키링
        self.assertEqual(saved["box"]["inbox"]["last_msg_key"], K.msg_key(kr, "mid:a2@corp.example"))
        self.assertEqual(saved["box"]["sent"]["last_msg_key"], "m" + "0" * 24)

    def test_T33_route_by_kind_new(self):
        out = str(self.sb.dir / "out" / "{kind}.jsonl.gz")
        data = jl(dict(H.raw_mail(), _kind="mail"), dict(H.raw_cal(), _kind="cal"), dict(H.raw_mail(
            internet_message_id="<b2@corp.example>"), _kind="mail"), dict(H.raw_sampler(), _kind="pc_session"),
            {"_cursor": {"mail.com": {"v": 1}, "cal.com": {"v": 2}, "pc.git": {"v": 3}}})
        code, sm, _ = self.run_pipe(["--route-by-kind", "--src-map", "mail=mail.com,cal=cal.com", "--pc", H.PC1,
                                     "--out", out], data)
        self.assertEqual(code, S.EXIT_BADLINES)                               # pc_session 줄은 지도 밖 → 형식 오류
        self.assertEqual(sm["by_kind"], {"cal": {"src": "cal.com", "stored": 1}, "mail": {"src": "mail.com", "stored": 2}})
        for kind, n in (("mail", 2), ("cal", 1)):
            rows = [json.loads(x) for x in gzip.decompress((self.sb.dir / "out" / f"{kind}.jsonl.gz").read_bytes())
                    .splitlines()]
            self.assertEqual(len(rows), n)
            for r in rows:
                self.assertEqual(r["kind"], kind)
                self.assertLessEqual(set(r), set(R.SCHEMAS[kind].columns))
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {"cal.com": {"v": 2}, "mail.com": {"v": 1}})
        self.assertEqual(len(self.audit()), 2)                                # kind 마다 1줄
        code5, _sm, _ = self.run_pipe(["--route-by-kind", "--src-map", "mail=mail.com", "--pc", H.PC1, "--out",
                                       str(self.sb.dir / "no_placeholder.jsonl.gz")], data)
        self.assertEqual(code5, S.EXIT_ARGS)

    def test_route_append_into_store(self):
        data = jl(dict(H.raw_mail(), _kind="mail"), dict(H.raw_cal(), _kind="cal"))
        code, sm, _ = self.run_pipe(["--route-by-kind", "--src-map", "mail=mail.com,cal=cal.com", "--pc", H.PC1,
                                     "--mode", "append"], data)
        self.assertEqual((code, sm["stored"]), (0, 2))
        self.assertEqual(len(self.store_rows("mail", "mail.com")), 1)
        self.assertEqual(len(self.store_rows("cal", "cal.com")), 1)
        good_out = str(self.paths.store_file(H.PC1, "mail", "mail.com", "2026-10-05"))
        code2, _, _ = self.run_pipe(self.args("mail", "mail.com", "--out", good_out), jl(H.raw_mail()))
        self.assertEqual(code2, 0)

    def test_T4_bulk_no_raw_values(self):
        """합성 메일 200건(카나리아 양성 문장을 제목·본문에) → 출력 1개, 허용 열만, 원값 0건."""
        cs = [c for c in canaries(groups=["pii"], weak=False) if c.sentence]
        recs = []
        for i in range(200):
            c = cs[i % len(cs)]
            recs.append(H.raw_mail(internet_message_id=f"<t4.{i}@corp.example>", subject=c.sentence,
                                   body_text=cs[(i + 7) % len(cs)].sentence, ts_utc=f"2026-09-{1 + i % 28:02d}T01:00:00Z"))
        out = self.sb.dir / "t4.jsonl.gz"
        code, sm, err = self.run_pipe(self.args("mail", "mail.com", "--out", str(out), mode="new"),
                                      jl({"_meta": {"my_addrs": [H.ME]}}, *recs))
        self.assertEqual(code, 0)
        self.assertEqual(sm["rows_in"], 200)
        self.assertEqual(sm["stored"] + sum(sm["dropped"].values()) + sum(sm["errors"].values()), 200)
        raw = gzip.decompress(out.read_bytes())
        for line in raw.splitlines():
            self.assertLessEqual(set(json.loads(line)), set(R.SCHEMAS["mail"].columns))
        self.assertEqual(find_canaries(raw, cs), [])
        self.assertEqual(find_canaries(self.paths.privacy_audit_file("2026-10-05").read_bytes(), cs), [])
        self.assertEqual(find_canaries(err.encode("utf-8"), cs), [])


class AgentPipeTest(_Base):
    agent = True

    def test_T29_no_key_exit6_cursor_unchanged(self):
        code, sm, _ = self.run_pipe(self.args(), jl(H.raw_sampler(fg_title="김철수 책임 보고서.docx - Word",
                                                                  fg_doc_name=None), {"_cursor": 1}))
        self.assertEqual((code, sm["mode"], sm["kid"], sm["stored"], sm["cursor_saved"]),
                         (S.EXIT_NOKEY, "agent", K.NO_KID, 1, False))
        row = self.store_rows()[0]
        self.assertEqual((row["flags"].get("no_key"), "doc_key" in row), (True, False))
        self.assertNotIn("[사람#", row["title_masked"])
        self.assertEqual(load_raw_cursor(self.paths, H.PC1), {})
        code2, sm2, _ = self.run_pipe(self.args("teams", "teams.uia"), jl(H.raw_teams()))
        self.assertEqual((code2, sm2["stored"], sm2["dropped"]), (S.EXIT_NOKEY, 0, {"no_key": 1}))
        ev = self.audit()
        self.assertEqual([e["stage"] for e in ev], ["agent", "agent"])
        self.assertEqual(ev[1]["dropped"], {"no_key": 1})

    def test_agent_with_subkeys_exit0(self):
        K.write_agent_subkeys(H.keyring(), self.paths.agent_dir(), None)
        code, sm, _ = self.run_pipe(self.args("teams", "teams.uia"), jl(H.raw_teams(), {"_cursor": {"t": 1}}))
        self.assertEqual((code, sm["mode"], sm["kid"], sm["stored"], sm["cursor_saved"]),
                         (0, "agent", H.keyring().kid, 1, True))
        self.assertEqual(self.audit()[0]["err"], {"cfg.ctxcache_missing": 1})   # 문맥 사본 없음은 감사에 남는다


class CloneSubprocessTest(CloneTestCase):
    """복제 트리에서 실제 ``lm27_pipe.py`` 를 동봉 파이썬으로 — 요약 1줄·저장·강제 종료 시 출력 없음(P-T5)."""

    def pipe(self, *args):
        return [self.clone.path("lm27_pipe.py"), *args]

    def test_run_and_kill(self):
        c = self.clone
        lad = c.lad / "LoadMonitor27"
        data = jl(H.raw_sampler(), {"_cursor": 1})
        cp = c.run_py(self.pipe("--kind", "pc_session", "--src", "pc.sampler", "--pc", H.PC1, "--mode", "append"),
                      input=data, flags=("-X", "utf8", "-I", "-B"), timeout=180)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace")[-500:])
        lines = cp.stdout.decode("utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        sm = json.loads(lines[0])
        self.assertEqual((sm["ok"], sm["mode"], sm["stored"], sm["cursor_saved"]), (True, "program", 1, True))
        p = Paths(c.root, lad=lad)
        self.assertEqual(len(store_files(p, H.PC1, "pc_session", "pc.sampler")), 1)
        self.assertEqual(load_raw_cursor(p, H.PC1), {"pc.sampler": 1})
        before = sorted(x.name for x in p.store_dir(H.PC1).rglob("*.gz"))
        before_bytes = [x.read_bytes() for x in sorted(p.store_dir(H.PC1).rglob("*.gz"))]
        proc = subprocess.Popen([str(c.python), "-X", "utf8", "-I", "-B",
                                 *map(str, self.pipe("--kind", "pc_session", "--src", "pc.sampler", "--pc", H.PC1,
                                                     "--mode", "append"))],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=c.env(),
                                cwd=str(c.temp), creationflags=0x08000000)
        for i in range(100):
            proc.stdin.write(jl(H.raw_sampler(ts_utc=f"2026-09-16T01:{i % 60:02d}:00Z")))
        proc.stdin.write(jl({"_cursor": 2}))
        proc.stdin.flush()
        time.sleep(0.5)
        proc.kill()                                                         # EOF 전 강제 종료
        proc.communicate(timeout=60)
        self.assertEqual(sorted(x.name for x in p.store_dir(H.PC1).rglob("*.gz")), before)
        self.assertEqual([x.read_bytes() for x in sorted(p.store_dir(H.PC1).rglob("*.gz"))], before_bytes)
        self.assertEqual(load_raw_cursor(p, H.PC1), {"pc.sampler": 1})
        cp5 = c.run_py(self.pipe("--route-by-kind", "--pc", H.PC1, "--mode", "append"), input=b"",
                       flags=("-X", "utf8", "-I", "-B"))
        self.assertEqual(cp5.returncode, S.EXIT_ARGS)


if __name__ == "__main__":
    unittest.main()
