import unittest
from dataclasses import replace
from types import SimpleNamespace

from resource_planning.animation_units import animation_units, validate_unit_selection, clause_visual_context
from resource_planning.teaching_planner import apply_teaching
from rendering.subgraph import compact_revisits
from resource_planning.llm_format import normalize_plan
import test_teaching


class AlignmentTests(unittest.TestCase):
    def test_visual_context_uses_only_selected_nodes_and_shared_roles(self):
        units = [dict(unit_id='S.U001', node_ids=['software', 'isa'], relation_ids=['r1']),
                 dict(unit_id='S.U002', node_ids=['isa', 'hardware'], relation_ids=['r2']),
                 dict(unit_id='S.U003', node_ids=['other'], relation_ids=['r3'])]
        evidence = {'scenes': [dict(id='S', animation_units=units, semantic_scene_plan={
            'layout_family': 'abstraction_interface', 'semantic_roles': {
                'upper_layer': 'software', 'boundary': 'isa', 'lower_layer': 'hardware',
                'implementation_1': 'other'}})]}
        data = {'lesson': [{'clauses': [dict(scene_ids=['S'], animation_unit_ids=['S.U001', 'S.U002'])]}]}
        context = clause_visual_context(data, evidence)[0]['scenes'][0]
        self.assertEqual(context['relation_ids'], ['r1', 'r2'])
        self.assertEqual(context['visible_semantic_roles'], {
            'upper_layer': 'software', 'boundary': 'isa', 'lower_layer': 'hardware'})
        data['lesson'][0]['clauses'][0]['animation_unit_ids'] = ['S.U001']
        context = clause_visual_context(data, evidence)[0]['scenes'][0]
        self.assertNotIn('lower_layer', context['visible_semantic_roles'])

    def setUp(self):
        fixture = test_teaching.TeachingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        first, second = fixture.story.scenes
        self.scene = replace(first, beats=first.beats + second.beats,
                             relation_ids=first.relation_ids + second.relation_ids,
                             metadata={'atomic_semantic_scene': True})
        self.story = replace(fixture.story, scenes=(self.scene,))

    def test_distinct_narrations_select_distinct_complete_actions(self):
        units = animation_units(self.scene)
        self.assertGreaterEqual(len(units), 2)
        data = {'lesson': [{'question': 'How?', 'clauses': [
            {'scene_ids': [self.scene.story_scene_id], 'animation_unit_ids': [u['unit_id']],
             'narration': f'Explanation {i}'} for i, u in enumerate(units)]}]}
        result = apply_teaching(self.story, data)
        for scene, unit in zip(result.scenes, units):
            self.assertEqual([b.parameters['source_beat_id'] for b in scene.beats], unit['beat_ids'])
            self.assertTrue(scene.metadata['narration_aligned'])

    def test_unspoken_units_can_be_omitted(self):
        unit = animation_units(self.scene)[-1]
        result = apply_teaching(self.story, {'lesson': [{'question': 'How?', 'clauses': [{
            'scene_ids': [self.scene.story_scene_id], 'animation_unit_ids': [unit['unit_id']],
            'narration': 'Only this action.'}]}]})
        self.assertEqual(len(result.scenes[0].beats), len(unit['beat_ids']))

    def test_missing_selection_and_partial_phase_rejected(self):
        with self.assertRaisesRegex(ValueError, 'animation_unit_ids'):
            apply_teaching(self.story, {'lesson': [{'question': 'How?', 'clauses': [{
                'scene_ids': [self.scene.story_scene_id], 'narration': 'Too broad.'}]}]})
        unit = animation_units(self.scene)[0]
        with self.assertRaisesRegex(ValueError, 'complete animation unit'):
            validate_unit_selection(self.scene, unit['beat_ids'][1:])

    def test_explicit_selection_never_becomes_whole_scene_highlight(self):
        scene = {'metadata': {'narration_aligned': True, 'source_beat_ids': ['a']},
                 'beats': [{'template_id': 'interface_bridge', 'parameters': {'source_beat_id': 'a'}}]}
        payload = {'scenes': [scene, scene]}
        self.assertEqual(compact_revisits(payload), payload)

    def test_safe_format_normalization_and_obsolete_summary(self):
        uid = animation_units(self.scene)[0]['unit_id']
        data = {'lesson': [{'question': 'How?', 'clauses': [{
            'scene_ids': self.scene.story_scene_id,
            'animation_unit_ids': ' ' + uid.rsplit('.', 1)[-1] + ' ',
            'narration': 'This action.'}]}],
            'answer_summary': {'text': 'Obsolete', 'evidence_relation_ids': ['not-selected']}}
        normalized, fixes = normalize_plan(data, self.story)
        self.assertNotIn('answer_summary', normalized)
        self.assertEqual(normalized['lesson'][0]['clauses'][0]['animation_unit_ids'], [uid])
        self.assertTrue(fixes)
        result = apply_teaching(self.story, normalized)
        self.assertNotIn('answer_summary', result.metadata)
        # Direct legacy callers must not resurrect the old summary gate either.
        result = apply_teaching(self.story, {**normalized, 'answer_summary': data['answer_summary']})
        self.assertNotIn('answer_summary', result.metadata)

    def test_unknown_ids_remain_invalid_with_actionable_diagnostics(self):
        valid = animation_units(self.scene)[0]['unit_id']
        for invalid in (['OTHER.U001'], [{'unit_id': valid}], [], [valid, valid]):
            data = {'lesson': [{'question': 'How?', 'clauses': [{
                'scene_ids': [self.scene.story_scene_id], 'animation_unit_ids': invalid,
                'narration': 'An action.'}]}]}
            with self.assertRaises(ValueError) as error:
                apply_teaching(self.story, data)
            self.assertIn('lesson[1].clauses[1]', str(error.exception))
            self.assertIn(valid, str(error.exception))

    def test_ambiguous_local_id_is_not_guessed(self):
        other = replace(self.scene, story_scene_id='OTHER')
        story = replace(self.story, scenes=(self.scene, other))
        data = {'lesson': [{'clauses': [{'scene_ids': [self.scene.story_scene_id, 'OTHER'],
                                      'animation_unit_ids': ['U001']}]}]}
        normalized, _ = normalize_plan(data, story)
        self.assertEqual(normalized['lesson'][0]['clauses'][0]['animation_unit_ids'], ['U001'])
