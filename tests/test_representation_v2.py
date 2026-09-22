from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys
import types

# Test-only neo4j stub: representation tests do not touch a live database.
if "neo4j" not in sys.modules:
    neo4j_stub = types.ModuleType("neo4j")
    class _DummyGraphDatabase: pass
    class _DummyManagedTransaction: pass
    neo4j_stub.GraphDatabase = _DummyGraphDatabase
    neo4j_stub.ManagedTransaction = _DummyManagedTransaction
    sys.modules["neo4j"] = neo4j_stub

from explanation.models import ExplanationPlan, ExplanationSegment
from representation.animation_grammar import AnimationGrammar
from representation.registry import RepresentationRegistry
from resource_planning.binder import RepresentationBinder
from resource_planning.story_planner import VisualStoryPlanner
from rendering.layout.engine import LayoutEngine
from rendering.manim.script_generator import ManimScriptGenerator


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "data" / "computer_core_kg_ch1_v0_2.xlsx"


def plan_from_segment(segment: ExplanationSegment, question: str = "test") -> ExplanationPlan:
    return ExplanationPlan(
        plan_type="explanation",
        structure_type=segment.segment_type,
        goal="test",
        question=question,
        intent=segment.intent,
        root_id=segment.root_id,
        root_name=segment.root_name,
        root_segment=segment,
        explanation_score=95.0,
    )


class RepresentationV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = RepresentationRegistry(WORKBOOK)
        cls.binder = RepresentationBinder(cls.registry, AnimationGrammar())
        cls.story = VisualStoryPlanner()
        cls.layout = LayoutEngine()

    def test_is_a_becomes_category_embed_not_raw_arrow(self):
        rel = {
            "id": "T_ISA_ISA",
            "type": "IS_A",
            "stored_start_id": "CO035",
            "stored_end_id": "CO034",
            "traversal_from": "CO035",
            "traversal_to": "CO034",
            "confidence": 1.0,
            "default_animation_pattern": "CATEGORY_GROUP",
        }
        seg = ExplanationSegment(
            segment_id="S1",
            segment_type="definition",
            goal_id="G1",
            title="什么是ISA？",
            intent="definition",
            root_id="CO035",
            root_name="指令集体系结构 / ISA",
            node_ids=("CO035", "CO034"),
            node_names=("指令集体系结构 / ISA", "抽象"),
            relations=(rel,),
            score=95.0,
        )
        rep = self.binder.bind(plan_from_segment(seg, "什么是ISA？"))
        rr = rep.root_segment.relations[0]
        self.assertEqual(rr.pattern_id, "CATEGORY_GROUP")
        self.assertEqual(rr.grammar_template_id, "category_embed")
        self.assertEqual(rr.relation_label_mode, "hidden")
        story = self.story.plan(rep)
        self.assertEqual(story.scenes[0].layout_hint, "category_embed")
        actions = [b.phase_id for b in story.scenes[0].beats]
        self.assertIn("embed_member", actions)

    def test_part_of_uses_inside_reveal(self):
        rel = {
            "id": "T_DP_CPU",
            "type": "PART_OF",
            "stored_start_id": "CO023",
            "stored_end_id": "CO022",
            "traversal_from": "CO022",
            "traversal_to": "CO023",
            "confidence": 1.0,
            "default_animation_pattern": "REVEAL_INSIDE",
        }
        child = ExplanationSegment(
            segment_id="S2.1", segment_type="fact", goal_id="G2", title="CPU包含数据通路",
            intent="composition", root_id="CO023", root_name="数据通路",
            node_ids=("CO022", "CO023"), node_names=("处理器 / CPU", "数据通路"), relations=(rel,), score=95.0,
        )
        seg = ExplanationSegment(
            segment_id="S2", segment_type="branch", goal_id="G2", title="CPU由哪些部分组成？",
            intent="composition", root_id="CO022", root_name="处理器 / CPU",
            node_ids=("CO022",), node_names=("处理器 / CPU",), children=(child,), score=95.0,
        )
        rep = self.binder.bind(plan_from_segment(seg, "CPU由哪些部分组成？"))
        story = self.story.plan(rep)
        self.assertEqual(story.scenes[0].layout_hint, "inside_container")
        self.assertTrue(any(b.template_id == "reveal_inside" for b in story.scenes[0].beats))

    def test_translation_uses_mediator_pipeline(self):
        rel = {
            "id": "T_TRANS",
            "type": "TRANSFORMS_TO",
            "stored_start_id": "CO011",
            "stored_end_id": "CO012",
            "traversal_from": "CO011",
            "traversal_to": "CO012",
            "mediated_by": "CO008",
            "confidence": 1.0,
            "default_animation_pattern": "PIPELINE_TRANSFORM",
        }
        seg = ExplanationSegment(
            segment_id="S3", segment_type="linear", goal_id="G3", title="编译",
            intent="transformation_execution", root_id="CO011", root_name="高级语言程序",
            node_ids=("CO011", "CO012"), node_names=("高级语言程序", "汇编语言程序"), relations=(rel,), score=95.0,
        )
        rep = self.binder.bind(plan_from_segment(seg, "高级语言怎么编译？"))
        rr = rep.root_segment.relations[0]
        self.assertEqual(rr.mediator_node_id, "CO008")
        self.assertEqual(rr.grammar_template_id, "pipeline_transform")
        story = self.story.plan(rep)
        self.assertIn("CO008", story.scenes[0].node_ids)
        self.assertTrue(any(b.phase_id == "pass_through" for b in story.scenes[0].beats))

    def test_layout_and_generated_script_compile(self):
        rel = {
            "id": "T_ISA_ISA",
            "type": "IS_A",
            "stored_start_id": "CO035",
            "stored_end_id": "CO034",
            "traversal_from": "CO035",
            "traversal_to": "CO034",
            "confidence": 1.0,
            "default_animation_pattern": "CATEGORY_GROUP",
        }
        seg = ExplanationSegment(
            segment_id="S4", segment_type="definition", goal_id="G4", title="什么是ISA？",
            intent="definition", root_id="CO035", root_name="指令集体系结构 / ISA",
            node_ids=("CO035", "CO034"), node_names=("指令集体系结构 / ISA", "抽象"), relations=(rel,), score=95.0,
        )
        rep = self.binder.bind(plan_from_segment(seg, "什么是ISA？"))
        story = self.story.plan(rep)
        render = self.layout.layout(story)
        self.assertEqual(render.scenes[0].layout, "category_embed")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "generated.py"
            ManimScriptGenerator().generate(render, out)
            compile(out.read_text(encoding="utf-8"), str(out), "exec")


if __name__ == "__main__":
    unittest.main()
