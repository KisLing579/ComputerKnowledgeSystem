import ast
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from rendering.manim.execution_nodes import address_calculation, execution_design, SOURCE, EXECUTION_ARCHETYPES
from rendering.manim.script_generator import _SCRIPT_TEMPLATE


class ExecutionNodeTests(unittest.TestCase):
    def design(self, kind, *req):
        return execution_design({"archetype": kind, "metadata": {"render_requirements": req}}, True)

    def test_signed_branch_and_32_bit_wrap(self):
        self.assertEqual(address_calculation("branch32")["result"], 4092)
        self.assertEqual(address_calculation("branch32", {"pc": 0xfffffffc, "immediate": 1})["result"], 4)
        self.assertEqual(address_calculation("branch32", {"pc": 0, "immediate": 0x8000})["result"], (4-131072) & 0xffffffff)
        with self.assertRaises(ValueError):
            address_calculation("branch32", {"immediate": 65536})

    def test_address_modes_and_input_validation(self):
        self.assertEqual(address_calculation("indexed", {"base": 100, "index": 5, "stride": 8})["result"], 140)
        self.assertEqual(address_calculation("base_offset", {"offset": -12})["result"], 4084)
        self.assertEqual(address_calculation("pc_relative", {"offset": -4})["result"], 4092)
        for values in ({"base": "100"}, {"stride": 0}, {"pc": 1}):
            with self.assertRaises(ValueError):
                address_calculation("indexed", values)

    def test_operand_and_concatenation_profiles_do_not_add(self):
        for req in ("register_operand", "constant_in_instruction", "26bit_target_shift2"):
            self.assertIsNone(self.design("addressing", req)["mode"])
        self.assertEqual(self.design("addressing", "pc_plus_4")["mode"], "branch32")
        self.assertEqual(self.design("addressing", "base_plus_scaled_index")["mode"], "indexed")

    def test_distinct_control_and_processor_structures(self):
        self.assertEqual(self.design("control_flow", "compare_equal")["labels"][0], "rs == rt?")
        self.assertEqual(self.design("control_flow", "compare_not_equal")["labels"][0], "rs != rt?")
        self.assertEqual(self.design("control_flow", "condition_false")["selected"], 1)
        self.assertEqual(self.design("datapath_graph", "select_signal")["layout"], "mux")
        self.assertEqual(self.design("datapath_graph", "alu_inputs")["layout"], "alu")
        self.assertEqual(len(self.design("datapath_graph", "five_stages")["labels"]), 5)

    def test_grammar_dispatch_and_phase_order(self):
        from representation.animation_grammar import TEMPLATES
        template = TEMPLATES["ADDRESS_CALC"]
        self.assertEqual([p.phase_id for p in template.phases], ["show_inputs", "calculate", "show_result"])
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", repr("{}")))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "animate_beat")
        effect = Mock()
        env = {"animate_address_calculation": effect}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "dispatch", "exec"), env)
        for phase in template.phases:
            env["animate_beat"](None, {}, {}, {"template_id": "address_calc", "phase_id": phase.phase_id})
        self.assertEqual(effect.call_count, 3)

    @unittest.skipUnless(importlib.util.find_spec("manim"), "Manim runtime is optional")
    def test_all_59_profiles_bilingual_bounds_and_caption_updates(self):
        from manim import tempconfig
        from representation.registry import RepresentationRegistry
        from rendering.layout.engine import LayoutEngine
        root = Path(__file__).resolve().parents[1]
        registry = RepresentationRegistry(root / "data/computer_core_kg_ch1_ch9_master_v0_6_dependencies.xlsx")
        profiles = [p for p in registry.profiles.values() if p.visual_archetype in EXECUTION_ARCHETYPES]
        self.assertEqual(len(profiles), 59)
        with tempconfig({"media_dir": str(root / "out_archetypes/batch02/test_media")}):
            for language in ("en", "zh"):
                env = {}
                code = _SCRIPT_TEMPLATE.replace("__PLAN_JSON__", repr(json.dumps({"metadata": {"language": language}})))
                exec(compile(code + "\n" + SOURCE, "execution_runtime", "exec"), env)
                for profile in profiles:
                    with self.subTest(language=language, profile=profile.profile_id):
                        w, h = LayoutEngine.BASE_SIZE[profile.visual_archetype]
                        spec = dict(archetype=profile.visual_archetype, width=w, height=h,
                                    name="Long English component title" if language == "en" else profile.profile_name,
                                    metadata={"render_requirements": profile.render_requirements})
                        node = env["make_node"](spec)
                        self.assertLessEqual(node.width, w + .081)
                        self.assertLessEqual(node.height, h + .081)
                spec = dict(knowledge_node_id="A", archetype="addressing", name="EA", width=4.2, height=2.2,
                            metadata={"render_requirements": ["base_plus_displacement"]})
                node = env["make_node"](spec)
                scene = Mock()
                # Mock attributes would mask the runtime's hasattr initialization.
                scene.address_examples = {}
                env["ensure_node"] = lambda *args: node
                for phase in ("show_inputs", "calculate", "show_result"):
                    beat = {"node_ids": ["A"], "phase_id": phase,
                            "parameters": {"address_values": {"base": 100, "offset": -8}} if phase == "show_inputs" else {}}
                    env["animate_address_calculation"](scene, {"nodes": [spec]}, {"A": node}, beat)
                self.assertEqual(next(iter(scene.address_examples.values()))["result"], 92)
                self.assertEqual(scene.play.call_count, 3)
