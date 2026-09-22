import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_representation_v2 import WORKBOOK
from explanation.path_fusion import PathFusionPlanner
from kg.query import ExplanationPath
from representation.registry import RepresentationRegistry
from resource_planning.binder import RepresentationBinder
from resource_planning.story_planner import VisualStoryPlanner
from resource_planning.teaching_planner import plan_teaching
from rendering.layout.engine import LayoutEngine


class TeachingTests(unittest.TestCase):
    def setUp(self):
        review = patch('resource_planning.continuity.review_lesson',
                       side_effect=lambda story, data, evidence, model: (data, {'status': 'passed'}))
        review.start()
        self.addCleanup(review.stop)
        relations = [dict(id=f"r{i}", type=kind, stored_start_id="CO011",
                          stored_end_id="CO012") for i, kind in enumerate(("USES", "TRANSFORMS_TO"))]
        fused = PathFusionPlanner().fuse("test", [], [
            ExplanationPath(("CO011", "CO012"), ("A", "B"), (r,), 80) for r in relations])
        rep = RepresentationBinder(RepresentationRegistry(WORKBOOK)).bind(fused.plan)
        self.story = VisualStoryPlanner().plan(rep)
        self.data = {"paragraphs": [{"title": "Combined", "narration": "A connected explanation.",
            "scene_ids": [s.story_scene_id for s in self.story.scenes],
            "evidence_relation_ids": [r for s in self.story.scenes for r in s.relation_ids]}]}

    def model(self, data):
        return SimpleNamespace(invoke=lambda prompt: {"content": json.dumps(data)})

    def test_rules_are_unchanged(self):
        result, report = plan_teaching(self.story)
        self.assertIs(result, self.story)
        self.assertEqual(report["mode"], "rules")

    def test_large_lesson_uses_configurable_total_scene_budget(self):
        from dataclasses import replace
        scenes = tuple(replace(self.story.scenes[0], story_scene_id=f'T{i}',
            beats=tuple(replace(b, beat_id=f'T{i}B{j}')
                        for j, b in enumerate(self.story.scenes[0].beats))) for i in range(27))
        story = replace(self.story, scenes=scenes)
        data = {'lesson': [{'question': 'How?', 'clauses': [
            {'scene_ids': [s.story_scene_id], 'narration': 'An evidence-backed step.'}
            for s in scenes]}], 'excluded_scenes': []}
        result, report = plan_teaching(story, self.model(data))
        self.assertEqual(report['mode'], 'llm')
        self.assertEqual(len(result.scenes), 27)
        _, report = plan_teaching(story, self.model(data), max_scenes=27)
        self.assertEqual(report['mode'], 'llm')
        _, report = plan_teaching(story, self.model(data), max_scenes=26)
        self.assertEqual(report['mode'], 'blocked')
        self.assertIn('1-26', report['validation_errors'][0])

    def test_invalid_scene_budget_is_rejected(self):
        for limit in (0, -1, True, 1.5):
            with self.assertRaisesRegex(ValueError, 'positive integer'):
                plan_teaching(self.story, max_scenes=limit)

    def test_prompt_example_covers_original_subquestions_and_retry_keeps_contract(self):
        from dataclasses import replace
        sources = [{'subquestion_id': 'RQ001', 'question': 'How?'},
                   {'subquestion_id': 'RQ002', 'question': 'Why?'}]
        story = replace(self.story, metadata={**self.story.metadata,
                                              'source_subquestions': sources})
        requests = []
        def invoke(prompt):
            requests.append(prompt)
            return {'content': json.dumps({'lesson': [
                {'subquestion_id': 'RQ001', 'question': 'How?', 'clauses': []}]})}
        _, report = plan_teaching(story, SimpleNamespace(invoke=invoke))
        self.assertEqual(report['mode'], 'blocked')
        self.assertEqual(len(requests), 2)
        for prompt in requests:
            example = prompt.split('结构示例（占位场景和关系ID必须替换为真实证据）：\n', 1)[1].split('\n', 1)[0]
            data = json.loads(example)
            self.assertEqual([q['subquestion_id'] for q in data['lesson']], ['RQ001', 'RQ002'])
            self.assertEqual(data['subquestion_decisions'], [
                {'subquestion_id': q['subquestion_id'], 'status': 'teach'} for q in sources])
        self.assertIn('Every original subquestion requires a decision', requests[1])

    def test_shared_scene_has_unique_execution_ids_and_original_provenance(self):
        from resource_planning.teaching_planner import apply_teaching
        first = self.story.scenes[0]
        data = {'lesson': [
            {'question': 'First', 'clauses': [{'scene_ids': [first.story_scene_id], 'narration': 'First explanation'}]},
            {'question': 'Second', 'clauses': [{'scene_ids': [first.story_scene_id], 'narration': 'Another use'}]}],
            'excluded_scenes': [{'scene_id': s.story_scene_id, 'reason': 'outside scope'} for s in self.story.scenes[1:]]}
        result = apply_teaching(self.story, data)
        ids = [b.beat_id for s in result.scenes for b in s.beats]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(result.scenes[0].relation_ids, result.scenes[1].relation_ids)
        self.assertTrue(all(b.parameters['evidence_reuse'] for b in result.scenes[1].beats))
        self.assertEqual([b.parameters['source_beat_id'] for b in result.scenes[1].beats],
                         [b.beat_id for b in first.beats])
        LayoutEngine().layout(result)

    def test_partial_answer_summary_discloses_missing_dimensions(self):
        from dataclasses import replace
        from resource_planning.summary import append_summary
        story = replace(self.story, metadata={**self.story.metadata,
            'answer_coverage': {'partial_answer': True, 'missing_requirements': ['适用场景']}})
        summary = append_summary(story).scenes[-1]
        self.assertIn('证据不足：适用场景', summary.narration_summary)
        self.assertTrue(any('证据不足' in beat.narration for beat in summary.beats))

    def test_summary_preserves_story_and_is_idempotent(self):
        from resource_planning.summary import append_summary
        result = append_summary(self.story)
        self.assertEqual(result.scenes[:-1], self.story.scenes)
        self.assertEqual(result.scenes[-1].scene_role, "summary")
        self.assertTrue(result.scenes[-1].metadata["summary_points"])
        self.assertIs(append_summary(result), result)
        render = LayoutEngine().layout(result)
        self.assertEqual(render.scenes[-1].metadata["summary_points"],
                         result.scenes[-1].metadata["summary_points"])

    def test_composition_summary_answers_whole_from_stored_direction(self):
        from resource_planning.summary import direct_answer
        nodes = [SimpleNamespace(knowledge_node_id=i, name=n) for i,n in
                 [("cpu", "CPU"), ("cu", "控制器"), ("alu", "运算器")]]
        relations = [SimpleNamespace(relation_id=i, relation_type="PART_OF",
            stored_source_node_id=i, stored_target_node_id="cpu") for i in ("cu", "alu")]
        story = SimpleNamespace(question="CPU的组成是什么？", intent="composition", metadata={},
            scenes=[SimpleNamespace(relation_ids=("cu", "alu"))],
            representation_plan=SimpleNamespace(root_segment=SimpleNamespace(nodes=nodes, relations=relations, children=[])))
        answer = direct_answer(story)
        self.assertIn("CPU的组成包括", answer)
        self.assertIn("控制器、运算器", answer)

    def test_lesson_selects_evidence_and_excludes_irrelevant_scene(self):
        first, second = self.story.scenes
        data = {"lesson": [{"question": "Why?", "clauses": [
            {"scene_ids": [first.story_scene_id], "narration": "A focused explanation."}]}],
            "excluded_scenes": [{"scene_id": second.story_scene_id, "reason": "Outside the question"}]}
        result, report = plan_teaching(self.story, self.model(data))
        self.assertEqual(report["mode"], "llm")
        self.assertEqual(result.scenes[0].relation_ids, first.relation_ids)
        self.assertEqual(result.estimated_duration, sum(b.duration for b in first.beats))
        data["excluded_scenes"] = []
        result, report = plan_teaching(self.story, self.model(data))
        self.assertIs(result, self.story)

    def test_lesson_can_combine_related_evidence(self):
        data = {"lesson": [{"question": "How?", "clauses": [
            {"scene_ids": [s.story_scene_id for s in self.story.scenes],
             "narration": "These facts jointly explain the result."}]}], "excluded_scenes": []}
        result, report = plan_teaching(self.story, self.model(data))
        self.assertEqual(report["mode"], "llm")
        self.assertEqual(len(result.scenes[0].relation_ids), 2)

    def subquestion_data(self):
        return {"subquestions": [{"question": "How does this work?", "steps": [
            {"beat_ids": [b.beat_id], "evidence_relation_ids": list(b.relation_ids),
             "narration": f"Sentence for {b.phase_id}."}
            for s in self.story.scenes for b in s.beats]}]}

    def test_sentence_alignment_preserves_each_action(self):
        data = self.subquestion_data()
        result, report = plan_teaching(self.story, self.model(data))
        self.assertEqual(report["mode"], "llm")
        self.assertEqual(len(result.scenes), sum(len(s.beats) for s in self.story.scenes))
        for scene, step in zip(result.scenes, data["subquestions"][0]["steps"]):
            self.assertEqual(scene.beats[0].narration, step["narration"])
            self.assertEqual(list(scene.relation_ids), step["evidence_relation_ids"])
        LayoutEngine().layout(result)

    def test_format_compatibility_and_derived_references(self):
        data = self.subquestion_data()
        data["sub_questions"] = data.pop("subquestions")
        for step in data["sub_questions"][0]["steps"]:
            step["beat_id"] = step.pop("beat_ids")[0]
            step["text"] = step.pop("narration")
            del step["evidence_relation_ids"]
        model = SimpleNamespace(invoke=lambda prompt: {"content": "```json\n" + json.dumps({"plan": data}) + "\n```"})
        result, report = plan_teaching(self.story, model)
        self.assertEqual(report["mode"], "llm")
        self.assertTrue(report["format_fixes"])

    def test_validation_failure_gets_one_repair_attempt(self):
        responses = iter([{"content": "invalid"}, {"content": json.dumps(self.subquestion_data())}])
        result, report = plan_teaching(self.story, SimpleNamespace(invoke=lambda prompt: next(responses)))
        self.assertEqual(report["mode"], "llm")
        self.assertEqual(report["attempts"], 2)
        self.assertTrue(report["validation_errors"])

    def test_reversed_phase_order_falls_back(self):
        data = self.subquestion_data()
        data["subquestions"][0]["steps"].reverse()
        result, report = plan_teaching(self.story, self.model(data))
        self.assertIs(result, self.story)
        self.assertEqual(report["mode"], "blocked")

    def test_query_decomposition_is_bounded_and_falls_back(self):
        from explanation.llm_questions import decompose
        questions, report = decompose("test", self.model({"questions": ["why", "how"]}))
        self.assertEqual(questions, ["why", "how"])
        questions, report = decompose("test", self.model({"questions": ["q"] * 5}))
        self.assertEqual(questions, [])
        self.assertEqual(report["mode"], "rules_fallback")

    def test_grouping_preserves_actions_and_supports_layout(self):
        result, report = plan_teaching(self.story, self.model(self.data))
        self.assertEqual(report["mode"], "llm")
        self.assertEqual(len(result.scenes), 1)
        self.assertEqual([b.beat_id for b in result.scenes[0].beats],
                         [b.beat_id for s in self.story.scenes for b in s.beats])
        self.assertTrue(all(b.narration == "A connected explanation." for b in result.scenes[0].beats))
        self.assertEqual(len(LayoutEngine().layout(result).scenes), 1)

    def test_invalid_evidence_and_unavailable_model_fall_back(self):
        self.data["paragraphs"][0]["evidence_relation_ids"] = ["invented"]
        result, report = plan_teaching(self.story, self.model(self.data))
        self.assertIs(result, self.story)
        self.assertEqual(report["mode"], "blocked")
        def fail(prompt): raise TimeoutError("private response must not be printed")
        result, report = plan_teaching(self.story, SimpleNamespace(invoke=fail))
        self.assertIs(result, self.story)
        self.assertEqual(report["reason"], "TimeoutError")

    def test_semantic_failure_retries_and_blocks(self):
        failed = {'status': 'fallback', 'checks': [
            {'scope': 'overall', 'pass': False, 'issues': ['Missing application evidence']} ]}
        with patch('resource_planning.continuity.review_lesson',
                   side_effect=lambda story, data, evidence, model: (data, failed)) as review:
            result, report = plan_teaching(self.story, self.model(self.data))
        self.assertEqual(review.call_count, 2)
        self.assertEqual(report['mode'], 'blocked')
        self.assertIn('Missing application evidence', report['validation_errors'][0])
        self.assertEqual(len(report['semantic_reviews']), 2)

    def test_semantic_failure_can_be_repaired(self):
        failed = {'status': 'fallback', 'reason': 'insufficient evidence'}
        with patch('resource_planning.continuity.review_lesson', side_effect=[
                (self.data, failed), (self.data, {'status': 'passed'})]):
            _, report = plan_teaching(self.story, self.model(self.data))
        self.assertEqual(report['mode'], 'llm')
        self.assertEqual(report['attempts'], 2)

    def test_omitted_scene_falls_back(self):
        self.data["paragraphs"][0]["scene_ids"].pop()
        self.data["paragraphs"][0]["evidence_relation_ids"].pop()
        result, report = plan_teaching(self.story, self.model(self.data))
        self.assertIs(result, self.story)
