import ast
import unittest
from unittest.mock import Mock

from representation.animation_grammar import TEMPLATES
from representation.coverage import implementation_status
from rendering.manim.script_generator import _SCRIPT_TEMPLATE
from rendering.manim.data_structure_effects import SOURCE


class DataStructureEffectsTests(unittest.TestCase):
    def test_both_patterns_dispatch_to_specialized_effect(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "animate_beat")
        effect = Mock()
        env = {"animate_data_structure": effect}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "dispatch", "exec"), env)
        for pid in ("TABLE_HIGHLIGHT", "PUSH_POP"):
            self.assertEqual(implementation_status(pid), "dedicated")
            template = TEMPLATES[pid]
            for phase in template.phases:
                beat = {"template_id": template.template_id, "phase_id": phase.phase_id}
                env["animate_beat"](None, {"layout": "connected_pair"}, {}, beat)
                self.assertEqual(effect.call_args.args[-1], beat)
        self.assertEqual(effect.call_count, 6)
        compile(SOURCE, "embedded_effects", "exec")

    def test_stack_orders_push_before_pop(self):
        self.assertEqual([p.phase_id for p in TEMPLATES["PUSH_POP"].phases],
                         ["show_stack", "push_value", "pop_value"])
