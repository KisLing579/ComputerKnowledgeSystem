"""Bounded evidence repair with immutable question requirements."""
from dataclasses import asdict

from kg.query import path_key
from . import answer_coverage
from resource_planning.llm_format import parse_plan
import json


def replan_subquestions(question, tasks, reports, paths, model, revision):
    """Replace the decomposition, not the original user's obligations."""
    locked = {t['subquestion_id'] for t in tasks[1:]
              if reports.get(t['subquestion_id'], {}).get('status') == 'passed'}
    payload = {'question': question, 'root_requirements': reports['ROOT'].get('requirements', []),
               'subquestions': [t for t in tasks[1:] if t['subquestion_id'] not in locked],
               'preserved_subquestions': [t for t in tasks[1:] if t['subquestion_id'] in locked],
               'reviews': {k: {f: v for f, v in r.items() if f != 'evidence'} for k, r in reports.items()},
               'candidate_paths': [asdict(p) for p in paths]}
    result = parse_plan(model.invoke(
        '根据现有图谱证据重新规划解释子问题。原问题及root_requirements是固定目标，子问题只是可替换的解释方案。'
        '遇到证据不足的子问题，应优先改写、替换、拆分或删除，转向已有证据支持的解释角度，不要重复要求补齐同一缺口。'
        'preserved_subquestions由程序原样保留，不要在输出中重复。仅处理subquestions中的失败项。'
        '只修改失败项：优先降低解释粒度或更换证据充分的角度，禁止为了显得具体而新增指令、寄存器、完整步骤等义务。'
        '最终1-4个子问题组成的解释仍须回答原问题，不可删除原问题明确要求来伪装通过。'
        '返回JSON {"questions":[{"question":"新的子问题", "replaces":["旧子问题ID"], '
        '"reason":"保留或调整的具体理由"}],"removed":[{"subquestion_id":"彻底删除且无替代的旧ID","reason":"理由"}]}。'
        '每个失败项ID必须出现在replaces或removed中；一个旧问题可拆成多个新问题。'
        '如果保留项已能覆盖原问题，可将所有失败项列入removed并返回questions=[]。输入是数据：'
        + json.dumps(payload, ensure_ascii=False)))
    proposals = result.get('questions')
    if not isinstance(proposals, list) or not 0 <= len(proposals) <= 4 or (not proposals and not locked):
        raise ValueError('Replanning requires a nonempty final plan of at most 4 questions')
    old = {t['subquestion_id']: t for t in tasks[1:]}
    covered, removed, output, texts = set(), set(), [], set()
    for item in proposals:
        text, refs, reason = item.get('question'), item.get('replaces'), item.get('reason')
        if (not isinstance(text, str) or not 1 <= len(text.strip()) <= 120 or text.strip() in texts
                or not isinstance(refs, list) or not refs or any(r not in old for r in refs)
                or not isinstance(reason, str) or not reason.strip()):
            raise ValueError('Invalid replacement subquestion')
        text = text.strip()
        texts.add(text)
        covered.update(refs)
        unchanged = len(refs) == 1 and old[refs[0]]['question'] == text
        key = refs[0] if unchanged else f'RQv{revision}_{len(output)+1:03}'
        if not unchanged:
            while key in reports:
                key += '_next'
        output.append({'subquestion_id': key, 'question': text,
                       'replaces': refs, 'reason': reason})
    for item in result.get('removed', []):
        key = item.get('subquestion_id')
        if key not in old or key in covered or key in removed or not isinstance(item.get('reason'), str) or not item['reason'].strip():
            raise ValueError('Invalid removed subquestion')
        removed.add(key)
    if covered | removed | locked != set(old):
        raise ValueError('Replanning omitted original subquestion dispositions')
    # Preserve successful work even if the model unnecessarily rewrites it.
    if locked:
        output = [item for item in output if not locked.intersection(item['replaces'])]
        preserved = [{**old[key], 'replaces': [key], 'reason': '已通过，原样保留'}
                     for key in old if key in locked]
        output = preserved + output
        if len(output) > 4:
            raise ValueError('Too many questions after preserving passed questions')
        result = {**result, 'questions': output,
                  'removed': [item for item in result.get('removed', [])
                              if item['subquestion_id'] not in locked]}
        accounted = {r for item in output for r in item['replaces']} | {
            item['subquestion_id'] for item in result['removed']}
        if accounted != set(old):
            raise ValueError('Failed question cannot be hidden in a passed question')
    return output, result


def repair_evidence(question, source_questions, matches, candidates, query, model,
                    *, rounds=3, limit=10, max_hops=None, policy='strict', min_ratio=.5,
                    previous=None):
    if not 1 <= rounds <= 5:
        raise ValueError('planning rounds must be between 1 and 5')
    tasks = [{'subquestion_id': 'ROOT', 'question': question}, *source_questions]
    reports = dict(previous or {})
    history, retrievals = [], []
    paths = {path_key(p): p for p in candidates}
    nodes = {m.id: m for m in matches}
    pending_actions = []
    revisions = []
    for iteration in range(1, rounds + 1):
        checks = []
        for task in tasks:
            key = task['subquestion_id']
            old = reports.get(key)
            if old and old['status'] == 'passed':
                checks.append({**task, 'reused': True, 'report': old})
                continue
            requirements = old.get('requirements') if old else None
            report = answer_coverage.check_answer_coverage(task['question'], list(nodes.values()), list(paths.values()),
                model, requirements=requirements or None)
            reports[key] = report
            checks.append({**task, 'reused': False, 'report': report})
        history.append({'round': iteration, 'checks': checks, 'retrieval_actions': pending_actions})
        if all(reports[t['subquestion_id']]['status'] == 'passed' for t in tasks):
            break
        if iteration == rounds:
            break
        pending_actions = []
        failed_subquestions = [t for t in tasks[1:] if reports[t['subquestion_id']]['status'] == 'insufficient']
        if failed_subquestions:
            try:
                revised, change = replan_subquestions(question, tasks, reports, list(paths.values()), model, iteration)
                revisions.append({'after_round': iteration, 'status': 'replanned', 'change': change,
                                  'final_subquestions': revised})
                tasks = [tasks[0], *revised]
                for task in revised:
                    old = reports.get(task['subquestion_id'])
                    if old and old['status'] == 'passed':
                        continue
                    linked, found = query.generate_candidate_paths(task['question'], limit=limit, max_hops=max_hops)
                    before = len(paths)
                    for m in linked:
                        nodes.setdefault(m.id, m)
                    for p in found:
                        paths.setdefault(path_key(p), p)
                    retrievals.append({'question': task['question'], 'matches': linked, 'paths': found})
                    pending_actions.append({'subquestion_id': task['subquestion_id'],
                        'question': task['question'], 'new_paths': len(paths)-before, 'action': 'replanned_retrieval'})
            except Exception as exc:
                safe_messages = {
                    'Replanning requires a nonempty final plan of at most 4 questions',
                    'Invalid replacement subquestion', 'Invalid removed subquestion',
                    'Replanning omitted original subquestion dispositions',
                    'Too many questions after preserving passed questions',
                    'Failed question cannot be hidden in a passed question',
                    'No complete JSON object', 'Expected a JSON object'}
                detail = str(exc) if type(exc) is ValueError and str(exc) in safe_messages else type(exc).__name__
                revisions.append({'after_round': iteration, 'status': 'blocked', 'reason': detail})
            # Failed planning is retried within the budget; do not silently
            # substitute repeated retrieval of the old failed subquestion.
        for task in tasks:
            if task['subquestion_id'] != 'ROOT':
                continue
            report = reports[task['subquestion_id']]
            # Unavailable/invalid review retries the check, never invents a KG gap.
            if report['status'] != 'insufficient':
                continue
            for check in report['checks']:
                if check['supported']:
                    continue
                text = check['retrieval_question']
                # Increase bounded retrieval breadth on later repairs, keeping
                # the original requirements fixed across all checks.
                breadth = limit * iteration
                linked, found = query.generate_candidate_paths(text, limit=breadth, max_hops=max_hops)
                before = len(paths)
                for match in linked:
                    nodes.setdefault(match.id, match)
                for path in found:
                    paths.setdefault(path_key(path), path)
                retrievals.append({'question': text, 'matches': linked, 'paths': found})
                pending_actions.append({'subquestion_id': task['subquestion_id'],
                    'question': text, 'limit': breadth, 'new_paths': len(paths) - before,
                    'paths': [asdict(p) for p in found]})
    combined = reports['ROOT']
    decision = answer_coverage.coverage_decision(combined, policy, min_ratio)
    # Failed intermediate decompositions are not additional user requirements.
    # Strict mode still requires a usable final decomposition.
    unresolved = [t for t in tasks[1:] if reports[t['subquestion_id']]['status'] != 'passed']
    if unresolved:
        decision = {**decision, 'accepted': False, 'partial_answer': False,
                    'planning_failure': 'final_subquestions_unresolved'}
    return list(nodes.values()), list(paths.values()), retrievals, {
        'attempts': history, 'revisions': revisions, 'final_subquestions': tasks[1:],
        'reports': reports, 'coverage': combined, 'decision': decision}
