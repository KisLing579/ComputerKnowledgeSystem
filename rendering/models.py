from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RenderNodeSpec:
    knowledge_node_id: str
    name: str
    definition: str
    archetype: str
    profile_id: str
    x: float
    y: float
    width: float
    height: float
    scale: float = 1.0
    role: str = "concept"
    emphasis: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderRelationSpec:
    relation_id: str
    source_node_id: str
    target_node_id: str
    stored_source_node_id: str
    stored_target_node_id: str
    relation_type: str
    narrative_relation_type: str
    pattern_id: str
    template_id: str
    label_mode: str = "hidden"
    mediator_node_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderBeat:
    beat_id: str
    beat_type: str
    template_id: str
    pattern_id: str
    phase_id: str
    node_ids: tuple[str, ...]
    relation_ids: tuple[str, ...] = ()
    narration: str = ""
    duration: float = 0.7
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderScene:
    scene_id: str
    story_scene_id: str
    title: str
    scene_role: str
    layout: str
    nodes: tuple[RenderNodeSpec, ...]
    relations: tuple[RenderRelationSpec, ...]
    beats: tuple[RenderBeat, ...]
    carry_over_node_ids: tuple[str, ...] = ()
    focus_node_ids: tuple[str, ...] = ()
    narration_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderPlan:
    question: str
    intent: str
    scenes: tuple[RenderScene, ...]
    estimated_duration: float
    metadata: dict[str, Any] = field(default_factory=dict)
