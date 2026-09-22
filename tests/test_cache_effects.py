import ast
import tempfile
import unittest
from pathlib import Path
from representation.animation_grammar import AnimationGrammar
from rendering.manim.script_generator import ManimScriptGenerator
from rendering.manim.cache_effects import SOURCE


class CacheEffectsTests(unittest.TestCase):
    def test_dedicated_templates(self):
        grammar = AnimationGrammar()
        for name in ('MECHANISM_OVERLAY', 'MULTILEVEL_CACHE_FALLBACK'):
            template = grammar.template_for(name)
            self.assertEqual(template.template_id, name.lower())
        phases = grammar.template_for('MULTILEVEL_CACHE_FALLBACK').phases
        self.assertEqual([p.phase_id for p in phases], ['show_levels', 'probe_l1',
            'fallback_l2', 'fallback_l3', 'access_memory', 'show_accounting'])

    def test_missing_relation_uses_safe_fallback(self):
        calls = []
        env = {'relation_by_id': lambda *_: None, 'fallback_relation': lambda *args: calls.append(args)}
        exec(SOURCE, env)
        env['animate_cache_mechanism'](None, {}, {}, {'phase_id': 'show_levels'})
        self.assertEqual(len(calls), 1)

    def test_generated_script_contains_dispatch_and_compiles(self):
        with tempfile.TemporaryDirectory() as directory:
            script = ManimScriptGenerator().generate_payload({'scenes': []}, Path(directory) / 'demo.py')
            text = script.read_text(encoding='utf-8')
            ast.parse(text)
            self.assertIn('animate_cache_mechanism(scene, scene_spec, objects, beat)', text)
            self.assertIn('def animate_cache_mechanism', text)
