from __future__ import annotations

from .models import ExplanationPlan, ExplanationSegment, PlanValidation


class ExplanationPlanValidator:
    """Validate recursive ExplanationPlan invariants.

    The plan is required to be a tree even though the source KG may contain
    cycles. Repeated knowledge concepts are allowed across branches, but segment
    ids cannot repeat along or across the plan structure.
    """

    def __init__(self, *, max_depth: int = 5, max_segments: int = 40, max_children: int = 8):
        self.max_depth = max_depth
        self.max_segments = max_segments
        self.max_children = max_children

    def validate(self, plan: ExplanationPlan) -> PlanValidation:
        root = plan.root_segment
        if root is None:
            return PlanValidation(valid=False, segment_count=0, max_depth=0, errors=("plan has no root_segment",))

        seen_segment_ids: set[str] = set()
        errors: list[str] = []
        warnings: list[str] = []
        count = 0
        observed_depth = 0

        def walk(segment: ExplanationSegment, depth: int, ancestor_ids: tuple[str, ...], ancestor_nodes: tuple[str, ...]) -> None:
            nonlocal count, observed_depth
            count += 1
            observed_depth = max(observed_depth, depth)

            if segment.segment_id in ancestor_ids:
                errors.append(f"segment cycle detected at {segment.segment_id}")
                return
            if segment.segment_id in seen_segment_ids:
                errors.append(f"segment_id reused: {segment.segment_id}")
                return
            seen_segment_ids.add(segment.segment_id)

            if depth > self.max_depth:
                errors.append(f"plan depth {depth} exceeds max_depth={self.max_depth}")
            if len(segment.children) > self.max_children:
                warnings.append(
                    f"segment {segment.segment_id} has {len(segment.children)} children; "
                    f"recommended max is {self.max_children}"
                )

            current_nodes = tuple(x for x in segment.node_ids if x)
            # Knowledge-node repetition is not itself a plan cycle. A child
            # segment often repeats its parent concept to express an incoming
            # relation (e.g. CPU -> Control Unit). Structural cycle detection is
            # based on segment ids; semantic re-entry can be represented with a
            # reference segment when the planner intentionally revisits content.
            new_ancestor_ids = ancestor_ids + (segment.segment_id,)
            new_ancestor_nodes = ancestor_nodes + current_nodes
            for child in segment.children:
                walk(child, depth + 1, new_ancestor_ids, new_ancestor_nodes)

        walk(root, 0, (), ())
        if count > self.max_segments:
            errors.append(f"segment count {count} exceeds max_segments={self.max_segments}")

        return PlanValidation(
            valid=not errors,
            segment_count=count,
            max_depth=observed_depth,
            errors=tuple(errors),
            warnings=tuple(dict.fromkeys(warnings)),
        )
