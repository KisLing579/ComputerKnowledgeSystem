from __future__ import annotations

from typing import Iterable

from explanation.models import ExplanationPlan, ExplanationSegment
from representation.animation_grammar import AnimationGrammar
from representation.models import (
    RepresentationNode,
    RepresentationPlan,
    RepresentationRelation,
    RepresentationSegment,
)
from representation.registry import RepresentationRegistry


class RepresentationBinder:
    """Bind explanation semantics to workbook-defined multi-representations.

    Responsibilities:
      1. choose one Visual_Profile for each KG node in the current context;
      2. choose one Animation_Pattern for each KG relation from the workbook;
      3. attach a semantic micro-scene grammar to that selected pattern.

    Exact scene order, coordinates, and timing are deliberately handled later.
    """

    INTENT_TAGS = {
        "transformation_execution": {"translation_pipeline", "instruction_execution", "compilation"},
        "composition": {"composition", "hardware_overview"},
        "interface_role": {"hardware_software_interface", "software_hardware_relation"},
        "role_function": {"resource_management"},
        "relation_structure": {"structure", "overview"},
        "causal_mechanism": {"mechanism"},
        "performance": {"performance", "metric"},
        "comparison": {"comparison"},
        "definition": {"overview", "definition"},
        "general": {"overview"},
    }

    def __init__(self, registry: RepresentationRegistry, grammar: AnimationGrammar | None = None):
        self.registry = registry
        self.grammar = grammar or AnimationGrammar()

    def bind(self, plan: ExplanationPlan) -> RepresentationPlan:
        if plan.root_segment is None:
            raise ValueError("ExplanationPlan.root_segment is required")
        validation = self.registry.validate()
        root = self._bind_segment(plan.root_segment)
        pattern_ids = self._collect_pattern_ids(root)
        grammar_warnings = self.grammar.validate_pattern_ids(pattern_ids)
        warnings = list(validation.warnings)
        warnings.extend(f"No explicit semantic grammar for pattern {pid}; generic relation fallback used." for pid in grammar_warnings)
        return RepresentationPlan(
            question=plan.question,
            intent=plan.intent,
            root_segment=root,
            source_workbook=str(self.registry.workbook),
            warnings=tuple(warnings),
            metadata={
                "explanation_structure": plan.structure_type,
                "explanation_score": plan.explanation_score,
                "representation_layer": "workbook_profiles_plus_semantic_animation_grammar_v0.2",
            },
        )

    def _bind_segment(self, segment: ExplanationSegment) -> RepresentationSegment:
        tags = self._context_tags(segment)
        names = {nid: name for nid, name in zip(segment.node_ids, segment.node_names)}
        if segment.root_id and segment.root_name:
            names.setdefault(segment.root_id, segment.root_name)

        # Relations sometimes introduce endpoints not repeated in node_ids.
        for rel in segment.relations:
            for key in ("traversal_from", "traversal_to", "stored_start_id", "stored_end_id"):
                nid = str(rel.get(key, "") or "")
                if nid:
                    names.setdefault(nid, self.registry.node_name(nid))

        nodes: dict[str, RepresentationNode] = {}
        for nid, name in names.items():
            nodes[nid] = self._bind_node(
                segment=segment,
                node_id=nid,
                name=name,
                role="root" if nid == segment.root_id else "concept",
                context_tags=tags,
            )

        relations: list[RepresentationRelation] = []
        for index, raw in enumerate(segment.relations, 1):
            rel = dict(raw)
            traversal_src = str(rel.get("traversal_from") or rel.get("stored_start_id") or "")
            traversal_dst = str(rel.get("traversal_to") or rel.get("stored_end_id") or "")
            if not traversal_src or not traversal_dst:
                if index - 1 < len(segment.node_ids) - 1:
                    traversal_src = segment.node_ids[index - 1]
                    traversal_dst = segment.node_ids[index]
                else:
                    continue

            for nid in (traversal_src, traversal_dst):
                if nid not in nodes:
                    nodes[nid] = self._bind_node(
                        segment=segment,
                        node_id=nid,
                        name=self.registry.node_name(nid),
                        role="concept",
                        context_tags=tags,
                    )

            rel_type = str(rel.get("type", "RELATED_TO") or "RELATED_TO")
            narrative_type = str(rel.get("narrative_relation_type", rel_type) or rel_type)
            requested_pattern = str(rel.get("default_animation_pattern", "") or "")
            pattern = self._choose_pattern(segment, rel_type, requested_pattern, tags)
            template = self.grammar.template_for(pattern)

            mediator_id = str(rel.get("mediated_by", "") or "") or None
            mediator_representation_id = None
            if mediator_id:
                if mediator_id not in nodes:
                    nodes[mediator_id] = self._bind_node(
                        segment=segment,
                        node_id=mediator_id,
                        name=self.registry.node_name(mediator_id),
                        role="mediator",
                        context_tags=set(tags) | {"translation_pipeline", "transformer"},
                    )
                mediator_representation_id = nodes[mediator_id].representation_id

            stored_src = str(rel.get("stored_start_id") or traversal_src)
            stored_dst = str(rel.get("stored_end_id") or traversal_dst)
            rid = str(rel.get("id", "") or "") or f"{segment.segment_id}.R{index:02d}"
            relations.append(
                RepresentationRelation(
                    relation_id=rid,
                    source_representation_id=nodes[traversal_src].representation_id,
                    target_representation_id=nodes[traversal_dst].representation_id,
                    source_node_id=traversal_src,
                    target_node_id=traversal_dst,
                    stored_source_node_id=stored_src,
                    stored_target_node_id=stored_dst,
                    relation_type=rel_type,
                    narrative_relation_type=narrative_type,
                    pattern_id=pattern.pattern_id,
                    pattern_category=pattern.category,
                    grammar_template_id=template.template_id,
                    grammar_phases=template.phases,
                    relation_label_mode=template.relation_label_mode,
                    mediator_representation_id=mediator_representation_id,
                    mediator_node_id=mediator_id,
                    confidence=float(rel.get("confidence", 1.0) or 1.0),
                    metadata={
                        "kg_relation_id": rel.get("kg_relation_id", rel.get("id")),
                        "relation_layer": rel.get("relation_layer", "semantic"),
                        "source_path_ids": list(rel.get("source_path_ids", [])),
                        "workbook_pattern_definition": pattern.definition,
                        "workbook_pattern_typical_use": pattern.typical_use,
                        "semantic_template_description": template.description,
                        "animation_candidates": rel.get("animation_candidates", ""),
                    },
                )
            )

        children = tuple(self._bind_segment(child) for child in segment.children)
        root_representation_id = nodes.get(segment.root_id).representation_id if segment.root_id in nodes else None
        return RepresentationSegment(
            segment_id=segment.segment_id,
            segment_type=segment.segment_type,
            title=segment.title,
            intent=segment.intent,
            root_representation_id=root_representation_id,
            nodes=tuple(nodes.values()),
            relations=tuple(relations),
            children=children,
            score=segment.score,
            semantic_scene_plan=segment.semantic_scene_plan,
            metadata={
                **segment.metadata,
                "referenced_node_ids": segment.referenced_node_ids,
                "context_tags": tuple(sorted(tags)),
            },
        )

    def _bind_node(
        self,
        *,
        segment: ExplanationSegment,
        node_id: str,
        name: str,
        role: str,
        context_tags: Iterable[str],
    ) -> RepresentationNode:
        profile = self.registry.choose_profile(node_id, context_tags)
        archetype = self.registry.archetype(profile.visual_archetype)
        return RepresentationNode(
            representation_id=f"{segment.segment_id}:{node_id}",
            knowledge_node_id=node_id,
            name=name or self.registry.node_name(node_id),
            definition=self.registry.node_definition(node_id),
            profile_id=profile.profile_id,
            profile_name=profile.profile_name,
            archetype=profile.visual_archetype,
            detail_level=profile.detail_level,
            role=role,
            use_cases=profile.use_cases,
            render_requirements=profile.render_requirements,
            metadata={
                "profile_description": profile.description,
                "semantic_type": self.registry.node_semantic_types.get(node_id, ''),
                "archetype_definition": archetype.definition,
                "archetype_typical_patterns": archetype.typical_animation_patterns,
            },
        )

    def _context_tags(self, segment: ExplanationSegment) -> set[str]:
        tags = {
            segment.intent,
            segment.segment_type,
            str(segment.metadata.get("purpose", "")),
            str(segment.metadata.get("evidence_strategy", "")),
            str(segment.metadata.get("evidence_type", "")),
        }
        tags |= self.INTENT_TAGS.get(segment.intent, set())
        relation_types = {str(r.get("type", "")) for r in segment.relations}
        if "TRANSFORMS_TO" in relation_types:
            tags |= {"translation_pipeline", "compilation"}
        if "EXECUTES" in relation_types:
            tags.add("instruction_execution")
        if "INTERFACES_WITH" in relation_types:
            tags.add("hardware_software_interface")
        if "MANAGES" in relation_types:
            tags.add("resource_management")
        if segment.root_id == "CO049":
            tags.add("memory_hierarchy")
        if segment.root_id == "CO033" and segment.intent == "relation_structure":
            tags.add("memory_hierarchy")
        return {x for x in tags if x}

    def _choose_pattern(self, segment: ExplanationSegment, relation_type: str, requested: str, tags: set[str]):
        # Prefer a workbook-defined candidate that better expresses the segment.
        if segment.segment_type == "branch" and relation_type == "PART_OF":
            candidate_ids = {x.pattern_id for x in self.registry.animation_candidates(relation_type)}
            if "REVEAL_INSIDE" in candidate_ids:
                return self.registry.pattern("REVEAL_INSIDE")
        if segment.segment_type == "branch" and relation_type == "IS_A":
            candidate_ids = {x.pattern_id for x in self.registry.animation_candidates(relation_type)}
            if "TREE_EXPAND" in candidate_ids:
                return self.registry.pattern("TREE_EXPAND")
        if relation_type == "IS_A" and (segment.segment_type == "definition" or segment.intent == "definition"):
            return self.registry.pattern("CATEGORY_GROUP")
        if relation_type == "TRANSFORMS_TO" and "translation_pipeline" in tags:
            return self.registry.pattern("PIPELINE_TRANSFORM")
        if relation_type == "EXECUTES" and "instruction_execution" in tags:
            return self.registry.pattern("TOKEN_ENTER_AND_ACT")
        if relation_type == "INTERFACES_WITH" and "hardware_software_interface" in tags:
            return self.registry.pattern("INTERFACE_BRIDGE")
        if relation_type in {"CONTROLS", "MANAGES"}:
            return self.registry.pattern("CONTROL_SIGNAL")
        if relation_type == "CONTRASTS_WITH":
            return self.registry.pattern("SIDE_BY_SIDE")
        return self.registry.choose_animation_pattern(
            relation_type,
            requested=requested,
            context_tags=tags,
        )

    @staticmethod
    def _collect_pattern_ids(segment: RepresentationSegment) -> set[str]:
        out = {r.pattern_id for r in segment.relations}
        for child in segment.children:
            out |= RepresentationBinder._collect_pattern_ids(child)
        return out
