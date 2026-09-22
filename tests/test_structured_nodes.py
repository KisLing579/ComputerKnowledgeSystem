import unittest
import importlib.util
from pathlib import Path
from rendering.manim.structured_nodes import structured_design, SOURCE


class StructuredNodeTests(unittest.TestCase):
    def design(self, kind, *requirements):
        return structured_design({"archetype": kind, "metadata": {"render_requirements": requirements}}, True)

    def test_instruction_fields_preserve_32_bit_boundaries(self):
        for requirement, widths in [("op_rs_rt_rd_shamt_funct", [6, 5, 5, 5, 5, 6]),
                                    ("op_rs_rt_16bit_immediate", [6, 5, 5, 16]),
                                    ("op_26bit_target", [6, 26])]:
            design = self.design("instruction_format", requirement)
            self.assertEqual([n for _, n in design["fields"]], widths)
            self.assertEqual(sum(n for _, n in design["fields"]), 32)
        self.assertFalse(self.design("instruction_format", "variable_bytes")["bits"])
        self.assertFalse(self.design("instruction_format")["bits"])

    def test_character_values_are_actual_encodings(self):
        for character, binary in self.design("character_table", "7bit")["rows"]:
            self.assertEqual(ord(character), int(binary, 2))
            self.assertEqual(len(binary), 7)
        for character, point in self.design("character_table", "codepoints")["rows"]:
            self.assertEqual(ord(character), int(point[2:], 16))

    def test_profile_variants_do_not_collapse(self):
        self.assertEqual(self.design("stack_frame", "fp_stack")["top"], 0)
        self.assertEqual(self.design("stack_frame", "lifo")["top"], 2)
        self.assertEqual(self.design("memory_map", "dynamic_allocation")["highlight"], 2)
        for requirement in ["variables_to_registers", "patch_locations", "settings"]:
            self.assertNotEqual(self.design("table_mapping", requirement)["rows"], self.design("table_mapping")["rows"])

    def test_embedded_source_is_standalone(self):
        env = {}
        exec(compile(SOURCE, "structured_nodes", "exec"), env)
        self.assertEqual(env["structured_design"]({"archetype": "memory_map"}),
                         structured_design({"archetype": "memory_map"}))

    def test_layout_keeps_profile_requirements_in_generated_plan(self):
        from dataclasses import asdict
        from representation.models import RepresentationNode
        from resource_planning.models import StoryScene
        from rendering.layout.engine import LayoutEngine
        node = RepresentationNode("rep", "N1", "R type", "", "profile", "R type",
                                  "instruction_format", 1, render_requirements=("op_rs_rt_rd_shamt_funct",))
        scene = StoryScene("story", "segment", "title", "fact", "center_satellites", ("N1",))
        result = LayoutEngine()._layout_scene(scene, {"N1": node}, {}, "scene")
        spec = asdict(result.nodes[0])
        self.assertEqual(spec["metadata"]["render_requirements"], ["op_rs_rt_rd_shamt_funct"])
        self.assertEqual(len(structured_design(spec)["fields"]), 6)

    @unittest.skipUnless(importlib.util.find_spec("manim"), "Manim runtime is optional")
    def test_all_workbook_profiles_fit_their_node_bounds(self):
        import json
        from manim import tempconfig
        from representation.registry import RepresentationRegistry
        from rendering.layout.engine import LayoutEngine
        from rendering.manim.script_generator import _SCRIPT_TEMPLATE
        from rendering.manim.structured_nodes import STRUCTURED_ARCHETYPES
        root = Path(__file__).resolve().parents[1]
        registry = RepresentationRegistry(root / "data/computer_core_kg_ch1_ch9_master_v0_6_dependencies.xlsx")
        with tempconfig({"media_dir": str(root / "out_archetypes/batch01/test_media")}):
            for language in ("en", "zh"):
                env = {}
                code = _SCRIPT_TEMPLATE.replace("__PLAN_JSON__", repr(json.dumps({"metadata": {"language": language}})))
                exec(compile(code + "\n" + SOURCE, "gallery_runtime", "exec"), env)
                for profile in registry.profiles.values():
                    if profile.visual_archetype not in STRUCTURED_ARCHETYPES:
                        continue
                    with self.subTest(language=language, profile=profile.profile_id):
                        w, h = LayoutEngine.BASE_SIZE[profile.visual_archetype]
                        spec = dict(archetype=profile.visual_archetype, width=w, height=h,
                                    name="Long English component title" if language == "en" else profile.profile_name,
                                    metadata={"render_requirements": profile.render_requirements})
                        node = env["make_node"](spec)
                        self.assertLessEqual(node.width, w + .081)
                        self.assertLessEqual(node.height, h + .081)
                        self.assertGreater(len(node[1].visual_parts), 1)
