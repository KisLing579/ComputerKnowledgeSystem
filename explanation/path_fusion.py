from __future__ import annotations

from dataclasses import dataclass, replace

from kg.query import ExplanationPath, NodeMatch, path_key, relationship_key
from .models import ExplanationPlan, ExplanationSegment
from .path_ranker import ExplanationPathRanker
from .question_analyzer import QuestionAnalyzer
from .validator import ExplanationPlanValidator
from .evidence_grouping import group_related_evidence


@dataclass(frozen=True)
class FusedAnswer:
    candidate_paths: tuple[ExplanationPath, ...]
    answer_graph: dict
    plan: ExplanationPlan


class PathFusionPlanner:
    """Preserve candidate edges, grouping known subgraphs into teaching scenes.

    The evidence graph may contain cycles. Its ordered teaching plan is a tree;
    source path membership preserves branch and convergence information.
    """

    def __init__(self, *, max_nodes_per_scene=8):
        self.max_nodes_per_scene = max_nodes_per_scene

    def fuse(self, question: str, matches: list[NodeMatch], paths: list[ExplanationPath]) -> FusedAnswer:
        analysis = QuestionAnalyzer().analyze(question, matches)
        unique: dict[tuple, ExplanationPath] = {}
        for path in paths:
            key = path_key(path)
            if key not in unique or path.score > unique[key].score:
                unique[key] = path
        ranked = ExplanationPathRanker().rank(analysis, unique.values())
        nodes: dict[str, dict] = {}
        edges: dict[tuple, dict] = {}
        memberships = []
        for index, ranked_path in enumerate(ranked, 1):
            path = ranked_path.path
            path_id = f"P{index:04d}"
            for nid, name in zip(path.node_ids, path.node_names):
                nodes.setdefault(nid, {"id": nid, "name": name})
            edge_ids = []
            for i, original in enumerate(path.relationships):
                key = relationship_key(original)
                if key not in edges:
                    rel = dict(original)
                    rel.setdefault("traversal_from", path.node_ids[i])
                    rel.setdefault("traversal_to", path.node_ids[i + 1])
                    edges[key] = {
                        "edge_id": f"E{len(edges) + 1:04d}",
                        "relationship": rel,
                        "source_path_ids": [],
                    }
                edge = edges[key]
                if path_id not in edge["source_path_ids"]:
                    edge["source_path_ids"].append(path_id)
                edge_ids.append(edge["edge_id"])
            memberships.append({"path_id": path_id, "node_ids": path.node_ids,
                                "edge_ids": edge_ids, "score": ranked_path.explanation_score})

        catalog = {m.id: {"id": m.id, "name": m.name, "name_en": m.name_en,
                             "semantic_type": m.semantic_type} for m in matches}
        catalog.update({nid: {**catalog.get(nid, {}), **node} for nid, node in nodes.items()})
        raw_relations = []
        for edge in edges.values():
            rel = dict(edge["relationship"])
            rel.update(kg_relation_id=rel.get("id"), id=edge["edge_id"],
                       source_path_ids=list(edge["source_path_ids"]))
            raw_relations.append(rel)
        groups = group_related_evidence(raw_relations, catalog, title=question,
            intent=analysis.intent.value, focal_ids=analysis.source_ids,
            max_nodes=self.max_nodes_per_scene)
        segments = []
        introduced: set[str] = set()
        for index, group in enumerate(groups, 1):
            rels = group.relations
            ids = tuple(dict.fromkeys(n for r in rels for n in
                        (r["traversal_from"], r["traversal_to"])))
            names = tuple(nodes[nid]["name"] for nid in ids)
            source_paths = list(dict.fromkeys(p for r in rels for p in r["source_path_ids"]))
            segments.append(ExplanationSegment(
                segment_id=f"EG{index:04d}" if group.scene_plan else rels[0]["id"],
                segment_type="evidence_group" if group.scene_plan else "fact", goal_id="fusion",
                title=group.scene_plan.visual_claim if group.scene_plan else " / ".join(names),
                intent=analysis.intent.value, root_id=group.focal_node_id,
                root_name=nodes[group.focal_node_id]["name"], node_ids=ids, node_names=names,
                relations=rels, referenced_node_ids=tuple(n for n in ids if n in introduced),
                semantic_scene_plan=group.scene_plan,
                metadata={"source_path_ids": source_paths, "evidence_relation_ids": [r["id"] for r in rels]},
            ))
            introduced.update(ids)
        root = ExplanationSegment(
            segment_id="answer", segment_type="sequence" if segments else "empty",
            goal_id="fusion", title=question, intent=analysis.intent.value,
            children=tuple(segments),
        )
        graph = {"nodes": list(nodes.values()), "edges": list(edges.values()),
                 "paths": memberships, "coverage": {
                     "candidate_count": len(ranked), "unique_relation_count": len(edges),
                     "planned_relation_count": sum(len(s.relations) for s in segments),
                     "evidence_group_count": len(groups), "relation_coverage": 1.0,
                 }}
        plan = ExplanationPlan(
            plan_type="explanation", structure_type=root.segment_type, goal="explain:fused_paths",
            question=question, intent=analysis.intent.value, root_segment=root,
            metadata={"fusion": "all_candidate_edges", **graph["coverage"]},
        )
        # Limits scale to the explicit candidate scope; never prune evidence.
        validation = ExplanationPlanValidator(
            max_depth=1, max_segments=len(segments) + 1, max_children=max(1, len(segments)),
        ).validate(plan)
        planned = {relationship_key(e["relationship"]) for e in edges.values()}
        expected = {relationship_key(r) for rp in ranked for r in rp.path.relationships}
        grouped_ids = [r['id'] for s in segments for r in s.relations]
        group_coverage_valid = (len(grouped_ids) == len(edges)
                                and set(grouped_ids) == {e['edge_id'] for e in edges.values()})
        if planned != expected or not group_coverage_valid or not validation.valid:
            raise ValueError("Fused answer failed relation coverage or plan validation")
        return FusedAnswer(tuple(r.path for r in ranked), graph, replace(plan, validation=validation))
