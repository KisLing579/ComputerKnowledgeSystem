from __future__ import annotations

from kg.query import relation_layer_priority

from .base import EvidenceContext, ExplanationEvidence


class DefinitionEvidenceStrategy:
    """0-1 hop, definition-first evidence.

    Definition questions must never fall back to arbitrary multi-hop paths.  The
    node's own definition is primary evidence; only a small whitelist of direct
    defining relations is admitted as support.
    """

    name = "definition"
    _ALLOWED = (
        "IS_A",
        "PART_OF",
        "CONTAINS",
        "INTERFACES_WITH",
        "IMPLEMENTS",
        "DESCRIBES",
        "CONTRASTS_WITH",
    )
    _REL_PRIORITY = {
        "IS_A": 1.00,
        "PART_OF": 0.95,
        "CONTAINS": 0.95,
        "INTERFACES_WITH": 0.90,
        "IMPLEMENTS": 0.75,
        "DESCRIBES": 0.70,
        "CONTRASTS_WITH": 0.55,
    }

    def collect(self, ctx: EvidenceContext) -> ExplanationEvidence:
        analysis = ctx.goal.analysis
        root_id = analysis.source_ids[0] if analysis.source_ids else (
            analysis.direct_mention_ids[0] if analysis.direct_mention_ids else None
        )
        root = ctx.node(root_id)
        if root is None:
            return ExplanationEvidence(
                evidence_type=self.name,
                score=0.0,
                metadata={"note": "definition root not found"},
            )

        limit = min(
            ctx.settings.explanation.definition_support_limit,
            ctx.settings.explanation.relation_neighbor_limit,
        )
        neighbors = ctx.query_service.find_relation_neighbors(
            root.id,
            self._ALLOWED,
            limit=max(limit * 3, limit),
        )

        def key(n):
            rel = str(n.relationship.get("type", ""))
            conf = float(n.relationship.get("confidence", 1.0) or 1.0)
            return (relation_layer_priority(n.relationship), -self._REL_PRIORITY.get(rel, 0.0), -conf, n.id)

        # Deduplicate and cap.  All evidence remains one hop from the defined node.
        dedup = {}
        for n in neighbors:
            dedup.setdefault(n.id, n)
        selected = tuple(sorted(dedup.values(), key=key)[:limit])

        has_definition = bool((root.definition or "").strip())
        support_quality = 0.0
        if selected:
            support_quality = sum(
                float(n.relationship.get("confidence", 1.0) or 1.0) for n in selected
            ) / len(selected)
        score = min(100.0, (70.0 if has_definition else 35.0) + 30.0 * support_quality)

        return ExplanationEvidence(
            evidence_type=self.name,
            root=root,
            definition_text=(root.definition or "").strip(),
            neighbors=selected,
            score=round(score, 2),
            metadata={
                "hop_budget": 1,
                "allowed_relations": self._ALLOWED,
                "support_count": len(selected),
                "definition_present": has_definition,
            },
        )
