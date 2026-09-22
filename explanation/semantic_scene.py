"""Scene semantics independent of workbook animation patterns and renderers."""
from dataclasses import dataclass, field
from enum import StrEnum


class ScenePattern(StrEnum):
    ABSTRACTION_INTERFACE = "ABSTRACTION_INTERFACE"
    CAUSAL_CHAIN = "CAUSAL_CHAIN"
    PROCESS_PIPELINE = "PROCESS_PIPELINE"
    HIERARCHICAL_COMPOSITION = "HIERARCHICAL_COMPOSITION"
    SIDE_BY_SIDE_CONTRAST = "SIDE_BY_SIDE_CONTRAST"
    ONE_ABSTRACTION_MULTI_IMPLEMENTATION = "ONE_ABSTRACTION_MULTI_IMPLEMENTATION"
    MAPPING_CORRESPONDENCE = "MAPPING_CORRESPONDENCE"
    STATE_TRANSITION = "STATE_TRANSITION"
    LAYERED_SYSTEM = "LAYERED_SYSTEM"


@dataclass(frozen=True)
class SemanticScenePlan:
    scene_pattern: str
    focal_node_ids: tuple[str, ...] = ()
    supporting_node_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    # Roles reference actual KG IDs, never invented software/CPU placeholders.
    semantic_roles: dict[str, str] = field(default_factory=dict)
    visual_claim: str = ""
    narrative_goal: str = ""
    layout_family: str = ""

    def __post_init__(self):
        ScenePattern(self.scene_pattern)
        if not self.visual_claim.strip():
            raise ValueError("A semantic scene requires a visual claim")

    @property
    def node_ids(self):
        return tuple(dict.fromkeys((*self.focal_node_ids, *self.supporting_node_ids)))
