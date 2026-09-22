import ast
import tempfile
import unittest
from pathlib import Path
from rendering.subgraph import add_subquestion_intros
from rendering.manim.script_generator import ManimScriptGenerator


class IntroTests(unittest.TestCase):
    def test_out_of_chapter_removes_old_voiced_prerequisite_and_cards_only(self):
        concept = {'title': '概念', 'metadata': {'prerequisite': True, 'subquestion_id': 'PRE.A'},
                   'nodes': [{'definition': '本章不展开'}],
                   'beats': [{'narration': '概念是……', 'audio': {'path': 'old.wav'}}]}
        answer = {'title': '正文', 'metadata': {}, 'nodes': [{'definition': '本章不展开'}], 'beats': []}
        payload = {'metadata': {'subquestion_intros': 3}, 'scenes': [
            {'scene_role': 'subquestion_intro', 'metadata': {'prerequisite_introduction': True}},
            {'scene_role': 'subquestion_intro', 'metadata': {'intro_for': 'PRE.A'}}, concept, answer]}
        result = add_subquestion_intros(payload)
        self.assertEqual(result['scenes'], [answer])
        self.assertEqual(add_subquestion_intros(result), result)
        self.assertEqual(len(payload['scenes']), 4)

    def test_once_per_question_and_before_drawing(self):
        scene = {'metadata': {'subquestion_id': 'Q01', 'subquestion': '为什么？'},
                 'nodes': [], 'relations': [], 'beats': []}
        result = add_subquestion_intros({'scenes': [scene, scene]})
        self.assertEqual(len(result['scenes']), 3)
        self.assertEqual(result['scenes'][0]['beats'][0]['narration'], '')
        self.assertEqual(result, add_subquestion_intros(result))

    def test_prerequisites_get_named_narrated_card(self):
        result = add_subquestion_intros({'scenes': [{'metadata': {
            'subquestion_id': 'SQ01', 'subquestion': '基础？', 'prerequisite': True}}]})
        self.assertEqual(len(result['scenes']), 3)
        self.assertEqual(result['scenes'][0]['beats'][0]['narration'], '下面介绍几个前置概念。')
        self.assertEqual(result['scenes'][1]['beats'][0]['narration'], '')

    def test_existing_title_audio_removed_but_explanation_audio_preserved(self):
        import copy
        title = {'scene_role': 'subquestion_intro', 'metadata': {'intro_for': 'Q1'},
                 'beats': [{'narration': 'Why?', 'audio': {'path': 'title.wav'}, 'audio_end': True}]}
        explanation = {'scene_id': 'S1', 'beats': [
            {'narration': 'Because...', 'audio': {'path': 'answer.wav'}, 'audio_end': True}]}
        payload = {'metadata': {'subquestion_intros': 3}, 'scenes': [title, explanation]}
        original = copy.deepcopy(payload)
        result = add_subquestion_intros(payload)
        self.assertEqual(result['scenes'][0]['beats'], [{'narration': ''}])
        self.assertEqual(result['scenes'][1], explanation)
        self.assertEqual(result, add_subquestion_intros(result))
        self.assertEqual(payload, original)

    def test_cards_preserve_evidence_ids_and_input(self):
        import copy
        original = {'scenes': [{'scene_id': 'SS001', 'metadata': {
            'subquestion_id': 'PRE.A', 'subquestion': 'A', 'prerequisite': True},
            'beats': [{'beat_id': 'evidence.A', 'narration': 'A是definition'}]}]}
        snapshot = copy.deepcopy(original)
        result = add_subquestion_intros(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(result['scenes'][-1], original['scenes'][0])
        self.assertEqual(add_subquestion_intros(result), result)

    def test_concept_definition_has_subject_and_invalidates_old_audio(self):
        payload = {'metadata': {'subquestion_intros': 3}, 'scenes': [{
            'title': '抽象', 'metadata': {'prerequisite': True, 'student_action': 'explain'},
            'beats': [{'narration': '隐藏底层细节的方法。', 'audio': {'path': 'old.wav'}, 'audio_end': True}]}]}
        result = add_subquestion_intros(payload)
        beat = result['scenes'][0]['beats'][0]
        self.assertEqual(beat['narration'], '抽象是隐藏底层细节的方法。')
        self.assertNotIn('audio', beat)
        self.assertEqual(add_subquestion_intros(result), result)

    def test_last_two_beats_reused_across_title_card(self):
        from rendering.manim.script_generator import _SCRIPT_TEMPLATE
        tree = ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', repr('{}')))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'recent_local_nodes')
        env = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), '<test>', 'exec'), env)
        scenes = [{'metadata': {'local_scene': {}}, 'beats': []}]
        scenes[0] = {'metadata': {'local_scene': {'nodes': []}}, 'beats': [
            {'node_ids': [name]} for name in ['A', 'B', 'C', 'D']]}
        scenes += [{'scene_role': 'subquestion_intro', 'beats': [{}]},
                   {'metadata': {'local_scene': {'nodes': []}}, 'beats': [{'node_ids': ['B']}]}]
        self.assertEqual(env['recent_local_nodes'](scenes, 2, 0), {'C', 'D'})
        self.assertEqual(env['recent_local_nodes'](scenes, 0, 3), {'B', 'C'})
        self.assertEqual(env['recent_local_nodes'](scenes, 2, 1), {'B', 'D'})

    def test_generated_script_compiles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = ManimScriptGenerator().generate_payload({'scenes': []}, Path(directory) / 'scene.py')
            ast.parse(path.read_text(encoding='utf-8'))
