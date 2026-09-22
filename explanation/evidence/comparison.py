from __future__ import annotations

from .base import EvidenceContext, ExplanationEvidence


class ComparisonEvidenceStrategy:
    name = "comparison"
    _SUPPORT_TYPES = ("CONTRASTS_WITH", "IS_A", "PART_OF", "CONTAINS", "USES", "DESCRIBES")

    def collect(self, ctx: EvidenceContext) -> ExplanationEvidence:
        a = ctx.goal.analysis
        ids = list(dict.fromkeys((*a.source_ids, *a.target_ids, *a.direct_mention_ids)))
        if len(ids) < 2:
            return ExplanationEvidence(self.name, score=0.0, metadata={"note": "comparison needs two concepts"})
        left = ctx.node(ids[0])
        right = ctx.node(next((x for x in ids[1:] if x != ids[0]), None))
        if left is None or right is None:
            return ExplanationEvidence(self.name, score=0.0, metadata={"note": "comparison endpoints not found"})

        direct = tuple(ctx.query_service.find_relations_among([left.id, right.id], limit=20))
        limit = min(ctx.settings.explanation.comparison_support_limit, ctx.settings.explanation.relation_neighbor_limit)
        left_neighbors = tuple(ctx.query_service.find_relation_neighbors(left.id, self._SUPPORT_TYPES, limit=limit))
        right_neighbors = tuple(ctx.query_service.find_relation_neighbors(right.id, self._SUPPORT_TYPES, limit=limit))
        has_contrast = any(str(r.relationship.get("type", "")) == "CONTRASTS_WITH" for r in direct)
        score = 100.0 if has_contrast else (80.0 if direct else 65.0)
        return ExplanationEvidence(
            evidence_type=self.name,
            root=left,
            relations=direct,
            left_neighbors=left_neighbors,
            right_neighbors=right_neighbors,
            score=score,
            metadata={"left_id": left.id, "left_name": left.name, "right_id": right.id, "right_name": right.name, "has_explicit_contrast": has_contrast},
        )
