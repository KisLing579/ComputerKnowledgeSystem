from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from representation.models import RepresentationPlan


@dataclass(frozen=True)
class StoryBeat:
    beat_id: str
    beat_type: str
    template_id: str
    pattern_id: str
    phase_id: str
    node_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    narration: str = ""
    duration: float = 0.7
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoryScene:
    story_scene_id: str
    segment_id: str
    title: str
    scene_role: str
    layout_hint: str
    node_ids: tuple[str, ...]
    relation_ids: tuple[str, ...] = ()
    beats: tuple[StoryBeat, ...] = ()
    focus_node_ids: tuple[str, ...] = ()
    carry_over_node_ids: tuple[str, ...] = ()
    narration_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoryPlan:
    question: str
    intent: str
    scenes: tuple[StoryScene, ...]
    estimated_duration: float
    representation_plan: RepresentationPlan
    metadata: dict[str, Any] = field(default_factory=dict)
