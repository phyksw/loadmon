"""Held source evidence must remain held through team reporting; TEMP only."""
import copy
import json
import re
import subprocess
import unittest
import test_reporting_contract as fixtures

AG, REPORT, TAG = fixtures.AG, fixtures.REPORT, fixtures.TAG


class CandidateEvidenceReportingTests(unittest.TestCase):
    setUp = fixtures.ReportingContractTests.setUp
    write_json = fixtures.ReportingContractTests.write_json
    member = fixtures.ReportingContractTests.member
    rows = fixtures.ReportingContractTests.rows
    agentic = fixtures.ReportingContractTests.agentic

    def mixed(self):
        data = self.agentic()
        data['match'][1].update(needs_review=True, kpi_eligible=False)
        data['new'][0].update(needs_review=True, kpi_eligible=False)
        return data

    def test_mixed_normalization_is_idempotent_and_keeps_work_mm(self):
        raw = self.mixed()
        original = copy.deepcopy(raw)
        out = AG.norm_agentic(raw)
        again = AG.norm_agentic(out)
        self.assertEqual(raw, original)
        self.assertEqual(out, again)
        self.assertTrue(out['allocation_verified'])
        self.assertEqual(out['unique_related_work_mm'], 10)
        self.assertAlmostEqual(out['match'][0]['allocated_candidate_mm'], 10 / 3)
        for held in (out['match'][1], out['new'][0]):
            self.assertEqual(held['related_work_mm'], 10)
            self.assertEqual(held['load_mm'], 10)
            self.assertIsNone(held['allocated_candidate_mm'])
            self.assertAlmostEqual(held['review_allocated_candidate_mm'], 10 / 3)
            self.assertTrue(held['needs_review'])

    def test_held_identical_and_cached_names_never_boost_normal_rank(self):
        good = dict(self.agentic()['new'][0], name='Synthetic candidate', kpi_eligible=True)
        held = dict(good, needs_review=True, kpi_eligible=False, allocated_candidate_mm=999)
        cands = REPORT.merge_candidates([{'owner': 'Good', 'new': [good]},
                                          *[{'owner': f'Held{i}', 'new': [held]} for i in range(5)]])
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0]['who'], ['Good'])
        self.assertAlmostEqual(cands[0]['mm'], 10 / 3)
        self.assertEqual(cands[1]['mm'], 0)
        self.assertFalse(cands[1]['allocation_verified'])
        self.write_json(self.share / REPORT.CAND_FILE, {'groups': {'Synthetic candidate': 'Alias'}})
        merged, _ = REPORT.cand_refine(str(self.share), cands)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]['who'], ['Good'])
        self.assertEqual(merged[1]['mm'], 0)
        self.assertTrue(merged[1]['needs_review'])

    def test_full_and_legacy_reports_keep_review_visible_and_workload(self):
        directory, _ = self.member()
        self.rows(directory)
        self.write_json(directory / f'agentic_{TAG}.json', self.mixed())
        members = AG.load_members(str(self.share))
        data = AG.collect_team_data(str(self.share), members)
        self.assertEqual(data['members'][0]['total_mm'], 10)
        body, _, _ = REPORT.render_full(str(self.share), str(self.html), log=lambda _: None)
        self.assertIn('검토 필요 · 후보 순위/안분 합계 제외', body)
        self.assertIn('if(!hit||held(hit))return;', body)
        self.assertIn('held(hit)?"검토 필요"', body)
        script = re.search(r'<script type="application/json" id="lm-team-data">(.*?)</script>', body, re.S)
        self.assertIsNotNone(script)
        embedded = json.loads(script.group(1))
        self.assertIsNone(embedded['agentic'][0]['match'][1]['allocated_candidate_mm'])
        scripts = re.findall(r'<script>(.*?)</script>', body, re.S)
        active = next(s for s in scripts if 'function mmOf' in s)
        start = active.index(' function held')
        stop = active.index(' var pc=')
        js = 'var D=' + json.dumps(embedded) + ';var tasks=D.tasks,ags=D.agentic,exP=new Set(),exC=new Set();'
        js += 'var cell={innerHTML:"",querySelectorAll:()=>[]};var document={getElementById:()=>cell};function E(s){return String(s);}'
        js += active[start:stop] + ';render();process.stdout.write(cell.innerHTML);'
        rendered = subprocess.run(['node', '-e', js], capture_output=True, text=True, encoding='utf-8', check=True).stdout
        summary = re.search(r'<tr class=sumrow>(.*?)</tr>', rendered, re.S).group(1)
        self.assertIn('3.33', summary)
        self.assertNotIn('6.67', summary)
        self.assertEqual(summary.count('1명'), 1)
        self.assertIn('검토 필요', rendered)
        path, _ = AG.build_team_agentic(str(self.share), members)
        from pathlib import Path
        legacy = Path(path).read_text(encoding='utf-8')
        self.assertIn('검토 필요', legacy)
        self.assertIn('안분 미확인', legacy)
        self.assertIn('A(3.33MM)', legacy)
        self.assertNotIn('B(3.33MM)', legacy)

if __name__ == '__main__':
    unittest.main()
