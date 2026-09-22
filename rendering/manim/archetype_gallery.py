"""Offline batch-1 gallery and a reproducible workbook archetype coverage report."""
import argparse
import ast
import json
from collections import Counter
from pathlib import Path

from representation.registry import RepresentationRegistry
from rendering.layout.engine import LayoutEngine
from .script_generator import _SCRIPT_TEMPLATE
from .structured_nodes import SOURCE, STRUCTURED_ARCHETYPES
from .execution_nodes import SOURCE as EXECUTION_SOURCE, EXECUTION_ARCHETYPES
from .memory_nodes import SOURCE as MEMORY_SOURCE, MEMORY_ARCHETYPES
from .memory_system_nodes import SOURCE as MEMORY_SYSTEM_SOURCE, MEMORY_SYSTEM_ARCHETYPES
from .processor_nodes import SOURCE as PROCESSOR_SOURCE, PROCESSOR_ARCHETYPES
from .memory_behavior import SOURCE as MEMORY_BEHAVIOR_SOURCE, MEMORY_BEHAVIOR_ARCHETYPES


def coverage_report(registry):
    tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", repr("{}")))
    make = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "make_node")
    implemented = set()
    branch = next(n for n in make.body if isinstance(n, ast.If))
    while isinstance(branch, ast.If):
        if isinstance(branch.test, ast.Compare) and isinstance(branch.test.left, ast.Name) and branch.test.left.id == "archetype":
            value = ast.literal_eval(branch.test.comparators[0])
            implemented.update([value] if isinstance(value, str) else value)
        branch = branch.orelse[0] if branch.orelse else None
    counts = Counter(p.visual_archetype for p in registry.profiles.values())
    entries = [{"archetype": key, "definition": value.definition,
                "status": "specialized" if key in implemented else "default" if key == "functional_block" else "fallback",
                "profiles": counts[key], "batch": 1 if key in STRUCTURED_ARCHETYPES else 2 if key in EXECUTION_ARCHETYPES else 3 if key in MEMORY_ARCHETYPES else 4 if key in MEMORY_SYSTEM_ARCHETYPES else 5 if key in PROCESSOR_ARCHETYPES else 6 if key in MEMORY_BEHAVIOR_ARCHETYPES else None}
               for key, value in sorted(registry.archetypes.items())]
    bound_nodes = {nid for nid, bindings in registry.bindings_by_node.items()
                   if any(registry.profiles.get(b.profile_id) and registry.profiles[b.profile_id].visual_archetype in implemented for b in bindings)}
    return {"counts": dict(Counter(e["status"] for e in entries)), "archetypes": entries,
            "nodes_with_specialized_profile": len(bound_nodes),
            "note": "Node graphics coverage only; specialized does not imply all process animations or profile semantics are complete."}


def build_gallery(workbook, out_dir, language="en", batch=1):
    registry = RepresentationRegistry(workbook)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "coverage.json").write_text(json.dumps(coverage_report(registry), ensure_ascii=False, indent=2), encoding="utf-8")
    names = {"instruction_format": ("R-type instruction", "R型指令格式", ["op_rs_rt_rd_shamt_funct"]),
             "stack_frame": ("Stack frame", "栈帧", ["frame_boundaries"]),
             "memory_map": ("Memory layout", "内存布局", ["text_data_heap_stack"]),
             "character_table": ("Unicode", "Unicode", ["codepoints"]),
             "table_mapping": ("Symbol table", "符号表", ["symbol_to_address"])}
    examples = [(kind, *values) for kind, values in names.items()]
    if batch == 2:
        examples = [("addressing", "Base + offset", "基址加偏移", ["base_plus_displacement"]),
                    ("addressing", "Array indexing", "数组下标", ["base_plus_scaled_index"]),
                    ("addressing", "Branch target", "分支目标", ["pc_plus_4"]),
                    ("control_flow", "Conditional branch", "条件分支", ["compare_equal"]),
                    ("datapath_graph", "Multiplexer", "多路复用器", ["select_signal"]),
                    ("datapath_graph", "ALU execution", "ALU执行", ["alu_inputs"])]
    if batch == 3:
        examples = [("cache_address_decode", "Cache address fields", "缓存地址字段", ["index_bits"]),
                    ("cache_lookup", "Cache tag lookup", "缓存标记查找", ["tag_match"]),
                    ("cache_set_lookup", "Set-associative cache", "组相联缓存", ["set_index"]),
                    ("tlb_translation", "TLB translation", "TLB地址转换", ["vpn_match"]),
                    ("page_table_map", "Page table", "页表", ["pte"]),
                    ("address_translation", "Virtual to physical", "虚拟地址到物理地址", ["offset_preserved"])]
    if batch == 4:
        examples = [("cache_write_policy", "Write-back cache", "写回缓存", ["cache_only_write"]),
                    ("replacement_choice", "LRU replacement", "LRU替换", ["recency"]),
                    ("memory_hierarchy_stack", "Memory hierarchy", "存储层次", ["L3"]),
                    ("virtual_memory_map", "Page residency", "页面驻留", ["virtual_page"]),
                    ("page_fault_flow", "Page fault handling", "缺页处理", ["page_in"]),
                    ("memory_request_timeline", "Overlapping requests", "重叠请求", ["overlap"])]
    if batch == 5:
        examples = [("timing_state", "Clocked state", "时钟状态", ["clock_edge"]),
                    ("control_fsm", "Control state machine", "控制状态机", ["current_state"]),
                    ("pipeline_timeline", "Pipeline overlap", "流水线重叠", ["overlap"]),
                    ("hazard_dependency", "Forwarding", "数据转发", ["bypass"]),
                    ("branch_predictor", "Two-bit predictor", "两位预测器", ["four_states"]),
                    ("dynamic_schedule", "Out-of-order execution", "乱序执行", ["in_order_commit"])]
    if batch == 6:
        examples = [("cache_map", "Cache mapping", "缓存映射", []),
                    ("banked_memory", "Memory banks", "交错存储体", []),
                    ("locality_trace", "Temporal locality", "时间局部性", ["temporal"]),
                    ("miss_taxonomy", "Miss classification", "缺失分类", []),
                    ("protection_boundary", "Protection boundary", "权限边界", []),
                    ("process_switch", "Context switch", "上下文切换", [])]
    specs = []
    for i, (kind, en, zh, req) in enumerate(examples):
        w, h = LayoutEngine.BASE_SIZE[kind]
        specs.append(dict(knowledge_node_id="gallery_" + str(i), archetype=kind, name=en if language == "en" else zh,
                          width=w, height=h, scale=.7 if batch in (5, 6) else .78 if batch == 4 else .82 if batch == 3 else .9,
                          x=(i % 3 - 1) * 4.35, y=1.6 if i < 3 else -1.4,
                          metadata={"render_requirements": req}))
    code = _SCRIPT_TEMPLATE.replace("__PLAN_JSON__", repr(json.dumps({"metadata": {"language": language}}))) + "\n" + SOURCE + "\n" + EXECUTION_SOURCE + "\n" + MEMORY_SOURCE + "\n" + MEMORY_SYSTEM_SOURCE + "\n" + PROCESSOR_SOURCE + "\n" + MEMORY_BEHAVIOR_SOURCE
    code += "\nGALLERY_SPECS = " + repr(specs) + r'''

class ArchetypeGallery(Scene):
    def construct(self):
        nodes = VGroup(*[make_node(spec) for spec in GALLERY_SPECS])
        self.play(FadeIn(nodes), run_time=.8)
        # Structural walkthrough only; no claim of simulating execution.
        for node in nodes:
            self.play(Indicate(node, scale_factor=1.025), run_time=.5)
        self.wait(1)
'''
    if batch == 2:
        code += r'''

class AddressCalculationDemo(Scene):
    def construct(self):
        spec = dict(GALLERY_SPECS[0], x=0, y=.6, width=8, height=4, scale=1)
        nodes = {spec["knowledge_node_id"]: make_node(spec)}
        self.add(*nodes.values())
        scene_spec = {"scene_id": "address_demo", "nodes": [spec]}
        for phase in ("show_inputs", "calculate", "show_result"):
            animate_beat(self, scene_spec, nodes,
                         {"template_id": "address_calc", "phase_id": phase,
                          "node_ids": [spec["knowledge_node_id"]], "duration": 1.2})
            self.wait(.6)
        self.wait(1)
'''
    path = out / ("gallery_" + language + ".py")
    path.write_text(code, encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", default="data/computer_core_kg_ch1_ch9_master_v0_6_dependencies.xlsx")
    parser.add_argument("--out-dir", default="out_archetypes/batch01")
    parser.add_argument("--language", choices=["zh", "en"], default="en")
    parser.add_argument("--batch", type=int, choices=[1, 2, 3, 4, 5, 6], default=1)
    args = parser.parse_args()
    print(build_gallery(args.workbook, args.out_dir, args.language, args.batch))
