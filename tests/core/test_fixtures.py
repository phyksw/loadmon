# -*- coding: utf-8 -*-
"""WP-05 시험 하네스·합성 자료 자체 시험 — 복제 트리(tree) · 카나리아(canary) · 합성 생성기(synth) · 주입 자료(inject).

실행: "<PY>" -X utf8 -B -m unittest discover -s tests\\core -t <루트>
"""
from __future__ import annotations

import gzip
import ipaddress
import json
import os
import re
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path

from tests.fixtures import canary, synth, tree
from tests.fixtures.canary import canaries, canary_ctx, find_canaries, find_canaries_in_tree, text_canaries
from tests.fixtures.synth import inject

FIX = Path(tree.__file__).resolve().parent
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")
PRIV_IP_RX = re.compile(r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?![\d.])")
RX = {
    "id": r"[0-9a-f]{16}", "pc_id": r"pcx?_[0-9a-f]{16}", "ts": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
    "off": r"[+-](?:0\d|1[0-4]):[0-5]\d", "rules_ver": r"\d{4}\.\d{1,2}\.\d{1,3}", "kid": r"k[0-9a-f]{8}",
    "src": r"(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|manual)", "w16": r"w[0-9a-f]{16}", "t16": r"t[0-9a-f]{16}",
    "h16": r"h[0-9a-f]{16}", "doc": r"[dr][0-9a-f]{16}", "f16": r"f[0-9a-f]{16}", "s16": r"s[0-9a-f]{16}",
    "g16": r"g[0-9a-f]{16}", "app_id": r"[a-z0-9_.:\-]{1,48}", "fg_exe": r"[a-z0-9_.\-]{1,64}\.exe",
    "ext": r"\.[0-9a-z]{1,5}",
}
SMOKE = '''import os
import sys
import unittest
from pathlib import Path

from tests.fixtures import tree


class Smoke(unittest.TestCase):
    def test_env(self):
        root = Path(os.environ["LM27T_CLONE"])
        self.assertEqual(tree.TREE_ROOT, root)
        self.assertEqual(tree.assert_test_root(root), root)
        self.assertTrue(os.environ["LOCALAPPDATA"].lower().startswith(str(root).lower()))
        self.assertTrue(sys.flags.dont_write_bytecode)
'''


def _example_domain(dom: str) -> bool:
    d = dom.lower()
    return d in ("example", "example.com") or d.endswith((".example", ".example.com"))


def _full(rx: str, v) -> bool:
    return isinstance(v, str) and re.fullmatch(rx, v) is not None


def _forbidden_words() -> list[str]:
    """CR-06 로컬 전용 금지어 목록(저장소 밖). 없으면 빈 목록 — 내용은 출력하지 않는다.
    복제 안(샌드박스 %LOCALAPPDATA%)에서는 tree.py 가 넘긴 위치(LM27T_FORBIDDEN_WORDS)를 읽는다(hook_check 와 같은 규칙)."""
    p = Path(tree.FORBIDDEN_LIST) if tree.FORBIDDEN_LIST else None
    if p is None or not p.is_file():
        return []
    words = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        w = line.strip()
        if w and not w.startswith("#"):
            words.append(w.lower())
    return words


# ── 복제 트리 ────────────────────────────────────────────────────────────────
class TreeTest(unittest.TestCase):
    def test_clone_layout_and_cleanup(self):
        with tree.make_clone() as c:
            root = c.root
            self.assertTrue(root.name.startswith(tree.CLONE_PREFIX))
            self.assertTrue((root / tree.CLONE_MARK).is_file())
            self.assertTrue((root / "tests" / "fixtures" / "tree.py").is_file())
            self.assertTrue((root / "tests" / "fixtures" / "synth" / "stored.py").is_file())
            if (tree.TREE_ROOT / "config" / "calendar.json").is_file():
                self.assertTrue((root / "config" / "calendar.json").is_file())
            self.assertFalse((root / "config" / "config.json").exists())
            self.assertFalse((root / "python").exists())            # 동봉 파이썬은 복제하지 않는다
            self.assertFalse(any(root.rglob("__pycache__")))
            for rel in (*tree.REPO_FILES, "docs/CONTRACT.md"):        # 저장소 설정·계약 문서(관문 시험 대상)도 복제
                if (tree.TREE_ROOT / rel).is_file():
                    self.assertTrue((root / rel).is_file(), rel)
            self.assertFalse((root / ".claude" / "settings.local.json").exists())
            self.assertFalse(list(c.lad.rglob("forbidden_words.txt")))  # 금지어 목록은 복사하지 않는다(위치만 env)
            if tree.FORBIDDEN_LIST:
                self.assertEqual(c.env()["LM27T_FORBIDDEN_WORDS"], tree.FORBIDDEN_LIST)
                self.assertFalse(tree.FORBIDDEN_LIST.lower().startswith(str(root).lower()))
            self.assertTrue(c.python.is_file())
            self.assertEqual(c.python.parent, tree.python_home())
            self.assertEqual(tree.assert_test_root(root), root)
            env = c.env(LM_INDEX_FAKE="x.json")
            self.assertEqual(env["LM_INDEX_FAKE"], "x.json")
            self.assertTrue(env["LOCALAPPDATA"].startswith(str(root)))
            self.assertNotIn("LM_OWA_FAKE", c.env())
            with c.patched_environ(LM_NO_BROWSER=1):
                self.assertEqual(os.environ["LM_NO_BROWSER"], "1")
                self.assertTrue(os.environ["LOCALAPPDATA"].startswith(str(root)))
            self.assertNotEqual(os.environ.get("LOCALAPPDATA", ""), str(c.lad))
        self.assertFalse(root.exists())

    def test_assert_test_root_rejects_real_paths(self):
        for bad in (tree.SOURCE_ROOT, tree.SOURCE_ROOT / "tests", Path(tempfile.gettempdir())):
            with self.assertRaises(AssertionError):
                tree.assert_test_root(bad)
        with tempfile.TemporaryDirectory(prefix="notclone_") as d, self.assertRaises(AssertionError):
            tree.assert_test_root(d)
        with self.assertRaises(AssertionError):
            tree.guard_write(tree.SOURCE_ROOT / "x.json")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tree.guard_write(Path(d) / "a.json"), (Path(d) / "a.json").resolve())

    def test_clone_runs_bundled_python(self):
        with tree.make_clone() as c:
            smoke = c.path("tests", "_smoke")
            smoke.mkdir()
            (smoke / "__init__.py").write_bytes(b"")
            (smoke / "test_smoke.py").write_bytes(SMOKE.encode("utf-8"))
            cp = c.run_unittest("_smoke", timeout=300)
            self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace")[-3000:])
            areas = tree.area_dirs(c.root)
            self.assertIn("core", areas)
            self.assertNotIn("_smoke", areas)                         # 밑줄 시작 폴더는 영역이 아니다
            self.assertNotIn("fixtures", areas)


class CleanupTest(unittest.TestCase):
    """W1 통합 창 잔여물 회귀: 지우기는 긴 경로·읽기 전용·잠깐 잠긴 파일을 처리하고, make 의 청소는 오래되고 주인이 끝났고
    아무도 쓰지 않는 lm27t_* 만 지운다(재부팅 전 %TEMP% 에 복제 136개가 남았던 결함)."""

    def _base(self) -> Path:
        b = Path(tempfile.mkdtemp(prefix="lm27t_cleanup_", dir=str(tree._TMP_BASE)))
        self.addCleanup(tree._rmtree, b)
        return b

    def test_rmtree_long_path_readonly_and_briefly_locked(self):
        import stat
        import threading
        b = self._base()
        deep = b
        for i in range(18):                                   # 300자 넘는 경로(MAX_PATH 260 초과)
            deep = deep / f"폴더_{i:02d}_가나다라마바사아자차"
        os.makedirs(tree.long_path(deep))
        self.assertGreater(len(str(deep)), 300)
        ro = tree.long_path(deep / "읽기전용.txt")
        with open(ro, "w", encoding="utf-8") as f:
            f.write("x")
        os.chmod(ro, stat.S_IREAD)
        held = open(tree.long_path(b / "잠김.txt"), "w", encoding="utf-8")   # noqa: SIM115 — 0.6초 뒤 닫는다
        t = threading.Timer(0.6, held.close)
        t.start()
        self.addCleanup(t.cancel)
        self.addCleanup(held.close)
        self.assertTrue(tree._rmtree(b))
        self.assertFalse(os.path.lexists(tree.long_path(b)))

    def test_sweep_only_old_ownerless_unused(self):
        import subprocess
        import sys
        b = self._base()
        dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True,
                              check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        dead_pid = int(dead.stdout.strip())
        old = time.time() - 2 * tree.STALE_AGE_S

        def mk(name, owner=None, age=old):
            d = b / name
            (d / "tests").mkdir(parents=True)
            (d / "tests" / "a.py").write_text("x", encoding="utf-8")
            if owner is not None:
                (d / tree.CLONE_MARK).write_text(f"src=x\nowner={owner}\n", encoding="utf-8")
                os.utime(d / tree.CLONE_MARK, (age, age))
            os.utime(d, (age, age))
            return d

        gone_old = mk("lm27t_dead", dead_pid)
        alive = mk("lm27t_alive", os.getpid())
        fresh = mk("lm27t_fresh", dead_pid, age=time.time())
        bare = mk("lm27t_bare")                                # 표지 없는 시험 임시 폴더(오래됨·아무도 안 씀)
        busy = mk("lm27t_busy")
        fh = open(busy / "tests" / "a.py", encoding="utf-8")   # noqa: SIM115 — 쓰는 중(이름 바꾸기 거부)
        self.addCleanup(fh.close)
        other = mk("notclone_old")
        gone = tree.sweep_stale(b)
        self.assertEqual(sorted(p.name for p in gone), ["lm27t_bare", "lm27t_dead"])
        self.assertFalse(gone_old.exists())
        self.assertFalse(bare.exists())
        self.assertFalse((b / "lm27t_dead.sweep").exists())
        for keep in (alive, fresh, busy, other):
            self.assertTrue(keep.is_dir(), keep.name)
        fh.close()
        os.utime(busy, (old, old))
        self.assertEqual([p.name for p in tree.sweep_stale(b)], ["lm27t_busy"])   # 다 쓰고 나면 다음 청소가 지운다
        with self.assertRaises(AssertionError):
            tree.sweep_stale(tree.SOURCE_ROOT)                 # %TEMP% 밖은 청소하지 않는다

    def test_mark_records_owner_and_cli_make_uses_parent(self):
        with tree.make_clone() as c:
            self.assertEqual(tree._mark_owner(c.root), os.getpid())
        self.assertTrue(tree._pid_alive(os.getpid()))
        self.assertFalse(tree._pid_alive(0))


class LeakHelperTest(unittest.TestCase):
    """누수 관문 도우미(tests\\fixtures\\leak.py) 자체 시험 — 일부러 새는 반복은 잡고, 새지 않는 반복은 통과시킨다."""

    def test_detects_memory_and_thread_growth(self):
        import threading

        from tests.fixtures import leak
        keep = []
        with self.assertRaises(AssertionError):
            leak.assert_bounded(self, lambda i: keep.append(bytearray(20000)), warm=2, n=20)
        keep.clear()
        stop = threading.Event()
        self.addCleanup(stop.set)
        with self.assertRaises(AssertionError):
            leak.assert_bounded(self, lambda i: threading.Thread(target=stop.wait, daemon=True).start(), warm=1, n=3)
        stop.set()
        leak.assert_bounded(self, lambda i: bytearray(20000), warm=2, n=20)
        self.assertGreater(leak.handle_count(), 0)
        self.assertEqual(leak.child_pids(), set())
        self.assertGreaterEqual(leak.temp_entries(), 0)
        self.assertLess(tree.best_of(lambda: None, n=3), 1.0)


class CloneCaseTest(tree.CloneTestCase):
    def test_class_clone(self):
        self.assertTrue(self.clone.path("tests", "fixtures", "canary.py").is_file())
        self.assertEqual(tree.assert_test_root(self.clone.root), self.clone.root)


# ── 카나리아 ────────────────────────────────────────────────────────────────
class CanaryTest(unittest.TestCase):
    def test_formats_cover_u03_and_t19(self):
        cs = canaries()
        cats = {c.cat for c in cs}
        need = {"phone", "rrn", "frn", "card", "brn", "passport", "license", "account", "email_ext", "email_int",
                "email_cust", "ip_private", "ip_private_b", "ip_private_c", "ip_public", "ipv6", "url", "path_win",
                "path_unc", "money_eok", "rate", "company", "birth", "person", "person_mention", "peer_name",
                "customer", "project", "person_dict", "self_name", "hostname", "winuser", "machine_guid",
                "who_key", "pc_id", "kid"} | {f"key_{p}" for p in "mehtdrfsg"}
        self.assertEqual(need - cats, set())
        refs = {c.ref for c in cs}
        want_refs = {f"P{i:02d}" for i in range(1, 61)} - {"P36"}      # P36('단가: 850')은 너무 짧아 바이트 카나리아 불가
        self.assertEqual(want_refs - refs, set())
        self.assertIn("U03", refs)
        self.assertEqual(len({c.cid for c in cs}), len(cs))
        self.assertEqual({c.group for c in cs}, set(canary.GROUPS))
        self.assertTrue(all(c.slot in canary.SLOTS for c in cs))
        self.assertTrue(all(c.value in c.sentence for c in cs if c.sentence))

    def test_deterministic_and_distinct_from_placeholders(self):
        self.assertEqual(canaries(), canaries(0))
        self.assertNotEqual([c.value for c in canaries(1)], [c.value for c in canaries(0)])
        P = synth.default_persona()
        names = {p.name for p in (P.me, *P.peers)}
        for c in canaries():
            if c.slot == "name":
                self.assertNotIn(c.value, names)
                self.assertNotIn("홍길동", c.value)
                self.assertNotIn("김철수", c.value)
        self.assertEqual(canaries(groups=("key",)), tuple(c for c in canaries() if c.group == "key"))
        self.assertFalse(any(c.weak for c in canaries(weak=False)))
        with self.assertRaises(ValueError):
            canaries(groups=("nope",))

    def test_checksums_and_ranges(self):
        self.assertTrue(canary.luhn_ok("4111-1111-1111-1111"))
        self.assertFalse(canary.luhn_ok("4111-1111-1111-1112"))
        self.assertTrue(canary.brn_ok("220-81-62517"))
        self.assertTrue(canary.rrn_ok("8501011234566"))
        for c in canaries():
            if c.cat in ("rrn", "rrn_digits", "rrn_plain", "file_rrn", "frn"):
                self.assertTrue(canary.rrn_ok(c.value), c.cid)
            if c.cat in ("card", "card_space", "card_amex"):
                self.assertTrue(canary.luhn_ok(c.value), c.cid)
            if c.cat in ("brn", "file_brn"):
                self.assertTrue(canary.brn_ok(c.value), c.cid)
            if c.cat in ("ip_private", "ip_private_b", "ip_private_c"):
                self.assertTrue(ipaddress.ip_address(c.value).is_private, c.cid)
            if c.cat == "email_ext":
                self.assertFalse(_example_domain(c.value.rsplit("@", 1)[1]), c.cid)   # 비예시 도메인(런타임 조립)

    def test_find_forms(self):
        for c in canaries(weak=True):
            for blob in (c.value.encode("utf-8"),
                         json.dumps({"x": c.value}).encode("ascii"),
                         json.dumps({"x": c.value}, ensure_ascii=False).encode("utf-8"),
                         c.value.encode("utf-16-le")):
                self.assertEqual(find_canaries(b"pre " + blob + b" post", [c]), [c.cid], c.cid)
            gz = gzip.compress(b"a\n" + c.value.encode("utf-8") + b"\n") + gzip.compress(b"tail\n")
            self.assertEqual(find_canaries(gz, [c]), [c.cid], c.cid)
        self.assertEqual(find_canaries(b"nothing here"), [])
        hx = next(c for c in canaries(groups=("key",)) if c.cat == "who_key")
        self.assertEqual(find_canaries(b"x" + hx.value.encode() + b"0", [hx]), [])     # 더 긴 16진 속 부분 일치는 아님

    def test_find_korean_windows_encodings(self):
        """한국어 Windows 의 기본 인코딩(CP949 — PS 5.1 Set-Content·cmd 리디렉션·encoding 없는 open)과 UTF-16BE 로
        새어도 찾는다. 이 형태를 못 찾으면 T-07 누출 시험이 거짓으로 통과한다."""
        ko = [c for c in canaries(weak=False) if not c.value.isascii()]
        self.assertGreaterEqual(len(ko), 10)
        for c in ko:
            for enc in ("cp949", "utf-16-be", "utf-16-le", "utf-8"):
                try:
                    raw = c.value.encode(enc)
                except UnicodeEncodeError:
                    continue
                with self.subTest(cid=c.cid, enc=enc):
                    self.assertEqual(find_canaries(b"x " + raw + b" y", [c]), [c.cid])
        self.assertEqual(find_canaries("합성 문장 홍길동 과제A".encode("cp949"), ko), [])

    def test_find_gzip_with_plain_tail_or_prefix(self):
        for c in canaries(weak=False)[:20]:
            v = c.value.encode("utf-8")
            with self.subTest(cid=c.cid):
                tail = gzip.compress(b"clean\n") + b"\n" + v + b"\n"                 # gzip 멤버 뒤 평문 꼬리
                self.assertEqual(find_canaries(tail, [c]), [c.cid])
                prefix = b"HEADER\n" + gzip.compress(b"a\n" + v + b"\n")             # gzip 앞에 머리말
                self.assertEqual(find_canaries(prefix, [c]), [c.cid])

    def test_ctx(self):
        ctx = canary_ctx()
        by = {c.cat: c.value for c in canaries()}
        self.assertEqual(ctx["customers"][0]["names"], [by["customer"]])
        self.assertEqual(ctx["projects"][0]["codenames"], [by["project"]])
        self.assertEqual(ctx["self_names"], [by["self_name"]])
        self.assertIn(by["person_dict"], ctx["persons"])
        self.assertIn(by["hostname"], ctx["canaries"])
        self.assertIn(by["machine_guid"].replace("-", ""), ctx["canaries"])

    def test_no_false_positive_on_synth_outputs(self):
        plan = synth.plan_month(2026, 9)
        blob = b"".join(inject.ndjson(v) for v in synth.raw_all(plan).values())
        blob += inject.canon_bytes(synth.stored_rows(plan))
        self.assertEqual(find_canaries(blob), [])

    def test_planted_raw_found_and_tree_scan(self):
        cs = canaries()
        plan = synth.plan_month(2026, 9)
        raw = synth.raw_all(plan, canaries=cs)
        blob = b"".join(inject.ndjson(v) for v in raw.values())
        found = set(find_canaries(blob, cs))
        self.assertEqual({c.cid for c in text_canaries(cs)} - found, set())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "seg").mkdir()
            (p / "seg" / "a.jsonl.gz").write_bytes(gzip.compress(inject.ndjson(raw["mail"])))
            (p / "clean.json").write_bytes(inject.canon_bytes(synth.stored_rows(plan, kinds=("cal",))))
            hits = find_canaries_in_tree(p, cs)
            self.assertEqual(sorted(hits), ["seg/a.jsonl.gz"])
            self.assertTrue(hits["seg/a.jsonl.gz"])

    def test_runtime_values_not_forbidden_words(self):
        """런타임에 조립하는 값(카나리아 이름·식별자)이 로컬 금지어(실명·코드네임)와 겹치지 않는다. 저장소 텍스트는 L-26 이 본다."""
        words = _forbidden_words()
        if not words:
            self.skipTest("로컬 금지어 목록 없음(CR-06) — 개발 PC 에서만 검사")
        toks: set[str] = set()
        hangul: list[str] = []
        for seed in (0, 1):
            for c in canaries(seed):
                for t in re.findall(r"[0-9a-z]+|[가-힣]+", c.value.lower()):
                    toks.add(t)
                    if not t.isascii():
                        hangul.append(t)
        n = 0
        for w in words:
            if w in toks or (not w.isascii() and len(w) >= 2 and any(w in h for h in hangul)):
                n += 1
        self.assertEqual(n, 0, f"런타임 조립 값과 겹치는 금지어 {n}개(내용은 출력하지 않음)")


# ── 페르소나·키 ──────────────────────────────────────────────────────────────
class PersonaTest(unittest.TestCase):
    def test_placeholders_and_ids(self):
        P = synth.default_persona()
        self.assertEqual(P.me.name, "홍길동")
        self.assertIn("김철수", [p.name for p in P.peers])
        self.assertEqual([p.codename for p in P.projects], [f"과제{x}" for x in "ABCDEF"])
        self.assertEqual({(o.oid, o.name) for o in P.orgs}, {("C01", "고객사A"), ("V01", "협력사")})
        for p in (P.me, *P.peers):
            self.assertTrue(_example_domain(p.addr.rsplit("@", 1)[1]), p.pid)
        for pc in P.pcs:
            self.assertTrue(_full(RX["pc_id"], pc.pc_id))
            self.assertEqual(pc.pc_id, synth.persona.pc_id_of(pc.machine_guid))
            self.assertTrue(_full(r"[0-9a-f]{32}", pc.install_id))
        self.assertEqual(P.pc("CLOUD").offset_min, 0)
        self.assertTrue(_full(r"p_[0-9a-f]{12}", P.person_key))
        self.assertIs(synth.default_persona(), P)
        self.assertNotEqual(synth.default_persona(1).pcs[0].pc_id, P.pcs[0].pc_id)

    def test_keys_and_doc_fam(self):
        k = synth.synth_keys()
        P = synth.default_persona()
        self.assertTrue(_full(RX["kid"], k.kid))
        self.assertTrue(_full(RX["w16"], k.who(P.peers[0])))
        self.assertEqual(k.who(P.peers[0]), synth.synth_keys(0).who(P.peers[0]))
        self.assertNotEqual(k.who(P.peers[0]), synth.synth_keys(1).who(P.peers[0]))
        self.assertEqual(k.doc("회로도_과제A_v3.xlsx"), k.doc("회로도_과제A.docx"))
        cases = {"보고서_최종.pptx": "보고서", "v2.docx": "v2", "photocopy.pdf": "photocopy", "보고서 (1).pptx": "보고서",
                 "2026 사업계획 v2 최종.pptx": "2026_사업계획", "과제A_열해석_v3.wbpj": "과제a_열해석"}
        from lm27.privacy.keys import doc_fam as real_doc_fam
        cases |= {"보고서 - 복사본.pptx": "보고서", "주간보고_20261005.xlsx": "주간보고_20261005",   # C16 · P §18.2 D03·D05·D07
                  "C:\\Users\\hong\\Documents\\2026 사업계획 v2 최종.pptx": "2026_사업계획"}
        for name, fam in cases.items():
            self.assertEqual(synth.doc_fam(name), fam, name)
            self.assertEqual(real_doc_fam(name), fam, name)                  # 합성 가짜 = 실물(계약 §4.3 · C16)
        self.assertEqual(P.mask("회로도_과제A_v3.xlsx", k), ("회로도_[과제:P-0001]_v3.xlsx", {"project": 1}))
        raw, masked, san = P.render(("@", ("person", "self"), " ", ("proj", 2), " 검토 ", ("org", "C01")), k)
        self.assertEqual(raw, "@홍길동 과제C 검토 고객사A")
        self.assertEqual(masked, "@[나] [과제:P-0003] 검토 [고객사:C01]")
        self.assertEqual(san, {"self": 1, "project": 1, "customer": 1})
        ctx = P.ctx_dict(k)
        self.assertEqual(ctx["self_names"], ["홍길동"])
        self.assertEqual(ctx["projects"][0], {"id": "P-0001", "codenames": ["과제A"]})


# ── 원시 레코드 ──────────────────────────────────────────────────────────────
class RawTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = synth.plan_month(2026, 9)

    def test_eight_kinds_with_raw_names(self):
        self.assertEqual(len(synth.KINDS), 8)
        for kind in synth.KINDS:
            recs = synth.raw_records(kind, self.plan)
            self.assertTrue(recs, kind)
            for r in recs:
                self.assertLessEqual(set(r), synth.RAW_FIELDS[kind], kind)
                self.assertNotIn("_kind", r)

    def test_every_route_id(self):
        n = 0
        for kind, srcs in synth.SRCS_BY_KIND.items():
            for src in srcs:
                recs = synth.raw_records(kind, self.plan, src=src)
                self.assertTrue(recs, src)
                for r in recs:
                    self.assertLessEqual(set(r), synth.RAW_FIELDS[kind], src)
                n += 1
        self.assertEqual(n, 21)                                    # 계약 §6.5 경로 ID 21종
        owa = synth.raw_records("mail", self.plan, src="mail.owa")
        self.assertEqual({r["ts_precision"] for r in owa}, {"date", "minute"})
        self.assertTrue(all(r["sender_addr"] is None for r in owa))
        web = synth.raw_records("teams", self.plan, src="teams.web")
        self.assertTrue(all(r["message_id"] and r["ts_precision"] == "exact" for r in web))
        uia = synth.raw_records("teams", self.plan, src="teams.uia")
        self.assertTrue(all(r["message_id"] is None and r["author_addr"] is None for r in uia))
        ev = synth.raw_records("pc_session", self.plan, src="pc.events")
        self.assertTrue(all("fg_title" not in r and "user" not in r and "message" not in r for r in ev))

    def test_same_seed_same_bytes(self):
        a = inject.canon_bytes(synth.raw_all(synth.plan_month(2026, 9, seed=7)))
        b = inject.canon_bytes(synth.raw_all(synth.plan_month(2026, 9, seed=7)))
        c = inject.canon_bytes(synth.raw_all(synth.plan_month(2026, 9, seed=8)))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_no_real_domain_or_private_ip(self):
        blob = inject.canon_bytes(synth.raw_all(self.plan)).decode("utf-8")
        blob += inject.canon_bytes(synth.stored_rows(self.plan)).decode("utf-8")
        blob += json.dumps([inject.index_fake(self.plan), inject.owa_fake(self.plan), inject.teamsweb_fake(self.plan)],
                           ensure_ascii=False)
        blob += inject.teams_rawfile(self.plan) + inject.events_csv(self.plan) + inject.mru_reg(self.plan)
        doms = {m.group(1) for m in EMAIL_RX.finditer(blob)}
        self.assertTrue(doms)
        self.assertEqual({d for d in doms if not _example_domain(d)}, set())
        self.assertIsNone(PRIV_IP_RX.search(blob))
        self.assertIn("홍길동", blob)
        self.assertIn("과제A", blob)

    def test_multi_pc_plan(self):
        plan = synth.plan_month(2026, 10, multi_pc=True)
        pcs = {ev.pc for ev in plan.ticks}
        self.assertEqual(pcs, {"PC1", "PC2"})
        rows = synth.stored_rows(plan, kinds=("pc_session",))
        self.assertEqual(len({r["pc_id"] for r in rows}), 2)


# ── 저장 행 ─────────────────────────────────────────────────────────────────
class StoredTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = synth.plan_month(2026, 9)
        cls.rows = synth.stored_rows(cls.plan)

    def test_columns_flags_formats(self):
        seen = set()
        for r in self.rows:
            k = r["kind"]
            seen.add(k)
            self.assertLessEqual(set(r), synth.STORED_COLUMNS[k], k)
            self.assertLessEqual(set(r.get("flags") or {}), synth.FLAG_KEYS[k], k)
            self.assertEqual(r["act"], "")
            self.assertTrue(_full(RX["id"], r["id"]))
            self.assertTrue(_full(RX["pc_id"], r["pc_id"]))
            self.assertTrue(_full(RX["ts"], r["ts_utc"]) and _full(RX["ts"], r["observed_at"]))
            self.assertTrue(_full(RX["off"], r["ts_local_offset"]))
            self.assertIn(r["ts_precision"], ("exact", "minute", "date", "summary", "unknown"))
            self.assertTrue(_full(RX["rules_ver"], r["rules_ver"]) and _full(RX["kid"], r["kid"]))
            self.assertTrue(_full(RX["src"], r["src"]) and r["src"] in synth.SRCS_BY_KIND[k])
            self.assertIn(r["priv_class"], ("work", "unknown", "media", "private", "social"))
            self.assertTrue(0.0 <= r["confidence"] <= 1.0)
            if r.get("ts_end") is not None:
                self.assertTrue(_full(RX["ts"], r["ts_end"]) and r["ts_end"] >= r["ts_utc"])
            for w in r.get("counterpart_keys") or []:
                self.assertTrue(_full(RX["w16"], w))
            if r.get("thread_key") is not None:
                self.assertTrue(_full(RX["t16"], r["thread_key"]))
            if r.get("doc_key") is not None:
                self.assertTrue(_full(RX["doc"], r["doc_key"]))
            if r.get("app_id") is not None:
                self.assertTrue(_full(RX["app_id"], r["app_id"]))
            if k in ("mail", "teams"):
                self.assertTrue(_full(r"m[0-9a-f]{24}", r["msg_key"]))
            if k == "cal":
                self.assertTrue(_full(r"e[0-9a-f]{24}", r["msg_key"]) and r["ts_end"])
            if k == "teams":
                self.assertTrue(_full(RX["h16"], r["chat_key"]) and r["chat_type"] in ("1:1", "group", "channel"))
                self.assertLessEqual(len(r["body_masked"]), 300)
                if r["chat_type"] == "1:1":
                    self.assertIsNone(r["chat_title_masked"])
            if k == "mail":
                self.assertIn(r["sender_label"], ("사내", "고객사:C01", "협력사:V01"))
                for e in r["attach_exts"]:
                    self.assertTrue(_full(RX["ext"], e))
            if k == "pc_session" and r["src"] == "pc.sampler":
                self.assertTrue(_full(RX["fg_exe"], r["fg_exe"]))
                self.assertIn(r["layer"], ("L2", "L3"))
            if k == "pc_session" and r["src"] == "pc.events":
                self.assertIn(r["layer"], ("L0", "L1"))
            if k == "pc_file":
                self.assertTrue(_full(RX["f16"], r["path_key"]) and all(_full(RX["s16"], s) for s in r["dir_keys"]))
            if k == "pc_git":
                self.assertTrue(_full(RX["g16"], r["commit_key"]) and r["doc_key"].startswith("r"))
        self.assertEqual(seen, set(synth.KINDS))

    def test_sorted_unique_and_counts(self):
        keys = [(r["ts_utc"], r["id"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len({r["id"] for r in self.rows}), len(self.rows))
        self.assertEqual(dict(Counter(r["kind"] for r in self.rows)), self.plan.counts())

    def test_deterministic(self):
        self.assertEqual(inject.canon_bytes(synth.stored_rows()), inject.canon_bytes(self.rows))
        self.assertNotEqual(inject.canon_bytes(synth.stored_rows(seed=1)), inject.canon_bytes(self.rows))

    def test_masked_text_has_no_raw_placeholders(self):
        raw_names = ["홍길동", "김철수", "고객사A", *(f"과제{x}" for x in "ABCDEF")]
        for r in self.rows:
            for col in synth.stored.TEXT_COLUMNS[r["kind"]]:
                v = r.get(col)
                for s in (v if isinstance(v, list) else [v] if v else []):
                    for n in raw_names:
                        self.assertNotIn(n, s, (r["kind"], col))

    def test_merge_and_witness_routes(self):
        rows = synth.stored_rows(self.plan, kinds=("mail",), srcs={"mail": ("mail.com", "mail.index", "mail.owa")})
        by = {s: {r["msg_key"] for r in rows if r["src"] == s} for s in ("mail.com", "mail.index", "mail.owa")}
        self.assertEqual(by["mail.com"], by["mail.index"])
        self.assertEqual(by["mail.com"], by["mail.owa"])
        self.assertIn("date", {r["ts_precision"] for r in rows if r["src"] == "mail.owa"})
        wit = synth.stored_rows(self.plan, kinds=("mail", "cal", "teams"),
                                srcs={"mail": ("mail.copilot",), "cal": ("cal.copilot",), "teams": ("teams.copilot",)})
        self.assertTrue(wit)
        for r in wit:
            self.assertEqual(r["confidence"], 0.3)
            self.assertEqual(r["ts_precision"], "date")
            self.assertLessEqual(len(r["text_masked"]), 200)
            self.assertLessEqual(set(r), synth.STORED_COLUMNS[r["kind"]])
        with self.assertRaises(ValueError):
            synth.stored_rows(self.plan, kinds=("mail",), srcs={"mail": ("cal.com",)})

    def test_doc_keys_link_window_file_mail(self):
        win = {r["doc_key"] for r in self.rows if r["kind"] == "pc_session" and r.get("doc_key")}
        fil = {r["doc_key"] for r in self.rows if r["kind"] == "pc_file"}
        att = {k for r in self.rows if r["kind"] == "mail" for k in r["attach_keys"]}
        self.assertTrue(win & fil)
        self.assertTrue(fil & att)


class PerfTest(unittest.TestCase):
    def test_three_months_signals_under_60s(self):
        t0 = time.perf_counter()
        rows = synth.signals_3m()
        dt = time.perf_counter() - t0
        self.assertLess(dt, 60.0)
        self.assertTrue(38_000 <= len(rows) <= 50_000, len(rows))      # 약 4.3만(T-19 · W-G9)


# ── 주입 자료 ────────────────────────────────────────────────────────────────
class InjectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = synth.plan_month(2026, 9)

    def test_env_names(self):
        contract = {"LM_OUTLOOK_SELFTEST", "LM_PROBE_FAKE", "LM_INDEX_FAKE", "LM_OWA_FAKE", "LM_TEAMSWEB_FAKE",
                    "LM_COPILOT_STUB", "LM_NO_BROWSER"}                      # 계약 §11.3 + v1.2 C3
        self.assertEqual(set(inject.INJECT_ENV.values()), contract)
        self.assertEqual(set(tree.INJECT_VARS), contract)
        self.assertEqual(inject.env_for(outlook_selftest=5, no_browser=True, owa_fake=None),
                         {"LM_OUTLOOK_SELFTEST": "5", "LM_NO_BROWSER": "1"})
        self.assertEqual(inject.outlook_selftest_env(3), {"LM_OUTLOOK_SELFTEST": "3"})
        self.assertEqual(inject.outlook_selftest_env(5, "newol", "horizon=2026-01", "hang=read"),
                         {"LM_OUTLOOK_SELFTEST": "5,newol,horizon=2026-01,hang=read"})       # v1.2 C3 문법
        for bad in ("graph", "horizon=26-1", "hang=x"):
            with self.assertRaises(ValueError):
                inject.outlook_selftest_env(1, bad)
        self.assertEqual(synth.SYNTH_VERSION, "2")
        with self.assertRaises(KeyError):
            inject.env_for(graph=1)

    def test_write_all(self):
        with tempfile.TemporaryDirectory() as d:
            paths = inject.write_all(d, self.plan)
            idx = json.loads(paths["index_fake"].read_text(encoding="utf-8"))
            self.assertTrue(idx["mail"] and idx["calendar"])
            self.assertTrue(all(r["System.ItemUrl"].startswith("mapi://") for r in idx["mail"]))
            owa = json.loads(paths["owa_fake"].read_text(encoding="utf-8"))
            self.assertFalse(owa["login"])
            self.assertTrue(owa["mail"]["2026-09"]["inbox"] and owa["mail"]["2026-09"]["sent"])
            self.assertTrue(owa["cal"])
            tw = json.loads(paths["teamsweb_fake"].read_text(encoding="utf-8"))
            self.assertEqual(tw["chats"]["n"], len(self.plan.rooms))
            mids = [x["mid"] for v in tw["msgs"].values() for page in v for x in page["items"] if x["t"] == "msg"]
            self.assertEqual(len(mids), len(self.plan.chats))
            stub = paths["copilot_stub"]
            self.assertEqual(sorted(p.name for p in stub.iterdir()), sorted(f"{s}.json" for s in inject.STUB_STAGES))
            sa = json.loads((stub / "speech_act.json").read_text(encoding="utf-8"))
            self.assertEqual(sa["mode"], ["ok"])
            self.assertEqual(set(sa), {"mode", "default", "by_key"})
            raw = paths["teams_rawfile"].read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
            self.assertGreater(len(raw[3:].decode("utf-8").splitlines()), len(self.plan.chats) // 2)
            csv = paths["events_csv"].read_bytes()
            self.assertTrue(csv.startswith(b"t,kind,src\r\n"))
            self.assertEqual(csv.count(b"\n"), csv.count(b"\r\n"))
            csv.decode("ascii")
            reg = paths["mru_reg"].read_bytes()
            self.assertTrue(reg.startswith(b"\xff\xfe"))
            text = reg[2:].decode("utf-16-le")
            self.assertTrue(text.startswith("Windows Registry Editor Version 5.00\r\n"))
            self.assertIn("\\User MRU\\", text)
            self.assertIn('"Item 1"="[F00000000][T', text)
            args = inject.events_args(paths["events_csv"], self.plan)
            self.assertEqual(args[0], "-EventsCsv")
            self.assertIn("-Now", args)
            self.assertIn("-BootTime", args)

    def test_owa_login_and_versions(self):
        self.assertTrue(inject.owa_fake(self.plan, login=True)["login"])
        self.assertTrue(inject.teamsweb_fake(self.plan, login=True)["login"])
        text = inject.mru_reg(self.plan, versions=("15.0", "14.0"))
        self.assertIn("\\Office\\15.0\\", text)
        self.assertIn("\\Office\\14.0\\", text)
        stub = inject.copilot_stub({"task_label": {"mode": ["truncate:0.6", "ok"]}})
        self.assertEqual(stub["task_label"]["mode"], ["truncate:0.6", "ok"])
        self.assertEqual(stub["task_label"]["by_key"], {})

    def test_ndjson_control_lines(self):
        recs = synth.raw_records("teams", self.plan)[:3]
        lines = inject.ndjson(recs, meta={"my_addrs": []}, cursor={"last_ts_utc": recs[-1]["ts_utc"]}).splitlines()
        self.assertEqual(len(lines), 5)
        self.assertIn("_meta", json.loads(lines[0]))
        self.assertIn("_cursor", json.loads(lines[-1]))
        self.assertTrue(all(json.loads(x)["_kind"] == "teams" for x in inject.ndjson(recs, kind="teams").splitlines()))
        line = inject.in_line(cfg={"teams.timeRegex": ""}, self_names=["홍길동"])
        self.assertTrue(line.endswith(b"\n"))
        obj = json.loads(line)["_in"]
        self.assertIsNone(obj["cursor"])
        self.assertEqual(obj["self_names"], ["홍길동"])
        self.assertNotIn("self_names", json.loads(inject.in_line(cursor={"x": 1}))["_in"])


# ── 저장소 텍스트(이 WP 소유 파일) ───────────────────────────────────────────
class RepoTextTest(unittest.TestCase):
    AREAS = ("core", "privacy", "time", "hier", "bridge", "report", "bundle", "team", "collect", "agent", "normalize",
             "pipeline", "ui", "e2e")                    # + fixtures\__init__.py 는 FIX.glob 에 이미 들어 있다

    def test_owned_sources_clean(self):
        """WP-05 소유 파일만 본다(남의 tests\\fixtures\\wpNN\\ 은 그 WP 가 책임진다)."""
        files = sorted(FIX.glob("*.py")) + sorted((FIX / "synth").glob("*.py")) + [Path(__file__).resolve()]
        files += [FIX.parent / a / "__init__.py" for a in self.AREAS] + [FIX.parent / "__init__.py"]
        self.assertEqual(len(files), len(set(files)))
        for f in files:
            data = f.read_bytes()
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), f.name)
            self.assertNotIn(b"\r", data, f.name)
            text = data.decode("utf-8")
            self.assertFalse(any(ord(ch) < 32 and ch not in "\n\t" for ch in text), f.name)
            self.assertIsNone(PRIV_IP_RX.search(text), f.name)
            bad = {m.group(1) for m in EMAIL_RX.finditer(text) if not _example_domain(m.group(1))}
            self.assertEqual(bad, set(), f.name)
            self.assertNotIn("Zone" + "Info", text, f.name)              # L-04(이 파일에도 리터럴을 두지 않게 조립)


if __name__ == "__main__":
    unittest.main()
