import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from explanation.planning_retry import repair_evidence
from explanation.planning_retry import replan_subquestions


def verdict(status):
    return {'status': status, 'requirements': ['mechanism'], 'checks': [
        {'requirement_id': 0, 'supported': status == 'passed',
         'retrieval_question': 'missing mechanism', 'reason': 'gap', 'evidence_ids': []}]}


class RetryTests(unittest.TestCase):
    def test_delete_failed_optional_question_preserves_successes(self):
        tasks = [{'subquestion_id': 'ROOT', 'question': 'root'},
                 {'subquestion_id': 'A', 'question': 'save'},
                 {'subquestion_id': 'B', 'question': 'exact stack offset'},
                 {'subquestion_id': 'C', 'question': 'restore'}]
        reports = {'ROOT': verdict('passed'), 'A': verdict('passed'),
                   'B': verdict('insufficient'), 'C': verdict('passed')}
        model = Mock()
        model.invoke.return_value = {'questions': [], 'removed': [
            {'subquestion_id': 'B', 'reason': 'implementation detail unnecessary for original question'}]}
        result, _ = replan_subquestions('root', tasks, reports, [], model, 1)
        self.assertEqual([(q['subquestion_id'], q['question']) for q in result],
                         [('A', 'save'), ('C', 'restore')])

    def test_retry_deletion_reaches_accepted_final_plan(self):
        query = SimpleNamespace(generate_candidate_paths=Mock(return_value=([], [])))
        model = Mock()
        model.invoke.return_value = {'questions': [], 'removed': [
            {'subquestion_id': 'B', 'reason': 'unnecessary detail'}]}
        with patch('explanation.answer_coverage.check_answer_coverage',
                   side_effect=[verdict('passed'), verdict('passed'), verdict('insufficient')]):
            *_, result = repair_evidence('root', [
                {'subquestion_id': 'A', 'question': 'mechanism'},
                {'subquestion_id': 'B', 'question': 'offset'}], [], [], query, model)
        self.assertTrue(result['decision']['accepted'])
        self.assertEqual(len(result['attempts']), 2)
        self.assertEqual([q['subquestion_id'] for q in result['final_subquestions']], ['A'])
        query.generate_candidate_paths.assert_not_called()
    def run_repair(self, reports, proposals=None, **kwargs):
        query = SimpleNamespace(generate_candidate_paths=Mock(return_value=([], [])))
        with patch('explanation.answer_coverage.check_answer_coverage', side_effect=reports) as check:
            model = Mock()
            model.invoke.side_effect = proposals or [
                {'questions': [{'question': 'alternative', 'replaces': ['RQ001'], 'reason': 'available mechanism'}], 'removed': []},
                {'questions': [{'question': 'another alternative', 'replaces': ['RQv1_001'], 'reason': 'available structure'}], 'removed': []}]
            result = repair_evidence('root', [{'subquestion_id': 'RQ001', 'question': 'sub'}],
                [], [], query, model, **kwargs)
        return result[-1], query, check

    def test_failed_subquestion_repairs_without_rechecking_passed_root(self):
        result, query, check = self.run_repair([verdict('passed'), verdict('insufficient'), verdict('passed')])
        self.assertTrue(result['decision']['accepted'])
        self.assertEqual(check.call_count, 3)
        self.assertEqual(query.generate_candidate_paths.call_count, 1)
        self.assertIsNone(check.call_args.kwargs['requirements'])
        self.assertEqual(result['final_subquestions'][0]['question'], 'alternative')
        self.assertEqual(query.generate_candidate_paths.call_args.args[0], 'alternative')
        self.assertTrue(result['attempts'][1]['checks'][0]['reused'])

    def test_three_rounds_then_strict_rejection(self):
        result, query, _ = self.run_repair([verdict('passed')] + [verdict('insufficient')] * 3)
        self.assertFalse(result['decision']['accepted'])
        self.assertEqual(len(result['attempts']), 3)
        self.assertEqual(query.generate_candidate_paths.call_count, 2)
        self.assertEqual(query.generate_candidate_paths.call_args.args[0], 'another alternative')

    def test_unresolved_plan_not_silently_accepted_as_partial(self):
        result, _, _ = self.run_repair([verdict('passed'), verdict('insufficient')], rounds=1, policy='partial')
        self.assertFalse(result['decision']['accepted'])
        self.assertEqual(result['decision']['planning_failure'], 'final_subquestions_unresolved')

    def test_root_obligations_survive_replacement(self):
        result, _, check = self.run_repair([verdict('insufficient'), verdict('insufficient'),
            verdict('insufficient'), verdict('passed')], rounds=2)
        self.assertFalse(result['decision']['accepted'])
        self.assertEqual(check.call_args_list[2].kwargs['requirements'], ['mechanism'])

    def test_invalid_replan_does_not_erase_failed_task(self):
        result, query, _ = self.run_repair([verdict('passed'), verdict('insufficient'), verdict('insufficient')],
            proposals=[{'questions': [], 'removed': []}], rounds=2)
        self.assertFalse(result['decision']['accepted'])
        self.assertEqual(result['final_subquestions'][0]['subquestion_id'], 'RQ001')
        query.generate_candidate_paths.assert_not_called()

    def test_unavailable_review_retries_without_kg_queries(self):
        blocked = {'status': 'blocked', 'requirements': [], 'checks': []}
        result, query, _ = self.run_repair([verdict('passed'), blocked, verdict('passed')])
        query.generate_candidate_paths.assert_not_called()
        self.assertTrue(result['decision']['accepted'])
