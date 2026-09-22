from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VisualProfile:
    profile_id: str
    profile_name: str
    visual_archetype: str
    detail_level: int
    use_cases: tuple[str, ...] = ()
    description: str = ""
    render_requirements: tuple[str, ...] = ()
    status: str = "active"


@dataclass(frozen=True)
class NodeVisualBinding:
    binding_id: str
    node_id: str
    profile_id: str
    is_default: bool = False
    selection_condition: str = ""
    status: str = "active"


@dataclass(frozen=True)
class AnimationPattern:
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
class BoundVisualNode:
    """A KG node bound to one visual profile for one explanation context."""

    visual_id: str
    knowledge_node_id: str
    name: str
    profile_id: str
    profile_name: str
    archetype: str
    detail_level: int
    role: str = "concept"
    use_cases: tuple[str, ...] = ()
    render_requirements: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BoundVisualRelation:
    relation_id: str
    source_visual_id: str
    target_visual_id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    narrative_relation_type: str
    pattern_id: str
    pattern_category: str = "generic"
    mediator_visual_id: str | None = None
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BoundVisualSegment:
    segment_id: str
    segment_type: str
    title: str
    intent: str
    root_visual_id: str | None
    nodes: tuple[BoundVisualNode, ...] = ()
    relations: tuple[BoundVisualRelation, ...] = ()
    children: tuple["BoundVisualSegment", ...] = ()
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisualPlan:
    question: str
    intent: str
    root_segment: BoundVisualSegment
    profile_source: str
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneNodeSpec:
    visual_id: str
    knowledge_node_id: str
    name: str
    archetype: str
    profile_id: str
    role: str
    x: float
    y: float
    scale: float = 1.0
    emphasis: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneRelationSpec:
    relation_id: str
    source_visual_id: str
    target_visual_id: str
    source_node_id: str
    target_node_id: str
    label: str
    pattern_id: str
    pattern_category: str
    mediator_visual_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneAction:
    action_type: str
    target_ids: tuple[str, ...] = ()
    pattern_id: str = ""
    duration: float = 0.8
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneSpec:
    scene_id: str
    segment_id: str
    scene_type: str
    title: str
    layout: str
    nodes: tuple[SceneNodeSpec, ...]
    relations: tuple[SceneRelationSpec, ...] = ()
    actions: tuple[SceneAction, ...] = ()
    carry_over_node_ids: tuple[str, ...] = ()
    focus_node_ids: tuple[str, ...] = ()
    clear_before: bool = False
    duration_hint: float = 3.0
    narration_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenePlan:
    question: str
    intent: str
    scenes: tuple[SceneSpec, ...]
    estimated_duration: float
    metadata: dict[str, Any] = field(default_factory=dict)
