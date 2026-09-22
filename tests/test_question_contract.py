import unittest
from types import SimpleNamespace
from resource_planning.teaching_planner import validate_question_coverage


class QuestionContractTests(unittest.TestCase):
    def setUp(self):
        self.story = SimpleNamespace(metadata={'source_subquestions': [
            {'subquestion_id': 'RQ001', 'question': 'A'},
            {'subquestion_id': 'RQ002', 'question': 'B'}]})

    def test_silent_collapse_rejected(self):
        with self.assertRaises(ValueError):
            validate_question_coverage(self.story, {'lesson': [{'subquestion_id': 'RQ001'}]})

    def test_explicit_merge_accepted(self):
        validate_question_coverage(self.story, {'lesson': [{'subquestion_id': 'RQ001'}],
            'subquestion_decisions': [{'subquestion_id': 'RQ001', 'status': 'teach'},
                {'subquestion_id': 'RQ002', 'status': 'merged', 'merged_into': 'RQ001', 'reason': 'shared mechanism'}]})

    def test_insufficient_requires_reason(self):
        with self.assertRaises(ValueError):
            validate_question_coverage(self.story, {'lesson': [{'subquestion_id': 'RQ001'}],
                'subquestion_decisions': [{'subquestion_id': 'RQ001', 'status': 'teach'},
                    {'subquestion_id': 'RQ002', 'status': 'insufficient'}]})

    def test_teach_all(self):
        validate_question_coverage(self.story, {'lesson': [{'subquestion_id': s} for s in ('RQ001', 'RQ002')],
            'subquestion_decisions': [{'subquestion_id': s, 'status': 'teach'} for s in ('RQ001', 'RQ002')]})
