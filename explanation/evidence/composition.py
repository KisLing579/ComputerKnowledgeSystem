from __future__ import annotations

from .base import EvidenceContext, ExplanationEvidence


class CompositionEvidenceStrategy:
    name = "composition"

    def collect(self, ctx: EvidenceContext) -> ExplanationEvidence:
        a = ctx.goal.analysis
        root = ctx.node(a.source_ids[0] if a.source_ids else None)
        if root is None:
            return ExplanationEvidence(self.name, score=0.0, metadata={"note": "composition root not found"})
        components = tuple(
            ctx.query_service.find_components(
                root.id,
                limit=ctx.settings.explanation.relation_neighbor_limit,
            )[: ctx.settings.explanation.max_children]
        )
        score = 100.0 if components else 0.0
        return ExplanationEvidence(
            evidence_type=self.name,
            root=root,
            components=components,
            score=score,
            metadata={"component_count": len(components)},
        )
