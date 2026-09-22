from __future__ import annotations

from .base import EvidenceContext, ExplanationEvidence


def _covered_nodes(relations) -> set[str]:
    out: set[str] = set()
    for edge in relations:
        out.add(edge.source_id)
        out.add(edge.target_id)
    return out


def _component_count(node_ids, relations) -> int:
    ids = list(dict.fromkeys(str(x) for x in node_ids if str(x)))
    if not ids:
        return 0
    parent = {x: x for x in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        if a not in parent or b not in parent:
            return
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for edge in relations:
        union(str(edge.source_id), str(edge.target_id))
    return len({find(x) for x in ids})


class RelationStructureEvidenceStrategy:
    name = "relation_structure"

    def collect(self, ctx: EvidenceContext) -> ExplanationEvidence:
        a = ctx.goal.analysis
        # Explicit “从A到B” relation questions are path-shaped even though the
        # coarse intent is relation_structure. Keep that decision local to the
        # evidence strategy rather than in the recursive planner.
        if a.source_ids and a.target_ids:
            from .path import PathEvidenceStrategy
            evidence = PathEvidenceStrategy().collect(ctx)
            return ExplanationEvidence(
                evidence_type="path",
                root=evidence.root,
                ranked_paths=evidence.ranked_paths,
                selected_path=evidence.selected_path,
                score=evidence.score,
                metadata={**evidence.metadata, "routed_from": self.name, "reason": "explicit_source_target"},
            )

        named_ids = list(dict.fromkeys(a.direct_mention_ids))
        if len(named_ids) < 2:
            return ExplanationEvidence(self.name, score=0.0, metadata={"note": "fewer than two named concepts"})

        relations = tuple(ctx.query_service.find_relations_among(named_ids, limit=100))
        base_components = _component_count(named_ids, relations)
        root = ctx.node(a.source_ids[0] if a.source_ids else named_ids[0])
        chosen_hub = None

        if base_components > 1:
            best = None
            best_relations = relations
            best_component_count = base_components
            best_coverage = len(_covered_nodes(relations) & set(named_ids))
            for hub in ctx.query_service.find_connecting_hubs(named_ids, limit=10):
                expanded_ids = named_ids + [hub.id]
                hub_relations = tuple(ctx.query_service.find_relations_among(expanded_ids, limit=100))
                component_count = _component_count(expanded_ids, hub_relations)
                coverage = len(_covered_nodes(hub_relations) & set(named_ids))
                candidate_key = (component_count, -coverage, hub.id)
                best_key = (best_component_count, -best_coverage, getattr(best, "id", "~"))
                if candidate_key < best_key:
                    best = hub
                    best_relations = hub_relations
                    best_component_count = component_count
                    best_coverage = coverage
            if best is not None and best_component_count < base_components:
                chosen_hub = best
                relations = best_relations
                # Convert the hub to a NodeMatch-like root using available fields.
                from kg.query import NodeMatch
                root = NodeMatch(
                    id=best.id,
                    name=best.name,
                    name_en=best.name_en,
                    semantic_type=best.semantic_type,
                    core_level=best.core_level,
                    definition=best.definition,
                    score=100.0,
                )

        final_ids = named_ids + ([chosen_hub.id] if chosen_hub else [])
        final_components = _component_count(final_ids, relations)
        coverage = len(_covered_nodes(relations) & set(named_ids)) / max(1, len(named_ids))
        score = max(0.0, min(100.0, 70.0 * coverage + (30.0 if final_components <= 1 else 0.0)))
        return ExplanationEvidence(
            evidence_type=self.name,
            root=root,
            relations=relations,
            score=round(score, 2),
            metadata={
                "named_concept_ids": tuple(named_ids),
                "chosen_hub_id": chosen_hub.id if chosen_hub else None,
                "base_component_count": base_components,
                "final_component_count": final_components,
                "named_coverage": round(coverage, 4),
            },
        )
