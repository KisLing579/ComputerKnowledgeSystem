from __future__ import annotations

from dataclasses import asdict

from kg.query import GraphNeighbor, NodeMatch

from .models import (
    ExplanationBranch,
    ExplanationPlan,
    KnowledgePath,
    QuestionAnalysis,
    RankedExplanationPath,
)


class ExplanationStructurer:
    """Turn ranked KG material into a scene-planner-friendly structure.

    This is the layer that prevents every explanation from being forced into a
    single path. The first special structure implemented is composition:

        CPU
        ├── Datapath
        └── Control Unit

    It also supports hybrid structures: a main explanatory spine plus side
    branches for definitions/components. Interface-role questions are the first
    concrete hybrid case.
    """

    def linear_plan(
        self,
        *,
        question: str,
        analysis: QuestionAnalysis,
        ranked: RankedExplanationPath,
    ) -> ExplanationPlan:
        path = ranked.path
        knowledge_path = KnowledgePath(
            path_type="explanation",
            goal=f"explain:{analysis.intent.value}",
            question=question,
            intent=analysis.intent.value,
            node_ids=path.node_ids,
            node_names=path.node_names,
            relations=path.relationships,
            explanation_score=ranked.explanation_score,
            metadata={
                "graph_score": ranked.graph_score,
                "score_breakdown": asdict(ranked.breakdown),
            },
        )
        return ExplanationPlan(
            plan_type="explanation",
            structure_type="linear",
            goal=knowledge_path.goal,
            question=question,
            intent=analysis.intent.value,
            root_id=path.node_ids[0] if path.node_ids else None,
            root_name=path.node_names[0] if path.node_names else None,
            main_path=knowledge_path,
            branches=(),
            explanation_score=ranked.explanation_score,
            metadata={"source": "ranked_path"},
        )

    def composition_plan(
        self,
        *,
        question: str,
        analysis: QuestionAnalysis,
        root: NodeMatch,
        components: list[GraphNeighbor],
    ) -> ExplanationPlan:
        branches: list[ExplanationBranch] = []
        branch_scores: list[float] = []

        for index, component in enumerate(components, 1):
            rel = dict(component.relationship)
            confidence = float(rel.get("confidence", 1.0) or 1.0)
            has_anim = bool(rel.get("default_animation_pattern"))
            score = min(100.0, 85.0 * confidence + (15.0 if has_anim else 0.0))
            branch_scores.append(score)

            branches.append(
                ExplanationBranch(
                    branch_id=f"branch_{index:02d}",
                    root_id=root.id,
                    root_name=root.name,
                    node_ids=(root.id, component.id),
                    node_names=(root.name, component.name),
                    relations=(rel,),
                    purpose="component",
                    score=round(score, 2),
                )
            )

        # A composition plan is high-confidence only if at least one explicit
        # component relation was found. Keep the score transparent rather than
        # inventing missing domain knowledge.
        if branch_scores:
            mean_branch = sum(branch_scores) / len(branch_scores)
            explanation_score = min(100.0, mean_branch)
        else:
            explanation_score = 0.0

        return ExplanationPlan(
            plan_type="explanation",
            structure_type="branching",
            goal="explain:composition",
            question=question,
            intent=analysis.intent.value,
            root_id=root.id,
            root_name=root.name,
            main_path=None,
            branches=tuple(branches),
            explanation_score=round(explanation_score, 2),
            metadata={
                "branch_count": len(branches),
                "relation_semantics": "root -> direct components",
                "note": "Stored PART_OF edges may point component->root; traversal is root->component for narration.",
            },
        )

    def interface_hybrid_plan(
        self,
        *,
        question: str,
        analysis: QuestionAnalysis,
        root: NodeMatch,
        interface_neighbors: list[GraphNeighbor],
        components: list[GraphNeighbor],
    ) -> ExplanationPlan:
        """Build a main interface spine plus supporting component branches.

        Canonical shape for the current KG is:

            System Software -> ISA -> Hardware
                              |\
                              | +-> Instruction Set
                              +---> Register

        The method stays generic: it requires actual INTERFACES_WITH evidence
        from the KG and never invents missing software/hardware neighbors.
        """
        if not interface_neighbors:
            return ExplanationPlan(
                plan_type="explanation",
                structure_type="hybrid",
                goal="explain:interface_role",
                question=question,
                intent=analysis.intent.value,
                root_id=root.id,
                root_name=root.name,
                main_path=None,
                branches=(),
                explanation_score=0.0,
                metadata={
                    "note": "No INTERFACES_WITH neighbors found; no model knowledge was added.",
                    "interface_neighbor_count": 0,
                    "branch_count": 0,
                },
            )

        left, right, extras = self._select_interface_sides(interface_neighbors)

        # Build the main explanatory spine. Prefer two-sided A -> root -> B;
        # if the KG has only one side, keep a one-edge spine rather than inventing
        # a missing counterpart.
        spine_nodes: list[GraphNeighbor | NodeMatch] = []
        spine_rels: list[dict] = []

        if left is not None and right is not None:
            spine_nodes = [left, root, right]
            left_rel = dict(left.relationship)
            left_rel["traversal_from"] = left.id
            left_rel["traversal_to"] = root.id
            right_rel = dict(right.relationship)
            right_rel["traversal_from"] = root.id
            right_rel["traversal_to"] = right.id
            spine_rels = [left_rel, right_rel]
        else:
            only = left or right or interface_neighbors[0]
            spine_nodes = [root, only]
            rel = dict(only.relationship)
            rel["traversal_from"] = root.id
            rel["traversal_to"] = only.id
            spine_rels = [rel]

        spine_conf = [float(r.get("confidence", 1.0) or 1.0) for r in spine_rels]
        mean_spine_conf = sum(spine_conf) / len(spine_conf) if spine_conf else 0.0
        spine_anim = (
            sum(1 for r in spine_rels if r.get("default_animation_pattern"))
            / max(1, len(spine_rels))
        )
        spine_score = min(100.0, 80.0 * mean_spine_conf + 20.0 * spine_anim)

        main_path = KnowledgePath(
            path_type="explanation",
            goal="explain:interface_role",
            question=question,
            intent=analysis.intent.value,
            node_ids=tuple(n.id for n in spine_nodes),
            node_names=tuple(n.name for n in spine_nodes),
            relations=tuple(spine_rels),
            explanation_score=round(spine_score, 2),
            metadata={
                "role": "interface_spine",
                "root_id": root.id,
                "relation_type": "INTERFACES_WITH",
            },
        )

        branches: list[ExplanationBranch] = []
        branch_scores: list[float] = []
        used_ids = set(main_path.node_ids)

        # Components explain what the interface exposes/contains, but remain
        # subordinate to the main software-interface-hardware spine.
        for component in components:
            if component.id in used_ids:
                continue
            rel = dict(component.relationship)
            confidence = float(rel.get("confidence", 1.0) or 1.0)
            has_anim = bool(rel.get("default_animation_pattern"))
            score = min(100.0, 85.0 * confidence + (15.0 if has_anim else 0.0))
            branch_scores.append(score)
            branches.append(
                ExplanationBranch(
                    branch_id=f"component_{len(branches)+1:02d}",
                    root_id=root.id,
                    root_name=root.name,
                    node_ids=(root.id, component.id),
                    node_names=(root.name, component.name),
                    relations=(rel,),
                    purpose="interface_component",
                    score=round(score, 2),
                )
            )

        # Extra INTERFACES_WITH neighbors are evidence too. Keep them as context
        # branches instead of forcing a crowded multi-node main path.
        for neighbor in extras:
            if neighbor.id in used_ids:
                continue
            rel = dict(neighbor.relationship)
            confidence = float(rel.get("confidence", 1.0) or 1.0)
            has_anim = bool(rel.get("default_animation_pattern"))
            score = min(100.0, 85.0 * confidence + (15.0 if has_anim else 0.0))
            branch_scores.append(score)
            branches.append(
                ExplanationBranch(
                    branch_id=f"context_{len(branches)+1:02d}",
                    root_id=root.id,
                    root_name=root.name,
                    node_ids=(root.id, neighbor.id),
                    node_names=(root.name, neighbor.name),
                    relations=(rel,),
                    purpose="interface_context",
                    score=round(score, 2),
                )
            )

        support_score = sum(branch_scores) / len(branch_scores) if branch_scores else spine_score
        explanation_score = min(100.0, 0.72 * spine_score + 0.28 * support_score)

        return ExplanationPlan(
            plan_type="explanation",
            structure_type="hybrid",
            goal="explain:interface_role",
            question=question,
            intent=analysis.intent.value,
            root_id=root.id,
            root_name=root.name,
            main_path=main_path,
            branches=tuple(branches),
            explanation_score=round(explanation_score, 2),
            metadata={
                "interface_neighbor_count": len(interface_neighbors),
                "branch_count": len(branches),
                "main_spine": "context -> interface -> context when two KG sides exist",
                "note": "Only KG-backed INTERFACES_WITH/PART_OF evidence is used.",
            },
        )

    @staticmethod
    def _select_interface_sides(
        neighbors: list[GraphNeighbor],
    ) -> tuple[GraphNeighbor | None, GraphNeighbor | None, list[GraphNeighbor]]:
        """Prefer software on the left and hardware on the right when present."""
        def text(n: GraphNeighbor) -> str:
            return f"{n.name} {n.name_en} {n.definition}".lower()

        software = [n for n in neighbors if "软件" in text(n) or "software" in text(n)]
        hardware = [n for n in neighbors if "硬件" in text(n) or "hardware" in text(n)]

        left = software[0] if software else None
        right = hardware[0] if hardware else None
        used = {x.id for x in (left, right) if x is not None}

        remaining = [n for n in neighbors if n.id not in used]
        if left is None and remaining:
            left = remaining.pop(0)
            used.add(left.id)
        if right is None and remaining:
            right = remaining.pop(0)
            used.add(right.id)

        extras = [n for n in neighbors if n.id not in used]
        return left, right, extras


    # ------------------------------------------------------------------
    # v0.4 recursive-segment builders
    # ------------------------------------------------------------------

    @staticmethod
    def sequence_segment(
        *,
        segment_id: str,
        goal_id: str,
        title: str,
        intent: str,
        children: list,
    ):
        from .models import ExplanationSegment

        scores = [float(c.score) for c in children if c is not None]
        return ExplanationSegment(
            segment_id=segment_id,
            segment_type="sequence",
            goal_id=goal_id,
            title=title,
            intent=intent,
            children=tuple(c for c in children if c is not None),
            score=round(sum(scores) / len(scores), 2) if scores else 0.0,
            metadata={"ordered": True, "child_count": len(children)},
        )

    @staticmethod
    def linear_segment(
        *,
        segment_id: str,
        goal_id: str,
        question: str,
        analysis: QuestionAnalysis,
        ranked: RankedExplanationPath,
    ):
        from .models import ExplanationSegment

        path = ranked.path
        return ExplanationSegment(
            segment_id=segment_id,
            segment_type="linear",
            goal_id=goal_id,
            title=question,
            intent=analysis.intent.value,
            root_id=path.node_ids[0] if path.node_ids else None,
            root_name=path.node_names[0] if path.node_names else None,
            node_ids=path.node_ids,
            node_names=path.node_names,
            relations=path.relationships,
            score=ranked.explanation_score,
            metadata={
                "graph_score": ranked.graph_score,
                "source": "ranked_path",
            },
        )

    @staticmethod
    def branch_segment_from_neighbors(
        *,
        segment_id: str,
        goal_id: str,
        title: str,
        intent: str,
        root: NodeMatch,
        neighbors: list[GraphNeighbor],
        purpose: str,
    ):
        from .models import ExplanationSegment

        children = []
        branch_scores: list[float] = []
        for i, neighbor in enumerate(neighbors, 1):
            rel = dict(neighbor.relationship)
            rel["traversal_from"] = root.id
            rel["traversal_to"] = neighbor.id
            rel["narrative_relation_type"] = ExplanationStructurer._narrative_relation_type(
                rel, root.id, neighbor.id
            )
            conf = float(rel.get("confidence", 1.0) or 1.0)
            has_anim = bool(rel.get("default_animation_pattern"))
            score = min(100.0, 85.0 * conf + (15.0 if has_anim else 0.0))
            branch_scores.append(score)
            children.append(
                ExplanationSegment(
                    segment_id=f"{segment_id}.{i}",
                    segment_type="fact",
                    goal_id=goal_id,
                    title=f"{root.name} → {neighbor.name}",
                    intent=intent,
                    root_id=neighbor.id,
                    root_name=neighbor.name,
                    node_ids=(root.id, neighbor.id),
                    node_names=(root.name, neighbor.name),
                    relations=(rel,),
                    score=round(score, 2),
                    metadata={"purpose": purpose},
                )
            )

        return ExplanationSegment(
            segment_id=segment_id,
            segment_type="branch",
            goal_id=goal_id,
            title=title,
            intent=intent,
            root_id=root.id,
            root_name=root.name,
            node_ids=(root.id,),
            node_names=(root.name,),
            children=tuple(children),
            score=round(sum(branch_scores) / len(branch_scores), 2) if branch_scores else 0.0,
            metadata={"purpose": purpose, "branch_count": len(children)},
        )

    @staticmethod
    def interface_segment(
        *,
        segment_id: str,
        goal_id: str,
        title: str,
        analysis: QuestionAnalysis,
        root: NodeMatch,
        interface_neighbors: list[GraphNeighbor],
        components: list[GraphNeighbor],
    ):
        from .models import ExplanationSegment

        from .scene_pattern_matcher import ScenePatternMatcher
        from kg.query import relationship_key
        catalog = {root.id: {"name": root.name, "name_en": root.name_en,
                            "semantic_type": root.semantic_type}}
        selected = {}
        for neighbor in (*interface_neighbors, *components):
            catalog[neighbor.id] = {"name": neighbor.name, "name_en": neighbor.name_en,
                                    "semantic_type": neighbor.semantic_type}
            rel = dict(neighbor.relationship)
            rel.update(traversal_from=root.id, traversal_to=neighbor.id)
            selected.setdefault((neighbor.id, relationship_key(rel)), rel)
        rels = tuple(dict(r, id=r.get('id') or f'{segment_id}.R{i:02}')
                     for i, r in enumerate(selected.values(), 1))
        grouped = ExplanationSegment(segment_id, 'evidence_group', goal_id, title,
            analysis.intent.value, root.id, root.name, tuple(catalog),
            tuple(n['name'] for n in catalog.values()), rels,
            metadata={'evidence_strategy': 'interface', 'evidence_relation_ids': [r['id'] for r in rels]})
        semantic = ScenePatternMatcher().match(grouped, catalog, rels)
        if semantic and len(catalog) <= 8:
            from dataclasses import replace
            return replace(grouped, semantic_scene_plan=semantic, score=100.0)

        left, right, extras = ExplanationStructurer._select_interface_sides(interface_neighbors)
        child_segments: list[ExplanationSegment] = []
        spine_score = 0.0

        if left is not None and right is not None:
            lrel = dict(left.relationship)
            lrel["traversal_from"] = left.id
            lrel["traversal_to"] = root.id
            lrel["narrative_relation_type"] = ExplanationStructurer._narrative_relation_type(
                lrel, left.id, root.id
            )
            rrel = dict(right.relationship)
            rrel["traversal_from"] = root.id
            rrel["traversal_to"] = right.id
            rrel["narrative_relation_type"] = ExplanationStructurer._narrative_relation_type(
                rrel, root.id, right.id
            )
            conf = (
                float(lrel.get("confidence", 1.0) or 1.0)
                + float(rrel.get("confidence", 1.0) or 1.0)
            ) / 2.0
            spine_score = min(100.0, 80.0 * conf + 20.0)
            child_segments.append(
                ExplanationSegment(
                    segment_id=f"{segment_id}.spine",
                    segment_type="linear",
                    goal_id=goal_id,
                    title=f"{left.name} → {root.name} → {right.name}",
                    intent=analysis.intent.value,
                    root_id=root.id,
                    root_name=root.name,
                    node_ids=(left.id, root.id, right.id),
                    node_names=(left.name, root.name, right.name),
                    relations=(lrel, rrel),
                    score=round(spine_score, 2),
                    metadata={"purpose": "interface_spine"},
                )
            )
        elif interface_neighbors:
            only = left or right or interface_neighbors[0]
            rel = dict(only.relationship)
            rel["traversal_from"] = root.id
            rel["traversal_to"] = only.id
            rel["narrative_relation_type"] = ExplanationStructurer._narrative_relation_type(
                rel, root.id, only.id
            )
            spine_score = min(100.0, 85.0 * float(rel.get("confidence", 1.0) or 1.0) + 15.0)
            child_segments.append(
                ExplanationSegment(
                    segment_id=f"{segment_id}.spine",
                    segment_type="linear",
                    goal_id=goal_id,
                    title=f"{root.name} → {only.name}",
                    intent=analysis.intent.value,
                    root_id=root.id,
                    root_name=root.name,
                    node_ids=(root.id, only.id),
                    node_names=(root.name, only.name),
                    relations=(rel,),
                    score=round(spine_score, 2),
                    metadata={"purpose": "interface_spine"},
                )
            )

        support = ExplanationStructurer.branch_segment_from_neighbors(
            segment_id=f"{segment_id}.support",
            goal_id=goal_id,
            title=f"{root.name} 的组成/支撑概念",
            intent=analysis.intent.value,
            root=root,
            neighbors=[n for n in components if n.id not in {x.id for x in (left, right) if x}],
            purpose="interface_component",
        )
        if support.children:
            child_segments.append(support)

        if extras:
            extra_seg = ExplanationStructurer.branch_segment_from_neighbors(
                segment_id=f"{segment_id}.context",
                goal_id=goal_id,
                title=f"{root.name} 的额外接口上下文",
                intent=analysis.intent.value,
                root=root,
                neighbors=extras,
                purpose="interface_context",
            )
            if extra_seg.children:
                child_segments.append(extra_seg)

        scores = [s.score for s in child_segments]
        return ExplanationSegment(
            segment_id=segment_id,
            segment_type="hybrid",
            goal_id=goal_id,
            title=title,
            intent=analysis.intent.value,
            root_id=root.id,
            root_name=root.name,
            node_ids=(root.id,),
            node_names=(root.name,),
            children=tuple(child_segments),
            score=round(sum(scores) / len(scores), 2) if scores else 0.0,
            metadata={
                "interface_neighbor_count": len(interface_neighbors),
                "component_count": len(components),
            },
        )

    @staticmethod
    def relation_tree_segment(
        *,
        segment_id: str,
        goal_id: str,
        title: str,
        intent: str,
        root: NodeMatch | GraphNeighbor,
        node_names: dict[str, str],
        relations: list,
        max_depth: int = 4,
    ):
        """Build a recursive tree from a bounded set of direct KG relations."""
        from .models import ExplanationSegment

        adjacency: dict[str, list[tuple[str, object]]] = {}
        for edge in relations:
            adjacency.setdefault(edge.source_id, []).append((edge.target_id, edge))
            adjacency.setdefault(edge.target_id, []).append((edge.source_id, edge))

        visited: set[str] = set()
        counter = [0]

        def build(node_id: str, parent_id: str | None, depth: int, ancestry: tuple[str, ...]):
            counter[0] += 1
            sid = f"{segment_id}.{counter[0]}"
            name = node_names.get(node_id, node_id)
            if node_id in ancestry:
                return ExplanationSegment(
                    segment_id=sid,
                    segment_type="reference",
                    goal_id=goal_id,
                    title=f"再次引用 {name}",
                    intent=intent,
                    root_id=node_id,
                    root_name=name,
                    node_ids=(node_id,),
                    node_names=(name,),
                    referenced_node_ids=(node_id,),
                    score=100.0,
                    metadata={"cycle_guard": True},
                )

            visited.add(node_id)
            children: list[ExplanationSegment] = []
            if depth < max_depth:
                for other_id, edge in adjacency.get(node_id, []):
                    if other_id == parent_id:
                        continue
                    other_name = node_names.get(other_id, other_id)
                    rel = dict(edge.relationship)
                    rel["traversal_from"] = node_id
                    rel["traversal_to"] = other_id
                    rel["narrative_relation_type"] = ExplanationStructurer._narrative_relation_type(
                        rel, node_id, other_id
                    )
                    conf = float(rel.get("confidence", 1.0) or 1.0)
                    if other_id in visited:
                        counter[0] += 1
                        children.append(
                            ExplanationSegment(
                                segment_id=f"{segment_id}.{counter[0]}",
                                segment_type="reference",
                                goal_id=goal_id,
                                title=f"{name} → {other_name}",
                                intent=intent,
                                root_id=other_id,
                                root_name=other_name,
                                node_ids=(node_id, other_id),
                                node_names=(name, other_name),
                                relations=(rel,),
                                referenced_node_ids=(other_id,),
                                score=round(100.0 * conf, 2),
                                metadata={"cross_reference": True},
                            )
                        )
                        continue
                    child = build(other_id, node_id, depth + 1, ancestry + (node_id,))
                    # Attach the parent->child relation to the child segment.
                    child = ExplanationSegment(
                        segment_id=child.segment_id,
                        segment_type=child.segment_type,
                        goal_id=child.goal_id,
                        title=child.title,
                        intent=child.intent,
                        root_id=child.root_id,
                        root_name=child.root_name,
                        node_ids=(node_id, other_id) if child.segment_type != "reference" else child.node_ids,
                        node_names=(name, other_name) if child.segment_type != "reference" else child.node_names,
                        relations=(rel,) if child.segment_type != "reference" else child.relations,
                        children=child.children,
                        score=round(100.0 * conf, 2) if child.score == 0 else child.score,
                        referenced_node_ids=child.referenced_node_ids,
                        metadata={**child.metadata, "incoming_relation": rel.get("narrative_relation_type", rel.get("type", ""))},
                    )
                    children.append(child)

            segment_type = "branch" if len(children) > 1 else ("linear" if children else "fact")
            return ExplanationSegment(
                segment_id=sid,
                segment_type=segment_type,
                goal_id=goal_id,
                title=name,
                intent=intent,
                root_id=node_id,
                root_name=name,
                node_ids=(node_id,),
                node_names=(name,),
                children=tuple(children),
                score=round(sum(c.score for c in children) / len(children), 2) if children else 100.0,
                metadata={"relation_tree": True, "depth": depth},
            )

        return build(root.id, None, 0, ())

    @staticmethod
    def mediated_role_segment(
        *,
        segment_id: str,
        goal_id: str,
        title: str,
        intent: str,
        root: NodeMatch,
        mediated_relations: list,
        direct_neighbors: list[GraphNeighbor],
    ):
        from .models import ExplanationSegment

        children: list[ExplanationSegment] = []
        for i, edge in enumerate(mediated_relations, 1):
            rel = dict(edge.relationship)
            rel["traversal_from"] = edge.source_id
            rel["traversal_to"] = edge.target_id
            rel["narrative_relation_type"] = rel.get("type", "")
            children.append(
                ExplanationSegment(
                    segment_id=f"{segment_id}.mediated.{i}",
                    segment_type="linear",
                    goal_id=goal_id,
                    title=f"{root.name} 参与：{edge.source_name} → {edge.target_name}",
                    intent=intent,
                    root_id=root.id,
                    root_name=root.name,
                    node_ids=(edge.source_id, edge.target_id),
                    node_names=(edge.source_name, edge.target_name),
                    relations=(rel,),
                    score=round(100.0 * float(rel.get("confidence", 1.0) or 1.0), 2),
                    metadata={"mediator_id": root.id, "mediator_name": root.name},
                )
            )

        direct = ExplanationStructurer.branch_segment_from_neighbors(
            segment_id=f"{segment_id}.direct",
            goal_id=goal_id,
            title=f"{root.name} 的直接功能关系",
            intent=intent,
            root=root,
            neighbors=direct_neighbors,
            purpose="role_function",
        )
        if direct.children:
            children.append(direct)

        return ExplanationSegment(
            segment_id=segment_id,
            segment_type="hybrid" if len(children) > 1 else (children[0].segment_type if children else "empty"),
            goal_id=goal_id,
            title=title,
            intent=intent,
            root_id=root.id,
            root_name=root.name,
            node_ids=(root.id,),
            node_names=(root.name,),
            children=tuple(children),
            score=round(sum(c.score for c in children) / len(children), 2) if children else 0.0,
            metadata={"mediated_count": len(mediated_relations), "direct_count": len(direct_neighbors)},
        )

    @staticmethod
    def definition_segment(
        *,
        segment_id: str,
        goal_id: str,
        title: str,
        intent: str,
        root: NodeMatch,
        definition_text: str,
        neighbors: list[GraphNeighbor],
        score: float,
    ):
        """Build a definition-first explanation with only 0-1 hop support."""
        from .models import ExplanationSegment

        children: list[ExplanationSegment] = []
        if definition_text:
            children.append(
                ExplanationSegment(
                    segment_id=f"{segment_id}.core",
                    segment_type="fact",
                    goal_id=goal_id,
                    title=f"核心定义：{definition_text}",
                    intent=intent,
                    root_id=root.id,
                    root_name=root.name,
                    node_ids=(root.id,),
                    node_names=(root.name,),
                    score=100.0,
                    metadata={"purpose": "core_definition", "text": definition_text},
                )
            )

        groups: dict[str, list[GraphNeighbor]] = {"identity": [], "components": [], "role": [], "other": []}
        for n in neighbors:
            rel = dict(n.relationship)
            rel_type = str(rel.get("type", ""))
            stored_start = str(rel.get("stored_start_id", ""))
            stored_end = str(rel.get("stored_end_id", ""))
            if rel_type == "IS_A" or (rel_type == "PART_OF" and stored_start == root.id):
                groups["identity"].append(n)
            elif (rel_type == "PART_OF" and stored_end == root.id) or (rel_type == "CONTAINS" and stored_start == root.id):
                groups["components"].append(n)
            elif rel_type in {"INTERFACES_WITH", "IMPLEMENTS", "DESCRIBES", "CONTRASTS_WITH"}:
                groups["role"].append(n)
            else:
                groups["other"].append(n)

        labels = {
            "identity": f"{root.name} 的类别/位置",
            "components": f"{root.name} 的组成/规定内容",
            "role": f"{root.name} 的关键角色/接口",
            "other": f"{root.name} 的补充定义关系",
        }
        for group_name in ("identity", "components", "role", "other"):
            items = groups[group_name]
            if not items:
                continue
            group = ExplanationStructurer.branch_segment_from_neighbors(
                segment_id=f"{segment_id}.{group_name}",
                goal_id=goal_id,
                title=labels[group_name],
                intent=intent,
                root=root,
                neighbors=items,
                purpose=f"definition_{group_name}",
            )
            # A one-item support group is better presented as the fact itself.
            if len(group.children) == 1:
                children.append(group.children[0])
            else:
                children.append(group)

        segment_type = "definition"
        return ExplanationSegment(
            segment_id=segment_id,
            segment_type=segment_type,
            goal_id=goal_id,
            title=root.name,
            intent=intent,
            root_id=root.id,
            root_name=root.name,
            node_ids=(root.id,),
            node_names=(root.name,),
            children=tuple(children),
            score=round(score, 2),
            metadata={
                "purpose": "definition",
                "core_statement": definition_text,
                "support_count": len(neighbors),
                "max_support_hops": 1,
            },
        )

    @staticmethod
    def comparison_segment(
        *,
        segment_id: str,
        goal_id: str,
        title: str,
        intent: str,
        root: NodeMatch,
        right_id: str,
        right_name: str,
        direct_relations: list,
        left_neighbors: list[GraphNeighbor],
        right_neighbors: list[GraphNeighbor],
        score: float,
    ):
        """Two-sided comparison plan; both sides stay parallel rather than forming a path."""
        from .models import ExplanationSegment

        children: list[ExplanationSegment] = []
        for i, edge in enumerate(direct_relations, 1):
            rel = dict(edge.relationship)
            rel["traversal_from"] = edge.source_id
            rel["traversal_to"] = edge.target_id
            rel["narrative_relation_type"] = ExplanationStructurer._narrative_relation_type(
                rel, edge.source_id, edge.target_id
            )
            children.append(
                ExplanationSegment(
                    segment_id=f"{segment_id}.contrast.{i}",
                    segment_type="fact",
                    goal_id=goal_id,
                    title=f"{edge.source_name} → {edge.target_name}",
                    intent=intent,
                    root_id=edge.source_id,
                    root_name=edge.source_name,
                    node_ids=(edge.source_id, edge.target_id),
                    node_names=(edge.source_name, edge.target_name),
                    relations=(rel,),
                    score=round(100.0 * float(rel.get("confidence", 1.0) or 1.0), 2),
                    metadata={"purpose": "comparison_direct"},
                )
            )

        def side_segment(sid: str, side_id: str, side_name: str, neighbors: list[GraphNeighbor]):
            # Build manually because the right side may not have a NodeMatch instance.
            facts: list[ExplanationSegment] = []
            for i, n in enumerate(neighbors, 1):
                if n.id in {root.id, right_id}:
                    continue
                rel = dict(n.relationship)
                rel["traversal_from"] = side_id
                rel["traversal_to"] = n.id
                rel["narrative_relation_type"] = ExplanationStructurer._narrative_relation_type(rel, side_id, n.id)
                facts.append(
                    ExplanationSegment(
                        segment_id=f"{sid}.{i}",
                        segment_type="fact",
                        goal_id=goal_id,
                        title=f"{side_name} → {n.name}",
                        intent=intent,
                        root_id=n.id,
                        root_name=n.name,
                        node_ids=(side_id, n.id),
                        node_names=(side_name, n.name),
                        relations=(rel,),
                        score=round(100.0 * float(rel.get("confidence", 1.0) or 1.0), 2),
                        metadata={"purpose": "comparison_side"},
                    )
                )
            return ExplanationSegment(
                segment_id=sid,
                segment_type="branch" if len(facts) > 1 else ("linear" if facts else "fact"),
                goal_id=goal_id,
                title=side_name,
                intent=intent,
                root_id=side_id,
                root_name=side_name,
                node_ids=(side_id,),
                node_names=(side_name,),
                children=tuple(facts),
                score=round(sum(f.score for f in facts) / len(facts), 2) if facts else 100.0,
                metadata={"purpose": "comparison_side"},
            )

        children.append(side_segment(f"{segment_id}.left", root.id, root.name, left_neighbors))
        children.append(side_segment(f"{segment_id}.right", right_id, right_name, right_neighbors))
        return ExplanationSegment(
            segment_id=segment_id,
            segment_type="comparison",
            goal_id=goal_id,
            title=title,
            intent=intent,
            root_id=root.id,
            root_name=root.name,
            node_ids=(root.id, right_id),
            node_names=(root.name, right_name),
            children=tuple(children),
            score=round(score, 2),
            metadata={"purpose": "comparison", "left_id": root.id, "right_id": right_id},
        )

    @staticmethod
    def segment_from_evidence(*, segment_id: str, goal, evidence):
        """Turn one atomic evidence bundle into a recursive ExplanationSegment."""
        et = evidence.evidence_type
        intent = goal.analysis.intent.value
        if et == "definition" and evidence.root is not None:
            return ExplanationStructurer.definition_segment(
                segment_id=segment_id,
                goal_id=goal.goal_id,
                title=goal.text,
                intent=intent,
                root=evidence.root,
                definition_text=evidence.definition_text,
                neighbors=list(evidence.neighbors),
                score=evidence.score,
            )
        if et == "composition" and evidence.root is not None and evidence.components:
            return ExplanationStructurer.branch_segment_from_neighbors(
                segment_id=segment_id,
                goal_id=goal.goal_id,
                title=goal.text,
                intent=intent,
                root=evidence.root,
                neighbors=list(evidence.components),
                purpose="composition",
            )
        if et == "interface" and evidence.root is not None:
            return ExplanationStructurer.interface_segment(
                segment_id=segment_id,
                goal_id=goal.goal_id,
                title=goal.text,
                analysis=goal.analysis,
                root=evidence.root,
                interface_neighbors=list(evidence.neighbors),
                components=list(evidence.components),
            )
        if et == "role_function" and evidence.root is not None:
            return ExplanationStructurer.mediated_role_segment(
                segment_id=segment_id,
                goal_id=goal.goal_id,
                title=goal.text,
                intent=intent,
                root=evidence.root,
                mediated_relations=list(evidence.mediated_relations),
                direct_neighbors=list(evidence.neighbors),
            )
        if et == "relation_structure" and evidence.root is not None and evidence.relations:
            node_names = {evidence.root.id: evidence.root.name}
            for edge in evidence.relations:
                node_names[edge.source_id] = edge.source_name
                node_names[edge.target_id] = edge.target_name
            return ExplanationStructurer.relation_tree_segment(
                segment_id=segment_id,
                goal_id=goal.goal_id,
                title=goal.text,
                intent=intent,
                root=evidence.root,
                node_names=node_names,
                relations=list(evidence.relations),
                max_depth=4,
            )
        if et == "comparison" and evidence.root is not None:
            return ExplanationStructurer.comparison_segment(
                segment_id=segment_id,
                goal_id=goal.goal_id,
                title=goal.text,
                intent=intent,
                root=evidence.root,
                right_id=str(evidence.metadata.get("right_id", "")),
                right_name=str(evidence.metadata.get("right_name", evidence.metadata.get("right_id", ""))),
                direct_relations=list(evidence.relations),
                left_neighbors=list(evidence.left_neighbors),
                right_neighbors=list(evidence.right_neighbors),
                score=evidence.score,
            )
        if et == "path" and evidence.selected_path is not None:
            return ExplanationStructurer.linear_segment(
                segment_id=segment_id,
                goal_id=goal.goal_id,
                question=goal.text,
                analysis=goal.analysis,
                ranked=evidence.selected_path,
            )
        return ExplanationStructurer.empty_segment(
            segment_id=segment_id,
            goal_id=goal.goal_id,
            title=goal.text,
            intent=intent,
            note=str(evidence.metadata.get("note", f"no usable {et} evidence")),
        )

    @staticmethod
    def empty_segment(*, segment_id: str, goal_id: str, title: str, intent: str, note: str):
        from .models import ExplanationSegment

        return ExplanationSegment(
            segment_id=segment_id,
            segment_type="empty",
            goal_id=goal_id,
            title=title,
            intent=intent,
            score=0.0,
            metadata={"note": note},
        )

    @staticmethod
    def _narrative_relation_type(rel: dict, traversal_from: str, traversal_to: str) -> str:
        stored_start = str(rel.get("stored_start_id", ""))
        stored_end = str(rel.get("stored_end_id", ""))
        rel_type = str(rel.get("type", ""))
        if stored_start == traversal_from and stored_end == traversal_to:
            return rel_type
        inverse = {
            "PART_OF": "CONTAINS",
            "CONTAINS": "PART_OF",
            "IS_A": "HAS_SUBTYPE",
            "CONTROLS": "CONTROLLED_BY",
            "MANAGES": "MANAGED_BY",
            "STORES": "STORED_IN",
            "EXECUTES": "EXECUTED_BY",
            "USES": "USED_BY",
            "IMPLEMENTS": "IMPLEMENTED_BY",
            "TRANSFORMS_TO": "TRANSFORMED_FROM",
            "AFFECTS": "AFFECTED_BY",
            "CONSTRAINS": "CONSTRAINED_BY",
            "EXPLOITS": "EXPLOITED_BY",
            "DESCRIBES": "DESCRIBED_BY",
            "TRIGGERS": "TRIGGERED_BY",
            "INTERFACES_WITH": "INTERFACES_WITH",
            "CONTRASTS_WITH": "CONTRASTS_WITH",
            "CONNECTS": "CONNECTED_BY",
        }
        return inverse.get(rel_type, f"INVERSE_{rel_type}" if rel_type else "RELATED_TO")
