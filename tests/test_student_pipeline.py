from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from explanation.path_fusion import PathFusionPlanner
from kg.config import load_settings
from kg.query import NodeMatch, ExplanationPath
from representation.animation_grammar import AnimationGrammar
from representation.registry import RepresentationRegistry
from resource_planning.binder import RepresentationBinder
from resource_planning.story_planner import VisualStoryPlanner
from resource_planning.teaching_planner import plan_teaching
from student_model.pipeline import adapt_plan, load_states, load_dependencies
from student_model.prerequisites import ExpansionPolicy
from student_model.state import StateStore, StudentNodeState, timestamp


class StudentPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = load_settings()
        cls.edges, cls.catalog, _ = load_dependencies(cls.settings.data)
        cls.registry = RepresentationRegistry(cls.settings.data.workbook)

    def make(self, student_id='S', states=None):
        match = NodeMatch('CO033', '高速缓存', 'Cache', '', 'core', '', 100)
        path = ExplanationPath(('CO033', 'CO040'), ('高速缓存', '主存'), (
            dict(id='test_fact', type='USES', stored_start_id='CO033', stored_end_id='CO040',
                 traversal_from='CO033', traversal_to='CO040'),), 80)
        answer = PathFusionPlanner().fuse('高速缓存', [match], [path]).plan
        retrieval = dict(question='高速缓存', matches=[match], paths=[path])
        plan, report = adapt_plan(answer, [retrieval, retrieval], self.edges, self.catalog,
            states or StateStore(), student_id, as_of=timestamp('2026-09-08T12:00:00Z'),
            policy=ExpansionPolicy())
        story = VisualStoryPlanner().plan(RepresentationBinder(self.registry, AnimationGrammar()).bind(plan))
        return answer, plan, report, story

    def test_real_workbook_unknown_adds_definition_and_preserves_answer(self):
        answer, plan, report, story = self.make()
        self.assertEqual(plan.root_segment.children[-1], answer.root_segment)
        self.assertEqual(report['teaching_node_ids'], ['CO050'])
        self.assertEqual(len(report['subquestions']), 2)
        self.assertEqual(story.scenes[0].metadata['student_action'], 'explain')
        self.assertEqual(story.scenes[0].title, '局部性')
        self.assertNotIn('前置概念', story.scenes[0].narration_summary)
        self.assertEqual(sum(bool(s.metadata.get('prerequisite')) for s in story.scenes), 1)
        self.assertEqual(sum(bool(s.metadata.get('prerequisite_introduction')) for s in story.scenes), 0)

    def test_mastered_changes_actual_story_to_reference(self):
        state = StudentNodeState('S', 'CO050', mastery_prob=.95, uncertainty=.05,
            forgetting_risk=.05, evidence_count=5, state_label='mastered',
            updated_at='2026-09-08T10:31:00Z')
        _, _, _, story = self.make(states=StateStore([state]))
        self.assertEqual(story.scenes[0].scene_role, 'reference')
        self.assertEqual(story.scenes[0].beats[0].narration, '局部性。')

    def test_out_of_chapter_prerequisite_is_not_scheduled(self):
        catalog = {**self.catalog, 'CO050': {**self.catalog['CO050'], 'notes': '本章不展开'}}
        with patch.object(self, 'catalog', catalog):
            answer, plan, report, story = self.make()
        self.assertEqual(plan, answer)
        self.assertEqual(report['teaching_node_ids'], [])
        self.assertTrue(any(x['reason'] == 'outside_chapter_scope' for x in report['omitted']))
        self.assertFalse(any(s.metadata.get('prerequisite') for s in story.scenes))

    def test_llm_cannot_remove_prerequisites(self):
        _, _, _, story = self.make()
        # Exercise the prefix wrapper with an intentionally failed provider.
        class Unavailable:
            def invoke(self, prompt):
                raise RuntimeError('offline')
        result, report = plan_teaching(story, Unavailable())
        self.assertEqual(report['mode'], 'blocked')
        self.assertEqual(result.scenes[0], story.scenes[0])
        self.assertEqual(len(result.scenes), len(story.scenes))

    def test_state_file_requires_matching_student(self):
        with self.assertRaises(ValueError):
            load_states(Path('data/student_model_demo/states.json'), 'missing')

    def test_pipeline_enables_adaptation_after_coverage(self):
        from test_pipeline_gates import PipelineGateTests
        from student_model import pipeline as adapter
        original = adapter.adapt_plan
        with patch.object(adapter, 'load_dependencies', return_value=(self.edges, self.catalog, 'loaded')), \
             patch.object(adapter, 'adapt_plan', wraps=original) as adapt:
            # Existing harness uses synthetic matches; still verify enabled wiring/report.
            harness = PipelineGateTests()
            _, _, _, _, reports = harness.run_pipeline(
                [{'status': 'passed'}], {'mode': 'blocked'}, ['--prerequisite-depth', '2'],
                prerequisites=True)
            adapt.assert_called_once()
            self.assertEqual(reports['prerequisite_plan.json']['policy']['max_depth'], 2)
