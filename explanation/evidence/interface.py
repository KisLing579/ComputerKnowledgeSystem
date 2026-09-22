from __future__ import annotations

from .base import EvidenceContext, ExplanationEvidence
from kg.query import relation_layer_priority, relationship_key


class InterfaceEvidenceStrategy:
    name = "interface"
    TIERS = (
        ("INTERFACES_WITH", "IMPLEMENTS", "DEPENDS_ON"),
        ("HAS_FUNCTION", "ENABLES", "BASED_ON", "REQUIRES"),
        ("PART_OF", "CONTAINS", "HAS_PART"),
        ("USES", "RELATED_TO"),
    )

    def collect(self, ctx: EvidenceContext) -> ExplanationEvidence:
        a = ctx.goal.analysis
        root = ctx.node(a.source_ids[0] if a.source_ids else None)
        if root is None:
            return ExplanationEvidence(self.name, score=0.0, metadata={"note": "interface root not found"})
        budget = ctx.settings.explanation.relation_neighbor_limit
        selected, seen, counts = [], set(), []
        # Separate queries prevent weak background from consuming the core budget.
        # Absent relationship types simply return no rows in Neo4j.
        for tier in self.TIERS:
            if tier == self.TIERS[3] and (counts[0] or counts[1]):
                # Weak background is a fallback, not extra syllabus once the
                # core/interface explanation already has direct evidence.
                counts.append(0)
                continue
            if len(selected) >= budget:
                counts.append(0)
                continue
            found = ctx.query_service.find_relation_neighbors(root.id, tier, limit=budget)
            found = sorted(found, key=lambda n: (relation_layer_priority(n.relationship),
                -float(n.relationship.get('confidence') or 1.0), n.id))
            count = 0
            for neighbor in found:
                key = (neighbor.id, relationship_key(neighbor.relationship))
                if key in seen or relation_layer_priority(neighbor.relationship) == 2:
                    continue
                seen.add(key)
                selected.append(neighbor)
                count += 1
                if len(selected) >= budget:
                    break
            counts.append(count)
        neighbors = tuple(selected)
        components = tuple(ctx.query_service.find_components(
            root.id,
            limit=ctx.settings.explanation.relation_neighbor_limit,
        )[: ctx.settings.explanation.max_children])
        score = 100.0 if neighbors else (55.0 if components else 0.0)
        return ExplanationEvidence(
            evidence_type=self.name,
            root=root,
            neighbors=neighbors,
            components=components,
            score=score,
            metadata={"interface_neighbor_count": len(neighbors), "component_count": len(components),
                      "relation_tiers": self.TIERS, "tier_counts": counts},
        )
