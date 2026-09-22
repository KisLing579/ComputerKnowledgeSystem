from __future__ import annotations

from dataclasses import dataclass

from .models import ScenePlan


@dataclass(frozen=True)
class ScenePlanValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class ScenePlanValidator:
    def __init__(self, *, max_nodes_per_scene: int = 8):
        self.max_nodes_per_scene = max_nodes_per_scene

    def validate(self, plan: ScenePlan) -> ScenePlanValidation:
        errors: list[str] = []
        warnings: list[str] = []
        seen_scene_ids: set[str] = set()
        previously_seen_nodes: set[str] = set()

        for scene in plan.scenes:
            if scene.scene_id in seen_scene_ids:
                errors.append(f"duplicate scene_id: {scene.scene_id}")
            seen_scene_ids.add(scene.scene_id)

            node_ids = {n.knowledge_node_id for n in scene.nodes}
            if len(scene.nodes) > self.max_nodes_per_scene:
                warnings.append(
                    f"{scene.scene_id} has {len(scene.nodes)} nodes; visual clutter likely."
                )
            if not scene.nodes and scene.scene_type not in {"evidence_gap", "reference_highlight"}:
                warnings.append(f"{scene.scene_id} has no visual nodes.")

            for rel in scene.relations:
                if rel.source_node_id not in node_ids or rel.target_node_id not in node_ids:
                    errors.append(
                        f"{scene.scene_id} relation {rel.relation_id} references endpoint not present in scene: "
                        f"{rel.source_node_id}->{rel.target_node_id}"
                    )

            for nid in scene.carry_over_node_ids:
                if nid not in node_ids:
                    errors.append(f"{scene.scene_id} carry-over node {nid} is not in current scene")
                if nid not in previously_seen_nodes:
                    warnings.append(f"{scene.scene_id} marks unseen node {nid} as carry-over")
            previously_seen_nodes |= node_ids

        return ScenePlanValidation(valid=not errors, errors=tuple(errors), warnings=tuple(warnings))
