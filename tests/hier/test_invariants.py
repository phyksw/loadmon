# -*- coding: utf-8 -*-
r"""WP-22 관문 시험 — 결정성·카나리아·불변식·시간 불변·프롬프트 크기·설정 읽기(H §15 · 계획 §5 WP-22 완료 기준).

- G-H1 · T-H15: 같은 입력(기록·특징·단위업무·귀속 행)을 순서만 섞어 3번 → labels.json·groups.json(이름 포함) 바이트 동일.
- G-H2 · T-H06: 레지스트리 코드네임·별칭·mask_name 이름에 카나리아 → task_label·bootstrap·consolidate 프롬프트와 ai_in 전송
  필드에 0회(`[과제:ID]` 로만). 코드네임 검토 [과제 이름] → L-0001 → 그 뒤 프롬프트에 원 낱말 0회.
- G-H3 · T-22: 불변식 H-I1(라벨 하나·코드 유효)·H-I2(영역 = 과제에서 유도)·H-I4(role_id 재계산) — 무작위 5,000건 퍼즈 + 통합.
- G-H4 · T-06: 분류 전후 `team_tables.json` 정규 바이트 동일 · 분류 중 표가 바뀌면 H-I5 로 중단.
- G-H9: 과제 0~500 개 레지스트리에서 task_label 묶음 프롬프트 ≤ `bridge.inputMaxChars`.
- T-H14(B_MEET 회의 시리즈 — 꼬리표 보조 표시만, 과제 MM 불변) · T-H16(코파일럿 꺼짐) · T-H20(영역 변경 → 라벨·롤업 따라감,
  재질의 0) · 이 작업 패키지 소유 `hier.*` 설정 키가 실제로 읽힌다(L-12 의 실행 짝).
시간 코어는 실물(WP-20)을 합성 한 달(`tests.fixtures.synth.stored_rows` — 자리표시자 텍스트·시험 키)로 돈다. 네트워크 0.
"""
import json
import random
import unittest
from datetime import UTC, date, datetime
from unittest import mock

from lm27.hier import HierInvariantError, check_invariants, classify_all, prepare, write_result
from lm27.hier import bootstrap as B
from lm27.hier import copilot_io as CI
from lm27.hier import proposals as PQ
from lm27.hier import vocab as V
from lm27.hier.apply import UnitLabel, apply_labels
from lm27.hier.groups import Group, TitleCache
from lm27.hier.registry import load_effective
from lm27.hier.team_out import team_parts
from lm27.hier.unitlabel import FieldFunc, RuleLabel, role_id
from lm27.time import analyze_time
from lm27.time.calendar import day0
from lm27.time.mm import rollup
from lm27.util.fsx import canon_bytes
from tests.fixtures.wp22 import hierkit as K
from tests.hier.test_golden import GOLD, assemble, boot_assemble, item_line, pack

K.install_fakes()

AS_OF = datetime(2026, 9, 30, 23, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
AT = "2026-10-01T09:00:00+09:00"
TEAM6 = {"schema": "lm27.registry/1", "version": 3, "projects": [
    {"id": "P-0001", "name": "과제A", "domain": "DEV", "copilot_desc": "회로 신규 개발"},
    {"id": "P-0002", "name": "과제B", "domain": "DEV", "copilot_desc": "센서 개발"},
    {"id": "P-0003", "name": "과제C", "domain": "MP", "copilot_desc": "양산 대응"},
    {"id": "P-0004", "name": "과제D", "domain": "EXT", "copilot_desc": "외부 지원"},
    {"id": "P-0005", "name": "과제E", "domain": "COM", "copilot_desc": "팀 운영"},
    {"id": "P-0006", "name": "과제F", "domain": "AX", "copilot_desc": "자동화 도구"}]}
OUT_FILES = ("labels.json", "groups.json", "evidence_tags.jsonl", "queue.json", "hier_meta.json")


def synth_rows(extra=()) -> list[dict]:
    from tests.fixtures.synth import stored_rows
    return sorted([dict(r) for r in stored_rows()] + list(extra), key=lambda r: (r["ts_utc"], r["id"]))


def time_run(rows, reg, cfg):
    feats, tags, trows = prepare(rows, reg, cfg)
    tr = analyze_time(K.fake_unit_id, rows, {}, K.CALENDAR, AS_OF, cfg=cfg, tags=tags)
    return feats, trows, tr


def run_ctx(cfg, reg, feats, tr, **kw) -> dict:
    d = {"cfg": cfg, "reg": reg, "feats": feats, "tasks": list(tr.tasks), "attrib": tr.attribution,
         "team_tables": tr.tables, "slot_basis": tr.env.basis, "now": NOW}
    d.update(kw)
    return d


def out_bytes(res) -> dict[str, bytes]:
    with K.TmpTree() as t:
        write_result(res, t.root / "out")
        return {n: (t.root / "out" / n).read_bytes() for n in OUT_FILES}


_BASE: dict = {}


def base():
    """합성 한 달 + 과제 6개 레지스트리의 시간 코어 결과(모듈 안 1회)."""
    if not _BASE:
        cfg = K.cfg()
        reg = K.golden_reg(team=TEAM6)
        rows = synth_rows()
        feats, trows, tr = time_run(rows, reg, cfg)
        _BASE.update(cfg=cfg, reg=reg, rows=rows, feats=feats, tr=tr)
    return _BASE


# ───────────────────────── G-H3 · T-22 불변식 ─────────────────────────
class InvariantCheckTest(unittest.TestCase):
    def test_detects(self):
        reg = K.golden_reg()
        good = UnitLabel(unit_id="u1", project="P-0007", domain="DEV", field="OPT", func="ANALYSIS", wtype="DEV",
                         role_id=role_id("P-0007", "OPT", "ANALYSIS"))
        self.assertEqual(check_invariants({"u1": good}, ["u1"], reg), [])
        bad = {
            "u1": UnitLabel(unit_id="u1", project="P-0007", domain="MP", field="OPT", func="ANALYSIS", wtype="DEV",
                            role_id=role_id("P-0007", "OPT", "ANALYSIS")),
            "u2": UnitLabel(unit_id="u2", project=None, domain="UNC", field="BOGUS", func="ANALYSIS", wtype="DEV",
                            role_id=role_id("UNC", "BOGUS", "ANALYSIS")),
            "u3": UnitLabel(unit_id="u3", project="P-0008", domain="MP", field="OPT", func="ANALYSIS", wtype="DEV",
                            role_id="r_000000"),
            "u4": UnitLabel(unit_id="u4", project="P-0008", proposal_id="pr_1", domain="MP", field="OPT",
                            func="ANALYSIS", wtype="DEV", role_id=role_id("P-0008", "OPT", "ANALYSIS")),
            "u9": good}
        errs = check_invariants(bad, ["u1", "u2", "u3", "u4", "u5"], reg)
        got = {(a, b) for a, b, _c in errs}
        self.assertEqual(got, {("H-I1", "u5"), ("H-I1", "u9"), ("H-I2", "u1"), ("H-I1", "u2"), ("H-I4", "u3"),
                               ("H-I1", "u4")})

    def test_fuzz_5000(self):
        """무작위 규칙 판정·코파일럿 답(목록 밖 코드·NEW·NONE·쓰레기 포함)·사용자 수정 5,000건 → 위반 0."""
        team = dict(K.GOLDEN_TEAM)
        team["projects"] = list(K.GOLDEN_TEAM["projects"]) + [
            {"id": "P-0030", "name": "예산 관리", "domain": "COM", "copilot_desc": "팀 예산"},
            {"id": "P-0040", "name": "옛 과제", "domain": "DEV", "status": "retired"}]
        local = {"schema": "lm27.registry_local/1",
                 "projects": [{"id": "L-0001", "name": "광센서 선행", "domain": "DEV", "proposal_id": "pr_1"}],
                 "vocab_add": {"fields": [{"code": "L_PHOTO", "name": "포토닉스", "maps_to": "OPT"}]}}
        reg = K.golden_reg(team=team, local=local)
        cfg = K.cfg()
        r = random.Random(22)
        reg_projects = ["P-0007", "P-0008", "P-0011", "P-0012", "P-0013", "P-0030", "P-0040", "L-0001"]
        reserved = list(V.RESERVED)
        fields = sorted(reg.vocab["fields"])
        funcs = sorted(reg.vocab["functions"])
        wtypes = sorted(reg.vocab["activity_types"])
        junk = ["", None, "BOGUS", "P-0999", 7, "NEW", "NONE", "pr_9", ["OPT"], {"x": 1}]
        total = 0
        for rnd in range(10):
            units, rule, ff, wt, groups, titles, ai, corr = {}, {}, {}, {}, [], {}, {}, {}
            uid_n = 0
            while uid_n < 500:
                gk = f"grp:{rnd:02d}{uid_n:010d}"
                members = []
                for _ in range(r.choice((1, 1, 1, 2, 3))):
                    uid = f"u_{rnd:02d}{uid_n:05d}"
                    uid_n += 1
                    members.append(uid)
                    units[uid] = K.U(uid, r.choice(("S1", "SELF", "APP", "ACK")),
                                     [(K.F(uid + "m", "mail", "공차 검토"), 1.0, "boundary")],
                                     effort_min=r.randint(1, 900), first_key="fk" + uid)
                    p = r.choice([None, None] + reg_projects + reserved)
                    src = "none" if p is None else ("domain_rule" if p in reserved else
                                                    r.choice(("token", "rule", "rule_probable")))
                    conf = "l" if p is None else r.choice("hml")
                    cands = tuple((r.choice(reg_projects), round(r.random(), 2)) for _ in range(r.randint(0, 3)))
                    rule[uid] = RuleLabel(p, 1.0 if p else 0.0, src, conf, cands, reg.domain_of(p) if p else "UNC")
                    ff[uid] = FieldFunc(r.choice(fields), r.choice("hml"), r.choice(funcs), r.choice("hml"))
                    wt[uid] = (r.choice(wtypes), r.choice("hml"), "")
                    if r.random() < 0.1:
                        corr[uid] = {k: r.choice(v) for k, v in (
                            ("project", reg_projects + reserved + junk), ("field", fields + junk),
                            ("func", funcs + junk), ("wtype", wtypes + junk), ("title", ["사용자 제목", "", "x"]))
                            if r.random() < 0.6}
                groups.append(Group(gk, "fk" + members[0], members[0], tuple(members),
                                    sum(units[m].effort_min for m in members)))
                titles[gk] = r.choice([("공차해석", "doc"), ("회의 자료", "subject"), ("해석 프로그램 작업", "app"),
                                       ("기타·기타 단위업무", "generic"), ("", "generic")])
                if r.random() < 0.7:
                    ai[gk] = {"by": r.choice(("ai", "ai", "rule_pending")), "ans": {
                        "project": r.choice(reg_projects + reserved + junk),
                        "field": r.choice(fields + junk), "func": r.choice(funcs + junk),
                        "wtype": r.choice(wtypes + junk), "title": r.choice(["광학 모듈 해석", "x", "", "가" * 90]),
                        "new": r.choice(["방열 모듈", "방열모듈", "레이저 모듈 2세대", "", "x"]),
                        "dom": r.choice(list(V.DOMAINS) + ["UNC", "", "ZZ", ["DEV"]]),
                        "conf": r.choice(["h", "m", "l", "x", ["h"]])}}
            props = PQ.ProposalQueue()
            labels, _conf, _st = apply_labels(rule, ff, wt, ai, corr, TitleCache(), props, reg, cfg, groups=groups,
                                              units=units, titles=titles, at=AT)
            errs = check_invariants(labels, units.keys(), reg, props)
            self.assertEqual(errs, [], (rnd, errs[:5]))
            for lb in labels.values():
                self.assertIn(lb.level, ("confirmed", "high", "medium", "low", "unclassified"))
                self.assertTrue(lb.title_src in ("user", "ai", "rule_doc", "rule_subject", "rule_app", "rule_generic"))
            total += len(labels)
        self.assertGreaterEqual(total, 5000)


# ───────────────────────── 통합(시간 코어 실물) ─────────────────────────
class PipelineTest(unittest.TestCase):
    def test_shuffle_determinism(self):
        """G-H1 · T-H15 — 기록·특징·단위업무·귀속 행 순서를 섞어 3번 → 결과 파일 바이트 동일(이름 포함)."""
        b = base()
        cfg, reg = b["cfg"], b["reg"]
        ref = classify_all(run_ctx(cfg, reg, b["feats"], b["tr"], build_ai_in=True))
        want = out_bytes(ref)
        want_items = canon_bytes(ref.ai_items)
        self.assertGreater(len(ref.labels), 50)
        for seed in (1, 2, 3):
            r = random.Random(seed)
            rows = list(b["rows"])
            r.shuffle(rows)
            feats, _trows, tr = time_run(rows, reg, cfg)
            feats = list(feats)
            r.shuffle(feats)
            tasks = list(tr.tasks)
            r.shuffle(tasks)
            att = list(tr.attribution.rows())
            r.shuffle(att)
            res = classify_all(run_ctx(cfg, reg, feats, tr, tasks=tasks, attrib=att, build_ai_in=True))
            got = out_bytes(res)
            for name in OUT_FILES:
                self.assertEqual(got[name], want[name], (seed, name))
            self.assertEqual(canon_bytes(res.ai_items), want_items, seed)

    def test_time_untouched(self):
        """G-H4 · T-06 — 분류 전후 team_tables 정규 바이트 동일. 분류 중 표가 바뀌면 H-I5 로 중단(결과 없음)."""
        b = base()
        tr = b["tr"]
        before = canon_bytes(tr.tables.as_json())
        tasks_before = canon_bytes([t.to_obj() if hasattr(t, "to_obj") else repr(t) for t in tr.tasks])
        res = classify_all(run_ctx(b["cfg"], b["reg"], b["feats"], tr, build_ai_in=True))
        self.assertEqual(canon_bytes(tr.tables.as_json()), before)
        self.assertEqual(canon_bytes([t.to_obj() if hasattr(t, "to_obj") else repr(t) for t in tr.tasks]), tasks_before)
        self.assertEqual(set(res.labels), {t.id for t in tr.tasks})                  # H-I1 — 단위업무마다 라벨 하나
        self.assertEqual(check_invariants(res.labels, [t.id for t in tr.tasks], b["reg"]), [])
        tables = json.loads(before.decode("utf-8"))
        real = __import__("lm27.hier.apply", fromlist=["apply_labels"]).apply_labels

        def tamper(*a, **kw):
            tables["alloc_daily"]["rows"][0][3] += 1                             # 분류 단계가 시간 표를 건드린 셈
            return real(*a, **kw)
        with mock.patch("lm27.hier.apply.apply_labels", side_effect=tamper):
            with self.assertRaises(HierInvariantError) as cm:
                classify_all(run_ctx(b["cfg"], b["reg"], b["feats"], tr, team_tables=tables))
        self.assertIn("H-I5", str(cm.exception))

    def test_result_files(self):
        """결과 `hier/1`(계약 §3.15) — 파일 6개, 정규 JSON·LF, 폴더는 out_dir 또는 paths.analysis_hier(run_id)."""
        b = base()
        res = classify_all(run_ctx(b["cfg"], b["reg"], b["feats"], b["tr"]))
        with K.TmpTree() as t:

            class FakePaths:
                def analysis_hier(self, run_id):
                    return t.root / "an" / run_id / "hier"
            names = write_result(res, paths=FakePaths(), run_id="r20261001")
            d = t.root / "an" / "r20261001" / "hier"
            self.assertEqual(sorted(names), sorted(p.name for p in d.iterdir()))
            self.assertEqual(len(names), 6)
            for n in names:
                raw = (d / n).read_bytes()
                self.assertNotIn(b"\r", raw)
                if n.endswith(".json"):
                    self.assertEqual(canon_bytes(json.loads(raw.decode("utf-8"))), raw.rstrip(b"\n"))
            meta = json.loads((d / "hier_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["hier_version"], "hier/1")
            self.assertTrue(all(k.split(".", 1)[0] == "hier" or k in ("episode.docs.genericStems",
                                                                     "episode.tokens.boilerplate", "time.tzOffsetMin",
                                                                     "team.unitTitleMode") for k in meta["cfg_used"]))
            lines = (d / "evidence_tags.jsonl").read_text(encoding="utf-8").splitlines()
            ids = [json.loads(x)["id"] for x in lines]
            self.assertEqual(ids, sorted(ids))
            self.assertEqual(set(json.loads(lines[0])), {"id", "proj", "score", "top2"})
            # out_dir 도 paths·run_id 도 없으면 ValueError(Paths.analysis_hier 는 W1 통합 창에서 lm27.paths 에 생김)
            with self.assertRaises(ValueError):
                write_result(res, paths=None, run_id="r1")
            with self.assertRaises(ValueError):
                write_result(res, paths=FakePaths(), run_id="")

    def test_copilot_off(self):
        """T-H16 — 코파일럿 꺼짐: 저장된 답이 있어도 쓰지 않고 ai_in 도 만들지 않는다. 규칙 라벨로 완주."""
        b = base()
        ref = classify_all(run_ctx(b["cfg"], b["reg"], b["feats"], b["tr"], build_ai_in=True))
        ai = {g.key: {"by": "ai", "ans": {"project": "P-0004", "field": "ETC", "func": "ETC", "wtype": "OFFICE",
                                          "title": "코파일럿 이름", "new": "", "dom": "", "conf": "h"}}
              for g in ref.groups}
        res = classify_all(run_ctx(b["cfg"], b["reg"], b["feats"], b["tr"], build_ai_in=True, write_ai_in=True,
                                   ai_out=ai, copilot_enabled=False))
        self.assertEqual(res.ai_items, [])
        self.assertFalse(res.copilot["used"])
        self.assertEqual(res.meta["counts"]["ai_items"], 0)
        self.assertEqual(set(res.labels), set(ref.labels))
        for lb in res.labels.values():
            self.assertFalse(any(str(v).startswith("ai") for v in lb.src.values()), lb.src)
            self.assertNotEqual(lb.title, "코파일럿 이름")
        on = classify_all(run_ctx(b["cfg"], b["reg"], b["feats"], b["tr"], ai_out=ai))
        self.assertTrue(on.copilot["used"])
        self.assertTrue(any(lb.title == "코파일럿 이름" for lb in on.labels.values()))   # 대조 — 켜면 답이 쓰인다

    def test_domain_change(self):
        """T-H20 — 과제 영역 DEV → MP: 라벨 영역·롤업이 따라가고, 역할·질의 내용 키는 그대로(재질의 0)."""
        b = base()
        team2 = json.loads(json.dumps(TEAM6))
        team2["projects"][0]["domain"] = "MP"
        reg2 = K.golden_reg(team=team2)
        r1 = classify_all(run_ctx(b["cfg"], b["reg"], b["feats"], b["tr"], build_ai_in=True))
        r2 = classify_all(run_ctx(b["cfg"], reg2, b["feats"], b["tr"], build_ai_in=True))
        p1 = [u for u, lb in r1.labels.items() if lb.project == "P-0001"]
        self.assertTrue(p1)
        for u in p1:
            self.assertEqual((r1.labels[u].domain, r2.labels[u].domain), ("DEV", "MP"))
            self.assertEqual(r1.labels[u].role_id, r2.labels[u].role_id)
        month = b["tr"].months[(2026, 9)]
        roll1, roll2 = rollup(month, r1.rollup_labels()), rollup(month, r2.rollup_labels())
        mm_p1 = roll1["project"]["P-0001"]
        self.assertAlmostEqual(roll2["domain"].get("MP", 0) - roll1["domain"].get("MP", 0), mm_p1)
        self.assertAlmostEqual(roll1["domain"]["DEV"] - roll2["domain"].get("DEV", 0), mm_p1)
        self.assertAlmostEqual(roll1["unattributed"], roll2["unattributed"])

        def content(items):
            return {it["key"]: {k: it["fields"][k] for k in CI.CONTENT_KEY_FIELDS} for it in items}
        self.assertEqual(content(r1.ai_items), content(r2.ai_items))
        self.assertTrue(all(it["fields"]["regv"] == "" for it in r2.ai_items))

    def test_meeting_bucket(self):
        """T-H14 — 과제 키워드가 든 회의 시리즈가 B_MEET(업무 미연결)면 꼬리표는 후보 보조 표시만, 과제 MM·팀 묶음 불변."""
        tpl = next(r for r in synth_rows() if r["kind"] == "cal")
        extra = []
        for d in ("2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28"):
            m = dict(tpl)
            m.update(id=K.fake_key("x", "meet" + d), msg_key=K.fake_key("e", "meet" + d, 24), ts_utc=d + "T07:00:00Z",
                     ts_end=d + "T08:00:00Z", observed_at=d + "T07:00:00Z", subject_masked="브라켓 정례 회의",
                     counterpart_keys=[K.fake_who("m1"), K.fake_who("m2")], n_participants=3)
            extra.append(m)
        cfg = K.cfg()
        reg = K.golden_reg()
        rows = synth_rows(extra)
        feats, trows, tr = time_run(rows, reg, cfg)
        self.assertGreater(tr.bucket_sec().get("B_MEET", 0), 0)
        ids = {m["id"] for m in extra}
        mine = [r for r in trows if r["id"] in ids]
        self.assertEqual(len(mine), 4)
        for r in mine:
            self.assertIsNone(r["proj"])                                      # 키워드만 — 시간 코어 연결 제약 아님
            self.assertEqual(r["top2"][0][0], "P-0007")                        # 개인 보고서 보조 표시 재료
        before = canon_bytes(tr.tables.as_json())
        res = classify_all(run_ctx(cfg, reg, feats, tr))
        self.assertEqual(canon_bytes(tr.tables.as_json()), before)
        self.assertEqual(set(res.labels), {t.id for t in tr.tasks})             # 회의 버킷에는 라벨이 없다
        month = tr.months[(2026, 9)]
        roll = rollup(month, res.rollup_labels())
        p7 = sum(month["units_mm"].get(u, 0.0) for u, lb in res.labels.items() if lb.project == "P-0007")
        self.assertAlmostEqual(roll["project"].get("P-0007", 0.0), p7)
        self.assertAlmostEqual(roll["unattributed"], month["mm"] - sum(month["units_mm"].values()))
        tp = team_parts(res.labels, reg, None, None, cfg=cfg)
        self.assertEqual(set(tp["units"]), set(res.labels))


# ───────────────────────── G-H2 · T-H06 카나리아 ─────────────────────────
class CanaryTest(unittest.TestCase):
    def _canaries(self):
        from tests.fixtures.canary import canaries
        by = {c.cat: c for c in canaries(groups=["ctx"])}
        return by["project"], by["customer"], by["person_dict"]

    def test_all_prompts(self):
        """G-H2 — 코드네임·별칭·mask_name 이름 카나리아가 저장 행에 남아 있어도(검토 전 저장) 프롬프트·전송 필드에 0회."""
        from tests.fixtures.canary import find_canaries
        c_code, c_alias, c_name = self._canaries()
        cs = (c_code, c_alias, c_name)
        team = json.loads(json.dumps(TEAM6))
        team["projects"].append({"id": "P-0097", "name": c_name.value, "mask_name": True, "aliases": [c_alias.value],
                                 "codenames": [c_code.value], "domain": "DEV", "copilot_desc": "광학 모듈 개발"})
        cfg = K.cfg()
        reg = K.golden_reg(team=team)
        rows = synth_rows()
        n = {"mail": 0, "pc_file": 0, "pc_session": 0}
        for r in rows:
            k = r["kind"]
            if k == "mail":
                n[k] += 1
                r["subject_masked"] = [f"{c_code.value} 일정 공유", f"{c_alias.value} 회의 자료",
                                       f"RE: {c_name.value} 검토 요청"][n[k] % 3]
                if r.get("attach_names_masked"):
                    r["attach_names_masked"] = [f"{c_code.value}_사양.xlsx"] + list(r["attach_names_masked"][1:])
            elif k == "pc_file":
                n[k] += 1
                if n[k] % 2:
                    r["name_masked"] = f"{c_code.value}_설계_v2"
            elif k == "pc_session" and r.get("title_masked"):
                n[k] += 1
                if n[k] % 5 == 0:
                    r["title_masked"] = f"{c_alias.value} 검토 - Excel"
        self.assertEqual(len(find_canaries(canon_bytes(rows), cs)), 3)          # 대조 — 재료에는 들어 있다
        feats, _trows, tr = time_run(rows, reg, cfg)
        res = classify_all(run_ctx(cfg, reg, feats, tr, build_ai_in=True))
        items = res.ai_items
        self.assertTrue(items)
        prompts = []
        g29 = GOLD["HG29"]
        batches, _fixed, compact = pack(reg, [it["fields"] for it in items], g29["budget"], (), ())
        prompts += [assemble(reg, bt, compact=compact) for bt in batches]
        samples = CI.build_bootstrap_samples(res.groups, res.rule_labels, reg, cfg, units=res.units, titles=res.titles)
        prompts.append(boot_assemble(reg, [s["fields"] for s in samples]))
        q = PQ.ProposalQueue()
        q.on_new_name(f"{c_alias.value} 후속", "DEV", "grp:000000000001", "bootstrap", reg, cfg=cfg, effort_min=300,
                      at=AT)
        rows_b = [{"name": c_code.value, "code": "", "dom": "DEV", "kind": "project",
                   "match": [c_alias.value, c_name.value, "브라켓"]},
                  {"name": f"{c_name.value} 개선", "code": "", "dom": "MP", "kind": "project", "match": ["수율"]}]
        cons = CI.build_consolidate_items(rows_b, q.items, reg)
        prompts.append("\n".join(CI.prompt_context(reg, CI.CONS_STAGE) + [
            f"{i + 1} | {it['fields']['name']} | {it['fields']['dom']} | {', '.join(it['fields']['match'])}"
            for i, it in enumerate(cons)]))
        prompts.append(canon_bytes([it["fields"] for it in items]).decode("utf-8"))
        prompts.append(canon_bytes([s["fields"] for s in samples]).decode("utf-8"))
        joined = "\n".join(prompts)
        self.assertEqual(find_canaries(joined.encode("utf-8"), cs), [])
        for c in cs:
            self.assertNotIn(c.value.casefold(), joined.casefold())
        self.assertIn("[과제:P-0097]", joined)                                   # 가린 토큰으로는 간다
        self.assertNotIn(c_name.value, "\n".join(CI.prompt_context(reg)))

    def test_codename_review(self):
        """T-H06 — 검토에서 'PROJ-X' 를 [과제 이름] → L-0001(codenames), 그 뒤 프롬프트에 'PROJ-X' 0회·[과제:L-0001] 만."""
        cfg = K.cfg()
        weeks = [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22)]
        feats = []
        for i, d in enumerate(weeks):
            t = day0(d) + 10 * 3600
            feats.append(K.F(f"m{i}", "mail", f"PROJ-X 시험 결과 {i}", t=t, subject=f"PROJ-X 시험 결과 {i}"))
            feats.append(K.F(f"f{i}", "file", f"PROJ-X_결과_{i}.xlsx", t=t,
                             names=((K.fake_doc(f"PROJ-X_결과_{i}"), f"PROJ-X_결과_{i}.xlsx"),)))
        with K.TmpTree() as tt:
            reg0, _st = load_effective(tt.paths, cfg, NOW, folder_key=K.fake_folder, doc_key=K.fake_doc)
            self.assertEqual(B.review_state(reg0), "pending")
            self.assertFalse(B.copilot_allowed(reg0, cfg)[0])
            cands = B.codename_candidates(feats, [], reg0, cfg)
            self.assertIn("PROJ-X", [c.token for c in cands])
            q = PQ.ProposalQueue.for_paths(tt.paths)
            dom = B.domain_vote([f for f in feats if "PROJ-X" in f.text], reg0)
            lid = q.from_codename("PROJ-X", dom, reg0, paths=tt.paths, at=AT)
            self.assertEqual(lid, "L-0001")
            self.assertEqual(q.get("pr_1")["status"], "accepted_local")
            PQ.mark_codename_review(paths=tt.paths, done_at=AT)
            q.save()
            reg1, _st = load_effective(tt.paths, cfg, NOW, folder_key=K.fake_folder, doc_key=K.fake_doc)
        pv = reg1.projects["L-0001"]
        self.assertEqual((tuple(pv.codenames), pv.proposal_id, pv.domain), (("PROJ-X",), "pr_1", "DEV"))
        self.assertTrue(B.copilot_allowed(reg1, cfg)[0])
        self.assertNotIn("PROJ-X", [c.token for c in B.codename_candidates(feats, [], reg1, cfg)])
        u = K.U("u1", "S1", [(f, 1.0, "boundary") for f in feats[:2]], subjects=("PROJ-X 시험 결과 공유",),
                fam_names={"dA": "PROJ-X_결과.xlsx"}, fam_min={"dA": 30}, effort_min=300, kinds={"메일수신": 1})
        g = Group("grp:00000000000x", "a", "u1", ("u1",), 300)
        items, _ = CI.build_task_label_items([g], {"u1": RuleLabel(None, 0.0, "none", "l", (), "UNC")},
                                             {"u1": FieldFunc("OPT", "l", "ANALYSIS", "l")},
                                             {"u1": ("DEV", "m", "")}, {}, reg1, cfg, units={"u1": u},
                                             titles={g.key: ("PROJ-X 결과", "doc")})
        text = "\n".join(CI.prompt_context(reg1) + CI.prompt_context(reg1, CI.BOOT_STAGE)) + \
            item_line(1, items[0]["fields"])
        self.assertNotIn("proj-x", text.casefold())
        self.assertIn("[과제:L-0001]", text)
        self.assertIn("L-0001 · DEV · (설명 없음)", text)


# ───────────────────────── G-H9 프롬프트 크기 ─────────────────────────
class PromptSizeTest(unittest.TestCase):
    def test_registry_0_to_500(self):
        """과제 0~500 개 레지스트리 — 모든 task_label 묶음 ≤ 입력 예산(= bridge.inputMaxChars 기본)."""
        g = GOLD["HG29"]
        b = g["budget"]
        self.assertLessEqual(b["pack_in"], int(K.cfg()["bridge.inputMaxChars"]))
        items = [dict(g["item"]) for _ in range(g["n_items"])]
        for n in (0, 1, 10, 40, 80, 150, 250, 400, 500):
            reg = K.golden_reg(team=K.mk_team(n))
            batches, _fixed, compact = pack(reg, items, b, g["seen"], g["overlap"])
            self.assertEqual(sum(len(x) for x in batches), len(items))
            for bt in batches:
                self.assertLessEqual(len(assemble(reg, bt, seen=g["seen"], overlap=g["overlap"], compact=compact)),
                                     b["pack_in"], (n, len(bt), compact))
            if n >= 250:
                self.assertTrue(compact, n)                                    # 큰 레지스트리는 후보만 싣는다


# ───────────────────────── 설정 읽기(L-12 실행 짝) ─────────────────────────
class CfgReadTest(unittest.TestCase):
    MINE = tuple("lm27.hier." + m for m in ("features", "rules", "unitlabel", "groups", "copilot_io", "apply",
                                             "proposals", "merge", "learn", "queue", "bootstrap", "team_out"))

    def test_owned_keys_read(self):
        reg_keys = json.loads(K.SETTINGS.read_text(encoding="utf-8"))["keys"]
        mine = sorted(k for k, m in reg_keys.items()
                      if (m.get("owner") in self.MINE or set(m.get("readers") or ()) & set(self.MINE))
                      and k.split(".", 1)[0] == "hier")
        self.assertGreater(len(mine), 60)
        c = K.fresh_cfg()
        reg = K.golden_reg(c, team=TEAM6)
        b = base()
        feats, _tags, _rows = prepare(b["rows"], reg, c)
        with K.TmpTree() as t:
            ctx = run_ctx(c, reg, feats, b["tr"], build_ai_in=True, paths=t.paths, persist=True,
                          as_of=date(2026, 9, 30))
            ref = classify_all(dict(ctx, persist=False, paths=None))
            g0 = next(g for g in ref.groups if ref.units[g.rep].convs)
            m0 = g0.rep
            ctx["ai_out"] = {g0.key: {"by": "ai", "ans": {"project": "NEW", "new": "방열 모듈", "dom": "DEV",
                                                          "field": "ETC", "func": "ETC", "wtype": "OFFICE",
                                                          "title": "방열 모듈 설계", "conf": "m"}}}
            corr = {"at": AT, "id": "c1", "scope": "similar", "set": {"project": "P-0002"},
                    "target": {"group": g0.key, "anchor": ref.units[m0].first_key, "unit_keys": [],
                               "fam_keys": [], "conv_keys": sorted(ref.units[m0].convs)[:1], "dir_keys": []}}
            p = t.paths.hier_local_file("corrections.jsonl")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((json.dumps(corr, ensure_ascii=False) + "\n").encode("utf-8"))
            res = classify_all(ctx)
        B.codename_candidates(feats, res.groups, reg, c)
        B.needs_bootstrap(reg, res.labels, None, c, groups=res.groups, as_of=date(2026, 9, 30))
        samples = CI.build_bootstrap_samples(res.groups, res.rule_labels, reg, c, units=res.units, titles=res.titles)
        B.apply_bootstrap([{"name": "방열 모듈", "code": "", "dom": "DEV", "kind": "project", "obs": [1]}], samples,
                          PQ.ProposalQueue(), reg, c)
        team_parts(res.labels, reg, None, None, cfg=c)
        used = set(c.used())
        missing = [k for k in mine if k not in used]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
