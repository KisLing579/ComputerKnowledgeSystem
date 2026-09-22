from __future__ import annotations

import math
from dataclasses import replace

from .models import (
    BoundVisualNode,
    BoundVisualRelation,
    BoundVisualSegment,
    SceneAction,
    SceneNodeSpec,
    ScenePlan,
    SceneRelationSpec,
    SceneSpec,
    VisualPlan,
)


class ScenePlanner:
    """Convert a recursive VisualPlan into a linear sequence of visual scenes.

    Explanation recursion expresses narrative structure. ScenePlanner flattens
    that tree into time while preserving visual continuity through knowledge-node
    carry-over.  It does not reinterpret KG semantics.
    """

    def __init__(
        self,
        *,
        max_nodes_per_scene: int = 8,
        default_scene_seconds: float = 3.0,
        transition_seconds: float = 0.6,
    ):
        self.max_nodes_per_scene = max_nodes_per_scene
        self.default_scene_seconds = default_scene_seconds
        self.transition_seconds = transition_seconds

    def plan(self, visual_plan: VisualPlan) -> ScenePlan:
        scenes: list[SceneSpec] = []
        self._emit_segment(visual_plan.root_segment, scenes, parent_segment_id=None)

        # Add continuity information after the recursive plan has been flattened.
        previous_ids: set[str] = set()
        enriched: list[SceneSpec] = []
        for index, scene in enumerate(scenes, 1):
            current_ids = {n.knowledge_node_id for n in scene.nodes}
            carry = tuple(sorted(previous_ids & current_ids))
            enriched.append(
                replace(
                    scene,
                    scene_id=f"SC{index:03d}",
                    carry_over_node_ids=carry,
                    clear_before=(index == 1),
                )
            )
            previous_ids = current_ids

        duration = sum(s.duration_hint for s in enriched)
        return ScenePlan(
            question=visual_plan.question,
            intent=visual_plan.intent,
            scenes=tuple(enriched),
            estimated_duration=round(duration, 2),
            metadata={
                "scene_count": len(enriched),
                "continuity_model": "reuse_by_knowledge_node_id",
                "planner": "recursive_segment_to_scene_sequence_v0.1",
                "visual_warnings": visual_plan.warnings,
            },
        )

    def _emit_segment(
        self,
        segment: BoundVisualSegment,
        out: list[SceneSpec],
        *,
        parent_segment_id: str | None,
    ) -> None:
        st = segment.segment_type
        if st == "sequence":
            for child in segment.children:
                self._emit_segment(child, out, parent_segment_id=segment.segment_id)
            return

        if st == "empty":
            out.append(self._empty_scene(segment, parent_segment_id))
            return

        if st == "reference":
            out.append(self._reference_scene(segment, parent_segment_id))
            return

        if st == "linear":
            out.append(self._linear_scene(segment, parent_segment_id))
            # Linear segments normally encode the entire atomic explanation and
            # therefore do not recursively emit children unless they exist.
            for child in segment.children:
                self._emit_segment(child, out, parent_segment_id=segment.segment_id)
            return

        if st == "fact":
            out.append(self._fact_scene(segment, parent_segment_id))
            return

        if st == "branch":
            out.append(self._branch_scene(segment, parent_segment_id))
            # Nested branch children get their own follow-up scenes so a complex
            # tree is not forced into one overcrowded frame.
            for child in segment.children:
                if child.children:
                    self._emit_segment(child, out, parent_segment_id=segment.segment_id)
            return

        if st == "definition":
            out.append(self._definition_scene(segment, parent_segment_id))
            for child in segment.children:
                if child.segment_type in {"branch", "hybrid"} and child.children:
                    self._emit_segment(child, out, parent_segment_id=segment.segment_id)
            return

        if st == "comparison":
            out.append(self._comparison_scene(segment, parent_segment_id))
            # Side detail is normally already summarized in the split-screen;
            # recurse only into unusually deep side structures.
            for child in segment.children:
                if any(grand.children for grand in child.children):
                    self._emit_segment(child, out, parent_segment_id=segment.segment_id)
            return

        if st == "hybrid":
            overview = self._hybrid_overview_scene(segment, parent_segment_id)
            if overview.nodes:
                out.append(overview)
            for child in segment.children:
                self._emit_segment(child, out, parent_segment_id=segment.segment_id)
            return

        # Unknown future segment type: render the local evidence generically,
        # then recurse. This keeps downstream code forward-compatible.
        out.append(self._generic_scene(segment, parent_segment_id))
        for child in segment.children:
            self._emit_segment(child, out, parent_segment_id=segment.segment_id)

    # ------------------------------------------------------------------
    # Scene constructors
    # ------------------------------------------------------------------

    def _linear_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        nodes = self._ordered_nodes_for_linear(segment)
        interface = bool(segment.relations) and all(
            r.relation_type == "INTERFACES_WITH" for r in segment.relations
        )
        layout = "interface_layers" if interface and len(nodes) <= 4 else "horizontal_flow"
        positions = (
            self._vertical_positions(nodes) if layout == "interface_layers" else self._horizontal_positions(nodes)
        )
        specs = self._node_specs(nodes, positions, focus_ids=self._root_ids(segment))
        rels = self._relation_specs(segment.relations)
        actions: list[SceneAction] = [
            SceneAction("reveal_nodes", tuple(n.visual_id for n in nodes), duration=0.7)
        ]
        for rel in segment.relations:
            target_ids = [rel.source_visual_id, rel.target_visual_id]
            if rel.mediator_visual_id:
                target_ids.insert(1, rel.mediator_visual_id)
            actions.append(
                SceneAction(
                    "animate_relation",
                    tuple(target_ids),
                    pattern_id=rel.pattern_id,
                    duration=self._pattern_duration(rel.pattern_id),
                )
            )
        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="linear_flow",
            title=segment.title,
            layout=layout,
            nodes=tuple(specs),
            relations=tuple(rels),
            actions=tuple(actions),
            focus_node_ids=tuple(self._root_ids(segment)),
            duration_hint=max(self.default_scene_seconds, 1.0 + sum(a.duration for a in actions)),
            narration_hint=self._linear_narration(segment),
            metadata={"parent_segment_id": parent, "segment_score": segment.score},
        )

    def _fact_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        nodes = list(segment.nodes)[:3]
        positions = self._horizontal_positions(nodes, span=5.0)
        actions = [SceneAction("reveal_nodes", tuple(n.visual_id for n in nodes), duration=0.6)]
        for rel in segment.relations:
            actions.append(
                SceneAction(
                    "animate_relation",
                    (rel.source_visual_id, rel.target_visual_id),
                    pattern_id=rel.pattern_id,
                    duration=self._pattern_duration(rel.pattern_id),
                )
            )
        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="fact_link",
            title=segment.title,
            layout="horizontal_pair",
            nodes=tuple(self._node_specs(nodes, positions, focus_ids=self._root_ids(segment))),
            relations=tuple(self._relation_specs(segment.relations)),
            actions=tuple(actions),
            focus_node_ids=tuple(self._root_ids(segment)),
            duration_hint=max(2.0, sum(a.duration for a in actions) + 0.8),
            narration_hint=segment.title,
            metadata={"parent_segment_id": parent},
        )

    def _branch_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        root = self._find_root_node(segment)
        direct_children = self._direct_child_nodes(segment)
        nodes = ([root] if root else []) + direct_children
        nodes = self._dedupe_nodes(nodes)[: self.max_nodes_per_scene]

        inside = bool(root and root.archetype == "container") and self._branch_is_composition(segment)
        layout = "inside_container" if inside else "branch_tree"
        positions = self._inside_positions(nodes) if inside else self._branch_positions(nodes)

        actions: list[SceneAction] = []
        if root:
            actions.append(SceneAction("focus_node", (root.visual_id,), duration=0.5))
        if direct_children:
            actions.append(
                SceneAction(
                    "branch_reveal",
                    tuple(n.visual_id for n in direct_children),
                    pattern_id="REVEAL_INSIDE" if inside else "TREE_EXPAND",
                    duration=1.2,
                )
            )
        for rel in segment.relations:
            actions.append(
                SceneAction(
                    "animate_relation",
                    (rel.source_visual_id, rel.target_visual_id),
                    pattern_id=rel.pattern_id,
                    duration=0.7,
                )
            )

        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="branch_reveal",
            title=segment.title,
            layout=layout,
            nodes=tuple(self._node_specs(nodes, positions, focus_ids=self._root_ids(segment), container_root=inside)),
            relations=tuple(self._relation_specs(self._collect_immediate_relations(segment))),
            actions=tuple(actions),
            focus_node_ids=tuple(self._root_ids(segment)),
            duration_hint=max(self.default_scene_seconds, 1.4 + sum(a.duration for a in actions)),
            narration_hint=f"围绕{root.name if root else segment.title}展开关键分支。",
            metadata={"parent_segment_id": parent, "inside_container": inside},
        )

    def _definition_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        root = self._find_root_node(segment)
        supports = self._collect_support_nodes(segment, exclude_ids={root.knowledge_node_id} if root else set())
        nodes = ([root] if root else []) + supports[: max(0, self.max_nodes_per_scene - 1)]
        positions = self._radial_positions(nodes)
        actions = []
        if root:
            actions.append(SceneAction("definition_focus", (root.visual_id,), duration=0.8))
        if supports:
            actions.append(
                SceneAction(
                    "support_reveal",
                    tuple(n.visual_id for n in supports[: self.max_nodes_per_scene - 1]),
                    duration=1.0,
                )
            )
        definition_text = str(segment.metadata.get("core_statement", segment.metadata.get("definition_text", "")) or "")
        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="definition_focus",
            title=segment.title,
            layout="center_satellites",
            nodes=tuple(self._node_specs(nodes, positions, focus_ids=self._root_ids(segment))),
            relations=tuple(self._relation_specs(self._collect_descendant_relations(segment, max_depth=1))),
            actions=tuple(actions),
            focus_node_ids=tuple(self._root_ids(segment)),
            duration_hint=max(3.0, 1.2 + sum(a.duration for a in actions)),
            narration_hint=definition_text or f"先给出{root.name if root else segment.title}的核心定义，再看最重要的邻近关系。",
            metadata={"parent_segment_id": parent, "definition_text": definition_text},
        )

    def _comparison_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        side_roots: list[BoundVisualNode] = []
        for child in segment.children:
            node = self._find_root_node(child)
            if node:
                side_roots.append(node)
        if len(side_roots) < 2:
            side_roots.extend([n for n in segment.nodes if n.knowledge_node_id not in {x.knowledge_node_id for x in side_roots}])
        side_roots = self._dedupe_nodes(side_roots)[:2]
        detail_nodes: list[BoundVisualNode] = []
        for child in segment.children[:2]:
            detail_nodes.extend(self._collect_support_nodes(child, exclude_ids={n.knowledge_node_id for n in side_roots}))
        nodes = side_roots + self._dedupe_nodes(detail_nodes)[: max(0, self.max_nodes_per_scene - 2)]
        positions = self._comparison_positions(nodes, side_roots)
        actions = [
            SceneAction("split_screen", tuple(n.visual_id for n in side_roots), pattern_id="SIDE_BY_SIDE", duration=1.0)
        ]
        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="comparison_split",
            title=segment.title,
            layout="split_screen",
            nodes=tuple(self._node_specs(nodes, positions, focus_ids=[n.knowledge_node_id for n in side_roots])),
            relations=tuple(self._relation_specs(self._collect_descendant_relations(segment, max_depth=2))),
            actions=tuple(actions),
            focus_node_ids=tuple(n.knowledge_node_id for n in side_roots),
            duration_hint=4.0,
            narration_hint="左右并列比较两个概念及其关键支撑关系。",
            metadata={"parent_segment_id": parent},
        )

    def _hybrid_overview_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        root = self._find_root_node(segment)
        child_roots = [self._find_root_node(c) for c in segment.children]
        nodes = ([root] if root else []) + [x for x in child_roots if x]
        nodes = self._dedupe_nodes(nodes)[: self.max_nodes_per_scene]
        positions = self._radial_positions(nodes)
        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="hybrid_overview",
            title=segment.title,
            layout="center_satellites",
            nodes=tuple(self._node_specs(nodes, positions, focus_ids=self._root_ids(segment))),
            relations=tuple(),
            actions=(SceneAction("overview_reveal", tuple(n.visual_id for n in nodes), duration=1.0),),
            focus_node_ids=tuple(self._root_ids(segment)),
            duration_hint=2.5,
            narration_hint="先建立整体框架，再逐项展开。",
            metadata={"parent_segment_id": parent},
        )

    def _reference_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        ids = tuple(str(x) for x in segment.metadata.get("referenced_node_ids", ()) or ())
        if not ids:
            ids = tuple(n.knowledge_node_id for n in segment.nodes)
        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="reference_highlight",
            title=segment.title,
            layout="reuse_existing",
            nodes=tuple(),
            actions=(SceneAction("highlight_existing", ids, duration=0.8),),
            focus_node_ids=ids,
            duration_hint=1.6,
            narration_hint=segment.title,
            metadata={"parent_segment_id": parent},
        )

    def _empty_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="evidence_gap",
            title=segment.title,
            layout="text_only",
            nodes=tuple(),
            actions=(SceneAction("show_note", duration=1.0),),
            duration_hint=2.0,
            narration_hint=str(segment.metadata.get("note", "当前知识图谱证据不足。")),
            metadata={"parent_segment_id": parent, "note": segment.metadata.get("note", "")},
        )

    def _generic_scene(self, segment: BoundVisualSegment, parent: str | None) -> SceneSpec:
        nodes = list(segment.nodes)[: self.max_nodes_per_scene]
        return SceneSpec(
            scene_id="",
            segment_id=segment.segment_id,
            scene_type="generic_graph",
            title=segment.title,
            layout="radial",
            nodes=tuple(self._node_specs(nodes, self._radial_positions(nodes), focus_ids=self._root_ids(segment))),
            relations=tuple(self._relation_specs(segment.relations)),
            actions=(SceneAction("overview_reveal", tuple(n.visual_id for n in nodes), duration=1.0),),
            focus_node_ids=tuple(self._root_ids(segment)),
            duration_hint=3.0,
            narration_hint=segment.title,
            metadata={"parent_segment_id": parent},
        )

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _ordered_nodes_for_linear(self, segment: BoundVisualSegment) -> list[BoundVisualNode]:
        by_id = {n.knowledge_node_id: n for n in segment.nodes}
        ordered: list[BoundVisualNode] = []
        if segment.relations:
            first = segment.relations[0].source_node_id
            if first in by_id:
                ordered.append(by_id[first])
            for rel in segment.relations:
                # Mediator visually sits between source and target.
                if rel.mediator_visual_id:
                    med = next((n for n in segment.nodes if n.visual_id == rel.mediator_visual_id), None)
                    if med and med.knowledge_node_id not in {x.knowledge_node_id for x in ordered}:
                        ordered.append(med)
                if rel.target_node_id in by_id and rel.target_node_id not in {x.knowledge_node_id for x in ordered}:
                    ordered.append(by_id[rel.target_node_id])
        for n in segment.nodes:
            if n.knowledge_node_id not in {x.knowledge_node_id for x in ordered}:
                ordered.append(n)
        return ordered[: self.max_nodes_per_scene]

    def _find_root_node(self, segment: BoundVisualSegment) -> BoundVisualNode | None:
        if segment.root_visual_id:
            node = next((n for n in segment.nodes if n.visual_id == segment.root_visual_id), None)
            if node:
                return node
        return segment.nodes[0] if segment.nodes else None

    def _direct_child_nodes(self, segment: BoundVisualSegment) -> list[BoundVisualNode]:
        root = self._find_root_node(segment)
        if not root:
            return []
        out: list[BoundVisualNode] = []
        for child in segment.children:
            # Fact children often carry both root and leaf; prefer child's root,
            # which structurer sets to the leaf node.
            node = self._find_root_node(child)
            if node and node.knowledge_node_id != root.knowledge_node_id:
                out.append(node)
        # Some branch segments encode direct relations locally instead.
        if not out:
            by_id = {n.knowledge_node_id: n for n in segment.nodes}
            for rel in segment.relations:
                other = rel.target_node_id if rel.source_node_id == root.knowledge_node_id else rel.source_node_id
                if other in by_id and other != root.knowledge_node_id:
                    out.append(by_id[other])
        return self._dedupe_nodes(out)

    def _collect_support_nodes(self, segment: BoundVisualSegment, *, exclude_ids: set[str], max_depth: int = 2) -> list[BoundVisualNode]:
        out: list[BoundVisualNode] = []

        def visit(seg: BoundVisualSegment, depth: int):
            if depth > max_depth:
                return
            for n in seg.nodes:
                if n.knowledge_node_id not in exclude_ids:
                    out.append(n)
            for child in seg.children:
                visit(child, depth + 1)

        for child in segment.children:
            visit(child, 1)
        return self._dedupe_nodes(out)

    def _collect_immediate_relations(self, segment: BoundVisualSegment) -> list[BoundVisualRelation]:
        rels = list(segment.relations)
        for child in segment.children:
            rels.extend(child.relations)
        return self._dedupe_relations(rels)

    def _collect_descendant_relations(self, segment: BoundVisualSegment, *, max_depth: int) -> list[BoundVisualRelation]:
        out = list(segment.relations)

        def visit(seg: BoundVisualSegment, depth: int):
            if depth > max_depth:
                return
            out.extend(seg.relations)
            for child in seg.children:
                visit(child, depth + 1)

        for child in segment.children:
            visit(child, 1)
        return self._dedupe_relations(out)

    def _root_ids(self, segment: BoundVisualSegment) -> list[str]:
        root = self._find_root_node(segment)
        return [root.knowledge_node_id] if root else []

    @staticmethod
    def _dedupe_nodes(nodes: list[BoundVisualNode]) -> list[BoundVisualNode]:
        out: list[BoundVisualNode] = []
        seen: set[str] = set()
        for n in nodes:
            if n.knowledge_node_id not in seen:
                seen.add(n.knowledge_node_id)
                out.append(n)
        return out

    @staticmethod
    def _dedupe_relations(rels: list[BoundVisualRelation]) -> list[BoundVisualRelation]:
        out: list[BoundVisualRelation] = []
        seen: set[tuple[str, str, str]] = set()
        for r in rels:
            key = (r.source_node_id, r.target_node_id, r.narrative_relation_type)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    @staticmethod
    def _branch_is_composition(segment: BoundVisualSegment) -> bool:
        if segment.intent == "composition" or segment.metadata.get("purpose") == "composition":
            return True
        rels = ScenePlanner._collect_static_relation_types(segment)
        return bool(rels) and rels <= {"PART_OF", "CONTAINS"}

    @staticmethod
    def _collect_static_relation_types(segment: BoundVisualSegment) -> set[str]:
        types = {r.relation_type for r in segment.relations}
        for child in segment.children:
            types |= {r.relation_type for r in child.relations}
        return types

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _node_specs(
        self,
        nodes: list[BoundVisualNode],
        positions: dict[str, tuple[float, float, float]],
        *,
        focus_ids: list[str],
        container_root: bool = False,
    ) -> list[SceneNodeSpec]:
        specs: list[SceneNodeSpec] = []
        for i, node in enumerate(nodes):
            x, y, scale = positions.get(node.knowledge_node_id, (0.0, 0.0, 1.0))
            if container_root and i == 0:
                scale = max(scale, 1.7)
            specs.append(
                SceneNodeSpec(
                    visual_id=node.visual_id,
                    knowledge_node_id=node.knowledge_node_id,
                    name=node.name,
                    archetype=node.archetype,
                    profile_id=node.profile_id,
                    role=node.role,
                    x=round(x, 3),
                    y=round(y, 3),
                    scale=round(scale, 3),
                    emphasis="focus" if node.knowledge_node_id in focus_ids else "normal",
                    metadata={
                        "detail_level": node.detail_level,
                        "render_requirements": node.render_requirements,
                    },
                )
            )
        return specs

    @staticmethod
    def _relation_specs(relations: list[BoundVisualRelation] | tuple[BoundVisualRelation, ...]) -> list[SceneRelationSpec]:
        return [
            SceneRelationSpec(
                relation_id=r.relation_id,
                source_visual_id=r.source_visual_id,
                target_visual_id=r.target_visual_id,
                source_node_id=r.source_node_id,
                target_node_id=r.target_node_id,
                label=r.narrative_relation_type,
                pattern_id=r.pattern_id,
                pattern_category=r.pattern_category,
                mediator_visual_id=r.mediator_visual_id,
                metadata={**r.metadata, "confidence": r.confidence},
            )
            for r in relations
        ]

    @staticmethod
    def _horizontal_positions(nodes: list[BoundVisualNode], span: float = 10.0) -> dict[str, tuple[float, float, float]]:
        if not nodes:
            return {}
        if len(nodes) == 1:
            return {nodes[0].knowledge_node_id: (0.0, 0.0, 1.0)}
        step = span / max(1, len(nodes) - 1)
        start = -span / 2
        return {n.knowledge_node_id: (start + i * step, 0.0, 0.9 if len(nodes) > 5 else 1.0) for i, n in enumerate(nodes)}

    @staticmethod
    def _vertical_positions(nodes: list[BoundVisualNode]) -> dict[str, tuple[float, float, float]]:
        if not nodes:
            return {}
        span = min(5.5, 2.2 * max(1, len(nodes) - 1))
        step = span / max(1, len(nodes) - 1)
        start = span / 2
        return {n.knowledge_node_id: (0.0, start - i * step, 1.0) for i, n in enumerate(nodes)}

    @staticmethod
    def _branch_positions(nodes: list[BoundVisualNode]) -> dict[str, tuple[float, float, float]]:
        if not nodes:
            return {}
        pos = {nodes[0].knowledge_node_id: (-4.2, 0.0, 1.1)}
        children = nodes[1:]
        if not children:
            return pos
        ys = ScenePlanner._even_values(len(children), 4.8)
        for node, y in zip(children, ys):
            pos[node.knowledge_node_id] = (2.3, y, 0.95)
        return pos

    @staticmethod
    def _inside_positions(nodes: list[BoundVisualNode]) -> dict[str, tuple[float, float, float]]:
        if not nodes:
            return {}
        pos = {nodes[0].knowledge_node_id: (0.0, 0.0, 1.8)}
        children = nodes[1:]
        if not children:
            return pos
        cols = 2
        for i, node in enumerate(children):
            col = i % cols
            row = i // cols
            x = -1.5 + col * 3.0
            y = 0.8 - row * 1.6
            pos[node.knowledge_node_id] = (x, y, 0.72)
        return pos

    @staticmethod
    def _radial_positions(nodes: list[BoundVisualNode]) -> dict[str, tuple[float, float, float]]:
        if not nodes:
            return {}
        pos = {nodes[0].knowledge_node_id: (0.0, 0.0, 1.15)}
        rest = nodes[1:]
        if not rest:
            return pos
        radius = 3.7
        for i, node in enumerate(rest):
            angle = math.pi / 2 - 2 * math.pi * i / max(1, len(rest))
            pos[node.knowledge_node_id] = (radius * math.cos(angle), radius * math.sin(angle), 0.85)
        return pos

    @staticmethod
    def _comparison_positions(nodes: list[BoundVisualNode], side_roots: list[BoundVisualNode]) -> dict[str, tuple[float, float, float]]:
        pos: dict[str, tuple[float, float, float]] = {}
        if side_roots:
            pos[side_roots[0].knowledge_node_id] = (-3.4, 1.2, 1.1)
        if len(side_roots) > 1:
            pos[side_roots[1].knowledge_node_id] = (3.4, 1.2, 1.1)
        details = [n for n in nodes if n.knowledge_node_id not in {x.knowledge_node_id for x in side_roots}]
        left_y = -0.6
        right_y = -0.6
        for i, node in enumerate(details):
            if i % 2 == 0:
                pos[node.knowledge_node_id] = (-3.4, left_y, 0.8)
                left_y -= 1.2
            else:
                pos[node.knowledge_node_id] = (3.4, right_y, 0.8)
                right_y -= 1.2
        return pos

    @staticmethod
    def _even_values(n: int, span: float) -> list[float]:
        if n <= 1:
            return [0.0] if n else []
        step = span / (n - 1)
        return [span / 2 - i * step for i in range(n)]

    # ------------------------------------------------------------------
    # Semantics / timing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pattern_duration(pattern_id: str) -> float:
        return {
            "PIPELINE_TRANSFORM": 1.4,
            "MORPH": 1.2,
            "TOKEN_ENTER_AND_ACT": 1.2,
            "CONTROL_SIGNAL": 1.0,
            "INTERFACE_BRIDGE": 1.0,
            "REVEAL_INSIDE": 1.0,
            "TREE_EXPAND": 1.0,
            "SIDE_BY_SIDE": 1.0,
        }.get(pattern_id, 0.8)

    @staticmethod
    def _linear_narration(segment: BoundVisualSegment) -> str:
        if not segment.relations:
            return segment.title
        pieces = []
        by_visual = {n.visual_id: n.name for n in segment.nodes}
        for rel in segment.relations:
            a = by_visual.get(rel.source_visual_id, rel.source_node_id)
            b = by_visual.get(rel.target_visual_id, rel.target_node_id)
            pieces.append(f"{a} --{rel.narrative_relation_type}--> {b}")
        return "；".join(pieces)
