from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from explanation.models import ExplanationPlan, ExplanationSegment
from manim_backend.script_generator import ManimScriptGenerator
from visual.binder import VisualBinder
from visual.registry import VisualRegistry
from visual.scene_planner import ScenePlanner


WORKBOOK = Path(__file__).resolve().parents[1] / "data" / "computer_core_kg_ch1_v0_2.xlsx"


def rel(rid, typ, a, b, pattern="", narrative=None, mediator=""):
    return {
        "id": rid,
        "type": typ,
        "stored_start_id": a,
        "stored_end_id": b,
        "traversal_from": a,
        "traversal_to": b,
        "narrative_relation_type": narrative or typ,
        "confidence": 1.0,
        "default_animation_pattern": pattern,
        "mediated_by": mediator,
    }


def plan_from(segment: ExplanationSegment, question="test") -> ExplanationPlan:
    return ExplanationPlan(
        plan_type="explanation",
        structure_type=segment.segment_type,
        goal="test",
        question=question,
        intent=segment.intent,
        root_id=segment.root_id,
        root_name=segment.root_name,
        root_segment=segment,
        explanation_score=segment.score,
    )


class VisualPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = VisualRegistry(WORKBOOK)
        cls.binder = VisualBinder(cls.registry)
        cls.scene_planner = ScenePlanner()

    def test_registry_reports_known_workbook_pattern_gaps(self):
        validation = self.registry.validate()
        text = "\n".join(validation.warnings)
        self.assertIn("CONNECT_HIGHLIGHT", text)
        self.assertIn("PROCESS_FLOW", text)

    def test_translation_linear_uses_special_profiles_and_pipeline_pattern(self):
        seg = ExplanationSegment(
            segment_id="S.G1",
            segment_type="linear",
            goal_id="G1",
            title="高级语言如何变成CPU指令",
            intent="transformation_execution",
            root_id="CO011",
            root_name="高级语言程序",
            node_ids=("CO011", "CO012", "CO013", "CO019", "CO022"),
            node_names=("高级语言程序", "汇编语言程序", "机器代码", "指令", "处理器 / CPU"),
            relations=(
                rel("R1", "TRANSFORMS_TO", "CO011", "CO012", mediator="CO008"),
                rel("R2", "TRANSFORMS_TO", "CO012", "CO013", mediator="CO009"),
                rel("R3", "USES", "CO013", "CO019"),
                rel("R4", "EXECUTES", "CO019", "CO022", narrative="EXECUTED_BY"),
            ),
            score=99.0,
        )
        visual = self.binder.bind(plan_from(seg))
        by_node = {n.knowledge_node_id: n for n in visual.root_segment.nodes}
        self.assertEqual(by_node["CO011"].profile_id, "VP_CO011_TRANSLATION")
        self.assertEqual(by_node["CO012"].profile_id, "VP_CO012_TRANSLATION")
        self.assertEqual(by_node["CO013"].profile_id, "VP_CO013_TRANSLATION")
        self.assertEqual(by_node["CO019"].profile_id, "VP_CO019_TOKEN")
        self.assertEqual(by_node["CO022"].profile_id, "VP_CO022_DATAPATH")
        self.assertEqual(visual.root_segment.relations[0].pattern_id, "PIPELINE_TRANSFORM")
        self.assertTrue(any(n.knowledge_node_id == "CO008" and n.role == "mediator" for n in visual.root_segment.nodes))

        scenes = self.scene_planner.plan(visual)
        self.assertEqual(len(scenes.scenes), 1)
        self.assertEqual(scenes.scenes[0].scene_type, "linear_flow")
        self.assertIn("编译器", [n.name for n in scenes.scenes[0].nodes])

    def test_cpu_composition_becomes_inside_container_branch_scene(self):
        c1 = ExplanationSegment(
            segment_id="S.G2.1",
            segment_type="fact",
            goal_id="G2",
            title="CPU → 数据通路",
            intent="composition",
            root_id="CO023",
            root_name="数据通路",
            node_ids=("CO022", "CO023"),
            node_names=("处理器 / CPU", "数据通路"),
            relations=(rel("R5", "PART_OF", "CO022", "CO023", narrative="CONTAINS"),),
            score=100,
        )
        c2 = ExplanationSegment(
            segment_id="S.G2.2",
            segment_type="fact",
            goal_id="G2",
            title="CPU → 控制器",
            intent="composition",
            root_id="CO024",
            root_name="控制器",
            node_ids=("CO022", "CO024"),
            node_names=("处理器 / CPU", "控制器"),
            relations=(rel("R6", "PART_OF", "CO022", "CO024", narrative="CONTAINS"),),
            score=100,
        )
        root = ExplanationSegment(
            segment_id="S.G2",
            segment_type="branch",
            goal_id="G2",
            title="CPU由哪些部分组成？",
            intent="composition",
            root_id="CO022",
            root_name="处理器 / CPU",
            node_ids=("CO022",),
            node_names=("处理器 / CPU",),
            children=(c1, c2),
            score=100,
            metadata={"purpose": "composition"},
        )
        visual = self.binder.bind(plan_from(root))
        self.assertEqual(visual.root_segment.nodes[0].profile_id, "VP_CO022_STRUCTURE")
        scenes = self.scene_planner.plan(visual)
        self.assertEqual(scenes.scenes[0].scene_type, "branch_reveal")
        self.assertEqual(scenes.scenes[0].layout, "inside_container")
        self.assertEqual({n.knowledge_node_id for n in scenes.scenes[0].nodes}, {"CO022", "CO023", "CO024"})

    def test_recursive_sequence_flattens_in_order_and_reuses_nodes(self):
        linear = ExplanationSegment(
            segment_id="S.G3.1",
            segment_type="linear",
            goal_id="G3.1",
            title="程序翻译",
            intent="transformation_execution",
            root_id="CO011",
            root_name="高级语言程序",
            node_ids=("CO011", "CO012"),
            node_names=("高级语言程序", "汇编语言程序"),
            relations=(rel("R7", "TRANSFORMS_TO", "CO011", "CO012"),),
            score=95,
        )
        branch_child = ExplanationSegment(
            segment_id="S.G3.2.1",
            segment_type="fact",
            goal_id="G3.2",
            title="OS管理内存",
            intent="role_function",
            root_id="CO025",
            root_name="存储器",
            node_ids=("CO007", "CO025"),
            node_names=("操作系统", "存储器"),
            relations=(rel("R8", "MANAGES", "CO007", "CO025"),),
            score=95,
        )
        branch = ExplanationSegment(
            segment_id="S.G3.2",
            segment_type="branch",
            goal_id="G3.2",
            title="操作系统作用",
            intent="role_function",
            root_id="CO007",
            root_name="操作系统",
            node_ids=("CO007",),
            node_names=("操作系统",),
            children=(branch_child,),
            score=95,
        )
        seq = ExplanationSegment(
            segment_id="S.G3",
            segment_type="sequence",
            goal_id="G3",
            title="复合解释",
            intent="general",
            children=(linear, branch),
            score=95,
        )
        scenes = self.scene_planner.plan(self.binder.bind(plan_from(seq)))
        self.assertEqual([s.scene_type for s in scenes.scenes], ["linear_flow", "branch_reveal"])

    def test_generated_manim_script_is_valid_python_syntax(self):
        seg = ExplanationSegment(
            segment_id="S.G4",
            segment_type="fact",
            goal_id="G4",
            title="ISA接口硬件",
            intent="interface_role",
            root_id="CO035",
            root_name="ISA",
            node_ids=("CO035", "CO021"),
            node_names=("ISA", "硬件"),
            relations=(rel("R9", "INTERFACES_WITH", "CO035", "CO021"),),
            score=100,
        )
        scene_plan = self.scene_planner.plan(self.binder.bind(plan_from(seg, "为什么ISA是接口？")))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "generated.py"
            ManimScriptGenerator().generate(scene_plan, path)
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
            self.assertIn("class GeneratedExplanation(Scene)", source)


if __name__ == "__main__":
    unittest.main()
