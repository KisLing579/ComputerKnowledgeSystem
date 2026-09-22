from __future__ import annotations

import math
from dataclasses import replace

from representation.models import RepresentationNode, RepresentationRelation, RepresentationSegment
from resource_planning.models import StoryPlan, StoryScene
from rendering.models import RenderBeat, RenderNodeSpec, RenderPlan, RenderRelationSpec, RenderScene


class LayoutEngine:
    """Adaptive 2-D layout for semantic story scenes.

    This is deliberately separate from the representation/story layers.  It
    measures each visual metaphor, lays out the scene, then scales the result to
    a safe frame.  Semantic animations remain intact even when coordinates vary.
    """

    SAFE_WIDTH = 11.4
    SAFE_HEIGHT = 5.25

    def __init__(self, *, safe_width: float = 11.4, safe_height: float = 5.25):
        self.SAFE_WIDTH = float(safe_width)
        self.SAFE_HEIGHT = float(safe_height)

    BASE_SIZE = {
        "cache_map": (4.8, 3.0),
        "banked_memory": (4.8, 3.0),
        "locality_trace": (4.8, 3.0),
        "access_pattern": (4.8, 3.0),
        "miss_taxonomy": (5.2, 3.2),
        "protection_boundary": (4.8, 3.0),
        "process_switch": (5.2, 3.0),
        "queue_flow": (4.8, 3.0),
        "timing_state": (4.8, 2.8),
        "control_fsm": (4.8, 2.8),
        "control_table": (4.8, 2.8),
        "microcode_flow": (4.8, 2.8),
        "pipeline_timeline": (5.4, 3.0),
        "hazard_dependency": (4.8, 2.8),
        "branch_predictor": (5.0, 2.8),
        "issue_bundle": (4.8, 2.8),
        "dynamic_schedule": (5.0, 2.8),
        "cache_write_policy": (4.5, 3.0),
        "replacement_choice": (4.6, 2.8),
        "memory_hierarchy_stack": (4.4, 3.2),
        "virtual_memory_map": (4.8, 3.0),
        "page_fault_flow": (4.8, 3.4),
        "memory_request_timeline": (5.0, 2.8),
        "cache_lookup": (4.5, 2.7),
        "cache_address_decode": (4.5, 2.4),
        "cache_set_lookup": (4.5, 2.7),
        "tlb_translation": (4.5, 2.7),
        "page_table_map": (4.8, 2.8),
        "address_translation": (4.5, 2.5),
        "addressing": (4.2, 2.2),
        "control_flow": (4.2, 2.6),
        "datapath_graph": (4.6, 2.4),
        "instruction_format": (4.2, 1.8),
        "stack_frame": (3.2, 2.2),
        "memory_map": (3.2, 2.6),
        "character_table": (3.8, 2.2),
        "table_mapping": (3.8, 2.2),
        "container": (3.2, 1.7),
        "hierarchy": (3.0, 1.35),
        "functional_block": (2.7, 1.15),
        "functional_diagram": (3.1, 1.45),
        "storage_block": (2.8, 1.35),
        "memory_chip": (2.5, 1.2),
        "data_token": (2.1, 0.75),
        "code_block": (3.0, 1.45),
        "bit_field": (3.0, 1.0),
        "bit_cell": (1.2, 0.8),
        "interface_layer": (4.0, 0.9),
        "interface_hub": (2.5, 1.5),
        "external_device": (2.2, 1.2),
        "hardware_icon": (2.2, 1.4),
        "physical_system": (3.0, 1.5),
        "concept_layer": (4.4, 2.2),
        "category_group": (4.5, 2.5),
        "network": (3.2, 1.5),
        "primitive_symbol": (1.8, 1.2),
        "metric": (2.3, 1.3),
        "timeline": (4.0, 1.2),
        "parallel_flow": (3.6, 1.5),
        "pipeline": (4.0, 1.4),
        "process_flow": (3.2, 1.3),
        "transformer": (2.6, 1.2),
    }

    def layout(self, story_plan: StoryPlan) -> RenderPlan:
        nodes = self._index_nodes(story_plan.representation_plan.root_segment)
        relations = self._index_relations(story_plan.representation_plan.root_segment)
        scenes: list[RenderScene] = []
        for i, story in enumerate(story_plan.scenes, 1):
            scenes.append(self._layout_scene(story, nodes, relations, f"SC{i:03d}"))
        return RenderPlan(
            question=story_plan.question,
            intent=story_plan.intent,
            scenes=tuple(scenes),
            estimated_duration=story_plan.estimated_duration,
            metadata={
                "layout_engine": "semantic_adaptive_layout_v0.2",
                "safe_width": self.SAFE_WIDTH,
                "safe_height": self.SAFE_HEIGHT,
                "story_scene_count": len(story_plan.scenes),
            },
        )

    def _layout_scene(
        self,
        story: StoryScene,
        nodes: dict[str, RepresentationNode],
        relations: dict[str, RepresentationRelation],
        scene_id: str,
    ) -> RenderScene:
        scene_nodes = [nodes[nid] for nid in story.node_ids if nid in nodes]
        scene_relations = [relations[rid] for rid in story.relation_ids if rid in relations]
        positions = self._positions(story, scene_nodes, scene_relations)

        specs: list[RenderNodeSpec] = []
        for n in scene_nodes:
            x, y, scale, meta = positions.get(n.knowledge_node_id, (0.0, 0.0, 1.0, {}))
            w, h = self._measure(n)
            specs.append(
                RenderNodeSpec(
                    knowledge_node_id=n.knowledge_node_id,
                    name=n.name,
                    definition=n.definition,
                    archetype="container" if meta.get("container_root") else n.archetype,
                    profile_id=n.profile_id,
                    x=x,
                    y=y,
                    width=meta.get('layout_width', w),
                    height=meta.get('layout_height', h),
                    scale=scale,
                    role=n.role,
                    emphasis="focus" if n.knowledge_node_id in story.focus_node_ids else "normal",
                    metadata={**n.metadata, **meta, "render_requirements": list(n.render_requirements)},
                )
            )
        specs = self._fit(specs)

        rel_specs = tuple(
            RenderRelationSpec(
                relation_id=r.relation_id,
                source_node_id=r.source_node_id,
                target_node_id=r.target_node_id,
                stored_source_node_id=r.stored_source_node_id,
                stored_target_node_id=r.stored_target_node_id,
                relation_type=r.relation_type,
                narrative_relation_type=r.narrative_relation_type,
                pattern_id=r.pattern_id,
                template_id=r.grammar_template_id,
                label_mode=r.relation_label_mode,
                mediator_node_id=r.mediator_node_id,
                metadata=r.metadata,
            )
            for r in scene_relations
        )
        beat_specs = tuple(
            RenderBeat(
                beat_id=b.beat_id,
                beat_type=b.beat_type,
                template_id=b.template_id,
                pattern_id=b.pattern_id,
                phase_id=b.phase_id,
                node_ids=b.node_ids,
                relation_ids=b.relation_ids,
                narration=b.narration,
                duration=b.duration,
                parameters=b.parameters,
            )
            for b in story.beats
        )
        return RenderScene(
            scene_id=scene_id,
            story_scene_id=story.story_scene_id,
            title=story.title,
            scene_role=story.scene_role,
            layout=story.layout_hint,
            nodes=tuple(specs),
            relations=rel_specs,
            beats=beat_specs,
            carry_over_node_ids=story.carry_over_node_ids,
            focus_node_ids=story.focus_node_ids,
            narration_summary=story.narration_summary,
            metadata=story.metadata,
        )

    # ------------------------------------------------------------------
    # Layout families
    # ------------------------------------------------------------------

    def _positions(self, story: StoryScene, nodes, relations):
        layout = story.layout_hint
        if layout == "abstraction_interface":
            return self._abstraction_interface(story, nodes)
        if layout == "layered_system":
            roles = story.metadata.get('semantic_roles', {})
            ordered = list(dict.fromkeys(roles.values()))
            return {n.knowledge_node_id: (0, (len(ordered)-1)/2 - ordered.index(n.knowledge_node_id), .7, {})
                    for n in nodes if n.knowledge_node_id in ordered}
        if layout == "category_embed":
            return self._category_embed(nodes, relations)
        if layout == "inside_container":
            return self._inside_container(story, nodes, relations)
        if layout == "branch_tree":
            return self._branch_tree(story, nodes, relations)
        if layout == "controller_targets":
            return self._controller_targets(nodes, relations)
        if layout == "interface_bridge":
            return self._interface_bridge(nodes)
        if layout == "execution_entry":
            return self._execution_entry(nodes, relations)
        if layout in {"transform_pipeline", "horizontal_flow"}:
            return self._horizontal(nodes)
        if layout in {"storage_write", "storage_read"}:
            return self._storage(nodes)
        if layout == "side_by_side":
            return self._side_by_side(nodes)
        if layout == "center_satellites":
            return self._center_satellites(story, nodes)
        if layout in {"parallel_lanes", "pipeline_stages", "timeline", "factors_to_metric"}:
            return self._horizontal(nodes)
        if layout == "text_only":
            return {}
        return self._connected_pair(nodes)

    def _abstraction_interface(self, story, nodes):
        roles = story.metadata['semantic_roles']
        boundary = roles['boundary']
        upper = list(dict.fromkeys(n for k, n in roles.items() if k.startswith('upper_layer')))
        lower = list(dict.fromkeys(n for k, n in roles.items()
                                  if k.startswith(('lower_layer', 'implementation_'))))
        pos = {boundary: (0, 0, 1, {'semantic_role': 'boundary',
            'layout_width': 6.8, 'layout_height': .65, 'interface_boundary': True})}
        for group, y, role in ((upper, 1.65, 'upper_layer'), (lower, -1.65, 'lower_layer')):
            for i, nid in enumerate(group):
                pos[nid] = ((i-(len(group)-1)/2)*2.8, y, .75,
                            {'semantic_role': role, 'layout_width': 2.7, 'layout_height': 1.15})
        extras = [n for n in nodes if n.knowledge_node_id not in pos]
        for i, n in enumerate(extras):
            pos[n.knowledge_node_id] = (4.65, (len(extras)-1)*.6-i*1.2, .65,
                {'semantic_role': 'support', 'layout_width': 2.5, 'layout_height': 1.0})
        return pos

    def _category_embed(self, nodes, relations):
        pos = {}
        member = None
        category = None
        if relations:
            r = relations[0]
            if r.relation_type == "IS_A":
                member = r.stored_source_node_id
                category = r.stored_target_node_id
        if category:
            pos[category] = (0.0, 0.1, 1.35, {"semantic_role": "category"})
        if member:
            pos[member] = (0.0, -0.1, 0.85, {"semantic_role": "member", "initial_x": -4.4, "initial_y": -0.2})
        for n in nodes:
            pos.setdefault(n.knowledge_node_id, (0.0, 0.0, 0.9, {}))
        return pos

    def _inside_container(self, story, nodes, relations):
        pos = {}
        pairs = [(r.stored_source_node_id, r.stored_target_node_id) if r.relation_type == 'PART_OF'
                 else (r.stored_target_node_id, r.stored_source_node_id)
                 for r in relations if r.relation_type in {'PART_OF', 'CONTAINS', 'HAS_PART'}]
        ids = {n.knowledge_node_id for n in nodes}
        pairs = [(part, whole) for part, whole in pairs if part in ids and whole in ids and part != whole]
        roots = {whole for _, whole in pairs}
        # A single container is only meaningful for one explicit whole and its
        # direct children. Never infer containment from focus or traversal order.
        if len(roots) != 1:
            return {n.knowledge_node_id: ((i - (len(nodes)-1)/2)*3, 0, .8, {})
                    for i, n in enumerate(nodes)}
        root_id = next(iter(roots))
        child_ids = {part for part, whole in pairs if whole == root_id}
        children = [n for n in nodes if n.knowledge_node_id in child_ids]
        if children:
            cols = min(3, len(children))
            rows = math.ceil(len(children) / cols)
            xgap = 2.5
            ygap = 1.3
            pos[root_id] = (0.0, 0.0, 1.0, {'semantic_role': 'whole', 'container_root': True,
                'layout_width': cols*xgap+.5, 'layout_height': rows*ygap+1.0})
            for i, n in enumerate(children):
                row, col = divmod(i, cols)
                x = (col - (cols - 1) / 2) * xgap
                y = (rows-1)*ygap/2 - row*ygap - .25
                pos[n.knowledge_node_id] = (x, y, 1.0, {"semantic_role": "part", "initial_scale": 0.1,
                    'layout_width': 2.1, 'layout_height': .95})
            extras = [n for n in nodes if n.knowledge_node_id not in child_ids | {root_id}]
            for i, n in enumerate(extras):
                pos[n.knowledge_node_id] = ((i-(len(extras)-1)/2)*2.5,
                    -(rows*ygap+1)/2-1, .65, {'semantic_role': 'context'})
        return pos

    def _branch_tree(self, story, nodes, relations):
        pos = {}
        root_id = story.focus_node_ids[0] if story.focus_node_ids else (nodes[0].knowledge_node_id if nodes else None)
        if root_id:
            pos[root_id] = (0.0, 1.6, 0.95, {"semantic_role": "root"})
        children = [n for n in nodes if n.knowledge_node_id != root_id]
        n = max(1, len(children))
        span = min(9.5, max(3.0, n * 2.35))
        for i, node in enumerate(children):
            x = 0.0 if n == 1 else -span / 2 + span * i / (n - 1)
            pos[node.knowledge_node_id] = (x, -1.1, 0.78, {"semantic_role": "branch"})
        return pos

    def _controller_targets(self, nodes, relations):
        pos = {}
        controller = None
        if relations:
            r = relations[0]
            if r.relation_type in {"CONTROLS", "MANAGES"}:
                controller = r.stored_source_node_id
        if controller:
            pos[controller] = (-3.2, 0.0, 1.0, {"semantic_role": "controller"})
        targets = [n for n in nodes if n.knowledge_node_id != controller]
        for i, n in enumerate(targets):
            y = (len(targets) - 1) * 0.9 / 2 - i * 0.9
            pos[n.knowledge_node_id] = (2.6, y, 0.85, {"semantic_role": "target"})
        return pos

    def _interface_bridge(self, nodes):
        pos = {}
        interfaces = [n for n in nodes if n.archetype == "interface_layer"]
        center = interfaces[0] if interfaces else (nodes[1] if len(nodes) >= 3 else (nodes[0] if nodes else None))
        if center:
            pos[center.knowledge_node_id] = (0.0, 0.0, 1.0, {"semantic_role": "interface"})
        others = [n for n in nodes if center is None or n.knowledge_node_id != center.knowledge_node_id]
        if others:
            pos[others[0].knowledge_node_id] = (0.0, 2.0, 0.9, {"semantic_role": "upper_layer"})
        if len(others) > 1:
            pos[others[1].knowledge_node_id] = (0.0, -2.0, 0.9, {"semantic_role": "lower_layer"})
        for i, n in enumerate(others[2:], 2):
            pos[n.knowledge_node_id] = (3.5, 1.2 - (i - 2) * 1.1, 0.75, {"semantic_role": "context"})
        return pos

    def _execution_entry(self, nodes, relations):
        pos = {}
        executor = token = None
        if relations:
            r = next((x for x in relations if x.relation_type == "EXECUTES"), relations[0])
            executor = r.stored_source_node_id
            token = r.stored_target_node_id
        if token:
            pos[token] = (-3.8, 0.0, 0.8, {"semantic_role": "token", "initial_x": -4.5, "initial_y": 0.0})
        if executor:
            pos[executor] = (2.4, 0.0, 1.2, {"semantic_role": "executor"})
        for n in nodes:
            pos.setdefault(n.knowledge_node_id, (0.0, 0.0, 0.8, {}))
        return pos

    def _horizontal(self, nodes):
        pos = {}
        widths = [self._measure(n)[0] * 0.78 for n in nodes]
        total = sum(widths) + max(0, len(nodes) - 1) * 0.65
        cursor = -total / 2
        for n, w in zip(nodes, widths):
            x = cursor + w / 2
            pos[n.knowledge_node_id] = (x, 0.0, 0.78, {"semantic_role": "flow_step"})
            cursor += w + 0.65
        return pos

    def _storage(self, nodes):
        pos = {}
        storage = next((n for n in nodes if n.archetype in {"storage_block", "memory_chip"}), None)
        if storage:
            pos[storage.knowledge_node_id] = (2.5, 0.0, 1.05, {"semantic_role": "storage"})
        others = [n for n in nodes if storage is None or n.knowledge_node_id != storage.knowledge_node_id]
        for i, n in enumerate(others):
            pos[n.knowledge_node_id] = (-3.0, 0.7 - i * 1.3, 0.8, {"semantic_role": "payload"})
        return pos

    def _side_by_side(self, nodes):
        pos = {}
        if nodes:
            pos[nodes[0].knowledge_node_id] = (-3.0, 0.0, 1.0, {"semantic_role": "left"})
        if len(nodes) > 1:
            pos[nodes[1].knowledge_node_id] = (3.0, 0.0, 1.0, {"semantic_role": "right"})
        for i, n in enumerate(nodes[2:], 2):
            x = -3.0 if i % 2 == 0 else 3.0
            y = -1.6 - (i // 2 - 1) * 0.9
            pos[n.knowledge_node_id] = (x, y, 0.7, {"semantic_role": "support"})
        return pos

    def _center_satellites(self, story, nodes):
        pos = {}
        root_id = story.focus_node_ids[0] if story.focus_node_ids else (nodes[0].knowledge_node_id if nodes else None)
        if root_id:
            pos[root_id] = (0.0, 0.0, 1.0, {"semantic_role": "center"})
        others = [n for n in nodes if n.knowledge_node_id != root_id]
        radius = 3.0
        for i, n in enumerate(others):
            angle = math.pi / 2 - (2 * math.pi * i / max(1, len(others)))
            pos[n.knowledge_node_id] = (radius * math.cos(angle), radius * 0.65 * math.sin(angle), 0.72, {"semantic_role": "satellite"})
        return pos

    def _connected_pair(self, nodes):
        pos = {}
        if nodes:
            pos[nodes[0].knowledge_node_id] = (-2.4, 0.0, 0.9, {})
        if len(nodes) > 1:
            pos[nodes[1].knowledge_node_id] = (2.4, 0.0, 0.9, {})
        for i, n in enumerate(nodes[2:], 2):
            pos[n.knowledge_node_id] = (0.0, -1.5 - (i - 2) * 0.9, 0.7, {})
        return pos

    # ------------------------------------------------------------------
    # Measurement / safe-frame fit
    # ------------------------------------------------------------------

    def _measure(self, node: RepresentationNode) -> tuple[float, float]:
        bw, bh = self.BASE_SIZE.get(node.archetype, (2.6, 1.2))
        # Estimate text width; visual profiles are allowed to grow rather than
        # forcing long Chinese/English labels into a fixed-size box.
        label_w = 1.25 + sum(0.23 if ord(ch) > 127 else 0.12 for ch in node.name)
        width = max(bw, min(4.8, label_w))
        return width, bh

    def _fit(self, specs: list[RenderNodeSpec]) -> list[RenderNodeSpec]:
        if not specs:
            return specs
        min_x = min(s.x - s.width * s.scale / 2 for s in specs)
        max_x = max(s.x + s.width * s.scale / 2 for s in specs)
        min_y = min(s.y - s.height * s.scale / 2 for s in specs)
        max_y = max(s.y + s.height * s.scale / 2 for s in specs)
        w = max_x - min_x
        h = max_y - min_y
        factor = min(1.0, self.SAFE_WIDTH / max(w, 0.01), self.SAFE_HEIGHT / max(h, 0.01))
        if factor >= 0.999:
            return specs
        return [
            replace(
                s,
                x=round(s.x * factor, 3),
                y=round(s.y * factor, 3),
                scale=round(s.scale * factor, 3),
                metadata={**s.metadata, "camera_fit_scale": round(factor, 3)},
            )
            for s in specs
        ]

    @staticmethod
    def _index_nodes(seg: RepresentationSegment) -> dict[str, RepresentationNode]:
        out: dict[str, RepresentationNode] = {}
        def visit(s):
            for n in s.nodes:
                out.setdefault(n.knowledge_node_id, n)
            for c in s.children:
                visit(c)
        visit(seg)
        return out

    @staticmethod
    def _index_relations(seg: RepresentationSegment) -> dict[str, RepresentationRelation]:
        out: dict[str, RepresentationRelation] = {}
        def visit(s):
            for r in s.relations:
                out.setdefault(r.relation_id, r)
            for c in s.children:
                visit(c)
        visit(seg)
        return out
