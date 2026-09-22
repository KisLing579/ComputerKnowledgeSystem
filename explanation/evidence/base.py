from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from kg.config import Settings
from kg.query import ExplanationPath, GraphNeighbor, GraphRelation, KGQueryService, NodeMatch

from ..models import ExplanationGoal, RankedExplanationPath
from ..path_ranker import ExplanationPathRanker


@dataclass(frozen=True)
class EvidenceContext:
    """Inputs available to one atomic explanation-evidence strategy."""

    goal: ExplanationGoal
    matches: tuple[NodeMatch, ...]
    query_service: KGQueryService
    ranker: ExplanationPathRanker
    settings: Settings

    def node(self, node_id: str | None = None) -> NodeMatch | None:
        if node_id is None:
            return self.matches[0] if self.matches else None
        return next((m for m in self.matches if m.id == node_id), None)


@dataclass(frozen=True)
class ExplanationEvidence:
    """KG-backed evidence for one atomic explanation goal.

    Evidence is deliberately distinct from ExplanationSegment.  Strategies only
    decide *what evidence to retrieve*; the structurer decides how that evidence
    should be narrated/visualized.
    """

    evidence_type: str
    root: NodeMatch | None = None
    definition_text: str = ""
    neighbors: tuple[GraphNeighbor, ...] = ()
    components: tuple[GraphNeighbor, ...] = ()
    relations: tuple[GraphRelation, ...] = ()
    mediated_relations: tuple[GraphRelation, ...] = ()
    left_neighbors: tuple[GraphNeighbor, ...] = ()
    right_neighbors: tuple[GraphNeighbor, ...] = ()
    ranked_paths: tuple[RankedExplanationPath, ...] = ()
    selected_path: RankedExplanationPath | None = None
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class EvidenceStrategy(Protocol):
    name: str

    def collect(self, ctx: EvidenceContext) -> ExplanationEvidence:
        ...


def graph_score_path(path: ExplanationPath, matches: tuple[NodeMatch, ...]) -> ExplanationPath:
    """Apply the same light graph prior previously embedded in planner.py."""

    score_by_id = {m.id: m.score for m in matches}
    endpoint = (
        score_by_id.get(path.node_ids[0], 0.0)
        + score_by_id.get(path.node_ids[-1], 0.0)
    ) / 2.0
    confs = [float(r.get("confidence", 1.0) or 1.0) for r in path.relationships]
    mean_conf = sum(confs) / len(confs) if confs else 0.0
    animation = (
        sum(1 for r in path.relationships if r.get("default_animation_pattern"))
        / max(1, len(path.relationships))
    )
    graph_score = 0.62 * endpoint + 25.0 * mean_conf + 8.0 * animation - max(0, path.hop_count - 4) * 3.0
    return ExplanationPath(
        node_ids=path.node_ids,
        node_names=path.node_names,
        relationships=path.relationships,
        score=round(graph_score, 4),
    )
