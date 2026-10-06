# -*- coding: utf-8 -*-
r"""WP-22 골든 — H §15.1 HG01~HG46(G-H8 · T-04). 자료 `tests\fixtures\wp22\golden.json`(참조 구현 결과를 HG 로 옮긴 것).

HG29·HG46(프롬프트 예산)은 단계 머리말·답 형식의 고정 문구(골든 자료)에 `copilot_io.prompt_context` 가 만드는
레지스트리·어휘 줄을 끼워 참조 구현과 같은 글자 수가 나오는지 본다 — 패킹은 참조 구현의 단순 패커를 시험 안에서 흉내 낸다.
HG39·HG40·HG43 은 WP-21 모듈(검증기·옛 어휘·kw_hit)을 그대로 부른다(46건 일치 확인을 한곳에서).
"""
import unittest

from lm27.hier import copilot_io as CI
from lm27.hier import groups as G
from lm27.hier import learn as LR
from lm27.hier import merge as MG
from lm27.hier import registry_schema as RS
from lm27.hier.apply import merge_project
from lm27.hier.match import kw_hit
from lm27.hier.names import ukey
from lm27.hier.registry import merge as reg_merge
from lm27.hier.rules import NEG, score_domains, score_projects, tag_rows
from lm27.hier.unitlabel import RuleLabel, ax_link, decide_wtype, field_func, role_id, unit_rule_label
from lm27.hier.vocab import legacy_code
from tests.fixtures.wp22 import hierkit as K

GOLD = K.golden()


def mkfeat(d: dict):
    kw = {}
    if d.get("dom_labels"):
        kw["dom_labels"] = d["dom_labels"]
    if d.get("folders"):
        kw["dir_keys"] = [K.fake_folder(s) for s in d["folders"]]
    for k in ("exts", "app", "app_cat", "conv"):
        if d.get(k):
            kw[k] = d[k]
    return K.F(d["id"], d["kind"], d["text"], **kw)


def mkunit(d: dict):
    ev = [(mkfeat(e["feat"]), float(e["w"]), e["role"]) for e in d["ev"]]
    kw = {k: d[k] for k in ("app_min", "meet_min", "offpc_min", "effort_min") if k in d}
    return K.U(d["id"], d["kind"], ev, **kw)


def tag_of(f, reg, cfg):
    row = next(r for r in tag_rows([f], reg, cfg) if r["id"] == f.id)
    return [row["proj"], row["score"]]


def scores_json(sc: dict) -> dict:
    return {k: ("-inf" if v == NEG else v) for k, v in sc.items()}


def label_json(rl) -> dict:
    return {"project": rl.project, "score": rl.score, "source": rl.source, "conf": rl.conf,
            "cands": [[p, s] for p, s in rl.cands], "domain": rl.domain}


class GoldenTagTest(unittest.TestCase):
    """HG01~HG09 · HG37 — 증거 점수·꼬리표(H §4.3~§4.5)."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = K.cfg()
        cls.reg = K.golden_reg(cls.cfg)

    def test_tags(self):
        for k in ("HG01", "HG02", "HG03", "HG04", "HG07", "HG09"):
            with self.subTest(k=k):
                self.assertEqual(tag_of(mkfeat(GOLD[k]["feat"]), self.reg, self.cfg), GOLD[k]["tag"])

    def test_scores(self):
        for k in ("HG05", "HG06"):
            with self.subTest(k=k):
                sc = score_projects(mkfeat(GOLD[k]["feat"]), self.reg, self.cfg)
                self.assertEqual(scores_json(sc), GOLD[k]["scores"])

    def test_domains(self):
        for k, case in sorted(GOLD["HG08"].items()):
            with self.subTest(k=k):
                f = K.F("x", "mail", case["text"])
                self.assertEqual(score_domains(f, self.reg, self.cfg), case["scores"])

    def test_learned_key_rule(self):
        g = GOLD["HG36"]
        rules = LR.learn_from(g["corr1"], [mkfeat(x) for x in g["feats"]], g["df"], g["n_groups"], [], cfg=self.cfg)
        reg = K.golden_reg(self.cfg, learned=rules)
        self.assertEqual(tag_of(mkfeat(GOLD["HG37"]["feat"]), reg, self.cfg), GOLD["HG37"]["tag"])


class GoldenUnitTest(unittest.TestCase):
    """HG10~HG23 · HG41 · HG44 · HG45 — 단위업무 과제·영역·분야·기능·유형·AX·role_id(H §4.7·§4.8·§10)."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = K.cfg()
        cls.reg = K.golden_reg(cls.cfg)

    def test_rule_labels(self):
        for k in ("HG10", "HG11", "HG12", "HG13", "HG14", "HG15", "HG44"):
            with self.subTest(k=k):
                rl = unit_rule_label(mkunit(GOLD[k]["unit"]), self.reg, self.cfg)
                self.assertEqual(label_json(rl), GOLD[k]["label"])

    def _ff_wt(self, g):
        u = mkunit(g["unit"])
        rl = RuleLabel(g.get("project"), 1.0 if g.get("project") else 0.0, "rule" if g.get("project") else "none",
                       "h", (), g.get("domain", "UNC"))
        ff = field_func(u, self.reg, rl, self.cfg)
        wt = decide_wtype(u, ff, rl, self.reg, self.cfg)
        return ff, wt

    def test_field_func_wtype(self):
        g = GOLD["HG16"]
        ff, wt = self._ff_wt(g)
        self.assertEqual({"field": ff.field, "fconf": ff.field_conf, "func": ff.func, "cconf": ff.func_conf,
                          "wtype": [wt[0], wt[1]]}, g["want"])
        g = GOLD["HG17"]
        ff, wt = self._ff_wt(g)
        self.assertEqual({"field": ff.field, "fconf": ff.field_conf, "func": ff.func, "cconf": ff.func_conf,
                          "wtype": [wt[0], wt[1]]}, g["want"])
        for k in ("HG18", "HG19", "HG20", "HG21", "HG22"):
            with self.subTest(k=k):
                ff, wt = self._ff_wt(GOLD[k])
                self.assertEqual({"func": ff.func, "wtype": [wt[0], wt[1]]}, GOLD[k]["want"])
        ff, _wt = self._ff_wt(GOLD["HG45"])
        self.assertEqual({"field": ff.field, "func": ff.func}, GOLD["HG45"]["want"])

    def test_ax_link(self):
        g = GOLD["HG23"]
        u = mkunit(g["unit"])
        got = {"dev": ax_link(u, "DEV", self.reg, "P-0007", self.cfg), "ax": ax_link(u, "AX", self.reg, "P-0011", self.cfg)}
        self.assertEqual(got, g["want"])

    def test_role_id(self):
        g = GOLD["HG41"]
        self.assertEqual(role_id(*g["args"]), g["role_id"])


class GoldenNamingTest(unittest.TestCase):
    """HG24~HG28 — 명명 군집·규칙 이름(H §5)."""

    def test_groups(self):
        g = GOLD["HG24"]
        rule_labels = {u: {"source": "rule", "project": p} for u, p in g["confirmed"].items()}
        groups = G.name_groups(g["units"], rule_labels, K.cfg())
        got = sorted(sorted(x.members) for x in groups)
        self.assertEqual(got, sorted(g["groups"]))

    def test_titles(self):
        ctx = {"reg": K.golden_reg(K.cfg()), "cfg": K.cfg()}
        for k in ("HG25", "HG26", "HG27", "HG28"):
            with self.subTest(k=k):
                self.assertEqual(list(G.rule_title(GOLD[k]["material"], ctx)), GOLD[k]["title"])


# ───────────────────────── 프롬프트 조립(시험 흉내 — 단계 소유 고정 문구 + prompt_context) ─────────────────────────
def item_line(n: int, it: dict) -> str:
    c = ", ".join(f"{p} {s:.2f}" for p, s in it["cands"]) or "-"
    return (f"{n} | {it['kinds']} | {' / '.join(it['subjects']) or '-'} | {', '.join(it['files']) or '-'} | "
            f"{', '.join(it['apps']) or '-'} | {', '.join(it['domains']) or '-'} | {c} | {it['hint']}")


def assemble(reg, items, rid="R7F3QK", seen=(), overlap=(), compact=False) -> str:
    p = GOLD["prompt"]["task_label"]
    cand = {pc for it in items for pc, _s in it["cands"]}
    parts = [p["first"].replace("{rid}", rid).replace("{n}", str(len(items)))] + list(p["lead"])
    parts += CI.prompt_context(reg, CI.STAGE, compact=compact, cand_codes=cand)
    if seen:
        parts.append("[앞서 쓴 이름] " + " / ".join(seen))
    if overlap:
        parts.append("[참고 — 이미 처리한 항목, 답하지 마세요]")
        parts += list(overlap)
    parts.append(p["cols"])
    parts += [item_line(i + 1, it) for i, it in enumerate(items)]
    parts.append(p["foot"].replace("{rid}", rid).replace("{n}", str(len(items))))
    return "\n".join(parts)


def pack(reg, items, b, seen, overlap):
    batches, cur = [], []
    fixed = len(assemble(reg, [], seen=seen, overlap=overlap))
    compact = b["pack_in"] - fixed < b["pack_in"] * 0.25
    for it in items:
        trial = cur + [it]
        n_in = len(assemble(reg, trial, seen=seen, overlap=overlap, compact=compact))
        if cur and (n_in > b["pack_in"] or b["env"] + b["est_out"] * len(trial) > b["pack_out"]
                    or len(trial) > b["max_items"]):
            batches.append(cur)
            cur = [it]
        else:
            cur = trial
    if cur:
        batches.append(cur)
    return batches, fixed, compact


def boot_assemble(reg, samples, rid="R3KQ7M") -> str:
    p = GOLD["prompt"]["bootstrap"]
    parts = [p["first"].replace("{rid}", rid).replace("{n}", str(len(samples)))] + list(p["lead"])
    parts += CI.prompt_context(reg, "taxonomy_bootstrap")
    parts.append(p["cols"])
    parts += [f"{i + 1} | {s['dom']} | {s['title']} | {', '.join(s['files']) or '-'} | {s['subject'] or '-'} | "
              f"{s['peer'] or '-'}" for i, s in enumerate(samples)]
    parts.append(p["foot"].replace("{rid}", rid))
    return "\n".join(parts)


class GoldenPromptTest(unittest.TestCase):
    """HG29 · HG46 — 프롬프트 예산(H §6.4 · §8.2)."""

    def test_budget(self):
        g = GOLD["HG29"]
        items = [dict(g["item"]) for _ in range(g["n_items"])]
        for n, want in sorted(g["cases"].items(), key=lambda kv: int(kv[0])):
            with self.subTest(n=n):
                reg = reg_merge(K.mk_team(int(n)), None, K.cfg())
                b, fixed, compact = pack(reg, items, g["budget"], g["seen"], g["overlap"])
                full = assemble(reg, b[0], seen=g["seen"], compact=compact)
                got = {"fixed": fixed, "compact": compact, "per_batch": [len(x) for x in b][:3],
                       "first_prompt_chars": len(full), "item_line": len(item_line(1, g["item"]))}
                self.assertEqual(got, want)

    def test_boot_fit(self):
        g = GOLD["HG46"]
        smp = [dict(g["sample"]) for _ in range(g["n_samples"])]

        def fit(reg):
            k = min(len(smp), g["max_lines"])
            while k > 0 and len(boot_assemble(reg, smp[:k])) > g["pack_in"]:
                k -= 1
            return k
        line = f"1 | {g['sample']['dom']} | {g['sample']['title']} | {', '.join(g['sample']['files'])} | " \
               f"{g['sample']['subject']} | {g['sample']['peer']}"
        got = {"empty_registry_lines": fit(K.empty_reg()), "reg10_lines": fit(reg_merge(K.mk_team(10), None, K.cfg())),
               "line_chars": len(line), "header_chars": len(boot_assemble(K.empty_reg(), []))}
        self.assertEqual(got, g["want"])


class GoldenAnswerTest(unittest.TestCase):
    """HG30~HG33 · HG42 — 답 검증·우선순위·재질의(H §6.5·§6.6)."""

    def test_validate(self):
        codes = CI.codes_for(K.golden_reg(K.cfg()))
        for c in GOLD["HG30"]["cases"]:
            with self.subTest(ans=c["ans"]["title"]):
                self.assertEqual(CI.validate_answer(c["ans"], codes, GOLD["HG30"]["ids"]), c["want"])

    def test_priority(self):
        for k in ("HG31", "HG32", "HG33"):
            with self.subTest(k=k):
                self.assertEqual(list(merge_project(GOLD[k]["rule"], GOLD[k]["ai"])), GOLD[k]["want"])

    def test_regv(self):
        g = GOLD["HG42"]

        def reg_of(ids):
            return reg_merge({"schema": "lm27.registry/1", "version": 1,
                              "projects": [{"id": p, "name": "과제" + p[-2:], "domain": "DEV"} for p in ids]}, None, K.cfg())
        regs = {"before": reg_of(g["before"]), "after": reg_of(g["after"])}
        got = [CI.regv_for({"project": c["prev"]}, regs[c["now"]], CI.set_hash(regs[c["reg_at"]].active_ids()))
               for c in g["cases"]]
        self.assertEqual(got, g["regv"])


class GoldenMergeLearnTest(unittest.TestCase):
    """HG34~HG38 — 이름 병합·제약 클러스터·학습·은퇴(H §9 · §11.4)."""

    def test_pair_scores(self):
        g = GOLD["HG34"]
        ctx = MG.MergeCtx(registry_ids={ukey(k): v for k, v in g["registry_names"].items()},
                          ai_pairs=frozenset(frozenset((ukey(a), ukey(b))) for a, b in g["ai_pairs"]))
        for c in g["cases"]:
            with self.subTest(a=c["a"], b=c["b"]):
                s, why = MG.pair_score(c["a"], c["b"], ctx)
                got = {"score": "-inf" if s == NEG else s, "zone": MG.zone(s, K.cfg()), "why": why}
                self.assertEqual(got, c["want"])

    def test_cluster(self):
        names = GOLD["HG35"]["names"]
        W = MG.pair_weights(names)
        self.assertEqual(MG.cluster(names, W, sorted(names)), GOLD["HG35"]["clusters"])

    def test_learn(self):
        g = GOLD["HG36"]
        feats = [mkfeat(x) for x in g["feats"]]
        r1 = LR.learn_from(g["corr1"], feats, g["df"], g["n_groups"], [], cfg=K.cfg())
        self.assertEqual([[r["id"], r["status"], r["support"]] for r in r1], g["learn1"])
        r2 = LR.learn_from(g["corr2"], feats, g["df"], g["n_groups"], r1, cfg=K.cfg())
        self.assertEqual([[r["id"], r["status"], r["support"]] for r in r2], g["learn2"])

    def test_retire(self):
        g = GOLD["HG38"]
        st, prec = LR.retire_check(g["agree"], g["disagree"], "active", K.cfg())
        self.assertEqual([st, prec], g["want"])


class GoldenRegistryVocabTest(unittest.TestCase):
    """HG39 · HG40 · HG43 — 레지스트리 검증·옛 어휘·kw_hit 경계(WP-21 모듈)."""

    def test_validate_registry(self):
        g = GOLD["HG39"]
        got = {(e.path, e.code) for e in RS.validate_registry(g["input"], "server")}
        self.assertEqual(got, {tuple(x) for x in g["validate"]})

    def test_legacy(self):
        g = GOLD["HG40"]
        self.assertEqual([legacy_code(n, k) for n, k in g["input"]], g["codes"])

    def test_kw_hit(self):
        for k, toks, mode, want in GOLD["HG43"]["cases"]:
            with self.subTest(k=k):
                self.assertEqual(kw_hit(k, set(toks), mode), want)


class GoldenCountTest(unittest.TestCase):
    def test_46(self):
        """골든 자료가 HG01~HG46 을 빠짐없이 담는다(G-H8)."""
        have = {k[:4] for k in GOLD if k.startswith("HG")}
        self.assertEqual(have, {f"HG{i:02d}" for i in range(1, 47)})


if __name__ == "__main__":
    unittest.main()
