import ast
import tempfile
import unittest

from rendering.manim.isa_effects import SOURCE
from rendering.manim.isa_demo import build_isa_demo


class ISAEffectsTests(unittest.TestCase):
    def test_stored_direction_survives_reverse_traversal(self):
        env = {"relation_by_id": lambda spec, rid: spec}
        exec(compile(SOURCE, "isa_effects", "exec"), env)
        rel = {"stored_source_node_id": "implementation", "stored_target_node_id": "isa",
               "source_node_id": "isa", "target_node_id": "implementation"}
        for template, expected in (("abstract_to_concrete", ("isa", "implementation")),
                                   ("principle_to_mechanism", ("isa", "implementation")),
                                   ("factor_to_metric", ("implementation", "isa"))):
            self.assertEqual(env["isa_endpoints"](rel, {"template_id": template}), expected)

    def test_entire_isa_neighborhood_binds_and_generates(self):
        with tempfile.TemporaryDirectory() as out:
            script, report = build_isa_demo(out)
            # Includes the two supplemental RISC/CISC ISA categories.
            self.assertEqual(report["relation_count"], 18)
            self.assertTrue(all(s == "dedicated" for s in report["patterns"].values()), report)
            code = script.read_text(encoding="utf-8")
            ast.parse(code)
            self.assertIn("def animate_isa_relation", code)


if __name__ == "__main__":
    unittest.main()
