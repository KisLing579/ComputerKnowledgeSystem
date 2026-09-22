from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from explanation.semantic_scene import SemanticScenePlan


@dataclass(frozen=True)
class VisualArchetypeSpec:
    archetype_id: str
    definition: str = ""
    typical_nodes: tuple[str, ...] = ()
    typical_animation_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepresentationProfile:
    profile_id: str
    profile_name: str
    visual_archetype: str
    detail_level: int
    use_cases: tuple[str, ...] = ()
    description: str = ""
    render_requirements: tuple[str, ...] = ()
    status: str = "active"


@dataclass(frozen=True)
class NodeRepresentationBinding:
    binding_id: str
    node_id: str
    profile_id: str
    is_default: bool = False
    selection_condition: str = ""
    status: str = "active"


@dataclass(frozen=True)
class AnimationPatternSpec:
    pattern_id: str
    definition: str = ""
    related_relation_types: tuple[str, ...] = ()
    typical_use: str = ""
    category: str = "generic"


@dataclass(frozen=True)
class RelationAnimationBinding:
    relation_type: str
    animation_pattern_id: str
    is_default: bool = False
    binding_role: str = "candidate"


@dataclass(frozen=True)
class SemanticPhase:
    phase_id: str
    action: str
    narration_cue: str = ""
    duration: float = 0.7
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticAnimationTemplate:
    """Engineering interpretation of a workbook animation pattern.

    The workbook remains the source of truth for *which* pattern is associated
    with a relation.  This template explains how that pattern becomes a short
    semantic micro-scene rather than a labeled arrow.
    """

    pattern_id: str
    template_id: str
    semantic_role: str
    layout_hint: str
    phases: tuple[SemanticPhase, ...]
    relation_label_mode: str = "hidden"
    preserve_object_identity: bool = True
    description: str = ""


@dataclass(frozen=True)
class RepresentationNode:
    representation_id: str
    knowledge_node_id: str
    name: str
    definition: str
    profile_id: str
    profile_name: str
    archetype: str
    detail_level: int
    role: str = "concept"
    use_cases: tuple[str, ...] = ()
    render_requirements: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepresentationRelation:
    relation_id: str
    source_representation_id: str
    target_representation_id: str
    source_node_id: str
    target_node_id: str
    stored_source_node_id: str
    stored_target_node_id: str
    relation_type: str
    narrative_relation_type: str
    pattern_id: str
    pattern_category: str
    grammar_template_id: str
    grammar_phases: tuple[SemanticPhase, ...]
    relation_label_mode: str = "hidden"
    mediator_representation_id: str | None = None
    mediator_node_id: str | None = None
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepresentationSegment:
    segment_id: str
    segment_type: str
    title: str
    intent: str
    root_representation_id: str | None
    nodes: tuple[RepresentationNode, ...] = ()
    relations: tuple[RepresentationRelation, ...] = ()
    children: tuple["RepresentationSegment", ...] = ()
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    semantic_scene_plan: SemanticScenePlan | None = None


@dataclass(frozen=True)
class RepresentationPlan:
    question: str
    intent: str
    root_segment: RepresentationSegment
    source_workbook: str
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
