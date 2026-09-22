"""Offline demonstration using real KG dependencies and simulated students.

Run: python -m student_model.demo
"""
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from kg.config import load_settings
from .state import StudentNodeState, StateStore, timestamp
from .prerequisites import Dependency, ExpansionPolicy, expand_prerequisites


def main():
    settings = load_settings()
    frame = pd.read_excel(settings.data.workbook, sheet_name=settings.data.dependencies_sheet)
    dependencies = [Dependency(str(r['dependency_id']), str(r[':START_ID']), str(r[':END_ID']),
                               str(r['strength']), float(r['weight:float']))
                    for r in frame.to_dict('records') if r.get('status') == 'active']
    states = []
    # Seven hypothetical students differ only in their state for locality.
    samples = [('unknown', None, 1.0, 0, 0, 0, None),
               ('introduced', 0.25, 0.8, 0, 0, 0, None),
               ('learning', 0.78, 0.16, 9, 7, 2, 0.11),
               ('mastered', 0.95, 0.08, 12, 11, 1, 0.05),
               ('unstable', 0.86, 0.40, 12, 8, 4, 0.25),
               ('forgotten', 0.45, 0.30, 12, 8, 4, 0.75),
               ('misconceived', 0.30, 0.12, 10, 2, 8, 0.10)]
    now = '2026-09-08T10:31:00Z'
    for index, (label, prob, uncertainty, count, positive, negative, risk) in enumerate(samples, 1):
        states.append(StudentNodeState(
            student_id=f'STU{index:03}', node_id='CO050', mastery_prob=prob,
            uncertainty=uncertainty, evidence_count=count, positive_evidence=positive,
            negative_evidence=negative, forgetting_risk=risk, state_label=label,
            last_interaction_at=None if label == 'unknown' else '2026-09-08T10:30:00Z',
            updated_at=now, model_name='mock', model_version='scenario-v1',
            last_mastered_at='2026-08-01T10:00:00Z' if label == 'forgotten' else None,
            misconception_ids=('MOCK_LOCALITY_001',) if label == 'misconceived' else (),
            is_simulated=True))
    store = StateStore(states)
    plans = [expand_prerequisites(s.student_id, 'CO033', dependencies, store,
                                  as_of=timestamp(now), policy=ExpansionPolicy()) for s in states]
    out = Path('data/student_model_demo')
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in [('states.json', [asdict(s) for s in states]), ('expansion_plans.json', plans)]:
        (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    for state, plan in zip(states, plans):
        locality = next(n for n in plan['nodes'] if n['node_id'] == 'CO050')
        print(state.student_id, state.state_label, locality['action'], len(plan['nodes']))


if __name__ == '__main__':
    main()
