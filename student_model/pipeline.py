"""Read-only student adaptation of an already coverage-checked answer plan."""
from dataclasses import asdict, replace
import json

import pandas as pd

from explanation.models import ExplanationSegment
from explanation.question_analyzer import QuestionAnalyzer
from explanation.validator import ExplanationPlanValidator
from .prerequisites import Dependency, expand_prerequisites
from .state import StateStore, StudentNodeState
from .scope import outside_chapter


def load_states(path, student_id):
    if path is None:
        return StateStore()
    with open(path, encoding='utf-8') as stream:
        rows = json.load(stream)
    if not isinstance(rows, list):
        raise ValueError('student states must be a JSON array')
    states = [StudentNodeState(**row) for row in rows]
    if not any(s.student_id == student_id for s in states):
        raise ValueError(f'No state records for student {student_id}')
    return StateStore(states)


def load_dependencies(data):
    with pd.ExcelFile(data.workbook) as excel:
        nodes = pd.read_excel(excel, sheet_name=data.nodes_sheet).fillna('')
        catalog = {str(r['node_id:ID']): r for r in nodes.to_dict('records')
                   if r.get('status', 'active') == 'active'}
        if data.dependencies_sheet not in excel.sheet_names:
            return [], catalog, 'missing_sheet'
        frame = pd.read_excel(excel, sheet_name=data.dependencies_sheet).fillna('')
    edges = []
    seen = set()
    for row in frame.to_dict('records'):
        if row.get('status', 'active') != 'active':
            continue
        edge = Dependency(str(row['dependency_id']), str(row[':START_ID']),
                          str(row[':END_ID']), str(row['strength']), float(row['weight:float']))
        if row[':TYPE'] != 'PREREQUISITE_OF' or edge.dependency_id in seen:
            raise ValueError('Invalid or duplicate teaching dependency')
        if edge.prerequisite_id not in catalog or edge.target_id not in catalog:
            raise ValueError(f'Dependency {edge.dependency_id} references an unavailable node')
        seen.add(edge.dependency_id)
        edges.append(edge)
    return edges, catalog, 'loaded'


def adapt_plan(plan, retrievals, dependencies, catalog, states, student_id, *, as_of, policy):
    """Keep answer facts unchanged; add shared prerequisite definitions before them."""
    report = dict(student_id=student_id, as_of=as_of.isoformat(), policy=asdict(policy),
                  source='workbook:Knowledge_Dependencies', subquestions=[], omitted=[],
                  teaching_node_ids=[], state_snapshots=[])
    segments, taught = [], set()
    for index, retrieval in enumerate(retrievals, 1):
        analysis = QuestionAnalyzer().analyze(retrieval['question'], retrieval['matches'])
        core_ids = list(dict.fromkeys(analysis.direct_mention_ids))
        if not core_ids:
            report['omitted'].append(dict(question=retrieval['question'], reason='no_explicit_core_nodes'))
        group = dict(subquestion_id=f'SQ{index:03}', question=retrieval['question'],
                     core_node_ids=core_ids, candidate_paths=[asdict(p) for p in retrieval['paths']],
                     subgraphs=[])
        for core_id in core_ids:
            if core_id not in catalog:
                report['omitted'].append(dict(node_id=core_id, reason='core_not_in_workbook'))
                continue
            graph = expand_prerequisites(student_id, core_id, dependencies, states,
                                        as_of=as_of, policy=policy)
            graph['subgraph_id'] = f"{group['subquestion_id']}.{core_id}"
            group['subgraphs'].append(graph)
            by_id = {n['node_id']: n for n in graph['nodes']}
            for node_id in graph['teaching_order']:
                if node_id == core_id:
                    continue
                node = by_id[node_id]
                record = catalog[node_id]
                if outside_chapter(record):
                    node['scheduled'] = False
                    report['omitted'].append(dict(node_id=node_id, reason='outside_chapter_scope'))
                    continue
                if node_id in taught:
                    node['shared_segment_id'] = f'PRE.{node_id}'
                    continue
                if len(taught) >= policy.max_nodes:
                    node['scheduled'] = False
                    report['omitted'].append(dict(node_id=node_id, reason='global_node_budget'))
                    continue
                record = catalog[node_id]
                # No invented remediation/definition when the workbook has no evidence.
                if node['action'] != 'reference' and not str(record.get('definition', '')).strip():
                    node['scheduled'] = False
                    report['omitted'].append(dict(node_id=node_id, reason='missing_definition'))
                    continue
                state = states.get(student_id, node_id)
                report['state_snapshots'].append(asdict(state))
                name = str(record['name'])
                action = node['action']
                definition = str(record.get('definition', '')).strip()
                narration = (f'{name}。' if action == 'reference' else
                             definition if definition.startswith(name) else f'{name}是{definition}')
                segments.append(ExplanationSegment(
                    segment_id=f'PRE.{node_id}', segment_type='reference' if action == 'reference' else 'definition',
                    goal_id=group['subquestion_id'], title=name, intent='definition',
                    root_id=node_id, root_name=name, node_ids=(node_id,), node_names=(name,),
                    referenced_node_ids=(node_id,) if action == 'reference' else (),
                    metadata={'prerequisite': True, 'student_action': action,
                              'student_narration': narration, 'subquestion_id': f'PRE.{node_id}',
                              'subquestion': name, 'source_subquestion_id': group['subquestion_id'],
                              'subgraph_id': graph['subgraph_id'],
                              'misconception_ids': state.misconception_ids,
                              'remediation_scope': 'definition_review_only' if action == 'remediate' else None}))
                taught.add(node_id)
                node['scheduled'] = True
        report['subquestions'].append(group)
    report['teaching_node_ids'] = [s.root_id for s in segments]
    report['status'] = 'partial' if report['omitted'] or any(
        e['reason'] != 'recommended_disabled' for q in report['subquestions']
        for g in q['subgraphs'] for e in g['omitted']) else 'planned'
    if not segments:
        return plan, report
    root = ExplanationSegment(segment_id='personalized_lesson', segment_type='sequence',
        goal_id='personalized', title=plan.question, intent=plan.intent,
        children=(*segments, plan.root_segment))
    result = replace(plan, root_segment=root, structure_type='sequence',
                     metadata={**plan.metadata, 'student_id': student_id,
                               'prerequisite_segment_ids': [s.segment_id for s in segments]})
    def size(seg):
        return 1 + sum(size(c) for c in seg.children)
    validation = ExplanationPlanValidator(max_depth=100, max_segments=size(root),
                                          max_children=size(root)).validate(result)
    if not validation.valid:
        raise ValueError('Personalized explanation plan failed validation')
    return replace(result, validation=validation), report
