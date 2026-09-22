import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from resource_planning.continuity import review_lesson

class ContinuityTests(unittest.TestCase):
    def test_invalid_optional_editor_json_does_not_skip_audit(self):
        data = {'lesson': [{'question': 'A', 'clauses': [{'scene_ids': ['S1'], 'narration': 'A'}]}]}
        model = SimpleNamespace(invoke=__import__('unittest.mock', fromlist=['Mock']).Mock(side_effect=[
            'not json', {'checks': [{'scope': 'question:0', 'pass': True, 'issues': []},
                                  {'scope': 'overall', 'pass': True, 'issues': []}]}]))
        with patch('resource_planning.teaching_planner.apply_teaching'):
            result, report = review_lesson(None, data, {}, model)
        self.assertEqual(result, data)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(model.invoke.call_count, 2)
        self.assertIn('editor_warning', report)
    def run_review(self, edited, checks):
        data = {'lesson': [{'question': 'A', 'clauses': [{'scene_ids': ['S1'], 'narration': 'A'}]}, {'question': 'B', 'clauses': [{'scene_ids': ['S2'], 'narration': 'B'}]}]}
        responses = iter([edited or copy.deepcopy(data), {'checks': checks}])
        import json
        model = SimpleNamespace(invoke=lambda _: {'content': json.dumps(next(responses))})
        with patch('resource_planning.teaching_planner.apply_teaching'):
            return data, review_lesson(None, data, {}, model)

    def test_all_scopes_required(self):
        original, (result, report) = self.run_review(None, [{'scope': 'overall', 'pass': True, 'issues': []}])
        self.assertEqual(result, original)
        self.assertEqual(report['status'], 'fallback')
        self.assertEqual(report['reason'], 'Incomplete review scopes')

    def test_full_review_passes(self):
        checks = [{'scope': s, 'pass': True, 'issues': []} for s in ['question:0', 'question:1', 'boundary:0:1', 'overall']]
        _, (_, report) = self.run_review(None, checks)
        self.assertEqual(report['status'], 'passed')

    def test_failed_boundary_retains_original_and_issues(self):
        checks = [{'scope': s, 'pass': s != 'boundary:0:1', 'issues': ['指代歧义'] if s == 'boundary:0:1' else []} for s in ['question:0', 'question:1', 'boundary:0:1', 'overall']]
        original, (result, report) = self.run_review(None, checks)
        self.assertEqual(result, original)
        self.assertEqual(report['checks'][2]['issues'], ['指代歧义'])

    def test_editor_cannot_change_evidence(self):
        original, (result, report) = self.run_review({'lesson': []}, [])
        self.assertEqual(result, original)
        self.assertEqual(report['status'], 'fallback')

    def test_invalid_edit_still_reviews_original_plan(self):
        checks = [{'scope': s, 'pass': True, 'issues': []} for s in
                  ['question:0', 'question:1', 'boundary:0:1', 'overall']]
        original, (result, report) = self.run_review({'lesson': []}, checks)
        self.assertEqual(result, original)
        self.assertEqual(report['status'], 'passed')
        self.assertIn('editor_warning', report)
