from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from explanation.models import ExplanationPlan, ExplanationSegment

from .models import (
    BoundVisualNode,
    BoundVisualRelation,
    BoundVisualSegment,
    VisualPlan,
)
from .registry import VisualRegistry


class VisualBinder:
    """Bind recursive explanation segments to workbook-defined visual semantics.

    This layer chooses *what each knowledge node should look like* and *which
    animation grammar pattern expresses each relation*.  It deliberately does
    not decide exact coordinates or scene timing; that is ScenePlanner's job.
    """

    INTENT_TAGS = {
        "transformation_execution": {
            "translation_pipeline",
            "instruction_execution",
            "compilation",
        },
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

    def __init__(self, registry: VisualRegistry):
        self.registry = registry

    def bind(self, plan: ExplanationPlan) -> VisualPlan:
        if plan.root_segment is None:
            raise ValueError("ExplanationPlan.root_segment is required by VisualBinder")
        validation = self.registry.validate()
        root = self._bind_segment(plan.root_segment)
        return VisualPlan(
            question=plan.question,
            intent=plan.intent,
            root_segment=root,
            profile_source=str(self.registry.workbook),
            warnings=validation.warnings,
            metadata={
                "explanation_structure": plan.structure_type,
                "explanation_score": plan.explanation_score,
                "binder": "workbook_profile_and_relation_grammar_v0.1",
            },
        )

    def _bind_segment(self, segment: ExplanationSegment) -> BoundVisualSegment:
        tags = self._context_tags(segment)
        names = {nid: name for nid, name in zip(segment.node_ids, segment.node_names)}
        if segment.root_id and segment.root_name:
            names.setdefault(segment.root_id, segment.root_name)

        # Ensure relation endpoints that may not be present in node_ids are still
        # visualizable. This happens in some fact/support segments.
        for rel in segment.relations:
            for key in ("traversal_from", "traversal_to", "stored_start_id", "stored_end_id"):
                nid = str(rel.get(key, "") or "")
                if nid:
                    names.setdefault(nid, self.registry.node_name(nid))

        nodes: dict[str, BoundVisualNode] = {}
        for nid, name in names.items():
            role = "root" if nid == segment.root_id else "concept"
            nodes[nid] = self._bind_node(
                segment=segment,
                node_id=nid,
                name=name,
                role=role,
                context_tags=tags,
            )

        relations: list[BoundVisualRelation] = []
        for index, raw in enumerate(segment.relations, 1):
            rel = dict(raw)
            src = str(rel.get("traversal_from") or rel.get("stored_start_id") or "")
            dst = str(rel.get("traversal_to") or rel.get("stored_end_id") or "")
            if not src or not dst:
                # Linear paths have ordered nodes; use the same position if the
                # relation metadata happens to omit traversal fields.
                if index - 1 < len(segment.node_ids) - 1:
                    src = segment.node_ids[index - 1]
                    dst = segment.node_ids[index]
                else:
                    continue
            for nid in (src, dst):
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
            pattern = self._choose_relation_pattern(
                segment=segment,
                relation_type=rel_type,
                narrative_type=narrative_type,
                requested=requested_pattern,
                tags=tags,
            )

            mediator_id = str(rel.get("mediated_by", "") or "") or None
            mediator_visual_id = None
            if mediator_id:
                if mediator_id not in nodes:
                    nodes[mediator_id] = self._bind_node(
                        segment=segment,
                        node_id=mediator_id,
                        name=self.registry.node_name(mediator_id),
                        role="mediator",
                        context_tags=set(tags) | {"translation_pipeline", "transformer"},
                    )
                mediator_visual_id = nodes[mediator_id].visual_id

            rid = str(rel.get("id", "") or "") or f"{segment.segment_id}.R{index:02d}"
            relations.append(
                BoundVisualRelation(
                    relation_id=rid,
                    source_visual_id=nodes[src].visual_id,
                    target_visual_id=nodes[dst].visual_id,
                    source_node_id=src,
                    target_node_id=dst,
                    relation_type=rel_type,
                    narrative_relation_type=narrative_type,
                    pattern_id=pattern.pattern_id,
                    pattern_category=pattern.category,
                    mediator_visual_id=mediator_visual_id,
                    confidence=float(rel.get("confidence", 1.0) or 1.0),
                    metadata={
                        "stored_start_id": rel.get("stored_start_id", ""),
                        "stored_end_id": rel.get("stored_end_id", ""),
                        "animation_candidates": rel.get("animation_candidates", ""),
                        "mediated_by": mediator_id or "",
                    },
                )
            )

        children = tuple(self._bind_segment(child) for child in segment.children)
        root_visual_id = nodes.get(segment.root_id).visual_id if segment.root_id in nodes else None
        return BoundVisualSegment(
            segment_id=segment.segment_id,
            segment_type=segment.segment_type,
            title=segment.title,
            intent=segment.intent,
            root_visual_id=root_visual_id,
            nodes=tuple(nodes.values()),
            relations=tuple(relations),
            children=children,
            score=segment.score,
            metadata={**segment.metadata, "referenced_node_ids": segment.referenced_node_ids, "context_tags": tuple(sorted(tags))},
        )

    def _bind_node(
        self,
        *,
        segment: ExplanationSegment,
        node_id: str,
        name: str,
        role: str,
        context_tags: Iterable[str],
    ) -> BoundVisualNode:
        profile = self.registry.choose_profile(node_id, context_tags)
        return BoundVisualNode(
            visual_id=f"{segment.segment_id}:{node_id}",
            knowledge_node_id=node_id,
            name=name or self.registry.node_name(node_id),
            profile_id=profile.profile_id,
            profile_name=profile.profile_name,
            archetype=profile.visual_archetype,
            detail_level=profile.detail_level,
            role=role,
            use_cases=profile.use_cases,
            render_requirements=profile.render_requirements,
            metadata={"profile_description": profile.description},
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

    def _choose_relation_pattern(
        self,
        *,
        segment: ExplanationSegment,
        relation_type: str,
        narrative_type: str,
        requested: str,
        tags: set[str],
    ):
        # Segment structure is allowed to choose between candidate grammars, but
        # it never changes the underlying semantic relation.
        if segment.segment_type == "comparison" or segment.intent == "comparison":
            if relation_type == "CONTRASTS_WITH":
                return self.registry.pattern("SIDE_BY_SIDE")
        if segment.segment_type == "branch" and relation_type in {"PART_OF", "IS_A"}:
            # A branch explanation reads more naturally as expansion than as a
            # single parent-child morph.
            return self.registry.pattern("TREE_EXPAND")
        if "translation_pipeline" in tags and relation_type == "TRANSFORMS_TO":
            return self.registry.pattern("PIPELINE_TRANSFORM")
        if "instruction_execution" in tags and relation_type == "EXECUTES":
            return self.registry.pattern("TOKEN_ENTER_AND_ACT")
        if "hardware_software_interface" in tags and relation_type == "INTERFACES_WITH":
            return self.registry.pattern("INTERFACE_BRIDGE")
        return self.registry.choose_animation_pattern(
            relation_type,
            requested=requested,
            context_tags=tags,
        )
