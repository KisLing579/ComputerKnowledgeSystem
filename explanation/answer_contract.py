"""Shared answer-shape requirements for mechanism questions."""
import re


MECHANISM_RULES = (
    '机制类问题应有依据地解释关键过程或原因，直接回答当前问题；条件→过程→结果只是组织建议，不要求每题列齐三项。'
    '分类IS_A、组成PART_OF、接口连接本身不能推出命中返回、逐级查询、减少等待或性能收益；'
    '节点定义若明确记载这些过程可以使用，但不得凭动画模板或常识补出机制。'
    '说明结果如何由过程产生，不能只在组成清单后加一句“提高性能”。'
    '解释粒度以用户问题为准；概念层面的解释充分时，不追加指令、寄存器或完整实现步骤的要求。'
    '涉及延迟时可用命中避免等待等有证据的关键机制说明，不强制穷尽所有访问路径；无证据时重规划而非编造。'
)


def is_mechanism_question(question):
    return bool(re.search(r'如何|为什么|为何|怎样|怎么|工作原理|作用机制|how\b|why\b', question, re.I))


def validate_mechanism_review(lesson, checks):
    """Require reviewers to locate the explanation chain in actual narration."""
    by_scope = {c['scope']: c for c in checks}
    for index, question in enumerate(lesson):
        if not is_mechanism_question(question['question']):
            continue
        check = by_scope[f'question:{index}']
        if not check['pass']:
            continue
        chain = check.get('answer_chain')
        clauses = question['clauses']
        if chain is None:
            continue
        if not isinstance(chain, dict):
            raise ValueError('Optional answer_chain must be an object')
        for role in ('condition', 'process', 'outcome'):
            if role not in chain:
                continue
            entry = chain[role]
            clause = entry.get('clause_index')
            quote = entry.get('quote')
            if (type(clause) is not int or not 0 <= clause < len(clauses)
                    or not isinstance(quote, str) or not quote.strip()
                    or quote not in clauses[clause]['narration']):
                raise ValueError('Mechanism answer_chain must cite existing clause text')
        if chain.get('causal_link_supported') is False:
            raise ValueError('Mechanism outcome lacks a supported causal link')
