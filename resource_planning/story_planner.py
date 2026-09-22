from __future__ import annotations

from dataclasses import asdict, replace

from representation.models import (
    RepresentationNode,
    RepresentationPlan,
    RepresentationRelation,
    RepresentationSegment,
)
from .models import StoryBeat, StoryPlan, StoryScene
from .narration_planner import NarrationPlanner
from .semantic_scene_planner import SemanticScenePlanner


class VisualStoryPlanner:
    """Turn recursive representation segments into semantic visual stories.

    This planner never falls back to "draw a box and label the relation" unless
    the selected workbook animation pattern itself has no semantic template.
    Each relation contributes a micro-scene grammar (phases), and related facts
    are grouped into one teaching scene when possible.
    """

    def __init__(self, narration: NarrationPlanner | None = None, *, max_nodes_per_scene: int = 8):
        self.narration = narration or NarrationPlanner()
        self.max_nodes_per_scene = max_nodes_per_scene
        self.semantic_planner = SemanticScenePlanner()
        self._nodes: dict[str, RepresentationNode] = {}
        self._relations: dict[str, RepresentationRelation] = {}

    def plan(self, representation_plan: RepresentationPlan) -> StoryPlan:
        self._nodes = self._index_nodes(representation_plan.root_segment)
        self._relations = self._index_relations(representation_plan.root_segment)
        scenes: list[StoryScene] = []
        self._emit_segment(representation_plan.root_segment, scenes)

        previous: set[str] = set()
        enriched: list[StoryScene] = []
        for i, scene in enumerate(scenes, 1):
            current = set(scene.node_ids)
            carry = tuple(sorted(previous & current))
            enriched.append(replace(scene, story_scene_id=f"SS{i:03d}", carry_over_node_ids=carry,
                metadata={**scene.metadata, 'visual_claim': scene.metadata.get('visual_claim')
                          or scene.narration_summary or scene.title}))
            previous = current

        duration = sum(sum(b.duration for b in s.beats) for s in enriched)
        return StoryPlan(
            question=representation_plan.question,
            intent=representation_plan.intent,
            scenes=tuple(enriched),
            estimated_duration=round(duration, 2),
            representation_plan=representation_plan,
            metadata={
                "planner": "subgraph_semantic_scene_planner_v0.3",
                "scene_count": len(enriched),
                "principle": "evidence group -> semantic scene -> workbook relation grammar -> story beats",
                "scene_plans": [s.metadata['semantic_scene_plan'] for s in enriched
                                if s.metadata.get('semantic_scene_plan')],
            },
        )

    # ------------------------------------------------------------------
    # Recursive segment planning
    # ------------------------------------------------------------------

    def _emit_segment(self, seg: RepresentationSegment, out: list[StoryScene]) -> None:
        if seg.metadata.get('prerequisite'):
            scenes = ([self._reference_scene(seg)] if seg.segment_type == 'reference'
                      else self._definition_scenes(seg))
            for scene in scenes:
                narration = seg.metadata['student_narration']
                out.append(replace(scene, narration_summary=narration,
                    beats=tuple(replace(b, narration=narration) for b in scene.beats),
                    metadata={**scene.metadata, **seg.metadata}))
            return
        if seg.segment_type == "sequence":
            for child in seg.children:
                self._emit_segment(child, out)
            return
        if seg.segment_type not in {"empty", "reference", "definition"}:
            rels = self._collect_relations(seg, depth=100)
            nodes = self._collect_nodes(seg, depth=100)
            semantic = self.semantic_planner.build(seg, nodes, rels)
            if semantic and len(set(semantic.node_ids) | {n.knowledge_node_id for n in nodes}) <= self.max_nodes_per_scene:
                out.append(self._semantic_scene(seg, semantic, rels))
                return
        if seg.segment_type == "empty":
            out.append(self._empty_scene(seg))
            return
        if seg.segment_type == "reference":
            out.append(self._reference_scene(seg))
            return
        if seg.segment_type == "definition":
            out.extend(self._definition_scenes(seg))
            return
        if seg.segment_type == "comparison":
            out.append(self._comparison_scene(seg))
            return
        if seg.segment_type == "branch":
            out.append(self._branch_scene(seg))
            for child in seg.children:
                if child.children and child.segment_type not in {"fact", "reference"}:
                    self._emit_segment(child, out)
            return
        if seg.segment_type == "linear":
            out.append(self._linear_scene(seg))
            for child in seg.children:
                self._emit_segment(child, out)
            return
        if seg.segment_type == "fact":
            if len(seg.relations) > 1:
                out.extend(self._relation_scene(seg, r, role="fact") for r in seg.relations)
            else:
                out.append(self._fact_scene(seg))
            return
        if seg.segment_type == "evidence_group":
            # A stricter runtime budget must never silently drop grouped edges.
            out.extend(self._relation_scene(seg, r, role="fact") for r in seg.relations)
            return
        if seg.segment_type == "hybrid":
            out.append(self._hybrid_overview(seg))
            for child in seg.children:
                self._emit_segment(child, out)
            return
        out.append(self._generic_scene(seg))

    def _semantic_scene(self, seg, plan, rels):
        rels = [r for r in rels if r.relation_id in plan.relation_ids]
        ids = self._dedupe_ids((*plan.node_ids,
            *(n for r in rels for n in self._relation_node_ids(r))))
        beats = []
        roles = plan.semantic_roles
        interface = plan.scene_pattern in {"ABSTRACTION_INTERFACE", "ONE_ABSTRACTION_MULTI_IMPLEMENTATION"}
        def scene_beat(phase, node_ids, narration):
            beats.append(StoryBeat(f'{seg.segment_id}.scene.{len(beats)+1}', 'scene_semantics',
                'semantic_scene', '', phase, tuple(node_ids), narration=narration,
                duration=.8, parameters={'scene_pattern': plan.scene_pattern,
                    'semantic_roles': roles, 'visual_claim': plan.visual_claim}))
        if interface:
            upper = self._dedupe_ids(n for role, n in roles.items() if role.startswith('upper_layer'))
            boundary = roles['boundary']
            for nid in upper:
                scene_beat('reveal_upper', (nid,), f'先看{self._nodes[nid].name}。')
            scene_beat('reveal_boundary', (boundary,), f'{self._nodes[boundary].name}位于接口边界。')
            # Complete the upper dependency before introducing implementations.
            rels.sort(key=lambda r: not bool(set(upper) & {r.source_node_id, r.target_node_id}))
        for i, rel in enumerate(rels, 1):
            local_beats = self._beats_for_relation(rel, prefix=f'{seg.segment_id}.r{i}')
            if interface:
                # Reuse relation-selected patterns/phases; scene mode keeps their
                # local effects at fixed semantic positions instead of morphing
                # or moving the shared boundary into an implementation.
                local_beats = [replace(b, parameters={**b.parameters,
                    'scene_pattern': plan.scene_pattern, 'scene_semantic_roles': roles,
                    'scene_relation_start': j == 0, 'scene_relation_end': j == len(local_beats)-1})
                    for j, b in enumerate(local_beats)]
            beats.extend(local_beats)
        scene_beat('highlight_boundary' if interface else 'highlight_claim', plan.focal_node_ids, plan.visual_claim)
        scene_beat('emphasize_claim', plan.focal_node_ids, plan.visual_claim)
        return StoryScene('', seg.segment_id, seg.title, 'semantic_scene', plan.layout_family,
            ids, tuple(r.relation_id for r in rels), tuple(beats),
            focus_node_ids=plan.focal_node_ids, narration_summary=plan.visual_claim,
            metadata={**seg.metadata, 'scene_pattern': plan.scene_pattern,
                'semantic_scene_plan': asdict(plan), 'semantic_roles': roles,
                'visual_claim': plan.visual_claim, 'atomic_semantic_scene': True})

    def _definition_scenes(self, seg: RepresentationSegment) -> list[StoryScene]:
        root = self._root_node(seg)
        if root is None:
            return [self._generic_scene(seg)]
        rels = self._collect_relations(seg, depth=1)
        isa = [r for r in rels if r.relation_type == "IS_A"]
        parts = [r for r in rels if r.relation_type == "PART_OF" and r.stored_target_node_id == root.knowledge_node_id]
        interfaces = [r for r in rels if r.relation_type == "INTERFACES_WITH"]
        others = [r for r in rels if r not in isa and r not in parts and r not in interfaces]
        scenes: list[StoryScene] = []

        # 1) Definition core + category membership.  For IS_A, the object is
        # animated into the larger category instead of being connected by a raw arrow.
        if isa:
            rel = isa[0]
            node_ids = self._dedupe_ids((rel.stored_target_node_id, rel.stored_source_node_id))
            beats = self._beats_for_relation(rel, prefix=f"{seg.segment_id}.isa")
            beats.append(
                StoryBeat(
                    beat_id=f"{seg.segment_id}.def",
                    beat_type="definition_text",
                    template_id="definition_focus",
                    pattern_id="",
                    phase_id="definition",
                    node_ids=(root.knowledge_node_id,),
                    narration=self.narration.definition_sentence(root),
                    duration=0.9,
                )
            )
            scenes.append(
                StoryScene(
                    story_scene_id="",
                    segment_id=seg.segment_id,
                    title=seg.title,
                    scene_role="definition_category",
                    layout_hint="category_embed",
                    node_ids=node_ids,
                    relation_ids=(rel.relation_id,),
                    beats=tuple(beats),
                    focus_node_ids=(root.knowledge_node_id,),
                    narration_summary=self.narration.definition_sentence(root),
                    metadata={"semantic_mode": "definition_plus_is_a"},
                )
            )
        else:
            scenes.append(
                StoryScene(
                    story_scene_id="",
                    segment_id=seg.segment_id,
                    title=seg.title,
                    scene_role="definition_focus",
                    layout_hint="center_focus",
                    node_ids=(root.knowledge_node_id,),
                    beats=(
                        StoryBeat(
                            beat_id=f"{seg.segment_id}.def",
                            beat_type="definition_text",
                            template_id="definition_focus",
                            pattern_id="",
                            phase_id="definition",
                            node_ids=(root.knowledge_node_id,),
                            narration=self.narration.definition_sentence(root),
                            duration=1.0,
                        ),
                    ),
                    focus_node_ids=(root.knowledge_node_id,),
                    narration_summary=self.narration.definition_sentence(root),
                )
            )

        # 2) Components/support should be shown as internal structure.
        if parts:
            node_ids = [root.knowledge_node_id]
            for rel in parts:
                node_ids.append(rel.stored_source_node_id)
            beats: list[StoryBeat] = []
            for i, rel in enumerate(parts, 1):
                beats.extend(self._beats_for_relation(rel, prefix=f"{seg.segment_id}.part{i}"))
            scenes.append(
                StoryScene(
                    story_scene_id="",
                    segment_id=seg.segment_id,
                    title=f"{root.name} 的内部/规定内容",
                    scene_role="definition_components",
                    layout_hint="inside_container",
                    node_ids=self._dedupe_ids(node_ids),
                    relation_ids=tuple(r.relation_id for r in parts),
                    beats=tuple(beats),
                    focus_node_ids=(root.knowledge_node_id,),
                    narration_summary=f"再看{root.name}内部包含或规定了哪些关键内容。",
                )
            )

        # 3) Interface role is a separate semantic view rather than another arrow.
        if interfaces:
            node_ids = [root.knowledge_node_id]
            for rel in interfaces:
                node_ids.extend((rel.source_node_id, rel.target_node_id))
            beats: list[StoryBeat] = []
            for i, rel in enumerate(interfaces, 1):
                beats.extend(self._beats_for_relation(rel, prefix=f"{seg.segment_id}.if{i}"))
            scenes.append(
                StoryScene(
                    story_scene_id="",
                    segment_id=seg.segment_id,
                    title=f"{root.name} 的接口位置",
                    scene_role="definition_interface",
                    layout_hint="interface_bridge",
                    node_ids=self._dedupe_ids(node_ids),
                    relation_ids=tuple(r.relation_id for r in interfaces),
                    beats=tuple(beats),
                    focus_node_ids=(root.knowledge_node_id,),
                    narration_summary=f"最后把{root.name}放回它所在的上下层关系中。",
                )
            )

        if others and len(scenes) == 1:
            # Add a small support scene only when the definition otherwise has no
            # structural support. This prevents definitions from exploding.
            rel = others[0]
            scenes.append(self._relation_scene(seg, rel, role="definition_support"))
        return scenes

    def _linear_scene(self, seg: RepresentationSegment) -> StoryScene:
        rels = list(seg.relations)
        node_ids = self._ordered_linear_nodes(seg)
        beats: list[StoryBeat] = []
        for i, rel in enumerate(rels, 1):
            beats.extend(self._beats_for_relation(rel, prefix=f"{seg.segment_id}.r{i}"))
        layout = self._linear_layout_hint(rels)
        return StoryScene(
            story_scene_id="",
            segment_id=seg.segment_id,
            title=seg.title,
            scene_role="linear_explanation",
            layout_hint=layout,
            node_ids=tuple(node_ids[: self.max_nodes_per_scene]),
            relation_ids=tuple(r.relation_id for r in rels),
            beats=tuple(beats),
            focus_node_ids=(node_ids[0],) if node_ids else (),
            narration_summary=seg.title,
        )

    def _branch_scene(self, seg: RepresentationSegment) -> StoryScene:
        root = self._root_node(seg)
        rels = self._collect_relations(seg, depth=1)
        if root is None:
            return self._generic_scene(seg)
        if not rels:
            child_roots = [self._root_node(c) for c in seg.children]
            node_ids = [root.knowledge_node_id] + [x.knowledge_node_id for x in child_roots if x]
            return StoryScene(
                story_scene_id="",
                segment_id=seg.segment_id,
                title=seg.title,
                scene_role="branch_overview",
                layout_hint="branch_tree",
                node_ids=self._dedupe_ids(node_ids),
                beats=(
                    StoryBeat(
                        beat_id=f"{seg.segment_id}.branch",
                        beat_type="branch_reveal",
                        template_id="tree_expand",
                        pattern_id="TREE_EXPAND",
                        phase_id="expand_children",
                        node_ids=self._dedupe_ids(node_ids),
                        narration="从中心概念向外展开相关分支。",
                        duration=0.9,
                    ),
                ),
                focus_node_ids=(root.knowledge_node_id,),
            )

        relation_types = {r.relation_type for r in rels}
        if relation_types <= {"PART_OF"}:
            layout = "inside_container"
        elif relation_types <= {"IS_A"}:
            layout = "branch_tree"
        elif relation_types <= {"CONTROLS", "MANAGES"}:
            layout = "controller_targets"
        else:
            layout = "branch_tree"

        node_ids = [root.knowledge_node_id]
        beats: list[StoryBeat] = []
        for i, rel in enumerate(rels, 1):
            node_ids.extend((rel.source_node_id, rel.target_node_id))
            beats.extend(self._beats_for_relation(rel, prefix=f"{seg.segment_id}.b{i}"))
        return StoryScene(
            story_scene_id="",
            segment_id=seg.segment_id,
            title=seg.title,
            scene_role="branch_explanation",
            layout_hint=layout,
            node_ids=self._dedupe_ids(node_ids)[: self.max_nodes_per_scene],
            relation_ids=tuple(r.relation_id for r in rels),
            beats=tuple(beats),
            focus_node_ids=(root.knowledge_node_id,),
            narration_summary=seg.title,
        )

    def _comparison_scene(self, seg: RepresentationSegment) -> StoryScene:
        rels = self._collect_relations(seg, depth=1)
        contrast = next((r for r in rels if r.relation_type == "CONTRASTS_WITH"), None)
        nodes = self._collect_nodes(seg, depth=1)
        node_ids = tuple(n.knowledge_node_id for n in nodes[: self.max_nodes_per_scene])
        beats: list[StoryBeat] = []
        if contrast:
            beats.extend(self._beats_for_relation(contrast, prefix=f"{seg.segment_id}.cmp"))
        else:
            beats.append(
                StoryBeat(
                    beat_id=f"{seg.segment_id}.cmp",
                    beat_type="comparison",
                    template_id="side_by_side",
                    pattern_id="SIDE_BY_SIDE",
                    phase_id="compare",
                    node_ids=node_ids,
                    narration="把两侧并列起来进行比较。",
                    duration=0.9,
                )
            )
        return StoryScene(
            story_scene_id="",
            segment_id=seg.segment_id,
            title=seg.title,
            scene_role="comparison",
            layout_hint="side_by_side",
            node_ids=node_ids,
            relation_ids=tuple(r.relation_id for r in rels),
            beats=tuple(beats),
            focus_node_ids=node_ids[:2],
            narration_summary=seg.title,
        )

    def _fact_scene(self, seg: RepresentationSegment) -> StoryScene:
        if seg.relations:
            return self._relation_scene(seg, seg.relations[0], role="fact")
        return self._generic_scene(seg)

    def _relation_scene(self, seg: RepresentationSegment, rel: RepresentationRelation, *, role: str) -> StoryScene:
        node_ids = self._relation_node_ids(rel)
        return StoryScene(
            story_scene_id="",
            segment_id=seg.segment_id,
            title=seg.title,
            scene_role=role,
            layout_hint=self._layout_for_relation(rel),
            node_ids=node_ids,
            relation_ids=(rel.relation_id,),
            beats=tuple(self._beats_for_relation(rel, prefix=f"{seg.segment_id}.rel")),
            focus_node_ids=(rel.source_node_id,),
            narration_summary=self.narration.relation_sentence(rel, self._nodes),
        )

    def _hybrid_overview(self, seg: RepresentationSegment) -> StoryScene:
        root = self._root_node(seg)
        child_roots = [self._root_node(c) for c in seg.children]
        node_ids = []
        if root:
            node_ids.append(root.knowledge_node_id)
        node_ids.extend(x.knowledge_node_id for x in child_roots if x)
        node_ids = list(self._dedupe_ids(node_ids))[: self.max_nodes_per_scene]
        return StoryScene(
            story_scene_id="",
            segment_id=seg.segment_id,
            title=seg.title,
            scene_role="hybrid_overview",
            layout_hint="center_satellites",
            node_ids=tuple(node_ids),
            beats=(
                StoryBeat(
                    beat_id=f"{seg.segment_id}.overview",
                    beat_type="overview",
                    template_id="overview_reveal",
                    pattern_id="FADE_REVEAL",
                    phase_id="reveal",
                    node_ids=tuple(node_ids),
                    narration="先建立整体框架，再逐项进入具体关系。",
                    duration=0.9,
                ),
            ),
            focus_node_ids=(root.knowledge_node_id,) if root else (),
        )

    def _reference_scene(self, seg: RepresentationSegment) -> StoryScene:
        ids = tuple(str(x) for x in seg.metadata.get("referenced_node_ids", ()) or ())
        if not ids:
            ids = tuple(n.knowledge_node_id for n in seg.nodes)
        return StoryScene(
            story_scene_id="",
            segment_id=seg.segment_id,
            title=seg.title,
            scene_role="reference",
            layout_hint="reuse_existing",
            node_ids=ids,
            beats=(
                StoryBeat(
                    beat_id=f"{seg.segment_id}.ref",
                    beat_type="reference",
                    template_id="highlight_existing",
                    pattern_id="",
                    phase_id="highlight",
                    node_ids=ids,
                    narration="回到前面已经出现过的概念。",
                    duration=0.65,
                ),
            ),
            focus_node_ids=ids,
        )

    def _empty_scene(self, seg: RepresentationSegment) -> StoryScene:
        note = str(seg.metadata.get("note", "当前知识图谱证据不足。"))
        return StoryScene(
            story_scene_id="",
            segment_id=seg.segment_id,
            title=seg.title,
            scene_role="evidence_gap",
            layout_hint="text_only",
            node_ids=(),
            beats=(
                StoryBeat(
                    beat_id=f"{seg.segment_id}.gap",
                    beat_type="note",
                    template_id="text_note",
                    pattern_id="",
                    phase_id="show_note",
                    narration=note,
                    duration=1.0,
                ),
            ),
            narration_summary=note,
        )

    def _generic_scene(self, seg: RepresentationSegment) -> StoryScene:
        nodes = self._collect_nodes(seg, depth=0)[: self.max_nodes_per_scene]
        ids = tuple(n.knowledge_node_id for n in nodes)
        return StoryScene(
            story_scene_id="",
            segment_id=seg.segment_id,
            title=seg.title,
            scene_role="generic",
            layout_hint="center_satellites",
            node_ids=ids,
            relation_ids=tuple(r.relation_id for r in seg.relations),
            beats=(
                StoryBeat(
                    beat_id=f"{seg.segment_id}.generic",
                    beat_type="overview",
                    template_id="fade_reveal",
                    pattern_id="FADE_REVEAL",
                    phase_id="reveal",
                    node_ids=ids,
                    narration=seg.title,
                    duration=0.8,
                ),
            ),
            focus_node_ids=ids[:1],
        )

    # ------------------------------------------------------------------
    # Beat construction / semantic roles
    # ------------------------------------------------------------------

    def _beats_for_relation(self, rel: RepresentationRelation, *, prefix: str) -> list[StoryBeat]:
        roles = self._semantic_roles(rel)
        node_ids = self._relation_node_ids(rel)
        beats: list[StoryBeat] = []
        for i, phase in enumerate(rel.grammar_phases, 1):
            narration = self.narration.phase_sentence(rel, phase.phase_id, self._nodes, phase.narration_cue)
            beats.append(
                StoryBeat(
                    beat_id=f"{prefix}.p{i}",
                    beat_type="semantic_animation",
                    template_id=rel.grammar_template_id,
                    pattern_id=rel.pattern_id,
                    phase_id=phase.phase_id,
                    node_ids=node_ids,
                    relation_ids=(rel.relation_id,),
                    narration=narration,
                    duration=phase.duration,
                    parameters={**phase.parameters, **roles, "relation_label_mode": rel.relation_label_mode},
                )
            )
        return beats

    def _semantic_roles(self, rel: RepresentationRelation) -> dict[str, str]:
        s, d = rel.stored_source_node_id, rel.stored_target_node_id
        rt = rel.relation_type
        if rt == "IS_A":
            return {"member_id": s, "category_id": d, "subtype_id": s, "supertype_id": d}
        if rt == "PART_OF":
            return {"part_id": s, "whole_id": d}
        if rt == "CONTAINS":
            return {"whole_id": s, "part_id": d}
        if rt == "TRANSFORMS_TO":
            result = {"source_id": s, "target_id": d}
            if rel.mediator_node_id:
                result["mediator_id"] = rel.mediator_node_id
            return result
        if rt == "EXECUTES":
            return {"executor_id": s, "token_id": d}
        if rt in {"CONTROLS", "MANAGES"}:
            return {"controller_id": s, "target_id": d}
        if rt == "STORES":
            return {"storage_id": s, "payload_id": d}
        if rt in {"USES", "CONNECTS"}:
            return {"source_id": s, "target_id": d}
        if rt == "IMPLEMENTS":
            return {"concrete_id": s, "abstract_id": d}
        if rt == "CONTRASTS_WITH":
            return {"left_id": s, "right_id": d}
        return {"source_id": rel.source_node_id, "target_id": rel.target_node_id}

    def _relation_node_ids(self, rel: RepresentationRelation) -> tuple[str, ...]:
        ids = [rel.source_node_id]
        if rel.mediator_node_id:
            ids.append(rel.mediator_node_id)
        ids.append(rel.target_node_id)
        return self._dedupe_ids(ids)

    def _layout_for_relation(self, rel: RepresentationRelation) -> str:
        if rel.grammar_template_id:
            # template -> layout is encoded by pattern grammar; this mapping only
            # handles semantic templates that need a specialized layout family.
            special = {
                "category_embed": "category_embed",
                "reveal_inside": "inside_container",
                "zoom_in_nesting": "nested_zoom",
                "tree_expand": "branch_tree",
                "pipeline_transform": "transform_pipeline",
                "morph": "transform_pair",
                "interface_bridge": "interface_bridge",
                "control_signal": "controller_target",
                "token_enter_and_act": "execution_entry",
                "write_in": "storage_write",
                "read_out": "storage_read",
                "side_by_side": "side_by_side",
                "split_screen": "side_by_side",
                "parallel_flow": "parallel_lanes",
                "pipeline_stages": "pipeline_stages",
                "timeline_trend": "timeline",
                "factor_to_metric": "factors_to_metric",
            }
            return special.get(rel.grammar_template_id, "connected_pair")
        return "connected_pair"

    def _linear_layout_hint(self, rels: list[RepresentationRelation]) -> str:
        templates = {r.grammar_template_id for r in rels}
        if "interface_bridge" in templates:
            return "interface_bridge"
        if templates and templates <= {"pipeline_transform", "morph", "sequence_reveal", "process_flow"}:
            return "transform_pipeline"
        if "token_enter_and_act" in templates:
            return "execution_entry"
        return "horizontal_flow"

    # ------------------------------------------------------------------
    # Tree/query helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _index_nodes(seg: RepresentationSegment) -> dict[str, RepresentationNode]:
        out: dict[str, RepresentationNode] = {}
        def visit(s: RepresentationSegment):
            for n in s.nodes:
                out.setdefault(n.knowledge_node_id, n)
            for c in s.children:
                visit(c)
        visit(seg)
        return out

    @staticmethod
    def _index_relations(seg: RepresentationSegment) -> dict[str, RepresentationRelation]:
        out: dict[str, RepresentationRelation] = {}
        def visit(s: RepresentationSegment):
            for r in s.relations:
                out.setdefault(r.relation_id, r)
            for c in s.children:
                visit(c)
        visit(seg)
        return out

    def _root_node(self, seg: RepresentationSegment) -> RepresentationNode | None:
        if seg.root_representation_id:
            for n in seg.nodes:
                if n.representation_id == seg.root_representation_id:
                    return n
        return seg.nodes[0] if seg.nodes else None

    def _collect_nodes(self, seg: RepresentationSegment, *, depth: int) -> list[RepresentationNode]:
        out = list(seg.nodes)
        if depth > 0:
            for child in seg.children:
                out.extend(self._collect_nodes(child, depth=depth - 1))
        seen: set[str] = set()
        deduped: list[RepresentationNode] = []
        for n in out:
            if n.knowledge_node_id not in seen:
                seen.add(n.knowledge_node_id)
                deduped.append(n)
        return deduped

    def _collect_relations(self, seg: RepresentationSegment, *, depth: int) -> list[RepresentationRelation]:
        out = list(seg.relations)
        if depth > 0:
            for child in seg.children:
                out.extend(self._collect_relations(child, depth=depth - 1))
        seen: set[tuple[str, str, str]] = set()
        deduped: list[RepresentationRelation] = []
        for r in out:
            key = r.relation_id
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped

    def _ordered_linear_nodes(self, seg: RepresentationSegment) -> list[str]:
        ordered: list[str] = []
        for i, rel in enumerate(seg.relations):
            if i == 0:
                ordered.append(rel.source_node_id)
            if rel.mediator_node_id:
                ordered.append(rel.mediator_node_id)
            ordered.append(rel.target_node_id)
        if not ordered:
            ordered.extend(n.knowledge_node_id for n in seg.nodes)
        return list(self._dedupe_ids(ordered))

    @staticmethod
    def _dedupe_ids(ids) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for x in ids:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return tuple(out)
