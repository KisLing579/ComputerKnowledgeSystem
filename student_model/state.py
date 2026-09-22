from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math


class StateLabel(StrEnum):
    UNKNOWN = 'unknown'
    INTRODUCED = 'introduced'
    LEARNING = 'learning'
    MASTERED = 'mastered'
    UNSTABLE = 'unstable'
    FORGOTTEN = 'forgotten'
    MISCONCEIVED = 'misconceived'


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamps must include a timezone')
    return parsed


@dataclass(frozen=True)
class StudentNodeState:
    student_id: str
    node_id: str
    mastery_prob: float | None = None
    uncertainty: float = 1.0
    evidence_count: int = 0
    positive_evidence: int = 0
    negative_evidence: int = 0
    last_interaction_at: str | None = None
    forgetting_risk: float | None = None
    state_label: str = 'unknown'
    model_name: str = 'uninitialized'
    model_version: str = 'none'
    updated_at: str | None = None
    last_mastered_at: str | None = None
    misconception_ids: tuple[str, ...] = ()
    is_simulated: bool = False
    state_version: str = 'v1'

    def __post_init__(self):
        if not self.student_id.strip() or not self.node_id.strip():
            raise ValueError('student_id and node_id are required')
        StateLabel(self.state_label)
        for key in ('mastery_prob', 'uncertainty', 'forgetting_risk'):
            value = getattr(self, key)
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f'{key} must be in [0, 1]')
        for key in ('evidence_count', 'positive_evidence', 'negative_evidence'):
            value = getattr(self, key)
            if type(value) is not int or value < 0:
                raise ValueError(f'{key} must be a nonnegative integer')
        if self.positive_evidence + self.negative_evidence > self.evidence_count:
            raise ValueError('classified evidence cannot exceed evidence_count')
        for key in ('last_interaction_at', 'updated_at', 'last_mastered_at'):
            if getattr(self, key) is not None:
                timestamp(getattr(self, key))
        if self.updated_at:
            for key in ('last_interaction_at', 'last_mastered_at'):
                if getattr(self, key) and timestamp(getattr(self, key)) > timestamp(self.updated_at):
                    raise ValueError(f'{key} cannot follow updated_at')
        if self.state_label == 'forgotten' and not self.last_mastered_at:
            raise ValueError('forgotten requires historical mastery')
        if self.state_label == 'misconceived' and not self.misconception_ids:
            raise ValueError('misconceived requires identified misconceptions')


class StateStore:
    def __init__(self, states=()):
        self._states = {}
        for state in states:
            key = (state.student_id, state.node_id)
            if key in self._states:
                raise ValueError(f'duplicate student-node state: {key}')
            self._states[key] = state

    def get(self, student_id: str, node_id: str) -> StudentNodeState:
        return self._states.get((student_id, node_id)) or StudentNodeState(student_id, node_id)
