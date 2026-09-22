import ast
import json
import unittest
from types import SimpleNamespace
from resource_planning.localization import localize_payload, localize_script


class LocalizationTests(unittest.TestCase):
    def model(self):
        def invoke(prompt):
            batch = json.loads(prompt.split('Input: ', 1)[1])
            return {'translations': ['English ' + str(i) for i, _ in enumerate(batch)]}
        return SimpleNamespace(invoke=invoke)

    def test_text_translated_ids_preserved_audio_removed(self):
        original = {'question': '计算机是什么？', 'opening_audio': {'path': 'zh.wav'},
            'scenes': [{'title': '硬件', 'nodes': [{'name': '硬件', 'knowledge_node_id': 'CO021'}],
                'beats': [{'beat_id': 'B1', 'narration': '硬件', 'audio': {'path': 'zh.wav'}, 'audio_end': True}]}]}
        result = localize_payload(original, 'en', self.model())
        self.assertEqual(result['metadata']['language'], 'en')
        self.assertNotIn('opening_audio', result)
        scene = result['scenes'][0]
        self.assertEqual(scene['title'], scene['nodes'][0]['name'])
        self.assertEqual(scene['title'], scene['beats'][0]['narration'])
        self.assertEqual(scene['nodes'][0]['knowledge_node_id'], 'CO021')
        self.assertNotIn('audio', scene['beats'][0])
        self.assertIn('audio', original['scenes'][0]['beats'][0])

    def test_chinese_mode_does_not_call_model(self):
        self.assertEqual(localize_payload({'question': '中文'}, 'zh'), {'question': '中文'})

    def test_script_captions_translated_without_touching_plan_json(self):
        code = 'import json\nPLAN=json.loads(\'{"id":"中文标识"}\')\ncaption="主存"\n'
        result = localize_script(code, self.model())
        ast.parse(result)
        env = {}
        exec(result, env)
        self.assertEqual(env['PLAN']['id'], '中文标识')
        self.assertTrue(env['caption'].startswith('English'))

    def test_invalid_translation_fails_explicitly(self):
        with self.assertRaises(ValueError):
            localize_payload({'title': '硬件'}, 'en', SimpleNamespace(invoke=lambda _: {'translations': []}))
