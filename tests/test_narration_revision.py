import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import test_teaching
from resource_planning.narration_revision import revise_narration
from resource_planning.teaching_planner import apply_teaching


class RevisionTests(unittest.TestCase):
    def setUp(self):
        fixture = test_teaching.TeachingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.source = fixture.story
        self.plan = {'lesson': [{'question': 'How?', 'clauses': [
            {'scene_ids': [s.story_scene_id], 'narration': 'Supported explanation.'}
            for s in self.source.scenes]}]}
        self.taught = apply_teaching(self.source, self.plan)
        self.report = {'mode': 'llm', 'plan': self.plan}

    def run_flow(self, responses, retrieve=None):
        model = SimpleNamespace(invoke=Mock(side_effect=responses))
        with tempfile.TemporaryDirectory() as d:
            with patch('resource_planning.narration_revision.review_lesson',
                       side_effect=lambda s, p, e, m: (p, {'status': 'passed'})):
                result = revise_narration(self.source, self.taught, self.report, model, Path(d), retrieve)
            audit = json.loads((Path(d) / 'teaching_revision_report.json').read_text())
        return result, audit, model

    def test_pass_never_retrieves_or_rewrites(self):
        retrieve = Mock()
        (story, _), report, model = self.run_flow([{'verdict': 'pass', 'edits': [], 'evidence_requests': []}], retrieve)
        self.assertIs(story, self.taught)
        retrieve.assert_not_called()
        self.assertEqual(model.invoke.call_count, 1)
        self.assertEqual(report['status'], 'passed_without_revision')

    def test_revision_acceptance_and_rejection(self):
        review = {'verdict': 'revise', 'edits': [{'action': 'rewrite'}], 'evidence_requests': []}
        for accepted in (True, False):
            (story, _), report, model = self.run_flow([review, self.plan,
                {'pass': accepted, 'issues': [] if accepted else ['Lost explanation']}])
            self.assertEqual(report['status'], 'accepted' if accepted else 'kept_original')
            if not accepted:
                self.assertIs(story, self.taught)
            self.assertEqual(model.invoke.call_count, 3)

    def test_provider_failure_preserves_valid_original(self):
        (story, _), report, _ = self.run_flow([RuntimeError('provider private details')])
        self.assertIs(story, self.taught)
        self.assertEqual(report['reason'], 'RuntimeError')
        self.assertNotIn('private', json.dumps(report))

    def test_targeted_retrieval_runs_once(self):
        from dataclasses import replace
        self.source = replace(self.source, metadata={**self.source.metadata,
            'source_subquestions': [{'subquestion_id': 'Q1', 'question': 'How?'}]})
        retrieve = Mock(return_value=(self.source, [{'new_paths': 0}]))
        review = {'verdict': 'revise', 'edits': [], 'evidence_requests': [
            {'subquestion_id': 'Q1', 'missing_claim': 'Required process', 'reason': 'Missing explanation'}]}
        (story, _), report, _ = self.run_flow([review, RuntimeError('rewrite unavailable')], retrieve)
        retrieve.assert_called_once_with(review['evidence_requests'])
        self.assertEqual(report['retrieval_rounds'], 1)
        self.assertIs(story, self.taught)
