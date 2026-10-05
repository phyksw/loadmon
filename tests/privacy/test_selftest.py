# -*- coding: utf-8 -*-
"""WP-10 회귀 말뭉치 관문 시험 — 계약 T-08(run_selftest 0), P-T1·T2, ``tools\\lm27_selftest.py privacy [--update-lock]``
rc 0·1, 잠금 갱신 규칙(P §16.4), 보류(다른 묶음 모듈 없음)·스키마·템플릿·감사 형식 절.

아직 없는 다른 작업 묶음 모듈(WP-11 keys·gate·records, WP-25 bridge.stages)은 계약 시그니처대로 만든 가짜를
``sys.modules`` 에 끼워 시험한다(계획 §4 '가짜는 소비 WP 의 tests 안에만'). 실물은 W1 통합 창에서 같은 말뭉치로 돈다.
잠금·스키마 파일은 %TEMP% 사본으로 돌려 실제 트리를 쓰지 않는다. 하위 프로세스 시험은 %TEMP% 복제 트리에서만.
"""
import dataclasses
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unicodedata
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lm27.privacy import rules, selftest
from lm27.privacy.detect import SanitizeContext, safe_truncate, sanitize, subkey
from lm27.privacy.rules import HIGH
from lm27.util import events, fsx
from tests.fixtures.canary import canaries
from tests.fixtures.tree import CloneTestCase, guard_write

WP10_PRIVACY = {"rules.py", "rules.lock.json", "detect.py", "scan.py", "classify.py", "selftest.py", "corpus"}


# ── 계약 시그니처대로 만든 가짜(WP-11 keys·gate·records) ─────────────────────────────────
def _fake_keys():
    m = types.ModuleType("lm27.privacy.keys")
    m.PURPOSES = ("person", "msg", "thread", "chat", "cal", "doc", "path", "dir", "repo", "commit", "unit", "host", "peer")
    m.AGENT_PURPOSES = ("person", "msg", "thread", "chat", "doc", "path", "dir")

    class NoKeyError(KeyError):
        pass

    @dataclasses.dataclass(frozen=True)
    class Keyring:
        primary_kid: str
        primary_secret: bytes
        all: dict

        @property
        def kid(self):
            return self.primary_kid

        def sub(self, purpose):
            return subkey(self.primary_secret, purpose)

    @dataclasses.dataclass(frozen=True)
    class AgentKeys:
        kid: str
        subkeys: dict

        def sub(self, purpose):
            try:
                return self.subkeys[purpose]
            except KeyError:
                raise NoKeyError(purpose) from None

    def keyed(kr, purpose, value, n=16):
        if purpose not in m.PURPOSES:
            raise ValueError("purpose")
        return hmac.new(kr.sub(purpose), value.encode("utf-8"), hashlib.sha256).hexdigest()[:n]

    tail = r"([_\-\s]?(v\d+(\.\d+)?|rev\d+|r\d+|최종|final|수정본?|사본|copy|\(\d+\)|\d{6,8}))$"   # 계약 §4.3 · W §4.1

    def doc_fam(name):
        x = unicodedata.normalize("NFKC", name).lower().strip()
        x = re.sub(r"\.(?:gz|zip|7z)$", "", x)
        x = re.sub(r"\.(?:prt|asm|drw)\.\d+$", "", x)
        x = re.sub(r"\.[0-9a-z]{1,5}$", "", x)
        for _ in range(5):
            y = re.sub(tail, "", x).strip(" _-")
            if y == x:
                break
            x = y
        return x

    m.NoKeyError, m.Keyring, m.AgentKeys, m.keyed, m.doc_fam = NoKeyError, Keyring, AgentKeys, keyed, doc_fam
    m.who_key = lambda kr, ident: "w" + keyed(kr, "person", ident, 16)
    m.doc_key = lambda kr, name: "d" + keyed(kr, "doc", "n:" + doc_fam(name), 16)
    return m


def _fake_gate(*, broken=False):
    """P §13.2·§14.4 코드 블록 그대로(가짜). broken=True 면 게이트가 아무것도 거르지 않는다(관문이 잡아야 함)."""
    m = types.ModuleType("lm27.privacy.gate")

    class GateSpecError(Exception):
        pass

    @dataclasses.dataclass
    class GateItem:
        item_id: str
        fields: dict
        meta: dict

    @dataclasses.dataclass(frozen=True)
    class StageSpec:
        name: str
        allowed_fields: frozenset
        text_fields: frozenset
        max_item_chars: int = 400

    @dataclasses.dataclass
    class GateContext:
        sctx: SanitizeContext
        canaries: tuple
        person_tokens: str = "plain"
        audit: object = None

    @dataclasses.dataclass
    class GateResult:
        kept: list
        dropped: list
        counts: dict

    def gate_text(text, gctx):
        r = sanitize(text, "copilot", gctx.sctx)
        if r.drop:
            return None, {"cred": 1}
        high = {k: v for k, v in r.hits.items() if k in HIGH}
        if high:
            return None, high
        t, low = r.text, r.text.lower()
        for c in gctx.canaries:
            c2 = c.lower()
            if len(c2) < 4:
                continue
            if re.fullmatch(r"[a-z0-9._\-]+", c2):
                if re.search(r"(?<![a-z0-9])" + re.escape(c2) + r"(?![a-z0-9])", low):
                    return None, {"canary": 1}
            elif c2 in low:
                return None, {"canary": 1}
        if gctx.person_tokens == "plain":
            t = re.sub(r"\[사람#[0-9a-f]{6}\]", "[사람]", t)
        return t, r.hits

    def gate_copilot(items, stage, gctx):
        kept, dropped, counts = [], [], {}
        for it in items:
            if set(it.fields) - stage.allowed_fields:
                raise GateSpecError(stage.name)
            if broken:
                kept.append(it)
                continue
            new_fields, bad = dict(it.fields), None
            for f in stage.text_fields & set(it.fields):
                out, info = gate_text(str(it.fields[f]), gctx)
                if out is None:
                    bad = next(iter(info))
                    break
                new_fields[f] = safe_truncate(out, stage.max_item_chars)
            if bad:
                dropped.append((it.item_id, "pii:" + bad))
                continue
            kept.append(GateItem(it.item_id, new_fields, it.meta))
        return GateResult(kept, dropped, counts)

    forbid = re.compile(r"@|\\|\d{5,}|\[사람#|\[이메일@|\[URL\]|\[경로\]")

    def check_team_label(s, gctx, max_len=40):
        v = []
        if len(s) > max_len:
            v.append("too_long")
        if forbid.search(s):
            v.append("forbidden_pattern")
        r = sanitize(s, "label", gctx.sctx)
        if r.drop or r.text != s or r.hits:
            v.append("not_clean")
        return v

    for k, v in {"GateSpecError": GateSpecError, "GateItem": GateItem, "StageSpec": StageSpec, "GateContext": GateContext,
                 "GateResult": GateResult, "gate_copilot": gate_copilot, "check_team_label": check_team_label}.items():
        setattr(m, k, v)
    return m


FAKE_SCHEMAS = {
    "mail": SimpleNamespace(columns=frozenset({"id", "kind", "src", "msg_key", "subject_masked", "attach_names_masked"}),
                            text_fields={"subject_masked": ("subject", 120, None), "attach_names_masked": ("a", 80, 5)}),
    "pc_compute": {"columns": ["id", "kind", "src", "cpu_core"], "text_fields": []},
}


def _fake_records(schemas=None):
    m = types.ModuleType("lm27.privacy.records")
    m.SCHEMAS = FAKE_SCHEMAS if schemas is None else schemas
    return m


class _Harness(unittest.TestCase):
    """잠금·스키마 파일을 %TEMP% 로 돌리고, 사람용 출력(events → stderr)을 잡는다."""

    def setUp(self):
        self.tmp = guard_write(tempfile.mkdtemp(prefix="lm27t_wp10_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.err = io.StringIO()
        events.configure(mode="text", err_stream=self.err)
        self.addCleanup(events.configure, mode="text")
        self.lock = self.tmp / "rules.lock.json"
        self.schemas = self.tmp / "schemas_v1.json"
        fsx.atomic_write(self.lock, fsx.canon_bytes({"rules_hash": rules.rules_hash(), "rules_ver": rules.RULES_VERSION})
                         + b"\n")
        fsx.atomic_write(self.schemas, fsx.canon_bytes(selftest.schema_snapshot(FAKE_SCHEMAS)))
        orig = selftest._resource

        def res(*rel):
            if rel == selftest.LOCK_REL:
                return self.lock
            if rel == selftest.SCHEMAS_REL:
                return self.schemas
            return orig(*rel)
        p = mock.patch.object(selftest, "_resource", res)
        p.start()
        self.addCleanup(p.stop)

    def deps(self, *, keys=True, gate=True, records=True, stages=None, gate_broken=False, schemas=None):
        mods = {"lm27.privacy.keys": _fake_keys() if keys else None,
                "lm27.privacy.gate": _fake_gate(broken=gate_broken) if gate else None,
                "lm27.privacy.records": _fake_records(schemas) if records else None,
                "lm27.bridge.stages": stages}
        return mock.patch.dict(sys.modules, mods)

    def stages_pkg(self, body, mod="fake_stage"):
        """가짜 lm27.bridge.stages 패키지(%TEMP% 폴더 하나에 모듈 하나). 같은 시험에서 여러 번 만들면 모듈 이름을 바꾼다."""
        d = Path(tempfile.mkdtemp(prefix="stages_", dir=self.tmp))
        fsx.atomic_write(d / (mod + ".py"), body)
        pkg = types.ModuleType("lm27.bridge.stages")
        pkg.__path__ = [str(d)]
        sys.modules.pop("lm27.bridge.stages." + mod, None)
        self.addCleanup(sys.modules.pop, "lm27.bridge.stages." + mod, None)
        return pkg

    def out(self):
        return self.err.getvalue()

    def corpus_copy(self, edit):
        rows = selftest.load_corpus()
        rows = edit(rows)
        p = self.tmp / "corpus.jsonl"
        fsx.atomic_write(p, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        return p


class RunSelftestTest(_Harness):
    def test_all_sections_pass_T08(self):
        """T-08/P-T1: 말뭉치 144 + 게이트·라벨 14 + 창 9 + ext 22 — 모든 절이 돌고 실패 0, 보류 0."""
        pkg = self.stages_pkg('PROMPT_TEMPLATE = "다음 항목의 업무 유형을 고르세요: {items}"\n'
                              'SYSTEM_PROMPTS = ("[사람] 토큰은 그대로 둡니다", {"ko": "JSON 으로만 답합니다"})\n')
        with self.deps(stages=pkg):
            rc = selftest.run_selftest()
        out = self.out()
        self.assertEqual(rc, 0, out)
        self.assertIn("결과: 통과", out)
        self.assertIn("보류 0", out)
        for name in ("양성(가림) … 통과 60/60", "멱등 … 통과 60/60", "자격증명 폐기 … 통과 6/6", "오탐 미끼 … 통과 50/50",
                     "광고 점수 … 통과 14/14", "공사 구분 … 통과 14/14", "창 분류 … 통과 9/9",
                     "게이트·팀 라벨 … 통과 14/14", "통과 22/22", "프롬프트 템플릿 scan 0 … 통과 3/3"):
            self.assertIn(name, out)

    def test_perf_section_optional(self):
        with self.deps(keys=False, gate=False, records=False):
            self.assertEqual(selftest.run_selftest(perf=False), 0)
        self.assertNotIn("성능 …", self.out())

    def test_pending_when_modules_absent(self):
        with self.deps(keys=False, gate=False, records=False):
            rc = selftest.run_selftest()
        out = self.out()
        self.assertEqual(rc, 0, out)
        self.assertIn("lm27.privacy.gate 없음", out)
        self.assertIn("lm27.privacy.keys 없음 — 11건 보류", out)
        self.assertIn("보류 4", out)

    def test_rule_change_fails_lock_T2(self):
        """P-T2: RX["mobile"] 한 글자 수정 → '규칙 고정' 실패."""
        p = rules.RX["mobile"]
        changed = re.compile(p.pattern.replace("{3,4}", "{3,5}", 1), p.flags)
        with self.deps(), mock.patch.dict(rules.RX, {"mobile": changed}):
            rc = selftest.run_selftest()
        self.assertEqual(rc, 1)
        self.assertRegex(self.out(), r"규칙 고정 … 실패.*판·말뭉치·잠금 갱신 안 됨")

    def test_missing_lock_fails(self):
        os.remove(self.lock)
        with self.deps():
            self.assertEqual(selftest.run_selftest(), 1)
        self.assertIn("잠금 파일 없음", self.out())

    def test_corpus_regression_reports_ids_only_I8(self):
        """기대값이 어긋나면 실패 — 보고에는 id·사유 코드만(말뭉치 원문·값 없음, I8)."""
        def edit(rows):
            for r in rows:
                if r["id"] == "P10":
                    r["expect"] = r["expect"].replace("[전화]", "[계좌]")
            return rows
        with self.deps():
            rc = selftest.run_selftest(self.corpus_copy(edit))
        out = self.out()
        self.assertEqual(rc, 1)
        self.assertIn("P10(text)", out)
        corpus = selftest.load_corpus()
        for r in corpus:
            for key in ("text", "expect", "arg"):
                v = r.get(key)
                if isinstance(v, str) and len(v) >= 8 and re.search(r"\d{4}", v):
                    self.assertNotIn(v, out)
        for c in canaries(groups=["pii"]):
            self.assertNotIn(c.value, out)

    def test_minimum_size_gate(self):
        """말뭉치를 줄이는 변경 차단: 양성 ≥30, 미끼 ≥20."""
        with self.deps(stages=self.stages_pkg('PROMPT = "분류하세요"\n')):
            keep40 = self.corpus_copy(lambda rows: [r for r in rows if r["type"] != "pos" or r["id"] > "P20"])
            self.assertEqual(selftest.run_selftest(keep40), 0, self.out())
            keep10 = self.corpus_copy(lambda rows: [r for r in rows if r["type"] != "pos" or r["id"] < "P11"])
            self.assertEqual(selftest.run_selftest(keep10), 1)
            self.assertIn("양성 10 < 30", self.out())
            neg19 = self.corpus_copy(lambda rows: [r for r in rows if r["type"] != "neg" or r["id"] < "N20"])
            self.assertEqual(selftest.run_selftest(neg19), 1)
            self.assertIn("미끼 19 < 20", self.out())

    def test_duplicate_and_bad_lines(self):
        with self.deps():
            rc = selftest.run_selftest(self.corpus_copy(lambda rows: rows + rows[:1]))
        self.assertEqual(rc, 1)
        self.assertIn("id 중복 P01", self.out())
        p = self.tmp / "bad.jsonl"
        fsx.atomic_write(p, '{"id": "P01", "type": "pos"}\n{oops\n')
        self.assertEqual(selftest.run_selftest(p), 1)
        self.assertIn("2번째 줄 JSON 형식 오류", self.out())
        self.assertEqual(selftest.run_selftest(self.tmp / "none.jsonl"), 1)
        self.assertIn("읽기 실패(FileNotFoundError)", self.out())

    def test_broken_gate_fails(self):
        with self.deps(gate_broken=True):
            self.assertEqual(selftest.run_selftest(), 1)
        self.assertRegex(self.out(), r"게이트·팀 라벨 … 실패 \d+/14")

    def test_doc_fam_contract_mismatch_fails(self):
        keys = _fake_keys()
        keys.doc_fam = lambda name: name                       # 정규화 안 하는 구현
        with mock.patch.dict(sys.modules, {"lm27.privacy.keys": keys, "lm27.privacy.gate": _fake_gate(),
                                           "lm27.privacy.records": _fake_records()}):
            self.assertEqual(selftest.run_selftest(), 1)
        self.assertIn("D01", self.out())

    def test_schema_snapshot_mismatch_fails(self):
        changed = dict(FAKE_SCHEMAS, pc_compute={"columns": ["id", "kind", "src", "cpu_core", "user"], "text_fields": []})
        with self.deps(schemas=changed):
            self.assertEqual(selftest.run_selftest(), 1)
        self.assertIn("pc_compute(스냅숏과 다름)", self.out())

    def test_template_with_pii_fails(self):
        phone = next(c for c in canaries() if c.cat == "phone").value
        pkg = self.stages_pkg(f'REVIEW_PROMPT = "예시 연락처 {phone} 로 회신"\nnot_checked = "{phone}"\n')
        with self.deps(stages=pkg):
            self.assertEqual(selftest.run_selftest(), 1)
        out = self.out()
        self.assertIn("fake_stage.REVIEW_PROMPT[0]", out)
        self.assertNotIn(phone, out)


class UpdateLockTest(_Harness):
    def test_writes_when_all_pass(self):
        os.remove(self.lock)
        with self.deps(stages=self.stages_pkg('PROMPT = "분류하세요"\n')):
            rc = selftest.run_selftest(update_lock=True)
        self.assertEqual(rc, 0, self.out())
        self.assertEqual(fsx.read_bytes(self.lock), fsx.canon_bytes(
            {"rules_hash": rules.rules_hash(), "rules_ver": rules.RULES_VERSION}) + b"\n")
        self.assertIn("잠금 기록", self.out())

    def test_refuses_with_pending(self):
        os.remove(self.lock)
        with self.deps(keys=False):
            self.assertEqual(selftest.run_selftest(update_lock=True), 1)
        self.assertFalse(self.lock.exists())
        self.assertIn("보류 절이 있어 잠금을 쓰지 않음", self.out())

    def test_refuses_without_version_bump(self):
        """P §16.4 ③: 규칙이 바뀌었는데 판을 안 올리면 --update-lock 도 거부."""
        before = fsx.read_bytes(self.lock)
        p = rules.RX["mobile"]
        changed = re.compile(p.pattern.replace("{3,4}", "{3,5}", 1), p.flags)
        with self.deps(stages=self.stages_pkg('PROMPT = "분류하세요"\n')), mock.patch.dict(rules.RX, {"mobile": changed}):
            rc = selftest.run_selftest(update_lock=True)
        self.assertEqual(rc, 1)
        self.assertEqual(fsx.read_bytes(self.lock), before)
        self.assertIn("RULES_VERSION 을 올리지 않음", self.out())

    def test_refuses_downgrade_and_failures(self):
        fsx.atomic_write(self.lock, fsx.canon_bytes({"rules_hash": "0" * 16, "rules_ver": "2099.1.0"}) + b"\n")
        with self.deps(stages=self.stages_pkg('PROMPT = "분류하세요"\n')):
            self.assertEqual(selftest.run_selftest(update_lock=True), 1)
        self.assertIn("판을 내릴 수 없음", self.out())
        with self.deps(gate_broken=True, stages=self.stages_pkg('PROMPT = "분류"\n', mod="s2")):
            self.assertEqual(selftest.run_selftest(update_lock=True), 1)
        self.assertIn("실패 절이 있어 잠금을 쓰지 않음", self.out())

    def test_version_bump_accepted(self):
        with self.deps(stages=self.stages_pkg('PROMPT = "분류하세요"\n')), \
                mock.patch.object(rules, "RULES_VERSION", "2026.10.1"), \
                mock.patch.object(selftest, "RULES_VERSION", "2026.10.1"):
            rc = selftest.run_selftest(update_lock=True)
            h = rules.rules_hash()
        self.assertEqual(rc, 0, self.out())
        self.assertEqual(selftest.read_lock(self.lock), {"rules_ver": "2026.10.1", "rules_hash": h})


class HelperTest(unittest.TestCase):
    def test_read_lock_shapes(self):
        tmp = guard_write(tempfile.mkdtemp(prefix="lm27t_wp10_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        p = tmp / "l.json"
        for body in (b"", b"[]", b'{"rules_ver": "x", "rules_hash": "0000000000000000"}',
                     b'{"rules_ver": "2026.10.0", "rules_hash": "XYZ"}'):
            fsx.atomic_write(p, body)
            with self.subTest(body=body), mock.patch.object(sys, "stderr", io.StringIO()):
                self.assertIsNone(selftest.read_lock(p))
        self.assertIsNone(selftest.read_lock(tmp / "none.json"))
        self.assertTrue(selftest.lock_matches())                 # 저장소 잠금 = 코드(L-24)

    def test_schema_snapshot_shape(self):
        snap = selftest.schema_snapshot(FAKE_SCHEMAS)
        self.assertEqual(snap["format"], "lm27-schemas/1")
        self.assertEqual(snap["kinds"]["mail"]["text_fields"], ["attach_names_masked", "subject_masked"])
        self.assertEqual(snap["kinds"]["pc_compute"], {"columns": ["cpu_core", "id", "kind", "src"], "text_fields": []})
        self.assertEqual(list(snap["kinds"]), sorted(snap["kinds"]))

    def test_audit_violations(self):
        ref = dict(selftest._AUDIT_REF)
        self.assertEqual(selftest.audit_violations(ref), [])
        at = chr(64)
        bad = [dict(ref, stage="a" + at + "b"), dict(ref, note="x"), dict(ref, masked={"phone": -1}),
               dict(ref, src="한글 문장 금지"), dict(ref, ts_utc="2026-10-05"), dict(ref, ev="nope"),
               dict(ref, dropped={"x" + at + "y": 1}), dict(ref, rows_in=True), dict(ref, err={"1" * 12: 1}), "x"]
        for ev in bad:
            with self.subTest(ev=str(ev)[:40]):
                self.assertNotEqual(selftest.audit_violations(ev), [])
        self.assertEqual(selftest.audit_violations(dict(ref, rules_hash="1234567890abcdef")), [])   # 해시는 숫자열 검사 면제
        self.assertEqual(selftest.audit_violations(dict(ref, items_in=3)), ["key:items_in"])        # 본문 키는 18개만(계약 §3.13)
        env = dict(ref, id="1234567890abcdef", kind="privacy_audit")
        self.assertEqual(selftest.audit_violations(env, envelope=True), [])
        self.assertEqual(selftest.audit_violations(env), ["key:id", "key:kind"])
        self.assertEqual(selftest.audit_violations(dict(ref, src="copilot", stage="copilot:classify")), [])
        got = selftest.audit_violations(dict(ref, note="x" + at))
        self.assertTrue(all(":" in g or g == "ev" for g in got))
        self.assertNotIn(at, "".join(got))

    def test_pathological_inputs(self):
        p = selftest.pathological_inputs()
        self.assertEqual(len(p), 12)
        self.assertEqual(len({n for n, _ in p}), 12)
        self.assertTrue(all(len(s) >= 4000 for _, s in p))

    def test_corpus_counts(self):
        rows = selftest.load_corpus()
        counts = {t: sum(r["type"] == t for r in rows) for t in selftest.TYPES}
        self.assertEqual(counts, {"pos": 60, "drop": 6, "neg": 50, "ad": 14, "priv": 14, "gate": 8, "label": 6, "win": 9,
                                  "ext": 22})
        raw = fsx.read_bytes(selftest._resource(*selftest.CORPUS_REL))
        self.assertNotIn(b"\r", raw)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(raw.endswith(b"\n"))


class ToolCloneTest(CloneTestCase):
    """%TEMP% 복제 트리에서 tools\\lm27_selftest.py · lm27_cli.py selftest privacy 실행(하위 프로세스).
    다른 묶음의 작업 중 파일과 무관하게 돌도록 복제 안의 lm27\\privacy 는 WP-10 파일만 남기고 lm27\\bridge 는 지운다."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        priv = cls.clone.path("lm27", "privacy")
        for p in priv.iterdir():
            if p.name not in WP10_PRIVACY:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        shutil.rmtree(cls.clone.path("lm27", "bridge"), ignore_errors=True)

    def run_tool(self, *args):
        cp = self.clone.run_py([self.clone.path("tools", "lm27_selftest.py"), *args], timeout=300)
        return cp.returncode, cp.stdout.decode("utf-8", "replace"), cp.stderr.decode("utf-8", "replace")

    def test_tool_rc0_and_text_on_stderr(self):
        rc, out, err = self.run_tool("privacy")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")
        self.assertIn("결과: 통과", err)
        self.assertIn("보류", err)                              # WP-11·WP-25 모듈이 없는 복제
        self.assertFalse(list(Path(self.clone.root).rglob("__pycache__")))

    def test_cli_same_gate(self):
        cp = self.clone.run_cli("selftest", "privacy", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        cp = self.clone.run_cli("selftest", "privacy", "--events", "jsonl", timeout=300)
        evs = [json.loads(x) for x in cp.stdout.decode("utf-8").splitlines()]
        summary = [e for e in evs if e.get("name") == "summary"]
        self.assertEqual((summary[0]["rc"], evs[-1]["ev"], evs[-1]["rc"]), (0, "run_end", 0))

    def test_bad_args_rc1(self):
        for args in ((), ("nosuch",), ("privacy", "--nope")):
            with self.subTest(args=args):
                self.assertEqual(self.run_tool(*args)[0], 1)
        self.assertEqual(self.run_tool("--help")[0], 0)

    def test_update_lock_refused_while_pending(self):
        lock = self.clone.path("lm27", "privacy", "rules.lock.json")
        before = lock.read_bytes()
        rc, _out, err = self.run_tool("privacy", "--update-lock")
        self.assertEqual(rc, 1)
        self.assertIn("보류 절이 있어 잠금을 쓰지 않음", err)
        self.assertEqual(lock.read_bytes(), before)

    def test_rules_edit_fails_T2(self):
        """P-T2(하위 프로세스): 복제의 rules.py 정규식 한 글자 수정 → rc 1, '규칙 고정' 실패. 끝나면 되돌린다."""
        p = self.clone.path("lm27", "privacy", "rules.py")
        orig = p.read_bytes()
        self.addCleanup(fsx.atomic_write, p, orig)
        src = orig.decode("utf-8")
        i = src.index('"mobile": re.compile(')
        j = src.index("{3,4}", i)
        fsx.atomic_write(p, (src[:j] + "{3,5}" + src[j + 5:]).encode("utf-8"))
        rc, _out, err = self.run_tool("privacy")
        self.assertEqual(rc, 1)
        self.assertRegex(err, r"규칙 고정 … 실패")


if __name__ == "__main__":
    unittest.main()
