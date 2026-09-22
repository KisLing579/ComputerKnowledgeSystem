from __future__ import annotations

from kg.query import path_key, ExplanationPath

from .base import EvidenceContext, ExplanationEvidence, graph_score_path


class PathEvidenceStrategy:
    name = "path"

    def collect(self, ctx: EvidenceContext) -> ExplanationEvidence:
        a = ctx.goal.analysis
        candidates: list[ExplanationPath] = []
        seen: set[tuple[str, ...]] = set()

        if a.source_ids and a.target_ids:
            for source in a.source_ids:
                for target in a.target_ids:
                    if source == target:
                        continue
                    found = ctx.query_service.find_paths_between(
                        source,
                        target,
                        max_hops=ctx.settings.query.max_hops,
                        limit=ctx.settings.query.paths_per_pair,
                    )
                    for path in found:
                        if path_key(path) in seen:
                            continue
                        seen.add(path_key(path))
                        candidates.append(graph_score_path(path, ctx.matches))
        else:
            _, generated = ctx.query_service.generate_candidate_paths(ctx.goal.text)
            candidates = list(generated)

        ranked = tuple(ctx.ranker.rank(a, candidates)[:ctx.settings.query.candidate_path_limit])
        selected = ranked[0] if ranked else None
        return ExplanationEvidence(
            evidence_type=self.name,
            root=ctx.node(a.source_ids[0] if a.source_ids else None),
            ranked_paths=ranked,
            selected_path=selected,
            score=selected.explanation_score if selected else 0.0,
            metadata={"candidate_count": len(candidates), "ranked_count": len(ranked)},
        )
