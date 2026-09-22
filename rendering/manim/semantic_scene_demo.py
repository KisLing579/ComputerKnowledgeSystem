"""Offline interface regression using real workbook evidence, without LLM/Neo4j."""
import json
from dataclasses import asdict
from pathlib import Path

import openpyxl

from kg.config import load_settings
from kg.query import KGQueryService, GraphNeighbor, relation_layer_priority
from explanation.path_fusion import PathFusionPlanner
from representation.registry import RepresentationRegistry
from resource_planning.binder import RepresentationBinder
from resource_planning.story_planner import VisualStoryPlanner
from resource_planning.scene_debug import scene_planning_report
from rendering.layout.engine import LayoutEngine
from rendering.subgraph import prepare_subgraph, group_subquestions
from .script_generator import ManimScriptGenerator


class WorkbookInterfaceQuery(KGQueryService):
    """Read-only direct-neighbor adapter for this offline regression, not path search."""
    def __init__(self, settings):
        super().__init__(None, settings)
        with_workbook = openpyxl.load_workbook(settings.data.workbook, read_only=True, data_only=True)
        try:
            def records(sheet):
                rows = with_workbook[sheet].iter_rows(values_only=True)
                headers = next(rows)
                return [dict(zip(headers, row)) for row in rows]
            self.catalog = {r['node_id:ID']: r for r in records(settings.data.nodes_sheet)
                            if r.get('status', 'active') == 'active'}
            self.edges = [r for r in records(settings.data.relations_sheet)
                          if r.get('status', 'active') == 'active']
        finally:
            with_workbook.close()

    def _all_active_nodes(self):
        return [dict(id=nid, **{k: r.get(k) or '' for k in
            ('name', 'name_en', 'semantic_type', 'core_level', 'definition')})
            for nid, r in self.catalog.items()]

    def find_paths_between(self, *args, **kwargs):
        return []  # Exercise the main pipeline's direct interface evidence route.

    def find_relation_neighbors(self, root_id, relation_types, *, limit=20):
        found = []
        for row in self.edges:
            a, b = row[':START_ID'], row[':END_ID']
            if root_id not in (a, b) or row[':TYPE'] not in relation_types:
                continue
            other = b if a == root_id else a
            if other not in self.catalog:
                continue
            rel = dict(id=row['rel_id'], type=row[':TYPE'], stored_start_id=a,
                stored_end_id=b, traversal_from=root_id, traversal_to=other,
                relation_layer=row.get('relation_layer') or 'semantic',
                default_animation_pattern=row.get('default_animation_pattern') or '',
                confidence=row.get('confidence:float') or 1.0)
            if relation_layer_priority(rel) == 2:
                continue
            node = self.catalog[other]
            found.append(GraphNeighbor(other, *(node.get(k) or '' for k in
                ('name', 'name_en', 'semantic_type', 'core_level', 'definition')), rel))
        return sorted(found, key=lambda n: (relation_layer_priority(n.relationship), n.id))[:limit]

    def find_components(self, root_id, *, limit=20):
        return [n for n in self.find_relation_neighbors(root_id, ('PART_OF', 'CONTAINS'), limit=200)
                if (n.relationship['type'] == 'PART_OF' and n.relationship['stored_end_id'] == root_id)
                or (n.relationship['type'] == 'CONTAINS' and n.relationship['stored_start_id'] == root_id)][:limit]


def build_interface_demo(out_dir='out_semantic_isa'):
    settings = load_settings()
    question = '为什么 ISA 被称为软硬件接口？'
    query = WorkbookInterfaceQuery(settings)
    matches, paths = query.generate_candidate_paths(question, limit=10)
    fused = PathFusionPlanner().fuse(question, matches, paths)
    representation = RepresentationBinder(RepresentationRegistry(settings.data.workbook)).bind(fused.plan)
    story = VisualStoryPlanner().plan(representation)
    render = LayoutEngine().layout(story)
    payload = prepare_subgraph(group_subquestions(asdict(render)))
    report = scene_planning_report(fused.plan, story, fused.answer_graph)
    report['validation_mode'] = 'offline_workbook_no_llm_no_neo4j'
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (('scene_planning_debug.json', report), ('explanation_plan.json', asdict(fused.plan)),
                       ('story_plan.json', asdict(story)), ('render_plan.json', payload)):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    script = ManimScriptGenerator().generate_payload(payload, out / 'isa_interface.py')
    return script, report


if __name__ == '__main__':
    script, report = build_interface_demo()
    print(script)
    print('Scene patterns:', [s['scene_pattern'] for s in report['scene_plans']])
