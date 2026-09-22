import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from explanation.path_fusion import PathFusionPlanner
from kg.query import ExplanationPath
from resource_planning import pipeline
from resource_planning.models import StoryPlan


class PipelineGateTests(unittest.TestCase):
    def run_pipeline(self, coverage_reports, teaching_report=None, extra_args=None, prerequisites=False):
        path = ExplanationPath(('a', 'b'), ('A', 'B'), (
            {'id': 'r', 'type': 'IS_A', 'stored_start_id': 'a', 'stored_end_id': 'b'},), 1)
        fused = PathFusionPlanner().fuse('question', [], [path])
        settings = NS(neo4j=None, data=NS(workbook='unused', dependencies_sheet='Knowledge_Dependencies'),
                      resource_planning=NS(max_nodes_per_scene=5),
                      rendering=NS(safe_width=10, safe_height=6))
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch('sys.argv', ['pipeline', 'question', '--out-dir', directory,
                                                   '--teaching', 'llm', '--planning-rounds', '2'] +
                                                   ([] if prerequisites else ['--no-prerequisites']) + (extra_args or [])))
            stack.enter_context(patch.object(pipeline, 'load_settings', return_value=settings))
            for name in ('Neo4jClient', 'RepresentationRegistry', 'AnimationGrammar',
                         'RepresentationBinder', 'VisualStoryPlanner', '_write_json'):
                stack.enter_context(patch.object(pipeline, name))
            layout = stack.enter_context(patch.object(pipeline, 'LayoutEngine'))
            query = stack.enter_context(patch.object(pipeline, 'KGQueryService')).return_value
            query.generate_candidate_paths.return_value = ([], [path])
            fusion = stack.enter_context(patch.object(pipeline, 'PathFusionPlanner')).return_value
            fusion.fuse.return_value = fused
            pipeline.VisualStoryPlanner.return_value.plan.return_value = StoryPlan(
                'question', 'general', (), 0, None)
            stack.enter_context(patch('resource_planning.text_engine.DeepseekModel'))
            coverage = stack.enter_context(patch('explanation.answer_coverage.check_answer_coverage',
                                                 side_effect=coverage_reports))
            teaching = stack.enter_context(patch('resource_planning.teaching_planner.plan_teaching',
                                                  return_value=(None, teaching_report)))
            with self.assertRaises(SystemExit):
                pipeline.main()
            layout.return_value.layout.assert_not_called()
            reports = {p.name: json.loads(p.read_text(encoding='utf-8'))
                       for p in Path(directory).glob('*.json')}
            self.assertNotIn('render_plan.json', reports)
            return query, fusion, coverage, teaching, reports

    def test_insufficient_evidence_retrieves_once_then_stops_before_fusion(self):
        report = {'status': 'insufficient', 'requirements': ['A scenarios'], 'checks': [
            {'supported': False, 'retrieval_question': 'A scenarios'}]}
        query, fusion, coverage, teaching, reports = self.run_pipeline([report, report])
        self.assertEqual(query.generate_candidate_paths.call_count, 2)
        self.assertEqual(coverage.call_args.kwargs['requirements'], ['A scenarios'])
        fusion.fuse.assert_not_called()
        teaching.assert_not_called()
        self.assertEqual(reports['answer_coverage.json']['status'], 'insufficient')

    def test_unavailable_coverage_stops_without_retrieval_retry(self):
        query, fusion, _, _, reports = self.run_pipeline([{'status': 'blocked'}, {'status': 'blocked'}])
        self.assertEqual(query.generate_candidate_paths.call_count, 1)
        fusion.fuse.assert_not_called()

    def test_failed_teaching_stops_before_render(self):
        _, fusion, _, teaching, reports = self.run_pipeline(
            [{'status': 'passed'}], {'mode': 'blocked', 'validation_errors': ['off topic']})
        fusion.fuse.assert_called_once()
        teaching.assert_called_once()
        self.assertEqual(reports['teaching_plan.json']['mode'], 'blocked')
        self.assertEqual(teaching.call_args.kwargs['max_scenes'], 32)

    def test_custom_teaching_scene_budget_is_forwarded(self):
        _, _, _, teaching, _ = self.run_pipeline(
            [{'status': 'passed'}], {'mode': 'blocked'}, ['--max-teaching-scenes', '48'])
        self.assertEqual(teaching.call_args.kwargs['max_scenes'], 48)

    def test_partial_passes_missing_dimensions_to_teaching(self):
        report = {'status': 'insufficient', 'requirements': ['advantages', 'scenarios'], 'checks': [
            {'requirement_id': 0, 'supported': True},
            {'requirement_id': 1, 'supported': False, 'retrieval_question': 'scenarios'}]}
        _, fusion, _, teaching, reports = self.run_pipeline([report, report], {'mode': 'blocked'},
            ['--coverage-policy', 'partial', '--coverage-min-ratio', '0.5'])
        fusion.fuse.assert_called_once()
        contract = teaching.call_args.args[0].metadata['answer_coverage']
        self.assertEqual(contract['missing_requirements'], ['scenarios'])
        self.assertEqual(reports['answer_coverage.json']['status'], 'insufficient')
        self.assertTrue(reports['answer_coverage.json']['decision']['accepted'])
