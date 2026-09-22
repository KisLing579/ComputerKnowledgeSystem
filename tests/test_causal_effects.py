import ast
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from representation.animation_grammar import TEMPLATES
from representation.coverage import implementation_status
from rendering.manim.causal_effects import SOURCE
from rendering.manim.script_generator import _SCRIPT_TEMPLATE


PATTERNS = ('DEPENDENCY_GATE', 'CAPABILITY_UNLOCK', 'CAUSE_CHAIN', 'PROBLEM_SOLUTION_BRIDGE')


class CausalEffectsTests(unittest.TestCase):
    def test_dispatches_every_phase(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'animate_beat')
        effect = Mock()
        env = {'animate_causal_relation': effect}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'dispatch', 'exec'), env)
        for pid in PATTERNS:
            self.assertEqual(implementation_status(pid), 'dedicated')
            for phase in TEMPLATES[pid].phases:
                env['animate_beat'](None, {}, {}, {'template_id': pid.lower(), 'phase_id': phase.phase_id})
        self.assertEqual(effect.call_count, 16)

    def test_stored_direction_and_all_phase_lifecycles(self):
        relation = {'stored_source_node_id': 'S', 'stored_target_node_id': 'T',
                    'source_node_id': 'T', 'target_node_id': 'S'}
        env = {name: MagicMock() for name in ('SurroundingRectangle', 'Line', 'VGroup', 'Create',
               'Indicate', 'FadeOut', 'FadeIn', 'Text', 'Arrow', 'Dot', 'MoveAlongPath')}
        env.update({name: 1 for name in ('RED', 'BLUE', 'GREEN', 'YELLOW', 'UP', 'DOWN', 'UL', 'DR')})
        env['relation_by_id'] = lambda *args: relation
        env['fallback_relation'] = Mock()
        env['remember_local_link'] = Mock()
        objects = {'S': MagicMock(), 'T': MagicMock()}
        objects['S'].get_center.return_value = [1, 0, 0]
        objects['T'].get_center.return_value = [-1, 0, 0]
        env['ensure_node'] = lambda scene, spec, registry, nid: registry[nid]
        exec(SOURCE, env)
        for pid in PATTERNS:
            scene = SimpleNamespace(play=Mock(), add=Mock(), remove=Mock())
            beat = {'template_id': pid.lower(), 'relation_ids': ['R']}
            expected = ('T', 'S') if pid in ('DEPENDENCY_GATE', 'PROBLEM_SOLUTION_BRIDGE') else ('S', 'T')
            self.assertEqual(env['causal_endpoints']({}, beat), expected)
            for phase in TEMPLATES[pid].phases:
                beat['phase_id'] = phase.phase_id
                env['animate_causal_relation'](scene, {'scene_id': 'demo'}, objects, beat)
            self.assertTrue(scene.play.called)
            self.assertTrue(all('lock' not in state for state in scene.causal_states.values()))
        env['fallback_relation'].assert_not_called()
        self.assertTrue(env['remember_local_link'].called)

    def test_missing_relation_falls_back(self):
        env = {'relation_by_id': lambda *args: None, 'fallback_relation': Mock()}
        exec(SOURCE, env)
        env['animate_causal_relation'](None, {}, {}, {'relation_ids': []})
        env['fallback_relation'].assert_called_once()
