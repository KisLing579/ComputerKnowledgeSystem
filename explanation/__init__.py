"""Recursive explanation planning for the Computer Core knowledge graph.

Keep package import lightweight. In particular, do not import ``planner`` here:
`python -m explanation.planner ...` should execute the module only once.
"""

from .models import (
    ExplanationBranch,
    ExplanationGoal,
    ExplanationIntent,
    ExplanationPlan,
    ExplanationSegment,
    KnowledgePath,
    PathScoreBreakdown,
    PlanValidation,
    QuestionAnalysis,
    RankedExplanationPath,
)
from .semantic_scene import ScenePattern, SemanticScenePlan

__all__ = [
    "ScenePattern",
    "SemanticScenePlan",
    "ExplanationBranch",
    "ExplanationGoal",
    "ExplanationIntent",
    "ExplanationPlan",
    "ExplanationSegment",
    "KnowledgePath",
    "PathScoreBreakdown",
    "PlanValidation",
    "QuestionAnalysis",
    "RankedExplanationPath",
]
