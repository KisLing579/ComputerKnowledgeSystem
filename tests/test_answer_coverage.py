import json
import unittest
from types import SimpleNamespace

from explanation.answer_coverage import check_answer_coverage, coverage_decision
from kg.query import ExplanationPath


class AnswerCoverageTests(unittest.TestCase):
    def test_partial_threshold_does_not_change_verdict(self):
        report = {'status': 'insufficient', 'requirements': ['advantages', 'scenarios'],
                  'checks': [self.verdict(0), self.verdict(1, False, [])]}
        self.assertFalse(coverage_decision(report)['accepted'])
        decision = coverage_decision(report, 'partial', 0.5)
        self.assertTrue(decision['partial_answer'])
        self.assertEqual(decision['missing_requirements'], ['scenarios'])
        self.assertEqual(decision['coverage_ratio'], 0.5)
        self.assertFalse(coverage_decision(report, 'partial', 0.75)['accepted'])
        self.assertEqual(report['status'], 'insufficient')

    def test_partial_does_not_bypass_unavailable_review_or_zero_support(self):
        for status in ['blocked', 'insufficient']:
            report = {'status': status, 'requirements': ['scenarios'],
                      'checks': [self.verdict(0, False, [])]}
            self.assertFalse(coverage_decision(report, 'partial', 0.1)['accepted'])
        for threshold in [0, -0.1, 1.1, float('nan')]:
            with self.assertRaises(ValueError):
                coverage_decision({'status': 'passed'}, 'partial', threshold)

    def check(self, checks, requirements=None):
        replies = iter(([{'requirements': ['A advantages', 'A scenarios']}]
                        if requirements is None else []) + [{'checks': checks}])
        model = SimpleNamespace(invoke=lambda _: {'content': json.dumps(next(replies))})
        path = ExplanationPath(('a', 'b'), ('A', 'B'), ({'type': 'IS_A'},), 1)
        return check_answer_coverage('A advantages and scenarios', [], [path], model,
                                     requirements=requirements)

    def verdict(self, i, supported=True, refs=None):
        return {'requirement_id': i, 'supported': supported,
                'evidence_ids': ['P1'] if refs is None else refs,
                'reason': 'supported' if supported else 'missing scenarios',
                'retrieval_question': 'A application conditions'}

    def test_missing_dimension_is_not_covered_by_existing_paths(self):
        report = self.check([self.verdict(0), self.verdict(1, False, [])])
        self.assertEqual(report['status'], 'insufficient')

    def test_all_requirements_and_valid_evidence_pass(self):
        self.assertEqual(self.check([self.verdict(0), self.verdict(1)])['status'], 'passed')

    def test_missing_or_duplicate_requirement_blocks(self):
        for checks in ([self.verdict(0)], [self.verdict(0), self.verdict(0)]):
            self.assertEqual(self.check(checks)['status'], 'blocked')

    def test_invented_or_empty_citations_block(self):
        for refs in (['invented'], []):
            self.assertEqual(self.check([self.verdict(0, refs=refs), self.verdict(1)])['status'], 'blocked')

    def test_recheck_preserves_original_requirements(self):
        report = self.check([self.verdict(0)], requirements=['original missing dimension'])
        self.assertEqual(report['requirements'], ['original missing dimension'])
        self.assertEqual(report['status'], 'passed')

    def test_model_failure_blocks(self):
        def fail(_):
            raise TimeoutError('private provider body')
        report = check_answer_coverage('question', [], [], SimpleNamespace(invoke=fail))
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['reason'], 'TimeoutError')
        self.assertNotIn('private', json.dumps(report))
