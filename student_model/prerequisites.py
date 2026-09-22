from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .state import StateStore, StudentNodeState, timestamp


@dataclass(frozen=True)
class ExpansionPolicy:
    max_depth: int = 3
    max_nodes: int = 20
    include_recommended: bool = False
    mastery_threshold: float = 0.85
    uncertainty_threshold: float = 0.20
    forgetting_threshold: float = 0.20
    min_evidence: int = 3
    max_state_age_days: int = 30

    def __post_init__(self):
        if self.max_depth < 0 or self.max_nodes < 1 or self.min_evidence < 1 or self.max_state_age_days < 0:
            raise ValueError('invalid expansion budget')
        for value in (self.mastery_threshold, self.uncertainty_threshold, self.forgetting_threshold):
            if not 0 <= value <= 1:
                raise ValueError('thresholds must be in [0, 1]')

    def action(self, state: StudentNodeState, as_of: datetime) -> tuple[str, str]:
        if as_of.tzinfo is None:
            raise ValueError('as_of must include a timezone')
        if state.state_label == 'misconceived':
            return 'remediate', 'identified_misconception'
        fresh = (state.updated_at is not None and
                 0 <= (as_of - timestamp(state.updated_at)).total_seconds() <= self.max_state_age_days * 86400)
        if (state.state_label == 'mastered' and fresh
                and state.mastery_prob is not None and state.mastery_prob >= self.mastery_threshold
                and state.uncertainty <= self.uncertainty_threshold
                and state.forgetting_risk is not None and state.forgetting_risk <= self.forgetting_threshold
                and state.evidence_count >= self.min_evidence):
            return 'reference', 'reliable_mastery'
        if state.state_label in ('mastered', 'unstable', 'forgotten'):
            return 'review', 'mastery_needs_revalidation'
        return 'explain', state.state_label


@dataclass(frozen=True)
class Dependency:
    dependency_id: str
    prerequisite_id: str
    target_id: str
    strength: str = 'required'
    weight: float = 1.0

    def __post_init__(self):
        if self.strength not in ('required', 'recommended') or not 0 <= self.weight <= 1:
            raise ValueError('invalid dependency strength/weight')


def expand_prerequisites(student_id, core_node_id, dependencies, states: StateStore,
                         *, as_of: datetime, policy: ExpansionPolicy | None = None):
    """Plan one core concept; preserve boundary/cycle/budget decisions for audit.

    This plans teaching scope, not factual evidence or mastery updates.
    Core concepts remain in scope even when mastered.
    """
    policy = policy or ExpansionPolicy()
    incoming = {}
    for edge in dependencies:
        incoming.setdefault(edge.target_id, []).append(edge)
    nodes, edges, omitted, order = {}, {}, [], []

    def visit(node_id, depth, ancestry):
        if node_id in nodes:
            return
        state = states.get(student_id, node_id)
        action, reason = policy.action(state, as_of)
        nodes[node_id] = dict(node_id=node_id, state_label=state.state_label,
                              action=action, reason=reason, depth=depth,
                              role='core' if depth == 0 else 'prerequisite')
        if depth == 0 or action != 'reference':
            for edge in sorted(incoming.get(node_id, []),
                               key=lambda e: (e.strength != 'required', -e.weight, e.dependency_id)):
                cause = None
                if edge.strength == 'recommended' and not policy.include_recommended:
                    cause = 'recommended_disabled'
                elif edge.prerequisite_id in ancestry or edge.prerequisite_id == node_id:
                    cause = 'cycle'
                elif depth >= policy.max_depth:
                    cause = 'depth_budget'
                elif edge.prerequisite_id not in nodes and len(nodes) >= policy.max_nodes:
                    cause = 'node_budget'
                if cause:
                    omitted.append(dict(dependency_id=edge.dependency_id, reason=cause))
                    continue
                edges[edge.dependency_id] = dict(dependency_id=edge.dependency_id,
                    prerequisite_id=edge.prerequisite_id, target_id=node_id, strength=edge.strength)
                visit(edge.prerequisite_id, depth + 1, ancestry | {node_id})
        order.append(node_id)

    visit(core_node_id, 0, set())
    return dict(student_id=student_id, core_node_id=core_node_id, as_of=as_of.isoformat(),
                policy_version='prerequisites-v1', nodes=list(nodes.values()),
                edges=list(edges.values()), teaching_order=order, omitted=omitted)
