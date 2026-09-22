from __future__ import annotations

from .base import EvidenceContext, ExplanationEvidence


class RoleFunctionEvidenceStrategy:
    name = "role_function"

    def collect(self, ctx: EvidenceContext) -> ExplanationEvidence:
        a = ctx.goal.analysis
        root = ctx.node(a.source_ids[0] if a.source_ids else None)
        if root is None:
            return ExplanationEvidence(self.name, score=0.0, metadata={"note": "role/function root not found"})
        mediated = tuple(ctx.query_service.find_mediated_relations(
            root.id,
            limit=ctx.settings.explanation.relation_neighbor_limit,
        ))
        functional_types = tuple(
            x for x in a.preferred_relations if x not in {"PART_OF", "IS_A", "CONTAINS"}
        )
        direct = tuple(ctx.query_service.find_relation_neighbors(
            root.id,
            functional_types or ("MANAGES", "CONTROLS", "INTERFACES_WITH", "USES", "EXECUTES", "STORES", "IMPLEMENTS"),
            limit=ctx.settings.explanation.relation_neighbor_limit,
        )[: ctx.settings.explanation.max_children])
        score = 100.0 if (mediated or direct) else 0.0
        return ExplanationEvidence(
            evidence_type=self.name,
            root=root,
            neighbors=direct,
            mediated_relations=mediated,
            score=score,
            metadata={"mediated_count": len(mediated), "direct_count": len(direct)},
        )
