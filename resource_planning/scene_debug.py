"""Trace the evidence/group/scene boundary using stable KG and execution IDs."""
from dataclasses import asdict


def scene_planning_report(plan, story, answer_graph):
    groups = []
    def visit(segment):
        if segment.metadata.get('prerequisite'):
            return
        if segment.relations:
            groups.append({'segment_id': segment.segment_id, 'explanation_goal': segment.intent,
                'goal_id': segment.goal_id, 'nodes': list(segment.node_ids),
                'relations': [r.get('id') for r in segment.relations],
                'source_path_ids': segment.metadata.get('source_path_ids', []),
                'scene_plan': asdict(segment.semantic_scene_plan) if segment.semantic_scene_plan else None})
        for child in segment.children:
            visit(child)
    visit(plan.root_segment)
    return {'question': plan.question, 'explanation_goal': plan.intent,
        'selected_evidence': answer_graph.get('edges', []), 'evidence_groups': groups,
        'scene_plans': [{'story_scene_id': s.story_scene_id, 'segment_id': s.segment_id,
            **s.metadata.get('semantic_scene_plan', {'scene_pattern': 'FALLBACK',
                'visual_claim': s.metadata.get('visual_claim', s.narration_summary or s.title)}),
            'nodes': list(s.node_ids), 'relations': list(s.relation_ids)}
            for s in story.scenes if not s.metadata.get('prerequisite')],
        'stages': ['KG evidence', 'Explanation grouping', 'Scene planning', 'Visual binding', 'Rendering']}
