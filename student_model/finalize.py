"""Restrict prerequisite teaching to the answer scenes actually selected."""
import copy
from dataclasses import replace


def finalize_prerequisites(story, report):
    report = copy.deepcopy(report)
    answer_scenes = [s for s in story.scenes if not s.metadata.get('prerequisite')]
    active = {nid for s in answer_scenes for nid in s.node_ids}
    support = {}
    for question in report.get('subquestions', []):
        for graph in question.get('subgraphs', []):
            core = graph['core_node_id']
            graph['used_by_final_answer'] = core in active
            if core not in active:
                continue
            for node in graph['nodes']:
                nid = node['node_id']
                if nid == core:
                    continue
                support.setdefault(nid, []).extend({
                    'core_node_id': core, 'scene_id': s.story_scene_id,
                    'subquestion_id': s.metadata.get('subquestion_id'),
                    'subquestion': s.metadata.get('subquestion', s.title),
                    'subgraph_id': graph['subgraph_id']}
                    for s in answer_scenes if core in s.node_ids)
    kept, removed, scenes = set(), [], []
    for scene in story.scenes:
        if not scene.metadata.get('prerequisite'):
            scenes.append(scene)
            continue
        ids = set(scene.node_ids)
        if not ids.intersection(support):
            removed.append({'scene_id': scene.story_scene_id, 'node_ids': sorted(ids),
                            'reason': 'no_dependency_on_final_answer_nodes'})
            continue
        kept.add(scene.segment_id)
        scenes.append(replace(scene, metadata={**scene.metadata,
            'supports_final_answer': [item for nid in ids for item in support.get(nid, [])]}))

    def prune(segment):
        if segment.metadata.get('prerequisite') and segment.segment_id not in kept:
            return None
        children = tuple(child for c in segment.children if (child := prune(c)) is not None)
        return replace(segment, children=children)

    representation = replace(story.representation_plan,
                             root_segment=prune(story.representation_plan.root_segment))
    report['final_selection'] = {'answer_node_ids': sorted(active),
        'supports': support, 'removed_scenes': removed, 'kept_segment_ids': sorted(kept)}
    report['teaching_node_ids'] = list(dict.fromkeys(nid for s in scenes
        if s.metadata.get('prerequisite') for nid in s.node_ids))
    result = replace(story, scenes=tuple(scenes), representation_plan=representation,
        estimated_duration=sum(b.duration for s in scenes for b in s.beats),
        metadata={**story.metadata, 'scene_count': len(scenes),
                  'prerequisite_selection': report['final_selection']})
    return result, report
