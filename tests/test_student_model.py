from dataclasses import replace
import unittest

from student_model.state import StudentNodeState, StateStore, timestamp
from student_model.prerequisites import Dependency, ExpansionPolicy, expand_prerequisites


class StudentModelTests(unittest.TestCase):
    now = timestamp('2026-09-08T10:31:00Z')

    def mastered(self):
        return StudentNodeState('S', 'B', mastery_prob=.95, uncertainty=.08,
            forgetting_risk=.05, evidence_count=10, positive_evidence=9,
            negative_evidence=1, state_label='mastered', updated_at=self.now.isoformat())

    def plan(self, states=(), dependencies=None, **kwargs):
        if dependencies is None:
            dependencies = [Dependency('AB', 'B', 'A'), Dependency('BC', 'C', 'B')]
        return expand_prerequisites('S', 'A', dependencies, StateStore(states),
                                    as_of=self.now, **kwargs)

    def test_missing_state_is_unknown_and_student_isolation(self):
        store = StateStore([self.mastered()])
        self.assertEqual(store.get('other', 'B').state_label, 'unknown')
        self.assertIsNone(store.get('other', 'B').mastery_prob)

    def test_mastered_boundary_changes_scope(self):
        self.assertEqual(self.plan()['teaching_order'], ['C', 'B', 'A'])
        self.assertEqual(self.plan([self.mastered()])['teaching_order'], ['B', 'A'])

    def test_stale_or_uncertain_mastery_expands(self):
        for state in (replace(self.mastered(), updated_at='2026-01-01T00:00:00Z'),
                      replace(self.mastered(), uncertainty=.8),
                      replace(self.mastered(), forgetting_risk=None)):
            self.assertEqual(self.plan([state])['teaching_order'], ['C', 'B', 'A'])

    def test_budget_and_cycles_reported(self):
        result = self.plan(policy=ExpansionPolicy(max_nodes=2))
        self.assertEqual(result['omitted'][0]['reason'], 'node_budget')
        result = self.plan(dependencies=[Dependency('AB', 'B', 'A'), Dependency('BA', 'A', 'B')])
        self.assertEqual(result['omitted'][0]['reason'], 'cycle')

    def test_recommended_opt_in(self):
        edges = [Dependency('AB', 'B', 'A', 'recommended')]
        self.assertEqual(len(self.plan(dependencies=edges)['nodes']), 1)
        self.assertEqual(len(self.plan(dependencies=edges,
            policy=ExpansionPolicy(include_recommended=True))['nodes']), 2)

    def test_shared_predecessor_once(self):
        edges = [Dependency('AB', 'B', 'A'), Dependency('AC', 'C', 'A'),
                 Dependency('BD', 'D', 'B'), Dependency('CD', 'D', 'C')]
        result = self.plan(dependencies=edges)
        self.assertEqual(result['teaching_order'].count('D'), 1)
        self.assertEqual(len(result['edges']), 4)

    def test_invalid_state_rejected(self):
        for changes in ({'mastery_prob': 1.1}, {'evidence_count': -1},
                        {'positive_evidence': 11}, {'state_label': 'forgotten'},
                        {'state_label': 'misconceived'}, {'updated_at': '2026-09-08T10:00:00'}):
            with self.assertRaises(ValueError):
                replace(self.mastered(), **changes)

    def test_duplicate_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            StateStore([self.mastered(), self.mastered()])

    def test_misconception_remediation(self):
        state = replace(self.mastered(), state_label='misconceived', misconception_ids=('M1',))
        result = self.plan([state])
        self.assertEqual(next(n for n in result['nodes'] if n['node_id'] == 'B')['action'], 'remediate')
        self.assertIn('C', result['teaching_order'])
