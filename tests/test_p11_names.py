# -*- coding: utf-8 -*-
r"""test_p11_names.py — LM28 진단 B: 과제명 관문(사람 이름·채팅방·공지류)과 큰 분류(Level 1) 채움.

core\details 의 관문 함수(person_keys·is_person_name·is_notice_name·is_notice_subject·task_name_ok·level1_fill·
entities 판별)와 그것을 쓰는 judge(sanitize_models·final_model·fallback_models·apply_merges·_load_prev_entities·
write_outputs·rehours_meta·프롬프트)·extract(규칙 후보·웹 경로 공지 메일·to_rows 상위)·mine.known_projects·refine 관문을
같은 프로세스에서 본다. 실 Outlook·Copilot 은 쓰지 않는다. 이름은 합성(홍길동·김철수·이영희·John Smith·Alpha-X·프로젝트A).
judge.main 수준(체계·판정 흐름)은 다른 시험이 본다."""
import contextlib
import csv
import io
import json
import os
import tempfile
import time
import unittest
from collections import Counter
from datetime import date, datetime
from unittest import mock

import _boot  # noqa: F401

import details  # noqa: E402
import extract  # noqa: E402

WHOS = ["홍길동/책임/Alpha개발팀", "김철수 선임", "John Smith", "나", "hong@corp.example"]
K = details.ukey2
D0, D1 = date(2026, 10, 1), date(2026, 10, 7)
MAIL_HDR = ["box", "time", "sender", "subject", "conversation", "rcv", "time_precision", "src"]
NOTICE_KEY = "공지·근태 메일(제목 — 웹 경로는 단체발송 구분 불가)"


def _keys():
    return details.person_keys(WHOS)


def _write_json(path, obj, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


# ════════════════════════════════ details 관문 ════════════════════════════════
class Guards(unittest.TestCase):
    def test_person_keys_and_guards(self):
        keys = _keys()
        self.assertLessEqual({K("홍길동"), K("김철수"), K("john smith")}, keys)
        self.assertFalse(any("alpha" in k for k in keys))                  # 부서 조각은 키가 아니다
        for nm in ("홍길동", "홍길동 책임", "Alpha-X 홍길동", "홍길동님 요청", "John Smith"):
            self.assertTrue(details.is_person_name(nm, keys), nm)
        self.assertTrue(details.is_person_name("[사람] 요청"))               # 가림 토큰
        self.assertTrue(details.is_person_name("이영희 책임"))               # 키 없이도 '이름 + 호칭'
        for nm in ("Alpha-X", "설계 검토", "프로젝트 매니저", "구매팀 과장"):
            self.assertFalse(details.is_person_name(nm, keys), nm)
        k2 = details.person_keys(["Smith, John (Alpha)", "개발팀 김철수", "Alpha개발팀", "(상대)", "인사팀", "시스템"])
        self.assertLessEqual({K("john smith"), K("smith john"), K("김철수")}, k2)
        self.assertFalse(any("alpha" in k or "인사" in k for k in k2))
        self.assertNotIn(K("시스템"), k2)                                     # 사람이 아닌 표시 이름
        self.assertTrue(details.is_person_name("홍길동, 김철수", keys))        # 사람 이름으로 된 채팅방
        self.assertFalse(details.is_person_name("판정 시스템", k2))

    def test_notice_name_and_subject(self):
        for nm in ("근태공지", "인사발령", "근태 관리", "10월 근태", "공지·근태", "Newsletter"):
            self.assertTrue(details.is_notice_name(nm), nm)
        for nm in ("인사시스템 개선", "공통", "Alpha-X", "제품 안내서", "전사적 자원관리"):
            self.assertFalse(details.is_notice_name(nm), nm)
        for s in ("[근태공지] 10월 근태 마감 안내", "RE: [인사] 조직 개편", "부고 알림", "사내 뉴스레터 10월호",
                  "건강검진 안내", "(공지) 사무실 이전", "인사발령 통보"):
            self.assertTrue(details.is_notice_subject(s), s)
        for s in ("[안내] Alpha-X 회의실 변경", "[알림] 빌드 완료", "Alpha-X 설계 검토", "인사이트 공유", ""):
            self.assertFalse(details.is_notice_subject(s), s)

    def test_task_name_ok(self):
        keys = _keys()
        self.assertTrue(details.task_name_ok("Alpha-X", keys))
        self.assertFalse(details.task_name_ok("홍길동", keys))
        self.assertFalse(details.task_name_ok("근태공지", keys))
        self.assertFalse(details.task_name_ok("", keys))
        self.assertTrue(details.task_name_ok("홍길동", keys, pinned=["홍길동"]))       # 지정은 늘 통과
        self.assertTrue(details.task_name_ok("홍길동", keys, pinned={K("홍길동")}))


class Level1(unittest.TestCase):
    def test_level1_fill(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p11_") as root:      # config 없는 루트 — 규칙 기본값만
            fill = details.level1_fill
            k = K("Alpha-X")
            self.assertEqual(fill("공통", "기타", root=root), "공통")
            self.assertEqual(fill("Alpha-X", "회로 설계", {k: "개발"}, root=root), "개발")
            self.assertEqual(fill("Alpha-X", "x", {k: "개발"}, pin={k: "양산"}, root=root), "양산")
            self.assertEqual(fill("홍길동", "기타", root=root), "")
            self.assertEqual(fill("공통", "기타", {K("공통"): "AX"}, root=root), "공통")    # '공통' 과제는 l1 표를 보지 않는다
            self.assertEqual(fill("프로젝트A", "보안교육", root=root), "공통")              # 규칙(영역 키워드)
        lines = details.l1_def_lines("  ")
        self.assertEqual(len(lines), len(details.L1_META))
        self.assertTrue(all(ln.startswith("  · ") for ln in lines))

    def test_entities_fallback_check(self):
        self.assertTrue(details.entities_is_fallback({"fallback": True, "models": [{"name": "Alpha-X", "l1": "개발"}]}))
        self.assertTrue(details.entities_is_fallback({"models": [{"name": "근태공지", "match": ["근태공지"]},
                                                                {"name": "공통", "match": []}]}))   # 옛 폴백(흔적 없음)
        self.assertFalse(details.entities_is_fallback({"models": [{"name": "Alpha-X", "match": ["alphax"],
                                                                  "obs": "설계 검토 메일"}]}))


# ════════════════════════════════ judge ════════════════════════════════
class JudgeNames(unittest.TestCase):
    def test_sanitize_and_final_model(self):
        import judge
        keys = _keys()
        out = judge.sanitize_models([{"name": "홍길동"}, {"name": "근태공지"}, {"name": "Alpha-X", "l1": "선행"},
                                     {"name": "김철수", "pinned": True}, {"name": "보고서"}], people=keys)
        self.assertEqual([m["name"] for m in out], ["Alpha-X", "김철수", "공통"])
        self.assertEqual(out[0]["l1"], "개발")                                # 상위는 고정 범주로 스냅
        models = [{"name": "Alpha-X", "match": ["alphax"]}, {"name": "공통", "match": []}]
        fm = judge.final_model
        self.assertEqual(fm("홍길동", models, keys, set()), "공통")
        self.assertEqual(fm("근태공지", models, keys, set()), "공통")
        self.assertEqual(fm("alpha-x", models, keys, set()), "Alpha-X")
        self.assertEqual(fm("NewProj", models, keys, set()), "NewProj")       # 새 과제 발견은 그대로
        self.assertEqual(fm("보고서", models, keys, set()), "공통")            # 상투어
        self.assertEqual(fm("V2X", models, keys, set()), "V2X")               # 대문자 코드는 버전 꼴이 아니다
        self.assertEqual(fm("v2", models, keys, set()), "공통")
        self.assertEqual(fm("", models), "공통")
        self.assertEqual(fm("홍길동", models, keys, {K("홍길동")}), "홍길동")   # 지정은 통과
        self.assertEqual(fm("근태공지", models + [{"name": "근태공지", "match": []}], keys, set()), "공통")

    def test_fallback_models_clean(self):
        import judge
        keys = _keys()
        rows = ([{"project": "홍길동"}] * 5 + [{"project": "근태공지"}] * 3 + [{"project": "alphax"}] * 3
                + [{"project": "radarq"}] * 2 + [{"project": "미지정"}] * 4)
        fb = judge.fallback_models(rows, [], keys, [{"name": "Alpha-X", "match": ["alpha-x"], "l1": "개발"}])
        names = [m["name"] for m in fb]
        self.assertIn("Alpha-X", names)
        self.assertIn("radarq", names)
        self.assertIn("공통", names)
        for bad in ("홍길동", "근태공지", "미지정"):
            self.assertNotIn(bad, names)
        lx = next(m for m in fb if m["name"] == "Alpha-X")
        self.assertIn("alphax", lx["match"])                                 # 같은 과제의 규칙 토큰은 매칭어로 합친다
        self.assertEqual(lx["l1"], "개발")
        self.assertTrue(all(m.get("obs") == "규칙 폴백" for m in fb))
        self.assertIn("Alpha-X", [m["name"] for m in judge.fallback_models(rows, [], keys, ["Alpha-X"])])
        self.assertIn("공통", [m["name"] for m in judge.fallback_models(rows, ["프로젝트A"])])   # 옛 호출 형태

    def test_apply_merges_keeps_product_l1(self):
        import judge
        draft = [{"name": "Alpha-X", "product": "제품X"}, {"name": "Alpha X 2차", "l1": "양산"}]
        cand = [{"name": "Alpha-X", "match": ["alphax"], "merged": ["Alpha X 2차"]}, {"name": "공통", "match": []}]
        out = judge.apply_merges(cand, draft)
        self.assertEqual((out[0]["product"], out[0]["l1"]), ("제품X", "양산"))
        self.assertIn("alpha x 2차", out[0]["match"])
        self.assertNotIn("product", judge.apply_merges(cand)[0])            # 초안 없이 부르면 예전 그대로

    def test_prev_entities_skip_fallback(self):
        import judge
        with tempfile.TemporaryDirectory(prefix="lm28_p11_rep_") as rep:
            now = time.time()
            _write_json(os.path.join(rep, "entities_20260101-20260930.json"), {"models": [
                {"name": "Alpha-X", "match": ["alphax"], "obs": "설계 검토 메일", "l1": "개발"},
                {"name": "홍길동", "match": ["홍길동"], "obs": "판정 중 발견"},
                {"name": "프로젝트A", "match": ["proja"], "pinned": True}, {"name": "공통", "match": []}]}, now - 300)
            _write_json(os.path.join(rep, "entities_20260101-20261005.json"),
                        {"fallback": True, "models": [{"name": "radarq", "match": ["radarq"], "obs": "규칙 폴백"}]},
                        now - 200)
            _write_json(os.path.join(rep, "entities_20260101-20261006.json"),     # 옛 폴백(표식 없음·흔적 없음)
                        {"models": [{"name": "근태공지", "match": ["근태공지"]}, {"name": "공통", "match": []}]}, now - 100)
            models, path = judge._load_prev_entities(rep, _keys())
        self.assertTrue(path.endswith("entities_20260101-20260930.json"), path)
        self.assertEqual([m["name"] for m in models], ["Alpha-X", "프로젝트A", "공통"])
        self.assertEqual(models[0]["l1"], "개발")
        self.assertFalse(any(m.get("pinned") for m in models))               # 옛 지정 표식은 뗀다
        with tempfile.TemporaryDirectory(prefix="lm28_p11_rep_") as rep:
            self.assertEqual(judge._load_prev_entities(rep), ([], ""))

    def test_prompts(self):
        import judge
        p = judge.judge_prompt([], 0, [{"name": "공통", "match": []}])
        self.assertIn("사람 이름·호칭·부서·채팅방 이름은 과제가 아니다", p)
        self.assertIn("근태·인사·발령·공지·교육 안내는 과제가 아니다", p)
        t = judge.taxonomy_prompt([], [], ())
        self.assertIn("models 에 넣지 말 것", t)
        for n in details.L1_META:
            self.assertIn(f"· {n} = ", t)
        ex = json.loads(judge.TAXONOMY_EXAMPLE)
        self.assertEqual([m.get("l1") for m in ex["models"]], [next(iter(details.L1_META)), details.snap1("공통")])
        self.assertIn(judge.TAXONOMY_EXAMPLE, t)

    def test_write_outputs_level1(self):
        import judge
        tag = "20260901-20260901"
        with tempfile.TemporaryDirectory(prefix="lm28_p11_root_") as root:
            rep = os.path.join(root, "report")
            _write_json(os.path.join(rep, f"mm_meta_{tag}.json"), {"total_mm": 0.05})
            _write_json(os.path.join(rep, f"entities_{tag}.json"),
                        {"models": [{"name": "Alpha-X", "match": ["alphax"], "l1": "양산"}, {"name": "공통", "match": []}]})
            _write_json(os.path.join(root, "config", "projects.json"), [{"name": "프로젝트A", "match": [], "level1": "AX"}])
            kept = [{"time": "2026-09-01 09:00", "source": "파일", "text": "a.dwg", "weight": "3", "model": "Alpha-X",
                     "detail": "설계", "worktype": "개발"},
                    {"time": "2026-09-01 10:00", "source": "메일(수신)", "text": "x", "weight": "1", "model": "공통",
                     "detail": "기타", "worktype": "사무"},
                    {"time": "2026-09-01 11:00", "source": "메일(수신)", "text": "y", "weight": "1", "model": "프로젝트A",
                     "detail": "검토", "worktype": "사무"}]
            with mock.patch.object(judge, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                judge.write_outputs(kept, tag, {}, rep)
            with open(os.path.join(rep, f"mm_rows_{tag}.csv"), encoding="utf-8-sig") as f:
                by = {r["Level 2"]: r["Level 1"] for r in csv.DictReader(f)}
        self.assertEqual(by, {"Alpha-X": "양산", "공통": "공통", "프로젝트A": "AX"})

    def test_rehours_meta_time_kept(self):
        import judge
        tag = "20260901-20260901"

        def fake(*_a, **_k):
            return {"total_mm": 0.04, "avail_mm": 0.05, "day_hours": {"2026-09-01": 6.0}, "time_kept_n": 3}
        with tempfile.TemporaryDirectory(prefix="lm28_p11_rep_") as rep:
            _write_json(os.path.join(rep, f"mm_meta_{tag}.json"), {"total_mm": 0.05, "period": ["2026-09-01", "2026-09-01"]})
            dropped = [{"time": "2026-09-01 10:00", "source": "메일(수신)", "text": "x", "weight": "1"}]
            with mock.patch.object(extract, "rehours_after_judge", fake):
                rh = judge.rehours_meta([], dropped, tag, {}, rep, rep, say=lambda *_a: None)
            with open(os.path.join(rep, f"mm_meta_{tag}.json"), encoding="utf-8") as f:
                mj = json.load(f)
        self.assertEqual((rh["ai_n_time_kept"], mj["ai_n_time_kept"]), (3, 3))


# ════════════════════════════════ extract · mine ════════════════════════════════
class RuleTokens(unittest.TestCase):
    @staticmethod
    def _sig():
        t = datetime(2026, 9, 1, 9, 0)
        sig = [(t, "팀즈(수신)", "홍길동 alphax 일정 공유", 0.4, "홍길동")] * 4
        sig += [(t, "팀즈(수신)", "홍길동 회신 드립니다", 0.4, "홍길동")] * 2
        sig += [(t, "메일(수신)", "[근태공지] 마감", 1.0, "인사팀")] * 3
        sig += [(t, "파일", f"note{i}", 3.0, "나") for i in range(9)]
        return sig

    def test_rule_tokens_skip_people_and_notice(self):
        items, assigns = extract.build_items2(self._sig(), None, min_w=0.0)
        projs = {a[5] for a in assigns} | {p for p, _a in items}
        self.assertIn("alphax", projs)
        self.assertNotIn("홍길동", projs)
        self.assertNotIn("근태공지", projs)
        # 관문을 끄면 같은 신호에서 사람 이름·공지가 과제가 된다 — 시험 신호가 관문을 실제로 겨누는지 확인
        with mock.patch.object(extract, "_name_guard", lambda _s: (lambda _x: True)):
            _items, assigns2 = extract.build_items2(self._sig(), None, min_w=0.0)
        self.assertLessEqual({"홍길동", "근태공지"}, {a[5] for a in assigns2})

    def test_to_rows_level1(self):
        def it(w):
            return {"w": w, "ev": [], "src": Counter({"파일": 1}), "days": {date(2026, 9, 1)}}
        items = {("Alpha-X", "설계"): it(3.0), ("공통", "기타"): it(1.0), ("프로젝트A", "검토"): it(1.0)}
        rows = extract.to_rows(items, 1.0, l1_map={K("Alpha-X"): "개발", K("프로젝트A"): "개발"},
                               pin={K("프로젝트A"): "양산"})
        by = {r["Level 2"]: r["Level 1"] for r in rows}
        self.assertEqual((by["Alpha-X"], by["공통"], by["프로젝트A"]), ("개발", "공통", "양산"))
        self.assertEqual(extract.to_rows(items, 1.0)[0]["Level 2"], "Alpha-X")    # 옛 호출 형태


class WebNoticeMail(unittest.TestCase):
    def test_web_notice_subject_excluded(self):
        rows = [
            ["inbox", "2026-10-05 09:00:00", "kim@corp.example", "[근태공지] 10월 근태 마감 안내",
             "[근태공지] 10월 근태 마감 안내", "to", "minute", "owa"],
            ["inbox", "2026-10-05 10:00:00", "kim@corp.example", "[근태공지] 10월 근태 마감 안내",
             "[근태공지] 10월 근태 마감 안내", "to", "minute", "com"],
            ["sent", "2026-10-05 11:00:00", "tester", "[근태공지] 10월 근태 마감 확인", "[근태공지] 10월 근태 마감 확인",
             "", "minute", "owa"],
            ["inbox", "2026-10-05 12:00:00", "kim@corp.example", "RE: [근태공지] 10월 근태 마감 확인",
             "[근태공지] 10월 근태 마감 확인", "to", "minute", "owa"],
            ["inbox", "2026-10-05 13:00:00", "lee@corp.example", "Alpha-X 설계 검토", "Alpha-X 설계 검토",
             "to", "minute", "owa"],
        ]
        with tempfile.TemporaryDirectory(prefix="lm28_p11_data_") as data:
            p = os.path.join(data, "outlook", "mail.csv")
            os.makedirs(os.path.dirname(p))
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(MAIL_HDR)
                w.writerows(rows)
            cfg = {"owner": "tester", "mm": {}, "noticeSenders": ["no-reply"]}
            with contextlib.redirect_stdout(io.StringIO()):
                sig, meta = extract.load_signals(data, D0, D1, (), cfg)
        self.assertEqual(meta["excluded"].get(NOTICE_KEY), 1)
        got = [(s[0].hour, s[2]) for s in sig if s[1].startswith("메일")]
        hours = [h for h, _t in got]
        self.assertNotIn(9, hours)                       # 웹 경로 공지(회신 없음) — 제외
        self.assertIn(10, hours)                         # COM 은 단체발송 구분이 되므로 제목으로 거르지 않는다
        self.assertIn(12, hours)                         # 내가 회신한 대화 — 남긴다
        self.assertIn(13, hours)


class KnownProjects(unittest.TestCase):
    def test_known_projects_skip_fallback_and_people(self):
        import mine
        with tempfile.TemporaryDirectory(prefix="lm28_p11_root_") as root:
            rep = os.path.join(root, "report")
            now = time.time()
            _write_json(os.path.join(rep, "entities_20260101-20260930.json"), {"models": [
                {"name": "Alpha-X", "match": ["alphax"], "obs": "설계 검토 메일", "l1": "개발"},
                {"name": "김철수", "match": ["김철수"], "obs": "판정 중 발견"},
                {"name": "근태공지", "match": ["근태공지"], "obs": "판정 중 발견"}, {"name": "공통", "match": []}]},
                now - 200)
            _write_json(os.path.join(rep, "entities_20260101-20261005.json"),
                        {"fallback": True, "models": [{"name": "홍길동", "match": ["홍길동"], "obs": "규칙 폴백"}]},
                        now - 100)
            _write_json(os.path.join(root, "config", "projects.json"),
                        [{"name": "프로젝트A", "match": ["proja"], "level1": "양산"}])
            with mock.patch.object(mine, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                kp = mine.known_projects({"projects": ["RadarQ"]}, details.person_keys(["홍길동/책임", "김철수 선임"]))
        by = {p["name"]: p for p in kp}
        self.assertEqual(list(by), ["RadarQ", "프로젝트A", "Alpha-X"])
        self.assertEqual((by["Alpha-X"]["l1"], by["Alpha-X"]["pinned"]), ("개발", False))
        self.assertEqual((by["프로젝트A"]["l1"], by["프로젝트A"]["pinned"]), ("양산", True))
        sig = [(datetime(2026, 9, 1, 9, 0), "메일(수신)", "alphax 회로 검토", 1.0, "김철수 선임")]
        _items, assigns = extract.build_items2(sig, kp, min_w=0.0)       # dict 항목도 규칙 기준선으로 받는다
        self.assertEqual(assigns[0][5], "Alpha-X")


class RefineGuard(unittest.TestCase):
    def test_guard_lv2(self):
        import refine
        keys = _keys()
        g = refine._guard_lv2
        self.assertEqual(g("홍길동", lambda: "Alpha-X", keys), "Alpha-X")         # 사람 이름 → 원본 다수결
        self.assertEqual(g("근태공지", lambda: "김철수", keys), "공통")           # 다수결도 사람 → 공통
        self.assertEqual(g("Alpha-X", lambda: self.fail("통과 이름에 다수결을 부르면 안 된다"), keys), "Alpha-X")
        self.assertEqual(g("홍길동", lambda: "x", keys, ["홍길동"]), "홍길동")      # 지정은 통과
        self.assertEqual(g("미지정", lambda: "x", keys), "미지정")


if __name__ == "__main__":
    unittest.main()
