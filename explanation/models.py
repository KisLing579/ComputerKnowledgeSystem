from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from kg.query import ExplanationPath, NodeMatch
from .semantic_scene import SemanticScenePlan


class ExplanationIntent(StrEnum):
    """Coarse explanation intent used by the deterministic v0.x planner."""

    TRANSFORMATION_EXECUTION = "transformation_execution"
    COMPOSITION = "composition"
    INTERFACE_ROLE = "interface_role"
    ROLE_FUNCTION = "role_function"
    RELATION_STRUCTURE = "relation_structure"
    CAUSAL_MECHANISM = "causal_mechanism"
    PERFORMANCE = "performance"
    COMPARISON = "comparison"
    DEFINITION = "definition"
    GENERAL = "general"


@dataclass(frozen=True)
class QuestionAnalysis:
    question: str
    intent: ExplanationIntent
    source_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    focus_ids: tuple[str, ...] = ()
    preferred_relations: tuple[str, ...] = ()
    discouraged_relations: tuple[str, ...] = ()
    direct_mention_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    rationale: tuple[str, ...] = ()

    def source_set(self) -> set[str]:
        return set(self.source_ids)

    def target_set(self) -> set[str]:
        return set(self.target_ids)

    def focus_set(self) -> set[str]:
        return set(self.focus_ids)


@dataclass(frozen=True)
class ExplanationGoal:
    """A recursive explanation objective.

    The recursion is over explanation *goals*, not over arbitrary KG neighbors.
    That distinction keeps planning goal-directed and prevents the KG itself from
    dictating an uncontrolled traversal.
    """

    goal_id: str
    text: str
    analysis: QuestionAnalysis
    depth: int = 0
    purpose: str = "explain"
    children: tuple["ExplanationGoal", ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PathScoreBreakdown:
    """Normalized [0, 100] explanation-quality components."""

    anchor_coverage: float
    focus_coverage: float
    relation_fit: float
    semantic_coherence: float
    path_length_fit: float
    animation_coverage: float
    edge_confidence: float
    detour_penalty: float
    graph_score: float
    explanation_score: float


@dataclass(frozen=True)
class RankedExplanationPath:
    path: ExplanationPath
    breakdown: PathScoreBreakdown
    rank: int = 0

    @property
    def explanation_score(self) -> float:
        return self.breakdown.explanation_score

    @property
    def graph_score(self) -> float:
        return self.breakdown.graph_score


@dataclass(frozen=True)
class KnowledgePath:
    """Planner-neutral linear path consumed by the future visual/scene layer."""

    path_type: str
    goal: str
    question: str
    intent: str
    node_ids: tuple[str, ...]
    node_names: tuple[str, ...]
    relations: tuple[dict[str, Any], ...]
    explanation_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExplanationBranch:
    """Backward-compatible one-level branch representation from v0.3."""

    branch_id: str
    root_id: str
    root_name: str
    node_ids: tuple[str, ...]
    node_names: tuple[str, ...]
    relations: tuple[dict[str, Any], ...]
    purpose: str = "support"
    score: float = 0.0


@dataclass(frozen=True)
class ExplanationSegment:
    """Recursive explanation-plan node.

    `children` forms a strict tree. Repeated knowledge concepts are represented
    by `reference` segments rather than by segment back-links, so the plan itself
    remains acyclic even when the source KG contains cycles.

    Common segment types:
      - sequence: ordered child explanations
      - linear: one path/process
      - branch: one root with nested children
      - hybrid: a main local structure with subordinate children
      - fact: one relation/fact
      - evidence_group: a local subgraph with one semantic scene plan
      - definition: core node definition + 0-1 hop defining support
      - comparison: two parallel concept sides + direct contrast evidence
      - reference: refer back to a concept already explained
      - empty: KG did not provide enough evidence
    """

    segment_id: str
    segment_type: str
    goal_id: str
    title: str
    intent: str
    root_id: str | None = None
    root_name: str | None = None
    node_ids: tuple[str, ...] = ()
    node_names: tuple[str, ...] = ()
    relations: tuple[dict[str, Any], ...] = ()
    children: tuple["ExplanationSegment", ...] = ()
    score: float = 0.0
    referenced_node_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    semantic_scene_plan: SemanticScenePlan | None = None


@dataclass(frozen=True)
class PlanValidation:
    valid: bool
    segment_count: int
    max_depth: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExplanationPlan:
    """Structured explanation result consumed by the visual layer.

    v0.4 makes `root_segment` the canonical representation. Legacy fields
    `main_path` and `branches` remain temporarily for old callers/tests.
    """

    plan_type: str
    structure_type: str
    goal: str
    question: str
    intent: str
    root_id: str | None = None
    root_name: str | None = None
    root_segment: ExplanationSegment | None = None
    main_path: KnowledgePath | None = None
    branches: tuple[ExplanationBranch, ...] = ()
    explanation_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    validation: PlanValidation | None = None


@dataclass(frozen=True)
class ExplanationResult:
    question: str
    matched_nodes: tuple[NodeMatch, ...]
    analysis: QuestionAnalysis
    ranked_paths: tuple[RankedExplanationPath, ...]
    selected_path: KnowledgePath | None
    selected_plan: ExplanationPlan | None = None
    root_goal: ExplanationGoal | None = None
