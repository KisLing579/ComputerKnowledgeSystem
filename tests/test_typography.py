import ast
import unittest
from rendering.manim.script_generator import _SCRIPT_TEMPLATE


class TypographyTests(unittest.TestCase):
    def test_real_manim_labels_fit_shapes_in_both_languages(self):
        try:
            from manim import Text, tempconfig
        except ImportError:
            self.skipTest('Manim required for glyph geometry regression')
        import tempfile
        with tempfile.TemporaryDirectory() as directory, tempconfig({'media_dir': directory}):
            env = {}
            exec(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', repr('{}')), env)
            for english in (True, False):
                env['ENGLISH'] = english
                for kind in ('code_block', 'storage_block', 'interface_hub', 'hardware_icon',
                             'bit_cell', 'container', 'functional_block'):
                    name = 'Processor and Memory Unit' if english else '处理器与存储管理单元'
                    obj = env['make_node']({'archetype': kind, 'name': name,
                                            'width': 2.1, 'height': .95})
                    drawing = obj[1]
                    body = drawing[0]
                    for item in drawing.submobjects:
                        if isinstance(item, Text):
                            with self.subTest(language=english, archetype=kind):
                                self.assertLessEqual(abs(item.get_x()-body.get_x()) + item.width/2,
                                                     body.width/2 + 1e-6)
                                self.assertLessEqual(abs(item.get_y()-body.get_y()) + item.height/2,
                                                     body.height/2 + 1e-6)

    def test_generated_script_compiles(self):
        compile(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', repr('{}')), '<generated>', 'exec')

    def test_english_wrap_preserves_words_and_fits_bounds(self):
        class Text:
            def __init__(self, text, **kwargs):
                self.text = text
                self.width = max(map(len, text.split('\n'))) * 0.1
                self.height = len(text.split('\n')) * 0.3
            def scale(self, factor):
                self.width *= factor
                self.height *= factor
        tree = ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', repr('{}')))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fitted_text')
        env = {'Text': Text, 'ENGLISH': True}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), '<helper>', 'exec'), env)
        for text in ['Instruction Set Architecture', 'CPU', 'VeryLongUnbrokenIdentifier', 'Memory\nManagement Unit']:
            result = env['fitted_text'](text, 22, 1.5, 0.7)
            self.assertEqual(result.text.split(), text.split())
            self.assertLessEqual(result.width, 1.5 + 1e-9)
            self.assertLessEqual(result.height, 0.7 + 1e-9)
            self.assertLessEqual(len(result.text.split('\n')), 2)
        self.assertIn('\n', env['fitted_text']('Instruction Set Architecture', 22, 1.5, 0.7).text)
        for english, name in [(True, 'Processor / CPU'), (False, '处理器 / CPU')]:
            env['ENGLISH'] = english
            for height in (0.95, 1.4):
                side = height * 0.85
                result = env['fitted_text'](name, 19, side * 0.8, side * 0.7)
                self.assertLessEqual(result.width, side * 0.8 + 1e-9)
                self.assertLessEqual(result.height, side * 0.7 + 1e-9)
