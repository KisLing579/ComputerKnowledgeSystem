from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace

from kg.config import Settings, load_settings
from kg.neo4j_client import Neo4jClient
from kg.query import path_key, ExplanationPath, GraphNeighbor, KGQueryService, NodeMatch, _format_path

from .evidence import EvidenceContext
from .evidence_router import EvidenceStrategyRouter
from .models import (
    ExplanationGoal,
    ExplanationIntent,
    ExplanationPlan,
    ExplanationResult,
    ExplanationSegment,
    KnowledgePath,
    RankedExplanationPath,
)
from .path_ranker import ExplanationPathRanker
from .question_analyzer import QuestionAnalyzer
from .question_decomposer import QuestionDecomposer
from .structurer import ExplanationStructurer
from .validator import ExplanationPlanValidator


class ExplanationPlanner:
    """Recursive, goal-driven explanation planner (v0.4).

    Important design rule:
        recursion is over ExplanationGoal -> subgoals,
        NOT over arbitrary KG neighbor traversal.

    Each atomic goal chooses a local evidence strategy:
      - path search for transformation/process/source->target goals;
      - neighborhood query for composition;
      - relation-set query for multi-entity structure;
      - interface neighborhood for interface-role goals;
      - direct/mediated relations for role/function goals.

    The resulting recursive ExplanationSegment tree is then validated before it
    is handed to the future Visual Binder / Scene Planner.
    """

    def __init__(
        self,
        query_service: KGQueryService,
        settings: Settings,
        analyzer: QuestionAnalyzer | None = None,
        ranker: ExplanationPathRanker | None = None,
        structurer: ExplanationStructurer | None = None,
        decomposer: QuestionDecomposer | None = None,
        validator: ExplanationPlanValidator | None = None,
        evidence_router: EvidenceStrategyRouter | None = None,
    ):
        self.query_service = query_service
        self.settings = settings
        self.analyzer = analyzer or QuestionAnalyzer()
        self.ranker = ranker or ExplanationPathRanker()
        self.structurer = structurer or ExplanationStructurer()
        self.decomposer = decomposer or QuestionDecomposer(
            self.analyzer,
            max_depth=settings.explanation.max_goal_depth,
        )
        self.evidence_router = evidence_router or EvidenceStrategyRouter()
        self.validator = validator or ExplanationPlanValidator(
            max_depth=settings.explanation.max_plan_depth,
            max_segments=settings.explanation.max_segments,
            max_children=settings.explanation.max_children,
        )

    def explain(self, question: str, *, top_n: int = 10) -> ExplanationResult:
        # Use a wider match set than the original path-only planner. Compound
        # questions can legitimately mention more than 8 concepts.
        match_limit = max(20, self.settings.query.top_k_nodes)
        root_matches = self.query_service.find_related_nodes(question, limit=match_limit)

        def match_provider(text: str) -> list[NodeMatch]:
            return self.query_service.find_related_nodes(text, limit=match_limit)

        root_goal = self.decomposer.decompose(question, match_provider)
        all_ranked: list[RankedExplanationPath] = []
        root_segment = self._plan_goal(
            root_goal,
            match_provider=match_provider,
            ancestry_signatures=(),
            all_ranked=all_ranked,
        )

        selected_path = self._first_linear_knowledge_path(root_segment, question)
        plan = ExplanationPlan(
            plan_type="explanation",
            structure_type=root_segment.segment_type,
            goal="explain:recursive",
            question=question,
            intent=root_goal.analysis.intent.value,
            root_id=root_segment.root_id,
            root_name=root_segment.root_name,
            root_segment=root_segment,
            main_path=selected_path if root_segment.segment_type == "linear" else None,
            branches=(),
            explanation_score=root_segment.score,
            metadata={
                "representation": "recursive_explanation_tree",
                "goal_count": self._count_goals(root_goal),
                "recursion_model": "goal_decomposition_not_kg_recursion",
            },
        )
        validation = self.validator.validate(plan)
        plan = replace(plan, validation=validation)

        # Aggregate path evidence only for diagnostics. The recursive segment
        # tree, not this list, is the canonical explanation representation.
        all_ranked.sort(key=lambda x: (-x.explanation_score, x.path.hop_count, x.path.node_ids))
        ranked_out = tuple(replace(rp, rank=i) for i, rp in enumerate(all_ranked[:top_n], 1))

        return ExplanationResult(
            question=question,
            matched_nodes=tuple(root_matches),
            analysis=root_goal.analysis,
            ranked_paths=ranked_out,
            selected_path=selected_path,
            selected_plan=plan,
            root_goal=root_goal,
        )

    def _plan_goal(
        self,
        goal: ExplanationGoal,
        *,
        match_provider,
        ancestry_signatures: tuple[tuple, ...],
        all_ranked: list[RankedExplanationPath],
    ) -> ExplanationSegment:
        signature = self._goal_signature(goal)
        if signature in ancestry_signatures:
            return ExplanationSegment(
                segment_id=f"S.{goal.goal_id}.ref",
                segment_type="reference",
                goal_id=goal.goal_id,
                title=f"回指：{goal.text}",
                intent=goal.analysis.intent.value,
                referenced_node_ids=tuple(goal.analysis.direct_mention_ids),
                score=100.0,
                metadata={"goal_cycle_guard": True},
            )

        if goal.depth > self.settings.explanation.max_goal_depth:
            return self.structurer.empty_segment(
                segment_id=f"S.{goal.goal_id}",
                goal_id=goal.goal_id,
                title=goal.text,
                intent=goal.analysis.intent.value,
                note="goal depth limit reached",
            )

        next_ancestry = ancestry_signatures + (signature,)

        if goal.children:
            children = [
                self._plan_goal(
                    child,
                    match_provider=match_provider,
                    ancestry_signatures=next_ancestry,
                    all_ranked=all_ranked,
                )
                for child in goal.children
            ]
            return self.structurer.sequence_segment(
                segment_id=f"S.{goal.goal_id}",
                goal_id=goal.goal_id,
                title=goal.text,
                intent=goal.analysis.intent.value,
                children=children,
            )

        matches = match_provider(goal.text)
        analysis = goal.analysis

        # Atomic goals no longer share a generic path fallback.  The router
        # chooses an explicit evidence strategy for the goal's intent.  This is
        # especially important for DEFINITION/COMPOSITION/RELATION_STRUCTURE,
        # where arbitrary multi-hop paths are often graph-valid but pedagogically
        # wrong.
        strategy = self.evidence_router.route(analysis.intent)
        evidence = strategy.collect(
            EvidenceContext(
                goal=goal,
                matches=tuple(matches),
                query_service=self.query_service,
                ranker=self.ranker,
                settings=self.settings,
            )
        )
        if evidence.ranked_paths:
            all_ranked.extend(evidence.ranked_paths[:3])

        segment = self.structurer.segment_from_evidence(
            segment_id=f"S.{goal.goal_id}",
            goal=goal,
            evidence=evidence,
        )
        return replace(
            segment,
            metadata={
                **segment.metadata,
                "evidence_strategy": strategy.name,
                "evidence_type": evidence.evidence_type,
                "evidence_score": evidence.score,
                **{f"evidence_{k}": v for k, v in evidence.metadata.items()},
            },
        )

    def _plan_composition(self, goal: ExplanationGoal, matches: list[NodeMatch]) -> ExplanationSegment:
        analysis = goal.analysis
        root = self._node_from_matches(matches, analysis.source_ids[0] if analysis.source_ids else None)
        if root is None:
            return self._empty_for_goal(goal, "composition root not found")
        components = self.query_service.find_components(
            root.id,
            limit=self.settings.explanation.relation_neighbor_limit,
        )
        if not components:
            return self._empty_for_goal(goal, "no KG-backed direct components found")
        return self.structurer.branch_segment_from_neighbors(
            segment_id=f"S.{goal.goal_id}",
            goal_id=goal.goal_id,
            title=goal.text,
            intent=analysis.intent.value,
            root=root,
            neighbors=components[: self.settings.explanation.max_children],
            purpose="composition",
        )

    def _plan_interface(self, goal: ExplanationGoal, matches: list[NodeMatch]) -> ExplanationSegment:
        analysis = goal.analysis
        root = self._node_from_matches(matches, analysis.source_ids[0] if analysis.source_ids else None)
        if root is None:
            return self._empty_for_goal(goal, "interface root not found")
        interface_neighbors = self.query_service.find_relation_neighbors(
            root.id,
            ("INTERFACES_WITH",),
            limit=self.settings.explanation.relation_neighbor_limit,
        )
        components = self.query_service.find_components(
            root.id,
            limit=self.settings.explanation.relation_neighbor_limit,
        )
        return self.structurer.interface_segment(
            segment_id=f"S.{goal.goal_id}",
            goal_id=goal.goal_id,
            title=goal.text,
            analysis=analysis,
            root=root,
            interface_neighbors=interface_neighbors,
            components=components,
        )

    def _plan_role_function(self, goal: ExplanationGoal, matches: list[NodeMatch]) -> ExplanationSegment:
        analysis = goal.analysis
        root = self._node_from_matches(matches, analysis.source_ids[0] if analysis.source_ids else None)
        if root is None:
            return self._empty_for_goal(goal, "role/function root not found")

        # A role can be encoded either as direct edges or as r.mediated_by.
        mediated = self.query_service.find_mediated_relations(
            root.id,
            limit=self.settings.explanation.relation_neighbor_limit,
        )
        functional_types = tuple(
            x
            for x in analysis.preferred_relations
            if x not in {"PART_OF", "IS_A", "CONTAINS"}
        )
        direct = self.query_service.find_relation_neighbors(
            root.id,
            functional_types or ("MANAGES", "CONTROLS", "INTERFACES_WITH", "USES", "EXECUTES"),
            limit=self.settings.explanation.relation_neighbor_limit,
        )
        return self.structurer.mediated_role_segment(
            segment_id=f"S.{goal.goal_id}",
            goal_id=goal.goal_id,
            title=goal.text,
            intent=analysis.intent.value,
            root=root,
            mediated_relations=mediated,
            direct_neighbors=direct[: self.settings.explanation.max_children],
        )

    def _plan_relation_structure(
        self,
        goal: ExplanationGoal,
        matches: list[NodeMatch],
        all_ranked: list[RankedExplanationPath],
        comparison_mode: bool = False,
    ) -> ExplanationSegment:
        analysis = goal.analysis

        # Explicit from-A-to-B structure is best treated as a bounded path.
        if analysis.source_ids and analysis.target_ids:
            return self._plan_linear(goal, matches, all_ranked)

        named_ids = list(dict.fromkeys(analysis.direct_mention_ids))
        if len(named_ids) < 2:
            return self._plan_linear(goal, matches, all_ranked)

        relations = self.query_service.find_relations_among(named_ids, limit=100)
        node_names = {m.id: m.name for m in matches if m.id in named_ids}

        # Relation-set questions are not satisfied merely because every named
        # node appears in *some* edge. The local evidence may still be a forest
        # (for example MainMemory--DRAM and Cache--SRAM). In that case, try a
        # structural one-hop hub and choose it only if it reduces the number of
        # connected components among the requested concepts.
        base_component_count = self._relation_component_count(named_ids, relations)
        chosen_hub_id = None
        root = self._node_from_matches(
            matches,
            analysis.source_ids[0] if analysis.source_ids else named_ids[0],
        )

        if base_component_count > 1:
            best = None
            best_component_count = base_component_count
            best_coverage = len(self._relation_covered_nodes(relations) & set(named_ids))
            for hub in self.query_service.find_connecting_hubs(named_ids, limit=10):
                expanded_ids = named_ids + [hub.id]
                hub_relations = self.query_service.find_relations_among(expanded_ids, limit=100)
                component_count = self._relation_component_count(expanded_ids, hub_relations)
                named_coverage = len(self._relation_covered_nodes(hub_relations) & set(named_ids))
                candidate_key = (component_count, -named_coverage, hub.id)
                best_key = (best_component_count, -best_coverage, getattr(best, "id", "~"))
                if candidate_key < best_key:
                    best = hub
                    best_component_count = component_count
                    best_coverage = named_coverage
                    relations = hub_relations
            if best is not None and best_component_count < base_component_count:
                node_names[best.id] = best.name
                root = best
                chosen_hub_id = best.id

        if root is None or not relations:
            return self._empty_for_goal(goal, "no direct/local relation-set evidence found")

        # Keep only relation evidence inside the requested local concept set (+hub).
        segment = self.structurer.relation_tree_segment(
            segment_id=f"S.{goal.goal_id}",
            goal_id=goal.goal_id,
            title=goal.text,
            intent=analysis.intent.value,
            root=root,
            node_names=node_names,
            relations=relations,
            max_depth=min(4, self.settings.explanation.max_plan_depth),
        )
        final_ids = list(node_names)
        final_component_count = self._relation_component_count(final_ids, relations)
        segment = replace(
            segment,
            metadata={
                **segment.metadata,
                "named_concept_ids": tuple(named_ids),
                "named_concept_count": len(named_ids),
                "relation_components_before_hub": base_component_count,
                "relation_components_after_hub": final_component_count,
                "connecting_hub_id": chosen_hub_id,
            },
        )
        if comparison_mode:
            segment = replace(segment, metadata={**segment.metadata, "layout_hint": "side_by_side"})
        return segment

    def _plan_linear(
        self,
        goal: ExplanationGoal,
        matches: list[NodeMatch],
        all_ranked: list[RankedExplanationPath],
    ) -> ExplanationSegment:
        analysis = goal.analysis
        candidates = self._anchored_candidates(analysis, matches)
        if not candidates:
            # Seed-pair fallback remains a local evidence tool; it is no longer
            # the global explanation representation.
            _, candidates = self.query_service.generate_candidate_paths(goal.text)
        ranked = self.ranker.rank(analysis, candidates)
        if not ranked:
            # One-root general/definition questions can still be answered from
            # a small preferred-relation neighborhood rather than inventing a target.
            root = self._node_from_matches(matches, analysis.source_ids[0] if analysis.source_ids else None)
            if root is not None and analysis.preferred_relations:
                neighbors = self.query_service.find_relation_neighbors(
                    root.id,
                    analysis.preferred_relations,
                    limit=min(self.settings.explanation.relation_neighbor_limit, self.settings.explanation.max_children),
                )
                if neighbors:
                    return self.structurer.branch_segment_from_neighbors(
                        segment_id=f"S.{goal.goal_id}",
                        goal_id=goal.goal_id,
                        title=goal.text,
                        intent=analysis.intent.value,
                        root=root,
                        neighbors=neighbors,
                        purpose="local_fallback",
                    )
            return self._empty_for_goal(goal, "no suitable KG path/evidence found")

        all_ranked.extend(ranked[:3])
        return self.structurer.linear_segment(
            segment_id=f"S.{goal.goal_id}",
            goal_id=goal.goal_id,
            question=goal.text,
            analysis=analysis,
            ranked=ranked[0],
        )

    def _anchored_candidates(self, analysis, matches: list[NodeMatch]) -> list[ExplanationPath]:
        max_hops = self.settings.query.max_hops
        per_pair = self.settings.query.paths_per_pair
        limit = self.settings.query.candidate_path_limit
        paths: list[ExplanationPath] = []
        seen: set[tuple[str, ...]] = set()

        for source in analysis.source_ids:
            for target in analysis.target_ids:
                if source == target:
                    continue
                found = self.query_service.find_paths_between(
                    source,
                    target,
                    max_hops=max_hops,
                    limit=per_pair,
                )
                for path in found:
                    if path_key(path) in seen:
                        continue
                    seen.add(path_key(path))
                    paths.append(self._with_graph_score(path, matches))
                    if len(paths) >= limit:
                        return paths
        return paths

    @staticmethod
    def _with_graph_score(path: ExplanationPath, matches: list[NodeMatch]) -> ExplanationPath:
        score_by_id = {m.id: m.score for m in matches}
        endpoint = (
            score_by_id.get(path.node_ids[0], 0.0)
            + score_by_id.get(path.node_ids[-1], 0.0)
        ) / 2.0
        confs = [float(r.get("confidence", 1.0) or 1.0) for r in path.relationships]
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        animation = (
            sum(1 for r in path.relationships if r.get("default_animation_pattern"))
            / max(1, len(path.relationships))
        )
        graph_score = 0.62 * endpoint + 25.0 * mean_conf + 8.0 * animation - max(0, path.hop_count - 4) * 3.0
        return ExplanationPath(
            node_ids=path.node_ids,
            node_names=path.node_names,
            relationships=path.relationships,
            score=round(graph_score, 4),
        )

    def _empty_for_goal(self, goal: ExplanationGoal, note: str) -> ExplanationSegment:
        return self.structurer.empty_segment(
            segment_id=f"S.{goal.goal_id}",
            goal_id=goal.goal_id,
            title=goal.text,
            intent=goal.analysis.intent.value,
            note=note,
        )

    @staticmethod
    def _goal_signature(goal: ExplanationGoal) -> tuple:
        a = goal.analysis
        return (
            a.intent.value,
            tuple(a.source_ids),
            tuple(a.target_ids),
            tuple(a.focus_ids),
            "".join(goal.text.split()).lower(),
        )

    @staticmethod
    def _count_goals(goal: ExplanationGoal) -> int:
        return 1 + sum(ExplanationPlanner._count_goals(c) for c in goal.children)

    @staticmethod
    def _relation_covered_nodes(relations) -> set[str]:
        out: set[str] = set()
        for edge in relations:
            out.add(edge.source_id)
            out.add(edge.target_id)
        return out

    @staticmethod
    def _relation_component_count(node_ids, relations) -> int:
        ids = list(dict.fromkeys(str(x) for x in node_ids if str(x)))
        if not ids:
            return 0
        parent = {x: x for x in ids}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            if a not in parent or b not in parent:
                return
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for edge in relations:
            union(str(edge.source_id), str(edge.target_id))
        return len({find(x) for x in ids})

    @staticmethod
    def _node_from_matches(matches: list[NodeMatch], node_id: str | None) -> NodeMatch | None:
        if node_id is None:
            return matches[0] if matches else None
        return next((m for m in matches if m.id == node_id), None)

    @staticmethod
    def _first_linear_knowledge_path(segment: ExplanationSegment, question: str) -> KnowledgePath | None:
        if segment.segment_type == "linear" and segment.node_ids:
            return KnowledgePath(
                path_type="explanation",
                goal=f"explain:{segment.intent}",
                question=question,
                intent=segment.intent,
                node_ids=segment.node_ids,
                node_names=segment.node_names,
                relations=segment.relations,
                explanation_score=segment.score,
                metadata={"segment_id": segment.segment_id},
            )
        for child in segment.children:
            found = ExplanationPlanner._first_linear_knowledge_path(child, question)
            if found is not None:
                return found
        return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan a recursive explanation over the Computer Core KG")
    parser.add_argument("question", help="Natural-language question")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _print_goal(goal: ExplanationGoal, prefix: str = "") -> None:
    print(
        f"{prefix}{goal.goal_id} [{goal.analysis.intent.value}] {goal.text}"
        + ("" if not goal.children else f"  ({len(goal.children)} subgoals)")
    )
    for i, child in enumerate(goal.children):
        connector = "└─ " if i == len(goal.children) - 1 else "├─ "
        _print_goal(child, prefix + connector)


def _segment_relation_label(segment: ExplanationSegment) -> str:
    if not segment.relations:
        return ""
    rel = segment.relations[0]
    return str(rel.get("narrative_relation_type") or rel.get("type") or "")


def _print_segment(segment: ExplanationSegment, prefix: str = "", is_last: bool = True, is_root: bool = True) -> None:
    connector = "" if is_root else ("└─ " if is_last else "├─ ")
    relation = _segment_relation_label(segment)
    rel_text = f" [{relation}]" if relation else ""
    ref = " ↩" if segment.segment_type == "reference" else ""
    print(
        f"{prefix}{connector}{segment.segment_type.upper()} "
        f"{segment.title}{rel_text}{ref}  score={segment.score:.2f}"
    )
    child_prefix = prefix if is_root else prefix + ("   " if is_last else "│  ")
    for i, child in enumerate(segment.children):
        _print_segment(
            child,
            prefix=child_prefix,
            is_last=i == len(segment.children) - 1,
            is_root=False,
        )


def _print_result(result: ExplanationResult) -> None:
    print("\nQuestion analysis")
    print("-----------------")
    print(f"intent     : {result.analysis.intent.value}")
    print(f"confidence : {result.analysis.confidence:.3f}")
    print(f"source     : {', '.join(result.analysis.source_ids) or '-'}")
    print(f"target     : {', '.join(result.analysis.target_ids) or '-'}")
    print(f"focus      : {', '.join(result.analysis.focus_ids) or '-'}")
    for reason in result.analysis.rationale:
        print(f"reason     : {reason}")

    if result.root_goal:
        print("\nExplanation goals")
        print("-----------------")
        _print_goal(result.root_goal)

    print("\nMatched nodes")
    print("-------------")
    for m in result.matched_nodes:
        print(f"{m.id:>6}  {m.score:8.3f}  {m.name} / {m.name_en}")

    if result.ranked_paths:
        print("\nPath evidence (diagnostic only)")
        print("-------------------------------")
        for rp in result.ranked_paths:
            b = rp.breakdown
            print(
                f"{rp.rank:02d}. explain={b.explanation_score:6.2f} "
                f"graph={b.graph_score:6.2f} hops={rp.path.hop_count}  {_format_path(rp.path)}"
            )

    if result.selected_plan and result.selected_plan.root_segment:
        plan = result.selected_plan
        print("\nSelected Recursive ExplanationPlan")
        print("----------------------------------")
        print(f"representation : {plan.metadata.get('representation')}")
        print(f"structure      : {plan.structure_type}")
        print(f"score          : {plan.explanation_score:.2f}")
        if plan.validation:
            print(f"valid          : {plan.validation.valid}")
            print(f"segments/depth : {plan.validation.segment_count}/{plan.validation.max_depth}")
            for err in plan.validation.errors:
                print(f"ERROR          : {err}")
            for warning in plan.validation.warnings:
                print(f"WARN           : {warning}")
        print("\nPlan tree")
        print("---------")
        _print_segment(plan.root_segment)


def main() -> None:
    args = _build_parser().parse_args()
    settings = load_settings(args.config)

    with Neo4jClient(settings.neo4j) as client:
        query_service = KGQueryService(client, settings)
        planner = ExplanationPlanner(query_service, settings)
        result = planner.explain(args.question, top_n=args.limit)

    if args.as_json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        _print_result(result)


if __name__ == "__main__":
    main()
