import unittest
from explanation.answer_contract import validate_mechanism_review


class MechanismContractTests(unittest.TestCase):
    lesson = [{'question': '高速缓存如何减少访存延迟？', 'clauses': [
        {'narration': '请求命中缓存时，直接返回数据，避免等待主存。'}]}]

    def test_semantic_pass_does_not_require_rigid_diagnostic_fields(self):
        validate_mechanism_review(self.lesson, [{'scope': 'question:0', 'pass': True}])

    def test_partial_diagnostic_is_allowed(self):
        validate_mechanism_review(self.lesson, [{'scope': 'question:0', 'pass': True,
            'answer_chain': {'process': {'clause_index': 0, 'quote': '直接返回数据'}}}])

    def test_grounded_chain(self):
        chain = {role: {'clause_index': 0, 'quote': quote} for role, quote in
                 [('condition', '请求命中缓存时'), ('process', '直接返回数据'), ('outcome', '避免等待主存')]}
        chain['causal_link_supported'] = True
        checks = [{'scope': 'question:0', 'pass': True, 'answer_chain': chain}]
        validate_mechanism_review(self.lesson, checks)
        chain['process']['quote'] = '查询L2'
        with self.assertRaises(ValueError):
            validate_mechanism_review(self.lesson, checks)

    def test_explicit_failure_is_preserved(self):
        validate_mechanism_review(self.lesson, [{'scope': 'question:0', 'pass': False,
                                               'issues': ['只有组成关系']}])
