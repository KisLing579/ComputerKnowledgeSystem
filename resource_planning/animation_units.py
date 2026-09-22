"""Selectable actions: keep dependent phases together, not whole evidence scenes."""


def animation_units(scene):
    units = []
    for beat in scene.beats:
        # A relation's establish/transform/emphasize phases share state. Scene
        # reveals and focus actions are independently executable.
        key = (beat.template_id, tuple(beat.relation_ids)) if beat.relation_ids else None
        if key is not None and units and units[-1]['key'] == key:
            unit = units[-1]
        else:
            unit = dict(unit_id=f'{scene.story_scene_id}.U{len(units)+1:03d}',
                        key=key, beat_ids=[], node_ids=[], relation_ids=[], narration=[],
                        phases=[], templates=[])
            units.append(unit)
        unit['beat_ids'].append(beat.beat_id)
        unit['phases'].append(beat.phase_id)
        if beat.template_id not in unit['templates']:
            unit['templates'].append(beat.template_id)
        for field in ('node_ids', 'relation_ids'):
            unit[field] = list(dict.fromkeys(unit[field] + list(getattr(beat, field))))
        if beat.narration and beat.narration not in unit['narration']:
            unit['narration'].append(beat.narration)
    for unit in units:
        unit['visual_scope'] = ('relation_action' if unit['relation_ids'] else
                                'definition_text' if 'definition_focus' in unit['templates'] else
                                'node_focus_only')
        unit['introduces_relation_evidence'] = bool(unit['relation_ids'])
    return [{k: v for k, v in unit.items() if k != 'key'} for unit in units]


def clause_visual_context(data, evidence):
    """Describe selected actions AND the layout they actually share.

    Never infer prior-shot persistence or include unselected scene relations.
    """
    scenes = {s['id']: s for s in evidence.get('scenes', [])}
    result = []
    for qi, question in enumerate(data.get('lesson', [])):
        for ci, clause in enumerate(question.get('clauses', [])):
            selected_ids = set(clause.get('animation_unit_ids', []))
            contexts = []
            for sid in clause.get('scene_ids', []):
                scene = scenes.get(sid, {})
                units = [u for u in scene.get('animation_units', []) if u['unit_id'] in selected_ids]
                node_ids = list(dict.fromkeys(n for u in units for n in u['node_ids']))
                relation_ids = list(dict.fromkeys(r for u in units for r in u['relation_ids']))
                plan = scene.get('semantic_scene_plan') or {}
                contexts.append(dict(scene_id=sid, selected_units=units,
                    node_ids=node_ids, relation_ids=relation_ids,
                    layout_family=plan.get('layout_family'),
                    visible_semantic_roles={k: n for k, n in plan.get('semantic_roles', {}).items()
                                            if n in node_ids}))
            result.append(dict(question_index=qi, clause_index=ci, scenes=contexts))
    return result


def validate_unit_selection(scene, ids):
    selected = set(ids)
    for unit in animation_units(scene):
        overlap = selected.intersection(unit['beat_ids'])
        if overlap and overlap != set(unit['beat_ids']):
            raise ValueError('Select a complete animation unit; dependent phases cannot be split')
    if ids != [b.beat_id for b in scene.beats if b.beat_id in selected]:
        raise ValueError('Animation unit phases must retain source order')
