"""Build an offline ISA neighborhood animation from the configured workbook."""
import json
from dataclasses import asdict
from pathlib import Path

import openpyxl

from kg.config import load_settings
from kg.query import ExplanationPath
from explanation.path_fusion import PathFusionPlanner
from representation.registry import RepresentationRegistry
from representation.coverage import implementation_status
from resource_planning.binder import RepresentationBinder
from resource_planning.story_planner import VisualStoryPlanner
from rendering.layout.engine import LayoutEngine
from rendering.manim.script_generator import ManimScriptGenerator


def build_isa_demo(out_dir="out_isa"):
    settings = load_settings()
    registry = RepresentationRegistry(settings.data.workbook)
    workbook = openpyxl.load_workbook(settings.data.workbook, read_only=True, data_only=True)
    paths = []
    try:
        rows = workbook["KG_Relations"].iter_rows(values_only=True)
        headers = next(rows)
        for row in rows:
            raw = dict(zip(headers, row))
            src, dst = raw[":START_ID"], raw[":END_ID"]
            if "CO035" not in (src, dst) or raw.get("status") != "active":
                continue
            rel = dict(id=raw["rel_id"], type=raw[":TYPE"], stored_start_id=src,
                       stored_end_id=dst, traversal_from=src, traversal_to=dst,
                       default_animation_pattern=raw["default_animation_pattern"],
                       relation_layer=raw.get('relation_layer') or 'semantic',
                       confidence=raw.get("confidence:float", 1.0))
            paths.append(ExplanationPath((src, dst), (registry.node_name(src), registry.node_name(dst)), (rel,), 80))
    finally:
        workbook.close()
    fused = PathFusionPlanner().fuse("ISA是什么，它的组成、接口、实现、功能和性能影响有哪些？", [], paths)
    rep = RepresentationBinder(registry).bind(fused.plan)
    story = VisualStoryPlanner().plan(rep)
    render = LayoutEngine().layout(story)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    patterns = sorted({b.pattern_id for s in story.scenes for b in s.beats if b.pattern_id})
    report = {"node_id": "CO035", "relation_count": len(paths),
              "patterns": {p: implementation_status(p) for p in patterns}}
    for name, data in (("coverage.json", report), ("render_plan.json", asdict(render))):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    script = ManimScriptGenerator().generate(render, out / "isa_explanation.py")
    return script, report


if __name__ == "__main__":
    script, report = build_isa_demo()
    print(script)
    print(json.dumps(report, ensure_ascii=False))
