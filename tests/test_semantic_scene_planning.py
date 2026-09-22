import ast
import copy
import json
import tempfile
import unittest
from collections import Counter
from dataclasses import asdict, replace
from types import SimpleNamespace

import numpy as np

from explanation.models import ExplanationSegment
from explanation.path_fusion import PathFusionPlanner
from explanation.scene_pattern_matcher import ScenePatternMatcher
from explanation.semantic_scene import ScenePattern, SemanticScenePlan
from explanation.evidence.base import EvidenceContext
from explanation.evidence.interface import InterfaceEvidenceStrategy
from explanation.models import ExplanationGoal
from explanation.path_ranker import ExplanationPathRanker
from explanation.question_analyzer import QuestionAnalyzer
from explanation.structurer import ExplanationStructurer
from kg.config import load_settings
from kg.query import ExplanationPath, NodeMatch
from representation.registry import RepresentationRegistry
from resource_planning.binder import RepresentationBinder
from resource_planning.story_planner import VisualStoryPlanner
from resource_planning.teaching_planner import apply_subquestions, apply_teaching
from rendering.layout.engine import LayoutEngine
from rendering.subgraph import prepare_subgraph, group_subquestions
from rendering.manim.semantic_scene_demo import build_interface_demo, WorkbookInterfaceQuery
from rendering.manim.script_generator import _SCRIPT_TEMPLATE


def edge(rid, source, target, kind, layer='semantic'):
    return dict(id=rid, type=kind, stored_start_id=source, stored_end_id=target,
                traversal_from=source, traversal_to=target, relation_layer=layer)


def interface_fixture():
    nodes = {'S': {'name': 'Software'}, 'I': {'name': 'ISA'},
             'A': {'name': 'CPU A'}, 'B': {'name': 'CPU B'}, 'F': {'name': 'Stable interface'}}
    rels = [edge('d', 'S', 'I', 'DEPENDS_ON'), edge('a', 'A', 'I', 'IMPLEMENTS'),
            edge('b', 'B', 'I', 'IMPLEMENTS'), edge('f', 'I', 'F', 'HAS_FUNCTION', 'explanatory')]
    return nodes, rels


class SceneMatcherTests(unittest.TestCase):
    def match(self, nodes, rels):
        seg = ExplanationSegment('s', 'evidence_group', 'g', 'why interface', 'interface_role', root_id='I')
        return ScenePatternMatcher().match(seg, nodes, rels)

    def test_interface_roles_use_existing_ids_and_store_all_evidence(self):
        nodes, rels = interface_fixture()
        plan = self.match(nodes, rels)
        self.assertEqual(plan.scene_pattern, ScenePattern.ABSTRACTION_INTERFACE)
        self.assertEqual(plan.semantic_roles['upper_layer'], 'S')
        self.assertEqual(plan.semantic_roles['boundary'], 'I')
        self.assertEqual({v for k, v in plan.semantic_roles.items() if k.startswith('implementation_')}, {'A', 'B'})
        self.assertEqual(set(plan.relation_ids), {'d', 'a', 'b', 'f'})
        self.assertTrue(plan.visual_claim)
        self.assertEqual(set(plan.node_ids), set(nodes))

    def test_single_implementation_is_not_duplicated(self):
        nodes, rels = interface_fixture()
        plan = self.match(nodes, [r for r in rels if r['id'] != 'b'])
        self.assertNotIn('B', plan.node_ids)
        self.assertNotIn('implementation_2', plan.semantic_roles)

    def test_weak_uses_edges_do_not_prove_an_interface(self):
        nodes, _ = interface_fixture()
        self.assertIsNone(self.match(nodes, [edge('s', 'S', 'I', 'USES'), edge('a', 'A', 'I', 'USES')]))

    def test_missing_side_reversed_implementation_and_teaching_do_not_match(self):
        nodes, rels = interface_fixture()
        self.assertIsNone(self.match(nodes, [rels[0], edge('a', 'I', 'A', 'IMPLEMENTS')]))
        self.assertIsNone(self.match(nodes, [rels[0]]))
        self.assertIsNone(self.match(nodes, [*rels, edge('t', 'A', 'I', 'PREREQUISITE_OF', 'teaching')]))

    def test_all_nine_patterns_have_minimal_rule_examples(self):
        nodes = {n: {'name': n, 'semantic_type': 'state'} for n in 'ABCDI'}
        cases = [
            ('CAUSAL_CHAIN', [('A', 'B', 'CAUSES'), ('B', 'C', 'RESULTS_IN')]),
            ('PROCESS_PIPELINE', [('A', 'B', 'TRANSFORMS_TO'), ('B', 'C', 'TRANSFORMS_TO')]),
            ('HIERARCHICAL_COMPOSITION', [('A', 'I', 'PART_OF'), ('B', 'I', 'PART_OF')]),
            ('SIDE_BY_SIDE_CONTRAST', [('A', 'B', 'CONTRASTS_WITH')]),
            ('ONE_ABSTRACTION_MULTI_IMPLEMENTATION', [('A', 'I', 'IMPLEMENTS'), ('B', 'I', 'IMPLEMENTS')]),
            ('MAPPING_CORRESPONDENCE', [('A', 'B', 'MAPS_TO')]),
            ('STATE_TRANSITION', [('A', 'B', 'TRANSFORMS_TO')]),
            ('LAYERED_SYSTEM', [('A', 'B', 'DEPENDS_ON'), ('B', 'C', 'DEPENDS_ON')]),
        ]
        seen = {'ABSTRACTION_INTERFACE'}
        for pattern, specs in cases:
            with self.subTest(pattern=pattern):
                plan = self.match(nodes, [edge(str(i), *spec) for i, spec in enumerate(specs)])
                self.assertIsNotNone(plan)
                self.assertEqual(plan.scene_pattern, pattern)
                seen.add(pattern)
        self.assertEqual(seen, set(ScenePattern))

    def test_claim_is_required(self):
        with self.assertRaises(ValueError):
            SemanticScenePlan('ABSTRACTION_INTERFACE')

    def test_parallel_interface_edges_are_not_collapsed_by_grouping(self):
        nodes, rels = interface_fixture()
        rels.append(dict(rels[0], id='parallel', relation_layer='explanatory'))
        from explanation.evidence_grouping import group_related_evidence
        groups = group_related_evidence(rels, nodes, title='interface', intent='interface_role', focal_ids=('I',))
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0].scene_plan.relation_ids), {'d', 'a', 'b', 'f', 'parallel'})


class SemanticSceneIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = RepresentationRegistry(load_settings().data.workbook)

    def build(self, *, max_nodes=8):
        nodes, rels = interface_fixture()
        matches = [NodeMatch(n, v['name'], v['name'], 'concept', '', '', 110 if n == 'I' else 80)
                   for n, v in nodes.items()]
        paths = [ExplanationPath((r['stored_start_id'], r['stored_end_id']),
            (nodes[r['stored_start_id']]['name'], nodes[r['stored_end_id']]['name']), (r,), 80) for r in rels]
        fused = PathFusionPlanner(max_nodes_per_scene=max_nodes).fuse('为什么 ISA 被称为软硬件接口？', matches, paths)
        representation = RepresentationBinder(self.registry).bind(fused.plan)
        story = VisualStoryPlanner(max_nodes_per_scene=max_nodes).plan(representation)
        return fused, representation, story

    def test_four_relations_form_one_scene_and_keep_animation_bindings(self):
        fused, representation, story = self.build()
        self.assertEqual(len(fused.plan.root_segment.children), 1)
        self.assertEqual(fused.answer_graph['coverage']['planned_relation_count'], 4)
        self.assertEqual(len(story.scenes), 1)
        scene = story.scenes[0]
        self.assertEqual(scene.metadata['scene_pattern'], 'ABSTRACTION_INTERFACE')
        rels = representation.root_segment.children[0].relations
        self.assertEqual(set(scene.relation_ids), {r.relation_id for r in rels})
        for r in rels:
            beats = [b for b in scene.beats if r.relation_id in b.relation_ids]
            self.assertEqual([b.phase_id for b in beats], [p.phase_id for p in r.grammar_phases])
            self.assertTrue(all(b.pattern_id == r.pattern_id for b in beats))
        self.assertEqual([b.phase_id for b in scene.beats[:2]], ['reveal_upper', 'reveal_boundary'])
        dependency = next(r.relation_id for r in rels if r.relation_type == 'DEPENDS_ON')
        local_ids = [r for b in scene.beats for r in b.relation_ids]
        self.assertEqual(local_ids[0], dependency)
        self.assertEqual(scene.beats[-1].phase_id, 'emphasize_claim')

    def test_budget_fallback_retains_every_relation_and_parallel_identity(self):
        fused, _, story = self.build(max_nodes=2)
        self.assertEqual(len(fused.plan.root_segment.children), 4)
        self.assertEqual(len(story.scenes), 4)
        self.assertEqual(Counter(r for s in story.scenes for r in s.relation_ids),
                         Counter(e['edge_id'] for e in fused.answer_graph['edges']))

    def test_layout_is_upper_boundary_lower_and_survives_payload_preparation(self):
        _, _, story = self.build()
        render = LayoutEngine().layout(story)
        payload = prepare_subgraph(group_subquestions(asdict(render)))
        scene = payload['scenes'][0]
        self.assertEqual(scene['layout'], 'abstraction_interface')
        nodes = {n['knowledge_node_id']: n for n in scene['nodes']}
        self.assertGreater(nodes['S']['y'], nodes['I']['y'])
        for n in 'AB':
            self.assertLess(nodes[n]['y'], nodes['I']['y'])
        self.assertNotEqual(nodes['A']['x'], nodes['B']['x'])
        self.assertTrue(nodes['I']['metadata']['interface_boundary'])
        self.assertFalse(any(n['archetype'] == 'graph_node' for n in scene['nodes']))
        self.assertEqual(prepare_subgraph(payload), payload)

    def test_teaching_preserves_atomic_scene_and_rejects_partial_beats(self):
        _, _, story = self.build()
        source = story.scenes[0]
        step = {'beat_ids': [b.beat_id for b in source.beats], 'narration': '软件通过接口联系实现。',
                'evidence_relation_ids': list(source.relation_ids)}
        data = {'subquestions': [{'question': '为何是接口？', 'steps': [step]}]}
        edited = apply_subquestions(story, data)
        self.assertEqual(edited.scenes[0].metadata['semantic_scene_plan'], source.metadata['semantic_scene_plan'])
        self.assertTrue(edited.scenes[0].metadata['atomic_semantic_scene'])
        step['beat_ids'] = step['beat_ids'][1:]
        with self.assertRaisesRegex(ValueError, 'Semantic scenes'):
            apply_subquestions(story, data)

    def test_atomic_scenes_are_not_merged_by_subquestion_grouping(self):
        _, _, story = self.build()
        first = story.scenes[0]
        second = replace(first, story_scene_id='other')
        story = replace(story, scenes=tuple(replace(s, metadata={**s.metadata, 'subquestion_id': 'Q1'})
                                           for s in (first, second)))
        payload = group_subquestions(asdict(LayoutEngine().layout(story)))
        self.assertEqual(len(payload['scenes']), 2)

    def test_cache_overlap_recovers_original_stage_positions_and_audio(self):
        def stage(sid, right):
            return {'scene_id': sid, 'layout': 'connected_pair', 'metadata': {'subquestion_id': 'RQ001'},
                'nodes': [{'knowledge_node_id': 'cache', 'x': -2.4, 'y': 0},
                          {'knowledge_node_id': right, 'x': 2.4, 'y': 0}],
                'relations': [], 'beats': []}
        first, second = stage('SC003', 'gap'), stage('SC004', 'buffer')
        combined = copy.deepcopy(first)
        combined['nodes'] = [{'knowledge_node_id': nid, 'x': -2.4, 'y': 0}
                             for nid in ('cache', 'gap', 'buffer')]
        combined['beats'] = [{'beat_id': 'gap.1', 'audio': {'path': 'existing.wav', 'duration': 3}, 'audio_end': True},
                             {'beat_id': 'buffer.1'}]
        combined['metadata']['local_stages'] = {'gap.1': first, 'buffer.1': second}
        payload = {'scenes': [combined], 'metadata': {'presentation': 'semantic_scenes', 'shot_unit': 'subquestion'}}
        fixed = group_subquestions(payload)
        self.assertEqual(len(fixed['scenes']), 2)
        for scene in fixed['scenes']:
            self.assertEqual([n['x'] for n in scene['nodes']], [-2.4, 2.4])
        self.assertEqual(fixed['scenes'][0]['beats'][0], combined['beats'][0])
        self.assertEqual(group_subquestions(fixed), fixed)
        self.assertEqual(payload['scenes'][0]['nodes'][1]['x'], -2.4)

    def test_fallback_arrow_attaches_outside_long_node_labels(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', "'{}'"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fallback_relation')
        def node(x, width):
            return SimpleNamespace(get_center=lambda: np.array([x, 0., 0.]),
                get_left=lambda: np.array([x-width/2, 0., 0.]),
                get_right=lambda: np.array([x+width/2, 0., 0.]))
        nodes = {'cache': node(-2.4, 3.2), 'gap': node(2.4, 3.8)}
        arrows = []
        def arrow(start, end, **kwargs):
            arrows.append((start, end, kwargs))
            return object()
        env = {'relation_by_id': lambda *args: {'source_node_id': 'cache', 'target_node_id': 'gap'},
               'ensure_node': lambda scene, spec, objects, nid: nodes[nid],
               'Arrow': arrow, 'Create': lambda x: x, 'FadeOut': lambda x: x}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'fallback', 'exec'), env)
        env['fallback_relation'](SimpleNamespace(play=lambda *args, **kwargs: None), {}, {}, {'relation_ids': ['r']})
        self.assertAlmostEqual(arrows[0][0][0], -.8)
        self.assertAlmostEqual(arrows[0][1][0], .5)

    def test_real_workbook_isa_regression_and_generated_script(self):
        with tempfile.TemporaryDirectory() as directory:
            script, report = build_interface_demo(directory)
            ast.parse(script.read_text(encoding='utf-8'))
            scenes = [s for s in report['scene_plans'] if s['scene_pattern'] == 'ABSTRACTION_INTERFACE']
            self.assertEqual(len(scenes), 1)
            roles = scenes[0]['semantic_roles']
            self.assertEqual(roles['boundary'], 'CO035')
            self.assertEqual(roles['upper_layer'], 'CO006')
            self.assertEqual({v for k, v in roles.items() if k.startswith('implementation_')}, {'CO037'})
            self.assertGreater(len(scenes[0]['relations']), 2)
            self.assertEqual(report['validation_mode'], 'offline_workbook_no_llm_no_neo4j')

    def test_interface_retrieval_uses_tiers_when_path_search_is_empty(self):
        query = WorkbookInterfaceQuery(load_settings())
        _, paths = query.generate_candidate_paths('为什么 ISA 被称为软硬件接口？', limit=5)
        kinds = [p.relationships[0]['type'] for p in paths]
        self.assertCountEqual(kinds[:3], ['INTERFACES_WITH', 'INTERFACES_WITH', 'IMPLEMENTS'])
        self.assertIn('HAS_FUNCTION', kinds)
        self.assertNotIn('USES', kinds)

    def test_interface_strategy_handles_absent_optional_types_and_weak_fallback(self):
        query = WorkbookInterfaceQuery(load_settings())
        query.edges = [r for r in query.edges if r[':TYPE'] == 'USES']
        matches = query.find_related_nodes('为什么 ISA 被称为软硬件接口？')
        analysis = QuestionAnalyzer().analyze('为什么 ISA 被称为软硬件接口？', matches)
        evidence = InterfaceEvidenceStrategy().collect(EvidenceContext(
            ExplanationGoal('test', analysis.question, analysis), tuple(matches), query,
            ExplanationPathRanker(), query.settings))
        self.assertTrue(evidence.neighbors)
        self.assertTrue(all(n.relationship['type'] == 'USES' for n in evidence.neighbors))
        self.assertEqual(evidence.metadata['tier_counts'][:3], [0, 0, 0])

    def test_existing_interface_structurer_uses_one_scene_when_evidence_fits(self):
        query = WorkbookInterfaceQuery(load_settings())
        matches = query.find_related_nodes('为什么 ISA 被称为软硬件接口？')
        analysis = QuestionAnalyzer().analyze('为什么 ISA 被称为软硬件接口？', matches)
        evidence = InterfaceEvidenceStrategy().collect(EvidenceContext(
            ExplanationGoal('test', analysis.question, analysis), tuple(matches), query,
            ExplanationPathRanker(), query.settings))
        segment = ExplanationStructurer.interface_segment(segment_id='i', goal_id='g',
            title=analysis.question, analysis=analysis, root=evidence.root,
            interface_neighbors=list(evidence.neighbors[:5]), components=[])
        self.assertEqual(segment.segment_type, 'evidence_group')
        self.assertEqual(segment.semantic_scene_plan.scene_pattern, 'ABSTRACTION_INTERFACE')
        self.assertEqual(len(segment.relations), 5)


if __name__ == '__main__':
    unittest.main()
